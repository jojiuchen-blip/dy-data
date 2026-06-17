from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from apps.api.dy_api.db import session_scope
from apps.api.dy_api.models import JobRun, utcnow
from apps.worker.pipeline import sanitize_error_message
from apps.worker.repositories import finish_job_run
from apps.worker.settlement import run_settlement_job


SETTLEMENT_REBUILD_JOB_NAME = "settlement_rebuild"


@dataclass(frozen=True)
class QueuedSettlementRebuildResult:
    processed_job_id: str | None = None
    superseded_job_ids: tuple[str, ...] = ()


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
