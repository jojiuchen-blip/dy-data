"""Synchronize the Douyin product catalogue and publish opted-in store scopes."""
from __future__ import annotations

import logging
import os
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import partial
from sys import intern
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from apps.api.dy_api.clue_product_routing import ProductRoutingError, publish_douyin_store_list
from apps.api.dy_api.db import session_scope
from apps.api.dy_api.models import ClueProductDouyinStoreScope, ClueProductRoutingConfig, DimStore, DimStorePoiMapping, JobRun
from apps.worker.daily_windows import SHANGHAI_TIMEZONE
from apps.worker.product_sync import DOUYIN_PRODUCT_STATUS_SEQUENCE, product_response_data
from apps.worker.repositories import finish_job_run

logger = logging.getLogger(__name__)
JOB_NAME = "clue_routing_store_sync"
PRODUCT_PAGE_SIZE = 20
PRODUCT_LIMIT = 10_000
SCOPE_WRITE_CHUNK_SIZE = 100
POI_LOOKUP_CHUNK_SIZE = 2_000


@dataclass(frozen=True)
class ProductPois:
    name: str | None
    pois: tuple[str, ...]


def _platform_id(value: Any) -> str | None:
    if type(value) is int and value > 0:
        return str(value)
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        return value
    return None


def _read_product_catalogue(fetch_page: Callable[[str | None], Mapping[str, Any]]) -> dict[str, ProductPois]:
    cursor = None
    seen_cursors: set[str] = set()
    result: dict[str, ProductPois] = {}
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
            if product_id is None:
                raise ValueError("PRODUCT_ID_INVALID")
            name = product.get("product_name")
            name = name.strip() if isinstance(name, str) else None
            if product_id in result:
                result[product_id] = ProductPois(result[product_id].name or name, ())
                continue
            pois = product.get("pois")
            poi_ids = ()
            if isinstance(pois, list) and pois:
                parsed = {_platform_id(poi.get("poi_id")) if isinstance(poi, Mapping) else None for poi in pois}
                if None not in parsed and len(parsed) == len(pois):
                    poi_ids = tuple(sorted(intern(poi) for poi in parsed if poi is not None))
            result[product_id] = ProductPois(name, poi_ids)
        if not has_more:
            return result
        cursor = data.get("next_cursor")
        if not isinstance(cursor, str) or not cursor or cursor in seen_cursors:
            raise ValueError("PRODUCT_CURSOR_INVALID")
        seen_cursors.add(cursor)
    raise ValueError("PRODUCT_SCAN_LIMIT")


def read_product_store_pois(
    fetch_page: Callable[[str | None], Mapping[str, Any]], product_ids: set[str],
) -> dict[str, set[str]]:
    return {product_id: set(product.pois) for product_id, product in _read_product_catalogue(fetch_page).items()
            if product_id in product_ids and product.pois}


def _fetch_catalogue() -> dict[str, ProductPois]:
    from apps.worker.pipeline import build_douyin_client_from_env

    client = build_douyin_client_from_env()
    products: dict[str, ProductPois] = {}
    for status in DOUYIN_PRODUCT_STATUS_SEQUENCE:
        fetch_page = partial(client.query_online_products, status=status, count=PRODUCT_PAGE_SIZE,
                             goods_query_type=2, query_all_poi=True)
        for product_id, product in _read_product_catalogue(lambda cursor: fetch_page(cursor=cursor)).items():
            previous = products.get(product_id)
            if previous is not None:
                product = ProductPois(previous.name or product.name, product.pois if previous.pois == product.pois else ())
            products[product_id] = product
    return products


def _mapped_stores(session, products: Mapping[str, ProductPois]) -> tuple[dict[str, str | None], set[str]]:
    poi_ids = sorted({poi for product in products.values() for poi in product.pois})
    stores: dict[str, str | None] = {}
    duplicates: set[str] = set()
    for offset in range(0, len(poi_ids), POI_LOOKUP_CHUNK_SIZE):
        for poi_id, store_id, active, status in session.execute(
            select(DimStorePoiMapping.poi_id, DimStore.store_id, DimStore.is_active, DimStore.location_status)
            .join(DimStore, DimStore.store_id == DimStorePoiMapping.store_id)
            .where(DimStorePoiMapping.poi_id.in_(poi_ids[offset:offset + POI_LOOKUP_CHUNK_SIZE]))
        ):
            if poi_id in stores:
                duplicates.add(poi_id)
            stores[poi_id] = store_id if active and status != "closed" else None
    return stores, duplicates


def _store_scope(product: ProductPois, stores: Mapping[str, str | None], duplicates: set[str]) -> tuple[str, list[str]]:
    if not product.pois:
        return "missing_or_invalid_pois", []
    if any(poi not in stores or poi in duplicates for poi in product.pois):
        return "poi_mapping_incomplete", []
    store_ids = sorted({stores[poi] for poi in product.pois if stores[poi] is not None})
    return ("valid", store_ids) if store_ids else ("no_active_stores", [])


