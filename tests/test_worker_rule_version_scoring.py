from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    ClueMasterLead,
    DimStore,
    StoreScoreSnapshot,
    StoreScoreSnapshotRun,
)
from apps.worker import clue_allocation
from apps.worker.clue_allocation_engine import allocate_lead
from apps.worker.clue_rule_versions import (
    bind_lead_rule_version,
    create_rule,
    create_rule_version,
    publish_rule_version,
)


def _dt(day: int, hour: int = 9) -> datetime:
    return datetime(2026, 7, day, hour, tzinfo=timezone.utc)


def _store(store_id: str, *, candidate: bool = True) -> DimStore:
    return DimStore(
        store_id=store_id,
        store_name=store_id,
        is_active=candidate,
        standard_province="CN-SH",
        standard_city="CN-SH",
        city_code="CN-SH",
        longitude=Decimal("121.470000"),
        latitude=Decimal("31.230000"),
        is_douyin_clue_applicable=candidate,
        participates_in_clue_allocation=candidate,
        location_source="test",
        location_status="valid",
        location_updated_at=_dt(1),
    )


def _lead() -> ClueMasterLead:
    return ClueMasterLead(
        lead_key="lead-1",
        source_clue_row_key="raw-lead-1",
        source_identity_key="identity-lead-1",
        canonical_clue_id="clue-lead-1",
        order_id="order-1",
        normalized_order_status="active",
        status_source="test",
        lifecycle_status="active",
        allocation_state="pending_allocation",
        anchor_poi_id="poi-anchor",
        anchor_store_id="anchor",
        anchor_source="test",
        anchor_province="CN-SH",
        anchor_city="CN-SH",
        anchor_city_code="CN-SH",
        anchor_longitude=Decimal("121.470000"),
        anchor_latitude=Decimal("31.230000"),
        first_seen_at=_dt(1),
        last_seen_at=_dt(1),
        created_at=_dt(1),
        updated_at=_dt(1),
    )


def _strategy_configs() -> list[dict]:
    return [
        {
            "strategy_type": "sales_store_priority",
            "enabled": False,
            "execution_order": 1,
            "params": {"max_distance_km": 10},
        },
        {
            "strategy_type": "nearby_city_optimization",
            "enabled": True,
            "execution_order": 2,
            "params": {"max_distance_km": 15},
        },
        {
            "strategy_type": "city_fallback",
            "enabled": False,
            "execution_order": 3,
            "params": {},
        },
    ]


def _publish_rule_version(
    session: Session,
    *,
    name: str,
    scope_type: str,
    city_code: str | None = None,
    lookback_days: int = 30,
    min_samples: int = 1,
    conversion_weight: Decimal = Decimal("0.7"),
    follow_24h_weight: Decimal = Decimal("0.3"),
):
    rule = create_rule(
        session,
        name=name,
        scope_type=scope_type,
        city_code=city_code,
        created_by="test-admin",
    )
    version = create_rule_version(
        session,
        rule.rule_id,
        auto_expiry_enabled=True,
        first_follow_up_sla_hours=24,
        protection_days=7,
        conversion_weight=conversion_weight,
        follow_24h_weight=follow_24h_weight,
        lookback_days=lookback_days,
        min_samples=min_samples,
        strategy_configs=_strategy_configs(),
        created_by="test-admin",
    )
    return publish_rule_version(session, version.rule_version_id, published_by="test-admin")


def _add_score_run(
    session: Session,
    *,
    run_id: str,
    rule_version_id: str | None,
    scores: dict[str, Decimal],
    computed_at: datetime,
) -> None:
    config = {
        "rule_version_id": rule_version_id,
        "lookback_days": 30,
        "min_samples": 1,
        "conversion_weight": "0.7",
        "follow_24h_weight": "0.3",
        "store_weight": "1",
    }
    session.add(
        StoreScoreSnapshotRun(
            snapshot_run_id=run_id,
            snapshot_date=computed_at.date(),
            run_mode="scheduled",
            window_start=computed_at - timedelta(days=30),
            window_end=computed_at,
            candidate_store_count=len(scores),
            snapshot_count=len(scores),
            config_json=config,
            computed_at=computed_at,
        )
    )
    for store_id, composite_score in scores.items():
        session.add(
            StoreScoreSnapshot(
                snapshot_id=f"{run_id}-{store_id}",
                snapshot_run_id=run_id,
                snapshot_date=computed_at.date(),
                run_mode="scheduled",
                store_id=store_id,
                city_code="CN-SH",
                window_start=computed_at - timedelta(days=30),
                window_end=computed_at,
                conversion_numerator=1,
                conversion_denominator=1,
                conversion_rate=Decimal("1"),
                conversion_value_source="store",
                follow_24h_numerator=0,
                follow_24h_denominator=1,
                follow_24h_rate=Decimal("0"),
                follow_24h_value_source="store",
                conversion_weight=Decimal("0.7"),
                follow_24h_weight=Decimal("0.3"),
                store_weight=Decimal("1"),
                composite_score=composite_score,
                config_json=config,
                computed_at=computed_at,
            )
        )


def test_scheduled_refresh_scores_each_published_rule_version_with_its_own_config(
    db_session: Session,
    monkeypatch,
) -> None:
    global_version = _publish_rule_version(
        db_session,
        name="Global",
        scope_type="global",
        lookback_days=60,
        conversion_weight=Decimal("0.8"),
        follow_24h_weight=Decimal("0.2"),
    )
    city_version = _publish_rule_version(
        db_session,
        name="Shanghai",
        scope_type="city",
        city_code="CN-SH",
        lookback_days=14,
        conversion_weight=Decimal("0.2"),
        follow_24h_weight=Decimal("0.8"),
    )
    db_session.add(_store("candidate"))
    db_session.commit()
    monkeypatch.setattr(
        clue_allocation,
        "_formal_store_metrics",
        lambda *_args: {
            "candidate": clue_allocation.StoreMetrics(
                conversion_numerator=1,
                conversion_denominator=1,
                follow_24h_numerator=0,
                follow_24h_denominator=1,
            )
        },
    )
    now = datetime(2026, 7, 10, 19, 1, tzinfo=timezone.utc)

    result = clue_allocation.refresh_due_store_score_snapshots(db_session, now=now)

    assert result["snapshots"] == 2
    runs = db_session.scalars(
        select(StoreScoreSnapshotRun).where(StoreScoreSnapshotRun.run_mode == "scheduled")
    ).all()
    assert len(runs) == 2
    runs_by_version = {run.config_json["rule_version_id"]: run for run in runs}
    assert set(runs_by_version) == {global_version.rule_version_id, city_version.rule_version_id}
    city_run = runs_by_version[city_version.rule_version_id]
    city_snapshot = db_session.scalar(
        select(StoreScoreSnapshot).where(StoreScoreSnapshot.snapshot_run_id == city_run.snapshot_run_id)
    )
    assert city_snapshot is not None
    actual_window_start = city_run.window_start
    if actual_window_start.tzinfo is None:
        actual_window_start = actual_window_start.replace(tzinfo=timezone.utc)
    assert actual_window_start == now - timedelta(days=14)
    assert city_run.config_json["min_samples"] == 1
    assert city_snapshot.conversion_weight == Decimal("0.2")
    assert city_snapshot.follow_24h_weight == Decimal("0.8")
    assert city_snapshot.store_weight == Decimal("1")
    assert city_snapshot.composite_score == Decimal("0.2")


def test_allocation_selects_scores_from_the_lead_bound_rule_version_only(db_session: Session) -> None:
    global_version = _publish_rule_version(db_session, name="Global", scope_type="global")
    city_version = _publish_rule_version(
        db_session,
        name="Shanghai",
        scope_type="city",
        city_code="CN-SH",
    )
    lead = _lead()
    db_session.add_all([_store("anchor", candidate=False), _store("store-a"), _store("store-b"), lead])
    _add_score_run(
        db_session,
        run_id="city-score-run",
        rule_version_id=city_version.rule_version_id,
        scores={"store-a": Decimal("0.1"), "store-b": Decimal("0.9")},
        computed_at=_dt(2),
    )
    _add_score_run(
        db_session,
        run_id="global-score-run",
        rule_version_id=global_version.rule_version_id,
        scores={"store-a": Decimal("0.9"), "store-b": Decimal("0.1")},
        computed_at=_dt(3),
    )
    _add_score_run(
        db_session,
        run_id="legacy-score-run",
        rule_version_id=None,
        scores={"store-a": Decimal("0.99"), "store-b": Decimal("0.01")},
        computed_at=_dt(4),
    )
    binding = bind_lead_rule_version(
        db_session,
        lead_key=lead.lead_key,
        anchor_store_id=lead.anchor_store_id,
        anchor_city_code=lead.anchor_city_code,
    )
    db_session.commit()

    result = allocate_lead(db_session, lead.lead_key, actor="test-admin")

    assert binding.rule_version_id == city_version.rule_version_id
    assert result.status == "assigned"
    assert result.selected_store_id == "store-b"
