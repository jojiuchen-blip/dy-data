"""Bounded, source-bound recovery for formal clue phone projections.

The clue center projection intentionally does not call the Douyin decrypt API
when it runs as part of the first-allocation compensation path.  This module
fills only the derived phone fields after a formal round is already committed.
It never changes allocation state, round state, or source facts.
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from time import monotonic
from typing import Any, Callable, Mapping

from sqlalchemy import select, text

from apps.api.dy_api.models import (
    ClueAssignmentRound,
    ClueCenterOrder,
    ClueMasterLead,
    RawDouyinClue,
    SyncSetting,
)
from apps.worker.clue_center import (
    ACTIVE_ROUND_STATUSES,
    CLUE_SOURCE_ACTIVE_ORDER_STATUSES,
    _clue_sort_key,
    _phone_source,
)
from src.dy_data.phones import mask_phone, normalize_phone, phone_source_fingerprint


LOG = logging.getLogger(__name__)

# This lock is deliberately different from the formal-allocation lock.  The
# lock connection remains outside a transaction while the network call runs;
# this gives the worker one consumer without holding a business transaction.
PHONE_RECOVERY_LOCK_KEY = 90310911
PHONE_RECOVERY_STATE_KEY = "clue_phone_recovery_state_v1"
PHONE_RECOVERY_BATCH_SIZE = 100
PHONE_RECOVERY_MAX_SECONDS = 10.0
PHONE_RECOVERY_TIMEOUT_SECONDS = 8.0
PHONE_RECOVERY_RETRY_ATTEMPTS = 1
PHONE_FAILURE_BASE_SECONDS = 60
PHONE_FAILURE_MAX_SECONDS = 3600
PHONE_FAILURE_STATE_LIMIT = 512
PHONE_FAILURE_STATE_RETENTION_SECONDS = 86400

_LOCAL_LOCK = Lock()


@dataclass(frozen=True)
class _PhoneSource:
    kind: str
    value: str
    label: str
    fingerprint: str | None


@dataclass(frozen=True)
class _Candidate:
    lead_key: str
    order_id: str
    round_id: str
    source: _PhoneSource


@dataclass
class _RecoveryState:
    phase: str = "missing"
    missing_cursor: str = ""
    stale_cursor: str = ""
    cooldowns: dict[str, dict[str, float | int]] = field(default_factory=dict)


def _aware(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


@contextmanager
def _phone_recovery_lock(factory):
    """Yield whether this process won the recovery lock.

    PostgreSQL advisory locks are held by a dedicated connection, but every
    transaction used for reads/writes is opened and closed separately.  The
    SQLite fallback protects the in-process test worker only.
    """

    with factory() as probe:
        engine = probe.get_bind()
    if engine.dialect.name != "postgresql":
        held = _LOCAL_LOCK.acquire(blocking=False)
        try:
            yield held
        finally:
            if held:
                _LOCAL_LOCK.release()
        return

    with engine.connect() as connection:
        held = bool(
            connection.scalar(
                text("SELECT pg_try_advisory_lock(:key)"),
                {"key": PHONE_RECOVERY_LOCK_KEY},
            )
        )
        connection.commit()
        try:
            yield held
        finally:
            if held:
                connection.execute(
                    text("SELECT pg_advisory_unlock(:key)"),
                    {"key": PHONE_RECOVERY_LOCK_KEY},
                )
                connection.commit()


def _load_state(session, now: datetime) -> _RecoveryState:
    row = session.get(SyncSetting, PHONE_RECOVERY_STATE_KEY)
    raw: Mapping[str, Any] = {}
    if row is not None:
        try:
            parsed = json.loads(row.setting_value or "{}")
            if isinstance(parsed, dict):
                raw = parsed
        except (TypeError, ValueError):
            LOG.warning("clue_phone_recovery_state_invalid")

    cooldowns: dict[str, dict[str, float | int]] = {}
    now_ts = now.timestamp()
    raw_cooldowns = raw.get("cooldowns")
    if isinstance(raw_cooldowns, dict):
        for fingerprint, value in raw_cooldowns.items():
            if not isinstance(fingerprint, str) or len(fingerprint) != 64:
                continue
            if not isinstance(value, dict):
                continue
            try:
                retry_at = float(value.get("retry_at", 0))
                attempts = max(1, int(value.get("attempts", 1)))
            except (TypeError, ValueError):
                continue
            last_failed_at = float(value.get("last_failed_at", retry_at))
            if last_failed_at >= now_ts - PHONE_FAILURE_STATE_RETENTION_SECONDS:
                cooldowns[fingerprint] = {
                    "retry_at": retry_at,
                    "attempts": attempts,
                    "last_failed_at": last_failed_at,
                }

    # Keep the setting bounded even if an upstream source keeps changing.
    if len(cooldowns) > PHONE_FAILURE_STATE_LIMIT:
        cooldowns = dict(
            sorted(
                cooldowns.items(),
                key=lambda item: float(item[1]["retry_at"]),
                reverse=True,
            )[:PHONE_FAILURE_STATE_LIMIT]
        )
    return _RecoveryState(
        phase=str(raw.get("phase") or "missing")
        if str(raw.get("phase") or "missing") in {"missing", "stale"}
        else "missing",
        missing_cursor=str(raw.get("missing_cursor") or "").strip(),
        stale_cursor=str(raw.get("stale_cursor") or "").strip(),
        cooldowns=cooldowns,
    )


def _save_state(session, state: _RecoveryState) -> None:
    payload = json.dumps(
        {
            "phase": state.phase,
            "missing_cursor": state.missing_cursor,
            "stale_cursor": state.stale_cursor,
            "cooldowns": state.cooldowns,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    row = session.get(SyncSetting, PHONE_RECOVERY_STATE_KEY)
    if row is None:
        session.add(
            SyncSetting(
                setting_key=PHONE_RECOVERY_STATE_KEY,
                setting_value=payload,
            )
        )
    else:
        row.setting_value = payload


def _source_for_clues(clues: list[RawDouyinClue]) -> _PhoneSource | None:
    if not clues:
        return None
    kind, value, label = _phone_source(sorted(clues, key=_clue_sort_key))
    if not kind or not value or not label:
        return None
    if kind == "plain":
        normalized = normalize_phone(value)
        if not normalized:
            return None
        return _PhoneSource(
            kind=kind,
            value=normalized,
            label=label,
            fingerprint=phone_source_fingerprint(plain_phone=normalized),
        )
    if kind == "masked":
        return _PhoneSource(
            kind=kind,
            value=str(value).strip(),
            label=label,
            fingerprint=None,
        )
    fingerprint = phone_source_fingerprint(cipher_text=value)
    if not fingerprint:
        return None
    return _PhoneSource(
        kind=kind,
        value=str(value).strip(),
        label=label,
        fingerprint=fingerprint,
    )


def _source_needs_repair(center: ClueCenterOrder, source: _PhoneSource) -> bool:
    if source.kind == "plain":
        return bool(
            normalize_phone(center.phone_plain) != source.value
            or center.phone_masked != mask_phone(source.value)
            or center.phone_source_fingerprint != source.fingerprint
        )
    if source.kind == "masked":
        return bool(
            normalize_phone(center.phone_plain)
            or center.phone_masked != source.value
            or center.phone_source_fingerprint is not None
            or center.phone_source != source.label
        )
    return not (
        normalize_phone(center.phone_plain)
        and center.phone_source_fingerprint == source.fingerprint
    )


def _active_formal_statement():
    return (
        select(ClueMasterLead, ClueCenterOrder, ClueAssignmentRound)
        .join(
            ClueCenterOrder,
            ClueCenterOrder.order_id == ClueMasterLead.order_id,
        )
        .join(
            ClueAssignmentRound,
            ClueAssignmentRound.assignment_round_id
            == ClueMasterLead.current_assignment_round_id,
        )
        .where(
            ClueMasterLead.master_kind == 1,
            ClueMasterLead.lifecycle_status == "active",
            ClueMasterLead.normalized_order_status == "active",
            ClueMasterLead.allocation_state == "assigned",
            ClueMasterLead.current_assignment_round_id.is_not(None),
            (ClueMasterLead.pool_location.is_(None)
             | (ClueMasterLead.pool_location != "headquarters_pool")),
            ClueCenterOrder.current_assignment_round_id
            == ClueAssignmentRound.assignment_round_id,
            ClueCenterOrder.order_id == ClueAssignmentRound.order_id,
            ClueCenterOrder.current_round_status.in_(ACTIVE_ROUND_STATUSES),
            ClueAssignmentRound.lead_key == ClueMasterLead.lead_key,
            ClueAssignmentRound.execution_mode == "formal",
            ClueAssignmentRound.round_status.in_(ACTIVE_ROUND_STATUSES),
            ClueAssignmentRound.assigned_store_id.is_not(None),
        )
    )


def _set_phase_timeouts(session, deadline: float | None) -> bool:
    if deadline is None:
        return True
    remaining_ms = int((deadline - monotonic()) * 1000)
    if remaining_ms <= 0:
        return False
    if session.get_bind().dialect.name == "postgresql":
        lock_ms = max(1, min(1000, remaining_ms))
        session.execute(text(f"SET LOCAL lock_timeout = '{lock_ms}ms'"))
        session.execute(text(f"SET LOCAL statement_timeout = '{max(1, remaining_ms)}ms'"))
    return True


def _read_candidates(
    factory,
    *,
    limit: int,
    now: datetime,
    deadline: float | None = None,
    order_ids: set[str] | None = None,
) -> tuple[list[_Candidate], dict[str, int]]:
    with factory() as session:
        if not _set_phase_timeouts(session, deadline):
            return [], {"deferred": 1}
        state = _load_state(session, now)
        selected: list[tuple[ClueMasterLead, ClueCenterOrder, ClueAssignmentRound]] = []
        phase = "targeted" if order_ids is not None else state.phase
        for _ in range(5):
            if not _set_phase_timeouts(session, deadline):
                return [], {"deferred": 1}
            if phase == "targeted":
                cursor = ""
                statement = _active_formal_statement().where(
                    ClueMasterLead.order_id.in_(order_ids or set())
                )
            elif phase == "missing":
                cursor = state.missing_cursor
                statement = _active_formal_statement().where(
                    (ClueCenterOrder.phone_plain.is_(None))
                    | (ClueCenterOrder.phone_plain == "")
                    | (ClueCenterOrder.phone_source_fingerprint.is_(None))
                    | (ClueCenterOrder.phone_source_fingerprint == "")
                )
            else:
                cursor = state.stale_cursor
                statement = _active_formal_statement().where(
                    ClueCenterOrder.phone_plain.is_not(None),
                    ClueCenterOrder.phone_plain != "",
                    ClueCenterOrder.phone_source_fingerprint.is_not(None),
                    ClueCenterOrder.phone_source_fingerprint != "",
                )
            if cursor:
                statement = statement.where(ClueMasterLead.lead_key > cursor)
            rows = list(
                session.execute(
                    statement.order_by(
                        ClueMasterLead.lead_key,
                        ClueMasterLead.order_id,
                        ClueAssignmentRound.assignment_round_id,
                    ).limit(limit)
                ).all()
            )
            if rows:
                selected = [(row[0], row[1], row[2]) for row in rows]
                break
            if phase == "targeted":
                break
            cursor_was_set = bool(state.missing_cursor if phase == "missing" else state.stale_cursor)
            if cursor_was_set:
                if phase == "missing":
                    state.missing_cursor = ""
                else:
                    state.stale_cursor = ""
                _save_state(session, state)
                session.commit()
                continue
            phase = "stale" if phase == "missing" else "missing"
            state.phase = phase
            continue

        if not selected:
            return [], {"wrapped": 1 if state.missing_cursor or state.stale_cursor else 0}

        if not _set_phase_timeouts(session, deadline):
            return [], {"deferred": 1}
        order_ids = {lead.order_id for lead, _, _ in selected if lead.order_id}
        raw_rows = list(
            session.scalars(
                select(RawDouyinClue)
                .where(RawDouyinClue.order_id.in_(order_ids))
                .where(RawDouyinClue.order_status.in_(CLUE_SOURCE_ACTIVE_ORDER_STATUSES))
                .order_by(
                    RawDouyinClue.order_id,
                    RawDouyinClue.create_time_detail,
                    RawDouyinClue.clue_id,
                    RawDouyinClue.clue_row_key,
                )
            )
        )
        grouped: dict[str, list[RawDouyinClue]] = {}
        for raw in raw_rows:
            if raw.order_id:
                grouped.setdefault(raw.order_id, []).append(raw)

        candidates: list[_Candidate] = []
        now_ts = now.timestamp()
        for lead, center, round_row in selected:
            source = _source_for_clues(grouped.get(lead.order_id or "", []))
            if source is None or not _source_needs_repair(center, source):
                continue
            if (
                source.fingerprint
                and float(
                    state.cooldowns.get(source.fingerprint, {}).get("retry_at", 0)
                )
                > now_ts
            ):
                continue
            candidates.append(
                _Candidate(
                    lead_key=lead.lead_key,
                    order_id=lead.order_id or "",
                    round_id=round_row.assignment_round_id,
                    source=source,
                )
            )

        if phase != "targeted":
            last_key = selected[-1][0].lead_key
            if phase == "missing":
                state.missing_cursor = last_key
            else:
                state.stale_cursor = last_key
            state.phase = "stale" if phase == "missing" else "missing"
            _save_state(session, state)
        if not _set_phase_timeouts(session, deadline):
            session.rollback()
            return [], {"deferred": 1}
        if phase != "targeted":
            session.commit()
        else:
            session.rollback()
        return candidates, {"wrapped": 0, "scanned": len(selected), "phase": phase}


def _current_candidates(
    session,
    candidates: list[_Candidate],
) -> dict[str, tuple[ClueMasterLead, ClueCenterOrder, ClueAssignmentRound, _PhoneSource]]:
    """Lock current rows and re-read source data for the final CAS check."""

    lead_keys = {candidate.lead_key for candidate in candidates}
    order_ids = {candidate.order_id for candidate in candidates}
    round_ids = {candidate.round_id for candidate in candidates}
    leads = {
        row.lead_key: row
        for row in session.scalars(
            select(ClueMasterLead)
            .where(ClueMasterLead.lead_key.in_(lead_keys))
            .order_by(ClueMasterLead.lead_key)
            .with_for_update()
        )
    }
    centers = {
        row.order_id: row
        for row in session.scalars(
            select(ClueCenterOrder)
            .where(ClueCenterOrder.order_id.in_(order_ids))
            .order_by(ClueCenterOrder.order_id)
            .with_for_update()
        )
    }
    rounds = {
        row.assignment_round_id: row
        for row in session.scalars(
            select(ClueAssignmentRound)
            .where(ClueAssignmentRound.assignment_round_id.in_(round_ids))
            .order_by(ClueAssignmentRound.assignment_round_id)
            .with_for_update()
        )
    }
    raw_rows = list(
        session.scalars(
            select(RawDouyinClue)
            .where(RawDouyinClue.order_id.in_(order_ids))
            .where(RawDouyinClue.order_status.in_(CLUE_SOURCE_ACTIVE_ORDER_STATUSES))
            .order_by(
                RawDouyinClue.order_id,
                RawDouyinClue.create_time_detail,
                RawDouyinClue.clue_id,
                RawDouyinClue.clue_row_key,
            )
            .with_for_update()
        )
    )
    grouped: dict[str, list[RawDouyinClue]] = {}
    for raw in raw_rows:
        if raw.order_id:
            grouped.setdefault(raw.order_id, []).append(raw)

    result: dict[str, tuple[ClueMasterLead, ClueCenterOrder, ClueAssignmentRound, _PhoneSource]] = {}
    for candidate in candidates:
        lead = leads.get(candidate.lead_key)
        center = centers.get(candidate.order_id)
        round_row = rounds.get(candidate.round_id)
        source = _source_for_clues(grouped.get(candidate.order_id, []))
        if lead is None or center is None or round_row is None or source is None:
            continue
        if not (
            lead.master_kind == 1
            and (lead.pool_location is None or lead.pool_location != "headquarters_pool")
            and lead.order_id == candidate.order_id
            and lead.lifecycle_status == "active"
            and lead.normalized_order_status == "active"
            and lead.allocation_state == "assigned"
            and lead.current_assignment_round_id == candidate.round_id
            and center.current_assignment_round_id == candidate.round_id
            and round_row.order_id == candidate.order_id
            and round_row.lead_key == candidate.lead_key
            and round_row.execution_mode == "formal"
            and round_row.round_status in ACTIVE_ROUND_STATUSES
            and round_row.assigned_store_id
            and source.kind == candidate.source.kind
            and source.value == candidate.source.value
            and source.fingerprint == candidate.source.fingerprint
        ):
            continue
        result[candidate.order_id] = (lead, center, round_row, source)
    return result


def _apply_source(center: ClueCenterOrder, source: _PhoneSource, plain: str | None) -> None:
    normalized = normalize_phone(plain)
    if source.kind == "plain":
        normalized = source.value
    if normalized:
        center.phone_plain = normalized
        center.phone_masked = mask_phone(normalized)
    else:
        center.phone_plain = None
        center.phone_masked = source.value if source.kind == "masked" else None
    center.phone_source = source.label if normalized or source.kind == "masked" else None
    center.phone_source_fingerprint = source.fingerprint


def _write_results(
    factory,
    candidates: list[_Candidate],
    decrypted: Mapping[str, Any],
    *,
    deadline: float | None = None,
) -> dict[str, int]:
    stats = {"repaired": 0, "source_changed": 0, "already_current": 0, "unresolved": 0}
    if not candidates:
        return stats
    with factory() as session:
        if not _set_phase_timeouts(session, deadline):
            stats["deferred"] = len(candidates)
            return stats
        current = _current_candidates(session, candidates)
        dirty = False
        for candidate in candidates:
            row = current.get(candidate.order_id)
            if row is None:
                stats["source_changed"] += 1
                continue
            _, center, _, source = row
            plain = (
                source.value
                if source.kind == "plain"
                else normalize_phone(decrypted.get(source.value))
                if source.kind == "cipher"
                else ""
            )
            if source.kind == "cipher" and not plain:
                stats["unresolved"] += 1
                continue
            if not _source_needs_repair(center, source):
                stats["already_current"] += 1
                continue
            _apply_source(center, source, plain)
            stats["repaired"] += 1
            dirty = True
        if dirty:
            if not _set_phase_timeouts(session, deadline):
                session.rollback()
                stats["deferred"] = len(candidates)
                stats["repaired"] = 0
                return stats
            session.commit()
        else:
            session.rollback()
    return stats


def _retry_after_seconds(error: BaseException | None) -> int | None:
    if error is None:
        return None
    for value in (
        getattr(error, "retry_after_seconds", None),
        getattr(getattr(error, "reservation", None), "retry_after_seconds", None),
    ):
        try:
            if value is not None:
                return max(PHONE_FAILURE_BASE_SECONDS, int(value))
        except (TypeError, ValueError):
            continue
    return None


def _update_cooldowns(
    factory,
    candidates: list[_Candidate],
    decrypted: Mapping[str, Any],
    *,
    error: BaseException | None,
    now: datetime,
    deadline: float | None = None,
) -> None:
    cipher_candidates = [candidate for candidate in candidates if candidate.source.kind == "cipher"]
    if not cipher_candidates:
        return
    with factory() as session:
        if not _set_phase_timeouts(session, deadline):
            return
        state = _load_state(session, now)
        retry_after = _retry_after_seconds(error)
        for candidate in cipher_candidates:
            fingerprint = candidate.source.fingerprint
            if not fingerprint:
                continue
            plain = normalize_phone(decrypted.get(candidate.source.value))
            if plain:
                state.cooldowns.pop(fingerprint, None)
                continue
            previous = state.cooldowns.get(fingerprint, {})
            attempts = max(1, int(previous.get("attempts", 0) or 0) + 1)
            delay = retry_after or min(
                PHONE_FAILURE_MAX_SECONDS,
                PHONE_FAILURE_BASE_SECONDS * (2 ** min(attempts - 1, 6)),
            )
            state.cooldowns[fingerprint] = {
                "retry_at": now.timestamp() + delay,
                "attempts": attempts,
                "last_failed_at": now.timestamp(),
            }
        _save_state(session, state)
        if not _set_phase_timeouts(session, deadline):
            session.rollback()
            return
        session.commit()


def _build_default_client() -> Any:
    from apps.worker.pipeline import build_douyin_client_from_env

    client = build_douyin_client_from_env()
    # Keep this recovery path bounded without changing the worker's shared
    # credential or quota construction.
    if hasattr(client, "timeout_seconds"):
        client.timeout_seconds = min(
            float(getattr(client, "timeout_seconds", PHONE_RECOVERY_TIMEOUT_SECONDS)),
            PHONE_RECOVERY_TIMEOUT_SECONDS,
        )
    if hasattr(client, "retry_attempts"):
        client.retry_attempts = min(
            int(getattr(client, "retry_attempts", PHONE_RECOVERY_RETRY_ATTEMPTS)),
            PHONE_RECOVERY_RETRY_ATTEMPTS,
        )
    return client


def run_clue_phone_recovery_batch(
    factory,
    *,
    phone_plain_resolver: Callable[[list[str]], Mapping[str, Any]] | None = None,
    client: Any | None = None,
    client_factory: Callable[[], Any] | None = None,
    max_items: int = PHONE_RECOVERY_BATCH_SIZE,
    max_seconds: float = PHONE_RECOVERY_MAX_SECONDS,
    now: datetime | None = None,
    order_ids: list[str] | tuple[str, ...] | set[str] | None = None,
) -> dict[str, int | str]:
    """Recover a bounded page of current formal-round phone projections.

    The public entry point accepts a resolver so tests and authenticated worker
    integrations can inject the existing decrypt endpoint.  The default client
    is built lazily only when encrypted candidates exist.
    """

    limit = max(1, min(int(max_items), PHONE_RECOVERY_BATCH_SIZE))
    target_order_ids = None
    if order_ids is not None:
        target_order_ids = sorted({str(value).strip() for value in order_ids if str(value).strip()})
        if len(target_order_ids) > 1000:
            raise ValueError("phone recovery order_ids exceeds 1000 orders")
    bounded_seconds = max(0.1, min(float(max_seconds), 30.0))
    deadline = monotonic() + bounded_seconds
    current_time = _aware(now)
    result: dict[str, int | str] = {
        "scanned": 0,
        "requested": 0,
        "repaired": 0,
        "source_changed": 0,
        "unresolved": 0,
        "failed": 0,
        "deferred": 0,
        "skipped": 0,
    }
    with _phone_recovery_lock(factory) as held:
        if not held:
            result["skipped"] = 1
            result["skip_reason"] = "locked"
            return result

        candidates, selection_stats = _read_candidates(
            factory,
            limit=limit,
            now=current_time,
            deadline=deadline,
            order_ids=set(target_order_ids) if target_order_ids is not None else None,
        )
        result["scanned"] = int(selection_stats.get("scanned", 0) or 0)
        result["deferred"] = int(selection_stats.get("deferred", 0) or 0)
        if not candidates:
            return result

        cipher_candidates = [candidate for candidate in candidates if candidate.source.kind == "cipher"]
        unique_ciphers = list(dict.fromkeys(candidate.source.value for candidate in cipher_candidates))
        decrypted: Mapping[str, Any] = {}
        error: BaseException | None = None
        if unique_ciphers:
            result["requested"] = len(unique_ciphers)
            resolver = phone_plain_resolver
            if resolver is None:
                active_client = client
                try:
                    if active_client is None:
                        active_client = (
                            client_factory() if client_factory is not None else _build_default_client()
                        )
                    if hasattr(active_client, "timeout_seconds"):
                        remaining = max(0.1, deadline - monotonic())
                        active_client.timeout_seconds = min(
                            float(getattr(active_client, "timeout_seconds", remaining)),
                            remaining,
                        )
                    resolver = getattr(active_client, "decrypt_cipher_texts", None)
                except Exception as exc:  # noqa: BLE001 - credential construction is an external boundary.
                    error = exc
                    LOG.warning("clue_phone_recovery_client_unavailable type=%s", type(exc).__name__)
            if not callable(resolver):
                error = RuntimeError("phone resolver is unavailable")
            else:
                try:
                    value = resolver(unique_ciphers)
                    decrypted = value if isinstance(value, Mapping) else {}
                except Exception as exc:  # noqa: BLE001 - external boundary is fail closed.
                    error = exc
                    LOG.warning("clue_phone_recovery_resolver_failed type=%s", type(exc).__name__)

        write_stats = _write_results(
            factory,
            candidates,
            decrypted,
            deadline=deadline,
        )
        for key in ("repaired", "source_changed", "unresolved", "already_current"):
            if key in write_stats:
                result[key] = int(result.get(key, 0) or 0) + int(write_stats[key])
        if error is not None:
            result["failed"] = 1
        _update_cooldowns(
            factory,
            cipher_candidates,
            decrypted,
            error=error,
            now=current_time,
            deadline=deadline,
        )
        result["deferred"] = max(
            int(result["deferred"]),
            int(write_stats.get("deferred", 0) or 0),
            max(0, len(candidates) - int(result["repaired"])),
        )
    return result


# Short alias for scheduler callers that do not need the batch suffix.
run_clue_phone_recovery = run_clue_phone_recovery_batch
