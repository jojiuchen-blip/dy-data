"""Refresh the store scope of opted-in Jingcheng products from Douyin."""
from __future__ import annotations

import logging
import os
from collections import Counter
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from apps.api.dy_api.clue_product_routing import ProductRoutingError, publish_douyin_store_list
from apps.api.dy_api.db import session_scope
from apps.api.dy_api.models import ClueProductRoutingConfig, DimStore, DimStorePoiMapping, JobRun
from apps.worker.daily_windows import SHANGHAI_TIMEZONE
from apps.worker.product_sync import product_response_data
from apps.worker.repositories import finish_job_run

logger = logging.getLogger(__name__)
JOB_NAME = "clue_routing_store_sync"
PRODUCT_PAGE_SIZE = 20
PRODUCT_LIMIT = 10_000


def _platform_id(value: Any) -> str | None:
    if type(value) is int and value > 0:
        return str(value)
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        return value
    return None


def read_product_store_pois(
    fetch_page: Callable[[str | None], Mapping[str, Any]], product_ids: set[str],
) -> dict[str, set[str]]:
    """Read a complete product scan, accepting only well-formed nonempty POI sets."""
    cursor = None
    seen_cursors: set[str] = set()
    seen_products: set[str] = set()
    result: dict[str, set[str]] = {}
    # The API allows at most 10,000 products. Bound both pages and rows even
    # when an upstream response ignores the requested count.
    row_count = 0
    for _ in range(PRODUCT_LIMIT // PRODUCT_PAGE_SIZE + 1):
        data = product_response_data(fetch_page(cursor), "Routing store list")
        rows, has_more = data.get("products"), data.get("has_more")
        if not isinstance(rows, list) or type(has_more) is not bool or (has_more and not rows):
            raise ValueError("PRODUCT_PAGE_INCOMPLETE")
        row_count += len(rows)
        if row_count >= PRODUCT_LIMIT:
            raise ValueError("PRODUCT_SCAN_LIMIT")
        for row in rows:
            product = row.get("product") if isinstance(row, Mapping) else None
            if not isinstance(product, Mapping):
                raise ValueError("PRODUCT_ROW_INVALID")
            product_id = _platform_id(product.get("product_id"))
            if product_id not in product_ids:
                continue
            if product_id in seen_products:
                result.pop(product_id, None)
                continue
            seen_products.add(product_id)
            pois = product.get("pois")
            if not isinstance(pois, list) or not pois:
                continue
            parsed = {_platform_id(poi.get("poi_id")) if isinstance(poi, Mapping) else None for poi in pois}
            if None not in parsed and len(parsed) == len(pois):
                result[product_id] = {poi for poi in parsed if poi is not None}
        if not has_more:
            return result
        cursor = data.get("next_cursor")
        if not isinstance(cursor, str) or not cursor or cursor in seen_cursors:
            raise ValueError("PRODUCT_CURSOR_INVALID")
        seen_cursors.add(cursor)
    raise ValueError("PRODUCT_SCAN_LIMIT")


def run_daily_routing_store_sync(
    factory, *, now: datetime | None = None,
    fetch_page: Callable[[str | None], Mapping[str, Any]] | None = None,
) -> str | None:
    """Claim one job per Shanghai date and publish each complete product atomically."""
    if fetch_page is None and os.getenv("DOUYIN_ROUTING_STORE_SYNC_ENABLED", "true").lower() != "true":
        return None
    now = now or datetime.now(timezone.utc)
    day = now.astimezone(SHANGHAI_TIMEZONE).date()
    job_id = f"clue-routing-stores-{day.isoformat()}"
    try:
        with session_scope(factory) as session:
            if session.get(JobRun, job_id) is not None:
                return None
            targets = dict(session.execute(select(ClueProductRoutingConfig.product_id, ClueProductRoutingConfig.store_list_sync_generation)
                .where(ClueProductRoutingConfig.store_list_source.in_(("auto_pending", "douyin")),
                       ClueProductRoutingConfig.store_list_sync_generation.is_not(None))).all())
            if not targets:
                return None
            session.add(JobRun(job_id=job_id, job_name=JOB_NAME, started_at=now, status="running"))
    except IntegrityError:
        # Two workers may see the same unclaimed date. The unique job ID elects one.
        return None

    counts: Counter[str] = Counter()
    try:
        if fetch_page is None:
            from apps.worker.pipeline import build_douyin_client_from_env

            client = build_douyin_client_from_env()

            def fetch_page(cursor):
                return client.query_online_products(status=None, count=PRODUCT_PAGE_SIZE, cursor=cursor,
                                                    goods_query_type=2, query_all_poi=True)

        products = read_product_store_pois(fetch_page, set(targets))
    except Exception as exc:
        # Exceptions from HTTP libraries can carry response fragments or request
        # parameters. Only the class and stable internal codes are logged.
        logger.warning("clue_routing_store_sync_failed run=%s error_type=%s", job_id, type(exc).__name__)
        counts["source_error"] = len(targets)
    else:
        for product_id, generation in targets.items():
            pois = products.get(product_id)
            if not pois:
                counts["missing_or_invalid_pois"] += 1
                continue
            try:
                with session_scope(factory) as session:
                    rows = session.execute(select(DimStorePoiMapping.poi_id, DimStore.store_id, DimStore.is_active, DimStore.location_status)
                        .join(DimStore, DimStore.store_id == DimStorePoiMapping.store_id)
                        .where(DimStorePoiMapping.poi_id.in_(sorted(pois)))).all()
                    mapped_pois = {row.poi_id for row in rows}
                    if mapped_pois != pois or len(rows) != len(mapped_pois):
                        counts["poi_mapping_incomplete"] += 1
                        continue
                    store_ids = {row.store_id for row in rows if row.is_active and row.location_status != "closed"}
                    outcome = publish_douyin_store_list(session, product_id, generation, store_ids, run_id=job_id, sync_date=day)
            except ProductRoutingError as exc:
                counts[exc.code.lower()] += 1
            except SQLAlchemyError:
                counts["publication_failed"] += 1
            else:
                counts[outcome] += 1

    successes = counts["published"] + counts["unchanged"]
    failed = len(targets) - successes - counts["source_changed"] - counts["stale_run"]
    with session_scope(factory) as session:
        job = finish_job_run(session, job_id, status="failed" if failed else "success",
                             success_count=successes, failed_count=failed,
                             error_message="部分或全部商品范围未通过校验" if failed else None)
        job.metadata_json = {"product_count": len(targets), "outcomes": dict(counts)}
    return job_id
