"""Regression cases for monthly economic posting and its reviewed write path."""
from concurrent.futures import ThreadPoolExecutor
from csv import DictReader
from datetime import datetime, timezone
from hashlib import sha256
from io import StringIO
import os
from urllib.parse import unquote
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from apps.api.dy_api.models import (
    Base, DataQualityIssue, DimStore, DouyinRefundEvent, FinanceOperationAudit, RawDouyinOrderCoupon,
    RawDouyinVerifyRecord, SettlementDispute,
    SettlementFeeResultCurrent,
    SettlementFeeAdjustment, SettlementStatement, SettlementStatementBalance,
    SettlementStatementConfirmation, SettlementStatementEntry, SettlementStatementVisibility,
)
from apps.worker.historical_fee_correction import HistoricalFeeCorrectionError, _model, evidence_sha256
from apps.worker.monthly_fee_corrections import (
    apply_monthly_fee_corrections, posted_monthly_dispute_statement, preview_monthly_fee_corrections,
    reviewed_fee_basis_condition,
)
from apps.worker.monthly_statement_balances import (
    MonthlyBalanceNotReady, carryforward_store_ids, freeze_statement_balances,
)
from apps.worker.repositories import upsert_verify_record
from apps.worker.settlement import (
    _effective_adjustment_totals, lock_settlement_statement, materialize_deferred_monthly_adjustments,
    rebuild_dual_fee_results, select_coupon_ids_by_verify_business_month,
    select_coupon_ids_for_monthly_cancellations, select_coupon_ids_for_monthly_refunds,
)
from test_api_store_billing import _login, client, dashboard_routes
from test_data_settlement import _fee_result, _load_dual_fee_fixture
from test_historical_fee_correction import MODELS, fingerprint, seed


def _event(event_id, *, occurred, amount, kind=1):
    return DouyinRefundEvent(
        refund_event_id=event_id, order_id="order-coupon-dual", coupon_id="coupon-dual",
        refund_status=2, refund_type=kind, refund_amount_cent=amount, occurred_at=occurred,
        successful_observed_at=occurred, source_run_id="synthetic-event",
    )


def test_monthly_fee_does_not_net_later_refund_into_first_calculation(db_session):
    _load_dual_fee_fixture(db_session, amount_cent=10000)
    # Midnight in Shanghai belongs to October even with a September UTC date.
    instant = datetime(2026, 9, 30, 16, tzinfo=timezone.utc)
    coupon = db_session.scalar(select(RawDouyinOrderCoupon).where(
        RawDouyinOrderCoupon.coupon_id == "coupon-dual",
    ))
    coupon.coupon_refunded_amount_cent = 1000
    db_session.add_all([
        _event("october-refund", occurred=instant, amount=1000),
        _event("october-zero", occurred=instant, amount=0, kind=2),
    ])
    db_session.flush()
    rebuild_dual_fee_results(
        db_session, calculation_run_id="initial-calc", coupon_ids=("coupon-dual",), accounting_month="2026-09",
    )
    originals = [_fee_result(db_session, "coupon-dual", direction) for direction in (1, 2)]
    assert [fee.fee_amount_cent for fee in originals] == [3000, 2000]
    assert list(db_session.scalars(select(SettlementFeeAdjustment))) == []
    candidates = select_coupon_ids_for_monthly_refunds(db_session, "2026-10")
    assert candidates == ("coupon-dual",)
    for run in ("month-refunds", "month-refunds-retry"):
        rebuild_dual_fee_results(
            db_session, calculation_run_id=run, coupon_ids=candidates, accounting_month="2026-10",
        )
    deltas = list(db_session.scalars(select(SettlementFeeAdjustment).order_by(SettlementFeeAdjustment.fee_direction)))
    assert [(row.original_business_month, row.adjustment_posting_month, row.adjustment_fee_cent)
            for row in deltas] == [("2026-09", "2026-10", -300), ("2026-09", "2026-10", -200)]
    assert [row.refund_event_id for row in deltas] == ["october-refund"] * 2


