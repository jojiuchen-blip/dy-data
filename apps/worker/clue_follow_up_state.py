from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session
from apps.api.dy_api.clue_followup_metrics import load_terminal_evidence

from apps.api.dy_api.models import (
    ClueAllocationAuditLog, ClueAssignmentRound, ClueCenterOrder,
    ClueFollowUpRecord, ClueLeadRuleVersionBinding, ClueMasterLead,
)
from src.dy_data.clue_access import can_access_clue_store


BUSINESS_EXECUTION_MODE = "formal"
FOLLOW_UP_ACTIONS = {
    "appointment",
    "further_follow_up",
    "lost",
    "unreachable",
    "request_store_change",
}
PROTECTION_ACTIONS = {"appointment", "further_follow_up", "unreachable"}
ACTIVE_ROUND_STATUSES = {"active_unfollowed", "active_followed"}
TERMINAL_ORDER_STATUSES = {"verified", "refunded", "closed"}


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
    appointment_at: datetime | None = None,
    now: datetime | None = None,
) -> FollowUpStateResult:
    """Persist one follow-up action against the actual current self-owned round."""

    action = (follow_result or "").strip()
    if action not in FOLLOW_UP_ACTIONS:
        return FollowUpStateResult("conflict")
    round_row, lead = _locked_round_state(session, assignment_round_id)
    if round_row is None or round_row.order_id != order_id:
        return FollowUpStateResult("not_found")
    if lead is None:
        return FollowUpStateResult("conflict")
    if not _actor_can_operate_round(round_row, actor):
        return FollowUpStateResult("forbidden")
    executed_at = _aware(now)
    from apps.worker.clue_allocation import refresh_terminal_evidence_for_locked_lead

    if refresh_terminal_evidence_for_locked_lead(session, lead, now=executed_at):
        if _uses_product_follow_up(lead) and round_row.round_status not in ACTIVE_ROUND_STATUSES:
            round_row.closed_at = round_row.closed_at or lead.closed_at or executed_at
        return FollowUpStateResult("conflict")
    if lead.normalized_order_status in TERMINAL_ORDER_STATUSES:
        if not _is_current_self_owned_round(lead, round_row):
            return FollowUpStateResult("conflict")
        _close_for_terminal_order(lead, round_row, executed_at, session)
        session.flush()
        return FollowUpStateResult("conflict")
    if not _is_current_active_round(lead, round_row):
        return FollowUpStateResult("conflict")
    product_rule = _uses_product_follow_up(lead)
    if product_rule and action == "appointment":
        if appointment_at is None:
            return FollowUpStateResult("appointment_required")
        if not isinstance(appointment_at, datetime) or appointment_at.utcoffset() is None:
            return FollowUpStateResult("appointment_invalid")
    accepted_appointment_at = (
        _aware(appointment_at).astimezone(timezone.utc)
        if action == "appointment" and appointment_at else None
    )

    record = ClueFollowUpRecord(
        follow_up_record_id=uuid4().hex,
        order_id=order_id,
        assignment_round_id=round_row.assignment_round_id,
        round_no=round_row.round_no,
        assigned_store_id=round_row.assigned_store_id,
        follow_result=action,
        appointment_at=accepted_appointment_at,
        note=(note or "").strip() or None,
        operator_user_id=_text(actor.get("user_id")),
        operator_username=_text(actor.get("username")),
        created_at=executed_at,
    )
    session.add(record)
    if action in {"lost", "request_store_change"}:
        if product_rule:
            round_row.followed_at = executed_at
            round_row.follow_result = action
            round_row.appointment_at = None
            round_row.is_followed = True
            _close_product_round(lead, round_row, "follow_lost" if action == "lost" else action, executed_at, session)
        else:
            _close_for_reassignment(lead, round_row, action, executed_at, session)
        session.flush()
        return FollowUpStateResult("ok", record, None)
    if product_rule:
        _apply_product_summary(session, lead, round_row, action, accepted_appointment_at, executed_at)
    else:
        _apply_visible_summary(round_row, action, executed_at)
    _project_current_round_summary(lead, round_row, session, executed_at)
    session.flush()
    return FollowUpStateResult("ok", record, round_row.assignment_round_id)


