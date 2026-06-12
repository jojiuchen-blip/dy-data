from __future__ import annotations

import argparse
from datetime import datetime, timezone

from apps.api.dy_api.db import get_session_factory, session_scope
from apps.worker.collectors.windows import resolve_collection_window
from apps.worker.pipeline import run_collect_and_settle
from apps.worker.settlement import run_settlement_job


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one backend collection/settlement cycle.")
    parser.add_argument("--start", default=None, help="Collection start, YYYY-MM-DD or ISO datetime.")
    parser.add_argument("--end", default=None, help="Collection end, YYYY-MM-DD or ISO datetime.")
    parser.add_argument("--overlap-days", type=int, default=None, help="Use a rolling overlap window.")
    parser.add_argument("--timezone", default=None, help="Collection timezone, defaults to Asia/Shanghai.")
    parser.add_argument("--job-id", default=None, help="Optional job_runs.job_id/source_run_id.")
    parser.add_argument("--settlement-only", action="store_true", help="Skip collection and rebuild settlement only.")
    parser.add_argument(
        "--skip-browser-export",
        action="store_true",
        help="Reserved for browser-export phase; Open API collection still runs.",
    )
    return parser.parse_args(argv)


def resolve_window_from_args(args: argparse.Namespace, *, now: datetime | None = None):
    return resolve_collection_window(
        now=now,
        start=args.start,
        end=args.end,
        overlap_days=args.overlap_days,
        timezone_name=args.timezone,
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    factory = get_session_factory()
    if factory is None:
        raise RuntimeError("Set DY_DATABASE_URL or DATABASE_URL before running collection.")

    with session_scope(factory) as session:
        if args.settlement_only:
            job_id = args.job_id or _job_id("settlement")
            run_settlement_job(session, job_id=job_id, source_run_id=job_id)
        else:
            run_collect_and_settle(session, window=resolve_window_from_args(args), job_id=args.job_id)
    return 0


def _job_id(prefix: str) -> str:
    return f"{prefix}_{datetime.now(timezone.utc):%Y%m%d%H%M%S}"


if __name__ == "__main__":
    raise SystemExit(main())

