from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    AggStoreMonthlySettlement,
    AggStoreRanking,
    DataQualityIssue,
    JobRun,
    RawDouyinOrder,
    RawDouyinOrderCoupon,
    RawDouyinVerifyRecord,
    SettlementOrderDetail,
)
from apps.worker.repositories import (
    upsert_aweme_account,
    upsert_order_coupon,
    upsert_raw_order,
    upsert_sku_product_rule,
    upsert_store,
    upsert_store_poi_mapping,
    upsert_verify_record,
)
from apps.worker.settlement import run_settlement_job


RUN_ID = "fixture-run"
SETTLEMENT_RUN_ID = "settlement-fixture"


def dt(day: int) -> datetime:
    return datetime(2026, 1, day, 10, 0, tzinfo=timezone.utc)


def count(session: Session, model: type) -> int:
    value = session.scalar(select(func.count()).select_from(model))
    assert value is not None
    return value


def load_fixture(session: Session) -> None:
    upsert_store(session, "store-s1", "Store S1")
    upsert_store(session, "store-s2", "Store S2")
    upsert_store_poi_mapping(session, "store-s1", "poi-s1", poi_name="POI S1", mapping_source="fixture")
    upsert_store_poi_mapping(session, "store-s2", "poi-s2", poi_name="POI S2", mapping_source="fixture")
    upsert_aweme_account(session, "owner-s1", nickname="Owner S1", store_id="store-s1", binding_status="active")
    upsert_aweme_account(session, "owner-s2", nickname="Fallback S2", store_id="store-s2", binding_status="active")
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

    refunded = db_session.get(SettlementOrderDetail, "coupon-refund")
    assert refunded is not None
    assert refunded.is_refund_excluded is True
    assert refunded.is_commissionable is False
    assert refunded.receivable_commission_cent == 0

    conflict = db_session.get(SettlementOrderDetail, "coupon-conflict")
    assert conflict is not None
    assert conflict.sale_store_id == "store-s2"
    assert conflict.relation_type == "same_store"

    issue_types = set(db_session.scalars(select(DataQualityIssue.issue_type)))
    assert {"unmatched_owner", "unmatched_sku", "unmatched_poi"}.issubset(issue_types)

    monthly_s1 = db_session.get(AggStoreMonthlySettlement, ("2026-01", "store-s1", "all"))
    monthly_s2 = db_session.get(AggStoreMonthlySettlement, ("2026-01", "store-s2", "all"))
    assert monthly_s1 is not None
    assert monthly_s2 is not None
    assert monthly_s1.estimated_receivable_commission_cent == 1000
    assert monthly_s1.commissionable_total_cent == 10000
    assert monthly_s2.estimated_payable_commission_cent == 1000

    ranking_s1 = db_session.get(AggStoreRanking, ("2026-01", "all", "store-s1"))
    assert ranking_s1 is not None
    assert ranking_s1.sales_order_count == 3
    assert ranking_s1.self_sold_other_verified_count == 2
    assert ranking_s1.effective_commission_income_cent == 1000


def test_numeric_verify_statuses_are_classified_before_settlement(db_session: Session) -> None:
    upsert_store(db_session, "store-s1", "Store S1")
    upsert_store(db_session, "store-s2", "Store S2")
    upsert_store_poi_mapping(db_session, "store-s2", "poi-s2", poi_name="POI S2", mapping_source="fixture")
    upsert_aweme_account(db_session, "owner-s1", nickname="Owner S1", store_id="store-s1", binding_status="active")
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
