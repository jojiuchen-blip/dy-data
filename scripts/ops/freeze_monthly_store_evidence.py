"""Preview or append a reviewed monthly sales-store evidence version.

The preview is read-only. Applying only adds immutable relationship evidence,
and does not change source rosters, fees, statements, confirmations, or invoices.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from sqlalchemy import select, text

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.api.dy_api.db import get_session_factory
from apps.api.dy_api.models import AccountQualificationVersion
from apps.worker.monthly_store_evidence import (
    StoreEvidenceError,
    freeze_store_evidence,
    preview_store_evidence,
)

PROTOCOL = "dydata-monthly-store-evidence-review-v1"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month", required=True)
    parser.add_argument("--qualification-sha256", required=True)
    parser.add_argument("--facts-file", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--preview-sha256")
    args = parser.parse_args(argv)
    if args.apply and not args.preview_sha256:
        parser.error("--apply requires the reviewed --preview-sha256")
    facts = []
    if args.facts_file:
        manifest = json.loads(args.facts_file.read_text(encoding="utf-8-sig"))
        if (manifest.get("business_month") != args.month
                or manifest.get("qualification_content_sha256") != args.qualification_sha256
                or not manifest.get("reviewed_by") or not isinstance(manifest.get("facts"), list)):
            parser.error("facts manifest must bind month, qualification digest, reviewer, and fact list")
        facts = [{**fact, "reviewed_by": manifest["reviewed_by"]} for fact in manifest["facts"]]
    factory = get_session_factory()
    if factory is None:
        parser.error("database_not_configured")
    try:
        with factory() as session, session.begin():
            if session.get_bind().dialect.name == "postgresql":
                session.execute(text("SET LOCAL statement_timeout = '30s'"))
                session.execute(text("SET LOCAL lock_timeout = '2s'"))
                if not args.apply:
                    session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            version = session.scalar(select(AccountQualificationVersion).where(
                AccountQualificationVersion.business_month == args.month,
            ))
            if version is None or version.content_sha256 != args.qualification_sha256:
                raise StoreEvidenceError("qualification_version_missing_or_changed")
            preview = preview_store_evidence(session, qualification_version=version, facts=facts)
            counts = {kind: sum(row["kind"] == kind for row in preview["records"])
                      for kind in ("account", "poi", "alias")}
            result = {"protocol": PROTOCOL, "business_month": args.month,
                "qualification_version_id": version.version_id,
                "content_sha256": preview["content_sha256"], "fact_count_by_kind": counts,
                "applied": False}
            if args.apply:
                frozen = freeze_store_evidence(session, qualification_version=version, facts=facts,
                    expected_content_sha256=args.preview_sha256)
                result.update(applied=True, version_id=frozen.version_id)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except StoreEvidenceError as exc:
        print(json.dumps({"protocol": PROTOCOL, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
