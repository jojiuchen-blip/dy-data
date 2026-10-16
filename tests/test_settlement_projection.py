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


@pytest.mark.parametrize("source_state", ["superseded", "current", "anchor"])
def test_sparse_builder_retains_only_current_or_anchored_immutable_adjustments(
    db_session: Session, source_state: str,
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
    if source_state == "anchor":
        old.reverification_anchor_id = current.fee_result_id
        old.result_version = 3
        old.result_status = 2
    elif source_state == "superseded":
        old.result_status = 2
    db_session.add_all([old, current])
    db_session.flush()
    db_session.add(
        SettlementFeeResultCurrent(
            coupon_id=current.coupon_id,
            fee_direction=1,
            fee_result_id=old.fee_result_id if source_state == "current" else current.fee_result_id,
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
    original_fee = 10 if source_state == "current" else 50
    expected = [("2026-08", original_fee, 0)]
    if source_state != "superseded":
        expected.append(("2026-09", 0, -10))
    assert [(row.month, row.promotion_original_fee_cent, row.promotion_adjustment_fee_cent) for row in all_rows] == expected
    # Retirement changes active visibility, never deletes the historical fact.
    assert db_session.scalar(select(func.count()).select_from(SettlementFeeAdjustment)) == 1
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
    assert cumulative.promotion_net_fee_cent == original_fee - (0 if source_state == "superseded" else 10)


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


# ---------------------------------------------------------------------------
# Compacted lineage: consecutive day finalizes and a second compaction must
# keep working over a verified terminal compact ancestor.  Red-first contract
# for DYDATA-102 P1: ``_sparse_base_chain`` and the lineage reader/builder used
# to reject every compact node that was not the pinned head itself, so the
# second daily finalize after a compaction publish failed with "ordinary
# lineage cannot contain a compact base".
# ---------------------------------------------------------------------------

from datetime import UTC, datetime, timedelta  # noqa: E402

from apps.api.dy_api.models import (  # noqa: E402
    JobEvent,
    JobRun,
    SettlementProjectionCompactionClosure,
)
from apps.worker.legacy_projection_bootstrap import (  # noqa: E402
    CompactionThresholdConfig,
    _ManifestChecksumAccumulator,
    compact_projection_metadata,
)
from apps.worker.projection_lineage import (  # noqa: E402
    LineageError,
    resolve_projection_partitions,
)
from apps.worker.projection_publish import (  # noqa: E402
    publish_settlement_compaction,
    publish_settlement_rebuild,
)
from tests.test_legacy_projection_bootstrap import _limits  # noqa: E402

_CYCLE_MONTH_AMOUNTS = {
    "2026-10": (100, 10),
    "2026-11": (200, 20),
    "2026-12": (300, 30),
    "2027-01": (400, 40),
}


def _cycle_factory(db_session: Session):
    from sqlalchemy.orm import sessionmaker

    return sessionmaker(bind=db_session.get_bind(), autoflush=False, future=True)


def _session(db_session: Session) -> Session:
    from sqlalchemy.orm import Session as SASession

    return SASession(bind=db_session.get_bind(), autoflush=False, future=True)


def _real_root_digest(db_session: Session, root: str) -> None:
    """Give a hand-seeded legacy root the digest of its (empty) manifest set."""

    root_row = db_session.get(SettlementProjectionGeneration, root)
    assert root_row is not None
    root_row.manifest_checksum = _ManifestChecksumAccumulator().hexdigest()
    db_session.commit()


def _seed_fee_month(
    db_session: Session,
    *,
    prefix: str,
    month: str,
    index: int,
    amounts: tuple[int, int] | None = None,
) -> None:
    source, fee = amounts if amounts is not None else _CYCLE_MONTH_AMOUNTS[month]
    result = _fee_result(
        result_id=f"{prefix}-result-{month}",
        coupon_id=f"{prefix}-coupon-{month}",
        direction=1,
        version=1,
        month=month,
        store_id=f"{prefix}-store",
        source_amount=source,
        fee_amount=fee,
    )
    db_session.add(result)
    db_session.flush()
    db_session.add(
        SettlementFeeResultCurrent(
            coupon_id=result.coupon_id,
            fee_direction=1,
            fee_result_id=result.fee_result_id,
        )
    )


def _running_job(
    db_session: Session, *, job_id: str, job_name: str, claim: str
) -> None:
    db_session.add(
        JobRun(
            job_id=job_id,
            job_name=job_name,
            status="running",
            started_at=datetime.now(UTC).replace(tzinfo=None),
            lease_owner=f"{job_id}-owner",
            claim_token=claim,
            lease_expires_at=datetime.now(UTC).replace(tzinfo=None)
            + timedelta(seconds=600),
            attempt_count=1,
            max_attempts=3,
        )
    )
    db_session.flush()


def _finish_job(db_session: Session, job_id: str) -> None:
    job = db_session.get(JobRun, job_id)
    assert job is not None
    job.status = "success"
    job.claim_token = None
    job.lease_expires_at = None
    db_session.commit()


def _publish_day(
    db_session: Session,
    *,
    generation_id: str,
    base_generation_id: str,
    affected_month: str,
) -> dict[str, object]:
    """Real sparse build + ready certification + audited rebuild publication."""

    fingerprint = (generation_id.encode("utf-8").hex() + "f" * 64)[:64]
    built = settlement.build_settlement_sparse_overlay(
        _cycle_factory(db_session),
        generation_id=generation_id,
        base_generation_id=base_generation_id,
        affected_months=(affected_month,),
        batch_size=2,
        input_fingerprint=fingerprint,
    )
    settlement.mark_settlement_sparse_overlay_ready(
        _cycle_factory(db_session),
        generation_id=generation_id,
        base_generation_id=base_generation_id,
        input_fingerprint=fingerprint,
    )
    job_id = f"job-{generation_id}"
    _running_job(
        db_session, job_id=job_id, job_name="settlement_rebuild", claim=f"claim-{generation_id}"
    )
    with _session(db_session) as session:
        payload = publish_settlement_rebuild(
            session,
            job_id=job_id,
            claim_id=f"claim-{generation_id}",
            generation_id=generation_id,
            base_generation_id=base_generation_id,
            input_fingerprint=fingerprint,
            manifest_checksum=built.manifest_checksum,
        )
        session.commit()
    _finish_job(db_session, job_id)
    db_session.expire_all()
    return {"fingerprint": fingerprint, "payload": payload, "built": built}


def _publish_compact(
    db_session: Session,
    *,
    base_generation_id: str,
    job_suffix: str,
    resource_limits=None,
) -> str:
    result = compact_projection_metadata(
        _cycle_factory(db_session),
        base_generation_id=base_generation_id,
        threshold_config=CompactionThresholdConfig(minimum_lineage_depth=1, batch_size=4),
        resource_limits=resource_limits or _limits(rows=50),
    )
    assert result.status == "ready"
    assert result.generation_id is not None
    db_session.expire_all()
    compact = db_session.get(SettlementProjectionGeneration, result.generation_id)
    assert compact is not None
    assert compact.manifest_checksum is not None
    assert compact.input_fingerprint is not None
    job_id = f"job-compaction-{job_suffix}"
    _running_job(
        db_session,
        job_id=job_id,
        job_name="settlement_compaction",
        claim=f"claim-compaction-{job_suffix}",
    )
    with _session(db_session) as session, session.begin():
        publish_settlement_compaction(
            session,
            job_id=job_id,
            claim_id=f"claim-compaction-{job_suffix}",
            generation_id=result.generation_id,
            input_fingerprint=compact.input_fingerprint,
            manifest_checksum=compact.manifest_checksum,
        )
    _finish_job(db_session, job_id)
    db_session.expire_all()
    return result.generation_id


def _monthly_resolution(
    db_session: Session, *, pinned: str, keys: tuple[str, ...]
):
    with _session(db_session) as session:
        return resolve_projection_partitions(
            session,
            artifact="monthly",
            partition_keys=keys,
            pinned_generation_id=pinned,
        )


def _monthly_ranking_resolution(
    db_session: Session, *, pinned: str, key: str
):
    with _session(db_session) as session:
        return resolve_projection_partitions(
            session,
            artifact="ranking",
            partition_keys=(key,),
            pinned_generation_id=pinned,
        )


def test_compacted_lineage_supports_consecutive_days_and_second_compaction(
    db_session: Session,
):
    prefix = "cycle"
    root = _seed_base(
        db_session, prefix=prefix, legacy_months=("2026-08", "2026-09")
    )
    # A real certified null root carries the digest of its (empty) manifest
    # set, not a placeholder; the compaction digest gate recomputes it.
    _real_root_digest(db_session, root)
    # A frozen legacy month with a locked statement: the cycle must never move
    # billing facts, and the freeze evidence must be non-trivial.
    db_session.add(
        SettlementStatement(
            statement_id=f"{prefix}-stmt",
            store_id=f"{prefix}-store",
            statement_month="2026-08",
            statement_status=4,
            lock_version=f"{prefix}-lock",
            promotion_original_fee_cent=11,
            promotion_adjustment_fee_cent=0,
            promotion_net_fee_cent=11,
            management_original_fee_cent=7,
            management_adjustment_fee_cent=0,
            management_net_fee_cent=7,
        )
    )
    for index, month in enumerate(_CYCLE_MONTH_AMOUNTS, start=1):
        _seed_fee_month(db_session, prefix=prefix, month=month, index=index)
    db_session.commit()

    frozen_agg = [
        (
            row.month,
            row.sales_amount_cent,
            row.promotion_net_fee_cent,
        )
        for row in db_session.scalars(
            select(AggStoreMonthlySettlement).order_by(AggStoreMonthlySettlement.month)
        ).all()
    ]
    frozen_statement = db_session.scalar(
        select(SettlementStatement).where(SettlementStatement.statement_id == f"{prefix}-stmt")
    )
    assert frozen_statement is not None
    frozen_statement_tuple = (
        frozen_statement.statement_id,
        frozen_statement.statement_status,
        frozen_statement.statement_month,
        frozen_statement.lock_version,
        frozen_statement.promotion_net_fee_cent,
        frozen_statement.management_net_fee_cent,
    )
    frozen_counts = (
        db_session.scalar(select(func.count()).select_from(SettlementFeeResult)),
        db_session.scalar(select(func.count()).select_from(SettlementStatement)),
        db_session.scalar(select(func.count()).select_from(SettlementFeeAdjustment)),
    )

    # Day 1 over the legacy root, then compaction #1.
    day1 = _publish_day(
        db_session,
        generation_id=f"{prefix}-l1",
        base_generation_id=root,
        affected_month="2026-10",
    )
    assert db_session.get(SettlementProjectionActive, "settlement").generation_id == f"{prefix}-l1"
    compact1 = _publish_compact(db_session, base_generation_id=f"{prefix}-l1", job_suffix="1")
    assert db_session.get(SettlementProjectionActive, "settlement").generation_id == compact1

    # Day 2 directly over the compact head, day 3 over its lineage.
    day2 = _publish_day(
        db_session,
        generation_id=f"{prefix}-l2",
        base_generation_id=compact1,
        affected_month="2026-11",
    )
    assert db_session.get(SettlementProjectionActive, "settlement").generation_id == f"{prefix}-l2"
    day3 = _publish_day(
        db_session,
        generation_id=f"{prefix}-l3",
        base_generation_id=f"{prefix}-l2",
        affected_month="2026-12",
    )
    assert db_session.get(SettlementProjectionActive, "settlement").generation_id == f"{prefix}-l3"

    # Second compaction over a chain whose ancestor is the first compact.
    compact2 = _publish_compact(db_session, base_generation_id=f"{prefix}-l3", job_suffix="2")
    assert db_session.get(SettlementProjectionActive, "settlement").generation_id == compact2

    # Day 4 over the second compact head.
    day4 = _publish_day(
        db_session,
        generation_id=f"{prefix}-l4",
        base_generation_id=compact2,
        affected_month="2027-01",
    )
    assert db_session.get(SettlementProjectionActive, "settlement").generation_id == f"{prefix}-l4"

    def generation(generation_id: str) -> SettlementProjectionGeneration:
        row = db_session.get(SettlementProjectionGeneration, generation_id)
        assert row is not None
        return row

    # Depth bookkeeping: compact resets to zero, every day adds exactly one hop.
    assert generation(f"{prefix}-l1").lineage_depth == 1
    assert generation(compact1).lineage_depth == 0
    assert generation(f"{prefix}-l2").lineage_depth == 1
    assert generation(f"{prefix}-l3").lineage_depth == 2
    assert generation(compact2).lineage_depth == 0
    assert generation(f"{prefix}-l4").lineage_depth == 1
    assert generation(f"{prefix}-l2").base_generation_id == compact1
    assert generation(f"{prefix}-l3").base_generation_id == f"{prefix}-l2"
    assert generation(f"{prefix}-l4").base_generation_id == compact2

    # Closure stays bounded: one row per chain member, never accumulated
    # across compactions (the second compact must not inherit the first
    # compact's own closure rows).
    closure1 = {
        row.source_generation_id
        for row in db_session.scalars(
            select(SettlementProjectionCompactionClosure).where(
                SettlementProjectionCompactionClosure.compact_generation_id == compact1
            )
        )
    }
    assert closure1 == {f"{prefix}-l1", root}
    closure2 = {
        row.source_generation_id
        for row in db_session.scalars(
            select(SettlementProjectionCompactionClosure).where(
                SettlementProjectionCompactionClosure.compact_generation_id == compact2
            )
        )
    }
    assert closure2 == {f"{prefix}-l3", f"{prefix}-l2", compact1}
    assert generation(compact2).checkpoint_json["source_generation_count"] == 3

    # Manifest resolution over the live day-4 chain: legacy months fall back to
    # the legacy root, compact-collapsed months resolve to the newest compact
    # (provenance: the first compact for the oldest month, the day lineages for
    # its own months), and day 4 owns its own month.
    resolution = _monthly_resolution(
        db_session,
        pinned=f"{prefix}-l4",
        keys=("2026-08", "2026-09", "2026-10", "2026-11", "2026-12", "2027-01"),
    )
    assert resolution["2026-08"].owner_state == "legacy_root"
    assert resolution["2026-09"].owner_state == "legacy_root"
    assert resolution["2026-10"].nearest_manifest_owner_generation == compact2
    assert resolution["2026-10"].actual_data_generation_id == f"{prefix}-l1"
    assert resolution["2026-11"].nearest_manifest_owner_generation == compact2
    assert resolution["2026-11"].actual_data_generation_id == f"{prefix}-l2"
    assert resolution["2026-12"].nearest_manifest_owner_generation == compact2
    assert resolution["2026-12"].actual_data_generation_id == f"{prefix}-l3"
    assert resolution["2027-01"].nearest_manifest_owner_generation == f"{prefix}-l4"

    # Real read entry: the dashboard resolves each partition to its data
    # generation and reads the actual overlay rows from it.  After TWO
    # compactions every historical month must still return its exact amounts
    # (10 / 20 / 30) plus the fresh day-4 month (40) — the compact heads are
    # metadata-only and must never be asked for business rows themselves.
    expected_monthly_fees = {
        "2026-10": 10,
        "2026-11": 20,
        "2026-12": 30,
        "2027-01": 40,
    }
    for month, expected_fee in expected_monthly_fees.items():
        part = resolution[month]
        assert part.source_kind == "overlay" and part.owner_state == "owned"
        rows = db_session.scalars(
            select(SettlementMonthlyOverlay).where(
                SettlementMonthlyOverlay.generation_id
                == part.actual_data_generation_id,
                SettlementMonthlyOverlay.month == month,
                SettlementMonthlyOverlay.product_scope == "all",
                SettlementMonthlyOverlay.product_type == "all",
            )
        ).all()
        assert [
            (row.promotion_net_fee_cent, row.management_net_fee_cent) for row in rows
        ] == [(expected_fee, 0)], month
    ranking_resolution = _monthly_ranking_resolution(
        db_session, pinned=f"{prefix}-l4", key="monthly:2026-10"
    )["monthly:2026-10"]
    # Real read entry through the ranking artifact: the partition survives two
    # compactions and still resolves to the original day-1 data generation.
    assert ranking_resolution.owner_state == "owned"
    assert ranking_resolution.nearest_manifest_owner_generation == compact2
    assert ranking_resolution.actual_data_generation_id == f"{prefix}-l1"
    ranking_rows = db_session.scalars(
        select(SettlementRankingOverlay).where(
            SettlementRankingOverlay.generation_id
            == ranking_resolution.actual_data_generation_id,
            SettlementRankingOverlay.partition_key == "monthly:2026-10",
            SettlementRankingOverlay.product_scope == "all",
            SettlementRankingOverlay.product_type == "all",
        )
    ).all()
    assert [
        (row.promotion_net_fee_cent, row.management_net_fee_cent) for row in ranking_rows
    ] == [(10, 0)]

    # Amounts survive both compactions bit-for-bit.
    compact2_manifest = db_session.scalar(
        select(SettlementProjectionPartitionManifest).where(
            SettlementProjectionPartitionManifest.generation_id == compact2,
            SettlementProjectionPartitionManifest.artifact == "monthly",
            SettlementProjectionPartitionManifest.partition_key == "2026-10",
        )
    )
    compact1_manifest = db_session.scalar(
        select(SettlementProjectionPartitionManifest).where(
            SettlementProjectionPartitionManifest.generation_id == compact1,
            SettlementProjectionPartitionManifest.artifact == "monthly",
            SettlementProjectionPartitionManifest.partition_key == "2026-10",
        )
    )
    assert compact1_manifest is not None and compact2_manifest is not None
    assert compact2_manifest.amount_total_cent == compact1_manifest.amount_total_cent
    assert compact2_manifest.row_count == compact1_manifest.row_count
    assert compact2_manifest.checksum == compact1_manifest.checksum
    day4_monthly = db_session.scalar(
        select(SettlementMonthlyOverlay).where(
            SettlementMonthlyOverlay.generation_id == f"{prefix}-l4",
            SettlementMonthlyOverlay.month == "2027-01",
            SettlementMonthlyOverlay.product_scope == "all",
            SettlementMonthlyOverlay.product_type == "all",
        )
    )
    assert day4_monthly is not None
    assert day4_monthly.promotion_net_fee_cent == 40

    # A replaced compact may legitimately become superseded; historical chains
    # that contain it must still resolve for audit reads.
    generation(compact1).state = "superseded"
    db_session.commit()
    historical = _monthly_resolution(
        db_session,
        pinned=f"{prefix}-l3",
        keys=("2026-10", "2026-11", "2026-12"),
    )
    assert historical["2026-10"].nearest_manifest_owner_generation == compact1
    assert historical["2026-11"].nearest_manifest_owner_generation == f"{prefix}-l2"
    assert historical["2026-12"].nearest_manifest_owner_generation == f"{prefix}-l3"

    # Frozen facts: the legacy aggregation, fee results and statements never
    # moved across the whole cycle.
    assert [
        (row.month, row.sales_amount_cent, row.promotion_net_fee_cent)
        for row in db_session.scalars(
            select(AggStoreMonthlySettlement).order_by(AggStoreMonthlySettlement.month)
        ).all()
    ] == frozen_agg
    assert (
        db_session.scalar(select(func.count()).select_from(SettlementFeeResult)),
        db_session.scalar(select(func.count()).select_from(SettlementStatement)),
        db_session.scalar(select(func.count()).select_from(SettlementFeeAdjustment)),
    ) == frozen_counts


def test_lineage_gates_still_reject_broken_compact_ancestors(db_session: Session):
    from apps.worker.legacy_projection_bootstrap import _load_compaction_lineage
    from apps.worker.settlement import _sparse_base_chain

    prefix = "broken-compact"
    root = _seed_base(db_session, prefix=prefix)

    def generation(generation_id: str, **kwargs: object) -> None:
        payload = {
            "generation_id": generation_id,
            "projection_name": "settlement",
            "state": "published",
            "input_fingerprint": (generation_id.encode("utf-8").hex() + "0" * 64)[:64],
            "checkpoint_json": {},
            "manifest_checksum": "3" * 64,
            "source_input_json": {},
        }
        payload.update(kwargs)
        db_session.add(SettlementProjectionGeneration(**payload))

    # An UNPUBLISHED compact ancestor (staging) is the corrupt shape that is
    # representable at the storage layer: the CHECK already forces compact rows
    # to base NULL + depth 0 + provenance set, so a non-terminal compact cannot
    # even be inserted.  Every gate must still refuse the unpublished ancestor.
    generation(f"{prefix}-l1", generation_kind="lineage", base_generation_id=root,
               lineage_depth=1, published_at=datetime.now(UTC))
    db_session.flush()
    generation(f"{prefix}-cbad", generation_kind="compact",
               base_generation_id=None, compaction_base_generation_id=f"{prefix}-l1",
               lineage_depth=0, published_at=None, state="staging")
    db_session.flush()
    db_session.add(
        SettlementProjectionGeneration(
            generation_id=f"{prefix}-l2", generation_kind="lineage",
            base_generation_id=f"{prefix}-cbad", projection_name="settlement",
            state="published",
            input_fingerprint=(f"{prefix}-l2".encode("utf-8").hex() + "0" * 64)[:64],
            lineage_depth=2, checkpoint_json={}, manifest_checksum="3" * 64,
            source_input_json={}, published_at=datetime.now(UTC),
        )
    )
    active = db_session.get(SettlementProjectionActive, "settlement")
    assert active is not None
    active.generation_id = f"{prefix}-l2"
    db_session.commit()

    # The unpublished compact ancestor is refused by every gate (the state
    # gate fires first on the chain walk; the reader and the compaction loader
    # refuse it as well).
    with pytest.raises(ValueError, match="unpublished"):
        with _session(db_session) as session:
            _sparse_base_chain(session, f"{prefix}-l2")
    with pytest.raises(LineageError):
        _monthly_resolution(db_session, pinned=f"{prefix}-l2", keys=("2026-08",))
    with pytest.raises(Exception, match="compaction lineage|compact"):
        _load_compaction_lineage(_cycle_factory(db_session), f"{prefix}-l2")

    # A real cycle (two lineage generations pointing at each other) stays
    # rejected by the chain walk.
    generation(f"{prefix}-cyc-a", generation_kind="lineage",
               base_generation_id=f"{prefix}-cyc-b", lineage_depth=2,
               published_at=datetime.now(UTC))
    generation(f"{prefix}-cyc-b", generation_kind="lineage",
               base_generation_id=f"{prefix}-cyc-a", lineage_depth=1,
               published_at=datetime.now(UTC))
    db_session.commit()
    with pytest.raises(ValueError, match="cycle"):
        with _session(db_session) as session:
            _sparse_base_chain(session, f"{prefix}-cyc-b")


def test_second_compaction_rejects_tampered_compact_source_digest(db_session: Session):
    prefix = "tamper"
    root = _seed_base(db_session, prefix=prefix, legacy_months=("2026-08",))
    _real_root_digest(db_session, root)
    for index, month in enumerate(("2026-10", "2026-11"), start=1):
        _seed_fee_month(db_session, prefix=prefix, month=month, index=index)
    db_session.commit()
    _publish_day(
        db_session,
        generation_id=f"{prefix}-l1",
        base_generation_id=root,
        affected_month="2026-10",
    )
    compact1 = _publish_compact(db_session, base_generation_id=f"{prefix}-l1", job_suffix="t1")
    _publish_day(
        db_session,
        generation_id=f"{prefix}-l2",
        base_generation_id=compact1,
        affected_month="2026-11",
    )

    # Tamper with the compact ancestor's declared digest: the second compaction
    # must refuse instead of silently trusting the chain.
    compact_row = db_session.get(SettlementProjectionGeneration, compact1)
    assert compact_row is not None and compact_row.manifest_checksum is not None
    original_digest = compact_row.manifest_checksum
    compact_row.manifest_checksum = ("e" * 63 + "0") if original_digest[-1] != "0" else ("e" * 63 + "1")
    db_session.commit()
    with pytest.raises(Exception, match="digest|manifest"):
        compact_projection_metadata(
            _cycle_factory(db_session),
            base_generation_id=f"{prefix}-l2",
            threshold_config=CompactionThresholdConfig(minimum_lineage_depth=1, batch_size=4),
            resource_limits=_limits(rows=50),
        )


# ---------------------------------------------------------------------------
# DYDATA-102/103 publication-blocker contracts (red first).
#
# Blocker 1: a third independent compaction over the day-4 chain used to fail
# with "compaction overlay source is invalid" because the builder only accepted
# leaf data generations that sit in the terminal compact's DIRECT closure, while
# the real leaf (day-1 generation) is proven one provenance hop further back.
#
# Blocker 2: the ordinary-lineage reader used a membership-only compact
# provenance helper, so a corrupted closure digest / source projection / source
# state on the terminal compact's closure was silently accepted.
# ---------------------------------------------------------------------------

from contextlib import contextmanager  # noqa: E402

from sqlalchemy import event  # noqa: E402


def _run_compaction_cycle(db_session: Session, *, prefix: str) -> dict[str, str]:
    """Real day1→C1→day2→day3→C2→day4 cycle through audited publishers only."""

    root = _seed_base(db_session, prefix=prefix, legacy_months=("2026-08", "2026-09"))
    _real_root_digest(db_session, root)
    for month in _CYCLE_MONTH_AMOUNTS:
        _seed_fee_month(db_session, prefix=prefix, month=month, index=1)
    db_session.commit()
    _publish_day(
        db_session,
        generation_id=f"{prefix}-l1",
        base_generation_id=root,
        affected_month="2026-10",
    )
    compact1 = _publish_compact(
        db_session, base_generation_id=f"{prefix}-l1", job_suffix=f"{prefix}-c1"
    )
    _publish_day(
        db_session,
        generation_id=f"{prefix}-l2",
        base_generation_id=compact1,
        affected_month="2026-11",
    )
    _publish_day(
        db_session,
        generation_id=f"{prefix}-l3",
        base_generation_id=f"{prefix}-l2",
        affected_month="2026-12",
    )
    compact2 = _publish_compact(
        db_session, base_generation_id=f"{prefix}-l3", job_suffix=f"{prefix}-c2"
    )
    _publish_day(
        db_session,
        generation_id=f"{prefix}-l4",
        base_generation_id=compact2,
        affected_month="2027-01",
    )
    assert db_session.get(SettlementProjectionActive, "settlement").generation_id == f"{prefix}-l4"
    return {
        "root": root,
        "l1": f"{prefix}-l1",
        "compact1": compact1,
        "l2": f"{prefix}-l2",
        "l3": f"{prefix}-l3",
        "compact2": compact2,
        "l4": f"{prefix}-l4",
    }


@contextmanager
def _statement_counter(db_session: Session):
    """Count executed SQL statements to assert batched (not per-partition) reads."""

    engine = db_session.get_bind()
    counter = {"count": 0}

    def _track(conn, cursor, statement, parameters, context, executemany):
        counter["count"] += 1

    event.listen(engine, "before_cursor_execute", _track)
    try:
        yield counter
    finally:
        event.remove(engine, "before_cursor_execute", _track)


def test_third_compaction_and_following_day_preserve_real_leaf_history(
    db_session: Session,
):
    prefix = "cycle3"
    ids = _run_compaction_cycle(db_session, prefix=prefix)

    # Blocker 1: the third independent compaction over the day-4 chain must
    # build and publish.  The real leaf data generation (cycle3-l1) lives one
    # provenance hop behind the terminal compact and must be accepted through
    # the same full provenance verifier the readers use.
    compact3 = _publish_compact(
        db_session, base_generation_id=f"{prefix}-l4", job_suffix="third-independent"
    )
    assert db_session.get(SettlementProjectionActive, "settlement").generation_id == compact3

    compact3_row = db_session.get(SettlementProjectionGeneration, compact3)
    assert compact3_row is not None
    assert compact3_row.generation_kind == "compact"
    assert compact3_row.base_generation_id is None
    assert compact3_row.compaction_base_generation_id == f"{prefix}-l4"
    assert compact3_row.lineage_depth == 0
    assert compact3_row.checkpoint_json["source_generation_count"] == 2

    # Each compaction records only its own lineage chain: the third compact's
    # closure must not inherit the first compact's closure rows.
    closure3 = {
        row.source_generation_id
        for row in db_session.scalars(
            select(SettlementProjectionCompactionClosure).where(
                SettlementProjectionCompactionClosure.compact_generation_id == compact3
            )
        )
    }
    assert closure3 == {f"{prefix}-l4", ids["compact2"]}

    # Compaction stays metadata-only: no business overlay rows are copied, and
    # the manifest keeps the real leaf id with the real frozen evidence.
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(SettlementMonthlyOverlay)
            .where(SettlementMonthlyOverlay.generation_id == compact3)
        )
        == 0
    )
    compact3_manifest = db_session.scalar(
        select(SettlementProjectionPartitionManifest).where(
            SettlementProjectionPartitionManifest.generation_id == compact3,
            SettlementProjectionPartitionManifest.artifact == "monthly",
            SettlementProjectionPartitionManifest.partition_key == "2026-10",
        )
    )
    assert compact3_manifest is not None
    assert compact3_manifest.data_generation_id == f"{prefix}-l1"
    assert compact3_manifest.reference_head_generation_id == compact3
    assert compact3_manifest.row_count == 1
    assert compact3_manifest.amount_total_cent == 10

    # A following day finalize over the third compact head must keep working.
    _seed_fee_month(
        db_session, prefix=prefix, month="2027-02", index=5, amounts=(500, 50)
    )
    db_session.commit()
    _publish_day(
        db_session,
        generation_id=f"{prefix}-l5",
        base_generation_id=compact3,
        affected_month="2027-02",
    )
    assert db_session.get(SettlementProjectionActive, "settlement").generation_id == f"{prefix}-l5"

    # Real read entry over the day-5 chain: every historical month resolves to
    # its original data generation with the exact seeded amounts (10/20/30/40)
    # plus the fresh day-5 month (50); legacy months stay on the legacy root.
    resolution = _monthly_resolution(
        db_session,
        pinned=f"{prefix}-l5",
        keys=(
            "2026-08",
            "2026-09",
            "2026-10",
            "2026-11",
            "2026-12",
            "2027-01",
            "2027-02",
        ),
    )
    assert resolution["2026-08"].owner_state == "legacy_root"
    assert resolution["2026-09"].owner_state == "legacy_root"
    expected = {
        "2026-10": (f"{prefix}-l1", compact3, 10),
        "2026-11": (f"{prefix}-l2", compact3, 20),
        "2026-12": (f"{prefix}-l3", compact3, 30),
        "2027-01": (f"{prefix}-l4", compact3, 40),
        "2027-02": (f"{prefix}-l5", f"{prefix}-l5", 50),
    }
    for month, (data_id, owner, fee) in expected.items():
        part = resolution[month]
        assert part.source_kind == "overlay" and part.owner_state == "owned", month
        assert part.actual_data_generation_id == data_id, month
        assert part.nearest_manifest_owner_generation == owner, month
        rows = db_session.scalars(
            select(SettlementMonthlyOverlay).where(
                SettlementMonthlyOverlay.generation_id == data_id,
                SettlementMonthlyOverlay.month == month,
                SettlementMonthlyOverlay.product_scope == "all",
                SettlementMonthlyOverlay.product_type == "all",
            )
        ).all()
        assert [
            (row.promotion_net_fee_cent, row.management_net_fee_cent) for row in rows
        ] == [(fee, 0)], month

    # Direct compact read entry over the third head: same real leaves.
    direct = _monthly_resolution(
        db_session, pinned=compact3, keys=("2026-10", "2026-11", "2026-12")
    )
    for month in ("2026-10", "2026-11", "2026-12"):
        assert direct[month].actual_data_generation_id == expected[month][0]
        assert direct[month].nearest_manifest_owner_generation == compact3

    # Batched reads: adding six more partitions costs at most one extra
    # statement per added distinct leaf pair (all reads are fixed-size
    # batches), never a per-partition query recursion.
    with _statement_counter(db_session) as one:
        _monthly_resolution(db_session, pinned=f"{prefix}-l5", keys=("2026-10",))
    many_keys = (
        "2026-08",
        "2026-09",
        "2026-10",
        "2026-11",
        "2026-12",
        "2027-01",
        "2027-02",
    )
    with _statement_counter(db_session) as many:
        _monthly_resolution(db_session, pinned=f"{prefix}-l5", keys=many_keys)
    added_partitions = len(many_keys) - 1
    assert many["count"] <= one["count"] + added_partitions
    assert many["count"] <= 32
    # A per-partition recursive reader would need at least a manifest,
    # provenance, and presence read per partition; the batched reader stays
    # far below that even with the deeper third-compaction provenance chain.
    assert many["count"] < 3 * len(many_keys)

    # Fourth compaction over the day-5 chain, then a following day finalize.
    # The original leaf amounts (10/20/30/40/50) and every frozen fact must
    # stay untouched across yet another metadata-only compaction.
    compact4 = _publish_compact(
        db_session, base_generation_id=f"{prefix}-l5", job_suffix="fourth-independent"
    )
    assert db_session.get(SettlementProjectionActive, "settlement").generation_id == compact4
    compact4_row = db_session.get(SettlementProjectionGeneration, compact4)
    assert compact4_row is not None
    assert compact4_row.generation_kind == "compact"
    assert compact4_row.base_generation_id is None
    assert compact4_row.compaction_base_generation_id == f"{prefix}-l5"
    assert compact4_row.lineage_depth == 0
    assert compact4_row.checkpoint_json["source_generation_count"] == 2
    closure4 = {
        row.source_generation_id
        for row in db_session.scalars(
            select(SettlementProjectionCompactionClosure).where(
                SettlementProjectionCompactionClosure.compact_generation_id == compact4
            )
        )
    }
    assert closure4 == {f"{prefix}-l5", compact3}
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(SettlementMonthlyOverlay)
            .where(SettlementMonthlyOverlay.generation_id == compact4)
        )
        == 0
    )
    compact4_manifest = db_session.scalar(
        select(SettlementProjectionPartitionManifest).where(
            SettlementProjectionPartitionManifest.generation_id == compact4,
            SettlementProjectionPartitionManifest.artifact == "monthly",
            SettlementProjectionPartitionManifest.partition_key == "2026-10",
        )
    )
    assert compact4_manifest is not None
    assert compact4_manifest.data_generation_id == f"{prefix}-l1"
    assert compact4_manifest.reference_head_generation_id == compact4
    assert compact4_manifest.row_count == 1
    assert compact4_manifest.amount_total_cent == 10

    # Following day finalize over the fourth compact head: the oldest leaf
    # (day-1 generation, fee 10) still resolves with its exact frozen amount.
    _seed_fee_month(
        db_session, prefix=prefix, month="2027-03", index=6, amounts=(600, 60)
    )
    db_session.commit()
    _publish_day(
        db_session,
        generation_id=f"{prefix}-l6",
        base_generation_id=compact4,
        affected_month="2027-03",
    )
    assert db_session.get(SettlementProjectionActive, "settlement").generation_id == f"{prefix}-l6"
    resolution4 = _monthly_resolution(
        db_session,
        pinned=f"{prefix}-l6",
        keys=(
            "2026-08",
            "2026-09",
            "2026-10",
            "2026-11",
            "2026-12",
            "2027-01",
            "2027-02",
            "2027-03",
        ),
    )
    assert resolution4["2026-08"].owner_state == "legacy_root"
    assert resolution4["2026-09"].owner_state == "legacy_root"
    expected4 = {
        "2026-10": (f"{prefix}-l1", compact4, 10),
        "2026-11": (f"{prefix}-l2", compact4, 20),
        "2026-12": (f"{prefix}-l3", compact4, 30),
        "2027-01": (f"{prefix}-l4", compact4, 40),
        "2027-02": (f"{prefix}-l5", compact4, 50),
        "2027-03": (f"{prefix}-l6", f"{prefix}-l6", 60),
    }
    for month, (data_id, owner, fee) in expected4.items():
        part = resolution4[month]
        assert part.source_kind == "overlay" and part.owner_state == "owned", month
        assert part.actual_data_generation_id == data_id, month
        assert part.nearest_manifest_owner_generation == owner, month
        rows = db_session.scalars(
            select(SettlementMonthlyOverlay).where(
                SettlementMonthlyOverlay.generation_id == data_id,
                SettlementMonthlyOverlay.month == month,
                SettlementMonthlyOverlay.product_scope == "all",
                SettlementMonthlyOverlay.product_type == "all",
            )
        ).all()
        assert [
            (row.promotion_net_fee_cent, row.management_net_fee_cent) for row in rows
        ] == [(fee, 0)], month

    # Frozen facts: the seeded fee results never moved or duplicated across the
    # whole fourth-compaction cycle (non-empty and compared by value).
    assert db_session.scalar(select(func.count()).select_from(SettlementFeeResult)) == 6
    assert [
        (row.original_business_month, row.fee_amount_cent)
        for row in db_session.scalars(
            select(SettlementFeeResult).order_by(SettlementFeeResult.original_business_month)
        ).all()
    ] == [
        ("2026-10", 10),
        ("2026-11", 20),
        ("2026-12", 30),
        ("2027-01", 40),
        ("2027-02", 50),
        ("2027-03", 60),
    ]


