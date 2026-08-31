from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import apps.worker.clue_allocation_cycles as clue_allocation_cycles
from apps.api.dy_api.models import (
    ClueAllocationAuditLog,
    ClueAllocationCandidate,
    ClueAllocationCycle,
    ClueAllocationCycleItem,
    ClueAllocationDecision,
    ClueAssignmentRound,
    ClueFollowUpRecord,
    ClueHeadquartersPoolEntry,
    ClueMasterLead,
    DimStore,
)
from apps.worker.clue_allocation_cycles import (
    AllocationCycleError,
    preview_trial_allocation_cycle,
    rebuild_trial_allocation_cycle,
    run_trial_allocation_cycle,
)
from apps.worker.clue_rule_versions import create_rule, create_rule_version, publish_rule_version


def _dt(day: int, hour: int = 9) -> datetime:
    return datetime(2026, 7, day, hour, tzinfo=timezone.utc)


def test_candidate_model_declares_the_migration_ranking_index() -> None:
    assert "ix_clue_allocation_candidates_composite_score" in {
        index.name for index in ClueAllocationCandidate.__table__.indexes
    }


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


def _lead(lead_key: str = "lead-1") -> ClueMasterLead:
    return ClueMasterLead(
        lead_key=lead_key,
        source_clue_row_key=f"raw-{lead_key}",
        source_identity_key=f"identity-{lead_key}",
        canonical_clue_id=f"clue-{lead_key}",
        order_id=f"order-{lead_key}",
        normalized_order_status="active",
        status_source="test",
        lifecycle_status="active",
        allocation_state="pending_allocation",
        anchor_poi_id="poi-anchor",
        anchor_store_id="anchor",
        anchor_source="douyin_follow_poi",
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


def _publish_global_rule(session: Session) -> None:
    rule = create_rule(session, name="Global default", scope_type="global", created_by="test-admin")
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
        strategy_configs=[
            {
                "strategy_type": "sales_store_priority",
                "enabled": True,
                "execution_order": 1,
                "params": {"max_distance_km": 10},
            },
            {
                "strategy_type": "nearby_city_optimization",
                "enabled": True,
                "execution_order": 2,
                "params": {"max_distance_km": 15},
            },
            {"strategy_type": "city_fallback", "enabled": True, "execution_order": 3, "params": {}},
        ],
        created_by="test-admin",
    )
    publish_rule_version(session, version.rule_version_id, published_by="test-admin")


def _seed_trial_candidates(session: Session) -> ClueMasterLead:
    lead = _lead()
    session.add_all([_store("anchor", candidate=False), _store("store-a"), _store("store-b"), lead])
    _publish_global_rule(session)
    session.commit()
    return lead


def test_trial_preview_does_not_persist_bindings_decisions_rounds_or_pool_entries(db_session: Session) -> None:
    lead = _seed_trial_candidates(db_session)

    preview = preview_trial_allocation_cycle(
        db_session,
        lead_keys=[lead.lead_key],
        actor="test-admin",
        now=_dt(2),
    )

    assert preview["requested_lead_count"] == 1
    assert preview["summary"]["assigned"] == 1
    assert db_session.scalar(select(func.count()).select_from(ClueAllocationCycle)) == 0
    assert db_session.scalar(select(func.count()).select_from(ClueAllocationDecision)) == 0
    assert db_session.scalar(select(func.count()).select_from(ClueAssignmentRound)) == 0
    refreshed = db_session.get(ClueMasterLead, lead.lead_key)
    assert refreshed is not None
    assert refreshed.current_assignment_round_id is None
    assert refreshed.allocation_state == "pending_allocation"


