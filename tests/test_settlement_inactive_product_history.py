"""Historical paid/redemption facts remain eligible after a proven delisting."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import delete, event, inspect, select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    DataQualityIssue,
    DimAwemeAccount,
    DimSkuProductRule,
    DouyinRefundEvent,
    InvoiceRecord,
    RawDouyinOrder,
    RawDouyinOrderCoupon,
    RawDouyinVerifyRecord,
    SettlementFeeResult,
    SettlementFeeAdjustment,
    SettlementScopeRule,
    SettlementStatement,
    SettlementStatementConfirmation,
    SkuFeeRule,
)
from apps.worker.settlement import rebuild_dual_fee_results
from test_data_settlement import (
    _add_fee_rule,
    _dual_time,
    _fee_result,
    _load_dual_fee_fixture,
)


def _product(session: Session) -> DimSkuProductRule:
    row = session.scalar(select(DimSkuProductRule).where(DimSkuProductRule.sku_id == "sku-dual"))
    assert row is not None
    return row


def _delist(session: Session) -> DimSkuProductRule:
    product = _product(session)
    product.is_active_product = False
    product.product_status_raw = "2"
    product.product_status_normalized = "INACTIVE"
    product.sync_status = "SUCCESS"
    product.last_synced_at = _dual_time(10, 23)
    product.sync_source = "douyin_product_api"
    product.sync_run_id = "synthetic-delisting-sync"
    session.flush()
    return product


def _historical_fixture(session: Session) -> DimSkuProductRule:
    _load_dual_fee_fixture(session, amount_cent=10000)
    _add_fee_rule(
        session, "historical-rule", date(2026, 9, 2),
        promotion="0.050000", management="0.050000",
    )
    return _delist(session)


def _run_without_catalog_writes(
    session: Session, *, run_id: str = "historical-rebuild", force: bool = False
) -> None:
    session.commit()
    product = _product(session)
    fields = [column.key for column in inspect(product).mapper.column_attrs]
    before = {field: getattr(product, field) for field in fields}
    catalog_dml: list[str] = []

    def capture_catalog_dml(connection, cursor, statement, parameters, context, executemany):
        normalized = statement.strip().lower()
        if "dim_sku_product_rules" in normalized and normalized.startswith(("insert ", "update ", "delete ")):
            catalog_dml.append(statement)

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", capture_catalog_dml)
    try:
        rebuild_dual_fee_results(session, calculation_run_id=run_id, force_recalculate=force)
        session.commit()
    finally:
        event.remove(engine, "before_cursor_execute", capture_catalog_dml)
    session.refresh(product)
    assert {field: getattr(product, field) for field in fields} == before
    assert catalog_dml == []


def _assert_no_fee_results(session: Session) -> None:
    assert list(session.scalars(select(SettlementFeeResult))) == []


def _assert_issue(session: Session, issue_type: str) -> None:
    assert issue_type in set(session.scalars(select(DataQualityIssue.issue_type)))


def test_successfully_synced_delisted_product_uses_historical_rule_and_real_basis(
    db_session: Session,
) -> None:
    _historical_fixture(db_session)
    _run_without_catalog_writes(db_session)
    for direction in (1, 2):
        result = _fee_result(db_session, "coupon-dual", direction)
        assert result is not None
        assert result.original_business_month == "2026-09"
        assert result.rule_match_date == date(2026, 9, 5)
        assert result.rule_version == "historical-rule"
        assert result.fee_rate == Decimal("0.050000")
        assert result.source_amount_cent == 10000
        assert result.fee_amount_cent == 500


@pytest.mark.parametrize("platform_status", ["UNKNOWN", "BANNED", "DELETED", "ACTIVE", None])
def test_other_platform_states_do_not_gain_historical_eligibility(
    db_session: Session, platform_status: str | None,
) -> None:
    product = _historical_fixture(db_session)
    product.product_status_normalized = platform_status
    _run_without_catalog_writes(db_session)
    _assert_no_fee_results(db_session)
    _assert_issue(db_session, "dual_fee_inactive_or_unknown_sku")


@pytest.mark.parametrize("sync_status", ["NOT_FOUND", "MASKED", "FAILED", "PARTIAL", None])
def test_unproven_delisting_does_not_gain_historical_eligibility(
    db_session: Session, sync_status: str | None,
) -> None:
    product = _historical_fixture(db_session)
    product.sync_status = sync_status
    _run_without_catalog_writes(db_session)
    _assert_no_fee_results(db_session)
    _assert_issue(db_session, "dual_fee_inactive_or_unknown_sku")


@pytest.mark.parametrize("rule_state", ["missing", "future", "inactive"])
def test_delisting_does_not_bypass_effective_fee_rule(
    db_session: Session, rule_state: str,
) -> None:
    _historical_fixture(db_session)
    if rule_state in {"missing", "future"}:
        db_session.execute(delete(SkuFeeRule))
        if rule_state == "future":
            _add_fee_rule(
                db_session, "future-only", date(2026, 10, 1),
                promotion="0.050000", management="0.050000",
            )
    else:
        db_session.scalar(select(SkuFeeRule).where(SkuFeeRule.rule_version == "historical-rule")).rule_status = 2
    _run_without_catalog_writes(db_session)
    _assert_no_fee_results(db_session)
    _assert_issue(db_session, "dual_fee_missing_fee_rule")


@pytest.mark.parametrize(
    "mutation,expected_issue",
    [
        ("missing_owner", "dual_fee_unstable_owner_account"),
        ("missing_sale_mapping", "dual_fee_missing_sale_store"),
        ("unknown_channel", "dual_fee_unknown_or_out_of_scope_channel"),
        ("missing_scope", "dual_fee_missing_scope_rule"),
        ("missing_receipt", "dual_fee_missing_coupon_amount"),
        ("missing_catalog", "dual_fee_inactive_or_unknown_sku"),
    ],
)
def test_delisted_product_keeps_all_downstream_identity_and_basis_gates(
    db_session: Session, mutation: str, expected_issue: str,
) -> None:
    product = _historical_fixture(db_session)
    order = db_session.scalar(select(RawDouyinOrder))
    if mutation == "missing_owner":
        product.owner_account_id = None
    elif mutation == "missing_sale_mapping":
        account = db_session.scalar(select(DimAwemeAccount))
        account.binding_status = "inactive"
        account.store_id = None
    elif mutation == "unknown_channel":
        order.sale_channel = "affiliate"
        order.sale_channel_normalized = "other"
    elif mutation == "missing_scope":
        db_session.execute(delete(SettlementScopeRule))
    elif mutation == "missing_receipt":
        order.raw_payload = {}
    else:
        order.sku_id = "no-platform-catalog"
    _run_without_catalog_writes(db_session)
    _assert_no_fee_results(db_session)
    _assert_issue(db_session, expected_issue)


@pytest.mark.parametrize("verify_state", ["unknown", "pending", "cancelled", "missing"])
def test_delisted_product_still_requires_valid_redemption(
    db_session: Session, verify_state: str,
) -> None:
    _historical_fixture(db_session)
    verify = db_session.scalar(select(RawDouyinVerifyRecord))
    if verify_state == "missing":
        db_session.delete(verify)
    else:
        verify.verify_status = verify_state
        if verify_state == "cancelled":
            verify.cancel_time = _dual_time(9, 6)
    _run_without_catalog_writes(db_session)
    _assert_no_fee_results(db_session)
    _assert_issue(db_session, "dual_fee_missing_valid_verify")


@pytest.mark.parametrize("refunded,expected_fee", [(4000, 300), (10000, 0)])
def test_delisting_does_not_bypass_partial_or_full_refund_basis(
    db_session: Session, refunded: int, expected_fee: int,
) -> None:
    _historical_fixture(db_session)
    coupon = db_session.scalar(select(RawDouyinOrderCoupon))
    coupon.coupon_refunded_amount_cent = refunded
    _run_without_catalog_writes(db_session)
    for direction in (1, 2):
        result = _fee_result(db_session, "coupon-dual", direction)
        assert result is not None
        assert result.refunded_amount_cent == refunded
        assert result.fee_amount_cent == expected_fee


def test_delisted_closed_unpaid_order_stays_excluded(db_session: Session) -> None:
    _historical_fixture(db_session)
    order = db_session.scalar(select(RawDouyinOrder))
    order.order_status = "closed"
    order.order_status_normalized = "closed"
    _run_without_catalog_writes(db_session)
    _assert_no_fee_results(db_session)


def test_delisted_sale_before_formal_start_stays_excluded(db_session: Session) -> None:
    _historical_fixture(db_session)
    order = db_session.scalar(select(RawDouyinOrder))
    order.sale_time = _dual_time(7, 31)
    order.pay_time = _dual_time(7, 31)
    _run_without_catalog_writes(db_session)
    _assert_no_fee_results(db_session)


def test_delisted_product_refund_adjustments_keep_event_month_and_idempotency(
    db_session: Session,
) -> None:
    _historical_fixture(db_session)
    _run_without_catalog_writes(db_session, run_id="before-refund")
    db_session.add(DouyinRefundEvent(
        refund_event_id="synthetic-later-refund", order_id="order-coupon-dual",
        coupon_id="coupon-dual", refund_type=1, refund_status=2,
        refund_amount_cent=4000, occurred_at=_dual_time(10, 2),
        source_run_id="synthetic-refund-sync", raw_payload={},
    ))
    _run_without_catalog_writes(db_session, run_id="after-refund")
    _run_without_catalog_writes(db_session, run_id="after-refund-again")
    adjustments = list(db_session.scalars(select(SettlementFeeAdjustment)))
    assert len(adjustments) == 2
    assert {row.fee_direction for row in adjustments} == {1, 2}
    assert all(row.adjustment_posting_month == "2026-10" for row in adjustments)
    assert all(row.adjustment_fee_cent == -200 for row in adjustments)
    assert all(row.adjustment_base_cent == -4000 for row in adjustments)
    assert all(
        _fee_result(db_session, "coupon-dual", direction).fee_amount_cent == 500
        for direction in (1, 2)
    )


def test_original_active_flag_compatibility_path_is_preserved(db_session: Session) -> None:
    product = _historical_fixture(db_session)
    product.is_active_product = True
    product.product_status_normalized = "UNKNOWN"
    product.sync_status = "NOT_FOUND"
    _run_without_catalog_writes(db_session)
    assert _fee_result(db_session, "coupon-dual", 1).fee_amount_cent == 500
    assert _fee_result(db_session, "coupon-dual", 2).fee_amount_cent == 500


def test_delisting_alone_keeps_original_result_and_idempotency(db_session: Session) -> None:
    _load_dual_fee_fixture(db_session, amount_cent=10000)
    rebuild_dual_fee_results(db_session, calculation_run_id="original-active")
    original = {
        direction: _fee_result(db_session, "coupon-dual", direction).fee_result_id
        for direction in (1, 2)
    }
    _delist(db_session)
    _run_without_catalog_writes(db_session, run_id="after-delisting")
    _run_without_catalog_writes(db_session, run_id="after-delisting")
    for direction in (1, 2):
        result = _fee_result(db_session, "coupon-dual", direction)
        assert result.fee_result_id == original[direction]
        assert result.result_status == 1
    assert len(list(db_session.scalars(select(SettlementFeeResult)))) == 2
    assert "dual_fee_inactive_or_unknown_sku" not in set(
        db_session.scalars(select(DataQualityIssue.issue_type))
    )


@pytest.mark.parametrize("protection", ["confirmation", "invoice", "locked"])
def test_delisted_recalculation_preserves_protected_original_amounts(
    db_session: Session, protection: str,
) -> None:
    _load_dual_fee_fixture(db_session, amount_cent=10000)
    rebuild_dual_fee_results(db_session, calculation_run_id="before-protection")
    originals = {
        direction: (
            _fee_result(db_session, "coupon-dual", direction).fee_result_id,
            _fee_result(db_session, "coupon-dual", direction).fee_amount_cent,
        )
        for direction in (1, 2)
    }
    for direction, store_id in ((1, "store-sale"), (2, "store-verify")):
        statement_id = f"protected-{direction}"
        db_session.add(SettlementStatement(
            statement_id=statement_id, store_id=store_id,
            statement_month="2026-09", statement_status=4 if protection == "locked" else 2,
            locked_at=_dual_time(10, 1) if protection == "locked" else None,
        ))
        db_session.flush()
        if protection == "confirmation":
            db_session.add(SettlementStatementConfirmation(
                confirmation_id=f"confirmation-{direction}", statement_id=statement_id,
                fee_direction=direction, confirmed_by="test", confirmed_at=_dual_time(10, 1),
                idempotency_key_hash=f"confirmation-{direction}",
            ))
        elif protection == "invoice":
            db_session.add(InvoiceRecord(
                invoice_id=f"invoice-{direction}", statement_id=statement_id,
                store_id=store_id, statement_month="2026-09", fee_direction=direction,
                invoice_number=f"{direction:020d}", invoice_date=date(2026, 10, 1),
                invoice_amount_cent=originals[direction][1], source_type=1,
                registered_by="test", is_current=True,
            ))
    _delist(db_session)
    _add_fee_rule(
        db_session, "later-historical-rule", date(2026, 9, 2),
        promotion="0.050000", management="0.050000",
    )
    _run_without_catalog_writes(db_session, run_id="protected-rebuild", force=True)
    for direction, original in originals.items():
        result = _fee_result(db_session, "coupon-dual", direction)
        assert (result.fee_result_id, result.fee_amount_cent) == original
        assert result.result_status == 1
    assert len(list(db_session.scalars(select(SettlementFeeResult)))) == 2
    _assert_issue(db_session, "dual_fee_locked_recalculation")
