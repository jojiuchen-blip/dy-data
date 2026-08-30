from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from apps.api.dy_api.models import (
    DataQualityIssue,
    DimAwemeAccount,
    DimSkuProductRule,
    DimStore,
    DimStorePoiMapping,
    DouyinRefundEvent,
    JobImpact,
    RawAwemeBinding,
    RawDouyinOrder,
    RawDouyinOrderCoupon,
    RawDouyinVerifyRecord,
    SettlementFeeAdjustment,
    SettlementOrderDetail,
    SettlementFeeResult,
    SettlementFeeResultCurrent,
    SettlementStatement,
    SettlementStatementEntry,
    SettlementStatementLine,
    SettlementScopeRule,
    SkuFeeRule,
)
import apps.worker.settlement as settlement_worker


def test_fee_result_fingerprint_is_stable_and_excludes_run_id() -> None:
    first = settlement_worker._fee_result_input_fingerprint(
        coupon_id="coupon-a",
        order_id="order-a",
        fee_direction=1,
        original_business_month="2026-08",
        rule_match_date=date(2026, 8, 7),
        sale_store_id="store-sale",
        verify_store_id="store-verify",
        sku_id="sku-a",
        product_scope="service",
        product_type="service",
        sale_channel_normalized="live",
        source_amount_cent=10000,
        refunded_amount_cent=0,
        fee_base_cent=10000,
        fee_rate=Decimal("0.100000"),
        fee_amount_cent=1000,
        rule_version="fee-v1",
        scope_rule_version="scope-v1",
        result_status=1,
    )
    second = settlement_worker._fee_result_input_fingerprint(
        coupon_id="coupon-a",
        order_id="order-a",
        fee_direction=1,
        original_business_month="2026-08",
        rule_match_date=date(2026, 8, 7),
        sale_store_id="store-sale",
        verify_store_id="store-verify",
        sku_id="sku-a",
        product_scope="service",
        product_type="service",
        sale_channel_normalized="live",
        source_amount_cent=10000,
        refunded_amount_cent=0,
        fee_base_cent=10000,
        fee_rate=Decimal("0.1"),
        fee_amount_cent=1000,
        rule_version="fee-v1",
        scope_rule_version="scope-v1",
        result_status=1,
    )

    assert first == second
    assert len(first) == 64


def test_incremental_dqi_identity_does_not_include_source_run_id() -> None:
    first = settlement_worker._issue_id(
        "incremental_invalid_coupon",
        "order-a",
        "coupon-a",
        "run-a",
        identity_suffix="invalid-or-closed",
        include_source_run=False,
    )
    second = settlement_worker._issue_id(
        "incremental_invalid_coupon",
        "order-a",
        "coupon-a",
        "run-b",
        identity_suffix="invalid-or-closed",
        include_source_run=False,
    )

    assert first == second


def _seed_local_coupon(
    session,
    coupon_id: str = "coupon-a",
    *,
    seed_dimensions: bool = True,
) -> RawDouyinOrderCoupon:
    observed = datetime(2026, 8, 7, 10, tzinfo=timezone.utc)
    if seed_dimensions:
        session.add_all(
            [
                DimStore(store_id="store-sale", store_name="Sale"),
                DimStore(store_id="store-verify", store_name="Verify"),
                DimAwemeAccount(
                    account_id="owner-sale",
                    nickname="Sale owner",
                    store_id="store-sale",
                    binding_status="active",
                ),
                RawAwemeBinding(
                    binding_key="binding-owner-sale",
                    douyin_nickname="Sale owner",
                    account_id="owner-sale",
                    account_name="Sale owner",
                    binding_status="active",
                ),
                DimStorePoiMapping(
                    store_id="store-verify",
                    poi_id="poi-verify",
                    poi_name="Verify",
                ),
                DimSkuProductRule(
                    sku_id="sku-service",
                    product_type="service",
                    product_scope="service",
                    is_service_product=True,
                    is_active_product=True,
                    owner_account_id="owner-product",
                    commission_rate=Decimal("0.1000"),
                ),
                SettlementScopeRule(
                    scope_rule_version="scope-v1",
                    idempotency_key_hash="scope-idempotency",
                    request_payload_sha256="a" * 64,
                    effective_month="2026-08",
                    owner_account_id="owner-product",
                    sale_channel_normalized="live",
                    is_active=True,
                    created_by="test",
                    change_reason="test",
                ),
                SkuFeeRule(
                    rule_version="fee-v1",
                    idempotency_key_hash="fee-idempotency",
                    request_payload_sha256="b" * 64,
                    sku_id="sku-service",
                    sku_name_snapshot="Service",
                    product_scope_snapshot="service",
                    product_type_snapshot="service",
                    promotion_service_fee_rate=Decimal("0.100000"),
                    management_service_fee_rate=Decimal("0.050000"),
                    effective_date=date(2026, 8, 1),
                    effective_at=observed,
                    rule_status=1,
                    created_by="test",
                    change_reason="test",
                    published_at=observed,
                ),
            ]
        )
        session.flush()
    order = RawDouyinOrder(
        order_id=f"order-{coupon_id}",
        order_status="paid",
        order_status_normalized="paid",
        sku_id="sku-service",
        product_name="Service",
        sale_channel="live",
        sale_channel_normalized="live",
        pay_time=observed,
        sale_time=observed,
        create_order_time=observed,
        paid_amount_cent=10000,
        order_paid_amount_cent=10000,
        owner_account_id="owner-sale",
        owner_account_name="Sale owner",
    )
    session.add(order)
    session.flush()
    coupon = RawDouyinOrderCoupon(
        coupon_id=coupon_id,
        order_id=order.order_id,
        raw_order_id=order.id,
        coupon_status="fulfilled",
        coupon_status_normalized="fulfilled",
        coupon_paid_amount_cent=10000,
    )
    session.add(coupon)
    session.add(
        RawDouyinVerifyRecord(
            verify_id=f"verify-{coupon_id}",
            coupon_id=coupon_id,
            verify_status="valid",
            verify_time=observed,
            poi_id="poi-verify",
            sku_id="sku-service",
            paid_amount_cent=10000,
        )
    )
    session.flush()
    return coupon


def test_local_kernel_same_input_different_run_and_a_b_a_are_version_idempotent(
    db_session,
) -> None:
    coupon = _seed_local_coupon(db_session)
    first = settlement_worker.settle_coupon_local(db_session, coupon, "run-a")
    db_session.commit()
    first_results = list(
        db_session.scalars(
            select(SettlementFeeResult)
            .where(SettlementFeeResult.coupon_id == coupon.coupon_id)
            .order_by(SettlementFeeResult.fee_direction)
        )
    )
    first_ids = {row.fee_direction: row.fee_result_id for row in first_results}
    first_fingerprints = {
        row.fee_direction: row.input_fingerprint for row in first_results
    }

    repeat = settlement_worker.settle_coupon_local(db_session, coupon, "run-b")
    db_session.commit()
    assert repeat["result_count"] == 0
    assert repeat["adjustment_count"] == 0
    assert db_session.scalar(select(SettlementFeeResultCurrent.id)) is not None
    assert db_session.scalar(
        select(SettlementFeeResult.id).where(
            SettlementFeeResult.coupon_id == coupon.coupon_id
        )
    ) is not None

    verify = db_session.scalar(
        select(RawDouyinVerifyRecord).where(
            RawDouyinVerifyRecord.coupon_id == coupon.coupon_id
        )
    )
    assert verify is not None
    coupon.coupon_paid_amount_cent = 9000
    verify.paid_amount_cent = 9000
    db_session.flush()
    settlement_worker.settle_coupon_local(db_session, coupon, "run-c")
    db_session.commit()
    coupon.coupon_paid_amount_cent = 10000
    verify.paid_amount_cent = 10000
    db_session.flush()
    settlement_worker.settle_coupon_local(db_session, coupon, "run-d")
    db_session.commit()

    versions = {
        direction: [
            row.result_version
            for row in db_session.scalars(
                select(SettlementFeeResult)
                .where(
                    SettlementFeeResult.coupon_id == coupon.coupon_id,
                    SettlementFeeResult.fee_direction == direction,
                )
                .order_by(SettlementFeeResult.result_version)
            )
        ]
        for direction in (1, 2)
    }
    assert versions == {1: [1, 2, 3], 2: [1, 2, 3]}
    final_results = {
        row.fee_direction: row
        for row in db_session.scalars(
            select(SettlementFeeResult)
            .where(SettlementFeeResult.coupon_id == coupon.coupon_id)
            .order_by(SettlementFeeResult.id)
        )
    }
    assert final_results[1].input_fingerprint == first_fingerprints[1]
    assert final_results[2].input_fingerprint == first_fingerprints[2]
    assert final_results[1].fee_result_id != first_ids[1]
    assert final_results[2].fee_result_id != first_ids[2]


def test_local_kernel_bounded_path_does_not_count_global_fee_tables(
    db_session, monkeypatch
) -> None:
    coupon = _seed_local_coupon(db_session)
    original_model_count = settlement_worker._model_count

    def fail_on_global_fee_count(session, model):
        if model in (SettlementFeeResult, SettlementFeeAdjustment):
            raise AssertionError("bounded local settlement must not count a global fee table")
        return original_model_count(session, model)

    monkeypatch.setattr(settlement_worker, "_model_count", fail_on_global_fee_count)
    result = settlement_worker.settle_coupon_local(db_session, coupon, "run-local")
    db_session.commit()

    assert result["completed"] is True
    assert result["result_count"] == 2


def test_legacy_force_recalculate_creates_new_version_for_same_fingerprint(
    db_session,
) -> None:
    coupon = _seed_local_coupon(db_session)
    settlement_worker.rebuild_dual_fee_results(
        db_session, calculation_run_id="run-a"
    )
    db_session.commit()

    forced = settlement_worker.rebuild_dual_fee_results(
        db_session,
        calculation_run_id="run-b",
        force_recalculate=True,
    )
    db_session.commit()
    assert forced.result_count == 2
    versions = {
        direction: [
            row.result_version
            for row in db_session.scalars(
                select(SettlementFeeResult)
                .where(
                    SettlementFeeResult.coupon_id == coupon.coupon_id,
                    SettlementFeeResult.fee_direction == direction,
                )
                .order_by(SettlementFeeResult.result_version)
            )
        ]
        for direction in (1, 2)
    }
    assert versions == {1: [1, 2], 2: [1, 2]}


