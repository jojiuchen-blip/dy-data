"""Claimable maintenance runner that compacts and publishes settlement lineage.

The runner mirrors the audited ``settlement_rebuild`` job lifecycle and joins
the shared heavy-slot control plane: the compaction JobRun carries
``execution_slot='heavy_sync'`` so the database-level unique running-slot index
(``uq_job_runs_heavy_sync_running_slot``) makes it mutually exclusive with
every other heavy job, claims serialize on the same
``HEAVY_SYNC_CLAIM_LOCK_KEY`` advisory lock used by the heavy worker, and both
the upstream rate-limit cooldown and resource admission decisions are
honoured.  Publication goes through the accepted
``publish_settlement_compaction`` and the success transition commits in the
same transaction, so a crash can never leave a published pointer with a
non-success job: reruns recover idempotently from the publisher's one-time
audit event.  Fee, statement, confirmation and invoice rows are never written
here, and the active pointer is never touched outside the audited publisher.
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from threading import Event, Lock, Thread
from typing import Any, Callable, Iterator
from uuid import uuid4

from sqlalchemy import and_, exists, func, or_, select, update
from sqlalchemy.orm import aliased, Session, sessionmaker

from apps.api.dy_api.db import session_scope
from apps.api.dy_api.models import (
    JobEvent,
    JobRun,
    SettlementProjectionActive,
    SettlementProjectionGeneration,
)
from apps.worker.legacy_projection_bootstrap import (
    CompactionResult,
    CompactionThresholdConfig,
    ResourceGateConfig,
    compact_projection_metadata,
)
from apps.worker.pipeline import sanitize_error_message
from apps.worker.projection_publish import (
    _COMPACTION_ONCE_PREFIX,
    publish_settlement_compaction,
)
from apps.worker.repositories import (
    HEAVY_SYNC_CLAIM_LOCK_KEY,
    heavy_sync_rate_limit_cooldown_active,
    resource_admission_allows_job,
)
from apps.worker.resource_monitor import current_resource_decision

SETTLEMENT_COMPACTION_JOB_NAME = "settlement_compaction"
SETTLEMENT_COMPACTION_PROTOCOL = "dydata-settlement-compaction-runner-v1"
DEFAULT_SETTLEMENT_COMPACTION_LEASE = timedelta(minutes=30)
DEFAULT_SETTLEMENT_COMPACTION_MAX_ATTEMPTS = 3
_SETTLEMENT_COMPACTION_CLAIM_PROCESS_LOCK = Lock()

MIN_COMPACTION_LINEAGE_DEPTH = 1
COMPACTION_BATCH_SIZE_LIMIT = 400
_RESOURCE_KEYS = (
    "max_manifest_rows",
    "max_estimated_write_bytes",
    "max_estimated_wal_bytes",
    "observed_disk_headroom_bytes",
    "min_disk_headroom_bytes",
)


class SettlementCompactionLeaseLost(RuntimeError):
    """The runner may no longer mutate state after losing its durable claim."""


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _database_utcnow(session: Session) -> datetime:
    if session.get_bind().dialect.name == "postgresql":
        value = session.scalar(select(func.clock_timestamp()))
    else:
        value = session.scalar(select(func.current_timestamp()))
    if isinstance(value, datetime):
        return _as_utc(value)
    return datetime.now(timezone.utc)


def settlement_compaction_job_id(base_generation_id: str) -> str:
    """Stable idempotent job identity for one compaction base."""

    if not isinstance(base_generation_id, str) or not base_generation_id:
        raise ValueError("base_generation_id must be a non-empty string")
    digest = hashlib.sha256(
        f"{SETTLEMENT_COMPACTION_PROTOCOL}|{base_generation_id}".encode("utf-8")
    ).hexdigest()[:32]
    return f"settlement-compaction-{digest}"


def _resource_limits_from_metadata(metadata: dict[str, object]) -> ResourceGateConfig:
    values: dict[str, int] = {}
    for key in _RESOURCE_KEYS:
        raw = metadata.get(key)
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            raise RuntimeError("settlement compaction job resource limits are invalid")
        values[key] = raw
    return ResourceGateConfig(**values)


def enqueue_settlement_compaction_job(
    factory: sessionmaker,
    *,
    base_generation_id: str,
    batch_size: int,
    resource_limits: ResourceGateConfig,
) -> str:
    """Queue one idempotent compaction job against the active settlement head."""

    if (
        isinstance(batch_size, bool)
        or not isinstance(batch_size, int)
        or not 1 <= batch_size <= COMPACTION_BATCH_SIZE_LIMIT
    ):
        raise ValueError("batch_size must be an integer between 1 and 400")
    if not isinstance(resource_limits, ResourceGateConfig):
        raise TypeError("resource_limits must be a ResourceGateConfig")
    job_id = settlement_compaction_job_id(base_generation_id)
    now = datetime.now(timezone.utc)
    metadata: dict[str, object] = {
        "protocol": SETTLEMENT_COMPACTION_PROTOCOL,
        "base_generation_id": base_generation_id,
        "batch_size": batch_size,
        **{key: int(getattr(resource_limits, key)) for key in _RESOURCE_KEYS},
    }
    with session_scope(factory) as session:
        active = session.get(SettlementProjectionActive, "settlement")
        if active is None or active.generation_id != base_generation_id:
            raise ValueError(
                "compaction base is not the active settlement generation"
            )
        head = session.get(SettlementProjectionGeneration, base_generation_id)
        if head is None or head.state != "published":
            raise ValueError("compaction base generation is not published")
        if head.generation_kind == "compact":
            raise ValueError("settlement head is already compact")
        if (int(head.lineage_depth or 0)) < MIN_COMPACTION_LINEAGE_DEPTH:
            raise ValueError("compaction base lineage depth is below the threshold")
        existing = session.get(JobRun, job_id)
        if existing is not None:
            if (existing.metadata_json or {}).get("base_generation_id") != (
                base_generation_id
            ):
                raise RuntimeError("settlement compaction job identity conflicts")
            return job_id
        session.add(
            JobRun(
                job_id=job_id,
                job_name=SETTLEMENT_COMPACTION_JOB_NAME,
                status="queued",
                started_at=now,
                success_count=0,
                failed_count=0,
                error_message=None,
                metadata_json=metadata,
                job_kind=None,
                execution_slot="heavy_sync",
                current_stage=None,
                attempt_count=0,
                max_attempts=DEFAULT_SETTLEMENT_COMPACTION_MAX_ATTEMPTS,
                lease_epoch=0,
            )
        )
    return job_id


def _no_other_running_heavy_slot() -> Any:
    other = aliased(JobRun)
    return ~exists(
        select(1).where(
            other.job_id != JobRun.job_id,
            other.execution_slot == "heavy_sync",
            other.status == "running",
        )
    )


def claim_settlement_compaction_job(
    factory: sessionmaker,
    *,
    lease_duration: timedelta = DEFAULT_SETTLEMENT_COMPACTION_LEASE,
    job_id: str | None = None,
    resource_decision: Any | None = None,
) -> tuple[str, str] | None:
    """Claim one compaction job through the shared heavy-slot control plane.

    Claims serialize on the same ``HEAVY_SYNC_CLAIM_LOCK_KEY`` advisory lock the
    heavy worker uses, honour the upstream rate-limit cooldown and the resource
    admission decision, and the running-slot mutation is guarded by the global
    "no other running heavy_sync job" predicate, which the database unique
    partial index enforces as a hard backstop.
    """

    if lease_duration <= timedelta(0):
        raise ValueError("lease_duration must be greater than zero")
    if resource_decision is None:
        # Never default to an implicit ALLOW: resolve the real guard decision.
        # With the guard enabled but the monitor missing or stale this is STOP,
        # so maintenance work cannot bypass resource admission.
        resource_decision = current_resource_decision()
    with factory() as probe:
        dialect_name = probe.get_bind().dialect.name
    process_lock_held = False
    if dialect_name != "postgresql":
        process_lock_held = _SETTLEMENT_COMPACTION_CLAIM_PROCESS_LOCK.acquire(
            blocking=False
        )
        if not process_lock_held:
            return None
    try:
        with session_scope(factory) as session:
            if dialect_name == "postgresql":
                acquired = bool(
                    session.scalar(
                        select(func.pg_try_advisory_xact_lock(
                            HEAVY_SYNC_CLAIM_LOCK_KEY
                        ))
                    )
                )
                if not acquired:
                    return None
            if heavy_sync_rate_limit_cooldown_active(session):
                return None
            no_other_running = _no_other_running_heavy_slot()
            if dialect_name == "postgresql":
                clock = func.statement_timestamp()
                expired_running = and_(
                    JobRun.status == "running",
                    JobRun.lease_expires_at.is_not(None),
                    JobRun.lease_expires_at <= clock,
                )
            else:
                now = _database_utcnow(session)
                expired_running = and_(
                    JobRun.status == "running",
                    JobRun.lease_expires_at.is_not(None),
                    JobRun.lease_expires_at <= now,
                )
            attempt_available = (
                func.coalesce(JobRun.attempt_count, 0)
                < (
                    func.coalesce(JobRun.max_attempts, 3)
                    + func.coalesce(JobRun.quota_pause_count, 0)
                )
            )
            statement = (
                select(JobRun)
                .where(
                    JobRun.job_name == SETTLEMENT_COMPACTION_JOB_NAME,
                    JobRun.execution_slot == "heavy_sync",
                    or_(JobRun.status == "queued", expired_running),
                    no_other_running,
                    attempt_available,
                )
                .order_by(JobRun.started_at, JobRun.job_id)
                .limit(1)
            )
            if job_id is not None:
                statement = statement.where(JobRun.job_id == job_id)
            job = session.scalar(statement)
            if job is None:
                return None
            if not resource_admission_allows_job(job, resource_decision):
                return None
            claim_id = f"settlement-compaction-{uuid4().hex}"
            claim_time = _database_utcnow(session)
            observed_status = job.status
            observed_attempt_count = job.attempt_count
            attempt_count = max(0, int(observed_attempt_count or 0)) + 1
            max_attempts = max(
                1,
                min(
                    DEFAULT_SETTLEMENT_COMPACTION_MAX_ATTEMPTS,
                    int(
                        job.max_attempts or DEFAULT_SETTLEMENT_COMPACTION_MAX_ATTEMPTS
                    ),
                ),
            )
            metadata = dict(job.metadata_json or {})
            metadata.update(
                {
                    "attemptCount": attempt_count,
                    "claimId": claim_id,
                    "claimedAt": claim_time.isoformat(),
                    "executor": "worker",
                    "stage": "CLAIMED",
                }
            )
            result = session.execute(
                update(JobRun)
                .where(
                    JobRun.job_id == job.job_id,
                    JobRun.job_name == SETTLEMENT_COMPACTION_JOB_NAME,
                    JobRun.execution_slot == "heavy_sync",
                    JobRun.status == observed_status,
                    (
                        JobRun.attempt_count.is_(None)
                        if observed_attempt_count is None
                        else JobRun.attempt_count == observed_attempt_count
                    ),
                    no_other_running,
                )
                .values(
                    status="running",
                    started_at=claim_time,
                    finished_at=None,
                    success_count=0,
                    failed_count=0,
                    error_message=None,
                    claim_token=claim_id,
                    lease_expires_at=claim_time + lease_duration,
                    heartbeat_at=claim_time,
                    next_retry_at=None,
                    state_updated_at=claim_time,
                    attempt_count=attempt_count,
                    max_attempts=max_attempts,
                    lease_owner="settlement_compaction_worker",
                    progress_current=0,
                    rows_read=0,
                    rows_written=0,
                    error_code=None,
                    error_summary=None,
                    metadata_json=metadata,
                )
                .execution_options(synchronize_session=False)
            )
            if result.rowcount != 1:
                return None
            return job.job_id, claim_id
    finally:
        if process_lock_held:
            _SETTLEMENT_COMPACTION_CLAIM_PROCESS_LOCK.release()


def _renew_settlement_compaction_lease(
    factory: sessionmaker,
    *,
    job_id: str,
    claim_id: str,
    lease_duration: timedelta,
) -> bool:
    with session_scope(factory) as session:
        now = _database_utcnow(session)
        result = session.execute(
            update(JobRun)
            .where(
                JobRun.job_id == job_id,
                JobRun.job_name == SETTLEMENT_COMPACTION_JOB_NAME,
                JobRun.status == "running",
                JobRun.claim_token == claim_id,
                JobRun.lease_expires_at > now,
            )
            .values(
                lease_expires_at=now + lease_duration,
                heartbeat_at=now,
                state_updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        return result.rowcount == 1


@contextmanager
def _compaction_heartbeat_watchdog(
    factory: sessionmaker,
    *,
    job_id: str,
    claim_id: str,
    lease_duration: timedelta,
    heartbeat_interval_seconds: float | None = None,
) -> Iterator[Callable[[str, int, int | None], None]]:
    lease_seconds = lease_duration.total_seconds()
    if lease_seconds <= 0:
        raise ValueError("lease_duration must be greater than zero")
    interval = (
        heartbeat_interval_seconds
        if heartbeat_interval_seconds is not None
        else min(60.0, lease_seconds / 3.0)
    )
    if interval <= 0 or interval > lease_seconds / 3.0:
        raise ValueError("heartbeat_interval_seconds must be within the lease")
    stop_event = Event()

    def renew() -> bool:
        try:
            return _renew_settlement_compaction_lease(
                factory,
                job_id=job_id,
                claim_id=claim_id,
                lease_duration=lease_duration,
            )
        except Exception:
            return False

    def watch() -> None:
        while not stop_event.wait(interval):
            if not renew():
                return

    if not renew():
        raise SettlementCompactionLeaseLost(
            "settlement compaction claim was lost before execution"
        )
    watchdog = Thread(
        target=watch,
        name=f"settlement-compaction-heartbeat-{job_id}",
        daemon=True,
    )
    watchdog.start()
    try:
        yield lambda stage, current, total: None
    finally:
        stop_event.set()
        watchdog.join(timeout=max(1.0, interval * 2.0))


def _compaction_event_id(job_id: str, key: str) -> str:
    suffix = hashlib.sha256(f"{job_id}|{key}".encode("utf-8")).hexdigest()
    return f"event-settlement-compaction-{suffix}"


def _record_compaction_event(
    session: Session,
    *,
    job: JobRun,
    event_type: str,
    reason: str,
    payload: dict[str, object],
) -> None:
    once_key = f"{SETTLEMENT_COMPACTION_PROTOCOL}:{event_type}:{job.job_id}"
    existing = session.scalar(
        select(JobEvent).where(
            JobEvent.job_id == job.job_id,
            JobEvent.idempotency_key == once_key,
        )
    )
    if existing is not None:
        return
    session.add(
        JobEvent(
            event_id=_compaction_event_id(job.job_id, event_type),
            job_id=job.job_id,
            stage_run_id=None,
            attempt_id=None,
            event_type=event_type,
            from_status=job.status,
            to_status=job.status,
            actor_type="worker" if job.lease_owner else "system",
            actor_id=job.lease_owner,
            reason=reason,
            idempotency_key=once_key,
            payload_json=payload,
            occurred_at=datetime.now(timezone.utc),
        )
    )


def _load_claimed_job(
    session: Session, *, job_id: str, claim_id: str, require_live_lease: bool
) -> JobRun:
    statement = select(JobRun).where(JobRun.job_id == job_id)
    if session.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    job = session.scalar(statement.execution_options(populate_existing=True))
    if require_live_lease:
        now = _database_utcnow(session)
        lease_valid = (
            job is not None
            and job.lease_expires_at is not None
            and _as_utc(job.lease_expires_at) > now
        )
    else:
        lease_valid = True
    if (
        job is None
        or job.job_name != SETTLEMENT_COMPACTION_JOB_NAME
        or job.status != "running"
        or job.claim_token != claim_id
        or not lease_valid
    ):
        raise SettlementCompactionLeaseLost(
            "settlement compaction claim is no longer active"
        )
    return job


def _finish_in_session(
    session: Session,
    job: JobRun,
    *,
    outcome: str,
    generation_id: str | None,
) -> None:
    now = _database_utcnow(session)
    metadata = dict(job.metadata_json or {})
    metadata.update(
        {
            "stage": "SUCCEEDED",
            "claimId": None,
            "completedAt": now.isoformat(),
            "result": {
                "outcome": outcome,
                "generationId": generation_id,
            },
        }
    )
    job.status = "success"
    job.finished_at = now
    job.success_count = 1
    job.claim_token = None
    job.lease_expires_at = None
    job.error_message = None
    job.metadata_json = metadata
    _record_compaction_event(
        session,
        job=job,
        event_type="settlement_compaction_completed",
        reason="settlement compaction job finished",
        payload={"outcome": outcome, "generation_id": generation_id},
    )


def _find_publication_evidence(
    session: Session, *, job_id: str, base_generation_id: str
) -> str | None:
    """Return the compact generation this job already published, if any.

    The publisher's one-time audit event is the durable crash evidence.  When
    the event exists the referenced generation must be a published compact head
    for the same base; anything else is treated as corrupted evidence and fails
    closed instead of being papered over.
    """

    events = list(
        session.scalars(
            select(JobEvent).where(
                JobEvent.job_id == job_id,
                JobEvent.event_type == "settlement_projection_published",
                JobEvent.idempotency_key.like(_COMPACTION_ONCE_PREFIX + "%"),
            )
        )
    )
    if not events:
        return None
    generation_ids: set[str] = set()
    for event in events:
        payload = event.payload_json if isinstance(event.payload_json, dict) else {}
        generation_id = payload.get("generation_id")
        evidence_base = payload.get("base_generation_id")
        if not isinstance(generation_id, str) or not generation_id:
            raise RuntimeError("settlement compaction publication evidence is invalid")
        if evidence_base != base_generation_id:
            raise RuntimeError(
                "settlement compaction publication evidence names another base"
            )
        generation_ids.add(generation_id)
    if len(generation_ids) != 1:
        raise RuntimeError("settlement compaction publication evidence conflicts")
    generation_id = next(iter(generation_ids))
    generation = session.get(SettlementProjectionGeneration, generation_id)
    if (
        generation is None
        or generation.generation_kind != "compact"
        or generation.state != "published"
        or generation.compaction_base_generation_id != base_generation_id
    ):
        raise RuntimeError("settlement compaction publication evidence is stale")
    return generation_id


def _fail_settlement_compaction_job(
    factory: sessionmaker,
    *,
    job_id: str,
    claim_id: str,
    error_message: str,
) -> bool:
    """Terminalize a failed attempt only while the claim is still live.

    An executor whose lease has expired must never overwrite the job state;
    the row stays untouched for the lease-expiry reclaim path.
    """

    with session_scope(factory) as session:
        statement = select(JobRun).where(JobRun.job_id == job_id)
        if session.get_bind().dialect.name == "postgresql":
            statement = statement.with_for_update()
        job = session.scalar(statement.execution_options(populate_existing=True))
        now = _database_utcnow(session)
        if (
            job is None
            or job.job_name != SETTLEMENT_COMPACTION_JOB_NAME
            or job.status != "running"
            or job.claim_token != claim_id
            or job.lease_expires_at is None
            or _as_utc(job.lease_expires_at) <= now
        ):
            return False
        attempt_count = max(0, int(job.attempt_count or 0))
        max_attempts = max(
            1,
            min(
                DEFAULT_SETTLEMENT_COMPACTION_MAX_ATTEMPTS,
                int(
                    job.max_attempts or DEFAULT_SETTLEMENT_COMPACTION_MAX_ATTEMPTS
                ),
            ),
        )
        retry = attempt_count < max_attempts
        metadata = dict(job.metadata_json or {})
        metadata.update(
            {
                "stage": "RETRY_QUEUED" if retry else "FAILED",
                "claimId": None,
                "failedAt": now.isoformat(),
            }
        )
        job.status = "queued" if retry else "failed"
        job.finished_at = None if retry else now
        job.claim_token = None
        job.lease_expires_at = None
        job.error_code = "settlement_compaction_failed"
        job.error_summary = sanitize_error_message(error_message)[:500]
        job.error_message = job.error_summary
        job.metadata_json = metadata
        _record_compaction_event(
            session,
            job=job,
            event_type="settlement_compaction_failed",
            reason="settlement compaction job failed",
            payload={
                "retry": retry,
                "error": job.error_summary,
            },
        )
        return True


def _fence_settlement_compaction_commit(
    session: Session, *, job_id: str, claim_id: str
) -> None:
    """Fence one builder-owned write commit with the live claim.

    Mirrors the settlement rebuild commit fence: the claim (status, token and
    lease window) is re-verified inside the same transaction, right before the
    data commit.  A runner whose lease expired can therefore never keep writing
    compaction rows after another executor reclaimed the job.
    """

    statement = select(JobRun).where(JobRun.job_id == job_id)
    if session.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    job = session.scalar(statement.execution_options(populate_existing=True))
    now = _database_utcnow(session)
    if (
        job is None
        or job.job_name != SETTLEMENT_COMPACTION_JOB_NAME
        or job.status != "running"
        or job.claim_token != claim_id
        or job.lease_expires_at is None
        or _as_utc(job.lease_expires_at) <= now
    ):
        raise SettlementCompactionLeaseLost(
            "settlement compaction claim was lost during a builder commit"
        )


def _claim_fenced_builder_factory(
    factory: sessionmaker,
    *,
    job_id: str,
    claim_id: str,
) -> Callable[[], Session]:
    """Wrap the builder factory so every session commit is claim-fenced."""

    def build() -> Session:
        session = factory()
        original_commit = session.commit

        def fenced_commit() -> None:
            _fence_settlement_compaction_commit(
                session, job_id=job_id, claim_id=claim_id
            )
            original_commit()

        session.commit = fenced_commit  # type: ignore[method-assign]
        return session

    return build


def run_settlement_compaction_job(
    *,
    job_id: str,
    factory: sessionmaker,
    claim_id: str,
    lease_duration: timedelta = DEFAULT_SETTLEMENT_COMPACTION_LEASE,
    heartbeat_interval_seconds: float | None = None,
) -> dict[str, object]:
    """Claim-verified compaction build plus fenced publication for one job."""

    with session_scope(factory) as session:
        job = _load_claimed_job(
            session, job_id=job_id, claim_id=claim_id, require_live_lease=True
        )
        metadata = dict(job.metadata_json or {})
        base_generation_id = metadata.get("base_generation_id")
        batch_size = metadata.get("batch_size")
        if not isinstance(base_generation_id, str) or not base_generation_id:
            raise RuntimeError("settlement compaction job base identity is invalid")
        if (
            isinstance(batch_size, bool)
            or not isinstance(batch_size, int)
            or not 1 <= batch_size <= COMPACTION_BATCH_SIZE_LIMIT
        ):
            raise RuntimeError("settlement compaction job batch size is invalid")
        resource_limits = _resource_limits_from_metadata(metadata)
        evidence = _find_publication_evidence(
            session, job_id=job_id, base_generation_id=base_generation_id
        )
        if evidence is not None:
            # Crash after the publish transaction committed but before the
            # success transition: recover idempotently without re-running the
            # builder (its base is no longer the active pointer).
            _finish_in_session(
                session,
                job,
                outcome="already_published",
                generation_id=evidence,
            )
            return {
                "status": "success",
                "outcome": "already_published",
                "generation_id": evidence,
            }

    try:
        with _compaction_heartbeat_watchdog(
            factory,
            job_id=job_id,
            claim_id=claim_id,
            lease_duration=lease_duration,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
        ):
            # Every builder-owned write transaction re-verifies the live claim
            # before its commit, so a runner that lost its lease (and whose
            # watchdog thread has exited) can never keep writing the same
            # compaction generation after another executor reclaimed the job.
            builder_factory = _claim_fenced_builder_factory(
                factory, job_id=job_id, claim_id=claim_id
            )
            result: CompactionResult = compact_projection_metadata(
                builder_factory,
                base_generation_id=base_generation_id,
                threshold_config=CompactionThresholdConfig(
                    minimum_lineage_depth=MIN_COMPACTION_LINEAGE_DEPTH,
                    batch_size=batch_size,
                ),
                resource_limits=resource_limits,
            )
            if result.status == "not_needed":
                with session_scope(factory) as session:
                    job = _load_claimed_job(
                        session,
                        job_id=job_id,
                        claim_id=claim_id,
                        require_live_lease=True,
                    )
                    _finish_in_session(
                        session, job, outcome="not_needed", generation_id=None
                    )
                return {
                    "status": "success",
                    "outcome": "not_needed",
                    "generation_id": None,
                }
            if (
                result.status in {"ready", "already_ready"}
                and result.generation_id is not None
            ):
                if result.manifest_checksum is None:
                    raise RuntimeError("ready compaction checksum is missing")
                with session_scope(factory) as session:
                    compact = session.get(
                        SettlementProjectionGeneration, result.generation_id
                    )
                    if compact is None or compact.input_fingerprint is None:
                        raise RuntimeError("ready compaction generation disappeared")
                    publish_settlement_compaction(
                        session,
                        job_id=job_id,
                        claim_id=claim_id,
                        generation_id=result.generation_id,
                        input_fingerprint=compact.input_fingerprint,
                        manifest_checksum=result.manifest_checksum,
                    )
                    job = session.get(JobRun, job_id)
                    if job is None:
                        raise SettlementCompactionLeaseLost(
                            "settlement compaction claim was lost during publication"
                        )
                    # Same-transaction success: the pointer promotion and the
                    # job success commit atomically under the publisher's lock
                    # order, so no crash window can split them.
                    _finish_in_session(
                        session,
                        job,
                        outcome="published",
                        generation_id=result.generation_id,
                    )
                outcome = "published"
                generation_id = result.generation_id
            elif result.status == "resource_guard":
                raise RuntimeError(
                    f"settlement compaction resource guard: {result.failure_code}"
                )
            else:
                raise RuntimeError(
                    f"unexpected compaction status: {result.status}"
                )
        return {
            "status": "success",
            "outcome": outcome,
            "generation_id": generation_id,
        }
    except Exception as exc:
        _fail_settlement_compaction_job(
            factory,
            job_id=job_id,
            claim_id=claim_id,
            error_message=str(exc),
        )
        raise


__all__ = [
    "DEFAULT_SETTLEMENT_COMPACTION_LEASE",
    "SettlementCompactionLeaseLost",
    "SETTLEMENT_COMPACTION_JOB_NAME",
    "SETTLEMENT_COMPACTION_PROTOCOL",
    "claim_settlement_compaction_job",
    "enqueue_settlement_compaction_job",
    "run_settlement_compaction_job",
    "settlement_compaction_job_id",
]
