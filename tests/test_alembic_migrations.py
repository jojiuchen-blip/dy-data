from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, text


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
    assert "uq_clue_allocation_rule_versions_published" in {
        index["name"] for index in inspector.get_indexes("clue_allocation_rule_versions")
    }
    assert "uq_clue_store_group_members_store_id" in {
        constraint["name"] for constraint in inspector.get_unique_constraints("clue_store_group_members")
    }
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


def test_clue_rule_version_migration_is_at_head_and_reversible(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "rule-versions.sqlite"
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")

    command.upgrade(config, "20260712_0012")
    command.upgrade(config, "head")

    inspector = inspect(create_engine(f"sqlite:///{database_path.as_posix()}"))
    assert {
        "clue_allocation_rules",
        "clue_allocation_rule_versions",
        "clue_allocation_strategy_configs",
        "clue_store_groups",
        "clue_store_group_members",
        "clue_lead_rule_version_bindings",
    }.issubset(inspector.get_table_names())
    assert {"lead_key", "rule_version_id", "scope_resolution_snapshot", "rule_version_snapshot"}.issubset(
        {column["name"] for column in inspector.get_columns("clue_lead_rule_version_bindings")}
    )
    assert "order_id" not in {column["name"] for column in inspector.get_columns("clue_lead_rule_version_bindings")}

    command.downgrade(config, "20260712_0012")

    downgraded = inspect(create_engine(f"sqlite:///{database_path.as_posix()}"))
    assert not {
        "clue_allocation_rules",
        "clue_allocation_rule_versions",
        "clue_allocation_strategy_configs",
        "clue_store_groups",
        "clue_store_group_members",
        "clue_lead_rule_version_bindings",
    }.intersection(downgraded.get_table_names())


def test_clue_allocation_engine_migration_preserves_legacy_rounds_and_has_an_empty_schema_round_trip(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "allocation-engine.sqlite"
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")

    command.upgrade(config, "20260712_0013")
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    now = datetime(2026, 7, 12, tzinfo=timezone.utc)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO clue_assignment_rounds (
                    assignment_round_id, order_id, round_no, assigned_at_source,
                    follow_result, is_followed, is_follow_success, round_status,
                    execution_mode, is_self_store_verified, created_at, updated_at
                ) VALUES (
                    :assignment_round_id, :order_id, :round_no, :assigned_at_source,
                    :follow_result, :is_followed, :is_follow_success, :round_status,
                    :execution_mode, :is_self_store_verified, :created_at, :updated_at
                )
                """
            ),
            {
                "assignment_round_id": "legacy-order-1",
                "order_id": "order-1",
                "round_no": 1,
                "assigned_at_source": "legacy",
                "follow_result": "pending",
                "is_followed": False,
                "is_follow_success": False,
                "round_status": "active_unfollowed",
                "execution_mode": "legacy",
                "is_self_store_verified": False,
                "created_at": now,
                "updated_at": now,
            },
        )

    command.upgrade(config, "head")
    inspector = inspect(create_engine(f"sqlite:///{database_path.as_posix()}"))
    assert "clue_allocation_decisions" in inspector.get_table_names()
    assert {
        "lead_key",
        "rule_version_id",
        "strategy_type",
        "allocation_decision_id",
    }.issubset({column["name"] for column in inspector.get_columns("clue_assignment_rounds")})
    assert "uq_clue_assignment_rounds_order_execution_mode_round" in {
        constraint["name"] for constraint in inspector.get_unique_constraints("clue_assignment_rounds")
    }

    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO clue_assignment_rounds (
                    assignment_round_id, order_id, round_no, assigned_at_source,
                    follow_result, is_followed, is_follow_success, round_status,
                    execution_mode, is_self_store_verified, created_at, updated_at
                ) VALUES (
                    :assignment_round_id, :order_id, :round_no, :assigned_at_source,
                    :follow_result, :is_followed, :is_follow_success, :round_status,
                    :execution_mode, :is_self_store_verified, :created_at, :updated_at
                )
                """
            ),
            {
                "assignment_round_id": "formal-order-1",
                "order_id": "order-1",
                "round_no": 1,
                "assigned_at_source": "engine",
                "follow_result": "pending",
                "is_followed": False,
                "is_follow_success": False,
                "round_status": "active_unfollowed",
                "execution_mode": "formal",
                "is_self_store_verified": False,
                "created_at": now,
                "updated_at": now,
            },
        )
        count = connection.scalar(text("SELECT COUNT(*) FROM clue_assignment_rounds WHERE order_id = 'order-1'"))
    assert count == 2
    with pytest.raises(RuntimeError, match="cannot downgrade clue allocation engine"):
        command.downgrade(config, "20260712_0013")

    reversible_path = tmp_path / "allocation-engine-reversible.sqlite"
    reversible_config = Config(str(repo_root / "alembic.ini"))
    reversible_config.set_main_option("script_location", str(repo_root / "alembic"))
    reversible_config.set_main_option("sqlalchemy.url", f"sqlite:///{reversible_path.as_posix()}")
    command.upgrade(reversible_config, "20260712_0013")
    command.upgrade(reversible_config, "head")
    command.downgrade(reversible_config, "20260712_0013")
    downgraded = inspect(create_engine(f"sqlite:///{reversible_path.as_posix()}"))
    assert "clue_allocation_decisions" not in downgraded.get_table_names()
    assert "lead_key" not in {column["name"] for column in downgraded.get_columns("clue_assignment_rounds")}