def test_local_affected_month_and_detail_lock_use_shanghai_business_month(
    db_session,
) -> None:
    coupon = _seed_local_coupon(db_session)
    boundary = datetime(2026, 8, 31, 16, 30, tzinfo=timezone.utc)
    order = db_session.get(RawDouyinOrder, coupon.raw_order_id)
    verify = db_session.scalar(
        select(RawDouyinVerifyRecord).where(
            RawDouyinVerifyRecord.coupon_id == coupon.coupon_id
        )
    )
    assert order is not None and verify is not None
    order.pay_time = boundary
    order.sale_time = boundary
    order.create_order_time = boundary
    verify.verify_time = boundary
    db_session.add(
        SettlementScopeRule(
            scope_rule_version="scope-september",
            idempotency_key_hash="scope-september-idempotency",
            request_payload_sha256="c" * 64,
            effective_month="2026-09",
            owner_account_id="owner-product",
            sale_channel_normalized="live",
            is_active=True,
            created_by="test",
            change_reason="test",
        )
    )
    db_session.flush()

    result = settlement_worker.settle_coupon_local(db_session, coupon, "run-boundary")
    db_session.commit()
    assert result["affected_months"] == ["2026-08", "2026-09"]

    detail = db_session.get(SettlementOrderDetail, coupon.coupon_id)
    assert detail is not None
    statement = settlement_worker.lock_settlement_statement(
        db_session,
        store_id="store-sale",
        statement_month="2026-09",
        lock_run_id="lock-boundary",
    )
    db_session.commit()
    # SQLite drops timezone metadata on DateTime columns; restore the source
    # UTC value on the in-memory detail so the local helper exercises the
    # Asia/Shanghai boundary conversion directly.
    detail.sale_time = boundary
    detail.verify_time = boundary
    detail.sale_store_id = "store-sale"
    detail.verify_store_id = "store-verify"
    detail_only_state = {
        "detail": detail,
        "current": [],
        "results": [],
        "adjustments": [],
    }
    assert statement.statement_status == 4
    assert settlement_worker._local_coupon_settlement_locked(
        db_session, detail_only_state
    ) is True


def _coupon_local_snapshot(session, coupon_id: str) -> dict[str, tuple]:
    detail_rows = list(
        session.scalars(
            select(SettlementOrderDetail).where(
                SettlementOrderDetail.coupon_id == coupon_id
            )
        )
    )
    result_rows = list(
        session.scalars(
            select(SettlementFeeResult)
            .where(SettlementFeeResult.coupon_id == coupon_id)
            .order_by(SettlementFeeResult.fee_direction, SettlementFeeResult.result_version)
        )
    )
    current_rows = list(
        session.scalars(
            select(SettlementFeeResultCurrent)
            .where(SettlementFeeResultCurrent.coupon_id == coupon_id)
            .order_by(SettlementFeeResultCurrent.fee_direction)
        )
    )
    adjustment_rows = list(
        session.scalars(
            select(SettlementFeeAdjustment)
            .where(SettlementFeeAdjustment.coupon_id == coupon_id)
            .order_by(SettlementFeeAdjustment.adjustment_id)
        )
    )
    issue_rows = list(
        session.scalars(
            select(DataQualityIssue)
            .where(DataQualityIssue.coupon_id == coupon_id)
            .order_by(DataQualityIssue.issue_id)
        )
    )
    return {
        "detail": tuple(
            (
                row.coupon_id,
                row.order_id,
                row.paid_amount_cent,
                row.sale_store_id,
                row.verify_store_id,
            )
            for row in detail_rows
        ),
        "results": tuple(
            (
                row.fee_result_id,
                row.fee_direction,
                row.result_version,
                row.input_fingerprint,
                row.source_amount_cent,
                row.fee_amount_cent,
            )
            for row in result_rows
        ),
        "current": tuple(
            (row.fee_direction, row.fee_result_id) for row in current_rows
        ),
        "adjustments": tuple(
            (
                row.adjustment_id,
                row.refund_event_id,
                row.original_fee_result_id,
                row.fee_direction,
                row.adjustment_posting_month,
                row.adjustment_fee_cent,
            )
            for row in adjustment_rows
        ),
        "issues": tuple(
            (row.issue_id, row.issue_type, row.source_run_id, row.raw_context_json)
            for row in issue_rows
        ),
    }


def test_local_kernel_isolates_coupon_a_from_coupon_b(db_session) -> None:
    coupon_a = _seed_local_coupon(db_session, "coupon-a")
    coupon_b = _seed_local_coupon(db_session, "coupon-b", seed_dimensions=False)
    settlement_worker.settle_coupon_local(db_session, coupon_b, "run-b")
    db_session.commit()
    before_b = _coupon_local_snapshot(db_session, coupon_b.coupon_id)

    settlement_worker.settle_coupon_local(db_session, coupon_a, "run-a")
    db_session.commit()

    assert _coupon_local_snapshot(db_session, coupon_b.coupon_id) == before_b


def test_invalid_unlocked_coupon_removes_only_local_current_and_is_idempotent(
    db_session,
) -> None:
    coupon_a = _seed_local_coupon(db_session, "coupon-a")
    coupon_b = _seed_local_coupon(db_session, "coupon-b", seed_dimensions=False)
    settlement_worker.settle_coupon_local(db_session, coupon_a, "run-a")
    settlement_worker.settle_coupon_local(db_session, coupon_b, "run-b")
    db_session.commit()
    before_b = _coupon_local_snapshot(db_session, coupon_b.coupon_id)
    a_before = _coupon_local_snapshot(db_session, coupon_a.coupon_id)

    coupon_a.coupon_status_normalized = "closed"
    db_session.flush()
    first = settlement_worker.settle_coupon_local(db_session, coupon_a, "run-invalid-a")
    db_session.commit()

    after_a = _coupon_local_snapshot(db_session, coupon_a.coupon_id)
    assert after_a["detail"] == ()
    assert after_a["current"] == ()
    assert after_a["results"] == a_before["results"]
    incremental_issues = tuple(
        row for row in after_a["issues"] if row[1] == "incremental_invalid_coupon"
    )
    assert len(incremental_issues) == 1
    assert first["invalid"] is True
    assert _coupon_local_snapshot(db_session, coupon_b.coupon_id) == before_b

    settlement_worker.settle_coupon_local(db_session, coupon_a, "run-invalid-b")
    db_session.commit()
    assert len(
        [
            row
            for row in _coupon_local_snapshot(db_session, coupon_a.coupon_id)["issues"]
            if row[1] == "incremental_invalid_coupon"
        ]
    ) == 1


def test_invalid_unlocked_revalidation_supersedes_old_active_history(
    db_session,
) -> None:
    coupon = _seed_local_coupon(db_session)
    settlement_worker.settle_coupon_local(db_session, coupon, "run-initial")
    db_session.commit()

    coupon.coupon_status_normalized = "closed"
    db_session.flush()
    settlement_worker.settle_coupon_local(db_session, coupon, "run-invalid")
    db_session.commit()
    assert not list(
        db_session.scalars(
            select(SettlementFeeResultCurrent).where(
                SettlementFeeResultCurrent.coupon_id == coupon.coupon_id
            )
        )
    )

    coupon.coupon_status_normalized = "fulfilled"
    db_session.flush()
    settlement_worker.settle_coupon_local(db_session, coupon, "run-revalid")
    db_session.commit()

    for direction in (1, 2):
        results = list(
            db_session.scalars(
                select(SettlementFeeResult)
                .where(
                    SettlementFeeResult.coupon_id == coupon.coupon_id,
                    SettlementFeeResult.fee_direction == direction,
                )
                .order_by(SettlementFeeResult.result_version)
            )
        )
        assert [result.result_version for result in results] == [1, 2]
        assert [result.result_status for result in results] == [2, 1]
        current = db_session.scalar(
            select(SettlementFeeResultCurrent).where(
                SettlementFeeResultCurrent.coupon_id == coupon.coupon_id,
                SettlementFeeResultCurrent.fee_direction == direction,
            )
        )
        assert current is not None
        assert current.fee_result_id == results[-1].fee_result_id


def test_invalid_locked_coupon_preserves_statement_and_current_head(db_session) -> None:
    coupon = _seed_local_coupon(db_session)
    settlement_worker.settle_coupon_local(db_session, coupon, "run-a")
    db_session.commit()
    statement = settlement_worker.lock_settlement_statement(
        db_session,
        store_id="store-sale",
        statement_month="2026-08",
        lock_run_id="lock-a",
    )
    db_session.commit()

    before_local = _coupon_local_snapshot(db_session, coupon.coupon_id)
    before_statement = (
        statement.statement_id,
        statement.statement_status,
        statement.promotion_original_fee_cent,
        statement.promotion_adjustment_fee_cent,
        statement.promotion_net_fee_cent,
        statement.locked_by,
        statement.locked_at,
        statement.lock_version,
    )
    before_lines = tuple(
        (
            row.statement_line_id,
            row.statement_id,
            row.fee_direction,
            row.net_base_cent,
            row.net_fee_cent,
        )
        for row in db_session.scalars(
            select(SettlementStatementLine)
            .where(SettlementStatementLine.statement_id == statement.statement_id)
            .order_by(SettlementStatementLine.statement_line_id)
        )
    )
    before_entries = tuple(
        (
            row.statement_entry_id,
            row.source_type,
            row.source_record_id,
            row.fee_direction,
            row.base_amount_cent,
            row.fee_amount_cent,
        )
        for row in db_session.scalars(
            select(SettlementStatementEntry)
            .where(SettlementStatementEntry.statement_id == statement.statement_id)
            .order_by(SettlementStatementEntry.statement_entry_id)
        )
    )

    coupon.coupon_status_normalized = "closed"
    db_session.flush()
    result = settlement_worker.settle_coupon_local(db_session, coupon, "run-invalid-a")
    db_session.commit()
    after_statement = db_session.get(SettlementStatement, statement.id)
    assert after_statement is not None
    assert (
        after_statement.statement_id,
        after_statement.statement_status,
        after_statement.promotion_original_fee_cent,
        after_statement.promotion_adjustment_fee_cent,
        after_statement.promotion_net_fee_cent,
        after_statement.locked_by,
        after_statement.locked_at,
        after_statement.lock_version,
    ) == before_statement
    assert tuple(
        (
            row.statement_line_id,
            row.statement_id,
            row.fee_direction,
            row.net_base_cent,
            row.net_fee_cent,
        )
        for row in db_session.scalars(
            select(SettlementStatementLine)
            .where(SettlementStatementLine.statement_id == statement.statement_id)
            .order_by(SettlementStatementLine.statement_line_id)
        )
    ) == before_lines
    assert tuple(
        (
            row.statement_entry_id,
            row.source_type,
            row.source_record_id,
            row.fee_direction,
            row.base_amount_cent,
            row.fee_amount_cent,
        )
        for row in db_session.scalars(
            select(SettlementStatementEntry)
            .where(SettlementStatementEntry.statement_id == statement.statement_id)
            .order_by(SettlementStatementEntry.statement_entry_id)
        )
    ) == before_entries
    after_local = _coupon_local_snapshot(db_session, coupon.coupon_id)
    assert after_local["detail"] == ()
    assert after_local["current"] == before_local["current"]
    assert after_local["results"] == before_local["results"]
    assert len(
        [row for row in after_local["issues"] if row[1] == "incremental_invalid_coupon"]
    ) == 1
    assert result["locked"] is True

    settlement_worker.settle_coupon_local(db_session, coupon, "run-invalid-b")
    db_session.commit()
    assert len(
        [
            row
            for row in _coupon_local_snapshot(db_session, coupon.coupon_id)["issues"]
            if row[1] == "incremental_invalid_coupon"
        ]
    ) == 1