def test_compact_provenance_corruption_rejected_on_both_read_entries(
    db_session: Session,
):
    prefix = "corrupt"
    ids = _run_compaction_cycle(db_session, prefix=prefix)
    l4 = ids["l4"]
    compact1 = ids["compact1"]
    compact2 = ids["compact2"]
    l3 = ids["l3"]
    history_keys = ("2026-10", "2026-11", "2026-12")

    def both_entries() -> tuple[dict, dict]:
        return (
            _monthly_resolution(db_session, pinned=l4, keys=history_keys),
            _monthly_resolution(db_session, pinned=compact2, keys=history_keys),
        )

    def expect_rejected_on_both_entries() -> None:
        with pytest.raises(LineageError):
            _monthly_resolution(db_session, pinned=l4, keys=history_keys)
        with pytest.raises(LineageError):
            _monthly_resolution(db_session, pinned=compact2, keys=history_keys)

    # Untampered baseline: both read entries resolve the real leaves.
    ordinary, direct = both_entries()
    for month, data_id in (
        ("2026-10", f"{prefix}-l1"),
        ("2026-11", f"{prefix}-l2"),
        ("2026-12", f"{prefix}-l3"),
    ):
        assert ordinary[month].actual_data_generation_id == data_id
        assert direct[month].actual_data_generation_id == data_id
        assert ordinary[month].nearest_manifest_owner_generation == compact2
        assert direct[month].nearest_manifest_owner_generation == compact2

    def compact2_closure_row(source_generation_id: str):
        row = db_session.scalar(
            select(SettlementProjectionCompactionClosure).where(
                SettlementProjectionCompactionClosure.compact_generation_id == compact2,
                SettlementProjectionCompactionClosure.source_generation_id
                == source_generation_id,
            )
        )
        assert row is not None
        return row

    # 1) Closure digest tampered to all zeros (controller reproduction):
    #    the ordinary lineage entry must refuse, exactly like the direct entry.
    tampered_digest = compact2_closure_row(compact1).source_digest
    assert tampered_digest is not None
    compact2_closure_row(compact1).source_digest = "0" * 64
    db_session.commit()
    expect_rejected_on_both_entries()
    compact2_closure_row(compact1).source_digest = tampered_digest
    db_session.commit()

    # 2) A closure source row is deleted: provenance membership loses a source
    #    and the partition it captured must fail closed on both entries.
    deleted_row = compact2_closure_row(f"{prefix}-l2")
    deleted_pair = (deleted_row.compact_generation_id, deleted_row.source_generation_id)
    deleted_digest = deleted_row.source_digest
    db_session.delete(deleted_row)
    db_session.commit()
    expect_rejected_on_both_entries()
    db_session.add(
        SettlementProjectionCompactionClosure(
            compact_generation_id=deleted_pair[0],
            source_generation_id=deleted_pair[1],
            source_digest=deleted_digest,
        )
    )
    db_session.commit()

    # 3) The captured compact source generation row itself is deleted.
    source_snapshot = {
        column.name: getattr(source_row, column.name)
        for column in SettlementProjectionGeneration.__table__.columns
        for source_row in [db_session.get(SettlementProjectionGeneration, compact1)]
        if source_row is not None
    }
    assert source_snapshot.get("generation_id") == compact1
    db_session.delete(db_session.get(SettlementProjectionGeneration, compact1))
    db_session.commit()
    expect_rejected_on_both_entries()
    db_session.add(SettlementProjectionGeneration(**source_snapshot))
    db_session.commit()

    # 4) Wrong projection on a closure source (storage CHECK bypassed to
    #    simulate the corruption class the reader must reject).
    wrong_projection_row = db_session.get(SettlementProjectionGeneration, compact1)
    assert wrong_projection_row is not None
    connection = db_session.connection()
    connection.exec_driver_sql("PRAGMA ignore_check_constraints = ON")
    try:
        wrong_projection_row.projection_name = "not-settlement"
        db_session.flush()
    finally:
        connection.exec_driver_sql("PRAGMA ignore_check_constraints = OFF")
    db_session.commit()
    expect_rejected_on_both_entries()
    db_session.get(SettlementProjectionGeneration, compact1).projection_name = "settlement"
    db_session.commit()

    # 5) Wrong state on an ordinary closure source of the terminal compact.
    l3_row = db_session.get(SettlementProjectionGeneration, l3)
    assert l3_row is not None
    l3_row.state = "staging"
    db_session.commit()
    expect_rejected_on_both_entries()
    db_session.get(SettlementProjectionGeneration, l3).state = "published"
    db_session.commit()

    # 6) Provenance path cycle: the first compact's closure is re-anchored onto
    #    the second compact while the second compact's closure still names the
    #    first one.  Both read entries must fail closed instead of walking the
    #    cycle (bounded path detection, never infinite provenance expansion).
    cycle_row = db_session.scalar(
        select(SettlementProjectionCompactionClosure).where(
            SettlementProjectionCompactionClosure.compact_generation_id == compact1,
            SettlementProjectionCompactionClosure.source_generation_id
            == f"{prefix}-l1",
        )
    )
    assert cycle_row is not None
    cycle_pair = (cycle_row.compact_generation_id, cycle_row.source_generation_id)
    cycle_digest = cycle_row.source_digest
    db_session.delete(cycle_row)
    compact2_checksum = db_session.get(SettlementProjectionGeneration, compact2).manifest_checksum
    assert compact2_checksum is not None
    db_session.add(
        SettlementProjectionCompactionClosure(
            compact_generation_id=compact1,
            source_generation_id=compact2,
            source_digest=compact2_checksum,
        )
    )
    db_session.commit()
    expect_rejected_on_both_entries()
    db_session.delete(
        db_session.scalar(
            select(SettlementProjectionCompactionClosure).where(
                SettlementProjectionCompactionClosure.compact_generation_id == compact1,
                SettlementProjectionCompactionClosure.source_generation_id == compact2,
            )
        )
    )
    db_session.add(
        SettlementProjectionCompactionClosure(
            compact_generation_id=cycle_pair[0],
            source_generation_id=cycle_pair[1],
            source_digest=cycle_digest,
        )
    )
    db_session.commit()

    # 7) Compact-owned manifest evidence tampered: the anchor chain must
    #    refuse field mismatches on both entries.
    tampered_manifest = db_session.scalar(
        select(SettlementProjectionPartitionManifest).where(
            SettlementProjectionPartitionManifest.generation_id == compact2,
            SettlementProjectionPartitionManifest.artifact == "monthly",
            SettlementProjectionPartitionManifest.partition_key == "2026-10",
        )
    )
    assert tampered_manifest is not None
    original_row_count = tampered_manifest.row_count
    tampered_manifest.row_count = original_row_count + 1
    db_session.commit()
    expect_rejected_on_both_entries()
    db_session.expire_all()
    restored_manifest = db_session.get(
        SettlementProjectionPartitionManifest,
        (compact2, "monthly", "2026-10"),
    )
    assert restored_manifest is not None
    restored_manifest.row_count = original_row_count
    db_session.commit()

    # After every tamper was rolled back, both read entries resolve again.
    ordinary, direct = both_entries()
    assert ordinary["2026-10"].actual_data_generation_id == f"{prefix}-l1"
    assert direct["2026-10"].actual_data_generation_id == f"{prefix}-l1"


