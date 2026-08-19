from __future__ import annotations

from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


def test_alembic_has_one_deployable_head() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))

    assert ScriptDirectory.from_config(config).get_heads() == ["20260813_0030"]


def test_online_postgresql_migrations_use_a_session_advisory_lock() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    env_source = (repo_root / "alembic" / "env.py").read_text(encoding="utf-8")

    assert "pg_advisory_lock" in env_source
    assert "pg_advisory_unlock" in env_source
    assert "SET statement_timeout = '10min'" in env_source


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


def test_clue_source_identifier_history_migration_backfills_and_is_reversible(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "clue-identifier-history.sqlite"
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")

    command.upgrade(config, "20260727_0028")
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    now = datetime(2026, 8, 4, tzinfo=timezone.utc)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO clue_master_leads (
                    lead_key, source_clue_row_key, source_identity_key,
                    canonical_clue_id, order_id, normalized_order_status,
                    status_source, lifecycle_status, allocation_state,
                    ended_without_assignment, first_seen_at, last_seen_at,
                    created_at, updated_at
                ) VALUES (
                    :lead_key, :source_clue_row_key, :source_identity_key,
                    :canonical_clue_id, :order_id, :normalized_order_status,
                    :status_source, :lifecycle_status, :allocation_state,
                    :ended_without_assignment, :first_seen_at, :last_seen_at,
                    :created_at, :updated_at
                )
                """
            ),
            {
                "lead_key": "lead-existing",
                "source_clue_row_key": "source-existing",
                "source_identity_key": "identity-existing",
                "canonical_clue_id": "clue-existing",
                "order_id": "order-existing",
                "normalized_order_status": "active",
                "status_source": "clue",
                "lifecycle_status": "active",
                "allocation_state": "pending_allocation",
                "ended_without_assignment": False,
                "first_seen_at": now,
                "last_seen_at": now,
                "created_at": now,
                "updated_at": now,
            },
        )

    command.upgrade(config, "head")

    inspector = inspect(engine)
    assert "clue_source_identifier_history" in inspector.get_table_names()
    assert {
        "identifier_history_id",
        "lead_key",
        "source_clue_row_key",
        "identifier_type",
        "identifier_value",
        "source_payload_hash",
        "first_seen_at",
        "last_seen_at",
        "is_current",
    }.issubset(
        {column["name"] for column in inspector.get_columns("clue_source_identifier_history")}
    )
    assert "uq_clue_source_identifier_history_source_type_value" in {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("clue_source_identifier_history")
    }
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT identifier_type, identifier_value, is_current
                FROM clue_source_identifier_history
                ORDER BY identifier_type
                """
            )
        ).all()
    assert rows == [
        ("clue_id", "clue-existing", 1),
        ("source_identity_key", "identity-existing", 1),
    ]

    command.downgrade(config, "20260727_0028")

    assert "clue_source_identifier_history" not in inspect(engine).get_table_names()


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