def test_cross_month_refund_and_cancellation_adjustments_are_append_only(db_session) -> None:
    coupon = _seed_local_coupon(db_session)
    settlement_worker.settle_coupon_local(db_session, coupon, "run-a")
    db_session.commit()
    original = db_session.scalar(
        select(SettlementFeeResult)
        .where(
            SettlementFeeResult.coupon_id == coupon.coupon_id,
            SettlementFeeResult.fee_direction == 1,
        )
    )
    assert original is not None
    observed_after_result = original.calculated_at + timedelta(seconds=1)
    db_session.add(
        DouyinRefundEvent(
            refund_event_id="refund-september",
            order_id=coupon.order_id,
            coupon_id=coupon.coupon_id,
            refund_type=1,
            refund_status=2,
            refund_amount_cent=4000,
            occurred_at=datetime(2026, 9, 3, 2, tzinfo=timezone.utc),
            successful_observed_at=observed_after_result,
            source_run_id="refund-source",
        )
    )
    db_session.flush()
    first_refund = settlement_worker.settle_coupon_local(db_session, coupon, "run-refund")
    db_session.commit()
    assert first_refund["adjustment_count"] == 2
    assert {"2026-08", "2026-09"}.issubset(first_refund["affected_months"])
    assert {"store-sale", "store-verify"}.issubset(first_refund["affected_store_ids"])
    adjustments_after_refund = _coupon_local_snapshot(db_session, coupon.coupon_id)[
        "adjustments"
    ]
    assert len(adjustments_after_refund) == 2

    repeat_refund = settlement_worker.settle_coupon_local(
        db_session, coupon, "run-refund"
    )
    db_session.commit()
    assert repeat_refund["adjustment_count"] == 0
    assert _coupon_local_snapshot(db_session, coupon.coupon_id)["adjustments"] == (
        adjustments_after_refund
    )

    verify = db_session.scalar(
        select(RawDouyinVerifyRecord).where(
            RawDouyinVerifyRecord.coupon_id == coupon.coupon_id
        )
    )
    assert verify is not None
    verify.cancel_time = datetime(2026, 9, 10, 2, tzinfo=timezone.utc)
    db_session.flush()
    first_cancellation = settlement_worker.settle_coupon_local(
        db_session, coupon, "run-cancellation"
    )
    db_session.commit()
    assert first_cancellation["adjustment_count"] == 1
    all_adjustments = _coupon_local_snapshot(db_session, coupon.coupon_id)["adjustments"]
    assert len(all_adjustments) == 3
    assert all(
        month in first_cancellation["affected_months"]
        for month in ("2026-08", "2026-09")
    )

    settlement_worker.settle_coupon_local(db_session, coupon, "run-cancellation")
    db_session.commit()
    assert _coupon_local_snapshot(db_session, coupon.coupon_id)["adjustments"] == (
        all_adjustments
    )


def test_management_refund_after_cancellation_does_not_make_net_negative(
    db_session,
) -> None:
    coupon = _seed_local_coupon(db_session)
    settlement_worker.settle_coupon_local(db_session, coupon, "run-initial")
    db_session.commit()
    management = db_session.scalar(
        select(SettlementFeeResult).where(
            SettlementFeeResult.coupon_id == coupon.coupon_id,
            SettlementFeeResult.fee_direction == 2,
        )
    )
    assert management is not None
    verify = db_session.scalar(
        select(RawDouyinVerifyRecord).where(
            RawDouyinVerifyRecord.coupon_id == coupon.coupon_id
        )
    )
    assert verify is not None
    verify.cancel_time = datetime(2026, 9, 1, 2, tzinfo=timezone.utc)
    db_session.flush()
    settlement_worker.settle_coupon_local(db_session, coupon, "run-cancel")
    db_session.commit()
    cancellation = db_session.scalar(
        select(SettlementFeeAdjustment).where(
            SettlementFeeAdjustment.coupon_id == coupon.coupon_id,
            SettlementFeeAdjustment.fee_direction == 2,
            SettlementFeeAdjustment.adjustment_type == 3,
        )
    )
    assert cancellation is not None
    assert cancellation.adjustment_fee_cent == -management.fee_amount_cent

    db_session.add(
        DouyinRefundEvent(
            refund_event_id="refund-after-cancellation",
            order_id=coupon.order_id,
            coupon_id=coupon.coupon_id,
            refund_type=1,
            refund_status=2,
            refund_amount_cent=4000,
            occurred_at=datetime(2026, 9, 3, 2, tzinfo=timezone.utc),
            successful_observed_at=management.calculated_at + timedelta(seconds=1),
            source_run_id="refund-after-cancel-source",
        )
    )
    db_session.flush()
    settlement_worker.settle_coupon_local(db_session, coupon, "run-refund")
    db_session.commit()
    management_adjustments = list(
        db_session.scalars(
            select(SettlementFeeAdjustment).where(
                SettlementFeeAdjustment.original_fee_result_id
                == management.fee_result_id,
                SettlementFeeAdjustment.fee_direction == 2,
            )
        )
    )
    promotion_adjustments = list(
        db_session.scalars(
            select(SettlementFeeAdjustment).where(
                SettlementFeeAdjustment.coupon_id == coupon.coupon_id,
                SettlementFeeAdjustment.fee_direction == 1,
            )
        )
    )
    assert management.fee_amount_cent + sum(
        row.adjustment_fee_cent for row in management_adjustments
    ) == 0
    assert management.fee_amount_cent + sum(
        row.adjustment_fee_cent for row in management_adjustments
    ) >= 0
    assert any(row.refund_event_id == "refund-after-cancellation" for row in promotion_adjustments)


def test_force_same_run_retry_fences_result_and_still_scans_adjustments(
    db_session,
) -> None:
    coupon = _seed_local_coupon(db_session)
    settlement_worker.rebuild_dual_fee_results(
        db_session, calculation_run_id="run-initial"
    )
    db_session.commit()
    settlement_worker.rebuild_dual_fee_results(
        db_session,
        calculation_run_id="run-force",
        force_recalculate=True,
    )
    db_session.commit()
    forced_management = db_session.scalar(
        select(SettlementFeeResult).where(
            SettlementFeeResult.coupon_id == coupon.coupon_id,
            SettlementFeeResult.fee_direction == 2,
            SettlementFeeResult.result_version == 2,
        )
    )
    assert forced_management is not None
    db_session.add(
        DouyinRefundEvent(
            refund_event_id="refund-on-force-retry",
            order_id=coupon.order_id,
            coupon_id=coupon.coupon_id,
            refund_type=1,
            refund_status=2,
            refund_amount_cent=4000,
            occurred_at=datetime(2026, 9, 3, 2, tzinfo=timezone.utc),
            successful_observed_at=forced_management.calculated_at
            + timedelta(seconds=1),
            source_run_id="refund-force-retry-source",
        )
    )
    db_session.flush()
    retry = settlement_worker.rebuild_dual_fee_results(
        db_session,
        calculation_run_id="run-force",
        force_recalculate=True,
    )
    db_session.commit()
    assert retry.result_count == 0
    assert retry.adjustment_count == 2
    assert {
        direction: [
            row.result_version
            for row in db_session.scalars(
                select(SettlementFeeResult)
                .where(
                    SettlementFeeResult.coupon_id == coupon.coupon_id,
                    SettlementFeeResult.fee_direction == direction,
                )
                .order_by(SettlementFeeResult.result_version)
            )
        ]
        for direction in (1, 2)
    } == {1: [1, 2], 2: [1, 2]}
    assert db_session.scalar(
        select(SettlementFeeResultCurrent.fee_result_id).where(
            SettlementFeeResultCurrent.coupon_id == coupon.coupon_id,
            SettlementFeeResultCurrent.fee_direction == 2,
        )
    ) == forced_management.fee_result_id


def test_settle_impacted_coupons_direct_coupon_uses_incremental_closure(db_session) -> None:
    coupon = _seed_local_coupon(db_session)
    db_session.add(
        JobImpact(
            impact_key="settlement-direct-coupon",
            entity_type="coupon",
            entity_key=coupon.coupon_id,
            old_values_json={},
            new_values_json={"coupon_id": coupon.coupon_id},
            affected_closure_json={
                "coupon_ids": [coupon.coupon_id],
                "order_ids": [coupon.order_id],
                "affected_months": ["2026-08"],
                "store_ids": ["store-sale", "store-verify"],
            },
            source_run_id="settlement-source-direct",
        )
    )
    db_session.commit()

    factory = sessionmaker(
        bind=db_session.get_bind(), autoflush=False, autocommit=False, future=True
    )
    result = settlement_worker.settle_impacted_coupons(
        factory,
        "settlement-source-direct",
        lambda session: True,
        impact_batch_size=1,
        coupon_batch_size=1,
    )

    assert result["impact_count"] == 1
    assert result["coupon_count"] == 1
    assert result["detail_count"] == 1
    assert result["result_count"] == 2
    assert result["adjustment_count"] == 0
    assert result["last_impact_id"] == 1
    assert result["affected_months"] == ["2026-08"]
    assert result["affected_store_ids"] == ["store-sale", "store-verify"]
    assert result["completed"] is True


def test_settle_impacted_coupons_no_impact_is_deterministic_and_fenced(db_session) -> None:
    factory = sessionmaker(
        bind=db_session.get_bind(), autoflush=False, autocommit=False, future=True
    )
    fence_sessions = []

    def fence(session):
        fence_sessions.append(session)
        return True

    first = settlement_worker.settle_impacted_coupons(
        factory, "no-impact-run", fence, impact_batch_size=2, coupon_batch_size=2
    )
    second = settlement_worker.settle_impacted_coupons(
        factory, "no-impact-run", fence, impact_batch_size=2, coupon_batch_size=2
    )

    assert first == second == {
        "impact_count": 0,
        "coupon_count": 0,
        "detail_count": 0,
        "result_count": 0,
        "adjustment_count": 0,
        "last_impact_id": 0,
        "affected_months": [],
        "affected_store_ids": [],
        "completed": True,
    }
    assert len(fence_sessions) == 2
    assert all(not session.in_transaction() for session in fence_sessions)


