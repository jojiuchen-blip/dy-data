from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, TypeVar
from uuid import uuid4

from sqlalchemy import and_, case, exists, func, literal_column, or_, select, text, update
from sqlalchemy.orm import Session, aliased

from apps.api.dy_api.models import (
    ComponentHeartbeat,
    DataQualityIssue,
    DimAwemeAccount,
    DimSkuProductRule,
    DimStore,
    DimStorePoiMapping,
    JobAttempt,
    JobEvent,
    JobRun,
    RawAwemeBinding,
    RawDouyinClue,
    RawDouyinOrder,
    RawDouyinOrderCoupon,
    RawDouyinVerifyRecord,
    utcnow,
)
from apps.worker.daily_windows import (
    validate_parent_sync_child_identity,
    validate_parent_sync_execution_identity,
)

ModelT = TypeVar("ModelT")


def _merge(
    session: Session,
    model: type[ModelT],
    keys: Mapping[str, Any],
    values: Mapping[str, Any],
    *,
    flush: bool = True,
) -> ModelT:
    payload = {**keys, **values}
    row = session.merge(model(**payload))
    if flush:
        session.flush()
    return row


def upsert_raw_order(session: Session, order_id: str, **values: Any) -> RawDouyinOrder:
    row = session.scalar(select(RawDouyinOrder).where(RawDouyinOrder.order_id == order_id))
    if row is None:
        row = RawDouyinOrder(order_id=order_id, **values)
        session.add(row)
    else:
        for field_name, value in values.items():
            setattr(row, field_name, value)
    session.flush()
    return row


def upsert_raw_clue(session: Session, clue_row_key: str, **values: Any) -> RawDouyinClue:
    return _merge(session, RawDouyinClue, {"clue_row_key": clue_row_key}, values)


def upsert_order_coupon(
    session: Session,
    coupon_id: str,
    order_id: str,
    **values: Any,
) -> RawDouyinOrderCoupon:
    order = session.scalar(select(RawDouyinOrder).where(RawDouyinOrder.order_id == order_id))
    if order is None:
        raise ValueError(f"raw order does not exist: order_id={order_id}")

    row = session.scalar(
        select(RawDouyinOrderCoupon).where(RawDouyinOrderCoupon.coupon_id == coupon_id)
    )
    payload = {"order_id": order_id, "raw_order_id": order.id, **values}
    if row is None:
        row = RawDouyinOrderCoupon(coupon_id=coupon_id, **payload)
        session.add(row)
    else:
        for field_name, value in payload.items():
            setattr(row, field_name, value)
    session.flush()
    return row


def upsert_verify_record(session: Session, verify_id: str, **values: Any) -> RawDouyinVerifyRecord:
    return _merge(session, RawDouyinVerifyRecord, {"verify_id": verify_id}, values)


def upsert_aweme_binding(session: Session, binding_key: str, **values: Any) -> RawAwemeBinding:
    return _merge(session, RawAwemeBinding, {"binding_key": binding_key}, values)


def upsert_store(session: Session, store_id: str, store_name: str, **values: Any) -> DimStore:
    return _merge(session, DimStore, {"store_id": store_id, "store_name": store_name}, values)


def upsert_store_poi_mapping(
    session: Session,
    store_id: str,
    poi_id: str,
    **values: Any,
) -> DimStorePoiMapping:
    return _merge(session, DimStorePoiMapping, {"store_id": store_id, "poi_id": poi_id}, values)


def upsert_sku_product_rule(
    session: Session,
    sku_id: str,
    product_type: str,
    **values: Any,
) -> DimSkuProductRule:
    row = session.scalar(
        select(DimSkuProductRule).where(DimSkuProductRule.sku_id == sku_id)
    )
    payload = {"product_type": product_type, **values}
    if row is None:
        row = DimSkuProductRule(sku_id=sku_id, **payload)
        session.add(row)
    else:
        for field_name, value in payload.items():
            setattr(row, field_name, value)
    session.flush()
    return row


def upsert_aweme_account(session: Session, account_id: str, **values: Any) -> DimAwemeAccount:
    return _merge(session, DimAwemeAccount, {"account_id": account_id}, values)


def start_job_run(
    session: Session,
    job_id: str,
    job_name: str,
    *,
    metadata_json: dict[str, Any] | None = None,
    started_at: datetime | None = None,
) -> JobRun:
    return _merge(
        session,
        JobRun,
        {"job_id": job_id},
        {
            "job_name": job_name,
            "status": "running",
            "started_at": started_at or utcnow(),
            "finished_at": None,
            "success_count": 0,
            "failed_count": 0,
            "error_message": None,
            "metadata_json": metadata_json or {},
        },
    )


def queue_job_run(
    session: Session,
    job_id: str,
    job_name: str,
    *,
    metadata_json: dict[str, Any] | None = None,
    started_at: datetime | None = None,
) -> JobRun:
    return _merge(
        session,
        JobRun,
        {"job_id": job_id},
        {
            "job_name": job_name,
            "status": "queued",
            "started_at": started_at or utcnow(),
            "finished_at": None,
            "success_count": 0,
            "failed_count": 0,
            "error_message": None,
            "metadata_json": metadata_json or {},
        },
    )


def finish_job_run(
    session: Session,
    job_id: str,
    *,
    status: str,
    success_count: int = 0,
    failed_count: int = 0,
    error_message: str | None = None,
    finished_at: datetime | None = None,
) -> JobRun:
    job = session.get(JobRun, job_id)
    if job is None:
        raise ValueError(f"Unknown job_id: {job_id}")
    job.status = status
    job.success_count = success_count
    job.failed_count = failed_count
    job.error_message = error_message
    job.finished_at = finished_at or utcnow()
    session.flush()
    return job


def upsert_data_quality_issue(
    session: Session,
    issue_id: str,
    *,
    issue_type: str,
    message: str,
    order_id: str | None = None,
    coupon_id: str | None = None,
    severity: str = "warning",
    raw_context_json: dict[str, Any] | None = None,
    source_run_id: str | None = None,
    flush: bool = True,
) -> DataQualityIssue:
    values = {
        "issue_type": issue_type,
        "order_id": order_id,
        "coupon_id": coupon_id,
        "severity": severity,
        "message": message,
        "raw_context_json": raw_context_json or {},
        "source_run_id": source_run_id,
    }
    if not flush:
        pending_issue = next(
            (
                row
                for row in session.new
                if isinstance(row, DataQualityIssue) and row.issue_id == issue_id
            ),
            None,
        )
        if pending_issue is not None:
            for field, value in values.items():
                setattr(pending_issue, field, value)
            return pending_issue
    return _merge(
        session,
        DataQualityIssue,
        {"issue_id": issue_id},
        values,
        flush=flush,
    )


