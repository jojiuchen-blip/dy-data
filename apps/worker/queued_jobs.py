from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import sessionmaker

from apps.api.dy_api.db import session_scope
from apps.api.dy_api.finance_dispute_detection import (
    FINANCE_DISPUTE_DETECTION_JOB_NAME,
    claim_finance_dispute_detection_job,
    fail_claimed_finance_dispute_detection_job,
    run_finance_dispute_detection_job,
)
from apps.api.dy_api.models import JobRun, SettlementProjectionActive, utcnow
from apps.worker.pipeline import sanitize_error_message
from apps.worker.settlement_rebuild import (
    SETTLEMENT_REBUILD_JOB_NAME,
    _database_utcnow,
    claim_latest_settlement_rebuild_job,
    reconcile_published_settlement_rebuild,
    run_settlement_rebuild_job,
)


DEFAULT_FINANCE_DETECTION_STALE_AFTER = timedelta(minutes=5)
DEFAULT_FINANCE_DETECTION_MAX_ATTEMPTS = 3
DEFAULT_FINANCE_DETECTION_BATCH_SIZE = 25
DEFAULT_SETTLEMENT_REBUILD_STALE_AFTER = timedelta(minutes=5)
DEFAULT_SETTLEMENT_REBUILD_MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class QueuedSettlementRebuildResult:
    processed_job_id: str | None = None
    superseded_job_ids: tuple[str, ...] = ()
    recovered_job_ids: tuple[str, ...] = ()
    failed_stale_job_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class QueuedFinanceDisputeDetectionResult:
    processed_job_ids: tuple[str, ...] = ()
    recovered_job_ids: tuple[str, ...] = ()
    failed_stale_job_ids: tuple[str, ...] = ()


def process_queued_finance_dispute_detections(
    factory: sessionmaker,
    *,
    now: datetime | None = None,
    stale_after: timedelta = DEFAULT_FINANCE_DETECTION_STALE_AFTER,
    max_attempts: int = DEFAULT_FINANCE_DETECTION_MAX_ATTEMPTS,
    max_jobs: int = DEFAULT_FINANCE_DETECTION_BATCH_SIZE,
) -> QueuedFinanceDisputeDetectionResult:
    """Recover and execute persisted detection jobs with atomic claims.

    Detection is read-only and never transitions the dispute, so a stale job
    can be safely retried. Every claim is committed before execution; another
    API or worker process can claim it only if its status is still ``queued``.
    """

    if stale_after <= timedelta(0):
        raise ValueError("stale_after must be greater than zero")
    if max_attempts <= 0:
        raise ValueError("max_attempts must be greater than zero")
    if max_jobs <= 0:
        raise ValueError("max_jobs must be greater than zero")
    current_time = _as_utc(now or utcnow())
    recovered_job_ids, failed_stale_job_ids = _recover_stale_finance_detections(
        factory,
        now=current_time,
        stale_after=stale_after,
        max_attempts=max_attempts,
    )
    processed_job_ids: list[str] = []
    for _ in range(max_jobs):
        claimed = _claim_next_finance_detection(factory, now=current_time)
        if claimed is None:
            break
        job_id, claim_id = claimed
        processed_job_ids.append(job_id)
        try:
            run_finance_dispute_detection_job(
                job_id=job_id,
                session_factory=factory,
                claim_id=claim_id,
            )
        except Exception as exc:
            _fail_claimed_finance_detection(
                factory,
                job_id=job_id,
                claim_id=claim_id,
                now=current_time,
                reason=sanitize_error_message(str(exc)),
            )
    return QueuedFinanceDisputeDetectionResult(
        processed_job_ids=tuple(processed_job_ids),
        recovered_job_ids=tuple(recovered_job_ids),
        failed_stale_job_ids=tuple(failed_stale_job_ids),
    )


def _claim_next_finance_detection(
    factory: sessionmaker,
    *,
    now: datetime,
) -> tuple[str, str] | None:
    with session_scope(factory) as session:
        candidate_ids = list(
            session.scalars(
                select(JobRun.job_id)
                .where(
                    JobRun.job_name == FINANCE_DISPUTE_DETECTION_JOB_NAME,
                    JobRun.status == "queued",
                )
                .order_by(JobRun.started_at, JobRun.job_id)
                .limit(10)
            )
        )
        for job_id in candidate_ids:
            claim_id = f"finance-detection-worker-{uuid4().hex}"
            if claim_finance_dispute_detection_job(
                session,
                job_id=job_id,
                claim_id=claim_id,
                claimed_at=now,
            ):
                return job_id, claim_id
    return None


