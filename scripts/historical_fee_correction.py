"""Preview by default; apply only the reviewed private historical correction."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from sqlalchemy import text

from apps.api.dy_api.db import get_session_factory
from apps.worker.historical_fee_correction import (
    HistoricalFeeCorrectionError, apply_correction, preview_correction,
)


def main() -> None:
    """Read configured database; never print configuration or source documents."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest",required=True,type=Path)
    parser.add_argument("--source",required=True,action="append",type=Path)
    parser.add_argument("--apply",action="store_true")
    parser.add_argument("--expected-preview-sha256")
    args = parser.parse_args()
    if args.apply and not args.expected_preview_sha256:
        parser.error("--apply requires --expected-preview-sha256 from the reviewed preview")
    raw = args.manifest.read_bytes()
    manifest = json.loads(raw.decode("utf-8-sig"))
    sources = {}
    for path in args.source:
        document = path.read_bytes()
        sources[hashlib.sha256(document).hexdigest()] = document
    factory = get_session_factory()
    if factory is None:
        parser.error("a configured database is required")
    try:
        with factory() as session:
            if args.apply:
                result = apply_correction(session,manifest,source_documents=sources,
                                          expected_preview_sha256=args.expected_preview_sha256)
                session.commit()
                # A fresh transaction verifies the durable audit/adjustment/bill
                # chain rather than interpreting a successful flush as commit.
                try:
                    replay = apply_correction(session,manifest,source_documents=sources,
                                              expected_preview_sha256=args.expected_preview_sha256)
                    result["durable_readback_verified"] = replay["already_applied"]
                except HistoricalFeeCorrectionError as exc:
                    # Commit has happened: report that fact even if a later
                    # confirmation/version change prevents strict readback.
                    result["durable_readback_verified"] = False
                    result["readback_conflict"] = str(exc)
                finally:
                    session.rollback()
            else:
                if session.get_bind().dialect.name == "postgresql":
                    session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
                result = preview_correction(session,manifest,source_documents=sources)
                session.rollback()
    except HistoricalFeeCorrectionError as exc:
        parser.exit(2,"Correction rejected: "+str(exc)+"\n")
    print(json.dumps({**result,"manifest_file_sha256":hashlib.sha256(raw).hexdigest()},
                     ensure_ascii=False,sort_keys=True,indent=2))
    if args.apply and not result["durable_readback_verified"]:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