def test_late_verified_event_reuses_immutable_source_once(db_session):
    _load_dual_fee_fixture(db_session, amount_cent=10000)
    rebuild_dual_fee_results(db_session, calculation_run_id="initial-calc")
    for store_id in ("store-sale", "store-verify"):
        lock_settlement_statement(db_session, store_id=store_id, statement_month="2026-10",
                                  lock_run_id=f"locked-october-{store_id}")
    event = _event("late-refund", occurred=datetime(2026, 10, 26, 8, tzinfo=timezone.utc), amount=1000)
    event.successful_observed_at = datetime(2026, 11, 2, 8, tzinfo=timezone.utc)
    db_session.add(event)
    db_session.flush()
    candidates = select_coupon_ids_for_monthly_refunds(db_session, "2026-11")
    assert candidates == ("coupon-dual",)
    rebuild_dual_fee_results(
        db_session, calculation_run_id="late-calc", coupon_ids=candidates, accounting_month="2026-11",
    )
    assert materialize_deferred_monthly_adjustments(db_session, month="2026-12") == {"store-sale", "store-verify"}
    assert materialize_deferred_monthly_adjustments(db_session, month="2026-11") == set()
    assert materialize_deferred_monthly_adjustments(db_session, month="2026-11") == set()
    deltas = list(db_session.scalars(select(SettlementFeeAdjustment).order_by(SettlementFeeAdjustment.fee_direction)))
    assert [(row.adjustment_posting_month, row.adjustment_fee_cent) for row in deltas] == [
        ("2026-11", -300), ("2026-11", -200),
    ]
    for row, adjustment in zip(deltas, (-300, -200), strict=True):
        assert _effective_adjustment_totals(db_session, original_fee_result_id=row.original_fee_result_id) == (
            -1000, adjustment,
        )
    audits = list(db_session.scalars(select(FinanceOperationAudit).where(
        FinanceOperationAudit.operation_type == "POST_DEFERRED_MONTHLY_REFUND",
    )))
    assert len(audits) == 2
    assert {(audit.after_snapshot["event_month"], audit.after_snapshot["posting_month"])
            for audit in audits} == {("2026-10", "2026-11")}


def _cancel_prior_verify(session, *, occurred, observed):
    upsert_verify_record(
        session, "verify-coupon-dual", coupon_id="coupon-dual", verify_status="cancelled",
        cancel_time=occurred, source_observed_at=observed, source_run_id="cancel-observation",
        raw_payload={"verify_status": "cancelled", "cancel_time": occurred.isoformat()},
    )


def test_known_future_cancel_keeps_first_positive_bill_and_reverses_in_event_month(db_session):
    _load_dual_fee_fixture(db_session, amount_cent=10000)
    event_at = datetime(2026, 10, 31, 16, tzinfo=timezone.utc)  # Nov 1 in Shanghai.
    _cancel_prior_verify(db_session, occurred=event_at, observed=event_at)
    ids = select_coupon_ids_by_verify_business_month(db_session, "2026-09", monthly=True)
    assert ids == ("coupon-dual",)
    assert select_coupon_ids_by_verify_business_month(db_session, "2026-09") == ()
    result = rebuild_dual_fee_results(
        db_session, calculation_run_id="september-close", coupon_ids=ids, accounting_month="2026-09",
    )
    assert (result.result_count, result.adjustment_count, result.blocked_count) == (2, 0, 0)
    for store_id in ("store-sale", "store-verify"):
        lock_settlement_statement(db_session, store_id=store_id, statement_month="2026-09",
                                  lock_run_id=f"frozen-september-{store_id}")
    db_session.add(_event("after-cancellation", occurred=datetime(2026, 11, 2, tzinfo=timezone.utc), amount=1000))
    db_session.flush()
    ids = select_coupon_ids_for_monthly_cancellations(db_session, "2026-11")
    assert ids == ("coupon-dual",)
    for attempt in ("initial", "retry"):
        rebuild_dual_fee_results(
            db_session, calculation_run_id=f"november-close-{attempt}", coupon_ids=ids,
            accounting_month="2026-11",
        )
    deltas = list(db_session.scalars(select(SettlementFeeAdjustment).order_by(SettlementFeeAdjustment.fee_direction)))
    assert [(row.adjustment_posting_month, row.adjustment_type, row.adjustment_fee_cent) for row in deltas] == [
        ("2026-11", 3, -3000), ("2026-11", 3, -2000),
    ]
    assert [_fee_result(db_session, "coupon-dual", direction).fee_amount_cent for direction in (1, 2)] == [3000, 2000]


