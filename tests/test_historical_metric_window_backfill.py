from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from apps.api.dy_api.models import ClueAllocationDecision, ClueAssignmentRound, ClueFollowUpRecord
from scripts.backfill_historical_metric_window import HistoricalMetricWindowError, apply_updates, plan_updates


def _correction(session, *, before_store="old-store", after_store="new-store"):
    executed_at = datetime(2026, 9, 16, 6, tzinfo=timezone.utc)
    round_row = ClueAssignmentRound(
        assignment_round_id="metric-round",
        order_id="metric-order",
        round_no=1,
        round_status="active_unfollowed",
        execution_mode="formal",
        assigned_store_id=after_store,
        assigned_at=executed_at - timedelta(days=3),
    )
    decision = ClueAllocationDecision(
        decision_id="metric-decision",
        attempt_key="metric-attempt",
        lead_key="metric-lead",
        order_id="metric-order",
        assignment_round_id="metric-round",
        selected_store_id=after_store,
        selected_store_name=after_store,
        strategy_type="nearby_city_optimization",
        execution_mode="formal",
        decision_status="selected",
        reason="historical correction",
        actor="source-store-historical-correction-20260916",
        executed_at=executed_at,
        decision_snapshot={"correction": {"before_round": {"assigned_store_id": before_store}}},
    )
    session.add_all([round_row, decision])
    session.flush()
    return round_row, decision


def test_backfill_plans_only_store_changed_corrections(db_session):
    _correction(db_session)
    updates = plan_updates(db_session)
    assert len(updates) == 1
    assert updates[0]["metric_follow_24h_start_at"].startswith("2026-09-16T06:00:00")


def test_backfill_is_idempotent_after_apply(db_session):
    round_row, _ = _correction(db_session)
    updates = plan_updates(db_session)
    assert apply_updates(db_session, updates) == 1
    assert round_row.metric_follow_24h_start_at is not None
    assert plan_updates(db_session) == []


def test_backfill_rejects_preexisting_follow_up(db_session):
    _correction(db_session)
    db_session.add(
        ClueFollowUpRecord(
            follow_up_record_id="before-correction-follow",
            order_id="metric-order",
            assignment_round_id="metric-round",
            round_no=1,
            assigned_store_id="old-store",
            follow_result="connected",
            created_at=datetime(2026, 9, 16, 5, 59, tzinfo=timezone.utc),
        )
    )
    db_session.flush()
    with pytest.raises(HistoricalMetricWindowError, match="follow-up existed before correction"):
        plan_updates(db_session)


def test_backfill_skips_corrections_that_kept_same_store(db_session):
    _correction(db_session, before_store="new-store", after_store="new-store")
    assert plan_updates(db_session) == []