HEAVY_SYNC_CLAIM_LOCK_KEY = 661893198734880846
DOUYIN_RATE_LIMIT_ERROR_CODE = "douyin_rate_limited"


def heavy_sync_rate_limit_cooldown_active(
    session: Session,
    *,
    now: datetime | None = None,
) -> bool:
    """Return whether one upstream rate limit must pause the global heavy slot."""

    if now is None:
        clock = (
            func.statement_timestamp()
            if session.get_bind().dialect.name == "postgresql"
            else datetime.now(timezone.utc)
        )
    else:
        clock = now
    return bool(
        session.scalar(
            select(
                exists().where(
                    JobRun.execution_slot == "heavy_sync",
                    JobRun.status == "retry_wait",
                    JobRun.error_code == DOUYIN_RATE_LIMIT_ERROR_CODE,
                    JobRun.next_retry_at.is_not(None),
                    JobRun.next_retry_at > clock,
                )
            )
        )
    )


def _heavy_claim_order_expressions():
    return (
        case((JobRun.job_kind == "parent_sync", 0), else_=1),
        case((JobRun.status == "running", 0), else_=1),
        case((JobRun.business_date.is_(None), 0), else_=1),
    )


def _heavy_claim_order_key(job: JobRun) -> tuple[int, int, int, date | None, str]:
    return (
        0 if job.job_kind == "parent_sync" else 1,
        0 if job.status == "running" else 1,
        0 if job.business_date is None else 1,
        job.business_date,
        job.job_id,
    )


def _heavy_claim_after_key(
    expressions: tuple[Any, Any, Any],
    last_key: tuple[int, int, int, date | None, str],
):
    kind_priority, status_priority, date_null_priority = expressions
    last_kind, last_status, last_date_null, last_date, last_job_id = last_key
    same_kind = kind_priority == last_kind
    same_status = and_(same_kind, status_priority == last_status)
    same_date_null = and_(same_status, date_null_priority == last_date_null)
    if last_date is None:
        date_after = or_(
            and_(same_status, date_null_priority > last_date_null),
            and_(
                same_date_null,
                JobRun.business_date.is_(None),
                JobRun.job_id > last_job_id,
            ),
        )
    else:
        date_after = or_(
            and_(same_status, date_null_priority > last_date_null),
            and_(
                same_date_null,
                JobRun.business_date > last_date,
            ),
            and_(
                same_date_null,
                JobRun.business_date == last_date,
                JobRun.job_id > last_job_id,
            ),
        )
    return or_(
        kind_priority > last_kind,
        and_(same_kind, status_priority > last_status),
        date_after,
    )


@dataclass(frozen=True)
class ClaimedJobRecord:
    """Return the durable identity of one fenced date-job claim."""

    job_id: str
    attempt_id: str
    attempt_number: int
    lease_owner: str
    lease_epoch: int
    component_instance_id: str
    business_date: date | None
    current_stage: str


@dataclass(frozen=True)
class ActiveExecutionState:
    """Database-authoritative state read after locking a valid execution token."""

    attempt_number: int
    max_attempts: int


@dataclass(frozen=True)
class _ExpiredRunningControlState:
    """Locked evidence used to classify one expired heavy-slot row."""

    attempts: tuple[JobAttempt, ...]
    unfinished_attempts: tuple[JobAttempt, ...]
    current_token_attempt: JobAttempt | None
    current_token_binding_valid: bool
    reasons: tuple[str, ...]
    counter_anomaly: bool
    history_anomaly: bool
    observed_attempt_count: int
    observed_max_attempt_number: int | None
    observed_max_lease_epoch: int | None


def parent_sync_gate_allows_claim(session: Session, job: JobRun) -> bool:
    """Fail closed when a date child declares required parent work.

    A missing parent execution is not equivalent to an empty parent plan.  The
    date metadata is the durable declaration of whether parent work is needed;
    when it is non-empty, exactly one matching successful ``parent_sync`` row
    must exist before the child can be claimed.
    """

    if job.job_kind == "parent_sync":
        return validate_parent_sync_execution_identity(session, job)
    if job.job_kind == "finalize":
        metadata = job.metadata_json or {}
        if (
            job.job_name != "finalize"
            or job.execution_slot != "heavy_sync"
            or job.business_date is not None
            or not job.parent_job_id
            or metadata.get("parent_job_id") != job.parent_job_id
            or metadata.get("target") not in {"all", "settlement"}
            or metadata.get("required_stages") != ["finalize"]
            or not isinstance(metadata.get("settle_stage_fences"), list)
        ):
            return False
        parent = session.get(JobRun, job.parent_job_id)
        return bool(
            parent is not None
            and parent.job_kind == "range_sync"
            and parent.status not in {"success", "failed", "cancelled"}
            and parent.data_source == job.data_source
            and parent.config_version == job.config_version
            and parent.window_start == job.window_start
            and parent.window_end == job.window_end
        )
    if job.job_kind != "date_sync":
        return True
    if not job.parent_job_id:
        return False
    if not validate_parent_sync_child_identity(session, job):
        return False
    range_parent = session.scalar(
        select(JobRun)
        .where(
            JobRun.job_id == job.parent_job_id,
            JobRun.job_kind == "range_sync",
        )
        .with_for_update()
    )
    if range_parent is None:
        return False
    range_metadata = range_parent.metadata_json or {}
    if not isinstance(range_metadata, dict):
        return False
    raw_parent_targets = range_metadata.get("parent_targets")
    if not isinstance(raw_parent_targets, list) or not all(
        isinstance(item, str) for item in raw_parent_targets
    ):
        return False
    if not raw_parent_targets:
        return True
    parent_rows = list(
        session.scalars(
            select(JobRun)
            .where(
                JobRun.parent_job_id == range_parent.job_id,
                JobRun.job_kind == "parent_sync",
            )
            .with_for_update()
        )
    )
    return len(parent_rows) == 1 and parent_rows[0].status == "success"


def date_job_advisory_lock_key(
    *,
    business_date: date,
    data_source: str,
    config_version: str,
) -> int:
    """Return a stable signed 64-bit PostgreSQL advisory-lock key."""

    identity = f"date_sync|{business_date.isoformat()}|{data_source}|{config_version}"
    digest = hashlib.blake2b(identity.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, byteorder="big", signed=True)


