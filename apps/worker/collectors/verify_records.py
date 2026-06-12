from __future__ import annotations

import os
from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from apps.worker.collectors.normalizers import amount_cent, data_items, first, next_cursor, source_datetime, text
from apps.worker.collectors.types import CollectionWindow, PhaseStats
from apps.worker.repositories import upsert_store, upsert_store_poi_mapping, upsert_verify_record


def collect_shop_pois(
    session: Session,
    client: Any,
    *,
    source_run_id: str,
    relation_types: tuple[int, ...] = (0,),
) -> PhaseStats:
    stats = PhaseStats(name="shop_pois")
    for relation_type in relation_types:
        cursor: str | None = None
        seen_cursors: set[str | None] = set()
        while cursor not in seen_cursors:
            seen_cursors.add(cursor)
            payload = client.query_shop_pois(relation_type=relation_type, cursor=cursor)
            pois = data_items(payload, "pois", "poi_list", "shop_pois", "list")
            for poi in pois:
                stats.fetched += 1
                poi_id = text(first(poi, "poi_id", "id"))
                if not poi_id:
                    stats.skipped += 1
                    continue
                store_id = text(first(poi, "store_id", "store.store_id"))
                if not store_id:
                    stats.skipped += 1
                    continue
                poi_name = text(first(poi, "poi_name", "name"))
                store_name = text(first(poi, "store_name", "store.store_name", "account_name")) or store_id
                upsert_store(session, store_id, store_name)
                upsert_store_poi_mapping(
                    session,
                    store_id,
                    poi_id,
                    poi_name=poi_name,
                    mapping_source="douyin_shop_poi",
                    is_primary=False,
                )
                stats.upserted += 2
            cursor = next_cursor(payload)
            if not cursor:
                break
    return stats


def collect_verify_records(
    session: Session,
    client: Any,
    window: CollectionWindow,
    *,
    source_run_id: str,
    poi_ids: list[str] | None = None,
    page_size: int = 20,
    chunk_days: int | None = None,
) -> PhaseStats:
    stats = PhaseStats(name="verify_records")
    targets = poi_ids or [None]
    for chunk_start, chunk_end in _split_window(window, chunk_days):
        for poi_id in targets:
            cursor: str | None = None
            seen_cursors: set[str | None] = set()
            while cursor not in seen_cursors:
                seen_cursors.add(cursor)
                payload = client.query_verify_records(
                    chunk_start,
                    chunk_end,
                    poi_id=poi_id,
                    page_size=page_size,
                    cursor=cursor,
                )
                records = data_items(payload, "verify_records", "records", "list")
                for record in records:
                    stats.fetched += 1
                    verify_id = text(first(record, "verify_id", "id"))
                    if not verify_id:
                        stats.skipped += 1
                        continue
                    upsert_verify_record(
                        session,
                        verify_id,
                        coupon_id=text(first(record, "coupon_id", "certificate_id", "code")),
                        verify_status=text(first(record, "verify_status", "status", "certificate_status")),
                        verify_time=source_datetime(first(record, "verify_time")),
                        poi_id=text(first(record, "poi_id", "verify_poi_id")),
                        verify_store_name_raw=text(first(record, "verify_store_name", "verify_poi_name")),
                        sku_id=text(first(record, "sku_id", "sku.sku_id")),
                        product_name=text(first(record, "product_name", "sku.title", "sku_name")),
                        paid_amount_cent=amount_cent(first(record, "paid_amount", "amount.pay_amount")),
                        cancel_time=source_datetime(first(record, "cancel_time")),
                        raw_payload=record,
                        source_run_id=source_run_id,
                    )
                    stats.upserted += 1
                cursor = next_cursor(payload)
                if not cursor:
                    break
    return stats


def _split_window(window: CollectionWindow, chunk_days: int | None):
    days = chunk_days
    if days is None:
        days = int(os.getenv("DOUYIN_VERIFY_CHUNK_DAYS", "7"))
    if days <= 0:
        yield window.start, window.end
        return

    chunk_start = window.start
    while chunk_start < window.end:
        chunk_end = min(chunk_start + timedelta(days=days), window.end)
        yield chunk_start, chunk_end
        chunk_start = chunk_end
