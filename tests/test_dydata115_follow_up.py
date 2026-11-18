"""Product-bound follow-up deadlines and immutable task history."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from apps.api.dy_api.models import (
    ClueAllocationAuditLog, ClueAssignmentRound, ClueCenterOrder,
    ClueFollowUpRecord, ClueLeadRuleVersionBinding, ClueMasterLead,
    RawDouyinOrder, RawDouyinOrderCoupon,
)
from apps.worker import clue_allocation_engine
from apps.worker.clue_follow_up_state import (
    apply_follow_up_action, run_product_follow_up_batch, soft_delete_follow_up_record,
)


START = datetime(2026, 11, 17, tzinfo=timezone.utc)
ACTOR = {"role": "admin", "store_scope_mode": "all", "username": "test-admin"}


def seed_product_task(session, *, key="one", mode="flow", round_no=0, policy=None):
    lead = ClueMasterLead(
        lead_key=f"lead-{key}", source_clue_row_key=f"raw-{key}",
        source_identity_key=f"identity-{key}", order_id=f"order-{key}",
        routing_mode=mode, normalized_order_status="active", lifecycle_status="active",
        allocation_state="assigned", pool_location="store_follow_up_pool",
        current_assignment_round_id=f"round-{key}", created_at=START, updated_at=START,
    )
    row = ClueAssignmentRound(
        assignment_round_id=f"round-{key}", lead_key=lead.lead_key, order_id=lead.order_id,
        assigned_store_id="store-one", round_no=round_no, assigned_at=START,
        round_status="active_unfollowed", execution_mode="formal", follow_result="pending",
        is_followed=False, is_follow_success=False, auto_expiry_enabled=True,
        first_follow_up_sla_hours=24, first_sla_expires_at=START + timedelta(hours=24),
        expires_at=START + timedelta(hours=24), created_at=START, updated_at=START,
    )
    center = ClueCenterOrder(
        order_id=lead.order_id, lead_status="active", current_assignment_round_id=row.assignment_round_id,
        assigned_store_id=row.assigned_store_id, current_round_no=round_no,
        current_round_status=row.round_status, assigned_at=START,
    )
    session.add(lead)
    session.flush()
    session.add_all([row, center])
    if policy is not None:
        session.add(ClueLeadRuleVersionBinding(
            lead_key=lead.lead_key, rule_version_id="test-version", scope_type="global", scope_key="global",
            rule_version_snapshot={"follow_up_policy": policy},
        ))
    session.commit()
    return lead, row


def submit(session, row, action, *, now=None, appointment_at=None, note=None):
    return apply_follow_up_action(
        session, order_id=row.order_id, assignment_round_id=row.assignment_round_id,
        follow_result=action, actor=ACTOR, appointment_at=appointment_at,
        now=now or START + timedelta(hours=1), note=note,
    )


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


@pytest.mark.parametrize("mode", ["flow", "direct", "original"])
def test_appointment_requires_real_zoned_time_but_other_actions_need_no_note(db_session, mode):
    _, row = seed_product_task(db_session, mode=mode)
    assert submit(db_session, row, "appointment").status == "appointment_required"
    assert submit(db_session, row, "appointment", appointment_at=START.replace(tzinfo=None)).status == "appointment_invalid"
    assert db_session.scalar(select(func.count()).select_from(ClueFollowUpRecord)) == 0
    result = submit(db_session, row, "further_follow_up")
    assert result.status == "ok" and result.record.note is None
    assert utc(row.protection_expires_at) == START + timedelta(hours=169)


def test_effective_status_changes_and_real_rebooking_recompute_without_note_extension(db_session):
    _, row = seed_product_task(db_session)
    appointment = (START + timedelta(days=5)).astimezone(timezone(timedelta(hours=8)))
    first = submit(db_session, row, "appointment", appointment_at=appointment)
    db_session.commit()
    initial_deadline = utc(row.protection_expires_at)
    assert initial_deadline == START + timedelta(days=8)
    assert utc(row.appointment_at) == utc(appointment)
    repeat = submit(db_session, row, "appointment", appointment_at=appointment,
                    now=START + timedelta(hours=2), note="added note")
    assert repeat.status == "ok" and repeat.record.follow_up_record_id != first.record.follow_up_record_id
    assert utc(row.protection_expires_at) == initial_deadline
    assert utc(row.protection_started_at) == START + timedelta(hours=1)
    submit(db_session, row, "appointment", appointment_at=appointment + timedelta(days=20),
           now=START + timedelta(hours=3))
    assert utc(row.protection_expires_at) == initial_deadline + timedelta(days=20)
    submit(db_session, row, "further_follow_up", now=START + timedelta(hours=4))
    assert row.appointment_at is None
    assert utc(row.protection_expires_at) == START + timedelta(hours=172)
    submit(db_session, row, "further_follow_up", now=START + timedelta(hours=5), note="same result")
    assert utc(row.protection_expires_at) == START + timedelta(hours=172)
    submit(db_session, row, "unreachable", now=START + timedelta(hours=6))
    assert utc(row.protection_expires_at) == START + timedelta(hours=174)
    assert db_session.scalar(select(func.count()).select_from(ClueFollowUpRecord)) == 6


def test_bound_policy_supplies_hours_and_new_records_cannot_be_reversed(db_session):
    lead, row = seed_product_task(db_session, policy={"further_follow_up_hours": 48})
    record = submit(db_session, row, "further_follow_up").record
    assert utc(row.protection_expires_at) == START + timedelta(hours=49)
    result = soft_delete_follow_up_record(db_session, follow_up_record_id=record.follow_up_record_id,
                                         actor=ACTOR, reason="correction")
    assert result.status == "immutable" and record.deleted_at is None
    db_session.commit()
    db_session.expire_all()
    assert db_session.get(ClueMasterLead, lead.lead_key).current_assignment_round_id == row.assignment_round_id
    assert db_session.get(ClueFollowUpRecord, record.follow_up_record_id).deleted_at is None


@pytest.mark.parametrize("mode", ["flow", "direct", "original"])
@pytest.mark.parametrize("action,reason", [("lost", "follow_lost"), ("request_store_change", "request_store_change")])
def test_business_close_never_queues_another_store(db_session, mode, action, reason):
    lead, row = seed_product_task(db_session, mode=mode)
    assert submit(db_session, row, action).status == "ok"
    db_session.commit()
    assert lead.current_assignment_round_id is None
    assert lead.pool_location == lead.allocation_state == "closed"
    assert lead.closed_reason == row.terminal_reason == reason
    assert utc(row.closed_at) == START + timedelta(hours=1)
    assert submit(db_session, row, "further_follow_up").status == "conflict"
    assert db_session.scalar(select(func.count()).select_from(ClueAssignmentRound)) == 1
    assert db_session.scalar(select(func.count()).select_from(ClueFollowUpRecord)) == 1


def next_store(session, lead_key, *, now, transition_key):
    lead = session.get(ClueMasterLead, lead_key)
    previous = session.scalars(select(ClueAssignmentRound).where(ClueAssignmentRound.lead_key == lead_key)).one()
    assert previous.round_status not in {"active_unfollowed", "active_followed"}
    row = ClueAssignmentRound(
        assignment_round_id=previous.assignment_round_id + "-next", order_id=lead.order_id,
        lead_key=lead_key, round_no=previous.round_no + 1, assigned_store_id="store-two",
        assigned_at=now, round_status="active_unfollowed", execution_mode="formal",
        follow_result="pending", is_followed=False, auto_expiry_enabled=True,
        first_sla_expires_at=now + timedelta(hours=24), updated_at=now,
    )
    session.add(row)
    lead.current_assignment_round_id = row.assignment_round_id
    lead.pool_location, lead.allocation_state = "store_follow_up_pool", "assigned"
    return SimpleNamespace(status="assigned")


def test_due_handoff_commits_old_invalidation_before_new_task_and_replay_is_empty(db_session, monkeypatch):
    lead, old = seed_product_task(db_session)
    monkeypatch.setattr(clue_allocation_engine, "continue_product_routing", next_store, raising=False)
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False)
    now = START + timedelta(days=2)
    stats = run_product_follow_up_batch(factory, now=now)
    assert stats["assigned"] == stats["sla_expired"] == 1
    assert run_product_follow_up_batch(factory, now=now)["processed"] == 0
    db_session.expire_all()
    assert utc(old.closed_at) == now
    assert lead.current_assignment_round_id == old.assignment_round_id + "-next"
    rows = db_session.scalars(select(ClueAssignmentRound)).all()
    assert len(rows) == 2
    assert sum(row.round_status in {"active_unfollowed", "active_followed"} for row in rows) == 1


@pytest.mark.parametrize("mode", [None, "direct", "original"])
def test_product_worker_never_expires_legacy_or_non_flow_tasks(db_session, monkeypatch, mode):
    lead, row = seed_product_task(db_session, mode=mode)
    monkeypatch.setattr(clue_allocation_engine, "continue_product_routing", lambda *a, **k: pytest.fail("unexpected allocation"), raising=False)
    assert run_product_follow_up_batch(sessionmaker(bind=db_session.get_bind()), now=START + timedelta(days=365))["processed"] == 0
    db_session.expire_all()
    assert lead.current_assignment_round_id == row.assignment_round_id
    assert row.round_status == "active_unfollowed"


@pytest.mark.parametrize("round_no,action", [(2, None), (0, "unreachable"), (1, "unreachable")])
def test_final_round_and_unreachable_close_instead_of_continuation(db_session, monkeypatch, round_no, action):
    lead, row = seed_product_task(db_session, round_no=round_no)
    if action:
        submit(db_session, row, action)
        db_session.commit()
    monkeypatch.setattr(clue_allocation_engine, "continue_product_routing", lambda *a, **k: pytest.fail("unexpected allocation"), raising=False)
    stats = run_product_follow_up_batch(sessionmaker(bind=db_session.get_bind()), now=START + timedelta(days=20))
    assert stats["closed"] == 1
    db_session.expire_all()
    assert lead.allocation_state == "closed"
    assert row.closed_at is not None


def test_failed_handoff_rolls_back_then_fairly_yields_to_untouched_due_task(db_session, monkeypatch):
    first, old = seed_product_task(db_session, key="a")
    second, other = seed_product_task(db_session, key="b", round_no=2)
    def fail(session, lead_key, **kwargs):
        session.add(ClueAssignmentRound(assignment_round_id="must-rollback", order_id=first.order_id,
                    lead_key=lead_key, round_no=1, assigned_at=START, execution_mode="formal"))
        session.flush()
        raise RuntimeError("injected failure")
    monkeypatch.setattr(clue_allocation_engine, "continue_product_routing", fail, raising=False)
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False)
    assert run_product_follow_up_batch(factory, now=START + timedelta(days=2), batch_size=1)["failed"] == 1
    db_session.expire_all()
    assert first.current_assignment_round_id == old.assignment_round_id
    assert old.round_status == "active_unfollowed" and old.closed_at is None
    assert db_session.get(ClueAssignmentRound, "must-rollback") is None
    assert db_session.scalar(select(func.count()).select_from(ClueAllocationAuditLog)) == 1
    assert run_product_follow_up_batch(factory, now=START + timedelta(days=2, hours=1), batch_size=1)["closed"] == 1
    db_session.expire_all()
    assert second.allocation_state == "closed" and other.closed_at is not None


def test_due_consumer_rechecks_new_terminal_source_fact_before_selecting_next_store(db_session, monkeypatch):
    lead, row = seed_product_task(db_session)
    db_session.add(RawDouyinOrder(order_id=lead.order_id, order_status="201", updated_at=START))
    db_session.add(RawDouyinOrderCoupon(order_id=lead.order_id, coupon_id="full-refund",
        coupon_status="301", coupon_status_normalized="refunded",
        latest_refund_at=START + timedelta(hours=2), source_observed_at=START + timedelta(hours=3)))
    db_session.commit()
    monkeypatch.setattr(clue_allocation_engine, "continue_product_routing", lambda *a, **k: pytest.fail("terminal must win"), raising=False)
    stats = run_product_follow_up_batch(sessionmaker(bind=db_session.get_bind()), now=START + timedelta(days=2))
    assert stats["terminal_closed"] == 1 and stats["assigned"] == 0
    db_session.expire_all()
    assert lead.normalized_order_status == "refunded"
    assert utc(row.closed_at) == START + timedelta(hours=2)
