"""DYDATA-102 targeted 2026-09-14 missing-day recovery driver (prepared, not run).

Drives one audited recovery generation through the existing worker control plane
only. Preconditions (controller-enforced): production runs the verified new code
(>= 5effd6e) and depth-64 lineage compaction is controlled. Default read-only;
--apply required before creating any recovery generation.

Design notes (reviewer-facing):

* The allocated recovery parent id is captured once, right after the allocation
  transaction commits, and every later round compares the actual winning
  generation against it.  If anything else wins the day, the driver stops with a
  non-zero exit instead of running children of an unexpected parent.
* Children are only ever selected under the allocated parent id, restricted to
  the exact daily chain shape (one parent_sync + one date_sync + one finalize).
  The selector never widens to other roots, days or targets.
* The deadline is a monotonic budget checked at the top of every round.  The
  resource decision is checked every round, before any child start: a non-ALLOW
  decision never reaches ``run_daily_child``.  Every wait (no candidate, BUSY,
  retry_wait, quota pause, resource block) sleeps at most ROUND_WAIT_SECONDS and
  the total budget stays monotonic.
* The child timeout passed to ``run_daily_child`` is always a legal, finite,
  positive value (validated with the real ``scheduler`` validator) that never
  exceeds the remaining budget; when the remainder is below the floor the loop
  ends instead of raising and then misreporting success.
* Exit codes: 0 only when the final verification proves the allocated parent and
  its whole chain are ``success`` AND September day revisions are published.
  Deadline is 3; every refused/failed/changed-parent outcome is 4; refused
  guards are 2; unexpected errors are 1.  The driver never prints exception
  strings (only the exception type and a coarse, static category).
"""

from __future__ import annotations

import argparse
import hashlib
import math
import sys
import time
from datetime import date

from sqlalchemy import select, text

from apps.api.dy_api.db import get_engine, get_session_factory
from apps.api.dy_api.models import JobRun
from apps.worker.day_recovery import (
    DayRecoveryNotAllowed,
    _as_shanghai,
    _spans_exactly_one_shanghai_day,
    plan_day_recovery,
    winning_generation,
)
from apps.worker.month_close import published_days_revisions
from apps.worker.priority_scheduler import (
    DAILY_JOB_KINDS,
    DAILY_REQUIRED_PURPOSE,
    HISTORY_PURPOSE,
    _priority_rows_for_day,
    _select_candidate,
    _stamp_recovery_generation,
)
from apps.worker.resource_monitor import ResourceAction, current_resource_decision, start_resource_monitor
from apps.worker.scheduler import _validate_daily_child_timeout_seconds, run_daily_child

TARGET_DATE = date(2026, 9, 14)
BUSINESS_MONTH = "2026-09"
MAX_LINEAGE_DEPTH = 48
ROUND_WAIT_SECONDS = 30
MIN_CHILD_TIMEOUT_SECONDS = 1.0
ADVISORY_TICKET = "dsh-dydata102-scoped-recovery-driver-v1"
# The official planner allocates parent_sync + date_sync first and creates
# finalize later through enqueue_finalize_if_ready, so both the in-progress
# two-child shape and the completed three-child shape are lawful.  Anything
# else refuses: a finalize without both collection children, a duplicate, or an
# unknown child kind.
PROGRESS_CHILD_KINDS = frozenset(("parent_sync", "date_sync"))
COMPLETE_CHILD_KINDS = frozenset(DAILY_JOB_KINDS)


def _advisory_key() -> int:
    return int.from_bytes(hashlib.blake2b(ADVISORY_TICKET.encode(), digest_size=8).digest(), "big", signed=True)


def _emit(message: str) -> None:
    print(message)
    sys.stdout.flush()


def _acquire_guard(engine):
    """Dedicated PG session-level advisory guard on its own connection.

    The SELECT that probes the lock would otherwise leave a long open
    transaction on the guard connection: the transaction is committed right
    after the acquire (a session-level advisory lock survives commit), the
    release commits after the unlock, and the connection is always closed.
    """

    if engine is None or engine.dialect.name != "postgresql":
        _emit("guard=unavailable dialect must be postgresql; refusing")
        return None
    conn = engine.connect()
    try:
        acquired = bool(conn.execute(
            text("SELECT pg_try_advisory_lock(:k)"), {"k": _advisory_key()}).scalar())
    except Exception:
        conn.close()
        raise
    if not acquired:
        conn.rollback()
        conn.close()
        _emit("guard=busy another driver instance holds the advisory lock")
        return None
    conn.commit()  # session-level lock persists; no long-held transaction
    return conn


