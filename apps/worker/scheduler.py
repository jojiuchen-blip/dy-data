from __future__ import annotations

import os
import math
import signal
import subprocess
import sys
import time
from datetime import datetime, time as datetime_time, timedelta, timezone
from collections.abc import Mapping
from collections.abc import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import JobRun
from apps.api.dy_api.db import get_session_factory, session_scope
from apps.worker.backfill import iter_backfill_windows, run_backfill
from apps.worker.collectors.types import CollectionWindow, PhaseStats
from apps.worker.collectors.windows import resolve_collection_window
from apps.worker.daily_windows import (
    SHANGHAI_TIMEZONE,
    SHANGHAI_TIMEZONE_NAME,
    DailySyncPlan,
    plan_daily_sync,
)
from apps.worker.materialize_once import MATERIALIZATION_STAGES
from apps.worker.pipeline import run_collect_and_settle, sanitize_error_message
from apps.worker.product_sync import PRODUCT_SYNC_JOB_NAME, run_product_sync_job
from apps.worker.queued_jobs import process_queued_settlement_rebuilds
from apps.worker.repositories import finish_job_run, queue_job_run, start_job_run
from apps.worker.settlement import run_settlement_job
from apps.worker.sync_config import DEFAULT_INTERVAL_SECONDS, DEFAULT_ROLLING_DAYS, load_sync_config
from apps.worker.subprocess_supervisor import (
    DEFAULT_LEASE_SECONDS,
    ChildRunResult,
    ChildRunStatus,
    SubprocessSupervisor,
)
from src.dy_data.config import douyin_account_id, douyin_app_id, douyin_app_secret


