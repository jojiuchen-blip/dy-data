from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.models import JobRun
from apps.api.dy_api.db import get_session_factory, session_scope
from apps.worker.collectors.types import CollectionStats, CollectionWindow
from apps.worker.collectors.windows import resolve_collection_window
from apps.worker.pipeline import run_collect_and_settle


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
    runner: Runner = run_collect_and_settle,
    queued_job_runner: Callable[[], object] | None = None,
    now: datetime | None = None,
) -> BackfillResult:
    session_factory = factory or get_session_factory()
    if session_factory is None:
        raise RuntimeError("Set DY_DATABASE_URL or DATABASE_URL before running worker backfill.")

    source_window = resolve_collection_window(
        now=now,
        start=start,
        end=end,
        timezone_name=timezone_name,
    )
    days = chunk_days if chunk_days is not None else int(os.getenv("WORKER_BACKFILL_CHUNK_DAYS", str(DEFAULT_CHUNK_DAYS)))
    should_skip_completed = (
        _truthy(os.getenv("WORKER_BACKFILL_SKIP_COMPLETED", "true"))
        if skip_completed is None
        else skip_completed
    )
    result = BackfillResult()
    completed_windows: set[tuple[str, str, str]] = set()
    if should_skip_completed:
        with session_scope(session_factory) as session:
            completed_windows = successful_window_keys(session)

    for index, chunk in enumerate(iter_backfill_windows(source_window, chunk_days=days), start=1):
        if should_skip_completed and _window_key(chunk) in completed_windows:
            result.skipped_windows.append(chunk)
            _log(f"chunk_skip index={index} start={chunk.start.isoformat()} end={chunk.end.isoformat()}")
            continue

        if queued_job_runner is not None:
            queued_job_runner()

        job_id = _chunk_job_id(index, chunk)
        _log(f"chunk_start index={index} job_id={job_id} start={chunk.start.isoformat()} end={chunk.end.isoformat()}")
        with session_scope(session_factory) as session:
            stats = runner(
                session,
                window=chunk,
                job_id=job_id,
                include_browser_export=include_browser_export,
            )
        result.chunks.append(stats)
        _log(
            "chunk_done "
            f"index={index} job_id={job_id} "
            f"success={stats.success_count} failed={stats.failed_count}"
        )

    _log(
        "backfill_done "
        f"chunks={len(result.chunks)} skipped={result.skipped_count} "
        f"success={result.success_count} failed={result.failed_count}"
    )
    return result


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


def _chunk_job_id(index: int, window: CollectionWindow) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"backfill_{index:04d}_{window.start:%Y%m%d}_{stamp}"


def _log(message: str) -> None:
    print(f"[worker-backfill] {message}", flush=True)