def _recover_stale_finance_detections(
    factory: sessionmaker,
    *,
    now: datetime,
    stale_after: timedelta,
    max_attempts: int,
) -> tuple[list[str], list[str]]:
    recovered: list[str] = []
    failed: list[str] = []
    with session_scope(factory) as session:
        running_jobs = list(
            session.scalars(
                select(JobRun)
                .where(
                    JobRun.job_name == FINANCE_DISPUTE_DETECTION_JOB_NAME,
                    JobRun.status == "running",
                )
                .order_by(JobRun.started_at, JobRun.job_id)
            )
        )
        for job in running_jobs:
            metadata = dict(job.metadata_json or {})
            observed_state_updated_at = job.state_updated_at
            observed_lease_expires_at = job.lease_expires_at
            claimed_at = _metadata_datetime(metadata.get("claimedAt"))
            last_activity = (
                _as_utc(job.state_updated_at)
                if job.state_updated_at is not None
                else claimed_at or _as_utc(job.started_at)
            )
            if now - last_activity < stale_after:
                continue
            try:
                attempt_count = max(0, int(metadata.get("attemptCount") or 0))
            except (TypeError, ValueError):
                attempt_count = 0
            if attempt_count >= max_attempts:
                reason = "检测任务超过安全重试次数，请重新发起检测。"
                metadata.update(
                    {
                        "stage": "FAILED",
                        "failureReason": reason,
                        "recoveryState": "FAILED_ATTEMPTS_EXHAUSTED",
                    }
                )
                result = session.execute(
                    update(JobRun)
                    .where(
                        JobRun.job_id == job.job_id,
                        JobRun.status == "running",
                        JobRun.claim_token == job.claim_token,
                        (
                            JobRun.state_updated_at.is_(None)
                            if observed_state_updated_at is None
                            else JobRun.state_updated_at
                            == observed_state_updated_at
                        ),
                        (
                            JobRun.lease_expires_at.is_(None)
                            if observed_lease_expires_at is None
                            else JobRun.lease_expires_at
                            == observed_lease_expires_at
                        ),
                    )
                    .values(
                        status="failed",
                        success_count=0,
                        failed_count=1,
                        error_message=reason,
                        finished_at=now,
                        claim_token=None,
                        lease_expires_at=None,
                        state_updated_at=now,
                        metadata_json=metadata,
                    )
                    .execution_options(synchronize_session=False)
                )
                if result.rowcount == 1:
                    failed.append(job.job_id)
                continue
            metadata.update(
                {
                    "result": None,
                    "failureReason": None,
                    "claimId": None,
                    "claimedAt": None,
                    "stage": "RETRY_QUEUED",
                    "recoveryCount": int(metadata.get("recoveryCount") or 0)
                    + 1,
                    "recoveryState": "REQUEUED_STALE_CLAIM",
                }
            )
            result = session.execute(
                update(JobRun)
                .where(
                        JobRun.job_id == job.job_id,
                        JobRun.status == "running",
                        JobRun.claim_token == job.claim_token,
                        (
                            JobRun.state_updated_at.is_(None)
                            if observed_state_updated_at is None
                            else JobRun.state_updated_at
                            == observed_state_updated_at
                        ),
                        (
                            JobRun.lease_expires_at.is_(None)
                            if observed_lease_expires_at is None
                            else JobRun.lease_expires_at
                            == observed_lease_expires_at
                        ),
                    )
                .values(
                    status="queued",
                    success_count=0,
                    failed_count=0,
                    error_message=None,
                    finished_at=None,
                    claim_token=None,
                    lease_expires_at=None,
                    state_updated_at=now,
                    metadata_json=metadata,
                )
                .execution_options(synchronize_session=False)
            )
            if result.rowcount == 1:
                recovered.append(job.job_id)
    return recovered, failed


def _fail_claimed_finance_detection(
    factory: sessionmaker,
    *,
    job_id: str,
    claim_id: str,
    now: datetime,
    reason: str,
) -> None:
    controlled_reason = reason or "检测任务执行失败，请重试。"
    with session_scope(factory) as session:
        fail_claimed_finance_dispute_detection_job(
            session,
            job_id=job_id,
            claim_id=claim_id,
            failed_at=now,
            failure_reason=controlled_reason,
        )


