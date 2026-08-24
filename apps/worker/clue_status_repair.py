from __future__ import annotations

import argparse

from apps.api.dy_api.db import get_session_factory, session_scope
from apps.worker.clue_allocation import refresh_unknown_clue_master_statuses

DEFAULT_BATCH_SIZE = 500


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Refresh unknown clue master statuses in bounded batches."
    )
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist the status and current-center updates. Without this flag the command is a dry run.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    factory = get_session_factory()
    if factory is None:
        raise RuntimeError("Set DY_DATABASE_URL or DATABASE_URL before repairing clue statuses.")
    with session_scope(factory) as session:
        stats = refresh_unknown_clue_master_statuses(
            session,
            batch_size=args.batch_size,
            dry_run=not args.apply,
        )
    print(
        "[clue-status-repair] "
        f"dry_run={stats['dry_run']} "
        f"scanned={stats['scanned']} "
        f"updated={stats['updated']} "
        f"resolved={stats['resolved']} "
        f"status_review={stats['status_review']} "
        f"batches={stats['batches']} "
        f"skipped={stats.get('skipped', '')}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