def _release_guard(conn) -> None:
    """Unlock, commit and close; never raises past cleanup."""

    if conn is None:
        return
    try:
        conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _advisory_key()})
        conn.commit()
    except Exception:
        _emit("guard_release_failed connection closed anyway")
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _lineage_ok(session) -> bool:
    row = session.execute(text(
        "SELECT g.state, g.lineage_depth FROM settlement_projection_active a "
        "JOIN settlement_projection_generation g ON g.generation_id = a.generation_id "
        "WHERE a.projection_name = 'settlement'")).first()
    ok = row is not None and row[0] == "published" and int(row[1]) < MAX_LINEAGE_DEPTH
    if not ok:
        _emit(f"lineage_guard=refused state={row[0] if row else None} depth={row[1] if row else None}")
    return ok


def _root_window_ok(window_start, window_end) -> bool:
    """Whether the window is the real half-open Shanghai day 2026-09-14.

    The daily window contract is ``[9/14 00:00, 9/15 00:00)`` Shanghai, so the
    end boundary carries the *next* date; requiring ``end.date() == 9/14`` (the
    old behaviour) rejected every legal plan.  This reuses the existing
    ``day_recovery._spans_exactly_one_shanghai_day`` (midnight-to-midnight, one
    local day, wrong-tz truncation and two-day spans refused) and then checks
    the Shanghai start date.
    """

    if window_start is None or window_end is None:
        return False
    probe = JobRun(window_start=window_start, window_end=window_end)
    if not _spans_exactly_one_shanghai_day(probe):
        return False
    return _as_shanghai(window_start).date() == TARGET_DATE


def _root_ok(session, root_job_id: str):
    root = session.get(JobRun, root_job_id)
    if root is None:
        _emit("root=missing")
        return None
    window_ok = _root_window_ok(root.window_start, root.window_end)
    ok = (root.job_kind == "range_sync" and root.parent_job_id is None
          and (root.metadata_json or {}).get("target") == "all" and window_ok)
    _emit(f"root_check={'ok' if ok else 'refused'} job_kind={root.job_kind} status={root.status}")
    return root if ok else None


def _validated_children(children) -> tuple | None:
    """Exactly parent_sync + date_sync (+ at most one finalize), or ``None``.

    The official planner allocates ``parent_sync`` and ``date_sync`` first and
    creates ``finalize`` later through ``enqueue_finalize_if_ready``, so the
    two-child shape is the lawful in-progress state and the three-child shape is
    the completed chain.  Unknown kinds, duplicates and a missing required child
    all refuse: the caller must inspect every child of the allocated parent, not
    filter unknown kinds away.
    """

    rows = tuple(children)
    kinds = [row.job_kind for row in rows]
    if any(kind not in DAILY_JOB_KINDS for kind in kinds):
        return None
    if len(kinds) != len(set(kinds)):
        return None
    kind_set = set(kinds)
    if kind_set == PROGRESS_CHILD_KINDS or kind_set == COMPLETE_CHILD_KINDS:
        return rows
    return None


def _allocated_children(session, parent_job_id: str):
    """Children of exactly the allocated parent; unknown kinds refuse.

    The selector inspects *every* row whose parent is the allocated recovery
    parent instead of pre-filtering ``job_kind``: a stray unknown child must stop
    the driver, never be silently ignored.
    """

    rows = session.scalars(select(JobRun).where(
        JobRun.parent_job_id == parent_job_id,
    )).all()
    return _validated_children(rows)


