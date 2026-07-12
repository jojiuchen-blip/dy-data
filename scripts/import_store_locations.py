from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.api.dy_api.db import make_engine, make_session_factory
from apps.worker.clue_allocation import import_store_locations


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import Douyin clue store locations through existing POI mappings.")
    parser.add_argument("--input", required=True, type=Path, help="Business-provided .xlsx store location workbook.")
    parser.add_argument(
        "--database-url",
        default=None,
        help="Optional database URL. Defaults to DY_DATABASE_URL or DATABASE_URL.",
    )
    parser.add_argument(
        "--enable-participation",
        action="store_true",
        help="Enable allocation participation for valid imported stores. Disabled by default.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and report the import, then roll back all changes.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = args.input.expanduser().resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"Input workbook does not exist: {input_path}")
    if input_path.suffix.lower() != ".xlsx":
        raise ValueError("Input workbook must be an .xlsx file")

    engine = make_engine(args.database_url)
    factory = make_session_factory(engine)
    with factory() as session:
        result = import_store_locations(
            session,
            input_path,
            enable_participation=bool(args.enable_participation),
        )
        if args.dry_run:
            session.rollback()
        else:
            session.commit()
    print(json.dumps({"dry_run": bool(args.dry_run), **result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
