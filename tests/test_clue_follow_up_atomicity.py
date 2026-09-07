"""Regression coverage for stale follow-up state and explicit operation scope."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    Base, ClueAssignmentRound, ClueCenterOrder, ClueFollowUpRecord, ClueMasterLead, RawDouyinClue,
)
from apps.worker.clue_follow_up_state import (
    apply_follow_up_action, process_due_transitions, soft_delete_follow_up_record,
)


def seed_active_round(session: Session) -> None:
    now = datetime(2026, 9, 1, tzinfo=timezone.utc)
    session.add_all([
        RawDouyinClue(clue_row_key="audit-raw", order_id="audit-order", order_status="201", telephone="13800000001", raw_payload={}),
        ClueMasterLead(
            lead_key="audit-lead", source_clue_row_key="audit-raw",
            source_identity_key="audit-identity", order_id="audit-order",
            normalized_order_status="active", lifecycle_status="active",
            pool_location="store_follow_up_pool", allocation_state="assigned",
            current_assignment_round_id="audit-round", created_at=now, updated_at=now,
        ),
        ClueAssignmentRound(
            assignment_round_id="audit-round", lead_key="audit-lead", order_id="audit-order",
            round_no=1, execution_mode="formal", round_status="active_unfollowed",
            assigned_store_id="audit-store", assigned_at=now, assigned_at_source="test",
            follow_result="pending", is_followed=False, is_follow_success=False,
            auto_expiry_enabled=True, first_follow_up_sla_hours=24, protection_days=7,
            first_sla_expires_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
            created_at=now, updated_at=now,
        ),
        ClueCenterOrder(
            order_id="audit-order", lead_status="active", current_round_no=1,
            current_assignment_round_id="audit-round", current_round_status="active_unfollowed",
            assigned_store_id="audit-store", phone_plain="13800000001",
            phone_masked="138****0001",
        ),
    ])
    session.flush([item for item in session.new if isinstance(item, ClueMasterLead)])
    session.commit()


STORE_ACTOR = {"role": "store", "store_scope_mode": "specified", "store_ids": ("audit-store",)}
ADMIN_ACTOR = {"role": "admin", "store_scope_mode": "all", "auth_type": "env_admin", "is_highest_admin": True}


def apply_action(session: Session, result: str, *, actor: dict | None = None):
    return apply_follow_up_action(
        session, order_id="audit-order", assignment_round_id="audit-round",
        follow_result=result, actor=actor if actor is not None else STORE_ACTOR,
        now=datetime(2026, 9, 2, tzinfo=timezone.utc),
    )


@pytest.mark.parametrize("closure", ["lost", "request_store_change", "due"])
@pytest.mark.parametrize("dirty", [False, True])
def test_stale_session_cannot_follow_after_committed_closure(tmp_path, closure: str, dirty: bool) -> None:
    engine = create_engine("sqlite+pysqlite:///" + str(tmp_path / "clue-atomicity.db"))
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as setup:
            seed_active_round(setup)
        with Session(engine, autoflush=False) as stale, Session(engine, autoflush=False) as closer:
            held = [stale.get(ClueMasterLead, "audit-lead"), stale.get(ClueAssignmentRound, "audit-round")]
            assert all(held)
            if closure == "due":
                stats = process_due_transitions(closer, now=datetime(2026, 9, 3, tzinfo=timezone.utc))
                assert stats["sla_expired"] == 1
            else:
                assert apply_action(closer, closure).status == "ok"
            closer.commit()
            if dirty:
                held[0].pool_location = "headquarters_pool"
                held[1].follow_result = "appointment"
            assert apply_action(stale, "appointment").status == "conflict"
            stale.commit()
        with Session(engine) as verify:
            assert verify.get(ClueMasterLead, "audit-lead").current_assignment_round_id is None
            assert verify.get(ClueAssignmentRound, "audit-round").round_status == "closed_reassigned"
            assert verify.get(ClueAssignmentRound, "audit-round").follow_result != "appointment"
            assert len(verify.scalars(select(ClueFollowUpRecord)).all()) == (0 if closure == "due" else 1)
    finally:
        engine.dispose()


def test_stale_record_cannot_be_deleted_twice(tmp_path) -> None:
    engine = create_engine("sqlite+pysqlite:///" + str(tmp_path / "clue-delete.db"))
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as setup:
            seed_active_round(setup)
            record_id = apply_action(setup, "appointment").record.follow_up_record_id
            setup.commit()
        with Session(engine, autoflush=False) as stale, Session(engine) as first:
            held = stale.get(ClueFollowUpRecord, record_id)
            assert held.deleted_at is None
            assert soft_delete_follow_up_record(
                first, follow_up_record_id=record_id, actor=ADMIN_ACTOR, reason="first",
            ).status == "ok"
            first.commit()
            assert soft_delete_follow_up_record(
                stale, follow_up_record_id=record_id, actor=ADMIN_ACTOR, reason="second",
            ).status == "conflict"
            stale.commit()
        with Session(engine) as verify:
            assert verify.get(ClueFollowUpRecord, record_id).deletion_reason == "first"
    finally:
        engine.dispose()


@pytest.mark.parametrize("actor,allowed", [
    ({"role": "admin", "store_scope_mode": "all"}, True),
    ({"role": "admin", "store_scope_mode": "specified", "store_ids": ["audit-store"]}, True),
    ({"role": "admin", "store_scope_mode": "specified", "store_ids": ["other"]}, False),
    ({"role": "admin", "store_scope_mode": "specified", "store_ids": []}, False),
    ({"role": "admin", "store_scope_mode": "none", "store_ids": ["audit-store"]}, False),
    ({"role": "admin", "store_ids": ["audit-store"]}, False),
    ({"role": "admin", "store_scope_mode": "unknown"}, False),
    ({"role": "store", "store_scope_mode": "specified", "store_ids": ["audit-store"]}, True),
    ({"role": "store", "store_scope_mode": "all", "store_ids": ["audit-store"]}, False),
    ({"role": "store", "store_ids": ["audit-store"]}, False),
])
def test_follow_up_requires_explicit_store_scope(db_session, actor: dict, allowed: bool) -> None:
    seed_active_round(db_session)
    assert apply_action(db_session, "appointment", actor=actor).status == ("ok" if allowed else "forbidden")
    assert len(db_session.scalars(select(ClueFollowUpRecord)).all()) == int(allowed)
