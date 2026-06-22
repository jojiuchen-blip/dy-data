from __future__ import annotations

import os
import signal
import time
from datetime import datetime, timezone
from collections.abc import Mapping
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import JobRun
from apps.api.dy_api.db import get_session_factory, session_scope
from apps.worker.backfill import iter_backfill_windows, run_backfill
from apps.worker.collectors.types import CollectionWindow, PhaseStats
from apps.worker.collectors.windows import resolve_collection_window
from apps.worker.pipeline import run_collect_and_settle, sanitize_error_message
from apps.worker.queued_jobs import process_queued_settlement_rebuilds
from apps.worker.repositories import finish_job_run, start_job_run
from apps.worker.settlement import run_settlement_job
from apps.worker.sync_config import DEFAULT_INTERVAL_SECONDS, DEFAULT_ROLLING_DAYS, load_sync_config


_STOP = False
DISABLED_POLL_SECONDS = 60
DEFAULT_INCREMENTAL_CHUNK_MAX_ATTEMPTS = 2
BrowserExportRunner = Callable[[Session, str], PhaseStats]


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _handle_stop(signum: int, frame: object) -> None:
    global _STOP
    _STOP = True


def _job_id(prefix: str = "settlement") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"{prefix}_{stamp}"


def _chunk_job_id(prefix: str, index: int, window: CollectionWindow) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"{prefix}_{index:04d}_{window.start:%Y%m%d}_{stamp}"