def test_settle_impacted_coupons_short_session_lifecycle_is_bounded(db_session) -> None:
    coupon = _seed_local_coupon(db_session, "coupon-session-lifecycle")
    db_session.add(
        JobImpact(
            impact_key="settlement-session-lifecycle",
            entity_type="coupon",
            entity_key=coupon.coupon_id,
            affected_closure_json={"coupon_ids": [coupon.coupon_id]},
            source_run_id="settlement-source-session-lifecycle",
        )
    )
    db_session.commit()
    base_factory = sessionmaker(bind=db_session.get_bind(), future=True)
    sessions = []

    class CountingSession:
        def __init__(self, wrapped):
            self.wrapped = wrapped
            self.commit_count = 0
            self.rollback_count = 0
            self.close_count = 0

        def __getattr__(self, name):
            return getattr(self.wrapped, name)

        def begin(self, *args, **kwargs):
            return self.wrapped.begin(*args, **kwargs)

        def commit(self):
            self.commit_count += 1
            return self.wrapped.commit()

        def rollback(self):
            self.rollback_count += 1
            return self.wrapped.rollback()

        def close(self):
            self.close_count += 1
            return self.wrapped.close()

    def counting_factory():
        session = CountingSession(base_factory())
        sessions.append(session)
        return session

    result = settlement_worker.settle_impacted_coupons(
        counting_factory,
        "settlement-source-session-lifecycle",
        lambda session: True,
        impact_batch_size=1,
        coupon_batch_size=1,
    )

    assert result["completed"] is True
    assert sessions
    assert all(session.close_count == 1 for session in sessions)
    assert any(session.commit_count == 1 for session in sessions)
    assert any(session.rollback_count >= 1 for session in sessions)


def test_settle_impacted_coupons_rejects_oversized_closure_before_coupon_query(
    db_session, monkeypatch
) -> None:
    db_session.add(
        JobImpact(
            impact_key="settlement-oversized-closure",
            entity_type="coupon",
            entity_key="coupon-oversized",
            affected_closure_json={
                "coupon_ids": [f"closure-value-{index}" for index in range(100_000)]
            },
            source_run_id="settlement-source-oversized",
        )
    )
    db_session.commit()
    base_factory = sessionmaker(bind=db_session.get_bind(), future=True)
    sessions = []

    class CountingSession:
        def __init__(self, wrapped):
            self.wrapped = wrapped
            self.rollback_count = 0
            self.close_count = 0

        def __getattr__(self, name):
            return getattr(self.wrapped, name)

        def begin(self, *args, **kwargs):
            return self.wrapped.begin(*args, **kwargs)

        def rollback(self):
            self.rollback_count += 1
            return self.wrapped.rollback()

        def close(self):
            self.close_count += 1
            return self.wrapped.close()

    def counting_factory():
        session = CountingSession(base_factory())
        sessions.append(session)
        return session

    def unexpected_coupon_query(*_args, **_kwargs):
        raise AssertionError("oversized closure must fail before coupon query")

    monkeypatch.setattr(
        settlement_worker, "_read_settlement_coupon_page", unexpected_coupon_query
    )
    with pytest.raises(ValueError, match="maximum cardinality") as error:
        settlement_worker.settle_impacted_coupons(
            counting_factory,
            "settlement-source-oversized",
            lambda session: True,
            impact_batch_size=1,
            coupon_batch_size=1,
        )

    assert "closure-value-99999" not in str(error.value)
    assert sessions and all(session.close_count == 1 for session in sessions)
    assert all(session.rollback_count >= 1 for session in sessions)


def test_settlement_closure_sequence_bound_covers_list_tuple_and_set() -> None:
    values = [f"sequence-value-{index}" for index in range(65)]
    for sequence in (values, tuple(values), set(values)):
        with pytest.raises(ValueError, match="maximum cardinality") as error:
            settlement_worker._settlement_coupon_selectors(
                {
                    "entity_type": "coupon",
                    "entity_key": "coupon-sequence-bound",
                    "old_values_json": {},
                    "new_values_json": {},
                    "affected_closure_json": {"coupon_ids": sequence},
                }
            )
        assert "sequence-value-0" not in str(error.value)


def test_settlement_two_times_safe_closure_limit_fails_before_coupon_query(
    db_session, monkeypatch
) -> None:
    db_session.add(
        JobImpact(
            impact_key="settlement-two-times-safe-limit",
            entity_type="coupon",
            entity_key="coupon-two-times-safe-limit",
            affected_closure_json={
                "coupon_ids": [
                    f"safe-limit-value-{index}" for index in range(129)
                ]
            },
            source_run_id="settlement-source-two-times-safe-limit",
        )
    )
    db_session.commit()
    factory = sessionmaker(bind=db_session.get_bind(), future=True)

    def unexpected_coupon_query(*_args, **_kwargs):
        raise AssertionError("oversized closure must fail before coupon query")

    monkeypatch.setattr(
        settlement_worker, "_read_settlement_coupon_page", unexpected_coupon_query
    )
    with pytest.raises(ValueError, match="maximum cardinality") as error:
        settlement_worker.settle_impacted_coupons(
            factory,
            "settlement-source-two-times-safe-limit",
            lambda session: True,
            impact_batch_size=1,
            coupon_batch_size=1,
        )
    assert "safe-limit-value-0" not in str(error.value)


def test_settlement_page_aggregate_bound_covers_nested_impacts_before_query(
    db_session, monkeypatch
) -> None:
    impacts = []
    for impact_index in range(43):
        base = impact_index * 64
        direct = [f"aggregate-coupon-{base + offset}" for offset in range(64)]
        old_direct = [
            f"aggregate-old-coupon-{base + offset}" for offset in range(64)
        ]
        new_direct = [
            f"aggregate-new-coupon-{base + offset}" for offset in range(64)
        ]
        old_months = [
            f"2026-{((base + offset) % 12) + 1:02d}"
            for offset in range(64)
        ]
        new_months = [
            f"2027-{((base + offset) % 12) + 1:02d}"
            for offset in range(64)
        ]
        old_stores = [f"aggregate-old-store-{base + offset}" for offset in range(64)]
        new_stores = [f"aggregate-new-store-{base + offset}" for offset in range(64)]
        impacts.append(
            JobImpact(
                impact_key=f"settlement-page-aggregate-{impact_index}",
                entity_type="coupon",
                entity_key=direct[0],
                old_values_json={},
                new_values_json={},
                affected_closure_json={
                    "coupon_ids": direct,
                    "old_values": {
                        "coupon_ids": old_direct,
                        "affected_months": old_months,
                        "store_ids": old_stores,
                    },
                    "new_values": {
                        "coupon_ids": new_direct,
                        "affected_months": new_months,
                        "store_ids": new_stores,
                    },
                },
                source_run_id="settlement-source-page-aggregate",
            )
        )
    db_session.add_all(impacts)
    db_session.commit()
    base_factory = sessionmaker(bind=db_session.get_bind(), future=True)
    sessions = []

    class CountingSession:
        def __init__(self, wrapped):
            self.wrapped = wrapped
            self.rollback_count = 0
            self.close_count = 0

        def __getattr__(self, name):
            return getattr(self.wrapped, name)

        def begin(self, *args, **kwargs):
            return self.wrapped.begin(*args, **kwargs)

        def rollback(self):
            self.rollback_count += 1
            return self.wrapped.rollback()

        def close(self):
            self.close_count += 1
            return self.wrapped.close()

    def counting_factory():
        session = CountingSession(base_factory())
        sessions.append(session)
        return session

    def unexpected_coupon_query(*_args, **_kwargs):
        raise AssertionError("aggregate page must fail before coupon query")

    monkeypatch.setattr(
        settlement_worker, "_read_settlement_coupon_page", unexpected_coupon_query
    )
    with pytest.raises(ValueError, match="maximum cardinality") as error:
        settlement_worker.settle_impacted_coupons(
            counting_factory,
            "settlement-source-page-aggregate",
            lambda session: True,
            impact_batch_size=64,
            coupon_batch_size=100,
        )
    assert "aggregate-coupon-0" not in str(error.value)
    assert sessions and all(session.close_count == 1 for session in sessions)
    assert all(session.rollback_count >= 1 for session in sessions)


def test_settlement_page_aggregate_bound_covers_prefixed_selector_fields(
    db_session, monkeypatch
) -> None:
    impacts = []
    for impact_index in range(64):
        base = impact_index * 64
        impacts.append(
            JobImpact(
                impact_key=f"settlement-page-prefixed-{impact_index}",
                entity_type="coupon",
                entity_key=f"aggregate-prefixed-entity-{impact_index}",
                old_values_json={},
                new_values_json={},
                affected_closure_json={
                    "old_coupon_ids": [
                        f"aggregate-prefixed-old-{base + offset}"
                        for offset in range(64)
                    ],
                    "new_coupon_ids": [
                        f"aggregate-prefixed-new-{base + offset}"
                        for offset in range(64)
                    ],
                },
                source_run_id="settlement-source-page-prefixed",
            )
        )
    db_session.add_all(impacts)
    db_session.commit()
    factory = sessionmaker(bind=db_session.get_bind(), future=True)

    def unexpected_coupon_query(*_args, **_kwargs):
        raise AssertionError("prefixed aggregate must fail before coupon query")

    monkeypatch.setattr(
        settlement_worker, "_read_settlement_coupon_page", unexpected_coupon_query
    )
    with pytest.raises(ValueError, match="maximum cardinality") as error:
        settlement_worker.settle_impacted_coupons(
            factory,
            "settlement-source-page-prefixed",
            lambda session: True,
            impact_batch_size=64,
            coupon_batch_size=100,
        )
    assert "aggregate-prefixed-old-0" not in str(error.value)


