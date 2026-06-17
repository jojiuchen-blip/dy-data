from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from apps.api.dy_api.models import SyncSetting


DEFAULT_HISTORY_START = "2026-01-01"
DEFAULT_HISTORY_CHUNK_DAYS = 1
DEFAULT_ROLLING_DAYS = 30
DEFAULT_INTERVAL_SECONDS = 60 * 60 * 24
DEFAULT_AUTO_SYNC_ENABLED = True

CONFIG_KEYS = {
    "history_start",
    "history_end",
    "history_chunk_days",
    "rolling_days",
    "interval_seconds",
    "auto_sync_enabled",
    "backfill_skip_completed",
}


@dataclass(frozen=True)
class SyncConfig:
    history_start: str
    history_end: str
    history_chunk_days: int
    rolling_days: int
    interval_seconds: int
    auto_sync_enabled: bool
    backfill_skip_completed: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_sync_config(
    session: Session | None = None,
    *,
    env: dict[str, str] | None = None,
) -> SyncConfig:
    source = os.environ if env is None else env
    values: dict[str, Any] = {
        "history_start": source.get("DOUYIN_COLLECT_START") or DEFAULT_HISTORY_START,
        "history_end": source.get("DOUYIN_COLLECT_END") or "",
        "history_chunk_days": source.get("WORKER_BACKFILL_CHUNK_DAYS") or str(DEFAULT_HISTORY_CHUNK_DAYS),
        "rolling_days": source.get("WORKER_ROLLING_DAYS") or str(DEFAULT_ROLLING_DAYS),
        "interval_seconds": source.get("WORKER_INTERVAL_SECONDS") or str(DEFAULT_INTERVAL_SECONDS),
        "auto_sync_enabled": source.get("WORKER_AUTO_SYNC_ENABLED") or str(DEFAULT_AUTO_SYNC_ENABLED).lower(),
        "backfill_skip_completed": source.get("WORKER_BACKFILL_SKIP_COMPLETED") or "true",
    }
    if session is not None:
        for row in session.query(SyncSetting).all():
            if row.setting_key in CONFIG_KEYS:
                values[row.setting_key] = row.setting_value

    return _coerce_config(values)


def save_sync_config(session: Session, updates: dict[str, Any]) -> SyncConfig:
    current = load_sync_config(session).as_dict()
    for key, value in updates.items():
        if key in CONFIG_KEYS and value is not None:
            current[key] = value
    normalized = _coerce_config(current)
    normalized_values = normalized.as_dict()
    for key, value in normalized_values.items():
        session.merge(
            SyncSetting(
                setting_key=key,
                setting_value=str(value).lower() if isinstance(value, bool) else str(value),
            )
        )
    session.flush()
    return normalized


def _coerce_config(values: dict[str, Any]) -> SyncConfig:
    return SyncConfig(
        history_start=_date_text(values.get("history_start"), DEFAULT_HISTORY_START),
        history_end=_date_text(values.get("history_end"), ""),
        history_chunk_days=_bounded_int(
            values.get("history_chunk_days"),
            DEFAULT_HISTORY_CHUNK_DAYS,
            minimum=1,
            maximum=31,
        ),
        rolling_days=_bounded_int(
            values.get("rolling_days"),
            DEFAULT_ROLLING_DAYS,
            minimum=1,
            maximum=180,
        ),
        interval_seconds=_bounded_int(
            values.get("interval_seconds"),
            DEFAULT_INTERVAL_SECONDS,
            minimum=300,
            maximum=86400 * 7,
        ),
        auto_sync_enabled=_truthy(str(values.get("auto_sync_enabled"))),
        backfill_skip_completed=_truthy(str(values.get("backfill_skip_completed"))),
    )


def _date_text(value: Any, default: str) -> str:
    text = str(value or "").strip()
    if not text:
        return default
    if len(text) == 10:
        datetime.strptime(text, "%Y-%m-%d")
    else:
        datetime.fromisoformat(text)
    return text


def _bounded_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}
