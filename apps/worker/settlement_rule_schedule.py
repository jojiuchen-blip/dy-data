"""Durable audit receipts for rule updates under either settlement schedule."""

from sqlalchemy.orm import Session

from apps.api.dy_api.models import JobRun
from apps.worker.repositories import finish_job_run, queue_job_run
from src.dy_data.settlement_schedule import monthly_settlement_enabled


MONTHLY_RULE_CHANGE_JOB = "settlement_rule_change"
MONTHLY_RULE_CHANGE_STATUS = "scheduled_monthly"


def schedule_rule_change(session: Session, job_id: str, metadata: dict) -> JobRun:
    if not monthly_settlement_enabled():
        return queue_job_run(session, job_id, "settlement_rebuild", metadata_json=metadata)
    job = queue_job_run(
        session, job_id, MONTHLY_RULE_CHANGE_JOB,
        metadata_json={**metadata, "settlement_calculation": "month_close"},
    )
    # The job records committed input, not a calculation that the queue can claim.
    return finish_job_run(session, job.job_id, status="success")


def rule_change_status(job: JobRun) -> str:
    if job.job_name == MONTHLY_RULE_CHANGE_JOB or (
        monthly_settlement_enabled() and job.status in {"queued", "retry_wait"}
    ):
        return MONTHLY_RULE_CHANGE_STATUS
    return job.status
