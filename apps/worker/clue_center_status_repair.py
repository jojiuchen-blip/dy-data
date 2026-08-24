from __future__ import annotations

import argparse

from apps.api.dy_api.db import get_session_factory, session_scope
from apps.worker.clue_allocation import synchronize_non_active_clue_states

DEFAULT_BATCH_SIZE = 500


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Close stale clue center snapshots and assignment rounds in bounded batches."
    )
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist the terminal-state synchronization. Without this flag the command is a dry run.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    factory = get_session_factory()
    if factory is None:
        raise RuntimeError("Set DY_DATABASE_URL or DATABASE_URL before repairing clue center states.")
    with session_scope(factory) as session:
        stats = synchronize_non_active_clue_states(
            session,
            batch_size=args.batch_size,
            dry_run=not args.apply,
        )
    print(
        "[clue-center-status-repair] "
        f"dry_run={stats['dry_run']} "
        f"scanned={stats['scanned']} "
        f"orders={stats['orders']} "
        f"rounds_closed={stats['rounds_closed']} "
        f"centers_closed={stats['centers_closed']} "
        f"headquarters_closed={stats['headquarters_closed']} "
        f"batches={stats['batches']} "
        f"skipped={stats.get('skipped', '')}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