def test_trial_cycle_persists_evidence_without_mutating_business_state(db_session: Session) -> None:
    lead = _seed_trial_candidates(db_session)

    result = run_trial_allocation_cycle(
        db_session,
        lead_keys=[lead.lead_key],
        actor="test-admin",
        now=_dt(2),
    )

    cycle = db_session.get(ClueAllocationCycle, result["allocation_cycle_id"])
    master = db_session.get(ClueMasterLead, lead.lead_key)
    assert cycle is not None
    assert cycle.cycle_type == "trial"
    assert cycle.execution_mode == "trial"
    assert cycle.status == "completed"
    assert master is not None
    assert master.current_assignment_round_id is None
    assert master.allocation_state == "pending_allocation"
    assert master.pool_location is None
    assert db_session.scalar(select(func.count()).select_from(ClueAssignmentRound)) == 0
    decisions = list(
        db_session.scalars(
            select(ClueAllocationDecision)
            .where(ClueAllocationDecision.allocation_cycle_id == cycle.allocation_cycle_id)
        )
    )
    assert decisions
    assert all(decision.execution_mode == "trial" for decision in decisions)
    assert all(decision.assignment_round_id is None for decision in decisions)
    assert all((decision.decision_snapshot or {}).get("dataset_kind") == "trial" for decision in decisions)
    item = db_session.scalar(
        select(ClueAllocationCycleItem).where(
            ClueAllocationCycleItem.allocation_cycle_id == cycle.allocation_cycle_id
        )
    )
    assert item is not None
    assert item.lead_key == lead.lead_key
    assert item.initial_pool_location == "pending_allocation"
    assert item.item_status == "assigned"
    assert item.decision_id in {decision.decision_id for decision in decisions}
    candidates = list(
        db_session.scalars(
            select(ClueAllocationCandidate).where(
                ClueAllocationCandidate.decision_id.in_(
                    [decision.decision_id for decision in decisions]
                )
            )
        )
    )
    assert candidates
    assert any(candidate.is_selected for candidate in candidates)
    assert db_session.scalar(select(func.count()).select_from(ClueAllocationAuditLog)) == 1