def test_first_compaction_deep_source_digest_tamper_rejected_on_both_entries(
    db_session: Session,
):
    """A C1-level (one provenance hop deeper) closure digest tamper must fail
    closed on the ordinary lineage entry exactly like the direct compact
    entry: the anchor walk reaches the first compact's own closure rows."""

    prefix = "deeptamper"
    ids = _run_compaction_cycle(db_session, prefix=prefix)
    compact1 = ids["compact1"]
    history_keys = ("2026-10",)

    ordinary = _monthly_resolution(db_session, pinned=ids["l4"], keys=history_keys)
    direct = _monthly_resolution(db_session, pinned=ids["compact2"], keys=history_keys)
    assert ordinary["2026-10"].actual_data_generation_id == f"{prefix}-l1"
    assert direct["2026-10"].actual_data_generation_id == f"{prefix}-l1"

    deep_row = db_session.scalar(
        select(SettlementProjectionCompactionClosure).where(
            SettlementProjectionCompactionClosure.compact_generation_id == compact1,
            SettlementProjectionCompactionClosure.source_generation_id == f"{prefix}-l1",
        )
    )
    assert deep_row is not None
    original_digest = deep_row.source_digest
    assert original_digest is not None
    deep_row.source_digest = "0" * 64
    db_session.commit()

    with pytest.raises(LineageError):
        _monthly_resolution(db_session, pinned=ids["l4"], keys=history_keys)
    with pytest.raises(LineageError):
        _monthly_resolution(db_session, pinned=ids["compact2"], keys=history_keys)

    deep_row.source_digest = original_digest
    db_session.commit()
    ordinary = _monthly_resolution(db_session, pinned=ids["l4"], keys=history_keys)
    assert ordinary["2026-10"].actual_data_generation_id == f"{prefix}-l1"
    direct = _monthly_resolution(db_session, pinned=ids["compact2"], keys=history_keys)
    assert direct["2026-10"].actual_data_generation_id == f"{prefix}-l1"


