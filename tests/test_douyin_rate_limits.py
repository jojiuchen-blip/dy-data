from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from src.dy_data.douyin_rate_limits import (
    DEFAULT_REQUEST_SLEEP_SECONDS,
    ENDPOINT_CLUES,
    ENDPOINT_ORDERS,
    ENDPOINT_REFUNDS,
    DouyinQuotaExceeded,
    InMemoryDailyQuotaStore,
    MonotonicRequestGovernor,
    PRODUCTION_APP_ID,
    RequestGovernor,
    endpoint_profile_for_app,
    seconds_until_next_shanghai_day,
    stable_endpoint_key,
)


def test_production_profile_uses_confirmed_limits_and_operational_soft_caps() -> None:
    profile = endpoint_profile_for_app(PRODUCTION_APP_ID)

    assert profile.default_interval_seconds == DEFAULT_REQUEST_SLEEP_SECONDS
    assert profile.limit_for(ENDPOINT_ORDERS).requests_per_window == 20
    assert profile.limit_for("verify_records").requests_per_window == 100
    assert profile.limit_for("certificates").requests_per_window == 35
    assert profile.limit_for(ENDPOINT_REFUNDS).requests_per_window == 100
    assert profile.limit_for(ENDPOINT_REFUNDS).soft_quota == 90
    assert profile.limit_for(ENDPOINT_REFUNDS).daily_quota == 90
    assert profile.limit_for(ENDPOINT_REFUNDS).interval_seconds == 0
    assert profile.limit_for("shop_pois").requests_per_window == 400
    assert profile.limit_for(ENDPOINT_CLUES).requests_per_window == 100
    assert profile.limit_for(ENDPOINT_CLUES).soft_quota == 90
    assert profile.limit_for("product_list").requests_per_window == 20
    assert profile.limit_for("product_detail").requests_per_window == 20

    governor = RequestGovernor(
        app_id=PRODUCTION_APP_ID,
        clock=lambda: 0.0,
        sleep=lambda _seconds: None,
    )
    assert governor.profile.limit_for(ENDPOINT_REFUNDS).daily_quota == 90


def test_unknown_app_and_unknown_endpoint_only_use_default_interval() -> None:
    profile = endpoint_profile_for_app("unregistered-app")
    assert profile.limit_for(ENDPOINT_ORDERS) is None
    assert profile.limit_for("unknown:open.douyin.com/private") is None

    assert stable_endpoint_key(
        "https://open.douyin.com/goodlife/v1/open_api/crm/clue/query/?token=secret"
    ) == ENDPOINT_CLUES
    unknown = stable_endpoint_key("https://example.invalid/custom?token=secret")
    assert unknown == stable_endpoint_key("https://example.invalid/custom?token=other")
    assert "secret" not in unknown
    assert "secret" not in str(DouyinQuotaExceeded("https://example.invalid/custom?token=secret", 1))

    with pytest.raises(ValueError, match="unverified endpoint"):
        endpoint_profile_for_app(
            PRODUCTION_APP_ID,
            limits_json={
                "unknown_endpoint": {
                    "requests_per_window": 10,
                    "window_seconds": 1,
                }
            },
        )

    with pytest.raises(ValueError, match="cannot raise requests_per_window"):
        endpoint_profile_for_app(
            PRODUCTION_APP_ID,
            limits_json={"orders": {"requests_per_window": 21}},
        )


def test_process_local_governor_spaces_clues_with_injected_clock_and_sleep() -> None:
    profile = endpoint_profile_for_app(PRODUCTION_APP_ID)
    now = [0.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    governor = MonotonicRequestGovernor(
        profile,
        clock=lambda: now[0],
        sleep=sleep,
    )
    governor.acquire(ENDPOINT_CLUES)
    governor.acquire(ENDPOINT_CLUES)

    assert sleeps == [pytest.approx(60 / 90)]


def test_in_memory_daily_quota_rejects_the_91st_refund_before_transport() -> None:
    profile = endpoint_profile_for_app(PRODUCTION_APP_ID)
    store = InMemoryDailyQuotaStore()
    now = datetime(2026, 9, 3, 15, 0, tzinfo=UTC)
    governor = RequestGovernor(
        profile,
        app_id=PRODUCTION_APP_ID,
        account_id="account-1",
        environment="production",
        quota_store=store,
        clock=lambda: 0.0,
        sleep=lambda _seconds: None,
        wall_clock=lambda: now,
    )

    for _ in range(90):
        governor.acquire(ENDPOINT_REFUNDS)

    with pytest.raises(DouyinQuotaExceeded) as raised:
        governor.acquire(ENDPOINT_REFUNDS)

    assert raised.value.endpoint == ENDPOINT_REFUNDS
    assert raised.value.retry_after_seconds == 60 * 60
    assert "endpoint=refunds" in str(raised.value)
    assert "retry_after_seconds=3600" in str(raised.value)
    assert store.count(
        environment="production",
        app_id=PRODUCTION_APP_ID,
        account_id="account-1",
        endpoint_key=ENDPOINT_REFUNDS,
        business_date=date(2026, 9, 3),
    ) == 90


def test_daily_ledger_uses_the_governor_wall_clock() -> None:
    observed_at = datetime(2026, 9, 3, 15, 59, 59, tzinfo=UTC)
    captured: list[datetime] = []

    class RecordingStore:
        def try_reserve(self, **kwargs):
            captured.append(kwargs["now"])
            return True

    governor = RequestGovernor(
        endpoint_profile_for_app(PRODUCTION_APP_ID),
        app_id=PRODUCTION_APP_ID,
        account_id="account-1",
        environment="production",
        quota_store=RecordingStore(),
        clock=lambda: 0.0,
        sleep=lambda _seconds: None,
        wall_clock=lambda: observed_at,
    )

    governor.acquire(ENDPOINT_REFUNDS)

    assert captured == [observed_at]


def test_next_shanghai_day_delay_is_injected_clock_independent() -> None:
    assert seconds_until_next_shanghai_day(datetime(2026, 9, 3, 15, 0, tzinfo=UTC)) == 3600
