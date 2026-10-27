"""Apply synthetic eight-coupon corrections through real settlement lifecycles."""
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from apps.api.dy_api.models import (
    AggStoreMonthlySettlement, DataQualityIssue, DimSkuProductRule,
    DouyinRefundEvent, FinanceOperationAudit, RawDouyinOrder,
    RawDouyinVerifyRecord, SettlementCarryforwardApplication, SettlementCarryforwardSource,
    SettlementFeeAdjustment, SettlementFeeResult, SettlementFeeResultCurrent,
    SettlementScopeRule, SettlementStatement, SettlementStatementEntry, SkuFeeRule,
)
from apps.worker import billing_source_capture, historical_fee_correction as correction
from apps.worker import settlement as worker
from apps.worker.repositories import (
    upsert_aweme_account, upsert_order_coupon, upsert_raw_order,
    upsert_sku_product_rule, upsert_store_poi_mapping, upsert_verify_record,
)
from test_historical_fee_correction import NOW, apply, seed


def instant(month,day):
    return datetime(2026,month,day,2,tzinfo=timezone.utc)


@pytest.fixture
def corrected(db_session):
    manifest,sources = seed(db_session)
    upsert_aweme_account(db_session,"owner-lifecycle",nickname="Lifecycle Owner",
                         store_id="sale-store",binding_status="active")
    upsert_sku_product_rule(db_session,"synthetic-sku","type",product_scope="scope",
        sku_name="Synthetic SKU",product_name="Synthetic lifecycle product",owner_account_id="owner-lifecycle",
        owner_account_name="Lifecycle Owner",product_status_normalized="active",is_active_product=True,is_service_product=True)
    db_session.add(SettlementScopeRule(scope_rule_version="scope-rule",idempotency_key_hash="a"*64,
        request_payload_sha256="b"*64,effective_month="2026-09",owner_account_id="owner-lifecycle",
        sale_channel_normalized="live",is_active=True,created_by="synthetic",change_reason="synthetic"))
    db_session.add(SkuFeeRule(rule_version="rule-frozen",idempotency_key_hash="c"*64,
        request_payload_sha256="d"*64,sku_id="synthetic-sku",sku_name_snapshot="Synthetic SKU",
        product_scope_snapshot="scope",product_type_snapshot="type",promotion_service_fee_rate=Decimal("0.1"),
        management_service_fee_rate=Decimal("0.1"),effective_date=date(2026,9,1),effective_at=instant(9,1),
        rule_status=1,created_by="synthetic",change_reason="synthetic",published_at=instant(9,1)))
    for index in range(8):
        fee = db_session.scalar(select(SettlementFeeResult).where(SettlementFeeResult.fee_result_id == f"fee-{index}-1"))
        amount = fee.source_amount_cent
        upsert_store_poi_mapping(db_session,f"verify-store-{index}",f"poi-lifecycle-{index}",mapping_source="synthetic")
        upsert_raw_order(db_session,f"order-{index}",order_status="paid",order_status_normalized="paid",
            sku_id="synthetic-sku",pay_time=instant(9,11),sale_time=instant(9,11),paid_amount_cent=amount,
            order_paid_amount_cent=amount,owner_account_id="owner-lifecycle",owner_account_name="Lifecycle Owner",
            sale_channel="live",sale_channel_normalized="live",raw_payload={"receipt_amount":amount},source_run_id="synthetic")
        upsert_order_coupon(db_session,f"coupon-{index}",f"order-{index}",coupon_status="fulfilled",
            coupon_status_normalized="available",coupon_paid_amount_cent=amount,coupon_refunded_amount_cent=0,source_run_id="synthetic")
        upsert_verify_record(db_session,f"verify-{index}",coupon_id=f"coupon-{index}",verify_status="valid",
            verify_time=instant(9,12),poi_id=f"poi-lifecycle-{index}",sku_id="synthetic-sku",paid_amount_cent=amount,source_run_id="synthetic")
    for fee in db_session.scalars(select(SettlementFeeResult)):
        fee.qualifying_verify_time = instant(9,12)
    for entry in db_session.scalars(select(SettlementStatementEntry).where(SettlementStatementEntry.source_type == 1)):
        entry.sale_time_snapshot = instant(9,11)
        entry.verify_time_snapshot = instant(9,12)
    # A genuine unrelated current result shares the sale slot but has no audit.
    template = db_session.scalar(select(SettlementFeeResult).where(SettlementFeeResult.fee_result_id == "fee-0-1"))
    db_session.add(correction._copy(template,fee_result_id="outside-fee",coupon_id="outside-coupon",order_id="outside-order",
        result_version=1,source_amount_cent=5000,fee_base_cent=5000,fee_amount_cent=500,
        qualifying_verify_id=None,qualifying_verify_time=None,qualifying_verify_store_id=None,rule_version="outside-rule"))
    db_session.add(SettlementFeeResultCurrent(coupon_id="outside-coupon",fee_direction=1,fee_result_id="outside-fee"))
    db_session.commit()
    preview = correction.preview_correction(db_session,manifest,source_documents=sources)
    result = apply(db_session,manifest,sources,preview)
    db_session.commit()
    assert result["delta_totals_cent"] == {"1":1290,"2":1290}
    return manifest,result