def process_due_transitions(session: Session, *, now: datetime | None = None) -> dict[str, int]:
    """Preserve the bound legacy transition rules; product flow has its own worker."""

    processed_at = _aware(now)
    stats = {"sla_expired": 0, "protection_expired": 0, "terminal_closed": 0}
    round_refs = session.execute(
        select(ClueAssignmentRound.assignment_round_id, ClueAssignmentRound.order_id)
        .join(ClueMasterLead, ClueMasterLead.lead_key == ClueAssignmentRound.lead_key)
        .where(ClueMasterLead.routing_mode.is_(None))
        .where(ClueAssignmentRound.execution_mode == BUSINESS_EXECUTION_MODE)
        .where(ClueAssignmentRound.round_status.in_(ACTIVE_ROUND_STATUSES))
        .order_by(ClueAssignmentRound.lead_key, ClueAssignmentRound.assignment_round_id)
        .execution_options(autoflush=False)
    ).all()
    terminal_by_order = load_terminal_evidence(
        session, {order_id for _, order_id in round_refs}, observed_through=processed_at,
    )
    from apps.worker.clue_allocation import refresh_terminal_evidence_for_locked_lead

    for round_id, _ in round_refs:
        round_row, lead = _locked_round_state(session, round_id)
        if round_row is None or lead is None or not _is_current_self_owned_round(lead, round_row):
            continue
        if refresh_terminal_evidence_for_locked_lead(session, lead, now=processed_at,
                terminal=terminal_by_order.get(round_row.order_id)):
            stats["terminal_closed"] += 1
            continue
        if lead.normalized_order_status in TERMINAL_ORDER_STATUSES:
            _close_for_terminal_order(lead, round_row, processed_at, session)
            stats["terminal_closed"] += 1
            continue
        if not _is_current_active_round(lead, round_row):
            continue
        if not round_row.auto_expiry_enabled:
            continue
        sla_expires_at = round_row.first_sla_expires_at or round_row.expires_at
        if not round_row.is_followed and sla_expires_at is not None and _aware(sla_expires_at) <= processed_at:
            _close_for_reassignment(lead, round_row, "sla_expired", processed_at, session)
            stats["sla_expired"] += 1
            continue
        if round_row.protection_expires_at is not None and _aware(round_row.protection_expires_at) <= processed_at:
            _close_for_reassignment(
                lead,
                round_row,
                "protection_expired",
                processed_at,
                session,
            )
            stats["protection_expired"] += 1
    session.flush()
    return stats


def run_product_follow_up_batch(
    factory: Any,
    *,
    now: datetime | None = None,
    batch_size: int = 100,
) -> dict[str, int]:
    """Consume bounded due flow tasks, committing each handoff atomically.

    Master locks fence follow-up submissions, terminal reconciliation and other
    consumers. Failed handoffs roll back the old task as well. Updating only a
    failed task's attempt clock in a separate transaction rotates it behind
    untouched due tasks; the audit event records why it was retried.
    """

    processed_at = _aware(now)
    limit = max(1, min(int(batch_size), 200))
    stats = {key: 0 for key in (
        "processed", "sla_expired", "protection_expired", "terminal_closed",
        "assigned", "headquarters", "closed", "skipped", "failed",
    )}
    attempted: set[str] = set()
    for _ in range(limit):
        lead_key = round_id = None
        try:
            with factory() as session:
                lead = session.scalar(_due_product_lead_query(processed_at, attempted))
                if lead is None:
                    break
                lead_key = lead.lead_key
                round_id = lead.current_assignment_round_id
                attempted.add(lead_key)
                round_row = session.scalar(
                    select(ClueAssignmentRound)
                    .where(ClueAssignmentRound.assignment_round_id == round_id)
                    .with_for_update().execution_options(populate_existing=True, autoflush=False)
                )
                outcome, cause = _process_product_due_round(session, lead, round_row, processed_at)
                session.commit()
                stats["processed"] += 1
                stats[outcome] += 1
                if cause:
                    stats[cause] += 1
        except Exception as exc:
            stats["failed"] += 1
            if lead_key is None or round_id is None:
                # An infrastructure failure before selecting a task cannot be
                # attributed safely and must be visible to the supervisor.
                raise
            _record_product_transition_failure(factory, lead_key, round_id, processed_at, exc)
    return stats


