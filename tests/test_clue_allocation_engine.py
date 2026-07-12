from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    Base,
    ClueAllocationDecision,
    ClueAssignmentRound,
    ClueCenterOrder,
    ClueMasterLead,
    DimStore,
    DimStorePoiMapping,
    RawDouyinClue,
    SettlementOrderDetail,
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


def _store(
    store_id: str,
    *,
    city_code: str = "CN-SH",
    longitude: str = "121.470000",
    latitude: str = "31.230000",
    candidate: bool = True,
) -> DimStore:
    return DimStore(
        store_id=store_id,
        store_name=store_id,
        is_active=candidate,
        standard_province=city_code,
        standard_city=city_code,
        city_code=city_code,
        longitude=Decimal(longitude),
        latitude=Decimal(latitude),
        is_douyin_clue_applicable=candidate,
        participates_in_clue_allocation=candidate,
        location_source="test",
        location_status="valid",
        location_updated_at=_dt(1),
    )


def _lead(
    lead_key: str = "lead-1",
    *,
    order_id: str = "order-1",
    anchor_store_id: str = "anchor",
    anchor_city_code: str = "CN-SH",
) -> ClueMasterLead:
    return ClueMasterLead(
        lead_key=lead_key,
        source_clue_row_key=f"raw-{lead_key}",
        source_identity_key=f"identity-{lead_key}",
        canonical_clue_id=f"clue-{lead_key}",
        order_id=order_id,
        normalized_order_status="active",
        status_source="test",
        lifecycle_status="active",
        allocation_state="pending_allocation",
        anchor_poi_id=f"poi-{anchor_store_id}",
        anchor_store_id=anchor_store_id,
        anchor_source="douyin_follow_poi",
        anchor_province=anchor_city_code,
        anchor_city=anchor_city_code,
        anchor_city_code=anchor_city_code,
        anchor_longitude=Decimal("121.470000"),
        anchor_latitude=Decimal("31.230000"),
        first_seen_at=_dt(1),
        last_seen_at=_dt(1),
        created_at=_dt(1),
        updated_at=_dt(1),
    )


def _strategy_configs(
    *,
    sales_enabled: bool = True,
    nearby_enabled: bool = True,
    fallback_enabled: bool = True,
    sales_distance: int = 10,
    nearby_distance: int = 15,
) -> list[dict]:
    return [
        {
            "strategy_type": "sales_store_priority",
            "enabled": sales_enabled,
            "execution_order": 1,
            "params": {"max_distance_km": sales_distance},
        },
        {
            "strategy_type": "nearby_city_optimization",
            "enabled": nearby_enabled,
            "execution_order": 2,
            "params": {"max_distance_km": nearby_distance},
        },
        {
            "strategy_type": "city_fallback",
            "enabled": fallback_enabled,
            "execution_order": 3,
            "params": {},
        },
    ]


def _publish_global_rule(session: Session, *, strategy_configs: list[dict] | None = None):
    rule = create_rule(session, name="Global default", scope_type="global", created_by="system-admin")
    version = create_rule_version(
        session,
        rule.rule_id,
        auto_expiry_enabled=True,
        first_follow_up_sla_hours=24,
        protection_days=7,
        conversion_weight=Decimal("0.7"),
        follow_24h_weight=Decimal("0.3"),
        lookback_days=30,
        min_samples=20,
        strategy_configs=strategy_configs or _strategy_configs(),
        created_by="system-admin",
    )
    return rule, publish_rule_version(session, version.rule_version_id, published_by="system-admin")


def _new_version(session: Session, rule_id: str, *, strategy_configs: list[dict]):
    version = create_rule_version(
        session,
        rule_id,
        auto_expiry_enabled=True,
        first_follow_up_sla_hours=48,
        protection_days=14,
        conversion_weight=Decimal("0.6"),
        follow_24h_weight=Decimal("0.4"),
        lookback_days=14,
        min_samples=10,
        strategy_configs=strategy_configs,
        created_by="system-admin",
    )
    return publish_rule_version(session, version.rule_version_id, published_by="system-admin")


