from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import ClueAssignmentRound, ClueCenterOrder, ClueFollowUpRecord, ClueMasterLead


SELF_OWNED_EXECUTION_MODES = {"formal", "trial"}
FOLLOW_UP_ACTIONS = {
    "appointment",
    "further_follow_up",
    "lost",
    "unreachable",
    "request_store_change",
}
PROTECTION_ACTIONS = {"appointment", "further_follow_up", "unreachable"}
ACTIVE_ROUND_STATUSES = {"active_unfollowed", "active_followed"}
TERMINAL_ORDER_STATUSES = {"verified", "refunded"}


@dataclass(frozen=True)
class FollowUpStateResult:
    status: str
    record: ClueFollowUpRecord | None = None
    assignment_round_id: str | None = None


def apply_follow_up_action(
    session: Session,
    *,
    order_id: str,
    assignment_round_id: str,
    follow_result: str,
    actor: dict[str, Any],
    note: str | None = None,
    now: datetime | None = None,
) -> FollowUpStateResult:
    """Persist one follow-up action against the actual current self-owned round."""

    action = (follow_result or "").strip()
    if action not in FOLLOW_UP_ACTIONS:
        return FollowUpStateResult("conflict")
    round_row = session.get(ClueAssignmentRound, assignment_round_id)
    if round_row is None or round_row.order_id != order_id:
        return FollowUpStateResult("not_found")
    lead = session.get(ClueMasterLead, round_row.lead_key) if round_row.lead_key else None
    if lead is None or not _is_current_active_round(lead, round_row):
        return FollowUpStateResult("conflict")
    if not _actor_can_operate_round(round_row, actor):
        return FollowUpStateResult("forbidden")

    executed_at = _aware(now)
    if lead.normalized_order_status in TERMINAL_ORDER_STATUSES:
        _close_for_terminal_order(lead, round_row, executed_at, session)
        session.flush()
        return FollowUpStateResult("conflict")

    record = ClueFollowUpRecord(
        follow_up_record_id=uuid4().hex,
        order_id=order_id,
        assignment_round_id=round_row.assignment_round_id,
        round_no=round_row.round_no,
        assigned_store_id=round_row.assigned_store_id,
        follow_result=action,
        note=(note or "").strip() or None,
        operator_user_id=_text(actor.get("user_id")),
        operator_username=_text(actor.get("username")),
        created_at=executed_at,
    )
    session.add(record)
    if action in {"lost", "request_store_change"}:
        _close_and_allocate_next(lead, round_row, action, executed_at, session, record.follow_up_record_id)
        session.flush()
        return FollowUpStateResult("ok", record, lead.current_assignment_round_id)
    _apply_visible_summary(round_row, action, executed_at)
    _project_current_round_summary(lead, round_row, session, executed_at)
    session.flush()
    return FollowUpStateResult("ok", record, round_row.assignment_round_id)


def process_due_transitions(session: Session, *, now: datetime | None = None) -> dict[str, int]:
    """Advance only existing active self-owned rounds; this never allocates pending leads."""

    processed_at = _aware(now)
    stats = {"sla_expired": 0, "protection_expired": 0, "terminal_closed": 0}
    rounds = session.scalars(
        select(ClueAssignmentRound)
        .where(ClueAssignmentRound.execution_mode.in_(SELF_OWNED_EXECUTION_MODES))
        .where(ClueAssignmentRound.round_status.in_(ACTIVE_ROUND_STATUSES))
        .order_by(ClueAssignmentRound.assignment_round_id)
    ).all()
    for round_row in rounds:
        lead = session.get(ClueMasterLead, round_row.lead_key) if round_row.lead_key else None
        if lead is None or lead.current_assignment_round_id != round_row.assignment_round_id:
            continue
        if lead.normalized_order_status in TERMINAL_ORDER_STATUSES:
            _close_for_terminal_order(lead, round_row, processed_at, session)
            stats["terminal_closed"] += 1
            continue
        if not round_row.auto_expiry_enabled:
            continue
        sla_expires_at = round_row.first_sla_expires_at or round_row.expires_at
        if not round_row.is_followed and sla_expires_at is not None and _aware(sla_expires_at) <= processed_at:
            _close_and_allocate_next(lead, round_row, "sla_expired", processed_at, session, f"due:{round_row.assignment_round_id}:sla")
            stats["sla_expired"] += 1
            continue
        if round_row.protection_expires_at is not None and _aware(round_row.protection_expires_at) <= processed_at:
            _close_and_allocate_next(
                lead,
                round_row,
                "protection_expired",
                processed_at,
                session,
                f"due:{round_row.assignment_round_id}:protection",
            )
            stats["protection_expired"] += 1
    session.flush()
    return stats