def test_settlement_caller_batch_sizes_clamp_and_keyset_cursor_processes_all_impacts(
    db_session, monkeypatch
) -> None:
    coupon = _seed_local_coupon(db_session, "coupon-batch-clamp")
    impacts = [
        JobImpact(
            impact_key="settlement-batch-clamp-direct",
            entity_type="coupon",
            entity_key=coupon.coupon_id,
            affected_closure_json={"coupon_ids": [coupon.coupon_id]},
            source_run_id="settlement-source-batch-clamp",
        )
    ]
    impacts.extend(
        JobImpact(
            impact_key=f"settlement-batch-clamp-unknown-{index}",
            entity_type="unrelated_entity",
            entity_key=f"unknown-{index}",
            affected_closure_json={},
            source_run_id="settlement-source-batch-clamp",
        )
        for index in range(130)
    )
    db_session.add_all(impacts)
    db_session.commit()
    factory = sessionmaker(bind=db_session.get_bind(), future=True)
    impact_limits = []
    coupon_limits = []
    original_impact_page = settlement_worker._read_settlement_impact_page
    original_coupon_page = settlement_worker._read_settlement_coupon_page

    def impact_page_spy(session_factory, *, source_run_id, after_impact_id, limit):
        impact_limits.append(limit)
        return original_impact_page(
            session_factory,
            source_run_id=source_run_id,
            after_impact_id=after_impact_id,
            limit=limit,
        )

    def coupon_page_spy(session_factory, selectors, *, after_coupon_id, limit):
        coupon_limits.append(limit)
        return original_coupon_page(
            session_factory,
            selectors,
            after_coupon_id=after_coupon_id,
            limit=limit,
        )

    monkeypatch.setattr(settlement_worker, "_read_settlement_impact_page", impact_page_spy)
    monkeypatch.setattr(settlement_worker, "_read_settlement_coupon_page", coupon_page_spy)
    result = settlement_worker.settle_impacted_coupons(
        factory,
        "settlement-source-batch-clamp",
        lambda session: True,
        impact_batch_size=10**9,
        coupon_batch_size=10**9,
    )

    assert result["completed"] is True
    assert result["impact_count"] == 131
    assert result["coupon_count"] == 1
    assert impact_limits and max(impact_limits) <= 64
    assert coupon_limits and max(coupon_limits) <= 100


def test_settle_impacted_coupons_keyset_page_limits_are_strict(db_session, monkeypatch) -> None:
    coupons = [
        _seed_local_coupon(db_session, f"coupon-keyset-{index}", seed_dimensions=index == 0)
        for index in range(3)
    ]
    for index, coupon in enumerate(coupons):
        db_session.add(
            JobImpact(
                impact_key=f"settlement-keyset-{index}",
                entity_type="coupon",
                entity_key=coupon.coupon_id,
                affected_closure_json={"coupon_ids": [coupon.coupon_id]},
                source_run_id="settlement-source-keyset",
            )
        )
    db_session.commit()
    factory = sessionmaker(bind=db_session.get_bind(), future=True)
    impact_limits = []
    coupon_limits = []
    original_impact_page = settlement_worker._read_settlement_impact_page
    original_coupon_page = settlement_worker._read_settlement_coupon_page

    def impact_page_spy(session_factory, *, source_run_id, after_impact_id, limit):
        impact_limits.append(limit)
        return original_impact_page(
            session_factory,
            source_run_id=source_run_id,
            after_impact_id=after_impact_id,
            limit=limit,
        )

    def coupon_page_spy(session_factory, selectors, *, after_coupon_id, limit):
        coupon_limits.append(limit)
        return original_coupon_page(
            session_factory,
            selectors,
            after_coupon_id=after_coupon_id,
            limit=limit,
        )

    monkeypatch.setattr(settlement_worker, "_read_settlement_impact_page", impact_page_spy)
    monkeypatch.setattr(settlement_worker, "_read_settlement_coupon_page", coupon_page_spy)
    result = settlement_worker.settle_impacted_coupons(
        factory,
        "settlement-source-keyset",
        lambda session: True,
        impact_batch_size=2,
        coupon_batch_size=1,
    )

    assert result["completed"] is True
    assert result["coupon_count"] == 3
    assert impact_limits and max(impact_limits) <= 2
    assert coupon_limits and max(coupon_limits) <= 1


def test_settle_impacted_coupons_large_unrelated_history_stays_page_bounded(
    db_session, monkeypatch
) -> None:
    coupon = _seed_local_coupon(db_session, "coupon-after-history")
    db_session.add_all(
        [
            JobImpact(
                impact_key=f"settlement-history-{index}",
                entity_type="unrelated_entity",
                entity_key=f"history-{index}",
                affected_closure_json={},
                source_run_id="settlement-source-history",
            )
            for index in range(300)
        ]
    )
    db_session.add(
        JobImpact(
            impact_key="settlement-history-relevant",
            entity_type="coupon",
            entity_key=coupon.coupon_id,
            affected_closure_json={"coupon_ids": [coupon.coupon_id]},
            source_run_id="settlement-source-history",
        )
    )
    db_session.commit()
    factory = sessionmaker(bind=db_session.get_bind(), future=True)
    impact_page_lengths = []
    original_impact_page = settlement_worker._read_settlement_impact_page

    def impact_page_spy(session_factory, *, source_run_id, after_impact_id, limit):
        page = original_impact_page(
            session_factory,
            source_run_id=source_run_id,
            after_impact_id=after_impact_id,
            limit=limit,
        )
        impact_page_lengths.append(len(page))
        assert len(page) <= 16
        return page

    monkeypatch.setattr(settlement_worker, "_read_settlement_impact_page", impact_page_spy)
    result = settlement_worker.settle_impacted_coupons(
        factory,
        "settlement-source-history",
        lambda session: True,
        impact_batch_size=16,
        coupon_batch_size=1,
    )

    assert result["completed"] is True
    assert result["impact_count"] == 301
    assert result["coupon_count"] == 1
    assert max(impact_page_lengths) <= 16


def test_settle_impacted_coupons_order_closure_reaches_all_coupons(db_session) -> None:
    first = _seed_local_coupon(db_session, "coupon-order-a")
    unrelated = _seed_local_coupon(
        db_session, "coupon-order-unrelated", seed_dimensions=False
    )
    second = RawDouyinOrderCoupon(
        coupon_id="coupon-order-b",
        order_id=first.order_id,
        raw_order_id=first.raw_order_id,
        coupon_status="fulfilled",
        coupon_status_normalized="fulfilled",
        coupon_paid_amount_cent=10000,
    )
    db_session.add(second)
    db_session.add(
        RawDouyinVerifyRecord(
            verify_id="verify-coupon-order-b",
            coupon_id=second.coupon_id,
            verify_status="valid",
            verify_time=datetime(2026, 8, 7, 10, tzinfo=timezone.utc),
            poi_id="poi-verify",
            sku_id="sku-service",
            paid_amount_cent=10000,
        )
    )
    db_session.add(
        JobImpact(
            impact_key="settlement-order-all-coupons",
            entity_type="order",
            entity_key=first.order_id,
            old_values_json={"order_id": first.order_id},
            new_values_json={"order_id": first.order_id},
            affected_closure_json={
                "order_ids": [first.order_id],
                "poi_ids": ["poi-verify"],
                "store_ids": ["store-verify"],
            },
            source_run_id="settlement-source-order",
        )
    )
    db_session.commit()
    factory = sessionmaker(bind=db_session.get_bind(), future=True)

    result = settlement_worker.settle_impacted_coupons(
        factory,
        "settlement-source-order",
        lambda session: True,
        impact_batch_size=1,
        coupon_batch_size=1,
    )

    assert result["coupon_count"] == 2
    assert db_session.scalar(
        select(SettlementOrderDetail.coupon_id).where(
            SettlementOrderDetail.coupon_id == unrelated.coupon_id
        )
    ) is None
    assert db_session.scalar(
        select(SettlementOrderDetail.coupon_id).where(
            SettlementOrderDetail.coupon_id == first.coupon_id
        )
    ) == first.coupon_id
    assert db_session.scalar(
        select(SettlementOrderDetail.coupon_id).where(
            SettlementOrderDetail.coupon_id == second.coupon_id
        )
    ) == second.coupon_id


def test_settle_impacted_coupons_direct_coupon_does_not_fan_out_order_siblings(
    db_session,
) -> None:
    first = _seed_local_coupon(db_session, "coupon-direct-only-a")
    second = RawDouyinOrderCoupon(
        coupon_id="coupon-direct-only-b",
        order_id=first.order_id,
        raw_order_id=first.raw_order_id,
        coupon_status="fulfilled",
        coupon_status_normalized="fulfilled",
        coupon_paid_amount_cent=10000,
    )
    db_session.add(second)
    db_session.add(
        RawDouyinVerifyRecord(
            verify_id="verify-coupon-direct-only-b",
            coupon_id=second.coupon_id,
            verify_status="valid",
            verify_time=datetime(2026, 8, 7, 10, tzinfo=timezone.utc),
            poi_id="poi-verify",
            sku_id="sku-service",
            paid_amount_cent=10000,
        )
    )
    db_session.add(
        JobImpact(
            impact_key="settlement-direct-only",
            entity_type="coupon",
            entity_key=first.coupon_id,
            affected_closure_json={
                "coupon_ids": [first.coupon_id],
                "order_ids": [first.order_id],
                "poi_ids": ["poi-verify"],
                "store_ids": ["store-verify"],
            },
            source_run_id="settlement-source-direct-only",
        )
    )
    db_session.commit()
    factory = sessionmaker(bind=db_session.get_bind(), future=True)

    result = settlement_worker.settle_impacted_coupons(
        factory,
        "settlement-source-direct-only",
        lambda session: True,
        impact_batch_size=1,
        coupon_batch_size=1,
    )

    assert result["coupon_count"] == 1
    assert db_session.scalar(
        select(SettlementOrderDetail.coupon_id).where(
            SettlementOrderDetail.coupon_id == first.coupon_id
        )
    ) == first.coupon_id
    assert db_session.scalar(
        select(SettlementOrderDetail.coupon_id).where(
            SettlementOrderDetail.coupon_id == second.coupon_id
        )
    ) is None


def test_settle_impacted_coupons_fence_false_rolls_back_current_batch_only(db_session) -> None:
    coupon = _seed_local_coupon(db_session)
    db_session.add(
        JobImpact(
            impact_key="settlement-fence-false",
            entity_type="coupon",
            entity_key=coupon.coupon_id,
            affected_closure_json={
                "coupon_ids": [coupon.coupon_id],
                "affected_months": ["2026-08", "2026-09"],
                "store_ids": ["store-rolled-back"],
            },
            source_run_id="settlement-source-fence",
        )
    )
    db_session.commit()
    factory = sessionmaker(bind=db_session.get_bind(), future=True)

    blocked = settlement_worker.settle_impacted_coupons(
        factory,
        "settlement-source-fence",
        lambda session: False,
        impact_batch_size=1,
        coupon_batch_size=1,
    )
    assert blocked["completed"] is False
    assert blocked["affected_months"] == []
    assert blocked["affected_store_ids"] == []
    assert db_session.scalar(
        select(SettlementOrderDetail).where(
            SettlementOrderDetail.coupon_id == coupon.coupon_id
        )
    ) is None

    completed = settlement_worker.settle_impacted_coupons(
        factory,
        "settlement-source-fence",
        lambda session: True,
        impact_batch_size=1,
        coupon_batch_size=1,
    )
    assert completed["completed"] is True
    assert db_session.scalar(
        select(SettlementOrderDetail).where(
            SettlementOrderDetail.coupon_id == coupon.coupon_id
        )
    ) is not None


