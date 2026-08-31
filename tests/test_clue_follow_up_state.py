from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    ClueAssignmentRound,
    ClueCenterOrder,
    ClueFollowUpRecord,
    ClueMasterLead,
    DimStore,
)
from apps.worker.clue_allocation_engine import allocate_lead
from apps.worker.clue_follow_up_state import (
    apply_follow_up_action,
    process_due_transitions,
    soft_delete_follow_up_record,
)
from apps.worker.clue_rule_versions import create_rule, create_rule_version, publish_rule_version


def _dt(day: int, hour: int = 9) -> datetime:
    return datetime(2026, 7, day, hour, tzinfo=timezone.utc)


def _active_formal_round() -> tuple[ClueMasterLead, ClueAssignmentRound]:
    lead = ClueMasterLead(
        lead_key="lead-1",
        source_clue_row_key="raw-1",
        source_identity_key="identity-1",
        order_id="order-1",
        normalized_order_status="active",
        lifecycle_status="active",
        pool_location="store_follow_up_pool",
        allocation_state="assigned",
        current_assignment_round_id="round-1",
        created_at=_dt(1),
        updated_at=_dt(1),
    )
    round_row = ClueAssignmentRound(
        assignment_round_id="round-1",
        order_id="order-1",
        lead_key="lead-1",
        round_no=1,
        assigned_at=_dt(1),
        assigned_at_source="test",
        assigned_store_id="store-1",
        follow_result="pending",
        is_followed=False,
        is_follow_success=False,
        round_status="active_unfollowed",
        execution_mode="formal",
        first_sla_expires_at=_dt(2),
        auto_expiry_enabled=True,
        first_follow_up_sla_hours=24,
        protection_days=7,
        created_at=_dt(1),
        updated_at=_dt(1),
    )
    return lead, round_row


def _store(store_id: str, *, candidate: bool = True) -> DimStore:
    return DimStore(
        store_id=store_id,
        store_name=store_id,
        is_active=candidate,
        standard_province="CN-SH",
        standard_city="CN-SH",
        city_code="CN-SH",
        longitude=121.47,
        latitude=31.23,
        is_douyin_clue_applicable=candidate,
        participates_in_clue_allocation=candidate,
        location_source="test",
        location_status="valid",
        location_updated_at=_dt(1),
    )


def _allocate_engine_round(db_session: Session, *, auto_expiry_enabled: bool = True) -> ClueAssignmentRound:
    lead = ClueMasterLead(
        lead_key="engine-lead",
        source_clue_row_key="engine-raw",
        source_identity_key="engine-identity",
        order_id="engine-order",
        normalized_order_status="active",
        lifecycle_status="active",
        allocation_state="pending_allocation",
        anchor_poi_id="anchor-poi",
        anchor_store_id="anchor",
        anchor_source="douyin_follow_poi",
        anchor_province="CN-SH",
        anchor_city="CN-SH",
        anchor_city_code="CN-SH",
        anchor_longitude=121.47,
        anchor_latitude=31.23,
        first_seen_at=_dt(1),
        last_seen_at=_dt(1),
        created_at=_dt(1),
        updated_at=_dt(1),
    )
    db_session.add_all([_store("anchor", candidate=False), _store("store-a"), _store("store-b"), lead])
    rule = create_rule(db_session, name="global", scope_type="global", created_by="admin")
    version = create_rule_version(
        db_session,
        rule.rule_id,
        auto_expiry_enabled=auto_expiry_enabled,
        first_follow_up_sla_hours=24,
        protection_days=7,
        conversion_weight=0.7,
        follow_24h_weight=0.3,
        lookback_days=30,
        min_samples=20,
        strategy_configs=[
            {"strategy_type": "sales_store_priority", "enabled": False, "execution_order": 1, "params": {"max_distance_km": 10}},
            {"strategy_type": "nearby_city_optimization", "enabled": True, "execution_order": 2, "params": {"max_distance_km": 15}},
            {"strategy_type": "city_fallback", "enabled": True, "execution_order": 3, "params": {}},
        ],
        created_by="admin",
    )
    publish_rule_version(db_session, version.rule_version_id, published_by="admin")
    db_session.commit()
    result = allocate_lead(db_session, lead.lead_key, actor="admin", now=_dt(1))
    assert result.assignment_round_id is not None
    round_row = db_session.get(ClueAssignmentRound, result.assignment_round_id)
    assert round_row is not None
    return round_row


