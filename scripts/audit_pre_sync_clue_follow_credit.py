"""Preview the impact of DYDATA-122 with a read-only database session."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
import json

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from apps.api.dy_api.clue_task_metrics import (
    PRE_SYNC_FOLLOW_FROM, SHANGHAI, load_clue_task_facts,
)
from apps.api.dy_api.db import get_session_factory
from apps.api.dy_api.models import ClueAssignmentRound


def audit(session: Session, *, start: datetime, end: datetime, cutoff: datetime, store_id: str | None) -> dict:
    scope = (
        ClueAssignmentRound.execution_mode == "formal",
        ClueAssignmentRound.assigned_at >= start,
        ClueAssignmentRound.assigned_at < end,
        ClueAssignmentRound.assigned_at <= cutoff,
    )
    if store_id:
        scope += (ClueAssignmentRound.assigned_store_id == store_id,)
    totals: defaultdict[str, Counter] = defaultdict(Counter)
    cursor = ""
    while True:
        order_ids = tuple(session.scalars(
            select(ClueAssignmentRound.order_id).distinct()
            .where(*scope, ClueAssignmentRound.order_id > cursor)
            .order_by(ClueAssignmentRound.order_id).limit(200)
        ))
        if not order_ids:
            break
        facts = load_clue_task_facts(session, order_ids, observed_through=cutoff)
        for fact in facts.values():
            if not start <= fact.assigned_at < end or (store_id and fact.store_id != store_id):
                continue
            row = totals[fact.store_id]
            row["denominator"] += fact.follow_denominator
            row["after_24h"] += fact.follow_24h_numerator
            row["after_any"] += fact.follow_any_numerator
            row["credited"] += int(fact.reason_code == "pre_sync_follow_credited")
            row["missing_observation"] += int(fact.reason_code == "pre_sync_observation_missing")
        cursor = order_ids[-1]
    return {
        "mode": "read_only",
        "start_inclusive": start.isoformat(),
        "end_exclusive": end.isoformat(),
        "observed_through": cutoff.isoformat(),
        "stores_examined": len(totals),
        "credited": sum(row["credited"] for row in totals.values()),
        "missing_observation": sum(row["missing_observation"] for row in totals.values()),
        "stores": [
            {"store_id": store, "follow_denominator": row["denominator"],
             "before_24h": row["after_24h"] - row["credited"], "after_24h": row["after_24h"],
             "before_any": row["after_any"] - row["credited"], "after_any": row["after_any"],
             "credited": row["credited"], "missing_observation": row["missing_observation"]}
            for store, row in sorted(totals.items()) if row["credited"] or row["missing_observation"] or store_id
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, default=PRE_SYNC_FOLLOW_FROM.date())
    parser.add_argument("--end", type=date.fromisoformat, default=datetime.now(SHANGHAI).date(),
                        help="Inclusive end date in Asia/Shanghai.")
    parser.add_argument("--store-id", help="Optional exact internal store ID.")
    args = parser.parse_args()
    if args.start < PRE_SYNC_FOLLOW_FROM.date() or args.start > args.end:
        parser.error("Require 2026-11-01 <= start <= end.")
    start = datetime.combine(args.start, time.min, SHANGHAI)
    end = datetime.combine(args.end + timedelta(days=1), time.min, SHANGHAI)
    factory = get_session_factory()
    if factory is None:
        raise RuntimeError("A read-only database connection is required.")
    with factory() as session:
        if session.get_bind().dialect.name == "postgresql":
            session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            session.execute(text("SET LOCAL statement_timeout = '30s'"))
        print(json.dumps(audit(session, start=start, end=end, cutoff=datetime.now(SHANGHAI),
                               store_id=args.store_id), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
