"""Read-only preflight for retiring pre-production legacy clue rounds.

The actual namespace conversion is owned by Alembic revision 20260831_0046 so
it is atomic with the schema constraint that prevents legacy writes from
returning. This command only reports blockers and never mutates business data.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.dy_api.db import get_session_factory, session_scope
from apps.api.dy_api.models import (
    ClueAssignmentRound,
    ClueCenterOrder,
    ClueFollowUpRecord,
    ClueMasterLead,
)


ACTIVE_ROUND_STATUSES = ("active_unfollowed", "active_followed")
ALLOWED_EXECUTION_MODES = ("legacy", "formal", "trial")
DEFAULT_BATCH_SIZE = 500
MAX_BATCH_SIZE = 500
MAX_SAMPLE_IDS = 20


def inspect_legacy_batch(
    session: Session,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    after_round_id: str | None = None,
    include_global_blockers: bool = True,
) -> dict[str, Any]:
    """Inspect one bounded legacy batch without acquiring write locks."""

    batch_size = _validated_batch_size(batch_size)
    statement = (
        select(ClueAssignmentRound)
        .where(ClueAssignmentRound.execution_mode == "legacy")
        .order_by(ClueAssignmentRound.assignment_round_id)
        .limit(batch_size)
    )
    if after_round_id:
        statement = statement.where(ClueAssignmentRound.assignment_round_id > after_round_id)
    rounds = list(session.scalars(statement).all())
    stats: Counter[str] = Counter()
    samples: dict[str, list[str]] = defaultdict(list)

    if include_global_blockers:
        global_stats, global_samples = _global_migration_blockers(session)
        stats.update(global_stats)
        samples.update(global_samples)

    for round_row in rounds:
        stats["scanned"] += 1
        blockers = _round_blockers(session, round_row)
        if blockers:
            stats["blocked"] += 1
            for blocker in blockers:
                stats[blocker] += 1
                if len(samples[blocker]) < MAX_SAMPLE_IDS:
                    samples[blocker].append(round_row.assignment_round_id)
        else:
            stats["ready"] += 1

    result = {
        **dict(stats),
        "has_more": len(rounds) == batch_size,
        "next_cursor": rounds[-1].assignment_round_id if rounds else None,
        "samples": dict(samples),
        "read_only": True,
    }
    result["migration_blocked"] = bool(result.get("blocked") or result.get("global_blocked"))
    return result


def recover_legacy_batch(
    session: Session,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    dry_run: bool = True,
    actor: str = "legacy-retirement-preflight",
    now: Any | None = None,
    after_round_id: str | None = None,
) -> dict[str, Any]:
    """Compatibility wrapper retained for callers of the former recovery tool."""

    del actor, now
    if not dry_run:
        raise RuntimeError(
            "legacy write recovery is retired; run the read-only preflight, then "
            "apply Alembic revision 20260831_0046"
        )
    return inspect_legacy_batch(
        session,
        batch_size=batch_size,
        after_round_id=after_round_id,
    )


def run_preflight(
    factory,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    limit: int | None = None,
) -> dict[str, Any]:
    """Inspect all legacy rounds with a fresh read session per bounded batch."""

    batch_size = _validated_batch_size(batch_size)
    totals: Counter[str] = Counter()
    samples: dict[str, list[str]] = defaultdict(list)
    remaining = limit
    cursor = None
    first_batch = True

    while remaining is None or remaining > 0:
        current_batch_size = min(batch_size, remaining) if remaining else batch_size
        with session_scope(factory) as session:
            result = inspect_legacy_batch(
                session,
                batch_size=current_batch_size,
                after_round_id=cursor,
                include_global_blockers=first_batch,
            )
        first_batch = False
        for key, value in result.items():
            if isinstance(value, int) and not isinstance(value, bool):
                totals[key] += value
        for key, values in result.get("samples", {}).items():
            for value in values:
                if len(samples[key]) < MAX_SAMPLE_IDS:
                    samples[key].append(value)
        if not result.get("scanned") or not result["has_more"]:
            break
        cursor = result["next_cursor"]
        if remaining is not None:
            remaining -= int(result["scanned"])

    result = {
        **dict(totals),
        "samples": dict(samples),
        "read_only": True,
        "migration_revision": "20260831_0046",
    }
    result["migration_blocked"] = bool(result.get("blocked") or result.get("global_blocked"))
    return result


def run_recovery(
    factory,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    dry_run: bool = True,
    actor: str = "legacy-retirement-preflight",
    limit: int | None = None,
) -> dict[str, Any]:
    del actor
    if not dry_run:
        raise RuntimeError("legacy write recovery is retired; only read-only preflight is supported")
    return run_preflight(factory, batch_size=batch_size, limit=limit)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect legacy clue rounds before Alembic revision 20260831_0046."
    )
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--limit", type=int, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    factory = get_session_factory()
    if factory is None:
        raise RuntimeError("Set DY_DATABASE_URL or DATABASE_URL before inspecting legacy rounds.")
    result = run_preflight(
        factory,
        batch_size=args.batch_size,
        limit=args.limit,
    )
    print(
        "[clue-legacy-retirement-preflight] "
        + json.dumps(result, ensure_ascii=False, sort_keys=True),
        flush=True,
    )
    return 1 if result.get("migration_blocked") else 0


def _global_migration_blockers(
    session: Session,
) -> tuple[Counter[str], dict[str, list[str]]]:
    """Mirror the migration-wide guards that are not attributable to one batch row."""

    samples: dict[str, list[str]] = {}
    unknown_modes = list(
        session.scalars(
            select(ClueAssignmentRound.assignment_round_id)
            .where(ClueAssignmentRound.execution_mode.not_in(ALLOWED_EXECUTION_MODES))
            .order_by(ClueAssignmentRound.assignment_round_id)
            .limit(MAX_SAMPLE_IDS)
        ).all()
    )
    duplicate_active = list(
        session.scalars(
            select(func.min(ClueAssignmentRound.assignment_round_id))
            .where(ClueAssignmentRound.execution_mode == "legacy")
            .where(ClueAssignmentRound.round_status.in_(ACTIVE_ROUND_STATUSES))
            .where(ClueAssignmentRound.lead_key.is_not(None))
            .group_by(ClueAssignmentRound.lead_key)
            .having(func.count() > 1)
            .order_by(func.min(ClueAssignmentRound.assignment_round_id))
            .limit(MAX_SAMPLE_IDS)
        ).all()
    )
    inconsistent_records = list(
        session.scalars(
            select(ClueFollowUpRecord.follow_up_record_id)
            .outerjoin(
                ClueAssignmentRound,
                ClueAssignmentRound.assignment_round_id
                == ClueFollowUpRecord.assignment_round_id,
            )
            .where(
                (ClueAssignmentRound.assignment_round_id.is_(None))
                | (ClueFollowUpRecord.order_id != ClueAssignmentRound.order_id)
                | (ClueFollowUpRecord.round_no != ClueAssignmentRound.round_no)
                | (
                    func.coalesce(ClueFollowUpRecord.assigned_store_id, "")
                    != func.coalesce(ClueAssignmentRound.assigned_store_id, "")
                )
            )
            .order_by(ClueFollowUpRecord.follow_up_record_id)
            .limit(MAX_SAMPLE_IDS)
        ).all()
    )

    for key, values in (
        ("unknown_execution_mode", unknown_modes),
        ("duplicate_active_legacy_round", duplicate_active),
        ("inconsistent_follow_up_record", inconsistent_records),
    ):
        if values:
            samples[key] = [str(value) for value in values]

    stats: Counter[str] = Counter({key: len(values) for key, values in samples.items()})
    stats["global_blocked"] = sum(stats.values())
    return stats, samples


def _round_blockers(session: Session, round_row: ClueAssignmentRound) -> list[str]:
    blockers: list[str] = []
    if round_row.lead_key:
        formal_collision = session.scalar(
            select(ClueAssignmentRound.assignment_round_id)
            .where(ClueAssignmentRound.lead_key == round_row.lead_key)
            .where(ClueAssignmentRound.round_no == round_row.round_no)
            .where(ClueAssignmentRound.execution_mode == "formal")
            .limit(1)
        )
        if formal_collision:
            blockers.append("formal_namespace_collision")

    if round_row.round_status not in ACTIVE_ROUND_STATUSES:
        return blockers

    if not round_row.lead_key:
        blockers.append("active_missing_lead_key")
        return blockers
    if not (round_row.assigned_store_id or "").strip():
        blockers.append("active_missing_store")

    lead = session.get(ClueMasterLead, round_row.lead_key)
    if lead is None:
        blockers.append("active_missing_master_lead")
    else:
        if lead.order_id != round_row.order_id:
            blockers.append("active_master_order_mismatch")
        if lead.current_assignment_round_id != round_row.assignment_round_id:
            blockers.append("active_master_pointer_mismatch")
        if (
            lead.lifecycle_status != "active"
            or lead.normalized_order_status != "active"
            or lead.pool_location != "store_follow_up_pool"
            or lead.allocation_state != "assigned"
        ):
            blockers.append("active_master_state_mismatch")

    center_pointer = session.scalar(
        select(ClueCenterOrder.order_id)
        .where(ClueCenterOrder.order_id == round_row.order_id)
        .where(ClueCenterOrder.current_assignment_round_id == round_row.assignment_round_id)
        .limit(1)
    )
    if center_pointer is None:
        blockers.append("active_center_pointer_mismatch")
    return blockers


def _validated_batch_size(value: int) -> int:
    if value < 1 or value > MAX_BATCH_SIZE:
        raise ValueError(f"batch_size must be between 1 and {MAX_BATCH_SIZE}")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
