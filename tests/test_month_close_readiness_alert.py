"""DYDATA-103: readiness alerts when a month cannot be closed yet.

The planner is fail-closed, but before this change an unready month was
*silent*: no job, no log, no quality issue.  These tests pin the required
behaviour: one idempotent, operator-visible readiness issue per
(business_month, state), cleared once the month becomes ready, and never any
commission or statement write.
"""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import select

from apps.api.dy_api.models import (
    DataQualityIssue,
    SettlementFeeResult,
    SettlementFeeResultCurrent,
    SettlementStatement,
)
from apps.worker import month_close
from apps.worker.month_close import (
    LOCKED,
    NO_CURRENT_RESULTS,
    READINESS_ISSUE_TYPE,
    WATERMARK_INCOMPLETE,
    ensure_month_close_job,
    month_close_preflight,
    readiness_issue_id,
)
from test_month_close import (  # noqa: E402 - shared real-fixture helpers
    CLOSE_NOW,
    MONTH,
    _add_current_result,
    _factory,
    _publish_day,
    _publish_month,
)


def _readiness_issues(db_session):
    return list(
        db_session.scalars(
            select(DataQualityIssue).where(
                DataQualityIssue.issue_type == READINESS_ISSUE_TYPE
            )
        )
    )


@pytest.mark.parametrize(
    "prepare,expected_state",
    [
        (lambda s: None, WATERMARK_INCOMPLETE),                      # no published days
        (lambda s: _publish_month(s), NO_CURRENT_RESULTS),           # days only
    ],
)
def test_unready_month_creates_one_visible_readiness_issue(
    db_session, prepare, expected_state
):
    prepare(db_session)

    assert ensure_month_close_job(_factory(db_session), now=CLOSE_NOW) is None

    state, _ = month_close_preflight(db_session, MONTH)
    assert state == expected_state
    issues = _readiness_issues(db_session)
    assert len(issues) == 1
    issue = issues[0]
    assert issue.issue_id == readiness_issue_id(MONTH, expected_state)
    assert issue.severity in {"warning", "error"}
    assert issue.raw_context_json["business_month"] == MONTH
    assert issue.raw_context_json["state"] == expected_state
    # Operator-visible message must name the month and the reason.
    assert MONTH in issue.message


def test_locked_month_creates_a_readiness_issue(db_session):
    from apps.api.dy_api.models import SettlementStatement as Statement

    _publish_month(db_session)
    _add_current_result(db_session, "sep-result", "coupon-1")
    db_session.add(
        Statement(
            statement_id="locked-sep",
            store_id="store-1",
            statement_month=MONTH,
            version_no=1,
            is_current=True,
            statement_status=4,
        )
    )
    db_session.commit()

    assert ensure_month_close_job(_factory(db_session), now=CLOSE_NOW) is None

    assert month_close_preflight(db_session, MONTH)[0] == LOCKED
    issues = _readiness_issues(db_session)
    assert [i.issue_id for i in issues] == [readiness_issue_id(MONTH, LOCKED)]


def test_repeated_ticks_do_not_duplicate_the_alert(db_session):
    _publish_month(db_session)
    factory = _factory(db_session)

    for _ in range(5):
        ensure_month_close_job(factory, now=CLOSE_NOW)

    assert len(_readiness_issues(db_session)) == 1


def test_ready_month_clears_the_previous_alert(db_session):
    _publish_month(db_session)
    factory = _factory(db_session)
    assert ensure_month_close_job(factory, now=CLOSE_NOW) is None
    assert len(_readiness_issues(db_session)) == 1

    # Source becomes ready (late current result arrives).
    _add_current_result(db_session, "sep-late", "coupon-2")
    db_session.commit()

    job_id = ensure_month_close_job(factory, now=CLOSE_NOW)

    assert job_id is not None
    assert _readiness_issues(db_session) == []


def test_readiness_alert_never_writes_commission_or_statement(db_session):
    _publish_month(db_session)
    before_results = len(list(db_session.scalars(select(SettlementFeeResult))))
    before_current = len(list(db_session.scalars(select(SettlementFeeResultCurrent))))
    before_statements = len(list(db_session.scalars(select(SettlementStatement))))

    ensure_month_close_job(_factory(db_session), now=CLOSE_NOW)

    assert len(list(db_session.scalars(select(SettlementFeeResult)))) == before_results
    assert len(list(db_session.scalars(select(SettlementFeeResultCurrent)))) == before_current
    assert len(list(db_session.scalars(select(SettlementStatement)))) == before_statements