def _due_product_lead_query(now: datetime, attempted: set[str]):
    first_deadline = func.coalesce(ClueAssignmentRound.first_sla_expires_at, ClueAssignmentRound.expires_at)
    due_at = case(
        (ClueAssignmentRound.is_followed.is_(False), first_deadline),
        else_=ClueAssignmentRound.protection_expires_at,
    )
    query = (
        select(ClueMasterLead)
        .join(ClueAssignmentRound, and_(
            ClueAssignmentRound.assignment_round_id == ClueMasterLead.current_assignment_round_id,
            ClueAssignmentRound.lead_key == ClueMasterLead.lead_key,
        ))
        .where(ClueMasterLead.routing_mode == "flow")
        .where(ClueMasterLead.lifecycle_status == "active")
        .where(ClueMasterLead.pool_location == "store_follow_up_pool")
        .where(ClueAssignmentRound.execution_mode == BUSINESS_EXECUTION_MODE)
        .where(ClueAssignmentRound.round_status.in_(ACTIVE_ROUND_STATUSES))
        .where(ClueAssignmentRound.auto_expiry_enabled.is_(True))
        .where(due_at <= now)
        .order_by(ClueAssignmentRound.updated_at, due_at, ClueMasterLead.lead_key)
        .limit(1)
        .with_for_update(of=ClueMasterLead, skip_locked=True)
        .execution_options(populate_existing=True, autoflush=False)
    )
    return query.where(ClueMasterLead.lead_key.not_in(attempted)) if attempted else query


def _process_product_due_round(
    session: Session,
    lead: ClueMasterLead,
    round_row: ClueAssignmentRound | None,
    now: datetime,
) -> tuple[str, str | None]:
    if (lead.routing_mode != "flow" or round_row is None
            or not _is_current_self_owned_round(lead, round_row)):
        return "skipped", None
    from apps.worker.clue_allocation import refresh_terminal_evidence_for_locked_lead

    # Read source evidence after acquiring the master lock, rather than reuse
    # a batch snapshot that may predate a waiting submit/terminal writer.
    if refresh_terminal_evidence_for_locked_lead(session, lead, now=now):
        if round_row.round_status not in ACTIVE_ROUND_STATUSES:
            round_row.closed_at = round_row.closed_at or lead.closed_at or now
        return "terminal_closed", None
    if lead.normalized_order_status in TERMINAL_ORDER_STATUSES:
        _close_for_terminal_order(lead, round_row, now, session)
        return "terminal_closed", None
    if not _is_current_active_round(lead, round_row) or not round_row.auto_expiry_enabled:
        return "skipped", None
    cause = _product_due_cause(round_row, now)
    if cause is None:
        return "skipped", None
    policy = _product_follow_up_policy(session, lead)
    action_key = "pending_action" if cause == "sla_expired" else f"{round_row.follow_result}_action"
    action = policy.get(action_key, "close")
    if action != "next" or int(round_row.round_no) >= 2:
        reason = "first_sla_expired" if cause == "sla_expired" else "protection_expired"
        _close_product_round(lead, round_row, reason, now, session)
        return "closed", cause
    _close_for_reassignment(lead, round_row, cause, now, session)
    # The old active row is written before allocation can create a new task.
    session.flush()
    from apps.worker.clue_allocation_engine import continue_product_routing

    result = continue_product_routing(
        session, lead.lead_key, now=now,
        transition_key=f"follow-up-due:{round_row.assignment_round_id}:{cause}",
    )
    if result.status not in {"assigned", "headquarters", "closed"}:
        raise RuntimeError("product continuation did not resolve the expired task")
    return result.status, cause


