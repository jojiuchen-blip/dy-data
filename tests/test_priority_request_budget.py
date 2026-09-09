from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from apps.api.dy_api.models import DouyinApiQuotaUsage
from apps.worker.douyin_api_quota import DouyinApiQuotaLedger
from apps.worker.priority_budget import PriorityBudgetPauseError, PriorityRequestGovernor
from src.dy_data.douyin_rate_limits import EndpointLimit, RequestGovernor, SHANGHAI_TIMEZONE


def test_history_and_daily_share_atomic_counter_but_protect_daily_reserve(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'budget.db'}")
    DouyinApiQuotaUsage.__table__.create(engine)
    factory = sessionmaker(engine)
    now = datetime(2026, 9, 10, 4, tzinfo=SHANGHAI_TIMEZONE)

    def build(purpose):
        governor = RequestGovernor(
            {"refunds": EndpointLimit(5, 86400, daily_quota=5)},
            app_id="test", account_id="test", environment="test",
            quota_store=DouyinApiQuotaLedger(factory),
            default_interval_seconds=0, wall_clock=lambda: now,
        )
        return PriorityRequestGovernor(governor, purpose=purpose, reserve=2, now=lambda: now)

    daily = build("daily_required")
    daily.acquire("refunds")
    history = build("history")
    history.acquire("refunds")
    history.acquire("refunds")
    with pytest.raises(PriorityBudgetPauseError):
        history.acquire("refunds")
    # A restarted history process cannot spend the protected two requests.
    with pytest.raises(PriorityBudgetPauseError):
        build("history").acquire("refunds")
    daily.acquire("refunds")
    daily.acquire("refunds")
    with pytest.raises(PriorityBudgetPauseError):
        daily.acquire("refunds")
    with factory() as session:
        assert session.scalar(select(DouyinApiQuotaUsage.request_count)) == 5


def test_history_yields_at_midnight_without_using_new_days_quota():
    now = datetime(2026, 9, 10, 23, 59, tzinfo=SHANGHAI_TIMEZONE)
    delegate = RequestGovernor({}, default_interval_seconds=0)
    wrapper = PriorityRequestGovernor(delegate, purpose="history", reserve=10, now=lambda: now)
    wrapper.acquire("orders")
    now += timedelta(minutes=2)
    with pytest.raises(PriorityBudgetPauseError) as error:
        wrapper.acquire("orders")
    assert error.value.retry_after_seconds == 7140


def test_qps_only_endpoint_has_no_invented_daily_budget():
    now = datetime(2026, 9, 10, 3, tzinfo=SHANGHAI_TIMEZONE)
    delegate = RequestGovernor(
        {"orders": EndpointLimit(20, 1)}, default_interval_seconds=0,
        clock=lambda: 0, sleep=lambda _: None,
    )
    wrapper = PriorityRequestGovernor(delegate, purpose="history", reserve=10, now=lambda: now)
    for _ in range(100):
        wrapper.acquire("orders")
    assert wrapper.profile.limit_for("orders").daily_quota is None


def test_history_is_blocked_before_two_even_after_restart():
    now = datetime(2026, 9, 11, 1, tzinfo=SHANGHAI_TIMEZONE)
    wrapper = PriorityRequestGovernor(
        RequestGovernor({}, default_interval_seconds=0),
        purpose="history", reserve=10, now=lambda: now,
    )
    with pytest.raises(PriorityBudgetPauseError):
        wrapper.acquire("orders")