def test_settle_impacted_coupons_fence_false_preserves_prior_committed_batch(db_session) -> None:
    first = _seed_local_coupon(db_session, "coupon-fence-prior-a")
    second = RawDouyinOrderCoupon(
        coupon_id="coupon-fence-prior-b",
        order_id=first.order_id,
        raw_order_id=first.raw_order_id,
        coupon_status="fulfilled",
        coupon_status_normalized="fulfilled",
        coupon_paid_amount_cent=10000,
    )
    db_session.add(second)
    db_session.add(
        RawDouyinVerifyRecord(
            verify_id="verify-coupon-fence-prior-b",
            coupon_id=second.coupon_id,
            verify_status="valid",
            verify_time=datetime(2026, 8, 7, 10, tzinfo=timezone.utc),
            poi_id="poi-verify",
            sku_id="sku-service",
            paid_amount_cent=10000,
        )
    )
    db_session.add(
        JobImpact(
            impact_key="settlement-fence-prior-order",
            entity_type="order",
            entity_key=first.order_id,
            affected_closure_json={
                "order_ids": [first.order_id],
                "affected_months": ["2026-08", "2026-09"],
                "store_ids": ["store-fence"],
            },
            source_run_id="settlement-source-fence-prior",
        )
    )
    db_session.commit()
    factory = sessionmaker(bind=db_session.get_bind(), future=True)
    fence_calls = {"count": 0}

    def fence_after_first_batch(session):
        fence_calls["count"] += 1
        return fence_calls["count"] == 1

    blocked = settlement_worker.settle_impacted_coupons(
        factory,
        "settlement-source-fence-prior",
        fence_after_first_batch,
        impact_batch_size=1,
        coupon_batch_size=1,
    )
    assert blocked["completed"] is False
    assert blocked["affected_months"] == ["2026-08", "2026-09"]
    assert "store-fence" in blocked["affected_store_ids"]
    assert db_session.scalar(
        select(SettlementOrderDetail.coupon_id).where(
            SettlementOrderDetail.coupon_id == first.coupon_id
        )
    ) == first.coupon_id
    assert db_session.scalar(
        select(SettlementOrderDetail.coupon_id).where(
            SettlementOrderDetail.coupon_id == second.coupon_id
        )
    ) is None

    completed = settlement_worker.settle_impacted_coupons(
        factory,
        "settlement-source-fence-prior",
        lambda session: True,
        impact_batch_size=1,
        coupon_batch_size=1,
    )
    assert completed["completed"] is True
    assert db_session.scalar(
        select(SettlementOrderDetail.coupon_id).where(
            SettlementOrderDetail.coupon_id == second.coupon_id
        )
    ) == second.coupon_id


def test_settle_impacted_coupons_order_level_refund_without_coupon_id(db_session) -> None:
    first = _seed_local_coupon(db_session, "coupon-refund-a")
    second = RawDouyinOrderCoupon(
        coupon_id="coupon-refund-b",
        order_id=first.order_id,
        raw_order_id=first.raw_order_id,
        coupon_status="fulfilled",
        coupon_status_normalized="fulfilled",
        coupon_paid_amount_cent=10000,
    )
    db_session.add(second)
    db_session.add(
        RawDouyinVerifyRecord(
            verify_id="verify-coupon-refund-b",
            coupon_id=second.coupon_id,
            verify_status="valid",
            verify_time=datetime(2026, 8, 7, 10, tzinfo=timezone.utc),
            poi_id="poi-verify",
            sku_id="sku-service",
            paid_amount_cent=10000,
        )
    )
    db_session.add(
        DouyinRefundEvent(
            refund_event_id="refund-order-level",
            order_id=first.order_id,
            coupon_id=None,
            refund_type=1,
            refund_status=2,
            refund_amount_cent=1000,
            occurred_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            source_run_id="settlement-source-refund",
        )
    )
    db_session.add(
        JobImpact(
            impact_key="settlement-refund-order-level",
            entity_type="refund",
            entity_key="refund-order-level",
            old_values_json={"order_id": first.order_id, "coupon_id": None},
            new_values_json={"order_id": first.order_id, "coupon_id": None},
            affected_closure_json={
                "order_ids": [first.order_id],
                "refund_months": ["2026-09"],
            },
            source_run_id="settlement-source-refund",
        )
    )
    db_session.commit()
    factory = sessionmaker(bind=db_session.get_bind(), future=True)

    result = settlement_worker.settle_impacted_coupons(
        factory,
        "settlement-source-refund",
        lambda session: True,
        impact_batch_size=1,
        coupon_batch_size=1,
    )

    assert result["coupon_count"] == 2
    assert result["affected_months"] == ["2026-08", "2026-09"]


def test_settle_impacted_coupons_verify_and_mapping_old_new_closure(db_session) -> None:
    coupon = _seed_local_coupon(db_session, "coupon-verify-mapping")
    db_session.add(
        DimStore(store_id="store-old", store_name="Old")
    )
    db_session.add(
        DimStorePoiMapping(
            store_id="store-old",
            poi_id="poi-old",
            poi_name="Old",
        )
    )
    db_session.add(
        JobImpact(
            impact_key="settlement-verify-old-new",
            entity_type="verify",
            entity_key=f"verify-{coupon.coupon_id}",
            old_values_json={
                "coupon_id": coupon.coupon_id,
                "poi_id": "poi-old",
                "verify_time": "2026-07-31T10:00:00+00:00",
            },
            new_values_json={
                "coupon_id": coupon.coupon_id,
                "poi_id": "poi-verify",
                "verify_time": "2026-08-07T10:00:00+00:00",
            },
            affected_closure_json={
                "coupon_ids": [coupon.coupon_id],
                "poi_ids": ["poi-old", "poi-verify"],
                "store_ids": ["store-old", "store-verify"],
                "verify_months": ["2026-07", "2026-08"],
                "affected_months": ["2026-07", "2026-08"],
            },
            source_run_id="settlement-source-verify",
        )
    )
    db_session.add(
        JobImpact(
            impact_key="settlement-mapping-old-new",
            entity_type="store_poi_mapping",
            entity_key="poi-verify",
            old_values_json={"poi_id": "poi-verify", "store_id": "store-old"},
            new_values_json={"poi_id": "poi-verify", "store_id": "store-verify"},
            affected_closure_json={
                "poi_ids": ["poi-verify"],
                "store_ids": ["store-old", "store-verify"],
                "affected_months": ["2026-07", "2026-08"],
            },
            source_run_id="settlement-source-mapping",
        )
    )
    db_session.commit()
    factory = sessionmaker(bind=db_session.get_bind(), future=True)

    verify_result = settlement_worker.settle_impacted_coupons(
        factory,
        "settlement-source-verify",
        lambda session: True,
        impact_batch_size=1,
        coupon_batch_size=1,
    )
    mapping_result = settlement_worker.settle_impacted_coupons(
        factory,
        "settlement-source-mapping",
        lambda session: True,
        impact_batch_size=1,
        coupon_batch_size=1,
    )

    assert verify_result["coupon_count"] == 1
    assert verify_result["affected_months"] == ["2026-07", "2026-08"]
    assert verify_result["affected_store_ids"] == [
        "store-old",
        "store-sale",
        "store-verify",
    ]
    assert mapping_result["coupon_count"] == 1
    assert mapping_result["affected_store_ids"] == [
        "store-old",
        "store-sale",
        "store-verify",
    ]


def test_settle_impacted_coupons_crash_after_first_batch_rescans_idempotently(
    db_session, monkeypatch
) -> None:
    first = _seed_local_coupon(db_session, "coupon-crash-a")
    second = RawDouyinOrderCoupon(
        coupon_id="coupon-crash-b",
        order_id=first.order_id,
        raw_order_id=first.raw_order_id,
        coupon_status="fulfilled",
        coupon_status_normalized="fulfilled",
        coupon_paid_amount_cent=10000,
    )
    db_session.add(second)
    db_session.add(
        RawDouyinVerifyRecord(
            verify_id="verify-coupon-crash-b",
            coupon_id=second.coupon_id,
            verify_status="valid",
            verify_time=datetime(2026, 8, 7, 10, tzinfo=timezone.utc),
            poi_id="poi-verify",
            sku_id="sku-service",
            paid_amount_cent=10000,
        )
    )
    db_session.add(
        JobImpact(
            impact_key="settlement-crash-order",
            entity_type="order",
            entity_key=first.order_id,
            affected_closure_json={"order_ids": [first.order_id]},
            source_run_id="settlement-source-crash",
        )
    )
    db_session.commit()
    factory = sessionmaker(bind=db_session.get_bind(), future=True)
    original = settlement_worker.settle_coupon_local
    calls = {"count": 0}

    def crash_on_second(session, coupon, calculation_run_id):
        calls["count"] += 1
        if calls["count"] == 2:
            raise KeyboardInterrupt("simulated process crash")
        return original(session, coupon, calculation_run_id)

    monkeypatch.setattr(settlement_worker, "settle_coupon_local", crash_on_second)
    with pytest.raises(KeyboardInterrupt):
        settlement_worker.settle_impacted_coupons(
            factory,
            "settlement-source-crash",
            lambda session: True,
            impact_batch_size=1,
            coupon_batch_size=1,
        )

    assert db_session.scalar(
        select(SettlementOrderDetail.coupon_id).where(
            SettlementOrderDetail.coupon_id == first.coupon_id
        )
    ) == first.coupon_id
    assert db_session.scalar(
        select(SettlementOrderDetail.coupon_id).where(
            SettlementOrderDetail.coupon_id == second.coupon_id
        )
    ) is None

    monkeypatch.setattr(settlement_worker, "settle_coupon_local", original)
    result = settlement_worker.settle_impacted_coupons(
        factory,
        "settlement-source-crash",
        lambda session: True,
        impact_batch_size=1,
        coupon_batch_size=1,
    )
    assert result["completed"] is True
    assert db_session.scalar(
        select(SettlementFeeResult.id).where(
            SettlementFeeResult.coupon_id == first.coupon_id
        )
    ) is not None
    assert db_session.scalar(
        select(SettlementFeeResult.id).where(
            SettlementFeeResult.coupon_id == second.coupon_id
        )
    ) is not None
    assert db_session.scalar(
        select(SettlementFeeResultCurrent.id).where(
            SettlementFeeResultCurrent.coupon_id == first.coupon_id
        )
    ) is not None
    assert db_session.scalar(
        select(SettlementFeeResultCurrent.id).where(
            SettlementFeeResultCurrent.coupon_id == second.coupon_id
        )
    ) is not None
    assert db_session.scalar(
        select(func.count()).select_from(SettlementFeeResult).where(
            SettlementFeeResult.coupon_id.in_([first.coupon_id, second.coupon_id])
        )
    ) == 4
    assert db_session.scalar(
        select(func.count()).select_from(SettlementFeeAdjustment).where(
            SettlementFeeAdjustment.coupon_id.in_([first.coupon_id, second.coupon_id])
        )
    ) == 0