def _add_sale_store(session: Session, *, order_id: str, store_id: str, coupon_id: str) -> None:
    session.add(
        SettlementOrderDetail(
            coupon_id=coupon_id,
            order_id=order_id,
            product_type="service",
            sale_store_id=store_id,
            sale_time=_dt(1),
            is_verified=False,
            relation_type="same_store",
            is_commissionable=False,
            is_refund_excluded=False,
            paid_amount_cent=0,
            commission_rate=Decimal("0"),
            receivable_commission_cent=0,
            payable_commission_cent=0,
            updated_at=_dt(1),
        )
    )


def _add_scores(session: Session, scores: dict[str, Decimal]) -> None:
    run_id = "score-run"
    if session.get(StoreScoreSnapshotRun, run_id) is None:
        session.add(
            StoreScoreSnapshotRun(
                snapshot_run_id=run_id,
                snapshot_date=date(2026, 7, 1),
                run_mode="scheduled",
                window_start=_dt(1) - timedelta(days=30),
                window_end=_dt(1),
                candidate_store_count=len(scores),
                snapshot_count=len(scores),
                config_json={"source": "test"},
                computed_at=_dt(1),
            )
        )
    for store_id, score in scores.items():
        session.add(
            StoreScoreSnapshot(
                snapshot_id=f"{run_id}-{store_id}",
                snapshot_run_id=run_id,
                snapshot_date=date(2026, 7, 1),
                run_mode="scheduled",
                store_id=store_id,
                city_code="CN-SH",
                window_start=_dt(1) - timedelta(days=30),
                window_end=_dt(1),
                conversion_numerator=4,
                conversion_denominator=10,
                conversion_rate=Decimal("0.4"),
                conversion_value_source="store",
                follow_24h_numerator=8,
                follow_24h_denominator=10,
                follow_24h_rate=Decimal("0.8"),
                follow_24h_value_source="city_average",
                conversion_weight=Decimal("0.7"),
                follow_24h_weight=Decimal("0.3"),
                store_weight=Decimal("1"),
                composite_score=score,
                config_json={"source": "test"},
                computed_at=_dt(1),
            )
        )


def _decision(session: Session, strategy_type: str) -> ClueAllocationDecision:
    row = session.scalar(
        select(ClueAllocationDecision)
        .where(ClueAllocationDecision.strategy_type == strategy_type)
        .order_by(ClueAllocationDecision.executed_at, ClueAllocationDecision.decision_id)
    )
    assert row is not None
    return row


def _active_round(
    *,
    assignment_round_id: str,
    lead_key: str,
    order_id: str,
    store_id: str,
    round_no: int = 1,
    execution_mode: str = "formal",
) -> ClueAssignmentRound:
    return ClueAssignmentRound(
        assignment_round_id=assignment_round_id,
        order_id=order_id,
        lead_key=lead_key,
        round_no=round_no,
        assigned_at=_dt(1),
        assigned_at_source="clue_allocation_engine",
        assigned_store_id=store_id,
        assigned_store_name=store_id,
        follow_result="pending",
        is_followed=False,
        is_follow_success=False,
        round_status="active_unfollowed",
        execution_mode=execution_mode,
        created_at=_dt(1),
        updated_at=_dt(1),
    )


def test_sales_store_priority_assigns_without_score_and_records_complete_snapshot(db_session: Session) -> None:
    lead = _lead()
    db_session.add_all([_store("anchor", candidate=False), _store("sale-store"), lead])
    _add_sale_store(db_session, order_id=lead.order_id or "", store_id="sale-store", coupon_id="coupon-1")
    _publish_global_rule(db_session)
    db_session.commit()

    result = allocate_lead(db_session, lead.lead_key, actor="test-admin")

    assert result.status == "assigned"
    assert result.selected_store_id == "sale-store"
    assert result.assignment_round_id is not None
    round_row = db_session.get(ClueAssignmentRound, result.assignment_round_id)
    assert round_row is not None
    assert round_row.execution_mode == "formal"
    assert round_row.strategy_type == "sales_store_priority"
    assert round_row.round_no == 1
    assert round_row.lead_key == lead.lead_key

    decision = _decision(db_session, "sales_store_priority")
    assert decision.decision_status == "selected"
    assert decision.selected_store_id == "sale-store"
    snapshot = decision.decision_snapshot
    assert snapshot["anchor"]["poi_id"] == "poi-anchor"
    assert snapshot["anchor"]["city_code"] == "CN-SH"
    assert snapshot["sale_store"]["status"] == "resolved"
    assert snapshot["strategy"]["max_distance_km"] == 10.0
    selected_candidate = next(row for row in snapshot["candidates"] if row["store_id"] == "sale-store")
    assert selected_candidate["rank"] == 1
    assert selected_candidate["score"]["used_for_ranking"] is False
    assert "phone" not in json.dumps(snapshot, ensure_ascii=False).lower()

    master = db_session.get(ClueMasterLead, lead.lead_key)
    center = db_session.get(ClueCenterOrder, lead.order_id)
    assert master is not None
    assert master.pool_location == "store_follow_up_pool"
    assert master.allocation_state == "assigned"
    assert master.current_assignment_round_id == result.assignment_round_id
    assert center is not None
    assert center.current_assignment_round_id == result.assignment_round_id
    assert center.assigned_store_id == "sale-store"


