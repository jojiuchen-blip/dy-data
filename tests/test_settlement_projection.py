from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    AggStoreMonthlySettlement,
    SettlementFeeAdjustment,
    SettlementFeeResult,
    SettlementFeeResultCurrent,
    SettlementMonthlyOverlay,
    SettlementProjectionActive,
    SettlementProjectionGeneration,
    SettlementProjectionPartitionManifest,
    SettlementRankingOverlay,
    SettlementStatement,
)
from apps.worker import settlement


def _seed_base(
    session: Session, *, prefix: str, legacy_months: tuple[str, ...] = ()
) -> str:
    base_generation_id = f"{prefix}-base"
    session.add(
        SettlementProjectionGeneration(
            generation_id=base_generation_id,
            generation_kind="legacy_root",
            projection_name="settlement",
            state="published",
            input_fingerprint=(prefix.encode("utf-8").hex() + "0" * 64)[:64],
            lineage_depth=0,
            checkpoint_json={},
            manifest_checksum="0" * 64,
            source_input_json={},
            published_at=datetime.now(timezone.utc),
        )
    )
    session.flush()
    session.add(
        SettlementProjectionActive(
            projection_name="settlement", generation_id=base_generation_id
        )
    )
    for index, month in enumerate(legacy_months, start=1):
        session.add(
            AggStoreMonthlySettlement(
                month=month,
                store_id=f"{prefix}-legacy-store",
                product_scope="all",
                product_type="all",
                sales_order_count=1,
                sales_amount_cent=100 * index,
                verified_order_count=1,
                verified_amount_cent=80 * index,
                promotion_base_cent=100 * index,
                promotion_original_fee_cent=10 * index,
                promotion_adjustment_fee_cent=0,
                promotion_net_fee_cent=10 * index,
                management_base_cent=80 * index,
                management_original_fee_cent=4 * index,
                management_adjustment_fee_cent=0,
                management_net_fee_cent=4 * index,
                statement_status=1,
                projection_run_id=f"{prefix}-legacy-run",
            )
        )
    session.commit()
    return base_generation_id


def _fee_result(
    *,
    result_id: str,
    coupon_id: str,
    direction: int,
    version: int,
    month: str,
    store_id: str,
    source_amount: int,
    fee_amount: int,
) -> SettlementFeeResult:
    return SettlementFeeResult(
        fee_result_id=result_id,
        coupon_id=coupon_id,
        order_id=f"order-{coupon_id}",
        fee_direction=direction,
        result_version=version,
        original_business_month=month,
        rule_match_date=date.fromisoformat(f"{month}-01"),
        sale_store_id=store_id if direction == 1 else None,
        verify_store_id=store_id if direction == 2 else None,
        sku_id="sku",
        product_scope="all",
        product_type="all",
        sale_channel_normalized="online",
        source_amount_cent=source_amount,
        refunded_amount_cent=0,
        fee_base_cent=source_amount,
        fee_rate=Decimal("0.100000"),
        fee_amount_cent=fee_amount,
        rule_version="rule-v1",
        scope_rule_version="scope-v1",
        result_status=1,
        calculation_run_id=f"run-{result_id}",
        calculated_at=datetime.now(timezone.utc),
    )


def _build(
    session: Session,
    *,
    generation_id: str,
    base_generation_id: str,
    affected_months: tuple[str, ...],
):
    assert hasattr(settlement, "build_settlement_sparse_overlay")
    return settlement.build_settlement_sparse_overlay(
        lambda: Session(bind=session.get_bind(), autoflush=False, future=True),
        generation_id=generation_id,
        base_generation_id=base_generation_id,
        affected_months=affected_months,
        batch_size=2,
        input_fingerprint=(generation_id.encode("utf-8").hex() + "f" * 64)[:64],
    )


def test_sparse_builder_claims_only_affected_month_and_complete_cumulative_suffix(
    db_session: Session,
):
    base = _seed_base(
        db_session,
        prefix="projection-suffix",
        legacy_months=("2026-09", "2026-10"),
    )
    legacy_before = db_session.scalars(
        select(AggStoreMonthlySettlement).order_by(AggStoreMonthlySettlement.month)
    ).all()
    legacy_snapshot = [
        (row.month, row.sales_amount_cent, row.promotion_net_fee_cent)
        for row in legacy_before
    ]

    result = _build(
        db_session,
        generation_id="projection-suffix-generation",
        base_generation_id=base,
        affected_months=("2026-08",),
    )

    db_session.expire_all()
    manifests = db_session.scalars(
        select(SettlementProjectionPartitionManifest)
        .where(
            SettlementProjectionPartitionManifest.generation_id
            == result.generation_id
        )
        .order_by(
            SettlementProjectionPartitionManifest.artifact,
            SettlementProjectionPartitionManifest.partition_key,
        )
    ).all()
    assert result.monthly_partitions == ("2026-08",)
    assert result.ranking_partitions == (
        "monthly:2026-08",
        "cumulative:2026-08",
        "cumulative:2026-09",
        "cumulative:2026-10",
    )
    assert {(row.artifact, row.partition_key) for row in manifests} == {
        ("monthly", "2026-08"),
        ("ranking", "monthly:2026-08"),
        ("ranking", "cumulative:2026-08"),
        ("ranking", "cumulative:2026-09"),
        ("ranking", "cumulative:2026-10"),
    }
    assert next(row for row in manifests if row.partition_key == "2026-08").source_kind == "tombstone"
    assert next(
        row for row in manifests if row.partition_key == "monthly:2026-08"
    ).source_kind == "tombstone"
    cumulative_08 = next(
        row for row in manifests if row.partition_key == "cumulative:2026-08"
    )
    assert cumulative_08.source_kind == "tombstone"
    cumulative_rows = db_session.scalars(
        select(SettlementRankingOverlay)
        .where(
            SettlementRankingOverlay.generation_id == result.generation_id,
            SettlementRankingOverlay.period_type == 2,
        )
        .order_by(SettlementRankingOverlay.period_key)
    ).all()
    assert [(row.period_key, row.sales_amount_cent) for row in cumulative_rows] == [
        ("2026-09", 100),
        ("2026-10", 300),
    ]
    assert db_session.scalar(
        select(func.count())
        .select_from(SettlementMonthlyOverlay)
        .where(SettlementMonthlyOverlay.generation_id == result.generation_id)
    ) == 0
    assert [
        (row.month, row.sales_amount_cent, row.promotion_net_fee_cent)
        for row in db_session.scalars(
            select(AggStoreMonthlySettlement).order_by(AggStoreMonthlySettlement.month)
        ).all()
    ] == legacy_snapshot


