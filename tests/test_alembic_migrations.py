from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from threading import Barrier

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

    assert ScriptDirectory.from_config(config).get_heads() == ["20260830_0044"]


def test_production_revision_chain_resolves_orphaned_0036() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    script = ScriptDirectory.from_config(config)

    assert script.get_revision("20260806_0036") is not None
    assert script.get_revision("20260819_0037") is not None


def test_existing_0036_database_can_upgrade_to_head(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "orphaned-0036.sqlite"
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")

    command.upgrade(config, "20260806_0036")
    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    inspector = inspect(engine)
    assert {"sku_product_import_batch", "sku_product_import_row"}.issubset(
        inspector.get_table_names()
    )
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20260830_0044"


def test_online_postgresql_migrations_use_a_session_advisory_lock() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    env_source = (repo_root / "alembic" / "env.py").read_text(encoding="utf-8")

    assert "pg_try_advisory_lock" in env_source
    assert "pg_advisory_unlock" in env_source
    assert "SELECT pg_advisory_lock(%s)" not in env_source
    assert "driver_connection.autocommit = True" in env_source
    assert "connection.connection.driver_connection" in env_source
    assert "connectable.raw_connection()" not in env_source
    assert "SET statement_timeout = '10min'" in env_source


def test_g2_management_sap_reversal_migration_is_reversible(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "g2-management-sap-reversal.sqlite"
    database_url = f"sqlite:///{database_path.as_posix()}"
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "20260821_0040")
    command.upgrade(config, "20260824_0041")

    engine = create_engine(database_url)
    upgraded = inspect(engine)
    assert {"sap_suggestion", "management_carryforward_application"}.issubset(
        upgraded.get_table_names()
    )
    assert {"source_type", "import_batch_id"}.issubset(
        {column["name"] for column in upgraded.get_columns("store_finance_profile")}
    )
    import_batch_column = next(
        column
        for column in upgraded.get_columns("store_finance_profile")
        if column["name"] == "import_batch_id"
    )
    assert import_batch_column["nullable"] is True
    assert "reverses_batch_id" in {
        column["name"] for column in upgraded.get_columns("finance_import_batch")
    }
    for table_name in (
        "store_finance_profile",
        "invoice_record",
        "promotion_invoice",
    ):
        assert "is_tombstone" in {
            column["name"] for column in upgraded.get_columns(table_name)
        }
    assert {
        "reversal_effect_type",
        "reverses_target_record_id",
        "previous_target_record_id",
    }.issubset(
        {column["name"] for column in upgraded.get_columns("finance_import_row")}
    )
    assert "idx_sap_suggestion_current" in {
        index["name"] for index in upgraded.get_indexes("sap_suggestion")
    }
    assert "idx_management_carryforward_current" in {
        index["name"]
        for index in upgraded.get_indexes("management_carryforward_application")
    }
    assert "uk_finance_import_batch_final_version" not in {
        index["name"] for index in upgraded.get_indexes("finance_import_batch")
    }

    command.downgrade(config, "20260821_0040")
    downgraded = inspect(engine)
    assert "sap_suggestion" not in downgraded.get_table_names()
    assert "management_carryforward_application" not in downgraded.get_table_names()
    assert "source_type" not in {
        column["name"] for column in downgraded.get_columns("store_finance_profile")
    }
    assert "reverses_batch_id" not in {
        column["name"] for column in downgraded.get_columns("finance_import_batch")
    }
    assert "is_tombstone" not in {
        column["name"] for column in downgraded.get_columns("invoice_record")
    }


def test_g2_management_sap_reversal_migration_refuses_lossy_downgrade(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "g2-management-sap-reversal-downgrade-guard.sqlite"
    database_url = f"sqlite:///{database_path.as_posix()}"
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "20260824_0041")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO sap_suggestion "
                "(suggestion_id, store_id, version_no, is_current, suggested_sap_code, "
                "suggestion_note, suggestion_status, submitted_by, submitted_at, gmt_create) "
                "VALUES ('sap-downgrade-guard', 'store-1', 1, 1, 'SAP-001', "
                "'keep immutable history', 1, 'store-user', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )

    with pytest.raises(RuntimeError, match="cannot downgrade 20260824_0041.*SAP suggestions"):
        command.downgrade(config, "20260821_0040")
    with engine.begin() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM sap_suggestion")).scalar_one() == 1
        connection.execute(text("DELETE FROM sap_suggestion"))

    command.downgrade(config, "20260821_0040")


@pytest.mark.parametrize(
    ("revision", "target", "insert_sql", "error_match"),
    [
        (
            "20260821_0028",
            "20260819_0037",
            """
            INSERT INTO finance_import_batch
                (batch_id, import_type, statement_month, file_name,
                 file_sha256, normalized_sha256, read_version, current_version,
                 submitted_by)
            VALUES ('downgrade-guard-0028', 1, '2026-08', 'guard.csv',
                    'sha-file', 'sha-normalized', 1, 1, 'test-user')
            """,
            "cannot downgrade 20260821_0028.*finance facts",
        ),
        (
            "20260821_0031",
            "20260821_0030",
            """
            INSERT INTO promotion_invoice
                (invoice_id, store_id, invoice_number, invoice_date,
                 invoice_amount_cent, registered_by, registered_at,
                 gmt_create, gmt_modified)
            VALUES ('downgrade-guard-0031', 'store-1', '12345678901234567890',
                    '2026-08-01', 100, 'test-user', CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            "cannot downgrade 20260821_0031.*promotion invoice facts",
        ),
        (
            "20260821_0034",
            "20260821_0033",
            """
            INSERT INTO store_finance_profile
                (profile_id, store_id, profile_type, store_name_snapshot,
                 import_batch_id, gmt_create, gmt_modified)
            VALUES ('downgrade-guard-0034', 'store-1', 1, 'Test Store',
                    'batch-1', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            "cannot downgrade 20260821_0034.*profile facts",
        ),
        (
            "20260821_0038",
            "20260821_0037",
            """
            INSERT INTO settlement_carryforward_application
                (carryforward_application_id, carryforward_source_id,
                 target_statement_id, target_statement_version,
                 target_adjustment_id, target_posting_month, applied_by,
                 applied_at)
            VALUES ('downgrade-guard-0038', 'source-1', 'statement-1', 1,
                    'adjustment-1', '2026-08', 'test-user', CURRENT_TIMESTAMP)
            """,
            "cannot downgrade 20260821_0038.*carryforward facts",
        ),
    ],
)
def test_finance_foundation_downgrades_refuse_populated_facts(
    tmp_path: Path,
    revision: str,
    target: str,
    insert_sql: str,
    error_match: str,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite:///{(tmp_path / 'downgrade-guard.sqlite').as_posix()}"
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, revision)
    with create_engine(database_url).begin() as connection:
        connection.execute(text(insert_sql))

    with pytest.raises(RuntimeError, match=error_match):
        command.downgrade(config, target)


def test_finance_import_final_version_guard_migration_is_reversible(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "finance-import-final-version-guard.sqlite"
    database_url = f"sqlite:///{database_path.as_posix()}"
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "20260824_0041")
    command.upgrade(config, "20260824_0042")
    engine = create_engine(database_url)
    upgraded = inspect(engine)
    assert "uk_finance_import_batch_final_version" in {
        index["name"] for index in upgraded.get_indexes("finance_import_batch")
    }

    insert_sql = text(
        "INSERT INTO finance_import_batch "
        "(batch_id, import_type, statement_month, file_name, file_sha256, "
        "normalized_sha256, read_version, current_version, batch_status, "
        "total_rows, success_rows, error_rows, content_changed, submitted_by, "
        "submitted_at, gmt_create, gmt_modified) "
        "VALUES (:batch_id, 1, '2026-08', :file_name, :file_sha256, "
        ":normalized_sha256, 0, 1, :batch_status, 0, 0, 0, 0, 'admin', "
        ":occurred_at, :occurred_at, :occurred_at)"
    )
    values = {
        "file_sha256": "a" * 64,
        "normalized_sha256": "b" * 64,
        "occurred_at": datetime(2026, 8, 24, tzinfo=timezone.utc),
    }
    with engine.begin() as connection:
        connection.execute(
            insert_sql,
            {**values, "batch_id": "final-v1", "file_name": "final-v1.csv", "batch_status": 5},
        )
        connection.execute(
            insert_sql,
            {**values, "batch_id": "preview-a", "file_name": "preview-a.csv", "batch_status": 3},
        )
        connection.execute(
            insert_sql,
            {**values, "batch_id": "preview-b", "file_name": "preview-b.csv", "batch_status": 4},
        )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                insert_sql,
                {**values, "batch_id": "final-v1-duplicate", "file_name": "duplicate.csv", "batch_status": 8},
            )

    command.downgrade(config, "20260824_0041")
    downgraded = inspect(engine)
    assert "uk_finance_import_batch_final_version" not in {
        index["name"] for index in downgraded.get_indexes("finance_import_batch")
    }


def test_g3_statement_snapshot_migration_backfills_deterministically_and_tracks_exceptions(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "g3-statement-snapshot.sqlite"
    database_url = f"sqlite:///{database_path.as_posix()}"
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "20260824_0042")
    engine = create_engine(database_url)

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO finance_import_batch "
                "(batch_id, import_type, statement_month, file_name, file_sha256, "
                "normalized_sha256, read_version, current_version, batch_status, "
                "total_rows, success_rows, error_rows, content_changed, submitted_by, "
                "committed_by, submitted_at, committed_at, gmt_create, gmt_modified) "
                "VALUES ('snapshot-profile-batch', 1, '2026-08', 'profile.csv', "
                ":file_sha256, :normalized_sha256, 0, 1, 5, 2, 2, 0, 1, "
                "'admin', 'admin', :submitted_at, :committed_at, :submitted_at, :committed_at)"
            ),
            {
                "file_sha256": "c" * 64,
                "normalized_sha256": "d" * 64,
                "submitted_at": datetime(2026, 8, 1, 8, tzinfo=timezone.utc),
                "committed_at": datetime(2026, 8, 1, 9, tzinfo=timezone.utc),
            },
        )
        connection.execute(
            text(
                "INSERT INTO store_finance_profile "
                "(profile_id, store_id, profile_type, source_type, version_no, is_current, "
                "is_tombstone, store_name_snapshot, sap_code, import_batch_id, gmt_create, gmt_modified) "
                "VALUES "
                "('profile-v1', 'store-1', 1, 1, 1, 0, 0, 'Historical Store V1', "
                "'SAP-OLD', 'snapshot-profile-batch', :v1_at, :v1_at), "
                "('profile-v2', 'store-1', 1, 1, 2, 1, 1, 'Historical Store V2', "
                "NULL, 'snapshot-profile-batch', :v2_at, :v2_at)"
            ),
            {
                "v1_at": datetime(2026, 8, 1, 10, tzinfo=timezone.utc),
                "v2_at": datetime(2026, 8, 1, 11, tzinfo=timezone.utc),
            },
        )
        connection.execute(
            text(
                "INSERT INTO settlement_statement "
                "(statement_id, store_id, statement_month, version_no, is_current, gmt_create, gmt_modified) "
                "VALUES "
                "('statement-backfilled', 'store-1', '2026-08', 1, 1, :statement_at, :statement_at), "
                "('statement-unresolved', 'store-2', '2026-08', 1, 1, :statement_at, :statement_at), "
                "('statement-invalid-version-order', 'store-3', '2026-08', 1, 1, :statement_at, :statement_at)"
            ),
            {"statement_at": datetime(2026, 8, 2, 8, tzinfo=timezone.utc)},
        )
        connection.execute(
            text(
                "INSERT INTO dim_stores "
                "(store_id, store_name, is_active, created_at, updated_at) VALUES "
                "('sale-store-historical', 'Historical Sale Store', 1, :at, :at), "
                "('verify-store-historical', 'Historical Verify Store', 1, :at, :at)"
            ),
            {"at": datetime(2026, 8, 1, 8, tzinfo=timezone.utc)},
        )
        connection.execute(
            text(
                "INSERT INTO dim_sku_product_rules "
                "(sku_id, sku_name, product_name, product_scope, product_type, "
                "is_service_product, is_active_product, commission_rate, gmt_create, gmt_modified) "
                "VALUES ('sku-snapshot-history', 'Historical SKU', 'Historical Product', "
                "'service', 'maintenance', 1, 1, 0.1000, :at, :at)"
            ),
            {"at": datetime(2026, 8, 1, 8, tzinfo=timezone.utc)},
        )
        connection.execute(
            text(
                "INSERT INTO raw_douyin_orders "
                "(order_id, order_status, order_status_normalized, sku_id, product_name, "
                "sale_time, sale_channel, sale_channel_normalized, raw_payload, created_at, updated_at) "
                "VALUES ('order-snapshot-history', 'completed', 'COMPLETED', "
                "'sku-snapshot-history', 'Historical Product', :sale_time, "
                "'short_video', 'short_video', '{}', :created_at, :created_at)"
            ),
            {
                "sale_time": datetime(2026, 7, 31, 8, tzinfo=timezone.utc),
                "created_at": datetime(2026, 8, 1, 8, tzinfo=timezone.utc),
            },
        )
        connection.execute(
            text(
                "INSERT INTO raw_douyin_order_coupons "
                "(coupon_id, order_id, raw_order_id, coupon_status, "
                "coupon_status_normalized, coupon_paid_amount_cent, raw_payload) "
                "SELECT 'coupon-snapshot-history', 'order-snapshot-history', id, "
                "'used', 'USED', 11000, '{}' FROM raw_douyin_orders "
                "WHERE order_id = 'order-snapshot-history'"
            )
        )
        connection.execute(
            text(
                "INSERT INTO raw_douyin_verify_records "
                "(verify_id, coupon_id, verify_status, verify_time, poi_id, "
                "verify_store_name_raw, sku_id, product_name, paid_amount_cent, raw_payload) "
                "VALUES ('verify-snapshot-history', 'coupon-snapshot-history', "
                "'used', :verify_time, 'poi-history', 'Historical Verify Store', "
                "'sku-snapshot-history', 'Historical Product', 11000, '{}')"
            ),
            {"verify_time": datetime(2026, 8, 1, 9, tzinfo=timezone.utc)},
        )
        connection.execute(
            text(
                "INSERT INTO settlement_fee_result "
                "(fee_result_id, coupon_id, order_id, fee_direction, result_version, "
                "original_business_month, rule_match_date, sale_store_id, verify_store_id, "
                "sku_id, product_scope, product_type, sale_channel_normalized, "
                "source_amount_cent, refunded_amount_cent, fee_base_cent, fee_rate, "
                "fee_amount_cent, rule_version, scope_rule_version, result_status, "
                "calculation_run_id, calculated_at) "
                "VALUES ('fee-result-snapshot-history', 'coupon-snapshot-history', "
                "'order-snapshot-history', 1, 1, '2026-08', '2026-08-01', "
                "'sale-store-historical', 'verify-store-historical', "
                "'sku-snapshot-history', 'service', 'maintenance', 'short_video', "
                "11000, 0, 11000, 0.100000, 1100, 'rule-history', 'scope-history', "
                "1, 'run-history', :calculated_at)"
            ),
            {"calculated_at": datetime(2026, 8, 1, 10, tzinfo=timezone.utc)},
        )
        connection.execute(
            text(
                "INSERT INTO settlement_statement_line "
                "(statement_line_id, statement_id, fee_direction, product_scope, "
                "product_type, original_entry_count, adjustment_entry_count, "
                "original_base_cent, adjustment_base_cent, net_base_cent, "
                "original_fee_cent, adjustment_fee_cent, net_fee_cent) "
                "VALUES ('line-snapshot-history', 'statement-backfilled', 1, "
                "'service', 'maintenance', 1, 0, 11000, 0, 11000, 1100, 0, 1100)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO settlement_statement_line "
                "(statement_line_id, statement_id, fee_direction, product_scope, "
                "product_type, original_entry_count, adjustment_entry_count, "
                "original_base_cent, adjustment_base_cent, net_base_cent, "
                "original_fee_cent, adjustment_fee_cent, net_fee_cent) "
                "VALUES ('line-snapshot-missing', 'statement-unresolved', 1, "
                "'service', 'maintenance', 1, 0, 5000, 0, 5000, 500, 0, 500)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO settlement_statement_entry "
                "(statement_entry_id, statement_id, statement_line_id, source_type, "
                "source_record_id, original_fee_result_id, coupon_id, order_id, "
                "fee_direction, original_business_month, statement_posting_month, "
                "product_scope, product_type, base_amount_cent, fee_amount_cent, rule_version) "
                "VALUES ('entry-snapshot-history', 'statement-backfilled', "
                "'line-snapshot-history', 1, 'fee-result-snapshot-history', "
                "'fee-result-snapshot-history', 'coupon-snapshot-history', "
                "'order-snapshot-history', 1, '2026-08', '2026-08', "
                "'service', 'maintenance', 11000, 1100, 'rule-history')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO settlement_statement_entry "
                "(statement_entry_id, statement_id, statement_line_id, source_type, "
                "source_record_id, original_fee_result_id, coupon_id, order_id, "
                "fee_direction, original_business_month, statement_posting_month, "
                "product_scope, product_type, base_amount_cent, fee_amount_cent, rule_version) "
                "VALUES ('entry-snapshot-missing', 'statement-unresolved', "
                "'line-snapshot-missing', 1, 'missing-fee-result', "
                "'missing-fee-result', 'missing-coupon', 'missing-order', 1, "
                "'2026-08', '2026-08', 'service', 'maintenance', 5000, 500, 'rule-missing')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO store_finance_profile "
                "(profile_id, store_id, profile_type, source_type, version_no, is_current, "
                "is_tombstone, store_name_snapshot, sap_code, gmt_create, gmt_modified) "
                "VALUES "
                "('invalid-version-v2', 'store-3', 1, 1, 2, 1, 0, 'Invalid V2', 'SAP-2', :v2_at, :v2_at), "
                "('invalid-version-v1', 'store-3', 1, 1, 1, 0, 0, 'Invalid V1', 'SAP-1', :v1_at, :v1_at)"
            ),
            {
                "v1_at": datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
                "v2_at": datetime(2026, 8, 1, 11, tzinfo=timezone.utc),
            },
        )

    command.upgrade(config, "20260824_0043")
    upgraded = inspect(engine)
    assert {
        "store_name_snapshot",
        "sap_code_snapshot",
        "store_snapshot_status",
        "store_snapshot_profile_id",
    }.issubset(
        {column["name"] for column in upgraded.get_columns("settlement_statement")}
    )
    assert {
        "settlement_statement_snapshot_migration_exception",
        "settlement_statement_entry_snapshot_migration_exception",
    }.issubset(upgraded.get_table_names())
    with engine.begin() as connection:
        backfilled = connection.execute(
            text(
                "SELECT store_name_snapshot, sap_code_snapshot, store_snapshot_status, "
                "store_snapshot_profile_id FROM settlement_statement "
                "WHERE statement_id = 'statement-backfilled'"
            )
        ).mappings().one()
        assert backfilled == {
            "store_name_snapshot": "Historical Store V2",
            "sap_code_snapshot": None,
            "store_snapshot_status": "BACKFILLED_PROFILE",
            "store_snapshot_profile_id": "profile-v2",
        }
        entry_snapshot = connection.execute(
            text(
                "SELECT order_status_snapshot, coupon_status_snapshot, "
                "product_name_snapshot, sku_id_snapshot, sale_channel_snapshot, "
                "sale_store_id_snapshot, sale_store_snapshot, verify_store_id_snapshot, "
                "verify_store_snapshot, received_amount_cent_snapshot, fee_rate_snapshot "
                "FROM settlement_statement_entry "
                "WHERE statement_entry_id = 'entry-snapshot-history'"
            )
        ).mappings().one()
        assert entry_snapshot == {
            "order_status_snapshot": "COMPLETED",
            "coupon_status_snapshot": "USED",
            "product_name_snapshot": "Historical Product",
            "sku_id_snapshot": "sku-snapshot-history",
            "sale_channel_snapshot": "short_video",
            "sale_store_id_snapshot": "sale-store-historical",
            "sale_store_snapshot": "Historical Sale Store",
            "verify_store_id_snapshot": "verify-store-historical",
            "verify_store_snapshot": "Historical Verify Store",
            "received_amount_cent_snapshot": 11000,
            "fee_rate_snapshot": 0.1,
        }
        unresolved = connection.execute(
            text(
                "SELECT store_snapshot_status FROM settlement_statement "
                "WHERE statement_id = 'statement-unresolved'"
            )
        ).scalar_one()
        assert unresolved == "UNRESOLVED"
        invalid_version = connection.execute(
            text(
                "SELECT store_snapshot_status FROM settlement_statement "
                "WHERE statement_id = 'statement-invalid-version-order'"
            )
        ).scalar_one()
        assert invalid_version == "UNRESOLVED"
        exceptions = connection.execute(
            text(
                "SELECT statement_id, reason_code, resolved_at "
                "FROM settlement_statement_snapshot_migration_exception "
                "ORDER BY statement_id"
            )
        ).mappings().all()
        assert exceptions == [
            {
                "statement_id": "statement-invalid-version-order",
                "reason_code": "INVALID_PROFILE_VERSION_ORDER",
                "resolved_at": None,
            },
            {
                "statement_id": "statement-unresolved",
                "reason_code": "NO_PRIOR_BASIC_PROFILE",
                "resolved_at": None,
            },
        ]
        entry_exceptions = connection.execute(
            text(
                "SELECT statement_entry_id, statement_id, reason_code, resolved_at "
                "FROM settlement_statement_entry_snapshot_migration_exception"
            )
        ).mappings().all()
        assert entry_exceptions == [
            {
                "statement_entry_id": "entry-snapshot-missing",
                "statement_id": "statement-unresolved",
                "reason_code": "MISSING_REQUIRED_ENTRY_SNAPSHOT",
                "resolved_at": None,
            }
        ]

        # Local release-gate fixture: once historical evidence is supplied and
        # every exception is explicitly resolved, the unresolved count reaches zero.
        connection.execute(
            text(
                "UPDATE settlement_statement SET "
                "store_name_snapshot = CASE statement_id "
                "WHEN 'statement-unresolved' THEN 'Recovered Store 2' ELSE 'Invalid V2' END, "
                "sap_code_snapshot = CASE statement_id "
                "WHEN 'statement-unresolved' THEN NULL ELSE 'SAP-2' END, "
                "store_snapshot_status = 'BACKFILLED_PROFILE', "
                "store_snapshot_profile_id = CASE statement_id "
                "WHEN 'statement-unresolved' THEN NULL ELSE 'invalid-version-v2' END "
                "WHERE statement_id IN ('statement-unresolved', 'statement-invalid-version-order')"
            )
        )
        connection.execute(
            text(
                "UPDATE settlement_statement_snapshot_migration_exception "
                "SET resolved_at = CURRENT_TIMESTAMP, "
                "resolution_note = 'fixture evidence reviewed and backfilled', "
                "gmt_modified = CURRENT_TIMESTAMP WHERE resolved_at IS NULL"
            )
        )
        connection.execute(
            text(
                "UPDATE settlement_statement_entry_snapshot_migration_exception "
                "SET resolved_at = CURRENT_TIMESTAMP, "
                "resolution_note = 'fixture entry evidence reviewed', "
                "gmt_modified = CURRENT_TIMESTAMP WHERE resolved_at IS NULL"
            )
        )
        assert connection.execute(
            text(
                "SELECT "
                "(SELECT COUNT(*) FROM settlement_statement_snapshot_migration_exception "
                " WHERE resolved_at IS NULL) + "
                "(SELECT COUNT(*) FROM settlement_statement_entry_snapshot_migration_exception "
                " WHERE resolved_at IS NULL)"
            )
        ).scalar_one() == 0

    with pytest.raises(RuntimeError, match="cannot downgrade 20260824_0043.*snapshot"):
        command.downgrade(config, "20260824_0042")
    still_upgraded = inspect(engine)
    assert "settlement_statement_snapshot_migration_exception" in still_upgraded.get_table_names()
    assert "store_name_snapshot" in {
        column["name"] for column in still_upgraded.get_columns("settlement_statement")
    }


