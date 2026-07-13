from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from apps.worker.collectors.normalizers import data_items, first, source_datetime, text
from apps.worker.collectors.types import CollectionWindow, PhaseStats
from apps.worker.repositories import upsert_raw_clue

PAGE_ITEM_LIMIT = 10_000
NEAR_PAGE_LIMIT_ROWS = 9_500
MAX_PAGE_SIZE = 100


def collect_clues(
    session: Session,
    client: Any,
    window: CollectionWindow,
    *,
    source_run_id: str,
    page_size: int = MAX_PAGE_SIZE,
) -> PhaseStats:
    stats = PhaseStats(name="clues")
    safe_page_size = min(max(int(page_size or MAX_PAGE_SIZE), 1), MAX_PAGE_SIZE)
    for start, end in _split_window(window.start, window.end, timedelta(days=1)):
        _collect_clue_window(
            session,
            client,
            start,
            end,
            source_run_id=source_run_id,
            page_size=safe_page_size,
            stats=stats,
            allow_split=True,
        )
    return stats


def _collect_clue_window(
    session: Session,
    client: Any,
    start: datetime,
    end: datetime,
    *,
    source_run_id: str,
    page_size: int,
    stats: PhaseStats,
    allow_split: bool,
) -> None:
    rows, near_limit = _fetch_clue_window(client, start, end, page_size=page_size)
    if near_limit and allow_split and (end - start) > timedelta(hours=1):
        for hour_start, hour_end in _split_window(start, end, timedelta(hours=1)):
            _collect_clue_window(
                session,
                client,
                hour_start,
                hour_end,
                source_run_id=source_run_id,
                page_size=page_size,
                stats=stats,
                allow_split=False,
            )
        return

    fetched_at = datetime.now(timezone.utc)
    for row in rows:
        stats.fetched += 1
        clue_row_key = _clue_row_key(row)
        if not clue_row_key:
            stats.skipped += 1
            continue
        upsert_raw_clue(
            session,
            clue_row_key,
            clue_id=text(first(row, "clue_id")),
            source_window_start=start,
            source_window_end=end,
            fetched_at=fetched_at,
            create_time_detail=source_datetime(first(row, "create_time_detail", "create_time")),
            modify_time=source_datetime(first(row, "modify_time", "update_time", "updated_at")),
            name=text(first(row, "name", "user_name", "customer_name")),
            telephone=phone_text(row),
            enc_telephone=text(first(row, "enc_telephone", "encrypted_telephone")),
            product_id=text(first(row, "product_id", "sku_id")),
            product_name=text(first(row, "product_name", "sku_name")),
            order_id=text(first(row, "order_id")),
            order_status=text(first(row, "order_status")),
            follow_life_account_id=text(first(row, "follow_life_account_id")),
            follow_life_account_name=text(first(row, "follow_life_account_name")),
            follow_poi_id=text(first(row, "follow_poi_id")),
            intention_poi_id=text(first(row, "intention_poi_id")),
            auto_city_name=text(first(row, "auto_city_name")),
            auto_province_name=text(first(row, "auto_province_name")),
            author_nickname=text(first(row, "author_nickname")),
            raw_payload=row,
            source_file=None,
            updated_at=fetched_at,
        )
        stats.upserted += 1


def _fetch_clue_window(
    client: Any,
    start: datetime,
    end: datetime,
    *,
    page_size: int,
) -> tuple[list[dict[str, Any]], bool]:
    page_limit = max(1, PAGE_ITEM_LIMIT // page_size)
    rows: list[dict[str, Any]] = []
    near_limit = False
    for page in range(1, page_limit + 1):
        payload = client.query_clues(start, end, page=page, page_size=page_size)
        items = _extract_clues(payload)
        total = _extract_total(payload)
        rows.extend(items)
        if total is not None and total >= NEAR_PAGE_LIMIT_ROWS:
            near_limit = True
        if len(rows) >= NEAR_PAGE_LIMIT_ROWS or page >= int(page_limit * 0.95):
            near_limit = True
        if len(items) < page_size:
            break
    return rows, near_limit


def _extract_clues(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return data_items(payload, "clue_data", "clues", "list", "records")


def _extract_total(payload: dict[str, Any]) -> int | None:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(data, dict):
        return None
    for key in ("total", "total_count", "count"):
        value = data.get(key)
        if value not in (None, ""):
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
    page = data.get("page")
    if isinstance(page, dict) and page.get("total") not in (None, ""):
        try:
            return int(page["total"])
        except (TypeError, ValueError):
            return None
    return None


def phone_text(row: dict[str, Any]) -> str | None:
    return text(
        first(
            row,
            "telephone",
            "tel_addr",
            "phone",
            "mobile",
            "phone_number",
            "customer_phone",
            "contact_phone",
        )
    )


def _clue_row_key(row: dict[str, Any]) -> str:
    clue_id = text(first(row, "clue_id"))
    if clue_id:
        return clue_id
    serialized = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:24]
    return f"raw-clue-{digest}"


def _split_window(
    start: datetime,
    end: datetime,
    step: timedelta,
) -> list[tuple[datetime, datetime]]:
    if start >= end:
        return []
    windows: list[tuple[datetime, datetime]] = []
    current = start
    while current < end:
        window_end = min(current + step, end)
        windows.append((current, window_end))
        current = window_end
    return windows
