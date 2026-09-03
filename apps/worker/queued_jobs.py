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
from apps.api.dy_api.models import JobRun, utcnow
from apps.worker.pipeline import sanitize_error_message
from apps.worker.repositories import finish_job_run
from apps.worker.settlement_rebuild import refresh_active_settlement_lineage
from apps.worker.settlement import run_settlement_job


SETTLEMENT_REBUILD_JOB_NAME = "settlement_rebuild"
DEFAULT_FINANCE_DETECTION_STALE_AFTER = timedelta(minutes=5)
DEFAULT_FINANCE_DETECTION_MAX_ATTEMPTS = 3
DEFAULT_FINANCE_DETECTION_BATCH_SIZE = 25


@dataclass(frozen=True)
class QueuedSettlementRebuildResult:
    processed_job_id: str | None = None
    superseded_job_ids: tuple[str, ...] = ()


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


def process_queued_settlement_rebuilds(factory: sessionmaker) -> QueuedSettlementRebuildResult:
    selected_job_id: str | None = None
    superseded_job_ids: tuple[str, ...] = ()

    with session_scope(factory) as session:
        running = session.scalar(
            select(JobRun)
            .where(
                JobRun.job_name == SETTLEMENT_REBUILD_JOB_NAME,
                JobRun.status == "running",
            )
            .limit(1)
        )
        if running is not None:
            return QueuedSettlementRebuildResult()

        queued_jobs = list(
            session.scalars(
                select(JobRun)
                .where(
                    JobRun.job_name == SETTLEMENT_REBUILD_JOB_NAME,
                    JobRun.status == "queued",
                )
                .order_by(JobRun.started_at, JobRun.job_id)
            )
        )
        if not queued_jobs:
            return QueuedSettlementRebuildResult()

        selected = queued_jobs[-1]
        selected_job_id = selected.job_id
        superseded_job_ids = tuple(job.job_id for job in queued_jobs[:-1])

    assert selected_job_id is not None
    try:
        with session_scope(factory) as session:
            job = session.get(JobRun, selected_job_id)
            source_run_id = _source_run_id(job.metadata_json if job else None, fallback=selected_job_id)
            run_settlement_job(session, job_id=selected_job_id, source_run_id=source_run_id)
        refresh_active_settlement_lineage(factory, job_id=selected_job_id)
    except Exception as exc:
        with session_scope(factory) as session:
            if session.get(JobRun, selected_job_id) is not None:
                finish_job_run(
                    session,
                    selected_job_id,
                    status="failed",
                    failed_count=1,
                    error_message=sanitize_error_message(str(exc)),
                )
        raise

    if superseded_job_ids:
        with session_scope(factory) as session:
            for job_id in superseded_job_ids:
                job = session.get(JobRun, job_id)
                if job is None or job.status != "queued":
                    continue
                metadata = dict(job.metadata_json or {})
                metadata["superseded_by"] = selected_job_id
                job.status = "success"
                job.success_count = 0
                job.failed_count = 0
                job.error_message = None
                job.finished_at = utcnow()
                job.metadata_json = metadata
            session.flush()

    return QueuedSettlementRebuildResult(
        processed_job_id=selected_job_id,
        superseded_job_ids=superseded_job_ids,
    )


def _source_run_id(metadata: dict[str, Any] | None, *, fallback: str) -> str:
    value = (metadata or {}).get("source_run_id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback
