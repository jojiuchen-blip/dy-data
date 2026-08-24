from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    ClueAllocationAuditLog,
    ClueAllocationCycle,
    ClueAssignmentRound,
    ClueCenterOrder,
    ClueMasterLead,
    DimStore,
)
from apps.worker.clue_operability_recovery import allocate_pending_batch, recover_legacy_batch
from apps.worker.clue_rule_versions import create_rule, create_rule_version, publish_rule_version


def _dt(day: int = 1) -> datetime:
    return datetime(2026, 7, day, 9, tzinfo=timezone.utc)


def _lead(lead_key: str, *, allocation_state: str = "pending_allocation") -> ClueMasterLead:
    return ClueMasterLead(
        lead_key=lead_key,
        source_clue_row_key=f"raw-{lead_key}",
        source_identity_key=f"identity-{lead_key}",
        canonical_clue_id=f"clue-{lead_key}",
        order_id=f"order-{lead_key}",
        normalized_order_status="active",
        status_source="test",
        lifecycle_status="active",
        allocation_state=allocation_state,
        anchor_poi_id="poi-anchor",
        anchor_store_id="anchor",
        anchor_source="douyin_follow_poi",
        anchor_province="CN-SH",
        anchor_city="Shanghai",
        anchor_city_code="CN-SH",
        anchor_longitude=Decimal("121.470000"),
        anchor_latitude=Decimal("31.230000"),
        first_seen_at=_dt(),
        last_seen_at=_dt(),
        created_at=_dt(),
        updated_at=_dt(),
    )


def _publish_rule(session: Session) -> None:
    rule = create_rule(session, name="Recovery rule", scope_type="global", created_by="test")
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
                "strategy_type": "city_fallback",
                "enabled": True,
                "execution_order": 1,
                "params": {},
            },
            {
                "strategy_type": "sales_store_priority",
                "enabled": False,
                "execution_order": 2,
                "params": {"max_distance_km": 10},
            },
            {
                "strategy_type": "nearby_city_optimization",
                "enabled": False,
                "execution_order": 3,
                "params": {"max_distance_km": 15},
            },
        ],
        created_by="test",
    )
    publish_rule_version(session, version.rule_version_id, published_by="test")


def test_legacy_recovery_promotes_current_round_and_is_idempotent(db_session: Session) -> None:
    lead = _lead("legacy-lead", allocation_state="pending_allocation")
    round_row = ClueAssignmentRound(
        assignment_round_id="order-legacy-lead-1",
        order_id=lead.order_id or "",
        lead_key=lead.lead_key,
        round_no=1,
        assigned_at=_dt(),
        assigned_store_id="store-1",
        assigned_store_name="Store 1",
        follow_result="pending",
        round_status="active_unfollowed",
        execution_mode="legacy",
        created_at=_dt(),
        updated_at=_dt(),
    )
    center = ClueCenterOrder(
        order_id=lead.order_id or "",
        lead_status="active",
        current_assignment_round_id=round_row.assignment_round_id,
        current_round_no=1,
        current_round_status="active_unfollowed",
        assigned_store_id="store-1",
        assigned_store_name="Store 1",
        created_at=_dt(),
        updated_at=_dt(),
    )
    db_session.add_all([lead, round_row, center])
    db_session.commit()

    result = recover_legacy_batch(db_session, dry_run=False, now=_dt(2))
    db_session.commit()

    assert result["migrated"] == 1
    assert db_session.get(ClueAssignmentRound, round_row.assignment_round_id).execution_mode == "formal"
    refreshed_lead = db_session.get(ClueMasterLead, lead.lead_key)
    assert refreshed_lead is not None
    assert refreshed_lead.allocation_state == "assigned"
    assert refreshed_lead.pool_location == "store_follow_up_pool"
    assert refreshed_lead.current_assignment_round_id == round_row.assignment_round_id
    assert db_session.scalar(select(func.count()).select_from(ClueAllocationCycle)) == 1

    second = recover_legacy_batch(db_session, dry_run=False, now=_dt(3))
    assert second["scanned"] == 0


def test_legacy_recovery_dry_run_does_not_mutate(db_session: Session) -> None:
    lead = _lead("legacy-dry-run")
    round_row = ClueAssignmentRound(
        assignment_round_id="order-legacy-dry-run-1",
        order_id=lead.order_id or "",
        lead_key=lead.lead_key,
        round_no=1,
        assigned_store_id="store-1",
        assigned_store_name="Store 1",
        round_status="active_unfollowed",
        execution_mode="legacy",
        created_at=_dt(),
        updated_at=_dt(),
    )
    center = ClueCenterOrder(
        order_id=lead.order_id or "",
        lead_status="active",
        current_assignment_round_id=round_row.assignment_round_id,
        current_round_status="active_unfollowed",
        created_at=_dt(),
        updated_at=_dt(),
    )
    db_session.add_all([lead, round_row, center])
    db_session.commit()

    result = recover_legacy_batch(db_session, dry_run=True)

    assert result["eligible"] == 1
    assert db_session.get(ClueAssignmentRound, round_row.assignment_round_id).execution_mode == "legacy"
    assert db_session.scalar(select(func.count()).select_from(ClueAllocationAuditLog)) == 0


def test_pending_recovery_assigns_formal_rounds_and_routes_no_candidate_to_headquarters(
    db_session: Session,
) -> None:
    db_session.add_all(
        [
            DimStore(
                store_id="store-1",
                store_name="Store 1",
                is_active=True,
                participates_in_clue_allocation=True,
                is_douyin_clue_applicable=True,
                standard_province="Shanghai",
                city_code="CN-SH",
                standard_city="Shanghai",
                longitude=Decimal("121.470000"),
                latitude=Decimal("31.230000"),
                location_status="valid",
            ),
            _lead("pending-lead"),
            _lead("no-anchor-lead"),
        ]
    )
    db_session.flush()
    no_anchor = db_session.get(ClueMasterLead, "no-anchor-lead")
    assert no_anchor is not None
    no_anchor.anchor_poi_id = None
    no_anchor.anchor_store_id = None
    no_anchor.anchor_city_code = None
    no_anchor.anchor_unavailable_reason = "follow_poi_missing"
    _publish_rule(db_session)
    db_session.commit()

    result = allocate_pending_batch(db_session, batch_size=2, dry_run=False, now=_dt(2))
    db_session.commit()

    assert result["assigned"] == 1
    assert result["headquarters"] == 1
    assigned = db_session.get(ClueMasterLead, "pending-lead")
    headquarters = db_session.get(ClueMasterLead, "no-anchor-lead")
    assert assigned is not None and assigned.allocation_state == "assigned"
    assert assigned.current_assignment_round_id is not None
    assert headquarters is not None and headquarters.allocation_state == "headquarters"


def test_pending_preview_does_not_persist_recovery_changes(db_session: Session) -> None:
    db_session.add(_lead("pending-preview"))
    db_session.commit()

    result = allocate_pending_batch(db_session, batch_size=1, dry_run=True)

    assert result["scanned"] == 1
    assert db_session.scalar(select(func.count()).select_from(ClueAssignmentRound)) == 0
    lead = db_session.get(ClueMasterLead, "pending-preview")
    assert lead is not None and lead.current_assignment_round_id is None
