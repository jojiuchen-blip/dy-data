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
    assert "uq_clue_assignment_rounds_lead_execution_mode_round" in {
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


def test_clue_follow_up_state_machine_migration_is_reversible(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "follow-up-state.sqlite"
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")

    command.upgrade(config, "20260712_0014")
    command.upgrade(config, "head")
    upgraded = inspect(create_engine(f"sqlite:///{database_path.as_posix()}"))
    assert {
        "first_sla_expires_at",
        "protection_started_at",
        "protection_expires_at",
        "auto_expiry_enabled",
        "first_follow_up_sla_hours",
        "protection_days",
    }.issubset({column["name"] for column in upgraded.get_columns("clue_assignment_rounds")})
    assert {
        "deleted_at",
        "deleted_by_user_id",
        "deleted_by_username",
        "deletion_reason",
    }.issubset({column["name"] for column in upgraded.get_columns("clue_follow_up_records")})

    command.downgrade(config, "20260712_0014")
    downgraded = inspect(create_engine(f"sqlite:///{database_path.as_posix()}"))
    assert "first_sla_expires_at" not in {column["name"] for column in downgraded.get_columns("clue_assignment_rounds")}
    assert "deleted_at" not in {column["name"] for column in downgraded.get_columns("clue_follow_up_records")}


def test_clue_allocation_cycle_and_headquarters_pool_migration_is_reversible(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "allocation-cycles.sqlite"
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")

    command.upgrade(config, "20260712_0015")
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    now = datetime(2026, 7, 12, tzinfo=timezone.utc)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO clue_master_leads (
                    lead_key, source_clue_row_key, source_identity_key,
                    normalized_order_status, status_source, lifecycle_status,
                    pool_location, allocation_state, ended_without_assignment,
                    created_at, updated_at
                ) VALUES (
                    :lead_key, :source_clue_row_key, :source_identity_key,
                    :normalized_order_status, :status_source, :lifecycle_status,
                    :pool_location, :allocation_state, :ended_without_assignment,
                    :created_at, :updated_at
                )
                """
            ),
            {
                "lead_key": "legacy-headquarters-lead",
                "source_clue_row_key": "legacy-headquarters-raw",
                "source_identity_key": "legacy-headquarters-identity",
                "normalized_order_status": "active",
                "status_source": "test",
                "lifecycle_status": "active",
                "pool_location": "headquarters_pool",
                "allocation_state": "headquarters",
                "ended_without_assignment": False,
                "created_at": now,
                "updated_at": now,
            },
        )
    command.upgrade(config, "head")
    upgraded = inspect(create_engine(f"sqlite:///{database_path.as_posix()}"))
    assert {
        "clue_allocation_cycles",
        "clue_headquarters_pool_entries",
        "clue_allocation_audit_logs",
    }.issubset(upgraded.get_table_names())
    assert "uq_clue_headquarters_pool_entries_active_lead" in {
        index["name"] for index in upgraded.get_indexes("clue_headquarters_pool_entries")
    }
    assert "preview_token_hash" in {
        column["name"] for column in upgraded.get_columns("clue_allocation_cycles")
    }
    with create_engine(f"sqlite:///{database_path.as_posix()}").connect() as connection:
        entries = connection.execute(
            text(
                "SELECT lead_key, status, reason FROM clue_headquarters_pool_entries "
                "WHERE lead_key = 'legacy-headquarters-lead'"
            )
        ).mappings().all()
    assert entries == [
        {
            "lead_key": "legacy-headquarters-lead",
            "status": "active",
            "reason": "legacy_headquarters_pool",
        }
    ]

    command.downgrade(config, "20260712_0015")
    downgraded = inspect(create_engine(f"sqlite:///{database_path.as_posix()}"))
    assert not {
        "clue_allocation_cycles",
        "clue_headquarters_pool_entries",
        "clue_allocation_audit_logs",
    }.intersection(downgraded.get_table_names())


def test_legacy_clue_reassign_rule_table_is_dropped_at_head(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "legacy-clue-rule.sqlite"
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")

    command.upgrade(config, "20260712_0016")
    before_upgrade = inspect(create_engine(f"sqlite:///{database_path.as_posix()}"))
    assert "clue_reassign_rule_settings" in before_upgrade.get_table_names()

    command.upgrade(config, "head")
    upgraded = inspect(create_engine(f"sqlite:///{database_path.as_posix()}"))
    assert "clue_reassign_rule_settings" not in upgraded.get_table_names()

    command.downgrade(config, "20260712_0016")
    downgraded = inspect(create_engine(f"sqlite:///{database_path.as_posix()}"))
    assert "clue_reassign_rule_settings" in downgraded.get_table_names()


def test_cli_authorization_migration_is_reversible(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "cli-authorizations.sqlite"
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")

    command.upgrade(config, "head")

    upgraded = inspect(create_engine(f"sqlite:///{database_path.as_posix()}"))
    assert {"cli_device_authorizations", "cli_refresh_tokens"}.issubset(upgraded.get_table_names())
    assert {
        "device_authorization_id",
        "device_code_hash",
        "user_code_hash",
        "status",
        "scope",
        "user_id",
        "expires_at",
        "approved_at",
        "consumed_at",
    }.issubset({column["name"] for column in upgraded.get_columns("cli_device_authorizations")})
    assert {
        "refresh_token_id",
        "token_hash",
        "user_id",
        "username",
        "auth_type",
        "authorization_fingerprint",
        "scope",
        "expires_at",
        "last_used_at",
        "revoked_at",
        "replaced_by_token_id",
    }.issubset({column["name"] for column in upgraded.get_columns("cli_refresh_tokens")})
    refresh_columns = {
        column["name"]: column
        for column in upgraded.get_columns("cli_refresh_tokens")
    }
    assert not refresh_columns["authorization_fingerprint"]["nullable"]
    device_indexes = {
        index["name"]: index for index in upgraded.get_indexes("cli_device_authorizations")
    }
    refresh_token_indexes = {
        index["name"]: index for index in upgraded.get_indexes("cli_refresh_tokens")
    }
    assert {
        "ix_cli_device_authorizations_device_code_hash",
        "ix_cli_device_authorizations_user_code_hash",
        "ix_cli_refresh_tokens_token_hash",
    }.issubset(
        device_indexes.keys() | refresh_token_indexes.keys()
    )
    assert device_indexes["ix_cli_device_authorizations_user_code_hash"]["unique"]

    command.downgrade(config, "20260713_0017")

    downgraded = inspect(create_engine(f"sqlite:///{database_path.as_posix()}"))
    assert not {"cli_device_authorizations", "cli_refresh_tokens"}.intersection(
        downgraded.get_table_names()
    )
