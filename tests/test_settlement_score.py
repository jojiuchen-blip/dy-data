from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    ClueAllocationRule,
    ClueAllocationRuleVersion,
    DimStore,
    SettlementProjectionActive,
    SettlementProjectionGeneration,
    SettlementProjectionPartitionManifest,
    StoreScoreSnapshot,
    StoreScoreSnapshotGeneration,
    StoreScoreSnapshotRun,
)
from apps.worker import clue_allocation


def _seed_generation(session: Session, *, prefix: str) -> tuple[str, str]:
    base_id = f"{prefix}-base"
    generation_id = f"{prefix}-generation"
    session.add(
        SettlementProjectionGeneration(
            generation_id=base_id,
            generation_kind="legacy_root",
            projection_name="settlement",
            state="published",
            input_fingerprint=(prefix.encode().hex() + "0" * 64)[:64],
            lineage_depth=0,
            checkpoint_json={},
            manifest_checksum="0" * 64,
            source_input_json={},
            published_at=datetime.now(timezone.utc),
        )
    )
    session.flush()
    session.add(
        SettlementProjectionGeneration(
            generation_id=generation_id,
            base_generation_id=base_id,
            generation_kind="lineage",
            projection_name="settlement",
            state="staging",
            input_fingerprint=(generation_id.encode().hex() + "f" * 64)[:64],
            lineage_depth=1,
            checkpoint_json={"phase": "settlement_ready"},
            source_input_json={"phase": "settlement_ready"},
        )
    )
    session.add(
        SettlementProjectionActive(
            projection_name="settlement", generation_id=base_id
        )
    )
    session.commit()
    return base_id, generation_id


def _seed_rule(
    session: Session, *, prefix: str, status: str = "published"
) -> tuple[str, str]:
    rule_id = f"{prefix}-rule"
    version_id = f"{prefix}-rule-v1"
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
            status=status,
            lookback_days=30,
            min_samples=1,
            conversion_weight=Decimal("0.7000"),
            follow_24h_weight=Decimal("0.3000"),
            published_at=datetime.now(timezone.utc) if status == "published" else None,
        )
    )
    session.commit()
    return rule_id, version_id


