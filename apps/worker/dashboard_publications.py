"""Independent bounded publication supervisor, separate from collection jobs.

Each build runs in a disposable subprocess. A slow builder cannot hold the
supervisor indefinitely or share an API process's memory. No credentials or
source exception messages are written to its logs.
"""

import argparse
from collections.abc import Mapping
from datetime import UTC, datetime
import importlib
import logging
import os
import signal
import subprocess
import sys
from threading import Event
import time

from sqlalchemy import inspect

from apps.api.dy_api.dashboard_publications.lifecycle import (
    Builder, PublicationError, SessionFactory, cleanup_publications, publish_module, resolve_publication,
)
from apps.api.dy_api.dashboard_publications.schema import metadata
from apps.api.dy_api.dashboard_publications.sources import (
    assert_sources_ready, source_fingerprint, writer_lock_keys,
)
from apps.api.dy_api.db import get_session_factory

logger = logging.getLogger(__name__)
BUILDER_SPECS = {
    "douyin-ranking": ("apps.api.dy_api.dashboard_publications.ranking", "build"),
    "sales": ("apps.api.dy_api.dashboard_publications.sales", "build"),
    "clue-overview": ("apps.api.dy_api.dashboard_publications.clues", "build"),
    "settlement": ("apps.api.dy_api.dashboard_publications.finance", "build_settlement"),
    "finance": ("apps.api.dy_api.dashboard_publications.finance", "build_finance"),
}


def load_builder(module: str) -> Builder:
    """Delay domain imports until a worker is asked to build that module."""
    if module not in BUILDER_SPECS:
        raise PublicationError("PUBLICATION_MODULE_UNKNOWN", "未知分析模块", 422)
    path, function = BUILDER_SPECS[module]
    try:
        builder = getattr(importlib.import_module(path), function)
    except Exception:
        raise PublicationError("PUBLICATION_BUILDER_UNAVAILABLE", "分析构建模块尚不可用", 503) from None
    if not callable(builder):
        raise PublicationError("PUBLICATION_BUILDER_UNAVAILABLE", "分析构建模块尚不可用", 503)
    return builder


def run_tick(
    factory: SessionFactory, registry: Mapping[str, Builder], *,
    now: datetime | None = None, guarded: bool = True,
) -> dict[str, str]:
    """Run injected modules for CLI/tests; one failure does not hide another.

    Production uses one module per subprocess. Registry injection permits
    testing the publisher before every sibling module has been integrated.
    """
    result: dict[str, str] = {}
    for module, builder in registry.items():
        # Use one observation instant for the time token and builder. If a
        # boundary passes during hydration, the next tick changes the token;
        # this build cannot claim a new roster while freezing the old cutoff.
        cutoff = now or datetime.now(UTC)
        try:
            publication = publish_module(
                factory, module, builder, now=cutoff,
                fingerprint=(lambda session, module=module: source_fingerprint(session, module, now=cutoff)) if guarded else None,
                readiness_check=assert_sources_ready if guarded else None,
                shared_lock_keys=writer_lock_keys() if guarded else (),
                refresh_on_interval=module == "douyin-ranking",
                statement_timeout_ms=_bounded_int("PUBLICATION_STATEMENT_TIMEOUT_MS", 120000, 1000, 900000),
            )
            result[module] = "published" if publication else "unchanged_or_busy"
            logger.info("publication_tick module=%s result=%s", module, result[module])
        except PublicationError as error:
            result[module] = error.code
            logger.warning("publication_tick module=%s code=%s", module, error.code)
        except Exception:
            # SQL driver exceptions may include URLs, SQL parameters or source
            # data. Do not emit their text/traceback into routine worker logs.
            result[module] = "PUBLICATION_WORKER_FAILED"
            logger.error("publication_tick module=%s code=PUBLICATION_WORKER_FAILED", module)
        try:
            with factory() as session:
                cleanup_publications(session, module=module, limit=2)
                session.commit()
        except Exception:
            logger.warning("publication_retention module=%s code=PUBLICATION_RETENTION_FAILED", module)
    return result


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def check_ready(factory: SessionFactory, modules: tuple[str, ...]) -> bool:
    """Read-only deployment gate: registered schema and every requested head.

    Domain imports belong to CLI startup; this function never creates tables,
    calculates a projection, or turns an absent head into an empty success.
    """
    try:
        with factory() as session:
            existing = set(inspect(session.connection()).get_table_names())
            if not set(metadata.tables).issubset(existing):
                logger.error("publication_ready code=PUBLICATION_SCHEMA_INCOMPLETE")
                return False
            for module in modules:
                resolve_publication(session, module)
    except PublicationError as error:
        logger.error("publication_ready code=%s", error.code)
        return False
    except Exception:
        logger.error("publication_ready code=PUBLICATION_READINESS_FAILED")
        return False
    return True


def supervise(modules: tuple[str, ...], stop: Event) -> None:
    """Fair bounded subprocess polling; wall limits include Python hydration."""
    poll_seconds = _bounded_int("PUBLICATION_POLL_SECONDS", 15, 5, 300)
    wall_seconds = _bounded_int("PUBLICATION_BUILD_TIMEOUT_SECONDS", 180, 10, 900)
    concurrency = _bounded_int("PUBLICATION_MAX_CONCURRENCY", 1, 1, 2)
    active: dict[str, tuple[subprocess.Popen, float]] = {}
    due = dict.fromkeys(modules, 0.0)
    try:
        while not stop.is_set():
            current = time.monotonic()
            for module, (process, started_at) in list(active.items()):
                finished = process.poll() is not None
                if not finished and current - started_at >= wall_seconds:
                    process.kill()
                    process.wait(timeout=5)
                    logger.error("publication_timeout module=%s", module)
                    finished = True
                if finished:
                    del active[module]
                    due[module] = current + poll_seconds
            available = sorted((when, module) for module, when in due.items() if module not in active and when <= current)
            for _, module in available[:max(0, concurrency - len(active))]:
                process = subprocess.Popen(
                    [sys.executable, "-m", "apps.worker.dashboard_publications", "--once", "--module", module],
                    # Windows developer runs should not open visible helper windows.
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                active[module] = (process, current)
            stop.wait(1)
    finally:
        for process, _ in active.values():
            process.terminate()
        for process, _ in active.values():
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build static dashboard publications outside the API/collector")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--check-ready", action="store_true", help="Read only: require schema and all selected successful heads")
    parser.add_argument("--require-ready", action="store_true", help="With --once, fail unless every selected module has a readable head")
    parser.add_argument("--module", choices=tuple(BUILDER_SPECS))
    arguments = parser.parse_args(argv)
    if arguments.require_ready and not arguments.once:
        parser.error("--require-ready requires --once")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    modules = (arguments.module,) if arguments.module else tuple(BUILDER_SPECS)
    if arguments.once or arguments.check_ready:
        factory = get_session_factory()
        if factory is None:
            logger.error("publication_worker code=DATABASE_UNAVAILABLE")
            return 1
        failed = False
        registry = {}
        for module in modules:
            try:
                builder = load_builder(module)
            except PublicationError as error:
                logger.error("publication_worker module=%s code=%s", module, error.code)
                failed = True
                continue
            registry[module] = builder
        if arguments.check_ready:
            return int(failed or not check_ready(factory, modules))
        for module, builder in registry.items():
            results = run_tick(factory, {module: builder})
            failed = failed or any(value not in {"published", "unchanged_or_busy", "PUBLICATION_SOURCE_BUSY"}
                                   for value in results.values())
        ready = check_ready(factory, modules)
        return int(failed or not ready)
    stop = Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    supervise(modules, stop)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