def _child_timeout(remaining_seconds) -> float | None:
    """A legal child timeout within the remaining budget, or ``None`` to stop.

    The real ``scheduler`` validator accepts any finite strictly-positive
    number, so any remaining budget above the floor is legal; anything else
    ends the loop instead of raising inside the child call.
    """

    if remaining_seconds is None:
        return None
    try:
        remaining = float(remaining_seconds)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(remaining) or remaining < MIN_CHILD_TIMEOUT_SECONDS:
        return None
    timeout = remaining
    try:
        _validate_daily_child_timeout_seconds(timeout)
    except ValueError:
        return None
    return timeout


def _plan_round(rows, children, *, expected_parent_id: str, select_candidate, session, now):
    """Classify one round without executing anything.

    Returns ``(kind, payload)`` with kind in {"done", "wait", "run", "refused"}.
    """

    winning = winning_generation(rows)
    if winning is None:
        return ("wait", "no_winning_generation")
    if winning.job_id != expected_parent_id:
        # The allocated parent must still own the day: anything else winning
        # means another generation took over, so never run its children.
        return ("refused", ("winning_parent_changed", 4))
    if winning.status == "success":
        return ("done", winning.job_id)
    if winning.status == "failed":
        return ("refused", ("budget_exhausted_parent", 4))
    if children is None:
        return ("refused", ("unexpected_children_shape", 4))
    dead = [c.job_id for c in children
            if c.status == "failed"
            and int(c.attempt_count or 0) >= int(c.max_attempts or 0) + int(c.quota_pause_count or 0)]
    if dead:
        return ("refused", ("budget_exhausted_child", 4))
    candidate = select_candidate(
        children, now=now, allowed_purposes={DAILY_REQUIRED_PURPOSE, HISTORY_PURPOSE}, session=session)
    if candidate is None:
        return ("wait", "no_candidate_gate_or_retry")
    return ("run", candidate.job_id)


def _wait(sleep, clock, deadline) -> bool:
    """Sleep at most ROUND_WAIT_SECONDS within the budget; False if it is over."""

    remaining = deadline - clock()
    if remaining <= 0:
        return False
    sleep(min(ROUND_WAIT_SECONDS, remaining))
    return True


def _drive(factory, *, expected_parent_id: str, deadline,
           clock=time.monotonic, sleep=time.sleep,
           resource_decision=current_resource_decision,
           run_child=None,
           rows_provider=None,
           children_provider=_allocated_children,
           select_candidate=_select_candidate) -> int:
    """Run rounds until the day is done, refused, or the deadline passes.

    The deadline is checked at the top of every round, the resource decision in
    every round (ALLOW is the only action that can reach ``run_child``), and
    every non-executing outcome sleeps within the monotonic budget.
    """

    while True:
        now = clock()
        if now >= deadline:
            _emit("deadline_reached stopping without reset")
            return 3
        decision = resource_decision()
        if decision.action is not ResourceAction.ALLOW:
            _emit(f"resource={decision.action.value} waiting no_child_started")
            if not _wait(sleep, clock, deadline):
                _emit("deadline_reached stopping without reset")
                return 3
            continue
        if rows_provider is None:
            with factory() as session:
                rows = _priority_rows_for_day(session, TARGET_DATE)
                _stamp_recovery_generation(session, rows)  # inherit root quota class
                session.commit()
                children = children_provider(session, expected_parent_id)
                plan = _plan_round(rows, children, expected_parent_id=expected_parent_id,
                                   select_candidate=select_candidate, session=session,
                                   now=datetime_now())
        else:
            rows = rows_provider()
            children = _validated_children(
                row for row in rows
                if row.parent_job_id == expected_parent_id)
            plan = _plan_round(rows, children, expected_parent_id=expected_parent_id,
                               select_candidate=select_candidate, session=None,
                               now=datetime_now())
        kind, payload = plan
        if kind == "refused":
            reason, code = payload
            _emit(f"refused reason={reason} stopping without reset")
            return code
        if kind == "done":
            _emit(f"day_done parent={payload}")
            return 0
        if kind == "wait":
            _emit(f"state=waiting reason={payload}")
            if not _wait(sleep, clock, deadline):
                _emit("deadline_reached stopping without reset")
                return 3
            continue
        candidate_id = payload
        remaining = deadline - clock()
        timeout = _child_timeout(remaining)
        if timeout is None:
            _emit("budget_too_small_for_child stopping without reset")
            return 3
        result = run_child(job_id=candidate_id, timeout_seconds=timeout)
        _emit(f"child_done job_id={result.job_id} status={result.status.value}")
        # BUSY / retry_wait / control_error must not turn into a hot loop.
        if not _wait(sleep, clock, deadline):
            _emit("deadline_reached stopping without reset")
            return 3