def test_account_access_control_migration_maps_legacy_roles_and_is_reversible(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "account-access-control.sqlite"
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")

    command.upgrade(config, "20260713_0017")
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    now = datetime(2026, 7, 21, tzinfo=timezone.utc)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO users (
                    user_id, username, display_name, role, status,
                    is_initialized, created_at, updated_at
                ) VALUES
                    ('legacy-admin', 'legacy-admin', 'Legacy Admin', 'admin', 'active', 1, :now, :now),
                    ('legacy-viewer', 'legacy-viewer', 'Legacy Viewer', 'viewer', 'active', 1, :now, :now),
                    ('legacy-store', 'legacy-store', 'Legacy Store', 'store', 'active', 1, :now, :now)
                """
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO dim_stores (store_id, store_name, is_active, created_at, updated_at) "
                "VALUES ('store-1', 'Store One', 1, :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO user_store_scopes (user_id, store_id, created_at) "
                "VALUES ('legacy-store', 'store-1', :now)"
            ),
            {"now": now},
        )

    command.upgrade(config, "head")
    upgraded = inspect(engine)
    assert {
        "access_pages",
        "role_page_permissions",
        "user_page_permission_overrides",
        "account_permission_audit_logs",
    }.issubset(upgraded.get_table_names())
    assert {"store_scope_mode", "auth_version"}.issubset(
        {column["name"] for column in upgraded.get_columns("users")}
    )
    assert "result" in {
        column["name"] for column in upgraded.get_columns("account_permission_audit_logs")
    }
    with engine.connect() as connection:
        users = connection.execute(
            text(
                "SELECT user_id, role, store_scope_mode FROM users "
                "ORDER BY user_id"
            )
        ).mappings().all()
        page_keys = connection.execute(
            text("SELECT page_key FROM access_pages ORDER BY page_key")
        ).scalars().all()
        ranking_routes = connection.execute(
            text("SELECT route_patterns FROM access_pages WHERE page_key = 'B01'")
        ).scalar_one()
    assert users == [
        {"user_id": "legacy-admin", "role": "highest_admin", "store_scope_mode": "all"},
        {"user_id": "legacy-store", "role": "store", "store_scope_mode": "specified"},
        {"user_id": "legacy-viewer", "role": "admin", "store_scope_mode": "all"},
    ]
    assert page_keys == [
        "A01", "A02", "B01", "B02", "B03", "C01",
        "D01", "D02", "D03", "D04", "D05", "D06", "D07", "D08", "D09", "D10",
    ]
    assert ranking_routes == '["/ranking"]'

    command.downgrade(config, "20260713_0017")
    downgraded = inspect(engine)
    assert "store_scope_mode" not in {
        column["name"] for column in downgraded.get_columns("users")
    }
    assert not {
        "access_pages",
        "role_page_permissions",
        "user_page_permission_overrides",
        "account_permission_audit_logs",
    }.intersection(downgraded.get_table_names())


def test_cli_authorization_migration_is_reversible(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "cli-authorizations.sqlite"
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")

    command.upgrade(config, "20260713_0017")
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    now = datetime.now(timezone.utc)
    with engine.begin() as connection:
        for user_id, username in (("legacy-1", "legacy-one"), ("legacy-2", "legacy-two")):
            connection.execute(
                text(
                    """
                    INSERT INTO users (
                        user_id, username, display_name, role, status,
                        is_initialized, created_at, updated_at
                    ) VALUES (
                        :user_id, :username, :display_name, 'viewer', 'active',
                        1, :created_at, :updated_at
                    )
                    """
                ),
                {
                    "user_id": user_id,
                    "username": username,
                    "display_name": username,
                    "created_at": now,
                    "updated_at": now,
                },
            )

    command.upgrade(config, "head")

    upgraded = inspect(engine)
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
        "issued_auth_generation",
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
    user_columns = {column["name"]: column for column in upgraded.get_columns("users")}
    assert not user_columns["cli_subject"]["nullable"]
    assert not user_columns["auth_generation"]["nullable"]
    with engine.connect() as connection:
        migrated_users = connection.execute(
            text(
                "SELECT user_id, cli_subject, auth_generation FROM users ORDER BY user_id"
            )
        ).mappings().all()
    assert [row["user_id"] for row in migrated_users] == ["legacy-1", "legacy-2"]
    assert all(row["cli_subject"] for row in migrated_users)
    assert len({row["cli_subject"] for row in migrated_users}) == 2
    assert {row["auth_generation"] for row in migrated_users} == {1}
    user_indexes = {index["name"]: index for index in upgraded.get_indexes("users")}
    assert user_indexes["ix_users_cli_subject"]["unique"]
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
    assert {"cli_subject", "auth_generation"}.isdisjoint(
        {column["name"] for column in downgraded.get_columns("users")}
    )


def test_cli_audit_and_refresh_family_migration_is_reversible(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "cli-audit-family.sqlite"
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")

    command.upgrade(config, "20260722_0019")
    command.upgrade(config, "head")

    upgraded = inspect(create_engine(f"sqlite:///{database_path.as_posix()}"))
    assert "cli_audit_events" in upgraded.get_table_names()
    assert {
        "audit_event_id",
        "event_type",
        "operation",
        "request_id",
        "command",
        "result_status",
        "created_at",
    }.issubset(
        {column["name"] for column in upgraded.get_columns("cli_audit_events")}
    )
    assert "family_id" in {
        column["name"] for column in upgraded.get_columns("cli_refresh_tokens")
    }
    audit_indexes = {
        index["name"] for index in upgraded.get_indexes("cli_audit_events")
    }
    refresh_indexes = {
        index["name"] for index in upgraded.get_indexes("cli_refresh_tokens")
    }
    assert "ix_cli_audit_events_command_created" in audit_indexes
    assert "ix_cli_refresh_tokens_family_id" in refresh_indexes

    command.downgrade(config, "20260722_0019")

    downgraded = inspect(create_engine(f"sqlite:///{database_path.as_posix()}"))
    assert "cli_audit_events" not in downgraded.get_table_names()
    assert "family_id" not in {
        column["name"] for column in downgraded.get_columns("cli_refresh_tokens")
    }


def test_mcp_oauth_migration_is_at_head_and_reversible(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "mcp-oauth.sqlite"
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")

    command.upgrade(config, "20260722_0020")
    command.upgrade(config, "head")

    upgraded = inspect(create_engine(f"sqlite:///{database_path.as_posix()}"))
    assert {
        "mcp_oauth_clients",
        "mcp_authorization_requests",
        "mcp_access_tokens",
        "mcp_refresh_tokens",
    }.issubset(upgraded.get_table_names())
    assert {
        "request_token_hash",
        "code_hash",
        "code_challenge",
        "resource",
        "environment",
        "consumed_at",
    }.issubset(
        {
            column["name"]
            for column in upgraded.get_columns("mcp_authorization_requests")
        }
    )
    assert {
        "family_id",
        "token_hash",
        "resource",
        "environment",
        "revoked_at",
        "replaced_by_token_id",
    }.issubset(
        {column["name"] for column in upgraded.get_columns("mcp_refresh_tokens")}
    )
    assert "ix_mcp_access_tokens_token_hash" in {
        index["name"] for index in upgraded.get_indexes("mcp_access_tokens")
    }
    assert "ix_mcp_refresh_tokens_family_id" in {
        index["name"] for index in upgraded.get_indexes("mcp_refresh_tokens")
    }

    command.downgrade(config, "20260722_0020")

    downgraded = inspect(create_engine(f"sqlite:///{database_path.as_posix()}"))
    assert not {
        "mcp_oauth_clients",
        "mcp_authorization_requests",
        "mcp_access_tokens",
        "mcp_refresh_tokens",
    }.intersection(downgraded.get_table_names())

    command.upgrade(config, "head")
    reupgraded = inspect(create_engine(f"sqlite:///{database_path.as_posix()}"))
    assert {
        "mcp_oauth_clients",
        "mcp_authorization_requests",
        "mcp_access_tokens",
        "mcp_refresh_tokens",
    }.issubset(reupgraded.get_table_names())


def test_agent_audit_context_migration_is_reversible(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "agent-audit-context.sqlite"
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")

    command.upgrade(config, "20260722_0021")
    command.upgrade(config, "head")

    upgraded = inspect(create_engine(f"sqlite:///{database_path.as_posix()}"))
    columns = {
        column["name"] for column in upgraded.get_columns("cli_audit_events")
    }
    assert {"environment", "channel", "authorization_scopes"}.issubset(columns)
    assert "ix_cli_audit_events_channel" in {
        index["name"] for index in upgraded.get_indexes("cli_audit_events")
    }

    command.downgrade(config, "20260722_0021")
    downgraded = inspect(create_engine(f"sqlite:///{database_path.as_posix()}"))
    columns = {
        column["name"] for column in downgraded.get_columns("cli_audit_events")
    }
    assert {"environment", "channel", "authorization_scopes"}.isdisjoint(columns)

    command.upgrade(config, "head")
    reupgraded = inspect(create_engine(f"sqlite:///{database_path.as_posix()}"))
    assert {"environment", "channel", "authorization_scopes"}.issubset(
        {
            column["name"]
            for column in reupgraded.get_columns("cli_audit_events")
        }
    )


def test_raw_order_internal_id_compat_migration_backfills_and_is_reversible(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "raw-order-internal-id.sqlite"
    database_url = f"sqlite:///{database_path.as_posix()}"
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "20260715_0018")
    engine = create_engine(database_url)
    now = datetime(2026, 7, 20, tzinfo=timezone.utc)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO raw_douyin_orders (
                    order_id, raw_payload, created_at, updated_at
                ) VALUES
                    ('order-1', '{}', :created_at, :updated_at),
                    ('order-2', '{}', :created_at, :updated_at)
                """
            ),
            {"created_at": now, "updated_at": now},
        )
        connection.execute(
            text(
                """
                INSERT INTO raw_douyin_order_coupons (
                    coupon_id, order_id, raw_payload
                ) VALUES
                    ('coupon-1', 'order-1', '{}'),
                    ('coupon-2', 'order-2', '{}')
                """
            )
        )

    command.upgrade(config, "20260720_0019")

    upgraded = inspect(create_engine(database_url))
    order_columns = {column["name"]: column for column in upgraded.get_columns("raw_douyin_orders")}
    coupon_columns = {
        column["name"]: column for column in upgraded.get_columns("raw_douyin_order_coupons")
    }
    assert order_columns["id"]["nullable"] is False
    assert coupon_columns["id"]["nullable"] is False
    assert coupon_columns["raw_order_id"]["nullable"] is False
    assert upgraded.get_pk_constraint("raw_douyin_orders")["constrained_columns"] == ["order_id"]
    assert upgraded.get_pk_constraint("raw_douyin_order_coupons")["constrained_columns"] == [
        "coupon_id"
    ]

    with create_engine(database_url).connect() as connection:
        orders = connection.execute(
            text("SELECT id, order_id FROM raw_douyin_orders ORDER BY order_id")
        ).mappings().all()
        coupons = connection.execute(
            text(
                "SELECT c.id, c.coupon_id, c.order_id, c.raw_order_id, o.id AS expected_order_id "
                "FROM raw_douyin_order_coupons AS c "
                "JOIN raw_douyin_orders AS o ON o.order_id = c.order_id "
                "ORDER BY c.coupon_id"
            )
        ).mappings().all()
    assert len({row["id"] for row in orders}) == 2
    assert all(row["id"] is not None for row in orders)
    assert len({row["id"] for row in coupons}) == 2
    assert all(row["id"] is not None for row in coupons)
    assert all(row["raw_order_id"] == row["expected_order_id"] for row in coupons)

    command.downgrade(config, "20260715_0018")
    downgraded = inspect(create_engine(database_url))
    assert "id" not in {
        column["name"] for column in downgraded.get_columns("raw_douyin_orders")
    }
    assert not {"id", "raw_order_id"}.intersection(
        column["name"] for column in downgraded.get_columns("raw_douyin_order_coupons")
    )