def _metadata_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return _as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def process_queued_settlement_rebuilds(
    factory: sessionmaker,
    *,
    now: datetime | None = None,
    stale_after: timedelta = DEFAULT_SETTLEMENT_REBUILD_STALE_AFTER,
    max_attempts: int = DEFAULT_SETTLEMENT_REBUILD_MAX_ATTEMPTS,
) -> QueuedSettlementRebuildResult:
    if stale_after <= timedelta(0):
        raise ValueError("stale_after must be greater than zero")
    if max_attempts <= 0:
        raise ValueError("max_attempts must be greater than zero")
    with factory() as session:
        current_time = _as_utc(now) if now is not None else _database_utcnow(session)
    _release_due_settlement_retries(factory, now=current_time)
    recovered_job_ids, failed_stale_job_ids = _recover_stale_settlement_rebuilds(
        factory,
        now=current_time,
        stale_after=stale_after,
        max_attempts=max_attempts,
    )
    legacy_recovered_job_id = _recover_unpublished_successful_settlement_rebuild(
        factory,
        now=current_time,
    )
    if legacy_recovered_job_id is not None:
        recovered_job_ids.append(legacy_recovered_job_id)
    claimed = claim_latest_settlement_rebuild_job(factory)
    if claimed is None:
        return QueuedSettlementRebuildResult(
            recovered_job_ids=tuple(recovered_job_ids),
            failed_stale_job_ids=tuple(failed_stale_job_ids),
        )
    selected_job_id, claim_id, superseded_job_ids = claimed
    try:
        run_settlement_rebuild_job(
            job_id=selected_job_id, factory=factory, claim_id=claim_id,
        )
    except Exception:
        # Only contain failures durably handed to retry/recovery; a database
        # outage or an unexpected live owner must remain visible to the caller.
        with factory() as session:
            job = session.get(JobRun, selected_job_id)
            if job is None or (
                job.status == "running" and job.claim_token == claim_id
                and job.lease_expires_at is not None
                and _as_utc(job.lease_expires_at) > _database_utcnow(session)
            ):
                raise

    return QueuedSettlementRebuildResult(
        processed_job_id=selected_job_id,
        superseded_job_ids=superseded_job_ids,
        recovered_job_ids=tuple(recovered_job_ids),
        failed_stale_job_ids=tuple(failed_stale_job_ids),
    )


def _release_due_settlement_retries(factory: sessionmaker, *, now: datetime) -> None:
    with session_scope(factory) as session:
        session.execute(
            update(JobRun)
            .where(
                JobRun.job_name == SETTLEMENT_REBUILD_JOB_NAME,
                JobRun.status == "retry_wait",
                JobRun.next_retry_at <= now,
            )
            .values(status="queued", next_retry_at=None, state_updated_at=now)
        )


def _recover_stale_settlement_rebuilds(
    factory: sessionmaker,
    *,
    now: datetime,
    stale_after: timedelta,
    max_attempts: int,
) -> tuple[list[str], list[str]]:
    recovered: list[str] = []
    failed: list[str] = []
    with session_scope(factory) as session:
        running_jobs = list(
            session.scalars(
                select(JobRun)
                .where(
                    JobRun.job_name == SETTLEMENT_REBUILD_JOB_NAME,
                    JobRun.status == "running",
                )
                .order_by(JobRun.started_at, JobRun.job_id)
            )
        )
        for job in running_jobs:
            observed_claim_token = job.claim_token
            observed_state_updated_at = job.state_updated_at
            observed_lease_expires_at = job.lease_expires_at
            lease_expires_at = (
                _as_utc(job.lease_expires_at)
                if job.lease_expires_at is not None
                else None
            )
            activity_values = [
                _as_utc(value)
                for value in (job.heartbeat_at, job.state_updated_at, job.started_at)
                if value is not None
            ]
            last_activity = max(activity_values) if activity_values else now
            if lease_expires_at is not None:
                if lease_expires_at > now:
                    continue
            elif now - last_activity < stale_after:
                continue

            attempt_count = max(0, int(job.attempt_count or 0))
            job_max_attempts = max(
                1,
                min(max_attempts, int(job.max_attempts or max_attempts)),
            )
            metadata = dict(job.metadata_json or {})
            claim_condition = (
                JobRun.claim_token.is_(None)
                if observed_claim_token is None
                else JobRun.claim_token == observed_claim_token
            )
            state_condition = (
                JobRun.state_updated_at.is_(None)
                if observed_state_updated_at is None
                else JobRun.state_updated_at == observed_state_updated_at
            )
            lease_condition = (
                JobRun.lease_expires_at.is_(None)
                if observed_lease_expires_at is None
                else JobRun.lease_expires_at == observed_lease_expires_at
            )
            if reconcile_published_settlement_rebuild(
                session,
                job=job,
                reconciled_at=now,
            ):
                continue
            if attempt_count >= job_max_attempts:
                reason = "结算重建超过安全重试次数，请重新发布分佣规则。"
                metadata.update(
                    {
                        "stage": "FAILED",
                        "failureReason": reason,
                        "recoveryState": "FAILED_ATTEMPTS_EXHAUSTED",
                    }
                )
                result = session.execute(
                    update(JobRun)
                    .where(
                        JobRun.job_id == job.job_id,
                        JobRun.status == "running",
                        claim_condition,
                        state_condition,
                        lease_condition,
                    )
                    .values(
                        status="failed",
                        success_count=0,
                        failed_count=1,
                        error_message=reason,
                        finished_at=now,
                        claim_token=None,
                        lease_expires_at=None,
                        heartbeat_at=now,
                        state_updated_at=now,
                        lease_owner=None,
                        current_stage=None,
                        error_code="SETTLEMENT_REBUILD_ATTEMPTS_EXHAUSTED",
                        error_summary=reason,
                        metadata_json=metadata,
                    )
                    .execution_options(synchronize_session=False)
                )
                if result.rowcount == 1:
                    failed.append(job.job_id)
                continue

            metadata.update(
                {
                    "claimId": None,
                    "claimedAt": None,
                    "stage": "RETRY_QUEUED",
                    "recoveryCount": int(metadata.get("recoveryCount") or 0) + 1,
                    "recoveryState": "REQUEUED_STALE_CLAIM",
                }
            )
            result = session.execute(
                update(JobRun)
                .where(
                    JobRun.job_id == job.job_id,
                    JobRun.status == "running",
                    claim_condition,
                    state_condition,
                    lease_condition,
                )
                .values(
                    status="queued",
                    success_count=0,
                    failed_count=0,
                    error_message=None,
                    finished_at=None,
                    claim_token=None,
                    lease_expires_at=None,
                    heartbeat_at=None,
                    state_updated_at=now,
                    lease_owner=None,
                    current_stage=None,
                    progress_current=0,
                    progress_total=None,
                    rows_read=0,
                    rows_written=0,
                    error_code=None,
                    error_summary=None,
                    metadata_json=metadata,
                )
                .execution_options(synchronize_session=False)
            )
            if result.rowcount == 1:
                recovered.append(job.job_id)
    return recovered, failed


