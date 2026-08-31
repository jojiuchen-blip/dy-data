"""Authoritative PostgreSQL lease state machine for daily synchronization jobs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import Enum
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from apps.worker import repositories


JOB_KINDS = frozenset(
    {"range_sync", "parent_sync", "date_sync", "finalize", "product_sync"}
)
JOB_STAGES = frozenset(
    {"collect", "collect_dimensions", "materialize", "settle", "finalize"}
)
JOB_STATUSES = frozenset(
    {
        "pending",
        "queued",
        "running",
        "retry_wait",
        "success",
        "partial",
        "failed",
        "cancelled",
    }
)
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_RETRY_BASE_DELAY_SECONDS = 30


class FailureKind(str, Enum):
    """Failure classifications used by the bounded retry policy."""

    TRANSIENT = "transient"
    BROWSER = "browser"
    DATA_INTEGRITY = "data_integrity"
    MEMORY_GUARD = "memory_guard"
    CRASHED = "crashed"


@dataclass(frozen=True)
class RetryDecision:
    """Describe the next durable state after a failed attempt."""

    status: str
    delay_seconds: int | None


@dataclass(frozen=True)
class LeaseToken:
    """Carry the owner and epoch required for every fenced mutation."""

    job_id: str
    attempt_id: str
    attempt_number: int
    lease_owner: str
    lease_epoch: int
    component_instance_id: str
    business_date: date | None
    current_stage: str


def retry_policy(
    failure_kind: FailureKind,
    *,
    attempt_number: int,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    previous_exit_type: str | None = None,
    base_delay_seconds: int = DEFAULT_RETRY_BASE_DELAY_SECONDS,
) -> RetryDecision:
    """Classify a failure into bounded exponential retry or terminal failure."""

    if attempt_number <= 0:
        raise ValueError("attempt_number must be positive")
    if max_attempts <= 0 or max_attempts > DEFAULT_MAX_ATTEMPTS:
        raise ValueError("max_attempts must be between 1 and 3")
    if base_delay_seconds <= 0:
        raise ValueError("base_delay_seconds must be positive")

    is_fatal = failure_kind is FailureKind.DATA_INTEGRITY
    if failure_kind is FailureKind.MEMORY_GUARD:
        is_fatal = previous_exit_type == "resource_guard"
    if attempt_number >= max_attempts:
        is_fatal = True
    if is_fatal:
        return RetryDecision(status="failed", delay_seconds=None)
    delay_seconds = base_delay_seconds * (2 ** (attempt_number - 1))
    return RetryDecision(status="retry_wait", delay_seconds=delay_seconds)


def advisory_lock_key(
    *,
    business_date: date,
    data_source: str,
    config_version: str,
) -> int:
    """Return the stable transaction-level advisory key for one business day."""

    return repositories.date_job_advisory_lock_key(
        business_date=business_date,
        data_source=data_source,
        config_version=config_version,
    )


def claim_next_job(
    session: Session,
    *,
    lease_owner: str,
    component_instance_id: str,
    lease_seconds: int,
) -> LeaseToken | None:
    """Claim the earliest executable heavy job without committing the transaction."""

    _validate_claim_inputs(
        lease_owner=lease_owner,
        component_instance_id=component_instance_id,
        lease_seconds=lease_seconds,
    )
    record = repositories.claim_next_heavy_job(
        session,
        lease_owner=lease_owner,
        component_instance_id=component_instance_id,
        lease_seconds=lease_seconds,
    )
    if record is None:
        return None
    return LeaseToken(
        job_id=record.job_id,
        attempt_id=record.attempt_id,
        attempt_number=record.attempt_number,
        lease_owner=record.lease_owner,
        lease_epoch=record.lease_epoch,
        component_instance_id=record.component_instance_id,
        business_date=record.business_date,
        current_stage=record.current_stage,
    )


def claim_job(
    session: Session,
    *,
    job_id: str,
    lease_owner: str,
    component_instance_id: str,
    lease_seconds: int,
) -> LeaseToken | None:
    """Claim one planned heavy job using the same fenced state machine.

    Production PostgreSQL uses the transaction advisory lock and row lock in
    ``repositories.claim_next_date_sync``.  SQLite remains available for unit
    tests with the same owner/epoch/attempt checks, but is not a production
    coordination backend.
    """

    _validate_claim_inputs(
        lease_owner=lease_owner,
        component_instance_id=component_instance_id,
        lease_seconds=lease_seconds,
    )
    if session.get_bind().dialect.name == "postgresql":
        record = repositories.claim_next_heavy_job(
            session,
            lease_owner=lease_owner,
            component_instance_id=component_instance_id,
            lease_seconds=lease_seconds,
            job_id=job_id,
        )
    else:
        record = _claim_job_sqlite(
            session,
            job_id=job_id,
            lease_owner=lease_owner,
            component_instance_id=component_instance_id,
            lease_seconds=lease_seconds,
        )
    if record is None:
        return None
    return LeaseToken(
        job_id=record.job_id,
        attempt_id=record.attempt_id,
        attempt_number=record.attempt_number,
        lease_owner=record.lease_owner,
        lease_epoch=record.lease_epoch,
        component_instance_id=record.component_instance_id,
        business_date=record.business_date,
        current_stage=record.current_stage,
    )


def _claim_job_sqlite(
    session: Session,
    *,
    job_id: str,
    lease_owner: str,
    component_instance_id: str,
    lease_seconds: int,
) -> repositories.ClaimedJobRecord | None:
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    from apps.api.dy_api.models import ComponentHeartbeat, JobAttempt, JobRun, JobStageRun

    job = session.get(JobRun, job_id)
    if (
        job is None
        or job.job_kind not in {"date_sync", "parent_sync", "finalize"}
        or job.execution_slot != "heavy_sync"
    ):
        return None
    if not repositories.parent_sync_gate_allows_claim(session, job):
        return None
    if job.status not in {"pending", "retry_wait"}:
        return None
    now = datetime.now(UTC)
    attempt_number = int(job.attempt_count or 0) + 1
    max_attempts = int(job.max_attempts or DEFAULT_MAX_ATTEMPTS)
    if attempt_number > max_attempts:
        return None
    lease_epoch = int(job.lease_epoch or 0) + 1
    attempt_id = f"attempt-{uuid4()}"
    component = session.get(ComponentHeartbeat, component_instance_id)
    if component is None:
        component = ComponentHeartbeat(
            component_instance_id=component_instance_id,
            component_type="worker",
            status="healthy",
            started_at=now,
            last_heartbeat_at=now,
            activity_json={},
            queue_summary_json={},
            created_at=now,
            updated_at=now,
        )
        session.add(component)
        session.flush()
    stage_name = job.current_stage or (
        "collect_dimensions"
        if job.job_kind == "parent_sync"
        else ("finalize" if job.job_kind == "finalize" else "collect")
    )
    stage = session.scalar(
        select(JobStageRun).where(
            JobStageRun.job_id == job_id,
            JobStageRun.stage_name == stage_name,
        )
    )
    if stage is None:
        stage = JobStageRun(
            stage_run_id=f"stage-{job_id}-{stage_name}",
            job_id=job_id,
            stage_name=stage_name,
            status="running",
            checkpoint_json={},
            lease_epoch=lease_epoch,
            started_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(stage)
        session.flush()
    attempt = JobAttempt(
        attempt_id=attempt_id,
        job_id=job_id,
        stage_run_id=stage.stage_run_id,
        attempt_number=attempt_number,
        lease_epoch=lease_epoch,
        component_type="worker",
        component_instance_id=component_instance_id,
        started_at=now,
        created_at=now,
    )
    session.add(attempt)
    job.status = "running"
    job.attempt_count = attempt_number
    job.lease_owner = lease_owner
    job.lease_epoch = lease_epoch
    job.lease_expires_at = now + timedelta(seconds=lease_seconds)
    job.heartbeat_at = now
    job.next_retry_at = None
    job.current_stage = stage_name
    component.current_job_id = job_id
    component.current_attempt_id = attempt_id
    component.last_heartbeat_at = now
    component.updated_at = now
    session.flush()
    return repositories.ClaimedJobRecord(
        job_id=job_id,
        attempt_id=attempt_id,
        attempt_number=attempt_number,
        lease_owner=lease_owner,
        lease_epoch=lease_epoch,
        component_instance_id=component_instance_id,
        business_date=job.business_date,
        current_stage=stage_name,
    )


def heartbeat_job(session: Session, token: LeaseToken, *, lease_seconds: int) -> bool:
    """Renew a lease only when owner, epoch, status, and expiry remain valid."""

    if lease_seconds <= 0:
        raise ValueError("lease_seconds must be positive")
    return repositories.heartbeat_claim(
        session,
        job_id=token.job_id,
        lease_owner=token.lease_owner,
        lease_epoch=token.lease_epoch,
        attempt_id=token.attempt_id,
        component_instance_id=token.component_instance_id,
        lease_seconds=lease_seconds,
    )


def record_attempt_observation(
    session: Session,
    token: LeaseToken,
    *,
    exit_code: int | None,
    rss_peak_bytes: int | None,
    error_code: str | None = None,
    error_summary: str | None = None,
) -> bool:
    """Persist child exit/RSS evidence without closing the active attempt.

    The supervisor calls this immediately before ``complete_job`` or
    ``fail_job`` in the same control transaction.  Keeping the attempt open
    until the final state-machine mutation lets the T1.2 API atomically finish
    the attempt, release the component binding, and append its audit event.
    """

    if rss_peak_bytes is not None and rss_peak_bytes < 0:
        raise ValueError("rss_peak_bytes cannot be negative")
    if session.get_bind().dialect.name == "postgresql":
        if repositories.lock_active_execution_state(
            session,
            job_id=token.job_id,
            lease_owner=token.lease_owner,
            lease_epoch=token.lease_epoch,
            attempt_id=token.attempt_id,
            component_instance_id=token.component_instance_id,
        ) is None:
            return False
        result = session.execute(
            update(repositories.JobAttempt)
            .where(
                repositories.JobAttempt.job_id == token.job_id,
                repositories.JobAttempt.attempt_id == token.attempt_id,
                repositories.JobAttempt.lease_epoch == token.lease_epoch,
                repositories.JobAttempt.finished_at.is_(None),
            )
            .values(
                exit_code=exit_code,
                rss_peak_bytes=rss_peak_bytes,
                error_code=error_code,
                error_summary=error_summary,
            )
        )
        return result.rowcount == 1
    return _record_attempt_observation_sqlite(
        session,
        token,
        exit_code=exit_code,
        rss_peak_bytes=rss_peak_bytes,
        error_code=error_code,
        error_summary=error_summary,
    )


def complete_job(
    session: Session,
    token: LeaseToken,
    *,
    success_count: int = 0,
) -> bool:
    """Complete a valid lease and its attempt in the caller's transaction."""

    if success_count < 0:
        raise ValueError("success_count cannot be negative")
    from apps.api.dy_api.models import JobRun

    job = session.get(JobRun, token.job_id)
    finalize_parent_id = None
    date_parent_id = None
    if job is not None and job.job_kind == "finalize":
        from apps.worker.finalize import verify_finalize_publication

        verify_finalize_publication(session, job.job_id)
        finalize_parent_id = job.parent_job_id
    elif job is not None and job.job_kind == "date_sync":
        date_parent_id = job.parent_job_id
    if session.get_bind().dialect.name == "postgresql":
        completed = repositories.complete_claim(
            session,
            job_id=token.job_id,
            lease_owner=token.lease_owner,
            lease_epoch=token.lease_epoch,
            attempt_id=token.attempt_id,
            component_instance_id=token.component_instance_id,
            success_count=success_count,
        )
    else:
        completed = _complete_job_sqlite(
            session, token, success_count=success_count
        )
    if completed and finalize_parent_id:
        from apps.worker.finalize import promote_range_parent_if_ready

        promote_range_parent_if_ready(session, finalize_parent_id)
    elif completed and date_parent_id:
        from apps.worker.daily_windows import enqueue_finalize_if_ready

        try:
            with session.begin_nested():
                enqueue_finalize_if_ready(session, date_parent_id)
        except RuntimeError:
            # Child completion is authoritative.  A deterministic finalize
            # identity conflict remains for the bounded reconciler/operator
            # instead of rolling the live-token completion back.
            pass
    return completed


