"""DYDATA-97 T1.1: commission must be based on order/coupon receipt amounts.

These tests encode the target receipt-basis contract for
``apps.worker.settlement``. They reuse the real fixtures and worker entry points
already exercised in ``tests/test_data_settlement.py`` (``db_session``,
``rebuild_dual_fee_results``, ``run_settlement_job``,
``lock_settlement_statement``).

Field names are deliberately limited to what already exists in the repository:

* order/coupon-level ``receipt_amount`` and order-level
  ``sub_order_amount_infos`` are taken from
  ``scripts/settlement/build_settlement_base_from_current_data.py``;
* attribution uses only the persisted ``RawDouyinOrderCoupon.order_item_id``
  and ``coupon_id`` columns.

Amounts are stored in cents; a receipt that is not a whole number of cents is
fractional-cent data and must not be silently rounded.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    AggStoreMonthlySettlement,
    DataQualityIssue,
    DouyinRefundEvent,
    RawDouyinOrder,
    RawDouyinOrderCoupon,
    SettlementFeeResult,
    SettlementFeeResultCurrent,
    SettlementOrderDetail,
    SettlementScopeRule,
    SkuFeeRule,
)
from apps.worker.repositories import (
    upsert_aweme_account,
    upsert_aweme_binding,
    upsert_order_coupon,
    upsert_raw_order,
    upsert_sku_product_rule,
    upsert_store,
    upsert_store_poi_mapping,
    upsert_verify_record,
)
from apps.worker.receipt_amounts import SubOrderReceipts
from apps.worker.settlement import (
    _receipt_amounts_for_details,
    lock_settlement_statement,
    rebuild_dual_fee_results,
    run_settlement_job,
)

PROMOTION_FEE = 1
MANAGEMENT_FEE = 2

# fee-sep-receipt: promotion 10%, management 20%.
PROMOTION_RATE = Decimal("0.100000")
MANAGEMENT_RATE = Decimal("0.200000")


def _dt(day: int) -> datetime:
    return datetime(2026, 9, day, 2, 0, tzinfo=timezone.utc)


def _add_fee_rule(
    session: Session,
    version: str,
    effective_date: date,
    *,
    promotion: str,
    management: str,
) -> None:
    session.add(
        SkuFeeRule(
            rule_version=version,
            idempotency_key_hash=(version * 64)[:64],
            request_payload_sha256=(version[::-1] * 64)[:64],
            sku_id="sku-dual",
            sku_name_snapshot="Receipt fee SKU",
            product_scope_snapshot="service",
            product_type_snapshot="maintenance",
            promotion_service_fee_rate=Decimal(promotion),
            management_service_fee_rate=Decimal(management),
            effective_date=effective_date,
            effective_at=datetime.combine(
                effective_date, datetime.min.time(), timezone.utc
            ),
            rule_status=1,
            created_by="test",
            change_reason="receipt basis fixture",
            published_at=datetime.combine(
                effective_date, datetime.min.time(), timezone.utc
            ),
        )
    )


def _add_scope_rule(session: Session, month: str) -> None:
    version = f"scope-{month}-short_video"
    session.add(
        SettlementScopeRule(
            scope_rule_version=version,
            idempotency_key_hash=(version * 64)[:64],
            request_payload_sha256=(version[::-1] * 64)[:64],
            effective_month=month,
            owner_account_id="owner-dual",
            sale_channel_normalized="short_video",
            is_active=True,
            created_by="test",
            change_reason="receipt basis fixture",
        )
    )


def _seed_dual_base(session: Session) -> None:
    """Stores, owner, SKU, scope rule and fee rule for the dual fee chain."""

    upsert_store(session, "store-sale", "Sale Store")
    upsert_store(session, "store-verify", "Verify Store")
    upsert_store_poi_mapping(
        session, "store-verify", "poi-verify", mapping_source="test"
    )
    upsert_aweme_account(
        session,
        "owner-dual",
        nickname="Owner Dual",
        store_id="store-sale",
        binding_status="active",
    )
    upsert_sku_product_rule(
        session,
        "sku-dual",
        "maintenance",
        sku_name="Receipt fee SKU",
        product_scope="service",
        product_name="Receipt fee product",
        owner_account_id="owner-dual",
        owner_account_name="Owner Dual",
        product_status_normalized="active",
        is_active_product=True,
        is_service_product=True,
    )
    _add_scope_rule(session, "2026-09")
    _add_fee_rule(
        session,
        "fee-sep-receipt",
        date(2026, 9, 1),
        promotion=str(PROMOTION_RATE),
        management=str(MANAGEMENT_RATE),
    )
    session.flush()


def _add_dual_order(
    session: Session,
    order_id: str,
    *,
    paid_cent: int,
    coupons: list[dict],
    order_payload: dict | None = None,
    coupon_paid_cent: int | None = None,
) -> None:
    """Create one order with the given coupons plus their valid verifications.

    ``coupons`` entries may carry ``coupon_id``, ``order_item_id`` and a
    coupon-level ``receipt_amount`` (stored in the coupon raw payload).
    """

    upsert_raw_order(
        session,
        order_id,
        order_status="paid",
        order_status_raw="paid",
        order_status_normalized="paid",
        sku_id="sku-dual",
        pay_time=_dt(5),
        sale_time=_dt(5),
        paid_amount_cent=paid_cent,
        order_paid_amount_cent=paid_cent,
        owner_account_id="owner-dual",
        owner_account_name="Owner Dual",
        sale_channel="short_video",
        sale_channel_raw="short_video",
        sale_channel_normalized="short_video",
        raw_payload=order_payload or {},
        source_run_id="receipt-source",
    )
    for entry in coupons:
        coupon_id = entry["coupon_id"]
        coupon_payload: dict = {}
        if "receipt_amount" in entry:
            coupon_payload["receipt_amount"] = entry["receipt_amount"]
        upsert_order_coupon(
            session,
            coupon_id,
            order_id,
            order_item_id=entry.get("order_item_id"),
            coupon_status="fulfilled",
            coupon_status_raw="fulfilled",
            coupon_status_normalized="available",
            coupon_paid_amount_cent=(
                coupon_paid_cent if coupon_paid_cent is not None else paid_cent
            ),
            coupon_refunded_amount_cent=0,
            raw_payload=coupon_payload,
            source_run_id="receipt-source",
        )
        upsert_verify_record(
            session,
            f"verify-{coupon_id}",
            coupon_id=coupon_id,
            verify_status="valid",
            verify_time=_dt(5),
            poi_id="poi-verify",
            sku_id="sku-dual",
            paid_amount_cent=paid_cent,
            source_run_id="receipt-source",
        )
    session.flush()


def _fee_result(
    session: Session, coupon_id: str, direction: int
) -> SettlementFeeResult | None:
    pointer = session.scalar(
        select(SettlementFeeResultCurrent).where(
            SettlementFeeResultCurrent.coupon_id == coupon_id,
            SettlementFeeResultCurrent.fee_direction == direction,
        )
    )
    if pointer is None:
        return None
    return session.scalar(
        select(SettlementFeeResult).where(
            SettlementFeeResult.fee_result_id == pointer.fee_result_id
        )
    )


def _has_issue(session: Session, issue_type: str, coupon_id: str) -> bool:
    value = session.scalar(
        select(func.count())
        .select_from(DataQualityIssue)
        .where(
            DataQualityIssue.issue_type == issue_type,
            DataQualityIssue.coupon_id == coupon_id,
        )
    )
    return bool(value)


def _result_count(session: Session, coupon_id: str) -> int:
    value = session.scalar(
        select(func.count())
        .select_from(SettlementFeeResult)
        .where(SettlementFeeResult.coupon_id == coupon_id)
    )
    return int(value or 0)


def test_single_coupon_uses_receipt_not_paid_for_both_directions(
    db_session: Session,
) -> None:
    _seed_dual_base(db_session)
    _add_dual_order(
        db_session,
        "order-receipt-single",
        paid_cent=10000,
        coupons=[{"coupon_id": "coupon-receipt-single", "order_item_id": "item-1"}],
        order_payload={"receipt_amount": 8000},
    )

    rebuild_dual_fee_results(db_session, calculation_run_id="receipt-single")

    promotion = _fee_result(db_session, "coupon-receipt-single", PROMOTION_FEE)
    management = _fee_result(db_session, "coupon-receipt-single", MANAGEMENT_FEE)
    assert promotion is not None
    assert management is not None
    # Both directions take the interface receipt (8000), never the paid 10000.
    assert promotion.source_amount_cent == 8000
    assert management.source_amount_cent == 8000
    assert promotion.fee_base_cent == 8000
    assert management.fee_base_cent == 8000
    assert promotion.fee_amount_cent == 800
    assert management.fee_amount_cent == 1600
    assert promotion.source_amount_cent != 10000

    order = db_session.scalar(
        select(RawDouyinOrder).where(RawDouyinOrder.order_id == "order-receipt-single")
    )
    assert order is not None
    assert order.paid_amount_cent == 10000  # paid fact is preserved, unused as basis
    assert not _has_issue(db_session, "dual_fee_missing_coupon_amount", "coupon-receipt-single")


def test_zero_receipt_is_preserved_as_zero(db_session: Session) -> None:
    _seed_dual_base(db_session)
    _add_dual_order(
        db_session,
        "order-receipt-zero",
        paid_cent=10000,
        coupons=[{"coupon_id": "coupon-receipt-zero", "order_item_id": "item-zero"}],
        order_payload={"receipt_amount": 0},
    )

    rebuild_dual_fee_results(db_session, calculation_run_id="receipt-zero")

    for direction in (PROMOTION_FEE, MANAGEMENT_FEE):
        result = _fee_result(db_session, "coupon-receipt-zero", direction)
        assert result is not None
        assert result.source_amount_cent == 0
        assert result.fee_base_cent == 0
        assert result.fee_amount_cent == 0
    assert not _has_issue(db_session, "dual_fee_missing_coupon_amount", "coupon-receipt-zero")


@pytest.mark.parametrize(
    "order_payload",
    [
        pytest.param({}, id="missing"),
        pytest.param({"receipt_amount": None}, id="null"),
        pytest.param({"receipt_amount": "not-a-number"}, id="invalid"),
        pytest.param({"receipt_amount": -1}, id="negative"),
        pytest.param({"receipt_amount": "100.5"}, id="fractional-cent"),
    ],
)
def test_missing_or_invalid_receipt_blocks_without_paid_fallback(
    db_session: Session, order_payload: dict
) -> None:
    _seed_dual_base(db_session)
    _add_dual_order(
        db_session,
        "order-receipt-blocked",
        paid_cent=10000,
        coupons=[{"coupon_id": "coupon-receipt-blocked"}],
        order_payload=order_payload,
    )

    rebuild_dual_fee_results(db_session, calculation_run_id="receipt-blocked")

    for direction in (PROMOTION_FEE, MANAGEMENT_FEE):
        assert _fee_result(db_session, "coupon-receipt-blocked", direction) is None
    assert _has_issue(db_session, "dual_fee_missing_coupon_amount", "coupon-receipt-blocked")
    # No result at all: the paid amount must not be used as a fallback basis.
    assert _result_count(db_session, "coupon-receipt-blocked") == 0


def test_multi_coupon_coupon_level_receipt_is_attributed_per_coupon(
    db_session: Session,
) -> None:
    _seed_dual_base(db_session)
    _add_dual_order(
        db_session,
        "order-receipt-coupons",
        paid_cent=20000,
        coupons=[
            {"coupon_id": "coupon-receipt-a", "order_item_id": "item-a", "receipt_amount": 3000},
            {"coupon_id": "coupon-receipt-b", "order_item_id": "item-b", "receipt_amount": 5000},
        ],
    )

    rebuild_dual_fee_results(db_session, calculation_run_id="receipt-coupons")

    promotion_a = _fee_result(db_session, "coupon-receipt-a", PROMOTION_FEE)
    management_a = _fee_result(db_session, "coupon-receipt-a", MANAGEMENT_FEE)
    promotion_b = _fee_result(db_session, "coupon-receipt-b", PROMOTION_FEE)
    management_b = _fee_result(db_session, "coupon-receipt-b", MANAGEMENT_FEE)
    assert promotion_a is not None and management_a is not None
    assert promotion_b is not None and management_b is not None
    assert promotion_a.source_amount_cent == 3000
    assert management_a.source_amount_cent == 3000
    assert promotion_b.source_amount_cent == 5000
    assert management_b.source_amount_cent == 5000
    assert promotion_a.fee_amount_cent == 300
    assert management_a.fee_amount_cent == 600
    assert promotion_b.fee_amount_cent == 500
    assert management_b.fee_amount_cent == 1000


def test_multi_coupon_sub_order_amount_infos_maps_by_order_item_id(
    db_session: Session,
) -> None:
    _seed_dual_base(db_session)
    _add_dual_order(
        db_session,
        "order-receipt-sub-items",
        paid_cent=20000,
        coupons=[
            {"coupon_id": "coupon-sub-a", "order_item_id": "item-a"},
            {"coupon_id": "coupon-sub-b", "order_item_id": "item-b"},
        ],
        order_payload={
            "sub_order_amount_infos": [
                {"order_item_id": "item-a", "receipt_amount": 3000},
                {"order_item_id": "item-b", "receipt_amount": 5000},
            ]
        },
    )

    rebuild_dual_fee_results(db_session, calculation_run_id="receipt-sub-items")

    assert _fee_result(db_session, "coupon-sub-a", PROMOTION_FEE).source_amount_cent == 3000
    assert _fee_result(db_session, "coupon-sub-a", MANAGEMENT_FEE).source_amount_cent == 3000
    assert _fee_result(db_session, "coupon-sub-b", PROMOTION_FEE).source_amount_cent == 5000
    assert _fee_result(db_session, "coupon-sub-b", MANAGEMENT_FEE).source_amount_cent == 5000


def test_multi_coupon_order_total_receipt_is_not_repeated_for_each_coupon(
    db_session: Session,
) -> None:
    _seed_dual_base(db_session)
    _add_dual_order(
        db_session,
        "order-receipt-total-only",
        paid_cent=20000,
        coupons=[
            {"coupon_id": "coupon-total-a", "order_item_id": "item-a"},
            {"coupon_id": "coupon-total-b", "order_item_id": "item-b"},
        ],
        order_payload={"receipt_amount": 9000},
    )

    rebuild_dual_fee_results(db_session, calculation_run_id="receipt-total-only")

    for coupon_id in ("coupon-total-a", "coupon-total-b"):
        for direction in (PROMOTION_FEE, MANAGEMENT_FEE):
            assert _fee_result(db_session, coupon_id, direction) is None
        assert _has_issue(db_session, "dual_fee_missing_coupon_amount", coupon_id)
        assert _result_count(db_session, coupon_id) == 0
    repeated = db_session.scalars(
        select(SettlementFeeResult).where(SettlementFeeResult.source_amount_cent == 9000)
    )
    assert list(repeated) == []


def test_single_coupon_sub_order_item_receipt_is_used_in_cent_without_scaling(
    db_session: Session,
) -> None:
    _seed_dual_base(db_session)
    _add_dual_order(
        db_session,
        "order-receipt-cent",
        paid_cent=20000,
        coupons=[{"coupon_id": "coupon-receipt-cent", "order_item_id": "item-cent"}],
        order_payload={
            "sub_order_amount_infos": [
                {"order_item_id": "item-cent", "receipt_amount": 12345}
            ]
        },
    )

    rebuild_dual_fee_results(db_session, calculation_run_id="receipt-cent")

    result = _fee_result(db_session, "coupon-receipt-cent", PROMOTION_FEE)
    management = _fee_result(db_session, "coupon-receipt-cent", MANAGEMENT_FEE)
    assert result is not None and management is not None
    # Already in cents: must not be multiplied by 100.
    assert result.source_amount_cent == 12345
    assert management.source_amount_cent == 12345
    assert result.fee_amount_cent == 1235  # 12345 * 0.1, ROUND_HALF_UP
    assert management.fee_amount_cent == 2469  # 12345 * 0.2, ROUND_HALF_UP


def test_partial_sub_order_amount_infos_cannot_supply_incomplete_total(
    db_session: Session,
) -> None:
    _seed_dual_base(db_session)
    _add_dual_order(
        db_session,
        "order-receipt-partial",
        paid_cent=20000,
        coupons=[
            {"coupon_id": "coupon-partial-a", "order_item_id": "item-a"},
            {"coupon_id": "coupon-partial-b", "order_item_id": "item-b"},
        ],
        order_payload={
            "sub_order_amount_infos": [
                {"order_item_id": "item-a", "receipt_amount": 3000},
                {"order_item_id": "item-b"},
            ]
        },
    )

    rebuild_dual_fee_results(db_session, calculation_run_id="receipt-partial")

    # item-a has its own exact receipt; item-b has none and must stay blocked.
    assert _fee_result(db_session, "coupon-partial-a", PROMOTION_FEE).source_amount_cent == 3000
    for direction in (PROMOTION_FEE, MANAGEMENT_FEE):
        assert _fee_result(db_session, "coupon-partial-b", direction) is None
    assert _has_issue(db_session, "dual_fee_missing_coupon_amount", "coupon-partial-b")
    # The incomplete aggregate (3000) may not stand in for the missing sub-order.
    blocked = db_session.scalars(
        select(SettlementFeeResult).where(
            SettlementFeeResult.coupon_id == "coupon-partial-b"
        )
    )
    assert list(blocked) == []


def test_locked_statement_is_not_rewritten_by_receipt_change(
    db_session: Session,
) -> None:
    _seed_dual_base(db_session)
    _add_dual_order(
        db_session,
        "order-receipt-locked",
        paid_cent=10000,
        coupons=[{"coupon_id": "coupon-receipt-locked", "order_item_id": "item-locked"}],
        order_payload={"receipt_amount": 8000},
    )
    rebuild_dual_fee_results(db_session, calculation_run_id="receipt-locked-seed")
    before = _fee_result(db_session, "coupon-receipt-locked", PROMOTION_FEE)
    assert before is not None
    assert before.source_amount_cent == 8000
    assert before.fee_amount_cent == 800

    for store_id in ("store-sale", "store-verify"):
        lock_settlement_statement(
            db_session,
            store_id=store_id,
            statement_month="2026-09",
            lock_run_id=f"receipt-lock-{store_id}",
        )

    order = db_session.scalar(
        select(RawDouyinOrder).where(RawDouyinOrder.order_id == "order-receipt-locked")
    )
    assert order is not None
    order.raw_payload = {**order.raw_payload, "receipt_amount": 5000}
    db_session.flush()

    rebuild_dual_fee_results(
        db_session, calculation_run_id="receipt-locked-change", force_recalculate=True
    )

    after = _fee_result(db_session, "coupon-receipt-locked", PROMOTION_FEE)
    assert after is not None
    assert after.fee_result_id == before.fee_result_id
    assert after.source_amount_cent == 8000
    assert after.fee_amount_cent == 800


def _monthly_settlement(
    session: Session, month: str, store_id: str
) -> AggStoreMonthlySettlement | None:
    return session.scalar(
        select(AggStoreMonthlySettlement).where(
            AggStoreMonthlySettlement.month == month,
            AggStoreMonthlySettlement.store_id == store_id,
            AggStoreMonthlySettlement.product_scope == "all",
            AggStoreMonthlySettlement.product_type == "all",
        )
    )


def _seed_legacy_cross_store(
    session: Session,
    *,
    order_id: str,
    coupon_id: str,
    order_payload: dict,
    moment: datetime | None = None,
) -> None:
    """Legacy single-fee cross-store fixture carrying a real order payload.

    The cross-store relation must be proven: the legacy owner match reads
    ``RawAwemeBinding`` nickname evidence, so an id-only account row is not
    enough. ``paid_amount_cent`` stays a distinct fact from the receipt.
    ``moment`` lets a test place the event in a month the incremental dual-fee
    projection does not rebuild, so the legacy monthly row survives to be read.
    """

    event_time = moment or _dt(5)
    upsert_store(session, "store-sale", "Sale Store")
    upsert_store(session, "store-verify", "Verify Store")
    upsert_store_poi_mapping(
        session, "store-verify", "poi-verify", mapping_source="test"
    )
    upsert_aweme_account(
        session,
        "owner-legacy",
        nickname="Owner Legacy",
        store_id="store-sale",
        binding_status="active",
    )
    upsert_aweme_binding(
        session,
        "owner-legacy:dy-owner-legacy:poi-sale",
        douyin_id="dy-owner-legacy",
        douyin_nickname="Owner Legacy",
        account_id="store-sale",
        account_name="Sale Store",
        poi_id="poi-sale",
        binding_status="active",
    )
    upsert_sku_product_rule(
        session,
        "sku-legacy",
        "service",
        product_name="Legacy service SKU",
        commission_rate=Decimal("0.1000"),
        is_service_product=True,
    )
    upsert_raw_order(
        session,
        order_id,
        order_status="paid",
        sku_id="sku-legacy",
        pay_time=event_time,
        paid_amount_cent=10000,
        owner_account_id="owner-legacy",
        owner_account_name="Owner Legacy",
        raw_payload=order_payload,
        source_run_id="legacy-receipt-source",
    )
    upsert_order_coupon(
        session,
        coupon_id,
        order_id,
        coupon_status="fulfilled",
        coupon_refunded_cent=0,
        source_run_id="legacy-receipt-source",
    )
    upsert_verify_record(
        session,
        f"verify-{coupon_id}",
        coupon_id=coupon_id,
        verify_status="valid",
        verify_time=event_time,
        poi_id="poi-verify",
        sku_id="sku-legacy",
        paid_amount_cent=10000,
        source_run_id="legacy-receipt-source",
    )
    session.flush()


def test_legacy_commission_uses_receipt_basis_and_preserves_paid_field(
    db_session: Session,
) -> None:
    _seed_legacy_cross_store(
        db_session,
        order_id="order-legacy-receipt",
        coupon_id="coupon-legacy-receipt",
        order_payload={"receipt_amount": 8000},
    )

    run_settlement_job(
        db_session, job_id="job-legacy-receipt", source_run_id="legacy-receipt-run"
    )

    detail = db_session.get(SettlementOrderDetail, "coupon-legacy-receipt")
    assert detail is not None
    assert detail.is_commissionable is True
    assert detail.receivable_commission_cent == 800  # 8000 * 0.1, not 10000 * 0.1
    assert detail.payable_commission_cent == 800
    assert detail.paid_amount_cent == 10000  # paid fact preserved verbatim


def test_legacy_missing_receipt_yields_no_commission(
    db_session: Session,
) -> None:
    _seed_legacy_cross_store(
        db_session,
        order_id="order-legacy-noreceipt",
        coupon_id="coupon-legacy-noreceipt",
        order_payload={},
    )

    run_settlement_job(
        db_session, job_id="job-legacy-noreceipt", source_run_id="legacy-noreceipt-run"
    )

    detail = db_session.get(SettlementOrderDetail, "coupon-legacy-noreceipt")
    assert detail is not None
    # No proven receipt: the paid amount must not be used as a fallback basis.
    assert detail.is_commissionable is False
    assert detail.receivable_commission_cent == 0
    assert detail.payable_commission_cent == 0
    assert detail.paid_amount_cent == 10000  # paid fact still preserved
    # A missing legacy receipt is a data-quality fact, not a silent zero.
    assert _has_issue(
        db_session, "legacy_missing_receipt_amount", "coupon-legacy-noreceipt"
    )


@pytest.mark.parametrize(
    "bad_value",
    [
        pytest.param(True, id="bool-true"),
        pytest.param(False, id="bool-false"),
        pytest.param("NaN", id="nan-string"),
        pytest.param(float("nan"), id="nan-float"),
        pytest.param("Infinity", id="infinity-string"),
        pytest.param(float("inf"), id="infinity-float"),
        pytest.param(float("-inf"), id="negative-infinity"),
    ],
)
def test_boolean_and_non_finite_order_receipts_are_rejected(
    db_session: Session, bad_value: object
) -> None:
    _seed_dual_base(db_session)
    _add_dual_order(
        db_session,
        "order-receipt-nonfinite",
        paid_cent=10000,
        coupons=[{"coupon_id": "coupon-receipt-nonfinite"}],
        order_payload={"receipt_amount": bad_value},
    )

    rebuild_dual_fee_results(db_session, calculation_run_id="receipt-nonfinite")

    for direction in (PROMOTION_FEE, MANAGEMENT_FEE):
        assert _fee_result(db_session, "coupon-receipt-nonfinite", direction) is None
    assert _has_issue(
        db_session, "dual_fee_missing_coupon_amount", "coupon-receipt-nonfinite"
    )
    assert _result_count(db_session, "coupon-receipt-nonfinite") == 0


def test_multi_coupon_sharing_one_item_is_ambiguous_and_blocked(
    db_session: Session,
) -> None:
    _seed_dual_base(db_session)
    _add_dual_order(
        db_session,
        "order-receipt-shared-item",
        paid_cent=20000,
        coupons=[
            {"coupon_id": "coupon-shared-a", "order_item_id": "shared-item"},
            {"coupon_id": "coupon-shared-b", "order_item_id": "shared-item"},
        ],
        order_payload={
            "sub_order_amount_infos": [
                {"order_item_id": "shared-item", "receipt_amount": 3000}
            ]
        },
    )

    rebuild_dual_fee_results(db_session, calculation_run_id="receipt-shared-item")

    for coupon_id in ("coupon-shared-a", "coupon-shared-b"):
        for direction in (PROMOTION_FEE, MANAGEMENT_FEE):
            assert _fee_result(db_session, coupon_id, direction) is None
        assert _has_issue(db_session, "dual_fee_missing_coupon_amount", coupon_id)
        assert _result_count(db_session, coupon_id) == 0


def test_single_coupon_partial_sub_order_total_is_not_used(
    db_session: Session,
) -> None:
    _seed_dual_base(db_session)
    _add_dual_order(
        db_session,
        "order-receipt-single-partial",
        paid_cent=20000,
        coupons=[{"coupon_id": "coupon-single-partial"}],
        order_payload={
            "sub_order_amount_infos": [
                {"order_item_id": "item-a", "receipt_amount": 3000},
                {"order_item_id": "item-b"},
            ]
        },
    )

    rebuild_dual_fee_results(db_session, calculation_run_id="receipt-single-partial")

    # The incomplete 3000 sub-order sum cannot stand in for the coupon receipt.
    for direction in (PROMOTION_FEE, MANAGEMENT_FEE):
        assert _fee_result(db_session, "coupon-single-partial", direction) is None
    assert _has_issue(
        db_session, "dual_fee_missing_coupon_amount", "coupon-single-partial"
    )


def test_refund_uses_receipt_base_without_double_subtracting_paid(
    db_session: Session,
) -> None:
    _seed_dual_base(db_session)
    _add_dual_order(
        db_session,
        "order-receipt-refund",
        paid_cent=10000,
        coupons=[{"coupon_id": "coupon-receipt-refund", "order_item_id": "item-r"}],
        order_payload={"receipt_amount": 8000},
    )
    db_session.add(
        DouyinRefundEvent(
            refund_event_id="refund-receipt",
            order_id="order-receipt-refund",
            coupon_id="coupon-receipt-refund",
            refund_type=1,
            refund_status=2,
            refund_amount_cent=3000,
            occurred_at=_dt(10),
            source_run_id="receipt-refund",
            raw_payload={},
        )
    )
    db_session.flush()

    rebuild_dual_fee_results(db_session, calculation_run_id="receipt-refund")

    promotion = _fee_result(db_session, "coupon-receipt-refund", PROMOTION_FEE)
    management = _fee_result(db_session, "coupon-receipt-refund", MANAGEMENT_FEE)
    assert promotion is not None and management is not None
    # One receipt base (8000, not paid 10000) minus the refund once.
    assert promotion.source_amount_cent == 8000
    assert promotion.refunded_amount_cent == 3000
    assert promotion.fee_base_cent == 5000
    assert promotion.fee_amount_cent == 500
    assert management.source_amount_cent == 8000
    assert management.refunded_amount_cent == 3000
    assert management.fee_base_cent == 5000
    assert management.fee_amount_cent == 1000


# ---------------------------------------------------------------------------
# Review round 2: sub-order aggregates, corrupt evidence, interface count,
# legacy monthly basis and locked-statement freeze.
# ---------------------------------------------------------------------------


def test_single_coupon_multi_sub_entries_sum_to_order_receipt(
    db_session: Session,
) -> None:
    """One coupon with two no-id sub lines must sum to the whole receipt."""

    _seed_dual_base(db_session)
    _add_dual_order(
        db_session,
        "order-receipt-aggregate",
        paid_cent=10000,
        coupons=[{"coupon_id": "coupon-receipt-aggregate"}],
        order_payload={
            "sub_order_amount_infos": [
                {"receipt_amount": 5000},
                {"receipt_amount": 3000},
            ]
        },
    )

    rebuild_dual_fee_results(db_session, calculation_run_id="receipt-aggregate")

    promotion = _fee_result(db_session, "coupon-receipt-aggregate", PROMOTION_FEE)
    management = _fee_result(db_session, "coupon-receipt-aggregate", MANAGEMENT_FEE)
    assert promotion is not None and management is not None
    # 5000 + 3000, not a single line and not the paid 10000.
    assert promotion.source_amount_cent == 8000
    assert management.source_amount_cent == 8000
    assert promotion.fee_amount_cent == 800
    assert management.fee_amount_cent == 1600


def test_single_coupon_multi_sub_entries_aggregate_beats_order_total(
    db_session: Session,
) -> None:
    """The authoritative sub-order sum wins over a differing order total."""

    _seed_dual_base(db_session)
    _add_dual_order(
        db_session,
        "order-receipt-aggregate-override",
        paid_cent=10000,
        coupons=[{"coupon_id": "coupon-receipt-aggregate-override"}],
        order_payload={
            "receipt_amount": 9999,
            "sub_order_amount_infos": [
                {"receipt_amount": 5000},
                {"receipt_amount": 3000},
            ],
        },
    )

    rebuild_dual_fee_results(
        db_session, calculation_run_id="receipt-aggregate-override"
    )

    promotion = _fee_result(
        db_session, "coupon-receipt-aggregate-override", PROMOTION_FEE
    )
    assert promotion is not None
    assert promotion.source_amount_cent == 8000
    assert promotion.source_amount_cent != 9999


def test_multi_coupon_sub_entries_without_item_id_are_not_aggregated(
    db_session: Session,
) -> None:
    """A no-id sub-order split can never be attributed across coupons."""

    _seed_dual_base(db_session)
    _add_dual_order(
        db_session,
        "order-receipt-multi-noid",
        paid_cent=20000,
        coupons=[
            {"coupon_id": "coupon-multi-noid-a"},
            {"coupon_id": "coupon-multi-noid-b"},
        ],
        order_payload={
            "sub_order_amount_infos": [
                {"receipt_amount": 5000},
                {"receipt_amount": 3000},
            ]
        },
    )

    rebuild_dual_fee_results(db_session, calculation_run_id="receipt-multi-noid")

    for coupon_id in ("coupon-multi-noid-a", "coupon-multi-noid-b"):
        for direction in (PROMOTION_FEE, MANAGEMENT_FEE):
            assert _fee_result(db_session, coupon_id, direction) is None
        assert _has_issue(db_session, "dual_fee_missing_coupon_amount", coupon_id)
    assert _result_count(db_session, "coupon-multi-noid-a") == 0


def test_single_coupon_duplicate_sub_attribution_blocks_aggregate(
    db_session: Session,
) -> None:
    """An explicit duplicate item line makes the whole sum unprovable."""

    _seed_dual_base(db_session)
    _add_dual_order(
        db_session,
        "order-receipt-duplicate-line",
        paid_cent=10000,
        coupons=[{"coupon_id": "coupon-receipt-duplicate-line"}],
        order_payload={
            "sub_order_amount_infos": [
                {"order_item_id": "item-dup", "receipt_amount": 5000},
                {"order_item_id": "item-dup", "receipt_amount": 3000},
            ]
        },
    )

    rebuild_dual_fee_results(db_session, calculation_run_id="receipt-duplicate-line")

    for direction in (PROMOTION_FEE, MANAGEMENT_FEE):
        assert _fee_result(db_session, "coupon-receipt-duplicate-line", direction) is None
    assert _has_issue(
        db_session, "dual_fee_missing_coupon_amount", "coupon-receipt-duplicate-line"
    )


def test_single_coupon_corrupt_sub_entry_blocks_even_with_own_item_id(
    db_session: Session,
) -> None:
    """A coupon's own line must not mask a corrupt sibling line."""

    _seed_dual_base(db_session)
    _add_dual_order(
        db_session,
        "order-receipt-corrupt-sibling",
        paid_cent=10000,
        coupons=[
            {"coupon_id": "coupon-receipt-corrupt-sibling", "order_item_id": "item-a"}
        ],
        order_payload={
            "sub_order_amount_infos": [
                {"order_item_id": "item-a", "receipt_amount": 5000},
                {"order_item_id": "item-b"},
            ]
        },
    )

    rebuild_dual_fee_results(db_session, calculation_run_id="receipt-corrupt-sibling")

    for direction in (PROMOTION_FEE, MANAGEMENT_FEE):
        assert (
            _fee_result(db_session, "coupon-receipt-corrupt-sibling", direction) is None
        )
    assert _has_issue(
        db_session, "dual_fee_missing_coupon_amount", "coupon-receipt-corrupt-sibling"
    )