def test_g3_statement_snapshot_migration_empty_schema_is_reversible(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "g3-empty-downgrade.sqlite"
    database_url = f"sqlite:///{database_path.as_posix()}"
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "20260824_0043")
    command.downgrade(config, "20260824_0042")

    downgraded = inspect(create_engine(database_url))
    assert "settlement_statement_snapshot_migration_exception" not in downgraded.get_table_names()
    assert "store_name_snapshot" not in {
        column["name"] for column in downgraded.get_columns("settlement_statement")
    }


def test_finance_import_final_version_guard_postgresql_ddl() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    output = StringIO()
    config = Config(str(repo_root / "alembic.ini"), output_buffer=output)
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option(
        "sqlalchemy.url", "postgresql+psycopg://user:pass@localhost/test"
    )

    command.upgrade(config, "20260824_0041:20260824_0042", sql=True)

    ddl = output.getvalue()
    assert "CREATE UNIQUE INDEX uk_finance_import_batch_final_version" in ddl
    assert "WHERE batch_status IN (5, 8, 9)" in ddl


def test_finance_import_final_version_guard_serializes_sqlite_writers(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "finance-import-final-version-concurrency.sqlite"
    database_url = f"sqlite:///{database_path.as_posix()}"
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "20260824_0042")
    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    barrier = Barrier(2)
    insert_sql = text(
        "INSERT INTO finance_import_batch "
        "(batch_id, import_type, statement_month, file_name, file_sha256, "
        "normalized_sha256, read_version, current_version, batch_status, "
        "total_rows, success_rows, error_rows, content_changed, submitted_by, "
        "submitted_at, gmt_create, gmt_modified) "
        "VALUES (:batch_id, 2, '2026-09', :file_name, :file_sha256, "
        ":normalized_sha256, 0, 1, 5, 0, 0, 0, 0, 'admin', "
        ":occurred_at, :occurred_at, :occurred_at)"
    )

    def finalize(batch_id: str) -> str:
        barrier.wait()
        try:
            with engine.begin() as connection:
                connection.execute(
                    insert_sql,
                    {
                        "batch_id": batch_id,
                        "file_name": f"{batch_id}.csv",
                        "file_sha256": "c" * 64,
                        "normalized_sha256": "d" * 64,
                        "occurred_at": datetime(2026, 8, 24, tzinfo=timezone.utc),
                    },
                )
            return "COMMITTED"
        except IntegrityError:
            return "VERSION_CONFLICT"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = sorted(executor.map(finalize, ["concurrent-a", "concurrent-b"]))

    assert results == ["COMMITTED", "VERSION_CONFLICT"]
    with engine.connect() as connection:
        assert connection.execute(
            text(
                "SELECT COUNT(*) FROM finance_import_batch "
                "WHERE import_type = 2 AND statement_month = '2026-09' "
                "AND current_version = 1 AND batch_status IN (5, 8, 9)"
            )
        ).scalar_one() == 1