def _record_product_transition_failure(
    factory: Any, lead_key: str, round_id: str, now: datetime, error: Exception,
) -> None:
    with factory() as session:
        lead = session.scalar(
            select(ClueMasterLead).where(ClueMasterLead.lead_key == lead_key)
            .with_for_update(skip_locked=True).execution_options(populate_existing=True)
        )
        if lead is None or lead.routing_mode != "flow" or lead.current_assignment_round_id != round_id:
            return
        round_row = session.scalar(
            select(ClueAssignmentRound).where(ClueAssignmentRound.assignment_round_id == round_id)
            .with_for_update().execution_options(populate_existing=True)
        )
        if round_row is None or not _is_current_active_round(lead, round_row):
            return
        round_row.updated_at = now
        session.add(ClueAllocationAuditLog(
            audit_log_id=f"follow-up-due-{uuid4().hex}",
            event_type="product_follow_up_transition_failed", actor="product_follow_up_worker",
            result_status="failed", reason_code="continuation_failed",
            detail_json={"lead_key": lead_key, "assignment_round_id": round_id, "error_type": type(error).__name__},
            created_at=now,
        ))
        session.commit()


def _product_due_cause(round_row: ClueAssignmentRound, now: datetime) -> str | None:
    if not round_row.is_followed:
        deadline = round_row.first_sla_expires_at or round_row.expires_at
        return "sla_expired" if deadline is not None and _aware(deadline) <= now else None
    deadline = round_row.protection_expires_at
    return "protection_expired" if deadline is not None and _aware(deadline) <= now else None


def _uses_product_follow_up(lead: ClueMasterLead) -> bool:
    return lead.routing_mode is not None


def _product_follow_up_policy(session: Session, lead: ClueMasterLead) -> dict[str, Any]:
    policy: dict[str, Any] = {
        "appointment_hours": 72, "further_follow_up_hours": 168, "unreachable_hours": 168,
        "pending_action": "next", "appointment_action": "next",
        "further_follow_up_action": "next", "unreachable_action": "close",
    }
    binding = session.get(ClueLeadRuleVersionBinding, lead.lead_key)
    snapshot = binding.rule_version_snapshot if binding is not None else {}
    configured = snapshot.get("follow_up_policy", {}) if isinstance(snapshot, dict) else {}
    if isinstance(configured, dict):
        policy.update(configured)
    return policy


def _apply_product_summary(
    session: Session, lead: ClueMasterLead, round_row: ClueAssignmentRound,
    action: str, appointment_at: datetime | None, now: datetime,
) -> None:
    changed = round_row.follow_result != action
    if action == "appointment":
        previous = round_row.appointment_at
        changed = changed or previous is None or _aware(previous) != appointment_at
    round_row.followed_at = now
    round_row.follow_result = action
    round_row.appointment_at = appointment_at
    round_row.is_followed = True
    round_row.is_follow_success = action in PROTECTION_ACTIONS
    round_row.round_status = "active_followed"
    round_row.updated_at = now
    if changed:
        policy = _product_follow_up_policy(session, lead)
        base = appointment_at if action == "appointment" else now
        round_row.protection_started_at = now
        round_row.protection_expires_at = base + timedelta(hours=int(policy[f"{action}_hours"]))
        round_row.expires_at = round_row.protection_expires_at


def _close_product_round(
    lead: ClueMasterLead, round_row: ClueAssignmentRound, reason: str,
    now: datetime, session: Session,
) -> None:
    round_row.round_status = {
        "follow_lost": "closed_follow_lost", "request_store_change": "closed_store_change",
    }.get(reason, "closed_follow_up_expired")
    round_row.terminal_reason = reason
    round_row.reassign_reason = reason
    round_row.closed_at = round_row.closed_at or now
    round_row.matured_at = round_row.closed_at
    round_row.is_follow_success = False
    round_row.updated_at = now
    lead.current_assignment_round_id = None
    lead.lifecycle_status = "closed_order"
    lead.pool_location = "closed"
    lead.allocation_state = "closed"
    lead.closed_at = lead.closed_at or now
    lead.closed_reason = reason
    lead.updated_at = now
    center = _locked_center(session, round_row.order_id)
    if center is not None and center.current_assignment_round_id == round_row.assignment_round_id:
        center.lead_status = "closed"
        center.current_round_status = round_row.round_status
        center.follow_result = round_row.follow_result
        center.is_followed = round_row.is_followed
        center.is_follow_success = False
        center.reassign_reason = reason
        center.updated_at = now