def test_single_coupon_corrupt_no_id_entry_is_not_ignored(
    db_session: Session,
) -> None:
    """A corrupt no-id line blocks; the order total must not mask it."""

    _seed_dual_base(db_session)
    _add_dual_order(
        db_session,
        "order-receipt-corrupt-noid",
        paid_cent=10000,
        coupons=[{"coupon_id": "coupon-receipt-corrupt-noid"}],
        order_payload={
            "receipt_amount": 8000,
            "sub_order_amount_infos": [
                {"order_item_id": "item-a", "receipt_amount": 5000},
                {"receipt_amount": "bad"},
            ],
        },
    )

    rebuild_dual_fee_results(db_session, calculation_run_id="receipt-corrupt-noid")

    for direction in (PROMOTION_FEE, MANAGEMENT_FEE):
        assert _fee_result(db_session, "coupon-receipt-corrupt-noid", direction) is None
    assert _has_issue(
        db_session, "dual_fee_missing_coupon_amount", "coupon-receipt-corrupt-noid"
    )
    assert _result_count(db_session, "coupon-receipt-corrupt-noid") == 0


def test_single_coupon_interface_count_above_one_blocks_order_basis(
    db_session: Session,
) -> None:
    """A proven interface count > 1 forbids the whole-order basis."""

    _seed_dual_base(db_session)
    _add_dual_order(
        db_session,
        "order-receipt-count-two",
        paid_cent=10000,
        coupons=[{"coupon_id": "coupon-receipt-count-two"}],
        order_payload={
            "receipt_amount": 9999,
            "count": 2,
            "sub_order_amount_infos": [
                {"receipt_amount": 5000},
                {"receipt_amount": 3000},
            ],
        },
    )

    rebuild_dual_fee_results(db_session, calculation_run_id="receipt-count-two")

    for direction in (PROMOTION_FEE, MANAGEMENT_FEE):
        assert _fee_result(db_session, "coupon-receipt-count-two", direction) is None
    assert _has_issue(
        db_session, "dual_fee_missing_coupon_amount", "coupon-receipt-count-two"
    )
    assert _result_count(db_session, "coupon-receipt-count-two") == 0


