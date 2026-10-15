"""Controlled day recovery: one independent, auditable plan generation.

An exhausted daily chain cannot be re-opened in place — ``begin_job_attempt``
derives ``attempt_number = attempt_count + 1`` and ``job_attempts`` is unique on
``(job_id, attempt_number)``, so reusing a row collides with the attempts it
already recorded.  ``plan_daily_sync`` derives a range parent id from
``(start, end, target, data_source, config_version)``, so a distinct
``config_version`` yields a *brand new* parent whose children are new job ids
with empty attempt space: no migration, and every original ``JobAttempt`` row is
left exactly as it was.

The generation is identified by an explicit ordinal carried in metadata (never
by job-id ordering), bounded per original day plan, and keyed by a stable
recovery request key so a repeated request returns the same generation instead of
stacking new ones.

This module is also the single authority for *generation awareness* across the
control plane: :func:`priority_generation_config` is the one predicate every
scheduler selection point must use so a recovery generation is visible exactly
where its original day plan was, and :func:`generation_order` /
:func:`winning_generation` decide which generation currently owns a day.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import JobAttempt, JobRun
from apps.worker.daily_windows import (
    SHANGHAI_TIMEZONE,
    DailySyncPlan,
    plan_daily_sync,
)

# Duplicated from ``priority_scheduler.PRIORITY_CONFIG_VERSION`` on purpose:
# ``priority_scheduler`` depends on this module for generation awareness, so
# importing it back here would be a cycle.  ``tests/test_priority_scheduler.py``
# asserts the two constants stay equal.
PRIORITY_CONFIG_VERSION = "priority-daily-v1"
RECOVERY_CONFIG_PREFIX = f"{PRIORITY_CONFIG_VERSION}-recovery"
DIMENSION_CONFIG_PREFIX = f"{PRIORITY_CONFIG_VERSION}-dimensions-"
MAX_RECOVERY_GENERATIONS = 2
RECOVERY_GENERATIONS_KEY = "recovery_generations"
RECOVERY_ROOT_KEY = "recovery_root_job_id"
RECOVERY_ORDINAL_KEY = "recovery_ordinal"
RECOVERED_BY_KEY = "recovered_by"
BASE_GENERATION_ORDINAL = 0
# Only a plan that has genuinely stopped may be replaced by a generation.  A
# ``success`` plan would be re-published (duplicate billing) and a live plan is
# still owned by the scheduler, so neither is recoverable.
RECOVERABLE_ROOT_STATUSES = frozenset({"failed", "cancelled"})


class DayRecoveryNotAllowed(ValueError):
    """Raised when a day plan may not be recovered."""


def recovery_config_version(request_key: str) -> str:
    """Traceable, deterministic config identity for one recovery generation."""

    normalized = (request_key or "").strip()
    if not normalized:
        raise DayRecoveryNotAllowed("recovery request key must not be blank")
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
    return f"{RECOVERY_CONFIG_PREFIX}-{digest}"


def priority_generation_config(config_version: str | None) -> bool:
    """Return whether a config version carries daily generation work.

    Recovery generations re-use their day's whole chain under a derived
    ``config_version``.  Every scheduler selection point therefore has to match
    this predicate instead of comparing to the bare base version, otherwise a
    recovered day is invisible to the selector that must finish it — and to the
    month-close readiness watermark that must wait for it.
    """

    if not isinstance(config_version, str):
        return False
    return config_version == PRIORITY_CONFIG_VERSION or config_version.startswith(
        RECOVERY_CONFIG_PREFIX
    )


def recovery_generations(parent: JobRun) -> list[dict[str, Any]]:
    recorded = (parent.metadata_json or {}).get(RECOVERY_GENERATIONS_KEY)
    return list(recorded) if isinstance(recorded, list) else []


def recovery_generation_by_request_key(
    session: Session,
    request_key: str,
) -> JobRun | None:
    """Return the generation already created for one recovery request key.

    The generation's ``config_version`` is a pure function of the request key, so
    this is the single, global answer to "did this request already happen?".
    Callers must use it *before* planning: without it, a duplicate request whose
    original day plan recorded nothing (window collision) would be refused instead
    of being replayed as the same generation.
    """

    normalized = (request_key or "").strip()
    if not normalized:
        return None
    return session.scalars(
        select(JobRun).where(
            JobRun.job_kind == "range_sync",
            JobRun.config_version == recovery_config_version(normalized),
            JobRun.parent_job_id.is_(None),
        )
    ).first()


def generation_ordinal(row: JobRun) -> int:
    """Explicit generation ordinal of one planned row (base generation is 0)."""

    raw = (row.metadata_json or {}).get(RECOVERY_ORDINAL_KEY)
    if isinstance(raw, bool):
        return BASE_GENERATION_ORDINAL
    if isinstance(raw, int):
        return raw if raw > BASE_GENERATION_ORDINAL else BASE_GENERATION_ORDINAL
    if isinstance(raw, str):
        try:
            parsed = int(raw.strip())
        except ValueError:
            return BASE_GENERATION_ORDINAL
        return parsed if parsed > BASE_GENERATION_ORDINAL else BASE_GENERATION_ORDINAL
    return BASE_GENERATION_ORDINAL


def generation_order(row: JobRun) -> tuple[int, str]:
    """Total, explicit order over generations — never job-id lexicographic.

    The ordinal is the authoritative term.  The recovery request digest is only a
    tie-break for malformed duplicate metadata, because a sha256 digest prefix is
    random relative to time; ``job_id`` is deliberately not used as the primary or
    secondary term, so "highest id wins" can never decide a generation.
    """

    if generation_ordinal(row) > BASE_GENERATION_ORDINAL:
        if not isinstance(row.config_version, str) or not row.config_version.startswith(
            RECOVERY_CONFIG_PREFIX
        ):
            # A non-recovery row must never outrank the base generation by
            # carrying stray recovery metadata.
            return (BASE_GENERATION_ORDINAL, "")
        return (
            generation_ordinal(row),
            row.config_version[len(RECOVERY_CONFIG_PREFIX) :],
        )
    return (BASE_GENERATION_ORDINAL, "")


def winning_generation(rows: tuple[JobRun, ...] | list[JobRun]) -> JobRun | None:
    """Return the newest valid generation of one business day, or ``None``.

    Superseded generations stay in the ledger as immutable failure evidence but
    stop owning the day: their failed children must not fail the day and their
    pending children must not be claimed again.
    """

    candidates = [
        row
        for row in rows
        if row.job_kind == "range_sync"
        and row.parent_job_id is None
        and (row.metadata_json or {}).get("target") == "all"
        and priority_generation_config(row.config_version)
    ]
    if not candidates:
        return None
    return max(candidates, key=generation_order)


def plan_day_recovery(
    session: Session,
    *,
    parent: JobRun,
    request_key: str,
    reason: str,
    actor: str,
    now: datetime | None = None,
) -> tuple[DailySyncPlan, bool]:
    """Create (or replay) one independent recovery generation for a day plan.

    Returns ``(plan, replayed)``.  ``request_key`` makes the request idempotent;
    the generation ordinal is explicit and bounded; the original parent keeps its
    status, attempts and error evidence and only gains an additive audit entry.

    Order of operations matters for concurrency: the original parent is locked
    *first*, and the generation ledger is re-read on the locked row, so two
    callers can never both allocate ordinal ``n`` and both stamp the recovered-by
    link.  Every eligibility fact (status, cancel, pause, live parent lease, live
    child lease, generation budget) is re-checked on that same locked row.
    """

    if parent.job_kind != "range_sync" or parent.parent_job_id is not None:
        raise DayRecoveryNotAllowed("only a range parent can be recovered")
    if parent.metadata_json is None:
        parent.metadata_json = {}
    # Fail fast on the obvious self-recovery request before taking any lock.
    _assert_recoverable_plan(parent)

    reference = now or datetime.now(timezone.utc)
    # Lock the original plan, then re-check every eligibility fact on the locked
    # row: a concurrent request or a state change must not be waved through.
    session.execute(
        select(JobRun.job_id).where(JobRun.job_id == parent.job_id).with_for_update()
    ).scalars().all()
    session.refresh(parent)
    _assert_recoverable_plan(parent)
    _assert_terminal_shape(session, parent, reference)
    if parent.cancel_requested_at is not None:
        raise DayRecoveryNotAllowed("cancelled day plan cannot be recovered")
    if parent.pause_after_stage_requested_at is not None:
        raise DayRecoveryNotAllowed("day plan has a pending pause request")
    if _holds_live_lease(parent.lease_expires_at, reference):
        raise DayRecoveryNotAllowed("day plan is still leased")
    active_children = _active_children(session, parent, reference)
    if active_children:
        # A recovery generation duplicates the whole chain.  Starting it while
        # any child of the plan still holds a live lease would run the same day
        # twice against the same upstream account, so the plan must settle first.
        raise DayRecoveryNotAllowed(
            "day plan still has an active child job: "
            + ", ".join(sorted(active_children))
        )

    config_version = recovery_config_version(request_key)
    generations = recovery_generations(parent)
    already_recorded = any(
        entry.get("config_version") == config_version for entry in generations
    )
    if already_recorded:
        # Idempotent replay: `plan_daily_sync` is deterministic for the same
        # window/target/source/version, so it returns the existing generation.
        # ``trigger_source`` is part of that identity, which is why the replay
        # has to pass the same one the creating request passed.
        return (
            plan_daily_sync(
                session,
                start=parent.window_start,
                end=parent.window_end,
                target="all",
                requested_by=f"recovery:{actor}",
                trigger_source="recovery",
                data_source=parent.data_source,
                config_version=config_version,
            ),
            True,
        )
    if len(generations) >= MAX_RECOVERY_GENERATIONS:
        raise DayRecoveryNotAllowed("recovery generation budget exhausted for this day")
    in_flight = _in_flight_generation(session, parent, generations, reference)
    if in_flight is not None:
        # A newer key must not stack a *parallel* generation on top of one that is
        # still running or still executable: two generations of the same day both
        # holding the heavy slot would collect the same window twice.
        raise DayRecoveryNotAllowed(
            f"recovery generation is still in flight: {in_flight}"
        )

    ordinal = len(generations) + 1
    plan = plan_daily_sync(
        session,
        start=parent.window_start,
        end=parent.window_end,
        target="all",
        requested_by=f"recovery:{actor}",
        trigger_source="recovery",
        data_source=parent.data_source,
        config_version=config_version,
    )
    recovery_parent = session.get(JobRun, plan.parent_job_id)
    if recovery_parent is None:  # pragma: no cover - plan_daily_sync guarantees it
        raise DayRecoveryNotAllowed("recovery plan was not persisted")
    _validate_recovery_plan(
        plan,
        origin=parent,
        config_version=config_version,
        recovery_parent=recovery_parent,
    )

    metadata = dict(recovery_parent.metadata_json or {})
    metadata.update(
        {
            RECOVERY_ROOT_KEY: parent.job_id,
            RECOVERY_ORDINAL_KEY: ordinal,
            "recovery_request_key": request_key,
            "recovery_reason": reason,
            "recovery_actor": actor,
            "recovery_of_config_version": parent.config_version,
        }
    )
    recovery_parent.metadata_json = metadata

    original_metadata = dict(parent.metadata_json or {})
    original_metadata[RECOVERY_GENERATIONS_KEY] = [
        *generations,
        {
            "ordinal": ordinal,
            "config_version": config_version,
            "parent_job_id": recovery_parent.job_id,
            "request_key": request_key,
            "reason": reason,
            "actor": actor,
            "requested_at": reference.isoformat(),
        },
    ]
    # Additive linkage only: status, attempt_count, error evidence and every
    # existing JobAttempt row stay exactly as recorded.  Only this one additive
    # field is written back, so a concurrent request that recorded a generation
    # of its own between the read and the flush cannot be erased here.
    parent.metadata_json = {
        **original_metadata,
        RECOVERED_BY_KEY: recovery_parent.job_id,
    }
    session.flush()
    return plan, False


def _validate_recovery_plan(
    plan: DailySyncPlan,
    *,
    origin: JobRun,
    config_version: str,
    recovery_parent: JobRun,
) -> None:
    """Prove the recovered plan really is a fresh generation of ``origin``.

    The generation's ``config_version`` embeds only the recovery request digest,
    so a caller re-using one request key for a different day would otherwise be
    handed the first day's plan.  ``plan_daily_sync`` derives the parent id from
    ``(window, target, source, version)`` and validates window/target/source/
    version against the row it found, so the window, source and root checks below
    are what makes the generation trustworthy: a mismatch is refused, never
    merged.
    """

    if (
        recovery_parent.job_kind != "range_sync"
        or recovery_parent.parent_job_id is not None
        or recovery_parent.config_version != config_version
        or (recovery_parent.metadata_json or {}).get("target") != "all"
    ):
        raise DayRecoveryNotAllowed("recovery plan identity is invalid")
    if not _same_plan_window(plan.window_start, origin.window_start) or not (
        _same_plan_window(plan.window_end, origin.window_end)
    ):
        raise DayRecoveryNotAllowed(
            "recovery request key already belongs to another day plan"
        )
    if (
        recovery_parent.data_source != origin.data_source
        or plan.data_source != origin.data_source
    ):
        raise DayRecoveryNotAllowed("recovery plan source identity is invalid")
    existing_root = (recovery_parent.metadata_json or {}).get(RECOVERY_ROOT_KEY)
    if existing_root is not None and existing_root != origin.job_id:
        # Same window and source is not enough: a generation is bound to the one
        # plan row it replaces.  Two different range parents can describe the
        # same day (different request budget dates), and pasting one over the
        # other would silently transfer failure evidence between them.
        raise DayRecoveryNotAllowed(
            "recovery request key already belongs to another day plan"
        )


def _assert_recoverable_plan(parent: JobRun) -> None:
    """Prove the plan's immutable identity permits a replacement generation.

    The *status* is not decided here: a terminal parent (``failed``/``cancelled``)
    is always recoverable, but the production failure shape keeps the range
    parent ``pending`` while its single date child has already exhausted every
    attempt.  That blocked shape is decided on the locked row in
    :func:`_assert_terminal_shape`, where the children can be read.
    """

    if (parent.metadata_json or {}).get(RECOVERY_ROOT_KEY) is not None:
        raise DayRecoveryNotAllowed("a recovery generation cannot itself be recovered")
    if not parent.window_start or not parent.window_end:
        raise DayRecoveryNotAllowed("day plan has an incomplete window")
    if not parent.data_source or not parent.config_version:
        raise DayRecoveryNotAllowed("day plan lacks its source identity")
    if parent.config_version != PRIORITY_CONFIG_VERSION:
        raise DayRecoveryNotAllowed(
            "only a base daily generation can be recovered"
        )
    if (parent.metadata_json or {}).get("target") != "all":
        raise DayRecoveryNotAllowed("only an all-target day plan can be recovered")
    if not _spans_exactly_one_shanghai_day(parent):
        raise DayRecoveryNotAllowed("day plan must span exactly one Shanghai day")


def _assert_terminal_shape(
    session: Session,
    parent: JobRun,
    reference: datetime,
) -> None:
    """Only a stopped plan may be replaced: terminal, or genuinely blocked.

    The two production failure shapes are:

    * the range parent itself is terminal (``failed``/``cancelled``); or
    * the parent is still ``pending`` but its day is blocked — exactly one
      ``date_sync`` child is terminal-failed with its attempt budget exhausted,
      the parent's own ``parent_sync`` work has already finished, and no child
      holds a live lease.  This is the real 09-14/16/20/25/28 shape.

    A ``pending`` plan whose children are still runnable is *not* blocked: the
    scheduler still owns it, and a replacement would collect the window twice.
    """

    if parent.status in RECOVERABLE_ROOT_STATUSES:
        return
    if parent.status != "pending":
        raise DayRecoveryNotAllowed(
            f"day plan is not terminal: status={parent.status}"
        )
    children = list(
        session.scalars(
            select(JobRun).where(
                JobRun.parent_job_id == parent.job_id,
                JobRun.job_kind.in_(("parent_sync", "date_sync", "finalize")),
            )
        )
    )
    date_children = [child for child in children if child.job_kind == "date_sync"]
    parent_sync = [child for child in children if child.job_kind == "parent_sync"]
    if len(date_children) != 1 or not parent_sync:
        raise DayRecoveryNotAllowed(
            "pending day plan is not a single-day blocked chain"
        )
    date_child = date_children[0]
    max_attempts = int(date_child.max_attempts or 0)
    attempts_used = int(date_child.attempt_count or 0)
    if date_child.status != "failed" or attempts_used < max_attempts:
        raise DayRecoveryNotAllowed(
            "pending day plan still has a runnable date child"
        )
    if any(
        child.status != "success" for child in parent_sync
    ):
        raise DayRecoveryNotAllowed(
            "pending day plan has not finished its parent sync work"
        )
    if any(
        child.status == "running"
        and _holds_live_lease(child.lease_expires_at, reference)
        for child in children
    ):
        raise DayRecoveryNotAllowed("day plan still has an active child job")
    if any(
        child.status in {"pending", "queued", "running", "retry_wait"}
        for child in children
        if child.job_kind == "date_sync"
    ):
        raise DayRecoveryNotAllowed("day plan still has an unfinished date child")


def _holds_live_lease(lease_expires_at: datetime | None, reference: datetime) -> bool:
    if lease_expires_at is None:
        return False
    if lease_expires_at.tzinfo is None:
        lease_expires_at = lease_expires_at.replace(tzinfo=timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return lease_expires_at > reference


def _active_children(
    session: Session,
    parent: JobRun,
    reference: datetime,
) -> list[str]:
    """Ids of the plan's children that are still running under a live lease."""

    children = list(
        session.scalars(
            select(JobRun).where(
                JobRun.parent_job_id == parent.job_id,
                JobRun.job_kind.in_(("parent_sync", "date_sync", "finalize")),
            )
        )
    )
    return [
        child.job_id
        for child in children
        if child.status == "running"
        and _holds_live_lease(child.lease_expires_at, reference)
    ]