def fail_job(
    session: Session,
    token: LeaseToken,
    *,
    failure_kind: FailureKind,
    error_code: str,
    error_summary: str,
    base_delay_seconds: int = DEFAULT_RETRY_BASE_DELAY_SECONDS,
) -> RetryDecision | None:
    """Fail a valid lease with bounded retry classification and audit history."""

    if not error_code.strip():
        raise ValueError("error_code is required")
    if not error_summary.strip():
        raise ValueError("error_summary is required")
    if session.get_bind().dialect.name == "postgresql":
        retry_state = repositories.lock_active_execution_state(
            session,
            job_id=token.job_id,
            lease_owner=token.lease_owner,
            lease_epoch=token.lease_epoch,
            attempt_id=token.attempt_id,
            component_instance_id=token.component_instance_id,
        )
        if retry_state is None:
            return None
        previous_exit_type = repositories.previous_attempt_exit_type(
            session,
            job_id=token.job_id,
            attempt_number=retry_state.attempt_number,
        )
        decision = retry_policy(
            failure_kind,
            attempt_number=retry_state.attempt_number,
            max_attempts=retry_state.max_attempts,
            previous_exit_type=previous_exit_type,
            base_delay_seconds=base_delay_seconds,
        )
        attempt_exit_type = _attempt_exit_type(failure_kind, decision)
        updated = repositories.fail_claim(
            session,
            job_id=token.job_id,
            lease_owner=token.lease_owner,
            lease_epoch=token.lease_epoch,
            attempt_id=token.attempt_id,
            component_instance_id=token.component_instance_id,
            status=decision.status,
            delay_seconds=decision.delay_seconds,
            attempt_exit_type=attempt_exit_type,
            error_code=error_code.strip(),
            error_summary=error_summary.strip(),
        )
        return decision if updated else None
    return _fail_job_sqlite(
        session,
        token,
        failure_kind=failure_kind,
        error_code=error_code.strip(),
        error_summary=error_summary.strip(),
        base_delay_seconds=base_delay_seconds,
    )


