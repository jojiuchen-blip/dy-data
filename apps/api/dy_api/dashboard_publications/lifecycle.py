"""Atomic publication, transaction-held reads and bounded sidecar retention."""

from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
import hashlib
import json
import re
from typing import Any, Iterator
from uuid import uuid4

from sqlalchemy import delete, event, func, select, text, update
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from .schema import heads, runs
from .sources import MODULE_CONTRACT_VERSIONS

REFRESH_INTERVAL = timedelta(minutes=5)
MIN_DELETE_AGE = timedelta(0)
Builder = Callable[[Session, str, datetime], dict[str, Any]]
SessionFactory = Callable[[], Session]


class PublicationError(Exception):
    """Safe API error; exception text never contains the builder exception."""

    def __init__(self, code: str, message: str, http_status: int = 503) -> None:
        self.code = code
        self.http_status = http_status
        self.status_code = http_status
        super().__init__(message)


def utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@dataclass(frozen=True)
class Publication:
    id: str
    module: str
    cutoff: datetime
    data_as_of: datetime | None
    published_at: datetime
    next_refresh_at: datetime | None
    status: str = "available"

    def meta(self) -> dict[str, Any]:
        """Return the value of meta.publication; all dates are explicit UTC."""
        return {
            "id": self.id, "module": self.module,
            "dataAsOf": self.data_as_of.isoformat() if self.data_as_of else None,
            "publishedAt": self.published_at.isoformat(), "status": self.status,
            "nextRefreshAt": self.next_refresh_at.isoformat() if self.next_refresh_at else None,
        }


def _publication(row: Mapping[str, Any]) -> Publication:
    return Publication(
        id=row["id"], module=row["module"], cutoff=utc(row["cutoff"]),
        data_as_of=utc(row["data_as_of"]), published_at=utc(row["published_at"]),
        next_refresh_at=utc(row["next_refresh_at"]),
    )


def resolve_publication(
    session: Session, module: str, publication_id: str | None = None,
) -> Publication:
    """Resolve once, holding a parent SHARE lock until the caller ends its tx.

    This is permission-neutral. Routes must apply current authorization to
    every projection query, including exports and requests specifying an ID.
    """
    statement = select(runs).where(runs.c.module == module, runs.c.status == "success")
    if publication_id is not None:
        statement = statement.where(runs.c.id == publication_id)
    else:
        statement = statement.where(runs.c.id == select(heads.c.publication_id)
                                    .where(heads.c.module == module).scalar_subquery())
    if session.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update(read=True)
    row = session.execute(statement).mappings().first()
    if row is None:
        if publication_id is not None:
            raise PublicationError("PUBLICATION_EXPIRED", "指定分析版本已过期，请刷新后重试", 410)
        raise PublicationError("PUBLICATION_NOT_READY", "首次分析版本尚未发布", 503)
    expected_contract = MODULE_CONTRACT_VERSIONS.get(module)
    actual_contract = (row["stats_json"] or {}).get("contract_version")
    # Financial history retains its original type snapshots and complete
    # all-scope partitions. Those legacy rows remain safely readable. Sales
    # and clues changed classification at build time, so their old rows must
    # not be presented as a publication of the new interpretation.
    legacy_financial = module == "settlement" and actual_contract is None
    if expected_contract and actual_contract != expected_contract and not legacy_financial:
        if publication_id is not None:
            raise PublicationError("PUBLICATION_EXPIRED", "指定分析版本使用旧商品分类，请刷新后重试", 410)
        raise PublicationError("PUBLICATION_NOT_READY", "新版商品分类分析尚未发布", 503)
    publication = _publication(row)
    # A historical successful version remains readable even after a failed
    # replacement. Status describes freshness, never changes its identity.
    is_active = publication_id is None or session.scalar(
        select(heads.c.publication_id).where(heads.c.module == module)
    ) == publication.id
    if is_active:
        latest = session.execute(select(runs.c.status).where(runs.c.module == module)
                                 .order_by(runs.c.created_at.desc(), runs.c.id.desc()).limit(1)).scalar()
        if latest == "building":
            publication = replace(publication, status="refreshing")
        elif latest == "failed":
            publication = replace(publication, status="failed")
        elif publication.next_refresh_at and datetime.now(UTC) >= publication.next_refresh_at:
            publication = replace(publication, status="stale")
    return publication


def _lock_key(module: str) -> int:
    return int.from_bytes(hashlib.sha256(("dashboard-publication:" + module).encode()).digest()[:8],
                          "big", signed=True)


