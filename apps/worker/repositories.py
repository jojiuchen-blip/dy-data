from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, TypeVar

from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    DataQualityIssue,
    DimAwemeAccount,
    DimSkuProductRule,
    DimStore,
    DimStorePoiMapping,
    JobRun,
    RawAwemeBinding,
    RawDouyinOrder,
    RawDouyinOrderCoupon,
    RawDouyinVerifyRecord,
    utcnow,
)

ModelT = TypeVar("ModelT")


def _merge(session: Session, model: type[ModelT], keys: Mapping[str, Any], values: Mapping[str, Any]) -> ModelT:
    payload = {**keys, **values}
    row = session.merge(model(**payload))
    session.flush()
    return row


def upsert_raw_order(session: Session, order_id: str, **values: Any) -> RawDouyinOrder:
    return _merge(session, RawDouyinOrder, {"order_id": order_id}, values)


def upsert_order_coupon(
    session: Session,
    coupon_id: str,
    order_id: str,
    **values: Any,
) -> RawDouyinOrderCoupon:
    return _merge(session, RawDouyinOrderCoupon, {"coupon_id": coupon_id, "order_id": order_id}, values)


def upsert_verify_record(session: Session, verify_id: str, **values: Any) -> RawDouyinVerifyRecord:
    return _merge(session, RawDouyinVerifyRecord, {"verify_id": verify_id}, values)


def upsert_aweme_binding(session: Session, binding_key: str, **values: Any) -> RawAwemeBinding:
    return _merge(session, RawAwemeBinding, {"binding_key": binding_key}, values)


def upsert_store(session: Session, store_id: str, store_name: str, **values: Any) -> DimStore:
    return _merge(session, DimStore, {"store_id": store_id, "store_name": store_name}, values)


def upsert_store_poi_mapping(
    session: Session,
    store_id: str,
    poi_id: str,
    **values: Any,
) -> DimStorePoiMapping:
    return _merge(session, DimStorePoiMapping, {"store_id": store_id, "poi_id": poi_id}, values)


def upsert_sku_product_rule(
    session: Session,
    sku_id: str,
    product_type: str,
    **values: Any,
) -> DimSkuProductRule:
    return _merge(session, DimSkuProductRule, {"sku_id": sku_id, "product_type": product_type}, values)


def upsert_aweme_account(session: Session, account_id: str, **values: Any) -> DimAwemeAccount:
    return _merge(session, DimAwemeAccount, {"account_id": account_id}, values)


def start_job_run(
    session: Session,
    job_id: str,
    job_name: str,
    *,
    metadata_json: dict[str, Any] | None = None,
    started_at: datetime | None = None,
) -> JobRun:
    return _merge(
        session,
        JobRun,
        {"job_id": job_id},
        {
            "job_name": job_name,
            "status": "running",
            "started_at": started_at or utcnow(),
            "finished_at": None,
            "success_count": 0,
            "failed_count": 0,
            "error_message": None,
            "metadata_json": metadata_json or {},
        },
    )


def finish_job_run(
    session: Session,
    job_id: str,
    *,
    status: str,
    success_count: int = 0,
    failed_count: int = 0,
    error_message: str | None = None,
    finished_at: datetime | None = None,
) -> JobRun:
    job = session.get(JobRun, job_id)
    if job is None:
        raise ValueError(f"Unknown job_id: {job_id}")
    job.status = status
    job.success_count = success_count
    job.failed_count = failed_count
    job.error_message = error_message
    job.finished_at = finished_at or utcnow()
    session.flush()
    return job


def upsert_data_quality_issue(
    session: Session,
    issue_id: str,
    *,
    issue_type: str,
    message: str,
    order_id: str | None = None,
    coupon_id: str | None = None,
    severity: str = "warning",
    raw_context_json: dict[str, Any] | None = None,
    source_run_id: str | None = None,
) -> DataQualityIssue:
    return _merge(
        session,
        DataQualityIssue,
        {"issue_id": issue_id},
        {
            "issue_type": issue_type,
            "order_id": order_id,
            "coupon_id": coupon_id,
            "severity": severity,
            "message": message,
            "raw_context_json": raw_context_json or {},
            "source_run_id": source_run_id,
        },
    )
