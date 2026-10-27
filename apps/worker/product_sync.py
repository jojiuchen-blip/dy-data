from __future__ import annotations

from collections.abc import Callable, Mapping
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import logging
import os
from typing import Any, Protocol

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from src.dy_data.product_classification import synced_product_type

from apps.api.dy_api.db import get_session_factory, session_scope
from apps.api.dy_api.models import (
    DataQualityIssue,
    DimSkuProductRule,
    JobRun,
    RawDouyinOrder,
    SkuProductSyncHistory,
    SyncSetting,
    utcnow,
)
from apps.ops_agent.resources import ResourceAction
from apps.worker.repositories import (
    HEAVY_SYNC_CLAIM_LOCK_KEY,
    heavy_sync_rate_limit_cooldown_active,
    no_other_running_heavy_job,
)
from apps.worker.resource_monitor import current_resource_decision


PRODUCT_SYNC_JOB_NAME = "product_sync"
PRODUCT_SYNC_CURSOR_SETTING_KEY = "product_sync.incremental_cursor"
PRODUCT_STATUSES = {"ACTIVE", "INACTIVE", "BANNED", "DELETED", "UNKNOWN"}
DOUYIN_ONLINE_STATUS_MAP = {
    "1": "ACTIVE",
    "2": "INACTIVE",
    "3": "BANNED",
}
DOUYIN_PRODUCT_STATUS_SEQUENCE = (1, 2, 3)
DOUYIN_PRODUCT_CURSOR_PREFIX = "dy-product-v1:"
PRODUCT_LOOKUP_ATTEMPTS = 3
logger = logging.getLogger(__name__)
PRODUCT_RAW_PAYLOAD_FIELDS = (
    "skuId",
    "skuName",
    "productId",
    "productName",
    "spuId",
    "creatorAccountId",
    "creatorAccountName",
    "ownerAccountId",
    "ownerAccountName",
    "productStatusRaw",
    "productStatus",
    "productUpdatedAt",
    "syncStatus",
    "syncError",
)
PLATFORM_FIELD_MAP = {
    "sku_name": "sku_name",
    "product_id": "product_id",
    "product_name": "product_name",
    "spu_id": "spu_id",
    "creator_account_id": "creator_account_id",
    "creator_account_name": "creator_account_name",
    "owner_account_id": "owner_account_id",
    "owner_account_name": "owner_account_name",
    "product_status_raw": "product_status_raw",
    "product_status_normalized": "product_status_normalized",
    "product_updated_at": "product_updated_at",
    "sync_status": "sync_status",
    "sync_error": "sync_error",
}


class ProductSyncAdapter(Protocol):
    def fetch_page(self, *, mode: str, cursor: str | None) -> "ProductSyncPage": ...


class ProductSyncPayloadError(ValueError):
    pass


class ProductSyncIncompleteError(ProductSyncPayloadError):
    """An exact-ID lookup remained incomplete after bounded retries."""


@dataclass(frozen=True)
class ProductSyncItem:
    sku_id: str
    sku_name: str | None
    product_id: str | None
    product_name: str | None
    spu_id: str | None
    creator_account_id: str | None
    creator_account_name: str | None
    owner_account_id: str | None
    owner_account_name: str | None
    product_status_raw: str | None
    product_status_normalized: str
    product_updated_at: datetime | None
    sync_status: str
    sync_error: str | None
    raw_payload: dict[str, Any]
    payload_sha256: str


@dataclass(frozen=True)
class ProductSyncPage:
    items: tuple[ProductSyncItem, ...]
    invalid_items: tuple[tuple[int, str], ...]
    observed_count: int
    has_more: bool
    next_cursor: str | None
    payload_sha256: str
    skipped_count: int = 0


@dataclass(frozen=True)
class ProductSyncResult:
    job_id: str
    status: str
    observed_count: int = 0
    inserted_count: int = 0
    updated_count: int = 0
    unchanged_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    error_code: str | None = None


class NormalizedProductSyncAdapter:
    """Adapter for the frozen internal product-page contract.

    The callable must return a sanitized, normalized page.  Mapping the real
    Douyin response into this shape remains deliberately outside this class until
    official sanitized samples document the external field and cursor semantics.
    """

    def __init__(self, fetch_page: Callable[..., Mapping[str, Any]]) -> None:
        self._fetch_page = fetch_page

    def fetch_page(self, *, mode: str, cursor: str | None) -> ProductSyncPage:
        payload = self._fetch_page(mode=mode, cursor=cursor)
        return parse_normalized_product_page(payload)


class UnavailableProductSyncAdapter:
    def fetch_page(self, *, mode: str, cursor: str | None) -> ProductSyncPage:
        _ = mode, cursor
        raise RuntimeError(
            "Douyin product sync mapping is not configured; provide sanitized official samples first"
        )


