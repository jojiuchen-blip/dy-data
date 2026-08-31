"""Deterministic Shanghai-day planning for the synchronization control plane."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from apps.api.dy_api.models import JobAttempt, JobRun, JobStageRun


SHANGHAI_TIMEZONE_NAME = "Asia/Shanghai"
SHANGHAI_TIMEZONE = ZoneInfo(SHANGHAI_TIMEZONE_NAME)
DEFAULT_DATA_SOURCE = "douyin"
DEFAULT_CONFIG_VERSION = "daily-sync-v3"
GLOBAL_DIMENSION_STAGE = "collect_dimensions"
FINALIZE_STAGE = "finalize"
READY_STATUSES = frozenset({"pending", "retry_wait"})
GLOBAL_DIMENSION_TARGETS = ("shop_pois", "aweme_bindings")
PARENT_ONLY_TARGETS = (*GLOBAL_DIMENSION_TARGETS, "backend_aweme_export")
ALL_DAILY_TARGETS = (
    "orders",
    "refunds",
    "clues",
    "verify_records",
    "clue_center",
    "settlement",
)
ALLOWED_SYNC_TARGETS = frozenset(
    {
        "all",
        "orders",
        "refunds",
        "clues",
        "verify_records",
        "shop_pois",
        "aweme_bindings",
        "backend_aweme_export",
        "settlement",
        "clue_center",
    }
)


@dataclass(frozen=True)
class ShanghaiDailyWindow:
    """One Shanghai business day represented as a half-open local-time window."""

    business_date: date
    start: datetime
    end: datetime
    timezone_name: str = SHANGHAI_TIMEZONE_NAME


@dataclass(frozen=True)
class PlannedDailyJob:
    """Read model for a durable daily child job."""

    job_id: str
    business_date: date
    status: str
    current_stage: str
    window: ShanghaiDailyWindow
    disposition: Literal["ready", "skipped", "blocked"]


@dataclass(frozen=True)
class DailySyncPlan:
    """Read model returned by every scheduler, backfill, and manual entry point."""

    parent_job_id: str
    parent_status: str
    target: str
    data_source: str
    config_version: str
    window_start: datetime
    window_end: datetime
    timezone_name: str
    daily_jobs: tuple[PlannedDailyJob, ...]
    global_stage_name: str | None
    global_stage_status: str | None
    finalize_job_id: str | None


def iter_shanghai_daily_windows(
    start: date | datetime | str,
    end: date | datetime | str,
) -> tuple[ShanghaiDailyWindow, ...]:
    """Return exact ``[00:00, next 00:00)`` windows in ``Asia/Shanghai``.

    Shanghai currently has no daylight-saving transitions. ``zoneinfo`` is still
    used so the business timezone remains explicit and local-midnight semantics
    are not replaced by fixed UTC arithmetic.
    """

    start_date = _business_boundary_date(start, field_name="start")
    end_date = _business_boundary_date(end, field_name="end")
    if end_date <= start_date:
        raise ValueError("daily range end must be after start")

    windows: list[ShanghaiDailyWindow] = []
    business_date = start_date
    while business_date < end_date:
        next_date = business_date + timedelta(days=1)
        windows.append(
            ShanghaiDailyWindow(
                business_date=business_date,
                start=datetime.combine(
                    business_date,
                    time.min,
                    tzinfo=SHANGHAI_TIMEZONE,
                ),
                end=datetime.combine(
                    next_date,
                    time.min,
                    tzinfo=SHANGHAI_TIMEZONE,
                ),
            )
        )
        business_date = next_date
    return tuple(windows)


def plan_daily_sync(
    session: Session,
    *,
    start: date | datetime | str,
    end: date | datetime | str,
    target: str,
    requested_by: str,
    trigger_source: str,
    data_source: str = DEFAULT_DATA_SOURCE,
    config_version: str = DEFAULT_CONFIG_VERSION,
) -> DailySyncPlan:
    """Plan one range atomically without taking ownership of the outer transaction.

    ``Session.begin_nested`` deliberately flushes caller-owned pending state before
    the savepoint. Any planning write or validation failure is then rolled back to
    that savepoint while the caller's transaction remains usable.
    """

    with session.begin_nested():
        return _plan_daily_sync(
            session,
            start=start,
            end=end,
            target=target,
            requested_by=requested_by,
            trigger_source=trigger_source,
            data_source=data_source,
            config_version=config_version,
        )


def _plan_daily_sync(
    session: Session,
    *,
    start: date | datetime | str,
    end: date | datetime | str,
    target: str,
    requested_by: str,
    trigger_source: str,
    data_source: str,
    config_version: str,
) -> DailySyncPlan:
    """Create or replay one deterministic parent and its daily children.

    The caller owns the short transaction. Inserts use native ``ON CONFLICT DO
    NOTHING`` on supported runtime databases, so a concurrent replay does not
    poison the caller's transaction with an ``IntegrityError``.
    """

    normalized_target = _required_identity_part(target, "target")
    if normalized_target not in ALLOWED_SYNC_TARGETS:
        raise ValueError(f"Unsupported daily sync target: {normalized_target}")
    normalized_source = _required_identity_part(data_source, "data_source")
    normalized_version = _required_identity_part(config_version, "config_version")
    normalized_actor = _required_identity_part(requested_by, "requested_by")
    normalized_trigger = _required_identity_part(trigger_source, "trigger_source")
    parent_targets, daily_targets = _partition_execution_targets(normalized_target)
    windows = iter_shanghai_daily_windows(start, end)
    range_start = windows[0].start
    range_end = windows[-1].end
    identity_hash = _identity_hash(
        {
            "kind": "range_sync",
            "timezone": SHANGHAI_TIMEZONE_NAME,
            "start": range_start.isoformat(),
            "end": range_end.isoformat(),
            "target": normalized_target,
            "data_source": normalized_source,
            "config_version": normalized_version,
        }
    )
    parent_job_id = f"range-sync-{identity_hash[:32]}"
    created_at = datetime.now(UTC)
    _insert_do_nothing(
        session,
        JobRun,
        {
            "job_id": parent_job_id,
            "job_name": "range_sync",
            "status": "pending",
            "started_at": created_at,
            "finished_at": None,
            "success_count": 0,
            "failed_count": 0,
            "error_message": None,
            "idempotency_key_hash": identity_hash,
            "metadata_json": {
                "planner_version": DEFAULT_CONFIG_VERSION,
                "target": normalized_target,
                "timezone": SHANGHAI_TIMEZONE_NAME,
                "requested_by": normalized_actor,
                "trigger_source": normalized_trigger,
                "parent_targets": list(parent_targets),
                "daily_targets": list(daily_targets),
            },
            "parent_job_id": None,
            "job_kind": "range_sync",
            "execution_slot": None,
            "business_date": None,
            "data_source": normalized_source,
            "config_version": normalized_version,
            "window_start": range_start,
            "window_end": range_end,
            "current_stage": None,
            "attempt_count": 0,
            "max_attempts": 3,
            "lease_epoch": 0,
        },
    )
    parent = session.get(JobRun, parent_job_id)
    if parent is None:
        raise RuntimeError("deterministic parent insert did not produce a readable job")
    _validate_parent_identity(
        parent,
        identity_hash=identity_hash,
        target=normalized_target,
        data_source=normalized_source,
        config_version=normalized_version,
        range_start=range_start,
        range_end=range_end,
        parent_targets=parent_targets,
        daily_targets=daily_targets,
    )

    global_stage = None
    if _requires_global_dimension_stage(normalized_target):
        global_stage = _ensure_parent_stage(
            session,
            parent_job_id=parent_job_id,
            stage_name=GLOBAL_DIMENSION_STAGE,
            checkpoint_json={
                "required_for_finalize": True,
                "parent_targets": list(parent_targets),
                "daily_targets": list(daily_targets),
            },
            created_at=created_at,
        )
        _ensure_parent_execution_job(
            session,
            parent_job_id=parent_job_id,
            target=normalized_target,
            parent_targets=parent_targets,
            daily_targets=daily_targets,
            data_source=normalized_source,
            config_version=normalized_version,
            window_start=range_start,
            window_end=range_end,
            created_at=created_at,
        )

    initial_stage = _initial_stage(normalized_target)
    required_stages = _required_stages(normalized_target)
    expected_children: dict[str, tuple[ShanghaiDailyWindow, str]] = {}
    child_windows = windows if daily_targets else ()
    for window in child_windows:
        child_job_id, child_identity_hash = _daily_child_identity(
            parent_job_id=parent_job_id,
            window=window,
            target=normalized_target,
            data_source=normalized_source,
            config_version=normalized_version,
        )
        expected_children[child_job_id] = (window, child_identity_hash)
        _insert_do_nothing(
            session,
            JobRun,
            {
                "job_id": child_job_id,
                "job_name": "date_sync",
                "status": "pending",
                "started_at": created_at,
                "finished_at": None,
                "success_count": 0,
                "failed_count": 0,
                "error_message": None,
                "idempotency_key_hash": child_identity_hash,
                "metadata_json": {
                    "target": normalized_target,
                    "parent_targets": list(parent_targets),
                    "daily_targets": list(daily_targets),
                    "required_stages": list(required_stages),
                    **_incremental_execution_modes(required_stages),
                    "timezone": SHANGHAI_TIMEZONE_NAME,
                    "source_window": {
                        "start": window.start.isoformat(),
                        "end": window.end.isoformat(),
                        "timezone": SHANGHAI_TIMEZONE_NAME,
                    },
                },
                "parent_job_id": parent_job_id,
                "job_kind": "date_sync",
                "execution_slot": "heavy_sync",
                "business_date": window.business_date,
                "data_source": normalized_source,
                "config_version": normalized_version,
                "window_start": window.start,
                "window_end": window.end,
                "current_stage": initial_stage,
                "attempt_count": 0,
                "max_attempts": 3,
                "lease_epoch": 0,
            },
        )

    session.flush()
    child_rows = list(
        session.scalars(
            select(JobRun)
            .where(
                JobRun.parent_job_id == parent_job_id,
                JobRun.job_kind == "date_sync",
            )
            .order_by(JobRun.business_date, JobRun.job_id)
        )
    )
    if len(child_rows) != len(expected_children):
        raise RuntimeError("deterministic daily plan is incomplete")
    if {row.job_id for row in child_rows} != set(expected_children):
        raise RuntimeError("deterministic daily plan contains an unexpected child")
    for row in child_rows:
        window, child_identity_hash = expected_children[row.job_id]
        _validate_child_identity(
            row,
            parent_job_id=parent_job_id,
            identity_hash=child_identity_hash,
            target=normalized_target,
            data_source=normalized_source,
            config_version=normalized_version,
            window=window,
            parent_targets=parent_targets,
            daily_targets=daily_targets,
            required_stages=required_stages,
        )
    daily_jobs = tuple(_planned_daily_job(row) for row in child_rows)
    finalize_job_id = session.scalar(
        select(JobRun.job_id).where(
            JobRun.parent_job_id == parent_job_id,
            JobRun.job_kind == "finalize",
        )
    )
    return DailySyncPlan(
        parent_job_id=parent.job_id,
        parent_status=parent.status,
        target=normalized_target,
        data_source=normalized_source,
        config_version=normalized_version,
        window_start=range_start,
        window_end=range_end,
        timezone_name=SHANGHAI_TIMEZONE_NAME,
        daily_jobs=daily_jobs,
        global_stage_name=global_stage.stage_name if global_stage is not None else None,
        global_stage_status=global_stage.status if global_stage is not None else None,
        finalize_job_id=finalize_job_id,
    )


def enqueue_finalize_if_ready(session: Session, parent_job_id: str) -> JobRun | None:
    """Enqueue finalize atomically without taking ownership of the outer transaction."""

    with session.begin_nested():
        return _enqueue_finalize_if_ready(session, parent_job_id)


def reconcile_finalize_queue(session: Session, *, limit: int = 100) -> int:
    """Boundedly recreate a missed enqueue after child completion committed."""

    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 400:
        raise ValueError("finalize reconcile limit must be between 1 and 400")
    parents = list(
        session.scalars(
            select(JobRun)
            .where(
                JobRun.job_kind == "range_sync",
                JobRun.status.notin_(("success", "failed", "cancelled")),
            )
            .order_by(JobRun.started_at, JobRun.job_id)
            .limit(limit)
        )
    )
    enqueued = 0
    for parent in parents:
        if (parent.metadata_json or {}).get("target") not in {"all", "settlement"}:
            continue
        try:
            if enqueue_finalize_if_ready(session, parent.job_id) is not None:
                enqueued += 1
        except RuntimeError:
            continue
    return enqueued


def reconcile_terminal_range_parents(session: Session, *, limit: int = 100) -> int:
    """Mark a finished range failed when every date is terminal and one failed."""

    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 400:
        raise ValueError("range parent reconcile limit must be between 1 and 400")
    statement = (
        select(JobRun)
        .where(
            JobRun.job_kind == "range_sync",
            JobRun.status.notin_(("success", "failed", "cancelled")),
        )
        .order_by(JobRun.started_at, JobRun.job_id)
        .limit(limit)
    )
    if session.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update(skip_locked=True)
    reconciled = 0
    terminal_statuses = {"success", "failed", "cancelled"}
    for parent in session.scalars(statement):
        children = _validated_daily_children_for_parent(session, parent)
        if not children or any(child.status not in terminal_statuses for child in children):
            continue
        failed_children = [child for child in children if child.status != "success"]
        if not failed_children:
            continue
        parent.status = "failed"
        parent.success_count = len(children) - len(failed_children)
        parent.failed_count = len(failed_children)
        parent.finished_at = max(
            (child.finished_at for child in children if child.finished_at is not None),
            default=datetime.now(UTC),
        )
        parent.error_code = "child_jobs_failed"
        parent.error_summary = (
            f"{len(failed_children)} of {len(children)} date_sync children failed"
        )
        parent.error_message = parent.error_summary
        reconciled += 1
    session.flush()
    return reconciled


def _enqueue_finalize_if_ready(
    session: Session,
    parent_job_id: str,
) -> JobRun | None:
    """Create one finalize job after the exact deterministic plan succeeds."""

    statement = select(JobRun).where(
        JobRun.job_id == parent_job_id,
        JobRun.job_kind == "range_sync",
    )
    if session.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    parent = session.scalar(statement)
    if parent is None:
        raise ValueError(f"Unknown range parent job: {parent_job_id}")

    parent_metadata = parent.metadata_json or {}
    target = parent_metadata.get("target")
    if target not in {"all", "settlement"}:
        return None

    children = _validated_daily_children_for_parent(session, parent)
    if any(child.status != "success" for child in children):
        return None
    required_parent_stage = _required_parent_stage_for_finalize(session, parent)
    if required_parent_stage is not None and required_parent_stage.status != "success":
        return None
    parent_stages = list(
        session.scalars(
            select(JobStageRun).where(
                JobStageRun.job_id == parent_job_id,
                JobStageRun.stage_name.notin_(
                    (FINALIZE_STAGE, GLOBAL_DIMENSION_STAGE)
                ),
            )
        )
    )
    for stage in parent_stages:
        checkpoint = stage.checkpoint_json or {}
        is_required = checkpoint.get("required_for_finalize", True) is not False
        if is_required and stage.status != "success":
            return None

    settle_stage_fences = _finalize_settle_stage_fences(session, children)

    finalize_hash = _identity_hash(
        {"kind": "finalize", "parent_job_id": parent_job_id}
    )
    finalize_job_id = f"finalize-{finalize_hash[:32]}"
    created_at = datetime.now(UTC)
    _insert_do_nothing(
        session,
        JobRun,
        {
            "job_id": finalize_job_id,
            "job_name": "finalize",
            "status": "pending",
            "started_at": created_at,
            "finished_at": None,
            "success_count": 0,
            "failed_count": 0,
            "error_message": None,
            "idempotency_key_hash": finalize_hash,
            "metadata_json": {
                "parent_job_id": parent_job_id,
                "target": target,
                "required_stages": [FINALIZE_STAGE],
                "settle_stage_fences": settle_stage_fences,
            },
            "parent_job_id": parent_job_id,
            "job_kind": "finalize",
            "execution_slot": "heavy_sync",
            "business_date": None,
            "data_source": parent.data_source,
            "config_version": parent.config_version,
            "window_start": parent.window_start,
            "window_end": parent.window_end,
            "current_stage": FINALIZE_STAGE,
            "attempt_count": 0,
            "max_attempts": 3,
            "lease_epoch": 0,
        },
    )
    session.flush()
    finalize_job = session.get(JobRun, finalize_job_id)
    if finalize_job is None:
        raise RuntimeError("finalize insert did not produce a readable job")
    _validate_finalize_identity(
        finalize_job,
        parent=parent,
        identity_hash=finalize_hash,
    )
    existing_metadata = finalize_job.metadata_json or {}
    expected_optional_metadata = {
        "target": target,
        "required_stages": [FINALIZE_STAGE],
        "settle_stage_fences": settle_stage_fences,
    }
    for key, expected_value in expected_optional_metadata.items():
        if key in existing_metadata and existing_metadata.get(key) != expected_value:
            raise RuntimeError("deterministic finalize job metadata is invalid")
    if finalize_job.status in {"failed", "cancelled"} or int(
        finalize_job.attempt_count or 0
    ) >= int(finalize_job.max_attempts or 3):
        raise RuntimeError("deterministic finalize job requires manual recovery")
    if finalize_job.status in {"pending", "retry_wait"}:
        now = datetime.now(UTC)
        lease_expires_at = finalize_job.lease_expires_at
        if lease_expires_at is not None and lease_expires_at.tzinfo is None:
            lease_expires_at = lease_expires_at.replace(tzinfo=UTC)
        unfinished_attempt = session.scalar(
            select(JobAttempt.attempt_id)
            .where(
                JobAttempt.job_id == finalize_job.job_id,
                JobAttempt.finished_at.is_(None),
            )
            .limit(1)
        )
        # Pending/retry rows may be legacy rows without the new metadata.  A
        # live lease is never rewritten here; the claim/reconciler owns it.
        if unfinished_attempt is not None or (
            lease_expires_at is not None and lease_expires_at > now
        ):
            return finalize_job
        finalize_job.metadata_json = {
            **(finalize_job.metadata_json or {}),
            "parent_job_id": parent_job_id,
            "target": target,
            "required_stages": [FINALIZE_STAGE],
            "settle_stage_fences": settle_stage_fences,
        }
    elif finalize_job.status == "running":
        return finalize_job
    elif finalize_job.status == "success":
        from apps.worker.finalize import verify_finalize_publication

        verify_finalize_publication(session, finalize_job.job_id)
        return finalize_job
    _ensure_parent_stage(
        session,
        parent_job_id=parent_job_id,
        stage_name=FINALIZE_STAGE,
        checkpoint_json={"required_for_finalize": False},
        created_at=created_at,
    )
    _ensure_parent_stage(
        session,
        parent_job_id=finalize_job_id,
        stage_name=FINALIZE_STAGE,
        checkpoint_json={},
        created_at=created_at,
    )
    session.flush()
    return finalize_job


def _finalize_settle_stage_fences(
    session: Session,
    children: list[JobRun],
) -> list[dict[str, object]]:
    fences: list[dict[str, object]] = []
    # FenceToken validates a canonical job-id order.  Daily children are loaded
    # in business-date order, which is intentionally independent of their
    # hashed job ids and can change when the planner contract version changes.
    for child in sorted(children, key=lambda item: item.job_id):
        metadata = child.metadata_json or {}
        required_stages = metadata.get("required_stages")
        if not isinstance(required_stages, list) or not required_stages:
            raise RuntimeError("daily child required_stages is invalid")
        stages = list(
            session.scalars(
                select(JobStageRun)
                .where(
                    JobStageRun.job_id == child.job_id,
                    JobStageRun.stage_name.in_(tuple(required_stages)),
                )
                .order_by(JobStageRun.stage_name)
            )
        )
        by_name = {stage.stage_name: stage for stage in stages}
        if set(by_name) != set(required_stages):
            raise RuntimeError("daily child required stage is missing")
        if any(
            stage.status != "success" or stage.committed_at is None
            for stage in stages
        ):
            raise RuntimeError("daily child required stage is not committed")
        settle = by_name.get("settle")
        if settle is None:
            raise RuntimeError("daily child settle stage is missing")
        checkpoint = settle.checkpoint_json
        if (
            not isinstance(checkpoint, dict)
            or not isinstance(checkpoint.get("settlement_summary"), dict)
            or not isinstance(checkpoint.get("store_score_snapshot"), dict)
        ):
            raise RuntimeError("daily child settle output is incomplete")
        committed_at = settle.committed_at
        assert committed_at is not None
        if committed_at.tzinfo is None:
            committed_at = committed_at.replace(tzinfo=UTC)
        fences.append(
            {
                "job_id": child.job_id,
                "stage_run_id": settle.stage_run_id,
                "lease_epoch": int(settle.lease_epoch or 0),
                "committed_at": committed_at.isoformat(),
                "status": settle.status,
            }
        )
    return fences


def _planned_daily_job(row: JobRun) -> PlannedDailyJob:
    if row.business_date is None or row.window_start is None or row.window_end is None:
        raise RuntimeError(f"date job has an incomplete window: {row.job_id}")
    current_stage = row.current_stage or "collect"
    if row.status == "success":
        disposition: Literal["ready", "skipped", "blocked"] = "skipped"
    elif row.status in READY_STATUSES:
        disposition = "ready"
    else:
        disposition = "blocked"
    return PlannedDailyJob(
        job_id=row.job_id,
        business_date=row.business_date,
        status=row.status,
        current_stage=current_stage,
        window=ShanghaiDailyWindow(
            business_date=row.business_date,
            start=_as_shanghai(row.window_start),
            end=_as_shanghai(row.window_end),
        ),
        disposition=disposition,
    )


def _ensure_parent_stage(
    session: Session,
    *,
    parent_job_id: str,
    stage_name: str,
    checkpoint_json: dict[str, object],
    created_at: datetime,
) -> JobStageRun:
    stage_run_id = _stage_run_id(parent_job_id, stage_name)
    _insert_do_nothing(
        session,
        JobStageRun,
        {
            "stage_run_id": stage_run_id,
            "job_id": parent_job_id,
            "stage_name": stage_name,
            "status": "pending",
            "checkpoint_json": checkpoint_json,
            "lease_epoch": 0,
            "started_at": None,
            "finished_at": None,
            "committed_at": None,
            "created_at": created_at,
            "updated_at": created_at,
        },
    )
    stage = session.get(JobStageRun, stage_run_id)
    if stage is None:
        raise RuntimeError("parent stage insert did not produce a readable checkpoint")
    _validate_parent_stage_identity(
        stage,
        stage_run_id=stage_run_id,
        parent_job_id=parent_job_id,
        stage_name=stage_name,
        checkpoint_json=checkpoint_json,
    )
    return stage


def _ensure_parent_execution_job(
    session: Session,
    *,
    parent_job_id: str,
    target: str,
    parent_targets: tuple[str, ...],
    daily_targets: tuple[str, ...],
    data_source: str,
    config_version: str,
    window_start: datetime,
    window_end: datetime,
    created_at: datetime,
) -> JobRun:
    """Create one fenced heavy-slot task for the range's parent work."""

    required_stages = parent_required_stages(target)
    identity_hash = _identity_hash(
        {
            "kind": "parent_sync",
            "parent_job_id": parent_job_id,
            "target": target,
            "parent_targets": list(parent_targets),
            "daily_targets": list(daily_targets),
            "required_stages": list(required_stages),
            "data_source": data_source,
            "config_version": config_version,
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
        }
    )
    parent_execution_id = f"parent-sync-{_identity_hash({'kind': 'parent_sync', 'parent_job_id': parent_job_id})[:32]}"
    _insert_do_nothing(
        session,
        JobRun,
        {
            "job_id": parent_execution_id,
            "job_name": "parent_sync",
            "status": "pending",
            "started_at": created_at,
            "finished_at": None,
            "success_count": 0,
            "failed_count": 0,
            "error_message": None,
            "idempotency_key_hash": identity_hash,
            "metadata_json": {
                "target": target,
                "parent_targets": list(parent_targets),
                "daily_targets": list(daily_targets),
                "required_stages": list(required_stages),
                **_incremental_execution_modes(required_stages),
                "timezone": SHANGHAI_TIMEZONE_NAME,
                "source_window": {
                    "start": window_start.isoformat(),
                    "end": window_end.isoformat(),
                    "timezone": SHANGHAI_TIMEZONE_NAME,
                },
            },
            "parent_job_id": parent_job_id,
            "job_kind": "parent_sync",
            "execution_slot": "heavy_sync",
            "business_date": None,
            "data_source": data_source,
            "config_version": config_version,
            "window_start": window_start,
            "window_end": window_end,
            "current_stage": GLOBAL_DIMENSION_STAGE,
            "attempt_count": 0,
            "max_attempts": 3,
            "lease_epoch": 0,
        },
    )
    execution_job = session.get(JobRun, parent_execution_id)
    if execution_job is None:
        raise RuntimeError("parent execution insert did not produce a readable job")
    _validate_parent_execution_identity(
        session,
        execution_job,
        parent_job_id=parent_job_id,
        target=target,
        parent_targets=parent_targets,
        daily_targets=daily_targets,
        required_stages=required_stages,
        identity_hash=identity_hash,
        data_source=data_source,
        config_version=config_version,
        window_start=window_start,
        window_end=window_end,
    )
    return execution_job


