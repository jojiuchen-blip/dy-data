from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import sessionmaker

from apps.api.dy_api.db import get_session_factory, session_scope
from apps.worker.collectors.types import CollectionStats, CollectionWindow
from apps.worker.collectors.windows import resolve_collection_window
from apps.worker.pipeline import run_collect_and_settle


Runner = Callable[..., CollectionStats]
DEFAULT_CHUNK_DAYS = 1


@dataclass
class BackfillResult:
    chunks: list[CollectionStats] = field(default_factory=list)

    @property
    def success_count(self) -> int:
        return sum(chunk.success_count for chunk in self.chunks)

    @property
    def failed_count(self) -> int:
        return sum(chunk.failed_count for chunk in self.chunks)


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
    runner: Runner = run_collect_and_settle,
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
    result = BackfillResult()

    for index, chunk in enumerate(iter_backfill_windows(source_window, chunk_days=days), start=1):
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

    _log(f"backfill_done chunks={len(result.chunks)} success={result.success_count} failed={result.failed_count}")
    return result


def _chunk_job_id(index: int, window: CollectionWindow) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"backfill_{index:04d}_{window.start:%Y%m%d}_{stamp}"


def _log(message: str) -> None:
    print(f"[worker-backfill] {message}", flush=True)