def _seed_store(session: Session, store_id: str) -> None:
    session.add(
        DimStore(
            store_id=store_id,
            store_name=store_id,
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
    session.commit()


def _build(
    session: Session,
    *,
    generation_id: str,
    base_generation_id: str,
    store_ids: tuple[str, ...],
    rule_ids: tuple[str, ...],
):
    assert hasattr(clue_allocation, "build_score_sparse_overlay")
    return clue_allocation.build_score_sparse_overlay(
        lambda: Session(bind=session.get_bind(), autoflush=False, future=True),
        generation_id=generation_id,
        base_generation_id=base_generation_id,
        affected_store_ids=store_ids,
        published_rule_ids=rule_ids,
        snapshot_date=date(2026, 8, 8),
        batch_size=2,
        closure_policy_hash="a" * 64,
    )


def test_score_sparse_same_day_rules_use_distinct_generation_qualified_runs(
    db_session: Session,
):
    base, generation = _seed_generation(db_session, prefix="score-rules")
    rule_a, version_a = _seed_rule(db_session, prefix="score-global")
    _, version_b = _seed_rule(db_session, prefix="score-city")
    _seed_store(db_session, "score-rules-store")

    result = _build(
        db_session,
        generation_id=generation,
        base_generation_id=base,
        store_ids=("score-rules-store",),
        rule_ids=(rule_a, version_b),
    )

    db_session.expire_all()
    runs = db_session.scalars(
        select(StoreScoreSnapshotRun).order_by(StoreScoreSnapshotRun.snapshot_run_id)
    ).all()
    assert result.rule_version_ids == tuple(sorted((version_a, version_b)))
    assert len(runs) == 2
    assert len({row.scheduled_key for row in runs}) == 2
    assert all(row.run_mode == "projection_sparse" for row in runs)
    assert all(row.config_json["projection_generation_id"] == generation for row in runs)
    sidecars = db_session.scalars(
        select(StoreScoreSnapshotGeneration).order_by(
            StoreScoreSnapshotGeneration.rule_version_id
        )
    ).all()
    assert [(row.rule_version_id, row.store_id) for row in sidecars] == [
        (version_b, "score-rules-store"),
        (version_a, "score-rules-store"),
    ]
    assert len({row.partition_key for row in sidecars}) == 2
    assert db_session.scalar(select(func.count()).select_from(StoreScoreSnapshot)) == 2


def test_score_sparse_missing_store_writes_manifest_tombstone_without_sentinel_row(
    db_session: Session,
):
    base, generation = _seed_generation(db_session, prefix="score-tombstone")
    _, version = _seed_rule(db_session, prefix="score-tombstone")

    result = _build(
        db_session,
        generation_id=generation,
        base_generation_id=base,
        store_ids=("score-missing-store",),
        rule_ids=(version,),
    )

    db_session.expire_all()
    manifest = db_session.scalar(
        select(SettlementProjectionPartitionManifest).where(
            SettlementProjectionPartitionManifest.generation_id == generation,
            SettlementProjectionPartitionManifest.artifact == "score",
        )
    )
    assert manifest is not None
    assert manifest.owner_state == "tombstone"
    assert manifest.source_kind == "tombstone"
    assert manifest.row_count == 0
    assert result.row_count == 0
    assert db_session.scalar(select(func.count()).select_from(StoreScoreSnapshot)) == 0
    assert db_session.scalar(
        select(func.count()).select_from(StoreScoreSnapshotGeneration)
    ) == 0


def test_score_sparse_retry_reuses_run_and_sidecar(db_session: Session):
    base, generation = _seed_generation(db_session, prefix="score-retry")
    _, version = _seed_rule(db_session, prefix="score-retry")
    _seed_store(db_session, "score-retry-store")
    first = _build(
        db_session,
        generation_id=generation,
        base_generation_id=base,
        store_ids=("score-retry-store",),
        rule_ids=(version,),
    )
    snapshot = (
        first.snapshot_run_ids,
        first.manifest_checksum,
        db_session.scalar(select(func.count()).select_from(StoreScoreSnapshot)),
        db_session.scalar(
            select(func.count()).select_from(StoreScoreSnapshotGeneration)
        ),
    )

    second = _build(
        db_session,
        generation_id=generation,
        base_generation_id=base,
        store_ids=("score-retry-store",),
        rule_ids=(version,),
    )
    assert second.resumed is True
    assert (
        second.snapshot_run_ids,
        second.manifest_checksum,
        db_session.scalar(select(func.count()).select_from(StoreScoreSnapshot)),
        db_session.scalar(
            select(func.count()).select_from(StoreScoreSnapshotGeneration)
        ),
    ) == snapshot


def test_score_sparse_rejects_unpublished_rule_without_score_writes(
    db_session: Session,
):
    base, generation = _seed_generation(db_session, prefix="score-draft")
    _, version = _seed_rule(db_session, prefix="score-draft", status="draft")
    active_before = db_session.get(SettlementProjectionActive, "settlement").generation_id

    with pytest.raises(ValueError, match="published"):
        _build(
            db_session,
            generation_id=generation,
            base_generation_id=base,
            store_ids=("score-draft-store",),
            rule_ids=(version,),
        )
    assert db_session.scalar(select(func.count()).select_from(StoreScoreSnapshotRun)) == 0
    assert db_session.scalar(select(func.count()).select_from(StoreScoreSnapshot)) == 0
    assert db_session.scalar(
        select(func.count()).select_from(StoreScoreSnapshotGeneration)
    ) == 0
    assert db_session.get(SettlementProjectionActive, "settlement").generation_id == active_before
