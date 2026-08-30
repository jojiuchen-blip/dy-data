from __future__ import annotations

import inspect
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
from typing import Any, Callable

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.dy_api.models import (
    AggStoreMonthlySettlement,
    AggStoreRanking,
    Base,
    ClueAllocationRule,
    ClueAllocationRuleVersion,
    DimAwemeAccount,
    DimSkuProductRule,
    DimStore,
    DimStorePoiMapping,
    JobImpact,
    RawAwemeBinding,
    RawDouyinOrder,
    RawDouyinOrderCoupon,
    RawDouyinVerifyRecord,
    SettlementFeeAdjustment,
    SettlementFeeResult,
    SettlementFeeResultCurrent,
    SettlementMonthlyOverlay,
    SettlementProjectionActive,
    SettlementProjectionGeneration,
    SettlementProjectionPartitionManifest,
    SettlementRankingOverlay,
    SettlementScopeRule,
    SettlementStatement,
    SkuFeeRule,
    StoreScoreSnapshot,
    StoreScoreSnapshotGeneration,
    StoreScoreSnapshotRun,
)
from apps.worker import clue_allocation, daily_task, finalize, settlement
from apps.worker.legacy_projection_bootstrap import (
    ResourceGateConfig,
    _manifest_checksum,
    certify_legacy_null_root,
)
from apps.worker.projection_lineage import resolve_projection_partitions


def _sqlite_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )


@pytest.fixture()
def shadow_factories() -> tuple[sessionmaker[Session], sessionmaker[Session]]:
    shadow = _sqlite_factory()
    incremental = _sqlite_factory()
    try:
        yield shadow, incremental
    finally:
        shadow.kw["bind"].dispose()
        incremental.kw["bind"].dispose()


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    return value


