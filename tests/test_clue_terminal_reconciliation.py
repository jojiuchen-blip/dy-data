from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, func

from apps.api.dy_api.models import (
    ClueMasterLead, ClueAssignmentRound, ClueCenterOrder, ClueFollowUpRecord,
    ClueOrderStatusEvent, RawDouyinClue, RawDouyinOrder, RawDouyinOrderCoupon,
    SettlementOrderDetail,
)
from apps.worker.clue_allocation import materialize_clue_master_leads


START = datetime(2026, 10, 1, 2, tzinfo=timezone.utc)


def seed_assigned(session):
    raw = RawDouyinClue(clue_row_key="raw-terminal", clue_id="clue-terminal",
        order_id="order-terminal", order_status="履约中", source_observed_at=START,
        observation_key="original", raw_payload={"version": 1}, updated_at=START)
    order = RawDouyinOrder(order_id="order-terminal", order_status="201",
        order_status_normalized="paid", updated_at=START)
    session.add_all([raw, order])
    session.flush()
    materialize_clue_master_leads(session, order_ids={order.order_id}, now=START)
    lead = session.scalar(select(ClueMasterLead).where(ClueMasterLead.order_id == order.order_id))
    lead.pool_location, lead.allocation_state = "store_follow_up_pool", "assigned"
    lead.current_assignment_round_id = "round-terminal"
    row = ClueAssignmentRound(assignment_round_id="round-terminal", lead_key=lead.lead_key,
        order_id=order.order_id, assigned_at=START, assigned_store_id="store-terminal",
        round_no=1, execution_mode="formal", round_status="active_followed",
        follow_result="further_follow_up", is_followed=True)
    center = ClueCenterOrder(order_id=order.order_id, lead_status="active",
        current_assignment_round_id=row.assignment_round_id, current_round_status=row.round_status,
        assigned_store_id=row.assigned_store_id, assigned_at=START)
    follow = ClueFollowUpRecord(follow_up_record_id="follow-terminal", order_id=order.order_id,
        assignment_round_id=row.assignment_round_id, round_no=1, assigned_store_id=row.assigned_store_id,
        follow_result="further_follow_up", created_at=START + timedelta(hours=1), note="preserve")
    session.add_all([row, center, follow])
    session.commit()
    return raw, order, lead, row, center, follow


@pytest.mark.parametrize("terminal", ["verified", "refunded"])
def test_unchanged_clue_accepts_new_order_terminal_and_preserves_history(db_session, terminal):
    raw, order, lead, row, center, follow = seed_assigned(db_session)
    source_snapshot = (lead.last_seen_at, lead.last_observation_key, lead.source_identity_key, raw.raw_payload)
    if terminal == "verified":
        db_session.add(SettlementOrderDetail(order_id=order.order_id, coupon_id="coupon-terminal",
            product_type="maintenance", is_verified=True, verify_time=START + timedelta(hours=2)))
    else:
        db_session.add(RawDouyinOrderCoupon(order_id=order.order_id, coupon_id="coupon-terminal",
            coupon_status="301", coupon_status_normalized="refunded",
            latest_refund_at=START + timedelta(hours=2), source_observed_at=START + timedelta(hours=3)))
    order.updated_at = START + timedelta(hours=3)
    db_session.commit()
    result = materialize_clue_master_leads(db_session, order_ids={order.order_id}, now=START + timedelta(days=1))
    db_session.commit()
    assert result["closed_leads"] == 1
    assert lead.lifecycle_status == "closed_" + terminal
    assert lead.pool_location == lead.allocation_state == "closed"
    assert row.round_status == "closed_order_" + terminal
    assert center.lead_status == ("converted" if terminal == "verified" else "refunded")
    assert row.follow_result == "further_follow_up" and row.is_followed
    assert db_session.get(ClueFollowUpRecord, follow.follow_up_record_id).note == "preserve"
    assert source_snapshot == (lead.last_seen_at, lead.last_observation_key, lead.source_identity_key, raw.raw_payload)
    event_count = db_session.scalar(select(func.count()).select_from(ClueOrderStatusEvent))
    version = lead.state_version
    materialize_clue_master_leads(db_session, order_ids={order.order_id}, now=START + timedelta(days=2))
    db_session.commit()
    assert lead.state_version == version
    assert db_session.scalar(select(func.count()).select_from(ClueOrderStatusEvent)) == event_count
    assert db_session.scalar(select(func.count()).select_from(ClueFollowUpRecord)) == 1