_STOP = False
DISABLED_POLL_SECONDS = 60
DEFAULT_DAILY_QUEUE_POLL_SECONDS = 5
DEFAULT_DAILY_CHILD_TIMEOUT_SECONDS = 6 * 60 * 60
DEFAULT_INCREMENTAL_CHUNK_MAX_ATTEMPTS = 2
DEFAULT_MATERIALIZATION_STAGE_TIMEOUT_SECONDS = 7200
DEFAULT_PRODUCT_SYNC_INTERVAL_SECONDS = 86400
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
    configured_timezone = (
        source.get("DOUYIN_COLLECT_TIMEZONE") or SHANGHAI_TIMEZONE_NAME
    ).strip()
    if configured_timezone != SHANGHAI_TIMEZONE_NAME:
        raise ValueError(
            "DOUYIN_COLLECT_TIMEZONE must be Asia/Shanghai for daily planning."
        )
    current = now or datetime.now(SHANGHAI_TIMEZONE)
    local_current = (
        current.astimezone(SHANGHAI_TIMEZONE)
        if current.tzinfo is not None
        else current.replace(tzinfo=SHANGHAI_TIMEZONE)
    )
    range_end_date = local_current.date()
    range_start_date = range_end_date - timedelta(days=days)
    return CollectionWindow(
        start=datetime.combine(
            range_start_date,
            datetime_time.min,
            tzinfo=SHANGHAI_TIMEZONE,
        ),
        end=datetime.combine(
            range_end_date,
            datetime_time.min,
            tzinfo=SHANGHAI_TIMEZONE,
        ),
        timezone_name=SHANGHAI_TIMEZONE_NAME,
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
        drain_ready_daily_children(factory)
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
    run_scheduled_product_sync(factory)


def run_scheduled_product_sync(factory, *, now: datetime | None = None) -> str | None:
    """Run the product master refresh when its independent interval is due."""

    if not _truthy(os.getenv("DOUYIN_PRODUCT_SYNC_ENABLED", "true")):
        return None
    if not all((douyin_app_id(), douyin_app_secret(), douyin_account_id())):
        _log("product_sync_skip reason=credentials_not_configured")
        return None
    current_time = now or datetime.now(timezone.utc)
    interval_seconds = _bounded_product_sync_interval()
    with session_scope(factory) as session:
        active = session.scalar(
            select(JobRun.job_id)
            .where(
                JobRun.job_name == PRODUCT_SYNC_JOB_NAME,
                JobRun.status.in_(("queued", "running")),
            )
            .limit(1)
        )
        if active is not None:
            _log("product_sync_skip reason=active_run")
            return None
        latest_started_at = session.scalar(
            select(func.max(JobRun.started_at)).where(
                JobRun.job_name == PRODUCT_SYNC_JOB_NAME
            )
        )
        if latest_started_at is not None:
            if latest_started_at.tzinfo is None:
                latest_started_at = latest_started_at.replace(tzinfo=timezone.utc)
            if (current_time - latest_started_at).total_seconds() < interval_seconds:
                _log("product_sync_skip reason=interval_not_due")
                return None
        job_id = f"product-sync-scheduled-{current_time:%Y%m%d%H%M%S}"
        queue_job_run(
            session,
            job_id,
            PRODUCT_SYNC_JOB_NAME,
            started_at=current_time,
            metadata_json={
                "mode": "INCREMENTAL",
                "reason": "scheduled product master refresh",
                "phase_counts": {},
            },
        )
    _log(f"product_sync_start job_id={job_id}")
    run_product_sync_job(job_id=job_id, factory=factory)
    _log(f"product_sync_done job_id={job_id}")
    return job_id


def run_incremental_collection_chunks(factory, config) -> DailySyncPlan:
    source_window = resolve_incremental_collection_window(
        env={
            **os.environ,
            "WORKER_ROLLING_DAYS": str(config.rolling_days),
        }
    )
    with session_scope(factory) as session:
        plan = plan_daily_sync(
            session,
            start=source_window.start,
            end=source_window.end,
            target="all",
            requested_by="worker-scheduler",
            trigger_source="scheduler",
        )
    _log(
        "incremental_planned "
        f"parent_job_id={plan.parent_job_id} dates={len(plan.daily_jobs)} "
        f"start={plan.window_start.isoformat()} end={plan.window_end.isoformat()}"
    )
    execute_ready_daily_child(factory, plan)
    return plan


def run_daily_child(
    factory,
    job_id: str | None = None,
    *,
    supervisor: SubprocessSupervisor | None = None,
    max_attempts: int | None = None,
    timeout_seconds: float | None = None,
) -> ChildRunResult:
    configured_lease_seconds = _configured_daily_lease_seconds()
    effective_timeout_seconds = (
        _configured_daily_child_timeout_seconds()
        if timeout_seconds is None
        else _validate_daily_child_timeout_seconds(timeout_seconds)
    )
    active_supervisor = supervisor or SubprocessSupervisor(
        control_session_factory=factory,
        lease_seconds=configured_lease_seconds,
        heartbeat_interval_seconds=_configured_daily_heartbeat_seconds(
            configured_lease_seconds
        ),
    )
    command = [sys.executable, "-m", "apps.worker.daily_task"]
    if job_id is not None:
        command.extend(("--job-id", job_id))
    return active_supervisor.run(
        job_id=job_id,
        command=command,
        max_attempts=max_attempts or _configured_chunk_max_attempts(),
        timeout_seconds=effective_timeout_seconds,
    )


def drain_ready_daily_children(
    factory,
    *,
    max_children: int | None = None,
) -> tuple[ChildRunResult, ...]:
    if not _truthy(os.getenv("WORKER_EXECUTE_DAILY_CHILD")):
        return ()
    if max_children is not None and max_children <= 0:
        raise ValueError("max_children must be positive when provided")

    results: list[ChildRunResult] = []
    yield_statuses = {
        ChildRunStatus.RETRY_WAIT,
        ChildRunStatus.BUSY,
        ChildRunStatus.CONTROL_ERROR,
    }
    while not _STOP and (
        max_children is None or len(results) < max_children
    ):
        result = run_daily_child(factory)
        results.append(result)
        _log(
            "daily_child_finished "
            f"job_id={result.job_id} status={result.status.value} "
            f"attempts={result.attempts} exit_code={result.exit_code} "
            f"rss_peak_bytes={result.rss_peak_bytes}"
        )
        if result.status in yield_statuses:
            break
    return tuple(results)


def execute_ready_daily_child(
    factory,
    plan: DailySyncPlan,
) -> ChildRunResult | None:
    _ = plan
    results = drain_ready_daily_children(factory)
    return results[-1] if results else None


def _configured_daily_lease_seconds() -> int:
    raw = os.getenv("WORKER_DAILY_LEASE_SECONDS")
    return DEFAULT_LEASE_SECONDS if raw is None else int(raw)


def _validate_daily_child_timeout_seconds(value: float | int) -> float:
    try:
        timeout_seconds = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "WORKER_DAILY_CHILD_TIMEOUT_SECONDS must be a finite positive number"
        ) from exc
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError(
            "WORKER_DAILY_CHILD_TIMEOUT_SECONDS must be a finite positive number"
        )
    return timeout_seconds


def _configured_daily_child_timeout_seconds() -> float:
    raw = os.getenv("WORKER_DAILY_CHILD_TIMEOUT_SECONDS")
    if raw is None:
        return float(DEFAULT_DAILY_CHILD_TIMEOUT_SECONDS)
    return _validate_daily_child_timeout_seconds(raw)


def _configured_daily_heartbeat_seconds(lease_seconds: int) -> float:
    raw = os.getenv("WORKER_DAILY_HEARTBEAT_INTERVAL_SECONDS")
    if raw is None:
        return min(5.0, max(0.1, lease_seconds / 2))
    return float(raw)