def target_fees(session,index=1):
    return [session.scalar(select(SettlementFeeResult).where(SettlementFeeResult.fee_result_id == f"fee-{index}-{direction}"))
            for direction in (1,2)]


def effective_net(session,fee):
    _,delta = worker._effective_adjustment_totals(session,original_fee_result_id=fee.fee_result_id)
    return fee.fee_amount_cent+delta


def add_refund(session,*,kind=2,event_id="lifecycle-refund",index=1,day=28):
    fee = target_fees(session,index)[0]
    session.add(DouyinRefundEvent(refund_event_id=event_id,order_id=f"order-{index}",coupon_id=f"coupon-{index}",
        refund_type=kind,refund_status=2,refund_amount_cent=fee.source_amount_cent if kind == 2 else 1000,
        occurred_at=instant(10,day),successful_observed_at=instant(10,day),source_run_id="synthetic",raw_payload={}))
    session.flush()


def run(session,run_id="lifecycle-run",*,index=1):
    return worker.rebuild_dual_fee_results(session,calculation_run_id=run_id,force_recalculate=True,
                                           coupon_ids=[f"coupon-{index}"])


def assert_projection(session,expected):
    sources = billing_source_capture.collect_billing_sources(session,months=["2026-09","2026-10","2026-11"])
    for source in sources:
        if source.source_type == 2 and source.adjustment_type == 4:
            assert source.refund_at is None
    assert sum(source.fee_amount_cent for source in sources) == expected
    worker.rebuild_dual_fee_projections(session,projection_run_id="lifecycle-projection")
    monthly = list(session.scalars(select(AggStoreMonthlySettlement).where(
        AggStoreMonthlySettlement.product_scope == "all",AggStoreMonthlySettlement.product_type == "all")))
    assert sum(row.promotion_net_fee_cent+row.management_net_fee_cent for row in monthly) == expected
    sparse = session.execute(worker._sparse_monthly_query("2026-09")).mappings().all()
    assert sum(row["promotion_original_fee_cent"]+row["promotion_adjustment_fee_cent"]
               +row["management_original_fee_cent"]+row["management_adjustment_fee_cent"]
               for row in sparse if row["product_scope"] == row["product_type"] == "all") >= 0


def test_applied_delta_survives_force_invalid_retirement_and_full_rebuild(db_session,corrected):
    manifest,_ = corrected
    expected_ids = {row["expected_fee_result_id"] for row in manifest["rows"]}
    for row in manifest["rows"]:
        assert worker._is_fee_result_locked(db_session,store_id=row["store_id"],month="2026-09",
                                             current_fee_result_id=row["expected_fee_result_id"])
    assert not worker._is_fee_result_locked(db_session,store_id="sale-store",month="2026-09")
    assert not worker._is_fee_result_locked(db_session,store_id="sale-store",month="2026-09",current_fee_result_id="outside-fee")
    worker.rebuild_dual_fee_results(db_session,calculation_run_id="manual-force",force_recalculate=True,
                                    coupon_ids=[f"coupon-{index}" for index in range(8)])
    assert_projection(db_session,27380)  # Two corrected 13440 totals plus unrelated 500.
    product = db_session.scalar(select(DimSkuProductRule).where(DimSkuProductRule.sku_id == "synthetic-sku"))
    product.is_active_product = False
    product.product_status_normalized = "unknown"
    db_session.flush()
    worker.rebuild_settlement(db_session,source_run_id="manual-invalid-full-rebuild")
    pointers = set(db_session.scalars(select(SettlementFeeResultCurrent.fee_result_id)))
    assert expected_ids.issubset(pointers)
    assert len(pointers) == 17
    assert sum(row.adjustment_fee_cent for row in db_session.scalars(select(SettlementFeeAdjustment))) == 2580
    assert_projection(db_session,27380)
    assert db_session.scalar(select(func.count()).select_from(FinanceOperationAudit).where(
        FinanceOperationAudit.operation_type == correction.OPERATION)) == 16


