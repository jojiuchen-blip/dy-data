"""Real PostgreSQL persistence and additive migration of monthly name evidence."""
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
        settlement.rebuild_dual_fee_results(session, calculation_run_id="pg-frozen-name")
        frozen_hash = version.content_sha256
    command.upgrade(config, "head")
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
