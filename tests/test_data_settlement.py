from __future__ import annotations

import json
import runpy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine, event, func, inspect, select, text
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api import models as dy_models
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
    StoreFinanceProfile,
)
from apps.api.dy_api.rule_utils import normalize_owner_account_name
import apps.worker.settlement as settlement_worker
import apps.worker.billing_source_capture as billing_capture
import apps.worker.historical_sale_attribution as sale_history
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
            raw_payload={"receipt_amount": amount_cent},
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
    assert count(db_session, JobRun) == 2
    publication = db_session.get(
        JobRun, "settlement-publication-after-job-settlement-fixture"
    )
    assert publication is not None
    assert publication.status == "queued"
    assert publication.metadata_json["source_run_id"] == SETTLEMENT_RUN_ID
    assert publication.metadata_json["trigger_source"] == "settlement_job_completed"


def test_failed_settlement_job_does_not_queue_publication(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_rebuild(*_args, **_kwargs):
        raise RuntimeError("settlement rebuild failed")

    monkeypatch.setattr(settlement_worker, "rebuild_settlement", fail_rebuild)

    with pytest.raises(RuntimeError, match="settlement rebuild failed"):
        run_settlement_job(
            db_session,
            job_id="failed-settlement-job",
            source_run_id="failed-settlement-job",
        )

    publication = db_session.get(
        JobRun,
        "settlement-publication-after-failed-settlement-job",
    )
    failed_job = db_session.get(JobRun, "failed-settlement-job")
    assert publication is None
    assert failed_job is not None
    assert failed_job.status == "failed"


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
    status: int = 1,
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
            rule_status=status,
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
        raw_payload={"receipt_amount": amount_cent},
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


@pytest.mark.parametrize("verify_status", [None, "unknown", "pending", "cancelled"])
def test_both_fee_directions_require_effective_redemption(
    db_session: Session, verify_status: str | None,
) -> None:
    _load_dual_fee_fixture(db_session, with_verify=verify_status is not None)
    if verify_status is not None:
        verify = db_session.scalar(select(RawDouyinVerifyRecord))
        assert verify is not None
        verify.verify_status = verify_status
        db_session.flush()

    rebuild_dual_fee_results(db_session, calculation_run_id="effective-verify-gate")

    assert _fee_result(db_session, "coupon-dual", 1) is None
    assert _fee_result(db_session, "coupon-dual", 2) is None


def test_cancel_timestamp_overrides_valid_redemption_status(db_session: Session) -> None:
    _load_dual_fee_fixture(db_session)
    verify = db_session.scalar(select(RawDouyinVerifyRecord))
    assert verify is not None
    verify.cancel_time = _dual_time(9, 8)
    db_session.flush()

    rebuild_dual_fee_results(db_session, calculation_run_id="cancelled-valid-status")

    assert _fee_result(db_session, "coupon-dual", 1) is None
    assert _fee_result(db_session, "coupon-dual", 2) is None


def test_fee_result_persists_qualifying_verification_identity(db_session: Session) -> None:
    _load_dual_fee_fixture(db_session)
    rebuild_dual_fee_results(db_session, calculation_run_id="verify-provenance")
    for direction in (1, 2):
        result = _fee_result(db_session, "coupon-dual", direction)
        assert result is not None
        assert getattr(result, "qualifying_verify_id", None) == "verify-coupon-dual"


def test_historical_statement_source_keeps_its_qualifying_verification(db_session: Session) -> None:
    _load_dual_fee_fixture(db_session)
    rebuild_dual_fee_results(db_session, calculation_run_id="source-before-reverify")
    original = _fee_result(db_session, "coupon-dual", 1)
    verify = db_session.scalar(select(RawDouyinVerifyRecord))
    assert original is not None and verify is not None
    verify.verify_status = "cancelled"
    verify.cancel_time = _dual_time(10, 8)
    upsert_verify_record(
        db_session, "verify-new-source", coupon_id="coupon-dual", verify_status="valid",
        verify_time=_dual_time(10, 10), poi_id="poi-verify", sku_id="sku-dual",
        paid_amount_cent=10001, source_run_id="reverify-source",
    )
    db_session.flush()

    snapshot = settlement_worker._statement_source_snapshots(db_session, result=original)

    assert settlement_worker._as_utc(snapshot["verify_time"]) == _dual_time(9, 5)


def test_recalculation_retires_unverified_unlocked_current_results(db_session: Session) -> None:
    _load_dual_fee_fixture(db_session)
    rebuild_dual_fee_results(db_session, calculation_run_id="before-invalid-verify")
    originals = [_fee_result(db_session, "coupon-dual", direction) for direction in (1, 2)]
    verify = db_session.scalar(select(RawDouyinVerifyRecord))
    assert verify is not None
    verify.verify_status = "unknown"
    db_session.flush()

    rebuild_dual_fee_results(db_session, calculation_run_id="repair-invalid-verify", force_recalculate=True)
    rebuild_dual_fee_results(db_session, calculation_run_id="repair-invalid-verify", force_recalculate=True)

    assert _fee_result(db_session, "coupon-dual", 1) is None
    assert _fee_result(db_session, "coupon-dual", 2) is None
    assert all(original is not None and original.result_status == 2 for original in originals)
    assert count(db_session, SettlementFeeResult) == 2


@pytest.mark.parametrize("ineligible", ["product", "channel", "owner", "scope", "closed"])
def test_current_results_exit_when_eligibility_is_revoked(db_session: Session, ineligible: str) -> None:
    _load_dual_fee_fixture(db_session)
    rebuild_dual_fee_results(db_session, calculation_run_id="before-eligibility-revoked")
    order = db_session.scalar(select(RawDouyinOrder))
    assert order is not None
    if ineligible == "product":
        product = db_session.scalar(select(DimSkuProductRule))
        assert product is not None
        product.is_active_product = False
    elif ineligible == "channel":
        order.sale_channel_normalized = "unknown"
    elif ineligible == "owner":
        db_session.add(DimNonCommissionOwnerAccount(
            owner_account_name="Owner Dual",
            normalized_owner_account_name=normalize_owner_account_name("Owner Dual"),
            is_active=True,
        ))
    elif ineligible == "scope":
        for scope in db_session.scalars(select(SettlementScopeRule)):
            scope.is_active = False
    else:
        order.order_status_normalized = "closed"
    db_session.flush()

    rebuild_dual_fee_results(db_session, calculation_run_id="eligibility-revoked")

    assert _fee_result(db_session, "coupon-dual", 1) is None
    assert _fee_result(db_session, "coupon-dual", 2) is None
    assert count(db_session, SettlementFeeResult) == 2


def test_cancellation_zeros_both_fees_once(db_session: Session) -> None:
    _load_dual_fee_fixture(db_session, amount_cent=10000)
    rebuild_dual_fee_results(db_session, calculation_run_id="before-dual-cancel")
    originals = [_fee_result(db_session, "coupon-dual", direction) for direction in (1, 2)]
    verify = db_session.scalar(select(RawDouyinVerifyRecord))
    assert verify is not None
    verify.verify_status = "cancelled"
    verify.cancel_time = _dual_time(10, 8)
    db_session.flush()

    rebuild_dual_fee_results(db_session, calculation_run_id="dual-cancel")
    rebuild_dual_fee_results(db_session, calculation_run_id="dual-cancel-repeat")

    adjustments = list(db_session.scalars(select(SettlementFeeAdjustment)))
    assert len(adjustments) == 2
    for original in originals:
        assert original is not None
        assert sum(row.adjustment_fee_cent for row in adjustments if row.original_fee_result_id == original.fee_result_id) == -original.fee_amount_cent
    assert {row.adjustment_posting_month for row in adjustments} == {"2026-10"}


def test_refund_after_pending_cancellation_does_not_double_reduce(db_session: Session) -> None:
    _load_dual_fee_fixture(db_session, amount_cent=10000)
    rebuild_dual_fee_results(db_session, calculation_run_id="before-pending-cancel")
    originals = [_fee_result(db_session, "coupon-dual", direction) for direction in (1, 2)]
    for store_id in ("store-sale", "store-verify"):
        lock_settlement_statement(db_session, store_id=store_id, statement_month="2026-10", lock_run_id=f"lock-{store_id}")
    verify = db_session.scalar(select(RawDouyinVerifyRecord))
    assert verify is not None
    verify.verify_status = "cancelled"
    verify.cancel_time = _dual_time(10, 8)
    db_session.flush()
    rebuild_dual_fee_results(db_session, calculation_run_id="pending-cancel")
    db_session.add(DouyinRefundEvent(
        refund_event_id="refund-after-cancel", order_id="order-coupon-dual", coupon_id="coupon-dual",
        refund_type=1, refund_status=2, refund_amount_cent=1000,
        occurred_at=_dual_time(10, 9), source_run_id="refund-after-cancel", raw_payload={},
    ))
    db_session.flush()

    rebuild_dual_fee_results(db_session, calculation_run_id="refund-after-pending-cancel")

    for original in originals:
        assert original is not None
        _, adjustment_fee = settlement_worker._effective_adjustment_totals(db_session, original_fee_result_id=original.fee_result_id)
        assert original.fee_amount_cent + adjustment_fee == 0


@pytest.mark.parametrize("reuse_verify_id", [False, True])
def test_reverification_is_not_zeroed_by_previous_cancellation(db_session: Session, reuse_verify_id: bool) -> None:
    _load_dual_fee_fixture(db_session, amount_cent=10000)
    rebuild_dual_fee_results(db_session, calculation_run_id="before-reverify")
    verify = db_session.scalar(select(RawDouyinVerifyRecord))
    assert verify is not None
    verify.verify_status = "cancelled"
    verify.cancel_time = _dual_time(10, 8)
    db_session.flush()
    rebuild_dual_fee_results(db_session, calculation_run_id="old-cancel")
    _add_scope_rule(db_session, "2026-10")
    upsert_verify_record(
        db_session, "verify-coupon-dual" if reuse_verify_id else "verify-again", coupon_id="coupon-dual", verify_status="valid",
        verify_time=_dual_time(10, 10), poi_id="poi-verify", sku_id="sku-dual",
        paid_amount_cent=10000, source_run_id="reverify-source",
    )
    if reuse_verify_id:
        verify.verify_status = "valid"
        verify.verify_time = _dual_time(10, 10)
        verify.cancel_time = None
    db_session.flush()
    rebuild_dual_fee_results(db_session, calculation_run_id="after-reverify")
    rebuild_dual_fee_results(db_session, calculation_run_id="after-reverify-repeat")

    for direction in (1, 2):
        current = _fee_result(db_session, "coupon-dual", direction)
        assert current is not None
        adjustments = list(db_session.scalars(select(SettlementFeeAdjustment).where(
            SettlementFeeAdjustment.original_fee_result_id == current.fee_result_id,
        )))
        assert current.fee_amount_cent > 0
        assert sum(row.adjustment_fee_cent for row in adjustments) == 0

    # V1's immutable cancellation rows still exist. They must not reduce V2
    # after the unlocked pointer has moved, in either aggregation path.
    assert count(db_session, SettlementFeeAdjustment) == 2
    rebuild_dual_fee_projections(db_session, projection_run_id="unlocked-reverify-projection")
    for month, store_id, prefix, expected in (
        ("2026-08", "store-sale", "promotion", 0),
        ("2026-09", "store-sale", "promotion", 0),
        ("2026-09", "store-verify", "management", 0),
        ("2026-10", "store-sale", "promotion", 3000),
        ("2026-10", "store-verify", "management", 2000),
    ):
        ordinary = monthly_projection(db_session, month, store_id, "all")
        ordinary_amount = getattr(ordinary, f"{prefix}_net_fee_cent") if ordinary else 0
        assert ordinary_amount == expected
        sparse_rows = db_session.execute(settlement_worker._sparse_monthly_query(month)).mappings().all()
        sparse_amount = sum(
            row[f"{prefix}_original_fee_cent"] + row[f"{prefix}_adjustment_fee_cent"]
            for row in sparse_rows
            if row["store_id"] == store_id and row["product_scope"] == row["product_type"] == "all"
        )
        assert sparse_amount == ordinary_amount
        captured = billing_capture.collect_billing_sources(db_session, months=[month])
        assert sum(source.fee_amount_cent for source in captured if source.store_id == store_id) == expected


def test_old_cancellation_does_not_keep_invalid_reverification_current(db_session: Session) -> None:
    _load_dual_fee_fixture(db_session)
    rebuild_dual_fee_results(db_session, calculation_run_id="exit-base")
    old = db_session.get(RawDouyinVerifyRecord, "verify-coupon-dual")
    old.verify_status = "cancelled"
    old.cancel_time = _dual_time(10, 8)
    db_session.flush()
    rebuild_dual_fee_results(db_session, calculation_run_id="exit-cancel")
    _add_scope_rule(db_session, "2026-10")
    upsert_verify_record(
        db_session, "exit-new", coupon_id="coupon-dual", verify_status="valid",
        verify_time=_dual_time(10, 10), poi_id="poi-verify", sku_id="sku-dual",
        paid_amount_cent=10001, source_run_id="exit-new",
    )
    db_session.flush()
    rebuild_dual_fee_results(db_session, calculation_run_id="exit-reverify")
    db_session.get(RawDouyinVerifyRecord, "exit-new").verify_status = "unknown"
    db_session.flush()
    for _ in range(2):
        rebuild_dual_fee_results(db_session, calculation_run_id="exit-invalid", force_recalculate=True)
    assert all(_fee_result(db_session, "coupon-dual", direction) is None for direction in (1, 2))


def test_reused_verification_keeps_historical_store_snapshot(db_session: Session) -> None:
    _load_dual_fee_fixture(db_session)
    rebuild_dual_fee_results(db_session, calculation_run_id="snapshot-original")
    originals = [_fee_result(db_session, "coupon-dual", direction) for direction in (1, 2)]
    upsert_store(db_session, "store-reverified", "Reverified Store")
    upsert_store_poi_mapping(db_session, "store-reverified", "poi-reverified", mapping_source="test")
    verify = db_session.get(RawDouyinVerifyRecord, "verify-coupon-dual")
    verify.verify_time = _dual_time(10, 10)
    verify.poi_id = "poi-reverified"
    db_session.flush()
    for original in originals:
        snapshot = settlement_worker._statement_source_snapshots(db_session, result=original)
        assert snapshot["verify_store_id"] == "store-verify"
        assert settlement_worker._as_utc(snapshot["verify_time"]) == _dual_time(9, 5)


@pytest.mark.parametrize("populated_column", [
    None, "qualifying_verify_store_id", "qualifying_verify_store_name", "reverification_anchor_id",
])
def test_reverification_migration_preserves_populated_provenance(populated_column: str | None) -> None:
    migration_path = Path(__file__).resolve().parents[1] / "alembic/versions/20260909_0051_fee_result_verification_provenance.py"
    migration = runpy.run_path(str(migration_path))
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE settlement_fee_result (id INTEGER PRIMARY KEY, result_version INTEGER DEFAULT 1)"))
        migration["upgrade"].__globals__["op"] = Operations(MigrationContext.configure(connection))
        migration["upgrade"]()
        new_columns = {"qualifying_verify_store_id", "qualifying_verify_store_name", "reverification_anchor_id"}
        columns = {column["name"]: column for column in inspect(connection).get_columns("settlement_fee_result")}
        assert all(columns[name]["nullable"] for name in new_columns)
        assert "idx_settlement_fee_result_reverification_anchor" in {
            index["name"] for index in inspect(connection).get_indexes("settlement_fee_result")
        }
        if populated_column:
            # The column is a fixed test enum, never external SQL input.
            connection.execute(text(f"INSERT INTO settlement_fee_result (id, {populated_column}) VALUES (1, 'preserved')"))
            with pytest.raises(RuntimeError, match="provenance is populated"):
                migration["downgrade"]()
            assert connection.execute(text(f"SELECT {populated_column} FROM settlement_fee_result")).scalar_one() == "preserved"
        else:
            migration["downgrade"]()
            assert not new_columns.intersection(column["name"] for column in inspect(connection).get_columns("settlement_fee_result"))
    engine.dispose()


def _assert_reverification_projection_sources(
    session: Session, *, month: str, expected: dict[str, int], expected_adjustment_ids: set[str],
) -> None:
    """Exercise SQL aggregation, durable billing capture and ordinary projection."""
    captured = billing_capture.collect_billing_sources(session, months=[month])
    assert expected_adjustment_ids.issubset({source.source_record_id for source in captured})
    capture_job = f"projection-proof-{month}"
    session.add(JobRun(job_id=capture_job, job_name="settlement_rebuild", status="running"))
    session.flush()
    billing_capture.freeze_billing_sources(session, generation_id=capture_job, job_id=capture_job, sources=captured)
    restored = billing_capture.load_billing_sources(session, generation_id=capture_job, job_id=capture_job)
    assert {source.source_record_id for source in restored} == {source.source_record_id for source in captured}
    sparse_rows = session.execute(settlement_worker._sparse_monthly_query(month)).mappings().all()
    for store_id, amount in expected.items():
        prefix = "promotion" if store_id == "store-sale" else "management"
        sparse = next(row for row in sparse_rows if row["store_id"] == store_id and row["product_scope"] == row["product_type"] == "all")
        assert sparse[f"{prefix}_original_fee_cent"] + sparse[f"{prefix}_adjustment_fee_cent"] == amount
        assert sum(source.fee_amount_cent for source in restored if source.store_id == store_id) == amount
    rebuild_dual_fee_projections(session, projection_run_id=capture_job)
    for store_id, amount in expected.items():
        row = monthly_projection(session, month, store_id, "all")
        assert row is not None
        prefix = "promotion" if store_id == "store-sale" else "management"
        assert getattr(row, f"{prefix}_net_fee_cent") == amount


@pytest.mark.parametrize("reuse_verify_id", [False, True])
@pytest.mark.parametrize("locked_event_month", [False, True])
def test_locked_reverification_appends_delta_and_preserves_history(
    db_session: Session, reuse_verify_id: bool, locked_event_month: bool,
) -> None:
    _load_dual_fee_fixture(db_session, amount_cent=10000)
    rebuild_dual_fee_results(db_session, calculation_run_id="locked-reverify-base")
    originals = [_fee_result(db_session, "coupon-dual", direction) for direction in (1, 2)]
    frozen = [lock_settlement_statement(
        db_session, store_id=store, statement_month=month, lock_run_id=f"freeze-{store}",
    ) for store, month in (("store-sale", "2026-09"), ("store-verify", "2026-09"))]
    frozen_totals = [(row.promotion_net_fee_cent, row.management_net_fee_cent) for row in frozen]
    if locked_event_month:
        for store in ("store-sale", "store-verify"):
            lock_settlement_statement(db_session, store_id=store, statement_month="2026-10", lock_run_id=f"freeze-oct-{store}")
    old = db_session.get(RawDouyinVerifyRecord, "verify-coupon-dual")
    old.verify_status = "cancelled"
    old.cancel_time = _dual_time(10, 8)
    db_session.flush()
    rebuild_dual_fee_results(db_session, calculation_run_id="locked-reverify-cancel")
    _add_scope_rule(db_session, "2026-10")
    verify_id = "verify-coupon-dual" if reuse_verify_id else "locked-new"
    upsert_verify_record(
        db_session, verify_id, coupon_id="coupon-dual", verify_status="valid",
        verify_time=_dual_time(10, 10), poi_id="poi-verify", sku_id="sku-dual",
        paid_amount_cent=10000, source_run_id="locked-new",
    )
    verify = db_session.get(RawDouyinVerifyRecord, verify_id)
    verify.verify_status = "valid"
    verify.verify_time = _dual_time(10, 10)
    verify.cancel_time = None
    db_session.flush()
    for run in ("locked-reverify-new", "locked-reverify-new", "locked-reverify-repeat"):
        rebuild_dual_fee_results(db_session, calculation_run_id=run, force_recalculate=True)
    restorations = list(db_session.scalars(select(SettlementFeeAdjustment).where(SettlementFeeAdjustment.adjustment_type == 4)))
    pending = list(db_session.scalars(select(dy_models.SettlementCarryforwardSource).where(dy_models.SettlementCarryforwardSource.adjustment_type == 4)))
    assert sorted(row.adjustment_fee_cent for row in restorations + pending) == [2000, 3000]
    assert count(db_session, SettlementFeeResult) == 4
    assert [_fee_result(db_session, "coupon-dual", direction).fee_result_id for direction in (1, 2)] == [row.fee_result_id for row in originals]
    assert [(row.promotion_net_fee_cent, row.management_net_fee_cent) for row in frozen] == frozen_totals
    if locked_event_month:
        for store in ("store-sale", "store-verify"):
            lock_settlement_statement(db_session, store_id=store, statement_month="2026-11", lock_run_id=f"apply-{store}")
        assert count(db_session, dy_models.SettlementCarryforwardApplication) == 4
    opening_adjustments = list(db_session.scalars(select(SettlementFeeAdjustment).where(
        SettlementFeeAdjustment.adjustment_type == 4,
    )))
    _assert_reverification_projection_sources(
        db_session, month="2026-11" if locked_event_month else "2026-10",
        expected={"store-sale": 0, "store-verify": 0},
        expected_adjustment_ids={row.adjustment_id for row in opening_adjustments},
    )
    # Refund and another cancellation follow the restored lineage, not the frozen one.
    db_session.add(DouyinRefundEvent(
        refund_event_id="restored-refund", order_id="order-coupon-dual", coupon_id="coupon-dual",
        refund_type=1, refund_status=2, refund_amount_cent=1000,
        occurred_at=_dual_time(12, 2), source_run_id="restored-refund", raw_payload={},
    ))
    db_session.flush()
    rebuild_dual_fee_results(db_session, calculation_run_id="restored-refund")
    refunds = list(db_session.scalars(select(SettlementFeeAdjustment).where(SettlementFeeAdjustment.refund_event_id == "restored-refund")))
    assert sorted(row.adjustment_fee_cent for row in refunds) == [-300, -200]
    _assert_reverification_projection_sources(
        db_session, month="2026-12", expected={"store-sale": -300, "store-verify": -200},
        expected_adjustment_ids={row.adjustment_id for row in refunds},
    )
    verify.verify_status = "cancelled"
    verify.cancel_time = _dual_time(12, 3)
    db_session.flush()
    for _ in range(2):
        rebuild_dual_fee_results(db_session, calculation_run_id="restored-cancel")
    for direction, original in zip((1, 2), originals):
        adjustments = settlement_worker._active_fee_adjustments(db_session)
        assert original.fee_amount_cent + sum(row.adjustment_fee_cent for row in adjustments if row.fee_direction == direction) == 0


@pytest.mark.parametrize("verify_paid", [0, 8000, 10000])
def test_verified_basis_uses_same_receipts_and_verification_day_rules(
    db_session: Session, verify_paid: int,
) -> None:
    # DYDATA-97: the fixture carries a real order receipt (12000) distinct from
    # the verification paid amount; the paid value must not steer the basis.
    _load_dual_fee_fixture(db_session, amount_cent=12000)
    _add_fee_rule(db_session, "fee-verify-day", date(2026, 9, 5), promotion="0.170000", management="0.170000")
    verify = db_session.get(RawDouyinVerifyRecord, "verify-coupon-dual")
    verify.paid_amount_cent = verify_paid
    db_session.flush()
    for run in ("common-basis", "common-basis", "common-basis-repeat"):
        rebuild_dual_fee_results(db_session, calculation_run_id=run)
    for direction in (1, 2):
        result = _fee_result(db_session, "coupon-dual", direction)
        assert result.original_business_month == "2026-09"
        assert result.rule_match_date == date(2026, 9, 5)
        assert result.rule_version == "fee-verify-day"
        assert result.source_amount_cent == result.fee_base_cent == 12000
        assert result.fee_amount_cent == 12000 * 17 // 100
        assert (result.sale_store_id if direction == 1 else result.verify_store_id) == ("store-sale" if direction == 1 else "store-verify")
    assert count(db_session, SettlementFeeResult) == 2


@pytest.mark.parametrize("old_slot_locked", [
    False, True, "confirmation", "confirmed_status", "confirmed_at", "historical_invoice",
])
def test_verified_basis_migrates_only_unlocked_legacy_sale_month(
    db_session: Session, old_slot_locked: bool,
) -> None:
    _load_dual_fee_fixture(db_session, amount_cent=10000)
    rebuild_dual_fee_results(db_session, calculation_run_id="legacy-seed")
    legacy = _fee_result(db_session, "coupon-dual", 1)
    # Represent the pre-change sale-month record, including its old rule/base.
    legacy.original_business_month = "2026-08"
    legacy.rule_match_date = date(2026, 8, 10)
    legacy.rule_version = "fee-aug"
    legacy.scope_rule_version = "scope-2026-08-short_video"
    legacy.fee_rate = Decimal("0.012345")
    legacy.fee_amount_cent = 123
    legacy.input_fingerprint = None
    db_session.flush()
    if old_slot_locked:
        # Even a protected old slot without an entry referencing this result
        # must not be bypassed by moving the result to another month.
        db_session.add(SettlementStatement(
            statement_id="legacy-locked-slot", store_id="store-sale", statement_month="2026-08",
            statement_status=4, locked_by="test", locked_at=_dual_time(9, 8), lock_version="legacy-lock",
        ))
        db_session.flush()
        statement = db_session.scalar(select(SettlementStatement).where(SettlementStatement.statement_id == "legacy-locked-slot"))
        if isinstance(old_slot_locked, str):
            statement.statement_status = 3 if old_slot_locked == "confirmed_status" else 2
            statement.locked_at = None
            statement.confirmed_at = _dual_time(9, 8) if old_slot_locked == "confirmed_at" else None
            if old_slot_locked == "confirmation":
                db_session.add(dy_models.SettlementStatementConfirmation(
                    confirmation_id="legacy-confirmation", statement_id=statement.statement_id,
                    fee_direction=1, confirmed_by="test", confirmed_at=_dual_time(9, 8),
                    idempotency_key_hash="legacy-confirmation",
                ))
            if old_slot_locked == "historical_invoice":
                db_session.add(dy_models.InvoiceRecord(
                    invoice_id="legacy-invoice", store_id="store-sale", statement_month="2026-08",
                    statement_id=statement.statement_id, fee_direction=1, is_current=False,
                    invoice_number="12345678901234567890", invoice_date=date(2026, 9, 8),
                    invoice_amount_cent=123, source_type=1, registered_by="test",
                ))
            db_session.flush()
    for _ in range(2):
        rebuild_dual_fee_results(db_session, calculation_run_id="legacy-repair", force_recalculate=True)
    current = _fee_result(db_session, "coupon-dual", 1)
    if old_slot_locked:
        assert current.fee_result_id == legacy.fee_result_id
        assert current.original_business_month == "2026-08"
        assert current.fee_amount_cent == 123
        assert db_session.scalar(select(func.count()).select_from(SettlementFeeResult).where(
            SettlementFeeResult.coupon_id == "coupon-dual", SettlementFeeResult.fee_direction == 1,
        )) == 1
        assert not [source for source in billing_capture.collect_billing_sources(db_session, months=["2026-09"])
                    if source.store_id == "store-sale"]
    else:
        assert current.fee_result_id != legacy.fee_result_id
        assert current.original_business_month == "2026-09"
        assert current.rule_version == "fee-sep"
        assert current.fee_amount_cent == 3000
        assert legacy.result_status == 2
        rebuild_dual_fee_projections(db_session, projection_run_id="legacy-repair-projection")
        old_month = monthly_projection(db_session, "2026-08", "store-sale", "all")
        assert old_month is None or old_month.promotion_net_fee_cent == 0
        assert monthly_projection(db_session, "2026-09", "store-sale", "all").promotion_net_fee_cent == 3000
    assert legacy.original_business_month == "2026-08"
    assert legacy.fee_amount_cent == 123


def test_dual_fee_results_use_directional_dates_rules_months_and_rounding(
    db_session: Session,
) -> None:
    _load_dual_fee_fixture(db_session)

    rebuild_dual_fee_results(db_session, calculation_run_id="dual-calc-1")

    promotion = _fee_result(db_session, "coupon-dual", 1)
    management = _fee_result(db_session, "coupon-dual", 2)
    assert promotion is not None
    assert management is not None
    assert promotion.original_business_month == "2026-09"
    assert promotion.rule_match_date == date(2026, 9, 5)
    assert promotion.sale_store_id == "store-sale"
    assert promotion.rule_version == "fee-sep"
    assert promotion.fee_rate == Decimal("0.300000")
    assert promotion.fee_amount_cent == 3000
    assert management.original_business_month == "2026-09"
    assert management.rule_match_date == date(2026, 9, 5)
    assert management.verify_store_id == "store-verify"
    assert management.rule_version == "fee-sep"
    assert management.fee_rate == Decimal("0.200000")
    assert management.fee_amount_cent == 2000


@pytest.mark.parametrize("account_without_store", [False, True])
@pytest.mark.parametrize("with_binding_dimension", [False, True])
def test_dual_fee_resolves_order_uid_through_unique_active_raw_binding(
    db_session: Session, account_without_store: bool, with_binding_dimension: bool
) -> None:
    _load_dual_fee_fixture(db_session)
    order = db_session.scalar(select(RawDouyinOrder))
    assert order is not None
    order.owner_account_id = "_000_opaque_order_uid"
    if account_without_store:
        upsert_aweme_account(
            db_session, order.owner_account_id,
            nickname="Owner Dual", binding_status="active",
        )
    upsert_aweme_binding(
        db_session, "binding-owner-dual", account_id="store-sale",
        douyin_nickname="Owner Dual", binding_status="active",
    )
    if with_binding_dimension:
        upsert_aweme_account(
            db_session, "store-sale", nickname="Owner Dual", store_id="store-sale",
            binding_status="认证成功", valid_from=date(2026, 8, 10),
            valid_to=date(2026, 8, 10),
        )
    db_session.flush()

    rebuild_dual_fee_results(db_session, calculation_run_id="uid-binding-fix")
    rebuild_dual_fee_results(db_session, calculation_run_id="uid-binding-repeat")
    rebuild_dual_fee_projections(db_session, projection_run_id="uid-projection")

    promotion = _fee_result(db_session, "coupon-dual", 1)
    management = _fee_result(db_session, "coupon-dual", 2)
    assert promotion is not None
    assert promotion.sale_store_id == "store-sale"
    assert promotion.fee_amount_cent == 3000
    assert management is not None
    assert management.sale_store_id == "store-sale"
    assert management.verify_store_id == "store-verify"
    assert management.fee_amount_cent == 2000
    assert count(db_session, SettlementFeeResult) == 2
    monthly = monthly_projection(db_session, "2026-09", "store-sale", "maintenance")
    assert monthly is not None
    assert monthly.promotion_net_fee_cent == 3000


@pytest.mark.parametrize(
    "invalid_binding",
    ["unbound", "unknown_store", "ambiguous", "id_conflict", "inactive_account",
     "before_valid_from", "after_valid_to", "non_commission", "inactive_store",
     "known_id_inactive", "known_id_expired", "missing_binding", "name_mismatch"],
)
def test_dual_fee_owner_binding_fails_closed(
    db_session: Session, invalid_binding: str
) -> None:
    _load_dual_fee_fixture(db_session)
    order = db_session.scalar(select(RawDouyinOrder))
    assert order is not None
    order.owner_account_id = "_000_opaque_order_uid"
    store_id = "unknown-store" if invalid_binding == "unknown_store" else "store-sale"
    upsert_aweme_binding(
        db_session, "binding-owner-dual", account_id=store_id,
        douyin_nickname="Unrelated Owner" if invalid_binding == "name_mismatch" else "Owner Dual",
        binding_status="已解绑" if invalid_binding == "unbound" else "active",
    )
    if invalid_binding == "missing_binding":
        order.owner_account_name = None
    if invalid_binding == "inactive_store":
        store = db_session.get(dy_models.DimStore, "store-sale")
        assert store is not None
        store.is_active = False
    if invalid_binding in {"known_id_inactive", "known_id_expired"}:
        upsert_aweme_account(
            db_session, order.owner_account_id, nickname="Owner Dual",
            store_id="store-sale",
            binding_status="已解绑" if invalid_binding == "known_id_inactive" else "active",
            valid_to=date(2026, 8, 9) if invalid_binding == "known_id_expired" else None,
        )
    if invalid_binding == "ambiguous":
        upsert_aweme_binding(
            db_session, "binding-owner-other", account_id="store-verify",
            douyin_nickname="Owner Dual", binding_status="active",
        )
    if invalid_binding == "id_conflict":
        upsert_aweme_account(
            db_session, order.owner_account_id, nickname="Owner Dual",
            store_id="store-verify", binding_status="active",
        )
    if invalid_binding in {"inactive_account", "before_valid_from", "after_valid_to"}:
        upsert_aweme_account(
            db_session, "store-sale", nickname="Owner Dual", store_id="store-sale",
            binding_status="已解绑" if invalid_binding == "inactive_account" else "active",
            valid_from=date(2026, 8, 11) if invalid_binding == "before_valid_from" else None,
            valid_to=date(2026, 8, 9) if invalid_binding == "after_valid_to" else None,
        )
    if invalid_binding == "non_commission":
        db_session.add(DimNonCommissionOwnerAccount(
            owner_account_name="Owner Dual",
            normalized_owner_account_name=normalize_owner_account_name("Owner Dual"),
            is_active=True,
        ))
    db_session.flush()

    rebuild_dual_fee_results(db_session, calculation_run_id="invalid-owner-binding")

    assert _fee_result(db_session, "coupon-dual", 1) is None
    assert _fee_result(db_session, "coupon-dual", 2) is None
    issue_types = set(db_session.scalars(select(DataQualityIssue.issue_type)))
    assert (
        "dual_fee_non_commission_owner" if invalid_binding == "non_commission"
        else "dual_fee_missing_sale_store"
    ) in issue_types


@pytest.mark.parametrize("direct_match", [False, True])
def test_dual_fee_does_not_resurrect_an_explicitly_unbound_identity(
    db_session: Session, direct_match: bool
) -> None:
    _load_dual_fee_fixture(db_session)
    order = db_session.scalar(select(RawDouyinOrder))
    assert order is not None
    if not direct_match:
        order.owner_account_id = "_000_opaque_order_uid"
    for key, status in [("old-active", "active"), ("new-unbound", "已解绑")]:
        upsert_aweme_binding(
            db_session, key, account_id="store-sale", douyin_id="seller-douyin-id",
            douyin_nickname="Owner Dual", poi_id="poi-sale", binding_status=status,
        )
    db_session.flush()

    rebuild_dual_fee_results(db_session, calculation_run_id="conflicting-binding-status")

    assert _fee_result(db_session, "coupon-dual", 1) is None
    assert _fee_result(db_session, "coupon-dual", 2) is None


def test_dual_fee_unrelated_unbound_identity_does_not_override_valid_binding(
    db_session: Session,
) -> None:
    _load_dual_fee_fixture(db_session)
    order = db_session.scalar(select(RawDouyinOrder))
    assert order is not None
    order.owner_account_id = "_000_opaque_order_uid"
    upsert_aweme_binding(
        db_session, "active-owner", account_id="store-sale", douyin_id="seller-a",
        douyin_nickname="Owner Dual", binding_status="active",
    )
    upsert_aweme_binding(
        db_session, "inactive-other", account_id="store-verify", douyin_id="seller-b",
        douyin_nickname="Owner Dual", binding_status="已解绑",
    )
    db_session.flush()

    rebuild_dual_fee_results(db_session, calculation_run_id="unrelated-binding-status")

    assert _fee_result(db_session, "coupon-dual", 1) is not None
    assert _fee_result(db_session, "coupon-dual", 2) is not None


@pytest.mark.parametrize("status", ["pending", "reviewing"])
@pytest.mark.parametrize("with_old_active", [False, True])
@pytest.mark.parametrize("direct_match", [False, True])
def test_dual_fee_pending_binding_never_qualifies_as_active(
    db_session: Session, status: str, with_old_active: bool, direct_match: bool
) -> None:
    _load_dual_fee_fixture(db_session)
    order = db_session.scalar(select(RawDouyinOrder))
    assert order is not None
    if not direct_match:
        order.owner_account_id = "_000_opaque_order_uid"
    statuses = ["active", status] if with_old_active else [status]
    for binding_status in statuses:
        upsert_aweme_binding(
            db_session, f"binding-{binding_status}", account_id="store-sale",
            douyin_id="seller-id", douyin_nickname="Owner Dual",
            binding_status=binding_status,
        )
    db_session.flush()

    rebuild_dual_fee_results(db_session, calculation_run_id="pending-binding")

    assert _fee_result(db_session, "coupon-dual", 1) is None
    assert _fee_result(db_session, "coupon-dual", 2) is None


def test_dual_fee_normalizes_numeric_binding_account_type(
    db_session: Session,
) -> None:
    _load_dual_fee_fixture(db_session)
    order = db_session.scalar(select(RawDouyinOrder))
    assert order is not None
    order.owner_account_id = "_000_opaque_order_uid"
    for key, status, payload in [
        ("numeric-type", "active", {"account_type": 1}),
        ("string-type", "已解绑", {"账号类型": "1"}),
    ]:
        upsert_aweme_binding(
            db_session, key, account_id="store-sale", douyin_id="seller-id",
            douyin_nickname="Owner Dual", binding_status=status, raw_payload=payload,
        )
    db_session.flush()

    rebuild_dual_fee_results(db_session, calculation_run_id="numeric-binding-type")

    assert _fee_result(db_session, "coupon-dual", 1) is None
    assert _fee_result(db_session, "coupon-dual", 2) is None


def test_dual_fee_ignores_status_conflict_without_a_real_store_candidate(
    db_session: Session,
) -> None:
    _load_dual_fee_fixture(db_session)
    order = db_session.scalar(select(RawDouyinOrder))
    assert order is not None
    order.owner_account_id = "_000_opaque_order_uid"
    upsert_aweme_binding(
        db_session, "actual-store-binding", account_id="store-sale",
        douyin_nickname="Owner Dual", binding_status="active",
    )
    for status in ["active", "已解绑"]:
        upsert_aweme_binding(
            db_session, f"unrelated-{status}", account_id="not-a-store",
            douyin_id="unrelated-seller", douyin_nickname="Owner Dual",
            binding_status=status,
        )
    db_session.flush()

    rebuild_dual_fee_results(db_session, calculation_run_id="irrelevant-status-conflict")

    assert _fee_result(db_session, "coupon-dual", 1) is not None
    assert _fee_result(db_session, "coupon-dual", 2) is not None


def test_dual_fee_direct_unbinding_cannot_be_masked_by_another_identity(
    db_session: Session,
) -> None:
    _load_dual_fee_fixture(db_session)
    upsert_aweme_binding(
        db_session, "direct-unbound", account_id="owner-dual",
        douyin_id="direct-douyin", douyin_nickname="Owner Dual",
        binding_status="unbound",
    )
    upsert_aweme_binding(
        db_session, "other-active", account_id="store-sale",
        douyin_id="other-douyin", douyin_nickname="Owner Dual",
        binding_status="active",
    )
    db_session.flush()

    rebuild_dual_fee_results(db_session, calculation_run_id="direct-unbinding-evidence")

    assert _fee_result(db_session, "coupon-dual", 1) is None
    assert _fee_result(db_session, "coupon-dual", 2) is None


@pytest.mark.parametrize("missing_store", [False, True])
def test_dual_fee_invalid_direct_store_cannot_be_replaced_by_same_name(
    db_session: Session, missing_store: bool
) -> None:
    _load_dual_fee_fixture(db_session)
    account = db_session.get(DimAwemeAccount, "owner-dual")
    assert account is not None
    if missing_store:
        account.store_id = "missing-direct-store"
    else:
        store = db_session.get(dy_models.DimStore, "store-sale")
        assert store is not None
        store.is_active = False
    upsert_aweme_binding(
        db_session, "other-store-active", account_id="store-verify",
        douyin_id="other-douyin", douyin_nickname="Owner Dual",
        binding_status="active",
    )
    db_session.flush()

    rebuild_dual_fee_results(db_session, calculation_run_id="invalid-direct-store")

    assert _fee_result(db_session, "coupon-dual", 1) is None
    assert _fee_result(db_session, "coupon-dual", 2) is None


@pytest.mark.parametrize(
    ("scenario", "reason_code", "failure_node"),
    [
        ("direct_inactive", "direct_binding_inactive", "direct_account_validity"),
        ("direct_expired", "direct_binding_after_valid_to", "direct_account_validity"),
        ("direct_future", "direct_binding_before_valid_from", "direct_account_validity"),
        ("direct_missing_sale", "direct_sale_date_missing", "direct_account_validity"),
        ("direct_store_missing", "direct_store_missing", "direct_store"),
        ("direct_store_inactive", "direct_store_inactive", "direct_store"),
        ("direct_raw_inactive", "direct_identity_has_inactive_binding", "binding_identity_statuses"),
        ("mixed_statuses", "binding_identity_status_conflict", "binding_identity_statuses"),
        ("direct_store_raw_inactive", "direct_store_bindings_inactive", "direct_store_binding_statuses"),
        ("candidate_inactive", "candidate_binding_inactive", "candidate_account_validity"),
        ("candidate_expired", "candidate_binding_after_valid_to", "candidate_account_validity"),
        ("candidate_future", "candidate_binding_before_valid_from", "candidate_account_validity"),
        ("candidate_missing_sale", "candidate_sale_date_missing", "candidate_account_validity"),
        ("candidate_store_conflict", "candidate_store_conflict", "candidate_store_consistency"),
        ("candidate_unknown_store", "no_valid_store", "unique_valid_store"),
        ("candidate_inactive_store", "no_valid_store", "unique_valid_store"),
        ("multiple_stores", "multiple_valid_stores", "unique_valid_store"),
        ("no_stores", "no_valid_store", "unique_valid_store"),
        ("resolved", "resolved", None),
    ],
)
def test_dual_fee_sale_diagnostic_identifies_the_actual_rejection_node(
    db_session: Session, scenario: str, reason_code: str, failure_node: str | None,
) -> None:
    _load_dual_fee_fixture(db_session)
    order = db_session.scalar(select(RawDouyinOrder))
    assert order is not None
    direct = db_session.get(DimAwemeAccount, order.owner_account_id)
    assert direct is not None
    if not scenario.startswith("direct_"):
        order.owner_account_id = "opaque-order-uid"
    if scenario == "direct_inactive":
        direct.binding_status = "已解绑"
    elif scenario == "direct_expired":
        direct.valid_to = date(2026, 8, 9)
    elif scenario == "direct_future":
        direct.valid_from = date(2026, 8, 11)
    elif scenario == "direct_missing_sale":
        direct.valid_from = date(2026, 8, 1)
        order.sale_time = order.pay_time = None
    elif scenario == "direct_store_missing":
        direct.store_id = "missing-store"
    elif scenario == "direct_store_inactive":
        db_session.get(dy_models.DimStore, "store-sale").is_active = False
    elif scenario == "direct_raw_inactive":
        upsert_aweme_binding(
            db_session, "direct-inactive", account_id=direct.account_id,
            douyin_nickname=order.owner_account_name, binding_status="已解绑",
        )
    elif scenario == "direct_store_raw_inactive":
        upsert_aweme_binding(
            db_session, "direct-store-inactive", account_id="store-sale",
            douyin_nickname=order.owner_account_name, binding_status="已解绑",
        )
    elif scenario != "no_stores":
        statuses = ("active", "已解绑") if scenario == "mixed_statuses" else ("active",)
        for status in statuses:
            upsert_aweme_binding(
                db_session, f"diagnostic-{status}", account_id=(
                    "unknown-store" if scenario == "candidate_unknown_store" else "store-sale"
                ),
                douyin_id="seller-one", poi_id="poi-sale",
                douyin_nickname=order.owner_account_name, binding_status=status,
                raw_payload={"account_type": 1, "private_secret": "never-copy-raw-payload"},
            )
        if scenario.startswith("candidate_"):
            if scenario == "candidate_inactive_store":
                db_session.get(dy_models.DimStore, "store-sale").is_active = False
            upsert_aweme_account(
                db_session, "store-sale", store_id=(
                    "store-verify" if scenario == "candidate_store_conflict" else "store-sale"
                ), binding_status="已解绑" if scenario == "candidate_inactive" else "active",
                valid_to=date(2026, 8, 9) if scenario == "candidate_expired" else None,
                valid_from=date(2026, 8, 11) if scenario in {
                    "candidate_future", "candidate_missing_sale",
                } else None,
            )
            if scenario == "candidate_missing_sale":
                order.sale_time = order.pay_time = None
        elif scenario == "multiple_stores":
            upsert_aweme_binding(
                db_session, "another-store", account_id="store-verify",
                douyin_nickname=order.owner_account_name, binding_status="active",
            )
    db_session.flush()

    diagnostic = settlement_worker.diagnose_dual_fee_sale_account(db_session, order)

    assert diagnostic.reason_code == reason_code
    assert diagnostic.failure_node == failure_node
    assert diagnostic.match == settlement_worker._resolve_dual_fee_sale_account(db_session, order)
    assert (diagnostic.match is not None) == (scenario == "resolved")
    context = diagnostic.as_context()
    assert context["reason_code"] == reason_code
    assert "never-copy-raw-payload" not in json.dumps(context)
    if scenario == "mixed_statuses":
        assert {row["binding_status"] for row in context["raw_bindings"]} == {"active", "已解绑"}
        assert context["failure_evidence"] == {
            "account_id": "store-sale", "douyin_id": "seller-one", "poi_id": "poi-sale",
            "account_type": "1", "active_values": [False, True],
        }
    if scenario == "multiple_stores":
        assert set(context["valid_store_ids"]) == {"store-sale", "store-verify"}
    if scenario in {"candidate_unknown_store", "candidate_inactive_store"}:
        assert context["candidates"][0]["reason_code"] == (
            "candidate_store_missing" if scenario == "candidate_unknown_store" else "candidate_store_inactive"
        )


def test_dual_fee_sale_diagnostic_bounds_context_but_retains_the_failure_identity(
    db_session: Session,
) -> None:
    _load_dual_fee_fixture(db_session)
    order = db_session.scalar(select(RawDouyinOrder))
    assert order is not None
    order.owner_account_id = "opaque-order-uid"
    for index in range(51):
        upsert_aweme_binding(
            db_session, f"unrelated-{index}", account_id="store-sale",
            douyin_id=f"seller-{index}", douyin_nickname=order.owner_account_name,
            binding_status="active",
        )
    for status in ("active", "已解绑"):
        upsert_aweme_binding(
            db_session, f"conflict-{status}", account_id="store-sale",
            douyin_id="failing-identity", douyin_nickname=order.owner_account_name,
            binding_status=status,
        )
    db_session.flush()

    diagnostic = settlement_worker.diagnose_dual_fee_sale_account(db_session, order)
    context = diagnostic.as_context()

    assert diagnostic.reason_code == "binding_identity_status_conflict"
    assert context["raw_binding_count"] == 53
    assert len(context["raw_bindings"]) == 50
    assert context["evidence_truncated"] is True
    assert context["failure_evidence"]["douyin_id"] == "failing-identity"


def test_dual_fee_sale_diagnostic_is_read_only_and_does_not_autoflush(db_session: Session) -> None:
    _load_dual_fee_fixture(db_session)
    order = db_session.scalar(select(RawDouyinOrder))
    assert order is not None
    db_session.flush()
    order.product_name = "pending unrelated source edit"
    statements: list[str] = []
    connection = db_session.connection()

    def capture_write(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().lower().startswith(("insert", "update", "delete")):
            statements.append(statement)

    event.listen(connection, "before_cursor_execute", capture_write)
    original_autoflush = db_session.autoflush
    try:
        # Enable the ordinary Session default to prove diagnostic reads suppress it.
        db_session.autoflush = True
        diagnostic = settlement_worker.diagnose_dual_fee_sale_account(db_session, order)
    finally:
        db_session.autoflush = original_autoflush
        event.remove(connection, "before_cursor_execute", capture_write)

    assert diagnostic.match is not None
    assert statements == []
    assert order in db_session.dirty


@pytest.mark.parametrize("source", ["account", "binding"])
@pytest.mark.parametrize("autoflush", [False, True])
def test_dual_fee_resolver_preserves_session_autoflush_for_pending_sources(
    db_session: Session, source: str, autoflush: bool,
) -> None:
    _load_dual_fee_fixture(db_session)
    order = db_session.scalar(select(RawDouyinOrder))
    assert order is not None
    order.owner_account_id = "pending-owner"
    db_session.flush()
    pending = (
        DimAwemeAccount(
            account_id="pending-owner", store_id="store-sale", binding_status="active",
        ) if source == "account" else dy_models.RawAwemeBinding(
            binding_key="pending-binding", account_id="store-sale",
            douyin_nickname=order.owner_account_name, binding_status="active",
        )
    )
    db_session.add(pending)
    original_autoflush = db_session.autoflush
    try:
        db_session.autoflush = autoflush
        diagnostic = settlement_worker.diagnose_dual_fee_sale_account(db_session, order)
        assert diagnostic.match is None
        assert pending in db_session.new

        match = settlement_worker._resolve_dual_fee_sale_account(db_session, order)

        assert (match is not None) is autoflush
        if autoflush:
            assert match.store_id == "store-sale"
        assert (pending in db_session.new) is not autoflush
        assert db_session.autoflush is autoflush
    finally:
        db_session.autoflush = original_autoflush


@pytest.mark.parametrize("source", ["account", "binding"])
def test_dual_fee_materialization_keeps_pending_source_autoflush(
    db_session: Session, monkeypatch: pytest.MonkeyPatch, source: str,
) -> None:
    _load_dual_fee_fixture(db_session)
    order = db_session.scalar(select(RawDouyinOrder))
    assert order is not None
    order.owner_account_id = "pending-owner"
    db_session.flush()
    original_lookup = settlement_worker.resolve_historical_sale_attribution
    pending_added = False

    def add_source_after_historical_lookup(session, **kwargs):
        nonlocal pending_added
        decision = original_lookup(session, **kwargs)
        if not pending_added:
            pending_added = True
            session.add(
                DimAwemeAccount(
                    account_id="pending-owner", store_id="store-sale", binding_status="active",
                ) if source == "account" else dy_models.RawAwemeBinding(
                    binding_key="pending-binding", account_id="store-sale",
                    douyin_nickname=order.owner_account_name, binding_status="active",
                )
            )
        return decision

    monkeypatch.setattr(
        settlement_worker, "resolve_historical_sale_attribution", add_source_after_historical_lookup,
    )
    original_autoflush = db_session.autoflush
    try:
        db_session.autoflush = True
        rebuild_dual_fee_results(db_session, calculation_run_id="pending-source-autoflush")
    finally:
        db_session.autoflush = original_autoflush

    assert pending_added
    assert _fee_result(db_session, "coupon-dual", 1) is not None
    assert _fee_result(db_session, "coupon-dual", 2) is not None
    assert not list(db_session.scalars(select(DataQualityIssue).where(
        DataQualityIssue.issue_type == "dual_fee_missing_sale_store",
    )))


def test_dual_fee_missing_sale_store_persists_specific_diagnostic(db_session: Session) -> None:
    _load_dual_fee_fixture(db_session)
    order = db_session.scalar(select(RawDouyinOrder))
    assert order is not None
    order.owner_account_id = "opaque-order-uid"
    for status in ("active", "已解绑"):
        upsert_aweme_binding(
            db_session, f"dq-{status}", account_id="store-sale", douyin_id="seller-one",
            douyin_nickname=order.owner_account_name, binding_status=status,
        )
    db_session.flush()

    rebuild_dual_fee_results(db_session, calculation_run_id="diagnostic-dq")

    issues = list(db_session.scalars(select(DataQualityIssue).where(
        DataQualityIssue.issue_type == "dual_fee_missing_sale_store",
    )))
    assert issues
    for issue in issues:
        diagnostic = issue.raw_context_json["sale_attribution_diagnostic"]
        assert diagnostic["reason_code"] == "binding_identity_status_conflict"
        assert diagnostic["failure_node"] == "binding_identity_statuses"
    assert _fee_result(db_session, "coupon-dual", 1) is None
    assert _fee_result(db_session, "coupon-dual", 2) is None


def _load_openapi_sale_binding_fixture(db_session: Session):
    _load_dual_fee_fixture(db_session)
    order = db_session.scalar(select(RawDouyinOrder))
    assert order is not None
    order.owner_account_id = "craftsman-exact"
    # A changed nickname must not prevent an exact source UID match.
    order.owner_account_name = "Earlier seller nickname"
    instant = int(settlement_worker._as_utc(order.sale_time).timestamp())
    payload = {
        "craftsman_uid": "craftsman-exact", "account_id": "merchant-account",
        "poi_id": "poi-api-sale", "bind_status": 2,
        "bind_start_time": instant - 60, "bind_end_time": instant + 60,
        "real_name": "never-copy-private-source",
    }
    binding = upsert_aweme_binding(
        db_session, "craftsman-exact:dy-api-sale:poi-api-sale",
        account_id="craftsman-exact", douyin_id="dy-api-sale",
        douyin_nickname="Current seller nickname", poi_id="poi-api-sale",
        binding_status="2", raw_payload=payload,
    )
    upsert_store_poi_mapping(db_session, "store-sale", "poi-api-sale", mapping_source="test")
    db_session.flush()
    return order, binding


@pytest.mark.parametrize("status", [2, 105, 5, "105"])
@pytest.mark.parametrize("unit", ["seconds", "milliseconds"])
def test_openapi_sale_fallback_uses_exact_uid_covering_interval_and_poi(
    db_session: Session, status: int | str, unit: str,
) -> None:
    order, binding = _load_openapi_sale_binding_fixture(db_session)
    # The inclusive point interval is compared as an instant, not a calendar day.
    order.sale_time = datetime(2026, 8, 11, 0, 0, 0, 123000, tzinfo=timezone(timedelta(hours=8)))
    instant = int(settlement_worker._as_utc(order.sale_time).timestamp())
    boundary = instant * 1000 + 123 if unit == "milliseconds" else instant
    if unit == "seconds":
        order.sale_time = order.sale_time.replace(microsecond=0)
    binding.binding_status = str(status)
    binding.raw_payload = {
        **binding.raw_payload, "bind_status": status,
        "bind_start_time": str(boundary), "bind_end_time": boundary,
    }
    db_session.flush()

    diagnostic = settlement_worker.diagnose_dual_fee_sale_account(db_session, order)

    assert diagnostic.match is not None
    assert diagnostic.match.account_id == order.owner_account_id
    assert diagnostic.match.store_id == "store-sale"
    assert diagnostic.match.match_source == "openapi_binding_interval"
    assert diagnostic.reason_code == "resolved_openapi_binding_interval"
    context = diagnostic.as_context()
    assert context["openapi_bindings"][0]["reason_code"] == "valid_openapi_candidate"
    assert "never-copy-private-source" not in json.dumps(context)


@pytest.mark.parametrize(
    ("case", "reason_code"),
    [
        ("missing_sale_time", "openapi_sale_time_missing"),
        ("missing_start", "openapi_interval_missing"),
        ("missing_end", "openapi_interval_missing"),
        ("zero", "openapi_interval_invalid"),
        ("negative", "openapi_interval_invalid"),
        ("bool", "openapi_interval_invalid"),
        ("float", "openapi_interval_invalid"),
        ("text", "openapi_interval_invalid"),
        ("overflow", "openapi_interval_invalid"),
        ("huge_text", "openapi_interval_invalid"),
        ("reverse", "openapi_interval_invalid"),
        ("before_start", "openapi_sale_outside_interval"),
        ("after_end", "openapi_sale_outside_interval"),
        ("payload_uid_mismatch", "openapi_source_identity_mismatch"),
        ("payload_poi_mismatch", "openapi_source_identity_mismatch"),
        ("payload_status_mismatch", "openapi_source_status_mismatch"),
        ("settlement_id_mismatch", "openapi_source_identity_mismatch"),
        ("unverified_source_key", "openapi_source_unverified"),
        ("missing_craftsman_uid", "no_valid_store"),
        ("different_owner_uid", "no_valid_store"),
        ("pending", "openapi_binding_status_ineligible"),
        ("disabled", "openapi_binding_status_ineligible"),
        ("unknown_status", "openapi_binding_status_ineligible"),
        ("missing_mapping", "openapi_poi_mapping_missing"),
        ("inactive_store", "openapi_store_inactive"),
        ("multiple_bindings", "openapi_multiple_bindings"),
        ("multiple_stores", "openapi_multiple_stores"),
    ],
)
def test_openapi_sale_fallback_fails_closed_without_exact_historical_evidence(
    db_session: Session, case: str, reason_code: str,
) -> None:
    order, binding = _load_openapi_sale_binding_fixture(db_session)
    payload = dict(binding.raw_payload)
    instant = int(settlement_worker._as_utc(order.sale_time).timestamp())
    if case == "missing_sale_time":
        order.sale_time = order.pay_time = None
    elif case in {"missing_start", "missing_end"}:
        payload.pop("bind_start_time" if case == "missing_start" else "bind_end_time")
    elif case in {"zero", "negative", "bool", "float", "text", "overflow", "huge_text"}:
        payload["bind_start_time"] = {
            "zero": 0, "negative": -1, "bool": True, "float": 1.5,
            "text": "not-a-time", "overflow": 10 ** 30, "huge_text": "9" * 5000,
        }[case]
    elif case == "reverse":
        payload["bind_start_time"], payload["bind_end_time"] = instant + 1, instant - 1
    elif case == "before_start":
        payload["bind_start_time"] = instant + 1
    elif case == "after_end":
        payload["bind_end_time"] = instant - 1
    elif case == "payload_uid_mismatch":
        payload["craftsman_uid"] = "different-craftsman"
    elif case == "payload_poi_mismatch":
        payload["poi_id"] = "different-poi"
    elif case == "payload_status_mismatch":
        payload["bind_status"] = 105
    elif case == "settlement_id_mismatch":
        payload["account_id_for_settlement"] = "different-canonical-id"
    elif case == "unverified_source_key":
        binding.binding_key = "backend-style:with-status:2"
    elif case == "missing_craftsman_uid":
        payload.pop("craftsman_uid")
    elif case == "different_owner_uid":
        order.owner_account_id = "different-order-owner"
        binding.douyin_nickname = order.owner_account_name
    elif case in {"pending", "disabled", "unknown_status"}:
        status = {"pending": 1, "disabled": 106, "unknown_status": 99}[case]
        binding.binding_status = str(status)
        payload["bind_status"] = status
    elif case == "missing_mapping":
        mapping = db_session.scalar(select(dy_models.DimStorePoiMapping).where(
            dy_models.DimStorePoiMapping.poi_id == binding.poi_id,
        ))
        db_session.delete(mapping)
    elif case == "inactive_store":
        db_session.get(dy_models.DimStore, "store-sale").is_active = False
    elif case in {"multiple_bindings", "multiple_stores"}:
        second_poi = "poi-api-other" if case == "multiple_stores" else binding.poi_id
        if case == "multiple_stores":
            upsert_store_poi_mapping(db_session, "store-verify", second_poi, mapping_source="test")
        second_payload = {**payload, "poi_id": second_poi}
        if case == "multiple_bindings":
            second_payload["bind_start_time"] -= 1
        upsert_aweme_binding(
            db_session, f"craftsman-exact:second-douyin:{second_poi}",
            account_id=order.owner_account_id, douyin_id="second-douyin", poi_id=second_poi,
            binding_status="2", douyin_nickname="Another current nickname",
            raw_payload=second_payload,
        )
    binding.raw_payload = payload
    db_session.flush()

    diagnostic = settlement_worker.diagnose_dual_fee_sale_account(db_session, order)

    assert diagnostic.match is None
    assert diagnostic.reason_code == reason_code
    assert settlement_worker._resolve_dual_fee_sale_account(db_session, order) is None


@pytest.mark.parametrize("guard", ["direct_inactive", "direct_expired", "mixed_statuses", "legacy_one", "legacy_multiple"])
def test_openapi_sale_fallback_preserves_existing_hard_guards_and_candidates(
    db_session: Session, guard: str,
) -> None:
    order, _binding = _load_openapi_sale_binding_fixture(db_session)
    if guard.startswith("direct_"):
        upsert_aweme_account(
            db_session, order.owner_account_id, store_id="store-sale",
            binding_status="inactive" if guard == "direct_inactive" else "active",
            valid_to=date(2026, 8, 9) if guard == "direct_expired" else None,
        )
    else:
        rows = [("store-verify", "active")]
        if guard == "mixed_statuses":
            rows.append(("store-verify", "unbound"))
        elif guard == "legacy_multiple":
            rows.append(("store-sale", "active"))
        for store_id, status in rows:
            upsert_aweme_binding(
                db_session, f"legacy-{store_id}-{status}", account_id=store_id,
                douyin_nickname=order.owner_account_name, binding_status=status,
            )
    db_session.flush()

    diagnostic = settlement_worker.diagnose_dual_fee_sale_account(db_session, order)

    if guard == "legacy_one":
        assert diagnostic.match is not None and diagnostic.match.store_id == "store-verify"
        assert diagnostic.match.match_source == "raw_aweme_bindings"
    else:
        assert diagnostic.match is None
        assert diagnostic.reason_code == {
            "direct_inactive": "direct_binding_inactive",
            "direct_expired": "direct_binding_after_valid_to",
            "mixed_statuses": "binding_identity_status_conflict",
            "legacy_multiple": "multiple_valid_stores",
        }[guard]


@pytest.mark.parametrize("difference", ["none", "interval", "status", "poi", "invalid_peer"])
def test_openapi_sale_fallback_deduplicates_only_identical_validated_facts(
    db_session: Session, difference: str,
) -> None:
    order, binding = _load_openapi_sale_binding_fixture(db_session)
    payload = dict(binding.raw_payload)
    second_poi = binding.poi_id
    second_status = "2"
    if difference == "interval":
        payload["bind_start_time"] -= 1
    elif difference == "status":
        payload["bind_status"] = 105
        second_status = "105"
    elif difference == "poi":
        second_poi = payload["poi_id"] = "different-poi-same-store"
        upsert_store_poi_mapping(db_session, "store-sale", second_poi, mapping_source="test")
    elif difference == "invalid_peer":
        payload["bind_end_time"] = 0
    upsert_aweme_binding(
        db_session, f"craftsman-exact:old-douyin-alias:{second_poi}",
        account_id=order.owner_account_id, douyin_id="old-douyin-alias",
        poi_id=second_poi, binding_status=second_status,
        douyin_nickname="Previous name", raw_payload=payload,
    )
    db_session.flush()

    diagnostic = settlement_worker.diagnose_dual_fee_sale_account(db_session, order)

    if difference == "none":
        assert diagnostic.match is not None
        assert diagnostic.match.store_id == "store-sale"
        assert diagnostic.reason_code == "resolved_openapi_binding_interval"
        evidence = diagnostic.as_context()["openapi_bindings"]
        assert len(evidence) == 2
        assert len({row["binding_key"] for row in evidence}) == 2
        assert len({row["canonical_fact_sha256"] for row in evidence}) == 1
    else:
        assert diagnostic.match is None
        assert diagnostic.reason_code == (
            "openapi_interval_invalid" if difference == "invalid_peer" else "openapi_multiple_bindings"
        )


def test_openapi_sale_fallback_rejects_ambiguous_poi_mapping(db_session: Session, monkeypatch) -> None:
    order, _binding = _load_openapi_sale_binding_fixture(db_session)
    original_scalars = db_session.scalars

    def conflicting_mapping(statement, *args, **kwargs):
        if statement.column_descriptions[0].get("entity") is dy_models.DimStorePoiMapping:
            return iter(["store-sale", "store-verify"])
        return original_scalars(statement, *args, **kwargs)

    monkeypatch.setattr(db_session, "scalars", conflicting_mapping)
    diagnostic = settlement_worker.diagnose_dual_fee_sale_account(db_session, order)
    assert diagnostic.match is None
    assert diagnostic.reason_code == "openapi_poi_mapping_ambiguous"


def test_openapi_sale_fallback_reads_without_changing_binding_or_permissions(db_session: Session) -> None:
    order, binding = _load_openapi_sale_binding_fixture(db_session)
    before = dict(binding.raw_payload)
    statements = []

    def watch(_conn, _cursor, statement, _params, _context, _executemany):
        if statement.lstrip().lower().startswith(("insert", "update", "delete")):
            statements.append(statement)

    connection = db_session.connection()
    event.listen(connection, "before_cursor_execute", watch)
    try:
        diagnostic = settlement_worker.diagnose_dual_fee_sale_account(db_session, order)
    finally:
        event.remove(connection, "before_cursor_execute", watch)

    assert diagnostic.match is not None
    assert statements == []
    assert binding.raw_payload == before
    assert db_session.get(DimAwemeAccount, order.owner_account_id) is None
    assert not db_session.new and not db_session.dirty


def test_openapi_sale_fallback_materializes_fees_and_keeps_historical_decision_priority(
    db_session: Session, monkeypatch,
) -> None:
    order, _binding = _load_openapi_sale_binding_fixture(db_session)
    rebuild_dual_fee_results(db_session, calculation_run_id="openapi-interval-fees")
    assert _fee_result(db_session, "coupon-dual", 1).sale_store_id == "store-sale"
    assert _fee_result(db_session, "coupon-dual", 2).sale_store_id == "store-sale"

    coupon = db_session.scalar(select(RawDouyinOrderCoupon))
    verify = settlement_worker._select_valid_verify_record(db_session, coupon.coupon_id)
    identity = sale_history._live_identity(order, coupon, verify, "store-verify")
    sale_history.import_decisions(db_session, {
        "batch_id": "synthetic-history-priority", "actor": "synthetic-operator",
        "evidence_sha256": "a" * 64,
        "approval_evidence": {"issue": "DYDATA-104", "approval": "synthetic review"},
        "rows": [{**identity, "approved_business_months": ["2026-09"]}],
    }, apply=True)

    def reject_ordinary_lookup(*args, **kwargs):
        raise AssertionError("a historical decision must precede all ordinary attribution")

    monkeypatch.setattr(settlement_worker, "_diagnose_dual_fee_sale_account", reject_ordinary_lookup)
    rebuild_dual_fee_results(db_session, calculation_run_id="openapi-history-priority")
    assert _fee_result(db_session, "coupon-dual", 1).sale_store_id == "store-verify"
    assert _fee_result(db_session, "coupon-dual", 2).sale_store_id == "store-verify"


def test_newer_inactive_fee_rule_suppresses_older_active_rule(
    db_session: Session,
) -> None:
    _load_dual_fee_fixture(db_session)
    _add_fee_rule(
        db_session,
        "fee-sep-disabled",
        date(2026, 9, 2),
        promotion="0.900000",
        management="0.900000",
        status=2,
    )
    db_session.flush()

    rebuild_dual_fee_results(db_session, calculation_run_id="dual-calc-disabled")

    assert _fee_result(db_session, "coupon-dual", 1) is None
    management = _fee_result(db_session, "coupon-dual", 2)
    assert management is None


def test_missing_verification_blocks_both_directions_and_rerun_is_idempotent(
    db_session: Session,
) -> None:
    _load_dual_fee_fixture(db_session, with_verify=False)

    rebuild_dual_fee_results(db_session, calculation_run_id="dual-calc-1")
    rebuild_dual_fee_results(db_session, calculation_run_id="dual-calc-1")

    assert _fee_result(db_session, "coupon-dual", 1) is None
    assert _fee_result(db_session, "coupon-dual", 2) is None
    assert count(db_session, SettlementFeeResult) == 0
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
    assert [row.adjustment_fee_cent for row in first_adjustments] == [-1200, -800]

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
    assert [row.adjustment_fee_cent for row in adjustments[2:]] == [-1800, -1200]
    assert [row.adjustment_type for row in adjustments[2:]] == [2, 2]
    assert [row.adjustment_posting_month for row in adjustments[2:]] == [
        "2026-11",
        "2026-11",
    ]


def test_cancelled_verification_adjusts_both_directions_at_original_rates(
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
    all_adjustments = list(db_session.scalars(select(SettlementFeeAdjustment)))
    assert len(all_adjustments) == 2
    promotion_adjustments = [row for row in all_adjustments if row.fee_direction == 1]
    assert promotion_adjustments[0].adjustment_fee_cent == -3000
    adjustments = [row for row in all_adjustments if row.fee_direction == 2]
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
            SettlementFeeAdjustment.adjustment_type == 3,
            SettlementFeeAdjustment.fee_direction == 2,
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
        "fee-sep-recalculated",
        date(2026, 9, 2),
        promotion="0.500000",
        management="0.200000",
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
    september_sale = monthly_projection(db_session, "2026-09", "store-sale", "all")
    september = monthly_projection(db_session, "2026-09", "store-verify", "all")
    october_sale = monthly_projection(db_session, "2026-10", "store-sale", "all")
    october_verify = monthly_projection(db_session, "2026-10", "store-verify", "all")
    assert september_sale is not None
    assert september is not None
    assert september_sale.promotion_original_fee_cent == 5000
    assert september_sale.promotion_adjustment_fee_cent == 0
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
        "fee-sep-new",
        date(2026, 9, 2),
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
    assert recalculated.rule_version == "fee-sep-new"
    assert recalculated.fee_result_id != original.fee_result_id
    assert original.result_status == 2

    db_session.add(
        SettlementStatement(
            statement_id="statement-sale-2026-09",
            store_id="store-sale",
            statement_month="2026-09",
            statement_status=4,
            lock_version="lock-sale-2026-09",
            locked_by="test",
            locked_at=_dual_time(10, 1),
        )
    )
    _add_fee_rule(
        db_session,
        "fee-sep-latest",
        date(2026, 9, 4),
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
    assert promotion.scope_rule_version == "scope-2026-09-short_video"


def test_dual_fee_non_commission_rule_uses_order_owner_not_product_owner(
    db_session: Session,
) -> None:
    _load_dual_fee_fixture(db_session)
    product = db_session.scalar(
        select(DimSkuProductRule).where(DimSkuProductRule.sku_id == "sku-dual")
    )
    assert product is not None
    product.owner_account_id = "product-owner-byd"
    product.owner_account_name = "比亚迪汽车销售有限公司"
    for scope_rule in db_session.scalars(select(SettlementScopeRule)):
        scope_rule.owner_account_id = "product-owner-byd"

    upsert_aweme_account(
        db_session,
        "owner-byd",
        nickname="比亚迪汽车销售有限公司",
        store_id="store-sale",
        binding_status="active",
    )
    upsert_raw_order(
        db_session,
        "order-coupon-excluded",
        order_status="paid",
        order_status_raw="paid",
        order_status_normalized="paid",
        sku_id="sku-dual",
        pay_time=_dual_time(8, 10),
        sale_time=_dual_time(8, 10),
        paid_amount_cent=10001,
        order_paid_amount_cent=10001,
        owner_account_id="owner-byd",
        owner_account_name="比亚迪汽车销售有限公司",
        sale_channel="short_video",
        sale_channel_raw="short_video",
        sale_channel_normalized="short_video",
        source_run_id="dual-source",
    )
    upsert_order_coupon(
        db_session,
        "coupon-excluded",
        "order-coupon-excluded",
        coupon_status="fulfilled",
        coupon_status_raw="fulfilled",
        coupon_status_normalized="available",
        coupon_paid_amount_cent=10001,
        coupon_refunded_amount_cent=0,
        source_run_id="dual-source",
    )
    upsert_verify_record(
        db_session,
        "verify-coupon-excluded",
        coupon_id="coupon-excluded",
        verify_status="valid",
        verify_time=_dual_time(9, 5),
        poi_id="poi-verify",
        sku_id="sku-dual",
        paid_amount_cent=10001,
        source_run_id="dual-source",
    )
    db_session.merge(
        DimNonCommissionOwnerAccount(
            normalized_owner_account_name=normalize_owner_account_name(
                "比亚迪汽车销售有限公司"
            ),
            owner_account_name="比亚迪汽车销售有限公司",
            is_active=True,
        )
    )
    db_session.flush()

    rebuild_dual_fee_results(db_session, calculation_run_id="dual-order-owner-rule")

    assert _fee_result(db_session, "coupon-dual", 1) is not None
    assert _fee_result(db_session, "coupon-dual", 2) is not None
    assert _fee_result(db_session, "coupon-excluded", 1) is None
    assert _fee_result(db_session, "coupon-excluded", 2) is None
    blocked_issues = list(
        db_session.scalars(
            select(DataQualityIssue).where(
                DataQualityIssue.coupon_id == "coupon-excluded",
                DataQualityIssue.issue_type == "dual_fee_non_commission_owner",
            )
        )
    )
    assert len(blocked_issues) == 2


def test_statement_lock_freezes_result_entry_line_and_head_idempotently(
    db_session: Session,
) -> None:
    _load_dual_fee_fixture(db_session, amount_cent=10000)
    db_session.add(
        StoreFinanceProfile(
            profile_id="profile-store-sale-v1",
            store_id="store-sale",
            profile_type=1,
            source_type=1,
            version_no=1,
            is_current=True,
            store_name_snapshot="Store Sale",
            sap_code="SAP-SALE-001",
            import_batch_id=None,
            created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )
    )
    db_session.flush()
    rebuild_dual_fee_results(db_session, calculation_run_id="statement-calc")

    first = lock_settlement_statement(
        db_session,
        store_id="store-sale",
        statement_month="2026-09",
        lock_run_id="statement-lock-1",
    )
    second = lock_settlement_statement(
        db_session,
        store_id="store-sale",
        statement_month="2026-09",
        lock_run_id="statement-lock-2",
    )

    assert second.statement_id == first.statement_id
    assert first.statement_status == 4
    assert first.lock_version is not None
    assert first.promotion_original_fee_cent == 3000
    assert first.promotion_adjustment_fee_cent == 0
    assert first.promotion_net_fee_cent == 3000
    assert first.management_net_fee_cent == 0
    assert first.store_name_snapshot == "Sale Store"
    assert first.sap_code_snapshot == "SAP-SALE-001"
    assert first.store_snapshot_status == "LIVE_CAPTURED"
    assert first.store_snapshot_profile_id == "profile-store-sale-v1"
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
    assert lines[0].net_fee_cent == 3000
    assert entries[0].source_type == 1
    assert entries[0].source_record_id == _fee_result(
        db_session, "coupon-dual", 1
    ).fee_result_id
    assert entries[0].order_status_snapshot == "paid"
    assert entries[0].coupon_status_snapshot == "available"
    assert entries[0].product_name_snapshot == "Dual fee product"
    assert entries[0].sku_id_snapshot == "sku-dual"
    assert entries[0].sku_name_snapshot == "Dual fee SKU"
    assert entries[0].sale_channel_snapshot == "short_video"
    assert entries[0].sale_store_id_snapshot == "store-sale"
    assert entries[0].sale_store_snapshot == "Sale Store"
    assert entries[0].verify_store_id_snapshot == "store-verify"
    assert entries[0].verify_store_snapshot == "Verify Store"
    assert entries[0].sale_time_snapshot == _dual_time(8, 10).replace(tzinfo=None)
    assert entries[0].verify_time_snapshot == _dual_time(9, 5).replace(tzinfo=None)
    assert entries[0].received_amount_cent_snapshot == 10000
    assert entries[0].fee_rate_snapshot == Decimal("0.300000")
    assert count(db_session, SettlementStatement) == 1
    assert count(db_session, SettlementStatementLine) == 1
    assert count(db_session, SettlementStatementEntry) == 1

    store = db_session.get(dy_models.DimStore, "store-sale")
    profile = db_session.scalar(
        select(StoreFinanceProfile).where(
            StoreFinanceProfile.profile_id == "profile-store-sale-v1"
        )
    )
    assert store is not None
    assert profile is not None
    store.store_name = "Renamed Store Sale"
    profile.sap_code = "SAP-SALE-999"
    db_session.flush()
    frozen_again = lock_settlement_statement(
        db_session,
        store_id="store-sale",
        statement_month="2026-09",
        lock_run_id="statement-lock-after-master-change",
    )
    assert frozen_again.store_name_snapshot == "Sale Store"
    assert frozen_again.sap_code_snapshot == "SAP-SALE-001"
    assert frozen_again.store_snapshot_profile_id == "profile-store-sale-v1"

    upsert_store(db_session, "store-sale-moved", "Moved Sale Store")
    sale_account = db_session.get(DimAwemeAccount, "owner-dual")
    assert sale_account is not None
    sale_account.store_id = "store-sale-moved"
    _add_fee_rule(
        db_session,
        "fee-sep-after-lock",
        date(2026, 9, 2),
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


def test_unlocked_statement_rebuild_keeps_original_store_snapshot(
    db_session: Session,
) -> None:
    _load_dual_fee_fixture(db_session, amount_cent=10000)
    rebuild_dual_fee_results(db_session, calculation_run_id="snapshot-unlocked-calc")
    db_session.add(
        SettlementStatement(
            statement_id="statement-unlocked-snapshot",
            store_id="store-sale",
            statement_month="2026-09",
            version_no=1,
            is_current=True,
            statement_status=1,
            store_name_snapshot="Frozen Store Sale",
            sap_code_snapshot="SAP-FROZEN-001",
            store_snapshot_status="LIVE_CAPTURED",
            store_snapshot_profile_id="profile-at-first-create",
        )
    )
    store = db_session.get(dy_models.DimStore, "store-sale")
    assert store is not None
    store.store_name = "Current Store Sale"
    db_session.flush()

    statement = lock_settlement_statement(
        db_session,
        store_id="store-sale",
        statement_month="2026-09",
        lock_run_id="snapshot-unlocked-lock",
    )

    assert statement.statement_id == "statement-unlocked-snapshot"
    assert statement.store_name_snapshot == "Frozen Store Sale"
    assert statement.sap_code_snapshot == "SAP-FROZEN-001"
    assert statement.store_snapshot_profile_id == "profile-at-first-create"


def test_statement_lock_queries_only_the_current_statement_version(
    db_session: Session,
) -> None:
    _load_dual_fee_fixture(db_session, amount_cent=10000)
    rebuild_dual_fee_results(db_session, calculation_run_id="current-statement-calc")
    db_session.add_all(
        [
            SettlementStatement(
                statement_id="statement-history-locked",
                store_id="store-sale",
                statement_month="2026-09",
                version_no=1,
                is_current=False,
                statement_status=4,
            ),
            SettlementStatement(
                statement_id="statement-current-unlocked",
                store_id="store-sale",
                statement_month="2026-09",
                version_no=2,
                is_current=True,
                supersedes_statement_id="statement-history-locked",
                statement_status=1,
            ),
        ]
    )
    db_session.flush()

    assert settlement_worker._locked_statement(db_session, "store-sale", "2026-09") is None
    statement = lock_settlement_statement(
        db_session,
        store_id="store-sale",
        statement_month="2026-09",
        lock_run_id="current-statement-lock",
    )

    assert statement.statement_id == "statement-current-unlocked"
    assert statement.is_current is True
    assert statement.statement_status == 4


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
        statement_month="2026-09",
        lock_run_id="shared-lock-statement",
    )

    assert acquired.count(("store-sale", "2026-09")) >= 2


def test_locked_month_blocks_first_result_for_late_coupon(
    db_session: Session,
) -> None:
    _load_dual_fee_fixture(db_session, amount_cent=10000)
    lock_settlement_statement(
        db_session,
        store_id="store-sale",
        statement_month="2026-09",
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


def test_locked_refund_creates_immutable_carryforward_sources(
    db_session: Session,
) -> None:
    _load_dual_fee_fixture(db_session, amount_cent=10000)
    rebuild_dual_fee_results(db_session, calculation_run_id="carryforward-base")
    for store_id in ("store-sale", "store-verify"):
        lock_settlement_statement(
            db_session,
            store_id=store_id,
            statement_month="2026-10",
            lock_run_id=f"carryforward-lock-{store_id}",
        )
    db_session.add(
        DouyinRefundEvent(
            refund_event_id="refund-carryforward-source",
            order_id="order-coupon-dual",
            coupon_id="coupon-dual",
            refund_type=1,
            refund_status=2,
            refund_amount_cent=1000,
            occurred_at=_dual_time(10, 20),
            source_run_id="carryforward-refund",
            raw_payload={},
        )
    )
    db_session.flush()

    rebuild_dual_fee_results(db_session, calculation_run_id="carryforward-calc")

    source_model = getattr(dy_models, "SettlementCarryforwardSource", None)
    assert source_model is not None, "locked refunds require immutable carryforward sources"
    sources = list(
        db_session.scalars(
            select(source_model).order_by(source_model.fee_direction)
        )
    )
    assert len(sources) == 2
    assert [source.fee_direction for source in sources] == [1, 2]
    assert [source.adjustment_base_cent for source in sources] == [-1000, -1000]
    assert [source.adjustment_fee_cent for source in sources] == [-300, -200]
    assert {source.event_month for source in sources} == {"2026-10"}
    assert not list(db_session.scalars(select(SettlementFeeAdjustment)))


def test_carryforward_applies_once_after_consecutive_locked_months(
    db_session: Session,
) -> None:
    _load_dual_fee_fixture(db_session, amount_cent=10000)
    rebuild_dual_fee_results(db_session, calculation_run_id="carryforward-apply-base")
    for month in ("2026-10", "2026-11"):
        for store_id in ("store-sale", "store-verify"):
            lock_settlement_statement(
                db_session,
                store_id=store_id,
                statement_month=month,
                lock_run_id=f"carryforward-apply-lock-{month}-{store_id}",
            )
    db_session.add(
        DouyinRefundEvent(
            refund_event_id="refund-carryforward-apply",
            order_id="order-coupon-dual",
            coupon_id="coupon-dual",
            refund_type=1,
            refund_status=2,
            refund_amount_cent=1000,
            occurred_at=_dual_time(10, 20),
            source_run_id="carryforward-apply-refund",
            raw_payload={},
        )
    )
    db_session.flush()
    rebuild_dual_fee_results(
        db_session, calculation_run_id="carryforward-apply-calc"
    )

    target_statements = {
        lock_settlement_statement(
            db_session,
            store_id=store_id,
            statement_month="2026-12",
            lock_run_id=f"carryforward-apply-december-{store_id}",
        ).statement_id
        for store_id in ("store-sale", "store-verify")
    }

    source_model = dy_models.SettlementCarryforwardSource
    application_model = dy_models.SettlementCarryforwardApplication
    sources = list(db_session.scalars(select(source_model)))
    applications = list(db_session.scalars(select(application_model)))
    adjustments = list(db_session.scalars(select(SettlementFeeAdjustment)))
    assert len(sources) == 2
    assert len(applications) == 2
    assert {row.carryforward_source_id for row in applications} == {
        row.carryforward_source_id for row in sources
    }
    assert {row.target_statement_id for row in applications} == target_statements
    assert {row.target_posting_month for row in applications} == {"2026-12"}
    assert {row.application_version for row in applications} == {1}
    assert all(row.is_current for row in applications)
    assert len(adjustments) == 2
    assert {row.adjustment_posting_month for row in adjustments} == {"2026-12"}
    assert {row.adjustment_base_cent for row in adjustments} == {-1000}
    assert {row.adjustment_fee_cent for row in adjustments} == {-300, -200}
    target_rows = list(
        db_session.scalars(
            select(SettlementStatement).where(
                SettlementStatement.statement_id.in_(target_statements)
            )
        )
    )
    assert sum(row.promotion_adjustment_fee_cent for row in target_rows) == -300
    assert sum(row.management_adjustment_fee_cent for row in target_rows) == -200
    carryforward_entry_ids = set(
        db_session.scalars(
            select(SettlementStatementEntry.source_record_id).where(
                SettlementStatementEntry.statement_id.in_(target_statements),
                SettlementStatementEntry.source_type == 2,
            )
        )
    )
    assert carryforward_entry_ids == {
        row.target_adjustment_id for row in applications
    }

    rebuild_dual_fee_results(
        db_session, calculation_run_id="carryforward-apply-repeat"
    )
    for store_id in ("store-sale", "store-verify"):
        lock_settlement_statement(
            db_session,
            store_id=store_id,
            statement_month="2026-12",
            lock_run_id=f"carryforward-apply-repeat-{store_id}",
        )
    assert count(db_session, source_model) == 2
    assert count(db_session, application_model) == 2
    assert count(db_session, SettlementFeeAdjustment) == 2

    management_pointer = db_session.scalar(
        select(SettlementFeeResultCurrent).where(
            SettlementFeeResultCurrent.coupon_id == "coupon-dual",
            SettlementFeeResultCurrent.fee_direction == 2,
        )
    )
    assert management_pointer is not None
    management_pointer.fee_result_id = "superseding-fee-result-not-yet-materialized"
    db_session.flush()
    frozen_sources = settlement_worker._statement_sources(
        db_session,
        store_id="store-verify",
        statement_month="2026-12",
    )
    assert [row.fee_amount_cent for row in frozen_sources if row.source_type == 2] == [
        -200
    ]
    assert "2026-12" in settlement_worker._projection_months(db_session)


def test_invoice_facts_make_event_month_immutable_without_locked_statement(
    db_session: Session,
) -> None:
    _load_dual_fee_fixture(db_session, amount_cent=10000)
    rebuild_dual_fee_results(db_session, calculation_run_id="invoice-fact-base")
    db_session.add_all(
        [
            dy_models.PromotionInvoiceAllocation(
                allocation_id="allocation-immutable-october",
                invoice_id="promotion-invoice-immutable-october",
                store_id="store-sale",
                statement_id="promotion-statement-immutable-october",
                statement_month="2026-10",
                settlement_batch_month="2026-09",
                allocated_amount_cent=123,
                is_current=True,
            ),
            dy_models.InvoiceRecord(
                invoice_id="management-invoice-immutable-october",
                store_id="store-verify",
                statement_month="2026-10",
                statement_id="management-statement-immutable-october",
                fee_direction=2,
                version_no=1,
                is_current=True,
                invoice_number="12345678901234567890",
                invoice_date=date(2026, 10, 10),
                invoice_amount_cent=2000,
                invoice_status=3,
                source_type=2,
                factory_deduction_date=date(2026, 10, 10),
                factory_deduction_amount_cent=2000,
                registered_by="finance-admin",
            ),
            dy_models.PromotionInvoiceAllocation(
                allocation_id="allocation-immutable-november",
                invoice_id="promotion-invoice-immutable-november",
                store_id="store-sale",
                statement_id="promotion-statement-immutable-november",
                statement_month="2026-11",
                settlement_batch_month="2026-10",
                allocated_amount_cent=123,
                is_current=True,
            ),
            dy_models.InvoiceRecord(
                invoice_id="management-invoice-immutable-november",
                store_id="store-verify",
                statement_month="2026-11",
                statement_id="management-statement-immutable-november",
                fee_direction=2,
                version_no=1,
                is_current=True,
                invoice_number="12345678901234567891",
                invoice_date=date(2026, 11, 10),
                invoice_amount_cent=2000,
                invoice_status=3,
                source_type=2,
                factory_deduction_date=date(2026, 11, 10),
                factory_deduction_amount_cent=2000,
                registered_by="finance-admin",
            ),
            DouyinRefundEvent(
                refund_event_id="refund-after-invoice-facts",
                order_id="order-coupon-dual",
                coupon_id="coupon-dual",
                refund_type=1,
                refund_status=2,
                refund_amount_cent=1000,
                occurred_at=_dual_time(10, 20),
                source_run_id="invoice-fact-refund",
                raw_payload={},
            ),
        ]
    )
    db_session.flush()

    rebuild_dual_fee_results(db_session, calculation_run_id="invoice-fact-calc")

    sources = list(
        db_session.scalars(select(dy_models.SettlementCarryforwardSource))
    )
    assert len(sources) == 2
    assert {row.fee_direction for row in sources} == {1, 2}
    assert not list(db_session.scalars(select(SettlementFeeAdjustment)))
    issues = list(
        db_session.scalars(
            select(DataQualityIssue).where(
                DataQualityIssue.source_run_id == "invoice-fact-calc",
                DataQualityIssue.issue_type
                == "dual_fee_locked_adjustment_posting_month",
            )
        )
    )
    assert len(issues) == 2
    assert {row.severity for row in issues} == {"warning"}
    for store_id in ("store-sale", "store-verify"):
        lock_settlement_statement(
            db_session,
            store_id=store_id,
            statement_month="2026-12",
            lock_run_id=f"invoice-fact-december-{store_id}",
        )
    assert count(db_session, dy_models.SettlementCarryforwardApplication) == 2
    assert {
        row.target_posting_month
        for row in db_session.scalars(
            select(dy_models.SettlementCarryforwardApplication)
        )
    } == {"2026-12"}


def test_pending_refund_then_cancellation_reaches_zero_without_double_counting(
    db_session: Session,
) -> None:
    _load_dual_fee_fixture(db_session, amount_cent=10000)
    rebuild_dual_fee_results(db_session, calculation_run_id="combined-base")
    for month in ("2026-10", "2026-11"):
        for store_id in ("store-sale", "store-verify"):
            lock_settlement_statement(
                db_session,
                store_id=store_id,
                statement_month=month,
                lock_run_id=f"combined-lock-{month}-{store_id}",
            )
    db_session.add(
        DouyinRefundEvent(
            refund_event_id="refund-before-cancellation",
            order_id="order-coupon-dual",
            coupon_id="coupon-dual",
            refund_type=1,
            refund_status=2,
            refund_amount_cent=1000,
            occurred_at=_dual_time(10, 19),
            source_run_id="combined-refund",
            raw_payload={},
        )
    )
    verify = db_session.get(RawDouyinVerifyRecord, "verify-coupon-dual")
    assert verify is not None
    verify.verify_status = "cancelled"
    verify.cancel_time = _dual_time(10, 20)
    db_session.flush()

    rebuild_dual_fee_results(db_session, calculation_run_id="combined-calc")

    management_sources = list(
        db_session.scalars(
            select(dy_models.SettlementCarryforwardSource).where(
                dy_models.SettlementCarryforwardSource.fee_direction == 2
            )
        )
    )
    assert len(management_sources) == 2
    assert sum(row.adjustment_base_cent for row in management_sources) == -10000
    assert sum(row.adjustment_fee_cent for row in management_sources) == -2000

    target = lock_settlement_statement(
        db_session,
        store_id="store-verify",
        statement_month="2026-12",
        lock_run_id="combined-apply",
    )
    assert target.management_original_fee_cent == 0
    assert target.management_adjustment_fee_cent == -2000
    assert target.management_net_fee_cent == -2000
    management_adjustments = list(
        db_session.scalars(
            select(SettlementFeeAdjustment).where(
                SettlementFeeAdjustment.fee_direction == 2
            )
        )
    )
    assert sum(row.adjustment_base_cent for row in management_adjustments) == -10000
    assert sum(row.adjustment_fee_cent for row in management_adjustments) == -2000


def test_applied_source_then_later_refund_uses_each_delta_once(
    db_session: Session,
) -> None:
    _load_dual_fee_fixture(db_session, amount_cent=10000)
    rebuild_dual_fee_results(db_session, calculation_run_id="later-refund-base")
    for month in ("2026-10", "2026-11"):
        for store_id in ("store-sale", "store-verify"):
            lock_settlement_statement(
                db_session,
                store_id=store_id,
                statement_month=month,
                lock_run_id=f"later-refund-lock-{month}-{store_id}",
            )
    db_session.add(
        DouyinRefundEvent(
            refund_event_id="refund-first-locked",
            order_id="order-coupon-dual",
            coupon_id="coupon-dual",
            refund_type=1,
            refund_status=2,
            refund_amount_cent=1000,
            occurred_at=_dual_time(10, 20),
            source_run_id="later-refund-first",
            raw_payload={},
        )
    )
    db_session.flush()
    rebuild_dual_fee_results(db_session, calculation_run_id="later-refund-first-calc")
    december = {
        store_id: lock_settlement_statement(
            db_session,
            store_id=store_id,
            statement_month="2026-12",
            lock_run_id=f"later-refund-december-{store_id}",
        )
        for store_id in ("store-sale", "store-verify")
    }

    db_session.add(
        DouyinRefundEvent(
            refund_event_id="refund-second-after-application",
            order_id="order-coupon-dual",
            coupon_id="coupon-dual",
            refund_type=1,
            refund_status=2,
            refund_amount_cent=500,
            occurred_at=_dual_time(12, 20),
            source_run_id="later-refund-second",
            raw_payload={},
        )
    )
    db_session.flush()
    rebuild_dual_fee_results(db_session, calculation_run_id="later-refund-second-calc")
    january = {
        store_id: lock_settlement_statement(
            db_session,
            store_id=store_id,
            statement_month="2027-01",
            lock_run_id=f"later-refund-january-{store_id}",
        )
        for store_id in ("store-sale", "store-verify")
    }

    assert december["store-sale"].promotion_adjustment_fee_cent == -300
    assert december["store-verify"].management_adjustment_fee_cent == -200
    assert january["store-sale"].promotion_adjustment_fee_cent == -150
    assert january["store-verify"].management_adjustment_fee_cent == -100
    adjustments = list(db_session.scalars(select(SettlementFeeAdjustment)))
    assert sum(
        row.adjustment_base_cent for row in adjustments if row.fee_direction == 1
    ) == -1500
    assert sum(
        row.adjustment_base_cent for row in adjustments if row.fee_direction == 2
    ) == -1500
    assert count(db_session, dy_models.SettlementCarryforwardSource) == 4
    assert count(db_session, dy_models.SettlementCarryforwardApplication) == 4


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

    adjustments = list(db_session.scalars(select(SettlementFeeAdjustment)))
    assert [row.fee_direction for row in adjustments] == [1]
    issue = db_session.scalar(
        select(DataQualityIssue).where(
            DataQualityIssue.issue_type
            == "dual_fee_locked_adjustment_posting_month",
            DataQualityIssue.source_run_id == "late-cancel-calc",
        )
    )
    assert issue is not None
    assert issue.raw_context_json["verify_id"] == "verify-coupon-dual"


def test_locked_cancellation_carries_management_fee_forward_once(
    db_session: Session,
) -> None:
    _load_dual_fee_fixture(db_session, amount_cent=10000)
    rebuild_dual_fee_results(db_session, calculation_run_id="cancel-carry-base")
    for month in ("2026-10", "2026-11"):
        lock_settlement_statement(
            db_session,
            store_id="store-verify",
            statement_month=month,
            lock_run_id=f"cancel-carry-lock-{month}",
        )
    verify = db_session.get(RawDouyinVerifyRecord, "verify-coupon-dual")
    assert verify is not None
    verify.verify_status = "cancelled"
    verify.cancel_time = _dual_time(10, 20)
    db_session.flush()

    rebuild_dual_fee_results(db_session, calculation_run_id="cancel-carry-source")

    source_model = dy_models.SettlementCarryforwardSource
    application_model = dy_models.SettlementCarryforwardApplication
    sources = list(db_session.scalars(select(source_model)))
    assert len(sources) == 1
    assert sources[0].fee_direction == 2
    assert sources[0].verify_id == "verify-coupon-dual"
    assert sources[0].refund_event_id is None
    assert sources[0].adjustment_base_cent == -10000
    assert sources[0].adjustment_fee_cent == -2000
    promotion_adjustments = list(db_session.scalars(select(SettlementFeeAdjustment)))
    assert [row.fee_direction for row in promotion_adjustments] == [1]
    assert promotion_adjustments[0].adjustment_fee_cent == -3000

    target = lock_settlement_statement(
        db_session,
        store_id="store-verify",
        statement_month="2026-12",
        lock_run_id="cancel-carry-apply",
    )
    applications = list(db_session.scalars(select(application_model)))
    adjustments = list(db_session.scalars(select(SettlementFeeAdjustment).where(
        SettlementFeeAdjustment.fee_direction == 2,
    )))
    assert len(applications) == 1
    assert applications[0].carryforward_source_id == sources[0].carryforward_source_id
    assert applications[0].target_statement_id == target.statement_id
    assert applications[0].target_posting_month == "2026-12"
    assert applications[0].application_version == 1
    assert applications[0].is_current is True
    assert len(adjustments) == 1
    assert adjustments[0].fee_direction == 2
    assert adjustments[0].adjustment_type == 3
    assert adjustments[0].adjustment_posting_month == "2026-12"

    rebuild_dual_fee_results(db_session, calculation_run_id="cancel-carry-repeat")
    lock_settlement_statement(
        db_session,
        store_id="store-verify",
        statement_month="2026-12",
        lock_run_id="cancel-carry-repeat-apply",
    )
    assert count(db_session, source_model) == 1
    assert count(db_session, application_model) == 1
    assert count(db_session, SettlementFeeAdjustment) == 2


def test_post_lock_refund_enters_event_month_without_changing_original_statements(
    db_session: Session,
) -> None:
    _load_dual_fee_fixture(db_session, amount_cent=10000)
    rebuild_dual_fee_results(db_session, calculation_run_id="statement-calc")
    promotion_statement = lock_settlement_statement(
        db_session,
        store_id="store-sale",
        statement_month="2026-09",
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

    assert promotion_statement.promotion_net_fee_cent == 3000
    assert management_statement.management_net_fee_cent == 2000
    assert promotion_adjustment_statement.promotion_original_fee_cent == 0
    assert promotion_adjustment_statement.promotion_adjustment_fee_cent == -1200
    assert promotion_adjustment_statement.promotion_net_fee_cent == -1200
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
        statement_month="2026-09",
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

    september_sale = monthly_projection(db_session, "2026-09", "store-sale", "all")
    september_verify = monthly_projection(
        db_session, "2026-09", "store-verify", "all"
    )
    october_sale = monthly_projection(db_session, "2026-10", "store-sale", "all")
    october_verify = monthly_projection(
        db_session, "2026-10", "store-verify", "all"
    )
    assert september_sale is not None
    assert september_sale.sales_order_count == 1
    assert september_sale.sales_amount_cent == 10000
    assert september_sale.promotion_base_cent == 10000
    assert september_sale.promotion_original_fee_cent == 3000
    assert september_sale.promotion_net_fee_cent == 3000
    assert september_sale.statement_status == 4
    assert september_verify is not None
    assert september_verify.verified_order_count == 1
    assert september_verify.verified_amount_cent == 10000
    assert september_verify.management_original_fee_cent == 2000
    assert september_verify.management_net_fee_cent == 2000
    assert october_sale is not None
    assert october_sale.promotion_base_cent == -4001
    assert october_sale.promotion_adjustment_fee_cent == -1200
    assert october_sale.promotion_net_fee_cent == -1200
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
    assert cumulative_sale.promotion_net_fee_cent == 1800
    assert cumulative_sale.net_settlement_reference_cent == 1800
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
    before = monthly_projection(db_session, "2026-09", "store-sale", "all")
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

    after = monthly_projection(db_session, "2026-09", "store-sale", "all")
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