class DouyinProductSyncAdapter:
    """Map the two official Goodlife product endpoints to the frozen worker contract."""

    supports_persistent_cursor = False

    def __init__(
        self,
        client: Any,
        *,
        known_products: Mapping[str, set[str]] | None = None,
        page_size: int = 50,
        goods_query_type: int = 2,
    ) -> None:
        if page_size < 1 or page_size > 50:
            raise ValueError("Product page size must be between 1 and 50")
        if goods_query_type not in {1, 2, 3}:
            raise ValueError("goods_query_type must be 1, 2, or 3")
        self._client = client
        self._known_products = {
            str(product_id): {str(sku_id) for sku_id in sku_ids if str(sku_id).strip()}
            for product_id, sku_ids in (known_products or {}).items()
            if str(product_id).strip()
        }
        known_sku_products: dict[str, str] = {}
        for product_id, sku_ids in self._known_products.items():
            for sku_id in sku_ids:
                if sku_id in known_sku_products and known_sku_products[sku_id] != product_id:
                    raise ProductSyncPayloadError("Known SKU has conflicting product identities")
                known_sku_products[sku_id] = product_id
        self._known_sku_products = known_sku_products
        self._observed_skus: dict[str, dict[str, Any]] = {}
        self._sku_lookup_cache: dict[str, dict[str, Mapping[str, Any]]] = {}
        self._page_size = page_size
        self._goods_query_type = goods_query_type
        self._seen_product_skus: dict[str, set[str]] = {}
        self._products_with_empty_skus: set[str] = set()
        self._fallback_product_ids: list[str] | None = None
        self._seen_list_cursors: set[tuple[int, str | None]] = set()
        self.lookup_stats = {
            "attempt_limit_per_batch": PRODUCT_LOOKUP_ATTEMPTS,
            "product_id_requests": 0,
            "sku_requests": 0,
            "partial_responses": 0,
            # Existing client transport retries apply per request. Partial
            # retries never catch transport/quota errors or restart a batch.
            "business_attempt_limit_per_query": max(1, getattr(client, "retry_attempts", 1)),
            "transport_attempt_limit_per_business_attempt": max(1, getattr(client, "retry_attempts", 1)),
            "product_http_attempt_upper_bound_per_query": max(1, getattr(client, "retry_attempts", 1)) ** 2,
        }

    def _validate_sku_identity(self, row: dict[str, Any], previous: dict[str, Any] | None) -> None:
        sku_id, product_id = row.get("skuId"), row.get("productId")
        if self._known_sku_products.get(sku_id, product_id) != product_id:
            raise ProductSyncPayloadError("Observed SKU conflicts with known product identity")
        if previous and any(
            previous.get(field) and row.get(field) and previous[field] != row[field]
            for field in ("productId", "ownerAccountId", "creatorAccountId")
        ):
            raise ProductSyncPayloadError("Repeated SKU product or ownership identity conflicts")

    def _observe_product_skus(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            product_id = row.get("productId")
            sku_id = row.get("skuId")
            if product_id and sku_id:
                previous = self._observed_skus.get(sku_id)
                self._validate_sku_identity(row, previous)
                self._observed_skus[sku_id] = {
                    **(previous or {}), **{field: value for field, value in row.items() if value is not None}
                }
                self._seen_product_skus.setdefault(product_id, set()).add(sku_id)

    def _products_with_sku_gaps(self) -> list[str]:
        return sorted(self._products_with_empty_skus | {
            product_id
            for product_id, sku_ids in self._known_products.items()
            if product_id not in self._seen_product_skus
            or sku_ids - self._seen_product_skus[product_id]
        })

    def fetch_page(self, *, mode: str, cursor: str | None) -> ProductSyncPage:
        _ = mode
        state = _decode_douyin_product_cursor(cursor)
        if state["stage"] == "ids":
            return self._fetch_id_page(int(state.get("offset") or 0))
        return self._fetch_list_page(
            status_index=int(state.get("status_index") or 0),
            upstream_cursor=_optional_text(state.get("cursor")),
        )

    def _fetch_list_page(
        self,
        *,
        status_index: int,
        upstream_cursor: str | None,
    ) -> ProductSyncPage:
        if status_index < 0 or status_index >= len(DOUYIN_PRODUCT_STATUS_SEQUENCE):
            raise ProductSyncPayloadError("Invalid product status page cursor")
        status = DOUYIN_PRODUCT_STATUS_SEQUENCE[status_index]
        self._seen_list_cursors.add((status_index, upstream_cursor))
        payload = self._client.query_online_products(
            status=status,
            cursor=upstream_cursor,
            count=self._page_size,
            goods_query_type=self._goods_query_type,
        )
        data = _product_response_data(payload, "Product list")
        rows = data.get("products")
        if not isinstance(rows, list):
            raise ProductSyncPayloadError("Product list response products must be a list")
        # List pages can expose different variants of the same product. Wait
        # for every page/status before the frozen product-ID gap fallback.
        normalized_rows, skipped_count = _normalize_douyin_online_rows(rows)
        # An empty record is unresolved even when a different page/status has
        # already shown some variants. Require one exact-ID reconciliation.
        for record in rows:
            if not isinstance(record, Mapping):
                continue
            product = record.get("product")
            product_id = _optional_text(product.get("product_id")) if isinstance(product, Mapping) else None
            single_sku = record.get("sku")
            has_single_sku = isinstance(single_sku, Mapping) and _optional_text(single_sku.get("sku_id"))
            has_multiple_skus = isinstance(record.get("skus"), list) and bool(record["skus"])
            if product_id and not has_single_sku and not has_multiple_skus:
                self._products_with_empty_skus.add(product_id)
        self._observe_product_skus(normalized_rows)
        has_more = data.get("has_more")
        if not isinstance(has_more, bool):
            raise ProductSyncPayloadError("Product list response has_more must be a boolean")
        next_upstream = _optional_text(data.get("next_cursor"))
        if has_more:
            if not next_upstream or (status_index, next_upstream) in self._seen_list_cursors:
                raise ProductSyncPayloadError(
                    "Product list response requires a new next_cursor"
                )
            next_cursor = _encode_douyin_product_cursor(
                stage="list",
                status_index=status_index,
                cursor=next_upstream,
            )
        elif status_index + 1 < len(DOUYIN_PRODUCT_STATUS_SEQUENCE):
            next_cursor = _encode_douyin_product_cursor(
                stage="list",
                status_index=status_index + 1,
            )
        else:
            # Freeze the gap set after every page/status. Each product enters
            # one bounded lookup batch, including newly observed empty rows.
            self._fallback_product_ids = self._products_with_sku_gaps()
            next_cursor = (
                _encode_douyin_product_cursor(stage="ids", offset=0)
                if self._fallback_product_ids
                else None
            )
        return parse_normalized_product_page(
            {
                "items": normalized_rows,
                "skippedCount": skipped_count,
                "hasMore": next_cursor is not None,
                "nextCursor": next_cursor,
            }
        )

    def _supplement_known_skus(self, rows: list[Any]) -> list[Any]:
        """Fill only missing already-known SKU identities from scoped SKU/get.

        A partial or conflicting reply fails the adapter before any current
        snapshot update. Cached proof avoids duplicate calls across list/ID
        pages, while the existing job-level duplicate guards remain intact.
        """
        result = []
        for record in rows:
            if not isinstance(record, Mapping):
                result.append(record)
                continue
            product = record.get("product")
            if not isinstance(product, Mapping):
                result.append(record)
                continue
            product_id = _optional_text(product.get("product_id"))
            known = self._known_products.get(product_id, set())
            if not known:
                result.append(record)
                continue
            cache = self._sku_lookup_cache.setdefault(product_id, {})
            available = []
            if isinstance(record.get("sku"), Mapping) and record["sku"].get("sku_id"):
                available.append(record["sku"])
            if isinstance(record.get("skus"), list):
                available.extend(row for row in record["skus"] if isinstance(row, Mapping))
            present = {_optional_text(row.get("sku_id")) for row in available}
            for row in available:
                sku_id = _optional_text(row.get("sku_id"))
                if sku_id in known:
                    if sku_id in cache and _canonical_sha256(cache[sku_id]) != _canonical_sha256(row):
                        raise ProductSyncPayloadError("Conflicting repeated known SKU metadata")
                    cache[sku_id] = row
            seen = (
                set() if product_id in self._products_with_empty_skus
                else self._seen_product_skus.get(product_id, set())
            )
            missing = sorted(known - present - seen)
            if not missing:
                result.append(record)
                continue
            if str(record.get("online_status")) not in DOUYIN_ONLINE_STATUS_MAP or any(
                not _optional_text(product.get(field)) or str(product.get(field)) == "0"
                for field in ("owner_account_id", "creator_account_id", "account_name")
            ):
                raise ProductSyncPayloadError("Known product lacks trusted status or ownership for SKU lookup")
            uncached = [sku_id for sku_id in missing if sku_id not in cache]
            for offset in range(0, len(uncached), 50):
                batch = uncached[offset:offset + 50]
                cache.update(self._fetch_sku_batch(product_id, product, batch))
            result.append({**record, "sku": {}, "skus": available + [cache[sku_id] for sku_id in missing]})
        return result

    def _fetch_sku_batch(
        self, product_id: str, product: Mapping[str, Any], batch: list[str]
    ) -> dict[str, Mapping[str, Any]]:
        found: dict[str, Mapping[str, Any]] = {}
        pending = list(batch)
        for attempt in range(1, PRODUCT_LOOKUP_ATTEMPTS + 1):
            self.lookup_stats["sku_requests"] += 1
            payload = self._client.query_product_skus(product_id, pending)
            data = _product_response_data(payload, "SKU")
            returned = data.get("skus")
            if not isinstance(returned, list):
                raise ProductSyncPayloadError("SKU response skus must be a list")
            by_id = {}
            for sku in returned:
                if not isinstance(sku, Mapping):
                    raise ProductSyncPayloadError("SKU lookup row must be an object")
                sku_id = _optional_text(sku.get("sku_id"))
                if sku_id not in pending or sku_id in by_id:
                    raise ProductSyncPayloadError("SKU lookup returned unexpected or duplicate identities")
                if (_optional_text(sku.get("product_id")) not in (None, product_id)
                    or any(_optional_text(sku.get(field)) not in (None, _optional_text(product.get(field)))
                           for field in ("owner_account_id", "creator_account_id"))):
                    raise ProductSyncPayloadError("SKU lookup product or owner identity conflicts")
                # SKU status has a separate enum; never infer online from a
                # deleted/unknown SKU, including under an inactive product.
                if type(sku.get("status")) is not int or sku["status"] != 1:
                    raise ProductSyncPayloadError("SKU lookup did not return an online variant")
                by_id[sku_id] = sku
            found.update(by_id)
            pending = [sku_id for sku_id in pending if sku_id not in by_id]
            if not pending:
                return found
            self.lookup_stats["partial_responses"] += 1
            logger.warning("Incomplete SKU lookup: attempt=%s missing_count=%s", attempt, len(pending))
        raise ProductSyncIncompleteError("SKU lookup incomplete after bounded retries; missing_count=" + str(len(pending)))

    def _fetch_product_batch(self, batch: list[str]) -> list[Any]:
        rows = []
        response_skus: dict[str, dict[str, Any]] = {}
        pending = list(batch)
        for attempt in range(1, PRODUCT_LOOKUP_ATTEMPTS + 1):
            self.lookup_stats["product_id_requests"] += 1
            payload = self._client.query_online_products_by_id(pending)
            data = _product_response_data(payload, "Product ID")
            returned = data.get("product_onlines")
            if not isinstance(returned, list):
                raise ProductSyncPayloadError("Product ID response product_onlines must be a list")
            returned_product_ids = set()
            for record in returned:
                product = record.get("product") if isinstance(record, Mapping) else None
                if not isinstance(product, Mapping) or _optional_text(product.get("product_id")) not in pending:
                    raise ProductSyncPayloadError("Product ID lookup returned an unexpected product")
                returned_product_ids.add(_optional_text(product.get("product_id")))
            normalized_rows, _ = _normalize_douyin_online_rows(returned)
            # A product envelope without any SKU is not complete. Known exact
            # SKU IDs can be recovered by SKU/get; unknown ones must retry the
            # product lookup until it actually supplies identities.
            found = {row.get("productId") for row in normalized_rows if row.get("skuId")}
            found.update(product_id for product_id in returned_product_ids if self._known_products.get(product_id))
            for row in normalized_rows:
                sku_id = row.get("skuId")
                self._validate_sku_identity(row, response_skus.get(sku_id) or self._observed_skus.get(sku_id))
                response_skus[sku_id] = row
            rows.extend(record for record in returned if _optional_text(record["product"].get("product_id")) in found)
            pending = [product_id for product_id in pending if product_id not in found]
            if not pending:
                return rows
            self.lookup_stats["partial_responses"] += 1
            logger.warning("Incomplete product ID lookup: attempt=%s missing_count=%s", attempt, len(pending))
        raise ProductSyncIncompleteError("Product ID lookup incomplete after bounded retries; missing_count=" + str(len(pending)))

    def _fetch_id_page(self, offset: int) -> ProductSyncPage:
        if self._fallback_product_ids is None:
            self._fallback_product_ids = self._products_with_sku_gaps()
        batch = self._fallback_product_ids[offset : offset + 10]
        if not batch:
            return parse_normalized_product_page(
                {"items": [], "hasMore": False, "nextCursor": None}
            )
        rows = self._fetch_product_batch(batch)
        normalized_rows, skipped_count = _normalize_douyin_online_rows(
            self._supplement_known_skus(rows)
        )
        previously_seen = {product_id: set(self._seen_product_skus.get(product_id, set())) for product_id in batch}
        self._observe_product_skus(normalized_rows)
        # Details may repeat list observations. Emit only new variants so a
        # later snapshot of an already seen SKU cannot conflict with that page.
        normalized_rows = [
            row for row in normalized_rows
            if row.get("skuId") not in previously_seen.get(row.get("productId"), set())
        ]
        next_offset = offset + len(batch)
        next_cursor = (
            _encode_douyin_product_cursor(stage="ids", offset=next_offset)
            if next_offset < len(self._fallback_product_ids)
            else None
        )
        return parse_normalized_product_page(
            {
                "items": normalized_rows,
                "skippedCount": skipped_count,
                "hasMore": next_cursor is not None,
                "nextCursor": next_cursor,
            }
        )


def parse_normalized_product_page(payload: Mapping[str, Any]) -> ProductSyncPage:
    if not isinstance(payload, Mapping):
        raise ProductSyncPayloadError("Product sync response must be an object")
    rows = payload.get("items")
    if not isinstance(rows, list):
        raise ProductSyncPayloadError("Product sync response items must be a list")
    has_more = payload.get("hasMore")
    if not isinstance(has_more, bool):
        raise ProductSyncPayloadError("Product sync response hasMore must be a boolean")
    skipped_count = payload.get("skippedCount", 0)
    if isinstance(skipped_count, bool) or not isinstance(skipped_count, int) or skipped_count < 0:
        raise ProductSyncPayloadError(
            "Product sync response skippedCount must be a non-negative integer"
        )
    next_cursor_value = payload.get("nextCursor")
    if next_cursor_value in (None, ""):
        next_cursor = None
    elif isinstance(next_cursor_value, (str, int)):
        next_cursor = str(next_cursor_value)
    else:
        raise ProductSyncPayloadError("Product sync response nextCursor must be a scalar")

    items: list[ProductSyncItem] = []
    invalid_items: list[tuple[int, str]] = []
    for row_index, row in enumerate(rows, start=1):
        if not isinstance(row, Mapping):
            invalid_items.append((row_index, "item must be an object"))
            continue
        sku_id = _optional_text(row.get("skuId"))
        if not sku_id:
            invalid_items.append((row_index, "skuId is required"))
            continue
        raw_payload = {
            key: row[key]
            for key in PRODUCT_RAW_PAYLOAD_FIELDS
            if key in row and _is_json_scalar(row[key])
        }
        status_value = (_optional_text(row.get("productStatus")) or "UNKNOWN").upper()
        normalized_status = status_value if status_value in PRODUCT_STATUSES else "UNKNOWN"
        payload_hash = _canonical_sha256(raw_payload)
        items.append(
            ProductSyncItem(
                sku_id=sku_id,
                sku_name=_optional_text(row.get("skuName")),
                product_id=_optional_text(row.get("productId")),
                product_name=_optional_text(row.get("productName")),
                spu_id=_optional_text(row.get("spuId")),
                creator_account_id=_optional_text(row.get("creatorAccountId")),
                creator_account_name=_optional_text(row.get("creatorAccountName")),
                owner_account_id=_optional_text(row.get("ownerAccountId")),
                owner_account_name=_optional_text(row.get("ownerAccountName")),
                product_status_raw=_optional_text(row.get("productStatusRaw")),
                product_status_normalized=normalized_status,
                product_updated_at=_optional_datetime(row.get("productUpdatedAt")),
                sync_status=(_optional_text(row.get("syncStatus")) or "SUCCESS").upper(),
                sync_error=_optional_text(row.get("syncError")),
                raw_payload=raw_payload,
                payload_sha256=payload_hash,
            )
        )
    page_fingerprint = {
        "itemPayloadHashes": [item.payload_sha256 for item in items],
        "invalidRows": invalid_items,
        "skippedCount": skipped_count,
        "hasMore": has_more,
        "nextCursor": next_cursor,
    }
    return ProductSyncPage(
        items=tuple(items),
        invalid_items=tuple(invalid_items),
        observed_count=len(rows) + skipped_count,
        has_more=has_more,
        next_cursor=next_cursor,
        payload_sha256=_canonical_sha256(page_fingerprint),
        skipped_count=skipped_count,
    )


def execute_product_sync(
    session: Session,
    *,
    job_id: str,
    adapter: ProductSyncAdapter,
    observed_at: datetime | None = None,
) -> ProductSyncResult:
    job = session.get(JobRun, job_id)
    if job is None or job.job_name != PRODUCT_SYNC_JOB_NAME:
        raise ValueError(f"Unknown product sync job: {job_id}")
    mode = str((job.metadata_json or {}).get("mode") or "").upper()
    if mode not in {"FULL", "INCREMENTAL"}:
        raise ValueError(f"Invalid product sync mode for {job_id}")

    other_running = session.scalar(
        select(JobRun)
        .where(
            JobRun.job_name == PRODUCT_SYNC_JOB_NAME,
            JobRun.status == "running",
            JobRun.job_id != job_id,
        )
        .limit(1)
    )
    if other_running is not None:
        return _finish_without_current_update(
            session,
            job,
            status="FAILED",
            error_code="CONCURRENT_RUN",
            error_message="Another product sync run is already running",
            retryable=True,
        )

    job.status = "running"
    job.finished_at = None
    session.flush()
    observed_time = observed_at or utcnow()
    cursor_setting = session.get(SyncSetting, PRODUCT_SYNC_CURSOR_SETTING_KEY)
    supports_persistent_cursor = bool(
        getattr(adapter, "supports_persistent_cursor", True)
    )
    current_cursor: str | None = (
        cursor_setting.setting_value if mode == "INCREMENTAL" and cursor_setting else None
    ) if supports_persistent_cursor else None
    checkpoint_cursor = current_cursor
    seen_page_hashes: set[str] = set()
    seen_items: dict[str, ProductSyncItem] = {}
    observed_count = 0
    invalid_count = 0
    skipped_count = 0
    page_count = 0
    error_code: str | None = None
    error_message: str | None = None

    while True:
        try:
            page = adapter.fetch_page(mode=mode, cursor=current_cursor)
        except ProductSyncPayloadError as exc:
            incomplete = isinstance(exc, ProductSyncIncompleteError)
            _record_quality_issue(
                session,
                job_id=job_id,
                issue_type="product_sync_incomplete_response" if incomplete else "product_sync_invalid_response",
                message=str(exc),
                sequence=page_count + 1,
            )
            return _finish_without_current_update(
                session,
                job,
                status="FAILED",
                observed_count=observed_count,
                skipped_count=skipped_count,
                failed_count=max(1, invalid_count),
                error_code="INCOMPLETE_RESPONSE" if incomplete else "INVALID_RESPONSE",
                error_message=str(exc),
                retryable=incomplete,
                next_cursor=current_cursor,
                page_count=page_count,
            )
        except Exception as exc:  # noqa: BLE001 - external adapter boundary.
            return _finish_without_current_update(
                session,
                job,
                status="FAILED",
                observed_count=observed_count,
                skipped_count=skipped_count,
                failed_count=max(1, invalid_count),
                error_code="UPSTREAM_ERROR",
                error_message=_sanitize_error_message(str(exc)),
                retryable=True,
                next_cursor=current_cursor,
                page_count=page_count,
            )
        finally:
            if hasattr(adapter, "lookup_stats"):
                job.metadata_json = {
                    **(job.metadata_json or {}),
                    "lookup_stats": dict(adapter.lookup_stats),
                }

        if page.payload_sha256 in seen_page_hashes:
            error_code = "DUPLICATE_PAGE"
            error_message = "Duplicate product page detected; current snapshot was not updated"
            _record_quality_issue(
                session,
                job_id=job_id,
                issue_type="product_sync_duplicate_page",
                message=error_message,
                sequence=page_count + 1,
            )
            invalid_count += 1
            break
        seen_page_hashes.add(page.payload_sha256)
        page_count += 1
        observed_count += page.observed_count
        skipped_count += page.skipped_count
        if page.skipped_count:
            _record_quality_issue(
                session,
                job_id=job_id,
                issue_type="product_sync_missing_sku_identity",
                message="Product rows omitted exact SKU identities; skipped_count=" + str(page.skipped_count),
                sequence=page_count,
            )

        for row_index, message in page.invalid_items:
            invalid_count += 1
            _record_quality_issue(
                session,
                job_id=job_id,
                issue_type="product_sync_invalid_item",
                message=f"Product page {page_count} row {row_index}: {message}",
                sequence=(page_count * 1_000_000) + row_index,
            )
        for item in page.items:
            existing = seen_items.get(item.sku_id)
            if existing is not None and existing.payload_sha256 != item.payload_sha256:
                invalid_count += 1
                error_code = "DUPLICATE_SKU"
                error_message = "Conflicting duplicate SKU observed; current snapshot was not updated"
                _record_quality_issue(
                    session,
                    job_id=job_id,
                    issue_type="product_sync_conflicting_sku",
                    message=f"Conflicting duplicate SKU: {item.sku_id}",
                    sequence=page_count,
                )
                continue
            seen_items.setdefault(item.sku_id, item)

        if page.has_more:
            if not page.next_cursor or page.next_cursor == current_cursor:
                error_code = "INVALID_CURSOR"
                error_message = "Product page requires a new next cursor; current snapshot was not updated"
                _record_quality_issue(
                    session,
                    job_id=job_id,
                    issue_type="product_sync_invalid_cursor",
                    message=error_message,
                    sequence=page_count,
                )
                invalid_count += 1
                break
            current_cursor = page.next_cursor
            checkpoint_cursor = current_cursor
            continue
        current_cursor = page.next_cursor
        if current_cursor is not None:
            checkpoint_cursor = current_cursor
        break

    _write_history_snapshots(
        session,
        job_id=job_id,
        items=seen_items.values(),
        observed_at=observed_time,
    )
    if invalid_count:
        return _finish_without_current_update(
            session,
            job,
            status="PARTIAL",
            observed_count=observed_count,
            skipped_count=skipped_count,
            failed_count=invalid_count,
            error_code=error_code or "INVALID_ITEM",
            error_message=error_message or "One or more product rows failed validation",
            retryable=True,
            next_cursor=current_cursor,
            page_count=page_count,
            snapshot_count=len(seen_items),
        )

    inserted_count, updated_count, unchanged_count = _update_current_snapshots(
        session,
        job_id=job_id,
        items=seen_items.values(),
        observed_at=observed_time,
    )
    metadata = dict(job.metadata_json or {})
    metadata.update(
        {
            "mode": mode,
            "observed_count": observed_count,
            "inserted_count": inserted_count,
            "updated_count": updated_count,
            "unchanged_count": unchanged_count,
            "skipped_count": skipped_count,
            "next_cursor_masked": _mask_cursor(current_cursor),
            "error_code": None,
            "retryable": False,
            "phase_counts": {
                "fetch": observed_count,
                "validate": max(0, observed_count - skipped_count),
                "snapshot": len(seen_items),
                "current": len(seen_items),
                "pages": page_count,
            },
        }
    )
    job.metadata_json = metadata
    job.status = "success"
    job.success_count = len(seen_items)
    job.failed_count = 0
    job.error_message = None
    job.finished_at = utcnow()
    if supports_persistent_cursor and checkpoint_cursor is not None:
        if cursor_setting is None:
            session.add(
                SyncSetting(
                    setting_key=PRODUCT_SYNC_CURSOR_SETTING_KEY,
                    setting_value=checkpoint_cursor,
                )
            )
        else:
            cursor_setting.setting_value = checkpoint_cursor
    elif not supports_persistent_cursor and cursor_setting is not None:
        session.delete(cursor_setting)
    session.flush()
    return ProductSyncResult(
        job_id=job_id,
        status="SUCCESS",
        observed_count=observed_count,
        inserted_count=inserted_count,
        updated_count=updated_count,
        unchanged_count=unchanged_count,
        skipped_count=skipped_count,
    )


def run_product_sync_job(
    *,
    job_id: str,
    adapter: ProductSyncAdapter | None = None,
    factory: sessionmaker | None = None,
) -> ProductSyncResult:
    session_factory = factory or get_session_factory()
    if session_factory is None:
        raise RuntimeError("Set DY_DATABASE_URL or DATABASE_URL before running product sync")
    with session_scope(session_factory) as session:
        # Keep the existing single execution transaction: its advisory lock
        # covers source scanning, adapter/network work and the final commit.
        # Other heavy claims cannot observe this uncommitted running row, so
        # both the shared lock and the durable running-slot fence are needed.
        if session.get_bind().dialect.name == "postgresql":
            acquired = session.scalar(select(func.pg_try_advisory_xact_lock(HEAVY_SYNC_CLAIM_LOCK_KEY)))
            if not acquired:
                return ProductSyncResult(job_id, "DEFERRED", error_code="HEAVY_SLOT_BUSY")
        job = session.get(JobRun, job_id)
        if job is None or job.job_name != PRODUCT_SYNC_JOB_NAME:
            raise ValueError(f"Unknown product sync job: {job_id}")
        if job.status != "queued":
            return ProductSyncResult(job_id, "DEFERRED", error_code="JOB_NOT_QUEUED")
        try:
            decision = current_resource_decision()
        except Exception:  # Resource evidence is required before any source work.
            return ProductSyncResult(job_id, "DEFERRED", error_code="RESOURCE_UNAVAILABLE")
        if getattr(decision, "action", None) is not ResourceAction.ALLOW:
            return ProductSyncResult(job_id, "DEFERRED", error_code="RESOURCE_NOT_ALLOW")
        if heavy_sync_rate_limit_cooldown_active(session):
            return ProductSyncResult(job_id, "DEFERRED", error_code="RATE_LIMIT_COOLDOWN")
        # Preserve the pre-existing same-product exclusion for legacy running
        # rows that were created before products joined the shared heavy slot.
        other_product = session.scalar(select(JobRun.job_id).where(
            JobRun.job_name == PRODUCT_SYNC_JOB_NAME,
            JobRun.status == "running", JobRun.job_id != job_id,
        ).limit(1))
        if other_product is not None:
            return ProductSyncResult(job_id, "DEFERRED", error_code="HEAVY_SLOT_BUSY")
        claimed = session.execute(update(JobRun).where(
            JobRun.job_id == job_id,
            JobRun.job_name == PRODUCT_SYNC_JOB_NAME,
            JobRun.status == "queued",
            no_other_running_heavy_job(),
        ).values(status="running", execution_slot="heavy_sync")
            .execution_options(synchronize_session=False))
        if claimed.rowcount != 1:
            return ProductSyncResult(job_id, "DEFERRED", error_code="HEAVY_SLOT_BUSY")
        session.refresh(job)
        active_adapter = adapter
        if active_adapter is None:
            try:
                from apps.worker.pipeline import build_douyin_client_from_env

                active_adapter = DouyinProductSyncAdapter(
                    build_douyin_client_from_env(),
                    known_products=extract_known_order_products(session),
                    page_size=_env_int(
                        "DOUYIN_PRODUCT_PAGE_SIZE", 50, minimum=1, maximum=50
                    ),
                    goods_query_type=_env_int(
                        "DOUYIN_PRODUCT_GOODS_QUERY_TYPE", 2, minimum=1, maximum=3
                    ),
                )
            except Exception as exc:  # noqa: BLE001 - runtime configuration boundary.
                job = session.get(JobRun, job_id)
                if job is None or job.job_name != PRODUCT_SYNC_JOB_NAME:
                    raise ValueError(f"Unknown product sync job: {job_id}") from exc
                return _finish_without_current_update(
                    session,
                    job,
                    status="FAILED",
                    error_code="INITIALIZATION_ERROR",
                    error_message=str(exc),
                    retryable=True,
                )
        return execute_product_sync(
            session,
            job_id=job_id,
            adapter=active_adapter,
        )


def extract_known_order_products(session: Session) -> dict[str, set[str]]:
    """Return exact catalog and order product/SKU pairs; reject contradictions."""

    products: dict[str, set[str]] = {}
    by_sku: dict[str, str] = {}

    def add_pair(product_id, sku_id):
        if not product_id or not sku_id:
            return
        if sku_id in by_sku and by_sku[sku_id] != product_id:
            raise ProductSyncPayloadError("Catalog and order SKU product identities conflict")
        by_sku[sku_id] = product_id
        products.setdefault(product_id, set()).add(sku_id)

    for product_id, sku_id in session.execute(select(DimSkuProductRule.product_id, DimSkuProductRule.sku_id)):
        add_pair(_optional_text(product_id), _optional_text(sku_id))
    payloads = session.scalars(
        select(RawDouyinOrder.raw_payload).execution_options(yield_per=500)
    )
    for payload in payloads:
        if not isinstance(payload, Mapping):
            continue
        rows = payload.get("products")
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            product_id = _optional_text(row.get("product_id"))
            sku_id = _optional_text(row.get("sku_id"))
            if product_id and sku_id:
                add_pair(product_id, sku_id)
    return products


def _write_history_snapshots(
    session: Session,
    *,
    job_id: str,
    items: Any,
    observed_at: datetime,
) -> None:
    for item in items:
        snapshot_id = "psh_" + sha256(
            f"{job_id}\x1f{item.sku_id}\x1f{item.payload_sha256}".encode("utf-8")
        ).hexdigest()[:48]
        exists = session.scalar(
            select(SkuProductSyncHistory.id).where(
                SkuProductSyncHistory.snapshot_id == snapshot_id
            )
        )
        if exists is not None:
            continue
        session.add(
            SkuProductSyncHistory(
                snapshot_id=snapshot_id,
                sync_run_id=job_id,
                sku_id=item.sku_id,
                sku_name=item.sku_name,
                product_id=item.product_id,
                product_name=item.product_name,
                spu_id=item.spu_id,
                creator_account_id=item.creator_account_id,
                creator_account_name=item.creator_account_name,
                owner_account_id=item.owner_account_id,
                owner_account_name=item.owner_account_name,
                product_status_raw=item.product_status_raw,
                product_status_normalized=item.product_status_normalized,
                product_updated_at=item.product_updated_at,
                sync_status=item.sync_status,
                sync_error=item.sync_error,
                payload_sha256=item.payload_sha256,
                observed_at=observed_at,
                raw_payload=item.raw_payload,
            )
        )
    session.flush()


def _update_current_snapshots(
    session: Session,
    *,
    job_id: str,
    items: Any,
    observed_at: datetime,
) -> tuple[int, int, int]:
    item_list = list(items)
    sku_ids = [item.sku_id for item in item_list]
    current_rows = {
        row.sku_id: row
        for row in session.scalars(
            select(DimSkuProductRule).where(DimSkuProductRule.sku_id.in_(sku_ids))
        )
    } if sku_ids else {}
    inserted_count = 0
    updated_count = 0
    unchanged_count = 0
    for item in item_list:
        row = current_rows.get(item.sku_id)
        if row is None:
            row = DimSkuProductRule(
                sku_id=item.sku_id,
                product_scope="",
                product_type="",
                is_service_product=False,
            )
            session.add(row)
            inserted_count += 1
        changed = False
        product_type = synced_product_type(row.product_scope, row.product_type)
        if row.product_type != product_type:
            row.product_type = product_type
            changed = True
        for model_field, item_field in PLATFORM_FIELD_MAP.items():
            incoming = getattr(item, item_field)
            if item.sync_status == "NOT_FOUND" and model_field in {
                "product_status_raw",
                "product_status_normalized",
            }:
                continue
            if incoming is None and model_field not in {"sync_error"}:
                continue
            if getattr(row, model_field) != incoming:
                setattr(row, model_field, incoming)
                changed = True
        if item.sync_status != "NOT_FOUND" and item.product_status_normalized != "UNKNOWN":
            is_active = item.product_status_normalized == "ACTIVE"
            if row.is_active_product != is_active:
                row.is_active_product = is_active
                changed = True
        row.sync_source = "douyin_product_api"
        row.sync_run_id = job_id
        if item.sync_status in {"SUCCESS", "MASKED"}:
            row.last_synced_at = observed_at
        if row.id is not None:
            if changed:
                updated_count += 1
            else:
                unchanged_count += 1
    session.flush()
    return inserted_count, updated_count, unchanged_count


def _finish_without_current_update(
    session: Session,
    job: JobRun,
    *,
    status: str,
    observed_count: int = 0,
    skipped_count: int = 0,
    failed_count: int = 1,
    error_code: str,
    error_message: str,
    retryable: bool,
    next_cursor: str | None = None,
    page_count: int = 0,
    snapshot_count: int = 0,
) -> ProductSyncResult:
    metadata = dict(job.metadata_json or {})
    metadata.update(
        {
            "observed_count": observed_count,
            "inserted_count": 0,
            "updated_count": 0,
            "unchanged_count": 0,
            "skipped_count": skipped_count,
            "next_cursor_masked": _mask_cursor(next_cursor),
            "error_code": error_code,
            "retryable": retryable,
            "phase_counts": {
                "fetch": observed_count,
                "validate": max(0, observed_count - failed_count - skipped_count),
                "snapshot": snapshot_count,
                "current": 0,
                "pages": page_count,
            },
        }
    )
    job.metadata_json = metadata
    job.status = status.lower()
    job.success_count = snapshot_count
    job.failed_count = failed_count
    job.error_message = _sanitize_error_message(error_message)
    job.finished_at = utcnow()
    session.flush()
    return ProductSyncResult(
        job_id=job.job_id,
        status=status,
        observed_count=observed_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        error_code=error_code,
    )


def _record_quality_issue(
    session: Session,
    *,
    job_id: str,
    issue_type: str,
    message: str,
    sequence: int,
) -> None:
    issue_id = "dqi_" + sha256(
        f"{job_id}\x1f{issue_type}\x1f{sequence}".encode("utf-8")
    ).hexdigest()[:48]
    if session.get(DataQualityIssue, issue_id) is not None:
        return
    session.add(
        DataQualityIssue(
            issue_id=issue_id,
            issue_type=issue_type,
            severity="warning",
            message=_sanitize_error_message(message),
            raw_context_json={"source": "product_sync"},
            source_run_id=job_id,
        )
    )


def product_sync_latest_success_at(session: Session, job_id: str) -> datetime | None:
    return session.scalar(
        select(func.max(DimSkuProductRule.last_synced_at)).where(
            DimSkuProductRule.sync_run_id == job_id
        )
    )


def _mask_cursor(cursor: str | None) -> str | None:
    if not cursor:
        return None
    return "sha256:" + sha256(cursor.encode("utf-8")).hexdigest()[:12]


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _optional_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _optional_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    if timestamp > 10_000_000_000:
        timestamp /= 1000
    try:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _required_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProductSyncPayloadError(f"{label} must be an object")
    return value


def _product_response_data(payload: Any, label: str) -> Mapping[str, Any]:
    payload = _required_mapping(payload, label + " response")
    data = _required_mapping(payload.get("data"), label + " response data")
    for container, field in ((payload, "error_code"), (data, "error_code"),
                             (payload.get("extra", {}), "error_code"),
                             (payload.get("BaseResp", {}), "StatusCode")):
        if isinstance(container, Mapping) and container.get(field) not in (None, 0, "0"):
            raise ProductSyncPayloadError(label + " lookup returned an upstream error code")
    return data


def _normalize_douyin_online_rows(rows: list[Any]) -> tuple[list[dict[str, Any]], int]:
    normalized: list[dict[str, Any]] = []
    skipped_count = 0
    for record in rows:
        if not isinstance(record, Mapping):
            normalized.append({})
            continue
        product = record.get("product")
        product = product if isinstance(product, Mapping) else {}
        sku_rows: list[Mapping[str, Any]] = []
        single_sku = record.get("sku")
        if isinstance(single_sku, Mapping) and single_sku and not _optional_text(single_sku.get("sku_id")):
            raise ProductSyncPayloadError("Inline SKU row requires an exact SKU identity")
        if isinstance(single_sku, Mapping) and single_sku.get("sku_id") not in (None, ""):
            sku_rows.append(single_sku)
        multiple_skus = record.get("skus")
        if isinstance(multiple_skus, list):
            if any(not isinstance(row, Mapping) or not _optional_text(row.get("sku_id")) for row in multiple_skus):
                raise ProductSyncPayloadError("Inline SKU row requires an exact SKU identity")
            sku_rows.extend(multiple_skus)
        deduplicated_skus: dict[str, Mapping[str, Any]] = {}
        for sku in sku_rows:
            sku_id = _optional_text(sku.get("sku_id"))
            if sku_id:
                if sku_id in deduplicated_skus and _canonical_sha256(deduplicated_skus[sku_id]) != _canonical_sha256(sku):
                    raise ProductSyncPayloadError("Conflicting duplicate inline SKU metadata")
                product_id = _optional_text(product.get("product_id"))
                if not product_id or _optional_text(sku.get("product_id")) not in (None, product_id):
                    raise ProductSyncPayloadError("Inline SKU product identity conflicts")
                if any(_optional_text(sku.get(field)) not in (None, _optional_text(product.get(field)))
                       for field in ("owner_account_id", "creator_account_id")):
                    raise ProductSyncPayloadError("Inline SKU ownership identity conflicts")
                deduplicated_skus.setdefault(sku_id, sku)
        if not deduplicated_skus:
            if _optional_text(product.get("product_id")):
                skipped_count += 1
                continue
            deduplicated_skus[""] = {}
        raw_status = _optional_text(record.get("online_status"))
        status = DOUYIN_ONLINE_STATUS_MAP.get(raw_status or "", "UNKNOWN")
        missing_fields = [
            name
            for name, value in (
                ("creator_account_id", product.get("creator_account_id")),
                ("owner_account_id", product.get("owner_account_id")),
                ("owner_account_name", product.get("account_name")),
            )
            if value in (None, "")
        ]
        sync_status = "MASKED" if missing_fields else "SUCCESS"
        sync_error = (
            "missing_" + ",".join(missing_fields) if missing_fields else None
        )
        for sku_id, sku in deduplicated_skus.items():
            normalized.append(
                {
                    "skuId": sku_id,
                    "skuName": sku.get("sku_name"),
                    "productId": product.get("product_id"),
                    "productName": product.get("product_name"),
                    "spuId": product.get("spu_id"),
                    "creatorAccountId": product.get("creator_account_id"),
                    "creatorAccountName": None,
                    "ownerAccountId": product.get("owner_account_id"),
                    "ownerAccountName": product.get("account_name"),
                    "productStatusRaw": raw_status,
                    "productStatus": status,
                    "productUpdatedAt": product.get("update_time"),
                    "syncStatus": sync_status,
                    "syncError": sync_error,
                }
            )
    return normalized, skipped_count


def _encode_douyin_product_cursor(**state: Any) -> str:
    raw = json.dumps(state, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return DOUYIN_PRODUCT_CURSOR_PREFIX + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_douyin_product_cursor(cursor: str | None) -> dict[str, Any]:
    if cursor in (None, ""):
        return {"stage": "list", "status_index": 0}
    if not str(cursor).startswith(DOUYIN_PRODUCT_CURSOR_PREFIX):
        raise ProductSyncPayloadError("Invalid product sync cursor")
    encoded = str(cursor)[len(DOUYIN_PRODUCT_CURSOR_PREFIX) :]
    try:
        padding = "=" * (-len(encoded) % 4)
        state = json.loads(base64.urlsafe_b64decode(encoded + padding).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProductSyncPayloadError("Invalid product sync cursor") from exc
    if not isinstance(state, dict) or state.get("stage") not in {"list", "ids"}:
        raise ProductSyncPayloadError("Invalid product sync cursor")
    return state


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value < minimum or value > maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
    return value


def _is_json_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _sanitize_error_message(message: str) -> str:
    lowered = message.lower()
    if any(token in lowered for token in ("cookie", "token", "secret", "password", "credential")):
        return "[redacted sensitive error]"
    return message[:1800]
