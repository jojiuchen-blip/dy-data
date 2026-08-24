"""Recover pre-allocation clue rows into the current operable model.

This module intentionally keeps recovery separate from the normal collection
pipeline.  It is a bounded, explicitly invoked operation with a dry-run
default so an operator can inspect the impact before changing assignment
state.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from apps.api.dy_api.db import get_session_factory, session_scope
from apps.api.dy_api.models import (
    ClueAllocationAuditLog,
    ClueAllocationCycle,
    ClueAssignmentRound,
    ClueCenterOrder,
    ClueMasterLead,
)
from apps.worker.clue_allocation_engine import allocate_leads


ACTIVE_ROUND_STATUSES = ("active_unfollowed", "active_followed")
DEFAULT_BATCH_SIZE = 500
MAX_BATCH_SIZE = 500


def recover_legacy_batch(
    session: Session,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    dry_run: bool = True,
    actor: str = "legacy-recovery",
    now: datetime | None = None,
    after_round_id: str | None = None,
) -> dict[str, Any]:
    """Promote current legacy rounds in one bounded transaction.

    The existing assignment round identity is kept because these rows are
    pre-production data rather than historical business rounds.  The store,
    assignment timestamp and follow-up summary are preserved; only the
    execution namespace and current master projection are repaired.
    """

    batch_size = _validated_batch_size(batch_size)
    executed_at = _aware(now or datetime.now(timezone.utc))
    rows = _legacy_rows(session, batch_size=batch_size, after_round_id=after_round_id)
    if not rows:
        return {
            "scanned": 0,
            "eligible": 0,
            "migrated": 0,
            "has_more": False,
            "next_cursor": None,
            "dry_run": dry_run,
        }
    stats: Counter[str] = Counter()
    eligible: list[tuple[ClueAssignmentRound, ClueCenterOrder, ClueMasterLead]] = []

    lead_keys = [round_row.lead_key for round_row, _center in rows if round_row.lead_key]
    leads_by_key = {
        lead.lead_key: lead
        for lead in session.scalars(
            select(ClueMasterLead).where(ClueMasterLead.lead_key.in_(lead_keys))
        ).all()
    }

    for round_row, center_order in rows:
        stats["scanned"] += 1
        lead = leads_by_key.get(round_row.lead_key or "")
        if lead is None:
            stats["skipped_missing_lead"] += 1
            continue
        if lead.lifecycle_status != "active" or lead.normalized_order_status != "active":
            stats["skipped_terminal"] += 1
            continue
        if lead.pool_location == "headquarters_pool":
            stats["skipped_headquarters"] += 1
            continue
        if not _clean(round_row.assigned_store_id):
            stats["skipped_missing_store"] += 1
            continue
        if lead.current_assignment_round_id and lead.current_assignment_round_id != round_row.assignment_round_id:
            current_round = session.get(ClueAssignmentRound, lead.current_assignment_round_id)
            if current_round is not None and current_round.execution_mode in {"formal", "trial"}:
                stats["skipped_existing_self_owned_round"] += 1
                continue
        eligible.append((round_row, center_order, lead))

    stats["eligible"] = len(eligible)
    if not dry_run and eligible:
        cycle = _new_cycle(
            cycle_type="legacy_migration",
            execution_mode="formal",
            actor=actor,
            lead_keys=[lead.lead_key for _round, _center, lead in eligible],
            executed_at=executed_at,
            planned_impact={"auto_expiry_enabled": False},
        )
        session.add(cycle)
        session.flush()

        for round_row, center_order, lead in eligible:
            round_row.execution_mode = "formal"
            round_row.allocation_cycle_id = cycle.allocation_cycle_id
            round_row.auto_expiry_enabled = False
            round_row.first_follow_up_sla_hours = None
            round_row.first_sla_expires_at = None
            round_row.expires_at = None
            round_row.reassign_reason = None
            round_row.reassigned_at = None
            round_row.updated_at = executed_at

            lead.current_assignment_round_id = round_row.assignment_round_id
            lead.pool_location = "store_follow_up_pool"
            lead.allocation_state = "assigned"
            lead.allocation_cycle_id = cycle.allocation_cycle_id
            lead.ended_without_assignment = False
            lead.updated_at = executed_at

            center_order.lead_status = "active"
            center_order.current_assignment_round_id = round_row.assignment_round_id
            center_order.current_round_no = round_row.round_no
            center_order.current_round_status = round_row.round_status
            center_order.assigned_at = round_row.assigned_at
            center_order.assigned_store_id = round_row.assigned_store_id
            center_order.assigned_store_name = round_row.assigned_store_name
            center_order.follow_result = round_row.follow_result
            center_order.is_followed = round_row.is_followed
            center_order.is_follow_success = round_row.is_follow_success
            center_order.expires_at = None
            center_order.reassign_reason = None
            center_order.updated_at = executed_at

        cycle.status = "completed"
        cycle.actual_impact_json = {
            "migrated": len(eligible),
            "auto_expiry_enabled": False,
        }
        cycle.completed_at = executed_at
        cycle.executed_at = executed_at
        session.add(
            ClueAllocationAuditLog(
                audit_log_id=f"clue-recovery-{uuid4().hex}",
                event_type="legacy_migrated_to_formal",
                allocation_cycle_id=cycle.allocation_cycle_id,
                actor=actor,
                privileged_confirmation=True,
                before_snapshot={"execution_mode": "legacy", "count": len(eligible)},
                after_snapshot={"execution_mode": "formal", "count": len(eligible)},
                detail_json={"auto_expiry_enabled": False},
                created_at=executed_at,
            )
        )
        stats["migrated"] = len(eligible)
    elif dry_run:
        stats["migrated"] = 0

    return _finish_batch_stats(stats, rows, batch_size=batch_size)


def allocate_pending_batch(
    session: Session,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    dry_run: bool = True,
    actor: str = "pending-allocation-recovery",
    now: datetime | None = None,
    after_lead_key: str | None = None,
) -> dict[str, Any]:
    """Allocate a bounded batch of active leads with no current round."""

    batch_size = _validated_batch_size(batch_size)
    executed_at = _aware(now or datetime.now(timezone.utc))
    statement = (
        select(ClueMasterLead.lead_key)
        .where(ClueMasterLead.lifecycle_status == "active")
        .where(ClueMasterLead.normalized_order_status == "active")
        .where(ClueMasterLead.current_assignment_round_id.is_(None))
        .where(ClueMasterLead.allocation_state == "pending_allocation")
        .order_by(ClueMasterLead.lead_key)
        .limit(batch_size)
    )
    if after_lead_key:
        statement = statement.where(ClueMasterLead.lead_key > after_lead_key)
    lead_keys = list(session.scalars(statement.with_for_update()).all())
    if not lead_keys:
        return {
            "scanned": 0,
            "assigned": 0,
            "headquarters": 0,
            "skipped": 0,
            "total": 0,
            "has_more": False,
            "next_cursor": None,
            "dry_run": dry_run,
        }

    if dry_run:
        savepoint = session.begin_nested()
        try:
            results = allocate_leads(
                session,
                lead_keys,
                execution_mode="formal",
                actor=actor,
                now=executed_at,
                auto_expiry_enabled_override=False,
            )
        finally:
            savepoint.rollback()
            session.expire_all()
        result = _allocation_result_summary(results)
    else:
        cycle = _new_cycle(
            cycle_type="pending_recovery",
            execution_mode="formal",
            actor=actor,
            lead_keys=lead_keys,
            executed_at=executed_at,
            planned_impact={"auto_expiry_enabled": False},
        )
        session.add(cycle)
        session.flush()
        results = allocate_leads(
            session,
            lead_keys,
            execution_mode="formal",
            allocation_cycle_id=cycle.allocation_cycle_id,
            actor=actor,
            now=executed_at,
            auto_expiry_enabled_override=False,
        )
        result = _allocation_result_summary(results)
        cycle.status = "completed"
        cycle.actual_impact_json = result
        cycle.completed_at = executed_at
        cycle.executed_at = executed_at
        session.add(
            ClueAllocationAuditLog(
                audit_log_id=f"clue-recovery-{uuid4().hex}",
                event_type="pending_allocation_recovered",
                allocation_cycle_id=cycle.allocation_cycle_id,
                actor=actor,
                privileged_confirmation=True,
                before_snapshot={"allocation_state": "pending_allocation", "count": len(lead_keys)},
                after_snapshot={"summary": result},
                detail_json={"auto_expiry_enabled": False},
                created_at=executed_at,
            )
        )

    result.update(
        {
            "scanned": len(lead_keys),
            "next_cursor": lead_keys[-1],
            "has_more": len(lead_keys) == batch_size,
            "dry_run": dry_run,
        }
    )
    return result


def run_recovery(
    factory,
    *,
    mode: str = "all",
    batch_size: int = DEFAULT_BATCH_SIZE,
    dry_run: bool = True,
    actor: str = "clue-operability-recovery",
    limit: int | None = None,
) -> dict[str, Any]:
    """Run either recovery path with a fresh session per batch."""

    batch_size = _validated_batch_size(batch_size)
    if mode not in {"legacy", "pending", "all"}:
        raise ValueError("mode must be legacy, pending, or all")
    totals: Counter[str] = Counter()
    totals["dry_run"] = int(dry_run)
    remaining = limit

    if mode in {"legacy", "all"}:
        cursor = None
        while remaining is None or remaining > 0:
            current_batch_size = min(batch_size, remaining) if remaining else batch_size
            with session_scope(factory) as session:
                result = recover_legacy_batch(
                    session,
                    batch_size=current_batch_size,
                    dry_run=dry_run,
                    actor=actor,
                    after_round_id=cursor,
                )
            _merge_counts(totals, result)
            if not result["scanned"] or not result["has_more"]:
                break
            cursor = result["next_cursor"]
            if remaining is not None:
                remaining -= int(result["scanned"])

    if mode in {"pending", "all"}:
        cursor = None
        while remaining is None or remaining > 0:
            current_batch_size = min(batch_size, remaining) if remaining else batch_size
            with session_scope(factory) as session:
                result = allocate_pending_batch(
                    session,
                    batch_size=current_batch_size,
                    dry_run=dry_run,
                    actor=actor,
                    after_lead_key=cursor,
                )
            _merge_counts(totals, result)
            if not result["scanned"] or not result["has_more"]:
                break
            cursor = result["next_cursor"]
            if remaining is not None:
                remaining -= int(result["scanned"])

    return dict(totals)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Recover clue rows into the operable allocation model.")
    parser.add_argument("--mode", choices=("legacy", "pending", "all"), default="all")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--actor", default="clue-operability-recovery")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist changes. Without this flag the command performs a dry run.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    factory = get_session_factory()
    if factory is None:
        raise RuntimeError("Set DY_DATABASE_URL or DATABASE_URL before recovering clue operability.")
    result = run_recovery(
        factory,
        mode=args.mode,
        batch_size=args.batch_size,
        dry_run=not args.apply,
        actor=args.actor,
        limit=args.limit,
    )
    print("[clue-operability-recovery] " + json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
    return 0


def _legacy_rows(
    session: Session,
    *,
    batch_size: int,
    after_round_id: str | None,
) -> list[tuple[ClueAssignmentRound, ClueCenterOrder]]:
    statement = (
        select(ClueAssignmentRound, ClueCenterOrder)
        .join(
            ClueCenterOrder,
            and_(
                ClueCenterOrder.order_id == ClueAssignmentRound.order_id,
                ClueCenterOrder.current_assignment_round_id == ClueAssignmentRound.assignment_round_id,
            ),
        )
        .where(ClueAssignmentRound.execution_mode == "legacy")
        .where(ClueAssignmentRound.round_status.in_(ACTIVE_ROUND_STATUSES))
        .where(ClueCenterOrder.current_round_status.in_(ACTIVE_ROUND_STATUSES))
        .order_by(ClueAssignmentRound.assignment_round_id)
        .limit(batch_size)
    )
    if after_round_id:
        statement = statement.where(ClueAssignmentRound.assignment_round_id > after_round_id)
    return list(session.execute(statement.with_for_update()).all())


def _new_cycle(
    *,
    cycle_type: str,
    execution_mode: str,
    actor: str,
    lead_keys: list[str],
    executed_at: datetime,
    planned_impact: dict[str, Any],
) -> ClueAllocationCycle:
    return ClueAllocationCycle(
        allocation_cycle_id=f"allocation-cycle-{uuid4().hex}",
        cycle_type=cycle_type,
        execution_mode=execution_mode,
        status="running",
        selected_lead_keys=lead_keys,
        requested_lead_count=len(lead_keys),
        active_lead_count=len(lead_keys),
        planned_impact_json=planned_impact,
        actual_impact_json={},
        actor=actor,
        privileged_confirmation=True,
        created_at=executed_at,
        executed_at=executed_at,
    )


def _allocation_result_summary(results: list[Any]) -> dict[str, Any]:
    status_counts = Counter(result.status for result in results)
    reason_counts = Counter(result.reason for result in results if result.reason)
    return {
        "assigned": int(status_counts["assigned"]),
        "headquarters": int(status_counts["headquarters"]),
        "skipped": int(status_counts["skipped"]),
        "total": len(results),
        "reason_counts": dict(sorted(reason_counts.items())),
    }


def _finish_batch_stats(
    stats: Counter[str],
    rows: list[tuple[ClueAssignmentRound, ClueCenterOrder]],
    *,
    batch_size: int,
) -> dict[str, Any]:
    return {
        **dict(stats),
        "has_more": len(rows) == batch_size,
        "next_cursor": rows[-1][0].assignment_round_id if rows else None,
    }


def _merge_counts(total: Counter[str], result: dict[str, Any]) -> None:
    for key, value in result.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            total[key] += value
        elif key == "reason_counts" and isinstance(value, dict):
            for reason, count in value.items():
                total[f"reason:{reason}"] += int(count)


def _validated_batch_size(value: int) -> int:
    if value < 1 or value > MAX_BATCH_SIZE:
        raise ValueError(f"batch_size must be between 1 and {MAX_BATCH_SIZE}")
    return value


def _clean(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


if __name__ == "__main__":
    raise SystemExit(main())
