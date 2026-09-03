"""Parent-process supervision for one heavy daily worker child."""

from __future__ import annotations

import os
import re
import socket
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, Callable, Sequence
from uuid import uuid4

from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.models import ComponentHeartbeat, JobAttempt, JobRun, JobStageRun
from apps.ops_agent.resources import (
    ResourceAction,
    ResourceDecision,
    ResourceThresholds,
    collect_resource_snapshot,
    evaluate_resource_guard,
)
from apps.worker import repositories
from apps.worker.pipeline import sanitize_error_message
from apps.worker.task_control import (
    DEFAULT_RETRY_BASE_DELAY_SECONDS,
    FailureKind,
    LeaseToken,
    RetryDecision,
    claim_job,
    claim_next_job,
    complete_job,
    fail_job,
    record_attempt_observation,
)


class ChildRunStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    RETRY_WAIT = "retry_wait"
    CONTROL_ERROR = "control_error"
    OOM = "oom"
    BUSY = "busy"
    TIMEOUT = "timeout"


class ChildTerminationReason(str, Enum):
    """Authoritative reason for how a child attempt ended."""

    PROCESS_EXIT = "process_exit"
    TIMEOUT = "timeout"
    RSS_GUARD = "rss_guard"
    LEASE_LOST = "lease_lost"
    SPAWN = "spawn"
    CONTROL = "control"


# Short alias for callers that prefer the generic name used by the control
# plane review vocabulary.
TerminationReason = ChildTerminationReason


@dataclass(frozen=True)
class ChildRunResult:
    job_id: str
    status: ChildRunStatus
    attempts: int
    exit_code: int | None = None
    rss_peak_bytes: int | None = None
    rss_last_bytes: int | None = None
    heartbeat_seen: bool = False
    lease_seen: bool = False
    timed_out: bool = False
    error_summary: str | None = None
    termination_reason: ChildTerminationReason | None = None


PopenFactory = Callable[..., Any]
RSSReader = Callable[[int], int | None]
DEFAULT_LEASE_SECONDS = 120
MIN_LEASE_SECONDS = 1
MAX_LEASE_SECONDS = 3600


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def worker_resource_decision() -> ResourceDecision:
    """Evaluate the benchmark-tuned guard before claiming a heavy child."""

    if not _truthy(os.getenv("WORKER_RESOURCE_GUARD_ENABLED")):
        return ResourceDecision(ResourceAction.ALLOW, ())
    try:
        snapshot = collect_resource_snapshot(os.getpid())
        return evaluate_resource_guard(snapshot, ResourceThresholds.from_env())
    except Exception:
        # A malformed threshold or unreadable sampler must not start another
        # memory-heavy child with an unknown safety posture.
        return ResourceDecision(ResourceAction.STOP, ("resource_guard_configuration_invalid",))