def _digest(value: Any) -> str:
    payload = json.dumps(
        _canonical(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _seed_coupon_fixture(session: Session, *, source_run_id: str | None) -> None:
    observed = datetime(2026, 8, 7, 10, tzinfo=UTC)
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
        order_id="order-equivalence",
        order_status="paid",
        order_status_normalized="paid",
        sku_id="sku-service",
        product_name="Service",
        sale_channel="live",
        sale_channel_normalized="live",
        pay_time=observed,
        sale_time=observed,
        create_order_time=observed,
        paid_amount_cent=10_000,
        order_paid_amount_cent=10_000,
        owner_account_id="owner-sale",
        owner_account_name="Sale owner",
    )
    session.add(order)
    session.flush()
    session.add(
        RawDouyinOrderCoupon(
            coupon_id="coupon-equivalence",
            order_id=order.order_id,
            raw_order_id=order.id,
            coupon_status="fulfilled",
            coupon_status_normalized="fulfilled",
            coupon_paid_amount_cent=10_000,
        )
    )
    session.add(
        RawDouyinVerifyRecord(
            verify_id="verify-equivalence",
            coupon_id="coupon-equivalence",
            verify_status="valid",
            verify_time=observed,
            poi_id="poi-verify",
            sku_id="sku-service",
            paid_amount_cent=10_000,
        )
    )
    if source_run_id is not None:
        session.add(
            JobImpact(
                impact_key=f"equivalence:{source_run_id}",
                entity_type="coupon",
                entity_key="coupon-equivalence",
                old_values_json={},
                new_values_json={"coupon_id": "coupon-equivalence"},
                affected_closure_json={
                    "coupon_ids": ["coupon-equivalence"],
                    "order_ids": ["order-equivalence"],
                    "affected_months": ["2026-08"],
                    "store_ids": ["store-sale", "store-verify"],
                },
                source_run_id=source_run_id,
            )
        )
    session.commit()


def _seed_lineage(
    session: Session,
    *,
    prefix: str,
    published: bool = False,
) -> tuple[str, str]:
    base_generation_id = f"{prefix}-base"
    generation_id = f"{prefix}-generation"
    session.add(
        SettlementProjectionGeneration(
            generation_id=base_generation_id,
            generation_kind="legacy_root",
            projection_name="settlement",
            state="published",
            input_fingerprint=(prefix.encode().hex() + "0" * 64)[:64],
            lineage_depth=0,
            checkpoint_json={"phase": "published"},
            manifest_checksum=_manifest_checksum([]),
            source_input_json={},
            published_at=datetime.now(UTC),
        )
    )
    session.flush()
    session.add(
        SettlementProjectionGeneration(
            generation_id=generation_id,
            base_generation_id=base_generation_id,
            generation_kind="lineage",
            projection_name="settlement",
            state="published" if published else "staging",
            input_fingerprint=(generation_id.encode().hex() + "f" * 64)[:64],
            lineage_depth=1,
            checkpoint_json={"phase": "published" if published else "settlement_ready"},
            manifest_checksum=_manifest_checksum([]) if published else None,
            source_input_json={},
            published_at=datetime.now(UTC) if published else None,
        )
    )
    session.add(
        SettlementProjectionActive(
            projection_name="settlement",
            generation_id=generation_id if published else base_generation_id,
        )
    )
    session.commit()
    return base_generation_id, generation_id


_MONTHLY_FIELDS = (
    "month",
    "store_id",
    "product_scope",
    "product_type",
    "sales_order_count",
    "sales_amount_cent",
    "verified_order_count",
    "verified_amount_cent",
    "promotion_base_cent",
    "promotion_original_fee_cent",
    "promotion_adjustment_fee_cent",
    "promotion_net_fee_cent",
    "management_base_cent",
    "management_original_fee_cent",
    "management_adjustment_fee_cent",
    "management_net_fee_cent",
    "statement_status",
    "estimated_receivable_commission_cent",
    "commissionable_total_cent",
    "estimated_payable_commission_cent",
)
_RANKING_FIELDS = (
    "period_type",
    "period_key",
    "store_id",
    "store_name",
    "product_scope",
    "product_type",
    "sales_order_count",
    "sales_amount_cent",
    "verified_order_count",
    "verified_amount_cent",
    "promotion_net_fee_cent",
    "management_net_fee_cent",
    "net_settlement_reference_cent",
    "month",
    "self_sold_self_verified_count",
    "self_sold_other_verified_count",
    "other_sold_self_verified_count",
    "self_verify_income_cent",
    "effective_commission_income_cent",
)


def _rows(session: Session, model: type, fields: tuple[str, ...]) -> tuple[tuple[Any, ...], ...]:
    values = [tuple(getattr(row, field) for field in fields) for row in session.scalars(select(model))]
    return tuple(sorted(values, key=lambda row: tuple(str(value) for value in row)))


def _manifest_rows(
    session: Session,
    generation_id: str,
) -> dict[tuple[str, str], tuple[int, int, dict[str, int], str]]:
    return {
        (row.artifact, row.partition_key): (
            int(row.row_count),
            int(row.amount_total_cent),
            dict(row.status_counts_json or {}),
            str(row.checksum),
        )
        for row in session.scalars(
            select(SettlementProjectionPartitionManifest).where(
                SettlementProjectionPartitionManifest.generation_id == generation_id
            )
        )
    }


def test_shadow_equivalence_mapping_verify_coupon_monthly_ranking_partition_checksum(
    shadow_factories: tuple[sessionmaker[Session], sessionmaker[Session]],
) -> None:
    shadow_factory, incremental_factory = shadow_factories
    with shadow_factory() as session:
        _seed_coupon_fixture(session, source_run_id=None)
        settlement.rebuild_settlement(session, source_run_id="equivalence-shadow")
        session.commit()
    root = certify_legacy_null_root(
        shadow_factory,
        batch_size=20,
        resource_limits=ResourceGateConfig(
            max_manifest_rows=100,
            max_estimated_write_bytes=10_000_000,
            max_estimated_wal_bytes=20_000_000,
            observed_disk_headroom_bytes=100_000_000,
            min_disk_headroom_bytes=0,
        ),
    )
    assert root.status == "published"

    with incremental_factory() as session:
        _seed_coupon_fixture(session, source_run_id="equivalence-incremental")
    summary = settlement.settle_impacted_coupons(
        incremental_factory,
        "equivalence-incremental",
        lambda _session: True,
        impact_batch_size=1,
        coupon_batch_size=1,
    )
    assert summary["completed"] is True
    assert summary["affected_months"] == ["2026-08"]
    with incremental_factory() as session:
        base_id, generation_id = _seed_lineage(session, prefix="equivalence-rows")
    built = settlement.build_settlement_sparse_overlay(
        incremental_factory,
        generation_id=generation_id,
        base_generation_id=base_id,
        affected_months=("2026-08",),
        batch_size=2,
        input_fingerprint=(generation_id.encode().hex() + "f" * 64)[:64],
    )
    assert built.generation_id == generation_id

    with shadow_factory() as shadow, incremental_factory() as incremental:
        shadow_monthly = _rows(shadow, AggStoreMonthlySettlement, _MONTHLY_FIELDS)
        sparse_monthly = _rows(incremental, SettlementMonthlyOverlay, _MONTHLY_FIELDS)
        shadow_ranking = _rows(shadow, AggStoreRanking, _RANKING_FIELDS)
        sparse_ranking = _rows(incremental, SettlementRankingOverlay, _RANKING_FIELDS)
        assert sparse_monthly == shadow_monthly
        assert sparse_ranking == shadow_ranking
        assert _digest(sparse_monthly) == _digest(shadow_monthly)
        assert _digest(sparse_ranking) == _digest(shadow_ranking)
        assert incremental.scalar(
            select(func.count()).select_from(AggStoreMonthlySettlement)
        ) == 0
        root_manifests = _manifest_rows(shadow, root.generation_id)
        sparse_manifests = _manifest_rows(incremental, generation_id)
        assert {key: value[:3] for key, value in sparse_manifests.items()} == {
            key: root_manifests[key][:3] for key in sorted(sparse_manifests)
        }
        assert all(
            len(value[3]) == 64
            for value in (*root_manifests.values(), *sparse_manifests.values())
        )


def _fee_result(
    *,
    result_id: str,
    coupon_id: str,
    version: int,
    source_amount: int,
    fee_amount: int,
) -> SettlementFeeResult:
    return SettlementFeeResult(
        fee_result_id=result_id,
        coupon_id=coupon_id,
        order_id=f"order-{coupon_id}",
        fee_direction=1,
        result_version=version,
        original_business_month="2026-08",
        rule_match_date=date(2026, 8, 1),
        sale_store_id="adjustment-store",
        verify_store_id=None,
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
        calculated_at=datetime.now(UTC),
    )


def _seed_adjustment_authority(session: Session) -> None:
    old = _fee_result(
        result_id="adjustment-old",
        coupon_id="adjustment-coupon",
        version=1,
        source_amount=100,
        fee_amount=10,
    )
    current = _fee_result(
        result_id="adjustment-current",
        coupon_id="adjustment-coupon",
        version=2,
        source_amount=500,
        fee_amount=50,
    )
    session.add_all([old, current])
    session.flush()
    session.add(
        SettlementFeeResultCurrent(
            coupon_id=current.coupon_id,
            fee_direction=1,
            fee_result_id=current.fee_result_id,
        )
    )
    session.add(
        SettlementFeeAdjustment(
            adjustment_id="adjustment-cross-month",
            original_fee_result_id=current.fee_result_id,
            coupon_id=current.coupon_id,
            order_id=current.order_id,
            fee_direction=1,
            original_business_month="2026-08",
            adjustment_posting_month="2026-09",
            adjustment_type=1,
            adjustment_base_cent=-100,
            adjustment_fee_cent=-10,
            rule_version="rule-v1",
            adjustment_reason="cross-month correction",
            occurred_at=datetime.now(UTC),
            created_by="test",
        )
    )
    session.commit()


def test_shadow_equivalence_cross_month_adjustment_retry_and_locked_counterexample(
    shadow_factories: tuple[sessionmaker[Session], sessionmaker[Session]],
) -> None:
    shadow_factory, incremental_factory = shadow_factories
    with shadow_factory() as session:
        _seed_adjustment_authority(session)
        settlement.rebuild_dual_fee_projections(
            session,
            projection_run_id="adjustment-shadow",
            batch_size=2,
        )
        session.commit()
    with incremental_factory() as session:
        _seed_adjustment_authority(session)
        base_id, generation_id = _seed_lineage(session, prefix="adjustment-sparse")
    first = settlement.build_settlement_sparse_overlay(
        incremental_factory,
        generation_id=generation_id,
        base_generation_id=base_id,
        affected_months=("2026-08",),
        batch_size=2,
        input_fingerprint=(generation_id.encode().hex() + "f" * 64)[:64],
    )
    with incremental_factory() as session:
        first_snapshot = (
            _rows(session, SettlementMonthlyOverlay, _MONTHLY_FIELDS),
            _rows(session, SettlementRankingOverlay, _RANKING_FIELDS),
            _manifest_rows(session, generation_id),
        )
    second = settlement.build_settlement_sparse_overlay(
        incremental_factory,
        generation_id=generation_id,
        base_generation_id=base_id,
        affected_months=("2026-08",),
        batch_size=2,
        input_fingerprint=(generation_id.encode().hex() + "f" * 64)[:64],
    )
    assert first.resumed is False
    assert second.resumed is True
    with shadow_factory() as shadow, incremental_factory() as incremental:
        assert _rows(incremental, SettlementMonthlyOverlay, _MONTHLY_FIELDS) == _rows(
            shadow, AggStoreMonthlySettlement, _MONTHLY_FIELDS
        )
        assert _rows(incremental, SettlementRankingOverlay, _RANKING_FIELDS) == _rows(
            shadow, AggStoreRanking, _RANKING_FIELDS
        )
        assert (
            _rows(incremental, SettlementMonthlyOverlay, _MONTHLY_FIELDS),
            _rows(incremental, SettlementRankingOverlay, _RANKING_FIELDS),
            _manifest_rows(incremental, generation_id),
        ) == first_snapshot
        august = incremental.scalar(
            select(SettlementMonthlyOverlay).where(
                SettlementMonthlyOverlay.generation_id == generation_id,
                SettlementMonthlyOverlay.month == "2026-08",
                SettlementMonthlyOverlay.product_scope == "all",
                SettlementMonthlyOverlay.product_type == "all",
            )
        )
        september = incremental.scalar(
            select(SettlementMonthlyOverlay).where(
                SettlementMonthlyOverlay.generation_id == generation_id,
                SettlementMonthlyOverlay.month == "2026-09",
                SettlementMonthlyOverlay.product_scope == "all",
                SettlementMonthlyOverlay.product_type == "all",
            )
        )
        assert august is not None and august.promotion_original_fee_cent == 50
        assert september is not None and september.promotion_adjustment_fee_cent == -10

    with incremental_factory() as session:
        session.add(
            SettlementStatement(
                statement_id="equivalence-locked",
                store_id="adjustment-store",
                statement_month="2026-08",
                statement_status=4,
                lock_version="equivalence-lock",
            )
        )
        session.commit()
    blocked_generation = "adjustment-locked-generation"
    with pytest.raises(settlement.LockedSettlementConflict):
        settlement.build_settlement_sparse_overlay(
            incremental_factory,
            generation_id=blocked_generation,
            base_generation_id=base_id,
            affected_months=("2026-08",),
            batch_size=2,
            input_fingerprint=(blocked_generation.encode().hex() + "f" * 64)[:64],
        )
    with incremental_factory() as session:
        assert session.get(SettlementProjectionGeneration, blocked_generation) is None
        assert session.get(SettlementProjectionActive, "settlement").generation_id == base_id


def _seed_score_fixture(session: Session, *, prefix: str) -> tuple[str, str]:
    rule_id = f"{prefix}-rule"
    version_id = f"{prefix}-rule-v1"
    session.add(
        DimStore(
            store_id="score-store",
            store_name="Score Store",
            is_active=True,
            standard_province="浙江省",
            standard_city="杭州市",
            city_code="杭州",
            longitude=Decimal("120.155100"),
            latitude=Decimal("30.274100"),
            is_douyin_clue_applicable=True,
            participates_in_clue_allocation=True,
            location_status="valid",
        )
    )
    session.add(
        ClueAllocationRule(
            rule_id=rule_id,
            rule_name=f"{prefix} rule",
            scope_type="global",
            scope_key=f"global:{prefix}",
        )
    )
    session.flush()
    session.add(
        ClueAllocationRuleVersion(
            rule_version_id=version_id,
            rule_id=rule_id,
            version_no=1,
            status="published",
            lookback_days=30,
            min_samples=1,
            conversion_weight=Decimal("0.7000"),
            follow_24h_weight=Decimal("0.3000"),
            published_at=datetime.now(UTC),
        )
    )
    session.commit()
    return rule_id, version_id


_SCORE_FIELDS = (
    "snapshot_date",
    "store_id",
    "city_code",
    "window_start",
    "window_end",
    "conversion_numerator",
    "conversion_denominator",
    "conversion_rate",
    "conversion_value_source",
    "follow_24h_numerator",
    "follow_24h_denominator",
    "follow_24h_rate",
    "follow_24h_value_source",
    "conversion_weight",
    "follow_24h_weight",
    "store_weight",
    "composite_score",
)


def test_shadow_equivalence_score_partition_retry_and_no_mix(
    shadow_factories: tuple[sessionmaker[Session], sessionmaker[Session]],
) -> None:
    shadow_factory, incremental_factory = shadow_factories
    with shadow_factory() as session:
        _rule_id, version_id = _seed_score_fixture(session, prefix="score-shadow")
        result = clue_allocation.refresh_store_score_snapshots(
            session,
            rule_version_id=version_id,
            now=datetime(2026, 8, 7, 19, tzinfo=UTC),
            run_mode="manual",
            triggered_by="shadow-equivalence",
        )
        assert result["snapshots"] == 1
        session.commit()
    with incremental_factory() as session:
        _rule_id, incremental_version = _seed_score_fixture(
            session,
            prefix="score-shadow",
        )
        assert incremental_version == version_id
        base_id, generation_id = _seed_lineage(session, prefix="score-sparse")
    first = clue_allocation.build_score_sparse_overlay(
        incremental_factory,
        generation_id=generation_id,
        base_generation_id=base_id,
        affected_store_ids=("score-store",),
        published_rule_ids=(version_id,),
        snapshot_date=date(2026, 8, 8),
        batch_size=2,
        closure_policy_hash="a" * 64,
    )
    with incremental_factory() as session:
        first_snapshot = (
            _rows(session, StoreScoreSnapshot, _SCORE_FIELDS),
            session.scalar(select(func.count()).select_from(StoreScoreSnapshotGeneration)),
            _manifest_rows(session, generation_id),
        )
    second = clue_allocation.build_score_sparse_overlay(
        incremental_factory,
        generation_id=generation_id,
        base_generation_id=base_id,
        affected_store_ids=("score-store",),
        published_rule_ids=(version_id,),
        snapshot_date=date(2026, 8, 8),
        batch_size=2,
        closure_policy_hash="a" * 64,
    )
    assert first.resumed is False
    assert second.resumed is True
    with shadow_factory() as shadow, incremental_factory() as incremental:
        shadow_rows = _rows(shadow, StoreScoreSnapshot, _SCORE_FIELDS)
        sparse_rows = _rows(incremental, StoreScoreSnapshot, _SCORE_FIELDS)
        assert sparse_rows == shadow_rows
        assert _digest(sparse_rows) == _digest(shadow_rows)
        sidecars = list(incremental.scalars(select(StoreScoreSnapshotGeneration)))
        assert [(row.rule_version_id, row.store_id) for row in sidecars] == [
            (version_id, "score-store")
        ]
        assert shadow.scalar(
            select(func.count()).select_from(StoreScoreSnapshotGeneration)
        ) == 0
        assert (
            sparse_rows,
            len(sidecars),
            _manifest_rows(incremental, generation_id),
        ) == first_snapshot
        assert incremental.scalar(
            select(func.count())
            .select_from(StoreScoreSnapshotRun)
            .where(StoreScoreSnapshotRun.run_mode == "projection_sparse")
        ) == 1


def test_no_change_lineage_fallback_and_incremental_finalize_never_calls_rebuild_settlement(
    shadow_factories: tuple[sessionmaker[Session], sessionmaker[Session]],
) -> None:
    _shadow_factory, incremental_factory = shadow_factories
    with incremental_factory() as session:
        _base_id, generation_id = _seed_lineage(
            session,
            prefix="no-change",
            published=True,
        )
    with incremental_factory() as session:
        for artifact, partition_key in (
            ("monthly", "2026-08"),
            ("ranking", "monthly:2026-08"),
            ("score", "2026-08-08|7:rule-v1|11:score-store"),
        ):
            resolution = resolve_projection_partitions(
                session,
                artifact=artifact,
                partition_keys=(partition_key,),
                pinned_generation_id=generation_id,
            )
            assert resolution[partition_key].source_kind == "legacy_root"
            assert resolution[partition_key].actual_data_generation_id is None

    forbidden = "rebuild_" + "settlement"
    assert forbidden not in inspect.getsource(finalize.run_finalize_stage)
    assert forbidden not in inspect.getsource(daily_task.execute_daily_task)
    assert forbidden not in inspect.getsource(settlement.settle_impacted_coupons)
