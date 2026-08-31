"""Coordinate browser exports through one shared active-marker protocol."""

from __future__ import annotations

import atexit
import logging
import os
import secrets
import signal
import threading
from contextlib import contextmanager
from pathlib import Path
from types import FrameType
from typing import Any, Iterator


FIXED_BROWSER_EXPORT_ACTIVE_FILE = Path("/run/browser/browser-export.active")

logger = logging.getLogger(__name__)


class BrowserExportActiveError(RuntimeError):
    """Raised when another export already owns the shared marker."""


class BrowserExportMarkerConfigurationError(RuntimeError):
    """Raised when a runtime tries to use a non-fixed marker path."""


class _BrowserExportMarker:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._owner_token: str | None = None
        self._atexit_callback: Any = None
        self._previous_signal_handlers: dict[int, Any] = {}

    def acquire(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        owner_token = f"{os.getpid()}:{secrets.token_hex(16)}\n"
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC

        try:
            descriptor = os.open(self._path, flags, 0o600)
        except FileExistsError as exc:
            raise BrowserExportActiveError(
                f"Browser export marker is already active: {self._path}"
            ) from exc

        try:
            with os.fdopen(descriptor, "w", encoding="ascii") as marker:
                marker.write(owner_token)
                marker.flush()
        except BaseException:
            self._path.unlink(missing_ok=True)
            raise

        self._owner_token = owner_token
        self._atexit_callback = self.cleanup
        atexit.register(self._atexit_callback)
        self._install_signal_handlers()

    def release(self) -> None:
        self._restore_signal_handlers()
        if self._atexit_callback is not None:
            atexit.unregister(self._atexit_callback)
            self._atexit_callback = None
        self.cleanup()

    def cleanup(self) -> None:
        owner_token = self._owner_token
        if owner_token is None:
            return
        try:
            current_token = self._path.read_text(encoding="ascii")
        except FileNotFoundError:
            self._owner_token = None
            return
        except OSError:
            logger.exception("Failed to inspect browser export marker: path=%s", self._path)
            return

        if current_token != owner_token:
            self._owner_token = None
            return
        try:
            self._path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            logger.exception("Failed to remove browser export marker: path=%s", self._path)
            return
        self._owner_token = None

    def _install_signal_handlers(self) -> None:
        if threading.current_thread() is not threading.main_thread():
            return
        watched_signals = [signal.SIGTERM, signal.SIGINT]
        if hasattr(signal, "SIGHUP"):
            watched_signals.append(signal.SIGHUP)
        for watched_signal in watched_signals:
            signum = int(watched_signal)
            self._previous_signal_handlers[signum] = signal.getsignal(watched_signal)
            signal.signal(watched_signal, self._handle_signal)

    def _restore_signal_handlers(self) -> None:
        for signum, previous_handler in self._previous_signal_handlers.items():
            signal.signal(signum, previous_handler)
        self._previous_signal_handlers.clear()

    def _handle_signal(self, signum: int, frame: FrameType | None) -> None:
        previous_handler = self._previous_signal_handlers.get(signum)
        if callable(previous_handler):
            previous_handler(signum, frame)
            return
        if previous_handler == signal.SIG_IGN:
            return
        self.cleanup()
        raise SystemExit(128 + signum)


def _configured_marker_path() -> Path:
    configured_path = os.getenv(
        "BROWSER_EXPORT_ACTIVE_FILE",
        str(FIXED_BROWSER_EXPORT_ACTIVE_FILE),
    )
    path = Path(configured_path)
    if path != FIXED_BROWSER_EXPORT_ACTIVE_FILE:
        raise BrowserExportMarkerConfigurationError(
            "BROWSER_EXPORT_ACTIVE_FILE must be /run/browser/browser-export.active"
        )
    return path


@contextmanager
def browser_export_active() -> Iterator[Path]:
    """Hold the fixed browser-export marker for the duration of one export."""

    marker_path = _configured_marker_path()
    marker = _BrowserExportMarker(marker_path)
    marker.acquire()
    try:
        yield marker_path
    finally:
        marker.release()