def test_first_observed_cancel_state_does_not_certify_zero_without_original_proof(db_session):
    _load_dual_fee_fixture(db_session, amount_cent=10000, with_verify=False)
    db_session.add(RawDouyinVerifyRecord(
        verify_id="first-observed-cancel", coupon_id="coupon-dual", verify_status="cancelled",
        verify_time=datetime(2026, 9, 5, tzinfo=timezone.utc),
        cancel_time=datetime(2026, 10, 7, tzinfo=timezone.utc), poi_id="poi-verify",
    ))
    db_session.flush()
    ids = select_coupon_ids_by_verify_business_month(db_session, "2026-09", monthly=True)
    result = rebuild_dual_fee_results(
        db_session, calculation_run_id="cancel-unknown", coupon_ids=ids, accounting_month="2026-09",
    )
    assert (result.result_count, result.adjustment_count, result.blocked_count) == (0, 0, 2)
    issues = list(db_session.scalars(select(DataQualityIssue).where(
        DataQualityIssue.issue_type == "dual_fee_cancelled_verify_basis_unproven",
    )))
    assert {issue.raw_context_json["fee_direction"] for issue in issues} == {1, 2}
    assert {issue.raw_context_json["verify_poi_id"] for issue in issues} == {"poi-verify"}


def test_late_cancellation_keeps_event_month_and_cannot_replay_as_second_posting(db_session):
    _load_dual_fee_fixture(db_session, amount_cent=10000)
    rebuild_dual_fee_results(db_session, calculation_run_id="initial-calc")
    for store_id in ("store-sale", "store-verify"):
        lock_settlement_statement(db_session, store_id=store_id, statement_month="2026-10",
                                  lock_run_id=f"locked-october-{store_id}")
    _cancel_prior_verify(
        db_session, occurred=datetime(2026, 10, 5, tzinfo=timezone.utc),
        observed=datetime(2026, 11, 4, tzinfo=timezone.utc),
    )
    ids = select_coupon_ids_for_monthly_cancellations(db_session, "2026-11")
    assert ids == ("coupon-dual",)
    stats = rebuild_dual_fee_results(
        db_session, calculation_run_id="late-cancel", coupon_ids=ids, accounting_month="2026-11",
    )
    assert stats.blocked_count == 0
    assert not list(db_session.scalars(select(SettlementFeeAdjustment)))
    assert materialize_deferred_monthly_adjustments(db_session, month="2026-11") == set()
    assert materialize_deferred_monthly_adjustments(db_session, month="2026-11") == set()
    for store_id in ("store-sale", "store-verify"):
        lock_settlement_statement(db_session, store_id=store_id, statement_month="2026-12",
                                  lock_run_id=f"existing-legacy-december-{store_id}")
    rows = list(db_session.scalars(select(SettlementFeeAdjustment).order_by(SettlementFeeAdjustment.fee_direction)))
    assert [(row.adjustment_posting_month, row.adjustment_type, row.adjustment_fee_cent) for row in rows] == [
        ("2026-11", 3, -3000), ("2026-11", 3, -2000),
    ]
    audits = list(db_session.scalars(select(FinanceOperationAudit).where(
        FinanceOperationAudit.operation_type == "POST_DEFERRED_MONTHLY_CANCELLATION",
    )))
    assert len(audits) == 2
    assert {(audit.after_snapshot["event_month"], audit.after_snapshot["posting_month"])
            for audit in audits} == {("2026-10", "2026-11")}