def test_raw_order_internal_id_cutover_switches_primary_keys_and_preserves_rows(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "raw-order-id-cutover.sqlite"
    database_url = f"sqlite:///{database_path.as_posix()}"
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "20260720_0023")
    engine = create_engine(database_url)
    now = datetime(2026, 7, 20, tzinfo=timezone.utc)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO raw_douyin_orders "
                "(id, order_id, raw_payload, created_at, updated_at) VALUES "
                "(101, 'order-cutover-1', '{}', :now, :now), "
                "(102, 'order-cutover-2', '{}', :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO raw_douyin_order_coupons "
                "(id, coupon_id, order_id, raw_order_id, raw_payload, "
                "coupon_refunded_amount_cent) VALUES "
                "(201, 'coupon-cutover-1', 'order-cutover-1', 101, '{}', 0), "
                "(202, 'coupon-cutover-2', 'order-cutover-2', 102, '{}', 0)"
            )
        )

    command.upgrade(config, "head")

    upgraded = inspect(create_engine(database_url))
    assert upgraded.get_pk_constraint("raw_douyin_orders")["constrained_columns"] == [
        "id"
    ]
    assert upgraded.get_pk_constraint("raw_douyin_order_coupons")[
        "constrained_columns"
    ] == ["id"]
    assert ("order_id",) in {
        tuple(constraint["column_names"])
        for constraint in upgraded.get_unique_constraints("raw_douyin_orders")
    }
    assert ("coupon_id",) in {
        tuple(constraint["column_names"])
        for constraint in upgraded.get_unique_constraints(
            "raw_douyin_order_coupons"
        )
    }
    assert upgraded.get_foreign_keys("raw_douyin_order_coupons") == []
    assert "idx_raw_douyin_order_coupons_raw_order" in {
        index["name"]
        for index in upgraded.get_indexes("raw_douyin_order_coupons")
    }
    with create_engine(database_url).begin() as connection:
        counts = connection.execute(
            text(
                "SELECT "
                "(SELECT count(*) FROM raw_douyin_orders) AS order_count, "
                "(SELECT count(*) FROM raw_douyin_order_coupons) AS coupon_count, "
                "(SELECT count(*) FROM raw_douyin_order_coupons c "
                "LEFT JOIN raw_douyin_orders o ON o.id = c.raw_order_id "
                "WHERE o.id IS NULL OR o.order_id <> c.order_id) AS mismatch_count"
            )
        ).mappings().one()
        connection.execute(
            text(
                "INSERT INTO raw_douyin_orders "
                "(order_id, raw_payload, created_at, updated_at) "
                "VALUES ('order-cutover-3', '{}', :now, :now)"
            ),
            {"now": now},
        )
        generated_id = connection.scalar(
            text(
                "SELECT id FROM raw_douyin_orders "
                "WHERE order_id = 'order-cutover-3'"
            )
        )
    assert counts == {"order_count": 2, "coupon_count": 2, "mismatch_count": 0}
    assert generated_id is not None

    command.downgrade(config, "20260720_0023")
    downgraded = inspect(create_engine(database_url))
    assert downgraded.get_pk_constraint("raw_douyin_orders")[
        "constrained_columns"
    ] == ["order_id"]
    assert downgraded.get_pk_constraint("raw_douyin_order_coupons")[
        "constrained_columns"
    ] == ["coupon_id"]
    assert len(downgraded.get_foreign_keys("raw_douyin_order_coupons")) == 1


