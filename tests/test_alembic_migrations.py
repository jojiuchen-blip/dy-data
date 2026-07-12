from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_clue_allocation_m1_migration_upgrades_existing_schema(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "migration.sqlite"
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")

    command.upgrade(config, "20260706_0011")
    command.upgrade(config, "head")

    inspector = inspect(create_engine(f"sqlite:///{database_path.as_posix()}"))
    assert {"clue_master_leads", "clue_order_status_events", "store_score_snapshots"}.issubset(
        inspector.get_table_names()
    )
    assert "store_score_snapshot_runs" in inspector.get_table_names()
    assert {"follow_poi_id", "intention_poi_id"}.issubset(
        {column["name"] for column in inspector.get_columns("raw_douyin_clues")}
    )
    assert {"execution_mode", "matured_at", "terminal_reason"}.issubset(
        {column["name"] for column in inspector.get_columns("clue_assignment_rounds")}
    )

    command.downgrade(config, "20260706_0011")

    downgraded = inspect(create_engine(f"sqlite:///{database_path.as_posix()}"))
    assert not {"clue_master_leads", "clue_order_status_events", "store_score_snapshot_runs", "store_score_snapshots"}.intersection(
        downgraded.get_table_names()
    )
    assert not {"follow_poi_id", "intention_poi_id"}.intersection(
        {column["name"] for column in downgraded.get_columns("raw_douyin_clues")}
    )
