"""Preview or apply an approved exact processing-month fee correction manifest."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text

from apps.api.dy_api.db import get_session_factory
from apps.worker.historical_fee_correction import HistoricalFeeCorrectionError
from apps.worker.monthly_fee_corrections import apply_monthly_fee_corrections, preview_monthly_fee_corrections


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--evidence", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="Private report path")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-preview-sha256")
    parser.add_argument("--approved-by")
    parser.add_argument("--approval-reference")
    args = parser.parse_args()
    if args.apply and not all((args.expected_preview_sha256, args.approved_by, args.approval_reference)):
        parser.error("--apply requires a reviewed hash, approver and exact approval reference")
    if args.output.exists():
        parser.error("--output must be a new private report file")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
    evidence = {}
    for path in args.evidence:
        source = path.read_bytes()
        evidence[sha256(source).hexdigest()] = source
    factory = get_session_factory()
    if factory is None:
        parser.error("a configured database is required")
    def run_apply(session):
        return apply_monthly_fee_corrections(
            session, manifest, evidence=evidence, expected_preview_sha256=args.expected_preview_sha256,
            approved_by=args.approved_by, approval_reference=args.approval_reference,
        )

    try:
        with factory() as session, args.output.open("x", encoding="utf-8") as report:
            if args.apply:
                result = run_apply(session)
                session.commit()
                try:
                    result["durable_readback_verified"] = run_apply(session)["already_applied"]
                except HistoricalFeeCorrectionError:
                    result["durable_readback_verified"] = False
            else:
                if session.get_bind().dialect.name == "postgresql":
                    session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
                result = preview_monthly_fee_corrections(session, manifest, evidence=evidence)
            json.dump(result, report, ensure_ascii=False, indent=2)
            report.write("\n")
    except HistoricalFeeCorrectionError as exc:
        parser.exit(2, f"Correction rejected ({exc}).\n")
    if args.apply and not result["durable_readback_verified"]:
        parser.exit(3, "Correction committed; durable audit/adjustment readback did not match.\n")


if __name__ == "__main__":
    main()