@pytest.mark.parametrize("event",["full-refund","cancel"])
@pytest.mark.parametrize("protected_posting",[False,True])
@pytest.mark.parametrize("closed_order",[False,True])
def test_full_reversal_includes_manual_delta_once_and_preserves_posting_protection(db_session,corrected,event,protected_posting,closed_order):
    fees = target_fees(db_session)
    if closed_order:
        order = db_session.scalar(select(RawDouyinOrder).where(RawDouyinOrder.order_id == "order-1"))
        order.order_status = order.order_status_normalized = "closed"
    if protected_posting:
        for store in ("sale-store","verify-store-1"):
            db_session.add(SettlementStatement(statement_id="oct-locked-"+store,store_id=store,statement_month="2026-10",
                statement_status=4,is_current=True,locked_at=NOW,lock_version="oct-locked-"+store))
    if event == "full-refund":
        add_refund(db_session)
    else:
        verify = db_session.get(RawDouyinVerifyRecord,"verify-1")
        verify.verify_status = "cancelled"
        verify.cancel_time = instant(10,28)
    db_session.flush()
    run(db_session)
    before = db_session.scalar(select(func.count()).select_from(SettlementFeeAdjustment))
    run(db_session,"lifecycle-repeat")
    assert db_session.scalar(select(func.count()).select_from(SettlementFeeAdjustment)) == before
    assert [effective_net(db_session,fee) for fee in fees] == [0,0]
    if protected_posting:
        pending = list(db_session.scalars(select(SettlementCarryforwardSource)))
        assert sorted(row.adjustment_fee_cent for row in pending) == [-1680,-1680]
        for store in ("sale-store","verify-store-1"):
            worker.lock_settlement_statement(db_session,store_id=store,statement_month="2026-11",lock_run_id="apply-"+store)
        assert db_session.scalar(select(func.count()).select_from(SettlementCarryforwardApplication)) == 2
        assert [effective_net(db_session,fee) for fee in fees] == [0,0]
        run(db_session,"lifecycle-repeat-after-carryforward")
        assert [effective_net(db_session,fee) for fee in fees] == [0,0]
    assert_projection(db_session,27380-3360)


def test_partial_refund_is_manual_review_not_guessed_adjustment_or_success(db_session,corrected):
    add_refund(db_session,kind=1)
    first = run(db_session,"partial-review")
    second = run(db_session,"partial-review-repeat")
    assert first.adjustment_count == second.adjustment_count == 0
    assert first.blocked_count >= 2 and second.blocked_count >= 2
    assert [effective_net(db_session,fee) for fee in target_fees(db_session)] == [1680,1680]
    issues = list(db_session.scalars(select(DataQualityIssue).where(
        DataQualityIssue.issue_type == "dual_fee_manual_correction_partial_refund_review")))
    assert len(issues) == 4
    assert all(row.severity == "error" and row.raw_context_json["resolution"] == "MANUAL_REVIEW_REQUIRED"
               and row.raw_context_json["adjustment_created"] is False for row in issues)
    assert_projection(db_session,27380)
    add_refund(db_session,event_id="later-full-refund",day=29)
    run(db_session,"partial-followed-by-full")
    assert [effective_net(db_session,fee) for fee in target_fees(db_session)] == [0,0]
    assert_projection(db_session,27380-3360)