@pytest.mark.parametrize(
    ("case", "sale_store_ids", "extra_stores", "reason"),
    [
        ("missing", [], [], "sale_store_missing"),
        ("ambiguous", ["sale-a", "sale-b"], ["sale-a", "sale-b"], "sale_store_ambiguous"),
        ("ineligible", ["sale-a"], ["sale-a"], "sale_store_ineligible"),
        ("over-distance", ["sale-a"], ["sale-a"], "sale_store_over_distance"),
    ],
)
def test_sales_store_invalid_missing_ambiguous_and_over_distance_are_auditable_skips(
    db_session: Session,
    case: str,
    sale_store_ids: list[str],
    extra_stores: list[str],
    reason: str,
) -> None:
    lead = _lead(f"lead-{case}", order_id=f"order-{case}")
    db_session.add_all([_store("anchor", candidate=False), lead])
    for store_id in extra_stores:
        if case == "ineligible":
            db_session.add(_store(store_id, candidate=False))
        elif case == "over-distance":
            db_session.add(_store(store_id, longitude="122.470000"))
        else:
            db_session.add(_store(store_id))
    for index, store_id in enumerate(sale_store_ids):
        _add_sale_store(
            db_session,
            order_id=lead.order_id or "",
            store_id=store_id,
            coupon_id=f"coupon-{case}-{index}",
        )
    _publish_global_rule(
        db_session,
        strategy_configs=_strategy_configs(nearby_enabled=False, fallback_enabled=False),
    )
    db_session.commit()

    result = allocate_lead(db_session, lead.lead_key, actor="test-admin")

    assert result.status == "headquarters"
    assert result.assignment_round_id is None
    sales_decision = _decision(db_session, "sales_store_priority")
    assert sales_decision.decision_status == "skipped"
    assert sales_decision.reason == reason
    assert db_session.scalar(select(func.count()).select_from(ClueAssignmentRound)) == 0
    assert db_session.scalar(
        select(func.count()).select_from(ClueAllocationDecision).where(
            ClueAllocationDecision.decision_status == "headquarters"
        )
    ) == 1


def test_sales_store_priority_excludes_a_previously_assigned_store(db_session: Session) -> None:
    lead = _lead()
    historical = _active_round(
        assignment_round_id="formal-history",
        lead_key=lead.lead_key,
        order_id=lead.order_id or "",
        store_id="sale-store",
    )
    historical.round_status = "expired"
    historical.matured_at = _dt(2)
    db_session.add_all(
        [
            _store("anchor", candidate=False),
            _store("sale-store"),
            _store("nearby-store"),
            lead,
            historical,
        ]
    )
    _add_sale_store(db_session, order_id=lead.order_id or "", store_id="sale-store", coupon_id="coupon-1")
    _add_scores(db_session, {"nearby-store": Decimal("0.8")})
    _publish_global_rule(db_session)
    db_session.commit()

    result = allocate_lead(db_session, lead.lead_key, actor="test-admin")

    assert result.status == "assigned"
    assert result.selected_store_id == "nearby-store"
    decision = _decision(db_session, "sales_store_priority")
    assert decision.reason == "sale_store_previously_assigned"
    sale_candidate = next(
        row for row in decision.decision_snapshot["candidates"] if row["store_id"] == "sale-store"
    )
    assert sale_candidate["exclusion_reasons"] == ["historically_self_owned"]


