from __future__ import annotations

import base64
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hmac
import json
import os
import secrets
from typing import Any, Iterable
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    ClueAllocationAuditLog,
    ClueAllocationCycle,
    ClueAssignmentRound,
    ClueFollowUpRecord,
    ClueHeadquartersPoolEntry,
    ClueMasterLead,
    utcnow,
)
from apps.worker.clue_allocation_engine import AllocationResult, allocate_lead


SELF_OWNED_EXECUTION_MODES = {"formal", "trial"}
ACTIVE_ROUND_STATUSES = {"active_unfollowed", "active_followed"}
PREVIEW_TOKEN_TTL_SECONDS = 15 * 60
_EPHEMERAL_PREVIEW_SECRET = secrets.token_bytes(32)


class AllocationCycleError(ValueError):
    pass


@dataclass(frozen=True)
class AllocationPreviewGrant:
    operation: str
    lead_keys: tuple[str, ...]
    source_cycle_id: str | None
    privileged_confirmation: bool
    previewed_at: datetime
    expires_at: datetime
    token: str
    token_hash: str


def preview_trial_allocation_cycle(
    session: Session,
    *,
    lead_keys: Iterable[str],
    actor: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Calculate a trial allocation outcome in a rolled-back savepoint."""

    keys = _normalized_lead_keys(lead_keys)
    executed_at = _aware(now or utcnow())
    _assert_no_headquarters_reentry(session, keys)
    active_keys = _active_lead_keys(session, keys)
    savepoint = session.begin_nested()
    try:
        results = [
            allocate_lead(
                session,
                lead_key,
                execution_mode="trial",
                actor=actor,
                now=executed_at,
                auto_expiry_enabled_override=False,
            )
            for lead_key in active_keys
        ]
        summary = _summary(results)
    finally:
        savepoint.rollback()
        session.expire_all()
    grant = _issue_preview_grant(
        operation="trial",
        lead_keys=active_keys,
        actor=actor,
        previewed_at=executed_at,
    )
    return {
        "requested_lead_count": len(keys),
        "active_lead_count": len(active_keys),
        "lead_keys": active_keys,
        "summary": summary,
        "operation": grant.operation,
        "source_cycle_id": grant.source_cycle_id,
        "preview_token": grant.token,
        "preview_expires_at": grant.expires_at,
    }


def preview_rebuild_trial_allocation_cycle(
    session: Session,
    *,
    source_cycle_id: str,
    actor: str,
    privileged_confirmation: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Calculate a rebuild from one source trial cycle without writing state."""

    executed_at = _aware(now or utcnow())
    source_cycle = _rebuild_source_cycle(session, source_cycle_id)
    active_keys = _rebuild_active_lead_keys(session, source_cycle)
    if not active_keys:
        raise AllocationCycleError("source_cycle_not_rebuildable")
    blocked_keys = _rebuild_blocked_lead_keys(session, active_keys)
    if blocked_keys and not privileged_confirmation:
        raise AllocationCycleError(
            f"rebuild_blocked_by_follow_up:{','.join(blocked_keys)}"
        )
    savepoint = session.begin_nested()
    try:
        _supersede_active_trial_rounds(
            session,
            active_keys,
            executed_at,
            source_cycle_id=source_cycle.allocation_cycle_id,
        )
        results = [
            allocate_lead(
                session,
                lead_key,
                execution_mode="trial",
                actor=actor,
                now=executed_at,
                auto_expiry_enabled_override=False,
            )
            for lead_key in active_keys
        ]
        summary = _summary(results)
    finally:
        savepoint.rollback()
        session.expire_all()
    grant = _issue_preview_grant(
        operation="rebuild",
        lead_keys=active_keys,
        actor=actor,
        previewed_at=executed_at,
        source_cycle_id=source_cycle.allocation_cycle_id,
        privileged_confirmation=privileged_confirmation,
    )
    return {
        "requested_lead_count": len(active_keys),
        "active_lead_count": len(active_keys),
        "lead_keys": active_keys,
        "summary": summary,
        "operation": grant.operation,
        "source_cycle_id": grant.source_cycle_id,
        "preview_token": grant.token,
        "preview_expires_at": grant.expires_at,
    }


def validate_allocation_preview_grant(
    preview_token: str | None,
    *,
    operation: str,
    actor: str,
    lead_keys: Iterable[str] | None = None,
    source_cycle_id: str | None = None,
    privileged_confirmation: bool = False,
    now: datetime | None = None,
) -> AllocationPreviewGrant:
    normalized_token = str(preview_token or "").strip()
    if not normalized_token:
        raise AllocationCycleError("preview_required")
    encoded_payload, separator, signature = normalized_token.partition(".")
    if not separator or not encoded_payload or not signature:
        raise AllocationCycleError("preview_token_invalid")
    expected_signature = _preview_signature(encoded_payload)
    if not hmac.compare_digest(signature, expected_signature):
        raise AllocationCycleError("preview_token_invalid")
    try:
        payload = json.loads(_urlsafe_b64decode(encoded_payload).decode("utf-8"))
        previewed_at = datetime.fromtimestamp(int(payload["previewed_at"]), tz=timezone.utc)
        expires_at = datetime.fromtimestamp(int(payload["expires_at"]), tz=timezone.utc)
        token_lead_keys = tuple(_normalized_lead_keys(payload["lead_keys"]))
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        raise AllocationCycleError("preview_token_invalid") from None
    current_time = _aware(now or utcnow())
    if current_time >= expires_at:
        raise AllocationCycleError("preview_expired")
    if payload.get("operation") != operation:
        raise AllocationCycleError("preview_token_mismatch")
    if not hmac.compare_digest(str(payload.get("actor_hash") or ""), _actor_hash(actor)):
        raise AllocationCycleError("preview_token_mismatch")
    expected_keys = tuple(_normalized_lead_keys(lead_keys or [])) if lead_keys is not None else None
    if expected_keys is not None and token_lead_keys != expected_keys:
        raise AllocationCycleError("preview_token_mismatch")
    normalized_source_cycle_id = str(source_cycle_id or "").strip() or None
    if (str(payload.get("source_cycle_id") or "").strip() or None) != normalized_source_cycle_id:
        raise AllocationCycleError("preview_token_mismatch")
    if payload.get("privileged_confirmation") is not privileged_confirmation:
        raise AllocationCycleError("preview_token_mismatch")
    return AllocationPreviewGrant(
        operation=operation,
        lead_keys=token_lead_keys,
        source_cycle_id=normalized_source_cycle_id,
        privileged_confirmation=privileged_confirmation,
        previewed_at=previewed_at,
        expires_at=expires_at,
        token=normalized_token,
        token_hash=sha256(normalized_token.encode("utf-8")).hexdigest(),
    )


def run_trial_allocation_cycle(
    session: Session,
    *,
    lead_keys: Iterable[str],
    actor: str,
    privileged_confirmation: bool = False,
    preview_token_hash: str | None = None,
    expected_lead_keys: Iterable[str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    return _execute_trial_cycle(
        session,
        lead_keys=lead_keys,
        actor=actor,
        cycle_type="trial",
        privileged_confirmation=privileged_confirmation,
        preview_token_hash=preview_token_hash,
        expected_lead_keys=expected_lead_keys,
        now=now,
    )


def rebuild_trial_allocation_cycle(
    session: Session,
    *,
    source_cycle_id: str,
    actor: str,
    privileged_confirmation: bool = False,
    preview_token_hash: str | None = None,
    expected_lead_keys: Iterable[str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    executed_at = _aware(now or utcnow())
    existing_cycle = _existing_cycle_for_preview_token(session, preview_token_hash)
    if existing_cycle is not None:
        return _cycle_execution_payload(existing_cycle)
    source_cycle = _rebuild_source_cycle(session, source_cycle_id)
    active_keys = _rebuild_active_lead_keys(session, source_cycle)
    if not active_keys:
        raise AllocationCycleError("source_cycle_not_rebuildable")
    if expected_lead_keys is not None and tuple(active_keys) != tuple(
        _normalized_lead_keys(expected_lead_keys)
    ):
        raise AllocationCycleError("preview_no_longer_matches")
    blocked_keys = _rebuild_blocked_lead_keys(session, active_keys)
    if blocked_keys and not privileged_confirmation:
        raise AllocationCycleError(
            f"rebuild_blocked_by_follow_up:{','.join(blocked_keys)}"
        )
    _supersede_active_trial_rounds(
        session,
        active_keys,
        executed_at,
        source_cycle_id=source_cycle.allocation_cycle_id,
    )
    return _execute_trial_cycle(
        session,
        lead_keys=active_keys,
        actor=actor,
        cycle_type="rebuild",
        parent_cycle_id=source_cycle.allocation_cycle_id,
        privileged_confirmation=privileged_confirmation,
        now=executed_at,
        already_filtered=True,
        preview_token_hash=preview_token_hash,
    )


def _execute_trial_cycle(
    session: Session,
    *,
    lead_keys: Iterable[str],
    actor: str,
    cycle_type: str,
    privileged_confirmation: bool,
    now: datetime | None,
    parent_cycle_id: str | None = None,
    already_filtered: bool = False,
    preview_token_hash: str | None = None,
    expected_lead_keys: Iterable[str] | None = None,
) -> dict[str, Any]:
    keys = _normalized_lead_keys(lead_keys)
    executed_at = _aware(now or utcnow())
    existing_cycle = _existing_cycle_for_preview_token(session, preview_token_hash)
    if existing_cycle is not None:
        return _cycle_execution_payload(existing_cycle)
    _assert_no_headquarters_reentry(session, keys)
    active_keys = keys if already_filtered else _active_lead_keys(session, keys, lock=True)
    if expected_lead_keys is not None and tuple(active_keys) != tuple(
        _normalized_lead_keys(expected_lead_keys)
    ):
        raise AllocationCycleError("preview_no_longer_matches")
    _ensure_no_conflicting_current_rounds(session, active_keys)
    cycle = ClueAllocationCycle(
        allocation_cycle_id=f"allocation-cycle-{uuid4().hex}",
        cycle_type=cycle_type,
        execution_mode="trial",
        status="running",
        parent_cycle_id=parent_cycle_id,
        selected_lead_keys=active_keys,
        requested_lead_count=len(keys),
        active_lead_count=len(active_keys),
        planned_impact_json={"lead_keys": active_keys, "auto_expiry_enabled": False},
        actual_impact_json={},
        actor=actor,
        privileged_confirmation=privileged_confirmation,
        preview_token_hash=preview_token_hash,
        created_at=executed_at,
        executed_at=executed_at,
    )
    session.add(cycle)
    session.flush()
    results = [
        allocate_lead(
            session,
            lead_key,
            execution_mode="trial",
            allocation_cycle_id=cycle.allocation_cycle_id,
            actor=actor,
            now=executed_at,
            auto_expiry_enabled_override=False,
        )
        for lead_key in active_keys
    ]
    summary = _summary(results)
    cycle.status = "completed"
    cycle.actual_impact_json = summary
    cycle.completed_at = executed_at
    _record_audit(
        session,
        event_type="trial_rebuilt" if cycle_type == "rebuild" else "trial_executed",
        cycle=cycle,
        actor=actor,
        privileged_confirmation=privileged_confirmation,
        before_snapshot={"lead_keys": active_keys, "parent_cycle_id": parent_cycle_id},
        after_snapshot=summary,
    )
    session.flush()
    return {
        "allocation_cycle_id": cycle.allocation_cycle_id,
        "cycle_type": cycle.cycle_type,
        "execution_mode": cycle.execution_mode,
        "status": cycle.status,
        "requested_lead_count": cycle.requested_lead_count,
        "active_lead_count": cycle.active_lead_count,
        "privileged_confirmation": cycle.privileged_confirmation,
        "parent_cycle_id": cycle.parent_cycle_id,
        "summary": summary,
    }


def _normalized_lead_keys(lead_keys: Iterable[str]) -> list[str]:
    values = {str(lead_key).strip() for lead_key in lead_keys if str(lead_key).strip()}
    if not values:
        raise AllocationCycleError("lead_keys_required")
    return sorted(values)


def _active_lead_keys(
    session: Session,
    lead_keys: list[str],
    *,
    lock: bool = False,
) -> list[str]:
    statement = (
        select(ClueMasterLead)
        .where(ClueMasterLead.lead_key.in_(lead_keys))
        .where(ClueMasterLead.lifecycle_status == "active")
        .where(ClueMasterLead.normalized_order_status == "active")
        .order_by(ClueMasterLead.lead_key)
    )
    if lock:
        statement = statement.with_for_update()
    rows = session.scalars(statement).all()
    return [row.lead_key for row in rows]


def _assert_no_headquarters_reentry(session: Session, lead_keys: list[str]) -> None:
    if not lead_keys:
        return
    retriable_entry = (
        select(ClueHeadquartersPoolEntry.headquarters_pool_entry_id)
        .where(ClueHeadquartersPoolEntry.lead_key == ClueMasterLead.lead_key)
        .where(ClueHeadquartersPoolEntry.status == "active")
        .where(ClueHeadquartersPoolEntry.reason == "rule_version_unavailable")
        .exists()
    )
    rows = session.scalars(
        select(ClueMasterLead.lead_key)
        .where(ClueMasterLead.lead_key.in_(lead_keys))
        .where(ClueMasterLead.lifecycle_status == "active")
        .where(ClueMasterLead.pool_location == "headquarters_pool")
        .where(~retriable_entry)
        .order_by(ClueMasterLead.lead_key)
    ).all()
    if rows:
        raise AllocationCycleError(
            f"headquarters_reentry_not_supported:{','.join(rows)}"
        )


def _ensure_no_conflicting_current_rounds(session: Session, lead_keys: list[str]) -> None:
    if not lead_keys:
        return
    rows = session.scalars(
        select(ClueMasterLead)
        .where(ClueMasterLead.lead_key.in_(lead_keys))
        .order_by(ClueMasterLead.lead_key)
    ).all()
    conflicts: list[str] = []
    for lead in rows:
        if not lead.current_assignment_round_id:
            continue
        round_row = session.get(ClueAssignmentRound, lead.current_assignment_round_id)
        if round_row is None or round_row.round_status not in ACTIVE_ROUND_STATUSES:
            continue
        conflicts.append(lead.lead_key)
    if conflicts:
        raise AllocationCycleError(f"active_round_exists:{','.join(conflicts)}")


def _rebuild_blocked_lead_keys(session: Session, lead_keys: list[str]) -> list[str]:
    if not lead_keys:
        return []
    followed_rows = session.scalars(
        select(ClueAssignmentRound.lead_key)
        .where(ClueAssignmentRound.lead_key.in_(lead_keys))
        .where(ClueAssignmentRound.execution_mode.in_(SELF_OWNED_EXECUTION_MODES))
        .where(ClueAssignmentRound.is_followed.is_(True))
    ).all()
    recorded_rows = session.scalars(
        select(ClueAssignmentRound.lead_key)
        .join(
            ClueFollowUpRecord,
            ClueFollowUpRecord.assignment_round_id == ClueAssignmentRound.assignment_round_id,
        )
        .where(ClueAssignmentRound.lead_key.in_(lead_keys))
        .where(ClueAssignmentRound.execution_mode.in_(SELF_OWNED_EXECUTION_MODES))
        .where(ClueFollowUpRecord.deleted_at.is_(None))
    ).all()
    return sorted({lead_key for lead_key in [*followed_rows, *recorded_rows] if lead_key})


def _supersede_active_trial_rounds(
    session: Session,
    lead_keys: list[str],
    now: datetime,
    *,
    source_cycle_id: str,
) -> None:
    if not lead_keys:
        return
    rounds = session.scalars(
        select(ClueAssignmentRound)
        .where(ClueAssignmentRound.lead_key.in_(lead_keys))
        .where(ClueAssignmentRound.execution_mode == "trial")
        .where(ClueAssignmentRound.allocation_cycle_id == source_cycle_id)
        .where(ClueAssignmentRound.round_status.in_(ACTIVE_ROUND_STATUSES))
    ).all()
    for round_row in rounds:
        round_row.round_status = "superseded"
        round_row.terminal_reason = "trial_rebuilt"
        round_row.reassign_reason = "trial_rebuilt"
        round_row.matured_at = now
        round_row.updated_at = now
        lead = session.get(ClueMasterLead, round_row.lead_key)
        if lead is not None and lead.current_assignment_round_id == round_row.assignment_round_id:
            lead.current_assignment_round_id = None
            lead.pool_location = None
            lead.allocation_state = "pending_allocation"
            lead.updated_at = now
    session.flush()


def _rebuild_source_cycle(session: Session, source_cycle_id: str) -> ClueAllocationCycle:
    normalized = str(source_cycle_id).strip()
    if not normalized:
        raise AllocationCycleError("source_cycle_required")
    cycle = session.get(ClueAllocationCycle, normalized)
    if (
        cycle is None
        or cycle.execution_mode != "trial"
        or cycle.status != "completed"
        or cycle.cycle_type not in {"trial", "rebuild"}
    ):
        raise AllocationCycleError("source_cycle_not_rebuildable")
    return cycle


def _rebuild_active_lead_keys(
    session: Session,
    source_cycle: ClueAllocationCycle,
) -> list[str]:
    rows = session.execute(
        select(ClueAssignmentRound.lead_key)
        .join(ClueMasterLead, ClueMasterLead.lead_key == ClueAssignmentRound.lead_key)
        .where(ClueAssignmentRound.allocation_cycle_id == source_cycle.allocation_cycle_id)
        .where(ClueAssignmentRound.execution_mode == "trial")
        .where(ClueAssignmentRound.round_status.in_(ACTIVE_ROUND_STATUSES))
        .where(ClueMasterLead.current_assignment_round_id == ClueAssignmentRound.assignment_round_id)
        .where(ClueMasterLead.lifecycle_status == "active")
        .where(ClueMasterLead.normalized_order_status == "active")
        .where(ClueMasterLead.pool_location != "headquarters_pool")
        .order_by(ClueAssignmentRound.lead_key)
        .with_for_update()
    ).scalars().all()
    return sorted({lead_key for lead_key in rows if lead_key})


def _summary(results: list[AllocationResult]) -> dict[str, int]:
    counts = Counter(result.status for result in results)
    return {
        "assigned": int(counts["assigned"]),
        "headquarters": int(counts["headquarters"]),
        "skipped": int(counts["skipped"]),
        "total": len(results),
    }


def _existing_cycle_for_preview_token(
    session: Session,
    preview_token_hash: str | None,
) -> ClueAllocationCycle | None:
    if not preview_token_hash:
        return None
    return session.scalar(
        select(ClueAllocationCycle)
        .where(ClueAllocationCycle.preview_token_hash == preview_token_hash)
        .where(ClueAllocationCycle.status == "completed")
    )


def _cycle_execution_payload(cycle: ClueAllocationCycle) -> dict[str, Any]:
    return {
        "allocation_cycle_id": cycle.allocation_cycle_id,
        "cycle_type": cycle.cycle_type,
        "execution_mode": cycle.execution_mode,
        "status": cycle.status,
        "requested_lead_count": cycle.requested_lead_count,
        "active_lead_count": cycle.active_lead_count,
        "privileged_confirmation": cycle.privileged_confirmation,
        "parent_cycle_id": cycle.parent_cycle_id,
        "summary": dict(cycle.actual_impact_json or {}),
    }


def _record_audit(
    session: Session,
    *,
    event_type: str,
    cycle: ClueAllocationCycle,
    actor: str,
    privileged_confirmation: bool,
    before_snapshot: dict[str, Any],
    after_snapshot: dict[str, Any],
) -> None:
    session.add(
        ClueAllocationAuditLog(
            audit_log_id=f"allocation-audit-{uuid4().hex}",
            event_type=event_type,
            allocation_cycle_id=cycle.allocation_cycle_id,
            actor=actor,
            privileged_confirmation=privileged_confirmation,
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            detail_json={
                "cycle_type": cycle.cycle_type,
                "execution_mode": cycle.execution_mode,
                "preview_token_hash": cycle.preview_token_hash,
            },
            created_at=cycle.completed_at or cycle.created_at,
        )
    )


def _issue_preview_grant(
    *,
    operation: str,
    lead_keys: Iterable[str],
    actor: str,
    previewed_at: datetime,
    source_cycle_id: str | None = None,
    privileged_confirmation: bool = False,
) -> AllocationPreviewGrant:
    normalized_keys = tuple(_normalized_lead_keys(lead_keys))
    issued_at = _aware(previewed_at)
    expires_at = issued_at.replace(microsecond=0) + timedelta(seconds=PREVIEW_TOKEN_TTL_SECONDS)
    payload = {
        "actor_hash": _actor_hash(actor),
        "expires_at": int(expires_at.timestamp()),
        "lead_keys": list(normalized_keys),
        "nonce": secrets.token_urlsafe(12),
        "operation": operation,
        "previewed_at": int(issued_at.timestamp()),
        "privileged_confirmation": privileged_confirmation,
        "source_cycle_id": source_cycle_id,
        "version": 1,
    }
    encoded_payload = _urlsafe_b64encode(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    token = f"{encoded_payload}.{_preview_signature(encoded_payload)}"
    return AllocationPreviewGrant(
        operation=operation,
        lead_keys=normalized_keys,
        source_cycle_id=source_cycle_id,
        privileged_confirmation=privileged_confirmation,
        previewed_at=issued_at,
        expires_at=expires_at,
        token=token,
        token_hash=sha256(token.encode("utf-8")).hexdigest(),
    )


def _preview_signature(encoded_payload: str) -> str:
    digest = hmac.new(
        _preview_token_secret(),
        encoded_payload.encode("ascii"),
        sha256,
    ).digest()
    return _urlsafe_b64encode(digest)


def _preview_token_secret() -> bytes:
    configured = os.getenv("DY_SESSION_SECRET", "").strip()
    return configured.encode("utf-8") if configured else _EPHEMERAL_PREVIEW_SECRET


def _actor_hash(actor: str) -> str:
    return sha256(str(actor).strip().encode("utf-8")).hexdigest()


def _urlsafe_b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _urlsafe_b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
