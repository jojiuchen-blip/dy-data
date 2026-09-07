from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Event, Lock, Thread
from uuid import uuid4

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.db import session_scope
from apps.api.dy_api.models import (
    JobEvent,
    JobRun,
    SettlementProjectionActive,
    SettlementProjectionGeneration,
    SettlementProjectionPartitionManifest,
    SettlementStatement,
    utcnow,
)
from apps.worker.projection_publish import (
    publish_settlement_rebuild,
    settlement_rebuild_publish_once_key,
)
from apps.worker.pipeline import sanitize_error_message
from apps.worker.settlement import (
    FORMAL_SETTLEMENT_START,
    SettlementStats,
    _projection_months,
    _sparse_base_chain,
    build_settlement_sparse_overlay,
    mark_settlement_sparse_overlay_ready,
    rebuild_settlement,
)


SETTLEMENT_REBUILD_SPARSE_BATCH_SIZE = 200
SETTLEMENT_REBUILD_JOB_NAME = "settlement_rebuild"
DEFAULT_SETTLEMENT_REBUILD_LEASE = timedelta(minutes=15)
DEFAULT_SETTLEMENT_REBUILD_MAX_ATTEMPTS = 3
SETTLEMENT_REBUILD_CLAIM_LOCK_KEY = 0x4459444154410087
_SETTLEMENT_REBUILD_CLAIM_PROCESS_LOCK = Lock()


class SettlementRebuildLeaseLost(RuntimeError):
    """The rebuild may no longer mutate state after losing its durable claim."""


@dataclass(frozen=True)
class _LineageRefreshPlan:
    job_id: str
    generation_id: str
    base_generation_id: str
    affected_months: tuple[str, ...]
    input_fingerprint: str


def _database_utcnow(session: Session) -> datetime:
    if session.get_bind().dialect.name == "sqlite":
        value = session.scalar(select(func.strftime("%Y-%m-%d %H:%M:%f", "now")))
        return _as_utc(datetime.fromisoformat(value))
    clock = (
        func.clock_timestamp()
        if session.get_bind().dialect.name == "postgresql"
        else func.current_timestamp()
    )
    value = session.scalar(select(clock))
    return _as_utc(value) if isinstance(value, datetime) else _as_utc(utcnow())


def _assert_active_settlement_rebuild_claim(
    session: Session,
    *,
    job_id: str,
    claim_id: str,
) -> JobRun:
    statement = select(JobRun).where(JobRun.job_id == job_id)
    if session.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    job = session.scalar(statement.execution_options(populate_existing=True))
    now = _database_utcnow(session)
    lease_expires_at = (
        _as_utc(job.lease_expires_at)
        if job is not None and job.lease_expires_at is not None
        else None
    )
    if (
        job is None
        or job.job_name != SETTLEMENT_REBUILD_JOB_NAME
        or job.status != "running"
        or job.claim_token != claim_id
        or lease_expires_at is None
        or lease_expires_at <= now
    ):
        raise SettlementRebuildLeaseLost(
            "settlement rebuild claim is no longer active"
        )
    return job


@contextmanager
def _settlement_rebuild_claim_transaction(
    factory: sessionmaker,
) -> Iterator[Session | None]:
    """Serialize only recovery selection and claim, never the long rebuild."""

    with factory() as probe:
        dialect_name = probe.get_bind().dialect.name

    process_lock_acquired = False
    if dialect_name != "postgresql":
        process_lock_acquired = _SETTLEMENT_REBUILD_CLAIM_PROCESS_LOCK.acquire(
            blocking=False
        )
        if not process_lock_acquired:
            yield None
            return

    try:
        with session_scope(factory) as session:
            if dialect_name == "postgresql":
                acquired = bool(
                    session.scalar(
                        text("SELECT pg_try_advisory_xact_lock(:lock_key)"),
                        {"lock_key": SETTLEMENT_REBUILD_CLAIM_LOCK_KEY},
                    )
                )
                if not acquired:
                    yield None
                    return
            yield session
    finally:
        if process_lock_acquired:
            _SETTLEMENT_REBUILD_CLAIM_PROCESS_LOCK.release()


