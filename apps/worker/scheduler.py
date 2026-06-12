from __future__ import annotations

import os
import signal
import time
from datetime import datetime, timezone

from apps.api.dy_api.db import get_session_factory, session_scope
from apps.worker.settlement import run_settlement_job


DEFAULT_INTERVAL_SECONDS = 60 * 60 * 24
_STOP = False


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _handle_stop(signum: int, frame: object) -> None:
    global _STOP
    _STOP = True


def _job_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"settlement_{stamp}"


def run_once() -> None:
    source_run_id = os.getenv("WORKER_SOURCE_RUN_ID", "scheduled")
    factory = get_session_factory()
    if factory is None:
        raise RuntimeError("Set DY_DATABASE_URL or DATABASE_URL before running worker scheduler.")
    with session_scope(factory) as session:
        run_settlement_job(session, job_id=_job_id(), source_run_id=source_run_id)


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
