from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.db import get_session_factory, session_scope
from apps.api.dy_api.models import (
    DataQualityIssue,
    DimSkuProductRule,
    JobRun,
    SkuProductSyncHistory,
    SyncSetting,
    utcnow,
)


PRODUCT_SYNC_JOB_NAME = "product_sync"
PRODUCT_SYNC_CURSOR_SETTING_KEY = "product_sync.incremental_cursor"
PRODUCT_STATUSES = {"ACTIVE", "INACTIVE", "DELETED", "UNKNOWN"}
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


@dataclass(frozen=True)
class ProductSyncResult:
    job_id: str
    status: str
    observed_count: int = 0
    inserted_count: int = 0
    updated_count: int = 0
    unchanged_count: int = 0
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


def parse_normalized_product_page(payload: Mapping[str, Any]) -> ProductSyncPage:
    if not isinstance(payload, Mapping):
        raise ProductSyncPayloadError("Product sync response must be an object")
    rows = payload.get("items")
    if not isinstance(rows, list):
        raise ProductSyncPayloadError("Product sync response items must be a list")
    has_more = payload.get("hasMore")
    if not isinstance(has_more, bool):
        raise ProductSyncPayloadError("Product sync response hasMore must be a boolean")
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
                raw_payload=raw_payload,
                payload_sha256=payload_hash,
            )
        )
    page_fingerprint = {
        "itemPayloadHashes": [item.payload_sha256 for item in items],
        "invalidRows": invalid_items,
        "hasMore": has_more,
        "nextCursor": next_cursor,
    }
    return ProductSyncPage(
        items=tuple(items),
        invalid_items=tuple(invalid_items),
        observed_count=len(rows),
        has_more=has_more,
        next_cursor=next_cursor,
        payload_sha256=_canonical_sha256(page_fingerprint),
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
    current_cursor: str | None = (
        cursor_setting.setting_value if mode == "INCREMENTAL" and cursor_setting else None
    )
    checkpoint_cursor = current_cursor
    seen_page_hashes: set[str] = set()
    seen_items: dict[str, ProductSyncItem] = {}
    observed_count = 0
    invalid_count = 0
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
            "next_cursor_masked": _mask_cursor(current_cursor),
            "error_code": None,
            "retryable": False,
            "phase_counts": {
                "fetch": observed_count,
                "validate": observed_count,
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
    if checkpoint_cursor is not None:
        if cursor_setting is None:
            session.add(
                SyncSetting(
                    setting_key=PRODUCT_SYNC_CURSOR_SETTING_KEY,
                    setting_value=checkpoint_cursor,
                )
            )
        else:
            cursor_setting.setting_value = checkpoint_cursor
    session.flush()
    return ProductSyncResult(
        job_id=job_id,
        status="SUCCESS",
        observed_count=observed_count,
        inserted_count=inserted_count,
        updated_count=updated_count,
        unchanged_count=unchanged_count,
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
        return execute_product_sync(
            session,
            job_id=job_id,
            adapter=adapter or UnavailableProductSyncAdapter(),
        )


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
        else:
            changed = any(
                getattr(row, model_field) != getattr(item, item_field)
                for model_field, item_field in PLATFORM_FIELD_MAP.items()
            ) or row.is_active_product != (item.product_status_normalized == "ACTIVE")
            if changed:
                updated_count += 1
            else:
                unchanged_count += 1
        for model_field, item_field in PLATFORM_FIELD_MAP.items():
            setattr(row, model_field, getattr(item, item_field))
        row.is_active_product = item.product_status_normalized == "ACTIVE"
        row.sync_source = "douyin_product_api"
        row.sync_run_id = job_id
        row.last_synced_at = observed_at
    session.flush()
    return inserted_count, updated_count, unchanged_count


def _finish_without_current_update(
    session: Session,
    job: JobRun,
    *,
    status: str,
    observed_count: int = 0,
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
            "next_cursor_masked": _mask_cursor(next_cursor),
            "error_code": error_code,
            "retryable": retryable,
            "phase_counts": {
                "fetch": observed_count,
                "validate": max(0, observed_count - failed_count),
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


def _is_json_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _sanitize_error_message(message: str) -> str:
    lowered = message.lower()
    if any(token in lowered for token in ("cookie", "token", "secret", "password", "credential")):
        return "[redacted sensitive error]"
    return message[:1800]
