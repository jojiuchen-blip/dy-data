"""Natural-month close planner (Asia/Shanghai), watermark-versioned.

Dispatch is keyed by a *verifiable* collection-completion watermark, not by a
raw impact counter: a month is only billable once every business date in that
month has a successful ``finalize`` job row (``job_runs.job_kind='finalize'``,
``status='success'``, ``business_date`` inside the month).  That is the same
durable signal the daily scheduler uses to call a day complete.

Consequences:

* the job id embeds the watermark fingerprint, so a month that gains late
  source after a successful close produces a *new* stable versioned job;
* an unchanged watermark is idempotent (the same id already exists);
* an incomplete month is **fail-closed**: nothing is dispatched, because a
  partial month must never be published as a bill;
* a locked month (``statement_status = 4``) is refused outright.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.db import session_scope
from apps.api.dy_api.models import (
    JobRun,
    SettlementFeeResult,
    SettlementFeeResultCurrent,
    SettlementStatement,
)
from apps.worker.priority_scheduler import _day_state, _priority_rows_for_day
from apps.worker.repositories import queue_job_run
from apps.worker.settlement import FORMAL_SETTLEMENT_START
from apps.worker.settlement_rebuild import (
    SETTLEMENT_REBUILD_JOB_NAME,
    settlement_month_scope_metadata,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
LOCKED_STATEMENT_STATUS = 4

# Automatic month close is enabled.  Every per-month guard stays in force:
# fail-closed completeness (every Shanghai business day published), a positive
# current-result count, lock refusal (statement_status = 4) and single-slot
# serialization against other rebuilds.  A month that is not verifiably ready
# therefore enqueues nothing rather than billing partially.
MONTH_CLOSE_ENABLED = True

WATERMARK_INCOMPLETE = "watermark_incomplete"
LOCKED = "locked"
ACTIVE_REBUILD = "active_rebuild"
READY = "ready"


def previous_business_month(now: datetime | None = None) -> str:
    """The last fully completed Shanghai calendar month (``YYYY-MM``)."""

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    local = current.astimezone(SHANGHAI)
    return (local.date().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")


def month_business_dates(business_month: str) -> tuple[date, ...]:
    """Every calendar date of one ``YYYY-MM`` month."""

    start = date.fromisoformat(f"{business_month}-01")
    next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return tuple(
        start + timedelta(days=offset)
        for offset in range((next_month - start).days)
    )


def month_current_results_fingerprint(
    session: Session, business_month: str
) -> tuple[str, int]:
    """Fingerprint of the month's *current* commission results.

    Ordered by ``(coupon_id, fee_direction, fee_result_id)`` so the value is
    stable for one result set and changes the moment late source adds or
    replaces a current result.
    """

    rows = session.execute(
        select(
            SettlementFeeResult.coupon_id,
            SettlementFeeResult.fee_direction,
            SettlementFeeResult.fee_result_id,
        )
        .join(
            SettlementFeeResultCurrent,
            SettlementFeeResultCurrent.fee_result_id
            == SettlementFeeResult.fee_result_id,
        )
        .where(SettlementFeeResult.original_business_month == business_month)
        .order_by(
            SettlementFeeResult.coupon_id,
            SettlementFeeResult.fee_direction,
            SettlementFeeResult.fee_result_id,
        )
    ).all()
    payload = ";".join(f"{coupon}|{direction}|{result}" for coupon, direction, result in rows)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12], len(rows)


def month_source_watermark(session: Session, business_month: str) -> str | None:
    """Fingerprint of the month's billable source, or ``None`` when not ready.

    Readiness requires **both**:

    1. every Shanghai business day of the month is *published* — the real
       priority-scheduler condition (``_day_state`` over
       ``_priority_rows_for_day``), because production does not write a per-day
       ``business_date`` on ``finalize`` rows; and
    2. at least one current commission result exists for the month, so a month
       whose rules/account mapping are not yet in place can never reach
       statement or projection generation.

    The revision per day is that day's finalize ``job_id`` and the result set is
    fingerprinted by ``(coupon, direction, fee_result_id)``, so late source
    advances the watermark while older or failed rows never do.  Anything
    unknown or missing returns ``None``: fail closed.
    """

    revisions: list[str] = []
    for day in month_business_dates(business_month):
        state = _day_state(day, _priority_rows_for_day(session, day))
        if state.state != "success":
            return None
        finalize_rows = [row for row in state.rows if row.job_kind == "finalize"]
        if len(finalize_rows) != 1:
            return None
        revisions.append(f"{day.isoformat()}@{finalize_rows[0].job_id}")

    results_fingerprint, result_count = month_current_results_fingerprint(
        session, business_month
    )
    if result_count == 0:
        # Zero commission results must never reach statement generation.
        return None

    payload = ",".join(revisions) + "||" + results_fingerprint
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def month_close_preflight(session: Session, business_month: str) -> tuple[str, str | None]:
    """Return ``(state, watermark)`` for one month without changing anything."""

    if business_month < FORMAL_SETTLEMENT_START.strftime("%Y-%m"):
        return WATERMARK_INCOMPLETE, None
    locked = session.scalar(
        select(SettlementStatement.statement_id)
        .where(
            SettlementStatement.statement_month == business_month,
            SettlementStatement.statement_status == LOCKED_STATEMENT_STATUS,
        )
        .limit(1)
    )
    if locked is not None:
        return LOCKED, None
    watermark = month_source_watermark(session, business_month)
    if watermark is None:
        return WATERMARK_INCOMPLETE, None
    if _active_rebuild_exists(session):
        return ACTIVE_REBUILD, watermark
    return READY, watermark


def month_close_job_id(business_month: str, watermark: str) -> str:
    """Stable idempotency key per (month, source watermark)."""

    return f"settlement-month-close-{business_month}-w{watermark}"


def ensure_month_close_job(
    factory: sessionmaker, *, now: datetime | None = None
) -> str | None:
    """Dispatch the previous month's close once per watermark.

    Returns the job id when a job exists or was created, ``None`` when the
    month is not verifiably complete, is locked, or another rebuild is active.
    """

    if factory is None:
        return None
    if not MONTH_CLOSE_ENABLED:
        # Fail closed: never dispatch an unverified automatic close.
        return None
    business_month = previous_business_month(now)
    with session_scope(factory) as session:
        state, watermark = month_close_preflight(session, business_month)
        if watermark is None:
            return None
        job_id = month_close_job_id(business_month, watermark)
        if session.get(JobRun, job_id) is not None:
            return job_id
        if state == ACTIVE_REBUILD:
            return None
        queue_job_run(
            session,
            job_id,
            SETTLEMENT_REBUILD_JOB_NAME,
            metadata_json={
                **settlement_month_scope_metadata(business_month),
                "trigger": "month_close",
                "source_run_id": job_id,
                "source_watermark": watermark,
            },
        )
    return job_id


def _active_rebuild_exists(session: Session) -> bool:
    return (
        session.scalar(
            select(JobRun.job_id)
            .where(
                JobRun.job_name == SETTLEMENT_REBUILD_JOB_NAME,
                JobRun.status.in_(("queued", "running", "retry_wait")),
            )
            .limit(1)
        )
        is not None
    )


__all__ = [
    "ACTIVE_REBUILD",
    "LOCKED",
    "READY",
    "SHANGHAI",
    "WATERMARK_INCOMPLETE",
    "ensure_month_close_job",
    "month_business_dates",
    "month_close_job_id",
    "month_close_preflight",
    "month_source_watermark",
    "previous_business_month",
]