def test_single_coupon_interface_count_one_allows_order_receipt(
    db_session: Session,
) -> None:
    """A proven single unit keeps the existing single-coupon order total."""

    _seed_dual_base(db_session)
    _add_dual_order(
        db_session,
        "order-receipt-count-one",
        paid_cent=10000,
        coupons=[
            {"coupon_id": "coupon-receipt-count-one", "order_item_id": "item-one"}
        ],
        order_payload={"receipt_amount": 8000, "count": 1},
    )

    rebuild_dual_fee_results(db_session, calculation_run_id="receipt-count-one")

    promotion = _fee_result(db_session, "coupon-receipt-count-one", PROMOTION_FEE)
    assert promotion is not None
    assert promotion.source_amount_cent == 8000


@pytest.mark.parametrize(
    "coupon_receipt",
    [
        pytest.param("bad", id="invalid"),
        pytest.param(None, id="null"),
    ],
)
def test_coupon_level_unusable_receipt_blocks_despite_valid_order_receipt(
    db_session: Session, coupon_receipt: object
) -> None:
    """A present-but-corrupt coupon field must not fall back to the order."""

    _seed_dual_base(db_session)
    _add_dual_order(
        db_session,
        "order-receipt-coupon-bad",
        paid_cent=10000,
        coupons=[
            {
                "coupon_id": "coupon-receipt-coupon-bad",
                "order_item_id": "item-bad",
                "receipt_amount": coupon_receipt,
            }
        ],
        order_payload={"receipt_amount": 8000},
    )

    rebuild_dual_fee_results(db_session, calculation_run_id="receipt-coupon-bad")

    for direction in (PROMOTION_FEE, MANAGEMENT_FEE):
        assert _fee_result(db_session, "coupon-receipt-coupon-bad", direction) is None
    assert _has_issue(
        db_session, "dual_fee_missing_coupon_amount", "coupon-receipt-coupon-bad"
    )
    assert _result_count(db_session, "coupon-receipt-coupon-bad") == 0