def claim_next_heavy_job(
    session: Session,
    *,
    lease_owner: str,
    component_instance_id: str,
    lease_seconds: int,
    job_kinds: tuple[str, ...] = ("parent_sync", "date_sync", "finalize"),
    job_id: str | None = None,
) -> ClaimedJobRecord | None:
    """Atomically claim the earliest executable heavy-slot job on PostgreSQL.

    The caller owns the transaction. Both advisory locks are transaction scoped,
    so they cannot leak when a pooled connection is returned.
    """

    _require_postgresql(session)
    global_lock_acquired = session.scalar(
        select(func.pg_try_advisory_xact_lock(HEAVY_SYNC_CLAIM_LOCK_KEY))
    )
    if not global_lock_acquired:
        return None
    if heavy_sync_rate_limit_cooldown_active(session):
        return None

    other_running = aliased(JobRun)
    attempt_available = (
        func.coalesce(JobRun.attempt_count, 0)
        < func.coalesce(JobRun.max_attempts, 3)
    )
    ready_to_start = and_(
        or_(
            JobRun.status == "pending",
            and_(
                JobRun.status == "retry_wait",
                JobRun.next_retry_at.is_not(None),
                JobRun.next_retry_at <= func.statement_timestamp(),
            ),
        ),
        attempt_available,
    )
    expired_running = and_(
        JobRun.status == "running",
        JobRun.lease_expires_at.is_not(None),
        JobRun.lease_expires_at <= func.statement_timestamp(),
    )
    ready_to_claim = or_(
        ready_to_start,
        expired_running,
    )
    no_other_running_slot = ~exists(
        select(1).where(
            other_running.job_id != JobRun.job_id,
            other_running.execution_slot == "heavy_sync",
            other_running.status == "running",
        )
    )
    predicates = [
        JobRun.job_kind.in_(job_kinds),
        JobRun.execution_slot == "heavy_sync",
        ready_to_claim,
        no_other_running_slot,
    ]
    predicates.append(
        or_(
            JobRun.job_kind != "date_sync",
            JobRun.business_date.is_not(None),
        )
    )
    # A missing/failed parent execution is a cheap, SQL-visible blocker.  Keep
    # it out of the ordered candidate set so an arbitrary number of blocked
    # date children cannot consume the bounded Python continuation.  Full
    # metadata identity (target lists, required stages, source window, etc.)
    # remains fail-closed in ``parent_sync_gate_allows_claim`` below.
    parent_targets_json = JobRun.metadata_json.op("->")("parent_targets")
    parent_targets_shape_valid = or_(
        parent_targets_json.is_(None),
        func.jsonb_typeof(parent_targets_json) == "array",
    )
    parent_targets_empty = or_(
        parent_targets_json.is_(None),
        parent_targets_json == literal_column("'[]'::jsonb"),
    )
    parent_execution = aliased(JobRun)
    successful_parent_exists = exists(
        select(1).where(
            parent_execution.parent_job_id == JobRun.parent_job_id,
            parent_execution.job_kind == "parent_sync",
            parent_execution.status == "success",
            parent_execution.execution_slot == "heavy_sync",
            parent_execution.business_date.is_(None),
            parent_execution.data_source == JobRun.data_source,
            parent_execution.config_version == JobRun.config_version,
        )
    )
    # Keep malformed *pending* children out of the ordered candidate set, but
    # retain every database-clock-expired running row for the Python gate.  An
    # expired running row whose planner identity is invalid must be fenced and
    # terminalized before keyset continuation can release the heavy slot.
    expired_running_candidate = and_(
        JobRun.status == "running",
        JobRun.lease_expires_at.is_not(None),
        JobRun.lease_expires_at <= func.statement_timestamp(),
    )
    predicates.append(
        or_(
            expired_running_candidate,
            JobRun.job_kind != "date_sync",
            and_(
                parent_targets_shape_valid,
                or_(parent_targets_empty, successful_parent_exists),
            ),
        )
    )
    if job_id is not None:
        predicates.append(JobRun.job_id == job_id)
    order_expressions = _heavy_claim_order_expressions()
    last_order_key: tuple[int, int, int, date | None, str] | None = None
    job: JobRun | None = None
    while True:
        candidate_predicates = list(predicates)
        if last_order_key is not None:
            candidate_predicates.append(
                _heavy_claim_after_key(order_expressions, last_order_key)
            )
        statement = (
            select(JobRun)
            .where(*candidate_predicates)
            .order_by(
                *order_expressions,
                JobRun.business_date,
                JobRun.job_id,
            )
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        savepoint = session.begin_nested()
        try:
            candidate = session.scalar(statement)
            if candidate is None:
                savepoint.rollback()
                return None
            candidate_key = _heavy_claim_order_key(candidate)
            database_now: datetime | None = None

            # Every database-clock-expired running row is first checked for a
            # complete, internally consistent control identity.  This check
            # deliberately precedes the planner gate: a malformed lease must
            # be fenced even when the planner metadata happens to be valid.
            if (
                candidate.status == "running"
                and candidate.lease_expires_at is not None
            ):
                database_now = _database_now(session)
                if candidate.lease_expires_at <= database_now:
                    control_state = _inspect_expired_running_control(
                        session,
                        job=candidate,
                    )
                    if control_state.reasons:
                        _quarantine_invalid_expired_running_job(
                            session,
                            job=candidate,
                            database_now=database_now,
                            control_state=control_state,
                        )
                        savepoint.commit()
                        if job_id is not None:
                            return None
                        last_order_key = candidate_key
                        continue

            # Pending/retry rows have no active lease to take over, but their
            # bounded attempt history still has to agree with JobRun counters.
            # A stale history or residual unfinished attempt is quarantined so
            # it cannot repeatedly collide with the next unique attempt key.
            if candidate.status in {"pending", "retry_wait"}:
                control_state = _inspect_expired_running_control(
                    session,
                    job=candidate,
                )
                if control_state.reasons:
                    if database_now is None:
                        database_now = _database_now(session)
                    _quarantine_invalid_expired_running_job(
                        session,
                        job=candidate,
                        database_now=database_now,
                        control_state=control_state,
                        require_expired=False,
                    )
                    savepoint.commit()
                    if job_id is not None:
                        return None
                    last_order_key = candidate_key
                    continue

            if not parent_sync_gate_allows_claim(session, candidate):
                if database_now is None:
                    database_now = _database_now(session)
                if (
                    candidate.status == "running"
                    and candidate.lease_expires_at is not None
                    and candidate.lease_expires_at <= database_now
                ):
                    _quarantine_invalid_expired_running_job(
                        session,
                        job=candidate,
                        database_now=database_now,
                    )
                    savepoint.commit()
                    if job_id is not None:
                        return None
                    last_order_key = candidate_key
                    continue
                savepoint.rollback()
                if job_id is not None:
                    return None
                last_order_key = candidate_key
                continue
            if candidate.job_kind == "date_sync":
                assert candidate.business_date is not None
                assert candidate.data_source is not None
                assert candidate.config_version is not None
                date_lock_key = date_job_advisory_lock_key(
                    business_date=candidate.business_date,
                    data_source=candidate.data_source,
                    config_version=candidate.config_version,
                )
                date_lock_acquired = session.scalar(
                    select(func.pg_try_advisory_xact_lock(date_lock_key))
                )
                if not date_lock_acquired:
                    savepoint.rollback()
                    if job_id is not None:
                        return None
                    last_order_key = candidate_key
                    continue
            savepoint.commit()
            job = candidate
            break
        except BaseException:
            savepoint.rollback()
            raise
    assert job is not None

    database_now = _database_now(session)
    previous_status = job.status
    previous_epoch = int(job.lease_epoch or 0)
    previous_attempt: JobAttempt | None = None
    if previous_status == "running":
        previous_attempt = _lock_expired_attempt(
            session,
            job_id=job.job_id,
            lease_epoch=previous_epoch,
        )

    completed_attempts = int(job.attempt_count or 0)
    max_attempts = int(job.max_attempts or 3)
    if previous_status == "running" and completed_attempts >= max_attempts:
        assert previous_attempt is not None
        with session.begin_nested():
            _close_expired_attempt(
                session,
                previous_attempt=previous_attempt,
                database_now=database_now,
            )
            _fail_job_after_exhausted_crash(
                session,
                job=job,
                attempt=previous_attempt,
                database_now=database_now,
                max_attempts=max_attempts,
            )
            session.flush()
        return None

    existing_component = _lock_worker_component(
        session,
        component_instance_id=component_instance_id,
        previous_attempt=previous_attempt,
    )
    attempt_number = completed_attempts + 1
    lease_epoch = previous_epoch + 1
    attempt_id = f"attempt-{uuid4()}"
    with session.begin_nested():
        component = _prepare_worker_component(
            session,
            component_instance_id=component_instance_id,
            database_now=database_now,
            existing_component=existing_component,
        )
        if previous_attempt is not None:
            _close_expired_attempt(
                session,
                previous_attempt=previous_attempt,
                database_now=database_now,
            )

        job.status = "running"
        job.attempt_count = attempt_number
        job.lease_owner = lease_owner
        job.lease_epoch = lease_epoch
        job.lease_expires_at = database_now + timedelta(seconds=lease_seconds)
        job.next_retry_at = None
        job.finished_at = None
        if job.current_stage is None:
            job.current_stage = "collect"
        job.error_code = None
        job.error_summary = None
        job.error_message = None

        attempt = JobAttempt(
            attempt_id=attempt_id,
            job_id=job.job_id,
            stage_run_id=None,
            attempt_number=attempt_number,
            lease_epoch=lease_epoch,
            component_type="worker",
            component_instance_id=component_instance_id,
            started_at=database_now,
            created_at=database_now,
        )
        session.add(attempt)
        session.flush()

        component.status = "healthy"
        component.last_heartbeat_at = database_now
        component.current_job_id = job.job_id
        component.current_attempt_id = attempt_id
        component.updated_at = database_now
        _add_job_event(
            session,
            job_id=job.job_id,
            attempt_id=attempt_id,
            event_type="job_claimed",
            from_status=previous_status,
            to_status="running",
            actor_id=lease_owner,
            occurred_at=database_now,
            payload_json={"lease_epoch": lease_epoch},
        )
        session.flush()
    return ClaimedJobRecord(
        job_id=job.job_id,
        attempt_id=attempt_id,
        attempt_number=attempt_number,
        lease_owner=lease_owner,
        lease_epoch=lease_epoch,
        component_instance_id=component_instance_id,
        business_date=job.business_date,
        current_stage=job.current_stage,
    )


def claim_next_date_sync(
    session: Session,
    *,
    lease_owner: str,
    component_instance_id: str,
    lease_seconds: int,
    job_id: str | None = None,
) -> ClaimedJobRecord | None:
    """Backward-compatible date-only wrapper around the heavy queue claim."""

    return claim_next_heavy_job(
        session,
        lease_owner=lease_owner,
        component_instance_id=component_instance_id,
        lease_seconds=lease_seconds,
        job_kinds=("date_sync",),
        job_id=job_id,
    )


def heartbeat_claim(
    session: Session,
    *,
    job_id: str,
    lease_owner: str,
    lease_epoch: int,
    attempt_id: str,
    component_instance_id: str,
    lease_seconds: int,
) -> bool:
    """Renew one non-expired fenced lease using database time."""

    _require_postgresql(session)
    if lock_active_execution_state(
        session,
        job_id=job_id,
        lease_owner=lease_owner,
        lease_epoch=lease_epoch,
        attempt_id=attempt_id,
        component_instance_id=component_instance_id,
    ) is None:
        return False
    renewed = False
    with session.begin_nested():
        result = session.execute(
            update(JobRun)
            .where(*_active_lease_conditions(job_id, lease_owner, lease_epoch))
            .values(
                heartbeat_at=func.statement_timestamp(),
                lease_expires_at=func.statement_timestamp()
                + timedelta(seconds=lease_seconds),
            )
            .returning(JobRun.heartbeat_at)
        )
        heartbeat_at = result.scalar_one_or_none()
        if heartbeat_at is not None:
            component_result = session.execute(
                update(ComponentHeartbeat)
                .where(
                    ComponentHeartbeat.component_instance_id
                    == component_instance_id,
                    ComponentHeartbeat.component_type == "worker",
                    ComponentHeartbeat.current_job_id == job_id,
                    ComponentHeartbeat.current_attempt_id == attempt_id,
                )
                .values(last_heartbeat_at=heartbeat_at, updated_at=heartbeat_at)
            )
            if component_result.rowcount != 1:
                raise RuntimeError(
                    "active attempt is not bound to the claimed worker component"
                )
            session.flush()
            renewed = True
    return renewed


def complete_claim(
    session: Session,
    *,
    job_id: str,
    lease_owner: str,
    lease_epoch: int,
    attempt_id: str,
    component_instance_id: str,
    success_count: int,
) -> bool:
    """Mark one non-expired fenced lease successful with attempt and event."""

    _require_postgresql(session)
    if lock_active_execution_state(
        session,
        job_id=job_id,
        lease_owner=lease_owner,
        lease_epoch=lease_epoch,
        attempt_id=attempt_id,
        component_instance_id=component_instance_id,
    ) is None:
        return False
    completed = False
    with session.begin_nested():
        result = session.execute(
            update(JobRun)
            .where(*_active_lease_conditions(job_id, lease_owner, lease_epoch))
            .values(
                status="success",
                success_count=success_count,
                failed_count=0,
                finished_at=func.statement_timestamp(),
                lease_owner=None,
                lease_expires_at=None,
                next_retry_at=None,
                error_code=None,
                error_summary=None,
                error_message=None,
            )
            .returning(JobRun.finished_at)
        )
        database_now = result.scalar_one_or_none()
        if database_now is not None:
            _finish_attempt(
                session,
                job_id=job_id,
                lease_epoch=lease_epoch,
                attempt_id=attempt_id,
                finished_at=database_now,
                exit_type="success",
            )
            _release_component_attempt(
                session,
                component_instance_id=component_instance_id,
                job_id=job_id,
                attempt_id=attempt_id,
                database_now=database_now,
                status="healthy",
            )
            _add_job_event(
                session,
                job_id=job_id,
                attempt_id=attempt_id,
                event_type="job_succeeded",
                from_status="running",
                to_status="success",
                actor_id=lease_owner,
                occurred_at=database_now,
            )
            session.flush()
            completed = True
    return completed


def lock_active_execution_state(
    session: Session,
    *,
    job_id: str,
    lease_owner: str,
    lease_epoch: int,
    attempt_id: str,
    component_instance_id: str,
    require_cancel_intent: bool = False,
) -> ActiveExecutionState | None:
    """Lock and validate JobRun, JobAttempt, then ComponentHeartbeat."""

    _require_postgresql(session)
    job = session.scalar(
        select(JobRun)
        .where(
            JobRun.job_id == job_id,
            JobRun.status == "running",
            JobRun.lease_owner == lease_owner,
            JobRun.lease_epoch == lease_epoch,
            JobRun.lease_expires_at.is_not(None),
        )
        .with_for_update()
    )
    if job is None or job.lease_expires_at is None:
        return None
    database_now = _database_now(session)
    if job.lease_expires_at <= database_now:
        return None
    if require_cancel_intent and job.cancel_requested_at is None:
        return None

    attempt = session.scalar(
        select(JobAttempt)
        .where(
            JobAttempt.job_id == job_id,
            JobAttempt.attempt_id == attempt_id,
            JobAttempt.lease_epoch == lease_epoch,
            JobAttempt.component_type == "worker",
            JobAttempt.component_instance_id == component_instance_id,
            JobAttempt.finished_at.is_(None),
        )
        .with_for_update()
    )
    if attempt is None:
        return None
    component = session.scalar(
        select(ComponentHeartbeat)
        .where(
            ComponentHeartbeat.component_instance_id == component_instance_id,
            ComponentHeartbeat.component_type == "worker",
            ComponentHeartbeat.current_job_id == job_id,
            ComponentHeartbeat.current_attempt_id == attempt_id,
        )
        .with_for_update()
    )
    if component is None:
        return None
    return ActiveExecutionState(
        attempt_number=int(job.attempt_count or 0),
        max_attempts=int(job.max_attempts or 3),
    )


def previous_attempt_exit_type(
    session: Session,
    *,
    job_id: str,
    attempt_number: int,
) -> str | None:
    """Return the immediately preceding attempt exit type, if any."""

    if attempt_number <= 1:
        return None
    return session.scalar(
        select(JobAttempt.exit_type).where(
            JobAttempt.job_id == job_id,
            JobAttempt.attempt_number == attempt_number - 1,
        )
    )


def fail_claim(
    session: Session,
    *,
    job_id: str,
    lease_owner: str,
    lease_epoch: int,
    attempt_id: str,
    component_instance_id: str,
    status: str,
    delay_seconds: int | None,
    attempt_exit_type: str,
    error_code: str,
    error_summary: str,
) -> bool:
    """Apply one fenced retry/fatal failure with attempt and event atomically."""

    _require_postgresql(session)
    if lock_active_execution_state(
        session,
        job_id=job_id,
        lease_owner=lease_owner,
        lease_epoch=lease_epoch,
        attempt_id=attempt_id,
        component_instance_id=component_instance_id,
    ) is None:
        return False
    next_retry_at = (
        func.statement_timestamp() + timedelta(seconds=delay_seconds)
        if delay_seconds is not None
        else None
    )
    failed = False
    with session.begin_nested():
        result = session.execute(
            update(JobRun)
            .where(*_active_lease_conditions(job_id, lease_owner, lease_epoch))
            .values(
                status=status,
                failed_count=1,
                finished_at=func.statement_timestamp() if status == "failed" else None,
                lease_owner=None,
                lease_expires_at=None,
                next_retry_at=next_retry_at,
                error_code=error_code,
                error_summary=error_summary,
                error_message=error_summary,
            )
            .returning(func.statement_timestamp())
        )
        database_now = result.scalar_one_or_none()
        if database_now is not None:
            _finish_attempt(
                session,
                job_id=job_id,
                lease_epoch=lease_epoch,
                attempt_id=attempt_id,
                finished_at=database_now,
                exit_type=attempt_exit_type,
                error_code=error_code,
                error_summary=error_summary,
            )
            _release_component_attempt(
                session,
                component_instance_id=component_instance_id,
                job_id=job_id,
                attempt_id=attempt_id,
                database_now=database_now,
                status="degraded" if status == "retry_wait" else "unhealthy",
            )
            _add_job_event(
                session,
                job_id=job_id,
                attempt_id=attempt_id,
                event_type=(
                    "job_retry_scheduled" if status == "retry_wait" else "job_failed"
                ),
                from_status="running",
                to_status=status,
                actor_id=lease_owner,
                occurred_at=database_now,
                reason=error_summary,
                payload_json={"error_code": error_code, "delay_seconds": delay_seconds},
            )
            session.flush()
            failed = True
    return failed


def cancel_claim(
    session: Session,
    *,
    job_id: str,
    lease_owner: str,
    lease_epoch: int,
    attempt_id: str,
    component_instance_id: str,
    reason: str,
) -> bool:
    """Confirm a cancel request only at a valid fenced execution boundary."""

    _require_postgresql(session)
    if lock_active_execution_state(
        session,
        job_id=job_id,
        lease_owner=lease_owner,
        lease_epoch=lease_epoch,
        attempt_id=attempt_id,
        component_instance_id=component_instance_id,
        require_cancel_intent=True,
    ) is None:
        return False
    cancelled = False
    with session.begin_nested():
        result = session.execute(
            update(JobRun)
            .where(
                *_active_lease_conditions(job_id, lease_owner, lease_epoch),
                JobRun.cancel_requested_at.is_not(None),
            )
            .values(
                status="cancelled",
                finished_at=func.statement_timestamp(),
                lease_owner=None,
                lease_expires_at=None,
                next_retry_at=None,
            )
            .returning(JobRun.finished_at)
        )
        database_now = result.scalar_one_or_none()
        if database_now is not None:
            _finish_attempt(
                session,
                job_id=job_id,
                lease_epoch=lease_epoch,
                attempt_id=attempt_id,
                finished_at=database_now,
                exit_type="cancelled",
            )
            _release_component_attempt(
                session,
                component_instance_id=component_instance_id,
                job_id=job_id,
                attempt_id=attempt_id,
                database_now=database_now,
                status="healthy",
            )
            _add_job_event(
                session,
                job_id=job_id,
                attempt_id=attempt_id,
                event_type="job_cancelled",
                from_status="running",
                to_status="cancelled",
                actor_id=lease_owner,
                occurred_at=database_now,
                reason=reason,
            )
            session.flush()
            cancelled = True
    return cancelled


def _require_postgresql(session: Session) -> None:
    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("date-job claim and lease fencing require PostgreSQL")


def _database_now(session: Session) -> datetime:
    database_now = session.scalar(select(func.clock_timestamp()))
    if database_now is None:
        raise RuntimeError("database did not return its current time")
    return database_now


def _lock_worker_component(
    session: Session,
    *,
    component_instance_id: str,
    previous_attempt: JobAttempt | None,
) -> ComponentHeartbeat | None:
    component = session.scalar(
        select(ComponentHeartbeat)
        .where(ComponentHeartbeat.component_instance_id == component_instance_id)
        .with_for_update()
    )
    if component is not None and component.component_type != "worker":
        raise RuntimeError("component instance is registered with a non-worker type")
    if component is None:
        return None
    current_binding = (component.current_job_id, component.current_attempt_id)
    if current_binding == (None, None):
        return component
    if previous_attempt is not None and current_binding == (
        previous_attempt.job_id,
        previous_attempt.attempt_id,
    ):
        return component
    raise RuntimeError("worker component is already bound to another execution")


def _prepare_worker_component(
    session: Session,
    *,
    component_instance_id: str,
    database_now: datetime,
    existing_component: ComponentHeartbeat | None,
) -> ComponentHeartbeat:
    if existing_component is None:
        component = ComponentHeartbeat(
            component_instance_id=component_instance_id,
            component_type="worker",
            status="healthy",
            started_at=database_now,
            last_heartbeat_at=database_now,
            activity_json={},
            queue_summary_json={},
            created_at=database_now,
            updated_at=database_now,
        )
        session.add(component)
        return component
    existing_component.status = "healthy"
    existing_component.last_heartbeat_at = database_now
    existing_component.updated_at = database_now
    return existing_component


def _active_lease_conditions(
    job_id: str,
    lease_owner: str,
    lease_epoch: int,
) -> tuple[Any, ...]:
    return (
        JobRun.job_id == job_id,
        JobRun.status == "running",
        JobRun.lease_owner == lease_owner,
        JobRun.lease_epoch == lease_epoch,
        JobRun.lease_expires_at.is_not(None),
        JobRun.lease_expires_at > func.statement_timestamp(),
    )


def _lock_expired_attempt(
    session: Session,
    *,
    job_id: str,
    lease_epoch: int,
) -> JobAttempt:
    previous_attempt = session.scalar(
        select(JobAttempt)
        .where(
            JobAttempt.job_id == job_id,
            JobAttempt.lease_epoch == lease_epoch,
            JobAttempt.finished_at.is_(None),
        )
        .with_for_update()
    )
    if previous_attempt is None:
        raise RuntimeError("expired fenced job has no matching attempt record")
    return previous_attempt


def _inspect_expired_running_control(
    session: Session,
    *,
    job: JobRun,
) -> _ExpiredRunningControlState:
    """Lock bounded attempt history and validate counters and identity."""

    attempts = tuple(
        session.scalars(
            select(JobAttempt)
            .where(JobAttempt.job_id == job.job_id)
            .order_by(JobAttempt.attempt_number, JobAttempt.attempt_id)
            .limit(4)
            .with_for_update()
        )
    )
    unfinished_attempts = tuple(
        attempt for attempt in attempts if attempt.finished_at is None
    )
    reasons: list[str] = []
    attempt_count = int(job.attempt_count or 0)
    lease_epoch = int(job.lease_epoch or 0)
    counter_anomaly = False
    history_anomaly = False
    if attempt_count < 0 or attempt_count > 3:
        counter_anomaly = True
        reasons.append("attempt_count_invalid")
    if lease_epoch != attempt_count:
        counter_anomaly = True
        reasons.append("lease_epoch_counter_mismatch")
    if len(attempts) != attempt_count:
        counter_anomaly = True
        reasons.append("attempt_row_count_mismatch")
    if len(attempts) >= 4:
        history_anomaly = True
        reasons.append("attempt_history_exceeds_limit")

    observed_numbers = [attempt.attempt_number for attempt in attempts]
    observed_epochs = [attempt.lease_epoch for attempt in attempts]
    expected_sequence = list(range(1, attempt_count + 1))
    if (
        len(attempts) <= 3
        and (
            sorted(observed_numbers) != expected_sequence
            or sorted(observed_epochs) != expected_sequence
            or any(
                attempt.attempt_number != attempt.lease_epoch
                for attempt in attempts
            )
        )
    ):
        history_anomaly = True
        reasons.append("attempt_history_non_contiguous")
    if any(attempt.component_type != "worker" for attempt in attempts):
        history_anomaly = True
        reasons.append("history_component_type_invalid")

    if job.status == "running":
        lease_owner = job.lease_owner
        if not isinstance(lease_owner, str) or not lease_owner.strip():
            reasons.append("lease_owner_missing")
        if lease_epoch <= 0:
            reasons.append("lease_epoch_invalid")
        if not unfinished_attempts:
            reasons.append("unfinished_attempt_missing")
        elif len(unfinished_attempts) != 1:
            reasons.append("multiple_unfinished_attempts")
    elif unfinished_attempts:
        reasons.append("unfinished_attempt_unexpected")
    elif (
        job.status in {"pending", "retry_wait"}
        and (
            job.lease_owner is not None
            or job.lease_expires_at is not None
        )
    ):
        reasons.append("active_lease_on_non_running")
    if lease_epoch < 0:
        reasons.append("lease_epoch_invalid")
        if job.status in {"pending", "retry_wait"} and not job.lease_owner:
            reasons.append("lease_owner_missing")
        if job.status in {"pending", "retry_wait"} and not unfinished_attempts:
            reasons.extend(
                ["unfinished_attempt_missing", "current_token_attempt_missing"]
            )

    current_token_attempt = next(
        (
            attempt
            for attempt in unfinished_attempts
            if attempt.lease_epoch == lease_epoch
        ),
        None,
    )
    if job.status == "running" and current_token_attempt is None:
        reasons.append("current_token_attempt_missing")

    current_token_binding_valid = False
    if current_token_attempt is not None:
        component = session.scalar(
            select(ComponentHeartbeat)
            .where(
                ComponentHeartbeat.component_instance_id
                == current_token_attempt.component_instance_id,
                ComponentHeartbeat.component_type == current_token_attempt.component_type,
            )
            .with_for_update()
        )
        current_token_binding_valid = bool(
            component is not None
            and component.current_job_id == current_token_attempt.job_id
            and component.current_attempt_id == current_token_attempt.attempt_id
        )
        if component is None:
            reasons.append("current_token_component_missing")
        elif current_token_attempt.component_type != "worker":
            reasons.append("component_type_invalid")
        elif not current_token_binding_valid:
            reasons.append("current_token_component_binding_mismatch")
    for attempt in attempts:
        if attempt.finished_at is None:
            continue
        component = session.scalar(
            select(ComponentHeartbeat)
            .where(
                ComponentHeartbeat.component_instance_id == attempt.component_instance_id,
                ComponentHeartbeat.component_type == attempt.component_type,
            )
            .with_for_update()
        )
        if (
            component is not None
            and component.current_job_id == attempt.job_id
            and component.current_attempt_id == attempt.attempt_id
        ):
            history_anomaly = True
            reasons.append("finished_attempt_component_binding_stale")

    return _ExpiredRunningControlState(
        attempts=attempts,
        unfinished_attempts=unfinished_attempts,
        current_token_attempt=current_token_attempt,
        current_token_binding_valid=current_token_binding_valid,
        reasons=tuple(dict.fromkeys(reasons)),
        counter_anomaly=counter_anomaly,
        history_anomaly=history_anomaly,
        observed_attempt_count=len(attempts),
        observed_max_attempt_number=max(observed_numbers, default=None),
        observed_max_lease_epoch=max(observed_epochs, default=None),
    )


def _attempt_finished_timestamp(
    *,
    started_at: datetime,
    database_now: datetime,
) -> tuple[datetime, bool]:
    """Honor the attempt time-order CHECK when clock data is in the future."""

    if started_at > database_now:
        return started_at, True
    return database_now, False


def _quarantine_invalid_expired_running_job(
    session: Session,
    *,
    job: JobRun,
    database_now: datetime,
    control_state: _ExpiredRunningControlState | None = None,
    require_expired: bool = True,
) -> None:
    """Fence an expired running row whose planner identity failed closed.

    The caller holds the candidate row lock inside a SAVEPOINT.  This helper
    deliberately does not assume that the attempt or its component binding is
    internally consistent: malformed control-plane state must still release
    the heavy slot without touching an unrelated component.
    """

    if require_expired and (
        job.status != "running"
        or job.lease_expires_at is None
        or job.lease_expires_at > database_now
    ):
        raise RuntimeError("invalid quarantine target is not an expired running job")

    if control_state is None:
        control_state = _inspect_expired_running_control(session, job=job)

    # The bounded inspection above is enough for the normal path to classify
    # a row, but quarantine must close every unfinished attempt, including
    # corrupt rows beyond the normal three-attempt budget.
    all_attempts = tuple(
        session.scalars(
            select(JobAttempt)
            .where(
                JobAttempt.job_id == job.job_id,
            )
            .order_by(JobAttempt.attempt_number, JobAttempt.attempt_id)
            .with_for_update()
        )
    )
    all_unfinished_attempts = tuple(
        attempt for attempt in all_attempts if attempt.finished_at is None
    )
    current_token_attempt = next(
        (
            attempt
            for attempt in all_unfinished_attempts
            if attempt.lease_epoch == int(job.lease_epoch or 0)
        ),
        None,
    )
    current_token_binding_valid = control_state.current_token_binding_valid
    if current_token_attempt is not None and (
        control_state.current_token_attempt is None
        or current_token_attempt.attempt_id
        != control_state.current_token_attempt.attempt_id
    ):
        component = session.scalar(
            select(ComponentHeartbeat)
            .where(
                ComponentHeartbeat.component_instance_id
                == current_token_attempt.component_instance_id,
                ComponentHeartbeat.component_type == current_token_attempt.component_type,
            )
            .with_for_update()
        )
        current_token_binding_valid = bool(
            component is not None
            and component.current_job_id == current_token_attempt.job_id
            and component.current_attempt_id == current_token_attempt.attempt_id
        )

    summary = "job failed closed after control-plane identity validation"
    closed_attempt_count = 0
    released_component_count = 0
    timestamp_anomaly_count = 0
    for attempt in all_attempts:
        if attempt.finished_at is None:
            finished_at, timestamp_anomaly = _attempt_finished_timestamp(
                started_at=attempt.started_at,
                database_now=database_now,
            )
            timestamp_anomaly_count += int(timestamp_anomaly)
            attempt.finished_at = finished_at
            attempt.exit_type = "fatal_failure"
            attempt.error_code = "control_plane_identity_invalid"
            attempt.error_summary = summary
            closed_attempt_count += 1
        release_result = session.execute(
            update(ComponentHeartbeat)
            .where(
                ComponentHeartbeat.component_instance_id == attempt.component_instance_id,
                ComponentHeartbeat.component_type == attempt.component_type,
                ComponentHeartbeat.current_job_id == attempt.job_id,
                ComponentHeartbeat.current_attempt_id == attempt.attempt_id,
            )
            .values(
                status="degraded",
                current_job_id=None,
                current_attempt_id=None,
                updated_at=database_now,
            )
        )
        released_component_count += int(release_result.rowcount or 0)

    control_state_reasons = [
        reason
        for reason in control_state.reasons
        if not (
            reason == "current_token_attempt_missing"
            and current_token_attempt is not None
        )
    ]
    if (
        current_token_attempt is not None
        and current_token_attempt.component_type != "worker"
        and "component_type_invalid" not in control_state_reasons
    ):
        control_state_reasons.append("component_type_invalid")
    if (
        current_token_attempt is not None
        and not current_token_binding_valid
        and "current_token_component_binding_mismatch" not in control_state_reasons
    ):
        control_state_reasons.append("current_token_component_binding_mismatch")

    from_status = job.status
    job.status = "failed"
    job.failed_count = max(int(job.failed_count or 0), 1)
    job.finished_at = database_now
    job.lease_owner = None
    job.lease_expires_at = None
    job.heartbeat_at = None
    job.next_retry_at = None
    job.error_code = "control_plane_identity_invalid"
    job.error_summary = summary
    job.error_message = summary
    _add_job_event(
        session,
        job_id=job.job_id,
        attempt_id=(
            current_token_attempt.attempt_id
            if current_token_attempt is not None
            else None
        ),
        event_type="job_quarantined",
        from_status=from_status,
        to_status="failed",
        actor_id=None,
        occurred_at=database_now,
        reason=summary,
        payload_json={
            "error_code": "control_plane_identity_invalid",
            "expired_lease_epoch": int(job.lease_epoch or 0),
            "attempt_present": bool(all_unfinished_attempts),
            "closed_attempt_count": closed_attempt_count,
            "released_component_count": released_component_count,
            "missing_attempt": current_token_attempt is None,
            "current_token_attempt_missing": current_token_attempt is None,
            "current_token_binding_mismatch": (
                current_token_attempt is not None and not current_token_binding_valid
            ),
            "timestamp_anomaly": timestamp_anomaly_count > 0,
            "timestamp_anomaly_attempt_count": timestamp_anomaly_count,
            "control_state_reasons": control_state_reasons,
            "counter_anomaly": control_state.counter_anomaly,
            "history_anomaly": control_state.history_anomaly,
            "observed_attempt_count": max(
                control_state.observed_attempt_count,
                len(all_attempts),
            ),
            "observed_max_attempt_number": max(
                control_state.observed_max_attempt_number or 0,
                max(
                    (attempt.attempt_number for attempt in all_attempts),
                    default=0,
                ),
            ),
            "observed_max_lease_epoch": max(
                control_state.observed_max_lease_epoch or 0,
                max(
                    (attempt.lease_epoch for attempt in all_attempts),
                    default=0,
                ),
            ),
        },
    )
    session.flush()


def _close_expired_attempt(
    session: Session,
    *,
    previous_attempt: JobAttempt,
    database_now: datetime,
) -> None:
    finished_at, timestamp_anomaly = _attempt_finished_timestamp(
        started_at=previous_attempt.started_at,
        database_now=database_now,
    )
    previous_attempt.finished_at = finished_at
    previous_attempt.exit_type = "crashed"
    previous_attempt.error_code = "lease_expired"
    previous_attempt.error_summary = "lease expired before the attempt completed"
    release_result = session.execute(
        update(ComponentHeartbeat)
        .where(
            ComponentHeartbeat.component_instance_id == previous_attempt.component_instance_id,
            ComponentHeartbeat.component_type == previous_attempt.component_type,
            ComponentHeartbeat.current_job_id == previous_attempt.job_id,
            ComponentHeartbeat.current_attempt_id == previous_attempt.attempt_id,
        )
        .values(
            status="degraded",
            current_job_id=None,
            current_attempt_id=None,
            updated_at=database_now,
        )
    )
    _add_job_event(
        session,
        job_id=previous_attempt.job_id,
        attempt_id=previous_attempt.attempt_id,
        event_type="lease_expired",
        from_status="running",
        to_status="running",
        actor_id=None,
        occurred_at=database_now,
        reason="lease expired before completion",
        payload_json={
            "expired_lease_epoch": previous_attempt.lease_epoch,
            "released_component_count": int(release_result.rowcount or 0),
            "timestamp_anomaly": timestamp_anomaly,
        },
    )


def _fail_job_after_exhausted_crash(
    session: Session,
    *,
    job: JobRun,
    attempt: JobAttempt,
    database_now: datetime,
    max_attempts: int,
) -> None:
    job.status = "failed"
    job.failed_count = 1
    job.finished_at = database_now
    job.lease_owner = None
    job.lease_expires_at = None
    job.next_retry_at = None
    job.error_code = "max_attempts_exhausted_after_crash"
    job.error_summary = "lease expired after the final permitted attempt"
    job.error_message = job.error_summary
    _add_job_event(
        session,
        job_id=job.job_id,
        attempt_id=attempt.attempt_id,
        event_type="job_failed",
        from_status="running",
        to_status="failed",
        actor_id=None,
        occurred_at=database_now,
        reason=job.error_summary,
        payload_json={
            "error_code": job.error_code,
            "max_attempts": max_attempts,
        },
    )


def _finish_attempt(
    session: Session,
    *,
    job_id: str,
    lease_epoch: int,
    attempt_id: str,
    finished_at: datetime,
    exit_type: str,
    error_code: str | None = None,
    error_summary: str | None = None,
) -> None:
    result = session.execute(
        update(JobAttempt)
        .where(
            JobAttempt.job_id == job_id,
            JobAttempt.lease_epoch == lease_epoch,
            JobAttempt.attempt_id == attempt_id,
            JobAttempt.finished_at.is_(None),
        )
        .values(
            finished_at=finished_at,
            exit_type=exit_type,
            error_code=error_code,
            error_summary=error_summary,
        )
    )
    if result.rowcount != 1:
        raise RuntimeError("active lease has no matching unfinished attempt")


def _release_component_attempt(
    session: Session,
    *,
    component_instance_id: str,
    job_id: str,
    attempt_id: str,
    database_now: datetime,
    status: str,
) -> None:
    result = session.execute(
        update(ComponentHeartbeat)
        .where(
            ComponentHeartbeat.component_instance_id == component_instance_id,
            ComponentHeartbeat.component_type == "worker",
            ComponentHeartbeat.current_job_id == job_id,
            ComponentHeartbeat.current_attempt_id == attempt_id,
        )
        .values(
            status=status,
            current_job_id=None,
            current_attempt_id=None,
            updated_at=database_now,
        )
    )
    if result.rowcount != 1:
        raise RuntimeError("active attempt is not bound to the claimed worker component")


def _add_job_event(
    session: Session,
    *,
    job_id: str,
    attempt_id: str | None,
    event_type: str,
    from_status: str | None,
    to_status: str | None,
    actor_id: str | None,
    occurred_at: datetime,
    reason: str | None = None,
    payload_json: dict[str, Any] | None = None,
) -> None:
    session.add(
        JobEvent(
            event_id=f"event-{uuid4()}",
            job_id=job_id,
            stage_run_id=None,
            attempt_id=attempt_id,
            event_type=event_type,
            from_status=from_status,
            to_status=to_status,
            actor_type="worker" if actor_id is not None else "system",
            actor_id=actor_id,
            reason=reason,
            payload_json=payload_json or {},
            occurred_at=occurred_at,
        )
    )