def _upsert_scopes(session, rows: list[dict[str, Any]], *, valid: bool) -> None:
    table = ClueProductDouyinStoreScope.__table__
    insert = postgres_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert
    for offset in range(0, len(rows), SCOPE_WRITE_CHUNK_SIZE):
        statement = insert(table).values(rows[offset:offset + SCOPE_WRITE_CHUNK_SIZE])
        incoming = statement.excluded
        fields = {
            "product_name": func.coalesce(incoming.product_name, table.c.product_name),
            "status": incoming.status,
            "checked_at": incoming.checked_at,
        }
        if valid:
            fields.update(last_success_at=incoming.last_success_at, store_ids=incoming.store_ids,
                          store_count=incoming.store_count)
        session.execute(statement.on_conflict_do_update(index_elements=[table.c.product_id], set_=fields,
                                                      where=table.c.checked_at < incoming.checked_at))


def _record_catalogue(session, products, now, targets, catalogue_counts):
    stores, duplicates = _mapped_stores(session, products)
    successful, unsuccessful, publishable = [], [], {}
    for product_id, product in sorted(products.items()):
        status, store_ids = _store_scope(product, stores, duplicates)
        row = dict(product_id=product_id, product_name=product.name or None, status=status, checked_at=now)
        catalogue_counts[status] += 1
        if status == "valid":
            successful.append(dict(row, last_success_at=now, store_ids=store_ids, store_count=len(store_ids)))
        else:
            unsuccessful.append(row)
        if product_id in targets:
            publishable[product_id] = (status, store_ids)
    _upsert_scopes(session, successful, valid=True)
    _upsert_scopes(session, unsuccessful, valid=False)
    missing = session.execute(update(ClueProductDouyinStoreScope).where(
        ClueProductDouyinStoreScope.checked_at < now).values(status="missing_product", checked_at=now))
    if missing.rowcount:
        catalogue_counts["missing_product"] = missing.rowcount
    return publishable


def _publish_catalogue(factory, targets, publishable, *, now, day, job_id):
    counts: Counter[str] = Counter()
    for product_id, generation in sorted(targets.items()):
        status, store_ids = publishable.get(product_id, ("missing_product", []))
        if status != "valid":
            counts[status] += 1
            continue
        try:
            with session_scope(factory) as session:
                outcome = publish_douyin_store_list(session, product_id, generation, set(store_ids),
                                                   run_id=job_id, sync_date=day, scope_checked_at=now)
        except ProductRoutingError as exc:
            counts[exc.code.lower()] += 1
        except SQLAlchemyError:
            counts["publication_failed"] += 1
        else:
            counts[outcome] += 1
    return counts


def run_daily_routing_store_sync(
    factory, *, now: datetime | None = None,
    fetch_page: Callable[[str | None], Mapping[str, Any]] | None = None,
) -> str | None:
    """Claim one job per Shanghai date, then refresh and independently publish scopes."""
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
            session.add(JobRun(job_id=job_id, job_name=JOB_NAME, started_at=now, status="running"))
    except IntegrityError:
        # Two workers may see the same unclaimed date. The unique job ID elects one.
        return None

    counts: Counter[str] = Counter()
    catalogue_counts: Counter[str] = Counter()
    products = {}
    try:
        products = _fetch_catalogue() if fetch_page is None else _read_product_catalogue(fetch_page)
    except Exception as exc:
        # Exceptions from HTTP libraries can carry response fragments or request
        # parameters. Only the class and stable internal codes are logged.
        logger.warning("clue_routing_store_sync_failed run=%s error_type=%s", job_id, type(exc).__name__)
        counts["source_error"] = len(targets)
        catalogue_counts["source_error"] = 1
    try:
        with session_scope(factory) as session:
            if catalogue_counts["source_error"]:
                session.execute(update(ClueProductDouyinStoreScope).where(
                    ClueProductDouyinStoreScope.checked_at < now).values(status="source_error", checked_at=now))
                publishable = {}
            else:
                publishable = _record_catalogue(session, products, now, targets, catalogue_counts)
    except SQLAlchemyError as exc:
        logger.warning("clue_routing_catalogue_write_failed run=%s error_type=%s", job_id, type(exc).__name__)
        catalogue_counts = Counter({"catalogue_write_failed": 1})
    else:
        if not catalogue_counts["source_error"]:
            counts = _publish_catalogue(factory, targets, publishable, now=now, day=day, job_id=job_id)

    publication_failed = len(targets) - sum(counts[key] for key in ("published", "unchanged", "source_changed", "stale_run"))
    failed = sum(catalogue_counts.values()) - catalogue_counts["valid"]
    with session_scope(factory) as session:
        unsuccessful = failed or publication_failed
        job = finish_job_run(session, job_id, status="failed" if unsuccessful else "success",
                             success_count=catalogue_counts["valid"], failed_count=failed,
                             error_message="部分或全部商品范围未通过校验或发布" if unsuccessful else None)
        job.metadata_json = {"product_count": len(products), "catalogue_outcomes": dict(catalogue_counts),
                             "publication_target_count": len(targets), "publication_failed_count": publication_failed,
                             "outcomes": dict(counts)}
    return job_id