def _bill(session, store, month, promotion, management, *, monthly=True):
    statement = SettlementStatement(
        statement_id=f"statement-{store}-{month}", store_id=store, statement_month=month,
        statement_status=2, promotion_original_fee_cent=max(promotion, 0),
        promotion_adjustment_fee_cent=min(promotion, 0), promotion_net_fee_cent=promotion,
        management_original_fee_cent=max(management, 0),
        management_adjustment_fee_cent=min(management, 0), management_net_fee_cent=management,
    )
    session.add(statement)
    session.flush()
    if monthly:
        freeze_statement_balances(session, statement, first_month="2026-10")
        session.flush()
    for direction, amount in ((1, promotion), (2, management)):
        session.add(SettlementStatementConfirmation(
            confirmation_id=f"confirm-{direction}-{statement.statement_id}", statement_id=statement.statement_id,
            fee_direction=direction, confirmation_status=1, confirmed_amount_cent=amount,
            confirmed_by="test", confirmed_at=datetime(2027, 2, 1, tzinfo=timezone.utc),
        ))
    session.flush()
    return statement


def test_frozen_credit_rolls_forward_only_per_store_and_direction(db_session):
    db_session.add_all([DimStore(store_id="one", store_name="one"), DimStore(store_id="two", store_name="two")])
    db_session.flush()
    legacy = _bill(db_session, "one", "2026-09", 200, 500, monthly=False)
    october = _bill(db_session, "one", "2026-10", -300, -400)
    assert carryforward_store_ids(db_session, month="2026-11") == {"one"}
    other = _bill(db_session, "two", "2026-10", 120, 140)
    november = _bill(db_session, "one", "2026-11", 0, 100)
    december = _bill(db_session, "one", "2026-12", 300, 200)
    january = _bill(db_session, "one", "2027-01", 120, 150)
    for statement, direction, opening, net, closing, previous in (
        (october, 1, 0, -300, -300, None),
        (november, 1, -300, -300, -300, october.statement_id),
        (december, 1, -300, 0, 0, november.statement_id),
        (january, 1, 0, 120, 0, december.statement_id),
        (january, 2, -100, 50, 0, december.statement_id),
        (other, 2, 0, 140, 0, None),
    ):
        balance = db_session.get(SettlementStatementBalance, (statement.statement_id, direction))
        assert (balance.opening_balance_cent, balance.net_due_cent, balance.closing_balance_cent,
                balance.previous_statement_id) == (opening, net, closing, previous)
    promotion, _ = dashboard_routes._promotion_invoice_carryforward_projection(db_session)
    assert promotion[legacy.statement_id]["allocated_amount_cent"] == 200
    assert promotion[january.statement_id]["allocated_amount_cent"] == 120
    assert promotion[december.statement_id]["invoiceable_amount_cent"] == 0
    management, applications = dashboard_routes._management_invoiceable_projection(db_session)
    assert applications == []
    invoiceable = {row["statement_id"]: row["invoiceable_amount_cent"] for row in management}
    assert invoiceable[legacy.statement_id] == 500
    assert invoiceable[january.statement_id] == 50
    assert invoiceable[other.statement_id] == 140


def test_unresolved_prior_period_and_unsettled_old_credit_do_not_become_zero(db_session):
    db_session.add(DimStore(store_id="store", store_name="store"))
    db_session.flush()
    _bill(db_session, "store", "2026-09", -1, 0, monthly=False)
    october = _bill(db_session, "store", "2026-10", 10, 10, monthly=False)
    with pytest.raises(MonthlyBalanceNotReady, match="legacy_pending_carryforward"):
        freeze_statement_balances(db_session, october, first_month="2026-10")
    december = _bill(db_session, "store", "2026-12", 10, 10, monthly=False)
    with pytest.raises(MonthlyBalanceNotReady, match="preceding_store_period_unresolved"):
        freeze_statement_balances(db_session, december, first_month="2026-10")


def test_visible_version_exports_direction_breakdown_in_yuan_and_chinese(client, db_session):
    first = _bill(db_session, "store-1", "2026-10", -101, 1)
    second = _bill(db_session, "store-1", "2026-11", 202, 13)
    path = f"/api/v1/store-settlements/{second.statement_id}/balances/export"
    assert client.get(path).status_code == 401
    _login(client)
    assert client.get(path).status_code == 404
    db_session.add(SettlementStatementVisibility(
        statement_id=second.statement_id, publication_id="published",
        first_visible_at=datetime(2026, 12, 5, tzinfo=timezone.utc),
    ))
    db_session.commit()
    response = client.get(path)
    assert response.status_code == 200
    assert "门店账单抵扣明细-2026-11-v1" in unquote(response.headers["content-disposition"])
    rows = list(DictReader(StringIO(response.content.decode("utf-8-sig"))))
    assert [(row["费用方向"], row["本期净费用（元）"], row["上期结转（元）"], row["抵扣后净额（元）"])
            for row in rows] == [("推广服务费", "2.02", "-1.01", "1.01"), ("管理服务费", "0.13", "0.00", "0.13")]
    assert db_session.get(SettlementStatementBalance, (first.statement_id, 1)).closing_balance_cent == -101


