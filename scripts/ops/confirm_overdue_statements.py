"""Preview an exact overdue-bill batch; write only with its reviewed hash."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from apps.api.dy_api.db import get_session_factory
from apps.worker.billing_auto_confirmation import apply_auto_confirmation, preview_auto_confirmation
from sqlalchemy.exc import SQLAlchemyError


def _private_report(path: Path) -> Path:
    if path.is_symlink():
        raise ValueError("report must not be a symbolic link")
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(ROOT)
    except ValueError:
        return resolved
    ignored = subprocess.run(["git", "check-ignore", "--quiet", "--", str(relative)],
        cwd=ROOT, capture_output=True, check=False)
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", "--", str(relative)],
        cwd=ROOT, capture_output=True, check=False)
    if ignored.returncode != 0 or tracked.returncode == 0:
        raise ValueError("report must be ignored and untracked, or outside the repository")
    return resolved


def main() -> int:
    """Write a private receipt without ever logging database credentials."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month", action="append", default=[])
    parser.add_argument("--store-id", action="append", default=[])
    parser.add_argument("--after-id", type=int, default=0)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-hash")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.apply and not args.expected_hash:
        parser.error("--apply requires the exact --expected-hash from a reviewed dry-run")
    if not args.apply and args.expected_hash:
        parser.error("--expected-hash is only valid with --apply")
    factory = get_session_factory()
    if factory is None:
        parser.error("database configuration is unavailable")
    options = {"months": tuple(sorted(set(args.month))), "store_ids": tuple(sorted(set(args.store_id))),
               "after_id": args.after_id, "limit": args.limit}
    os.umask(0o077)
    report = _private_report(args.report)
    report.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Reserve a writable private destination before any financial mutation.
    applied = False
    apply_started = False
    try:
        with report.open("x", encoding="utf-8") as output:
            os.chmod(report, 0o600)
            if args.apply:
                apply_started = True
                result = apply_auto_confirmation(factory, preview_hash=args.expected_hash, **options)
            else:
                result = preview_auto_confirmation(factory, **options)
            applied = bool(args.apply)
            json.dump({"mode": "apply" if args.apply else "dry_run", **result}, output,
                      ensure_ascii=False, sort_keys=True, default=str, indent=2)
    except (SQLAlchemyError, OSError, ValueError) as exc:
        print(json.dumps({"status": "applied_but_report_failed" if applied else "operation_failed",
            "apply_started": apply_started, "applied": True if applied else None if apply_started else False,
            "error_type": type(exc).__name__, "automatic_retry": False}), file=sys.stderr)
        return 4 if applied else 2
    print(json.dumps({"mode": "apply" if args.apply else "dry_run", "report": str(report),
        "preview_hash": result.get("preview_hash"), "counts": result.get("counts"),
        "confirmed_count": result.get("confirmed_count", 0), "has_more": result.get("has_more")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