def test_corrupt_sub_order_array_blocks_instead_of_order_receipt(
    db_session: Session,
) -> None:
    """A present but corrupt sub array must not be masked by the order total."""

    _seed_dual_base(db_session)
    _add_dual_order(
        db_session,
        "order-receipt-corrupt-array",
        paid_cent=10000,
        coupons=[{"coupon_id": "coupon-receipt-corrupt-array"}],
        order_payload={
            "receipt_amount": 8000,
            "sub_order_amount_infos": [{"receipt_amount": "bad"}],
        },
    )

    rebuild_dual_fee_results(db_session, calculation_run_id="receipt-corrupt-array")

    for direction in (PROMOTION_FEE, MANAGEMENT_FEE):
        assert (
            _fee_result(db_session, "coupon-receipt-corrupt-array", direction) is None
        )
    assert _has_issue(
        db_session, "dual_fee_missing_coupon_amount", "coupon-receipt-corrupt-array"
    )


def test_coupon_level_zero_receipt_beats_order_receipt(db_session: Session) -> None:
    """A proven coupon-level 0 keeps priority over a non-zero order total."""

    _seed_dual_base(db_session)
    _add_dual_order(
        db_session,
        "order-receipt-zero-level",
        paid_cent=10000,
        coupons=[{"coupon_id": "coupon-receipt-zero-level", "receipt_amount": 0}],
        order_payload={"receipt_amount": 8000},
    )

    rebuild_dual_fee_results(db_session, calculation_run_id="receipt-zero-level")

    for direction in (PROMOTION_FEE, MANAGEMENT_FEE):
        result = _fee_result(db_session, "coupon-receipt-zero-level", direction)
        assert result is not None
        assert result.source_amount_cent == 0
        assert result.fee_amount_cent == 0


