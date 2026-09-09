"""Bounded Shanghai-day scheduler for the priority daily sync mode.

The legacy scheduler owns the rolling compatibility mode.  This module keeps
the new mode deliberately small: one tick plans at most one missing day and
invokes at most one fenced heavy job.  The database remains the source of
truth for leases, stage checkpoints, retries, and publication state.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
import logging
import os
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.db import session_scope
from apps.api.dy_api.models import JobRun
from apps.worker.daily_windows import DailySyncPlan, plan_daily_sync
from apps.worker.repositories import parent_sync_gate_allows_claim
from apps.worker.sync_config import load_sync_config


LOGGER = logging.getLogger(__name__)

SHANGHAI_TIMEZONE_NAME = "Asia/Shanghai"
SHANGHAI_TIMEZONE = ZoneInfo(SHANGHAI_TIMEZONE_NAME)
PRIORITY_DAILY_MODE = "priority_daily"
PRIORITY_CONFIG_VERSION = "priority-daily-v1"
PRIORITY_DAILY_CUTOFF = time(2, 0)
DIMENSION_REFRESH_INTERVAL = timedelta(hours=2)
MAX_HISTORY_SCAN_DAYS = 3_660
MAX_PRIORITY_ROWS = 2_000
DIMENSION_TARGETS = ("shop_pois", "aweme_bindings", "backend_aweme_export")
DAILY_JOB_KINDS = ("parent_sync", "date_sync", "finalize")
DAILY_REQUIRED_PURPOSE = "daily_required"
HISTORY_PURPOSE = "history"


@dataclass(frozen=True, slots=True)
class PriorityTickResult:
    """Outcome of one bounded scheduler tick."""

    mode: str
    action: str
    business_date: date | None = None
    selected_job_id: str | None = None
    selected_purpose: str | None = None
    status: str | None = None
    reason: str | None = None
    product_sync_job_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-safe operational snapshot."""

        return {
            "mode": self.mode,
            "action": self.action,
            "business_date": self.business_date.isoformat()
            if self.business_date is not None
            else None,
            "selected_job_id": self.selected_job_id,
            "selected_purpose": self.selected_purpose,
            "status": self.status,
            "reason": self.reason,
            "product_sync_job_id": self.product_sync_job_id,
        }


@dataclass(frozen=True, slots=True)
class _HistoryGap:
    business_date: date
    state: str
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class _DayState:
    state: str
    parent: JobRun | None
    rows: tuple[JobRun, ...]


def resolve_scheduler_mode(env: Mapping[str, str] | None = None) -> str:
    """Resolve the scheduler family without changing the legacy mode."""

    source = os.environ if env is None else env
    value = (source.get("WORKER_SCHEDULER_MODE") or "legacy").strip().lower()
    if value not in {"legacy", PRIORITY_DAILY_MODE}:
        raise ValueError(
            "WORKER_SCHEDULER_MODE must be legacy or priority_daily."
        )
    return value


def local_shanghai_now(now: datetime | None = None) -> datetime:
    """Normalize a clock value to timezone-aware Asia/Shanghai time."""

    current = now or datetime.now(SHANGHAI_TIMEZONE)
    if current.tzinfo is None:
        return current.replace(tzinfo=SHANGHAI_TIMEZONE)
    return current.astimezone(SHANGHAI_TIMEZONE)


def priority_business_date(now: datetime | None = None) -> date:
    """Return the day eligible for the daily priority window.

    At or after 02:00 the target is yesterday.  Before 02:00 it is the day
    before yesterday, which prevents a pre-cutoff tick from consuming the
    quota reserved for the upcoming daily collection.
    """

    local_now = local_shanghai_now(now)
    days_back = 1 if local_now.time() >= PRIORITY_DAILY_CUTOFF else 2
    return local_now.date() - timedelta(days=days_back)


def is_priority_cutoff_open(now: datetime | None = None) -> bool:
    """Return whether the Shanghai 02:00 daily window has opened."""

    return local_shanghai_now(now).time() >= PRIORITY_DAILY_CUTOFF


