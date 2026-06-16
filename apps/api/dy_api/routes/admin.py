from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import text

from apps.worker.backfill import iter_backfill_windows, successful_window_keys
from apps.worker.collectors.types import CollectionWindow
from apps.worker.collectors.windows import resolve_collection_window
from apps.worker.manual_sync import run_manual_sync_job
from apps.worker.settlement import run_settlement_job
from apps.worker.sync_config import load_sync_config, save_sync_config
from dy_api.auth import get_current_admin
from dy_api.routes._data import get_data_store, generated_at
from dy_api.schemas import (
    ManualSyncRequest,
    ManualSyncResult,
    SkuRuleBulkUpdateRequest,
    SkuRuleBulkUpdateResult,
    SkuRuleListData,
    SyncAdminData,
    SyncConfigData,
    SyncConfigUpdate,
    SyncProgressData,
    SyncWindowData,
    dump_model,
)


router = APIRouter()
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


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


@router.get("/sync")
def get_sync_admin(
    _username: str = Depends(get_current_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    data = _sync_admin_data(store)
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.put("/sync/config")
def update_sync_config(
    payload: SyncConfigUpdate,
    _username: str = Depends(get_current_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    config = save_sync_config(store.session, dump_model(payload))
    data = SyncAdminData(
        config=SyncConfigData(**config.as_dict()),
        progress=_sync_progress(store.session, config.as_dict()),
        jobs=store.recent_jobs(20),
    )
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.post("/sync/run")
def run_sync_now(
    payload: ManualSyncRequest,
    background_tasks: BackgroundTasks,
    _username: str = Depends(get_current_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    start, end = _manual_window(payload)
    job_id = f"manual-{payload.target}-{uuid4().hex[:12]}"
    background_tasks.add_task(
        run_manual_sync_job,
        job_id=job_id,
        target=payload.target,
        start=start,
        end=end,
    )
    data = ManualSyncResult(
        job_id=job_id,
        target=payload.target,
        window=SyncWindowData(
            start=start.isoformat(),
            end=end.isoformat(),
            timezone="Asia/Shanghai",
        ),
    )
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


def _sync_admin_data(store) -> SyncAdminData:
    config = load_sync_config(store.session)
    return SyncAdminData(
        config=SyncConfigData(**config.as_dict()),
        progress=_sync_progress(store.session, config.as_dict()),
        jobs=store.recent_jobs(20),
    )


def _sync_progress(session, config: dict) -> SyncProgressData:
    history_end = config.get("history_end") or datetime.now(SHANGHAI_TZ).isoformat()
    source_window = resolve_collection_window(
        start=config.get("history_start"),
        end=history_end,
        timezone_name="Asia/Shanghai",
    )
    chunks = list(
        iter_backfill_windows(
            source_window,
            chunk_days=int(config.get("history_chunk_days") or 1),
        )
    )
    completed_keys = successful_window_keys(session)
    completed_chunks = [chunk for chunk in chunks if _window_key(chunk) in completed_keys]
    latest = max(completed_chunks, key=lambda chunk: chunk.end, default=None)
    recent_jobs = session.execute(
        text(
            """
            SELECT
                SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END) AS running_jobs,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_jobs
            FROM job_runs
            """
        )
    ).mappings().first()
    return SyncProgressData(
        total_windows=len(chunks),
        completed_windows=len(completed_chunks),
        running_jobs=int((recent_jobs or {}).get("running_jobs") or 0),
        failed_jobs=int((recent_jobs or {}).get("failed_jobs") or 0),
        latest_completed_window=(
            SyncWindowData(
                start=latest.start.isoformat(),
                end=latest.end.isoformat(),
                timezone=latest.timezone_name,
            )
            if latest
            else None
        ),
    )


def _manual_window(payload: ManualSyncRequest) -> tuple[datetime, datetime]:
    end = _coerce_datetime(payload.end) if payload.end else datetime.now(SHANGHAI_TZ)
    if payload.start:
        start = _coerce_datetime(payload.start)
    else:
        days = payload.days or 30
        start = (end - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    if end <= start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Sync end must be after start.",
        )
    return start, end


def _coerce_datetime(value: datetime) -> datetime:
    return value.astimezone(SHANGHAI_TZ) if value.tzinfo else value.replace(tzinfo=SHANGHAI_TZ)


def _window_key(window: CollectionWindow) -> tuple[str, str, str]:
    return (window.start.isoformat(), window.end.isoformat(), window.timezone_name)