@pytest.mark.parametrize(
    "order_payload",
    [
        pytest.param({}, id="missing"),
        pytest.param({"receipt_amount": "bad"}, id="invalid"),
    ],
)
def test_locked_statement_survives_unprovable_receipt_force_recalculation(
    db_session: Session, order_payload: dict
) -> None:
    """force recalculation must not delete a frozen amount when receipt breaks."""

    _seed_dual_base(db_session)
    _add_dual_order(
        db_session,
        "order-receipt-locked-bad",
        paid_cent=10000,
        coupons=[
            {"coupon_id": "coupon-receipt-locked-bad", "order_item_id": "item-locked"}
        ],
        order_payload={"receipt_amount": 8000},
    )
    rebuild_dual_fee_results(db_session, calculation_run_id="receipt-locked-bad-seed")
    before = _fee_result(db_session, "coupon-receipt-locked-bad", PROMOTION_FEE)
    assert before is not None
    assert before.source_amount_cent == 8000
    assert before.fee_amount_cent == 800

    for store_id in ("store-sale", "store-verify"):
        lock_settlement_statement(
            db_session,
            store_id=store_id,
            statement_month="2026-09",
            lock_run_id=f"receipt-lock-bad-{store_id}",
        )

    order = db_session.scalar(
        select(RawDouyinOrder).where(
            RawDouyinOrder.order_id == "order-receipt-locked-bad"
        )
    )
    assert order is not None
    order.raw_payload = dict(order_payload)
    db_session.flush()

    rebuild_dual_fee_results(
        db_session,
        calculation_run_id="receipt-locked-bad-force",
        force_recalculate=True,
    )

    after = _fee_result(db_session, "coupon-receipt-locked-bad", PROMOTION_FEE)
    assert after is not None
    assert after.fee_result_id == before.fee_result_id
    assert after.source_amount_cent == 8000
    assert after.fee_amount_cent == 800