def soft_delete_follow_up_record(
    session: Session,
    *,
    follow_up_record_id: str,
    actor: dict[str, Any],
    reason: str | None,
    now: datetime | None = None,
) -> FollowUpStateResult:
    """Audit-reverse one follow-up record without reopening a past transition."""

    if not _actor_is_highest_admin(actor):
        return FollowUpStateResult("forbidden")
    record = session.get(ClueFollowUpRecord, follow_up_record_id)
    if record is None:
        return FollowUpStateResult("not_found")
    if record.deleted_at is not None:
        return FollowUpStateResult("conflict")
    deleted_at = _aware(now)
    record.deleted_at = deleted_at
    record.deleted_by_user_id = _text(actor.get("user_id"))
    record.deleted_by_username = _text(actor.get("username"))
    record.deletion_reason = _text(reason)
    session.flush()

    round_row = session.get(ClueAssignmentRound, record.assignment_round_id)
    lead = session.get(ClueMasterLead, round_row.lead_key) if round_row is not None and round_row.lead_key else None
    if round_row is not None and lead is not None and _is_current_active_round(lead, round_row):
        _recalculate_active_round_summary(session, lead, round_row, deleted_at)
    elif round_row is not None:
        _recalculate_legacy_active_round_summary(session, round_row, deleted_at)
    session.flush()
    return FollowUpStateResult("ok", record, round_row.assignment_round_id if round_row is not None else None)


def can_reveal_current_order_phone(session: Session, *, order_id: str, actor: dict[str, Any]) -> bool:
    """Use the compatibility pointer only to locate the authoritative master-owned round."""

    center = session.get(ClueCenterOrder, order_id)
    if center is None or not center.current_assignment_round_id:
        return False
    round_row = session.get(ClueAssignmentRound, center.current_assignment_round_id)
    lead = session.get(ClueMasterLead, round_row.lead_key) if round_row is not None and round_row.lead_key else None
    if round_row is None or lead is None or not _is_current_active_round(lead, round_row):
        return False
    role = _text(actor.get("role"))
    if role == "admin":
        return True
    store_ids = {_text(store_id) for store_id in actor.get("store_ids") or ()}
    return role == "store" and bool(round_row.assigned_store_id and round_row.assigned_store_id in store_ids)


def _recalculate_active_round_summary(
    session: Session,
    lead: ClueMasterLead,
    round_row: ClueAssignmentRound,
    now: datetime,
) -> None:
    records = session.scalars(
        select(ClueFollowUpRecord)
        .where(ClueFollowUpRecord.assignment_round_id == round_row.assignment_round_id)
        .where(ClueFollowUpRecord.deleted_at.is_(None))
        .order_by(ClueFollowUpRecord.created_at, ClueFollowUpRecord.follow_up_record_id)
    ).all()
    latest = records[-1] if records else None
    if latest is None:
        round_row.followed_at = None
        round_row.follow_result = "pending"
        round_row.is_followed = False
        round_row.is_follow_success = False
        round_row.round_status = "active_unfollowed"
        round_row.protection_started_at = None
        round_row.protection_expires_at = None
    else:
        round_row.followed_at = latest.created_at
        round_row.follow_result = latest.follow_result
        round_row.is_followed = True
        round_row.is_follow_success = False
        round_row.round_status = "active_followed"
        first_protection = next((item for item in records if item.follow_result in PROTECTION_ACTIONS), None)
        if first_protection is None:
            round_row.protection_started_at = None
            round_row.protection_expires_at = None
        else:
            started_at = _aware(first_protection.created_at)
            round_row.protection_started_at = started_at
            round_row.protection_expires_at = started_at + timedelta(days=int(round_row.protection_days or 7))
    round_row.updated_at = now
    _project_current_round_summary(lead, round_row, session, now)