def test_raw_order_internal_id_cutover_blocks_mismatched_shadow_reference(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "raw-order-id-cutover-mismatch.sqlite"
    database_url = f"sqlite:///{database_path.as_posix()}"
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "20260720_0023")
    now = datetime(2026, 7, 20, tzinfo=timezone.utc)
    with create_engine(database_url).begin() as connection:
        connection.execute(
            text(
                "INSERT INTO raw_douyin_orders "
                "(id, order_id, raw_payload, created_at, updated_at) VALUES "
                "(101, 'order-cutover-1', '{}', :now, :now), "
                "(102, 'order-cutover-2', '{}', :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO raw_douyin_order_coupons "
                "(id, coupon_id, order_id, raw_order_id, raw_payload, "
                "coupon_refunded_amount_cent) VALUES "
                "(201, 'coupon-cutover-1', 'order-cutover-1', 102, '{}', 0)"
            )
        )

    with pytest.raises(
        RuntimeError, match="internal_reference_mismatch_count=1"
    ):
        command.upgrade(config, "head")

    unchanged = inspect(create_engine(database_url))
    assert unchanged.get_pk_constraint("raw_douyin_orders")[
        "constrained_columns"
    ] == ["order_id"]
    assert unchanged.get_pk_constraint("raw_douyin_order_coupons")[
        "constrained_columns"
    ] == ["coupon_id"]


