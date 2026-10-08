"""Preview or repair terminal clue state in bounded, restartable transactions.

Default mode rolls every page back. --apply is explicit; this script never
allocates rounds, creates follow-ups, or deletes historical records.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select, func

from apps.api.dy_api.db import get_session_factory
from apps.api.dy_api.models import ClueMasterLead, ClueAssignmentRound, ClueCenterOrder
from apps.worker.clue_allocation import refresh_terminal_evidence_for_locked_lead
from apps.api.dy_api.clue_followup_metrics import load_terminal_evidence, TerminalEvidence
from datetime import datetime, timezone


def _utc(value):
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def repair_terminal_states(session_factory, *, apply=False, batch_size=100,
                           max_batches=20, after="", order_ids=None, on_batch=None):
    """Reconcile existing masters; return a cursor suitable for the next run."""
    if not 1 <= batch_size <= 500 or max_batches < 1:
        raise ValueError("batch_size must be 1..500 and max_batches positive")
    totals = {"dry_run": not apply, "scanned": 0, "changed_masters": 0,
              "changed_rounds": 0, "changed_centers": 0, "batches": 0, "after": after}
    with session_factory() as session:
        upper = session.scalar(select(func.max(ClueMasterLead.lead_key))) or ""
    for _ in range(max_batches):
        with session_factory() as session:
            query = select(ClueMasterLead).where(
                ClueMasterLead.lead_key > totals["after"], ClueMasterLead.lead_key <= upper,
                ClueMasterLead.order_id.is_not(None),
            ).order_by(ClueMasterLead.lead_key).limit(batch_size)
            if order_ids:
                query = query.where(ClueMasterLead.order_id.in_(tuple(order_ids)))
            leads = list(session.scalars(query))
            if not leads:
                totals["complete"] = True
                break
            ids = {row.order_id for row in leads}
            def snapshot():
                masters = {r.lead_key: (r.lifecycle_status, r.pool_location, r.allocation_state, _utc(r.closed_at),
                        r.normalized_order_status, r.raw_order_status, r.status_source, r.closed_reason, r.ended_without_assignment)
                    for r in session.scalars(select(ClueMasterLead).where(ClueMasterLead.order_id.in_(ids)))}
                rounds = {r.assignment_round_id: (r.round_status, r.terminal_reason, _utc(r.matured_at))
                    for r in session.scalars(select(ClueAssignmentRound).where(ClueAssignmentRound.order_id.in_(ids)))}
                centers = {r.order_id: (r.lead_status, r.current_round_status)
                    for r in session.scalars(select(ClueCenterOrder).where(ClueCenterOrder.order_id.in_(ids)))}
                return masters, rounds, centers
            before = snapshot()
            # Lock masters before their rounds/centers, matching online writers.
            locked = list(session.scalars(select(ClueMasterLead).where(
                ClueMasterLead.lead_key.in_([row.lead_key for row in leads])
            ).order_by(ClueMasterLead.lead_key).with_for_update().execution_options(populate_existing=True)))
            now = datetime.now(timezone.utc)
            evidence = load_terminal_evidence(session, ids, observed_through=now)
            for lead in locked:
                terminal = evidence.get(lead.order_id)
                if (terminal is None or not terminal.is_terminal) and lead.normalized_order_status in {"verified", "refunded", "closed"}:
                    terminal = TerminalEvidence(lead.normalized_order_status, lead.closed_at,
                        lead.order_status_observed_at, lead.status_source)
                if terminal is not None and terminal.is_terminal:
                    refresh_terminal_evidence_for_locked_lead(session, lead, now=now, terminal=terminal)
            session.flush()
            after_state = snapshot()
            page = {"scanned": len(leads), "after": leads[-1].lead_key}
            for index, name in enumerate(("changed_masters", "changed_rounds", "changed_centers")):
                page[name] = sum(value != before[index].get(key) for key, value in after_state[index].items())
            # Capture scalars before commit expires ORM rows, or rollback undoes them.
            if apply:
                session.commit()
            else:
                session.rollback()
            for name in ("scanned", "changed_masters", "changed_rounds", "changed_centers"):
                totals[name] += page[name]
            totals["after"] = page["after"]
            totals["batches"] += 1
            if on_batch:
                on_batch({**page, "dry_run": not apply})
    totals.setdefault("complete", False)
    return totals


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--max-batches", type=int, default=20)
    parser.add_argument("--after", default="")
    parser.add_argument("--order-id", action="append", default=[])
    args = parser.parse_args()
    factory = get_session_factory()
    if factory is None:
        raise RuntimeError("Database is not configured")
    result = repair_terminal_states(factory, apply=args.apply, batch_size=args.batch_size,
        max_batches=args.max_batches, after=args.after, order_ids=args.order_id,
        on_batch=lambda page: print(json.dumps(page, ensure_ascii=False), flush=True))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