def test_nearby_city_ranking_uses_score_then_distance_then_store_id_and_excludes_history(
    db_session: Session,
) -> None:
    lead = _lead()
    db_session.add_all(
        [
            _store("anchor", candidate=False),
            _store("history-store", longitude="121.471000"),
            _store("store-b", longitude="121.470000"),
            _store("store-a", longitude="121.470000"),
            lead,
            _active_round(
                assignment_round_id="formal-history",
                lead_key=lead.lead_key,
                order_id=lead.order_id or "",
                store_id="history-store",
            ),
        ]
    )
    _add_scores(
        db_session,
        {
            "history-store": Decimal("0.99"),
            "store-a": Decimal("0.80"),
            "store-b": Decimal("0.80"),
        },
    )
    _publish_global_rule(db_session)
    db_session.commit()

    result = allocate_lead(db_session, lead.lead_key, actor="test-admin")

    assert result.status == "assigned"
    assert result.selected_store_id == "store-a"
    decision = _decision(db_session, "nearby_city_optimization")
    assert decision.selected_store_id == "store-a"
    candidates = {row["store_id"]: row for row in decision.decision_snapshot["candidates"]}
    assert candidates["history-store"]["exclusion_reasons"] == ["historically_self_owned"]
    assert candidates["store-a"]["rank"] == 1
    assert candidates["store-b"]["rank"] == 2
    assert candidates["store-a"]["score"]["snapshot_date"] == "2026-07-01"
    assert candidates["store-a"]["score"]["follow_24h_value_source"] == "city_average"


def test_nearby_city_prefers_latest_score_before_distance(db_session: Session) -> None:
    lead = _lead()
    db_session.add_all(
        [
            _store("anchor", candidate=False),
            _store("a-near-low-score", longitude="121.471000"),
            _store("z-far-high-score", longitude="121.550000"),
            lead,
        ]
    )
    _add_scores(
        db_session,
        {
            "a-near-low-score": Decimal("0.10"),
            "z-far-high-score": Decimal("0.90"),
        },
    )
    _publish_global_rule(db_session)
    db_session.commit()

    result = allocate_lead(db_session, lead.lead_key, actor="test-admin")

    assert result.selected_store_id == "z-far-high-score"
    decision = _decision(db_session, "nearby_city_optimization")
    candidates = {candidate["store_id"]: candidate for candidate in decision.decision_snapshot["candidates"]}
    assert candidates["z-far-high-score"]["rank"] == 1
    assert candidates["a-near-low-score"]["rank"] == 2


def test_city_fallback_selects_same_city_candidate_after_nearby_distance_skip(db_session: Session) -> None:
    lead = _lead()
    db_session.add_all(
        [
            _store("anchor", candidate=False),
            _store("far-store", longitude="121.770000"),
            lead,
        ]
    )
    _add_scores(db_session, {"far-store": Decimal("0.75")})
    _publish_global_rule(db_session)
    db_session.commit()

    result = allocate_lead(db_session, lead.lead_key, actor="test-admin")

    assert result.status == "assigned"
    assert result.selected_store_id == "far-store"
    assert db_session.get(ClueAssignmentRound, result.assignment_round_id).strategy_type == "city_fallback"
    nearby = _decision(db_session, "nearby_city_optimization")
    assert nearby.decision_status == "skipped"
    assert nearby.reason == "no_candidate"
    fallback = _decision(db_session, "city_fallback")
    assert fallback.decision_status == "selected"
    far_candidate = next(
        candidate
        for candidate in fallback.decision_snapshot["candidates"]
        if candidate["store_id"] == "far-store"
    )
    assert far_candidate["distance_km"] > 15


def test_disabled_strategy_logs_skip_before_next_enabled_strategy(db_session: Session) -> None:
    lead = _lead()
    db_session.add_all([_store("anchor", candidate=False), _store("sale-store"), _store("best-store"), lead])
    _add_sale_store(db_session, order_id=lead.order_id or "", store_id="sale-store", coupon_id="coupon-1")
    _add_scores(db_session, {"sale-store": Decimal("0.1"), "best-store": Decimal("0.9")})
    _publish_global_rule(db_session, strategy_configs=_strategy_configs(sales_enabled=False))
    db_session.commit()

    result = allocate_lead(db_session, lead.lead_key, actor="test-admin")

    assert result.selected_store_id == "best-store"
    assert _decision(db_session, "sales_store_priority").reason == "strategy_disabled"
    assert db_session.get(ClueAssignmentRound, result.assignment_round_id).strategy_type == "nearby_city_optimization"