def test_raw_order_internal_id_cutover_blocks_orphaned_internal_reference(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "raw-order-id-cutover-orphan.sqlite"
    database_url = f"sqlite:///{database_path.as_posix()}"
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "20260720_0023")
    now = datetime(2026, 7, 20, tzinfo=timezone.utc)
    with create_engine(database_url).begin() as connection:
        connection.execute(
            text(
                "INSERT INTO raw_douyin_orders "
                "(id, order_id, raw_payload, created_at, updated_at) VALUES "
                "(101, 'order-cutover-1', '{}', :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO raw_douyin_order_coupons "
                "(id, coupon_id, order_id, raw_order_id, raw_payload, "
                "coupon_refunded_amount_cent) VALUES "
                "(201, 'coupon-cutover-1', 'order-cutover-1', 999, '{}', 0)"
            )
        )

    with pytest.raises(
        RuntimeError, match="internal_reference_mismatch_count=1"
    ):
        command.upgrade(config, "head")

    unchanged = inspect(create_engine(database_url))
    assert unchanged.get_pk_constraint("raw_douyin_orders")[
        "constrained_columns"
    ] == ["order_id"]
    assert unchanged.get_pk_constraint("raw_douyin_order_coupons")[
        "constrained_columns"
    ] == ["coupon_id"]


def test_raw_order_internal_id_cutover_postgresql_ddl_is_short_lock_safe() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    output = StringIO()
    config = Config(str(repo_root / "alembic.ini"), output_buffer=output)
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option(
        "sqlalchemy.url", "postgresql+psycopg://user:pass@localhost/test"
    )

    command.upgrade(config, "20260720_0023:20260721_0026", sql=True)

    ddl = output.getvalue()
    assert "CREATE UNIQUE INDEX CONCURRENTLY" in ddl
    assert "SET statement_timeout = '5min'" in ddl
    assert "RESET statement_timeout" in ddl
    assert "SET LOCAL lock_timeout" in ddl
    validation_lock = (
        "LOCK TABLE raw_douyin_orders, raw_douyin_order_coupons "
        "IN SHARE ROW EXCLUSIVE MODE"
    )
    cutover_lock = (
        "LOCK TABLE raw_douyin_orders, raw_douyin_order_coupons "
        "IN ACCESS EXCLUSIVE MODE"
    )
    assert validation_lock in ddl
    assert cutover_lock in ddl
    assert ddl.index(validation_lock) < ddl.index(cutover_lock)
    assert "USING INDEX" in ddl
    assert ddl.count("pg_get_serial_sequence") == 2


def test_product_sync_active_slot_migration_preflights_duplicates() -> None:
    migration = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260721_0025_product_sync_active_slot.py"
    ).read_text(encoding="utf-8")

    assert "duplicate active product-sync jobs" in migration
    assert migration.index("duplicate active product-sync jobs") < migration.index(
        "op.create_index"
    )