class SubprocessSupervisor:
    """Run at most one ``heavy_sync`` child and persist each attempt outcome."""

    _heavy_child_lock = threading.Lock()

    def __init__(
        self,
        *,
        control_session_factory: sessionmaker[Session] | Callable[[], Session] | None = None,
        popen_factory: PopenFactory = subprocess.Popen,
        rss_reader: RSSReader | None = None,
        poll_interval_seconds: float = 0.25,
        graceful_timeout_seconds: float = 5.0,
        heartbeat_interval_seconds: float = 5.0,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        rss_limit_bytes: int | None = None,
    ) -> None:
        self.control_session_factory = control_session_factory
        self.popen_factory = popen_factory
        self.rss_reader = rss_reader or read_process_rss_bytes
        self.poll_interval_seconds = max(0.0, poll_interval_seconds)
        self.graceful_timeout_seconds = max(0.1, graceful_timeout_seconds)
        if lease_seconds < MIN_LEASE_SECONDS or lease_seconds > MAX_LEASE_SECONDS:
            raise ValueError(
                f"lease_seconds must be between {MIN_LEASE_SECONDS} and {MAX_LEASE_SECONDS}"
            )
        if heartbeat_interval_seconds <= 0 or heartbeat_interval_seconds >= lease_seconds:
            raise ValueError("heartbeat_interval_seconds must be positive and less than lease_seconds")
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.lease_seconds = lease_seconds
        self.rss_limit_bytes = rss_limit_bytes
        process_start_id = uuid4().hex
        host_id = socket.gethostname() or "unknown-host"
        self.component_instance_id = (
            f"worker-supervisor-{host_id}-{os.getpid()}-{process_start_id}"
        )
        self.lease_owner = f"scheduler-{host_id}-{os.getpid()}-{process_start_id}"

    def run(
        self,
        *,
        job_id: str | None = None,
        command: Sequence[str],
        max_attempts: int = 3,
        env: dict[str, str] | None = None,
        timeout_seconds: float | None = None,
    ) -> ChildRunResult:
        if job_id is not None and not job_id.strip():
            raise ValueError("job_id is required")
        if not command:
            raise ValueError("command is required")
        if max_attempts <= 0 or max_attempts > 3:
            raise ValueError("max_attempts must be between 1 and 3")

        resource_decision = worker_resource_decision()
        if resource_decision.action is not ResourceAction.ALLOW:
            reasons = ",".join(resource_decision.reasons) or "resource_guard_blocked"
            return ChildRunResult(
                job_id=job_id or "",
                status=ChildRunStatus.CONTROL_ERROR,
                attempts=0,
                error_summary=f"worker resource guard blocked child claim: {reasons}",
                termination_reason=ChildTerminationReason.RSS_GUARD,
            )

        if not self._heavy_child_lock.acquire(blocking=False):
            return ChildRunResult(
                job_id=job_id,
                status=ChildRunStatus.BUSY,
                attempts=0,
                error_summary="heavy child already running",
                termination_reason=ChildTerminationReason.CONTROL,
            )
        try:
            return self._run_locked(
                job_id=job_id,
                command=command,
                max_attempts=max_attempts,
                env=env,
                timeout_seconds=timeout_seconds,
            )
        finally:
            self._heavy_child_lock.release()

    def _run_locked(
        self,
        *,
        job_id: str,
        command: Sequence[str],
        max_attempts: int,
        env: dict[str, str] | None,
        timeout_seconds: float | None,
    ) -> ChildRunResult:
        last_exit: int | None = None
        peak_rss: int | None = None
        last_rss: int | None = None
        last_error: str | None = None
        heartbeat_seen = False
        lease_seen = False
        timed_out = False
        termination_reason: ChildTerminationReason | None = None
        attempts_completed = 0
        deferred_retry = False

        for attempt_number in range(1, max_attempts + 1):
            claim = self._start_attempt(job_id, attempt_number=attempt_number)
            if claim is None:
                status = self._claim_failure_status(job_id)
                return ChildRunResult(
                    job_id=job_id or "",
                    status=status,
                    attempts=attempts_completed,
                    error_summary="daily job lease is already owned or exhausted",
                    termination_reason=ChildTerminationReason.CONTROL,
                )
            job_id = claim.job_id
            attempt_id = claim.attempt_id
            component_id = claim.component_instance_id
            started = time.monotonic()
            process: Any | None = None
            exit_code: int | None = None
            rss_peak: int | None = None
            rss_last: int | None = None
            attempt_error: str | None = None
            attempt_timed_out = False
            attempt_termination_reason: ChildTerminationReason | None = None
            failure_decision: RetryDecision | None = None
            stdout_buffer: list[str] = []
            stderr_buffer: list[str] = []
            drain_threads: list[threading.Thread] = []
            try:
                child_env = os.environ.copy()
                if env:
                    child_env.update(env)
                child_env.update(
                    {
                        "DY_WORKER_LEASE_OWNER": claim.lease_owner,
                        "DY_WORKER_LEASE_EPOCH": str(claim.lease_epoch),
                        "DY_WORKER_ATTEMPT_ID": claim.attempt_id,
                        "DY_WORKER_COMPONENT_ID": claim.component_instance_id,
                        "DY_WORKER_JOB_ID": claim.job_id,
                    }
                )
                child_env.setdefault("PYTHONUNBUFFERED", "1")
                process = self.popen_factory(
                    list(command),
                    env=child_env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                drain_threads = _start_pipe_drainers(process, stdout_buffer, stderr_buffer)
                attempt_started_persisted = self._mark_attempt_started(
                    claim,
                    process_id=getattr(process, "pid", None),
                )
                if not attempt_started_persisted:
                    attempt_error = "control-plane attempt start was not persisted"
                    attempt_termination_reason = ChildTerminationReason.CONTROL
                    self._terminate_child(process)
                    exit_code = process.poll()
                    if exit_code is None:
                        exit_code = -11
                heartbeat_seen = attempt_started_persisted and self._renew_lease(claim)
                lease_seen = heartbeat_seen
                last_heartbeat_monotonic = time.monotonic()
                while True:
                    if attempt_error is not None and exit_code is not None:
                        break
                    exit_code = process.poll()
                    rss_last = self._safe_rss(process)
                    if rss_last is not None:
                        rss_peak = max(rss_peak or 0, rss_last)
                        peak_rss = max(peak_rss or 0, rss_last)
                        last_rss = rss_last
                    if (
                        self.rss_limit_bytes is not None
                        and rss_last is not None
                        and rss_last >= self.rss_limit_bytes
                    ):
                        attempt_error = "worker RSS limit reached"
                        attempt_termination_reason = ChildTerminationReason.RSS_GUARD
                        self._terminate_child(process)
                        exit_code = process.poll()
                        if exit_code is None:
                            exit_code = -9
                        break
                    if exit_code is not None:
                        break
                    if time.monotonic() - last_heartbeat_monotonic >= self.heartbeat_interval_seconds:
                        renewed = self._renew_lease(claim)
                        last_heartbeat_monotonic = time.monotonic()
                        heartbeat_seen = heartbeat_seen or renewed
                        lease_seen = lease_seen or renewed
                        if not renewed:
                            attempt_error = "worker lease renewal failed"
                            attempt_termination_reason = ChildTerminationReason.LEASE_LOST
                            self._terminate_child(process)
                            exit_code = process.poll()
                            if exit_code is None:
                                exit_code = -10
                            break
                    if timeout_seconds is not None and time.monotonic() - started >= timeout_seconds:
                        attempt_error = "worker child timed out"
                        attempt_termination_reason = ChildTerminationReason.TIMEOUT
                        self._terminate_child(process)
                        attempt_timed_out = True
                        timed_out = True
                        exit_code = process.poll()
                        if exit_code is None:
                            exit_code = -15
                        break
                    if self.poll_interval_seconds:
                        time.sleep(self.poll_interval_seconds)
                if exit_code is None:
                    exit_code = process.wait(timeout=self.graceful_timeout_seconds)
                for drain_thread in drain_threads:
                    drain_thread.join(timeout=0.5)
                attempt_error = attempt_error or sanitize_error_message("\n".join(stderr_buffer).strip())
                attempt_termination_reason = (
                    attempt_termination_reason or ChildTerminationReason.PROCESS_EXIT
                )
            except Exception as exc:
                attempt_error = sanitize_error_message(str(exc))
                attempt_termination_reason = (
                    ChildTerminationReason.SPAWN
                    if process is None
                    else ChildTerminationReason.CONTROL
                )
            finally:
                if process is not None and exit_code is None:
                    try:
                        exit_code = process.wait(timeout=self.graceful_timeout_seconds)
                    except Exception:
                        self._terminate_child(process)
                        exit_code = process.poll()
                attempt_persisted, failure_decision = self._persist_attempt_outcome(
                    job_id,
                    token=claim,
                    exit_code=exit_code,
                    rss_peak_bytes=rss_peak,
                    error_summary=attempt_error,
                    timed_out=attempt_timed_out,
                    termination_reason=attempt_termination_reason,
                )
                if not attempt_persisted:
                    attempt_error = "control-plane attempt finalization was rejected by lease fencing"

            last_exit = exit_code
            last_error = attempt_error
            termination_reason = attempt_termination_reason
            attempts_completed = attempt_number
            if not attempt_persisted:
                break
            if failure_decision is not None and failure_decision.status == "success":
                return ChildRunResult(
                    job_id=job_id,
                    status=ChildRunStatus.SUCCESS,
                    attempts=attempt_number,
                    exit_code=exit_code,
                    rss_peak_bytes=peak_rss,
                    rss_last_bytes=last_rss,
                    heartbeat_seen=heartbeat_seen,
                    lease_seen=lease_seen,
                    timed_out=timed_out,
                    error_summary=last_error,
                    termination_reason=termination_reason,
                )
            if exit_code == 0 and failure_decision is None:
                return ChildRunResult(
                    job_id=job_id,
                    status=ChildRunStatus.SUCCESS,
                    attempts=attempt_number,
                    exit_code=exit_code,
                    rss_peak_bytes=peak_rss,
                    rss_last_bytes=last_rss,
                    heartbeat_seen=heartbeat_seen,
                    lease_seen=lease_seen,
                    timed_out=timed_out,
                    error_summary=last_error,
                    termination_reason=termination_reason,
                )
            if failure_decision is not None and failure_decision.status == "retry_wait":
                if attempt_number < max_attempts:
                    continue
                # The caller's invocation budget is independent from the
                # durable JobRun.max_attempts policy.  Do not label a job
                # terminally failed while T1.2 has left it retry_wait.
                deferred_retry = True
            break

        if deferred_retry:
            status = ChildRunStatus.RETRY_WAIT
        elif termination_reason is ChildTerminationReason.RSS_GUARD:
            status = ChildRunStatus.OOM
        elif termination_reason is ChildTerminationReason.TIMEOUT:
            status = ChildRunStatus.TIMEOUT
        else:
            status = ChildRunStatus.FAILED
        return ChildRunResult(
            job_id=job_id,
            status=status,
            attempts=attempts_completed,
            exit_code=last_exit,
            rss_peak_bytes=peak_rss,
            rss_last_bytes=last_rss,
            heartbeat_seen=heartbeat_seen,
            lease_seen=lease_seen,
            timed_out=timed_out,
            error_summary=last_error,
            termination_reason=termination_reason,
        )

    def _safe_rss(self, process: Any) -> int | None:
        try:
            pid = int(process.pid)
            value = self.rss_reader(pid)
            return max(0, int(value)) if value is not None else None
        except Exception:
            return None

    def _renew_lease(self, token: LeaseToken) -> bool:
        if self.control_session_factory is None:
            return False
        session = self.control_session_factory()
        try:
            session.begin()
            if session.get_bind().dialect.name == "postgresql":
                from apps.worker.task_control import heartbeat_job

                renewed = heartbeat_job(
                    session,
                    token,
                    lease_seconds=self.lease_seconds,
                )
            else:
                now = datetime.now(UTC)
                result = session.execute(
                    update(JobRun)
                    .where(
                        JobRun.job_id == token.job_id,
                        JobRun.status == "running",
                        JobRun.lease_owner == token.lease_owner,
                        JobRun.lease_epoch == token.lease_epoch,
                    )
                    .values(
                        heartbeat_at=now,
                        lease_expires_at=now + timedelta(seconds=self.lease_seconds),
                    )
                )
                renewed = result.rowcount == 1
                if renewed:
                    component_result = session.execute(
                        update(ComponentHeartbeat)
                        .where(
                            ComponentHeartbeat.component_instance_id
                            == token.component_instance_id,
                            ComponentHeartbeat.component_type == "worker",
                            ComponentHeartbeat.current_job_id == token.job_id,
                            ComponentHeartbeat.current_attempt_id == token.attempt_id,
                        )
                        .values(last_heartbeat_at=now, updated_at=now)
                    )
                    renewed = component_result.rowcount == 1
            session.commit()
            return bool(renewed)
        except Exception:
            session.rollback()
            return False
        finally:
            session.close()

    def _terminate_child(self, process: Any) -> None:
        try:
            process.terminate()
            process.wait(timeout=self.graceful_timeout_seconds)
            return
        except Exception:
            pass
        try:
            process.kill()
            process.wait(timeout=self.graceful_timeout_seconds)
        except Exception:
            pass

    def _start_attempt(self, job_id: str | None, *, attempt_number: int) -> LeaseToken | None:
        component_id = self.component_instance_id
        lease_owner = self.lease_owner
        if self.control_session_factory is None:
            # A control plane is mandatory for production execution.  The
            # no-database path is retained only for command-level smoke tests.
            return None
        session = self.control_session_factory()
        try:
            session.begin()
            from apps.worker.finalize import reconcile_finalize_parents
            from apps.worker.daily_windows import (
                reconcile_finalize_queue,
                reconcile_terminal_range_parents,
            )

            reconcile_terminal_range_parents(session)
            reconcile_finalize_queue(session)
            reconcile_finalize_parents(session)
            if job_id is None:
                if session.get_bind().dialect.name == "postgresql":
                    token = claim_next_job(
                        session,
                        lease_owner=lease_owner,
                        component_instance_id=component_id,
                        lease_seconds=self.lease_seconds,
                    )
                else:
                    candidate = session.scalar(
                        select(JobRun)
                        .where(
                            JobRun.job_kind.in_(("parent_sync", "date_sync", "finalize")),
                            JobRun.execution_slot == "heavy_sync",
                            or_(
                                JobRun.status == "pending",
                                and_(
                                    JobRun.status == "retry_wait",
                                    JobRun.next_retry_at.is_not(None),
                                    JobRun.next_retry_at <= datetime.now(UTC),
                                ),
                            ),
                        )
                        .order_by(
                            case((JobRun.job_kind == "parent_sync", 0), else_=1),
                            JobRun.business_date,
                            JobRun.job_id,
                        )
                    )
                    token = (
                        claim_job(
                            session,
                            job_id=candidate.job_id,
                            lease_owner=lease_owner,
                            component_instance_id=component_id,
                            lease_seconds=self.lease_seconds,
                        )
                        if candidate is not None
                        else None
                    )
            else:
                token = claim_job(
                    session,
                    job_id=job_id,
                    lease_owner=lease_owner,
                    component_instance_id=component_id,
                    lease_seconds=self.lease_seconds,
                )
            if token is None:
                # PostgreSQL may have durably finalized an expired last
                # attempt before returning no new token.  Committing this
                # claim transaction preserves that recovery disposition;
                # callers distinguish the no-token result from a new claim.
                session.commit()
                return None
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
        return token

    def _claim_failure_status(self, job_id: str | None) -> ChildRunStatus:
        if self.control_session_factory is None:
            return ChildRunStatus.BUSY
        if job_id is None:
            return ChildRunStatus.BUSY
        session = self.control_session_factory()
        try:
            job = session.get(JobRun, job_id)
            if job is not None and job.status in {"failed", "cancelled", "success"}:
                return (
                    ChildRunStatus.SUCCESS
                    if job.status == "success"
                    else ChildRunStatus.FAILED
                )
            if job is not None and job.status == "retry_wait":
                return ChildRunStatus.RETRY_WAIT
            if (
                job is not None
                and job.status == "pending"
                and int(job.attempt_count or 0) >= int(job.max_attempts or 3)
            ):
                # No active token exists here, so fail closed instead of
                # fabricating a terminal mutation outside T1.2's event/attempt
                # state machine. The control-plane inconsistency is surfaced
                # to the scheduler for operator repair.
                return ChildRunStatus.CONTROL_ERROR
            return ChildRunStatus.BUSY
        except Exception:
            session.rollback()
            return ChildRunStatus.BUSY
        finally:
            session.close()

    def _mark_attempt_started(
        self,
        token: LeaseToken,
        *,
        process_id: int | None,
    ) -> bool:
        if self.control_session_factory is None:
            return False
        persisted = False
        session = self.control_session_factory()
        try:
            session.begin()
            now = datetime.now(UTC)
            with session.begin_nested():
                if session.get_bind().dialect.name == "postgresql":
                    active = repositories.lock_active_execution_state(
                        session,
                        job_id=token.job_id,
                        lease_owner=token.lease_owner,
                        lease_epoch=token.lease_epoch,
                        attempt_id=token.attempt_id,
                        component_instance_id=token.component_instance_id,
                    )
                    if active is None:
                        return False
                    attempt_result = session.execute(
                        update(JobAttempt)
                        .where(
                            JobAttempt.job_id == token.job_id,
                            JobAttempt.attempt_id == token.attempt_id,
                            JobAttempt.lease_epoch == token.lease_epoch,
                            JobAttempt.finished_at.is_(None),
                        )
                        .values(process_id=int(process_id) if process_id is not None else None)
                    )
                    heartbeat_result = session.execute(
                        update(ComponentHeartbeat)
                        .where(
                            ComponentHeartbeat.component_instance_id
                            == token.component_instance_id,
                            ComponentHeartbeat.component_type == "worker",
                            ComponentHeartbeat.current_job_id == token.job_id,
                            ComponentHeartbeat.current_attempt_id == token.attempt_id,
                        )
                        .values(
                            last_heartbeat_at=func.greatest(
                                func.coalesce(
                                    ComponentHeartbeat.last_heartbeat_at,
                                    func.clock_timestamp(),
                                ),
                                func.clock_timestamp(),
                            ),
                            updated_at=func.greatest(
                                func.coalesce(
                                    ComponentHeartbeat.updated_at,
                                    func.clock_timestamp(),
                                ),
                                func.clock_timestamp(),
                            ),
                        )
                    )
                    if attempt_result.rowcount != 1 or heartbeat_result.rowcount != 1:
                        raise RuntimeError("active attempt identity changed before process start")
                else:
                    job = session.scalar(
                        select(JobRun).where(
                            JobRun.job_id == token.job_id,
                            JobRun.status == "running",
                            JobRun.lease_owner == token.lease_owner,
                            JobRun.lease_epoch == token.lease_epoch,
                        )
                    )
                    lease_expires_at = job.lease_expires_at if job is not None else None
                    if lease_expires_at is None:
                        return False
                    if lease_expires_at.tzinfo is None:
                        lease_expires_at = lease_expires_at.replace(tzinfo=UTC)
                    if lease_expires_at <= now:
                        return False
                    attempt = session.scalar(
                        select(JobAttempt).where(
                            JobAttempt.job_id == token.job_id,
                            JobAttempt.attempt_id == token.attempt_id,
                            JobAttempt.lease_epoch == token.lease_epoch,
                            JobAttempt.component_instance_id == token.component_instance_id,
                            JobAttempt.finished_at.is_(None),
                        )
                    )
                    heartbeat = session.scalar(
                        select(ComponentHeartbeat).where(
                            ComponentHeartbeat.component_instance_id
                            == token.component_instance_id,
                            ComponentHeartbeat.component_type == "worker",
                            ComponentHeartbeat.current_job_id == token.job_id,
                            ComponentHeartbeat.current_attempt_id == token.attempt_id,
                        )
                    )
                    if attempt is None or heartbeat is None:
                        return False
                    attempt.process_id = int(process_id) if process_id is not None else None
                    heartbeat.last_heartbeat_at = now
                    heartbeat.updated_at = now
                session.flush()
            persisted = True
            session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()
        return persisted

    def _persist_attempt_outcome(
        self,
        job_id: str,
        *,
        token: LeaseToken,
        exit_code: int | None,
        rss_peak_bytes: int | None,
        error_summary: str | None,
        timed_out: bool,
        termination_reason: ChildTerminationReason | None,
    ) -> tuple[bool, RetryDecision | None]:
        """Record evidence and close the attempt through T1.2 atomically."""

        if self.control_session_factory is None:
            return False, None
        session = self.control_session_factory()
        try:
            session.begin()
            summary = sanitize_error_message(error_summary) or "daily child failed"
            reason = termination_reason or ChildTerminationReason.PROCESS_EXIT
            has_termination_evidence = (
                exit_code not in (None, 0)
                or reason is not ChildTerminationReason.PROCESS_EXIT
            )
            if not record_attempt_observation(
                session,
                token,
                exit_code=exit_code,
                rss_peak_bytes=rss_peak_bytes,
                error_code=_failure_error_code(
                    exit_code,
                    termination_reason=termination_reason,
                    rss_peak_bytes=rss_peak_bytes,
                    rss_limit_bytes=self.rss_limit_bytes,
                    error_summary=summary,
                ),
                error_summary=summary if has_termination_evidence else None,
            ):
                session.rollback()
                return False, None
            if _all_required_stage_checkpoints_success(session, job_id):
                persisted = complete_job(session, token, success_count=1)
                if not persisted:
                    session.rollback()
                    return False, None
                if has_termination_evidence:
                    # ``complete_job`` closes the attempt through the T1.2
                    # API, but a non-zero process exit remains useful evidence
                    # when durable required checkpoints already prove the
                    # business work committed.
                    session.execute(
                        update(JobAttempt)
                        .where(
                            JobAttempt.job_id == token.job_id,
                            JobAttempt.attempt_id == token.attempt_id,
                        )
                        .values(
                            error_code=_failure_error_code(
                                exit_code,
                                termination_reason=termination_reason,
                                rss_peak_bytes=rss_peak_bytes,
                                rss_limit_bytes=self.rss_limit_bytes,
                            ),
                            error_summary=summary,
                        )
                    )
                session.commit()
                return True, RetryDecision(status="success", delay_seconds=None)
            reason = termination_reason or ChildTerminationReason.PROCESS_EXIT
            if exit_code == 0 and reason is ChildTerminationReason.PROCESS_EXIT:
                failure_kind = FailureKind.DATA_INTEGRITY
                error_code = "stage_checkpoint_incomplete"
                summary = "daily child exited successfully before all stage checkpoints completed"
            else:
                failure_kind = _failure_kind(
                    exit_code,
                    termination_reason=termination_reason,
                    error_summary=summary,
                    rss_peak_bytes=rss_peak_bytes,
                    rss_limit_bytes=self.rss_limit_bytes,
                )
                error_code = _failure_error_code(
                    exit_code,
                    termination_reason=termination_reason,
                    rss_peak_bytes=rss_peak_bytes,
                    rss_limit_bytes=self.rss_limit_bytes,
                    error_summary=summary,
                )
            decision = fail_job(
                session,
                token,
                failure_kind=failure_kind,
                error_code=error_code,
                error_summary=summary,
                base_delay_seconds=_failure_retry_base_delay_seconds(summary),
                fixed_delay_seconds=_quota_retry_after_seconds(summary),
            )
            if decision is None:
                session.rollback()
                return False, None
            session.commit()
            return True, decision
        except Exception:
            session.rollback()
            return False, None
        finally:
            session.close()


def _is_oom(
    exit_code: int | None,
    *,
    termination_reason: ChildTerminationReason | None = None,
    rss_peak_bytes: int | None,
    rss_limit_bytes: int | None,
) -> bool:
    _ = (exit_code, rss_peak_bytes, rss_limit_bytes)
    return termination_reason is ChildTerminationReason.RSS_GUARD


def _is_fatal_error(error_summary: str | None) -> bool:
    normalized = (error_summary or "").lower()
    return any(marker in normalized for marker in ("integrity", "data_integrity", "fatal"))


def _is_douyin_rate_limit_error(error_summary: str | None) -> bool:
    summary = error_summary or ""
    normalized = summary.lower()
    return (
        "2119003" in summary
        or "请求太过频繁" in summary
        or "douyin_api_quota_exhausted" in normalized
    )


_RETRY_AFTER_SECONDS_RE = re.compile(r"retry_after_seconds=(\d+)", re.IGNORECASE)


def _quota_retry_after_seconds(error_summary: str | None) -> int | None:
    match = _RETRY_AFTER_SECONDS_RE.search(error_summary or "")
    if match is None:
        return None
    return max(60, min(172800, int(match.group(1))))


def _failure_retry_base_delay_seconds(error_summary: str | None) -> int:
    if not _is_douyin_rate_limit_error(error_summary):
        return DEFAULT_RETRY_BASE_DELAY_SECONDS
    quota_retry_after = _quota_retry_after_seconds(error_summary)
    if quota_retry_after is not None:
        return quota_retry_after
    raw = os.getenv("DOUYIN_RATE_LIMIT_RETRY_BASE_SECONDS", "1800")
    try:
        value = int(raw)
    except ValueError:
        value = 1800
    return max(60, min(3600, value))


def _all_required_stage_checkpoints_success(session: Session, job_id: str) -> bool:
    job = session.get(JobRun, job_id)
    if job is None:
        return False
    required_stages = (job.metadata_json or {}).get("required_stages")
    if not isinstance(required_stages, list) or not required_stages:
        required_stages = ["collect", "materialize", "settle"]
    statuses = dict(
        session.execute(
            select(JobStageRun.stage_name, JobStageRun.status).where(
                JobStageRun.job_id == job_id,
                JobStageRun.stage_name.in_(required_stages),
            )
        ).all()
    )
    return all(statuses.get(stage_name) == "success" for stage_name in required_stages)


# Backward-compatible private helper name for callers outside this module.
_all_stage_checkpoints_success = _all_required_stage_checkpoints_success


def _failure_kind(
    exit_code: int | None,
    *,
    termination_reason: ChildTerminationReason | None = None,
    error_summary: str | None,
    rss_peak_bytes: int | None,
    rss_limit_bytes: int | None,
) -> FailureKind:
    reason = termination_reason or ChildTerminationReason.PROCESS_EXIT
    if _is_douyin_rate_limit_error(error_summary):
        return FailureKind.TRANSIENT
    if reason is ChildTerminationReason.RSS_GUARD:
        return FailureKind.MEMORY_GUARD
    if reason in {
        ChildTerminationReason.TIMEOUT,
        ChildTerminationReason.LEASE_LOST,
        ChildTerminationReason.SPAWN,
        ChildTerminationReason.CONTROL,
    }:
        return FailureKind.TRANSIENT
    if _is_fatal_error(error_summary):
        return FailureKind.DATA_INTEGRITY
    return FailureKind.CRASHED


def _failure_error_code(
    exit_code: int | None,
    *,
    termination_reason: ChildTerminationReason | None = None,
    rss_peak_bytes: int | None,
    rss_limit_bytes: int | None,
    error_summary: str | None = None,
) -> str | None:
    reason = termination_reason or ChildTerminationReason.PROCESS_EXIT
    if _is_douyin_rate_limit_error(error_summary):
        return repositories.DOUYIN_RATE_LIMIT_ERROR_CODE
    if reason is ChildTerminationReason.TIMEOUT:
        return "worker_timeout"
    if reason is ChildTerminationReason.RSS_GUARD:
        return "worker_memory_guard"
    if reason is ChildTerminationReason.LEASE_LOST:
        return "worker_lease_lost"
    if reason is ChildTerminationReason.SPAWN:
        return "worker_spawn_error"
    if reason is ChildTerminationReason.CONTROL:
        return "worker_control_error"
    if exit_code == 0:
        return None
    if exit_code is None:
        return "worker_no_exit_code"
    return f"worker_exit_{abs(int(exit_code))}"[:64]


def _start_pipe_drainers(
    process: Any,
    stdout_buffer: list[str],
    stderr_buffer: list[str],
) -> list[threading.Thread]:
    """Drain both child pipes concurrently so verbose children cannot block."""

    threads: list[threading.Thread] = []
    for stream, buffer in ((getattr(process, "stdout", None), stdout_buffer), (getattr(process, "stderr", None), stderr_buffer)):
        if stream is None:
            continue

        def drain(target_stream=stream, target_buffer=buffer) -> None:
            tail: deque[str] = deque()
            tail_size = 0
            try:
                while True:
                    try:
                        chunk = target_stream.read(4096)
                    except TypeError:
                        # Small fake streams used by unit tests may expose a
                        # zero-argument ``read``; real Popen pipes take a size.
                        chunk = target_stream.read()
                    if not chunk:
                        break
                    chunk = str(chunk)
                    if len(chunk) >= 8192:
                        tail.clear()
                        tail.append(chunk[-8192:])
                        tail_size = 8192
                        continue
                    tail.append(chunk)
                    tail_size += len(chunk)
                    while tail_size > 8192 and tail:
                        removed = tail.popleft()
                        overflow = tail_size - 8192
                        if len(removed) <= overflow:
                            tail_size -= len(removed)
                        else:
                            tail.appendleft(removed[overflow:])
                            tail_size -= overflow
                if tail:
                    target_buffer.append("".join(tail))
            except Exception:
                return

        thread = threading.Thread(target=drain, name="dy-worker-child-pipe", daemon=True)
        thread.start()
        threads.append(thread)
    return threads


def read_process_rss_bytes(pid: int) -> int | None:
    """Best-effort RSS reader without making psutil a hard dependency."""

    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                # psapi requires the complete PROCESS_MEMORY_COUNTERS layout;
                # passing a truncated structure makes GetProcessMemoryInfo
                # return FALSE even for the current process.
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            open_process = ctypes.windll.kernel32.OpenProcess
            open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            open_process.restype = wintypes.HANDLE
            close_handle = ctypes.windll.kernel32.CloseHandle
            close_handle.argtypes = [wintypes.HANDLE]
            close_handle.restype = wintypes.BOOL
            handle = open_process(0x0410, False, pid)
            if not handle:
                return None
            try:
                counters = PROCESS_MEMORY_COUNTERS()
                counters.cb = ctypes.sizeof(counters)
                get_process_memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
                get_process_memory_info.argtypes = [
                    wintypes.HANDLE,
                    ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
                    wintypes.DWORD,
                ]
                get_process_memory_info.restype = wintypes.BOOL
                ok = get_process_memory_info(handle, ctypes.byref(counters), counters.cb)
                return int(counters.WorkingSetSize) if ok else None
            finally:
                close_handle(handle)
        with open(f"/proc/{pid}/status", encoding="utf-8") as status:
            for line in status:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except (FileNotFoundError, OSError, ValueError):
        return None
    return None