def _in_flight_generation(
    session: Session,
    root: JobRun,
    generations: list[dict[str, Any]],
    reference: datetime,
) -> str | None:
    """Id of a recorded generation that has not stopped yet, if any.

    "In flight" is deliberately broad — a pending or retryable generation is
    still going to run, so a second generation started now would race it for the
    same window rather than replace it.  The single exception is the production
    stopped shape proven by :func:`_pending_generation_is_stopped` against the
    original root and its own ledger entry: the newest generation is pending
    only because its finalize failed with its attempt budget exhausted, so the
    original ledger may append the next ordinal.
    """

    parent_ids = [
        entry.get("parent_job_id")
        for entry in generations
        if isinstance(entry.get("parent_job_id"), str)
    ]
    if not parent_ids:
        return None
    candidates = list(
        session.scalars(
            select(JobRun).where(
                JobRun.job_id.in_(parent_ids),
                JobRun.job_kind == "range_sync",
            )
        )
    )
    entries = {
        entry.get("parent_job_id"): entry
        for entry in generations
        if isinstance(entry.get("parent_job_id"), str)
    }
    latest_ordinal = max(
        (
            int(entry.get("ordinal"))
            for entry in entries.values()
            if isinstance(entry.get("ordinal"), int)
        ),
        default=None,
    )
    for candidate in candidates:
        if candidate.status in {"success", "failed", "cancelled"}:
            continue
        if candidate.status == "pending" and _pending_generation_is_stopped(
            session,
            candidate,
            reference,
            root=root,
            entry=entries.get(candidate.job_id, {}),
            latest_ordinal=latest_ordinal,
        ):
            # The newest generation genuinely stopped: its collection children
            # really succeeded and its single finalize failed with its attempt
            # budget exhausted.  It owns no future work, so the original ledger
            # may append the next ordinal instead of racing a doomed row.
            continue
        # Any other non-terminal generation — running, queued, retry_wait, or a
        # pending row that does not match the stopped shape — is still going to
        # run.  A `retry_wait` with a future `next_retry_at` is not "settled":
        # its child still owns the day's retry budget, so a second generation
        # would stack onto it and collect the window twice.
        return candidate.job_id
    return None


