from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


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