def test_large_table_indexes_are_created_concurrently_on_postgresql() -> None:
    versions = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    refund_migration = (versions / "20260720_0023_refund_success_observed_at.py").read_text(
        encoding="utf-8"
    )
    product_migration = (
        versions / "20260727_0028_product_sync_production_fields.py"
    ).read_text(encoding="utf-8")

    assert "CREATE INDEX CONCURRENTLY" in refund_migration
    assert product_migration.count("CREATE INDEX CONCURRENTLY") == 1


def test_product_rule_schema_preserves_legacy_sku_data_and_is_reversible(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "product-rule-schema.sqlite"
    database_url = f"sqlite:///{database_path.as_posix()}"
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "20260720_0019")
    engine = create_engine(database_url)
    now = datetime(2026, 7, 20, tzinfo=timezone.utc)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO dim_sku_product_rules (
                    sku_id, product_scope, product_type, product_name,
                    commission_rate, is_service_product, updated_at
                ) VALUES (
                    'legacy-sku', 'legacy-scope', 'legacy-type', 'Legacy Product',
                    0.1250, true, :updated_at
                )
                """
            ),
            {"updated_at": now},
        )

    command.upgrade(config, "head")

    upgraded = inspect(create_engine(database_url))
    assert {
        "sku_product_sync_history",
        "settlement_scope_rule",
        "sku_fee_rule",
        "sku_fee_rule_import_batch",
        "sku_fee_rule_import_row",
    }.issubset(upgraded.get_table_names())
    assert upgraded.get_pk_constraint("dim_sku_product_rules")["constrained_columns"] == [
        "id"
    ]
    assert ("sku_id",) in {
        tuple(constraint["column_names"])
        for constraint in upgraded.get_unique_constraints("dim_sku_product_rules")
    }
    assert {
        "sku_name",
        "product_id",
        "spu_id",
        "owner_account_id",
        "product_status_normalized",
        "sync_run_id",
        "last_synced_at",
        "manual_modified_by",
        "manual_modified_at",
        "gmt_create",
        "gmt_modified",
    }.issubset(
        column["name"] for column in upgraded.get_columns("dim_sku_product_rules")
    )

    with create_engine(database_url).connect() as connection:
        legacy = connection.execute(
            text(
                "SELECT id, sku_id, product_scope, product_type, product_name, "
                "commission_rate, is_service_product, gmt_modified "
                "FROM dim_sku_product_rules WHERE sku_id = 'legacy-sku'"
            )
        ).mappings().one()
        fee_rule_count = connection.scalar(text("SELECT COUNT(*) FROM sku_fee_rule"))
    assert legacy["id"] is not None
    assert legacy["product_scope"] == "legacy-scope"
    assert legacy["product_type"] == "legacy-type"
    assert legacy["product_name"] == "Legacy Product"
    assert float(legacy["commission_rate"]) == pytest.approx(0.125)
    assert bool(legacy["is_service_product"]) is True
    assert fee_rule_count == 0

    command.downgrade(config, "20260720_0019")
    downgraded = inspect(create_engine(database_url))
    assert not {
        "sku_product_sync_history",
        "settlement_scope_rule",
        "sku_fee_rule",
        "sku_fee_rule_import_batch",
        "sku_fee_rule_import_row",
    }.intersection(downgraded.get_table_names())
    assert downgraded.get_pk_constraint("dim_sku_product_rules")["constrained_columns"] == [
        "sku_id"
    ]
    with create_engine(database_url).connect() as connection:
        restored = connection.execute(
            text(
                "SELECT sku_id, product_scope, product_type, product_name, "
                "commission_rate, is_service_product, updated_at "
                "FROM dim_sku_product_rules WHERE sku_id = 'legacy-sku'"
            )
        ).mappings().one()
    assert restored["product_scope"] == "legacy-scope"
    assert restored["product_type"] == "legacy-type"
    assert float(restored["commission_rate"]) == pytest.approx(0.125)


def test_settlement_reporting_schema_preserves_legacy_projections_and_is_reversible(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "settlement-reporting-schema.sqlite"
    database_url = f"sqlite:///{database_path.as_posix()}"
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "20260720_0020")
    engine = create_engine(database_url)
    now = datetime(2026, 7, 20, tzinfo=timezone.utc)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO agg_store_monthly_settlement (
                    month, store_id, product_type,
                    estimated_receivable_commission_cent,
                    commissionable_total_cent,
                    estimated_payable_commission_cent,
                    updated_at
                ) VALUES (
                    '2026-07', 'legacy-store', 'legacy-type',
                    1200, 10000, 300, :updated_at
                )
                """
            ),
            {"updated_at": now},
        )
        connection.execute(
            text(
                """
                INSERT INTO agg_store_ranking (
                    month, product_type, store_id, store_name,
                    sales_order_count, self_sold_self_verified_count,
                    self_sold_other_verified_count, other_sold_self_verified_count,
                    self_verify_income_cent, effective_commission_income_cent,
                    updated_at
                ) VALUES (
                    '2026-07', 'legacy-type', 'legacy-store', 'Legacy Store',
                    3, 1, 1, 1, 10000, 1200, :updated_at
                )
                """
            ),
            {"updated_at": now},
        )

    command.upgrade(config, "head")

    upgraded = inspect(create_engine(database_url))
    assert {
        "douyin_refund_event",
        "settlement_fee_result",
        "settlement_fee_result_current",
        "settlement_fee_adjustment",
        "settlement_statement",
        "settlement_statement_line",
        "settlement_statement_entry",
    }.issubset(upgraded.get_table_names())
    assert upgraded.get_pk_constraint("agg_store_monthly_settlement")[
        "constrained_columns"
    ] == ["id"]
    assert upgraded.get_pk_constraint("agg_store_ranking")["constrained_columns"] == [
        "id"
    ]

    with create_engine(database_url).connect() as connection:
        monthly = connection.execute(
            text(
                "SELECT product_scope, estimated_receivable_commission_cent, "
                "commissionable_total_cent, estimated_payable_commission_cent, "
                "promotion_original_fee_cent, management_original_fee_cent, "
                "projection_run_id FROM agg_store_monthly_settlement "
                "WHERE month = '2026-07' AND store_id = 'legacy-store'"
            )
        ).mappings().one()
        ranking = connection.execute(
            text(
                "SELECT period_type, period_key, product_scope, sales_order_count, "
                "effective_commission_income_cent, promotion_net_fee_cent, "
                "management_net_fee_cent, projection_run_id FROM agg_store_ranking "
                "WHERE month = '2026-07' AND store_id = 'legacy-store'"
            )
        ).mappings().one()
    assert monthly["product_scope"] == "all"
    assert monthly["estimated_receivable_commission_cent"] == 1200
    assert monthly["commissionable_total_cent"] == 10000
    assert monthly["estimated_payable_commission_cent"] == 300
    assert monthly["promotion_original_fee_cent"] == 0
    assert monthly["management_original_fee_cent"] == 0
    assert monthly["projection_run_id"] == "migration-20260720-0021"
    assert ranking["period_type"] == 1
    assert ranking["period_key"] == "2026-07"
    assert ranking["product_scope"] == "all"
    assert ranking["sales_order_count"] == 3
    assert ranking["effective_commission_income_cent"] == 1200
    assert ranking["promotion_net_fee_cent"] == 0
    assert ranking["management_net_fee_cent"] == 0

    with pytest.raises(IntegrityError):
        with create_engine(database_url).begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO settlement_fee_result (
                        fee_result_id, coupon_id, order_id, fee_direction,
                        result_version, original_business_month, rule_match_date,
                        sku_id, product_scope, product_type, sale_channel_normalized,
                        source_amount_cent, refunded_amount_cent, fee_base_cent,
                        fee_rate, fee_amount_cent, rule_version, scope_rule_version,
                        result_status, calculation_run_id, calculated_at
                    ) VALUES (
                        'invalid-rate', 'coupon-1', 'order-1', 1,
                        1, '2026-08', '2026-08-01',
                        'sku-1', '', '', 'live',
                        10000, 0, 10000,
                        1.500000, 15000, 'rule-1', 'scope-1',
                        1, 'run-1', :calculated_at
                    )
                    """
                ),
                {"calculated_at": now},
            )

    with pytest.raises(IntegrityError):
        with create_engine(database_url).begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO settlement_statement_line (
                        statement_line_id, statement_id, fee_direction,
                        product_scope, product_type, original_entry_count,
                        adjustment_entry_count, original_base_cent,
                        adjustment_base_cent, net_base_cent, original_fee_cent,
                        adjustment_fee_cent, net_fee_cent
                    ) VALUES (
                        'invalid-net', 'statement-1', 1,
                        '', '', 1,
                        1, 10000,
                        -2000, 9000, 1000,
                        -200, 900
                    )
                    """
                )
            )

    command.downgrade(config, "20260720_0020")
    downgraded = inspect(create_engine(database_url))
    assert not {
        "douyin_refund_event",
        "settlement_fee_result",
        "settlement_fee_result_current",
        "settlement_fee_adjustment",
        "settlement_statement",
        "settlement_statement_line",
        "settlement_statement_entry",
    }.intersection(downgraded.get_table_names())
    assert downgraded.get_pk_constraint("agg_store_monthly_settlement")[
        "constrained_columns"
    ] == ["month", "store_id", "product_type"]
    assert downgraded.get_pk_constraint("agg_store_ranking")["constrained_columns"] == [
        "month",
        "product_type",
        "store_id",
    ]
    with create_engine(database_url).connect() as connection:
        restored_monthly = connection.execute(
            text(
                "SELECT estimated_receivable_commission_cent, "
                "commissionable_total_cent, estimated_payable_commission_cent "
                "FROM agg_store_monthly_settlement WHERE month = '2026-07' "
                "AND store_id = 'legacy-store' AND product_type = 'legacy-type'"
            )
        ).mappings().one()
    assert restored_monthly["estimated_receivable_commission_cent"] == 1200
    assert restored_monthly["commissionable_total_cent"] == 10000
    assert restored_monthly["estimated_payable_commission_cent"] == 300