def _attempt_budget_exhausted(job: JobRun) -> bool:
    attempt_count = max(0, int(job.attempt_count or 0))
    budget = int(job.max_attempts or 3) + max(0, int(job.quota_pause_count or 0))
    return attempt_count >= budget


def _pending_generation_is_stopped(
    session: Session,
    candidate: JobRun,
    reference: datetime,
    *,
    root: JobRun,
    entry: dict[str, Any],
    latest_ordinal: int | None,
) -> bool:
    """Whether a *pending* recorded generation has genuinely stopped.

    The production 2026-09-14 shape, proven fail-closed against the original
    root and the generation's own ledger entry: the newest recovery generation
    is still ``pending`` only because its single finalize child failed with its
    attempt budget exhausted after its one date_sync and one parent_sync child
    really succeeded.  Every check below refuses instead of allowing: an older
    pending generation is never judged stopped; the row's recovery metadata
    (recovery root, ordinal, request key) and its config identity must match the
    ledger entry and the root; window and data_source must match the root; the
    child set must be exactly one date_sync + one parent_sync + one finalize
    with no unfinished ``JobAttempt`` row and no cancel/pause request; every
    collection child must be a genuine success and the finalize a terminal
    failure with no attempt budget left.  A recovery generation is never
    reopened and never recovers itself — only the original ledger grows.
    """

    if latest_ordinal is None:
        return False
    if not isinstance(entry.get("ordinal"), int):
        return False
    if entry["ordinal"] != latest_ordinal:
        return False
    metadata = candidate.metadata_json or {}
    if metadata.get(RECOVERY_ROOT_KEY) != root.job_id:
        return False
    if metadata.get(RECOVERY_ORDINAL_KEY) != entry["ordinal"]:
        return False
    if metadata.get("recovery_request_key") != entry.get("request_key"):
        return False
    if candidate.config_version != entry.get("config_version"):
        return False
    if not str(candidate.config_version or "").startswith(RECOVERY_CONFIG_PREFIX):
        return False
    if not _same_plan_window(candidate.window_start, root.window_start):
        return False
    if not _same_plan_window(candidate.window_end, root.window_end):
        return False
    if candidate.data_source != root.data_source:
        return False
    if candidate.cancel_requested_at is not None:
        return False
    if candidate.pause_after_stage_requested_at is not None:
        return False
    if _holds_live_lease(candidate.lease_expires_at, reference):
        return False
    children = list(
        session.scalars(
            select(JobRun).where(JobRun.parent_job_id == candidate.job_id)
        )
    )
    date_children = [child for child in children if child.job_kind == "date_sync"]
    parent_children = [
        child for child in children if child.job_kind == "parent_sync"
    ]
    finalizes = [child for child in children if child.job_kind == "finalize"]
    if len(children) != 3:
        return False
    if len(date_children) != 1 or len(parent_children) != 1 or len(finalizes) != 1:
        return False
    unfinished_attempts = (
        session.scalar(
            select(func.count())
            .select_from(JobAttempt)
            .where(
                JobAttempt.job_id.in_(
                    [child.job_id for child in children] + [candidate.job_id]
                ),
                JobAttempt.finished_at.is_(None),
            )
        )
        or 0
    )
    if unfinished_attempts:
        return False
    for child in children:
        if child.cancel_requested_at is not None:
            return False
        if child.pause_after_stage_requested_at is not None:
            return False
        if child.config_version != candidate.config_version:
            return False
        if child.data_source != candidate.data_source:
            return False
        if _holds_live_lease(child.lease_expires_at, reference):
            return False
        if child.job_kind == "finalize":
            if child.status != "failed":
                return False
            if not _attempt_budget_exhausted(child):
                return False
        else:
            if child.status != "success":
                return False
    return True


