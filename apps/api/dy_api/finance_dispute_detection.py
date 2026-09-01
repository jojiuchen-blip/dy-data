from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.models import (
    JobRun,
    SettlementDispute,
    SettlementDisputeOrder,
    SettlementStatement,
    SettlementStatementEntry,
    utcnow,
)


FINANCE_DISPUTE_DETECTION_JOB_NAME = "finance_dispute_detection"
FINANCE_DISPUTE_DETECTION_LEASE = timedelta(minutes=5)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def finance_dispute_detection_item(job: JobRun) -> dict[str, Any]:
    """Serialize one persisted detection job without deriving a business verdict."""

    metadata = job.metadata_json or {}
    result = metadata.get("result")
    result_summary = None
    if isinstance(result, dict):
        consistency_status = result.get("consistencyStatus")
        if consistency_status == "CONSISTENT":
            result_summary = "正式数据库一致性检查通过"
        elif consistency_status == "INCONSISTENT":
            result_summary = "正式数据库一致性检查发现差异"
    started_at = _as_utc(job.started_at)
    completed_at = _as_utc(job.finished_at)
    updated_at = _as_utc(job.state_updated_at) or completed_at or started_at
    checks = result.get("checks") if isinstance(result, dict) else None
    evidence = result.get("evidence") if isinstance(result, dict) else None
    return {
        "detection_id": job.job_id,
        "dispute_id": metadata.get("disputeId"),
        "status": job.status.upper(),
        "stage": metadata.get("stage")
        or {
            "queued": "QUEUED",
            "running": "EVALUATING_CONSISTENCY",
            "succeeded": "COMPLETED",
            "failed": "FAILED",
        }.get(job.status, "UNKNOWN"),
        "progress_percent": max(
            0, min(int(metadata.get("progress") or 0), 100)
        ),
        "result_summary": result_summary,
        "checks": checks if isinstance(checks, dict) else {},
        "evidence": evidence if isinstance(evidence, list) else [],
        "failure_reason": metadata.get("failureReason") or job.error_message,
        "started_at": started_at,
        "completed_at": completed_at,
        "updated_at": updated_at,
    }


def _evaluate_dispute_consistency(
    session: Session, dispute: SettlementDispute
) -> dict[str, Any]:
    """Evaluate only immutable database facts; never accept or reject a dispute."""

    dispute_orders = list(
        session.scalars(
            select(SettlementDisputeOrder).where(
                SettlementDisputeOrder.dispute_id == dispute.dispute_id
            )
        )
    )
    submitted_statement = session.scalar(
        select(SettlementStatement).where(
            SettlementStatement.statement_id == dispute.statement_id
        )
    )
    current_statement = session.scalar(
        select(SettlementStatement).where(
            SettlementStatement.store_id == dispute.store_id,
            SettlementStatement.statement_month == dispute.statement_month,
            SettlementStatement.is_current.is_(True),
        )
    )
    submitted_entries = (
        list(
            session.scalars(
                select(SettlementStatementEntry).where(
                    SettlementStatementEntry.statement_id == dispute.statement_id,
                    SettlementStatementEntry.fee_direction == dispute.fee_direction,
                )
            )
        )
        if submitted_statement is not None
        else []
    )
    frozen_scope = {
        (entry.order_id, entry.coupon_id) for entry in submitted_entries
    }
    requested_scope = {
        (order.order_id, order.coupon_id) for order in dispute_orders
    }
    checks = {
        "linkedOrderScope": bool(requested_scope)
        and requested_scope.issubset(frozen_scope),
        "disputedAmountSum": bool(dispute_orders)
        and sum(order.disputed_amount_cent for order in dispute_orders)
        == dispute.disputed_amount_cent,
        "submittedStatementSnapshot": submitted_statement is not None
        and bool(submitted_entries),
        "currentStatementVersion": current_statement is not None
        and submitted_statement is not None
        and current_statement.version_no >= submitted_statement.version_no,
        "frozenEntryEvidence": bool(submitted_entries),
    }
    return {
        "consistencyStatus": (
            "CONSISTENT" if all(checks.values()) else "INCONSISTENT"
        ),
        "checks": checks,
        "submittedStatementId": (
            submitted_statement.statement_id
            if submitted_statement is not None
            else None
        ),
        "submittedStatementVersion": (
            submitted_statement.version_no
            if submitted_statement is not None
            else None
        ),
        "currentStatementId": (
            current_statement.statement_id
            if current_statement is not None
            else None
        ),
        "currentStatementVersion": (
            current_statement.version_no
            if current_statement is not None
            else None
        ),
        "linkedOrderCount": len(dispute_orders),
        "frozenEntryCount": len(submitted_entries),
        "evidence": [
            {
                "evidenceType": "SUBMITTED_STATEMENT",
                "recordId": (
                    submitted_statement.statement_id
                    if submitted_statement is not None
                    else None
                ),
                "version": (
                    submitted_statement.version_no
                    if submitted_statement is not None
                    else None
                ),
            },
            {
                "evidenceType": "CURRENT_STATEMENT",
                "recordId": (
                    current_statement.statement_id
                    if current_statement is not None
                    else None
                ),
                "version": (
                    current_statement.version_no
                    if current_statement is not None
                    else None
                ),
            },
            {
                "evidenceType": "DISPUTE_ORDER_SCOPE",
                "recordId": dispute.dispute_id,
                "recordCount": len(dispute_orders),
            },
        ],
        "note": "仅报告正式数据库一致性，不构成异议接受或驳回结论。",
    }


