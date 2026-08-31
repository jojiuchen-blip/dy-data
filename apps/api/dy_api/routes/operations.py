from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
import os
import re
from typing import Any, Mapping
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    ComponentHeartbeat,
    JobAttempt,
    JobEvent,
    JobRun,
    JobStageRun,
    OpsCommand,
)
from apps.api.dy_api.schemas import (
    AdminControlIntentRequest,
    AdminOperationCreateJobRequest,
    AdminOpsCommandRequest,
)
from apps.worker.daily_windows import plan_daily_sync
from dy_api.auth import get_current_super_admin
from dy_api.routes._data import (
    generated_at,
    get_session_dependency,
    sanitize_error_message,
)


router = APIRouter()

COMPONENT_TYPES = ("api", "postgres", "worker", "browser", "proxy", "ops_agent")
RESTARTABLE_COMPONENTS = frozenset({"worker", "browser"})
COMPONENT_LOST_AFTER = timedelta(seconds=90)
OPS_COMMAND_TTL = timedelta(minutes=2)
OPS_COMMAND_COOLDOWN = timedelta(minutes=5)
SENSITIVE_KEY = re.compile(
    r"(?i)(authorization|cookie|credential|password|passwd|request.?body|secret|stack|token|traceback)"
)


def _now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _idempotency_hash(value: str) -> str:
    normalized = value.strip()
    if not 16 <= len(normalized) <= 128:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Idempotency-Key must contain 16 to 128 characters",
        )
    return sha256(normalized.encode("utf-8")).hexdigest()


def _require_trusted_origin(request: Request) -> None:
    fetch_site = (request.headers.get("sec-fetch-site") or "").strip().lower()
    if fetch_site and fetch_site not in {"same-origin", "same-site", "none"}:
        raise HTTPException(status_code=403, detail="Cross-site control request denied")
    origin = (request.headers.get("origin") or "").strip().rstrip("/")
    if not origin:
        return
    allowed = {str(request.base_url).rstrip("/")}
    allowed.update(
        item.strip().rstrip("/")
        for item in os.getenv("DY_API_CORS_ORIGINS", "").split(",")
        if item.strip()
    )
    if origin not in allowed:
        raise HTTPException(status_code=403, detail="Control request origin denied")


