"""Default dry-run: publish reviewed current authority without recalculating fees."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.api.dy_api.db import get_session_factory
from apps.ops_agent.resources import ResourceAction
from apps.worker.resource_monitor import current_resource_decision, start_resource_monitor
from apps.worker.settlement_publication_only import (
    PROTOCOL, apply_settlement_publication, preview_settlement_publication,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month", action="append", required=True, help="YYYY-MM; repeat for multiple requested months")
    parser.add_argument("--apply", action="store_true", help="Apply only an exact previously reviewed dry-run hash")
    parser.add_argument("--preview-hash", help="Required with --apply; copied from the full-month dry-run")
    parser.add_argument("--admission-wait-seconds", type=int, default=90, help="Bounded wait for the real resource monitor; admission is never bypassed")
    args = parser.parse_args(argv)
    if args.apply and not args.preview_hash:
        parser.error("--apply requires --preview-hash")
    if not 0 <= args.admission_wait_seconds <= 600:
        parser.error("--admission-wait-seconds must be between 0 and 600")
    factory = get_session_factory()
    if factory is None:
        print(json.dumps({"protocol": PROTOCOL, "status": "error", "error_type": "database_not_configured"}))
        return 1
    monitor = None
    try:
        if args.apply:
            monitor = start_resource_monitor(factory)
            if monitor is not None:
                deadline = time.monotonic() + args.admission_wait_seconds
                while True:
                    decision = current_resource_decision()
                    if decision is not None and decision.action == ResourceAction.ALLOW:
                        break
                    if time.monotonic() >= deadline:
                        print(json.dumps({"protocol": PROTOCOL, "status": "not_admitted", "reason": "resource_observation_not_ready"}))
                        return 1
                    time.sleep(1)
            result = apply_settlement_publication(factory, months=tuple(args.month), preview_hash=args.preview_hash)
        else:
            result = {"status": "dry_run", **preview_settlement_publication(factory, months=tuple(args.month))}
        print(json.dumps(result, default=str, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        # Operational errors are controlled; never print connection strings or private source rows.
        print(json.dumps({"protocol": PROTOCOL, "status": "error", "error_type": type(exc).__name__}), file=sys.stderr)
        return 1
    finally:
        if monitor is not None:
            monitor.stop()


if __name__ == "__main__":
    raise SystemExit(main())