def _recover_unpublished_successful_settlement_rebuild(
    factory: sessionmaker,
    *,
    now: datetime,
) -> str | None:
    """Repair jobs completed by the old success-before-publication workflow."""

    valid_projection_statuses = {
        "published",
        "legacy_root",
        "no_affected_months",
        "superseded",
    }
    with session_scope(factory) as session:
        active_work = session.scalar(
            select(JobRun.job_id)
            .where(
                JobRun.job_name == SETTLEMENT_REBUILD_JOB_NAME,
                JobRun.status.in_(("queued", "running", "retry_wait")),
            )
            .limit(1)
        )
        if active_work is not None:
            return None

        statement = (
            select(JobRun)
            .where(
                JobRun.job_name == SETTLEMENT_REBUILD_JOB_NAME,
                JobRun.status.in_(("success", "succeeded")),
            )
            .order_by(
                JobRun.finished_at.desc(),
                JobRun.started_at.desc(),
                JobRun.job_id.desc(),
            )
            .limit(1)
        )
        if session.get_bind().dialect.name == "postgresql":
            statement = statement.with_for_update(skip_locked=True)
        job = session.scalar(statement)
        if job is None:
            return None
        metadata = dict(job.metadata_json or {})
        trigger = metadata.get("trigger")
        if not isinstance(trigger, str) or not trigger.startswith("admin_"):
            return None
        projection = metadata.get("settlement_projection")
        if (
            isinstance(projection, dict)
            and projection.get("status") in valid_projection_statuses
        ):
            return None
        if reconcile_published_settlement_rebuild(
            session,
            job=job,
            reconciled_at=now,
            recovery_state="RECONCILED_LEGACY_SUCCESS",
        ):
            return None

        active = session.get(SettlementProjectionActive, "settlement")
        if active is None or active.generation_id is None:
            return None

        observed_finished_at = job.finished_at
        observed_state_updated_at = job.state_updated_at
        metadata.update(
            {
                "stage": "RETRY_QUEUED",
                "claimId": None,
                "claimedAt": None,
                "recoveryState": "REQUEUED_UNPUBLISHED_SUCCESS",
                "recoveredAt": now.isoformat(),
            }
        )
        result = session.execute(
            update(JobRun)
            .where(
                JobRun.job_id == job.job_id,
                JobRun.status.in_(("success", "succeeded")),
                (
                    JobRun.finished_at.is_(None)
                    if observed_finished_at is None
                    else JobRun.finished_at == observed_finished_at
                ),
                (
                    JobRun.state_updated_at.is_(None)
                    if observed_state_updated_at is None
                    else JobRun.state_updated_at == observed_state_updated_at
                ),
            )
            .values(
                status="queued",
                success_count=0,
                failed_count=0,
                error_message=None,
                finished_at=None,
                claim_token=None,
                lease_expires_at=None,
                heartbeat_at=None,
                state_updated_at=now,
                attempt_count=0,
                lease_owner=None,
                current_stage=None,
                progress_current=0,
                progress_total=None,
                rows_read=0,
                rows_written=0,
                error_code=None,
                error_summary=None,
                metadata_json=metadata,
            )
            .execution_options(synchronize_session=False)
        )
        return job.job_id if result.rowcount == 1 else None