def test_settle_impacted_coupons_kernel_failure_rolls_back_and_closes_batch(
    db_session, monkeypatch
) -> None:
    coupon = _seed_local_coupon(db_session, "coupon-kernel-failure")
    db_session.add(
        JobImpact(
            impact_key="settlement-kernel-failure",
            entity_type="coupon",
            entity_key=coupon.coupon_id,
            affected_closure_json={"coupon_ids": [coupon.coupon_id]},
            source_run_id="settlement-source-kernel-failure",
        )
    )
    db_session.commit()
    base_factory = sessionmaker(bind=db_session.get_bind(), future=True)
    sessions = []

    class CountingSession:
        def __init__(self, wrapped):
            self.wrapped = wrapped
            self.rollback_count = 0
            self.close_count = 0

        def __getattr__(self, name):
            return getattr(self.wrapped, name)

        def begin(self, *args, **kwargs):
            return self.wrapped.begin(*args, **kwargs)

        def rollback(self):
            self.rollback_count += 1
            return self.wrapped.rollback()

        def close(self):
            self.close_count += 1
            return self.wrapped.close()

    def counting_factory():
        session = CountingSession(base_factory())
        sessions.append(session)
        return session

    def fail_kernel(session, coupon_id, calculation_run_id):
        raise RuntimeError("kernel failed")

    monkeypatch.setattr(settlement_worker, "settle_coupon_local", fail_kernel)
    with pytest.raises(RuntimeError, match="kernel failed"):
        settlement_worker.settle_impacted_coupons(
            counting_factory,
            "settlement-source-kernel-failure",
            lambda session: True,
            impact_batch_size=1,
            coupon_batch_size=1,
        )

    assert sessions
    assert all(session.close_count == 1 for session in sessions)
    assert any(session.rollback_count >= 1 for session in sessions)
    assert db_session.scalar(
        select(SettlementOrderDetail).where(
            SettlementOrderDetail.coupon_id == coupon.coupon_id
        )
    ) is None


def test_settle_impacted_coupons_nth_kernel_failure_rolls_back_entire_batch(
    db_session, monkeypatch
) -> None:
    first = _seed_local_coupon(db_session, "coupon-batch-failure-a")
    second = RawDouyinOrderCoupon(
        coupon_id="coupon-batch-failure-b",
        order_id=first.order_id,
        raw_order_id=first.raw_order_id,
        coupon_status="fulfilled",
        coupon_status_normalized="fulfilled",
        coupon_paid_amount_cent=10000,
    )
    db_session.add(second)
    db_session.add(
        RawDouyinVerifyRecord(
            verify_id="verify-coupon-batch-failure-b",
            coupon_id=second.coupon_id,
            verify_status="valid",
            verify_time=datetime(2026, 8, 7, 10, tzinfo=timezone.utc),
            poi_id="poi-verify",
            sku_id="sku-service",
            paid_amount_cent=10000,
        )
    )
    db_session.add(
        JobImpact(
            impact_key="settlement-nth-kernel-failure",
            entity_type="order",
            entity_key=first.order_id,
            affected_closure_json={"order_ids": [first.order_id]},
            source_run_id="settlement-source-nth-kernel-failure",
        )
    )
    db_session.commit()
    base_factory = sessionmaker(bind=db_session.get_bind(), future=True)
    sessions = []

    class CountingSession:
        def __init__(self, wrapped):
            self.wrapped = wrapped
            self.rollback_count = 0
            self.close_count = 0

        def __getattr__(self, name):
            return getattr(self.wrapped, name)

        def begin(self, *args, **kwargs):
            return self.wrapped.begin(*args, **kwargs)

        def rollback(self):
            self.rollback_count += 1
            return self.wrapped.rollback()

        def close(self):
            self.close_count += 1
            return self.wrapped.close()

    def counting_factory():
        session = CountingSession(base_factory())
        sessions.append(session)
        return session

    original = settlement_worker.settle_coupon_local
    calls = {"count": 0}

    def fail_on_second(session, coupon, calculation_run_id):
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("second coupon kernel failed")
        return original(session, coupon, calculation_run_id)

    monkeypatch.setattr(settlement_worker, "settle_coupon_local", fail_on_second)
    with pytest.raises(RuntimeError, match="second coupon kernel failed"):
        settlement_worker.settle_impacted_coupons(
            counting_factory,
            "settlement-source-nth-kernel-failure",
            lambda session: True,
            impact_batch_size=1,
            coupon_batch_size=2,
        )

    assert calls["count"] == 2
    assert sessions and all(session.close_count == 1 for session in sessions)
    assert any(session.rollback_count >= 1 for session in sessions)
    assert db_session.scalar(
        select(func.count()).select_from(SettlementOrderDetail).where(
            SettlementOrderDetail.coupon_id.in_([first.coupon_id, second.coupon_id])
        )
    ) == 0
    assert db_session.scalar(
        select(func.count()).select_from(SettlementFeeResult).where(
            SettlementFeeResult.coupon_id.in_([first.coupon_id, second.coupon_id])
        )
    ) == 0


def test_settle_impacted_coupons_source_run_isolation(db_session) -> None:
    coupon_a = _seed_local_coupon(db_session, "coupon-source-a")
    coupon_b = _seed_local_coupon(db_session, "coupon-source-b", seed_dimensions=False)
    db_session.add_all(
        [
            JobImpact(
                impact_key="settlement-source-a",
                entity_type="coupon",
                entity_key=coupon_a.coupon_id,
                affected_closure_json={"coupon_ids": [coupon_a.coupon_id]},
                source_run_id="settlement-source-a",
            ),
            JobImpact(
                impact_key="settlement-source-b",
                entity_type="coupon",
                entity_key=coupon_b.coupon_id,
                affected_closure_json={"coupon_ids": [coupon_b.coupon_id]},
                source_run_id="settlement-source-b",
            ),
        ]
    )
    db_session.commit()
    factory = sessionmaker(bind=db_session.get_bind(), future=True)

    result = settlement_worker.settle_impacted_coupons(
        factory,
        "settlement-source-a",
        lambda session: True,
        impact_batch_size=1,
        coupon_batch_size=1,
    )

    assert result["coupon_count"] == 1
    assert db_session.scalar(
        select(SettlementOrderDetail.coupon_id).where(
            SettlementOrderDetail.coupon_id == coupon_a.coupon_id
        )
    ) == coupon_a.coupon_id
    assert db_session.scalar(
        select(SettlementOrderDetail.coupon_id).where(
            SettlementOrderDetail.coupon_id == coupon_b.coupon_id
        )
    ) is None


def test_settle_impacted_coupons_dedupes_within_impact_page(db_session) -> None:
    coupon = _seed_local_coupon(db_session, "coupon-page-dedupe")
    db_session.add_all(
        [
            JobImpact(
                impact_key="settlement-page-dedupe-a",
                entity_type="coupon",
                entity_key=coupon.coupon_id,
                affected_closure_json={"coupon_ids": [coupon.coupon_id]},
                source_run_id="settlement-source-page-dedupe",
            ),
            JobImpact(
                impact_key="settlement-page-dedupe-b",
                entity_type="verify",
                entity_key=f"verify-{coupon.coupon_id}",
                affected_closure_json={
                    "coupon_ids": [coupon.coupon_id],
                    "poi_ids": ["poi-verify"],
                },
                source_run_id="settlement-source-page-dedupe",
            ),
        ]
    )
    db_session.commit()
    factory = sessionmaker(bind=db_session.get_bind(), future=True)

    result = settlement_worker.settle_impacted_coupons(
        factory,
        "settlement-source-page-dedupe",
        lambda session: True,
        impact_batch_size=2,
        coupon_batch_size=1,
    )

    assert result["impact_count"] == 2
    assert result["coupon_count"] == 1
    assert result["result_count"] == 2


def test_settle_impacted_coupons_unknown_impact_is_skipped(db_session) -> None:
    coupon = _seed_local_coupon(db_session, "coupon-unknown-impact")
    db_session.add_all(
        [
            JobImpact(
                impact_key="settlement-unknown",
                entity_type="unrelated_entity",
                entity_key="unrelated-key",
                affected_closure_json={
                    "coupon_ids": [coupon.coupon_id],
                    "affected_months": ["2099-01"],
                    "store_ids": ["unrelated-store"],
                },
                source_run_id="settlement-source-unknown",
            ),
            JobImpact(
                impact_key="settlement-known-after-unknown",
                entity_type="coupon",
                entity_key=coupon.coupon_id,
                affected_closure_json={"coupon_ids": [coupon.coupon_id]},
                source_run_id="settlement-source-unknown",
            ),
        ]
    )
    db_session.commit()
    factory = sessionmaker(bind=db_session.get_bind(), future=True)

    result = settlement_worker.settle_impacted_coupons(
        factory,
        "settlement-source-unknown",
        lambda session: True,
        impact_batch_size=2,
        coupon_batch_size=1,
    )

    assert result["impact_count"] == 2
    assert result["coupon_count"] == 1
    assert "2099-01" not in result["affected_months"]
    assert "unrelated-store" not in result["affected_store_ids"]


def test_settle_impacted_coupons_valid_closure_without_current_coupon_keeps_dimensions(
    db_session,
) -> None:
    db_session.add(
        JobImpact(
            impact_key="settlement-valid-missing-coupon",
            entity_type="coupon",
            entity_key="coupon-deleted",
            affected_closure_json={
                "coupon_ids": ["coupon-deleted"],
                "affected_months": ["2026-06", "2026-09"],
                "store_ids": ["store-old", "store-new"],
            },
            source_run_id="settlement-source-missing-coupon",
        )
    )
    db_session.commit()
    factory = sessionmaker(bind=db_session.get_bind(), future=True)

    result = settlement_worker.settle_impacted_coupons(
        factory,
        "settlement-source-missing-coupon",
        lambda session: True,
        impact_batch_size=1,
        coupon_batch_size=1,
    )

    assert result["completed"] is True
    assert result["coupon_count"] == 0
    assert result["affected_months"] == ["2026-06", "2026-09"]
    assert result["affected_store_ids"] == ["store-new", "store-old"]