def test_first_protection_action_sets_fixed_window_without_extension(db_session: Session) -> None:
    lead, round_row = _active_formal_round()
    db_session.add_all([lead, round_row])
    db_session.commit()

    first = apply_follow_up_action(
        db_session,
        order_id="order-1",
        assignment_round_id="round-1",
        follow_result="appointment",
        actor={"user_id": "store-user", "username": "store-user", "role": "store", "auth_type": "user", "store_ids": ("store-1",)},
        now=_dt(3),
    )

    assert first.status == "ok"
    assert round_row.protection_started_at == _dt(3)
    assert round_row.protection_expires_at == _dt(3) + timedelta(days=7)

    second = apply_follow_up_action(
        db_session,
        order_id="order-1",
        assignment_round_id="round-1",
        follow_result="unreachable",
        actor={"user_id": "store-user", "username": "store-user", "role": "store", "auth_type": "user", "store_ids": ("store-1",)},
        now=_dt(4),
    )

    assert second.status == "ok"
    assert round_row.protection_started_at == _dt(3)
    assert round_row.protection_expires_at == _dt(3) + timedelta(days=7)


def test_admin_and_assigned_store_can_write_but_master_pool_pointer_is_authoritative(db_session: Session) -> None:
    lead, round_row = _active_formal_round()
    db_session.add_all([lead, round_row])
    db_session.commit()

    ordinary_admin = apply_follow_up_action(
        db_session,
        order_id="order-1",
        assignment_round_id="round-1",
        follow_result="appointment",
        actor={"user_id": "admin-user", "username": "admin-user", "role": "admin", "auth_type": "user", "is_highest_admin": False},
        now=_dt(2),
    )
    assert ordinary_admin.status == "ok"

    lead.pool_location = "headquarters_pool"
    highest_admin = apply_follow_up_action(
        db_session,
        order_id="order-1",
        assignment_round_id="round-1",
        follow_result="appointment",
        actor={"username": "ordinary-admin", "role": "admin", "auth_type": "user", "is_highest_admin": False},
        now=_dt(2),
    )
    assert highest_admin.status == "conflict"


def test_only_highest_admin_can_soft_delete_without_reopening_a_terminal_round(db_session: Session) -> None:
    lead, round_row = _active_formal_round()
    db_session.add_all([lead, round_row])
    db_session.commit()
    created = apply_follow_up_action(
        db_session,
        order_id="order-1",
        assignment_round_id="round-1",
        follow_result="appointment",
        actor={"username": "system-admin", "role": "admin", "auth_type": "env_admin", "is_highest_admin": True},
        now=_dt(2),
    )
    assert created.record is not None

    denied = soft_delete_follow_up_record(
        db_session,
        follow_up_record_id=created.record.follow_up_record_id,
        actor={"username": "ordinary-admin", "role": "admin", "auth_type": "user", "is_highest_admin": False},
        reason="correction",
        now=_dt(3),
    )
    assert denied.status == "forbidden"

    round_row.round_status = "closed_reassigned"
    round_row.terminal_reason = "follow_lost"
    lead.current_assignment_round_id = None
    deleted = soft_delete_follow_up_record(
        db_session,
        follow_up_record_id=created.record.follow_up_record_id,
        actor={"username": "system-admin", "role": "admin", "auth_type": "env_admin", "is_highest_admin": True},
        reason="correction",
        now=_dt(3),
    )

    assert deleted.status == "ok"
    assert created.record.deleted_at == _dt(3)
    assert created.record.deleted_by_username == "system-admin"
    assert created.record.deletion_reason == "correction"
    assert round_row.round_status == "closed_reassigned"
    assert lead.current_assignment_round_id is None