def confirm_cancel_job(session: Session, token: LeaseToken, *, reason: str) -> bool:
    """Confirm cancellation at a safe boundary under the same lease fencing."""

    if not reason.strip():
        raise ValueError("cancel reason is required")
    return repositories.cancel_claim(
        session,
        job_id=token.job_id,
        lease_owner=token.lease_owner,
        lease_epoch=token.lease_epoch,
        attempt_id=token.attempt_id,
        component_instance_id=token.component_instance_id,
        reason=reason.strip(),
    )


def _attempt_exit_type(
    failure_kind: FailureKind,
    decision: RetryDecision,
) -> str:
    if failure_kind is FailureKind.MEMORY_GUARD:
        return "resource_guard"
    if failure_kind is FailureKind.CRASHED:
        return "crashed"
    if decision.status == "retry_wait":
        return "retryable_failure"
    return "fatal_failure"


def _record_attempt_observation_sqlite(
    session: Session,
    token: LeaseToken,
    *,
    exit_code: int | None,
    rss_peak_bytes: int | None,
    error_code: str | None,
    error_summary: str | None,
) -> bool:
    active = _sqlite_active_execution(session, token)
    if active is None:
        return False
    _job, attempt, _component = active
    attempt.exit_code = exit_code
    attempt.rss_peak_bytes = rss_peak_bytes
    attempt.error_code = error_code
    attempt.error_summary = error_summary
    session.flush()
    return True


