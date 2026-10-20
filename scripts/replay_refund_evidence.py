"""Preview existing refund evidence; apply requires an approved preview digest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from sqlalchemy.exc import SQLAlchemyError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.api.dy_api.db import make_engine  # noqa: E402
from apps.worker.refund_replay import (  # noqa: E402
    RefundReplayError, ReplayBounds, apply_refunds, preview_refunds,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Require explicit source and finite traversal limits in both modes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", help="Defaults to DY_DATABASE_URL or DATABASE_URL; never printed.")
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--after-id", required=True, type=int)
    parser.add_argument("--batch-size", required=True, type=int, help="1..100")
    parser.add_argument("--max-batches", required=True, type=int, help="1..20")
    parser.add_argument("--upper-id", type=int, help="Optional frozen upper PK for continued previews.")
    parser.add_argument("--statement-timeout-ms", type=int, default=3000)
    parser.add_argument("--lock-timeout-ms", type=int, default=500)
    parser.add_argument("--transaction-timeout-ms", type=int, default=15000)
    parser.add_argument("--apply", action="store_true", help="Explicit write opt-in. Default is strict read-only preview.")
    parser.add_argument("--preview-file", type=Path)
    parser.add_argument("--preview-digest")
    parser.add_argument("--repair-run-id")
    parser.add_argument("--reason")
    args = parser.parse_args(argv)
    if args.apply and not all((args.preview_file, args.preview_digest, args.repair_run_id, args.reason)):
        parser.error("--apply requires --preview-file, --preview-digest, --repair-run-id and --reason")
    if not args.apply and any((args.preview_file, args.preview_digest, args.repair_run_id, args.reason)):
        parser.error("apply authorization flags require --apply")
    return args


def main(argv: list[str] | None = None) -> int:
    """Emit only bounded, PII-free JSON; any blocked row returns nonzero."""
    args = parse_args(argv)
    engine = None
    try:
        bounds = ReplayBounds(args.source_run_id, args.after_id, args.batch_size, args.max_batches,
                              args.statement_timeout_ms, args.lock_timeout_ms, args.transaction_timeout_ms)
        preview = None
        if args.apply:
            if args.preview_file.stat().st_size > 2_000_000:
                raise RefundReplayError("preview file exceeds bounded size")
            preview = json.loads(args.preview_file.read_text(encoding="utf-8"))
            if not isinstance(preview, dict):
                raise RefundReplayError("preview must be a JSON object")
            if preview.get("bounds") != vars(bounds) or (args.upper_id is not None and preview.get("upper_id") != args.upper_id):
                raise RefundReplayError("CLI bounds do not match reviewed preview")
        engine = make_engine(args.database_url)
        if args.apply and engine.dialect.name != "postgresql":
            raise RefundReplayError("CLI apply requires PostgreSQL row locks")
        result = (apply_refunds(engine, preview, expected_digest=args.preview_digest,
                               repair_run_id=args.repair_run_id, reason=args.reason)
                  if args.apply else preview_refunds(engine, bounds, upper_id=args.upper_id))
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 2 if result["blocked"] or (args.apply and not result["audit_finalized"]) else 0
    except (RefundReplayError, SQLAlchemyError, TimeoutError, OSError, TypeError, KeyError, json.JSONDecodeError) as exc:
        # DB exceptions can include payloads/URLs. Do not print their messages.
        message = str(exc) if isinstance(exc, RefundReplayError) else "preview_or_apply_failed_safely"
        print(json.dumps({"status": "blocked", "error": message}, ensure_ascii=False))
        return 2
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