def test_soft_delete_rejects_trial_evidence_without_mutating_round_or_projection(
    db_session: Session,
) -> None:
    lead, round_row = _active_formal_round()
    round_row.execution_mode = "trial"
    round_row.follow_result = "unreachable"
    round_row.is_followed = True
    round_row.is_follow_success = True
    round_row.round_status = "active_followed"
    center = ClueCenterOrder(
        order_id=round_row.order_id,
        lead_status="active",
        current_assignment_round_id=round_row.assignment_round_id,
        current_round_no=round_row.round_no,
        current_round_status=round_row.round_status,
        follow_result=round_row.follow_result,
        is_followed=True,
        is_follow_success=True,
        created_at=_dt(1),
        updated_at=_dt(1),
    )
    record = ClueFollowUpRecord(
        follow_up_record_id="trial-evidence",
        order_id=round_row.order_id,
        assignment_round_id=round_row.assignment_round_id,
        round_no=round_row.round_no,
        assigned_store_id=round_row.assigned_store_id,
        follow_result="unreachable",
        created_at=_dt(2),
    )
    db_session.add_all([lead, round_row, center, record])
    db_session.commit()

    result = soft_delete_follow_up_record(
        db_session,
        follow_up_record_id=record.follow_up_record_id,
        actor={
            "username": "system-admin",
            "role": "admin",
            "auth_type": "env_admin",
            "is_highest_admin": True,
        },
        reason="correction",
        now=_dt(3),
    )

    assert result.status == "conflict"
    assert record.deleted_at is None
    assert round_row.follow_result == "unreachable"
    assert round_row.round_status == "active_followed"
    assert center.follow_result == "unreachable"
    assert center.current_round_status == "active_followed"


def test_shared_order_follow_up_isolated_by_assignment_round_and_lead_key(db_session: Session) -> None:
    lead_a, round_a = _active_formal_round()
    lead_b = ClueMasterLead(
        lead_key="lead-2",
        source_clue_row_key="raw-2",
        source_identity_key="identity-2",
        order_id="order-1",
        normalized_order_status="active",
        lifecycle_status="active",
        pool_location="store_follow_up_pool",
        allocation_state="assigned",
        current_assignment_round_id="round-2",
        created_at=_dt(1),
        updated_at=_dt(1),
    )
    round_b = ClueAssignmentRound(
        assignment_round_id="round-2",
        order_id="order-1",
        lead_key="lead-2",
        round_no=1,
        assigned_at=_dt(1),
        assigned_at_source="test",
        assigned_store_id="store-2",
        follow_result="pending",
        is_followed=False,
        is_follow_success=False,
        round_status="active_unfollowed",
        execution_mode="formal",
        first_sla_expires_at=_dt(2),
        auto_expiry_enabled=True,
        first_follow_up_sla_hours=24,
        protection_days=7,
        created_at=_dt(1),
        updated_at=_dt(1),
    )
    projection = ClueCenterOrder(
        order_id="order-1",
        lead_status="active",
        current_assignment_round_id="round-1",
        current_round_status="active_unfollowed",
        created_at=_dt(1),
        updated_at=_dt(1),
    )
    db_session.add_all([lead_a, round_a, lead_b, round_b, projection])
    db_session.commit()

    result = apply_follow_up_action(
        db_session,
        order_id="order-1",
        assignment_round_id="round-2",
        follow_result="appointment",
        actor={"username": "system-admin", "role": "admin", "auth_type": "env_admin", "is_highest_admin": True},
        now=_dt(2),
    )

    assert result.status == "ok"
    assert round_a.follow_result == "pending"
    assert round_b.follow_result == "appointment"
    assert projection.current_assignment_round_id == "round-1"
    assert projection.follow_result == "pending"


