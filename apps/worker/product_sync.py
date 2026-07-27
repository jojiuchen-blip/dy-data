from __future__ import annotations

from collections.abc import Callable, Mapping
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

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
        self._page_size = page_size
        self._goods_query_type = goods_query_type
        self._seen_product_ids: set[str] = set()
        self._fallback_product_ids: list[str] | None = None

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
        payload = self._client.query_online_products(
            status=status,
            cursor=upstream_cursor,
            count=self._page_size,
            goods_query_type=self._goods_query_type,
        )
        data = _required_mapping(payload.get("data"), "Product list response data")
        rows = data.get("products")
        if not isinstance(rows, list):
            raise ProductSyncPayloadError("Product list response products must be a list")
        normalized_rows, skipped_count = _normalize_douyin_online_rows(rows)
        self._seen_product_ids.update(
            row["productId"] for row in normalized_rows if row.get("productId")
        )
        has_more = data.get("has_more")
        if not isinstance(has_more, bool):
            raise ProductSyncPayloadError("Product list response has_more must be a boolean")
        next_upstream = _optional_text(data.get("next_cursor"))
        if has_more:
            if not next_upstream or next_upstream == upstream_cursor:
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
            self._fallback_product_ids = sorted(
                set(self._known_products) - self._seen_product_ids
            )
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

    def _fetch_id_page(self, offset: int) -> ProductSyncPage:
        if self._fallback_product_ids is None:
            self._fallback_product_ids = sorted(
                set(self._known_products) - self._seen_product_ids
            )
        batch = self._fallback_product_ids[offset : offset + 10]
        if not batch:
            return parse_normalized_product_page(
                {"items": [], "hasMore": False, "nextCursor": None}
            )
        payload = self._client.query_online_products_by_id(batch)
        data = _required_mapping(payload.get("data"), "Product ID response data")
        rows = data.get("product_onlines")
        if not isinstance(rows, list):
            raise ProductSyncPayloadError(
                "Product ID response product_onlines must be a list"
            )
        normalized_rows, skipped_count = _normalize_douyin_online_rows(rows)
        returned_product_ids = {
            row["productId"] for row in normalized_rows if row.get("productId")
        }
        self._seen_product_ids.update(returned_product_ids)
        for product_id in batch:
            if product_id in returned_product_ids:
                continue
            for sku_id in sorted(self._known_products.get(product_id, set())):
                normalized_rows.append(
                    {
                        "skuId": sku_id,
                        "productId": product_id,
                        "productStatus": "UNKNOWN",
                        "syncStatus": "NOT_FOUND",
                        "syncError": "product_not_returned",
                    }
                )
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
            _record_quality_issue(
                session,
                job_id=job_id,
                issue_type="product_sync_invalid_response",
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
                error_code="INVALID_RESPONSE",
                error_message=str(exc),
                retryable=False,
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
    """Return the de-duplicated product/SKU pairs observed in order payloads."""

    products: dict[str, set[str]] = {}
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
                products.setdefault(product_id, set()).add(sku_id)
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
        if isinstance(single_sku, Mapping) and single_sku.get("sku_id") not in (None, ""):
            sku_rows.append(single_sku)
        multiple_skus = record.get("skus")
        if isinstance(multiple_skus, list):
            sku_rows.extend(row for row in multiple_skus if isinstance(row, Mapping))
        deduplicated_skus: dict[str, Mapping[str, Any]] = {}
        for sku in sku_rows:
            sku_id = _optional_text(sku.get("sku_id"))
            if sku_id:
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
