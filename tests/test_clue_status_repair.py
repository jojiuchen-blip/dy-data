from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    ClueAssignmentRound,
    ClueCenterOrder,
    ClueMasterLead,
    RawDouyinClue,
    RawDouyinOrder,
    RawDouyinOrderCoupon,
)
from apps.worker.clue_allocation import (
    materialize_clue_master_leads,
    refresh_unknown_clue_master_statuses,
    synchronize_non_active_clue_states,
)


def _now() -> datetime:
    return datetime(2026, 8, 24, 8, tzinfo=timezone.utc)


def _clue(order_id: str) -> RawDouyinClue:
    return RawDouyinClue(
        clue_row_key=f"clue-row-{order_id}",
        clue_id=f"clue-{order_id}",
        order_id=order_id,
        order_status="1",
        create_time_detail=_now(),
        fetched_at=_now(),
        imported_at=_now(),
        updated_at=_now(),
        raw_payload={"clue_id": f"clue-{order_id}"},
    )


def test_materialization_uses_separate_coupon_projection(db_session: Session) -> None:
    order = RawDouyinOrder(
        order_id="order-refunded-by-coupon",
        order_status="1",
        order_status_raw="1",
        order_status_normalized="refunded",
        raw_payload={},
    )
    db_session.add(order)
    db_session.flush()
    db_session.add_all(
        [
            _clue(order.order_id),
            RawDouyinOrderCoupon(
                coupon_id="coupon-refunded-by-coupon",
                order_id=order.order_id,
                raw_order_id=order.id,
                coupon_status="301",
                coupon_status_raw="301",
                coupon_status_normalized="refunded",
                raw_payload={},
            ),
        ]
    )
    db_session.commit()

    materialize_clue_master_leads(db_session, now=_now())
    lead = db_session.query(ClueMasterLead).one()

    assert lead.normalized_order_status == "refunded"
    assert lead.lifecycle_status == "closed_refunded"


def test_unknown_status_repair_is_bounded_idempotent_and_closes_center_row(
    db_session: Session,
) -> None:
    order = RawDouyinOrder(
        order_id="order-repair",
        order_status="1",
        order_status_raw="1",
        order_status_normalized="unknown",
        raw_payload={},
    )
    order_id = order.order_id
    db_session.add(order)
    db_session.flush()
    db_session.add(_clue(order_id))
    db_session.commit()

    materialize_clue_master_leads(db_session, now=_now())
    lead = db_session.query(ClueMasterLead).one()
    lead_key = lead.lead_key
    round_row = ClueAssignmentRound(
        assignment_round_id="order-repair-1",
        order_id=order_id,
        lead_key=lead.lead_key,
        round_no=1,
        assigned_at=_now(),
        assigned_store_id="store-1",
        assigned_store_name="测试门店",
        round_status="active_unfollowed",
        execution_mode="legacy",
    )
    round_id = round_row.assignment_round_id
    lead.current_assignment_round_id = round_row.assignment_round_id
    center = ClueCenterOrder(
        order_id=order_id,
        lead_status="active",
        current_assignment_round_id=round_row.assignment_round_id,
        current_round_status="active_unfollowed",
    )
    db_session.add_all([round_row, center])
    db_session.commit()

    order.order_status_normalized = "refunded"
    db_session.add(
        RawDouyinOrderCoupon(
            coupon_id="coupon-repair",
            order_id=order_id,
            raw_order_id=order.id,
            coupon_status="301",
            coupon_status_raw="301",
            coupon_status_normalized="refunded",
            raw_payload={},
        )
    )
    db_session.commit()

    dry_run = refresh_unknown_clue_master_statuses(
        db_session,
        now=_now(),
        batch_size=1,
        dry_run=True,
    )
    assert dry_run["scanned"] == 1
    assert dry_run["resolved"] == 1
    assert dry_run["updated"] == 1
    assert db_session.get(ClueMasterLead, lead_key).normalized_order_status == "unknown"

    applied = refresh_unknown_clue_master_statuses(
        db_session,
        now=_now(),
        batch_size=1,
    )
    assert applied["resolved"] == 1
    refreshed_lead = db_session.get(ClueMasterLead, lead_key)
    refreshed_center = db_session.get(ClueCenterOrder, order_id)
    refreshed_round = db_session.get(ClueAssignmentRound, round_id)
    assert refreshed_lead.normalized_order_status == "refunded"
    assert refreshed_lead.lifecycle_status == "closed_refunded"
    assert refreshed_center.lead_status == "refunded"
    assert refreshed_center.current_round_status == "closed_order_refunded"
    assert refreshed_round.round_status == "closed_order_refunded"

    repeat = refresh_unknown_clue_master_statuses(db_session, now=_now(), batch_size=1)
    assert repeat["scanned"] == 0


def test_terminal_state_sync_closes_all_existing_rounds_without_creating_one(
    db_session: Session,
) -> None:
    lead = ClueMasterLead(
        lead_key="lead-terminal-sync",
        source_clue_row_key="clue-row-terminal-sync",
        source_identity_key="identity-terminal-sync",
        order_id="order-terminal-sync",
        normalized_order_status="verified",
        status_source="settlement",
        lifecycle_status="closed_verified",
        pool_location="closed",
        allocation_state="closed",
        closed_at=_now(),
        closed_reason="order_verified",
    )
    first_round = ClueAssignmentRound(
        assignment_round_id="order-terminal-sync-1",
        order_id=lead.order_id,
        lead_key=lead.lead_key,
        round_no=1,
        assigned_at=_now(),
        assigned_store_id="store-1",
        round_status="active_unfollowed",
        execution_mode="legacy",
    )
    second_round = ClueAssignmentRound(
        assignment_round_id="order-terminal-sync-2",
        order_id=lead.order_id,
        lead_key=lead.lead_key,
        round_no=2,
        assigned_at=_now(),
        assigned_store_id="store-2",
        round_status="active_followed",
        execution_mode="legacy",
    )
    center = ClueCenterOrder(
        order_id=lead.order_id,
        lead_status="active",
        current_assignment_round_id=second_round.assignment_round_id,
        current_round_status="active_followed",
    )
    db_session.add_all([lead, first_round, second_round, center])
    db_session.commit()

    dry_run = synchronize_non_active_clue_states(
        db_session,
        now=_now(),
        batch_size=1,
        dry_run=True,
    )
    assert dry_run["scanned"] == 1
    assert dry_run["orders"] == 1
    assert dry_run["rounds_closed"] == 2
    assert dry_run["centers_closed"] == 1
    assert db_session.get(ClueCenterOrder, lead.order_id).lead_status == "active"

    applied = synchronize_non_active_clue_states(db_session, now=_now(), batch_size=1)
    assert applied["rounds_closed"] == 2
    assert applied["centers_closed"] == 1
    assert db_session.get(ClueAssignmentRound, first_round.assignment_round_id).round_status == "closed_order_verified"
    assert db_session.get(ClueAssignmentRound, second_round.assignment_round_id).round_status == "closed_order_verified"
    refreshed_center = db_session.get(ClueCenterOrder, lead.order_id)
    assert refreshed_center.lead_status == "converted"
    assert refreshed_center.current_round_status == "closed_order_verified"

    repeat = synchronize_non_active_clue_states(db_session, now=_now(), batch_size=1)
    assert repeat["rounds_closed"] == 0
    assert repeat["centers_closed"] == 0
