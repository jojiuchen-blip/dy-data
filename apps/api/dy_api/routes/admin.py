from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select, text

from apps.api.dy_api.models import JobRun
from apps.api.dy_api.db import get_session_factory, session_scope
from apps.worker.backfill import iter_backfill_windows, successful_window_keys
from apps.worker.collectors.types import CollectionWindow
from apps.worker.collectors.windows import resolve_collection_window
from apps.worker.clue_center import rebuild_clue_center
from apps.worker.manual_sync import run_manual_sync_job
from apps.worker.repositories import finish_job_run, queue_job_run
from apps.worker.settlement import run_settlement_job
from apps.worker.sync_config import load_sync_config, save_sync_config
from dy_api.auth import get_current_admin
from dy_api.routes._data import get_data_store, generated_at
from dy_api.schemas import (
    ManualSyncRequest,
    ManualSyncResult,
    ClueReassignRuleData,
    ClueReassignRuleUpdate,
    ClueRebuildResult,
    NonCommissionOwnerAccountBulkUpdateRequest,
    NonCommissionOwnerAccountBulkUpdateResult,
    NonCommissionOwnerAccountListData,
    SkuRuleBulkUpdateRequest,
    SkuRuleBulkUpdateResult,
    SkuRuleListData,
    SkuRuleLookupData,
    SkuRuleLookupRequest,
    SyncAdminData,
    SyncConfigData,
    SyncConfigUpdate,
    SyncProgressData,
    SyncScheduleData,
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


@router.post("/sku-rules/lookup")
def lookup_sku_rules(
    payload: SkuRuleLookupRequest,
    _username: str = Depends(get_current_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    data = SkuRuleLookupData(**store.lookup_sku_rules(payload.sku_ids))
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.put("/sku-rules")
def update_sku_rules(
    payload: SkuRuleBulkUpdateRequest,
    background_tasks: BackgroundTasks,
    _username: str = Depends(get_current_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    rules = [dump_model(rule) for rule in payload.rules]
    updated_count = store.upsert_sku_rules(rules)
    job_id = f"admin-sku-rules-{uuid4().hex[:12]}"
    queue_job_run(
        store.session,
        job_id,
        "settlement_rebuild",
        metadata_json={
            "source_run_id": job_id,
            "trigger": "admin_sku_rules",
            "updated_rule_count": updated_count,
        },
    )
    # Make the rules visible to the background rebuild before the request
    # dependency closes this session.
    store.session.commit()
    background_tasks.add_task(run_admin_sku_rule_rebuild_job, job_id=job_id)
    data = SkuRuleBulkUpdateResult(
        updated_count=updated_count,
        job_id=job_id,
        rebuild_status="queued",
    )
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.get("/non-commission-owner-accounts")
def list_non_commission_owner_accounts(
    _username: str = Depends(get_current_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    data = NonCommissionOwnerAccountListData(
        rows=store.list_non_commission_owner_accounts()
    )
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.put("/non-commission-owner-accounts")
def update_non_commission_owner_accounts(
    payload: NonCommissionOwnerAccountBulkUpdateRequest,
    background_tasks: BackgroundTasks,
    username: str = Depends(get_current_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    result = store.replace_non_commission_owner_accounts(
        [account.owner_account_name for account in payload.accounts],
        updated_by=username,
    )
    job_id = f"admin-non-commission-accounts-{uuid4().hex[:12]}"
    queue_job_run(
        store.session,
        job_id,
        "settlement_rebuild",
        metadata_json={
            "source_run_id": job_id,
            "trigger": "admin_non_commission_owner_accounts",
            "updated_rule_count": result["updated_count"],
        },
    )
    store.session.commit()
    background_tasks.add_task(run_admin_sku_rule_rebuild_job, job_id=job_id)
    data = NonCommissionOwnerAccountBulkUpdateResult(
        rows=result["rows"],
        updated_count=result["updated_count"],
        job_id=job_id,
        rebuild_status="queued",
    )
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.get("/clue-reassign-rule")
def get_clue_reassign_rule(
    _username: str = Depends(get_current_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    data = ClueReassignRuleData(**store.get_clue_reassign_rule())
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.put("/clue-reassign-rule")
def update_clue_reassign_rule(
    payload: ClueReassignRuleUpdate,
    username: str = Depends(get_current_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    data = ClueReassignRuleData(
        **store.save_clue_reassign_rule(
            reassign_sla_hours=payload.reassign_sla_hours,
            updated_by=username,
        )
    )
    store.session.commit()
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.post("/clues/rebuild")
def rebuild_clues(
    _username: str = Depends(get_current_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    stats = rebuild_clue_center(store.session)
    store.session.commit()
    data = ClueRebuildResult(
        rebuilt_order_count=stats.get("eligible_orders", 0),
        rebuilt_round_count=stats.get("assignment_rounds", 0),
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
    config_data = config.as_dict()
    data = SyncAdminData(
        config=SyncConfigData(**config_data),
        progress=_sync_progress(store.session, config_data),
        schedule=_sync_schedule(store.session, config_data),
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
    config_data = config.as_dict()
    return SyncAdminData(
        config=SyncConfigData(**config_data),
        progress=_sync_progress(store.session, config_data),
        schedule=_sync_schedule(store.session, config_data),
        jobs=store.recent_jobs(20),
    )


def _sync_schedule(session, config: dict) -> SyncScheduleData:
    latest_success = session.execute(
        select(JobRun.finished_at)
        .where(JobRun.job_name == "collect_and_settle")
        .where(JobRun.status == "success")
        .where(JobRun.finished_at.is_not(None))
        .order_by(JobRun.finished_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    auto_sync_enabled = bool(config.get("auto_sync_enabled", True))
    next_scheduled_at = None
    if auto_sync_enabled:
        interval_seconds = int(config.get("interval_seconds") or 86400)
        latest_success = _aware_utc(latest_success)
        next_scheduled_at = (
            latest_success + timedelta(seconds=interval_seconds)
            if latest_success is not None
            else datetime.now(timezone.utc)
        )
    return SyncScheduleData(
        auto_sync_enabled=auto_sync_enabled,
        latest_successful_sync_at=_aware_utc(latest_success),
        next_scheduled_sync_at=next_scheduled_at,
    )


def run_admin_sku_rule_rebuild_job(*, job_id: str) -> None:
    factory = get_session_factory()
    if factory is None:
        return
    with session_scope(factory) as session:
        try:
            run_settlement_job(session, job_id=job_id, source_run_id=job_id)
        except Exception as exc:
            try:
                finish_job_run(
                    session,
                    job_id,
                    status="failed",
                    failed_count=1,
                    error_message=str(exc),
                )
            except ValueError:
                pass
            raise


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


def _aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _window_key(window: CollectionWindow) -> tuple[str, str, str]:
    return (window.start.isoformat(), window.end.isoformat(), window.timezone_name)
