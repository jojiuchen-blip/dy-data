from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.api.dy_api.db import make_engine, make_session_factory
from apps.worker.clue_allocation import refresh_store_score_snapshots


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create an immutable manual store score snapshot.")
    parser.add_argument(
        "--database-url",
        default=None,
        help="Optional database URL. Defaults to DY_DATABASE_URL or DATABASE_URL.",
    )
    parser.add_argument("--lookback-days", type=int, default=30, help="Rolling score window in days.")
    parser.add_argument("--min-samples", type=int, default=20, help="Minimum samples before a rate is trusted.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Calculate and report the snapshot, then roll back all changes.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    engine = make_engine(args.database_url)
    factory = make_session_factory(engine)
    with factory() as session:
        result = refresh_store_score_snapshots(
            session,
            run_mode="manual",
            lookback_days=args.lookback_days,
            min_samples=args.min_samples,
        )
        if args.dry_run:
            session.rollback()
        else:
            session.commit()
    print(json.dumps({"dry_run": bool(args.dry_run), **result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