def _claim_settlement_rebuild_in_session(
    session: Session,
    *,
    job_id: str,
    claim_time: datetime,
    lease_duration: timedelta,
) -> str | None:
    claim_id = f"settlement-rebuild-{uuid4().hex}"
    job = session.get(JobRun, job_id)
    if (
        job is None
        or job.job_name != SETTLEMENT_REBUILD_JOB_NAME
        or job.status != "queued"
    ):
        return None

    observed_attempt_count = job.attempt_count
    attempt_count = max(0, int(observed_attempt_count or 0)) + 1
    max_attempts = max(
        1,
        min(
            DEFAULT_SETTLEMENT_REBUILD_MAX_ATTEMPTS,
            int(job.max_attempts or DEFAULT_SETTLEMENT_REBUILD_MAX_ATTEMPTS),
        ),
    )
    if attempt_count > max_attempts:
        return None

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
            JobRun.job_id == job_id,
            JobRun.job_name == SETTLEMENT_REBUILD_JOB_NAME,
            JobRun.status == "queued",
            (
                JobRun.attempt_count.is_(None)
                if observed_attempt_count is None
                else JobRun.attempt_count == observed_attempt_count
            ),
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
            lease_owner="settlement_rebuild_worker",
            current_stage="settle",
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
    return claim_id if result.rowcount == 1 else None


def claim_latest_settlement_rebuild_job(
    factory: sessionmaker,
    *,
    claimed_at: datetime | None = None,
    lease_duration: timedelta = DEFAULT_SETTLEMENT_REBUILD_LEASE,
) -> tuple[str, str, tuple[str, ...]] | None:
    """Claim the newest queued snapshot, superseding older pending retries too."""

    if lease_duration <= timedelta(0):
        raise ValueError("lease_duration must be greater than zero")
    with _settlement_rebuild_claim_transaction(factory) as session:
        if session is None:
            return None
        running = session.scalar(
            select(JobRun.job_id)
            .where(
                JobRun.job_name == SETTLEMENT_REBUILD_JOB_NAME,
                JobRun.status == "running",
            )
            .limit(1)
        )
        if running is not None:
            return None

        statement = (
            select(JobRun)
            .where(
                JobRun.job_name == SETTLEMENT_REBUILD_JOB_NAME,
                JobRun.status.in_(("queued", "retry_wait")),
            )
            .order_by(JobRun.started_at, JobRun.job_id)
        )
        if session.get_bind().dialect.name == "postgresql":
            statement = statement.with_for_update()
        pending_jobs = list(session.scalars(statement))
        queued_jobs = [job for job in pending_jobs if job.status == "queued"]
        if not queued_jobs:
            return None

        claim_time = (
            _as_utc(claimed_at)
            if claimed_at is not None
            else _database_utcnow(session)
        )
        selected = queued_jobs[-1]
        claim_id = _claim_settlement_rebuild_in_session(
            session,
            job_id=selected.job_id,
            claim_time=claim_time,
            lease_duration=lease_duration,
        )
        if claim_id is None:
            return None

        superseded_ids: list[str] = []
        for obsolete in pending_jobs[:pending_jobs.index(selected)]:
            metadata = dict(obsolete.metadata_json or {})
            metadata.update(
                {
                    "stage": "SUPERSEDED",
                    "claimId": None,
                    "superseded_by": selected.job_id,
                    "settlement_projection": {
                        "status": "superseded",
                        "superseded_by": selected.job_id,
                    },
                }
            )
            obsolete.status = "success"
            obsolete.success_count = 0
            obsolete.failed_count = 0
            obsolete.error_message = None
            obsolete.finished_at = claim_time
            obsolete.claim_token = None
            obsolete.lease_expires_at = None
            obsolete.heartbeat_at = claim_time
            obsolete.next_retry_at = None
            obsolete.state_updated_at = claim_time
            obsolete.lease_owner = None
            obsolete.current_stage = None
            obsolete.error_code = None
            obsolete.error_summary = None
            obsolete.metadata_json = metadata
            superseded_ids.append(obsolete.job_id)

        return selected.job_id, claim_id, tuple(superseded_ids)


