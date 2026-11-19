"""Real PostgreSQL evidence for historical manual records and terminal ties."""

from datetime import timedelta

from apps.api.dy_api.clue_task_metrics import load_clue_task_facts, load_self_store_verifications
from apps.api.dy_api.models import ClueFollowUpRecord
from test_clue_task_metrics import AT, CUTOFF, _follow, _order, _task, _verify
from test_dashboard_publication_sales_postgres import publication_postgres_session


def test_historical_manual_records_and_independent_terminal_ties_on_postgresql(publication_postgres_session):
    session = publication_postgres_session
    orders = ("continued", "manual-success", "manual-failed", "actual-verify", "projection-only")
    for order_id in orders:
        _order(session, order_id)
        row = _task(session, order_id + "-task", order_id=order_id)
        if order_id == "continued":
            _follow(session, order_id + "-record", order_id=order_id, task=row.assignment_round_id,
                    result="continue_following")
        elif order_id in {"manual-success", "manual-failed", "actual-verify"}:
            row.closed_at = AT + timedelta(hours=2)
            row.round_status = "closed_lost" if order_id == "manual-failed" else "closed_order_verified"
            result = "failed" if order_id == "manual-failed" else "success"
            _follow(session, order_id + "-record", order_id=order_id, task=row.assignment_round_id,
                    result=result, hour=2)
            if result == "success":
                row.verified_at, row.verified_store_id = row.closed_at, "A"
            if order_id == "actual-verify":
                # Force the round-only projection to sort before the raw
                # verification identity. Independent evidence still wins.
                _verify(session, "zz-actual-verify", order_id=order_id, hour=2)
        else:
            row.followed_at, row.follow_result = AT + timedelta(hours=1), "continue_following"
            row.is_followed = row.is_follow_success = True
    session.commit()

    facts = load_clue_task_facts(session, orders, observed_through=CUTOFF)
    for order_id in ("continued", "manual-success", "manual-failed"):
        fact = facts[order_id + "-task"]
        assert (fact.follow_24h_numerator, fact.follow_any_numerator, fact.follow_denominator) == (1, 1, 1)
        assert fact.verification_numerator == 0
    for order_id in ("actual-verify", "projection-only"):
        fact = facts[order_id + "-task"]
        assert (fact.follow_24h_numerator, fact.follow_any_numerator, fact.follow_denominator) == (0, 0, 1)
    assert facts["actual-verify-task"].verification_numerator == 1
    assert facts["actual-verify-task"].verification_facts[0].had_valid_follow_before_verify is False
    assert session.get(ClueFollowUpRecord, "manual-success-record").follow_result == "success"
    volumes = load_self_store_verifications(session, orders, observed_through=CUTOFF)
    assert [(fact.order_id, fact.verify_id) for fact in volumes] == [("actual-verify", "zz-actual-verify")]
