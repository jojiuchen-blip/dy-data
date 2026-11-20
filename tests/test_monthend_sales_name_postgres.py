"""Real PostgreSQL persistence and additive migration of monthly name evidence."""
import json

from alembic import command
import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import sessionmaker

from apps.api.dy_api.models import RawDouyinOrder, RawDouyinVerifyRecord, SettlementFeeResult
from apps.worker import account_qualification as q, settlement
from account_qualification_fixtures import seed_month_qualification
from test_dashboard_publication_migration import full_pg_stack
from test_data_settlement import _add_scope_rule, _dual_time, _load_dual_fee_fixture


def _insert_0069_name_evidence(session, version):
    """Seed the immutable 0069 record shape without running newer algorithms."""
    evidence = {
        "policy": "settlement-monthend-sale-name-v1",
        "qualification_version_id": version.version_id,
        "content_sha256": version.content_sha256,
        "source_field": "owner_account_name",
        "account_name": "Owner Dual", "account_id": "owner-dual", "douyin_id": "dy-owner",
        "poi_ids": ["poi-sale"], "store_id": "store-sale",
    }
    for direction, rate, amount in ((1, "0.300000", 3000), (2, "0.200000", 2000)):
        session.execute(text("""
            INSERT INTO settlement_fee_result (
                fee_result_id, coupon_id, order_id, fee_direction, result_version,
                original_business_month, rule_match_date, sale_store_id, verify_store_id,
                sku_id, product_scope, product_type, sale_channel_normalized,
                source_amount_cent, refunded_amount_cent, fee_base_cent, fee_rate, fee_amount_cent,
                rule_version, scope_rule_version, result_status, calculation_run_id,
                account_qualification_version_id, sale_account_match_json,
                calculated_at, gmt_create, gmt_modified
            ) VALUES (
                :identity, 'coupon-dual', 'order-coupon-dual', :direction, 1,
                '2026-10', :rule_date, 'store-sale', 'store-verify',
                'sku-dual', 'service', 'maintenance', 'short_video',
                10001, 0, 10001, :rate, :amount,
                'fee-sep', 'scope-2026-10-short_video', 1, 'pg-frozen-name',
                :version, CAST(:evidence AS jsonb), :at, :at, :at
            )
        """), {"identity": "legacy-name-fee-" + str(direction), "direction": direction,
                "rule_date": _dual_time(10, 5).date(), "rate": rate, "amount": amount,
                "version": version.version_id, "evidence": json.dumps(evidence),
                "at": version.frozen_at})


def _stored_name_evidence(engine):
    with engine.connect() as connection:
        return connection.execute(text("""
            SELECT fee_result_id, fee_direction, fee_amount_cent, sale_store_id,
                   account_qualification_version_id, sale_account_match_json
            FROM settlement_fee_result ORDER BY fee_direction
        """)).mappings().all()


def test_real_postgres_name_proof_survives_clue_upgrade_and_blocks_destructive_downgrade(full_pg_stack):
    config, engine = full_pg_stack
    command.upgrade(config, "20261118_0069")
    column = next(column for column in inspect(engine).get_columns("settlement_fee_result")
                  if column["name"] == "sale_account_match_json")
    assert column["nullable"] and isinstance(column["type"], JSONB)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as session:
        _load_dual_fee_fixture(session)
        _add_scope_rule(session, "2026-10")
        session.get(RawDouyinVerifyRecord, "verify-coupon-dual").verify_time = _dual_time(10, 5)
        order = session.scalar(select(RawDouyinOrder))
        order.owner_account_id = "opaque-unmatched-account"
        version = seed_month_qualification(session)
        session.flush()
        # A historical schema migration consumes already-stored historical
        # data. Current workers require the current migrated schema.
        _insert_0069_name_evidence(session, version)
        frozen_hash = version.content_sha256
    original = _stored_name_evidence(engine)
    assert len(original) == 2
    assert [row["fee_amount_cent"] for row in original] == [3000, 2000]
    assert "monthly_store_evidence_snapshot" not in inspect(engine).get_table_names()
    command.upgrade(config, "20261119_0071")
    assert _stored_name_evidence(engine) == original
    assert "monthly_store_evidence_snapshot" not in inspect(engine).get_table_names()
    command.upgrade(config, "head")
    assert _stored_name_evidence(engine) == original
    with factory() as session:
        results = list(session.scalars(select(SettlementFeeResult)))
        assert len(results) == 2
        assert all(result.sale_store_id == "store-sale" for result in results)
        assert all(result.sale_account_match_json["policy"] == q.SALE_ACCOUNT_MATCH_POLICY for result in results)
        assert all(result.sale_account_match_json["content_sha256"] == frozen_hash for result in results)
        assert all(result.sale_account_match_json["account_id"] == "owner-dual" for result in results)
    with pytest.raises(RuntimeError, match="Preserve frozen sales attribution evidence"):
        command.downgrade(config, "20261117_0068")
    assert "sale_account_match_json" in {column["name"] for column in inspect(engine).get_columns("settlement_fee_result")}
    assert _stored_name_evidence(engine) == original


