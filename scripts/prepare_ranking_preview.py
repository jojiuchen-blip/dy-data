"""Create a NEW isolated SQLite DB; exercise migration roundtrip and synthetic rules.

Run from repository root: python scripts/prepare_ranking_preview.py --database tmp/ranking-preview.db
Existing databases are always rejected. No real business data is imported.
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def prepare(path: Path):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect
    from sqlalchemy.orm import Session
    from apps.api.dy_api.ranking_schema_v1 import metadata
    from apps.api.dy_api.ranking_snapshots import calculate_snapshot, read_snapshot_report
    from apps.worker.ranking_preview_fixture import seed_preview, START, END, CUTOFF, ELIGIBILITY_VERSION

    path = path.resolve()
    if path.exists():
        raise ValueError("Refusing to overwrite an existing database")
    path.parent.mkdir(parents=True, exist_ok=True)
    url = "sqlite:///" + path.as_posix()
    old_url = os.environ.get("DY_DATABASE_URL")
    os.environ["DY_DATABASE_URL"] = url
    try:
        config = Config(str(ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(ROOT / "alembic"))
        command.upgrade(config, "20260911_0057")
        command.upgrade(config, "20260911_0058")
        engine = create_engine(url)
        assert set(metadata.tables).issubset(inspect(engine).get_table_names())
        engine.dispose()
        command.downgrade(config, "20260911_0057")
        engine = create_engine(url)
        assert not set(metadata.tables).intersection(inspect(engine).get_table_names())
        engine.dispose()
        command.upgrade(config, "20260911_0058")
        engine = create_engine(url)
        with Session(engine) as session:
            seed_preview(session)
            calculate_snapshot(session, run_id="synthetic-baseline", period_start=START, period_end=END,
                observed_through=CUTOFF, roster_at=START, eligibility_version=ELIGIBILITY_VERSION)
            session.commit()
            report = read_snapshot_report(session, period_start=START, period_end=END, level="store")
            totals = report["totals"]
            assert (totals["order_count"], totals["store_count"], totals["follow_24h_rate"], totals["verification_rate"]) == (10, 3, .3, .5)
        engine.dispose()
        path.with_suffix(".report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(json.dumps({"database": str(path), "migration_roundtrip": "passed", "totals": totals}, ensure_ascii=False))
    finally:
        if old_url is None:
            os.environ.pop("DY_DATABASE_URL", None)
        else:
            os.environ["DY_DATABASE_URL"] = old_url


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    prepare(parser.parse_args().database)
