"""Bounded, non-authoritative request resource observations without request data.

Only internally generated IDs, registered route templates and process/resource
measurements are logged. RSS is a process snapshot, not a request allocation or
peak measurement. An absent response status means no headers were observed;
FastAPI's outer error handler may subsequently send its normal error response.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from threading import Lock
from time import perf_counter
from typing import Callable
from uuid import uuid4

from starlette.routing import Match, Mount, Route, Router
from starlette.types import ASGIApp, Message, Receive, Scope, Send


LOGGER_NAME = "dy_api.request_resources"
UNKNOWN_ROUTE = "unknown"
logger = logging.getLogger(LOGGER_NAME)
_SAFE_EXCEPTION_CLASS = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,79}\Z")


class _ObservationStdoutHandler(logging.Handler):
    """Flush one JSON line; a broken log sink must not affect a request."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            sys.stdout.write(self.format(record) + "\n")
            sys.stdout.flush()
        except Exception:
            # Do not invoke logging.handleError: its traceback can disclose
            # exception messages and must not replace the application's error.
            return


def configure_request_resource_logging() -> None:
    """Make INFO records visible on production stdout without root-log changes."""
    logger.disabled = False
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not any(isinstance(handler, _ObservationStdoutHandler) for handler in logger.handlers):
        handler = _ObservationStdoutHandler(level=logging.INFO)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)


def read_process_rss_bytes() -> int | None:
    """Read current Linux process RSS; unsupported or unreadable means unknown."""
    try:
        with open("/proc/self/statm", "rb") as source:
            fields = source.read(128).split()
        resident_pages = int(fields[1])
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        if resident_pages > 0 and page_size > 0:
            return resident_pages * page_size
    except (OSError, ValueError, IndexError, AttributeError, OverflowError):
        pass
    return None


def _registered_template(router: Router, scope: Scope, *, prefix: str = "", depth: int = 0) -> str:
    if depth >= 8:
        return UNKNOWN_ROUTE
    partial: str | None = None
    for route in router.routes:
        # Never accept a template from incoming scope["route"] or from a path
        # fallback. Unknown/custom routing remains deliberately unclassified.
        if not isinstance(route, (Route, Mount)):
            continue
        match, child_scope = route.matches(scope)
        if match == Match.NONE:
            continue
        template = prefix + route.path
        if isinstance(route, Mount) and match == Match.FULL:
            child_router = getattr(route, "_base_app", None)
            if not isinstance(child_router, Router):
                child_router = getattr(child_router, "router", None)
            if isinstance(child_router, Router):
                return _registered_template(child_router, {**scope, **child_scope}, prefix=template, depth=depth + 1)
            return UNKNOWN_ROUTE
        if match == Match.FULL:
            return template if len(template) <= 512 else UNKNOWN_ROUTE
        if partial is None:
            partial = template
    return partial if partial is not None and len(partial) <= 512 else UNKNOWN_ROUTE


def _safe_template(router: Router, scope: Scope) -> str:
    try:
        return _registered_template(router, scope)
    except Exception:
        # Matching is observational only. The real router retains ownership of
        # its normal matching errors; never log a converter error or its value.
        return UNKNOWN_ROUTE


def _safe_rss(reader: Callable[[], int | None]) -> int | None:
    try:
        value = reader()
        return value if type(value) is int and value > 0 else None
    except Exception:
        return None


def _emit(event: dict[str, object]) -> None:
    try:
        logger.info("%s", json.dumps(event, ensure_ascii=True, separators=(",", ":")))
    except Exception:
        # No traceback, exception message, or secondary log attempt here.
        return


class RequestResourceObservationMiddleware:
    """Observe the full HTTP ASGI lifetime while passing messages unchanged."""

    def __init__(self, app: ASGIApp, *, router: Router,
                 rss_reader: Callable[[], int | None] | None = None) -> None:
        self.app = app
        self.router = router
        self.rss_reader = rss_reader or read_process_rss_bytes
        self._active_requests = 0
        self._counter_lock = Lock()

    @property
    def active_requests(self) -> int:
        """Number of currently executing HTTP calls in this middleware instance."""
        with self._counter_lock:
            return self._active_requests

    def _change_active(self, delta: int) -> int:
        with self._counter_lock:
            self._active_requests += delta
            return self._active_requests

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = uuid4().hex
        route_template = _safe_template(self.router, scope)
        started = perf_counter()
        status: int | None = None
        exception_class: str | None = None
        active = self._change_active(1)
        try:
            _emit({"event": "api_request_start", "request_id": request_id, "route_template": route_template,
                   "rss_bytes": _safe_rss(self.rss_reader), "active_requests": active,
                   "duration_ms": None, "status": None, "exception_class": None})

            async def observe_send(message: Message) -> None:
                nonlocal status
                if message["type"] == "http.response.start":
                    candidate = message.get("status")
                    status = candidate if type(candidate) is int and 100 <= candidate <= 599 else None
                await send(message)

            await self.app(scope, receive, observe_send)
        except BaseException as exc:
            name = type(exc).__name__
            exception_class = name if _SAFE_EXCEPTION_CLASS.fullmatch(name) else "unknown"
            raise
        finally:
            # Release the counter before any fallible observation or logging.
            active = self._change_active(-1)
            _emit({"event": "api_request_end", "request_id": request_id, "route_template": route_template,
                   "rss_bytes": _safe_rss(self.rss_reader), "active_requests": active,
                   "duration_ms": round((perf_counter() - started) * 1000, 3),
                   "status": status, "exception_class": exception_class})