def test_zero_delta_apply_directions_keep_original_partial_refunds_and_pin(db_session,corrected):
    # The real service fixture applies all 16 reviewed directions. Its four
    # zero-delta audits are intact and produced no type4 amount adjustments.
    for index in (0,2):
        for fee in target_fees(db_session,index):
            assert (fee.fee_base_cent,fee.fee_amount_cent,fee.fee_rate) == (16800,1680,Decimal("0.1"))
            audit = db_session.scalar(select(FinanceOperationAudit).where(FinanceOperationAudit.target_id == fee.fee_result_id))
            assert audit.after_snapshot["old_fee_cent"] == audit.after_snapshot["target_fee_cent"] == 1680
            assert audit.after_snapshot["delta_cent"] == 0
            assert worker._has_historical_fee_correction(db_session,fee.fee_result_id)
            assert not worker._has_historical_fee_amount_override(db_session,fee.fee_result_id)
        add_refund(db_session,kind=1,event_id=f"zero-delta-partial-{index}",index=index)
    add_refund(db_session,kind=1,event_id="nonzero-delta-partial",index=1)
    for index in (0,2,1):
        run(db_session,f"mixed-partial-{index}",index=index)
    refunds = list(db_session.scalars(select(SettlementFeeAdjustment).where(
        SettlementFeeAdjustment.refund_event_id.in_(["zero-delta-partial-0","zero-delta-partial-2"]))))
    assert len(refunds) == 4
    assert all(row.adjustment_type == 1 and row.adjustment_fee_cent == -100 and row.adjustment_base_cent == -1000 for row in refunds)
    assert [effective_net(db_session,fee) for index in (0,2) for fee in target_fees(db_session,index)] == [1580]*4
    assert [effective_net(db_session,fee) for fee in target_fees(db_session,1)] == [1680,1680]
    reviews = list(db_session.scalars(select(DataQualityIssue).where(
        DataQualityIssue.issue_type == "dual_fee_manual_correction_partial_refund_review")))
    assert len(reviews) == 2 and {row.coupon_id for row in reviews} == {"coupon-1"}
    before_count = db_session.scalar(select(func.count()).select_from(SettlementFeeAdjustment))
    for index in (0,2,1):
        run(db_session,f"mixed-repeat-{index}",index=index)
    assert db_session.scalar(select(func.count()).select_from(SettlementFeeAdjustment)) == before_count
    assert db_session.scalar(select(func.count()).select_from(FinanceOperationAudit).where(
        FinanceOperationAudit.operation_type == correction.OPERATION)) == 16
    assert set(db_session.scalars(select(SettlementFeeResultCurrent.fee_result_id).where(
        SettlementFeeResultCurrent.coupon_id.in_(["coupon-0","coupon-2"])))) == {
            f"fee-{index}-{direction}" for index in (0,2) for direction in (1,2)}
    assert_projection(db_session,27380-400)


def test_reverification_uses_new_anchor_amount_not_old_manual_fixed_amount(db_session,corrected):
    originals = target_fees(db_session)
    old = db_session.get(RawDouyinVerifyRecord,"verify-1")
    old.verify_status = "cancelled"
    old.cancel_time = instant(9,18)
    db_session.flush()
    run(db_session,"late-september-cancellation")
    assert [effective_net(db_session,fee) for fee in originals] == [0,0]
    upsert_verify_record(db_session,"lifecycle-new-verify",coupon_id="coupon-1",verify_status="valid",
        verify_time=instant(9,21),poi_id="poi-lifecycle-1",sku_id="synthetic-sku",paid_amount_cent=12800,source_run_id="new")
    db_session.flush()
    for run_id in ("new-anchor","new-anchor-repeat"):
        run(db_session,run_id)
    anchors = list(db_session.scalars(select(SettlementFeeResult).where(SettlementFeeResult.reverification_anchor_id.in_(
        [fee.fee_result_id for fee in originals]))))
    assert len(anchors) == 2
    assert [fee.fee_amount_cent for fee in anchors] == [1280,1280]
    assert all(not worker._has_historical_fee_correction(db_session,fee.fee_result_id) for fee in anchors)
    assert set(db_session.scalars(select(SettlementFeeResultCurrent.fee_result_id).where(
        SettlementFeeResultCurrent.coupon_id == "coupon-1"))) == {fee.fee_result_id for fee in originals}
    assert_projection(db_session,27380-3360+2560)
    add_refund(db_session,kind=1,event_id="new-anchor-partial")
    run(db_session,"new-anchor-refund")
    refunds = list(db_session.scalars(select(SettlementFeeAdjustment).where(SettlementFeeAdjustment.refund_event_id == "new-anchor-partial")))
    assert sorted(row.adjustment_fee_cent for row in refunds) == [-100,-100]
    assert {row.original_fee_result_id for row in refunds} == {fee.fee_result_id for fee in anchors}
    assert db_session.scalar(select(func.count()).select_from(DataQualityIssue).where(
        DataQualityIssue.issue_type == "dual_fee_manual_correction_partial_refund_review")) == 0
    assert_projection(db_session,27380-3360+2560-200)
    # A later closed order must still reverse the restored (ordinary) basis,
    # using its actual remaining amount, never the old manual fixed amount.
    add_refund(db_session,event_id="new-anchor-full",day=29)
    order = db_session.scalar(select(RawDouyinOrder).where(RawDouyinOrder.order_id == "order-1"))
    order.order_status = order.order_status_normalized = "closed"
    db_session.flush()
    for run_id in ("closed-anchor-full","closed-anchor-full-repeat"):
        run(db_session,run_id)
    full = list(db_session.scalars(select(SettlementFeeAdjustment).where(SettlementFeeAdjustment.refund_event_id == "new-anchor-full")))
    assert sorted(row.adjustment_fee_cent for row in full) == [-1180,-1180]
    assert all(effective_net(db_session,fee) == 0 for fee in anchors)
    assert_projection(db_session,27380-3360)