# ---------------------------------------------------------------------------
# DYDATA-103 acceptance addendum: compaction page session lifecycle and a
# batching proof that is independent of the partition count.
# ---------------------------------------------------------------------------


def _month_sequence(start_month: str, count: int) -> tuple[str, ...]:
    year, month = int(start_month[:4]), int(start_month[5:7])
    months: list[str] = []
    for _ in range(count):
        months.append(f"{year:04d}-{month:02d}")
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1
    return tuple(months)


def test_compaction_page_closes_session_after_terminal_compact_verification(
    db_session: Session,
):
    """The terminal compact's full provenance verification must run inside the
    open page session (after every database read) and before its single close:
    the provenance context must never be used while holding a closed session,
    and a closed session must never execute again nor be reopened."""

    from apps.worker import projection_lineage as lineage_module
    from apps.worker.legacy_projection_bootstrap import (
        _compaction_source_payload_page,
        _load_compaction_lineage,
    )

    prefix = "pageclose"
    ids = _run_compaction_cycle(db_session, prefix=prefix)
    l4 = ids["l4"]
    terminal_compact = ids["compact2"]
    lineage_rows = _load_compaction_lineage(_cycle_factory(db_session), l4)
    assert str(lineage_rows[-1]["generation_id"]) == terminal_compact
    assert lineage_rows[-1]["generation_kind"] == "compact"

    real_session = _session(db_session)
    state = {
        "closed": False,
        "close_count": 0,
        "factory_calls": 0,
        "execute_count": 0,
    }

    class _CloseRejectingSessionProxy:
        """Real session proxy: any execute after close() fails the test."""

        def __init__(self, inner: Session) -> None:
            self._inner = inner

        def execute(self, *args: object, **kwargs: object):
            assert not state["closed"], "session executed after close"
            state["execute_count"] += 1
            return self._inner.execute(*args, **kwargs)  # type: ignore[attr-defined]

        def scalar(self, *args: object, **kwargs: object):
            assert not state["closed"], "session scalar executed after close"
            return self._inner.scalar(*args, **kwargs)  # type: ignore[attr-defined]

        def close(self):
            state["close_count"] += 1
            state["closed"] = True
            return self._inner.close()  # type: ignore[attr-defined]

        def __getattr__(self, name: str):
            return getattr(self._inner, name)

    def guarded_factory() -> _CloseRejectingSessionProxy:
        state["factory_calls"] += 1
        return _CloseRejectingSessionProxy(real_session)

    closure_calls: list[dict[str, object]] = []
    original_verified_closure = lineage_module._CompactProvenanceContext.verified_closure

    def traced_verified_closure(self, compact_generation_id, *, allowed_states):
        closure_calls.append(
            {
                "compact_id": compact_generation_id,
                "after_close": state["closed"],
            }
        )
        return original_verified_closure(self, compact_generation_id, allowed_states=allowed_states)

    lineage_module._CompactProvenanceContext.verified_closure = traced_verified_closure
    try:
        # A page with NO compact-owned partition: 2027-01 is owned by the
        # ordinary day-4 head.  The terminal compact verification must still
        # execute, inside the open session, before the single normal close.
        payloads = _compaction_source_payload_page(
            guarded_factory, l4, lineage_rows, [("monthly", "2027-01")]
        )
    finally:
        lineage_module._CompactProvenanceContext.verified_closure = original_verified_closure

    assert state["factory_calls"] == 1, "closed session must never be reopened"
    assert state["close_count"] == 1
    assert [(p["artifact"], p["partition_key"]) for p in payloads] == [
        ("monthly", "2027-01")
    ]
    assert payloads[0]["source_kind"] == "overlay"
    assert payloads[0]["data_generation_id"] == l4
    # Verification still ran for the terminal compact...
    assert any(call["compact_id"] == terminal_compact for call in closure_calls)
    # ...but never while (or after) the session was closed.
    assert not any(call["after_close"] for call in closure_calls)
    assert state["execute_count"] > 0


