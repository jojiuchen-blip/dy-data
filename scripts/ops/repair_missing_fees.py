"""Private exact missing-fee preview (default) and hash-bound PostgreSQL apply."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
for directory in (ROOT, ROOT / "src"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from apps.api.dy_api.db import make_engine
from apps.worker.missing_fee_repair import (
    MissingFeeRepairError, apply_missing_fees, digest, preview_missing_fees,
)


def _private_destination(path: Path) -> Path:
    path = path.resolve()
    try:
        relative = path.relative_to(ROOT)
    except ValueError:
        return path
    ignored = subprocess.run(["git", "check-ignore", "--quiet", "--", str(relative)],
                             cwd=ROOT, capture_output=True, check=False)
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", "--", str(relative)],
                             cwd=ROOT, capture_output=True, check=False)
    if ignored.returncode != 0 or tracked.returncode == 0:
        raise MissingFeeRepairError("private report must be ignored/untracked or outside repository")
    return path


def main(argv: list[str] | None = None) -> int:
    """Run once; sensitive reports never go to stdout or tracked paths."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--exclusions", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--apply", metavar="EXACT_PREVIEW_SHA256")
    args = parser.parse_args(argv)
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
        exclusions = json.loads(args.exclusions.read_text(encoding="utf-8-sig"))
        operation = "apply" if args.apply else "preview"
        output = _private_destination(args.output or ROOT / ".tmp" / "missing-fee-repair" /
                                      (digest(manifest.get("request_id"))[:24] + f"-{operation}.json"))
        output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Reserve the output before any database mutation, never follow an
        # existing report/symlink or discover an unwritable path after commit.
        with output.open("x", encoding="utf-8") as report_file:
            os.chmod(output, 0o600)
            engine = make_engine()
            try:
                with Session(engine, autoflush=False, expire_on_commit=False) as session:
                    if args.apply:
                        report = apply_missing_fees(session, manifest=manifest, exclusions=exclusions,
                                                    preview_hash=args.apply)
                    else:
                        report = preview_missing_fees(session, manifest=manifest, exclusions=exclusions)
                json.dump(report, report_file, ensure_ascii=False, indent=2)
                report_file.write("\n")
            finally:
                engine.dispose()
        print(json.dumps({"applied": report["applied"], "replayed": report["replayed"],
                          "coupon_count": report["coupon_count"], "preview_hash": report["preview_hash"],
                          "report_path": str(output)}, ensure_ascii=False))
        return 0
    except (MissingFeeRepairError, OSError, ValueError) as exc:
        print(f"missing-fee repair rejected: {exc}", file=sys.stderr)
        return 2
    except SQLAlchemyError:
        # Driver messages may contain database URLs or raw platform identities.
        print("missing-fee repair database failure; transaction rolled back", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