def _sanitize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): "[redacted]" if SENSITIVE_KEY.search(str(key)) else _sanitize(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        return sanitize_error_message(value)
    return value


def _job_summary(job: JobRun) -> dict[str, Any]:
    current = int(job.progress_current or 0)
    total = int(job.progress_total or 0)
    progress_percent = None
    if total > 0:
        progress_percent = round(min(max(current / total, 0), 1) * 100, 1)
    return {
        "job_id": job.job_id,
        "parent_job_id": job.parent_job_id,
        "job_name": job.job_name,
        "job_kind": job.job_kind,
        "business_date": job.business_date.isoformat() if job.business_date else None,
        "status": job.status,
        "current_stage": job.current_stage,
        "attempt_count": int(job.attempt_count or 0),
        "max_attempts": int(job.max_attempts or 0),
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "heartbeat_at": job.heartbeat_at,
        "next_retry_at": job.next_retry_at,
        "progress_current": current,
        "progress_total": total,
        "progress_percent": progress_percent,
        "rows_read": int(job.rows_read or 0),
        "rows_written": int(job.rows_written or 0),
        "rows_affected": int(job.rows_affected or 0),
        "rss_peak_bytes": int(job.rss_peak_bytes or 0),
        "error_code": job.error_code,
        "error_summary": sanitize_error_message(job.error_summary or job.error_message),
        "cancel_requested": job.cancel_requested_at is not None,
        "pause_requested": job.pause_after_stage_requested_at is not None,
    }


def _eta(job: JobRun, now: datetime) -> dict[str, Any]:
    current = int(job.progress_current or 0)
    total = int(job.progress_total or 0)
    started_at = _as_utc(job.started_at)
    if job.status != "running" or current <= 0 or total <= current or started_at is None:
        return {"state": "estimating", "remaining_seconds": None, "confidence": "low"}
    elapsed = max((now - started_at).total_seconds(), 1.0)
    throughput = current / elapsed
    if throughput <= 0:
        return {"state": "estimating", "remaining_seconds": None, "confidence": "low"}
    return {
        "state": "available",
        "remaining_seconds": max(int((total - current) / throughput), 1),
        "confidence": "current_throughput" if current >= 10 else "low",
    }


def _component_rows(session: Session, now: datetime) -> list[dict[str, Any]]:
    rows = list(
        session.scalars(
            select(ComponentHeartbeat).order_by(
                ComponentHeartbeat.component_type,
                ComponentHeartbeat.last_heartbeat_at.desc(),
            )
        )
    )
    latest: dict[str, ComponentHeartbeat] = {}
    for row in rows:
        latest.setdefault(row.component_type, row)
    result = []
    for component_type in COMPONENT_TYPES:
        row = latest.get(component_type)
        if row is None:
            result.append(
                {
                    "component_type": component_type,
                    "component_instance_id": None,
                    "declared_status": None,
                    "observed_status": "unknown",
                    "last_heartbeat_at": None,
                    "allow_restart": component_type in RESTARTABLE_COMPONENTS,
                    "activity": {},
                    "queue_summary": {},
                    "resources": {},
                }
            )
            continue
        heartbeat = _as_utc(row.last_heartbeat_at)
        observed_status = row.status
        if heartbeat is None or now - heartbeat > COMPONENT_LOST_AFTER:
            observed_status = "lost"
        result.append(
            {
                "component_type": component_type,
                "component_instance_id": row.component_instance_id,
                "declared_status": row.status,
                "observed_status": observed_status,
                "last_heartbeat_at": row.last_heartbeat_at,
                "allow_restart": component_type in RESTARTABLE_COMPONENTS,
                "current_job_id": row.current_job_id,
                "current_attempt_id": row.current_attempt_id,
                "activity": _sanitize(row.activity_json or {}),
                "queue_summary": _sanitize(row.queue_summary_json or {}),
                "resources": {
                    "cpu_percent": row.cpu_percent,
                    "rss_bytes": row.rss_bytes,
                    "rss_peak_bytes": row.rss_peak_bytes,
                    "memory_limit_bytes": row.memory_limit_bytes,
                    "queue_depth": row.queue_depth,
                },
            }
        )
    return result


def _success(data: Any) -> dict[str, Any]:
    return {"data": data, "meta": {"generated_at": generated_at(), "source": "postgres"}}


@router.get("/overview")
def operations_overview(
    _username: str = Depends(get_current_super_admin),
    session: Session = Depends(get_session_dependency),
):
    now = _now()
    jobs = list(
        session.scalars(select(JobRun).order_by(JobRun.started_at.desc()).limit(50))
    )
    return _success(
        {
            "components": _component_rows(session, now),
            "jobs": [_job_summary(job) for job in jobs],
            "active_count": sum(job.status == "running" for job in jobs),
            "queued_count": sum(job.status in {"pending", "queued", "retry_wait"} for job in jobs),
        }
    )


@router.get("/components")
def list_components(
    _username: str = Depends(get_current_super_admin),
    session: Session = Depends(get_session_dependency),
):
    return _success({"rows": _component_rows(session, _now())})


@router.get("/jobs")
def list_jobs(
    job_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    _username: str = Depends(get_current_super_admin),
    session: Session = Depends(get_session_dependency),
):
    statement = select(JobRun)
    if job_status:
        statement = statement.where(JobRun.status == job_status)
    jobs = list(session.scalars(statement.order_by(JobRun.started_at.desc()).limit(limit)))
    return _success({"rows": [_job_summary(job) for job in jobs]})


@router.get("/jobs/{job_id}")
def get_job_detail(
    job_id: str,
    _username: str = Depends(get_current_super_admin),
    session: Session = Depends(get_session_dependency),
):
    job = session.get(JobRun, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    children = list(
        session.scalars(
            select(JobRun)
            .where(JobRun.parent_job_id == job_id)
            .order_by(JobRun.business_date, JobRun.job_id)
        )
    )
    stages = list(
        session.scalars(
            select(JobStageRun)
            .where(JobStageRun.job_id == job_id)
            .order_by(JobStageRun.created_at, JobStageRun.stage_name)
        )
    )
    attempts = list(
        session.scalars(
            select(JobAttempt)
            .where(JobAttempt.job_id == job_id)
            .order_by(JobAttempt.attempt_number, JobAttempt.started_at)
        )
    )
    events = list(
        session.scalars(
            select(JobEvent)
            .where(JobEvent.job_id == job_id)
            .order_by(JobEvent.occurred_at.desc(), JobEvent.event_id.desc())
            .limit(200)
        )
    )
    return _success(
        {
            "job": _job_summary(job),
            "eta": _eta(job, _now()),
            "children": [_job_summary(child) for child in children],
            "stages": [
                {
                    "stage_run_id": row.stage_run_id,
                    "stage_name": row.stage_name,
                    "status": row.status,
                    "started_at": row.started_at,
                    "finished_at": row.finished_at,
                    "committed_at": row.committed_at,
                }
                for row in stages
            ],
            "attempts": [
                {
                    "attempt_id": row.attempt_id,
                    "attempt_number": row.attempt_number,
                    "component_type": row.component_type,
                    "component_instance_id": row.component_instance_id,
                    "started_at": row.started_at,
                    "finished_at": row.finished_at,
                    "exit_type": row.exit_type,
                    "rss_peak_bytes": row.rss_peak_bytes,
                    "error_id": row.error_id,
                    "error_code": row.error_code,
                    "error_summary": sanitize_error_message(row.error_summary),
                }
                for row in attempts
            ],
            "events": [
                {
                    "event_id": row.event_id,
                    "event_type": row.event_type,
                    "from_status": row.from_status,
                    "to_status": row.to_status,
                    "actor_type": row.actor_type,
                    "actor_id": row.actor_id,
                    "reason": sanitize_error_message(row.reason),
                    "error_id": row.error_id,
                    "payload": _sanitize(row.payload_json or {}),
                    "occurred_at": row.occurred_at,
                }
                for row in events
            ],
        }
    )


def _existing_control_event(
    session: Session, *, job_id: str | None, idempotency_key: str, request_sha: str
) -> JobEvent | None:
    statement = select(JobEvent).where(JobEvent.idempotency_key == idempotency_key)
    if job_id is not None:
        statement = statement.where(JobEvent.job_id == job_id)
    existing = session.scalar(statement.order_by(JobEvent.occurred_at).limit(1))
    if existing is None:
        return None
    if (existing.payload_json or {}).get("request_sha256") != request_sha:
        raise HTTPException(status_code=409, detail="Idempotency-Key request mismatch")
    return existing


def _add_control_event(
    session: Session,
    *,
    job: JobRun,
    action: str,
    actor: str,
    reason: str,
    idempotency_key: str,
    request_sha: str,
    from_status: str | None = None,
    to_status: str | None = None,
) -> JobEvent:
    event = JobEvent(
        event_id=f"admin-event-{uuid4().hex}",
        job_id=job.job_id,
        stage_run_id=None,
        attempt_id=None,
        event_type=action,
        from_status=from_status,
        to_status=to_status,
        actor_type="user",
        actor_id=actor,
        reason=reason,
        idempotency_key=idempotency_key,
        payload_json={"request_sha256": request_sha, "control_intent_only": True},
        occurred_at=_now(),
    )
    session.add(event)
    return event


@router.post("/jobs")
def create_sync_job(
    payload: AdminOperationCreateJobRequest,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    username: str = Depends(get_current_super_admin),
    session: Session = Depends(get_session_dependency),
):
    _require_trusted_origin(request)
    key = f"admin-create:{_idempotency_hash(idempotency_key)}"
    request_payload = {
        "start": payload.start.isoformat(),
        "end": payload.end.isoformat(),
        "target": payload.target,
        "reason": payload.reason,
    }
    request_sha = _canonical_sha256(request_payload)
    existing = _existing_control_event(
        session, job_id=None, idempotency_key=key, request_sha=request_sha
    )
    if existing is not None:
        return _success({**_job_summary(session.get(JobRun, existing.job_id)), "replayed": True})
    try:
        plan = plan_daily_sync(
            session,
            start=payload.start,
            end=payload.end,
            target=payload.target,
            requested_by=username,
            trigger_source="admin_control_api",
        )
        job = session.get(JobRun, plan.parent_job_id)
        if job is None:
            raise RuntimeError("planned parent job is missing")
        _add_control_event(
            session,
            job=job,
            action="admin_sync_created",
            actor=username,
            reason=payload.reason,
            idempotency_key=key,
            request_sha=request_sha,
            to_status=job.status,
        )
        session.commit()
    except (ValueError, IntegrityError) as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        session.rollback()
        raise
    return _success({**_job_summary(job), "replayed": False})


def _control_job(
    session: Session,
    *,
    job_id: str,
    action: str,
    reason: str,
    actor: str,
    idempotency_key: str,
) -> dict[str, Any]:
    job = session.get(JobRun, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    request_sha = _canonical_sha256(
        {"job_id": job_id, "action": action, "reason": reason}
    )
    key = f"admin-{action}:{_idempotency_hash(idempotency_key)}"
    if _existing_control_event(
        session, job_id=job_id, idempotency_key=key, request_sha=request_sha
    ) is not None:
        return {**_job_summary(job), "replayed": True, "intent": action}
    before = job.status
    now = _now()
    if action == "pause":
        if job.status in {"success", "failed", "cancelled"}:
            raise HTTPException(status_code=409, detail="Terminal job cannot be paused")
        job.pause_after_stage_requested_at = now
    elif action == "resume":
        job.pause_after_stage_requested_at = None
    elif action == "cancel":
        if job.status in {"pending", "queued", "retry_wait"}:
            job.status = "cancelled"
            job.finished_at = now
        elif job.status == "running":
            job.cancel_requested_at = now
        else:
            raise HTTPException(status_code=409, detail="Job cannot be cancelled")
    elif action == "retry":
        if job.status != "failed":
            raise HTTPException(status_code=409, detail="Only failed jobs can be retried")
        if int(job.attempt_count or 0) >= int(job.max_attempts or 3):
            raise HTTPException(status_code=409, detail="Job reached the retry limit")
        job.status = "retry_wait"
        job.next_retry_at = now
        job.finished_at = None
        job.error_code = None
        job.error_summary = None
        job.error_message = None
    else:  # pragma: no cover - private allowlist
        raise HTTPException(status_code=422, detail="Unsupported control action")
    _add_control_event(
        session,
        job=job,
        action=f"admin_{action}_requested",
        actor=actor,
        reason=reason,
        idempotency_key=key,
        request_sha=request_sha,
        from_status=before,
        to_status=job.status,
    )
    session.commit()
    return {**_job_summary(job), "replayed": False, "intent": action}


def _control_endpoint(action: str):
    def endpoint(
        job_id: str,
        payload: AdminControlIntentRequest,
        request: Request,
        idempotency_key: str = Header(alias="Idempotency-Key"),
        username: str = Depends(get_current_super_admin),
        session: Session = Depends(get_session_dependency),
    ):
        _require_trusted_origin(request)
        try:
            data = _control_job(
                session,
                job_id=job_id,
                action=action,
                reason=payload.reason,
                actor=username,
                idempotency_key=idempotency_key,
            )
        except HTTPException:
            session.rollback()
            raise
        except Exception:
            session.rollback()
            raise
        return _success(data)

    return endpoint


router.post("/jobs/{job_id}/pause")(_control_endpoint("pause"))
router.post("/jobs/{job_id}/resume")(_control_endpoint("resume"))
router.post("/jobs/{job_id}/cancel")(_control_endpoint("cancel"))
router.post("/jobs/{job_id}/retry")(_control_endpoint("retry"))


def _command_payload(command: OpsCommand) -> dict[str, Any]:
    return {
        "command_id": command.command_id,
        "command_type": command.command_type,
        "target_component": command.target_component,
        "requested_by": command.requested_by,
        "request_reason": command.request_reason,
        "confirmed_at": command.confirmed_at,
        "status": command.status,
        "related_job_id": command.related_job_id,
        "created_at": command.created_at,
        "started_at": command.started_at,
        "finished_at": command.finished_at,
        "expires_at": command.expires_at,
        "cooldown_until": command.cooldown_until,
        "result_code": command.result_code,
        "result_summary": sanitize_error_message(command.result_summary),
    }


@router.get("/commands")
def list_commands(
    limit: int = Query(default=50, ge=1, le=200),
    _username: str = Depends(get_current_super_admin),
    session: Session = Depends(get_session_dependency),
):
    rows = list(
        session.scalars(select(OpsCommand).order_by(OpsCommand.created_at.desc()).limit(limit))
    )
    return _success({"rows": [_command_payload(row) for row in rows]})


@router.post("/commands")
def create_command(
    payload: AdminOpsCommandRequest,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    username: str = Depends(get_current_super_admin),
    session: Session = Depends(get_session_dependency),
):
    _require_trusted_origin(request)
    if not payload.confirmed:
        raise HTTPException(status_code=422, detail="Explicit confirmation is required")
    key_hash = _idempotency_hash(idempotency_key)
    request_sha = _canonical_sha256(
        {
            "command_type": payload.command_type,
            "target_component": payload.target_component,
            "reason": payload.reason,
            "related_job_id": payload.related_job_id,
        }
    )
    existing = session.scalar(
        select(OpsCommand).where(OpsCommand.idempotency_key_hash == key_hash)
    )
    if existing is not None:
        if existing.request_payload_sha256 != request_sha:
            raise HTTPException(status_code=409, detail="Idempotency-Key request mismatch")
        return _success({**_command_payload(existing), "replayed": True})
    now = _now()
    active = session.scalar(
        select(OpsCommand)
        .where(OpsCommand.target_component == payload.target_component)
        .where(
            (OpsCommand.status.in_(("pending", "running")))
            | (OpsCommand.cooldown_until > now)
        )
        .order_by(OpsCommand.created_at.desc())
        .limit(1)
    )
    if active is not None:
        raise HTTPException(status_code=409, detail="Component command is active or cooling down")
    if payload.related_job_id and session.get(JobRun, payload.related_job_id) is None:
        raise HTTPException(status_code=422, detail="Related job does not exist")
    command = OpsCommand(
        command_id=f"ops-{uuid4().hex}",
        command_type="restart",
        target_component=payload.target_component,
        requested_by=username,
        request_reason=payload.reason,
        confirmed_at=now,
        status="pending",
        idempotency_key_hash=key_hash,
        request_payload_sha256=request_sha,
        related_job_id=payload.related_job_id,
        created_at=now,
        expires_at=now + OPS_COMMAND_TTL,
        cooldown_until=now + OPS_COMMAND_COOLDOWN,
        updated_at=now,
    )
    session.add(command)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        concurrent = session.scalar(
            select(OpsCommand).where(OpsCommand.idempotency_key_hash == key_hash)
        )
        if concurrent is not None and concurrent.request_payload_sha256 == request_sha:
            return _success({**_command_payload(concurrent), "replayed": True})
        raise HTTPException(status_code=409, detail="Component command already exists") from exc
    return _success({**_command_payload(command), "replayed": False})