def test_raw_settlement_field_migration_backfills_single_coupon_and_is_reversible(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "raw-settlement-fields.sqlite"
    database_url = f"sqlite:///{database_path.as_posix()}"
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "20260720_0021")

    observed_at = datetime(2026, 8, 8, tzinfo=timezone.utc)
    with create_engine(database_url).begin() as connection:
        connection.execute(
            text(
                "INSERT INTO raw_douyin_orders ("
                "id, order_id, order_status, pay_time, paid_amount_cent, "
                "owner_account_id, sale_channel, raw_payload, created_at, updated_at"
                ") VALUES ("
                "1, 'legacy-order', 'paid', :observed_at, 12345, "
                "'owner-1', 'short_video', '{}', :observed_at, :observed_at"
                ")"
            ),
            {"observed_at": observed_at},
        )
        connection.execute(
            text(
                "INSERT INTO raw_douyin_order_coupons ("
                "id, raw_order_id, coupon_id, order_id, coupon_status, "
                "coupon_refunded_cent, raw_payload"
                ") VALUES ("
                "1, 1, 'legacy-coupon', 'legacy-order', 'fulfilled', 345, '{}'"
                ")"
            )
        )

    command.upgrade(config, "head")

    with create_engine(database_url).connect() as connection:
        order = connection.execute(
            text(
                "SELECT order_status_raw, order_status_normalized, sale_time, "
                "order_paid_amount_cent, sale_channel_raw, sale_channel_normalized "
                "FROM raw_douyin_orders WHERE order_id = 'legacy-order'"
            )
        ).mappings().one()
        coupon = connection.execute(
            text(
                "SELECT coupon_status_raw, coupon_status_normalized, "
                "coupon_paid_amount_cent, coupon_refunded_amount_cent "
                "FROM raw_douyin_order_coupons WHERE coupon_id = 'legacy-coupon'"
            )
        ).mappings().one()
    assert order["order_status_raw"] == "paid"
    assert order["order_status_normalized"] == "paid"
    assert order["sale_time"] is not None
    assert order["order_paid_amount_cent"] == 12345
    assert order["sale_channel_raw"] == "short_video"
    assert order["sale_channel_normalized"] == "short_video"
    assert coupon["coupon_status_raw"] == "fulfilled"
    assert coupon["coupon_status_normalized"] == "verified"
    assert coupon["coupon_paid_amount_cent"] == 12345
    assert coupon["coupon_refunded_amount_cent"] == 345

    command.downgrade(config, "20260720_0021")
    downgraded = inspect(create_engine(database_url))
    assert not {
        "order_status_raw",
        "order_status_normalized",
        "sale_time",
        "order_paid_amount_cent",
        "sale_channel_raw",
        "sale_channel_normalized",
    }.intersection(
        {column["name"] for column in downgraded.get_columns("raw_douyin_orders")}
    )


def test_sku_product_import_migration_links_rows_to_batches(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "sku-product-import.sqlite"
    database_url = f"sqlite:///{database_path.as_posix()}"
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "head")

    foreign_keys = inspect(create_engine(database_url)).get_foreign_keys(
        "sku_product_import_row"
    )
    assert len(foreign_keys) == 1
    assert foreign_keys[0]["constrained_columns"] == ["batch_id"]
    assert foreign_keys[0]["referred_table"] == "sku_product_import_batch"
    assert foreign_keys[0]["referred_columns"] == ["batch_id"]
    assert foreign_keys[0]["options"] == {"ondelete": "CASCADE"}