@pytest.fixture
def monthly_pg():
    raw_url = os.getenv("DYDATA_MONTHLY_TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("requires the disposable local monthly PostgreSQL test database")
    url = make_url(raw_url)
    if (not url.drivername.startswith("postgresql") or url.host not in {"127.0.0.1", "localhost"}
            or url.database != "dydata_monthly_test"):
        pytest.fail("monthly posting test requires loopback dydata_monthly_test")
    schema = f"test_monthly_posting_{uuid4().hex}"
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-c search_path={schema} -c lock_timeout=10000"})
    try:
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def test_reviewed_correction_pg_concurrent_replay_preserves_original(monthly_pg):
    now = datetime(2026, 11, 30, 16, tzinfo=timezone.utc)
    with monthly_pg() as session:
        old, evidence = seed(session)
        selected = old["rows"][2:4]
        for row in selected:
            session.add(SettlementStatementVisibility(
                statement_id=row["expected_statement_id"], publication_id="published",
                first_visible_at=datetime(2026, 10, 3, tzinfo=timezone.utc),
            ))
        session.commit()
        rows = [{
            "case_id": f"reviewed-case-{row['fee_direction']}",
            "coupon_id": row["coupon_id"], "order_id": row["order_id"],
            "store_id": row["store_id"], "fee_direction": row["fee_direction"],
            "original_statement_id": row["expected_statement_id"],
            "original_statement_version": row["expected_statement_version"],
            "original_business_month": row["business_month"], "original_entry_id": row["expected_entry_id"],
            "expected_fee_cent": row["old_fee_cent"],
            "corrected_fee_cent": row["old_fee_cent"] + (91 if row["fee_direction"] == 1 else -57),
            "evidence_sha256": row["source_sha256"],
        } for row in selected]
        manifest = {"request_id": "monthly-correction", "processing_month": "2026-12", "rows": rows, "schema_version": 1}
        before = fingerprint(session)
        original_models = (model for model in MODELS if model not in (SettlementFeeAdjustment, FinanceOperationAudit))
        before_immutable = {
            model: sorted((_model(row) for row in session.scalars(select(model))), key=evidence_sha256)
            for model in original_models
        }
        preview = preview_monthly_fee_corrections(session, manifest, evidence=evidence, now=now)
        assert fingerprint(session) == before
        assert sorted(row["delta_cent"] for row in preview["rows"]) == [-57, 91]
        approval = {"expected_preview_sha256": preview["preview_sha256"],
                    "approved_by": "approver", "approval_reference": "reviewed-exact-two"}
        with pytest.raises(HistoricalFeeCorrectionError, match="EXACT_CORRECTION_PREVIEW_CHANGED"):
            apply_monthly_fee_corrections(session, manifest, evidence=evidence, now=now,
                                          **{**approval, "expected_preview_sha256": "0" * 64})
        session.rollback()
        assert fingerprint(session) == before

    def run():
        with monthly_pg() as session:
            result = apply_monthly_fee_corrections(session, manifest, evidence=evidence, now=now, **approval)
            session.commit()
            return result["already_applied"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: run(), range(2))) == [False, True]
    with monthly_pg() as session:
        for model, records in before_immutable.items():
            assert sorted((_model(row) for row in session.scalars(select(model))), key=evidence_sha256) == records
        deltas = list(session.scalars(select(SettlementFeeAdjustment).where(
            reviewed_fee_basis_condition(SettlementFeeAdjustment.original_fee_result_id),
        ).order_by(SettlementFeeAdjustment.fee_direction)))
        assert [(row.original_business_month, row.adjustment_posting_month, row.adjustment_fee_cent)
                for row in deltas] == [("2026-09", "2026-12", 91), ("2026-09", "2026-12", -57)]