def resolve_worker_mode(env: Mapping[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    value = source.get("WORKER_MODE", "collect_and_settle").strip().lower()
    if value not in {"collect_and_settle", "settlement_only", "backfill", "browser_export_only"}:
        raise ValueError("WORKER_MODE must be collect_and_settle, settlement_only, backfill, or browser_export_only.")
    return value


def resolve_incremental_collection_window(
    *,
    now: datetime | None = None,
    env: Mapping[str, str] | None = None,
) -> CollectionWindow:
    source = os.environ if env is None else env
    days = int(source.get("WORKER_ROLLING_DAYS", str(DEFAULT_ROLLING_DAYS)))
    if days <= 0:
        raise ValueError("WORKER_ROLLING_DAYS must be greater than 0.")
    return resolve_collection_window(
        now=now,
        overlap_days=days,
        timezone_name=source.get("DOUYIN_COLLECT_TIMEZONE"),
        env={},
    )


def run_once() -> None:
    source_run_id = os.getenv("WORKER_SOURCE_RUN_ID", "scheduled")
    mode = resolve_worker_mode()
    _log(f"run_once_start mode={mode} source_run_id={source_run_id}")
    factory = get_session_factory()
    if factory is None:
        raise RuntimeError("Set DY_DATABASE_URL or DATABASE_URL before running worker scheduler.")
    process_queued_settlement_rebuilds(factory)
    if mode == "backfill":
        with session_scope(factory) as session:
            config = load_sync_config(session)
        run_backfill(
            factory=factory,
            start=config.history_start,
            end=config.history_end or None,
            chunk_days=config.history_chunk_days,
            skip_completed=config.backfill_skip_completed,
            queued_job_runner=lambda: process_queued_settlement_rebuilds(factory),
        )
        return
    if mode == "browser_export_only":
        run_browser_export_once(factory)
        return
    with session_scope(factory) as session:
        if mode == "settlement_only":
            run_settlement_job(session, job_id=_job_id("settlement"), source_run_id=source_run_id)
            return
        config = load_sync_config(session)
    run_incremental_collection_chunks(factory, config)


def run_incremental_collection_chunks(factory, config) -> None:
    source_window = resolve_incremental_collection_window(
        env={"WORKER_ROLLING_DAYS": str(config.rolling_days)}
    )
    chunks = list(iter_backfill_windows(source_window, chunk_days=config.history_chunk_days))
    day_start = _window_day_start(source_window)
    with session_scope(factory) as session:
        completed_windows = _successful_collect_window_keys(session, since=day_start)
    _log(
        "incremental_start "
        f"chunks={len(chunks)} chunk_days={config.history_chunk_days} "
        f"start={source_window.start.isoformat()} end={source_window.end.isoformat()}"
    )
    failed_chunks = 0
    max_attempts = _configured_chunk_max_attempts()
    for index, chunk in enumerate(chunks, start=1):
        if _window_key(chunk) in completed_windows:
            _log(f"incremental_chunk_skip index={index} start={chunk.start.isoformat()} end={chunk.end.isoformat()}")
            continue

        process_queued_settlement_rebuilds(factory)
        job_id = _chunk_job_id("collect", index, chunk)
        _log(f"incremental_chunk_start index={index} job_id={job_id} start={chunk.start.isoformat()} end={chunk.end.isoformat()}")
        stats = None
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                with session_scope(factory) as session:
                    stats = run_collect_and_settle(
                        session,
                        job_id=job_id,
                        window=chunk,
                        include_browser_export=False,
                        include_materialization=False,
                    )
                break
            except Exception as exc:
                last_error = exc
                if attempt < max_attempts:
                    _log(
                        f"incremental_chunk_retry index={index} job_id={job_id} "
                        f"attempt={attempt + 1}/{max_attempts}"
                    )
                    continue
        if stats is None:
            assert last_error is not None
            _record_failed_collect_chunk(factory, job_id=job_id, window=chunk, error=last_error)
            _log(f"incremental_chunk_failed index={index} job_id={job_id} attempts={max_attempts}")
            failed_chunks += 1
            continue
        completed_windows.add(_window_key(chunk))
        _log(
            f"incremental_chunk_done index={index} job_id={job_id} "
            f"success={stats.success_count} failed={stats.failed_count}"
        )
    materialize_job_id = _job_id("collect_materialize")
    _log(f"incremental_materialize_start job_id={materialize_job_id}")
    try:
        with session_scope(factory) as session:
            stats = run_collect_and_settle(
                session,
                job_id=materialize_job_id,
                window=source_window,
                include_browser_export=False,
                include_materialization=True,
                collectors=[],
            )
    except Exception as exc:
        _record_failed_collect_chunk(factory, job_id=materialize_job_id, window=source_window, error=exc)
        _log(f"incremental_materialize_failed job_id={materialize_job_id}")
        return
    _log(
        f"incremental_materialize_done job_id={materialize_job_id} "
        f"success={stats.success_count} failed={stats.failed_count}"
    )
    _log(f"incremental_done failed_chunks={failed_chunks}")


def run_browser_export_once(factory) -> None:
    error: Exception | None = None
    with session_scope(factory) as session:
        try:
            run_browser_export_job(session)
        except Exception as exc:
            error = exc
    if error is not None:
        raise error


def run_browser_export_job(
    session: Session,
    *,
    job_id: str | None = None,
    runner: BrowserExportRunner | None = None,
) -> PhaseStats:
    source_run_id = job_id or _job_id("backend_aweme_export")
    start_job_run(
        session,
        source_run_id,
        "backend_aweme_export",
        metadata_json={"phases": {}},
    )
    try:
        active_runner = runner or _run_backend_aweme_export
        stats = active_runner(session, source_run_id)
        job = session.get(JobRun, source_run_id)
        if job is not None:
            job.metadata_json = {"phases": {stats.name: stats.as_metadata()}}
            session.flush()
        finish_job_run(
            session,
            source_run_id,
            status="success",
            success_count=stats.success_count,
            failed_count=stats.failed_count,
        )
        return stats
    except Exception as exc:
        finish_job_run(
            session,
            source_run_id,
            status="failed",
            failed_count=1,
            error_message=sanitize_error_message(str(exc)),
        )
        raise


def _run_backend_aweme_export(session: Session, source_run_id: str) -> PhaseStats:
    from apps.worker.browser_exports.backend_aweme import run_backend_aweme_export

    return run_backend_aweme_export(session, source_run_id=source_run_id)


def main() -> None:
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    run_on_start = _truthy(os.getenv("WORKER_RUN_ON_START", "true"))
    run_once_only = _truthy(os.getenv("WORKER_RUN_ONCE"))
    factory = get_session_factory()

    if run_once_only:
        run_once()
        return
    if run_on_start and _auto_sync_enabled(factory):
        run_once()

    while not _STOP:
        if not _auto_sync_enabled(factory):
            _sleep_until_stop(DISABLED_POLL_SECONDS)
            continue
        interval_seconds = _configured_interval_seconds(factory)
        _sleep_until_stop(interval_seconds)
        if not _STOP and _auto_sync_enabled(factory):
            run_once()


def _configured_interval_seconds(factory) -> int:
    if factory is None:
        return int(os.getenv("WORKER_INTERVAL_SECONDS", str(DEFAULT_INTERVAL_SECONDS)))
    with session_scope(factory) as session:
        return load_sync_config(session).interval_seconds


def _auto_sync_enabled(factory) -> bool:
    if factory is None:
        return _truthy(os.getenv("WORKER_AUTO_SYNC_ENABLED", "true"))
    with session_scope(factory) as session:
        return load_sync_config(session).auto_sync_enabled


def _configured_chunk_max_attempts() -> int:
    try:
        attempts = int(os.getenv("WORKER_CHUNK_MAX_ATTEMPTS", str(DEFAULT_INCREMENTAL_CHUNK_MAX_ATTEMPTS)))
    except ValueError:
        attempts = DEFAULT_INCREMENTAL_CHUNK_MAX_ATTEMPTS
    return max(1, min(5, attempts))


def _sleep_until_stop(seconds: int) -> None:
    sleep_until = time.monotonic() + seconds
    while not _STOP and time.monotonic() < sleep_until:
        time.sleep(min(5, max(0, sleep_until - time.monotonic())))


def _record_failed_collect_chunk(
    factory,
    *,
    job_id: str,
    window: CollectionWindow,
    error: Exception,
) -> None:
    with session_scope(factory) as session:
        start_job_run(
            session,
            job_id,
            "collect_and_settle",
            metadata_json={"source_window": window.as_metadata(), "phases": {}},
        )
        finish_job_run(
            session,
            job_id,
            status="failed",
            failed_count=1,
            error_message=sanitize_error_message(str(error)),
        )


def _successful_collect_window_keys(
    session: Session,
    *,
    since: datetime,
) -> set[tuple[str, str, str]]:
    rows = session.scalars(
        select(JobRun).where(
            JobRun.job_name == "collect_and_settle",
            JobRun.status == "success",
            JobRun.started_at >= since,
        )
    ).all()
    keys: set[tuple[str, str, str]] = set()
    for row in rows:
        key = _metadata_window_key(row.metadata_json)
        if key is not None:
            keys.add(key)
    return keys


def _metadata_window_key(metadata: dict | None) -> tuple[str, str, str] | None:
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


def _window_day_start(window: CollectionWindow) -> datetime:
    return window.end.replace(hour=0, minute=0, second=0, microsecond=0)


def _log(message: str) -> None:
    print(f"[worker-scheduler] {message}", flush=True)


if __name__ == "__main__":
    main()