def test_hundred_partition_compacted_reads_do_not_scale_with_partition_count(
    db_session: Session,
):
    """One vs >=100 legal partitions at the same depth and from the same
    source set must cost the same number of queries: reads are batched by a
    fixed pair budget, never per partition.  Partitions are produced by the
    real sparse builder and audited compaction publisher, so every resolved
    partition is verifiable down to its real leaf."""

    prefix = "qcount"
    # The cumulative suffix starts at the formal settlement start (2026-08) and
    # covers every later authoritative month: one affected month at 2026-08 in
    # front of 100 legacy months yields 100 legal cumulative ranking
    # partitions in a single day build.
    legacy_months = _month_sequence("2026-09", 100)  # 2026-09 .. 2034-12
    assert len(legacy_months) >= 100
    root = _seed_base(db_session, prefix=prefix, legacy_months=legacy_months)
    _real_root_digest(db_session, root)
    affected1 = "2026-08"
    db_session.commit()
    _publish_day(
        db_session,
        generation_id=f"{prefix}-l1",
        base_generation_id=root,
        affected_month=affected1,
    )
    compact1 = _publish_compact(
        db_session,
        base_generation_id=f"{prefix}-l1",
        job_suffix=f"{prefix}-c1",
        resource_limits=_limits(
            rows=1000, write=10_000_000, wal=20_000_000, headroom=100_000_000
        ),
    )
    affected2 = "2035-01"
    db_session.commit()
    _publish_day(
        db_session,
        generation_id=f"{prefix}-l2",
        base_generation_id=compact1,
        affected_month=affected2,
    )
    assert db_session.get(SettlementProjectionActive, "settlement").generation_id == f"{prefix}-l2"

    # Same depth (day-2 head, lineage depth 1) and same source set
    # ({l2, compact1}) for both measurements.
    many_keys = tuple(f"cumulative:{month}" for month in legacy_months)
    assert len(many_keys) >= 100
    assert len(set(many_keys)) == len(many_keys)

    with _statement_counter(db_session) as one:
        single = _monthly_ranking_resolution(
            db_session, pinned=f"{prefix}-l2", key=many_keys[0]
        )
    with _statement_counter(db_session) as many:
        with _session(db_session) as session:
            resolved = resolve_projection_partitions(
                session,
                artifact="ranking",
                partition_keys=many_keys,
                pinned_generation_id=f"{prefix}-l2",
            )
    # 100 pairs stay far below the 400-pair batch budget: the query count must
    # be identical, proving reads never grow per partition.
    assert many["count"] == one["count"]

    # Every partition is a legal compact-owned partition verified down to the
    # same real leaf data generation (the full provenance verifier ran).
    assert single[many_keys[0]].nearest_manifest_owner_generation == compact1
    assert single[many_keys[0]].actual_data_generation_id == f"{prefix}-l1"
    for key in many_keys:
        part = resolved[key]
        assert part.source_kind == "overlay" and part.owner_state == "owned", key
        assert part.nearest_manifest_owner_generation == compact1, key
        assert part.actual_data_generation_id == f"{prefix}-l1", key

    # The resolved partitions carry real, checkable overlay facts: the
    # cumulative ranking sums the legacy sales (100 per legacy month).
    oldest = db_session.scalar(
        select(SettlementRankingOverlay).where(
            SettlementRankingOverlay.generation_id == f"{prefix}-l1",
            SettlementRankingOverlay.partition_key == many_keys[0],
            SettlementRankingOverlay.product_scope == "all",
            SettlementRankingOverlay.product_type == "all",
        )
    )
    assert oldest is not None
    assert oldest.sales_amount_cent == 100
    newest_legacy = db_session.scalar(
        select(SettlementRankingOverlay).where(
            SettlementRankingOverlay.generation_id == f"{prefix}-l1",
            SettlementRankingOverlay.partition_key == many_keys[-1],
            SettlementRankingOverlay.product_scope == "all",
            SettlementRankingOverlay.product_type == "all",
        )
    )
    assert newest_legacy is not None
    assert newest_legacy.sales_amount_cent == 100 * sum(range(1, len(legacy_months) + 1))