def test_typed_settlement_selectors_are_entity_scoped_and_refund_side_aware() -> None:
    refund = settlement_worker._settlement_coupon_selectors(
        {
            "entity_type": "refund",
            "entity_key": "refund-event-1",
            "old_values_json": {
                "refund_event_id": "refund-event-1",
                "coupon_id": "coupon-old",
                "order_id": "order-old",
            },
            "new_values_json": {
                "refund_event_id": "refund-event-1",
                "coupon_id": None,
                "order_id": "order-new",
            },
            "affected_closure_json": {},
        }
    )
    assert refund.direct_coupon_ids == ("coupon-old",)
    assert refund.order_ids == ("order-new",)
    assert refund.verify_ids == ()
    assert refund.poi_ids == ()
    assert refund.store_ids == ()

    reverse_refund = settlement_worker._settlement_coupon_selectors(
        {
            "entity_type": "refund",
            "entity_key": "refund-event-reverse",
            "old_values_json": {
                "refund_event_id": "refund-event-reverse",
                "coupon_id": None,
                "order_id": "order-old",
            },
            "new_values_json": {
                "refund_event_id": "refund-event-reverse",
                "coupon_id": "coupon-new",
                "order_id": "order-new",
            },
            "affected_closure_json": {},
        }
    )
    assert reverse_refund.direct_coupon_ids == ("coupon-new",)
    assert reverse_refund.order_ids == ("order-old",)

    coupon = settlement_worker._settlement_coupon_selectors(
        {
            "entity_type": "coupon",
            "entity_key": "coupon-direct",
            "old_values_json": {},
            "new_values_json": {},
            "affected_closure_json": {
                "coupon_ids": ["coupon-direct"],
                "order_ids": ["order-context"],
                "poi_ids": ["poi-context"],
                "store_ids": ["store-context"],
            },
        }
    )
    assert coupon.direct_coupon_ids == ("coupon-direct",)
    assert coupon.order_ids == coupon.verify_ids == coupon.poi_ids == coupon.store_ids == ()

    order = settlement_worker._settlement_coupon_selectors(
        {
            "entity_type": "order",
            "entity_key": "order-direct",
            "old_values_json": {},
            "new_values_json": {},
            "affected_closure_json": {
                "order_ids": ["order-direct"],
                "coupon_ids": ["coupon-context"],
                "poi_ids": ["poi-context"],
                "store_ids": ["store-context"],
            },
        }
    )
    assert order.order_ids == ("order-direct",)
    assert order.direct_coupon_ids == order.verify_ids == order.poi_ids == order.store_ids == ()

    verify = settlement_worker._settlement_coupon_selectors(
        {
            "entity_type": "verify",
            "entity_key": "verify-direct",
            "old_values_json": {"verify_id": "verify-old", "coupon_id": "coupon-old", "poi_id": "poi-old"},
            "new_values_json": {"verify_id": "verify-new", "coupon_id": "coupon-new", "poi_id": "poi-new"},
            "affected_closure_json": {
                "order_ids": ["order-context"],
                "store_ids": ["store-context"],
            },
        }
    )
    assert verify.direct_coupon_ids == ("coupon-new", "coupon-old")
    assert verify.verify_ids == ("verify-direct", "verify-new", "verify-old")
    assert verify.poi_ids == ("poi-new", "poi-old")
    assert verify.order_ids == verify.store_ids == ()


def test_typed_selector_entity_key_collisions_do_not_guess_refund_or_mapping_store() -> None:
    refund = settlement_worker._settlement_coupon_selectors(
        {
            "entity_type": "refund",
            "entity_key": "order-collision",
            "old_values_json": {"refund_event_id": "order-collision"},
            "new_values_json": {"refund_event_id": "order-collision"},
            "affected_closure_json": {},
        }
    )
    assert refund.direct_coupon_ids == refund.order_ids == ()

    mapping = settlement_worker._settlement_coupon_selectors(
        {
            "entity_type": "store_poi_mapping",
            "entity_key": "poi-collision",
            "old_values_json": {"store_id": "store-old", "poi_id": "poi-collision"},
            "new_values_json": {"store_id": "store-new", "poi_id": "poi-collision"},
            "affected_closure_json": {},
        }
    )
    assert mapping.poi_ids == ("poi-collision",)
    assert mapping.store_ids == ("store-new", "store-old")

    mapping_collision = settlement_worker._settlement_coupon_selectors(
        {
            "entity_type": "store_poi_mapping",
            "entity_key": "shared-id",
            "old_values_json": {},
            "new_values_json": {},
            "affected_closure_json": {},
        }
    )
    assert mapping_collision.poi_ids == ("shared-id",)
    assert mapping_collision.store_ids == ()


def test_deleted_coupon_impact_keeps_raw_and_shanghai_months_from_iso_times(db_session) -> None:
    db_session.add(
        JobImpact(
            impact_key="settlement-deleted-cross-shanghai-month",
            entity_type="coupon",
            entity_key="coupon-deleted-cross-month",
            old_values_json={
                "coupon_id": "coupon-deleted-cross-month",
                "sale_time": "2026-08-31T16:30:00+00:00",
                "verify_time": "2026-08-31T16:30:00+00:00",
            },
            new_values_json={
                "coupon_id": "coupon-deleted-cross-month",
                "sale_time": "2026-08-31T16:30:00+00:00",
                "verify_time": "2026-08-31T16:30:00+00:00",
            },
            affected_closure_json={},
            source_run_id="settlement-source-deleted-cross-month",
        )
    )
    db_session.commit()
    factory = sessionmaker(bind=db_session.get_bind(), future=True)

    result = settlement_worker.settle_impacted_coupons(
        factory,
        "settlement-source-deleted-cross-month",
        lambda session: True,
        impact_batch_size=1,
        coupon_batch_size=1,
    )

    assert result["coupon_count"] == 0
    assert result["affected_months"] == ["2026-08", "2026-09"]


def test_settlement_months_treat_naive_datetimes_as_utc_but_date_only_as_raw() -> None:
    assert settlement_worker._settlement_months(
        "2026-08-31T16:30:00"
    ) == {"2026-08", "2026-09"}
    assert settlement_worker._settlement_months(
        datetime(2026, 8, 31, 16, 30)
    ) == {"2026-08", "2026-09"}
    assert settlement_worker._settlement_months(
        "2026-08-31T16:30:00Z"
    ) == {"2026-08", "2026-09"}
    assert settlement_worker._settlement_months("2026-08-31") == {"2026-08"}
    assert settlement_worker._settlement_months(date(2026, 8, 31)) == {"2026-08"}
    assert settlement_worker._settlement_months("2026-08") == {"2026-08"}


def test_settle_impacted_coupons_refund_direct_coupon_does_not_fan_out_siblings(
    db_session,
) -> None:
    first = _seed_local_coupon(db_session, "coupon-refund-direct-a")
    second = RawDouyinOrderCoupon(
        coupon_id="coupon-refund-direct-b",
        order_id=first.order_id,
        raw_order_id=first.raw_order_id,
        coupon_status="fulfilled",
        coupon_status_normalized="fulfilled",
        coupon_paid_amount_cent=10000,
    )
    db_session.add(second)
    db_session.add(
        RawDouyinVerifyRecord(
            verify_id="verify-coupon-refund-direct-b",
            coupon_id=second.coupon_id,
            verify_status="valid",
            verify_time=datetime(2026, 8, 7, 10, tzinfo=timezone.utc),
            poi_id="poi-verify",
            sku_id="sku-service",
            paid_amount_cent=10000,
        )
    )
    db_session.add(
        DouyinRefundEvent(
            refund_event_id="refund-direct-impact",
            order_id=first.order_id,
            coupon_id=first.coupon_id,
            refund_type=1,
            refund_status=2,
            refund_amount_cent=1000,
            occurred_at=datetime(2026, 8, 8, tzinfo=timezone.utc),
            source_run_id="settlement-source-refund-direct",
        )
    )
    db_session.add(
        JobImpact(
            impact_key="settlement-refund-direct-impact",
            entity_type="refund",
            entity_key="refund-direct-impact",
            old_values_json={
                "refund_event_id": "refund-direct-impact",
                "coupon_id": first.coupon_id,
                "order_id": first.order_id,
            },
            new_values_json={
                "refund_event_id": "refund-direct-impact",
                "coupon_id": first.coupon_id,
                "order_id": first.order_id,
            },
            affected_closure_json={
                "coupon_ids": [first.coupon_id],
                "order_ids": [first.order_id],
                "poi_ids": ["poi-verify"],
                "store_ids": ["store-verify"],
            },
            source_run_id="settlement-source-refund-direct",
        )
    )
    db_session.commit()
    factory = sessionmaker(bind=db_session.get_bind(), future=True)

    result = settlement_worker.settle_impacted_coupons(
        factory,
        "settlement-source-refund-direct",
        lambda session: True,
        impact_batch_size=1,
        coupon_batch_size=1,
    )

    assert result["coupon_count"] == 1
    assert db_session.scalar(
        select(SettlementOrderDetail.coupon_id).where(
            SettlementOrderDetail.coupon_id == first.coupon_id
        )
    ) == first.coupon_id
    assert db_session.scalar(
        select(SettlementOrderDetail.coupon_id).where(
            SettlementOrderDetail.coupon_id == second.coupon_id
        )
    ) is None


def test_settle_impacted_coupons_refund_entity_key_collision_is_not_order_fanout(
    db_session,
) -> None:
    coupon = _seed_local_coupon(db_session, "coupon-refund-id-collision")
    db_session.add(
        JobImpact(
            impact_key="settlement-refund-id-collision",
            entity_type="refund",
            entity_key=coupon.order_id,
            old_values_json={"refund_event_id": coupon.order_id},
            new_values_json={"refund_event_id": coupon.order_id},
            affected_closure_json={},
            source_run_id="settlement-source-refund-id-collision",
        )
    )
    db_session.commit()
    factory = sessionmaker(bind=db_session.get_bind(), future=True)

    result = settlement_worker.settle_impacted_coupons(
        factory,
        "settlement-source-refund-id-collision",
        lambda session: True,
        impact_batch_size=1,
        coupon_batch_size=1,
    )

    assert result["completed"] is True
    assert result["coupon_count"] == 0
    assert db_session.scalar(
        select(SettlementOrderDetail.coupon_id).where(
            SettlementOrderDetail.coupon_id == coupon.coupon_id
        )
    ) is None


def test_settle_impacted_coupons_mapping_entity_key_collision_is_not_store_fanout(
    db_session,
) -> None:
    coupon = _seed_local_coupon(db_session, "coupon-mapping-id-collision")
    db_session.add(
        JobImpact(
            impact_key="settlement-mapping-id-collision",
            entity_type="store_poi_mapping",
            entity_key="store-verify",
            old_values_json={},
            new_values_json={},
            affected_closure_json={},
            source_run_id="settlement-source-mapping-id-collision",
        )
    )
    db_session.commit()
    factory = sessionmaker(bind=db_session.get_bind(), future=True)

    result = settlement_worker.settle_impacted_coupons(
        factory,
        "settlement-source-mapping-id-collision",
        lambda session: True,
        impact_batch_size=1,
        coupon_batch_size=1,
    )

    assert result["completed"] is True
    assert result["coupon_count"] == 0
    assert db_session.scalar(
        select(SettlementOrderDetail.coupon_id).where(
            SettlementOrderDetail.coupon_id == coupon.coupon_id
        )
    ) is None