@contextmanager
def _publisher_connection(
    factory: SessionFactory, module: str, shared_lock_keys: tuple[int, ...],
) -> Iterator[Connection | None]:
    """Keep session-level locks on one owned physical connection across txs."""
    with factory() as probe:
        bind = probe.get_bind()
        engine = bind.engine if isinstance(bind, Connection) else bind
    with engine.connect() as connection:
        acquired: list[tuple[int, bool]] = []
        try:
            if connection.dialect.name == "postgresql":
                key = _lock_key(module)
                if not connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key}):
                    connection.rollback()
                    yield None
                    return
                acquired.append((key, False))
                connection.commit()
            # The module-exclusive lock proves a previous building attempt no
            # longer owns a live builder. Commit its failure BEFORE source
            # locks/readiness: a busy writer must not leave it refreshing forever.
            connection.execute(update(runs).where(runs.c.module == module, runs.c.status == "building")
                               .values(status="failed", error_code="PUBLICATION_INTERRUPTED"))
            connection.commit()
            if connection.dialect.name == "postgresql":
                for key in sorted(set(shared_lock_keys)):
                    if not connection.scalar(text("SELECT pg_try_advisory_lock_shared(:key)"), {"key": key}):
                        connection.rollback()
                        yield None
                        return
                    acquired.append((key, True))
                connection.commit()
            yield connection
        finally:
            connection.rollback()
            for key, shared in reversed(acquired):
                function = "pg_advisory_unlock_shared" if shared else "pg_advisory_unlock"
                connection.execute(text(f"SELECT {function}(:key)"), {"key": key})
            if acquired:
                connection.commit()


def _safe_stats(value: dict[str, Any]) -> dict[str, Any]:
    # Builder output is a small statistics contract, never a dump of source
    # payloads/errors. Reject oversized results before publication.
    clean = {key: item for key, item in value.items() if key != "data_as_of"}
    encoded = json.dumps(clean, ensure_ascii=False, allow_nan=False)
    if len(encoded.encode()) > 65536:
        raise ValueError("publication statistics exceed 64 KiB")
    return clean


def _lock_snapshot_sources(session: Session, tables: tuple[str, ...]) -> None:
    """Lock declared relations before the first repeatable-read snapshot.

    Ordinary DML remains concurrent; TRUNCATE and schema replacement cannot
    make an as-yet unread relation disappear from this MVCC snapshot.
    """
    names = sorted(set(tables))
    if not names or len(names) > 128 or any(
        not isinstance(name, str) or re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", name) is None for name in names
    ):
        raise ValueError("invalid publication snapshot relations")
    quote = session.get_bind().dialect.identifier_preparer.quote
    session.execute(text("LOCK TABLE " + ", ".join(quote(name) for name in names)
                         + " IN ACCESS SHARE MODE NOWAIT"))