def _replace_metadata(job: JobRun, **updates: Any) -> None:
    metadata = dict(job.metadata_json or {})
    metadata.update(updates)
    job.metadata_json = metadata


def claim_finance_dispute_detection_job(
    session: Session,
    *,
    job_id: str,
    claim_id: str,
    claimed_at: datetime | None = None,
) -> bool:
    """Atomically claim one queued detection across API and worker processes."""

    job = session.get(JobRun, job_id)
    if (
        job is None
        or job.job_name != FINANCE_DISPUTE_DETECTION_JOB_NAME
        or job.status != "queued"
    ):
        return False
    metadata = dict(job.metadata_json or {})
    try:
        attempt_count = max(0, int(metadata.get("attemptCount") or 0))
    except (TypeError, ValueError):
        attempt_count = 0
    claim_time = _as_utc(claimed_at or utcnow())
    assert claim_time is not None
    metadata.update(
        {
            "attemptCount": attempt_count + 1,
            "claimId": claim_id,
            "claimedAt": claim_time.isoformat(),
            "progress": max(0, min(int(metadata.get("progress") or 0), 100)),
            "failureReason": None,
            "stage": "CLAIMED",
        }
    )
    lease_expires_at = claim_time + FINANCE_DISPUTE_DETECTION_LEASE
    claimed = session.execute(
        update(JobRun)
        .where(
            JobRun.job_id == job_id,
            JobRun.job_name == FINANCE_DISPUTE_DETECTION_JOB_NAME,
            JobRun.status == "queued",
        )
        .values(
            status="running",
            finished_at=None,
            error_message=None,
            claim_token=claim_id,
            lease_expires_at=lease_expires_at,
            state_updated_at=claim_time,
            metadata_json=metadata,
        )
    )
    session.flush()
    return claimed.rowcount == 1


def fail_claimed_finance_dispute_detection_job(
    session: Session,
    *,
    job_id: str,
    claim_id: str,
    failed_at: datetime,
    failure_reason: str,
) -> bool:
    """Fail one claim only if its observed lease state is still current."""

    job = session.get(JobRun, job_id)
    metadata = dict(job.metadata_json or {}) if job is not None else {}
    if (
        job is None
        or job.job_name != FINANCE_DISPUTE_DETECTION_JOB_NAME
        or job.status != "running"
        or job.claim_token != claim_id
        or metadata.get("claimId") != claim_id
    ):
        return False
    observed_state_updated_at = job.state_updated_at
    observed_lease_expires_at = job.lease_expires_at
    metadata.update(
        {
            "stage": "FAILED",
            "result": None,
            "failureReason": failure_reason,
        }
    )
    failed = session.execute(
        update(JobRun)
        .where(
            JobRun.job_id == job_id,
            JobRun.job_name == FINANCE_DISPUTE_DETECTION_JOB_NAME,
            JobRun.status == "running",
            JobRun.claim_token == claim_id,
            (
                JobRun.state_updated_at.is_(None)
                if observed_state_updated_at is None
                else JobRun.state_updated_at == observed_state_updated_at
            ),
            (
                JobRun.lease_expires_at.is_(None)
                if observed_lease_expires_at is None
                else JobRun.lease_expires_at == observed_lease_expires_at
            ),
        )
        .values(
            status="failed",
            success_count=0,
            failed_count=1,
            finished_at=failed_at,
            error_message=failure_reason,
            claim_token=None,
            lease_expires_at=None,
            state_updated_at=failed_at,
            metadata_json=metadata,
        )
        .execution_options(synchronize_session=False)
    )
    session.flush()
    return failed.rowcount == 1