def _retry_is_due(job: JobRun, reference: datetime) -> bool:
    if job.next_retry_at is None:
        return True
    retry_at = job.next_retry_at
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return retry_at <= reference


def _same_plan_window(left: datetime | None, right: datetime | None) -> bool:
    """Whether two range boundaries are the same window, start *and* end.

    Window boundaries follow the existing ``daily_windows`` normalization, the
    same one ``_validate_child_identity`` and ``_validate_parent_identity`` use:
    a plain ``DateTime(timezone=True)`` column returns an offset-aware value on
    PostgreSQL and a naive value elsewhere, and a naive boundary is the same
    Shanghai wall-clock instant.  Normalizing with ``_as_shanghai`` therefore
    compares true instants on PostgreSQL while keeping one plan's own boundaries
    equal to themselves after a SQLite round trip.

    This is deliberately *not* the lease/attempt policy: those columns carry real
    UTC instants and are compared as UTC elsewhere in the worker, so they are
    handled by their own helpers below.  Deriving a local business date here
    instead would compare too weakly — two distinct plans on one day would pass.
    """

    left_local = _as_shanghai(left) if left is not None else None
    right_local = _as_shanghai(right) if right is not None else None
    return left_local is not None and left_local == right_local


def plan_window_matches(left: datetime | None, right: datetime | None) -> bool:
    """Public form of :func:`_same_plan_window` for API-level identity checks."""

    return _same_plan_window(left, right)


