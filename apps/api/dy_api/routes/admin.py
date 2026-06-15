from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status

from apps.worker.settlement import run_settlement_job
from dy_api.auth import get_current_admin
from dy_api.routes._data import get_data_store, generated_at
from dy_api.schemas import (
    SkuRuleBulkUpdateRequest,
    SkuRuleBulkUpdateResult,
    SkuRuleListData,
    dump_model,
)


router = APIRouter()


def _require_available_store(store):
    if not store.available:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is not available",
        )
    return store


@router.get("/sku-rules")
def list_sku_rules(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=500, ge=1, le=1000),
    q: str | None = None,
    _username: str = Depends(get_current_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    data = SkuRuleListData(
        **store.list_sku_rules(page=page, page_size=page_size, q=q)
    )
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.put("/sku-rules")
def update_sku_rules(
    payload: SkuRuleBulkUpdateRequest,
    _username: str = Depends(get_current_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    rules = [dump_model(rule) for rule in payload.rules]
    updated_count = store.upsert_sku_rules(rules)
    job_id = f"admin-sku-rules-{uuid4().hex[:12]}"
    stats = run_settlement_job(store.session, job_id=job_id, source_run_id=job_id)
    data = SkuRuleBulkUpdateResult(
        updated_count=updated_count,
        settlement_detail_count=stats.detail_count,
        settlement_monthly_count=stats.monthly_count,
        job_id=job_id,
    )
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }
