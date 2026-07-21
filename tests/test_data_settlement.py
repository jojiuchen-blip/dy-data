from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.models import (
    AggStoreMonthlySettlement,
    AggStoreRanking,
    Base,
    DataQualityIssue,
    DimAwemeAccount,
    DouyinRefundEvent,
    DimNonCommissionOwnerAccount,
    DimSkuProductRule,
    JobRun,
    RawDouyinOrder,
    RawDouyinOrderCoupon,
    RawDouyinVerifyRecord,
    SettlementFeeAdjustment,
    SettlementFeeResult,
    SettlementFeeResultCurrent,
    SettlementOrderDetail,
    SettlementScopeRule,
    SettlementStatement,
    SettlementStatementEntry,
    SettlementStatementLine,
    SkuFeeRule,
)
from apps.api.dy_api.rule_utils import normalize_owner_account_name
import apps.worker.settlement as settlement_worker
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
from apps.worker.settlement import (
    lock_settlement_statement,
    rebuild_dual_fee_projections,
    rebuild_dual_fee_results,
    rebuild_settlement,
    run_settlement_job,
)
from apps.api.dy_api.db import session_scope


RUN_ID = "fixture-run"
SETTLEMENT_RUN_ID = "settlement-fixture"


def dt(day: int) -> datetime:
    return datetime(2026, 1, day, 10, 0, tzinfo=timezone.utc)


def count(session: Session, model: type) -> int:
    value = session.scalar(select(func.count()).select_from(model))
    assert value is not None
    return value


def monthly_projection(
    session: Session, month: str, store_id: str, product_type: str
) -> AggStoreMonthlySettlement | None:
    return session.scalar(
        select(AggStoreMonthlySettlement).where(
            AggStoreMonthlySettlement.month == month,
            AggStoreMonthlySettlement.store_id == store_id,
            AggStoreMonthlySettlement.product_scope == "all",
            AggStoreMonthlySettlement.product_type == product_type,
        )
    )


def ranking_projection(
    session: Session, month: str, product_type: str, store_id: str
) -> AggStoreRanking | None:
    return session.scalar(
        select(AggStoreRanking).where(
            AggStoreRanking.period_type == 1,
            AggStoreRanking.period_key == month,
            AggStoreRanking.store_id == store_id,
            AggStoreRanking.product_scope == "all",
            AggStoreRanking.product_type == product_type,
        )
    )


def load_fixture(session: Session) -> None:
    upsert_store(session, "store-s1", "Store S1")
    upsert_store(session, "store-s2", "Store S2")
    upsert_store_poi_mapping(session, "store-s1", "poi-s1", poi_name="POI S1", mapping_source="fixture")
    upsert_store_poi_mapping(session, "store-s2", "poi-s2", poi_name="POI S2", mapping_source="fixture")
    upsert_aweme_account(session, "owner-s1", nickname="Owner S1", store_id="store-s1", binding_status="active")
    upsert_aweme_account(session, "owner-s2", nickname="Fallback S2", store_id="store-s2", binding_status="active")
    upsert_aweme_binding(
        session,
        "owner-s1:dy-owner-s1:poi-s1",
        douyin_id="dy-owner-s1",
        douyin_nickname="Owner S1",
        account_id="store-s1",
        account_name="Store S1",
        poi_id="poi-s1",
        binding_status="active",
    )
    upsert_aweme_binding(
        session,
        "owner-s2:dy-owner-s2:poi-s2",
        douyin_id="dy-owner-s2",
        douyin_nickname="Fallback S2",
        account_id="store-s2",
        account_name="Store S2",
        poi_id="poi-s2",
        binding_status="active",
    )
    upsert_sku_product_rule(
        session,
        "sku-service",
        "service",
        product_name="Service SKU",
        commission_rate=Decimal("0.1000"),
        is_service_product=True,
    )

    rows = [
        ("order-cross", "coupon-cross", "verify-cross", "owner-s1", "Owner S1", "sku-service", "poi-s2", 10000, None, None),
        ("order-same", "coupon-same", "verify-same", None, "Fallback S2", "sku-service", "poi-s2", 20000, None, None),
        ("order-no-owner", "coupon-no-owner", "verify-no-owner", None, "Missing", "sku-service", "poi-s2", 30000, None, None),
        ("order-no-sku", "coupon-no-sku", "verify-no-sku", "owner-s1", "Owner S1", "sku-missing", "poi-s2", 40000, None, None),
        ("order-no-poi", "coupon-no-poi", "verify-no-poi", "owner-s1", "Owner S1", "sku-service", "poi-missing", 50000, None, None),
        ("order-refund", "coupon-refund", "verify-refund", "owner-s1", "Owner S1", "sku-service", "poi-s2", 60000, "refunded", 60000),
        ("order-conflict", "coupon-conflict", "verify-conflict", "owner-s1", "Fallback S2", "sku-service", "poi-s2", 1000, None, None),
    ]

    for index, (
        order_id,
        coupon_id,
        verify_id,
        owner_id,
        owner_name,
        sku_id,
        poi_id,
        amount_cent,
        coupon_status,
        refunded_cent,
    ) in enumerate(rows, start=1):
        upsert_raw_order(
            session,
            order_id,
            order_status="paid",
            sku_id=sku_id,
            product_name="Fixture product",
            pay_time=dt(index),
            create_order_time=dt(index),
            paid_amount_cent=amount_cent,
            owner_account_id=owner_id,
            owner_account_name=owner_name,
            source_run_id=RUN_ID,
        )
        upsert_order_coupon(
            session,
            coupon_id,
            order_id,
            coupon_status=coupon_status or "fulfilled",
            coupon_refunded_cent=refunded_cent,
            source_run_id=RUN_ID,
        )
        upsert_verify_record(
            session,
            verify_id,
            coupon_id=coupon_id,
            verify_status="valid",
            verify_time=dt(index),
            poi_id=poi_id,
            sku_id=sku_id,
            paid_amount_cent=amount_cent,
            source_run_id=RUN_ID,
        )


def test_fixture_upsert_and_settlement_rebuild_are_idempotent(db_session: Session) -> None:
    load_fixture(db_session)
    load_fixture(db_session)

    assert count(db_session, RawDouyinOrder) == 7
    assert count(db_session, RawDouyinOrderCoupon) == 7
    assert count(db_session, RawDouyinVerifyRecord) == 7

    first_stats = run_settlement_job(db_session, job_id="job-settlement-fixture", source_run_id=SETTLEMENT_RUN_ID)
    second_stats = run_settlement_job(db_session, job_id="job-settlement-fixture", source_run_id=SETTLEMENT_RUN_ID)

    assert first_stats.detail_count == 7
    assert second_stats.detail_count == 7
    assert count(db_session, SettlementOrderDetail) == 7
    assert count(db_session, JobRun) == 1


def test_settlement_rebuild_clears_stale_quality_issues(db_session: Session) -> None:
    load_fixture(db_session)
    db_session.add(
        DataQualityIssue(
            issue_id="stale-issue",
            issue_type="stale",
            order_id="old-order",
            coupon_id="old-coupon",
            severity="warning",
            message="Stale issue from a previous full rebuild.",
            raw_context_json={},
            source_run_id="old-run",
        )
    )
    db_session.commit()

    run_settlement_job(db_session, job_id="job-settlement-fixture", source_run_id=SETTLEMENT_RUN_ID)

    assert db_session.get(DataQualityIssue, "stale-issue") is None
    assert "old-run" not in set(db_session.scalars(select(DataQualityIssue.source_run_id)))


def test_settlement_owner_matching_issues_refund_exclusion_and_aggregates(db_session: Session) -> None:
    load_fixture(db_session)
    run_settlement_job(db_session, job_id="job-settlement-fixture", source_run_id=SETTLEMENT_RUN_ID)

    cross = db_session.get(SettlementOrderDetail, "coupon-cross")
    assert cross is not None
    assert cross.sale_store_id == "store-s1"
    assert cross.verify_store_id == "store-s2"
    assert cross.relation_type == "cross_store"
    assert cross.is_commissionable is True
    assert cross.receivable_commission_cent == 1000

    same = db_session.get(SettlementOrderDetail, "coupon-same")
    assert same is not None
    assert same.sale_store_id == "store-s2"
    assert same.relation_type == "same_store"
    assert same.is_commissionable is False
    assert same.commission_rate == Decimal("0.0000")
    assert same.receivable_commission_cent == 0
    assert same.payable_commission_cent == 0

    refunded = db_session.get(SettlementOrderDetail, "coupon-refund")
    assert refunded is not None
    assert refunded.is_refund_excluded is True
    assert refunded.is_commissionable is False
    assert refunded.commission_rate == Decimal("0.0000")
    assert refunded.receivable_commission_cent == 0
    assert refunded.payable_commission_cent == 0

    conflict = db_session.get(SettlementOrderDetail, "coupon-conflict")
    assert conflict is not None
    assert conflict.sale_store_id == "store-s2"
    assert conflict.relation_type == "same_store"

    issue_types = set(db_session.scalars(select(DataQualityIssue.issue_type)))
    assert {"unmatched_owner", "unmatched_sku", "unmatched_poi"}.issubset(issue_types)

    monthly_s1 = monthly_projection(db_session, "2026-01", "store-s1", "all")
    monthly_s2 = monthly_projection(db_session, "2026-01", "store-s2", "all")
    assert monthly_s1 is not None
    assert monthly_s2 is not None
    assert monthly_s1.estimated_receivable_commission_cent == 1000
    assert monthly_s1.commissionable_total_cent == 10000
    assert monthly_s2.estimated_payable_commission_cent == 1000

    ranking_s1 = ranking_projection(db_session, "2026-01", "all", "store-s1")
    assert ranking_s1 is not None
    assert ranking_s1.sales_order_count == 3
    assert ranking_s1.self_sold_other_verified_count == 2
    assert ranking_s1.effective_commission_income_cent == 1000


def test_non_commission_owner_account_forces_zero_rate_and_amounts(
    db_session: Session,
) -> None:
    load_fixture(db_session)
    db_session.merge(
        DimNonCommissionOwnerAccount(
            normalized_owner_account_name=normalize_owner_account_name(" Owner S1 "),
            owner_account_name="Owner S1",
            is_active=True,
        )
    )

    run_settlement_job(db_session, job_id="job-non-commission-owner", source_run_id=SETTLEMENT_RUN_ID)

    cross = db_session.get(SettlementOrderDetail, "coupon-cross")
    assert cross is not None
    assert cross.relation_type == "cross_store"
    assert cross.is_commissionable is False
    assert cross.commission_rate == Decimal("0.0000")
    assert cross.receivable_commission_cent == 0
    assert cross.payable_commission_cent == 0

    monthly_s1 = monthly_projection(db_session, "2026-01", "store-s1", "all")
    if monthly_s1 is not None:
        assert monthly_s1.estimated_receivable_commission_cent == 0
        assert monthly_s1.commissionable_total_cent == 0

    ranking_s1 = ranking_projection(db_session, "2026-01", "all", "store-s1")
    assert ranking_s1 is not None
    assert ranking_s1.effective_commission_income_cent == 0


def test_numeric_verify_statuses_are_classified_before_settlement(db_session: Session) -> None:
    upsert_store(db_session, "store-s1", "Store S1")
    upsert_store(db_session, "store-s2", "Store S2")
    upsert_store_poi_mapping(db_session, "store-s2", "poi-s2", poi_name="POI S2", mapping_source="fixture")
    upsert_aweme_account(db_session, "owner-s1", nickname="Owner S1", store_id="store-s1", binding_status="active")
    upsert_aweme_binding(
        db_session,
        "owner-s1:dy-owner-s1:poi-s1",
        douyin_id="dy-owner-s1",
        douyin_nickname="Owner S1",
        account_id="store-s1",
        account_name="Store S1",
        poi_id="poi-s1",
        binding_status="active",
    )
    upsert_sku_product_rule(
        db_session,
        "sku-service",
        "service",
        product_name="Service SKU",
        commission_rate=Decimal("0.1000"),
        is_service_product=True,
    )
    for suffix, status in (("valid", "1"), ("cancelled", "2")):
        order_id = f"order-{suffix}"
        coupon_id = f"coupon-{suffix}"
        upsert_raw_order(
            db_session,
            order_id,
            sku_id="sku-service",
            pay_time=dt(1),
            owner_account_name="Owner S1",
            paid_amount_cent=10000,
        )
        upsert_order_coupon(db_session, coupon_id, order_id, coupon_status="fulfilled")
        upsert_verify_record(
            db_session,
            f"verify-{suffix}",
            coupon_id=coupon_id,
            verify_status=status,
            verify_time=dt(1),
            poi_id="poi-s2",
            sku_id="sku-service",
            paid_amount_cent=10000,
        )

    run_settlement_job(db_session, job_id="job-numeric-status", source_run_id=SETTLEMENT_RUN_ID)

    assert db_session.get(SettlementOrderDetail, "coupon-valid").is_verified is True
    assert db_session.get(SettlementOrderDetail, "coupon-cancelled").is_verified is False


def test_owner_nickname_matches_raw_aweme_binding_when_dimension_nickname_is_overwritten(
    db_session: Session,
) -> None:
    upsert_store(
        db_session,
        "store-from-binding",
        "Store From Raw Binding",
        certified_subject_name="Subject From Raw Binding",
    )
    upsert_store(db_session, "store-verify", "Verify Store")
    upsert_store_poi_mapping(db_session, "store-verify", "poi-verify", mapping_source="fixture")
    upsert_aweme_account(
        db_session,
        "store-from-binding",
        nickname="Another Douyin Nickname",
        store_id="store-from-binding",
        binding_status="认证成功",
    )
    upsert_aweme_binding(
        db_session,
        "store-from-binding:dy-raw:poi-sale",
        douyin_id="dy-raw",
        douyin_nickname="Raw Binding Nickname",
        account_id="store-from-binding",
        account_name="Store From Raw Binding",
        poi_id="poi-sale",
        binding_status="认证成功",
        raw_payload={"认证主体": "Subject From Raw Binding"},
    )
    upsert_sku_product_rule(
        db_session,
        "sku-service",
        "service",
        product_name="Service SKU",
        commission_rate=Decimal("0.1000"),
        is_service_product=True,
    )
    upsert_raw_order(
        db_session,
        "order-raw-binding",
        sku_id="sku-service",
        pay_time=dt(1),
        owner_account_id="transfer-uid-not-in-binding",
        owner_account_name="Raw Binding Nickname",
        paid_amount_cent=10000,
    )
    upsert_order_coupon(db_session, "coupon-raw-binding", "order-raw-binding", coupon_status="fulfilled")
    upsert_verify_record(
        db_session,
        "verify-raw-binding",
        coupon_id="coupon-raw-binding",
        verify_status="valid",
        verify_time=dt(1),
        poi_id="poi-verify",
        sku_id="sku-service",
        paid_amount_cent=10000,
    )

    run_settlement_job(db_session, job_id="job-raw-binding-owner", source_run_id=SETTLEMENT_RUN_ID)

    detail = db_session.get(SettlementOrderDetail, "coupon-raw-binding")
    assert detail is not None
    assert detail.sale_store_id == "store-from-binding"
    assert detail.sale_store_name == "Store From Raw Binding"