def _insert_do_nothing(
    session: Session,
    model: type[JobRun] | type[JobStageRun],
    values: dict[str, object],
) -> None:
    dialect_name = session.get_bind().dialect.name
    table = model.__table__
    if dialect_name == "postgresql":
        statement = postgresql_insert(table).values(**values).on_conflict_do_nothing()
    elif dialect_name == "sqlite":
        statement = sqlite_insert(table).values(**values).on_conflict_do_nothing()
    else:
        raise RuntimeError(
            "daily planning requires PostgreSQL or SQLite ON CONFLICT support"
        )
    session.execute(statement)


def _business_boundary_date(
    value: date | datetime | str,
    *,
    field_name: str,
) -> date:
    parsed: date | datetime
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        return value
    elif isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} is required")
        parsed = (
            date.fromisoformat(normalized)
            if len(normalized) == 10
            else datetime.fromisoformat(normalized)
        )
    else:
        raise TypeError(f"{field_name} must be a date, datetime, or ISO string")

    if isinstance(parsed, datetime):
        local = _as_shanghai(parsed)
        if local.timetz().replace(tzinfo=None) != time.min:
            raise ValueError(f"{field_name} must be aligned to Shanghai midnight")
        return local.date()
    return parsed


def _as_shanghai(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=SHANGHAI_TIMEZONE)
    return value.astimezone(SHANGHAI_TIMEZONE)


