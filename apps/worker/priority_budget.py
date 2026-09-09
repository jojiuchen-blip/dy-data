"""Per-request protection for the priority scheduler's shared endpoint budgets."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, time, timedelta
import math
import os
from typing import Any, Callable

from src.dy_data.douyin_rate_limits import (
    DouyinEndpointProfile,
    DouyinQuotaExceeded,
    RequestGovernor,
    SHANGHAI_TIMEZONE,
)


class PriorityBudgetPauseError(RuntimeError):
    """Yield a resumable job without consuming its real-failure retry budget."""

    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = max(60, int(retry_after_seconds))
        super().__init__(
            "priority_budget_pause "
            f"retry_after_seconds={self.retry_after_seconds}"
        )


def next_daily_delay(now: datetime) -> int:
    local = now.astimezone(SHANGHAI_TIMEZONE)
    due = datetime.combine(local.date(), time(2), tzinfo=SHANGHAI_TIMEZONE)
    if due <= local:
        due += timedelta(days=1)
    return max(60, math.ceil((due - local).total_seconds()))


def history_reserve() -> int:
    """Local retry allowance; this is not an extra platform daily quota."""
    try:
        value = int(os.getenv("WORKER_HISTORY_DAILY_RESERVE", "10"))
    except ValueError as exc:
        raise ValueError("WORKER_HISTORY_DAILY_RESERVE must be an integer") from exc
    if value < 1 or value > 90:
        raise ValueError("WORKER_HISTORY_DAILY_RESERVE must be between 1 and 90")
    return value


class PriorityRequestGovernor:
    """Keep QPS pacing, atomically protect daily quota, and yield at rollover."""

    def __init__(
        self,
        governor: RequestGovernor,
        *,
        purpose: str,
        reserve: int,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._now = now or (lambda: datetime.now(SHANGHAI_TIMEZONE))
        self._started_day = self._now().astimezone(SHANGHAI_TIMEZONE).date()
        self.purpose = purpose
        self._blocked_endpoints: set[str] = set()
        if purpose == "history":
            limits = {}
            for key, limit in governor.profile.endpoints.items():
                if limit.daily_quota is not None:
                    remaining_ceiling = limit.daily_quota - reserve
                    if remaining_ceiling <= 0:
                        self._blocked_endpoints.add(key)
                    else:
                        limit = replace(limit, daily_quota=remaining_ceiling)
                limits[key] = limit
            # The same durable ledger counts all purposes. Only the admission
            # ceiling differs; this is not a second independent quota bucket.
            governor.profile = DouyinEndpointProfile(
                app_id=governor.profile.app_id,
                endpoints=limits,
                default_interval_seconds=governor.profile.default_interval_seconds,
            )
        self._governor = governor

    def __getattr__(self, name: str) -> Any:
        return getattr(self._governor, name)

    def acquire(self, endpoint_key: str) -> None:
        now = self._now().astimezone(SHANGHAI_TIMEZONE)
        if (
            now.date() != self._started_day
            or (self.purpose == "history" and now.hour < 2)
            or endpoint_key in self._blocked_endpoints
        ):
            raise PriorityBudgetPauseError(next_daily_delay(now))
        try:
            self._governor.acquire(endpoint_key)
        except DouyinQuotaExceeded as exc:
            # Keep the control-plane marker free of the legacy global cooldown
            # code: a refund budget pause must not block unrelated endpoints.
            raise PriorityBudgetPauseError(next_daily_delay(now)) from exc


def protect_priority_requests(client: Any, job: Any) -> None:
    """Install once on a task-local client; leave legacy and test clients intact."""
    if job.config_version != "priority-daily-v1":
        return
    governor = getattr(client, "request_governor", None)
    if governor is None or isinstance(governor, PriorityRequestGovernor):
        return
    purpose = (job.metadata_json or {}).get("priority_purpose", "daily_required")
    if purpose not in {"daily_required", "history", "reconcile"}:
        raise ValueError("unknown priority budget purpose")
    client.request_governor = PriorityRequestGovernor(
        governor, purpose=purpose, reserve=history_reserve()
    )