def test_inactive_raw_aweme_binding_does_not_fall_back_to_dimension_nickname(
    db_session: Session,
) -> None:
    upsert_store(db_session, "store-stale", "Stale Store")
    upsert_store(db_session, "store-verify", "Verify Store")
    upsert_store_poi_mapping(db_session, "store-verify", "poi-verify", mapping_source="fixture")
    upsert_aweme_account(
        db_session,
        "store-stale",
        nickname="Inactive Binding Nickname",
        store_id="store-stale",
        binding_status="认证成功",
    )
    upsert_aweme_binding(
        db_session,
        "store-stale:dy-inactive:poi-sale",
        douyin_id="dy-inactive",
        douyin_nickname="Inactive Binding Nickname",
        account_id="store-stale",
        account_name="Stale Store",
        poi_id="poi-sale",
        binding_status="已解绑",
    )
    upsert_sku_product_rule(
        db_session,
        "sku-service",
        "service",
        product_name="Service SKU",
        commission_rate=Decimal("0.1000"),
        is_service_product=True,
    )
    upsert_raw_order(
        db_session,
        "order-inactive-binding",
        sku_id="sku-service",
        pay_time=dt(1),
        owner_account_name="Inactive Binding Nickname",
        paid_amount_cent=10000,
    )
    upsert_order_coupon(db_session, "coupon-inactive-binding", "order-inactive-binding", coupon_status="fulfilled")
    upsert_verify_record(
        db_session,
        "verify-inactive-binding",
        coupon_id="coupon-inactive-binding",
        verify_status="valid",
        verify_time=dt(1),
        poi_id="poi-verify",
        sku_id="sku-service",
        paid_amount_cent=10000,
    )

    run_settlement_job(db_session, job_id="job-inactive-binding-owner", source_run_id=SETTLEMENT_RUN_ID)

    detail = db_session.get(SettlementOrderDetail, "coupon-inactive-binding")
    assert detail is not None
    assert detail.sale_store_id is None
    assert detail.sale_store_name is None


def _dual_time(month: int, day: int) -> datetime:
    return datetime(2026, month, day, 2, 0, tzinfo=timezone.utc)


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
            sku_name_snapshot="Dual fee SKU",
            product_scope_snapshot="service",
            product_type_snapshot="maintenance",
            promotion_service_fee_rate=Decimal(promotion),
            management_service_fee_rate=Decimal(management),
            effective_date=effective_date,
            effective_at=datetime.combine(effective_date, datetime.min.time(), timezone.utc),
            rule_status=1,
            created_by="test",
            change_reason="test fixture",
            published_at=datetime.combine(effective_date, datetime.min.time(), timezone.utc),
        )
    )


def _add_scope_rule(session: Session, month: str, *, channel: str = "short_video") -> None:
    version = f"scope-{month}-{channel}"
    session.add(
        SettlementScopeRule(
            scope_rule_version=version,
            idempotency_key_hash=(version * 64)[:64],
            request_payload_sha256=(version[::-1] * 64)[:64],
            effective_month=month,
            owner_account_id="owner-dual",
            sale_channel_normalized=channel,
            is_active=True,
            created_by="test",
            change_reason="test fixture",
        )
    )