def test_terminal_order_before_first_materialization_never_enters_assignment_pool(db_session):
    db_session.add_all([
        RawDouyinClue(clue_row_key="pre-closed", clue_id="pre-closed", order_id="pre-closed",
            order_status="履约中", source_observed_at=START, updated_at=START),
        RawDouyinOrder(order_id="pre-closed", order_status="已退款", updated_at=START),
    ])
    db_session.flush()
    materialize_clue_master_leads(db_session, order_ids={"pre-closed"}, now=START)
    db_session.commit()
    lead = db_session.scalar(select(ClueMasterLead).where(ClueMasterLead.order_id == "pre-closed"))
    assert lead.lifecycle_status == "closed_refunded"
    assert lead.ended_without_assignment
    assert lead.current_assignment_round_id is None


def add_refund(session, order):
    session.add(RawDouyinOrderCoupon(order_id=order.order_id, coupon_id="refund-guard",
        coupon_status="301", coupon_status_normalized="refunded",
        latest_refund_at=START + timedelta(hours=2), source_observed_at=START + timedelta(hours=3)))
    session.commit()


@pytest.mark.parametrize("action", ["appointment", "request_store_change"])
def test_terminal_evidence_blocks_follow_and_transfer_before_projection(db_session, action):
    from apps.worker.clue_follow_up_state import apply_follow_up_action
    raw, order, lead, row, center, follow = seed_assigned(db_session)
    add_refund(db_session, order)
    result = apply_follow_up_action(db_session, order_id=order.order_id,
        assignment_round_id=row.assignment_round_id, follow_result=action,
        actor={"role": "admin", "auth_type": "env_admin", "is_highest_admin": True},
        now=START + timedelta(hours=4))
    assert result.status == "conflict" and result.record is None
    assert lead.lifecycle_status == "closed_refunded"
    assert row.round_status == "closed_order_refunded"
    assert db_session.scalar(select(func.count()).select_from(ClueFollowUpRecord)) == 1


def test_terminal_evidence_blocks_allocation_and_due_reassignment(db_session):
    from apps.worker.clue_allocation_engine import allocate_lead
    from apps.worker.clue_follow_up_state import process_due_transitions
    raw, order, lead, row, center, follow = seed_assigned(db_session)
    add_refund(db_session, order)
    result = process_due_transitions(db_session, now=START + timedelta(days=2))
    assert result["terminal_closed"] == 1
    assert result["sla_expired"] == result["protection_expired"] == 0
    allocate_lead(db_session, lead.lead_key, actor="admin", now=START + timedelta(days=2))
    assert db_session.scalar(select(func.count()).select_from(ClueAssignmentRound)) == 1
    assert lead.allocation_state == "closed"


def test_terminal_repair_is_dry_run_bounded_and_idempotent(db_session):
    from sqlalchemy.orm import sessionmaker
    from scripts.repair_clue_terminal_states import repair_terminal_states
    raw, order, lead, row, center, follow = seed_assigned(db_session)
    add_refund(db_session, order)
    key = lead.lead_key
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False)
    preview = repair_terminal_states(factory, batch_size=1, max_batches=1)
    assert preview["dry_run"] and preview["changed_masters"] == 1
    assert preview["after"] == key and not preview["complete"]
    db_session.expire_all()
    assert db_session.get(ClueMasterLead, key).lifecycle_status == "active"
    applied = repair_terminal_states(factory, apply=True)
    assert applied["changed_masters"] == applied["changed_rounds"] == applied["changed_centers"] == 1
    repeated = repair_terminal_states(factory, apply=True)
    assert repeated["changed_masters"] == repeated["changed_rounds"] == repeated["changed_centers"] == 0
    assert repeated["complete"]
    db_session.expire_all()
    assert db_session.scalar(select(func.count()).select_from(ClueFollowUpRecord)) == 1
    assert db_session.get(ClueFollowUpRecord, "follow-terminal").note == "preserve"


def test_score_counts_active_under_24h_without_changing_conversion_maturity(db_session):
    from apps.api.dy_api.models import DimStore
    from apps.worker.clue_allocation import _formal_store_metrics
    raw, order, lead, row, center, follow = seed_assigned(db_session)
    db_session.delete(follow)
    row.matured_at = None
    db_session.commit()
    store = DimStore(store_id="store-terminal", store_name="Terminal")
    metrics = _formal_store_metrics(db_session, [store], START - timedelta(days=1), START + timedelta(hours=2))
    assert metrics[store.store_id].follow_24h_denominator == 1
    assert metrics[store.store_id].follow_24h_numerator == 0
    assert metrics[store.store_id].conversion_denominator == 0
    add_refund(db_session, order)
    metrics = _formal_store_metrics(db_session, [store], START - timedelta(days=1), START + timedelta(hours=4))
    assert metrics[store.store_id].follow_24h_denominator == 0
    assert metrics[store.store_id].conversion_denominator == 0


