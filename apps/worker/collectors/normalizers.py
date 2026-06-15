from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any


def first(payload: dict[str, Any], *paths: str) -> Any:
    for path in paths:
        value = get_path(payload, path)
        if value not in (None, ""):
            return value
    return None


def get_path(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    result = str(value).strip()
    if result.endswith(".0"):
        result = result[:-2]
    return result or None


def source_datetime(value: Any) -> datetime | None:
    if value in (None, "", 0, "0"):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 10_000_000_000:
            number = number / 1000
        return datetime.fromtimestamp(number, tz=timezone.utc)
    raw = str(value).strip()
    try:
        if raw.isdigit():
            return source_datetime(int(raw))
        parsed = datetime.fromisoformat(raw)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def amount_cent(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(Decimal(str(value)))
    except Exception:  # noqa: BLE001 - tolerate external source field drift.
        return None


def data_items(payload: dict[str, Any], *keys: str) -> list[dict[str, Any]]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(data, dict):
        return []
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def next_cursor(payload: dict[str, Any]) -> str | None:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(data, dict):
        return None
    cursor = text(first(data, "next_cursor", "cursor"))
    if not cursor:
        for key in ("records", "verify_records", "records_v2", "list"):
            rows = data.get(key)
            if isinstance(rows, list) and rows and isinstance(rows[-1], dict):
                cursor = text(rows[-1].get("cursor"))
                if cursor:
                    break
    if cursor in {"0", "-1"}:
        return None
    if data.get("has_more") is False:
        return None
    return cursor