# ---------------------------------------------------------------------------
# DYDATA-102 signed-amount acceptance: cross-month refund adjustments are a
# legal production fact (signed amount schema), so a negative
# ``amount_total_cent`` manifest must read back through every real entry
# instead of being rejected as a non-negative count.
# ---------------------------------------------------------------------------


def _seed_positive_fee_with_cross_month_refund(
    db_session: Session,
    *,
    prefix: str,
    month: str,
    posting_month: str,
    source_amount: int,
    fee_amount: int,
    adjustment_base_cent: int,
    adjustment_fee_cent: int,
    adjustment_id: str,
):
    """Seed one positive fee result plus one legal cross-month refund adjustment."""

    result = _fee_result(
        result_id=f"{prefix}-result-{month}",
        coupon_id=f"{prefix}-coupon-{month}",
        direction=1,
        version=1,
        month=month,
        store_id=f"{prefix}-store",
        source_amount=source_amount,
        fee_amount=fee_amount,
    )
    db_session.add(result)
    db_session.flush()
    db_session.add(
        SettlementFeeResultCurrent(
            coupon_id=result.coupon_id,
            fee_direction=1,
            fee_result_id=result.fee_result_id,
        )
    )
    adjustment = SettlementFeeAdjustment(
        adjustment_id=adjustment_id,
        original_fee_result_id=result.fee_result_id,
        coupon_id=result.coupon_id,
        order_id=result.order_id,
        fee_direction=1,
        original_business_month=month,
        adjustment_posting_month=posting_month,
        adjustment_type=1,
        adjustment_base_cent=adjustment_base_cent,
        adjustment_fee_cent=adjustment_fee_cent,
        rule_version="rule-v1",
        adjustment_reason="cross-month refund",
        occurred_at=datetime.now(UTC),
        created_by="test",
    )
    db_session.add(adjustment)
    db_session.flush()
    return result, adjustment


