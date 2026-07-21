from __future__ import annotations

from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


def test_clue_allocation_m1_migration_upgrades_existing_schema(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "migration.sqlite"
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")

    command.upgrade(config, "20260706_0011")
    command.upgrade(config, "20260720_0019")

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

    command.upgrade(config, "20260720_0023:head", sql=True)

    ddl = output.getvalue()
    assert "CREATE UNIQUE INDEX CONCURRENTLY" in ddl
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