def test_failed_trial_cycle_records_a_failed_audit_result(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lead = _seed_trial_candidates(db_session)

    def fail_trial_evidence(*args, **kwargs):
        raise RuntimeError("simulated trial failure")

    monkeypatch.setattr(
        clue_allocation_cycles,
        "_persist_trial_evidence",
        fail_trial_evidence,
    )

    result = run_trial_allocation_cycle(
        db_session,
        lead_keys=[lead.lead_key],
        actor="test-admin",
        now=_dt(2),
    )

    assert result["cycle_status"] == "failed"
    audit = db_session.scalar(select(ClueAllocationAuditLog))
    assert audit is not None
    assert audit.result_status == "failed"
    assert audit.reason_code == "cycle_items_failed"


def test_rebuild_creates_new_immutable_trial_evidence_without_rounds(db_session: Session) -> None:
    lead = _seed_trial_candidates(db_session)
    first = run_trial_allocation_cycle(
        db_session,
        lead_keys=[lead.lead_key],
        actor="test-admin",
        now=_dt(2),
    )
    source_decision_ids = set(
        db_session.scalars(
            select(ClueAllocationDecision.decision_id)
            .where(ClueAllocationDecision.allocation_cycle_id == first["allocation_cycle_id"])
        )
    )

    rebuilt = rebuild_trial_allocation_cycle(
        db_session,
        source_cycle_id=first["allocation_cycle_id"],
        actor="test-admin",
        now=_dt(3),
    )

    rebuilt_cycle = db_session.get(ClueAllocationCycle, rebuilt["allocation_cycle_id"])
    rebuilt_decision_ids = set(
        db_session.scalars(
            select(ClueAllocationDecision.decision_id)
            .where(ClueAllocationDecision.allocation_cycle_id == rebuilt["allocation_cycle_id"])
        )
    )
    current = db_session.get(ClueMasterLead, lead.lead_key)
    assert rebuilt_cycle is not None
    assert rebuilt_cycle.cycle_type == "trial_rebuild"
    assert rebuilt_cycle.parent_cycle_id == first["allocation_cycle_id"]
    assert source_decision_ids
    assert rebuilt_decision_ids
    assert source_decision_ids.isdisjoint(rebuilt_decision_ids)
    assert current is not None
    assert current.current_assignment_round_id is None
    assert current.allocation_state == "pending_allocation"
    assert db_session.scalar(select(func.count()).select_from(ClueAssignmentRound)) == 0
    assert first["allocation_cycle_id"] != rebuilt["allocation_cycle_id"]


def test_rebuild_links_to_the_latest_cycle_for_the_selected_lead_only(
    db_session: Session,
) -> None:
    lead_a = _seed_trial_candidates(db_session)
    lead_b = _lead("lead-2")
    db_session.add(lead_b)
    db_session.commit()

    first_a = run_trial_allocation_cycle(
        db_session,
        lead_keys=[lead_a.lead_key],
        actor="test-admin",
        now=_dt(2),
    )
    first = run_trial_allocation_cycle(
        db_session,
        lead_keys=[lead_b.lead_key],
        actor="test-admin",
        now=_dt(3),
    )

    rebuilt = rebuild_trial_allocation_cycle(
        db_session,
        source_cycle_id=first_a["allocation_cycle_id"],
        actor="test-admin",
        now=_dt(4),
    )

    cycle = db_session.get(ClueAllocationCycle, rebuilt["allocation_cycle_id"])
    assert cycle is not None
    assert cycle.parent_cycle_id == first_a["allocation_cycle_id"]


def test_rebuild_blocks_formal_follow_up_without_privileged_confirmation(db_session: Session) -> None:
    lead = _seed_trial_candidates(db_session)
    first = run_trial_allocation_cycle(
        db_session,
        lead_keys=[lead.lead_key],
        actor="test-admin",
        now=_dt(2),
    )
    formal_round = ClueAssignmentRound(
        assignment_round_id="formal-followed-round",
        order_id=lead.order_id or "",
        lead_key=lead.lead_key,
        round_no=1,
        assigned_at=_dt(3),
        assigned_store_id="store-a",
        assigned_store_name="store-a",
        followed_at=_dt(3),
        follow_result="appointment",
        is_followed=True,
        is_follow_success=True,
        round_status="closed_reassigned",
        execution_mode="formal",
        reassign_reason="manual_test",
        reassigned_at=_dt(3),
        created_at=_dt(3),
        updated_at=_dt(3),
    )
    db_session.add_all(
        [
            formal_round,
            ClueFollowUpRecord(
                follow_up_record_id="formal-followed-record",
                order_id=lead.order_id or "",
                assignment_round_id=formal_round.assignment_round_id,
                round_no=1,
                assigned_store_id="store-a",
                follow_result="appointment",
                note="Formal follow-up must block a routine rebuild.",
                operator_username="test-admin",
                created_at=_dt(3),
            ),
        ]
    )
    db_session.commit()

    with pytest.raises(AllocationCycleError, match="rebuild_blocked_by_follow_up"):
        rebuild_trial_allocation_cycle(
            db_session,
            source_cycle_id=first["allocation_cycle_id"],
            actor="test-admin",
            now=_dt(4),
        )


def test_trial_headquarters_result_does_not_move_master_or_create_pool_entry(
    db_session: Session,
) -> None:
    lead = _seed_trial_candidates(db_session)
    for store_id in ("store-a", "store-b"):
        store = db_session.get(DimStore, store_id)
        assert store is not None
        store.is_active = False
        store.is_douyin_clue_applicable = False
        store.participates_in_clue_allocation = False
    db_session.commit()

    result = run_trial_allocation_cycle(
        db_session,
        lead_keys=[lead.lead_key],
        actor="test-admin",
        now=_dt(2),
    )

    master = db_session.get(ClueMasterLead, lead.lead_key)
    entry = db_session.scalar(
        select(ClueHeadquartersPoolEntry)
        .where(ClueHeadquartersPoolEntry.lead_key == lead.lead_key)
        .where(ClueHeadquartersPoolEntry.status == "active")
    )
    assert result["summary"]["headquarters"] == 1
    assert master is not None
    assert master.allocation_cycle_id is None
    assert master.pool_location is None
    assert master.allocation_state == "pending_allocation"
    assert entry is None
    assert db_session.scalar(select(func.count()).select_from(ClueAssignmentRound)) == 0


def test_trial_rejects_headquarters_pool_reentry(db_session: Session) -> None:
    lead = _seed_trial_candidates(db_session)
    lead.pool_location = "headquarters_pool"
    lead.allocation_state = "headquarters"
    db_session.commit()

    with pytest.raises(AllocationCycleError, match="headquarters_reentry_not_supported"):
        run_trial_allocation_cycle(
            db_session,
            lead_keys=[lead.lead_key],
            actor="test-admin",
            now=_dt(2),
        )