def _required_identity_part(value: str, field_name: str) -> str:
    normalized = " ".join(value.strip().split())
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _identity_hash(payload: dict[str, object]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _initial_stage(target: str) -> str:
    if target == "settlement":
        return "settle"
    if target == "clue_center":
        return "materialize"
    return "collect"


def _required_stages(target: str) -> tuple[str, ...]:
    if target == "settlement":
        return ("settle",)
    if target == "clue_center":
        return ("materialize",)
    return ("collect", "materialize", "settle")


def _incremental_execution_modes(required_stages: tuple[str, ...]) -> dict[str, str]:
    """Stamp bounded execution modes on every planner-created heavy job.

    The stage handlers intentionally preserve the legacy full-table behavior for
    pre-control-plane rows that do not carry an explicit rollout mode.  New
    deterministic plans must therefore opt in at creation time; otherwise a
    perfectly valid planned job silently selects the unbounded compatibility
    path.
    """

    modes: dict[str, str] = {}
    if "materialize" in required_stages:
        modes["clue_materialization_mode"] = "incremental"
    if "settle" in required_stages:
        modes["settlement_mode"] = "incremental"
    return modes


def parent_required_stages(target: str) -> tuple[str, ...]:
    """Return the durable stages required by one parent-only execution."""

    if target == "all":
        return (GLOBAL_DIMENSION_STAGE,)
    if target in {"shop_pois", "aweme_bindings"}:
        return (GLOBAL_DIMENSION_STAGE, "materialize", "settle")
    if target == "backend_aweme_export":
        return (GLOBAL_DIMENSION_STAGE, "settle")
    return (GLOBAL_DIMENSION_STAGE,)


def _requires_global_dimension_stage(target: str) -> bool:
    parent_targets, _ = _partition_execution_targets(target)
    return bool(parent_targets)


def _partition_execution_targets(target: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Separate no-date parent work from daily work for the future executor."""

    if target == "all":
        return GLOBAL_DIMENSION_TARGETS, ALL_DAILY_TARGETS
    if target in PARENT_ONLY_TARGETS:
        return (target,), ()
    return (), (target,)


def _stage_run_id(parent_job_id: str, stage_name: str) -> str:
    identity_hash = _identity_hash(
        {"job_id": parent_job_id, "stage": stage_name}
    )
    return f"stage-{identity_hash[:32]}"


def _daily_child_identity(
    *,
    parent_job_id: str,
    window: ShanghaiDailyWindow,
    target: str,
    data_source: str,
    config_version: str,
) -> tuple[str, str]:
    identity_hash = _identity_hash(
        {
            "kind": "date_sync",
            "parent_job_id": parent_job_id,
            "business_date": window.business_date.isoformat(),
            "target": target,
            "data_source": data_source,
            "config_version": config_version,
        }
    )
    return f"date-sync-{identity_hash[:32]}", identity_hash


def _validated_daily_children_for_parent(
    session: Session,
    parent: JobRun,
) -> tuple[JobRun, ...]:
    """Rebuild and validate the exact child set encoded by a range parent."""

    metadata = parent.metadata_json or {}
    target = metadata.get("target")
    data_source = parent.data_source
    config_version = parent.config_version
    if (
        not isinstance(target, str)
        or target not in ALLOWED_SYNC_TARGETS
        or not isinstance(data_source, str)
        or not data_source
        or not isinstance(config_version, str)
        or not config_version
        or parent.window_start is None
        or parent.window_end is None
    ):
        raise RuntimeError("range parent cannot define a deterministic daily plan")

    range_start = _as_shanghai(parent.window_start)
    range_end = _as_shanghai(parent.window_end)
    try:
        windows = iter_shanghai_daily_windows(range_start, range_end)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "range parent cannot define a deterministic daily plan"
        ) from exc
    parent_targets, daily_targets = _partition_execution_targets(target)
    parent_identity_hash = _identity_hash(
        {
            "kind": "range_sync",
            "timezone": SHANGHAI_TIMEZONE_NAME,
            "start": range_start.isoformat(),
            "end": range_end.isoformat(),
            "target": target,
            "data_source": data_source,
            "config_version": config_version,
        }
    )
    _validate_parent_identity(
        parent,
        identity_hash=parent_identity_hash,
        target=target,
        data_source=data_source,
        config_version=config_version,
        range_start=range_start,
        range_end=range_end,
        parent_targets=parent_targets,
        daily_targets=daily_targets,
    )

    expected_children: dict[str, tuple[ShanghaiDailyWindow, str]] = {}
    child_windows = windows if daily_targets else ()
    for window in child_windows:
        child_job_id, child_identity_hash = _daily_child_identity(
            parent_job_id=parent.job_id,
            window=window,
            target=target,
            data_source=data_source,
            config_version=config_version,
        )
        expected_children[child_job_id] = (window, child_identity_hash)
    children = tuple(
        session.scalars(
            select(JobRun)
            .where(
                JobRun.parent_job_id == parent.job_id,
                JobRun.job_kind == "date_sync",
            )
            .order_by(JobRun.business_date, JobRun.job_id)
        )
    )
    if len(children) != len(expected_children):
        raise RuntimeError("deterministic daily plan is incomplete")
    if {child.job_id for child in children} != set(expected_children):
        raise RuntimeError("deterministic daily plan contains an unexpected child")
    for child in children:
        window, child_identity_hash = expected_children[child.job_id]
        _validate_child_identity(
            child,
            parent_job_id=parent.job_id,
            identity_hash=child_identity_hash,
            target=target,
            data_source=data_source,
            config_version=config_version,
            window=window,
            parent_targets=parent_targets,
            daily_targets=daily_targets,
            required_stages=_required_stages(target),
        )
    return children


def _required_parent_stage_for_finalize(
    session: Session,
    parent: JobRun,
) -> JobStageRun | None:
    metadata = parent.metadata_json or {}
    target = metadata.get("target")
    if not isinstance(target, str) or target not in ALLOWED_SYNC_TARGETS:
        raise RuntimeError("range parent cannot define finalize prerequisites")
    parent_targets, daily_targets = _partition_execution_targets(target)
    if not parent_targets:
        return None

    stage_run_id = _stage_run_id(parent.job_id, GLOBAL_DIMENSION_STAGE)
    stage = session.get(JobStageRun, stage_run_id)
    if stage is None:
        raise RuntimeError("required parent stage is missing")
    _validate_parent_stage_identity(
        stage,
        stage_run_id=stage_run_id,
        parent_job_id=parent.job_id,
        stage_name=GLOBAL_DIMENSION_STAGE,
        checkpoint_json={
            "required_for_finalize": True,
            "parent_targets": list(parent_targets),
            "daily_targets": list(daily_targets),
        },
    )
    return stage


def _validate_parent_stage_identity(
    stage: JobStageRun,
    *,
    stage_run_id: str,
    parent_job_id: str,
    stage_name: str,
    checkpoint_json: dict[str, object],
) -> None:
    if (
        stage.stage_run_id != stage_run_id
        or stage.job_id != parent_job_id
        or stage.stage_name != stage_name
    ):
        raise RuntimeError("deterministic parent stage identity is invalid")
    checkpoint = stage.checkpoint_json
    if not isinstance(checkpoint, dict) or any(
        checkpoint.get(key) != expected_value
        for key, expected_value in checkpoint_json.items()
    ):
        raise RuntimeError("deterministic parent stage identity is invalid")


def _validate_finalize_identity(
    finalize_job: JobRun,
    *,
    parent: JobRun,
    identity_hash: str,
) -> None:
    metadata = finalize_job.metadata_json or {}
    actual = (
        finalize_job.job_id,
        finalize_job.parent_job_id,
        finalize_job.job_kind,
        finalize_job.job_name,
        finalize_job.idempotency_key_hash,
        metadata.get("parent_job_id"),
        finalize_job.business_date,
        finalize_job.data_source,
        finalize_job.config_version,
        _as_shanghai(finalize_job.window_start)
        if finalize_job.window_start
        else None,
        _as_shanghai(finalize_job.window_end) if finalize_job.window_end else None,
        finalize_job.current_stage,
        finalize_job.execution_slot,
    )
    expected = (
        f"finalize-{identity_hash[:32]}",
        parent.job_id,
        "finalize",
        "finalize",
        identity_hash,
        parent.job_id,
        None,
        parent.data_source,
        parent.config_version,
        _as_shanghai(parent.window_start) if parent.window_start else None,
        _as_shanghai(parent.window_end) if parent.window_end else None,
        FINALIZE_STAGE,
        "heavy_sync",
    )
    if actual != expected:
        raise RuntimeError("deterministic finalize job identity is invalid")


def _validate_parent_identity(
    parent: JobRun,
    *,
    identity_hash: str,
    target: str,
    data_source: str,
    config_version: str,
    range_start: datetime,
    range_end: datetime,
    parent_targets: tuple[str, ...],
    daily_targets: tuple[str, ...],
) -> None:
    metadata = parent.metadata_json or {}
    actual = (
        parent.job_kind,
        parent.idempotency_key_hash,
        metadata.get("target"),
        metadata.get("timezone"),
        metadata.get("parent_targets"),
        metadata.get("daily_targets"),
        parent.data_source,
        parent.config_version,
        _as_shanghai(parent.window_start) if parent.window_start else None,
        _as_shanghai(parent.window_end) if parent.window_end else None,
    )
    expected = (
        "range_sync",
        identity_hash,
        target,
        SHANGHAI_TIMEZONE_NAME,
        list(parent_targets),
        list(daily_targets),
        data_source,
        config_version,
        range_start,
        range_end,
    )
    if actual != expected:
        raise RuntimeError("deterministic parent identity collides with another request")


def _validate_parent_execution_identity(
    session: Session,
    execution: JobRun,
    *,
    parent_job_id: str,
    target: str,
    parent_targets: tuple[str, ...],
    daily_targets: tuple[str, ...],
    required_stages: tuple[str, ...],
    identity_hash: str,
    data_source: str,
    config_version: str,
    window_start: datetime,
    window_end: datetime,
) -> None:
    range_parent = session.get(JobRun, parent_job_id)
    metadata = execution.metadata_json or {}
    expected_modes = _incremental_execution_modes(required_stages)
    actual = (
        execution.parent_job_id,
        execution.job_kind,
        execution.job_name,
        execution.execution_slot,
        execution.idempotency_key_hash,
        execution.business_date,
        execution.data_source,
        execution.config_version,
        _as_shanghai(execution.window_start) if execution.window_start else None,
        _as_shanghai(execution.window_end) if execution.window_end else None,
        metadata.get("target"),
        metadata.get("parent_targets"),
        metadata.get("daily_targets"),
        metadata.get("required_stages"),
        metadata.get("clue_materialization_mode"),
        metadata.get("settlement_mode"),
        metadata.get("timezone"),
        metadata.get("source_window"),
    )
    expected = (
        parent_job_id,
        "parent_sync",
        "parent_sync",
        "heavy_sync",
        identity_hash,
        None,
        data_source,
        config_version,
        _as_shanghai(window_start),
        _as_shanghai(window_end),
        target,
        list(parent_targets),
        list(daily_targets),
        list(required_stages),
        expected_modes.get("clue_materialization_mode"),
        expected_modes.get("settlement_mode"),
        SHANGHAI_TIMEZONE_NAME,
        {
            "start": window_start.isoformat(),
            "end": window_end.isoformat(),
            "timezone": SHANGHAI_TIMEZONE_NAME,
        },
    )
    if range_parent is None or range_parent.job_kind != "range_sync" or actual != expected:
        raise RuntimeError("deterministic parent execution identity is invalid")


def validate_parent_sync_execution_identity(
    session: Session,
    execution: JobRun,
) -> bool:
    """Validate a parent-sync row against its deterministic range plan.

    Parent executions are themselves heavy-slot jobs.  They therefore need the
    same immutable identity checks as date children *before* a queue claim,
    otherwise a tampered pending parent could run once and only be rejected
    later when a date child tries to consume it.
    """

    try:
        if execution.job_kind != "parent_sync" or not execution.parent_job_id:
            return False
        range_parent = session.scalar(
            select(JobRun)
            .where(
                JobRun.job_id == execution.parent_job_id,
                JobRun.job_kind == "range_sync",
            )
            .with_for_update()
        )
        if range_parent is None:
            return False
        if (
            range_parent.job_name != "range_sync"
            or range_parent.parent_job_id is not None
            or range_parent.execution_slot is not None
            or range_parent.business_date is not None
        ):
            return False
        range_metadata = range_parent.metadata_json or {}
        if not isinstance(range_metadata, dict):
            return False
        target = range_metadata.get("target")
        data_source = range_parent.data_source
        config_version = range_parent.config_version
        if (
            not isinstance(target, str)
            or target not in ALLOWED_SYNC_TARGETS
            or not isinstance(data_source, str)
            or not data_source
            or not isinstance(config_version, str)
            or not config_version
            or range_parent.window_start is None
            or range_parent.window_end is None
        ):
            return False
        parent_targets, daily_targets = _partition_execution_targets(target)
        if not parent_targets:
            return False
        range_start = _as_shanghai(range_parent.window_start)
        range_end = _as_shanghai(range_parent.window_end)
        if (
            range_start >= range_end
            or range_start.time() != time.min
            or range_end.time() != time.min
        ):
            return False
        parent_identity_hash = _identity_hash(
            {
                "kind": "range_sync",
                "timezone": SHANGHAI_TIMEZONE_NAME,
                "start": range_start.isoformat(),
                "end": range_end.isoformat(),
                "target": target,
                "data_source": data_source,
                "config_version": config_version,
            }
        )
        _validate_parent_identity(
            range_parent,
            identity_hash=parent_identity_hash,
            target=target,
            data_source=data_source,
            config_version=config_version,
            range_start=range_start,
            range_end=range_end,
            parent_targets=parent_targets,
            daily_targets=daily_targets,
        )
        required_stages = parent_required_stages(target)
        execution_hash = _identity_hash(
            {
                "kind": "parent_sync",
                "parent_job_id": range_parent.job_id,
                "target": target,
                "parent_targets": list(parent_targets),
                "daily_targets": list(daily_targets),
                "required_stages": list(required_stages),
                "data_source": data_source,
                "config_version": config_version,
                "window_start": range_start.isoformat(),
                "window_end": range_end.isoformat(),
            }
        )
        expected_execution_id = (
            "parent-sync-"
            + _identity_hash(
                {"kind": "parent_sync", "parent_job_id": range_parent.job_id}
            )[:32]
        )
        if execution.job_id != expected_execution_id:
            return False
        _validate_parent_execution_identity(
            session,
            execution,
            parent_job_id=range_parent.job_id,
            target=target,
            parent_targets=parent_targets,
            daily_targets=daily_targets,
            required_stages=required_stages,
            identity_hash=execution_hash,
            data_source=data_source,
            config_version=config_version,
            window_start=range_start,
            window_end=range_end,
        )
        return True
    except (AttributeError, KeyError, TypeError, ValueError, RuntimeError):
        return False


def validate_parent_sync_child_identity(
    session: Session,
    child: JobRun,
) -> bool:
    """Validate one date child against its deterministic range/parent plan.

    The queue gate must not trust mutable child metadata to decide whether a
    parent is required.  Rebuild the expected identity from the range parent,
    then validate the unique successful parent execution and this child against
    that source of truth.  Malformed or incomplete rows fail closed.
    """

    try:
        if child.job_kind != "date_sync" or not child.parent_job_id:
            return False
        range_parent = session.scalar(
            select(JobRun)
            .where(
                JobRun.job_id == child.parent_job_id,
                JobRun.job_kind == "range_sync",
            )
            .with_for_update()
        )
        if range_parent is None:
            return False
        if (
            range_parent.job_name != "range_sync"
            or range_parent.parent_job_id is not None
            or range_parent.execution_slot is not None
            or range_parent.business_date is not None
        ):
            return False
        range_metadata = range_parent.metadata_json or {}
        if not isinstance(range_metadata, dict):
            return False
        target = range_metadata.get("target")
        data_source = range_parent.data_source
        config_version = range_parent.config_version
        if (
            not isinstance(target, str)
            or target not in ALLOWED_SYNC_TARGETS
            or not isinstance(data_source, str)
            or not data_source
            or not isinstance(config_version, str)
            or not config_version
            or range_parent.window_start is None
            or range_parent.window_end is None
        ):
            return False

        parent_targets, daily_targets = _partition_execution_targets(target)
        child_metadata = child.metadata_json or {}
        if not isinstance(child_metadata, dict) or child_metadata.get("target") != target:
            return False
        range_start = _as_shanghai(range_parent.window_start)
        range_end = _as_shanghai(range_parent.window_end)
        if (
            range_start >= range_end
            or range_start.time() != time.min
            or range_end.time() != time.min
        ):
            return False
        parent_identity_hash = _identity_hash(
            {
                "kind": "range_sync",
                "timezone": SHANGHAI_TIMEZONE_NAME,
                "start": range_start.isoformat(),
                "end": range_end.isoformat(),
                "target": target,
                "data_source": data_source,
                "config_version": config_version,
            }
        )
        _validate_parent_identity(
            range_parent,
            identity_hash=parent_identity_hash,
            target=target,
            data_source=data_source,
            config_version=config_version,
            range_start=range_start,
            range_end=range_end,
            parent_targets=parent_targets,
            daily_targets=daily_targets,
        )

        expected_child_start = datetime.combine(
            child.business_date,
            time.min,
            tzinfo=SHANGHAI_TIMEZONE,
        ) if child.business_date is not None else None
        expected_child_end = (
            expected_child_start + timedelta(days=1)
            if expected_child_start is not None
            else None
        )
        if (
            expected_child_start is None
            or expected_child_start < range_start
            or expected_child_end is None
            or expected_child_end > range_end
        ):
            return False
        expected_child_id, child_identity_hash = _daily_child_identity(
            parent_job_id=range_parent.job_id,
            window=ShanghaiDailyWindow(
                business_date=child.business_date,
                start=expected_child_start,
                end=expected_child_end,
            ),
            target=target,
            data_source=data_source,
            config_version=config_version,
        )
        if child.job_id != expected_child_id:
            return False

        if parent_targets:
            parent_executions = list(
                session.scalars(
                    select(JobRun)
                    .where(
                        JobRun.parent_job_id == range_parent.job_id,
                        JobRun.job_kind == "parent_sync",
                    )
                    .with_for_update()
                )
            )
            if len(parent_executions) != 1:
                return False
            parent_execution = parent_executions[0]
            if parent_execution.status != "success":
                return False
            parent_execution_hash = _identity_hash(
                {
                    "kind": "parent_sync",
                    "parent_job_id": range_parent.job_id,
                    "target": target,
                    "parent_targets": list(parent_targets),
                    "daily_targets": list(daily_targets),
                    "required_stages": list(parent_required_stages(target)),
                    "data_source": data_source,
                    "config_version": config_version,
                    "window_start": range_start.isoformat(),
                    "window_end": range_end.isoformat(),
                }
            )
            expected_parent_execution_id = (
                "parent-sync-"
                + _identity_hash(
                    {"kind": "parent_sync", "parent_job_id": range_parent.job_id}
                )[:32]
            )
            if parent_execution.job_id != expected_parent_execution_id:
                return False
            _validate_parent_execution_identity(
                session,
                parent_execution,
                parent_job_id=range_parent.job_id,
                target=target,
                parent_targets=parent_targets,
                daily_targets=daily_targets,
                required_stages=parent_required_stages(target),
                identity_hash=parent_execution_hash,
                data_source=data_source,
                config_version=config_version,
                window_start=range_start,
                window_end=range_end,
            )

        _validate_child_identity(
            child,
            parent_job_id=range_parent.job_id,
            identity_hash=child_identity_hash,
            target=target,
            data_source=data_source,
            config_version=config_version,
            window=ShanghaiDailyWindow(
                business_date=child.business_date,
                start=expected_child_start,
                end=expected_child_end,
            ),
            parent_targets=parent_targets,
            daily_targets=daily_targets,
            required_stages=_required_stages(target),
        )
        return True
    except (AttributeError, KeyError, TypeError, ValueError, RuntimeError):
        return False


def _validate_child_identity(
    child: JobRun,
    *,
    parent_job_id: str,
    identity_hash: str,
    target: str,
    data_source: str,
    config_version: str,
    window: ShanghaiDailyWindow,
    parent_targets: tuple[str, ...],
    daily_targets: tuple[str, ...],
    required_stages: tuple[str, ...],
) -> None:
    metadata = child.metadata_json or {}
    expected_modes = _incremental_execution_modes(required_stages)
    actual = (
        child.parent_job_id,
        child.job_kind,
        child.job_name,
        child.execution_slot,
        child.idempotency_key_hash,
        child.business_date,
        child.data_source,
        child.config_version,
        _as_shanghai(child.window_start) if child.window_start else None,
        _as_shanghai(child.window_end) if child.window_end else None,
        metadata.get("target"),
        metadata.get("parent_targets"),
        metadata.get("daily_targets"),
        metadata.get("required_stages"),
        metadata.get("clue_materialization_mode"),
        metadata.get("settlement_mode"),
        metadata.get("timezone"),
        metadata.get("source_window"),
    )
    expected = (
        parent_job_id,
        "date_sync",
        "date_sync",
        "heavy_sync",
        identity_hash,
        window.business_date,
        data_source,
        config_version,
        window.start,
        window.end,
        target,
        list(parent_targets),
        list(daily_targets),
        list(required_stages),
        expected_modes.get("clue_materialization_mode"),
        expected_modes.get("settlement_mode"),
        SHANGHAI_TIMEZONE_NAME,
        {
            "start": window.start.isoformat(),
            "end": window.end.isoformat(),
            "timezone": SHANGHAI_TIMEZONE_NAME,
        },
    )
    if actual != expected:
        raise RuntimeError(
            f"deterministic daily child identity is invalid: {child.job_id}"
        )