def test_lost_closes_round_and_waits_for_explicit_reassignment(db_session: Session) -> None:
    round_row = _allocate_engine_round(db_session)
    assert round_row.strategy_type == "nearby_city_optimization"

    result = apply_follow_up_action(
        db_session,
        order_id=round_row.order_id,
        assignment_round_id=round_row.assignment_round_id,
        follow_result="lost",
        actor={"username": "system-admin", "role": "admin", "auth_type": "env_admin", "is_highest_admin": True},
        now=_dt(2),
    )

    assert result.status == "ok"
    assert round_row.round_status == "closed_reassigned"
    assert round_row.terminal_reason == "follow_lost"
    lead = db_session.get(ClueMasterLead, "engine-lead")
    assert lead is not None
    assert lead.current_assignment_round_id is None
    assert lead.allocation_state == "pending_reassign"
    assert db_session.scalar(
        select(func.count()).select_from(ClueAssignmentRound).where(
            ClueAssignmentRound.lead_key == lead.lead_key
        )
    ) == 1


def test_due_transition_respects_auto_expiry_but_terminal_order_still_wins(db_session: Session) -> None:
    due_round = _allocate_engine_round(db_session)
    disabled_lead = ClueMasterLead(
        lead_key="disabled-lead",
        source_clue_row_key="disabled-raw",
        source_identity_key="disabled-identity",
        order_id="disabled-order",
        normalized_order_status="active",
        lifecycle_status="active",
        pool_location="store_follow_up_pool",
        allocation_state="assigned",
        current_assignment_round_id="disabled-round",
        created_at=_dt(1),
        updated_at=_dt(1),
    )
    disabled_round = ClueAssignmentRound(
        assignment_round_id="disabled-round",
        order_id="disabled-order",
        lead_key="disabled-lead",
        round_no=1,
        assigned_at=_dt(1),
        assigned_at_source="test",
        assigned_store_id="store-a",
        follow_result="pending",
        is_followed=False,
        is_follow_success=False,
        round_status="active_unfollowed",
        execution_mode="formal",
        first_sla_expires_at=_dt(2),
        auto_expiry_enabled=False,
        first_follow_up_sla_hours=24,
        protection_days=7,
        created_at=_dt(1),
        updated_at=_dt(1),
    )
    db_session.add_all([disabled_lead, disabled_round])
    db_session.flush()

    stats = process_due_transitions(db_session, now=_dt(3))

    assert stats["sla_expired"] == 1
    assert due_round.round_status == "closed_reassigned"
    due_lead = db_session.get(ClueMasterLead, "engine-lead")
    assert due_lead is not None
    assert due_lead.current_assignment_round_id is None
    assert due_lead.allocation_state == "pending_reassign"
    assert disabled_round.round_status == "active_unfollowed"

    disabled_lead.normalized_order_status = "verified"
    stats = process_due_transitions(db_session, now=_dt(4))

    assert stats["terminal_closed"] == 1
    assert disabled_round.round_status == "closed_order_verified"


def test_terminal_order_action_closes_current_round_before_returning_conflict(
    db_session: Session,
) -> None:
    lead, round_row = _active_formal_round()
    lead.normalized_order_status = "verified"
    db_session.add_all([lead, round_row])
    db_session.commit()

    result = apply_follow_up_action(
        db_session,
        order_id="order-1",
        assignment_round_id="round-1",
        follow_result="appointment",
        actor={"username": "system-admin", "role": "admin", "is_highest_admin": True},
        now=_dt(2),
    )

    assert result.status == "conflict"
    assert round_row.round_status == "closed_order_verified"
    assert lead.lifecycle_status == "closed_verified"
    assert lead.current_assignment_round_id is None
