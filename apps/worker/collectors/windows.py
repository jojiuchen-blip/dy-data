from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apps.worker.collectors.types import CollectionWindow


DEFAULT_TIMEZONE = "Asia/Shanghai"
DEFAULT_BACKFILL_START = "2026-01-01"


def resolve_collection_window(
    *,
    now: datetime | None = None,
    start: str | datetime | None = None,
    end: str | datetime | None = None,
    overlap_days: int | None = None,
    timezone_name: str | None = None,
    env: Mapping[str, str] | None = None,
) -> CollectionWindow:
    source = os.environ if env is None else env
    tz_name = timezone_name or source.get("DOUYIN_COLLECT_TIMEZONE") or DEFAULT_TIMEZONE
    tz = ZoneInfo(tz_name)
    current = _coerce_datetime(now, tz) if now is not None else datetime.now(tz)

    raw_start = start if start is not None else source.get("DOUYIN_COLLECT_START")
    raw_end = end if end is not None else source.get("DOUYIN_COLLECT_END")
    raw_overlap = overlap_days
    if raw_overlap is None and source.get("DOUYIN_COLLECT_OVERLAP_DAYS"):
        raw_overlap = int(source["DOUYIN_COLLECT_OVERLAP_DAYS"])

    if raw_start is not None:
        resolved_start = _coerce_datetime(raw_start, tz)
    elif raw_overlap and raw_overlap > 0:
        resolved_start = (current - timedelta(days=raw_overlap)).replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        resolved_start = _coerce_datetime(DEFAULT_BACKFILL_START, tz)

    resolved_end = _coerce_datetime(raw_end, tz) if raw_end is not None else current
    if resolved_end <= resolved_start:
        raise ValueError("Collection window end must be after start.")
    return CollectionWindow(start=resolved_start, end=resolved_end, timezone_name=tz_name)


def _coerce_datetime(value: str | datetime, tz: ZoneInfo) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(tz) if value.tzinfo else value.replace(tzinfo=tz)
    text = value.strip()
    if len(text) == 10:
        parsed = datetime.strptime(text, "%Y-%m-%d")
    else:
        parsed = datetime.fromisoformat(text)
    return parsed.astimezone(tz) if parsed.tzinfo else parsed.replace(tzinfo=tz)