def test_legacy_monthly_commissionable_total_uses_receipt_basis(
    db_session: Session,
) -> None:
    """Legacy monthly base must be the receipt, never the paid amount."""

    moment = datetime(2026, 7, 5, 2, 0, tzinfo=timezone.utc)
    _seed_legacy_cross_store(
        db_session,
        order_id="order-legacy-monthly",
        coupon_id="coupon-legacy-monthly",
        order_payload={"receipt_amount": 8000},
        moment=moment,
    )

    run_settlement_job(
        db_session, job_id="job-legacy-monthly", source_run_id="legacy-monthly-run"
    )

    detail = db_session.get(SettlementOrderDetail, "coupon-legacy-monthly")
    assert detail is not None
    assert detail.is_commissionable is True
    assert detail.receivable_commission_cent == 800
    assert detail.paid_amount_cent == 10000

    monthly = _monthly_settlement(db_session, "2026-07", "store-sale")
    assert monthly is not None
    # paid 10000 must not become the monthly commissionable base.
    assert monthly.commissionable_total_cent == 8000
    assert monthly.estimated_receivable_commission_cent == 800


def test_legacy_monthly_commissionable_total_keeps_receipt_on_rounding(
    db_session: Session,
) -> None:
    """Monthly base keeps the raw receipt instead of reverse-engineering fees."""

    moment = datetime(2026, 7, 6, 2, 0, tzinfo=timezone.utc)
    _seed_legacy_cross_store(
        db_session,
        order_id="order-legacy-rounding",
        coupon_id="coupon-legacy-rounding",
        order_payload={"receipt_amount": 12345},
        moment=moment,
    )

    run_settlement_job(
        db_session, job_id="job-legacy-rounding", source_run_id="legacy-rounding-run"
    )

    detail = db_session.get(SettlementOrderDetail, "coupon-legacy-rounding")
    assert detail is not None
    assert detail.receivable_commission_cent == 1235  # 1234.5 rounds half up
    assert detail.paid_amount_cent == 10000

    monthly = _monthly_settlement(db_session, "2026-07", "store-sale")
    assert monthly is not None
    # 1235 / 0.10 would be 12350; the raw receipt is the authoritative base.
    assert monthly.commissionable_total_cent == 12345