def _complete_job_sqlite(
    session: Session,
    token: LeaseToken,
    *,
    success_count: int,
) -> bool:
    active = _sqlite_active_execution(session, token)
    if active is None:
        return False
    job, attempt, component = active
    now = datetime.now(UTC)
    job.status = "success"
    job.success_count = success_count
    job.failed_count = 0
    job.finished_at = now
    job.lease_owner = None
    job.lease_expires_at = None
    job.next_retry_at = None
    job.error_code = None
    job.error_summary = None
    job.error_message = None
    attempt.finished_at = now
    attempt.exit_type = "success"
    component.status = "healthy"
    component.current_job_id = None
    component.current_attempt_id = None
    component.updated_at = now
    session.add(
        _job_event_sqlite(
            token,
            event_type="job_succeeded",
            from_status="running",
            to_status="success",
            occurred_at=now,
        )
    )
    session.flush()
    return True


def _fail_job_sqlite(
    session: Session,
    token: LeaseToken,
    *,
    failure_kind: FailureKind,
    error_code: str,
    error_summary: str,
    base_delay_seconds: int,
) -> RetryDecision | None:
    active = _sqlite_active_execution(session, token)
    if active is None:
        return None
    job, attempt, component = active
    previous_exit_type = session.scalar(
        select(repositories.JobAttempt.exit_type).where(
            repositories.JobAttempt.job_id == token.job_id,
            repositories.JobAttempt.attempt_number == int(job.attempt_count or 0) - 1,
        )
    )
    decision = retry_policy(
        failure_kind,
        attempt_number=int(job.attempt_count or 0),
        max_attempts=int(job.max_attempts or DEFAULT_MAX_ATTEMPTS),
        previous_exit_type=previous_exit_type,
        base_delay_seconds=base_delay_seconds,
    )
    now = datetime.now(UTC)
    job.status = decision.status
    job.finished_at = now if decision.status == "failed" else None
    job.lease_owner = None
    job.lease_expires_at = None
    job.next_retry_at = (
        now + timedelta(seconds=decision.delay_seconds)
        if decision.delay_seconds is not None
        else None
    )
    job.failed_count = max(1, int(job.failed_count or 0))
    job.error_code = error_code
    job.error_summary = error_summary
    job.error_message = error_summary
    attempt.finished_at = now
    attempt.exit_type = _attempt_exit_type(failure_kind, decision)
    attempt.error_code = error_code
    attempt.error_summary = error_summary
    component.status = "degraded" if decision.status == "retry_wait" else "unhealthy"
    component.current_job_id = None
    component.current_attempt_id = None
    component.updated_at = now
    session.add(
        _job_event_sqlite(
            token,
            event_type=(
                "job_retry_scheduled" if decision.status == "retry_wait" else "job_failed"
            ),
            from_status="running",
            to_status=decision.status,
            occurred_at=now,
            reason=error_summary,
            payload_json={"error_code": error_code, "delay_seconds": decision.delay_seconds},
        )
    )
    session.flush()
    return decision