def test_sparse_builder_uses_immutable_adjustment_original_after_current_supersedes(
    db_session: Session,
):
    base = _seed_base(db_session, prefix="projection-adjustment")
    old = _fee_result(
        result_id="projection-adjustment-old",
        coupon_id="projection-adjustment-coupon",
        direction=1,
        version=1,
        month="2026-08",
        store_id="projection-adjustment-store",
        source_amount=100,
        fee_amount=10,
    )
    current = _fee_result(
        result_id="projection-adjustment-current",
        coupon_id="projection-adjustment-coupon",
        direction=1,
        version=2,
        month="2026-08",
        store_id="projection-adjustment-store",
        source_amount=500,
        fee_amount=50,
    )
    db_session.add_all([old, current])
    db_session.flush()
    db_session.add(
        SettlementFeeResultCurrent(
            coupon_id=current.coupon_id,
            fee_direction=1,
            fee_result_id=current.fee_result_id,
        )
    )
    db_session.add(
        SettlementFeeAdjustment(
            adjustment_id="projection-adjustment-a1",
            original_fee_result_id=old.fee_result_id,
            coupon_id=old.coupon_id,
            order_id=old.order_id,
            fee_direction=1,
            original_business_month="2026-08",
            adjustment_posting_month="2026-09",
            adjustment_type=1,
            adjustment_base_cent=-100,
            adjustment_fee_cent=-10,
            rule_version="rule-v1",
            adjustment_reason="cross-month correction",
            occurred_at=datetime.now(timezone.utc),
            created_by="test",
        )
    )
    db_session.commit()

    result = _build(
        db_session,
        generation_id="projection-adjustment-generation",
        base_generation_id=base,
        affected_months=("2026-08",),
    )
    db_session.expire_all()
    monthly = db_session.scalars(
        select(SettlementMonthlyOverlay)
        .where(SettlementMonthlyOverlay.generation_id == result.generation_id)
        .order_by(SettlementMonthlyOverlay.month)
    ).all()
    all_rows = [
        row
        for row in monthly
        if row.product_scope == "all" and row.product_type == "all"
    ]
    assert [(row.month, row.promotion_original_fee_cent, row.promotion_adjustment_fee_cent) for row in all_rows] == [
        ("2026-08", 50, 0),
        ("2026-09", 0, -10),
    ]
    cumulative = db_session.scalar(
        select(SettlementRankingOverlay).where(
            SettlementRankingOverlay.generation_id == result.generation_id,
            SettlementRankingOverlay.period_type == 2,
            SettlementRankingOverlay.period_key == "2026-09",
            SettlementRankingOverlay.product_scope == "all",
            SettlementRankingOverlay.product_type == "all",
        )
    )
    assert cumulative is not None
    assert cumulative.promotion_net_fee_cent == 40


def test_sparse_builder_is_idempotent_for_same_generation(db_session: Session):
    base = _seed_base(
        db_session, prefix="projection-retry", legacy_months=("2026-08",)
    )
    first = _build(
        db_session,
        generation_id="projection-retry-generation",
        base_generation_id=base,
        affected_months=("2026-08",),
    )
    first_snapshot = (
        db_session.scalar(
            select(func.count())
            .select_from(SettlementProjectionPartitionManifest)
            .where(
                SettlementProjectionPartitionManifest.generation_id
                == first.generation_id
            )
        ),
        first.manifest_checksum,
    )

    second = _build(
        db_session,
        generation_id="projection-retry-generation",
        base_generation_id=base,
        affected_months=("2026-08",),
    )
    assert second.generation_id == first.generation_id
    assert second.resumed is True
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(SettlementProjectionPartitionManifest)
            .where(
                SettlementProjectionPartitionManifest.generation_id
                == first.generation_id
            )
        ),
        second.manifest_checksum,
    ) == first_snapshot


def test_sparse_builder_rejects_locked_affected_month_without_writes(
    db_session: Session,
):
    base = _seed_base(db_session, prefix="projection-locked")
    db_session.add(
        SettlementStatement(
            statement_id="projection-locked-statement",
            store_id="projection-locked-store",
            statement_month="2026-08",
            statement_status=4,
            lock_version="projection-locked-version",
        )
    )
    db_session.commit()
    assert hasattr(settlement, "LockedSettlementConflict")

    with pytest.raises(settlement.LockedSettlementConflict):
        _build(
            db_session,
            generation_id="projection-locked-generation",
            base_generation_id=base,
            affected_months=("2026-08",),
        )
    assert db_session.get(
        SettlementProjectionGeneration, "projection-locked-generation"
    ) is None