def test_missed_coupon_correction_requires_review_and_posts_to_dispute_after_publication(monthly_pg):
    now = datetime(2026, 10, 20, 8, tzinfo=timezone.utc)
    source = b"synthetic approved immutable source"
    source_hash = sha256(source).hexdigest()
    evidence = {source_hash: source}
    with monthly_pg() as session:
        _load_dual_fee_fixture(session, amount_cent=10000)
        original = _bill(session, "store-sale", "2026-09", 0, 0, monthly=False)
        original.statement_status = 4
        dispute = SettlementDispute(
            dispute_id="synthetic-dispute", statement_id=original.statement_id,
            store_id="store-sale", statement_month="2026-09", fee_direction=1, dispute_type=2,
            status=3, disputed_amount_cent=3000, description="missed fee",
            contact_name="synthetic", contact_phone_ciphertext="fake", submitted_by="fake",
        )
        session.add(dispute)
        session.commit()
        manifest = {
            "request_id": "reviewed-missed", "schema_version": 1, "processing_month": "2026-10",
            "dispute_id": dispute.dispute_id, "rows": [{
                "case_id": "missed-coupon", "coupon_id": "coupon-dual", "order_id": "order-coupon-dual",
                "store_id": "store-sale", "fee_direction": 1, "original_statement_id": original.statement_id,
                "original_statement_version": 1, "original_business_month": "2026-09", "original_entry_id": None,
                "expected_fee_cent": 0, "corrected_fee_cent": 3000, "evidence_sha256": source_hash,
            }],
        }
        preview = preview_monthly_fee_corrections(session, manifest, evidence=evidence, now=now)
        assert preview["rows"][0]["delta_cent"] == 3000
        apply_monthly_fee_corrections(
            session, manifest, evidence=evidence, expected_preview_sha256=preview["preview_sha256"],
            approved_by="test", approval_reference="reviewed-exact", now=now,
        )
        session.commit()
        assert list(session.scalars(select(SettlementFeeResultCurrent))) == []
        assert posted_monthly_dispute_statement(session, dispute=dispute, adjustment_amount_cent=3000) is None
        delta = session.scalar(select(SettlementFeeAdjustment))
        processed = _bill(session, "store-sale", "2026-10", 3000, 0)
        session.add(SettlementStatementEntry(
            statement_entry_id="synthetic-correction-posted", statement_id=processed.statement_id,
            statement_line_id="synthetic-line", source_type=2, source_record_id=delta.adjustment_id,
            original_fee_result_id=delta.original_fee_result_id, coupon_id=delta.coupon_id, order_id=delta.order_id,
            fee_direction=1, original_business_month="2026-09", statement_posting_month="2026-10",
            fee_amount_cent=delta.adjustment_fee_cent, rule_version=delta.rule_version,
        ))
        session.flush()
        assert posted_monthly_dispute_statement(session, dispute=dispute, adjustment_amount_cent=3000) is None
        session.add(SettlementStatementVisibility(
            statement_id=processed.statement_id, publication_id="published",
            first_visible_at=datetime(2026, 11, 10, tzinfo=timezone.utc),
        ))
        session.commit()
        assert posted_monthly_dispute_statement(session, dispute=dispute, adjustment_amount_cent=2999) is None
        assert posted_monthly_dispute_statement(session, dispute=dispute, adjustment_amount_cent=3000) == processed
        assert original.promotion_net_fee_cent == 0
        session.add(_event("verified-full", occurred=datetime(2026, 11, 15, 16, tzinfo=timezone.utc),
                           amount=10000, kind=2))
        session.flush()
        rebuild_dual_fee_results(
            session, calculation_run_id="monthly-adjust-after-missed",
            coupon_ids=("coupon-dual",), accounting_month="2026-11",
        )
        refund = session.scalar(select(SettlementFeeAdjustment).where(SettlementFeeAdjustment.refund_event_id == "verified-full"))
        assert (refund.adjustment_posting_month, refund.adjustment_fee_cent) == ("2026-11", -3000)
