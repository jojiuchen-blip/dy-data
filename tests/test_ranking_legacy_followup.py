from datetime import datetime, timedelta, timezone
from dataclasses import replace
import pytest
from apps.api.dy_api.clue_followup_metrics import AssignmentRoundEvidence, FollowUpEvidence
from apps.api.dy_api.ranking_legacy_followup import evaluate_legacy_ranking_round
AT = datetime(2026, 9, 7, tzinfo=timezone.utc)
ROUND = AssignmentRoundEvidence('R', 'O', 1, 'S', AT)

def record(hours, **changes):
    return replace(FollowUpEvidence('F', 'O', 'R', 'S', AT + timedelta(hours=hours)), **changes)

@pytest.mark.parametrize('hours, expected', [(0,1),(24,1),(24.0001,0),(25,0)])
def test_manual_window_is_inclusive_and_any_follow_has_no_limit(hours, expected):
    metric = evaluate_legacy_ranking_round(ROUND, follow_ups=[record(hours)], observed_through=AT+timedelta(days=3))
    assert (metric.numerator, metric.denominator) == (expected, 1)
    assert (metric.follow_any_numerator, metric.follow_any_denominator) == (1, 1)

@pytest.mark.parametrize('changes', [dict(deleted_at=AT),dict(assigned_store_id='OTHER'),dict(assignment_round_id='OTHER'),dict(created_at=AT-timedelta(seconds=1)),dict(created_at=AT+timedelta(days=4))])
def test_invalid_manual_records_do_not_credit_the_round(changes):
    metric = evaluate_legacy_ranking_round(ROUND, follow_ups=[record(2, **changes)], observed_through=AT+timedelta(days=3))
    assert (metric.numerator,metric.follow_any_numerator,metric.denominator) == (0,0,1)

def test_verified_round_without_manual_follow_is_zero_of_one():
    metric = evaluate_legacy_ranking_round(replace(ROUND,verified_store_id='S',verified_at=AT+timedelta(hours=2)),observed_through=AT+timedelta(days=3))
    assert (metric.numerator,metric.follow_any_numerator,metric.denominator) == (0,0,1)

@pytest.mark.parametrize('changes', [dict(execution_mode='shadow'),dict(assigned_at=None),dict(assigned_at=AT+timedelta(days=4))])
def test_unobserved_or_nonformal_round_is_excluded(changes):
    metric = evaluate_legacy_ranking_round(replace(ROUND,**changes),observed_through=AT+timedelta(days=3))
    assert (metric.denominator,metric.follow_any_denominator) == (0,0)

def test_multiple_records_count_one_round():
    metric = evaluate_legacy_ranking_round(ROUND,follow_ups=[record(2),record(2),record(3,follow_up_record_id='F2')],observed_through=AT+timedelta(days=3))
    assert (metric.numerator,metric.follow_any_numerator) == (1,1)
    assert metric.follow_record_ids == ('F','F2')