# ---------------------------------------------------------------------------
# Review round 3: a present-but-non-list ``sub_order_amount_infos`` is damaged
# evidence and must block. An absent field and an explicitly empty list are not
# damage: they carry no sub-order lines, so the valid whole-order receipt (or a
# proven 0) is still used.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "corrupt_value",
    [
        pytest.param(None, id="null"),
        pytest.param({"receipt_amount": 3000}, id="dict"),
        pytest.param("3000", id="string"),
        pytest.param(3000, id="number"),
    ],
)
def test_sub_order_field_present_but_not_a_list_is_corrupt(
    corrupt_value: object,
) -> None:
    """Parsing flags a non-list field as damage instead of treating it absent."""

    parsed = SubOrderReceipts.from_payload({"sub_order_amount_infos": corrupt_value})

    assert parsed.corrupt is True
    assert parsed.entries_present is False
    assert parsed.complete_total is None


def test_sub_order_absent_or_explicitly_empty_is_not_corrupt() -> None:
    """A missing field and ``[]`` are both "no sub lines", not damaged evidence."""

    absent = SubOrderReceipts.from_payload({})
    empty = SubOrderReceipts.from_payload({"sub_order_amount_infos": []})

    for parsed in (absent, empty):
        assert parsed.corrupt is False
        assert parsed.entries_present is False
        assert parsed.complete_total is None
        assert parsed.unique == {}
        assert parsed.unusable == frozenset()


@pytest.mark.parametrize(
    "corrupt_value",
    [
        pytest.param(None, id="null"),
        pytest.param({"receipt_amount": 3000}, id="dict"),
        pytest.param("3000", id="string"),
        pytest.param(3000, id="number"),
    ],
)
def test_present_non_list_sub_order_field_blocks_valid_order_receipt(
    db_session: Session, corrupt_value: object
) -> None:
    """A corrupt sub field must not be masked by the legitimate whole-order 8000."""

    _seed_dual_base(db_session)
    _add_dual_order(
        db_session,
        "order-receipt-sub-type",
        paid_cent=10000,
        coupons=[{"coupon_id": "coupon-receipt-sub-type"}],
        order_payload={
            "receipt_amount": 8000,
            "sub_order_amount_infos": corrupt_value,
        },
    )

    rebuild_dual_fee_results(db_session, calculation_run_id="receipt-sub-type")

    for direction in (PROMOTION_FEE, MANAGEMENT_FEE):
        assert _fee_result(db_session, "coupon-receipt-sub-type", direction) is None
    assert _has_issue(
        db_session, "dual_fee_missing_coupon_amount", "coupon-receipt-sub-type"
    )
    assert _result_count(db_session, "coupon-receipt-sub-type") == 0