def datetime_now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


def _final_outcome(session, expected_parent_id: str) -> tuple[bool, str]:
    """The only shape that may exit 0 (all checks are real control-plane state)."""

    rows = _priority_rows_for_day(session, TARGET_DATE)
    winning = winning_generation(rows)
    if winning is None or winning.job_id != expected_parent_id:
        return False, "final_parent_mismatch"
    parent = session.get(JobRun, expected_parent_id)
    if parent is None or parent.status != "success":
        return False, "final_parent_not_success"
    children = _allocated_children(session, expected_parent_id)
    if children is None:
        return False, "final_children_shape_invalid"
    if any(child.status != "success" for child in children):
        return False, "final_children_not_success"
    finalize = [child for child in children if child.job_kind == "finalize"]
    if len(finalize) != 1 or finalize[0].status != "success":
        return False, "final_finalize_not_success"
    revisions = published_days_revisions(session, BUSINESS_MONTH)
    if revisions is None:
        return False, "september_source_incomplete"
    return True, "success"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root-job-id", required=True)
    ap.add_argument("--request-key", required=True)
    ap.add_argument("--actor", required=True)
    ap.add_argument("--reason", required=True)
    ap.add_argument("--max-wait-seconds", required=True, type=int)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if not 30 <= args.max_wait_seconds <= 7200:
        _emit("arg_error=max_wait_seconds must be within 30..7200")
        return 2
    engine, factory = get_engine(), get_session_factory()
    if factory is None or engine is None:
        _emit("db=unavailable")
        return 2
    guard = _acquire_guard(engine)
    if guard is None:
        return 2
    monitor = None
    try:
        with factory() as session:
            if not _lineage_ok(session):
                return 2
            root = _root_ok(session, args.root_job_id)
            if root is None:
                return 2
            n_children = len(session.scalars(select(JobRun.job_id).where(
                JobRun.parent_job_id == root.job_id, JobRun.job_kind.in_(DAILY_JOB_KINDS))).all())
            _emit(f"root_children={n_children} kinds=parent_sync/date_sync/finalize only")
            if not args.apply:
                _emit("dry_run=true no recovery generation requested; exiting")
                return 0
            try:
                plan, replayed = plan_day_recovery(
                    session, parent=root, request_key=args.request_key,
                    reason=args.reason, actor=args.actor)
                session.commit()  # allocation transaction ends before any execution
            except DayRecoveryNotAllowed as exc:
                _emit(f"recovery_refused type={type(exc).__name__}")
                return 2
            expected_parent_id = plan.parent_job_id
            _emit(f"recovery_parent={expected_parent_id} replayed={replayed}")
        monitor = start_resource_monitor(factory)
        deadline = time.monotonic() + args.max_wait_seconds

        def _run_child(*, job_id: str, timeout_seconds: float):
            return run_daily_child(factory, job_id=job_id, timeout_seconds=timeout_seconds)

        code = _drive(factory, expected_parent_id=expected_parent_id, deadline=deadline,
                      run_child=_run_child)
        if code != 0:
            return code
        with factory() as session:
            ok, reason = _final_outcome(session, expected_parent_id)
            if ok:
                for child in _allocated_children(session, expected_parent_id):
                    _emit(f"child job_id={child.job_id} kind={child.job_kind} status={child.status}")
                _emit(f"final=success parent={expected_parent_id}")
                return 0
            _emit(f"final=not_success reason={reason}")
            return 4
    except Exception as exc:
        # Only the exception type and a static category are printed; exception
        # strings can embed SQL parameters or connection details.
        _emit(f"error type={type(exc).__name__} category=unexpected")
        return 1
    finally:
        if monitor is not None:
            monitor.stop()
        _release_guard(guard)


if __name__ == "__main__":
    sys.exit(main())