def _configured_daily_queue_poll_seconds() -> float:
    raw = os.getenv("WORKER_DAILY_QUEUE_POLL_SECONDS")
    if raw is None:
        return float(DEFAULT_DAILY_QUEUE_POLL_SECONDS)
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(
            "WORKER_DAILY_QUEUE_POLL_SECONDS must be a number"
        ) from exc
    return min(60.0, max(0.1, value))


def run_isolated_materialization(
    *,
    window: CollectionWindow,
    job_id: str,
    command_runner=subprocess.run,
    timeout_seconds: int | None = None,
) -> tuple[str, ...]:
    """Run each memory-heavy projection in a fresh process."""

    timeout = timeout_seconds or _configured_materialization_stage_timeout()
    completed: list[str] = []
    for stage in MATERIALIZATION_STAGES:
        command = [
            sys.executable,
            "-m",
            "apps.worker.materialize_once",
            "--job-id",
            job_id,
            "--stage",
            stage,
        ]
        _log(
            f"materialization_stage_start job_id={job_id} stage={stage} "
            f"start={window.start.isoformat()} end={window.end.isoformat()}"
        )
        try:
            result = command_runner(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"materialization stage {stage} timed out after {timeout} seconds"
            ) from exc
        if result.returncode != 0:
            detail = _subprocess_detail(result.stderr or result.stdout)
            raise RuntimeError(
                f"materialization stage {stage} exited {result.returncode}: {detail}"
            )
        completed.append(stage)
        _log(
            f"materialization_stage_done job_id={job_id} stage={stage} "
            f"result={_subprocess_detail(result.stdout)}"
        )
    return tuple(completed)


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
    auto_enabled = _auto_sync_enabled(factory)
    if run_on_start and auto_enabled:
        run_once()
        next_plan_at = time.monotonic() + _configured_interval_seconds(factory)
    elif auto_enabled:
        next_plan_at = time.monotonic() + _configured_interval_seconds(factory)
    else:
        next_plan_at = None

    while not _STOP:
        drain_ready_daily_children(factory)
        if _STOP:
            break

        auto_enabled = _auto_sync_enabled(factory)
        now = time.monotonic()
        if auto_enabled:
            if next_plan_at is None or now >= next_plan_at:
                run_once()
                next_plan_at = (
                    time.monotonic()
                    + _configured_interval_seconds(factory)
                )
            sleep_seconds = _configured_daily_queue_poll_seconds()
            if next_plan_at is not None:
                sleep_seconds = min(
                    sleep_seconds,
                    max(0.1, next_plan_at - time.monotonic()),
                )
        else:
            next_plan_at = None
            sleep_seconds = _configured_daily_queue_poll_seconds()
        _sleep_until_stop(sleep_seconds)


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
    return max(1, min(3, attempts))


def _configured_materialization_stage_timeout() -> int:
    try:
        seconds = int(
            os.getenv(
                "WORKER_MATERIALIZATION_STAGE_TIMEOUT_SECONDS",
                str(DEFAULT_MATERIALIZATION_STAGE_TIMEOUT_SECONDS),
            )
        )
    except ValueError:
        seconds = DEFAULT_MATERIALIZATION_STAGE_TIMEOUT_SECONDS
    return max(60, min(21600, seconds))


def _bounded_product_sync_interval() -> int:
    try:
        seconds = int(
            os.getenv(
                "DOUYIN_PRODUCT_SYNC_INTERVAL_SECONDS",
                str(DEFAULT_PRODUCT_SYNC_INTERVAL_SECONDS),
            )
        )
    except ValueError as exc:
        raise ValueError("DOUYIN_PRODUCT_SYNC_INTERVAL_SECONDS must be an integer") from exc
    return max(1800, min(604800, seconds))


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


def _record_successful_materialization(
    factory,
    *,
    job_id: str,
    window: CollectionWindow,
    completed_stages: tuple[str, ...],
) -> None:
    phases = {
        stage: {"name": stage, "status": "success"}
        for stage in completed_stages
    }
    with session_scope(factory) as session:
        start_job_run(
            session,
            job_id,
            "collect_and_settle",
            metadata_json={"source_window": window.as_metadata(), "phases": phases},
        )
        finish_job_run(
            session,
            job_id,
            status="success",
            success_count=len(completed_stages),
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


def _incremental_chunks_latest_first(
    source_window: CollectionWindow,
    *,
    chunk_days: int,
) -> list[CollectionWindow]:
    """Process the newest window first so long historical retries do not hide fresh data."""

    return list(reversed(list(iter_backfill_windows(source_window, chunk_days=chunk_days))))


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


def _subprocess_detail(value: str | None) -> str:
    lines = [line.strip() for line in (value or "").splitlines() if line.strip()]
    return sanitize_error_message(lines[-1] if lines else "no output")


def _log(message: str) -> None:
    print(f"[worker-scheduler] {message}", flush=True)


if __name__ == "__main__":
    main()