def _spans_exactly_one_shanghai_day(parent: JobRun) -> bool:
    """A recoverable plan is one Shanghai day: local midnight to next midnight."""

    start = _as_shanghai(parent.window_start) if parent.window_start else None
    end = _as_shanghai(parent.window_end) if parent.window_end else None
    if start is None or end is None:
        return False
    if start.time() != time.min or end.time() != time.min:
        return False
    return (end.date() - start.date()) == timedelta(days=1)


def _as_shanghai(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=SHANGHAI_TIMEZONE)
    return value.astimezone(SHANGHAI_TIMEZONE)


__all__ = [
    "BASE_GENERATION_ORDINAL",
    "DIMENSION_CONFIG_PREFIX",
    "MAX_RECOVERY_GENERATIONS",
    "PRIORITY_CONFIG_VERSION",
    "RECOVERABLE_ROOT_STATUSES",
    "RECOVERED_BY_KEY",
    "RECOVERY_CONFIG_PREFIX",
    "RECOVERY_GENERATIONS_KEY",
    "RECOVERY_ORDINAL_KEY",
    "RECOVERY_ROOT_KEY",
    "DayRecoveryNotAllowed",
    "generation_order",
    "generation_ordinal",
    "plan_day_recovery",
    "plan_window_matches",
    "priority_generation_config",
    "recovery_config_version",
    "recovery_generation_by_request_key",
    "recovery_generations",
    "winning_generation",
]