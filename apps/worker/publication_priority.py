"""Read-only admission for collection ahead of static analysis builds."""

from datetime import datetime

from sqlalchemy.orm import Session

from apps.api.dy_api.models import JobRun
from apps.worker import priority_scheduler as priority
from apps.worker.repositories import heavy_sync_rate_limit_cooldown_active, parent_sync_gate_allows_claim


def priority_sync_pending(session: Session, *, now: datetime | None = None) -> bool:
    """Whether existing required work can claim before another analysis build.

    This probe never creates a plan, stamps metadata, takes row/advisory locks,
    or changes a retry budget. The actual supervisor still owns atomic claim.
    Old optional backfills and obsolete recovery generations cannot reserve a
    publication window. A job created just after this observation waits at most
    the existing bounded build before the next probe.
    """
    if heavy_sync_rate_limit_cooldown_active(session):
        return False
    local_now = priority.local_shanghai_now(now)
    target = priority._resolve_daily_target_date(
        session, priority.priority_business_date(local_now), local_now,
    )
    if target is not None:
        state = priority._day_state(target, priority._priority_rows_for_day(session, target))
        daily = state.rows
        if state.state == "failed":
            daily = tuple(row for row in daily if priority._is_manual_domain_row(row)
                          or (row.job_kind == "parent_sync" and priority._row_target(row) == "all"))
        manual_blockers = any(priority._is_manual_domain_row(row)
                              and row.status in {"pending", "running", "retry_wait", "failed"}
                              for row in daily)
        for row in daily:
            if manual_blockers and not (priority._is_manual_domain_row(row)
                                       or row.job_kind == "parent_sync"):
                continue
            if _runnable(session, row, local_now):
                return True
    return any(_runnable(session, row, local_now)
               for row in priority._dimension_rows_for_day(session, local_now.date()))


def _runnable(session: Session, row: JobRun, now: datetime) -> bool:
    maximum = (3 if row.max_attempts is None else row.max_attempts) + (row.quota_pause_count or 0)
    if (row.status not in {"pending", "retry_wait"}
            or not priority._is_ready_pending(row, now)
            or (row.attempt_count or 0) >= maximum
            or row.cancel_requested_at is not None
            or row.pause_after_stage_requested_at is not None
            or (row.started_at is not None and priority._as_shanghai(row.started_at) > now)
            or row.execution_slot != "heavy_sync"
            or priority._priority_purpose(row, priority.DAILY_REQUIRED_PURPOSE) != priority.DAILY_REQUIRED_PURPOSE):
        return False
    parent = session.get(JobRun, row.parent_job_id) if row.parent_job_id else None
    if (parent is None or parent.status in {"success", "failed", "cancelled"}
            or parent.cancel_requested_at is not None
            or parent.pause_after_stage_requested_at is not None):
        return False
    return parent_sync_gate_allows_claim(session, row, lock=False)