def publish_module(
    session_factory: SessionFactory, module: str, builder: Builder, *,
    now: datetime | None = None, data_as_of: datetime | None = None,
    fingerprint: Callable[[Session], str] | None = None,
    readiness_check: Callable[[Session], None] | None = None,
    shared_lock_keys: tuple[int, ...] = (), force: bool = False,
    statement_timeout_ms: int = 120000, refresh_on_interval: bool = False,
    snapshot_tables: tuple[str, ...] = (),
) -> Publication | None:
    """Build in REPEATABLE READ; commit facts, success and head atomically.

    Returns None on lock contention or a still-fresh identical input. Production
    workers must supply source readiness/fingerprint and shared writer locks.
    A separate committed attempt exposes updating/failure without exposing
    partially written analytical rows. Builder commit/rollback is forbidden.
    Audited PostgreSQL callers may declare every source relation to publish a
    complete consistent snapshot as stale when later transactions advance it.
    Other callers retain the strict observer equality requirement.
    """
    if not module or len(module) > 64 or not 1 <= statement_timeout_ms <= 900000:
        raise ValueError("invalid publication module or timeout")
    cutoff = utc(now or datetime.now(UTC))
    publication_id = uuid4().hex
    with _publisher_connection(session_factory, module, shared_lock_keys) as connection:
        if connection is None:
            return None
        snapshot_mode = bool(snapshot_tables) and connection.dialect.name == "postgresql"
        if snapshot_mode and (fingerprint is None or readiness_check is None):
            raise ValueError("snapshot publication requires readiness and fingerprint checks")
        with Session(bind=connection, autoflush=False) as session:
            if readiness_check:
                readiness_check(session)
            token = fingerprint(session) if fingerprint else None
            current = session.execute(select(runs).join(heads, heads.c.publication_id == runs.c.id)
                                      .where(heads.c.module == module)).mappings().first()
            expected_head_id = current["id"] if current else None
            latest_status = session.scalar(select(runs.c.status).where(runs.c.module == module)
                                           .order_by(runs.c.created_at.desc(), runs.c.id.desc()).limit(1))
            if (not force and current and fingerprint and current["source_fingerprint"] == token
                    and (module not in MODULE_CONTRACT_VERSIONS or
                         (current["stats_json"] or {}).get("contract_version") == MODULE_CONTRACT_VERSIONS[module])
                    and latest_status == "success"):
                due = utc(current["next_refresh_at"]) is None or cutoff >= utc(current["next_refresh_at"])
                if not refresh_on_interval or not due:
                    if due:
                        # A successful unchanged-source check advances only the
                        # next check. Coverage and publication times stay true.
                        session.execute(update(runs).where(runs.c.id == current["id"])
                                        .values(next_refresh_at=cutoff + REFRESH_INTERVAL))
                        session.commit()
                    return None
            session.execute(runs.insert().values(
                id=publication_id, module=module, status="building", cutoff=cutoff,
                created_at=cutoff, stats_json={}, source_fingerprint=token,
            ))
            session.commit()
        if connection.dialect.name == "postgresql":
            connection.execution_options(isolation_level="REPEATABLE READ")
        try:
            with Session(bind=connection, autoflush=False) as session:
                if connection.dialect.name == "postgresql":
                    # SET does not establish a data snapshot. All source locks
                    # must precede readiness/fingerprint's first SELECT.
                    session.execute(text(f"SET LOCAL statement_timeout = {statement_timeout_ms}"))
                    session.execute(text("SET LOCAL work_mem = '16MB'"))
                    if snapshot_mode:
                        _lock_snapshot_sources(session, snapshot_tables)
                if readiness_check:
                    readiness_check(session)
                initial_token = fingerprint(session) if fingerprint else None
                session.connection()  # Establish a root tx even for an empty/injected builder.
                build_transaction = session.get_transaction()
                connection_transaction = connection.get_transaction()
                session.info["publication_builder"] = True
                transaction_violation = False

                def prevent_commit(current_session: Session) -> None:
                    nonlocal transaction_violation
                    if current_session.info.get("publication_builder") and not current_session.in_nested_transaction():
                        transaction_violation = True
                        raise RuntimeError("publication builders must not commit")

                def prevent_connection_end(current_connection: Connection) -> None:
                    nonlocal transaction_violation
                    if session.info.get("publication_builder"):
                        transaction_violation = True
                        raise RuntimeError("publication builders must not end their connection transaction")

                event.listen(session, "before_commit", prevent_commit)
                if snapshot_mode:
                    event.listen(connection, "commit", prevent_connection_end)
                    event.listen(connection, "rollback", prevent_connection_end)
                try:
                    statistics = builder(session, publication_id, cutoff)
                    if (transaction_violation or session.get_transaction() is not build_transaction
                            or connection.get_transaction() is not connection_transaction
                            or connection_transaction is None or not connection_transaction.is_active):
                        raise RuntimeError("publication builders must not end their transaction")
                    session.flush()
                    if snapshot_mode:
                        if connection.get_isolation_level() != "REPEATABLE READ":
                            raise RuntimeError("publication snapshot isolation changed")
                        if fingerprint(session) != initial_token:
                            raise PublicationError("PUBLICATION_SOURCE_CHANGED", "构建修改了来源，保留上一完整版本", 503)
                finally:
                    session.info["publication_builder"] = False
                    if snapshot_mode:
                        event.remove(connection, "commit", prevent_connection_end)
                        event.remove(connection, "rollback", prevent_connection_end)
                # The independent observer still rejects incomplete writers or
                # missing tracking. A later complete commit advances freshness,
                # while the protected RR snapshot remains internally coherent.
                source_advanced = False
                with session_factory() as observer:
                    if snapshot_mode and (observer.connection().connection.dbapi_connection
                                          is connection.connection.dbapi_connection):
                        raise RuntimeError("publication observer must use an independent connection")
                    if readiness_check:
                        readiness_check(observer)
                    if fingerprint and fingerprint(observer) != initial_token:
                        if not snapshot_mode:
                            raise PublicationError("PUBLICATION_SOURCE_CHANGED", "来源正在更新，保留上一完整版本", 503)
                        source_advanced = True
                observed = utc(statistics.get("data_as_of", data_as_of))
                if observed is not None and observed > cutoff:
                    raise ValueError("source coverage must not exceed the observation cutoff")
                published_at = datetime.now(UTC)
                if module in MODULE_CONTRACT_VERSIONS:
                    statistics = {**statistics, "contract_version": MODULE_CONTRACT_VERSIONS[module]}
                if snapshot_mode:
                    statistics = {**statistics, "source_advanced_during_build": source_advanced}
                next_refresh_at = published_at if source_advanced else published_at + REFRESH_INTERVAL
                session.execute(update(runs).where(runs.c.id == publication_id).values(
                    status="success", published_at=published_at, data_as_of=observed,
                    next_refresh_at=next_refresh_at,
                    source_fingerprint=initial_token, stats_json=_safe_stats(statistics),
                ))
                if expected_head_id is not None:
                    switched = session.execute(update(heads).where(
                        heads.c.module == module, heads.c.publication_id == expected_head_id,
                    ).values(publication_id=publication_id))
                    if switched.rowcount != 1:
                        raise PublicationError("PUBLICATION_HEAD_CHANGED", "分析版本已变化，暂缓更新", 503)
                else:
                    session.execute(heads.insert().values(module=module, publication_id=publication_id))
                session.info["publication_builder"] = False
                session.commit()
                return Publication(publication_id, module, cutoff, observed, published_at, next_refresh_at,
                                   "stale" if source_advanced else "available")
        except Exception as error:
            connection.rollback()
            if snapshot_mode:
                # A rejected Connection.commit()/rollback() deactivates its
                # SQLAlchemy RootTransaction even though our event prevented
                # the DBAPI operation. Roll back that physical transaction
                # before reusing the connection for the failure receipt.
                connection.connection.rollback()
            code = error.code if isinstance(error, PublicationError) else "PUBLICATION_BUILD_FAILED"
            with Session(bind=connection) as failure_session:
                failure_session.execute(update(runs).where(runs.c.id == publication_id)
                                        .values(status="failed", error_code=code))
                failure_session.commit()
            raise PublicationError(code, "分析版本更新未完成，继续显示上一完整版本", 503) from None


