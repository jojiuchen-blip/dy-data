"""Refresh, export and retention policy for ranking snapshots.

Ranking facts are immutable once published.  This module owns the mutable
policy around those facts: source change detection, static snapshot lookup,
read protection and bounded retention.  It intentionally does not alter the
V1 ranking fact tables or the metric formulas.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import logging
import re
from typing import Any, Iterable

from sqlalchemy import delete, func, inspect, select, text, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from apps.api.dy_api.models import Base
from apps.api.dy_api.ranking_configuration import RANKING_WRITE_LOCK
from apps.api.dy_api.ranking_lifecycle_schema import (
    SOURCE_TABLES,
    metadata,
    snapshot_lifecycle,
    source_change_counters,
)
from apps.api.dy_api.ranking_schema_v1 import runs, samples, snapshots


# Retention, configuration publication and snapshot publication share one
# transaction advisory lock. A separate retention lock would allow a cleanup
# to race a newly published configuration or snapshot.
SNAPSHOT_RETENTION_LOCK = RANKING_WRITE_LOCK
SNAPSHOT_MIN_DELETE_AGE = timedelta(hours=1)
SNAPSHOT_IDLE_RANGE_AGE = timedelta(days=30)
DEFAULT_RETENTION_LIMIT = 50
logger = logging.getLogger(__name__)


def utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _now(value: datetime | None = None) -> datetime:
    return utc(value or datetime.now(timezone.utc)) or datetime.now(timezone.utc)


def _table_exists(session: Session, table_name: str) -> bool:
    try:
        if session.bind.dialect.name == "sqlite":
            return bool(
                session.scalar(
                    text(
                        "SELECT 1 FROM sqlite_master "
                        "WHERE type IN ('table', 'view') AND name = :name LIMIT 1"
                    ),
                    {"name": table_name},
                )
            )
        return bool(inspect(session.connection()).has_table(table_name))
    except (AttributeError, SQLAlchemyError):
        return False


def _existing_source_tables(session: Session) -> tuple[str, ...]:
    cached = session.info.get("ranking_lifecycle_source_tables")
    if cached is not None:
        return tuple(cached)
    if session.bind.dialect.name == "sqlite":
        existing = set(
            session.scalars(
                text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type IN ('table', 'view')"
                )
            )
        )
    else:
        existing = set(inspect(session.connection()).get_table_names())
    names = tuple(name for name in SOURCE_TABLES if name in existing)
    session.info["ranking_lifecycle_source_tables"] = names
    return names


def _trigger_name(table_name: str, event: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", table_name)
    return f"trg_ranking_source_change_{safe}_{event}"


def _postgres_trigger_name(table_name: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", table_name)
    return f"trg_ranking_source_change_{safe}_statement"


def _install_sqlite_tracking(session: Session, table_names: Iterable[str]) -> None:
    """Install real INSERT/UPDATE/DELETE counters for lightweight SQLite use.

    Production PostgreSQL installs equivalent statement-level triggers in
    migration 0062.  SQLite cannot create a statement trigger, so one row
    trigger per operation is the exact fallback used by tests and local tools.
    """

    if session.bind.dialect.name != "sqlite":
        return
    for table_name in table_names:
        quoted = '"' + table_name.replace('"', '""') + '"'
        for event in ("insert", "update", "delete"):
            trigger = _trigger_name(table_name, event)
            operation = event.upper()
            source_literal = "'" + table_name.replace("'", "''") + "'"
            session.execute(
                text(
                    f"CREATE TRIGGER IF NOT EXISTS \"{trigger}\" "
                    f"AFTER {operation} ON {quoted} BEGIN "
                    "UPDATE ranking_source_change_counters "
                    "SET generation = generation + 1, changed_at = CURRENT_TIMESTAMP "
                    f"WHERE source_name = {source_literal}; END"
                )
            )


def _postgres_tracking_ready(session: Session, table_names: Iterable[str]) -> bool:
    if session.bind.dialect.name != "postgresql":
        return False
    names = tuple(table_names)
    if not names:
        return False
    try:
        for table_name in names:
            row = session.execute(
                text(
                    "SELECT t.tgenabled, t.tgtype "
                    "FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = current_schema() "
                    "AND c.relname = :table_name "
                    "AND t.tgname = :trigger_name AND NOT t.tgisinternal"
                ),
                {"table_name": table_name, "trigger_name": _postgres_trigger_name(table_name)},
            ).mappings().first()
            if not row or row["tgenabled"] != "O":
                return False
            # tgtype bit 1 is ROW; event bits 4|8|16|32 are INSERT, DELETE,
            # UPDATE and TRUNCATE. We require an AFTER statement-level all-events
            # triggers, rather than an approximate trigger count.
            tgtype = int(row["tgtype"])
            if (tgtype & 1) or ((tgtype & 60) != 60):
                return False
        return True
    except SQLAlchemyError:
        return False


def ensure_lifecycle_schema(session: Session) -> None:
    """Make local/test sessions usable before their Alembic upgrade.

    The deploy path creates these objects in migration 0062.  ``checkfirst``
    keeps this helper harmless in production and allows existing unit tests
    that create only the V1 metadata to exercise the new policy.
    """

    if session.bind.dialect.name == "sqlite":
        # Bind DDL to the Session's current connection. Using the Engine here
        # can create lifecycle tables on a second in-memory SQLite connection.
        # Probe that same connection first; an Engine-level inspector can see
        # a different in-memory connection when a test client crosses threads.
        connection = session.connection()
        missing_lifecycle_table = False
        for table_name in (snapshot_lifecycle.name, source_change_counters.name):
            try:
                connection.exec_driver_sql(f'SELECT 1 FROM "{table_name}" LIMIT 0')
            except SQLAlchemyError:
                missing_lifecycle_table = True
                break
        if missing_lifecycle_table:
            metadata.create_all(connection, checkfirst=True)
    elif not (
        _table_exists(session, snapshot_lifecycle.name)
        and _table_exists(session, source_change_counters.name)
    ):
        raise RuntimeError("ranking lifecycle migration 20261009_0062 is required before serving rankings")
    table_names = _existing_source_tables(session)
    if table_names:
        existing = set(
            session.scalars(
                select(source_change_counters.c.source_name).where(
                    source_change_counters.c.source_name.in_(table_names)
                )
            )
        )
        now = _now()
        missing = [
            {"source_name": name, "generation": 0, "changed_at": now}
            for name in table_names
            if name not in existing
        ]
        if missing:
            if session.bind.dialect.name == "postgresql":
                raise RuntimeError(
                    "ranking lifecycle source counters are incomplete; apply migration 20261009_0062"
                )
            session.execute(source_change_counters.insert(), missing)
        # DDL and trigger creation can be rolled back with a test transaction.
        # Cache only for the current root transaction so a later retry never
        # trusts a marker left behind by a rolled-back setup.
        root_transaction = session.get_transaction()
        if session.info.get("ranking_lifecycle_sqlite_transaction") is not root_transaction:
            _install_sqlite_tracking(session, table_names)
            if session.bind.dialect.name == "sqlite":
                session.info["ranking_lifecycle_sqlite_transaction"] = root_transaction
                session.info.pop("ranking_lifecycle_tracking_ready", None)
    # DDL/trigger setup is deliberately committed by the caller's normal
    # transaction.  A savepoint caller can still roll it back safely.
    session.info["ranking_lifecycle_schema_ready"] = True


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return utc(value).isoformat() if value.tzinfo else value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_value(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, bytes):
        return value.hex()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _exact_source_fingerprint(session: Session, table_names: Iterable[str]) -> str:
    digest = sha256()
    all_tables = dict(Base.metadata.tables)
    try:
        from apps.api.dy_api import ranking_schema_v1

        all_tables.update(ranking_schema_v1.metadata.tables)
    except ImportError:
        pass
    for table_name in table_names:
        table = all_tables.get(table_name)
        if table is None or not _table_exists(session, table_name):
            continue
        statement = select(table)
        for column in table.primary_key.columns:
            statement = statement.order_by(column)
        digest.update(table_name.encode("utf-8"))
        digest.update(b"\0")
        try:
            rows = session.execute(statement).mappings()
            for row in rows:
                payload = json.dumps(
                    _json_value(dict(row)),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
                digest.update(payload)
                digest.update(b"\n")
        except SQLAlchemyError:
            # A partial local schema should never be treated as stable source
            # data.  Include the table name and an explicit error marker so a
            # later complete schema produces a different fingerprint.
            digest.update(b"<unreadable>\n")
    return digest.hexdigest()


def source_fingerprint(session: Session) -> str:
    """Return a write-complete source token.

    Migrated PostgreSQL/SQLite databases use INSERT/UPDATE/DELETE counters,
    which detect changes even when a timestamp is unchanged or a row is
    deleted.  A direct, unmigrated test database uses an exact row-content
    digest instead; it is slower but remains correct and is never a max-time
    heuristic.
    """

    ensure_lifecycle_schema(session)
    table_names = _existing_source_tables(session)
    if not table_names:
        return sha256(b"no-ranking-source-tables").hexdigest()
    ready = session.info.get("ranking_lifecycle_tracking_ready")
    if ready is None:
        ready = session.bind.dialect.name == "sqlite" or _postgres_tracking_ready(session, table_names)
        # SQLite triggers are installed by ensure_lifecycle_schema.  For any
        # other dialect, only a migration-provided trigger set may use tokens.
        if session.bind.dialect.name == "sqlite":
            ready = True
        session.info["ranking_lifecycle_tracking_ready"] = ready
    if session.bind.dialect.name == "postgresql" and not ready:
        raise RuntimeError("ranking lifecycle source triggers are incomplete; apply migration 20261009_0062")
    if ready:
        rows = session.execute(
            select(source_change_counters.c.source_name, source_change_counters.c.generation)
            .where(source_change_counters.c.source_name.in_(table_names))
            .order_by(source_change_counters.c.source_name)
        ).all()
        if len(rows) == len(table_names):
            payload = [(name, int(generation)) for name, generation in rows]
            return sha256(json.dumps(payload, separators=(",", ":")).encode("utf-8")).hexdigest()
    if session.bind.dialect.name == "postgresql":
        raise RuntimeError("ranking lifecycle source triggers are incomplete; apply migration 20261009_0062")
    return _exact_source_fingerprint(session, table_names)


def _lifecycle_row(session: Session, run_id: str) -> dict[str, Any] | None:
    row = session.execute(
        select(snapshot_lifecycle).where(snapshot_lifecycle.c.run_id == run_id)
    ).mappings().first()
    return dict(row) if row else None


def backfill_lifecycle_metadata(
    session: Session,
    *,
    limit: int = 10000,
    run_id: str | None = None,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
    metric_version: str | None = None,
    data_mode: str | None = None,
) -> int:
    """Register old successful runs without pretending their source is fresh."""

    ensure_lifecycle_schema(session)
    conditions = [
        runs.c.status == "success",
        snapshot_lifecycle.c.run_id.is_(None),
    ]
    if run_id is not None:
        conditions.append(runs.c.run_id == run_id)
    if period_start is not None:
        conditions.append(runs.c.period_start == utc(period_start))
    if period_end is not None:
        conditions.append(runs.c.period_end == utc(period_end))
    if metric_version is not None:
        conditions.append(runs.c.metric_version == metric_version)
    if data_mode is not None:
        conditions.append(runs.c.data_mode == data_mode)
    query = (
        select(runs, snapshot_lifecycle.c.run_id.label("lifecycle_run_id"))
        .select_from(
            runs.outerjoin(snapshot_lifecycle, runs.c.run_id == snapshot_lifecycle.c.run_id)
        )
        .where(*conditions)
        .order_by(runs.c.created_at.asc(), runs.c.run_id.asc())
        .limit(limit)
    )
    if session.bind.dialect.name == "postgresql":
        query = query.with_for_update(read=True, key_share=True, of=runs)
    rows = session.execute(query).mappings().all()
    if not rows:
        return 0
    now = _now()
    payload = []
    for row in rows:
        created_at = utc(row["created_at"]) or now
        payload.append(
            {
                "run_id": row["run_id"],
                "period_start": row["period_start"],
                "period_end": row["period_end"],
                "metric_version": row["metric_version"],
                "data_mode": row["data_mode"],
                "source_fingerprint": None,
                "created_at": created_at,
                "last_accessed_at": created_at,
                "next_refresh_at": None,
                "pinned_at": None,
                "pin_reason": None,
                "pinned_by": None,
                "metadata_json": {"backfilled": True},
            }
        )
    # Another reader/export may create the same sidecar after our SELECT.
    # Never overwrite its access, pin or source fingerprint on that race.
    if session.bind.dialect.name == "postgresql":
        statement = postgres_insert(snapshot_lifecycle).on_conflict_do_nothing(
            index_elements=[snapshot_lifecycle.c.run_id],
        )
    elif session.bind.dialect.name == "sqlite":
        statement = sqlite_insert(snapshot_lifecycle).on_conflict_do_nothing(
            index_elements=[snapshot_lifecycle.c.run_id],
        )
    else:
        statement = snapshot_lifecycle.insert()
    if session.bind.dialect.name in {"postgresql", "sqlite"}:
        # psycopg executemany may report rowcount=-1 even after an insert.
        # RETURNING counts only rows actually inserted by this transaction.
        return len(session.execute(
            statement.returning(snapshot_lifecycle.c.run_id), payload,
        ).scalars().all())
    result = session.execute(statement, payload)
    return max(result.rowcount, 0)


def register_snapshot(
    session: Session,
    *,
    run_id: str,
    source_token: str,
    next_refresh_at: datetime | None = None,
    metadata_json: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> None:
    """Persist the lifecycle record only after a complete snapshot exists."""

    ensure_lifecycle_schema(session)
    run = session.execute(select(runs).where(runs.c.run_id == run_id)).mappings().first()
    if not run:
        raise ValueError("cannot register unknown ranking snapshot")
    observed = _now(now)
    created_at = utc(run["created_at"]) or observed
    values = {
        "run_id": run_id,
        "period_start": run["period_start"],
        "period_end": run["period_end"],
        "metric_version": run["metric_version"],
        "data_mode": run["data_mode"],
        "source_fingerprint": source_token,
        "created_at": created_at,
        "last_accessed_at": observed,
        "next_refresh_at": utc(next_refresh_at),
        "metadata_json": metadata_json or {},
    }
    existing = _lifecycle_row(session, run_id)
    if existing:
        session.execute(
            snapshot_lifecycle.update()
            .where(snapshot_lifecycle.c.run_id == run_id)
            .values(
                source_fingerprint=source_token,
                next_refresh_at=utc(next_refresh_at),
                last_accessed_at=observed,
                metadata_json=metadata_json or existing.get("metadata_json") or {},
            )
        )
    else:
        session.execute(snapshot_lifecycle.insert().values(**values))


def _future_deadline(session: Session, run_id: str) -> datetime | None:
    rows = session.execute(
        select(samples.c.evidence_json).where(
            samples.c.run_id == run_id,
            samples.c.metric_key == "follow_24h",
        )
    ).scalars()
    deadlines: list[datetime] = []
    for evidence in rows:
        if not isinstance(evidence, dict) or evidence.get("reason_code") != "active_under_observation":
            continue
        raw = evidence.get("deadline")
        if not raw:
            continue
        try:
            parsed = datetime.fromisoformat(raw)
        except (TypeError, ValueError):
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        deadlines.append(parsed.astimezone(timezone.utc))
    return min(deadlines) if deadlines else None


def _model_tables() -> dict[str, Any]:
    """Return the model tables without asking the database to inspect them."""

    tables = dict(Base.metadata.tables)
    try:
        from apps.api.dy_api import ranking_schema_v1

        tables.update(ranking_schema_v1.metadata.tables)
    except ImportError:
        pass
    return tables


def _future_column_min(
    session: Session,
    *,
    table_name: str,
    id_column: str,
    ids: set[str],
    timestamp_columns: tuple[str, ...],
    cutoff: datetime,
    bounds: tuple[Any, ...] = (),
) -> list[datetime]:
    """Find future event times for evidence IDs using bounded indexed probes."""

    if not ids:
        return []
    table = _model_tables().get(table_name)
    if table is None or id_column not in table.c:
        return []
    id_field = table.c[id_column]
    values = tuple(ids)
    result: list[datetime] = []
    # Keep IN lists below common PostgreSQL parameter limits for large runs.
    for offset in range(0, len(values), 1000):
        chunk = values[offset : offset + 1000]
        for column_name in timestamp_columns:
            if column_name not in table.c:
                continue
            column = table.c[column_name]
            predicates = [id_field.in_(chunk), column > cutoff, *bounds]
            value = session.scalar(select(func.min(column)).where(*predicates))
            if value is not None:
                parsed = utc(value)
                if parsed is not None:
                    result.append(parsed)
    return result


def _future_global_min(
    session: Session,
    *,
    table_name: str,
    timestamp_columns: tuple[str, ...],
    cutoff: datetime,
    bounds: tuple[Any, ...] = (),
    period_start: datetime | None = None,
    period_end: datetime | None = None,
) -> list[datetime]:
    """Find a conservative clock boundary for rows in the selected period."""

    table = _model_tables().get(table_name)
    if table is None:
        return []
    result: list[datetime] = []
    for column_name in timestamp_columns:
        if column_name not in table.c:
            continue
        column = table.c[column_name]
        predicates = [column > cutoff, *bounds]
        if period_start is not None:
            predicates.append(column >= period_start)
        if period_end is not None:
            predicates.append(column < period_end)
        value = session.scalar(
            select(func.min(column)).where(*predicates)
        )
        if value is not None:
            parsed = utc(value)
            if parsed is not None:
                result.append(parsed)
    return result


def _future_terminal_payload_min(
    session: Session,
    order_ids: set[str],
    *,
    cutoff: datetime,
) -> list[datetime]:
    """Extract future terminal times with the ranking evidence parser.

    Terminal timestamps can live inside raw payload JSON (for example
    ``closed_at`` or ``completed_at``), so a column-only probe would miss a
    maturity boundary.  Keep this call bounded to order IDs represented by
    the run and reuse the same parser that calculates terminal evidence.
    """

    if not order_ids:
        return []
    from apps.api.dy_api.clue_followup_metrics import load_terminal_evidence

    evidence_by_order = load_terminal_evidence(
        session,
        order_ids,
        observed_through=cutoff,
        include_raw_clues=True,
    )
    boundaries: list[datetime] = []
    for evidence in evidence_by_order.values():
        terminal_at = utc(evidence.terminal_at)
        if terminal_at is not None and terminal_at > cutoff:
            boundaries.append(terminal_at)
    return boundaries


def _next_refresh_at(
    session: Session,
    run_id: str,
    *,
    period_start: datetime,
    period_end: datetime,
    cutoff: datetime,
) -> datetime | None:
    """Return the earliest known clock boundary that can change this run.

    Source counters cover writes. This companion boundary covers timestamps
    already present in the database whose meaning changes when ``observed_through``
    crosses them: sales, assignments, follows, verification and terminal/refund
    events. Evidence IDs bound most probes; sales and assignments also probe
    the selected period for future rows not yet present in this run.
    """

    order_ids: set[str] = set()
    round_ids: set[str] = set()
    rows = session.execute(
        select(samples.c.metric_key, samples.c.sample_key, samples.c.evidence_json).where(
            samples.c.run_id == run_id
        )
    ).all()
    for metric_key, sample_key, evidence in rows:
        if isinstance(evidence, dict):
            order_id = evidence.get("order_id")
            round_id = evidence.get("round_id")
            if order_id:
                order_ids.add(str(order_id))
            if round_id:
                round_ids.add(str(round_id))
        if metric_key == "follow_24h" and sample_key:
            round_ids.add(str(sample_key))

    start, end = utc(period_start), utc(period_end)
    boundaries: list[datetime] = []
    if start is not None and end is not None:
        # Rows already present but outside the current observed cutoff do not
        # appear in ``samples`` yet. Probe the selected period directly so a
        # sale/pay or formal assignment crossing the cutoff cannot remain
        # cached forever simply because it was not included in the first run.
        boundaries.extend(
            _future_global_min(
                session,
                table_name="raw_douyin_orders",
                timestamp_columns=("sale_time", "pay_time"),
                cutoff=cutoff,
                period_start=start,
                period_end=end,
            )
        )
        boundaries.extend(
            _future_global_min(
                session,
                table_name="clue_assignment_rounds",
                timestamp_columns=("assigned_at",),
                cutoff=cutoff,
                period_start=start,
                period_end=end,
            )
        )
        boundaries.extend(
            _future_column_min(
                session,
                table_name="raw_douyin_orders",
                id_column="order_id",
                ids=order_ids,
                timestamp_columns=("sale_time", "pay_time", "source_observed_at", "updated_at"),
                cutoff=cutoff,
            )
        )
    boundaries.extend(
        _future_column_min(
            session,
            table_name="clue_assignment_rounds",
            id_column="assignment_round_id",
            ids=round_ids,
            timestamp_columns=("assigned_at", "verified_at", "updated_at"),
            cutoff=cutoff,
        )
    )
    boundaries.extend(
        _future_column_min(
            session,
            table_name="clue_follow_up_records",
            id_column="assignment_round_id",
            ids=round_ids,
            timestamp_columns=("created_at", "deleted_at"),
            cutoff=cutoff,
        )
    )
    boundaries.extend(
        _future_column_min(
            session,
            table_name="raw_douyin_order_coupons",
            id_column="order_id",
            ids=order_ids,
            timestamp_columns=(
                "coupon_updated_at",
                "coupon_refund_time",
                "latest_refund_at",
                "source_observed_at",
            ),
            cutoff=cutoff,
        )
    )
    coupon_ids: set[str] = set()
    coupon_table = _model_tables().get("raw_douyin_order_coupons")
    if coupon_table is not None and order_ids:
        coupon_rows = session.execute(
            select(coupon_table.c.coupon_id).where(coupon_table.c.order_id.in_(tuple(order_ids)))
        ).scalars()
        coupon_ids.update(str(value) for value in coupon_rows if value)
    boundaries.extend(
        _future_column_min(
            session,
            table_name="raw_douyin_verify_records",
            id_column="coupon_id",
            ids=coupon_ids,
            timestamp_columns=("verify_time", "cancel_time", "source_observed_at"),
            cutoff=cutoff,
        )
    )
    for table_name, columns in (
        ("settlement_order_details", ("sale_time", "verify_time", "updated_at")),
        (
            "raw_douyin_refund_records",
            ("refund_applied_at", "refund_completed_at", "source_observed_at", "gmt_modified"),
        ),
        (
            "douyin_refund_event",
            ("occurred_at", "successful_observed_at", "source_observed_at", "updated_at"),
        ),
        (
            "raw_douyin_clues",
            ("create_time_detail", "modify_time", "source_observed_at", "updated_at"),
        ),
        ("clue_center_orders", ("assigned_at", "verified_at", "expires_at", "updated_at")),
    ):
        boundaries.extend(
            _future_column_min(
                session,
                table_name=table_name,
                id_column="order_id",
                ids=order_ids,
                timestamp_columns=columns,
                cutoff=cutoff,
            )
        )
    boundaries.extend(_future_terminal_payload_min(session, order_ids, cutoff=cutoff))
    deadline = _future_deadline(session, run_id)
    if deadline is not None:
        boundaries.append(deadline)
    return min(boundaries) if boundaries else None


def reusable_business_snapshot(
    session: Session,
    *,
    period_start: datetime,
    period_end: datetime,
    metric_version: str,
    source_token: str,
    now: datetime | None = None,
    data_mode: str = "business",
) -> str | None:
    """Find a reusable snapshot with unchanged inputs.

    The UI may ask every five minutes, but the five-minute request cadence is
    not a write TTL.  An unchanged source is reused across that boundary; a
    known future evidence timestamps and pending 24-hour windows are the
    time-driven expiry boundaries.
    """

    ensure_lifecycle_schema(session)
    start, end = utc(period_start), utc(period_end)
    # A request only backfills the selected key.  The unfiltered form is
    # reserved for the bounded maintenance CLI, so an old database cannot
    # cause every ranking request to scan all historical runs.
    backfill_lifecycle_metadata(
        session,
        period_start=start,
        period_end=end,
        metric_version=metric_version,
        data_mode=data_mode,
        limit=2,
    )
    cutoff = _now(now)
    query = (
        select(runs.c.run_id, snapshot_lifecycle)
        .select_from(runs.join(snapshot_lifecycle, runs.c.run_id == snapshot_lifecycle.c.run_id))
        .where(
            runs.c.period_start == start,
            runs.c.period_end == end,
            runs.c.metric_version == metric_version,
            runs.c.data_mode == data_mode,
            runs.c.status == "success",
            snapshot_lifecycle.c.source_fingerprint == source_token,
        )
        .order_by(runs.c.created_at.desc(), runs.c.run_id.desc())
        .limit(1)
    )
    if session.bind.dialect.name == "postgresql":
        # Hold the parent before touching access metadata. Otherwise an idle
        # cleanup could delete the selected run while the touch waits, and a
        # cache hit would return a run_id that no longer exists.
        query = query.with_for_update(read=True, key_share=True, of=runs)
    row = session.execute(query).mappings().first()
    if not row:
        return None
    refresh_at = utc(row.get("next_refresh_at"))
    if refresh_at is not None and cutoff >= refresh_at:
        return None
    session.execute(
        snapshot_lifecycle.update()
        .where(snapshot_lifecycle.c.run_id == row["run_id"])
        .values(last_accessed_at=cutoff)
    )
    return row["run_id"]


def resolve_static_snapshot(
    session: Session,
    *,
    period_start: datetime,
    period_end: datetime,
    metric_version: str,
    data_mode: str = "business",
    now: datetime | None = None,
    lock_for_read: bool = True,
) -> str:
    """Resolve and hold the newest successful snapshot for a static export."""

    # Static export is intentionally read-only with respect to lifecycle
    # metadata.  In particular, do not bootstrap schema, backfill sidecars or
    # update last_accessed_at here.  The caller must run the lifecycle
    # migration before using this production path; a missing snapshot is a
    # clear error rather than an implicit recomputation.
    start, end = utc(period_start), utc(period_end)
    query = select(runs).where(
        runs.c.period_start == start,
        runs.c.period_end == end,
        runs.c.metric_version == metric_version,
        runs.c.data_mode == data_mode,
        runs.c.status == "success",
    )
    if lock_for_read and session.bind.dialect.name == "postgresql":
        # KEY SHARE conflicts with deletion/UPDATE but coexists with other
        # readers, and is held until the export transaction ends.
        query = query.with_for_update(read=True, key_share=True)
    run = session.execute(
        query.order_by(runs.c.created_at.desc(), runs.c.run_id.desc()).limit(1)
    ).mappings().first()
    if not run:
        raise ValueError("当前日期范围尚未生成榜单快照，请先刷新榜单后再导出")
    return run["run_id"]


def record_snapshot_access(
    session: Session,
    run_id: str,
    *,
    now: datetime | None = None,
) -> None:
    """Record a successful export access for one already resolved run.

    Export resolution and workbook generation remain fact-read operations.  A
    successful download may then update (or create) exactly one sidecar row so
    a frequently downloaded legacy run is not treated as idle.  This function
    never creates ranking facts, computes a fingerprint or backfills another
    run.
    """

    ensure_lifecycle_schema(session)
    run = session.execute(
        select(runs).where(runs.c.run_id == run_id, runs.c.status == "success")
    ).mappings().first()
    if not run:
        raise ValueError("ranking snapshot not found")
    accessed_at = _now(now)
    created_at = utc(run.get("created_at")) or accessed_at
    values = {
        "run_id": run_id,
        "period_start": run["period_start"],
        "period_end": run["period_end"],
        "metric_version": run["metric_version"],
        "data_mode": run["data_mode"],
        "source_fingerprint": None,
        "created_at": created_at,
        "last_accessed_at": accessed_at,
        "next_refresh_at": None,
        "pinned_at": None,
        "pin_reason": None,
        "pinned_by": None,
        "metadata_json": {"backfilled": True, "access_recorded": True},
    }
    # Two exports can resolve the same legacy run before either has created
    # its sidecar. Use a real dialect upsert so the loser only refreshes the
    # access timestamp and never overwrites source or pin metadata.
    if session.bind.dialect.name == "postgresql":
        statement = postgres_insert(snapshot_lifecycle).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[snapshot_lifecycle.c.run_id],
            set_={"last_accessed_at": accessed_at},
        )
    elif session.bind.dialect.name == "sqlite":
        statement = sqlite_insert(snapshot_lifecycle).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[snapshot_lifecycle.c.run_id],
            set_={"last_accessed_at": accessed_at},
        )
    else:
        # The supported production/test backends above are atomic. Keep a
        # portable fallback for local dialects that do not expose upsert.
        updated = session.execute(
            snapshot_lifecycle.update()
            .where(snapshot_lifecycle.c.run_id == run_id)
            .values(last_accessed_at=accessed_at)
        )
        if updated.rowcount:
            return
        statement = snapshot_lifecycle.insert().values(**values)
    session.execute(statement)


def hold_snapshot_read(session: Session, run_id: str) -> dict[str, Any]:
    """Hold the published parent run while a board reads its fact rows."""

    query = select(runs).where(
        runs.c.run_id == run_id,
        runs.c.status == "success",
    )
    if session.bind.dialect.name == "postgresql":
        query = query.with_for_update(read=True, key_share=True)
    row = session.execute(query).mappings().first()
    if not row:
        raise ValueError("ranking snapshot not found")
    return dict(row)


def touch_snapshot(session: Session, run_id: str, *, now: datetime | None = None) -> None:
    ensure_lifecycle_schema(session)
    session.execute(
        snapshot_lifecycle.update()
        .where(snapshot_lifecycle.c.run_id == run_id)
        .values(last_accessed_at=_now(now))
    )


def archive_snapshot(
    session: Session,
    run_id: str,
    *,
    reason: str,
    actor: str | None = None,
    now: datetime | None = None,
) -> None:
    """Pin a snapshot for a named business/audit reason."""

    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("archive reason is required")
    ensure_lifecycle_schema(session)
    _lock_retention_policy(session)
    run = _lock_parent_run(session, run_id)
    if not run or run["status"] != "success":
        raise ValueError("ranking snapshot not found")
    if not _lifecycle_row(session, run_id):
        backfill_lifecycle_metadata(
            session,
            limit=1,
            run_id=run_id,
            period_start=run["period_start"],
            period_end=run["period_end"],
            metric_version=run["metric_version"],
            data_mode=run["data_mode"],
        )
    result = session.execute(
        snapshot_lifecycle.update()
        .where(snapshot_lifecycle.c.run_id == run_id)
        .values(
            pinned_at=_now(now),
            pin_reason=reason.strip(),
            pinned_by=(actor or "").strip() or None,
        )
    )
    if result.rowcount != 1:
        raise ValueError("ranking snapshot not found")


def unarchive_snapshot(session: Session, run_id: str) -> None:
    ensure_lifecycle_schema(session)
    _lock_retention_policy(session)
    run = _lock_parent_run(session, run_id)
    if not run or run["status"] != "success":
        raise ValueError("ranking snapshot not found")
    if not _lifecycle_row(session, run_id):
        backfill_lifecycle_metadata(
            session,
            limit=1,
            run_id=run_id,
            period_start=run["period_start"],
            period_end=run["period_end"],
            metric_version=run["metric_version"],
            data_mode=run["data_mode"],
        )
    session.execute(
        snapshot_lifecycle.update()
        .where(snapshot_lifecycle.c.run_id == run_id)
        .values(pinned_at=None, pin_reason=None, pinned_by=None)
    )


def _try_retention_lock(session: Session) -> bool:
    if session.bind.dialect.name != "postgresql":
        return True
    return bool(
        session.scalar(
            text("SELECT pg_try_advisory_xact_lock(:key)"),
            {"key": RANKING_WRITE_LOCK},
        )
    )


def _lock_retention_policy(session: Session) -> None:
    """Take the blocking policy lock for an explicit pin/archive action."""

    if session.bind.dialect.name == "postgresql":
        session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": RANKING_WRITE_LOCK},
        )


def _lock_parent_run(session: Session, run_id: str) -> dict[str, Any] | None:
    query = select(runs).where(runs.c.run_id == run_id)
    if session.bind.dialect.name == "postgresql":
        query = query.with_for_update()
    row = session.execute(query).mappings().first()
    return dict(row) if row else None


def _delete_run(session: Session, run_id: str) -> None:
    # Fact rows first, parent run last.  Lifecycle is independent and is
    # removed after the V1 parent so a failed batch can be retried safely.
    session.execute(delete(samples).where(samples.c.run_id == run_id))
    session.execute(delete(snapshots).where(snapshots.c.run_id == run_id))
    session.execute(delete(runs).where(runs.c.run_id == run_id))
    session.execute(delete(snapshot_lifecycle).where(snapshot_lifecycle.c.run_id == run_id))


def cleanup_snapshots(
    session: Session,
    *,
    now: datetime | None = None,
    dry_run: bool = True,
    max_runs: int = DEFAULT_RETENTION_LIMIT,
    idle_age: timedelta = SNAPSHOT_IDLE_RANGE_AGE,
    min_age: timedelta = SNAPSHOT_MIN_DELETE_AGE,
) -> dict[str, Any]:
    """Plan or delete bounded obsolete snapshots.

    For every active period/metric/mode key, the newest two successful runs
    survive.  Pinned runs survive indefinitely.  A range not accessed for 30
    days is eligible in full (except pins).  Old rows are selected with
    ``SKIP LOCKED`` on PostgreSQL so an export never blocks a web request.
    """

    ensure_lifecycle_schema(session)
    if max_runs < 0:
        raise ValueError("max_runs must be non-negative")
    if not _try_retention_lock(session):
        return {"dry_run": dry_run, "planned": [], "deleted": 0, "skipped": "retention lock busy"}
    # Backfill and candidate planning are inside the same policy lock as
    # archive/unarchive and snapshot publication, so an old run cannot be
    # inserted twice or pinned halfway through planning.
    backfill_lifecycle_metadata(session)
    cutoff = _now(now)

    rows = session.execute(
        select(runs, snapshot_lifecycle)
        .select_from(runs.join(snapshot_lifecycle, runs.c.run_id == snapshot_lifecycle.c.run_id))
        .where(runs.c.status == "success")
        .order_by(runs.c.created_at.desc(), runs.c.run_id.desc())
    ).mappings().all()
    groups: defaultdict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (
            row["period_start"],
            row["period_end"],
            row["metric_version"],
            row["data_mode"],
        )
        groups[key].append(dict(row))

    candidates: list[dict[str, Any]] = []
    for key, group in groups.items():
        non_pinned = [row for row in group if row.get("pinned_at") is None]
        last_accessed = max(
            (utc(row.get("last_accessed_at")) or utc(row.get("created_at")) or cutoff)
            for row in group
        )
        idle_range = cutoff - last_accessed >= idle_age
        keep_ids = {row["run_id"] for row in non_pinned[:2]} if not idle_range else set()
        for row in group:
            if row.get("pinned_at") is not None or row["run_id"] in keep_ids:
                continue
            created = utc(row.get("created_at")) or cutoff
            if cutoff - created < min_age:
                continue
            candidates.append(
                {
                    "run_id": row["run_id"],
                    "period_start": row["period_start"],
                    "period_end": row["period_end"],
                    "metric_version": row["metric_version"],
                    "data_mode": row["data_mode"],
                    "reason": "idle_range" if idle_range else "older_than_latest_two",
                }
            )

    candidates = candidates[:max_runs]
    if dry_run or not candidates:
        return {"dry_run": dry_run, "planned": candidates, "deleted": 0}

    # Lock parent runs with SKIP LOCKED before deleting dependent facts. A
    # concurrent export holds KEY SHARE on its run and is skipped here.
    ids = [item["run_id"] for item in candidates]
    lock_query = select(runs.c.run_id).where(runs.c.run_id.in_(ids))
    if session.bind.dialect.name == "postgresql":
        lock_query = lock_query.with_for_update(skip_locked=True)
    locked = set(session.scalars(lock_query))
    deleted = 0
    for item in candidates:
        if item["run_id"] not in locked:
            continue
        # Re-read mutable lifecycle state after the parent row is locked. A
        # board refresh may have touched last_accessed_at after candidate
        # planning, and a pin action may have raced on a non-PostgreSQL test
        # backend. Never delete based only on the initial candidate snapshot.
        state_query = select(snapshot_lifecycle).where(
            snapshot_lifecycle.c.run_id == item["run_id"]
        )
        if session.bind.dialect.name == "postgresql":
            state_query = state_query.with_for_update(skip_locked=True)
        state = session.execute(state_query).mappings().first()
        if not state or state.get("pinned_at") is not None:
            continue
        created = utc(state.get("created_at")) or cutoff
        if cutoff - created < min_age:
            continue
        if item["reason"] == "idle_range":
            last_accessed = utc(state.get("last_accessed_at")) or created
            if cutoff - last_accessed < idle_age:
                continue
        _delete_run(session, item["run_id"])
        deleted += 1
    return {"dry_run": False, "planned": candidates, "deleted": deleted}


def run_background_retention(session_factory: Any) -> dict[str, Any]:
    """Run one bounded cleanup in an independent, short-lived session.

    This is intended for FastAPI ``BackgroundTasks`` after a successful
    ranking request. Cleanup failure is isolated from the already-published
    response; the maintenance CLI remains available for a later retry.
    PostgreSQL gets a local statement timeout so a large historical range
    cannot occupy a worker indefinitely.
    """

    session = session_factory()
    try:
        if session.bind.dialect.name == "postgresql":
            session.execute(text("SET LOCAL statement_timeout = '5000ms'"))
        result = cleanup_snapshots(session, dry_run=False, max_runs=1)
        session.commit()
        return result
    except Exception as exc:  # maintenance must not change the request result
        session.rollback()
        logger.warning("ranking snapshot background retention failed", exc_info=True)
        return {"dry_run": False, "planned": [], "deleted": 0, "error": str(exc)}
    finally:
        session.close()


__all__ = [
    "SNAPSHOT_IDLE_RANGE_AGE",
    "SNAPSHOT_MIN_DELETE_AGE",
    "archive_snapshot",
    "backfill_lifecycle_metadata",
    "cleanup_snapshots",
    "ensure_lifecycle_schema",
    "hold_snapshot_read",
    "register_snapshot",
    "record_snapshot_access",
    "resolve_static_snapshot",
    "reusable_business_snapshot",
    "run_background_retention",
    "source_fingerprint",
    "touch_snapshot",
    "unarchive_snapshot",
]