def run_finance_dispute_detection_job(
    *,
    job_id: str,
    session_factory: sessionmaker[Session],
    claim_id: str | None = None,
) -> None:
    """Run one detection outside the request and persist every observable state."""

    with session_factory() as session:
        active_claim_id = claim_id or f"api-background-{uuid4().hex}"
        if claim_id is None:
            if not claim_finance_dispute_detection_job(
                session,
                job_id=job_id,
                claim_id=active_claim_id,
            ):
                session.rollback()
                return
            session.commit()
        job = session.get(JobRun, job_id)
        metadata = job.metadata_json if job is not None else {}
        if (
            job is None
            or job.job_name != FINANCE_DISPUTE_DETECTION_JOB_NAME
            or job.status != "running"
            or job.claim_token != active_claim_id
            or (metadata or {}).get("claimId") != active_claim_id
        ):
            return
        observed_state_updated_at = job.state_updated_at
        observed_lease_expires_at = job.lease_expires_at
        try:
            heartbeat_at = utcnow()
            heartbeat_metadata = dict(metadata or {})
            heartbeat_metadata.update(
                {
                    "progress": 10,
                    "stage": "EVALUATING_CONSISTENCY",
                    "failureReason": None,
                }
            )
            heartbeat = session.execute(
                update(JobRun)
                .where(
                    JobRun.job_id == job_id,
                    JobRun.job_name
                    == FINANCE_DISPUTE_DETECTION_JOB_NAME,
                    JobRun.status == "running",
                    JobRun.claim_token == active_claim_id,
                    (
                        JobRun.state_updated_at.is_(None)
                        if observed_state_updated_at is None
                        else JobRun.state_updated_at == observed_state_updated_at
                    ),
                    (
                        JobRun.lease_expires_at.is_(None)
                        if observed_lease_expires_at is None
                        else JobRun.lease_expires_at == observed_lease_expires_at
                    ),
                )
                .values(
                    state_updated_at=heartbeat_at,
                    lease_expires_at=(
                        heartbeat_at + FINANCE_DISPUTE_DETECTION_LEASE
                    ),
                    metadata_json=heartbeat_metadata,
                )
                .execution_options(synchronize_session=False)
            )
            if heartbeat.rowcount != 1:
                session.rollback()
                return
            session.commit()

            dispute_id = str(heartbeat_metadata.get("disputeId") or "")
            dispute = session.scalar(
                select(SettlementDispute).where(
                    SettlementDispute.dispute_id == dispute_id
                )
            )
            if dispute is None:
                raise ValueError("异议记录不存在")
            result = _evaluate_dispute_consistency(session, dispute)
            completed_at = utcnow()
            completed_metadata = dict(heartbeat_metadata)
            completed_metadata.update(
                {
                    "progress": 100,
                    "stage": "COMPLETED",
                    "result": result,
                    "failureReason": None,
                }
            )
            completed = session.execute(
                update(JobRun)
                .where(
                    JobRun.job_id == job_id,
                    JobRun.job_name
                    == FINANCE_DISPUTE_DETECTION_JOB_NAME,
                    JobRun.status == "running",
                    JobRun.claim_token == active_claim_id,
                    JobRun.state_updated_at == heartbeat_at,
                    JobRun.lease_expires_at
                    == heartbeat_at + FINANCE_DISPUTE_DETECTION_LEASE,
                )
                .values(
                    status="succeeded",
                    success_count=1,
                    failed_count=0,
                    finished_at=completed_at,
                    error_message=None,
                    claim_token=None,
                    lease_expires_at=None,
                    state_updated_at=completed_at,
                    metadata_json=completed_metadata,
                )
                .execution_options(synchronize_session=False)
            )
            if completed.rowcount != 1:
                session.rollback()
                return
            session.commit()
        except Exception:
            session.rollback()
            failure_reason = "检测任务执行失败，请重试或联系管理员查看受控日志。"
            failed_at = utcnow()
            if fail_claimed_finance_dispute_detection_job(
                session,
                job_id=job_id,
                claim_id=active_claim_id,
                failed_at=failed_at,
                failure_reason=failure_reason,
            ):
                session.commit()
            else:
                session.rollback()
