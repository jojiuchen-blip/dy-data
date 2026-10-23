"""Real PostgreSQL append-only, source fence, and complete migration checks."""

from alembic import command
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import Session

from apps.api.dy_api.dashboard_publications.sources import MODULE_SOURCE_TABLES
from apps.api.dy_api.models import HistoricalSaleAttributionDecision, RawDouyinOrder, RawDouyinVerifyRecord, SettlementFeeResult
from apps.worker import historical_sale_attribution as history
from apps.worker import month_close, settlement
from apps.worker.repositories import HEAVY_SYNC_CLAIM_LOCK_KEY
from test_dashboard_publication_finance_postgres import POSTGRES_URL, postgres_session
from test_dashboard_publication_migration import full_pg_stack
from test_historical_sale_attribution import (
    reviewed_manifest,
    test_import_defaults_to_dry_run_and_apply_replays_after_durable_readback as _assert_replay,
    test_exact_decision_enables_dual_fees_without_changing_raw_or_dim_bindings as _assert_dual_fees,
    test_second_invalid_row_rejects_first_valid_row_without_partial_audit as _assert_batch,
    test_exact_decision_never_overwrites_protected_statement_or_amount as _assert_protection,
    test_approved_fee_keeps_normal_refund_and_cancellation_adjustments as _assert_financial_events,
    test_reverification_does_not_expand_exact_approval as _assert_reverification,
)
from test_data_settlement import _load_dual_fee_fixture

pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="dedicated PostgreSQL test URL not configured")


def test_postgres_import_durable_replay(postgres_session):
    _assert_replay(postgres_session)


def test_postgres_exact_attribution_leaves_bindings_unchanged(postgres_session):
    _assert_dual_fees(postgres_session)


def test_postgres_entire_batch_rejected(postgres_session):
    _assert_batch(postgres_session)


@pytest.mark.parametrize("protected", ["confirmed", "locked", "invoice"])
def test_postgres_exact_decision_preserves_financial_protection(postgres_session, protected):
    _assert_protection(postgres_session, protected)


@pytest.mark.parametrize("change", ["refund", "cancel"])
def test_postgres_approved_financial_events_remain_append_only(postgres_session, change):
    _assert_financial_events(postgres_session, change)


@pytest.mark.parametrize("reuse_verify_id", [False, True])
def test_postgres_reverification_does_not_expand_approval(postgres_session, reuse_verify_id):
    _assert_reverification(postgres_session, reuse_verify_id)


def test_postgres_exact_decision_rebuild_and_real_result_watermark(postgres_session, monkeypatch):
    manifest = reviewed_manifest(postgres_session, ambiguous_binding=False)
    order = postgres_session.scalar(select(RawDouyinOrder))
    order.owner_account_id = "owner-dual"
    postgres_session.flush()
    settlement.rebuild_dual_fee_results(postgres_session, calculation_run_id="before-reviewed-decision")
    postgres_session.commit()
    assert len(list(postgres_session.scalars(select(SettlementFeeResult)))) == 2
    monkeypatch.setattr(month_close, "published_days_revisions", lambda *_: ["published-source-finalize"])
    before = {month: month_close.month_source_watermark(postgres_session, month)
              for month in ("2026-08", "2026-09")}
    order.owner_account_id = manifest["rows"][0]["source_account_id"]
    postgres_session.commit()
    history.import_decisions(postgres_session, manifest, apply=True)
    postgres_session.commit()
    reviewed = month_close.month_source_watermark(postgres_session, "2026-09")
    assert reviewed is not None and reviewed != before["2026-09"]
    assert month_close.month_source_watermark(postgres_session, "2026-08") == before["2026-08"]
    settlement.rebuild_dual_fee_results(postgres_session, calculation_run_id="after-reviewed-decision",
                                      coupon_ids=(manifest["rows"][0]["coupon_id"],))
    postgres_session.commit()
    rows = list(postgres_session.scalars(select(SettlementFeeResult).where(SettlementFeeResult.result_status == 1)))
    assert len(rows) == 2 and all(row.sale_attribution_decision_id for row in rows)
    assert month_close.month_source_watermark(postgres_session, "2026-09") != reviewed


@pytest.mark.parametrize("key", [HEAVY_SYNC_CLAIM_LOCK_KEY, history._REBUILD_LOCK])
def test_postgres_import_conflicts_with_either_writer_claim(postgres_session, key):
    manifest = reviewed_manifest(postgres_session)
    postgres_session.commit()
    with postgres_session.get_bind().begin() as other:
        assert other.scalar(select(func.pg_try_advisory_xact_lock(key)))
        with pytest.raises(history.HistoricalAttributionError, match="claim lock"):
            history.import_decisions(postgres_session, manifest, apply=True)