def _financial_row_snapshot(db_session: Session, row: object) -> dict[str, object]:
    """Read one row back from the database by its full column set."""

    table = type(row).__table__  # type: ignore[attr-defined]
    identity = {
        column.key: getattr(row, column.key)
        for column in table.primary_key.columns
    }
    db_row = db_session.execute(
        select(table).where(
            *[getattr(table.c, key) == value for key, value in identity.items()]
        )
    ).mappings().one()
    return dict(db_row)


def test_cross_month_refund_negative_amount_survives_compaction(db_session: Session):
    prefix = "refund"
    root = _seed_base(db_session, prefix=prefix)
    _real_root_digest(db_session, root)
    result, adjustment = _seed_positive_fee_with_cross_month_refund(
        db_session,
        prefix=prefix,
        month="2026-08",
        posting_month="2026-09",
        source_amount=100,
        fee_amount=10,
        adjustment_base_cent=-100,
        adjustment_fee_cent=-10,
        adjustment_id=f"{prefix}-adj-1",
    )
    _seed_fee_month(db_session, prefix=prefix, month="2026-10", index=2, amounts=(200, 20))
    db_session.commit()

    result_snapshot = _financial_row_snapshot(db_session, result)
    adjustment_snapshot = _financial_row_snapshot(db_session, adjustment)
    fee_row_id, adjustment_row_id = result.id, adjustment.id

    _publish_day(
        db_session,
        generation_id=f"{prefix}-l1",
        base_generation_id=root,
        affected_month="2026-08",
    )
    db_session.expire_all()

    # The real sparse builder produced the Sep monthly row and the
    # monthly:2026-09 ranking row with the real refund amounts.
    sep_monthly = db_session.scalar(
        select(SettlementMonthlyOverlay).where(
            SettlementMonthlyOverlay.generation_id == f"{prefix}-l1",
            SettlementMonthlyOverlay.month == "2026-09",
            SettlementMonthlyOverlay.product_scope == "all",
            SettlementMonthlyOverlay.product_type == "all",
        )
    )
    assert sep_monthly is not None
    assert (
        sep_monthly.promotion_original_fee_cent,
        sep_monthly.promotion_adjustment_fee_cent,
        sep_monthly.promotion_net_fee_cent,
    ) == (0, -10, -10)
    sep_ranking = db_session.scalar(
        select(SettlementRankingOverlay).where(
            SettlementRankingOverlay.generation_id == f"{prefix}-l1",
            SettlementRankingOverlay.partition_key == "monthly:2026-09",
            SettlementRankingOverlay.product_scope == "all",
            SettlementRankingOverlay.product_type == "all",
        )
    )
    assert sep_ranking is not None
    assert sep_ranking.promotion_net_fee_cent == -10

    day1_monthly_manifest = db_session.scalar(
        select(SettlementProjectionPartitionManifest).where(
            SettlementProjectionPartitionManifest.generation_id == f"{prefix}-l1",
            SettlementProjectionPartitionManifest.artifact == "monthly",
            SettlementProjectionPartitionManifest.partition_key == "2026-09",
        )
    )
    assert day1_monthly_manifest is not None
    assert day1_monthly_manifest.row_count == 1
    assert day1_monthly_manifest.amount_total_cent == -10
    day1_ranking_manifest = db_session.scalar(
        select(SettlementProjectionPartitionManifest).where(
            SettlementProjectionPartitionManifest.generation_id == f"{prefix}-l1",
            SettlementProjectionPartitionManifest.artifact == "ranking",
            SettlementProjectionPartitionManifest.partition_key == "monthly:2026-09",
        )
    )
    assert day1_ranking_manifest is not None
    assert day1_ranking_manifest.amount_total_cent == -10

    # Ordinary (pre-compaction) entry already resolves the negative partition.
    ordinary = _monthly_resolution(db_session, pinned=f"{prefix}-l1", keys=("2026-09",))
    assert ordinary["2026-09"].owner_state == "owned"
    assert ordinary["2026-09"].actual_data_generation_id == f"{prefix}-l1"

    # First compact publish: the direct compact reader must accept the signed
    # partition and resolve it down to the real leaf without masking anything.
    compact1 = _publish_compact(
        db_session, base_generation_id=f"{prefix}-l1", job_suffix=f"{prefix}-c1"
    )
    direct = _monthly_resolution(db_session, pinned=compact1, keys=("2026-09",))
    assert direct["2026-09"].owner_state == "owned"
    assert direct["2026-09"].source_kind == "overlay"
    assert direct["2026-09"].nearest_manifest_owner_generation == compact1
    assert direct["2026-09"].actual_data_generation_id == f"{prefix}-l1"
    leaf_rows = db_session.scalars(
        select(SettlementMonthlyOverlay).where(
            SettlementMonthlyOverlay.generation_id == f"{prefix}-l1",
            SettlementMonthlyOverlay.month == "2026-09",
            SettlementMonthlyOverlay.product_scope == "all",
            SettlementMonthlyOverlay.product_type == "all",
        )
    ).all()
    assert [
        (row.promotion_adjustment_fee_cent, row.promotion_net_fee_cent)
        for row in leaf_rows
    ] == [(-10, -10)]
    direct_ranking = _monthly_ranking_resolution(
        db_session, pinned=compact1, key="monthly:2026-09"
    )["monthly:2026-09"]
    assert direct_ranking.owner_state == "owned"
    assert direct_ranking.actual_data_generation_id == f"{prefix}-l1"

    # Compaction preserved the real signed evidence bit-for-bit.
    compact1_monthly_manifest = db_session.scalar(
        select(SettlementProjectionPartitionManifest).where(
            SettlementProjectionPartitionManifest.generation_id == compact1,
            SettlementProjectionPartitionManifest.artifact == "monthly",
            SettlementProjectionPartitionManifest.partition_key == "2026-09",
        )
    )
    assert compact1_monthly_manifest is not None
    assert compact1_monthly_manifest.amount_total_cent == -10
    assert compact1_monthly_manifest.row_count == day1_monthly_manifest.row_count
    assert compact1_monthly_manifest.checksum == day1_monthly_manifest.checksum

    # A following day and a second compaction keep the signed partition,
    # its real leaf, and the summary intact on every entry.
    _publish_day(
        db_session,
        generation_id=f"{prefix}-l2",
        base_generation_id=compact1,
        affected_month="2026-10",
    )
    compact2 = _publish_compact(
        db_session, base_generation_id=f"{prefix}-l2", job_suffix=f"{prefix}-c2"
    )
    for pinned in (f"{prefix}-l2", compact2):
        resolution = _monthly_resolution(
            db_session, pinned=pinned, keys=("2026-09", "2026-10")
        )
        assert resolution["2026-09"].owner_state == "owned"
        assert resolution["2026-09"].actual_data_generation_id == f"{prefix}-l1"
        assert resolution["2026-10"].owner_state == "owned"
        assert resolution["2026-10"].actual_data_generation_id == f"{prefix}-l2"
        rows = db_session.scalars(
            select(SettlementMonthlyOverlay).where(
                SettlementMonthlyOverlay.generation_id == f"{prefix}-l1",
                SettlementMonthlyOverlay.month == "2026-09",
                SettlementMonthlyOverlay.product_scope == "all",
                SettlementMonthlyOverlay.product_type == "all",
            )
        ).all()
        assert [(row.promotion_net_fee_cent, row.management_net_fee_cent) for row in rows] == [
            (-10, 0)
        ]
    compact2_monthly_manifest = db_session.scalar(
        select(SettlementProjectionPartitionManifest).where(
            SettlementProjectionPartitionManifest.generation_id == compact2,
            SettlementProjectionPartitionManifest.artifact == "monthly",
            SettlementProjectionPartitionManifest.partition_key == "2026-09",
        )
    )
    assert compact2_monthly_manifest is not None
    assert compact2_monthly_manifest.amount_total_cent == -10
    assert compact2_monthly_manifest.checksum == compact1_monthly_manifest.checksum

    # Compaction never changed a financial row.
    db_session.expire_all()
    assert _financial_row_snapshot(db_session, db_session.get(SettlementFeeResult, fee_row_id)) == result_snapshot
    assert _financial_row_snapshot(
        db_session, db_session.get(SettlementFeeAdjustment, adjustment_row_id)
    ) == adjustment_snapshot