def soft_delete_follow_up_record(
    session: Session,
    *,
    follow_up_record_id: str,
    actor: dict[str, Any],
    reason: str | None,
    now: datetime | None = None,
) -> FollowUpStateResult:
    """Audit-reverse one follow-up record without reopening a past transition."""

    if _text(actor.get("role")) not in {"admin", "highest_admin"}:
        return FollowUpStateResult("forbidden")
    round_id = session.scalar(
        select(ClueFollowUpRecord.assignment_round_id)
        .where(ClueFollowUpRecord.follow_up_record_id == follow_up_record_id)
        .execution_options(autoflush=False)
    )
    if round_id is None:
        return FollowUpStateResult("not_found")
    round_row, lead = _locked_round_state(session, round_id)
    if round_row is None or not can_access_clue_store(actor, round_row.assigned_store_id):
        return FollowUpStateResult("not_found")
    if round_row.execution_mode != BUSINESS_EXECUTION_MODE:
        return FollowUpStateResult("conflict")
    if lead is not None and _uses_product_follow_up(lead):
        return FollowUpStateResult("immutable")
    record = session.scalar(
        select(ClueFollowUpRecord)
        .where(ClueFollowUpRecord.follow_up_record_id == follow_up_record_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if record is None:
        return FollowUpStateResult("not_found")
    if record.deleted_at is not None or record.assignment_round_id != round_id:
        return FollowUpStateResult("conflict")
    deleted_at = _aware(now)
    record.deleted_at = deleted_at
    record.deleted_by_user_id = _text(actor.get("user_id"))
    record.deleted_by_username = _text(actor.get("username"))
    record.deletion_reason = _text(reason)
    session.flush()

    if round_row is not None and lead is not None and _is_current_active_round(lead, round_row):
        _recalculate_active_round_summary(session, lead, round_row, deleted_at)
    elif round_row is not None:
        _recalculate_detached_round_summary(session, round_row, deleted_at)
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
    return _actor_can_operate_round(round_row, actor)


def _locked_round_state(
    session: Session, assignment_round_id: str,
) -> tuple[ClueAssignmentRound | None, ClueMasterLead | None]:
    """Lock master then round and replace cached ORM state before validation."""
    with session.no_autoflush:
        lead_key = session.scalar(
            select(ClueAssignmentRound.lead_key)
            .where(ClueAssignmentRound.assignment_round_id == assignment_round_id)
        )
        lead = None
        if lead_key:
            lead = session.scalar(
                select(ClueMasterLead).where(ClueMasterLead.lead_key == lead_key)
                .with_for_update().execution_options(populate_existing=True)
            )
        round_row = session.scalar(
            select(ClueAssignmentRound)
            .where(ClueAssignmentRound.assignment_round_id == assignment_round_id)
            .with_for_update().execution_options(populate_existing=True)
        )
        if round_row is not None and round_row.lead_key != lead_key:
            return round_row, None
        return round_row, lead


def _locked_center(session: Session, order_id: str) -> ClueCenterOrder | None:
    """Lock the compatibility projection only after its master and round."""
    return session.scalar(
        select(ClueCenterOrder).where(ClueCenterOrder.order_id == order_id)
        .with_for_update().execution_options(populate_existing=True, autoflush=False)
    )


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
        round_row.is_follow_success = latest.follow_result in PROTECTION_ACTIONS
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


def _recalculate_detached_round_summary(
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
        round_row.is_follow_success = latest.follow_result in (PROTECTION_ACTIONS | {"success"})
        should_reassign = latest.follow_result in {"lost", "request_store_change"}
        round_row.round_status = "failed_pending_reassign" if should_reassign else "active_followed"
        reassign_reason = (
            "follow_lost"
            if latest.follow_result == "lost"
            else "request_store_change"
            if latest.follow_result == "request_store_change"
            else None
        )
    round_row.reassign_reason = reassign_reason
    round_row.updated_at = now
    center = _locked_center(session, round_row.order_id)
    if center is not None and center.current_assignment_round_id == round_row.assignment_round_id:
        center.follow_result = round_row.follow_result
        center.is_followed = round_row.is_followed
        center.is_follow_success = round_row.is_follow_success
        center.current_round_status = round_row.round_status
        center.lead_status = "pending_reassign" if round_row.round_status == "failed_pending_reassign" else "active"
        center.reassign_reason = reassign_reason
        center.updated_at = now


def _close_for_reassignment(
    lead: ClueMasterLead,
    round_row: ClueAssignmentRound,
    cause: str,
    now: datetime,
    session: Session,
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
    round_row.closed_at = round_row.closed_at or now
    round_row.matured_at = now
    round_row.updated_at = now
    lead.current_assignment_round_id = None
    lead.pool_location = None
    lead.allocation_state = "pending_reassign"
    lead.updated_at = now
    _project_closed_round(round_row, reason, session, now)
    session.flush()


def _project_closed_round(round_row: ClueAssignmentRound, reason: str, session: Session, now: datetime) -> None:
    center = _locked_center(session, round_row.order_id)
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
    round_row.is_follow_success = action in PROTECTION_ACTIONS
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
    center = _locked_center(session, round_row.order_id)
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
    refunded = lead.normalized_order_status == "refunded"
    round_row.round_status = (
        "closed_order_verified"
        if verified
        else "closed_order_refunded"
        if refunded
        else "closed_order_closed"
    )
    round_row.terminal_reason = (
        "order_verified" if verified else "order_refunded" if refunded else "order_closed"
    )
    closed_at = _aware(lead.closed_at) if lead.closed_at is not None else now
    round_row.closed_at = round_row.closed_at or closed_at
    round_row.matured_at = closed_at
    round_row.updated_at = now
    lead.lifecycle_status = "closed_verified" if verified else "closed_refunded" if refunded else "closed_order"
    lead.pool_location = "closed"
    lead.allocation_state = "closed"
    lead.current_assignment_round_id = None
    lead.closed_at = closed_at
    lead.closed_reason = round_row.terminal_reason
    lead.updated_at = now
    center = _locked_center(session, round_row.order_id)
    if center is not None and center.current_assignment_round_id == round_row.assignment_round_id:
        center.lead_status = "converted" if verified else "refunded" if refunded else "closed"
        center.current_round_status = round_row.round_status
        center.reassign_reason = round_row.terminal_reason
        center.updated_at = now


def _is_current_active_round(lead: ClueMasterLead, round_row: ClueAssignmentRound) -> bool:
    return bool(
        _is_current_self_owned_round(lead, round_row)
        and lead.lifecycle_status == "active"
        and lead.normalized_order_status == "active"
        and lead.pool_location == "store_follow_up_pool"
        and round_row.round_status in ACTIVE_ROUND_STATUSES
    )


def _is_current_self_owned_round(lead: ClueMasterLead, round_row: ClueAssignmentRound) -> bool:
    return bool(
        round_row.execution_mode == BUSINESS_EXECUTION_MODE
        and lead.current_assignment_round_id == round_row.assignment_round_id
    )


def _actor_can_operate_round(round_row: ClueAssignmentRound | None, actor: dict[str, Any]) -> bool:
    return round_row is not None and can_access_clue_store(actor, round_row.assigned_store_id)


def _aware(value: datetime | None) -> datetime:
    result = value or datetime.now(timezone.utc)
    return result if result.tzinfo is not None else result.replace(tzinfo=timezone.utc)


def _text(value: Any) -> str | None:
    result = str(value or "").strip()
    return result or None