def _day_window(business_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(business_date, time.min, tzinfo=SHANGHAI_TIMEZONE)
    return start, start + timedelta(days=1)


def ensure_daily_priority_plan(
    session: Session,
    business_date: date,
    *,
    now: datetime | None = None,
    requested_by: str = "priority-daily-scheduler",
    trigger_source: str = "scheduler",
) -> DailySyncPlan:
    """Create or replay one idempotent ``target=all`` daily plan."""

    start, end = _day_window(business_date)
    plan = plan_daily_sync(
        session,
        start=start,
        end=end,
        target="all",
        requested_by=requested_by,
        trigger_source=trigger_source,
        config_version=PRIORITY_CONFIG_VERSION,
    )
    _stamp_plan_metadata(
        session,
        parent_job_id=plan.parent_job_id,
        purpose=DAILY_REQUIRED_PURPOSE,
        priority_date=business_date,
        request_budget_date=local_shanghai_now(now).date(),
    )
    return plan


def run_priority_daily_tick(
    factory: sessionmaker[Session] | Callable[[], Session] | None,
    *,
    now: datetime | None = None,
    child_runner: Callable[..., Any] | None = None,
    product_sync_runner: Callable[..., str | None] | None = None,
) -> PriorityTickResult:
    """Run one bounded priority tick.

    A tick performs no unbounded queue drain.  It chooses one exact heavy job,
    or one product refresh, and returns.  Future retry timestamps and active
    leases are respected by the selector before the fenced supervisor is
    invoked.
    """

    local_now = local_shanghai_now(now)
    if factory is None:
        return _snapshot(
            PriorityTickResult(
                mode=PRIORITY_DAILY_MODE,
                action="blocked",
                business_date=priority_business_date(local_now),
                reason="database_unavailable",
            )
        )

    daily_date = priority_business_date(local_now)
    with session_scope(factory) as session:
        target_date = _resolve_daily_target_date(session, daily_date, local_now)
        if target_date is None:
            # There is no daily plan to create before 02:00.  Keep the clock
            # date for the ancillary two-hour dimension cadence; daily state
            # remains ``missing`` and therefore cannot unlock history.
            target_date = daily_date

        if is_priority_cutoff_open(local_now):
            ensure_daily_priority_plan(session, target_date, now=local_now)

        daily_rows = _priority_rows_for_day(session, target_date)
        _stamp_unmarked_daily_rows(
            session,
            daily_rows,
            priority_date=target_date,
            request_budget_date=local_now.date(),
        )
        daily_rows = _priority_rows_for_day(session, target_date)
        day_state = _day_state(target_date, daily_rows)
        daily_selection_rows = daily_rows
        if day_state.state == "failed":
            # A failed domain must not release the all-domain date/finalize
            # closure, but unrelated manual domains can still make progress.
            daily_selection_rows = tuple(
                row
                for row in daily_rows
                if _is_manual_domain_row(row)
                or (row.job_kind == "parent_sync" and _row_target(row) == "all")
            )
        daily_candidate = _select_candidate(
            daily_selection_rows,
            now=local_now,
            allowed_purposes={DAILY_REQUIRED_PURPOSE},
            session=session,
        )
        if daily_candidate is not None:
            if _is_active_running(daily_candidate, local_now):
                return _snapshot(
                    _waiting_result(
                        target_date,
                        daily_candidate,
                        reason="active_lease",
                    )
                )
            selected = (target_date, daily_candidate)
        else:
            selected = None

        live_heavy = _live_heavy_job(session, local_now)
        if selected is not None:
            if (
                live_heavy is not None
                and live_heavy.job_id != selected[1].job_id
                and not _is_active_running(selected[1], local_now)
            ):
                return _snapshot(
                    _waiting_result(
                        target_date,
                        live_heavy,
                        reason="heavy_slot_busy",
                    )
                )

        elif live_heavy is not None:
            return _snapshot(
                _waiting_result(
                    target_date,
                    live_heavy,
                    reason="heavy_slot_busy",
                )
            )
        else:
            # Dimensions are an independent cadence.  A daily retry or
            # terminal failure must not starve stores, bindings, or the
            # browser roster; only history remains gated by daily publication.
            dimension_candidate = _select_due_dimension_candidate(
                session,
                local_now,
            )
            if dimension_candidate is not None:
                if _is_active_running(dimension_candidate, local_now):
                    return _snapshot(
                        _waiting_result(
                            local_now.date(),
                            dimension_candidate,
                            reason="active_dimension_lease",
                        )
                    )
                selected = (local_now.date(), dimension_candidate)
            else:
                due_dimension_plans = _plan_due_dimensions(session, local_now)
                if due_dimension_plans:
                    dimension_rows = _dimension_rows_for_day(
                        session,
                        local_now.date(),
                    )
                    dimension_candidate = _select_candidate(
                        dimension_rows,
                        now=local_now,
                        allowed_purposes={DAILY_REQUIRED_PURPOSE},
                        session=session,
                    )
                    if dimension_candidate is not None:
                        if _is_active_running(dimension_candidate, local_now):
                            return _snapshot(
                                _waiting_result(
                                    local_now.date(),
                                    dimension_candidate,
                                    reason="active_dimension_lease",
                                )
                            )
                        selected = (local_now.date(), dimension_candidate)

        if selected is not None:
            selected_date, selected_job = selected
            job_id = selected_job.job_id
            purpose = _priority_purpose(selected_job, DAILY_REQUIRED_PURPOSE)
        else:
            selected_date = None
            selected_job = None
            job_id = None
            purpose = None

    if selected_job is not None:
        active_runner = child_runner or _default_child_runner
        result = active_runner(factory, job_id)
        return _snapshot(
            PriorityTickResult(
                mode=PRIORITY_DAILY_MODE,
                action="executed",
                business_date=selected_date,
                selected_job_id=job_id,
                selected_purpose=purpose,
                status=_result_status(result),
                reason=_result_reason(result),
            )
        )

    active_product_runner = product_sync_runner or _default_product_sync_runner
    product_job_id = _run_product_sync(
        active_product_runner,
        factory,
        local_now,
    )
    if product_job_id:
        with session_scope(factory) as session:
            _stamp_job_metadata(
                session,
                job_id=product_job_id,
                purpose=DAILY_REQUIRED_PURPOSE,
                priority_date=daily_date,
                request_budget_date=local_now.date(),
                extra={"priority_kind": "product"},
            )
        return _snapshot(
            PriorityTickResult(
                mode=PRIORITY_DAILY_MODE,
                action="product_sync",
                business_date=daily_date,
                selected_purpose=DAILY_REQUIRED_PURPOSE,
                product_sync_job_id=product_job_id,
                status="success",
            )
        )

    # History is optional work.  Preserve the next daily window before 02:00,
    # and keep it behind a complete, published daily closure after the cutoff.
    if not is_priority_cutoff_open(local_now):
        return _snapshot(
            PriorityTickResult(
                mode=PRIORITY_DAILY_MODE,
                action="waiting",
                business_date=daily_date,
                selected_purpose=HISTORY_PURPOSE,
                reason="before_cutoff",
            )
        )
    if day_state.state != "success":
        reason = (
            "daily_failed"
            if day_state.state == "failed"
            else "daily_incomplete"
        )
        return _snapshot(
            PriorityTickResult(
                mode=PRIORITY_DAILY_MODE,
                action="blocked" if day_state.state == "failed" else "waiting",
                business_date=daily_date,
                selected_purpose=HISTORY_PURPOSE,
                reason=reason,
            )
        )

    # Request-level PriorityRequestGovernor admission owns the shared endpoint
    # reserve.  A scheduler-wide refund precheck would read its reduced history
    # ceiling as the base quota and reserve the same calls a second time.
    with session_scope(factory) as session:
        history_start, history_end = _history_bounds(
            session,
            daily_date=daily_date,
        )
        gap = _find_history_gap(
            session,
            upper_date=history_end,
            history_start=history_start,
        )
        if gap is None:
            return _snapshot(
                PriorityTickResult(
                    mode=PRIORITY_DAILY_MODE,
                    action="idle",
                    business_date=daily_date,
                    reason="history_complete",
                )
            )
        if gap.state == "failed":
            return _snapshot(
                PriorityTickResult(
                    mode=PRIORITY_DAILY_MODE,
                    action="blocked",
                    business_date=gap.business_date,
                    selected_purpose=HISTORY_PURPOSE,
                    reason=gap.reason or "history_failed",
                )
            )

        gap_rows = _priority_rows_for_day(session, gap.business_date)
        manual_candidate = _select_candidate(
            gap_rows,
            now=local_now,
            allowed_purposes={DAILY_REQUIRED_PURPOSE},
            session=session,
        )
        if manual_candidate is not None:
            if _is_active_running(manual_candidate, local_now):
                return _snapshot(
                    _waiting_result(
                        gap.business_date,
                        manual_candidate,
                        reason="active_manual_priority_lease",
                    )
                )
            selected_job = manual_candidate
            selected_date = gap.business_date
            purpose = DAILY_REQUIRED_PURPOSE
        else:
            ensure_history_priority_plan(
                session,
                gap.business_date,
                now=local_now,
            )
            history_rows = _priority_rows_for_day(session, gap.business_date)
            history_candidate = _select_candidate(
                history_rows,
                now=local_now,
                allowed_purposes={HISTORY_PURPOSE, DAILY_REQUIRED_PURPOSE},
                session=session,
            )
            if history_candidate is None:
                return _snapshot(
                    PriorityTickResult(
                        mode=PRIORITY_DAILY_MODE,
                        action="waiting",
                        business_date=gap.business_date,
                        selected_purpose=HISTORY_PURPOSE,
                        reason="history_plan_waiting_for_parent_gate",
                    )
                )
            if _is_active_running(history_candidate, local_now):
                return _snapshot(
                    _waiting_result(
                        gap.business_date,
                        history_candidate,
                        reason="active_history_lease",
                    )
                )
            selected_job = history_candidate
            selected_date = gap.business_date
            purpose = _priority_purpose(history_candidate, HISTORY_PURPOSE)
        job_id = selected_job.job_id

    active_runner = child_runner or _default_child_runner
    result = active_runner(factory, job_id)
    return _snapshot(
        PriorityTickResult(
            mode=PRIORITY_DAILY_MODE,
            action="executed",
            business_date=selected_date,
            selected_job_id=job_id,
            selected_purpose=purpose,
            status=_result_status(result),
            reason=_result_reason(result),
        )
    )


def ensure_history_priority_plan(
    session: Session,
    business_date: date,
    *,
    now: datetime | None = None,
) -> DailySyncPlan:
    """Create one history plan, preserving an explicitly daily manual plan."""

    start, end = _day_window(business_date)
    plan = plan_daily_sync(
        session,
        start=start,
        end=end,
        target="all",
        requested_by="priority-daily-scheduler",
        trigger_source="history",
        config_version=PRIORITY_CONFIG_VERSION,
    )
    plan_rows = list(
        session.scalars(
            select(JobRun).where(
                (JobRun.job_id == plan.parent_job_id)
                | (JobRun.parent_job_id == plan.parent_job_id)
            )
        )
    )
    if not any(
        _priority_purpose(row, "") == DAILY_REQUIRED_PURPOSE
        for row in plan_rows
    ):
        _stamp_plan_metadata(
            session,
            parent_job_id=plan.parent_job_id,
            purpose=HISTORY_PURPOSE,
            priority_date=business_date,
            request_budget_date=local_shanghai_now(now).date(),
        )
    return plan


def _resolve_daily_target_date(
    session: Session,
    regular_target: date,
    now: datetime,
) -> date | None:
    if is_priority_cutoff_open(now):
        return regular_target

    manual_target = _latest_active_manual_day(session, now)
    if manual_target is not None:
        return manual_target

    fallback_rows = _priority_rows_for_day(session, regular_target)
    if fallback_rows:
        return regular_target
    return None


def _latest_active_manual_day(session: Session, now: datetime) -> date | None:
    rows = list(
        session.scalars(
            select(JobRun)
            .where(
                JobRun.config_version == PRIORITY_CONFIG_VERSION,
                JobRun.job_kind.in_(DAILY_JOB_KINDS),
                JobRun.status.in_(("pending", "running", "retry_wait")),
            )
            .order_by(JobRun.business_date.desc(), JobRun.job_id)
            .limit(MAX_PRIORITY_ROWS)
        )
    )
    candidates: list[date] = []
    for row in rows:
        purpose = _priority_purpose(row, DAILY_REQUIRED_PURPOSE)
        if purpose != DAILY_REQUIRED_PURPOSE:
            continue
        if row.status == "retry_wait" and not _is_retry_due(row, now):
            continue
        if row.business_date is not None:
            candidates.append(row.business_date)
        elif row.window_start is not None:
            candidates.append(_as_shanghai(row.window_start).date())
    return max(candidates) if candidates else None


def _priority_rows_for_day(session: Session, business_date: date) -> tuple[JobRun, ...]:
    rows = list(
        session.scalars(
            select(JobRun)
            .where(
                JobRun.config_version == PRIORITY_CONFIG_VERSION,
                JobRun.job_kind.in_(("range_sync", *DAILY_JOB_KINDS)),
                _business_date_predicate(business_date),
            )
            .order_by(JobRun.job_id)
            .limit(MAX_PRIORITY_ROWS)
        )
    )
    return tuple(row for row in rows if _job_business_date(row) == business_date)


def _dimension_rows_for_day(
    session: Session,
    business_date: date,
) -> tuple[JobRun, ...]:
    rows = list(
        session.scalars(
            select(JobRun)
            .where(
                JobRun.config_version.like(f"{PRIORITY_CONFIG_VERSION}-dimensions-%"),
                JobRun.job_kind.in_(("parent_sync", "finalize")),
                _business_date_predicate(business_date),
            )
            .order_by(JobRun.job_id)
            .limit(MAX_PRIORITY_ROWS)
        )
    )
    return tuple(
        row
        for row in rows
        if _row_target(row) in DIMENSION_TARGETS
        and _job_business_date(row) == business_date
    )


def _all_priority_rows(
    session: Session,
    *,
    lower_date: date,
    upper_date: date,
) -> tuple[JobRun, ...]:
    if upper_date < lower_date:
        return ()
    range_start = _day_window(lower_date)[0]
    range_end = _day_window(upper_date)[1]
    rows = list(
        session.scalars(
            select(JobRun)
            .where(
                JobRun.config_version == PRIORITY_CONFIG_VERSION,
                JobRun.job_kind.in_(("range_sync", *DAILY_JOB_KINDS)),
                or_(
                    and_(
                        JobRun.business_date.is_not(None),
                        JobRun.business_date >= lower_date,
                        JobRun.business_date <= upper_date,
                    ),
                    and_(
                        JobRun.business_date.is_(None),
                        JobRun.window_start >= range_start,
                        JobRun.window_start < range_end,
                    ),
                ),
            )
            .order_by(JobRun.business_date, JobRun.window_start, JobRun.job_id)
        )
    )
    return tuple(row for row in rows if _job_business_date(row) is not None)


def _business_date_predicate(business_date: date):
    """Filter explicit dates and Shanghai-local parent windows in SQL."""

    start, end = _day_window(business_date)
    return or_(
        JobRun.business_date == business_date,
        and_(
            JobRun.business_date.is_(None),
            JobRun.window_start >= start,
            JobRun.window_start < end,
        ),
    )


def _day_state(business_date: date, rows: tuple[JobRun, ...]) -> _DayState:
    parent = next(
        (
            row
            for row in rows
            if row.job_kind == "range_sync" and _row_target(row) == "all"
        ),
        None,
    )
    executable_rows = tuple(
        row
        for row in rows
        if row.job_kind in DAILY_JOB_KINDS
        and _row_target(row) == "all"
    )
    manual_rows = tuple(
        row
        for row in rows
        if row.job_kind in DAILY_JOB_KINDS
        and _row_target(row) not in {None, "all"}
        and _priority_purpose(row, DAILY_REQUIRED_PURPOSE) == DAILY_REQUIRED_PURPOSE
    )
    if any(row.status == "failed" for row in (*executable_rows, *manual_rows)):
        return _DayState("failed", parent, rows)
    if parent is None:
        return _DayState("missing", None, rows)
    if parent.status == "failed":
        return _DayState("failed", parent, rows)
    finalize_rows = tuple(row for row in executable_rows if row.job_kind == "finalize")
    published = (
        parent.status == "success"
        and len(finalize_rows) == 1
        and finalize_rows[0].status == "success"
        and all(row.status == "success" for row in executable_rows)
        and all(row.status == "success" for row in manual_rows)
    )
    return _DayState("success" if published else "incomplete", parent, rows)


def _find_history_gap(
    session: Session,
    *,
    upper_date: date,
    history_start: date,
) -> _HistoryGap | None:
    if upper_date < history_start:
        return None
    grouped: dict[date, list[JobRun]] = {}
    for row in _all_priority_rows(
        session,
        lower_date=history_start,
        upper_date=upper_date,
    ):
        row_date = _job_business_date(row)
        if row_date is not None:
            grouped.setdefault(row_date, []).append(row)
    scan_limit = min(
        MAX_HISTORY_SCAN_DAYS,
        (upper_date - history_start).days + 1,
    )
    current = upper_date
    for _ in range(scan_limit):
        day_rows = tuple(grouped.get(current, ()))
        state = _day_state(current, day_rows)
        if state.state == "success":
            current -= timedelta(days=1)
            continue
        if state.state == "failed":
            return _HistoryGap(
                current,
                "failed",
                f"history_day_failed:{current.isoformat()}",
            )
        return _HistoryGap(current, "missing" if state.state == "missing" else "incomplete")
    return None


def _history_bounds(session: Session, *, daily_date: date) -> tuple[date, date]:
    config = load_sync_config(session)
    history_start = date.fromisoformat(config.history_start[:10])
    upper_date = daily_date - timedelta(days=1)
    if config.history_end:
        configured_end = date.fromisoformat(config.history_end[:10]) - timedelta(days=1)
        upper_date = min(upper_date, configured_end)
    return history_start, upper_date


def _select_due_dimension_candidate(
    session: Session,
    now: datetime,
) -> JobRun | None:
    rows = _dimension_rows_for_day(session, now.date())
    return _select_candidate(
        rows,
        now=now,
        allowed_purposes={DAILY_REQUIRED_PURPOSE},
        session=session,
    )


def _plan_due_dimensions(
    session: Session,
    now: datetime,
) -> tuple[DailySyncPlan, ...]:
    if not _dimension_refresh_due(session, now):
        return ()
    slot_hour = (now.hour // 2) * 2
    slot = f"{now:%Y%m%d}{slot_hour:02d}"
    config_version = f"{PRIORITY_CONFIG_VERSION}-dimensions-{slot}"
    start, end = _day_window(now.date())
    plans: list[DailySyncPlan] = []
    for target in DIMENSION_TARGETS:
        plan = plan_daily_sync(
            session,
            start=start,
            end=end,
            target=target,
            requested_by="priority-daily-scheduler",
            trigger_source="dimension_refresh",
            config_version=config_version,
        )
        _stamp_plan_metadata(
            session,
            parent_job_id=plan.parent_job_id,
            purpose=DAILY_REQUIRED_PURPOSE,
            priority_date=now.date(),
            request_budget_date=now.date(),
            extra={
                "priority_kind": "dimensions",
                "priority_dimension_target": target,
                "priority_refresh_slot": slot,
            },
        )
        plans.append(plan)
    return tuple(plans)


def _dimension_refresh_due(session: Session, now: datetime) -> bool:
    rows = list(
        session.scalars(
            select(JobRun)
            .where(
                JobRun.job_kind == "parent_sync",
                JobRun.status == "success",
                JobRun.config_version.like(f"{PRIORITY_CONFIG_VERSION}-dimensions-%"),
            )
            .order_by(JobRun.finished_at.desc(), JobRun.job_id)
            .limit(MAX_PRIORITY_ROWS)
        )
    )
    timestamps = [
        _as_shanghai(row.finished_at or row.started_at)
        for row in rows
        if _row_target(row) in DIMENSION_TARGETS
        and (row.finished_at is not None or row.started_at is not None)
    ]
    if not timestamps:
        return True
    return now - max(timestamps) >= DIMENSION_REFRESH_INTERVAL


def _live_heavy_job(session: Session, now: datetime) -> JobRun | None:
    rows = list(
        session.scalars(
            select(JobRun)
            .where(
                JobRun.execution_slot == "heavy_sync",
                JobRun.status == "running",
            )
            .order_by(JobRun.job_id)
            .limit(20)
        )
    )
    for row in rows:
        if _is_active_running(row, now):
            return row
    return None


def _select_candidate(
    rows: tuple[JobRun, ...],
    *,
    now: datetime,
    allowed_purposes: set[str],
    session: Session,
) -> JobRun | None:
    manual_blockers = tuple(
        row
        for row in rows
        if _is_manual_domain_row(row)
        and row.status in {"pending", "running", "retry_wait", "failed"}
    )
    filtered = [
        row
        for row in rows
        if _priority_purpose(row, DAILY_REQUIRED_PURPOSE) in allowed_purposes
        and row.job_kind in DAILY_JOB_KINDS
        and (
            _is_active_running(row, now)
            or _is_expired_running(row, now)
            or _is_ready_pending(row, now)
        )
        and _parent_gate_allows_selection(session, row)
    ]
    if not filtered:
        return None
    if manual_blockers:
        # A manual domain plan contributes to the final published scope.  Give
        # it the heavy slot before the all-domain date/finalize rows, and keep
        # those rows out of the selector while a manual domain is unfinished.
        manual_candidates = [row for row in filtered if _is_manual_domain_row(row)]
        if manual_candidates:
            active = [row for row in manual_candidates if _is_active_running(row, now)]
            return min(active or manual_candidates, key=_candidate_sort_key)
        parent_candidates = [
            row
            for row in filtered
            if row.job_kind == "parent_sync"
            and _row_target(row) == "all"
            and _priority_purpose(row, DAILY_REQUIRED_PURPOSE)
            == DAILY_REQUIRED_PURPOSE
        ]
        if parent_candidates:
            active = [row for row in parent_candidates if _is_active_running(row, now)]
            return min(active or parent_candidates, key=_candidate_sort_key)
        return None
    active = [row for row in filtered if _is_active_running(row, now)]
    candidates = active or filtered
    return min(candidates, key=_candidate_sort_key)


def _candidate_sort_key(row: JobRun) -> tuple[int, int, int, str, str]:
    target = _row_target(row)
    target_rank = 0 if target not in {None, "all"} else 1
    kind_rank = {"parent_sync": 0, "date_sync": 1, "finalize": 2}.get(
        row.job_kind or "",
        3,
    )
    status_rank = 0 if row.status == "running" else 1
    date_value = _job_business_date(row)
    return (
        target_rank,
        kind_rank,
        status_rank,
        date_value.isoformat() if date_value is not None else "",
        row.job_id,
    )


def _is_manual_domain_row(row: JobRun) -> bool:
    return (
        row.job_kind in DAILY_JOB_KINDS
        and _row_target(row) not in {None, "all"}
        and _priority_purpose(row, DAILY_REQUIRED_PURPOSE)
        == DAILY_REQUIRED_PURPOSE
    )


def _parent_gate_allows_selection(session: Session, row: JobRun) -> bool:
    if row.job_kind not in {"parent_sync", "date_sync", "finalize"}:
        return True
    try:
        return parent_sync_gate_allows_claim(session, row)
    except Exception:
        LOGGER.exception(
            "priority_scheduler_parent_gate_check_failed job_id=%s",
            row.job_id,
        )
        return False


def _is_ready_pending(row: JobRun, now: datetime) -> bool:
    if row.status == "pending":
        return True
    return row.status == "retry_wait" and _is_retry_due(row, now)


def _is_retry_due(row: JobRun, now: datetime) -> bool:
    return row.next_retry_at is not None and _as_shanghai(row.next_retry_at) <= now


def _is_active_running(row: JobRun, now: datetime) -> bool:
    return row.status == "running" and (
        row.lease_expires_at is None
        or _as_shanghai(row.lease_expires_at) > now
    )


def _is_expired_running(row: JobRun, now: datetime) -> bool:
    return row.status == "running" and row.lease_expires_at is not None and _as_shanghai(row.lease_expires_at) <= now


def _stamp_unmarked_daily_rows(
    session: Session,
    rows: tuple[JobRun, ...],
    *,
    priority_date: date,
    request_budget_date: date,
) -> None:
    for row in rows:
        if row.job_kind not in DAILY_JOB_KINDS:
            continue
        metadata = dict(row.metadata_json or {})
        purpose = metadata.get("priority_purpose")
        if purpose not in {DAILY_REQUIRED_PURPOSE, HISTORY_PURPOSE}:
            purpose = DAILY_REQUIRED_PURPOSE
        if purpose == DAILY_REQUIRED_PURPOSE:
            metadata["priority_purpose"] = DAILY_REQUIRED_PURPOSE
            metadata["priority_mode"] = PRIORITY_DAILY_MODE
            metadata["priority_business_date"] = priority_date.isoformat()
            metadata["request_budget_date"] = request_budget_date.isoformat()
            metadata["quota_business_date"] = request_budget_date.isoformat()
            row.metadata_json = metadata


def _stamp_plan_metadata(
    session: Session,
    *,
    parent_job_id: str,
    purpose: str,
    priority_date: date,
    request_budget_date: date,
    extra: Mapping[str, Any] | None = None,
) -> None:
    rows = list(
        session.scalars(
            select(JobRun).where(
                (JobRun.job_id == parent_job_id)
                | (JobRun.parent_job_id == parent_job_id)
            )
        )
    )
    values = {
        "priority_purpose": purpose,
        "priority_mode": PRIORITY_DAILY_MODE,
        "priority_business_date": priority_date.isoformat(),
        "request_budget_date": request_budget_date.isoformat(),
        "quota_business_date": request_budget_date.isoformat(),
    }
    if extra:
        values.update(extra)
    for row in rows:
        metadata = dict(row.metadata_json or {})
        metadata.update(values)
        row.metadata_json = metadata


def _stamp_job_metadata(
    session: Session,
    *,
    job_id: str,
    purpose: str,
    priority_date: date,
    request_budget_date: date,
    extra: Mapping[str, Any] | None = None,
) -> None:
    job = session.get(JobRun, job_id)
    if job is None:
        return
    metadata = dict(job.metadata_json or {})
    metadata.update(
        {
            "priority_purpose": purpose,
            "priority_mode": PRIORITY_DAILY_MODE,
            "priority_business_date": priority_date.isoformat(),
            "request_budget_date": request_budget_date.isoformat(),
            "quota_business_date": request_budget_date.isoformat(),
            **(dict(extra) if extra else {}),
        }
    )
    job.metadata_json = metadata


def _priority_purpose(row: JobRun | None, default: str) -> str:
    if row is None:
        return default
    value = (row.metadata_json or {}).get("priority_purpose")
    return value if value in {DAILY_REQUIRED_PURPOSE, HISTORY_PURPOSE} else default


def _row_target(row: JobRun) -> str | None:
    value = (row.metadata_json or {}).get("target")
    return value if isinstance(value, str) else None


def _job_business_date(row: JobRun) -> date | None:
    if row.business_date is not None:
        return row.business_date
    if row.window_start is not None:
        return _as_shanghai(row.window_start).date()
    return None


def _as_shanghai(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=SHANGHAI_TIMEZONE)
    return value.astimezone(SHANGHAI_TIMEZONE)


def _default_child_runner(factory: Any, job_id: str) -> Any:
    from apps.worker.scheduler import run_daily_child

    return run_daily_child(factory, job_id=job_id)


def _default_product_sync_runner(
    factory: Any,
    *,
    now: datetime,
) -> str | None:
    from apps.worker.scheduler import run_scheduled_product_sync

    return run_scheduled_product_sync(factory, now=now)


def _run_product_sync(
    runner: Callable[..., str | None],
    factory: Any,
    now: datetime,
) -> str | None:
    """Call a product runner while retaining compatibility with simple fakes."""

    try:
        return runner(factory, now=now)
    except TypeError as exc:
        # Test and embedding callers historically supplied ``factory`` only.
        # Retry only when the callable rejects the keyword at its boundary;
        # internal TypeErrors still propagate through the second invocation.
        if "now" not in str(exc):
            raise
        return runner(factory)


def _result_status(result: Any) -> str | None:
    value = getattr(result, "status", None)
    return getattr(value, "value", value)


def _result_reason(result: Any) -> str | None:
    return getattr(result, "error_summary", None)


def _waiting_result(
    business_date: date,
    job: JobRun,
    *,
    reason: str,
) -> PriorityTickResult:
    return PriorityTickResult(
        mode=PRIORITY_DAILY_MODE,
        action="waiting",
        business_date=business_date,
        selected_job_id=job.job_id,
        selected_purpose=_priority_purpose(job, DAILY_REQUIRED_PURPOSE),
        status=job.status,
        reason=reason,
    )


def _snapshot(result: PriorityTickResult) -> PriorityTickResult:
    LOGGER.info(
        "priority_scheduler_snapshot mode=%s business_date=%s "
        "selected_job_id=%s selected_purpose=%s action=%s status=%s reason=%s",
        result.mode,
        result.business_date.isoformat() if result.business_date else None,
        result.selected_job_id,
        result.selected_purpose,
        result.action,
        result.status,
        result.reason,
    )
    return result


__all__ = [
    "DAILY_REQUIRED_PURPOSE",
    "DIMENSION_REFRESH_INTERVAL",
    "HISTORY_PURPOSE",
    "PRIORITY_CONFIG_VERSION",
    "PRIORITY_DAILY_CUTOFF",
    "PRIORITY_DAILY_MODE",
    "PriorityTickResult",
    "ensure_daily_priority_plan",
    "ensure_history_priority_plan",
    "is_priority_cutoff_open",
    "local_shanghai_now",
    "priority_business_date",
    "resolve_scheduler_mode",
    "run_priority_daily_tick",
]
