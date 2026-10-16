"""DYDATA-103: month-close planner with the real published-day marker.

Readiness = every Shanghai business day *published* (the real
``_day_state``/``_priority_rows_for_day`` condition) **and** at least one current
commission result for the month.  Fixtures are built with the real plan path:
one single-day ``plan_daily_sync`` per day, promoted via the daily-orchestrator
helper and ``enqueue_finalize_if_ready``.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.models import (
    JobRun,
    SettlementFeeResult,
    SettlementFeeResultCurrent,
    SettlementStatement,
)
from apps.worker import month_close
from apps.worker.daily_windows import enqueue_finalize_if_ready, plan_daily_sync
from apps.worker.month_close import (
    LOCKED,
    SHANGHAI,
    WATERMARK_INCOMPLETE,
    ensure_month_close_job,
    month_business_dates,
    month_close_preflight,
    month_source_watermark,
    previous_business_month,
)
from apps.worker.priority_scheduler import (
    PRIORITY_CONFIG_VERSION,
    _day_state,
    _priority_rows_for_day,
)
from apps.worker.repositories import queue_job_run
from test_worker_daily_orchestrator import _complete_finalize_prerequisites

UTC = timezone.utc
MONTH = "2026-09"
CLOSE_NOW = datetime(2026, 10, 1, 9, 0, tzinfo=SHANGHAI)


def _factory(session: Session) -> sessionmaker:
    return sessionmaker(
        bind=session.get_bind(), autoflush=False, autocommit=False, future=True
    )


def _publish_day(session: Session, day: date) -> str:
    """Publish exactly one business day through the real daily plan path."""

    plan = plan_daily_sync(
        session,
        start=day,
        end=day + timedelta(days=1),
        target="all",
        requested_by="highest-admin",
        trigger_source="manual",
        config_version=PRIORITY_CONFIG_VERSION,
    )
    _complete_finalize_prerequisites(session, plan)
    finalize = enqueue_finalize_if_ready(session, plan.parent_job_id)
    assert finalize is not None
    session.get(JobRun, plan.parent_job_id).status = "success"
    finalize.status = "success"
    # The real promotion (finalize.run_finalize_stage ->
    # promote_range_parent_if_ready) also closes the parent_sync row, which
    # _day_state requires before it reports "success".
    for row in _priority_rows_for_day(session, day):
        if row.job_kind == "parent_sync":
            row.status = "success"
    session.flush()
    return finalize.job_id


def _publish_month(session: Session) -> None:
    for day in month_business_dates(MONTH):
        _publish_day(session, day)
    session.commit()


def _add_current_result(session: Session, result_id: str, coupon_id: str) -> None:
    session.add(
        SettlementFeeResult(
            fee_result_id=result_id,
            coupon_id=coupon_id,
            order_id=f"order-{result_id}",
            fee_direction=1,
            original_business_month=MONTH,
            rule_match_date=date(2026, 9, 1),
            sku_id="sku-service",
            sale_channel_normalized="direct",
            source_amount_cent=10000,
            refunded_amount_cent=0,
            fee_base_cent=10000,
            fee_rate=Decimal("0.100000"),
            fee_amount_cent=1000,
            rule_version="rule-v1",
            scope_rule_version="scope-v1",
            result_status=1,
            calculation_run_id=f"run-{result_id}",
            calculated_at=datetime(2026, 10, 1, tzinfo=UTC),
        )
    )
    session.add(
        SettlementFeeResultCurrent(
            coupon_id=coupon_id, fee_direction=1, fee_result_id=result_id
        )
    )
    session.flush()


@pytest.mark.parametrize("moment,expected", [
    (datetime(2026, 10, 1, 0, 0, tzinfo=SHANGHAI), "2026-09"),
    (datetime(2026, 9, 30, 23, 59, tzinfo=SHANGHAI), "2026-08"),
    (datetime(2026, 9, 30, 16, 0, tzinfo=UTC), "2026-09"),
    (datetime(2026, 9, 30, 15, 59, tzinfo=UTC), "2026-08"),
    (datetime(2026, 1, 1, 0, 0, tzinfo=SHANGHAI), "2025-12"),
])
def test_previous_business_month_uses_shanghai_boundaries(moment, expected):
    assert previous_business_month(moment) == expected


def test_real_daily_plans_publish_every_day_of_the_month(db_session):
    _publish_month(db_session)

    for day in month_business_dates(MONTH):
        assert _day_state(day, _priority_rows_for_day(db_session, day)).state == "success", day
    # Days are complete but there is no billable source yet -> still not ready.
    assert month_source_watermark(db_session, MONTH) is None


def test_watermark_requires_both_complete_days_and_current_results(db_session):
    _publish_month(db_session)
    _add_current_result(db_session, "sep-result", "coupon-1")
    db_session.commit()

    assert month_source_watermark(db_session, MONTH) is not None
    state, watermark = month_close_preflight(db_session, MONTH)
    assert state != WATERMARK_INCOMPLETE and watermark is not None


def test_partial_month_is_incomplete(db_session):
    _publish_day(db_session, month_business_dates(MONTH)[0])
    _add_current_result(db_session, "sep-result", "coupon-1")
    db_session.commit()

    assert month_source_watermark(db_session, MONTH) is None
    assert month_close_preflight(db_session, MONTH) == (WATERMARK_INCOMPLETE, None)


def test_zero_current_results_fails_closed(db_session):
    _publish_month(db_session)

    assert month_source_watermark(db_session, MONTH) is None
    # Days are complete but nothing is billable: the preflight now reports this
    # distinctly so the readiness alert can name the real reason.
    from apps.worker.month_close import NO_CURRENT_RESULTS

    assert month_close_preflight(db_session, MONTH) == (NO_CURRENT_RESULTS, None)


def test_planner_enabled_but_incomplete_month_enqueues_nothing(db_session):
    """Production default is enabled; an unready month still dispatches nothing."""

    assert month_close.MONTH_CLOSE_ENABLED is True
    _publish_day(db_session, month_business_dates(MONTH)[0])  # 29 days unpublished
    _add_current_result(db_session, "sep-result", "coupon-1")
    db_session.commit()

    assert ensure_month_close_job(_factory(db_session), now=CLOSE_NOW) is None
    with _factory(db_session)() as session:
        assert list(
            session.scalars(select(JobRun).where(JobRun.job_name == "settlement_rebuild"))
        ) == []


def test_planner_enabled_dispatches_a_ready_month(db_session):
    _publish_month(db_session)
    _add_current_result(db_session, "sep-result", "coupon-1")
    db_session.commit()

    job_id = ensure_month_close_job(_factory(db_session), now=CLOSE_NOW)

    assert job_id is not None
    assert job_id.startswith("settlement-month-close-2026-09-w")


def test_late_source_after_success_dispatches_a_new_versioned_job(db_session, monkeypatch):
    monkeypatch.setattr(month_close, "MONTH_CLOSE_ENABLED", True)
    _publish_month(db_session)
    _add_current_result(db_session, "sep-result", "coupon-1")
    db_session.commit()
    factory = _factory(db_session)

    first_job = ensure_month_close_job(factory, now=CLOSE_NOW)
    assert first_job is not None
    first_watermark = month_source_watermark(db_session, MONTH)

    with factory() as session:
        session.get(JobRun, first_job).status = "success"
        session.commit()

    # Late source arrives: a new current result for the same month.
    with factory() as session:
        _add_current_result(session, "sep-result-late", "coupon-2")
        session.commit()

    second_watermark = month_source_watermark(db_session, MONTH)
    assert second_watermark is not None and second_watermark != first_watermark

    second_job = ensure_month_close_job(factory, now=CLOSE_NOW)
    assert second_job is not None and second_job != first_job


def test_same_watermark_is_idempotent(db_session, monkeypatch):
    monkeypatch.setattr(month_close, "MONTH_CLOSE_ENABLED", True)
    _publish_month(db_session)
    _add_current_result(db_session, "sep-result", "coupon-1")
    db_session.commit()
    factory = _factory(db_session)

    first = ensure_month_close_job(factory, now=CLOSE_NOW)
    second = ensure_month_close_job(factory, now=CLOSE_NOW)

    assert first == second and first is not None
    with factory() as session:
        jobs = list(
            session.scalars(select(JobRun).where(JobRun.job_name == "settlement_rebuild"))
        )
        assert len(jobs) == 1


def test_locked_month_is_refused(db_session, monkeypatch):
    monkeypatch.setattr(month_close, "MONTH_CLOSE_ENABLED", True)
    _publish_month(db_session)
    _add_current_result(db_session, "sep-result", "coupon-1")
    db_session.add(
        SettlementStatement(
            statement_id="locked-sep",
            store_id="store-1",
            statement_month=MONTH,
            version_no=1,
            is_current=True,
            statement_status=4,
        )
    )
    db_session.commit()

    assert month_close_preflight(db_session, MONTH)[0] == LOCKED
    assert ensure_month_close_job(_factory(db_session), now=CLOSE_NOW) is None


def test_active_rebuild_blocks_dispatch(db_session, monkeypatch):
    monkeypatch.setattr(month_close, "MONTH_CLOSE_ENABLED", True)
    _publish_month(db_session)
    _add_current_result(db_session, "sep-result", "coupon-1")
    factory = _factory(db_session)
    with factory() as session:
        queue_job_run(session, "other-rebuild", "settlement_rebuild")
        session.commit()

    assert ensure_month_close_job(factory, now=CLOSE_NOW) is None
