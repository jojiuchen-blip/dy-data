from __future__ import annotations

import os
import signal
import time
from datetime import datetime, timezone
from collections.abc import Mapping
from collections.abc import Callable

from sqlalchemy.orm import Session

from apps.api.dy_api.models import JobRun
from apps.api.dy_api.db import get_session_factory, session_scope
from apps.worker.backfill import run_backfill
from apps.worker.collectors.types import PhaseStats
from apps.worker.pipeline import run_collect_and_settle, sanitize_error_message
from apps.worker.repositories import finish_job_run, start_job_run
from apps.worker.settlement import run_settlement_job


DEFAULT_INTERVAL_SECONDS = 60 * 60 * 24
_STOP = False
BrowserExportRunner = Callable[[Session, str], PhaseStats]


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _handle_stop(signum: int, frame: object) -> None:
    global _STOP
    _STOP = True


def _job_id(prefix: str = "settlement") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"{prefix}_{stamp}"


def resolve_worker_mode(env: Mapping[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    value = source.get("WORKER_MODE", "collect_and_settle").strip().lower()
    if value not in {"collect_and_settle", "settlement_only", "backfill", "browser_export_only"}:
        raise ValueError("WORKER_MODE must be collect_and_settle, settlement_only, backfill, or browser_export_only.")
    return value


def run_once() -> None:
    source_run_id = os.getenv("WORKER_SOURCE_RUN_ID", "scheduled")
    mode = resolve_worker_mode()
    factory = get_session_factory()
    if factory is None:
        raise RuntimeError("Set DY_DATABASE_URL or DATABASE_URL before running worker scheduler.")
    if mode == "backfill":
        run_backfill(factory=factory)
        return
    if mode == "browser_export_only":
        run_browser_export_once(factory)
        return
    with session_scope(factory) as session:
        if mode == "settlement_only":
            run_settlement_job(session, job_id=_job_id("settlement"), source_run_id=source_run_id)
            return
        run_collect_and_settle(session, job_id=_job_id("collect"))


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
    interval_seconds = int(os.getenv("WORKER_INTERVAL_SECONDS", str(DEFAULT_INTERVAL_SECONDS)))

    if run_on_start or run_once_only:
        run_once()
    if run_once_only:
        return

    while not _STOP:
        sleep_until = time.monotonic() + interval_seconds
        while not _STOP and time.monotonic() < sleep_until:
            time.sleep(min(5, max(0, sleep_until - time.monotonic())))
        if not _STOP:
            run_once()


if __name__ == "__main__":
    main()