def test_definitive_terminal_closes_newer_active_projection_clock(db_session):
    from apps.worker.clue_allocation import refresh_terminal_evidence_for_locked_lead
    raw, order, lead, row, center, follow = seed_assigned(db_session)
    add_refund(db_session, order)
    lead.order_status_observed_at = START + timedelta(hours=5)
    db_session.commit()
    assert refresh_terminal_evidence_for_locked_lead(db_session, lead, now=START + timedelta(hours=6))
    assert lead.lifecycle_status == "closed_refunded"
    assert row.round_status == "closed_order_refunded"
    assert lead.closed_at == START + timedelta(hours=2)
    assert lead.order_status_observed_at == START + timedelta(hours=5)


@pytest.mark.parametrize("source", ["verify", "refund"])
def test_new_raw_terminal_event_without_order_or_clue_update_closes_all_projections(db_session, source):
    from apps.api.dy_api.models import RawDouyinVerifyRecord, RawDouyinRefundRecord
    raw, order, lead, row, center, follow = seed_assigned(db_session)
    if source == "verify":
        db_session.add(RawDouyinOrderCoupon(order_id=order.order_id, coupon_id="raw-event-coupon",
            coupon_status_normalized="available", source_observed_at=START))
        db_session.add(RawDouyinVerifyRecord(verify_id="raw-event-verify", coupon_id="raw-event-coupon",
            verify_status="success", verify_time=START + timedelta(hours=2),
            source_observed_at=START + timedelta(hours=3)))
    else:
        db_session.add(RawDouyinRefundRecord(source_record_key="raw-event-refund", refund_id="raw-event-refund",
            order_id=order.order_id, normalized_refund_status=2, raw_refund_status="50",
            refund_completed_at=START + timedelta(hours=2), source_observed_at=START + timedelta(hours=3),
            payload_hash="event", raw_payload={"refund_type": "2"}))
    db_session.commit()
    materialize_clue_master_leads(db_session, order_ids={order.order_id}, now=START + timedelta(hours=4))
    expected = "verified" if source == "verify" else "refunded"
    assert lead.normalized_order_status == expected
    assert row.round_status == "closed_order_" + expected
    assert center.lead_status == ("converted" if source == "verify" else "refunded")
    assert db_session.scalar(select(func.count()).select_from(ClueFollowUpRecord)) == 1


def test_canceled_verification_does_not_close_from_stale_settlement(db_session):
    from apps.api.dy_api.models import RawDouyinVerifyRecord
    raw, order, lead, row, center, follow = seed_assigned(db_session)
    db_session.add_all([
        RawDouyinOrderCoupon(order_id=order.order_id, coupon_id="cancel-coupon",
            coupon_status_normalized="available", source_observed_at=START + timedelta(hours=3)),
        RawDouyinVerifyRecord(verify_id="cancel-verify", coupon_id="cancel-coupon", verify_status="success",
            verify_time=START + timedelta(hours=1), cancel_time=START + timedelta(hours=2),
            source_observed_at=START + timedelta(hours=3)),
        SettlementOrderDetail(order_id=order.order_id, coupon_id="cancel-coupon", verify_id="cancel-verify",
            product_type="maintenance", is_verified=True, verify_time=START + timedelta(hours=1),
            updated_at=START + timedelta(hours=1)),
    ])
    db_session.commit()
    materialize_clue_master_leads(db_session, order_ids={order.order_id}, now=START + timedelta(hours=4))
    assert lead.lifecycle_status == "active"
    assert row.round_status == "active_followed"


def test_terminal_guard_does_not_close_round_owned_by_another_lead(db_session):
    from apps.worker.clue_allocation import refresh_terminal_evidence_for_locked_lead
    raw, order, lead, row, center, follow = seed_assigned(db_session)
    add_refund(db_session, order)
    row.lead_key = "other-lead"
    db_session.commit()
    assert refresh_terminal_evidence_for_locked_lead(db_session, lead, now=START + timedelta(hours=4))
    assert lead.lifecycle_status == "closed_refunded"
    assert row.round_status == "active_followed"