def test_real_postgres_current_worker_calculates_name_proof_on_current_schema(full_pg_stack):
    from apps.worker.monthly_store_evidence import freeze_store_evidence

    config, engine = full_pg_stack
    command.upgrade(config, "head")
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as session:
        _load_dual_fee_fixture(session)
        _add_scope_rule(session, "2026-10")
        session.get(RawDouyinVerifyRecord, "verify-coupon-dual").verify_time = _dual_time(10, 5)
        session.scalar(select(RawDouyinOrder)).owner_account_id = "opaque-unmatched-account"
        version = seed_month_qualification(session)
        evidence = freeze_store_evidence(session, qualification_version=version, facts=[{
            "kind": "account", "key": "owner-dual", "store_id": "store-sale",
            "source_reference": "synthetic-month-end-account-store-proof", "source_sha256": "a" * 64,
            "observed_at": "2026-10-31T15:00:00+00:00", "valid_from": "2026-10-01", "valid_to": None,
        }])
        session.info["monthly_store_evidence_version_id"] = evidence.version_id
        settlement.rebuild_dual_fee_results(session, calculation_run_id="pg-current-frozen-name")
        frozen_hash = version.content_sha256
        mapping_context = evidence.as_context()
    with factory() as session:
        results = list(session.scalars(select(SettlementFeeResult).order_by(SettlementFeeResult.fee_direction)))
        assert [result.fee_amount_cent for result in results] == [3000, 2000]
        assert all(result.sale_store_id == "store-sale" for result in results)
        assert all(result.sale_account_match_json["policy"] == q.SALE_ACCOUNT_MATCH_POLICY for result in results)
        assert all(result.sale_account_match_json["content_sha256"] == frozen_hash for result in results)
        assert all(result.sale_account_match_json["account_id"] == "owner-dual" for result in results)
        assert all(result.sale_account_match_json["store_evidence"] == mapping_context for result in results)


def test_real_postgres_legacy_none_is_sql_null_and_empty_evidence_can_downgrade(full_pg_stack):
    config, engine = full_pg_stack
    command.upgrade(config, "head")
    factory = sessionmaker(bind=engine)
    with factory.begin() as session:
        _load_dual_fee_fixture(session)
        settlement.rebuild_dual_fee_results(session, calculation_run_id="pg-legacy-september")
    with engine.begin() as connection:
        before = connection.execute(text(
            "SELECT count(*), sum(fee_amount_cent) FROM settlement_fee_result"
        )).one()
        assert before[0] == 2
        assert connection.scalar(text(
            "SELECT count(*) FROM settlement_fee_result WHERE sale_account_match_json IS NULL"
        )) == 2
        # An earlier candidate may have encoded Python None as JSON null.
        # This also carries no attribution evidence and must not pin a schema.
        connection.execute(text(
            "UPDATE settlement_fee_result SET sale_account_match_json='null'::jsonb WHERE fee_direction=1"
        ))
    command.downgrade(config, "20261117_0068")
    assert "sale_account_match_json" not in {column["name"] for column in inspect(engine).get_columns("settlement_fee_result")}
    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT count(*), sum(fee_amount_cent) FROM settlement_fee_result"
        )).one() == before
    command.upgrade(config, "head")
    with factory() as session:
        assert all(result.sale_account_match_json is None for result in session.scalars(select(SettlementFeeResult)))