def test_absent_sub_order_field_uses_valid_order_receipt(db_session: Session) -> None:
    """A missing sub field leaves the single-coupon order receipt usable."""

    _seed_dual_base(db_session)
    _add_dual_order(
        db_session,
        "order-receipt-sub-absent",
        paid_cent=10000,
        coupons=[{"coupon_id": "coupon-receipt-sub-absent"}],
        order_payload={"receipt_amount": 8000},
    )

    rebuild_dual_fee_results(db_session, calculation_run_id="receipt-sub-absent")

    promotion = _fee_result(db_session, "coupon-receipt-sub-absent", PROMOTION_FEE)
    management = _fee_result(db_session, "coupon-receipt-sub-absent", MANAGEMENT_FEE)
    assert promotion is not None and management is not None
    assert promotion.source_amount_cent == 8000
    assert management.source_amount_cent == 8000
    assert promotion.fee_amount_cent == 800
    assert management.fee_amount_cent == 1600
    assert not _has_issue(
        db_session, "dual_fee_missing_coupon_amount", "coupon-receipt-sub-absent"
    )


def test_explicit_empty_sub_order_list_uses_valid_order_receipt(
    db_session: Session,
) -> None:
    """An explicit ``[]`` means "no sub lines" and keeps the order receipt."""

    _seed_dual_base(db_session)
    _add_dual_order(
        db_session,
        "order-receipt-sub-empty",
        paid_cent=10000,
        coupons=[{"coupon_id": "coupon-receipt-sub-empty"}],
        order_payload={"receipt_amount": 8000, "sub_order_amount_infos": []},
    )

    rebuild_dual_fee_results(db_session, calculation_run_id="receipt-sub-empty")

    promotion = _fee_result(db_session, "coupon-receipt-sub-empty", PROMOTION_FEE)
    management = _fee_result(db_session, "coupon-receipt-sub-empty", MANAGEMENT_FEE)
    assert promotion is not None and management is not None
    assert promotion.source_amount_cent == 8000
    assert management.source_amount_cent == 8000
    assert promotion.fee_amount_cent == 800
    assert management.fee_amount_cent == 1600
    assert not _has_issue(
        db_session, "dual_fee_missing_coupon_amount", "coupon-receipt-sub-empty"
    )


@pytest.mark.parametrize(
    "order_payload",
    [
        pytest.param({"receipt_amount": 0}, id="absent-sub"),
        pytest.param(
            {"receipt_amount": 0, "sub_order_amount_infos": []}, id="empty-sub"
        ),
    ],
)
def test_zero_order_receipt_stays_zero_for_absent_or_empty_sub(
    db_session: Session, order_payload: dict
) -> None:
    """A proven order-level 0 is kept as 0, never confused with a missing value."""

    _seed_dual_base(db_session)
    _add_dual_order(
        db_session,
        "order-receipt-zero-sub",
        paid_cent=10000,
        coupons=[{"coupon_id": "coupon-receipt-zero-sub"}],
        order_payload=order_payload,
    )

    rebuild_dual_fee_results(db_session, calculation_run_id="receipt-zero-sub")

    for direction in (PROMOTION_FEE, MANAGEMENT_FEE):
        result = _fee_result(db_session, "coupon-receipt-zero-sub", direction)
        assert result is not None
        assert result.source_amount_cent == 0
        assert result.fee_base_cent == 0
        assert result.fee_amount_cent == 0
    assert not _has_issue(
        db_session, "dual_fee_missing_coupon_amount", "coupon-receipt-zero-sub"
    )


def test_receipt_batch_variable_limit_resolves_all_coupons_without_n_plus_one(
    db_session: Session,
) -> None:
    """DYDATA-97: a large coupon batch must be chunked, not one huge IN list.

    This is a real-database regression for ``_receipt_amounts_for_details``.
    The connection is capped at 999 bound variables for the duration of the
    call, so the previous single ``IN (1001 coupons)`` lookup raises
    ``too many SQL variables``. The fixed implementation must chunk its reads
    and still return every coupon's proven receipt with a bounded number of
    read statements instead of a query per coupon.

    The cap is applied to this test's SQLite connection only and restored in
    ``finally``; query counting is removed in the same ``finally``.
    """

    coupon_total = 1001

    order = RawDouyinOrder(
        order_id="order-receipt-batch-limit",
        order_status_normalized="paid",
        raw_payload={},
        source_run_id="receipt-batch-limit",
    )
    db_session.add(order)
    db_session.flush()

    expected: dict[str, int] = {}
    coupons: list[RawDouyinOrderCoupon] = []
    for index in range(coupon_total):
        coupon_id = f"coupon-receipt-batch-{index:04d}"
        receipt_cent = 8000 + index
        expected[coupon_id] = receipt_cent
        coupons.append(
            RawDouyinOrderCoupon(
                coupon_id=coupon_id,
                order_id=order.order_id,
                raw_order_id=order.id,
                order_item_id=f"item-receipt-batch-{index:04d}",
                coupon_status_normalized="available",
                raw_payload={"receipt_amount": receipt_cent},
                source_run_id="receipt-batch-limit",
            )
        )
    db_session.add_all(coupons)
    db_session.flush()

    # The helper only reads ``coupon_id`` from each detail.
    details = [SimpleNamespace(coupon_id=coupon_id) for coupon_id in expected]

    read_statements: list[str] = []
    bind = db_session.get_bind()

    def _count_read_statements(
        _conn: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        if statement.lstrip().lower().startswith("select"):
            read_statements.append(statement)

    event.listen(bind, "before_cursor_execute", _count_read_statements)
    raw_connection = db_session.connection().connection
    driver_connection = getattr(raw_connection, "driver_connection", raw_connection)
    previous_limit = driver_connection.getlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER)
    driver_connection.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 999)
    try:
        receipts = _receipt_amounts_for_details(db_session, details)
    finally:
        driver_connection.setlimit(
            sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, previous_limit
        )
        event.remove(bind, "before_cursor_execute", _count_read_statements)

    # Every one of the 1001 coupons resolves to its own proven receipt amount,
    # even though the wire batch can no longer fit in a single IN parameter list.
    assert len(receipts) == coupon_total
    assert receipts == expected
    # Chunked prefetch, not one query per coupon.
    assert len(read_statements) <= 20, (
        "expected a bounded number of receipt reads for 1001 coupons, "
        f"got {len(read_statements)}"
    )
