"""Preview/apply bounded ranking snapshot retention actions.

The command is intentionally dry-run by default.  It never truncates ranking
tables and deletes at most the requested number of complete snapshot runs,
with one complete run per transaction.
"""

from __future__ import annotations

import argparse
import json

from apps.api.dy_api.db import get_session_factory, session_scope
from apps.api.dy_api.ranking_lifecycle import (
    archive_snapshot,
    cleanup_snapshots,
    ensure_lifecycle_schema,
    unarchive_snapshot,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preview/apply bounded ranking snapshot retention.")
    parser.add_argument("--limit", type=int, default=50, help="Maximum complete snapshot runs per invocation.")
    parser.add_argument("--apply", action="store_true", help="Delete planned old snapshots; default is dry-run.")
    parser.add_argument("--archive", metavar="RUN_ID", help="Pin a snapshot for an explicit business reason.")
    parser.add_argument("--unarchive", metavar="RUN_ID", help="Remove a previous pin.")
    parser.add_argument("--reason", help="Required with --archive.")
    parser.add_argument("--actor", help="Optional operator identity recorded with --archive.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.limit < 0:
        raise SystemExit("--limit must be non-negative")
    if args.archive and args.unarchive:
        raise SystemExit("--archive and --unarchive cannot be combined")
    if args.archive and not (args.reason or "").strip():
        raise SystemExit("--reason is required with --archive")
    factory = get_session_factory()
    if factory is None:
        raise RuntimeError("Set DY_DATABASE_URL or DATABASE_URL before maintaining ranking snapshots.")
    if args.archive or args.unarchive:
        with session_scope(factory) as session:
            ensure_lifecycle_schema(session)
            if args.archive:
                archive_snapshot(session, args.archive, reason=args.reason, actor=args.actor)
                print(json.dumps({"action": "archive", "run_id": args.archive}, ensure_ascii=False))
                return 0
            unarchive_snapshot(session, args.unarchive)
            print(json.dumps({"action": "unarchive", "run_id": args.unarchive}, ensure_ascii=False))
            return 0

    if not args.apply:
        # A preview may backfill sidecar rows in memory so old runs are
        # counted correctly, but it must never commit that backfill.
        with session_scope(factory) as session:
            ensure_lifecycle_schema(session)
            result = cleanup_snapshots(session, dry_run=True, max_runs=args.limit)
            session.rollback()
        print(json.dumps(result, ensure_ascii=False, default=str))
        return 0

    # Apply one complete run per transaction. This bounds locks, WAL and
    # rollback cost even when the caller asks for many old versions.
    applied: list[dict] = []
    for _ in range(args.limit):
        with session_scope(factory) as session:
            ensure_lifecycle_schema(session)
            result = cleanup_snapshots(session, dry_run=False, max_runs=1)
        applied.append(result)
        if result.get("deleted", 0) == 0:
            break
    result = {
        "dry_run": False,
        "planned": [item for batch in applied for item in batch.get("planned", [])],
        "deleted": sum(int(item.get("deleted", 0)) for item in applied),
        "batches": len(applied),
    }
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