def test_postgres_source_fence_blocks_uncoordinated_api_writes(postgres_session):
    history._import_lock(postgres_session)
    with postgres_session.get_bind().connect() as other:
        with other.begin():
            other.execute(text("SET LOCAL lock_timeout = '100ms'"))
            with pytest.raises(OperationalError):
                other.execute(text("LOCK TABLE raw_douyin_verify_records IN ROW EXCLUSIVE MODE"))
            other.rollback()


@pytest.mark.parametrize("source", ["order", "verify"])
def test_postgres_committed_identity_drift_is_not_hidden_by_identity_map(postgres_session, source):
    manifest = reviewed_manifest(postgres_session)
    postgres_session.commit()
    with Session(postgres_session.get_bind()) as other:
        if source == "order":
            other.scalar(select(RawDouyinOrder)).owner_account_id = "different-source"
        else:
            other.scalar(select(RawDouyinVerifyRecord)).verify_status = "cancelled"
        other.commit()
    with pytest.raises(history.HistoricalAttributionError, match="identity"):
        history.import_decisions(postgres_session, manifest, apply=True)
    assert list(postgres_session.scalars(select(HistoricalSaleAttributionDecision))) == []


def test_full_postgres_chain_immutable_ledger_and_narrow_source_counter(full_pg_stack):
    config, engine = full_pg_stack
    command.upgrade(config, "head")
    with Session(engine, autoflush=False) as session:
        manifest = reviewed_manifest(session)
        session.commit()
        before = dict(session.execute(text(
            "SELECT source_name,generation FROM dashboard_publication_source_counters"
        )).all())
        history.import_decisions(session, manifest, apply=True)
        session.commit()
        after = dict(session.execute(text(
            "SELECT source_name,generation FROM dashboard_publication_source_counters"
        )).all())
        assert after[history.TABLE_NAME] == before[history.TABLE_NAME] + 1
        # Audit-only job rows are outside publication dependencies.
        assert {key for key in before if before[key] != after[key]} == {history.TABLE_NAME}
        assert all(history.TABLE_NAME in MODULE_SOURCE_TABLES[module] for module in ("finance", "settlement"))
        assert all(history.TABLE_NAME not in MODULE_SOURCE_TABLES[module]
                   for module in ("sales", "clue-overview", "douyin-ranking"))
        decision = session.scalar(select(HistoricalSaleAttributionDecision))
        assert decision.actor == manifest["actor"]
        for sql in (
            "UPDATE historical_sale_attribution_decisions SET actor='changed'",
            "DELETE FROM historical_sale_attribution_decisions",
            "TRUNCATE historical_sale_attribution_decisions CASCADE",
        ):
            with pytest.raises(DBAPIError, match="immutable"):
                with session.begin_nested():
                    session.execute(text(sql))
        session.rollback()
    with pytest.raises(RuntimeError, match="populated"):
        command.downgrade(config, "20261022_0064")


def test_postgres_existing_fee_rows_upgrade_with_null_provenance_and_same_fingerprint(full_pg_stack):
    config, engine = full_pg_stack
    command.upgrade(config, "head")
    with Session(engine, autoflush=False) as session:
        _load_dual_fee_fixture(session)
        settlement.rebuild_dual_fee_results(session, calculation_run_id="legacy-unadjudicated")
        session.commit()
        before = session.execute(text(
            "SELECT fee_result_id,input_fingerprint,fee_amount_cent FROM settlement_fee_result ORDER BY fee_result_id"
        )).all()
        assert len(before) == 2
    command.downgrade(config, "20261022_0064")
    command.upgrade(config, "head")
    with Session(engine, autoflush=False) as session:
        after = session.execute(text(
            "SELECT fee_result_id,input_fingerprint,fee_amount_cent FROM settlement_fee_result ORDER BY fee_result_id"
        )).all()
        assert before == after
        assert session.scalar(text(
            "SELECT count(*) FROM settlement_fee_result WHERE sale_attribution_decision_id IS NOT NULL"
        )) == 0
        settlement.rebuild_dual_fee_results(session, calculation_run_id="legacy-recomputed")
        session.commit()
        assert session.execute(text(
            "SELECT fee_result_id,input_fingerprint,fee_amount_cent FROM settlement_fee_result ORDER BY fee_result_id"
        )).all() == before