def _recalculate_legacy_active_round_summary(
    session: Session,
    round_row: ClueAssignmentRound,
    now: datetime,
) -> None:
    if round_row.round_status not in ACTIVE_ROUND_STATUSES:
        return
    records = session.scalars(
        select(ClueFollowUpRecord)
        .where(ClueFollowUpRecord.assignment_round_id == round_row.assignment_round_id)
        .where(ClueFollowUpRecord.deleted_at.is_(None))
        .order_by(ClueFollowUpRecord.created_at, ClueFollowUpRecord.follow_up_record_id)
    ).all()
    latest = records[-1] if records else None
    if latest is None:
        round_row.followed_at = None
        round_row.follow_result = "pending"
        round_row.is_followed = False
        round_row.is_follow_success = False
        round_row.round_status = "active_unfollowed"
        reassign_reason = None
    else:
        round_row.followed_at = latest.created_at
        round_row.follow_result = latest.follow_result
        round_row.is_followed = True
        round_row.is_follow_success = latest.follow_result == "success"
        round_row.round_status = "failed_pending_reassign" if latest.follow_result == "lost" else "active_followed"
        reassign_reason = "follow_lost" if latest.follow_result == "lost" else None
    round_row.reassign_reason = reassign_reason
    round_row.updated_at = now
    center = session.get(ClueCenterOrder, round_row.order_id)
    if center is not None and center.current_assignment_round_id == round_row.assignment_round_id:
        center.follow_result = round_row.follow_result
        center.is_followed = round_row.is_followed
        center.is_follow_success = round_row.is_follow_success
        center.current_round_status = round_row.round_status
        center.lead_status = "pending_reassign" if round_row.round_status == "failed_pending_reassign" else "active"
        center.reassign_reason = reassign_reason
        center.updated_at = now


def _close_and_allocate_next(
    lead: ClueMasterLead,
    round_row: ClueAssignmentRound,
    cause: str,
    now: datetime,
    session: Session,
    transition_key: str,
) -> None:
    reason_by_cause = {
        "lost": "follow_lost",
        "request_store_change": "request_store_change",
        "sla_expired": "first_sla_expired",
        "protection_expired": "protection_expired",
    }
    reason = reason_by_cause[cause]
    round_row.followed_at = now if cause in FOLLOW_UP_ACTIONS else round_row.followed_at
    round_row.follow_result = cause if cause in FOLLOW_UP_ACTIONS else round_row.follow_result
    round_row.is_followed = bool(round_row.followed_at)
    round_row.is_follow_success = False
    round_row.round_status = "closed_reassigned"
    round_row.terminal_reason = reason
    round_row.reassign_reason = reason
    round_row.reassigned_at = now
    round_row.matured_at = now
    round_row.updated_at = now
    lead.current_assignment_round_id = None
    lead.pool_location = None
    lead.allocation_state = "pending_reassign"
    lead.updated_at = now
    _project_closed_round(round_row, reason, session, now)
    session.flush()

    from apps.worker.clue_allocation_engine import allocate_lead

    allocate_lead(
        session,
        lead.lead_key,
        execution_mode=round_row.execution_mode,
        allocation_cycle_id=lead.allocation_cycle_id,
        actor="follow_up_state",
        now=now,
        start_after_strategy=round_row.strategy_type,
        transition_key=transition_key,
    )