def pin_publication(session: Session, publication_id: str, *, reason: str, actor: str) -> None:
    if not reason.strip() or not actor.strip():
        raise ValueError("pin requires a reason and actor")
    statement = select(runs.c.id).where(runs.c.id == publication_id, runs.c.status == "success")
    if session.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    if session.scalar(statement) is None:
        raise PublicationError("PUBLICATION_EXPIRED", "指定分析版本已过期", 410)
    session.execute(update(runs).where(runs.c.id == publication_id)
                    .values(pinned_at=datetime.now(UTC), pin_reason=reason, pinned_by=actor))


def unpin_publication(session: Session, publication_id: str) -> None:
    session.execute(update(runs).where(runs.c.id == publication_id)
                    .values(pinned_at=None, pin_reason=None, pinned_by=None))


def cleanup_publications(
    session: Session, module: str | None = None, *, now: datetime | None = None,
    min_age: timedelta = MIN_DELETE_AGE, keep: int = 2, limit: int = 10,
) -> dict[str, Any]:
    """Delete complete sidecar versions only; protect heads, pins and readers.

    Domain projection FKs cascade; no settlement lineage or business tables
    are traversed. There is no default grace period: PostgreSQL reader locks
    protect active requests, and expired browser IDs receive HTTP 410.
    Preserve each module's latest attempt so its failure/refresh status remains
    visible even when that attempt owns no analytical facts.
    """
    if keep < 2 or not 0 <= limit <= 100 or min_age < MIN_DELETE_AGE:
        raise ValueError("retention requires two versions, nonnegative age, limit <=100")
    cutoff = utc(now or datetime.now(UTC)) - min_age
    newer = runs.alias("newer")
    newer_count = select(func.count()).select_from(newer).where(
        newer.c.module == runs.c.module, newer.c.status == "success", newer.c.pinned_at.is_(None),
        (newer.c.published_at > runs.c.published_at)
        | ((newer.c.published_at == runs.c.published_at) & (newer.c.id > runs.c.id)),
    ).correlate(runs).scalar_subquery()
    newer_attempt = runs.alias("newer_attempt")
    has_newer_attempt = select(newer_attempt.c.id).where(
        newer_attempt.c.module == runs.c.module,
        (newer_attempt.c.created_at > runs.c.created_at)
        | ((newer_attempt.c.created_at == runs.c.created_at) & (newer_attempt.c.id > runs.c.id)),
    ).correlate(runs).exists()
    statement = select(runs.c.id).where(
        runs.c.pinned_at.is_(None), runs.c.created_at < cutoff,
        ~select(heads.c.module).where(heads.c.publication_id == runs.c.id).exists(),
        has_newer_attempt,
        ((runs.c.status == "success") & (newer_count >= keep)) | (runs.c.status == "failed"),
    )
    if module:
        statement = statement.where(runs.c.module == module)
    statement = statement.order_by(runs.c.created_at, runs.c.id).limit(limit)
    if session.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update(skip_locked=True)
    identifiers = list(session.scalars(statement))
    deleted_ids = []
    for identifier in identifiers:
        result = session.execute(delete(runs).where(runs.c.id == identifier, runs.c.pinned_at.is_(None),
                         has_newer_attempt,
                         ~select(heads.c.module).where(heads.c.publication_id == runs.c.id).exists()))
        if result.rowcount:
            deleted_ids.append(identifier)
    return {"deleted": len(deleted_ids), "publication_ids": deleted_ids}