def _load_dual_fee_fixture(
    session: Session,
    *,
    coupon_id: str = "coupon-dual",
    amount_cent: int = 10001,
    sale_channel: str = "short_video",
    with_verify: bool = True,
) -> None:
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
        sku_name="Dual fee SKU",
        product_scope="service",
        product_name="Dual fee product",
        owner_account_id="owner-dual",
        owner_account_name="Owner Dual",
        product_status_normalized="active",
        is_active_product=True,
        is_service_product=True,
    )
    upsert_raw_order(
        session,
        f"order-{coupon_id}",
        order_status="paid",
        order_status_raw="paid",
        order_status_normalized="paid",
        sku_id="sku-dual",
        pay_time=_dual_time(8, 10),
        sale_time=_dual_time(8, 10),
        paid_amount_cent=amount_cent,
        order_paid_amount_cent=amount_cent,
        owner_account_id="owner-dual",
        owner_account_name="Owner Dual",
        sale_channel=sale_channel,
        sale_channel_raw=sale_channel,
        sale_channel_normalized=sale_channel,
        source_run_id="dual-source",
    )
    upsert_order_coupon(
        session,
        coupon_id,
        f"order-{coupon_id}",
        coupon_status="fulfilled",
        coupon_status_raw="fulfilled",
        coupon_status_normalized="available",
        coupon_paid_amount_cent=amount_cent,
        coupon_refunded_amount_cent=0,
        source_run_id="dual-source",
    )
    if with_verify:
        upsert_verify_record(
            session,
            f"verify-{coupon_id}",
            coupon_id=coupon_id,
            verify_status="valid",
            verify_time=_dual_time(9, 5),
            poi_id="poi-verify",
            sku_id="sku-dual",
            paid_amount_cent=amount_cent,
            source_run_id="dual-source",
        )
    _add_scope_rule(session, "2026-08")
    _add_scope_rule(session, "2026-09")
    _add_fee_rule(
        session,
        "fee-aug",
        date(2026, 8, 1),
        promotion="0.012345",
        management="0.100000",
    )
    _add_fee_rule(
        session,
        "fee-sep",
        date(2026, 9, 1),
        promotion="0.300000",
        management="0.200000",
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


def test_dual_fee_results_use_directional_dates_rules_months_and_rounding(
    db_session: Session,
) -> None:
    _load_dual_fee_fixture(db_session)

    rebuild_dual_fee_results(db_session, calculation_run_id="dual-calc-1")

    promotion = _fee_result(db_session, "coupon-dual", 1)
    management = _fee_result(db_session, "coupon-dual", 2)
    assert promotion is not None
    assert management is not None
    assert promotion.original_business_month == "2026-08"
    assert promotion.rule_match_date == date(2026, 8, 10)
    assert promotion.sale_store_id == "store-sale"
    assert promotion.rule_version == "fee-aug"
    assert promotion.fee_rate == Decimal("0.012345")
    assert promotion.fee_amount_cent == 123
    assert management.original_business_month == "2026-09"
    assert management.rule_match_date == date(2026, 9, 5)
    assert management.verify_store_id == "store-verify"
    assert management.rule_version == "fee-sep"
    assert management.fee_rate == Decimal("0.200000")
    assert management.fee_amount_cent == 2000


def test_dual_fee_direction_failure_is_isolated_and_rerun_is_idempotent(
    db_session: Session,
) -> None:
    _load_dual_fee_fixture(db_session, with_verify=False)

    rebuild_dual_fee_results(db_session, calculation_run_id="dual-calc-1")
    rebuild_dual_fee_results(db_session, calculation_run_id="dual-calc-1")

    assert _fee_result(db_session, "coupon-dual", 1) is not None
    assert _fee_result(db_session, "coupon-dual", 2) is None
    assert count(db_session, SettlementFeeResult) == 1
    issue_types = set(db_session.scalars(select(DataQualityIssue.issue_type)))
    assert "dual_fee_missing_valid_verify" in issue_types


def test_internal_order_reference_mismatch_blocks_settlement_without_guessing(
    db_session: Session,
) -> None:
    _load_dual_fee_fixture(db_session, amount_cent=10000)
    wrong_order = upsert_raw_order(
        db_session,
        "order-wrong-internal-reference",
        order_status="paid",
        order_status_raw="paid",
        order_status_normalized="paid",
        sku_id="sku-dual",
        pay_time=_dual_time(8, 10),
        sale_time=_dual_time(8, 10),
        paid_amount_cent=10000,
        order_paid_amount_cent=10000,
        owner_account_id="owner-dual",
        owner_account_name="Owner Dual",
        sale_channel="short_video",
        sale_channel_raw="short_video",
        sale_channel_normalized="short_video",
        source_run_id="dual-source",
    )
    coupon = db_session.scalar(
        select(RawDouyinOrderCoupon).where(
            RawDouyinOrderCoupon.coupon_id == "coupon-dual"
        )
    )
    assert coupon is not None
    coupon.raw_order_id = wrong_order.id
    db_session.flush()

    rebuild_settlement(db_session, source_run_id="internal-reference-audit")

    assert db_session.get(SettlementOrderDetail, "coupon-dual") is None
    assert _fee_result(db_session, "coupon-dual", 1) is None
    assert _fee_result(db_session, "coupon-dual", 2) is None
    issue = db_session.scalar(
        select(DataQualityIssue).where(
            DataQualityIssue.issue_type
            == "raw_order_internal_reference_mismatch"
        )
    )
    assert issue is not None
    assert issue.raw_context_json["raw_order_id"] == wrong_order.id


def test_orphaned_internal_order_reference_blocks_settlement_without_guessing(
    db_session: Session,
) -> None:
    _load_dual_fee_fixture(db_session)
    coupon = db_session.scalar(
        select(RawDouyinOrderCoupon).where(
            RawDouyinOrderCoupon.coupon_id == "coupon-dual"
        )
    )
    assert coupon is not None
    coupon.raw_order_id = 999999
    db_session.flush()

    rebuild_settlement(db_session, source_run_id="internal-reference-orphan")

    assert db_session.get(SettlementOrderDetail, "coupon-dual") is None
    assert _fee_result(db_session, "coupon-dual", 1) is None
    assert _fee_result(db_session, "coupon-dual", 2) is None
    issue = db_session.scalar(
        select(DataQualityIssue).where(
            DataQualityIssue.issue_type
            == "raw_order_internal_reference_mismatch",
            DataQualityIssue.source_run_id == "internal-reference-orphan",
        )
    )
    assert issue is not None
    assert issue.raw_context_json["raw_order_id"] == 999999
    assert issue.raw_context_json["referenced_order_id"] is None


def test_refund_events_create_cross_month_immutable_adjustments_once(
    db_session: Session,
) -> None:
    _load_dual_fee_fixture(db_session, amount_cent=10000)
    rebuild_dual_fee_results(db_session, calculation_run_id="dual-calc-1")
    db_session.add(
        DouyinRefundEvent(
            refund_event_id="refund-partial",
            order_id="order-coupon-dual",
            coupon_id="coupon-dual",
            refund_type=1,
            refund_status=2,
            refund_amount_cent=4001,
            occurred_at=_dual_time(10, 2),
            source_run_id="refund-run",
            raw_payload={},
        )
    )
    db_session.flush()

    rebuild_dual_fee_results(db_session, calculation_run_id="dual-calc-2")
    first_adjustments = list(
        db_session.scalars(
            select(SettlementFeeAdjustment).order_by(
                SettlementFeeAdjustment.fee_direction
            )
        )
    )
    assert len(first_adjustments) == 2
    assert [row.adjustment_posting_month for row in first_adjustments] == [
        "2026-10",
        "2026-10",
    ]
    assert [row.adjustment_base_cent for row in first_adjustments] == [-4001, -4001]
    assert [row.adjustment_fee_cent for row in first_adjustments] == [-49, -800]

    db_session.add(
        DouyinRefundEvent(
            refund_event_id="refund-full",
            order_id="order-coupon-dual",
            coupon_id="coupon-dual",
            refund_type=2,
            refund_status=2,
            refund_amount_cent=5999,
            occurred_at=_dual_time(11, 3),
            source_run_id="refund-run",
            raw_payload={},
        )
    )
    db_session.flush()
    rebuild_dual_fee_results(db_session, calculation_run_id="dual-calc-3")
    rebuild_dual_fee_results(db_session, calculation_run_id="dual-calc-3")

    adjustments = list(
        db_session.scalars(
            select(SettlementFeeAdjustment).order_by(
                SettlementFeeAdjustment.occurred_at,
                SettlementFeeAdjustment.fee_direction,
            )
        )
    )
    assert len(adjustments) == 4
    assert [row.adjustment_base_cent for row in adjustments[2:]] == [-5999, -5999]
    assert [row.adjustment_fee_cent for row in adjustments[2:]] == [-74, -1200]
    assert [row.adjustment_type for row in adjustments[2:]] == [2, 2]
    assert [row.adjustment_posting_month for row in adjustments[2:]] == [
        "2026-11",
        "2026-11",
    ]


def test_cancelled_verification_adjusts_management_only(
    db_session: Session,
) -> None:
    _load_dual_fee_fixture(db_session, amount_cent=10000)
    rebuild_dual_fee_results(db_session, calculation_run_id="dual-calc-1")
    verify = db_session.get(RawDouyinVerifyRecord, "verify-coupon-dual")
    assert verify is not None
    verify.verify_status = "cancelled"
    verify.cancel_time = _dual_time(10, 8)
    db_session.flush()

    rebuild_dual_fee_results(db_session, calculation_run_id="dual-calc-2")
    adjustments = list(db_session.scalars(select(SettlementFeeAdjustment)))
    assert len(adjustments) == 1
    assert adjustments[0].fee_direction == 2
    assert adjustments[0].adjustment_type == 3
    assert adjustments[0].adjustment_base_cent == -10000
    assert adjustments[0].adjustment_fee_cent == -2000
    assert adjustments[0].adjustment_posting_month == "2026-10"


def test_backdated_late_refund_uses_observed_time_not_business_time(
    db_session: Session,
) -> None:
    _load_dual_fee_fixture(db_session, amount_cent=10000)
    rebuild_dual_fee_results(db_session, calculation_run_id="dual-calc-1")
    promotion = _fee_result(db_session, "coupon-dual", 1)
    assert promotion is not None
    observed_at = promotion.calculated_at.replace(tzinfo=timezone.utc) + timedelta(days=1)
    db_session.add(
        DouyinRefundEvent(
            refund_event_id="refund-backdated-late",
            order_id="order-coupon-dual",
            coupon_id="coupon-dual",
            refund_type=1,
            refund_status=2,
            refund_amount_cent=1000,
            occurred_at=_dual_time(7, 19),
            source_run_id="refund-late-run",
            raw_payload={},
            created_at=observed_at,
            updated_at=observed_at,
        )
    )
    db_session.flush()

    rebuild_dual_fee_results(db_session, calculation_run_id="dual-calc-2")

    adjustments = list(
        db_session.scalars(
            select(SettlementFeeAdjustment).where(
                SettlementFeeAdjustment.refund_event_id == "refund-backdated-late"
            )
        )
    )
    assert len(adjustments) == 2
    assert {row.fee_direction for row in adjustments} == {1, 2}


def test_backdated_cancellation_adjusts_existing_management_result(
    db_session: Session,
) -> None:
    _load_dual_fee_fixture(db_session, amount_cent=10000)
    rebuild_dual_fee_results(db_session, calculation_run_id="dual-calc-1")
    management = _fee_result(db_session, "coupon-dual", 2)
    verify = db_session.get(RawDouyinVerifyRecord, "verify-coupon-dual")
    assert management is not None
    assert verify is not None
    management.calculated_at = _dual_time(12, 1)
    verify.verify_status = "cancelled"
    verify.cancel_time = _dual_time(10, 8)
    db_session.flush()

    rebuild_dual_fee_results(db_session, calculation_run_id="dual-calc-2")

    adjustment = db_session.scalar(
        select(SettlementFeeAdjustment).where(
            SettlementFeeAdjustment.adjustment_type == 3
        )
    )
    assert adjustment is not None
    assert adjustment.fee_direction == 2
    assert adjustment.adjustment_fee_cent == -2000


def test_order_level_refund_is_assigned_only_when_order_has_one_coupon(
    db_session: Session,
) -> None:
    _load_dual_fee_fixture(db_session, amount_cent=10000)
    rebuild_dual_fee_results(db_session, calculation_run_id="dual-calc-1")
    db_session.add(
        DouyinRefundEvent(
            refund_event_id="refund-order-level-single",
            order_id="order-coupon-dual",
            coupon_id=None,
            refund_type=1,
            refund_status=2,
            refund_amount_cent=1000,
            occurred_at=_dual_time(10, 2),
            source_run_id="refund-order-level-run",
            raw_payload={},
        )
    )
    db_session.flush()

    rebuild_dual_fee_results(db_session, calculation_run_id="dual-calc-2")

    adjustments = list(
        db_session.scalars(
            select(SettlementFeeAdjustment).where(
                SettlementFeeAdjustment.refund_event_id
                == "refund-order-level-single"
            )
        )
    )
    assert len(adjustments) == 2
    assert {row.coupon_id for row in adjustments} == {"coupon-dual"}


def test_order_level_refund_blocks_ambiguous_multi_coupon_allocation(
    db_session: Session,
) -> None:
    _load_dual_fee_fixture(db_session, amount_cent=10000)
    upsert_order_coupon(
        db_session,
        "coupon-second",
        "order-coupon-dual",
        coupon_status="fulfilled",
        coupon_status_raw="fulfilled",
        coupon_status_normalized="available",
        coupon_paid_amount_cent=4000,
        coupon_refunded_amount_cent=0,
        source_run_id="dual-source",
    )
    rebuild_dual_fee_results(db_session, calculation_run_id="dual-calc-1")
    db_session.add(
        DouyinRefundEvent(
            refund_event_id="refund-order-level-ambiguous",
            order_id="order-coupon-dual",
            coupon_id=None,
            refund_type=1,
            refund_status=2,
            refund_amount_cent=1000,
            occurred_at=_dual_time(10, 2),
            source_run_id="refund-order-level-run",
            raw_payload={},
        )
    )
    db_session.flush()

    rebuild_dual_fee_results(db_session, calculation_run_id="dual-calc-2")

    assert not list(
        db_session.scalars(
            select(SettlementFeeAdjustment).where(
                SettlementFeeAdjustment.refund_event_id
                == "refund-order-level-ambiguous"
            )
        )
    )
    issues = list(
        db_session.scalars(
            select(DataQualityIssue).where(
                DataQualityIssue.issue_type
                == "dual_fee_ambiguous_order_level_refund"
            )
        )
    )
    assert len(issues) == 1


def test_recalculation_after_refund_uses_only_current_result_lineage(
    db_session: Session,
) -> None:
    _load_dual_fee_fixture(db_session, amount_cent=10000)
    rebuild_dual_fee_results(db_session, calculation_run_id="dual-calc-1")
    db_session.add(
        DouyinRefundEvent(
            refund_event_id="refund-before-recalc",
            order_id="order-coupon-dual",
            coupon_id="coupon-dual",
            refund_type=1,
            refund_status=2,
            refund_amount_cent=4001,
            occurred_at=_dual_time(10, 2),
            source_run_id="refund-run",
            raw_payload={},
        )
    )
    db_session.flush()
    rebuild_dual_fee_results(db_session, calculation_run_id="dual-calc-2")
    _add_fee_rule(
        db_session,
        "fee-aug-recalculated",
        date(2026, 8, 5),
        promotion="0.500000",
        management="0.500000",
    )
    db_session.flush()

    rebuild_dual_fee_results(
        db_session,
        calculation_run_id="dual-calc-3",
        force_recalculate=True,
    )
    rebuild_dual_fee_projections(db_session, projection_run_id="projection-recalc")

    current_promotion = _fee_result(db_session, "coupon-dual", 1)
    current_management = _fee_result(db_session, "coupon-dual", 2)
    assert current_promotion is not None
    assert current_management is not None
    assert current_promotion.refunded_amount_cent == 0
    assert current_promotion.fee_amount_cent == 5000
    assert current_management.refunded_amount_cent == 0
    assert current_management.fee_amount_cent == 2000
    august = monthly_projection(db_session, "2026-08", "store-sale", "all")
    september = monthly_projection(db_session, "2026-09", "store-verify", "all")
    october_sale = monthly_projection(db_session, "2026-10", "store-sale", "all")
    october_verify = monthly_projection(db_session, "2026-10", "store-verify", "all")
    assert august is not None
    assert september is not None
    assert august.promotion_original_fee_cent == 5000
    assert august.promotion_adjustment_fee_cent == 0
    assert september.management_original_fee_cent == 2000
    assert september.management_adjustment_fee_cent == 0
    assert october_sale is not None
    assert october_verify is not None
    assert october_sale.promotion_adjustment_fee_cent == -2000
    assert october_verify.management_adjustment_fee_cent == -800
    current_adjustments = list(
        db_session.scalars(
            select(SettlementFeeAdjustment).where(
                SettlementFeeAdjustment.original_fee_result_id.in_(
                    [
                        current_promotion.fee_result_id,
                        current_management.fee_result_id,
                    ]
                )
            )
        )
    )
    assert len(current_adjustments) == 2
    assert {row.adjustment_posting_month for row in current_adjustments} == {
        "2026-10"
    }


def test_refund_snapshot_is_not_adjusted_when_only_metadata_is_resynced(
    db_session: Session,
) -> None:
    _load_dual_fee_fixture(db_session, amount_cent=10000)
    event = DouyinRefundEvent(
        refund_event_id="refund-before-result",
        order_id="order-coupon-dual",
        coupon_id="coupon-dual",
        refund_type=1,
        refund_status=2,
        refund_amount_cent=1000,
        occurred_at=_dual_time(8, 15),
        source_run_id="refund-first-sync",
        raw_payload={"sync": 1},
    )
    db_session.add(event)
    db_session.flush()
    first_success_observed_at = event.successful_observed_at

    rebuild_dual_fee_results(db_session, calculation_run_id="snapshot-calc")
    promotion = _fee_result(db_session, "coupon-dual", 1)
    management = _fee_result(db_session, "coupon-dual", 2)
    assert promotion is not None
    assert management is not None
    assert promotion.refunded_amount_cent == 1000
    assert management.refunded_amount_cent == 1000
    assert not list(db_session.scalars(select(SettlementFeeAdjustment)))

    event.source_run_id = "refund-repeat-sync"
    event.raw_payload = {"sync": 2}
    event.updated_at = _dual_time(12, 20)
    db_session.flush()
    assert event.successful_observed_at == first_success_observed_at

    rebuild_dual_fee_results(db_session, calculation_run_id="snapshot-rerun")

    assert not list(db_session.scalars(select(SettlementFeeAdjustment)))


def test_unlocked_recalculation_versions_result_but_locked_statement_freezes_pointer(
    db_session: Session,
) -> None:
    _load_dual_fee_fixture(db_session)
    rebuild_dual_fee_results(db_session, calculation_run_id="dual-calc-1")
    original = _fee_result(db_session, "coupon-dual", 1)
    assert original is not None
    _add_fee_rule(
        db_session,
        "fee-aug-new",
        date(2026, 8, 5),
        promotion="0.500000",
        management="0.500000",
    )
    db_session.flush()

    rebuild_dual_fee_results(
        db_session, calculation_run_id="dual-calc-2", force_recalculate=True
    )
    recalculated = _fee_result(db_session, "coupon-dual", 1)
    assert recalculated is not None
    assert recalculated.result_version == 2
    assert recalculated.rule_version == "fee-aug-new"
    assert recalculated.fee_result_id != original.fee_result_id
    assert original.result_status == 2

    db_session.add(
        SettlementStatement(
            statement_id="statement-sale-2026-08",
            store_id="store-sale",
            statement_month="2026-08",
            statement_status=4,
            lock_version="lock-sale-2026-08",
            locked_by="test",
            locked_at=_dual_time(10, 1),
        )
    )
    _add_fee_rule(
        db_session,
        "fee-aug-latest",
        date(2026, 8, 8),
        promotion="0.900000",
        management="0.900000",
    )
    db_session.flush()
    rebuild_dual_fee_results(
        db_session, calculation_run_id="dual-calc-3", force_recalculate=True
    )

    frozen = _fee_result(db_session, "coupon-dual", 1)
    assert frozen is not None
    assert frozen.fee_result_id == recalculated.fee_result_id
    promotion_result_count = db_session.scalar(
        select(func.count()).select_from(SettlementFeeResult).where(
            SettlementFeeResult.fee_direction == 1
        )
    )
    assert promotion_result_count == 2
    issue_types = set(db_session.scalars(select(DataQualityIssue.issue_type)))
    assert "dual_fee_locked_recalculation" in issue_types


def test_closed_unpaid_order_is_excluded_from_both_fee_directions(
    db_session: Session,
) -> None:
    _load_dual_fee_fixture(db_session)
    order = db_session.scalar(
        select(RawDouyinOrder).where(
            RawDouyinOrder.order_id == "order-coupon-dual"
        )
    )
    assert order is not None
    order.order_status = "closed"
    order.order_status_normalized = "closed"
    db_session.flush()

    rebuild_dual_fee_results(db_session, calculation_run_id="dual-closed")

    assert _fee_result(db_session, "coupon-dual", 1) is None
    assert _fee_result(db_session, "coupon-dual", 2) is None
    assert count(db_session, SettlementFeeResult) == 0


def test_july_sale_with_august_verification_is_excluded_from_formal_management_fee(
    db_session: Session,
) -> None:
    _load_dual_fee_fixture(db_session)
    order = db_session.scalar(
        select(RawDouyinOrder).where(
            RawDouyinOrder.order_id == "order-coupon-dual"
        )
    )
    verify = db_session.get(RawDouyinVerifyRecord, "verify-coupon-dual")
    assert order is not None
    assert verify is not None
    order.sale_time = _dual_time(7, 31)
    order.pay_time = _dual_time(7, 31)
    verify.verify_time = _dual_time(8, 5)
    db_session.flush()

    rebuild_dual_fee_results(db_session, calculation_run_id="dual-july-sale")

    assert _fee_result(db_session, "coupon-dual", 1) is None
    assert _fee_result(db_session, "coupon-dual", 2) is None


def test_same_store_order_keeps_two_independent_fee_directions(
    db_session: Session,
) -> None:
    _load_dual_fee_fixture(db_session)
    upsert_store_poi_mapping(
        db_session, "store-sale", "poi-sale-same", mapping_source="test"
    )
    verify = db_session.get(RawDouyinVerifyRecord, "verify-coupon-dual")
    assert verify is not None
    verify.poi_id = "poi-sale-same"
    db_session.flush()

    rebuild_dual_fee_results(db_session, calculation_run_id="dual-same-store")

    promotion = _fee_result(db_session, "coupon-dual", 1)
    management = _fee_result(db_session, "coupon-dual", 2)
    assert promotion is not None
    assert management is not None
    assert promotion.sale_store_id == "store-sale"
    assert management.verify_store_id == "store-sale"


@pytest.mark.parametrize(
    ("mutation", "expected_issue"),
    [
        ("unknown_sku", "dual_fee_inactive_or_unknown_sku"),
        ("unknown_channel", "dual_fee_unknown_or_out_of_scope_channel"),
        ("missing_owner", "dual_fee_unstable_owner_account"),
    ],
)
def test_unknown_settlement_dimensions_block_without_guessing(
    db_session: Session,
    mutation: str,
    expected_issue: str,
) -> None:
    _load_dual_fee_fixture(db_session)
    order = db_session.scalar(
        select(RawDouyinOrder).where(
            RawDouyinOrder.order_id == "order-coupon-dual"
        )
    )
    assert order is not None
    if mutation == "unknown_sku":
        order.sku_id = "sku-not-synced"
    elif mutation == "unknown_channel":
        order.sale_channel = "affiliate"
        order.sale_channel_normalized = "other"
    else:
        product = db_session.scalar(
            select(DimSkuProductRule).where(DimSkuProductRule.sku_id == "sku-dual")
        )
        assert product is not None
        product.owner_account_id = None
    db_session.flush()

    rebuild_dual_fee_results(db_session, calculation_run_id=f"dual-{mutation}")

    assert _fee_result(db_session, "coupon-dual", 1) is None
    assert _fee_result(db_session, "coupon-dual", 2) is None
    issue_types = set(db_session.scalars(select(DataQualityIssue.issue_type)))
    assert expected_issue in issue_types


def test_product_owner_scope_is_independent_from_order_sale_attribution(
    db_session: Session,
) -> None:
    _load_dual_fee_fixture(db_session)
    upsert_aweme_account(
        db_session,
        "sale-attribution-account",
        nickname="Sale Attribution",
        store_id="store-sale",
        binding_status="active",
    )
    order = db_session.scalar(
        select(RawDouyinOrder).where(
            RawDouyinOrder.order_id == "order-coupon-dual"
        )
    )
    assert order is not None
    order.owner_account_id = "sale-attribution-account"
    db_session.flush()

    rebuild_dual_fee_results(db_session, calculation_run_id="dual-owner-boundary")

    promotion = _fee_result(db_session, "coupon-dual", 1)
    management = _fee_result(db_session, "coupon-dual", 2)
    assert promotion is not None
    assert management is not None
    assert promotion.sale_store_id == "store-sale"
    assert promotion.scope_rule_version == "scope-2026-08-short_video"


def test_statement_lock_freezes_result_entry_line_and_head_idempotently(
    db_session: Session,
) -> None:
    _load_dual_fee_fixture(db_session, amount_cent=10000)
    rebuild_dual_fee_results(db_session, calculation_run_id="statement-calc")

    first = lock_settlement_statement(
        db_session,
        store_id="store-sale",
        statement_month="2026-08",
        lock_run_id="statement-lock-1",
    )
    second = lock_settlement_statement(
        db_session,
        store_id="store-sale",
        statement_month="2026-08",
        lock_run_id="statement-lock-2",
    )

    assert second.statement_id == first.statement_id
    assert first.statement_status == 4
    assert first.lock_version is not None
    assert first.promotion_original_fee_cent == 123
    assert first.promotion_adjustment_fee_cent == 0
    assert first.promotion_net_fee_cent == 123
    assert first.management_net_fee_cent == 0
    lines = list(
        db_session.scalars(
            select(SettlementStatementLine).where(
                SettlementStatementLine.statement_id == first.statement_id
            )
        )
    )
    entries = list(
        db_session.scalars(
            select(SettlementStatementEntry).where(
                SettlementStatementEntry.statement_id == first.statement_id
            )
        )
    )
    assert len(lines) == 1
    assert len(entries) == 1
    assert lines[0].fee_direction == 1
    assert lines[0].original_entry_count == 1
    assert lines[0].original_base_cent == 10000
    assert lines[0].adjustment_entry_count == 0
    assert lines[0].net_base_cent == 10000
    assert lines[0].net_fee_cent == 123
    assert entries[0].source_type == 1
    assert entries[0].source_record_id == _fee_result(
        db_session, "coupon-dual", 1
    ).fee_result_id
    assert count(db_session, SettlementStatement) == 1
    assert count(db_session, SettlementStatementLine) == 1
    assert count(db_session, SettlementStatementEntry) == 1

    upsert_store(db_session, "store-sale-moved", "Moved Sale Store")
    sale_account = db_session.get(DimAwemeAccount, "owner-dual")
    assert sale_account is not None
    sale_account.store_id = "store-sale-moved"
    _add_fee_rule(
        db_session,
        "fee-aug-after-lock",
        date(2026, 8, 5),
        promotion="0.900000",
        management="0.900000",
    )
    db_session.flush()
    rebuild_dual_fee_results(
        db_session,
        calculation_run_id="statement-recalc-after-store-move",
        force_recalculate=True,
    )
    frozen = _fee_result(db_session, "coupon-dual", 1)
    assert frozen is not None
    assert frozen.fee_result_id == entries[0].source_record_id


def test_recalculation_and_statement_lock_share_store_month_slot_lock(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _load_dual_fee_fixture(db_session, amount_cent=10000)
    acquired: list[tuple[str, str]] = []
    original_lock = settlement_worker._lock_settlement_slot

    def record_lock(session: Session, store_id: str, statement_month: str) -> None:
        acquired.append((store_id, statement_month))
        original_lock(session, store_id, statement_month)

    monkeypatch.setattr(settlement_worker, "_lock_settlement_slot", record_lock)
    rebuild_dual_fee_results(db_session, calculation_run_id="shared-lock-calc")
    lock_settlement_statement(
        db_session,
        store_id="store-sale",
        statement_month="2026-08",
        lock_run_id="shared-lock-statement",
    )

    assert acquired.count(("store-sale", "2026-08")) >= 2


def test_locked_month_blocks_first_result_for_late_coupon(
    db_session: Session,
) -> None:
    _load_dual_fee_fixture(db_session, amount_cent=10000)
    lock_settlement_statement(
        db_session,
        store_id="store-sale",
        statement_month="2026-08",
        lock_run_id="lock-empty-august",
    )

    rebuild_dual_fee_results(db_session, calculation_run_id="late-coupon-calc")

    assert _fee_result(db_session, "coupon-dual", 1) is None
    assert _fee_result(db_session, "coupon-dual", 2) is not None
    issue_types = set(db_session.scalars(select(DataQualityIssue.issue_type)))
    assert "dual_fee_locked_slot_materialization" in issue_types


def test_locked_event_month_blocks_unbillable_refund_adjustments(
    db_session: Session,
) -> None:
    _load_dual_fee_fixture(db_session, amount_cent=10000)
    rebuild_dual_fee_results(db_session, calculation_run_id="locked-event-calc")
    for store_id in ("store-sale", "store-verify"):
        lock_settlement_statement(
            db_session,
            store_id=store_id,
            statement_month="2026-10",
            lock_run_id=f"lock-empty-october-{store_id}",
        )
    db_session.add(
        DouyinRefundEvent(
            refund_event_id="refund-after-event-month-lock",
            order_id="order-coupon-dual",
            coupon_id="coupon-dual",
            refund_type=1,
            refund_status=2,
            refund_amount_cent=1000,
            occurred_at=_dual_time(10, 20),
            source_run_id="late-refund-run",
            raw_payload={},
        )
    )
    db_session.flush()

    rebuild_dual_fee_results(db_session, calculation_run_id="late-refund-calc")

    assert not list(db_session.scalars(select(SettlementFeeAdjustment)))
    blocked_issues = list(
        db_session.scalars(
            select(DataQualityIssue).where(
                DataQualityIssue.issue_type
                == "dual_fee_locked_adjustment_posting_month"
            )
        )
    )
    assert len(blocked_issues) == 2


def test_locked_event_month_blocks_unbillable_cancellation_adjustment(
    db_session: Session,
) -> None:
    _load_dual_fee_fixture(db_session, amount_cent=10000)
    rebuild_dual_fee_results(db_session, calculation_run_id="locked-cancel-calc")
    lock_settlement_statement(
        db_session,
        store_id="store-verify",
        statement_month="2026-10",
        lock_run_id="lock-empty-october-cancel",
    )
    verify = db_session.get(RawDouyinVerifyRecord, "verify-coupon-dual")
    assert verify is not None
    verify.verify_status = "cancelled"
    verify.cancel_time = _dual_time(10, 20)
    db_session.flush()

    rebuild_dual_fee_results(db_session, calculation_run_id="late-cancel-calc")

    assert not list(db_session.scalars(select(SettlementFeeAdjustment)))
    issue = db_session.scalar(
        select(DataQualityIssue).where(
            DataQualityIssue.issue_type
            == "dual_fee_locked_adjustment_posting_month",
            DataQualityIssue.source_run_id == "late-cancel-calc",
        )
    )
    assert issue is not None
    assert issue.raw_context_json["verify_id"] == "verify-coupon-dual"


def test_post_lock_refund_enters_event_month_without_changing_original_statements(
    db_session: Session,
) -> None:
    _load_dual_fee_fixture(db_session, amount_cent=10000)
    rebuild_dual_fee_results(db_session, calculation_run_id="statement-calc")
    promotion_statement = lock_settlement_statement(
        db_session,
        store_id="store-sale",
        statement_month="2026-08",
        lock_run_id="lock-promotion",
    )
    management_statement = lock_settlement_statement(
        db_session,
        store_id="store-verify",
        statement_month="2026-09",
        lock_run_id="lock-management",
    )
    db_session.add(
        DouyinRefundEvent(
            refund_event_id="refund-after-lock",
            order_id="order-coupon-dual",
            coupon_id="coupon-dual",
            refund_type=1,
            refund_status=2,
            refund_amount_cent=4001,
            occurred_at=_dual_time(10, 12),
            source_run_id="refund-run",
            raw_payload={},
        )
    )
    db_session.flush()
    rebuild_dual_fee_results(db_session, calculation_run_id="refund-after-lock-run")

    promotion_adjustment_statement = lock_settlement_statement(
        db_session,
        store_id="store-sale",
        statement_month="2026-10",
        lock_run_id="lock-promotion-adjustment",
    )
    management_adjustment_statement = lock_settlement_statement(
        db_session,
        store_id="store-verify",
        statement_month="2026-10",
        lock_run_id="lock-management-adjustment",
    )

    assert promotion_statement.promotion_net_fee_cent == 123
    assert management_statement.management_net_fee_cent == 2000
    assert promotion_adjustment_statement.promotion_original_fee_cent == 0
    assert promotion_adjustment_statement.promotion_adjustment_fee_cent == -49
    assert promotion_adjustment_statement.promotion_net_fee_cent == -49
    assert management_adjustment_statement.management_original_fee_cent == 0
    assert management_adjustment_statement.management_adjustment_fee_cent == -800
    assert management_adjustment_statement.management_net_fee_cent == -800
    adjustment_entries = list(
        db_session.scalars(
            select(SettlementStatementEntry).where(
                SettlementStatementEntry.source_type == 2
            )
        )
    )
    assert len(adjustment_entries) == 2
    assert {entry.statement_posting_month for entry in adjustment_entries} == {
        "2026-10"
    }


def test_monthly_and_cumulative_projections_use_locked_sources_and_exclude_july(
    db_session: Session,
) -> None:
    _load_dual_fee_fixture(db_session, amount_cent=10000)
    rebuild_dual_fee_results(db_session, calculation_run_id="projection-calc")
    lock_settlement_statement(
        db_session,
        store_id="store-sale",
        statement_month="2026-08",
        lock_run_id="projection-lock-promotion",
    )
    lock_settlement_statement(
        db_session,
        store_id="store-verify",
        statement_month="2026-09",
        lock_run_id="projection-lock-management",
    )
    db_session.add(
        DouyinRefundEvent(
            refund_event_id="refund-projection",
            order_id="order-coupon-dual",
            coupon_id="coupon-dual",
            refund_type=1,
            refund_status=2,
            refund_amount_cent=4001,
            occurred_at=_dual_time(10, 15),
            source_run_id="refund-run",
            raw_payload={},
        )
    )
    db_session.flush()
    rebuild_dual_fee_results(db_session, calculation_run_id="projection-refund")
    lock_settlement_statement(
        db_session,
        store_id="store-sale",
        statement_month="2026-10",
        lock_run_id="projection-lock-promotion-adjustment",
    )
    lock_settlement_statement(
        db_session,
        store_id="store-verify",
        statement_month="2026-10",
        lock_run_id="projection-lock-management-adjustment",
    )
    db_session.add(
        AggStoreMonthlySettlement(
            month="2026-07",
            store_id="store-sale",
            product_scope="all",
            product_type="all",
            sales_order_count=99,
            sales_amount_cent=999999,
            promotion_net_fee_cent=99999,
            projection_run_id="legacy-july",
        )
    )
    db_session.flush()

    first = rebuild_dual_fee_projections(
        db_session, projection_run_id="projection-1", batch_size=1
    )
    first_monthly_count = count(db_session, AggStoreMonthlySettlement)
    first_ranking_count = count(db_session, AggStoreRanking)
    second = rebuild_dual_fee_projections(
        db_session, projection_run_id="projection-2", batch_size=1
    )

    august_sale = monthly_projection(db_session, "2026-08", "store-sale", "all")
    september_verify = monthly_projection(
        db_session, "2026-09", "store-verify", "all"
    )
    october_sale = monthly_projection(db_session, "2026-10", "store-sale", "all")
    october_verify = monthly_projection(
        db_session, "2026-10", "store-verify", "all"
    )
    assert august_sale is not None
    assert august_sale.sales_order_count == 1
    assert august_sale.sales_amount_cent == 10000
    assert august_sale.promotion_base_cent == 10000
    assert august_sale.promotion_original_fee_cent == 123
    assert august_sale.promotion_net_fee_cent == 123
    assert august_sale.statement_status == 4
    assert september_verify is not None
    assert september_verify.verified_order_count == 1
    assert september_verify.verified_amount_cent == 10000
    assert september_verify.management_original_fee_cent == 2000
    assert september_verify.management_net_fee_cent == 2000
    assert october_sale is not None
    assert october_sale.promotion_base_cent == -4001
    assert october_sale.promotion_adjustment_fee_cent == -49
    assert october_sale.promotion_net_fee_cent == -49
    assert october_verify is not None
    assert october_verify.management_base_cent == -4001
    assert october_verify.management_adjustment_fee_cent == -800
    assert october_verify.management_net_fee_cent == -800

    cumulative_sale = db_session.scalar(
        select(AggStoreRanking).where(
            AggStoreRanking.period_type == 2,
            AggStoreRanking.period_key == "2026-10",
            AggStoreRanking.store_id == "store-sale",
            AggStoreRanking.product_scope == "all",
            AggStoreRanking.product_type == "all",
        )
    )
    cumulative_verify = db_session.scalar(
        select(AggStoreRanking).where(
            AggStoreRanking.period_type == 2,
            AggStoreRanking.period_key == "2026-10",
            AggStoreRanking.store_id == "store-verify",
            AggStoreRanking.product_scope == "all",
            AggStoreRanking.product_type == "all",
        )
    )
    assert cumulative_sale is not None
    assert cumulative_sale.sales_order_count == 1
    assert cumulative_sale.sales_amount_cent == 10000
    assert cumulative_sale.promotion_net_fee_cent == 74
    assert cumulative_sale.net_settlement_reference_cent == 74
    assert cumulative_verify is not None
    assert cumulative_verify.verified_order_count == 1
    assert cumulative_verify.verified_amount_cent == 10000
    assert cumulative_verify.management_net_fee_cent == 1200
    assert cumulative_verify.net_settlement_reference_cent == -1200
    assert first.monthly_count == second.monthly_count
    assert first.ranking_count == second.ranking_count
    assert first.processed_count > 0
    assert first.skipped_count > 0
    assert first.failed_count == 0
    assert second.processed_count == first.processed_count
    assert second.skipped_count == first.skipped_count
    assert second.failed_count == 0
    assert count(db_session, AggStoreMonthlySettlement) == first_monthly_count
    assert count(db_session, AggStoreRanking) == first_ranking_count
    july = monthly_projection(db_session, "2026-07", "store-sale", "all")
    assert july is not None
    assert july.sales_order_count == 99


def test_projection_rebuild_failure_rolls_back_without_half_updated_rows(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _load_dual_fee_fixture(db_session, amount_cent=10000)
    rebuild_dual_fee_results(db_session, calculation_run_id="rollback-calc")
    rebuild_dual_fee_projections(db_session, projection_run_id="projection-good")
    before = monthly_projection(db_session, "2026-08", "store-sale", "all")
    assert before is not None
    before_values = (
        before.sales_order_count,
        before.sales_amount_cent,
        before.promotion_net_fee_cent,
        before.projection_run_id,
    )

    def fail_ranking(*_args, **_kwargs):
        raise RuntimeError("injected projection failure")

    monkeypatch.setattr(settlement_worker, "_add_target_ranking_row", fail_ranking)
    with pytest.raises(RuntimeError, match="injected projection failure"):
        rebuild_dual_fee_projections(db_session, projection_run_id="projection-bad")

    after = monthly_projection(db_session, "2026-08", "store-sale", "all")
    assert after is not None
    assert (
        after.sales_order_count,
        after.sales_amount_cent,
        after.promotion_net_fee_cent,
        after.projection_run_id,
    ) == before_values
    issue_types = set(db_session.scalars(select(DataQualityIssue.issue_type)))
    assert "dual_fee_projection_rebuild_failed" in issue_types


def test_projection_failure_audit_survives_session_scope_rollback(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'projection-audit.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        future=True,
    )
    with session_scope(factory) as session:
        _load_dual_fee_fixture(session, amount_cent=10000)
        rebuild_dual_fee_results(session, calculation_run_id="audit-calc")

    def fail_projection_dimensions(*_args):
        raise RuntimeError("audit rollback injection")

    monkeypatch.setattr(
        settlement_worker, "_projection_dimensions", fail_projection_dimensions
    )
    with pytest.raises(RuntimeError, match="audit rollback injection"):
        with session_scope(factory) as session:
            rebuild_dual_fee_projections(
                session, projection_run_id="projection-audit-failed"
            )

    with factory() as session:
        issue = session.scalar(
            select(DataQualityIssue).where(
                DataQualityIssue.issue_type == "dual_fee_projection_rebuild_failed",
                DataQualityIssue.source_run_id == "projection-audit-failed",
            )
        )
        assert issue is not None
        assert issue.raw_context_json["failed"] == 1