def test_no_candidate_routes_to_headquarters_with_final_audit_and_no_empty_round(db_session: Session) -> None:
    lead = _lead()
    db_session.add_all([_store("anchor", candidate=False), lead])
    _publish_global_rule(db_session)
    db_session.commit()

    result = allocate_lead(db_session, lead.lead_key, actor="test-admin")

    assert result.status == "headquarters"
    assert result.assignment_round_id is None
    assert db_session.scalar(select(func.count()).select_from(ClueAssignmentRound)) == 0
    master = db_session.get(ClueMasterLead, lead.lead_key)
    assert master is not None
    assert master.pool_location == "headquarters_pool"
    assert master.allocation_state == "headquarters"
    final = _decision(db_session, "allocation_finalization")
    assert final.decision_status == "headquarters"
    assert final.reason == "no_candidate"


def test_rule_version_unavailable_is_retryable_after_a_global_rule_is_published(db_session: Session) -> None:
    lead = _lead()
    db_session.add_all([_store("anchor", candidate=False), _store("candidate"), lead])
    _add_scores(db_session, {"candidate": Decimal("0.8")})
    db_session.commit()

    first = allocate_lead(db_session, lead.lead_key, actor="test-admin")

    assert first.status == "headquarters"
    assert first.reason == "rule_version_unavailable"
    assert _decision(db_session, "rule_version_resolution").decision_status == "headquarters"

    _publish_global_rule(db_session)
    db_session.commit()
    second = allocate_lead(db_session, lead.lead_key, actor="test-admin")

    assert second.status == "assigned"
    assert second.selected_store_id == "candidate"


def test_bound_rule_snapshot_survives_future_rule_change_and_excludes_phone(db_session: Session) -> None:
    lead = _lead()
    db_session.add_all([_store("anchor", candidate=False), _store("candidate"), lead])
    _add_scores(db_session, {"candidate": Decimal("0.8")})
    rule, first_version = _publish_global_rule(db_session)
    binding = bind_lead_rule_version(
        db_session,
        lead_key=lead.lead_key,
        anchor_store_id=lead.anchor_store_id,
        anchor_city_code=lead.anchor_city_code,
    )
    second_version = _new_version(
        db_session,
        rule.rule_id,
        strategy_configs=_strategy_configs(nearby_enabled=False, fallback_enabled=True),
    )
    db_session.commit()

    result = allocate_lead(db_session, lead.lead_key, actor="test-admin")

    assert result.selected_store_id == "candidate"
    assert binding.rule_version_id == first_version.rule_version_id
    assert second_version.rule_version_id != first_version.rule_version_id
    decision = _decision(db_session, "nearby_city_optimization")
    assert decision.rule_version_id == first_version.rule_version_id
    assert decision.decision_snapshot["rule_version"]["timing"] == {
        "auto_expiry_enabled": True,
        "first_follow_up_sla_hours": 24,
        "protection_days": 7,
        "lookback_days": 30,
        "min_samples": 20,
        "conversion_weight": 0.7,
        "follow_24h_weight": 0.3,
    }
    assert "phone" not in json.dumps(decision.decision_snapshot, ensure_ascii=False).lower()


def test_repeating_same_first_allocation_is_idempotent(db_session: Session) -> None:
    lead = _lead()
    db_session.add_all([_store("anchor", candidate=False), _store("sale-store"), lead])
    _add_sale_store(db_session, order_id=lead.order_id or "", store_id="sale-store", coupon_id="coupon-1")
    _publish_global_rule(db_session)
    db_session.commit()

    first = allocate_lead(db_session, lead.lead_key, actor="test-admin")
    second = allocate_lead(db_session, lead.lead_key, actor="test-admin")

    assert second.assignment_round_id == first.assignment_round_id
    assert second.selected_store_id == first.selected_store_id
    assert db_session.scalar(select(func.count()).select_from(ClueAssignmentRound)) == 1
    decisions = db_session.scalars(select(ClueAllocationDecision)).all()
    assert len(decisions) == 1
    assert decisions[0].attempt_key.startswith("clue-allocation:")