def _project_closed_round(round_row: ClueAssignmentRound, reason: str, session: Session, now: datetime) -> None:
    center = session.get(ClueCenterOrder, round_row.order_id)
    if center is None or center.current_assignment_round_id != round_row.assignment_round_id:
        return
    center.follow_result = round_row.follow_result
    center.is_followed = round_row.is_followed
    center.is_follow_success = False
    center.current_round_status = round_row.round_status
    center.lead_status = "pending_reassign"
    center.reassign_reason = reason
    center.updated_at = now


def _apply_visible_summary(round_row: ClueAssignmentRound, action: str, now: datetime) -> None:
    round_row.followed_at = now
    round_row.follow_result = action
    round_row.is_followed = True
    round_row.is_follow_success = False
    round_row.round_status = "active_followed"
    round_row.updated_at = now
    if action in PROTECTION_ACTIONS and round_row.protection_started_at is None:
        protection_days = int(round_row.protection_days or 7)
        round_row.protection_started_at = now
        round_row.protection_expires_at = now + timedelta(days=protection_days)


def _project_current_round_summary(
    lead: ClueMasterLead,
    round_row: ClueAssignmentRound,
    session: Session,
    now: datetime,
) -> None:
    center = session.get(ClueCenterOrder, round_row.order_id)
    if center is None or center.current_assignment_round_id != round_row.assignment_round_id:
        return
    center.follow_result = round_row.follow_result
    center.is_followed = round_row.is_followed
    center.is_follow_success = round_row.is_follow_success
    center.current_round_status = round_row.round_status
    center.lead_status = "active"
    center.reassign_reason = None
    center.updated_at = now


def _close_for_terminal_order(
    lead: ClueMasterLead,
    round_row: ClueAssignmentRound,
    now: datetime,
    session: Session,
) -> None:
    verified = lead.normalized_order_status == "verified"
    round_row.round_status = "closed_order_verified" if verified else "closed_order_refunded"
    round_row.terminal_reason = "order_verified" if verified else "order_refunded"
    round_row.matured_at = now
    round_row.updated_at = now
    lead.lifecycle_status = "closed_verified" if verified else "closed_refunded"
    lead.pool_location = "closed"
    lead.allocation_state = "closed"
    lead.current_assignment_round_id = None
    lead.closed_at = now
    lead.closed_reason = round_row.terminal_reason
    lead.updated_at = now
    center = session.get(ClueCenterOrder, round_row.order_id)
    if center is not None and center.current_assignment_round_id == round_row.assignment_round_id:
        center.lead_status = "converted" if verified else "refunded"
        center.current_round_status = round_row.round_status
        center.reassign_reason = round_row.terminal_reason
        center.updated_at = now


def _is_current_active_round(lead: ClueMasterLead, round_row: ClueAssignmentRound) -> bool:
    return bool(
        round_row.execution_mode in SELF_OWNED_EXECUTION_MODES
        and lead.current_assignment_round_id == round_row.assignment_round_id
        and lead.lifecycle_status == "active"
        and lead.normalized_order_status == "active"
        and lead.pool_location == "store_follow_up_pool"
        and round_row.round_status in ACTIVE_ROUND_STATUSES
    )


def _actor_can_operate_round(round_row: ClueAssignmentRound | None, actor: dict[str, Any]) -> bool:
    role = _text(actor.get("role"))
    if role == "admin":
        return True
    if role != "store" or round_row is None:
        return False
    store_ids = {_text(store_id) for store_id in actor.get("store_ids") or ()}
    return bool(round_row.assigned_store_id and round_row.assigned_store_id in store_ids)


def _actor_is_highest_admin(actor: dict[str, Any]) -> bool:
    return bool(actor.get("is_highest_admin") and _text(actor.get("auth_type")) == "env_admin")


def _aware(value: datetime | None) -> datetime:
    result = value or datetime.now(timezone.utc)
    return result if result.tzinfo is not None else result.replace(tzinfo=timezone.utc)


def _text(value: Any) -> str | None:
    result = str(value or "").strip()
    return result or None