def _sqlite_active_execution(
    session: Session,
    token: LeaseToken,
):
    from apps.api.dy_api.models import ComponentHeartbeat, JobAttempt, JobRun

    job = session.get(JobRun, token.job_id)
    if job is None or job.status != "running":
        return None
    if (
        job.lease_owner != token.lease_owner
        or int(job.lease_epoch or 0) != int(token.lease_epoch)
        or job.lease_expires_at is None
        or _as_utc(job.lease_expires_at) <= datetime.now(UTC)
    ):
        return None
    attempt = session.scalar(
        select(JobAttempt).where(
            JobAttempt.job_id == token.job_id,
            JobAttempt.attempt_id == token.attempt_id,
            JobAttempt.lease_epoch == token.lease_epoch,
            JobAttempt.component_instance_id == token.component_instance_id,
            JobAttempt.finished_at.is_(None),
        )
    )
    component = session.scalar(
        select(ComponentHeartbeat).where(
            ComponentHeartbeat.component_instance_id == token.component_instance_id,
            ComponentHeartbeat.component_type == "worker",
            ComponentHeartbeat.current_job_id == token.job_id,
            ComponentHeartbeat.current_attempt_id == token.attempt_id,
        )
    )
    if attempt is None or component is None:
        return None
    return job, attempt, component


def _job_event_sqlite(
    token: LeaseToken,
    *,
    event_type: str,
    from_status: str,
    to_status: str,
    occurred_at: datetime,
    reason: str | None = None,
    payload_json: dict | None = None,
):
    from apps.api.dy_api.models import JobEvent

    return JobEvent(
        event_id=f"event-{uuid4()}",
        job_id=token.job_id,
        attempt_id=token.attempt_id,
        event_type=event_type,
        from_status=from_status,
        to_status=to_status,
        actor_type="worker",
        actor_id=token.lease_owner,
        reason=reason,
        payload_json=payload_json or {},
        occurred_at=occurred_at,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _validate_claim_inputs(
    *,
    lease_owner: str,
    component_instance_id: str,
    lease_seconds: int,
) -> None:
    if not lease_owner.strip():
        raise ValueError("lease_owner is required")
    if not component_instance_id.strip():
        raise ValueError("component_instance_id is required")
    if lease_seconds <= 0:
        raise ValueError("lease_seconds must be positive")