def test_round_namespace_allows_legacy_and_formal_round_one_for_one_order(db_session: Session) -> None:
    lead = _lead()
    db_session.add(lead)
    db_session.add_all(
        [
            _active_round(
                assignment_round_id="order-1-1",
                lead_key=lead.lead_key,
                order_id="order-1",
                store_id="legacy-store",
                execution_mode="legacy",
            ),
            _active_round(
                assignment_round_id="formal-order-1-1",
                lead_key=lead.lead_key,
                order_id="order-1",
                store_id="formal-store",
                execution_mode="formal",
            ),
        ]
    )
    db_session.flush()

    constraints = {constraint.name for constraint in Base.metadata.tables["clue_assignment_rounds"].constraints}
    assert "uq_clue_assignment_rounds_lead_execution_mode_round" in constraints
    assert "uq_clue_assignment_rounds_order_round" not in constraints
    assert db_session.scalar(select(func.count()).select_from(ClueAssignmentRound)) == 2


def test_contact_level_leads_for_one_order_each_start_at_round_one_without_overwriting_projection(
    db_session: Session,
) -> None:
    first = _lead("lead-first", order_id="shared-order")
    second = _lead("lead-second", order_id="shared-order")
    db_session.add_all([_store("anchor", candidate=False), _store("candidate"), first, second])
    _add_scores(db_session, {"candidate": Decimal("0.8")})
    _publish_global_rule(db_session)
    db_session.commit()

    first_result = allocate_lead(db_session, first.lead_key, actor="test-admin")
    second_result = allocate_lead(db_session, second.lead_key, actor="test-admin")

    first_round = db_session.get(ClueAssignmentRound, first_result.assignment_round_id)
    second_round = db_session.get(ClueAssignmentRound, second_result.assignment_round_id)
    center_order = db_session.get(ClueCenterOrder, "shared-order")
    assert first_round is not None and first_round.round_no == 1
    assert second_round is not None and second_round.round_no == 1
    assert first_round.lead_key != second_round.lead_key
    assert center_order is not None
    assert center_order.current_assignment_round_id == first_result.assignment_round_id


def test_master_materialization_preserves_active_self_owned_state_and_closes_it_on_terminal_order(
    db_session: Session,
) -> None:
    db_session.add_all(
        [
            _store("anchor"),
            DimStorePoiMapping(store_id="anchor", poi_id="poi-anchor", mapping_source="test"),
            RawDouyinClue(
                clue_row_key="raw-1",
                clue_id="clue-1",
                order_id="order-1",
                order_status="履约中",
                follow_poi_id="poi-anchor",
                create_time_detail=_dt(1),
                fetched_at=_dt(1),
                raw_payload={"clue_id": "clue-1"},
                imported_at=_dt(1),
                updated_at=_dt(1),
            ),
        ]
    )
    db_session.commit()
    clue_allocation.materialize_clue_master_leads(db_session, now=_dt(2))
    master = db_session.scalar(select(ClueMasterLead).where(ClueMasterLead.order_id == "order-1"))
    assert master is not None
    formal = _active_round(
        assignment_round_id="formal-order-1-1",
        lead_key=master.lead_key,
        order_id="order-1",
        store_id="formal-store",
    )
    master.current_assignment_round_id = formal.assignment_round_id
    master.pool_location = "store_follow_up_pool"
    master.allocation_state = "assigned"
    db_session.add(formal)
    db_session.commit()

    clue_allocation.materialize_clue_master_leads(db_session, now=_dt(3))

    preserved = db_session.get(ClueMasterLead, master.lead_key)
    assert preserved is not None
    assert preserved.current_assignment_round_id == formal.assignment_round_id
    assert preserved.pool_location == "store_follow_up_pool"
    assert preserved.allocation_state == "assigned"

    raw = db_session.get(RawDouyinClue, "raw-1")
    assert raw is not None
    raw.order_status = "已核销"
    db_session.commit()
    clue_allocation.materialize_clue_master_leads(db_session, now=_dt(4))

    closed = db_session.get(ClueMasterLead, master.lead_key)
    round_row = db_session.get(ClueAssignmentRound, formal.assignment_round_id)
    assert closed is not None
    assert closed.lifecycle_status == "closed_verified"
    assert closed.allocation_state == "closed"
    assert round_row is not None
    assert round_row.round_status == "closed_order_verified"
    assert round_row.terminal_reason == "order_verified"