def test_manifest_signed_amount_and_nonnegative_count_gates():
    from apps.worker.projection_lineage import (
        LineageError,
        _canonical_status_counts,
        _manifest_integer,
        _manifest_signed_integer,
    )

    # Signed amounts stay signed — negatives are legal, never abs/clamped.
    assert _manifest_signed_integer({"amount_total_cent": -10}, "amount_total_cent") == -10
    assert _manifest_signed_integer({"amount_total_cent": 0}, "amount_total_cent") == 0
    # Booleans and non-integer amounts are still illegal.
    with pytest.raises(LineageError):
        _manifest_signed_integer({"amount_total_cent": True}, "amount_total_cent")
    with pytest.raises(LineageError):
        _manifest_signed_integer({"amount_total_cent": "1.5"}, "amount_total_cent")
    with pytest.raises(LineageError):
        _manifest_signed_integer({"amount_total_cent": "abc"}, "amount_total_cent")
    # Counts (row_count) and status_counts remain strictly non-negative.
    with pytest.raises(LineageError):
        _manifest_integer({"row_count": -1}, "row_count")
    with pytest.raises(LineageError):
        _manifest_integer({"row_count": True}, "row_count")
    assert _manifest_integer({"row_count": 3}, "row_count") == 3
    with pytest.raises(LineageError):
        _canonical_status_counts({"paid": -1})
    assert _canonical_status_counts({"paid": 2}) == (("paid", 2),)


@pytest.mark.parametrize(
    "raw",
    [
        1.5,
        -0.5,
        Decimal("1.5"),
        Decimal("-0.5"),
        Decimal("NaN"),
        Decimal("Infinity"),
        float("nan"),
        float("inf"),
        float("-inf"),
        "1.5",
        "-0.5",
        "nan",
        "inf",
        "1e2",
        "abc",
        "",
    ],
)
def test_manifest_non_integer_amounts_rejected(raw):
    from apps.worker.projection_lineage import (
        LineageError,
        _manifest_integer,
        _manifest_signed_integer,
    )

    with pytest.raises(LineageError):
        _manifest_signed_integer({"amount_total_cent": raw}, "amount_total_cent")
    # Counts must never be truncated either.
    with pytest.raises(LineageError):
        _manifest_integer({"row_count": raw}, "row_count")


def test_manifest_integer_amounts_accepted_without_precision_loss():
    from apps.worker.projection_lineage import (
        _manifest_integer,
        _manifest_signed_integer,
    )

    # Normal integers and integer digit strings keep the original semantics.
    assert _manifest_signed_integer({"amount_total_cent": None}, "amount_total_cent") == 0
    assert _manifest_signed_integer({}, "amount_total_cent") == 0
    assert _manifest_signed_integer({"amount_total_cent": 7}, "amount_total_cent") == 7
    assert _manifest_signed_integer({"amount_total_cent": "-7"}, "amount_total_cent") == -7
    assert _manifest_signed_integer({"amount_total_cent": 2.0}, "amount_total_cent") == 2
    assert (
        _manifest_signed_integer({"amount_total_cent": Decimal("2")}, "amount_total_cent")
        == 2
    )
    # Big integers must not lose precision through a float round-trip.
    big = 9007199254740993
    assert _manifest_signed_integer({"amount_total_cent": big}, "amount_total_cent") == big
    assert _manifest_signed_integer(
        {"amount_total_cent": str(big)}, "amount_total_cent"
    ) == big
    assert _manifest_signed_integer(
        {"amount_total_cent": f"-{big}"}, "amount_total_cent"
    ) == -big
    # Counts accept the same integer forms, still non-negative.
    assert _manifest_integer({"row_count": "3"}, "row_count") == 3
    assert _manifest_integer({"row_count": None}, "row_count") == 0