def test_dispute_idempotency_migration_is_reversible(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "dispute-idempotency.sqlite"
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")

    command.upgrade(config, "20260821_0031")
    command.upgrade(config, "20260821_0032")

    upgraded = inspect(create_engine(f"sqlite:///{database_path.as_posix()}"))
    assert {"idempotency_key_hash", "request_payload_sha256"}.issubset(
        {column["name"] for column in upgraded.get_columns("settlement_dispute")}
    )
    assert {"idempotency_key_hash", "request_payload_sha256"}.issubset(
        {column["name"] for column in upgraded.get_columns("finance_operation_audit")}
    )
    assert "uk_settlement_dispute_idempotency_key" in {
        constraint["name"]
        for constraint in upgraded.get_unique_constraints("settlement_dispute")
    }

    command.downgrade(config, "20260821_0031")
    downgraded = inspect(create_engine(f"sqlite:///{database_path.as_posix()}"))
    assert "idempotency_key_hash" not in {
        column["name"] for column in downgraded.get_columns("settlement_dispute")
    }


def test_finance_import_result_migrations_are_reversible(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "finance-import-results.sqlite"
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")

    command.upgrade(config, "20260821_0032")
    command.upgrade(config, "20260821_0036")

    upgraded = inspect(create_engine(f"sqlite:///{database_path.as_posix()}"))
    assert "store_finance_profile" in upgraded.get_table_names()
    assert {"factory_deduction_date", "factory_deduction_amount_cent"}.issubset(
        {column["name"] for column in upgraded.get_columns("invoice_record")}
    )
    assert {"result_reason", "business_date", "business_amount_cent"}.issubset(
        {column["name"] for column in upgraded.get_columns("invoice_status_event")}
    )
    assert "idx_promotion_invoice_current_number" in {
        index["name"] for index in upgraded.get_indexes("promotion_invoice")
    }
    assert {
        "upload_idempotency_key_hash",
        "upload_request_payload_sha256",
    }.issubset(
        {column["name"] for column in upgraded.get_columns("finance_import_batch")}
    )

    command.downgrade(config, "20260821_0032")
    downgraded = inspect(create_engine(f"sqlite:///{database_path.as_posix()}"))
    assert "store_finance_profile" not in downgraded.get_table_names()
    assert "factory_deduction_date" not in {
        column["name"] for column in downgraded.get_columns("invoice_record")
    }
    assert "business_date" not in {
        column["name"] for column in downgraded.get_columns("invoice_status_event")
    }


def test_promotion_invoice_registration_facts_migration_is_reversible_and_backfills(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "promotion-invoice-registration-facts.sqlite"
    database_url = f"sqlite:///{database_path.as_posix()}"
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "20260821_0036")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO promotion_invoice (
                    invoice_id, store_id, version_no, is_current,
                    invoice_number, invoice_date, invoice_amount_cent,
                    invoice_status, registered_by, registered_at,
                    gmt_create, gmt_modified
                ) VALUES (
                    'legacy-promotion-invoice', 'store-1', 1, 1,
                    '12345678901234567890', '2026-10-10', 1100,
                    2, 'legacy-user', '2026-10-10 15:59:59+00:00',
                    '2026-10-10 15:59:59+00:00', '2026-10-10 15:59:59+00:00'
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO promotion_invoice_allocation (
                    allocation_id, invoice_id, store_id, statement_id,
                    statement_month, allocated_amount_cent, is_current,
                    gmt_create, gmt_modified
                ) VALUES (
                    'legacy-promotion-allocation', 'legacy-promotion-invoice',
                    'store-1', 'statement-1', '2026-08', 1100, 1,
                    '2026-10-10 15:59:59+00:00', '2026-10-10 15:59:59+00:00'
                )
                """
            )
        )

    command.upgrade(config, "20260821_0037")
    upgraded = inspect(engine)
    assert {"buyer_name", "tax_rate_percent"}.issubset(
        {column["name"] for column in upgraded.get_columns("promotion_invoice")}
    )
    assert "settlement_batch_month" in {
        column["name"]
        for column in upgraded.get_columns("promotion_invoice_allocation")
    }
    with engine.connect() as connection:
        invoice_facts = connection.execute(
            text(
                "SELECT buyer_name, tax_rate_percent FROM promotion_invoice "
                "WHERE invoice_id = 'legacy-promotion-invoice'"
            )
        ).one()
        allocation_batch = connection.execute(
            text(
                "SELECT settlement_batch_month FROM promotion_invoice_allocation "
                "WHERE allocation_id = 'legacy-promotion-allocation'"
            )
        ).scalar_one()
    assert invoice_facts == ("比亚迪汽车销售有限公司", 6)
    assert allocation_batch == "2026-09"

    command.downgrade(config, "20260821_0036")
    downgraded = inspect(engine)
    assert "buyer_name" not in {
        column["name"] for column in downgraded.get_columns("promotion_invoice")
    }
    assert "settlement_batch_month" not in {
        column["name"]
        for column in downgraded.get_columns("promotion_invoice_allocation")
    }


def test_settlement_carryforward_migration_is_reversible(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "settlement-carryforward.sqlite"
    database_url = f"sqlite:///{database_path.as_posix()}"
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "20260821_0037")
    command.upgrade(config, "20260821_0038")

    upgraded = inspect(create_engine(database_url))
    assert {
        "settlement_carryforward_source",
        "settlement_carryforward_application",
    }.issubset(upgraded.get_table_names())
    assert "uk_settlement_carryforward_source_business" in {
        constraint["name"]
        for constraint in upgraded.get_unique_constraints(
            "settlement_carryforward_source"
        )
    }
    assert "idx_settlement_carryforward_application_current" in {
        index["name"]
        for index in upgraded.get_indexes("settlement_carryforward_application")
    }
    assert "ck_settlement_carryforward_source_event_reference" in {
        constraint["name"]
        for constraint in upgraded.get_check_constraints(
            "settlement_carryforward_source"
        )
    }

    command.downgrade(config, "20260821_0037")
    downgraded = inspect(create_engine(database_url))
    assert "settlement_carryforward_source" not in downgraded.get_table_names()
    assert "settlement_carryforward_application" not in downgraded.get_table_names()


def test_promotion_invoice_lifecycle_migration_backfills_and_reverses(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "promotion-invoice-lifecycle.sqlite"
    database_url = f"sqlite:///{database_path.as_posix()}"
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "20260821_0038")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO promotion_invoice "
                "(invoice_id, store_id, version_no, is_current, invoice_number, "
                "invoice_date, invoice_amount_cent, buyer_name, tax_rate_percent, "
                "invoice_status, registered_by, registered_at, supersedes_invoice_id, "
                "gmt_create, gmt_modified) VALUES "
                "('invoice-backfill-v1', 'store-1', 1, 0, '81345678901234567890', "
                "'2026-08-10', 1100, '比亚迪汽车销售有限公司', 6, 2, 'store-user', "
                "'2026-08-10 00:00:00', NULL, '2026-08-10 00:00:00', '2026-08-10 00:00:00'), "
                "('invoice-backfill-v2', 'store-1', 2, 1, '81345678901234567890', "
                "'2026-08-10', 1100, '比亚迪汽车销售有限公司', 6, 3, 'store-user', "
                "'2026-08-21 00:00:00', 'invoice-backfill-v1', "
                "'2026-08-21 00:00:00', '2026-08-21 00:00:00')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO promotion_invoice "
                "(invoice_id, store_id, version_no, is_current, invoice_number, "
                "invoice_date, invoice_amount_cent, buyer_name, tax_rate_percent, "
                "invoice_status, registered_by, registered_at, supersedes_invoice_id, "
                "gmt_create, gmt_modified) VALUES "
                "('invoice-missing-parent', 'store-1', 2, 1, '83345678901234567890', "
                "'2026-08-12', 800, '比亚迪汽车销售有限公司', 6, 3, 'store-user', "
                "'2026-08-12 00:00:00', 'invoice-parent-not-present', "
                "'2026-08-12 00:00:00', '2026-08-12 00:00:00')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO promotion_invoice "
                "(invoice_id, store_id, version_no, is_current, invoice_number, "
                "invoice_date, invoice_amount_cent, buyer_name, tax_rate_percent, "
                "invoice_status, registered_by, registered_at, gmt_create, gmt_modified) VALUES "
                "('invoice-ambiguous-a', 'store-1', 1, 0, '82345678901234567890', "
                "'2026-08-10', 900, '比亚迪汽车销售有限公司', 6, 2, 'store-user', "
                "'2026-08-10 00:00:00', '2026-08-10 00:00:00', '2026-08-10 00:00:00'), "
                "('invoice-ambiguous-b', 'store-1', 1, 0, '82345678901234567890', "
                "'2026-08-11', 900, '比亚迪汽车销售有限公司', 6, 2, 'store-user', "
                "'2026-08-11 00:00:00', '2026-08-11 00:00:00', '2026-08-11 00:00:00')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO promotion_invoice "
                "(invoice_id, store_id, version_no, is_current, invoice_number, "
                "invoice_date, invoice_amount_cent, buyer_name, tax_rate_percent, "
                "invoice_status, registered_by, registered_at, supersedes_invoice_id, "
                "gmt_create, gmt_modified) VALUES "
                "('invoice-invalid-current-v1', 'store-1', 1, 1, '84345678901234567890', "
                "'2026-08-10', 700, 'BYD', 6, 2, 'store-user', "
                "'2026-08-10 00:00:00', NULL, '2026-08-10 00:00:00', '2026-08-10 00:00:00'), "
                "('invoice-invalid-current-v2', 'store-1', 2, 0, '84345678901234567890', "
                "'2026-08-10', 700, 'BYD', 6, 3, 'store-user', "
                "'2026-08-21 00:00:00', 'invoice-invalid-current-v1', "
                "'2026-08-21 00:00:00', '2026-08-21 00:00:00')"
            )
        )

    command.upgrade(config, "20260821_0039")
    upgraded = inspect(engine)
    assert {
        "promotion_invoice_lifecycle_event",
        "promotion_invoice_number_registry",
        "promotion_invoice_lifecycle_migration_exception",
        "promotion_invoice_replacement_source",
    }.issubset(upgraded.get_table_names())
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT physical_invoice_id, version_kind FROM promotion_invoice "
                "WHERE invoice_number = '81345678901234567890' ORDER BY version_no"
            )
        ).all()
        ambiguous_rows = connection.execute(
            text(
                "SELECT physical_invoice_id FROM promotion_invoice "
                "WHERE invoice_number = '82345678901234567890' ORDER BY invoice_id"
            )
        ).all()
        registry_count = connection.execute(
            text("SELECT COUNT(*) FROM promotion_invoice_number_registry")
        ).scalar_one()
        exception_count = connection.execute(
            text(
                "SELECT COUNT(*) FROM promotion_invoice_lifecycle_migration_exception "
                "WHERE reason_code = 'AMBIGUOUS_INVOICE_VERSION_CHAIN'"
            )
        ).scalar_one()
        missing_parent_exception_count = connection.execute(
            text(
                "SELECT COUNT(*) FROM promotion_invoice_lifecycle_migration_exception "
                "WHERE invoice_id = 'invoice-missing-parent' "
                "AND reason_code = 'AMBIGUOUS_INVOICE_VERSION_CHAIN'"
            )
        ).scalar_one()
    assert rows[0][0] == rows[1][0]
    assert [row[1] for row in rows] == [1, 2]
    assert registry_count == 1
    assert ambiguous_rows[0][0] != ambiguous_rows[1][0]
    assert exception_count == 5
    assert missing_parent_exception_count == 1

    command.downgrade(config, "20260821_0038")
    downgraded = inspect(engine)
    assert "promotion_invoice_lifecycle_event" not in downgraded.get_table_names()
    assert "physical_invoice_id" not in {
        column["name"] for column in downgraded.get_columns("promotion_invoice")
    }


def test_promotion_invoice_negative_allocation_migration_is_reversible(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "promotion-invoice-negative-allocation.sqlite"
    database_url = f"sqlite:///{database_path.as_posix()}"
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "20260821_0039")
    engine = create_engine(database_url)

    command.upgrade(config, "20260821_0040")
    upgraded = inspect(engine)
    assert "ck_promotion_invoice_allocation_amount" not in {
        constraint["name"]
        for constraint in upgraded.get_check_constraints(
            "promotion_invoice_allocation"
        )
    }
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO promotion_invoice_allocation "
                "(allocation_id, invoice_id, store_id, statement_id, "
                "statement_month, settlement_batch_month, allocated_amount_cent, "
                "is_current, gmt_create, gmt_modified) VALUES "
                "('negative-allocation', 'invoice-negative', 'store-1', "
                "'statement-negative', '2026-10', '2026-12', -150, 1, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )

    with pytest.raises(
        RuntimeError,
        match="negative promotion invoice allocations exist",
    ):
        command.downgrade(config, "20260821_0039")
    with engine.connect() as connection:
        assert connection.execute(
            text(
                "SELECT allocated_amount_cent FROM promotion_invoice_allocation "
                "WHERE allocation_id = 'negative-allocation'"
            )
        ).scalar_one() == -150

    with engine.begin() as connection:
        connection.execute(
            text(
                "DELETE FROM promotion_invoice_allocation "
                "WHERE allocation_id = 'negative-allocation'"
            )
        )

    command.downgrade(config, "20260821_0039")
    downgraded = inspect(engine)
    assert "ck_promotion_invoice_allocation_amount" in {
        constraint["name"]
        for constraint in downgraded.get_check_constraints(
            "promotion_invoice_allocation"
        )
    }


def test_promotion_invoice_lifecycle_migration_refuses_lossy_downgrade(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "promotion-invoice-lifecycle-downgrade-guard.sqlite"
    database_url = f"sqlite:///{database_path.as_posix()}"
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "20260821_0039")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO promotion_invoice_lifecycle_event "
                "(lifecycle_event_id, physical_invoice_id, invoice_id, invoice_version, "
                "event_type, reason, read_version, is_current, operator_id, "
                "idempotency_key_hash, request_payload_sha256, occurred_at, gmt_create) "
                "VALUES ('event-downgrade-guard', 'physical-downgrade-guard', "
                "'invoice-downgrade-guard', 1, 2, 'external void', 1, 1, "
                "'store-user', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', "
                "'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )

    with pytest.raises(RuntimeError, match="lifecycle or replacement facts exist"):
        command.downgrade(config, "20260821_0038")
    with engine.begin() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM promotion_invoice_lifecycle_event")
        ).scalar_one() == 1
        connection.execute(text("DELETE FROM promotion_invoice_lifecycle_event"))
        connection.execute(
            text(
                "INSERT INTO promotion_invoice "
                "(invoice_id, physical_invoice_id, store_id, version_no, version_kind, "
                "is_current, replaces_invoice_id, invoice_number, invoice_date, "
                "invoice_amount_cent, buyer_name, tax_rate_percent, invoice_status, "
                "registered_by, registered_at, gmt_create, gmt_modified) VALUES "
                "('replacement-pointer-only', 'physical-pointer-only', 'store-1', "
                "1, 1, 1, 'missing-source-link', '85345678901234567890', "
                "'2026-08-21', 100, 'BYD', 6, 2, 'store-user', CURRENT_TIMESTAMP, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )

    with pytest.raises(RuntimeError, match="lifecycle or replacement facts exist"):
        command.downgrade(config, "20260821_0038")
    with engine.begin() as connection:
        assert connection.execute(
            text(
                "SELECT replaces_invoice_id FROM promotion_invoice "
                "WHERE invoice_id = 'replacement-pointer-only'"
            )
        ).scalar_one() == "missing-source-link"
        connection.execute(
            text(
                "UPDATE promotion_invoice SET replaces_invoice_id = NULL "
                "WHERE invoice_id = 'replacement-pointer-only'"
            )
        )

    command.downgrade(config, "20260821_0038")
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


def test_finance_closure_migration_creates_versioned_tables(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "finance-closure.sqlite"
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")

    command.upgrade(config, "head")

    upgraded = inspect(create_engine(config.get_main_option("sqlalchemy.url")))
    assert {
        "settlement_statement_confirmation",
        "settlement_dispute",
        "settlement_dispute_order",
        "invoice_record",
        "invoice_status_event",
        "finance_import_batch",
        "finance_import_row",
        "finance_operation_audit",
    }.issubset(upgraded.get_table_names())
    assert "idx_invoice_record_current_slot" in {
        index["name"] for index in upgraded.get_indexes("invoice_record")
    }
    assert "idx_promotion_invoice_current_number" in {
        index["name"] for index in upgraded.get_indexes("promotion_invoice")
    }
    assert "uk_promotion_invoice_number" not in {
        constraint["name"]
        for constraint in upgraded.get_unique_constraints("promotion_invoice")
    }


def test_statement_versioning_migration_preserves_and_versions_snapshots(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "statement-versioning.sqlite"
    database_url = f"sqlite:///{database_path.as_posix()}"
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "20260821_0028")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO settlement_statement (
                    statement_id, store_id, statement_month
                ) VALUES ('statement-v1', 'store-001', '2026-08')
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO settlement_statement_entry (
                    statement_entry_id, statement_id, statement_line_id,
                    source_type, source_record_id, original_fee_result_id,
                    coupon_id, order_id, fee_direction, original_business_month,
                    statement_posting_month, product_scope, product_type,
                    base_amount_cent, fee_amount_cent, rule_version
                ) VALUES (
                    'entry-v1', 'statement-v1', 'line-v1',
                    1, 'fee-result-001', 'fee-result-001',
                    'coupon-001', 'order-001', 1, '2026-08',
                    '2026-08', '', '', 10000, 800, 'rule-v1'
                )
                """
            )
        )

    command.upgrade(config, "20260821_0030")
    inspector = inspect(create_engine(database_url))
    statement_columns = {
        column["name"] for column in inspector.get_columns("settlement_statement")
    }
    statement_constraints = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("settlement_statement")
    }
    entry_constraints = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("settlement_statement_entry")
    }
    confirmation_columns = {
        column["name"]
        for column in inspector.get_columns("settlement_statement_confirmation")
    }
    confirmation_constraints = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints(
            "settlement_statement_confirmation"
        )
    }

    assert {"version_no", "is_current", "supersedes_statement_id"}.issubset(
        statement_columns
    )
    assert ("store_id", "statement_month", "version_no") in statement_constraints
    assert ("store_id", "statement_month") not in statement_constraints
    assert ("statement_id", "source_type", "source_record_id") in entry_constraints
    assert {"idempotency_key_hash", "request_payload_sha256"}.issubset(
        confirmation_columns
    )
    assert ("idempotency_key_hash",) in confirmation_constraints
    with engine.connect() as connection:
        version_one = connection.execute(
            text(
                """
                SELECT version_no, is_current
                FROM settlement_statement
                WHERE statement_id = 'statement-v1'
                """
            )
        ).one()
    assert version_one == (1, 1)

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE settlement_statement
                SET is_current = 0
                WHERE statement_id = 'statement-v1'
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO settlement_statement (
                    statement_id, store_id, statement_month, version_no,
                    is_current, supersedes_statement_id
                ) VALUES (
                    'statement-v2', 'store-001', '2026-08', 2,
                    1, 'statement-v1'
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO settlement_statement_entry (
                    statement_entry_id, statement_id, statement_line_id,
                    source_type, source_record_id, original_fee_result_id,
                    coupon_id, order_id, fee_direction, original_business_month,
                    statement_posting_month, product_scope, product_type,
                    base_amount_cent, fee_amount_cent, rule_version
                ) VALUES (
                    'entry-v2', 'statement-v2', 'line-v2',
                    1, 'fee-result-001', 'fee-result-001',
                    'coupon-001', 'order-001', 1, '2026-08',
                    '2026-08', '', '', 10000, 800, 'rule-v1'
                )
                """
            )
        )

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO settlement_statement (
                        statement_id, store_id, statement_month, version_no,
                        is_current
                    ) VALUES (
                        'statement-v3', 'store-001', '2026-08', 3, 1
                    )
                """
            )
        )

    with pytest.raises(
        RuntimeError,
        match="(?:version history exists|statement snapshot or exception facts exist)",
    ):
        command.downgrade(config, "20260821_0028")

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                DELETE FROM settlement_statement_entry
                WHERE statement_id = 'statement-v2'
                """
            )
        )
        connection.execute(
            text(
                """
                DELETE FROM settlement_statement
                WHERE statement_id = 'statement-v2'
                """
            )
        )
        connection.execute(
            text(
                """
                UPDATE settlement_statement
                SET is_current = 1
                WHERE statement_id = 'statement-v1'
                """
            )
        )

    command.downgrade(config, "20260821_0028")
    downgraded = inspect(create_engine(database_url))
    downgraded_statement_columns = {
        column["name"] for column in downgraded.get_columns("settlement_statement")
    }
    assert not {"version_no", "is_current", "supersedes_statement_id"}.intersection(
        downgraded_statement_columns
    )
