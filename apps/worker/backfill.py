from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.models import JobRun
from apps.api.dy_api.db import get_session_factory, session_scope
from apps.worker.daily_windows import (
    DEFAULT_CONFIG_VERSION,
    DEFAULT_DATA_SOURCE,
    SHANGHAI_TIMEZONE,
    SHANGHAI_TIMEZONE_NAME,
    DailySyncPlan,
    plan_daily_sync,
)
from apps.worker.collectors.types import CollectionStats, CollectionWindow
from apps.worker.collectors.windows import resolve_collection_window


Runner = Callable[..., CollectionStats]
DEFAULT_CHUNK_DAYS = 1


@dataclass
class BackfillResult:
    chunks: list[CollectionStats] = field(default_factory=list)
    skipped_windows: list[CollectionWindow] = field(default_factory=list)

    @property
    def success_count(self) -> int:
        return sum(chunk.success_count for chunk in self.chunks)

    @property
    def failed_count(self) -> int:
        return sum(chunk.failed_count for chunk in self.chunks)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped_windows)


def iter_backfill_windows(window: CollectionWindow, *, chunk_days: int) -> Iterable[CollectionWindow]:
    if chunk_days <= 0:
        yield window
        return

    chunk_start = window.start
    while chunk_start < window.end:
        chunk_end = min(chunk_start + timedelta(days=chunk_days), window.end)
        yield CollectionWindow(start=chunk_start, end=chunk_end, timezone_name=window.timezone_name)
        chunk_start = chunk_end


def run_backfill(
    *,
    factory: sessionmaker | None = None,
    start: str | datetime | None = None,
    end: str | datetime | None = None,
    chunk_days: int | None = None,
    timezone_name: str | None = None,
    include_browser_export: bool | None = None,
    skip_completed: bool | None = None,
    runner: Runner | None = None,
    queued_job_runner: Callable[[], object] | None = None,
    now: datetime | None = None,
    target: str = "all",
    data_source: str = DEFAULT_DATA_SOURCE,
    config_version: str = DEFAULT_CONFIG_VERSION,
) -> DailySyncPlan:
    session_factory = factory or get_session_factory()
    if session_factory is None:
        raise RuntimeError("Set DY_DATABASE_URL or DATABASE_URL before running worker backfill.")

    reference_now = now or datetime.now(SHANGHAI_TIMEZONE)
    source_window = resolve_collection_window(
        now=reference_now,
        start=start,
        end=end,
        timezone_name=timezone_name,
    )
    if source_window.timezone_name != SHANGHAI_TIMEZONE_NAME:
        raise ValueError(
            "DOUYIN_COLLECT_TIMEZONE must be Asia/Shanghai for daily planning."
        )
    # Keep legacy arguments source-compatible, but never use them to re-enter
    # the old in-process historical pipeline.
    _ = (
        chunk_days,
        include_browser_export,
        skip_completed,
        runner,
        queued_job_runner,
    )
    plan_start, plan_end = _covering_business_dates(source_window)
    local_reference_now = (
        reference_now.astimezone(SHANGHAI_TIMEZONE)
        if reference_now.tzinfo is not None
        else reference_now.replace(tzinfo=SHANGHAI_TIMEZONE)
    )
    plan_end = min(plan_end, local_reference_now.date())
    if plan_end <= plan_start:
        raise ValueError("Backfill range contains no closed Shanghai business day.")
    with session_scope(session_factory) as session:
        plan = plan_daily_sync(
            session,
            start=plan_start,
            end=plan_end,
            target=target,
            requested_by="worker-backfill",
            trigger_source="backfill",
            data_source=data_source,
            config_version=config_version,
        )
    _log(
        "backfill_planned "
        f"parent_job_id={plan.parent_job_id} dates={len(plan.daily_jobs)} "
        f"start={plan.window_start.isoformat()} end={plan.window_end.isoformat()}"
    )
    return plan


def successful_window_keys(session: Session, *, job_name: str = "collect_and_settle") -> set[tuple[str, str, str]]:
    rows = session.scalars(
        select(JobRun).where(
            JobRun.job_name == job_name,
            JobRun.status == "success",
        )
    ).all()
    keys: set[tuple[str, str, str]] = set()
    for row in rows:
        key = _metadata_window_key(row.metadata_json)
        if key is not None:
            keys.add(key)
    return keys


def _metadata_window_key(metadata: dict[str, Any] | None) -> tuple[str, str, str] | None:
    source_window = (metadata or {}).get("source_window")
    if not isinstance(source_window, dict):
        return None
    start = source_window.get("start")
    end = source_window.get("end")
    timezone_name = source_window.get("timezone")
    if not isinstance(start, str) or not isinstance(end, str) or not isinstance(timezone_name, str):
        return None
    return (start, end, timezone_name)


def _window_key(window: CollectionWindow) -> tuple[str, str, str]:
    return (window.start.isoformat(), window.end.isoformat(), window.timezone_name)


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _covering_business_dates(window: CollectionWindow) -> tuple[date, date]:
    return window.start.date(), window.end.date()


def _chunk_job_id(index: int, window: CollectionWindow) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"backfill_{index:04d}_{window.start:%Y%m%d}_{stamp}"


def _log(message: str) -> None:
    print(f"[worker-backfill] {message}", flush=True)
