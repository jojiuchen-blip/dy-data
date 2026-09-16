"""Backfill the KPI-only 24-hour start for the historical source-store fix."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from sqlalchemy import func, select, text

from apps.api.dy_api.db import make_engine, make_session_factory
from apps.api.dy_api.models import (
    ClueAllocationDecision,
    ClueAssignmentRound,
    ClueFollowUpRecord,
)


ACTOR = "source-store-historical-correction-20260916"
APPLY_CONFIRMATION = "BACKUP_COPIED_AND_HASH_VERIFIED"


class HistoricalMetricWindowError(RuntimeError):
    pass


def _json_value(value):
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def plan_updates(session, *, actor: str = ACTOR) -> list[dict[str, str | None]]:
    decisions = session.scalars(
        select(ClueAllocationDecision)
        .where(ClueAllocationDecision.actor == actor)
        .where(ClueAllocationDecision.decision_status == "selected")
        .order_by(ClueAllocationDecision.decision_id)
    ).all()
    updates: list[dict[str, str | None]] = []
    for decision in decisions:
        correction = (decision.decision_snapshot or {}).get("correction")
        before_round = correction.get("before_round") if isinstance(correction, dict) else None
        before_store_id = before_round.get("assigned_store_id") if isinstance(before_round, dict) else None
        if not before_round or before_store_id == decision.selected_store_id:
            continue
        if not decision.assignment_round_id or not decision.executed_at:
            raise HistoricalMetricWindowError(f"correction decision is incomplete: {decision.decision_id}")
        round_row = session.get(ClueAssignmentRound, decision.assignment_round_id)
        if round_row is None:
            raise HistoricalMetricWindowError(f"assignment round is missing: {decision.assignment_round_id}")
        if round_row.assigned_store_id != decision.selected_store_id:
            raise HistoricalMetricWindowError(f"assignment store changed after correction: {decision.decision_id}")
        if round_row.metric_follow_24h_start_at is not None:
            if round_row.metric_follow_24h_start_at == decision.executed_at:
                continue
            raise HistoricalMetricWindowError(f"metric window already has a different value: {decision.assignment_round_id}")
        prior_follow = session.scalar(
            select(ClueFollowUpRecord.follow_up_record_id)
            .where(ClueFollowUpRecord.order_id == decision.order_id)
            .where(ClueFollowUpRecord.created_at <= decision.executed_at)
            .limit(1)
        )
        if prior_follow is not None:
            raise HistoricalMetricWindowError(
                f"follow-up existed before correction: {decision.order_id}"
            )
        updates.append(
            {
                "decision_id": decision.decision_id,
                "assignment_round_id": decision.assignment_round_id,
                "order_id": decision.order_id,
                "metric_follow_24h_start_at": decision.executed_at.isoformat(),
                "before_store_id": before_store_id,
                "after_store_id": decision.selected_store_id,
            }
        )
    return updates


def apply_updates(session, updates: list[dict[str, str | None]]) -> int:
    for update in updates:
        row = session.get(ClueAssignmentRound, update["assignment_round_id"])
        if row is None:
            raise HistoricalMetricWindowError(f"assignment round is missing: {update['assignment_round_id']}")
        row.metric_follow_24h_start_at = datetime.fromisoformat(update["metric_follow_24h_start_at"])
    session.flush()
    return len(updates)


def _backup_payload(session, updates: list[dict[str, str | None]]) -> dict:
    rows = []
    for update in updates:
        row = session.get(ClueAssignmentRound, update["assignment_round_id"])
        rows.append(
            {
                "assignment_round_id": row.assignment_round_id,
                "order_id": row.order_id,
                "metric_follow_24h_start_at_before": None,
                "metric_follow_24h_start_at_after": update["metric_follow_24h_start_at"],
                "decision_id": update["decision_id"],
            }
        )
    return {"actor": ACTOR, "created_at": datetime.now(timezone.utc).isoformat(), "rows": rows}


def run(mode: str, *, backup_dir: Path) -> dict:
    if mode not in {"preview", "apply"}:
        raise ValueError("mode must be preview or apply")
    with make_session_factory(make_engine())() as session:
        session.execute(text("SET LOCAL lock_timeout='5s'"))
        session.execute(text("SET LOCAL statement_timeout='60s'"))
        session.execute(
            text(
                "LOCK TABLE clue_assignment_rounds, clue_allocation_decisions, "
                "clue_follow_up_records IN SHARE ROW EXCLUSIVE MODE"
            )
        )
        updates = plan_updates(session)
        payload = _backup_payload(session, updates)
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        backup_dir.mkdir(parents=True, exist_ok=True)
        path = backup_dir / f"historical-metric-window-{mode}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
        with path.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        result = {
            "mode": mode,
            "updates": len(updates),
            "backup": str(path),
            "sha256": sha256(data).hexdigest(),
        }
        if mode == "apply":
            # The production wrapper copies the fsynced backup out of the
            # container and verifies its hash before allowing the transaction
            # to commit.  Keeping this gate in the script prevents a partial
            # apply when the backup handoff was skipped.
            print(json.dumps({**result, "awaiting": APPLY_CONFIRMATION}, ensure_ascii=False), flush=True)
            if input().strip() != APPLY_CONFIRMATION:
                raise HistoricalMetricWindowError("backup copy/hash verification was not confirmed")
            apply_updates(session, updates)
            session.commit()
            result["committed"] = True
        else:
            session.rollback()
            result["rolled_back"] = True
        return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("preview", "apply"), required=True)
    parser.add_argument("--backup-dir", type=Path, default=Path("/tmp"))
    args = parser.parse_args()
    result = run(args.mode, backup_dir=args.backup_dir)
    if args.mode == "preview":
        print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