def _lineage_refresh_plan(
    factory: sessionmaker, *, job_id: str
) -> _LineageRefreshPlan | None:
    with session_scope(factory) as session:
        active = session.get(SettlementProjectionActive, "settlement")
        if active is None or active.generation_id is None:
            # A nullable pointer means the legacy root is authoritative. The
            # full rebuild already refreshed that root, so no overlay is needed.
            return None

        published_for_job = session.scalar(
            select(SettlementProjectionGeneration).where(
                SettlementProjectionGeneration.generation_id
                == active.generation_id,
                SettlementProjectionGeneration.state == "published",
                SettlementProjectionGeneration.source_job_id == job_id,
            )
        )
        if published_for_job is not None:
            # The rebuild can be retried after the worker has already
            # published its overlay.  Treat the durable published generation
            # as the idempotency record and do not use it as its own base.
            return None

        base_generation_id = active.generation_id
        _base, lineage_ids = _sparse_base_chain(session, base_generation_id)
        candidate_months = set(_projection_months(session))
        manifest_keys = session.scalars(
            select(SettlementProjectionPartitionManifest.partition_key).where(
                SettlementProjectionPartitionManifest.generation_id.in_(lineage_ids),
                SettlementProjectionPartitionManifest.artifact == "monthly",
            )
        )
        formal_start = FORMAL_SETTLEMENT_START.strftime("%Y-%m")
        for partition_key in manifest_keys:
            value = str(partition_key)
            if value >= formal_start:
                candidate_months.add(value)

        locked_months = set(
            session.scalars(
                select(SettlementStatement.statement_month).where(
                    SettlementStatement.statement_status == 4
                )
            )
        )
        affected_months = tuple(
            sorted(month for month in candidate_months if month not in locked_months)
        )
        if not affected_months:
            return None

        fingerprint_payload = {
            "protocol": "settlement-admin-rebuild-lineage-v1",
            "job_id": job_id,
            "base_generation_id": base_generation_id,
            "affected_months": list(affected_months),
        }
        input_fingerprint = hashlib.sha256(
            json.dumps(
                fingerprint_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        generation_id = (
            f"settlement-admin-rebuild:{job_id}:{input_fingerprint[:16]}"
        )
        return _LineageRefreshPlan(
            job_id=job_id,
            generation_id=generation_id,
            base_generation_id=base_generation_id,
            affected_months=affected_months,
            input_fingerprint=input_fingerprint,
        )


def _fence_settlement_rebuild_commit(
    session: Session,
    *,
    job_id: str,
    claim_id: str,
    stage: str,
    lease_duration: timedelta = DEFAULT_SETTLEMENT_REBUILD_LEASE,
) -> None:
    """Fence a data commit with the live claim in the same transaction."""

    del stage, lease_duration
    # Flush may wait for data-row locks; heartbeat renewal remains independent
    # until all pending data has been written and the final claim lock is taken.
    session.flush()
    _assert_active_settlement_rebuild_claim(
        session,
        job_id=job_id,
        claim_id=claim_id,
    )


def _supersede_obsolete_settlement_generations(
    factory: sessionmaker,
    *,
    job_id: str,
    claim_id: str,
    generation_id: str,
    lease_duration: timedelta = DEFAULT_SETTLEMENT_REBUILD_LEASE,
) -> None:
    """Retire incomplete generations left by an earlier attempt of this job."""

    with session_scope(factory) as session:
        if session.get_bind().dialect.name == "postgresql":
            session.execute(text("SET LOCAL lock_timeout = '5s'"))
        obsolete = list(
            session.scalars(
                select(SettlementProjectionGeneration).where(
                    SettlementProjectionGeneration.source_job_id == job_id,
                    SettlementProjectionGeneration.generation_id != generation_id,
                    SettlementProjectionGeneration.state.in_(("staging", "ready")),
                )
            )
        )
        for generation in obsolete:
            generation.state = "superseded"
            generation.failure_code = "SUPERSEDED_BY_RETRY"
            generation.failure_reason = (
                f"Superseded by settlement projection generation {generation_id}."
            )
        _fence_settlement_rebuild_commit(
            session,
            job_id=job_id,
            claim_id=claim_id,
            stage="supersede_obsolete_projection",
            lease_duration=lease_duration,
        )


def refresh_active_settlement_lineage(
    factory: sessionmaker,
    *,
    job_id: str,
    claim_id: str,
    progress_callback: Callable[[str, int, int | None], None] | None = None,
    lease_duration: timedelta = DEFAULT_SETTLEMENT_REBUILD_LEASE,
) -> dict[str, object] | None:
    """Build and publish the active settlement overlay after a full rebuild."""

    plan = _lineage_refresh_plan(factory, job_id=job_id)
    if plan is None:
        _record_settlement_projection_noop(
            factory,
            job_id=job_id,
            claim_id=claim_id,
        )
        return None

    _supersede_obsolete_settlement_generations(
        factory,
        job_id=job_id,
        claim_id=claim_id,
        generation_id=plan.generation_id,
        lease_duration=lease_duration,
    )
    commit_guard = lambda session: _fence_settlement_rebuild_commit(
        session,
        job_id=job_id,
        claim_id=claim_id,
        stage="build_sparse_projection",
        lease_duration=lease_duration,
    )

    build_settlement_sparse_overlay(
        factory,
        generation_id=plan.generation_id,
        base_generation_id=plan.base_generation_id,
        affected_months=plan.affected_months,
        batch_size=SETTLEMENT_REBUILD_SPARSE_BATCH_SIZE,
        input_fingerprint=plan.input_fingerprint,
        source_job_id=job_id,
        commit_guard=commit_guard,
        progress_callback=progress_callback,
    )
    manifest = mark_settlement_sparse_overlay_ready(
        factory,
        generation_id=plan.generation_id,
        base_generation_id=plan.base_generation_id,
        input_fingerprint=plan.input_fingerprint,
        commit_guard=commit_guard,
    )
    if progress_callback is not None:
        progress_callback("certify_sparse_projection", 1, 1)
    with session_scope(factory) as session:
        publication = publish_settlement_rebuild(
            session,
            job_id=job_id,
            claim_id=claim_id,
            generation_id=plan.generation_id,
            base_generation_id=plan.base_generation_id,
            input_fingerprint=plan.input_fingerprint,
            manifest_checksum=manifest.manifest_checksum,
        )
        job = session.get(JobRun, job_id)
        if job is None:  # pragma: no cover - guarded by publication validation
            raise RuntimeError("settlement rebuild job disappeared before metadata update")
        metadata = dict(job.metadata_json or {})
        metadata["settlement_projection"] = {
            "status": "published",
            "generation_id": plan.generation_id,
            "base_generation_id": plan.base_generation_id,
            "input_fingerprint": plan.input_fingerprint,
            "manifest_checksum": manifest.manifest_checksum,
            "affected_months": list(plan.affected_months),
            "manifest_count": manifest.manifest_count,
            "row_count": manifest.row_count,
        }
        job.metadata_json = metadata
        return publication


def _record_settlement_projection_noop(
    factory: sessionmaker,
    *,
    job_id: str,
    claim_id: str,
) -> None:
    with session_scope(factory) as session:
        job = _assert_active_settlement_rebuild_claim(
            session,
            job_id=job_id,
            claim_id=claim_id,
        )

        active = session.get(SettlementProjectionActive, "settlement")
        generation = (
            session.get(SettlementProjectionGeneration, active.generation_id)
            if active is not None and active.generation_id is not None
            else None
        )
        if (
            generation is not None
            and generation.state == "published"
            and generation.source_job_id == job_id
        ):
            marker: dict[str, object] = {
                "status": "published",
                "generation_id": generation.generation_id,
                "manifest_checksum": generation.manifest_checksum,
            }
        elif active is None or active.generation_id is None:
            marker = {"status": "legacy_root"}
        else:
            marker = {
                "status": "no_affected_months",
                "active_generation_id": active.generation_id,
            }
        metadata = dict(job.metadata_json or {})
        metadata["settlement_projection"] = marker
        job.metadata_json = metadata


def reconcile_published_settlement_rebuild(
    session: Session,
    *,
    job: JobRun,
    reconciled_at: datetime,
    recovery_state: str = "RECONCILED_PUBLISHED",
) -> bool:
    """Close a published job even after a later publication advances the head."""

    observed_owner = (job.status, job.claim_token, job.lease_expires_at, job.state_updated_at)
    statement = select(JobRun).where(JobRun.job_id == job.job_id)
    if session.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    job = session.scalar(statement.execution_options(populate_existing=True))
    if job is None or observed_owner != (
        job.status, job.claim_token, job.lease_expires_at, job.state_updated_at,
    ):
        return False

    # The append-only event is committed atomically with pointer promotion.
    # Unlike the current head, it survives later overlays and compaction.
    publication = None
    events = session.scalars(select(JobEvent).where(
        JobEvent.job_id == job.job_id,
        JobEvent.event_type == "settlement_projection_published",
        JobEvent.stage_run_id.is_(None),
    ).order_by(JobEvent.occurred_at.desc(), JobEvent.event_id))
    for event in events:
        payload = event.payload_json or {}
        if not all(isinstance(payload.get(key), str) and payload[key] for key in (
            "generation_id", "base_generation_id", "input_fingerprint", "manifest_checksum",
        )):
            continue
        try:
            once_key = settlement_rebuild_publish_once_key(job.job_id, payload["input_fingerprint"])
        except ValueError:
            continue
        if event.idempotency_key != once_key:
            continue
        published = session.get(SettlementProjectionGeneration, payload["generation_id"])
        if published is not None and (
            published.source_job_id != job.job_id
            or published.state not in {"published", "superseded"}
            or published.base_generation_id != payload["base_generation_id"]
            or published.input_fingerprint != payload["input_fingerprint"]
            or published.manifest_checksum != payload["manifest_checksum"]
        ):
            continue
        publication = {"status": "published", **payload}
        break

    active = session.get(SettlementProjectionActive, "settlement")
    generation = (
        session.get(SettlementProjectionGeneration, active.generation_id)
        if active is not None and active.generation_id is not None
        else None
    )
    legacy_generation_id = f"settlement-admin-rebuild:{job.job_id}"
    if publication is None and (
        generation is None
        or generation.state != "published"
        or not (
            generation.source_job_id == job.job_id
            or (
                generation.source_job_id is None
                and generation.generation_id == legacy_generation_id
            )
        )
    ):
        return False

    if publication is None:
        publication = {
            "status": "published",
            "generation_id": generation.generation_id,
            "base_generation_id": generation.base_generation_id,
            "input_fingerprint": generation.input_fingerprint,
            "manifest_checksum": generation.manifest_checksum,
        }
    completed_at = _as_utc(reconciled_at)
    metadata = dict(job.metadata_json or {})
    metadata.update(
        {
            "stage": "SUCCEEDED",
            "claimId": None,
            "completedAt": completed_at.isoformat(),
            "recoveryState": recovery_state,
            "settlement_projection": publication,
        }
    )
    job.status = "success"
    job.success_count = max(0, int(job.progress_current or job.success_count or 0))
    job.failed_count = 0
    job.error_message = None
    job.finished_at = completed_at
    job.claim_token = None
    job.lease_expires_at = None
    job.heartbeat_at = completed_at
    job.state_updated_at = completed_at
    job.lease_owner = None
    job.current_stage = None
    job.error_code = None
    job.error_summary = None
    job.metadata_json = metadata
    return True


def claim_settlement_rebuild_job(
    factory: sessionmaker,
    *,
    job_id: str,
    claimed_at: datetime | None = None,
    lease_duration: timedelta = DEFAULT_SETTLEMENT_REBUILD_LEASE,
) -> str | None:
    """Atomically claim one queued rebuild and return its fencing token."""

    if lease_duration <= timedelta(0):
        raise ValueError("lease_duration must be greater than zero")
    with _settlement_rebuild_claim_transaction(factory) as session:
        if session is None:
            return None
        running = session.scalar(
            select(JobRun.job_id)
            .where(
                JobRun.job_name == SETTLEMENT_REBUILD_JOB_NAME,
                JobRun.status == "running",
            )
            .limit(1)
        )
        if running is not None:
            return None
        claim_time = (
            _as_utc(claimed_at)
            if claimed_at is not None
            else _database_utcnow(session)
        )
        return _claim_settlement_rebuild_in_session(
            session,
            job_id=job_id,
            claim_time=claim_time,
            lease_duration=lease_duration,
        )


def heartbeat_settlement_rebuild_job(
    factory: sessionmaker,
    *,
    job_id: str,
    claim_id: str,
    stage: str,
    progress_current: int = 0,
    progress_total: int | None = None,
    heartbeat_at: datetime | None = None,
    lease_duration: timedelta = DEFAULT_SETTLEMENT_REBUILD_LEASE,
) -> bool:
    """Renew a claimed rebuild lease while recording bounded progress."""

    if lease_duration <= timedelta(0):
        raise ValueError("lease_duration must be greater than zero")
    with session_scope(factory) as session:
        statement = select(JobRun).where(JobRun.job_id == job_id)
        if session.get_bind().dialect.name == "postgresql":
            statement = statement.with_for_update()
        job = session.scalar(statement.execution_options(populate_existing=True))
        current_time = (
            _as_utc(heartbeat_at)
            if heartbeat_at is not None
            else _database_utcnow(session)
        )
        observed_lease_expires_at = (
            job.lease_expires_at if job is not None else None
        )
        active_lease_expires_at = (
            _as_utc(observed_lease_expires_at)
            if observed_lease_expires_at is not None
            else None
        )
        if (
            job is None
            or job.status != "running"
            or job.claim_token != claim_id
            or active_lease_expires_at is None
            or active_lease_expires_at <= current_time
        ):
            return False
        metadata = dict(job.metadata_json or {})
        metadata["stage"] = stage
        metadata["progress"] = {
            "current": max(0, int(progress_current)),
            "total": (
                max(0, int(progress_total)) if progress_total is not None else None
            ),
        }
        values: dict[str, object] = {
            "heartbeat_at": current_time,
            "lease_expires_at": current_time + lease_duration,
            "state_updated_at": current_time,
            "progress_current": max(0, int(progress_current)),
            "metadata_json": metadata,
        }
        if progress_total is not None:
            values["progress_total"] = max(0, int(progress_total))
        result = session.execute(
            update(JobRun)
            .where(
                JobRun.job_id == job_id,
                JobRun.job_name == SETTLEMENT_REBUILD_JOB_NAME,
                JobRun.status == "running",
                JobRun.claim_token == claim_id,
                JobRun.lease_expires_at == observed_lease_expires_at,
                JobRun.lease_expires_at > current_time,
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        return result.rowcount == 1


@contextmanager
def _settlement_rebuild_heartbeat_watchdog(
    factory: sessionmaker,
    *,
    job_id: str,
    claim_id: str,
    lease_duration: timedelta,
    heartbeat_interval_seconds: float | None = None,
) -> Iterator[Callable[[str, int, int | None], None]]:
    """Renew the lease by elapsed time, even while one stage is silent."""

    lease_seconds = lease_duration.total_seconds()
    if lease_seconds <= 0:
        raise ValueError("lease_duration must be greater than zero")
    interval = (
        heartbeat_interval_seconds
        if heartbeat_interval_seconds is not None
        else min(60.0, lease_seconds / 3.0)
    )
    if interval <= 0:
        raise ValueError("heartbeat_interval_seconds must be greater than zero")
    interval = min(interval, lease_seconds / 3.0)

    stop_event = Event()
    lease_lost = Event()
    state_lock = Lock()
    heartbeat_lock = Lock()
    state: dict[str, object] = {
        "stage": "settle",
        "current": 0,
        "total": None,
    }

    def renew() -> bool:
        if lease_lost.is_set():
            return False
        with heartbeat_lock:
            if lease_lost.is_set():
                return False
            with state_lock:
                stage = str(state["stage"])
                current = int(state["current"])
                total_value = state["total"]
                total = int(total_value) if total_value is not None else None
            try:
                active = heartbeat_settlement_rebuild_job(
                    factory,
                    job_id=job_id,
                    claim_id=claim_id,
                    stage=stage,
                    progress_current=current,
                    progress_total=total,
                    lease_duration=lease_duration,
                )
            except Exception:
                active = False
            if not active:
                lease_lost.set()
            return active

    def report_progress(stage: str, current: int, total: int | None) -> None:
        with state_lock:
            state["stage"] = stage
            state["current"] = max(0, int(current))
            state["total"] = max(0, int(total)) if total is not None else None
        if not renew():
            raise SettlementRebuildLeaseLost(
                "settlement rebuild claim was lost during execution"
            )

    def watch() -> None:
        while not stop_event.wait(interval):
            if not renew():
                return

    report_progress("settle", 0, None)
    watchdog = Thread(
        target=watch,
        name=f"settlement-rebuild-heartbeat-{job_id}",
        daemon=True,
    )
    watchdog.start()
    try:
        yield report_progress
    finally:
        stop_event.set()
        watchdog.join(timeout=max(1.0, interval * 2.0))


def _finish_claimed_settlement_rebuild(
    factory: sessionmaker,
    *,
    job_id: str,
    claim_id: str,
    stats: SettlementStats,
) -> None:
    with session_scope(factory) as session:
        statement = select(JobRun).where(JobRun.job_id == job_id)
        if session.get_bind().dialect.name == "postgresql":
            statement = statement.with_for_update()
        job = session.scalar(statement.execution_options(populate_existing=True))
        finished_at = _database_utcnow(session)
        observed_lease_expires_at = (
            job.lease_expires_at if job is not None else None
        )
        active_lease_expires_at = (
            _as_utc(observed_lease_expires_at)
            if observed_lease_expires_at is not None
            else None
        )
        if (
            job is None
            or job.status != "running"
            or job.claim_token != claim_id
            or active_lease_expires_at is None
            or active_lease_expires_at <= finished_at
        ):
            raise SettlementRebuildLeaseLost(
                "settlement rebuild claim was lost before completion"
            )
        metadata = dict(job.metadata_json or {})
        metadata.update(
            {
                "stage": "SUCCEEDED",
                "claimId": None,
                "completedAt": finished_at.isoformat(),
                "result": {
                    "detailCount": stats.detail_count,
                    "issueCount": stats.issue_count,
                    "rankingCount": stats.ranking_count,
                    "monthlyCount": stats.monthly_count,
                },
            }
        )
        result = session.execute(
            update(JobRun)
            .where(
                JobRun.job_id == job_id,
                JobRun.job_name == SETTLEMENT_REBUILD_JOB_NAME,
                JobRun.status == "running",
                JobRun.claim_token == claim_id,
                JobRun.lease_expires_at == observed_lease_expires_at,
                JobRun.lease_expires_at > finished_at,
            )
            .values(
                status="success",
                success_count=stats.detail_count,
                failed_count=0,
                error_message=None,
                finished_at=finished_at,
                claim_token=None,
                lease_expires_at=None,
                heartbeat_at=finished_at,
                state_updated_at=finished_at,
                lease_owner=None,
                current_stage=None,
                rows_written=stats.detail_count,
                error_code=None,
                error_summary=None,
                metadata_json=metadata,
            )
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            raise SettlementRebuildLeaseLost(
                "settlement rebuild claim was lost before completion"
            )


def _fail_claimed_settlement_rebuild(
    factory: sessionmaker,
    *,
    job_id: str,
    claim_id: str,
    error_message: str,
) -> str | None:
    controlled_error = sanitize_error_message(error_message) or "结算重建失败，请重试。"
    with session_scope(factory) as session:
        statement = select(JobRun).where(JobRun.job_id == job_id)
        if session.get_bind().dialect.name == "postgresql":
            statement = statement.with_for_update()
        job = session.scalar(statement.execution_options(populate_existing=True))
        failed_at = _database_utcnow(session)
        observed_lease_expires_at = (
            job.lease_expires_at if job is not None else None
        )
        active_lease_expires_at = (
            _as_utc(observed_lease_expires_at)
            if observed_lease_expires_at is not None
            else None
        )
        if (
            job is None
            or job.status != "running"
            or job.claim_token != claim_id
            or active_lease_expires_at is None
            or active_lease_expires_at <= failed_at
        ):
            return None
        if reconcile_published_settlement_rebuild(
            session,
            job=job,
            reconciled_at=failed_at,
        ):
            return "reconciled"

        attempt_count = max(0, int(job.attempt_count or 0))
        max_attempts = max(
            1,
            min(
                DEFAULT_SETTLEMENT_REBUILD_MAX_ATTEMPTS,
                int(job.max_attempts or DEFAULT_SETTLEMENT_REBUILD_MAX_ATTEMPTS),
            ),
        )
        retryable = attempt_count < max_attempts
        metadata = dict(job.metadata_json or {})
        metadata.update(
            {
                "stage": "RETRY_QUEUED" if retryable else "FAILED",
                "claimId": None,
                "failureReason": controlled_error,
                "failedAt": failed_at.isoformat(),
                "recoveryState": (
                    "REQUEUED_RETRYABLE_FAILURE"
                    if retryable
                    else "FAILED_ATTEMPTS_EXHAUSTED"
                ),
            }
        )
        result = session.execute(
            update(JobRun)
            .where(
                JobRun.job_id == job_id,
                JobRun.job_name == SETTLEMENT_REBUILD_JOB_NAME,
                JobRun.status == "running",
                JobRun.claim_token == claim_id,
                JobRun.lease_expires_at == observed_lease_expires_at,
                JobRun.lease_expires_at > failed_at,
            )
            .values(
                status="retry_wait" if retryable else "failed",
                next_retry_at=(
                    failed_at + timedelta(seconds=min(300, 30 * 2 ** (attempt_count - 1)))
                    if retryable else None
                ),
                success_count=0,
                failed_count=0 if retryable else 1,
                error_message=controlled_error,
                finished_at=None if retryable else failed_at,
                claim_token=None,
                lease_expires_at=None,
                heartbeat_at=None if retryable else failed_at,
                state_updated_at=failed_at,
                lease_owner=None,
                current_stage=None,
                progress_current=0 if retryable else job.progress_current,
                progress_total=None if retryable else job.progress_total,
                error_code=(
                    "SETTLEMENT_REBUILD_RETRY_QUEUED"
                    if retryable
                    else "SETTLEMENT_REBUILD_ATTEMPTS_EXHAUSTED"
                ),
                error_summary=controlled_error,
                metadata_json=metadata,
            )
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            return None
        return "retry_wait" if retryable else "failed"


def _settlement_rebuild_source_run_id(
    factory: sessionmaker,
    *,
    job_id: str,
) -> str:
    with factory() as session:
        job = session.get(JobRun, job_id)
        metadata = dict(job.metadata_json or {}) if job is not None else {}
    value = metadata.get("source_run_id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return job_id


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def run_settlement_rebuild_job(
    *,
    job_id: str,
    factory: sessionmaker,
    source_run_id: str | None = None,
    claimed_at: datetime | None = None,
    claim_id: str | None = None,
    lease_duration: timedelta = DEFAULT_SETTLEMENT_REBUILD_LEASE,
    heartbeat_interval_seconds: float | None = None,
) -> bool:
    """Run a settlement rebuild and publish its active lineage overlay."""

    if factory is None:
        raise RuntimeError("settlement rebuild requires a database session factory")
    if claim_id is None:
        claim_id = claim_settlement_rebuild_job(
            factory,
            job_id=job_id,
            claimed_at=claimed_at,
            lease_duration=lease_duration,
        )
    if claim_id is None:
        return False
    active_source_run_id = source_run_id or _settlement_rebuild_source_run_id(
        factory, job_id=job_id,
    )
    try:
        with _settlement_rebuild_heartbeat_watchdog(
            factory,
            job_id=job_id,
            claim_id=claim_id,
            lease_duration=lease_duration,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
        ) as report_progress:
            report_progress("settle", 0, None)
            # The legacy rebuild owns one transaction. Sparse overlay partitions
            # intentionally use independent transactions, so they start only after
            # the authoritative fee results are committed and visible.
            with session_scope(factory) as session:
                stats = rebuild_settlement(
                    session,
                    source_run_id=active_source_run_id,
                    progress_callback=report_progress,
                )
                _fence_settlement_rebuild_commit(
                    session, job_id=job_id, claim_id=claim_id,
                    stage="legacy_projection_committed",
                    lease_duration=lease_duration,
                )
            report_progress(
                "publish_projection", stats.detail_count, stats.detail_count
            )
            refresh_active_settlement_lineage(
                factory,
                job_id=job_id,
                claim_id=claim_id,
                progress_callback=report_progress,
                lease_duration=lease_duration,
            )
            report_progress(
                "projection_published", stats.detail_count, stats.detail_count
            )
        _finish_claimed_settlement_rebuild(
            factory, job_id=job_id, claim_id=claim_id, stats=stats,
        )
    except SettlementRebuildLeaseLost:
        raise
    except Exception as exc:
        transition = _fail_claimed_settlement_rebuild(
            factory, job_id=job_id, claim_id=claim_id, error_message=str(exc),
        )
        if transition == "reconciled":
            return True
        raise
    return True


__all__ = [
    "SETTLEMENT_REBUILD_JOB_NAME",
    "SETTLEMENT_REBUILD_SPARSE_BATCH_SIZE",
    "SettlementRebuildLeaseLost",
    "claim_settlement_rebuild_job",
    "heartbeat_settlement_rebuild_job",
    "reconcile_published_settlement_rebuild",
    "refresh_active_settlement_lineage",
    "run_settlement_rebuild_job",
]
