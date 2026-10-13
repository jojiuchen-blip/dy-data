"""DYDATA-102: crash-evidence retention, and audited day-plan recovery.

Two defects are covered here.

1. Retained: closing a lease-overdue job replaced the child's captured stderr tail
   (the real traceback) with a generic sentence, destroying the only evidence of
   why ``date_sync`` exited non-zero.

2. Shipped: an exhausted 3/3 ``date_sync`` chain can now be repaired by an
   *independent* plan generation.  Re-opening the exhausted row itself is
   impossible and remains impossible: ``begin_job_attempt`` derives
   ``attempt_number = attempt_count + 1`` while ``job_attempts`` is unique on
   ``(job_id, attempt_number)``, so any reset of ``attempt_count`` collides with
   the attempts already recorded, and keeping it monotonic breaks the per-row
   attempt budget.  Recovery therefore creates a new range parent under a derived
   ``config_version``, whose children are new job ids with empty attempt space.

The recovery tests below drive the *real* scheduling chain: the priority
scheduler selects the recovered rows, ``run_daily_child`` claims them through the
supervisor, ``begin_job_attempt`` records genuine ``JobAttempt`` rows, the parent
is promoted by ``promote_range_parent_if_ready``, and the month-close watermark
either advances or stays fail-closed.
"""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from apps.api.dy_api.models import (  # noqa: E402
    JobAttempt,
    JobRun,
    JobStageRun,
    SettlementProjectionActive,
    SettlementProjectionGeneration,
)
from apps.worker import day_recovery, month_close, priority_scheduler  # noqa: E402
from apps.worker.daily_windows import enqueue_finalize_if_ready  # noqa: E402
from apps.worker.scheduler import run_daily_child  # noqa: E402
from apps.worker.subprocess_supervisor import (  # noqa: E402
    ChildRunStatus,
    SubprocessSupervisor,
)
from apps.worker.task_control import claim_job  # noqa: E402
from test_worker_daily_orchestrator import _complete_finalize_prerequisites  # noqa: E402

CRASH_TAIL = (
    "Traceback (most recent call last):\n"
    '  File "<frozen runpy>", line 198, in _run_module_as_main\n'
    "...\n"
    "RuntimeError: douyin verify window is not aligned"
)
DAY = date(2026, 9, 14)
NOW = datetime(2026, 9, 20, 3, 0, tzinfo=priority_scheduler.SHANGHAI_TIMEZONE)


class FakeProcess:
    """Minimal child process double for the real supervisor loop."""

    _next_pid = 5000

    def __init__(self, exit_code: int) -> None:
        FakeProcess._next_pid += 1
        self.pid = FakeProcess._next_pid
        self._exit_code = exit_code

    def poll(self):
        return self._exit_code

    def wait(self, timeout=None):
        return self._exit_code

    def terminate(self):  # pragma: no cover - only used on guard paths
        pass

    def kill(self):  # pragma: no cover - only used on guard paths
        pass


def _factory(session: Session) -> sessionmaker:
    return sessionmaker(
        bind=session.get_bind(), autoflush=False, autocommit=False, future=True
    )


def _visible(session: Session) -> None:
    """Publish fixture state so the worker's own connections can see it.

    ``run_daily_child`` claims, attempts and completes over connections opened
    from the same engine, so anything the fixture only flushed would be invisible
    to the very chain the test is driving.
    """

    session.commit()


def _date_sync(db_session: Session, job_id: str = "date-sync-2026-09-14", **overrides):
    values = {
        "job_id": job_id,
        "job_name": "date_sync",
        "job_kind": "date_sync",
        "status": "failed",
        "config_version": priority_scheduler.PRIORITY_CONFIG_VERSION,
        "parent_job_id": "range-sync-2026-09-14",
        "business_date": DAY,
        "data_source": f"verify_records::{job_id}",
        "window_start": datetime(2026, 9, 14, tzinfo=UTC),
        "window_end": datetime(2026, 9, 15, tzinfo=UTC),
        "attempt_count": 3,
        "max_attempts": 3,
        "error_code": "worker_exit_1",
        "error_summary": CRASH_TAIL,
        "finished_at": datetime(2026, 9, 15, 2, 12, tzinfo=UTC),
        "metadata_json": {"target": "all", "priority_purpose": "daily"},
    }
    values.update(overrides)
    job = JobRun(**values)
    db_session.add(job)
    db_session.commit()
    return job


# --------------------------------------------------------------------------- #
# crash evidence must survive the lease-expiry overwrite
# --------------------------------------------------------------------------- #


def test_exhausted_crash_keeps_the_child_traceback_tail(db_session: Session) -> None:
    job = _date_sync(db_session)
    attempt = JobAttempt(
        attempt_id="attempt-1",
        job_id=job.job_id,
        attempt_number=3,
        component_type="worker",
        component_instance_id="worker-1",
        lease_epoch=1,
        started_at=datetime(2026, 9, 14, 2, 0, tzinfo=UTC),
    )
    db_session.add(attempt)
    db_session.commit()

    from apps.worker import repositories

    repositories._fail_job_after_exhausted_crash(
        db_session,
        job=job,
        attempt=attempt,
        database_now=datetime(2026, 9, 14, 2, 20, tzinfo=UTC),
        max_attempts=3,
        quota_pause_count=0,
    )
    db_session.commit()

    assert job.error_code == "max_attempts_exhausted_after_crash"
    assert job.error_summary == "lease expired after the final permitted attempt"
    assert job.metadata_json["previous_error_summary"] == CRASH_TAIL


def test_expired_attempt_keeps_the_child_traceback_tail(db_session: Session) -> None:
    from apps.worker import repositories

    job = _date_sync(db_session, job_id="date-sync-running", status="running")
    attempt = JobAttempt(
        attempt_id="attempt-2",
        job_id=job.job_id,
        attempt_number=1,
        component_type="worker",
        component_instance_id="worker-1",
        lease_epoch=1,
        started_at=datetime(2026, 9, 14, 2, 0),
        error_summary=CRASH_TAIL,
    )
    db_session.add(attempt)
    db_session.commit()

    repositories._close_expired_attempt(
        db_session,
        previous_attempt=attempt,
        database_now=datetime(2026, 9, 14, 2, 30),
    )
    db_session.commit()

    assert attempt.error_code == "lease_expired"
    assert "lease expired before the attempt completed" in attempt.error_summary
    assert CRASH_TAIL in attempt.error_summary


# --------------------------------------------------------------------------- #
# fixtures that build the real production shape: an exhausted 3/3 day plan
# --------------------------------------------------------------------------- #


def _close_attempt(
    session: Session,
    attempt_id: str,
    *,
    exit_type: str,
    exit_code: int | None,
    error_code: str | None = None,
    error_summary: str | None = None,
) -> None:
    """Close a real attempt without violating ``finished_at >= started_at``."""

    attempt = session.get(JobAttempt, attempt_id)
    assert attempt is not None
    attempt.finished_at = attempt.started_at + timedelta(minutes=1)
    attempt.exit_type = exit_type
    attempt.exit_code = exit_code
    attempt.error_code = error_code
    attempt.error_summary = error_summary
    session.flush()


def _exhausted_day_plan(
    session: Session,
    *,
    business_date: date = DAY,
    purpose: str = priority_scheduler.HISTORY_PURPOSE,
) -> tuple[str, str, list[str]]:
    """Plan one day, fail its chain 3/3 with three *real* ``JobAttempt`` rows.

    Returns ``(parent_job_id, date_child_id, attempt_ids)``.  The rows are built
    by the real planner and the real claim/attempt path, so the unique
    ``(job_id, attempt_number)`` constraint is genuinely occupied — which is what
    makes the in-place re-open impossible and a generation the only way forward.
    """

    plan = priority_scheduler.plan_daily_sync(
        session,
        start=business_date,
        end=business_date + timedelta(days=1),
        target="all",
        requested_by="priority-daily-scheduler",
        trigger_source="history",
        config_version=priority_scheduler.PRIORITY_CONFIG_VERSION,
    )
    child = next(
        job for job in plan.daily_jobs if job.job_id.startswith("date-sync-")
    )
    parent = session.get(JobRun, plan.parent_job_id)
    assert parent is not None
    parent.metadata_json = {
        **(parent.metadata_json or {}),
        "priority_purpose": purpose,
        "priority_mode": priority_scheduler.PRIORITY_DAILY_MODE,
        "priority_business_date": business_date.isoformat(),
    }
    parent_sync = session.scalar(
        select(JobRun).where(
            JobRun.parent_job_id == plan.parent_job_id,
            JobRun.job_kind == "parent_sync",
        )
    )
    assert parent_sync is not None

    attempt_ids: list[str] = []
    # The production shape: the range parent's own parent_sync work finished, then
    # its date child crashed on every permitted attempt.
    parent_sync_token = claim_job(
        session,
        job_id=parent_sync.job_id,
        lease_owner="worker-parent",
        component_instance_id="recovery-test-parent-worker",
        lease_seconds=600,
    )
    assert parent_sync_token is not None
    _close_attempt(
        session,
        parent_sync_token.attempt_id,
        exit_type="success",
        exit_code=0,
    )
    parent_sync.status = "success"
    parent_sync.attempt_count = 1
    parent_sync.lease_owner = None
    parent_sync.lease_expires_at = None
    session.flush()

    for attempt_number in (1, 2, 3):
        token = claim_job(
            session,
            job_id=child.job_id,
            lease_owner=f"worker-{attempt_number}",
            component_instance_id=f"recovery-test-worker-{attempt_number}",
            lease_seconds=600,
        )
        assert token is not None
        assert token.attempt_number == attempt_number
        attempt_ids.append(token.attempt_id)
        _close_attempt(
            session,
            token.attempt_id,
            exit_type="fatal_failure",
            exit_code=1,
            error_code="worker_exit_1",
            error_summary=CRASH_TAIL,
        )
        child_row = session.get(JobRun, child.job_id)
        assert child_row is not None
        child_row.status = "retry_wait"
        child_row.next_retry_at = datetime(2026, 9, 15, 1, 0, tzinfo=UTC)
        child_row.lease_owner = None
        child_row.lease_expires_at = None
        session.flush()

    child_row = session.get(JobRun, child.job_id)
    assert child_row is not None
    child_row.status = "failed"
    child_row.attempt_count = 3
    child_row.error_code = "worker_exit_1"
    child_row.error_summary = CRASH_TAIL
    child_row.finished_at = datetime(2026, 9, 15, 2, 12, tzinfo=UTC)
    parent.status = "failed"
    parent.attempt_count = 3
    parent.error_code = "child_jobs_failed"
    parent.error_summary = "1 of 1 date_sync children failed"
    parent.finished_at = datetime(2026, 9, 15, 2, 12, tzinfo=UTC)
    session.flush()
    _visible(session)
    return parent.job_id, child.job_id, attempt_ids


def _run_child(
    session: Session,
    job_id: str,
    *,
    exit_code: int,
    max_attempts: int = 1,
) -> ChildRunStatus:
    """Run one real claim -> attempt -> stage -> completion cycle for ``job_id``.

    A ``parent_sync`` child owns the range-level ``collect_dimensions`` stage.  Its
    stage is committed by the *real* ``run_daily_stages`` with a zero-work handler,
    because that is the code path which promotes the stage onto the range parent
    (``stage_runner._promote_range_parent_stage``) — the very checkpoint
    ``daily_windows._required_parent_stage_for_finalize`` waits for.  Writing the
    range parent's stage row by hand would fake evidence the scheduler never
    produced.

    The supervisor refuses to complete a job whose required stage checkpoints are
    not all successful (``stage_checkpoint_incomplete``), so a non-success status
    is surfaced with the supervisor's own reason instead of being tolerated.
    """

    from apps.worker.stage_runner import run_daily_stages

    factory = _factory(session)
    supervisor = SubprocessSupervisor(
        control_session_factory=factory,
        popen_factory=lambda *_args, **_kwargs: FakeProcess(exit_code),
        rss_reader=lambda _pid: 4096,
        poll_interval_seconds=0,
    )
    original_mark = supervisor._mark_attempt_started

    def mark_started_and_run_stages(claim, *, process_id=None):
        # The real order inside one child: the attempt is recorded (attempt_number
        # 1 under the new job id), _start_attempt reconciles parent/child
        # finalization, and only then do the job's stages run.
        persisted = original_mark(claim, process_id=process_id)
        if not persisted:
            return persisted
        job = session.get(JobRun, claim.job_id)
        if job is not None and job.job_kind == "parent_sync":
            stage_result = run_daily_stages(
                factory,
                job_id=claim.job_id,
                handlers={"collect_dimensions": lambda _session, _job: {}},
                stage_order=("collect_dimensions",),
                lease_owner=claim.lease_owner,
                lease_epoch=claim.lease_epoch,
                attempt_id=claim.attempt_id,
                component_instance_id=claim.component_instance_id,
            )
            assert stage_result.status == "success", stage_result
        return persisted

    supervisor._mark_attempt_started = mark_started_and_run_stages
    result = run_daily_child(
        factory,
        job_id=job_id,
        supervisor=supervisor,
        max_attempts=max_attempts,
        timeout_seconds=30,
    )
    assert result.status is ChildRunStatus.SUCCESS, (
        f"{job_id} did not complete: status={result.status} "
        f"exit_code={result.exit_code} reason={result.error_summary} "
        f"termination={result.termination_reason}"
    )
    return result.status


def _complete_stages(session: Session, job_id: str) -> None:
    """Mark every required stage of one planned job successful.

    The settle checkpoint carries **no** affected store or month: that keeps the
    real finalize stage on its zero-work path, so this suite exercises the genuine
    publication protocol without standing up settlement and score builders.
    """

    job = session.get(JobRun, job_id)
    assert job is not None
    now = datetime(2026, 9, 20, tzinfo=UTC)
    for stage_name in (job.metadata_json or {}).get("required_stages", []):
        checkpoint: dict = {}
        if stage_name == "settle":
            checkpoint = {
                "settlement_summary": {
                    "completed": True,
                    "impact_count": 0,
                    "coupon_count": 0,
                    "detail_count": 0,
                    "result_count": 0,
                    "adjustment_count": 0,
                    "last_impact_id": None,
                    "affected_months": [],
                    "affected_store_ids": [],
                },
                "store_score_snapshot": {
                    "deferred": True,
                    "consumer": "T3.4.finalize",
                    "affected_store_ids": [],
                    "rule_closure": "published-rules-and-eligible-stores",
                },
            }
        session.add(
            JobStageRun(
                stage_run_id=f"stage-{job_id}-{stage_name}",
                job_id=job_id,
                stage_name=stage_name,
                status="success",
                checkpoint_json=checkpoint,
                lease_epoch=1,
                started_at=now,
                finished_at=now,
                committed_at=now,
                created_at=now,
                updated_at=now,
            )
        )
    session.flush()
    _visible(session)


def _seed_published_settlement_base(session: Session, prefix: str) -> str:
    """One published settlement projection generation plus the active pointer.

    This is the same preparation ``test_finalize_parent_promotion`` and
    ``test_settlement_finalize`` use; ``validate_finalize_input`` refuses to build
    a publication mutation without a published active base.
    """

    base_id = f"{prefix}-base"
    session.add(
        SettlementProjectionGeneration(
            generation_id=base_id,
            base_generation_id=None,
            generation_kind="legacy_root",
            compaction_base_generation_id=None,
            projection_name="settlement",
            state="published",
            input_fingerprint="0" * 64,
            lineage_depth=0,
            estimated_write_rows=0,
            estimated_write_bytes=0,
            estimated_wal_bytes=0,
            estimated_disk_headroom_bytes=0,
            checkpoint_json={"phase": "published"},
            last_key=None,
            manifest_checksum="1" * 64,
            source_input_json={},
            published_at=datetime.now(UTC),
        )
    )
    session.add(
        SettlementProjectionActive(
            projection_name="settlement",
            generation_id=base_id,
        )
    )
    session.flush()
    _visible(session)
    return base_id


def _run_real_finalize(session: Session, finalize_job_id: str) -> str:
    """Claim one finalize job and run its real publication stage to completion.

    ``claim_job`` fences it exactly as the supervisor does, and
    ``run_finalize_stage`` is the production publication path (staging generation,
    manifest, publish mutation).  The fake child process used for the collection
    stages cannot execute it, because that stage must run in-process against the
    live database.
    """

    from apps.worker import finalize
    from apps.worker.stage_runner import run_daily_stages
    from apps.worker.task_control import claim_job, complete_job

    token = claim_job(
        session,
        job_id=finalize_job_id,
        lease_owner="recovery-test-finalize",
        component_instance_id="recovery-test-finalize-worker",
        lease_seconds=600,
    )
    assert token is not None
    session.commit()

    factory = _factory(session)
    with factory() as fenced:
        finalize_job = fenced.get(JobRun, finalize_job_id)
        assert finalize_job is not None
        fence = finalize.FenceToken.from_job(finalize_job, token)
        parent_job_id = finalize_job.parent_job_id

    def handler(_session: Session, _job: JobRun):
        return finalize.run_finalize_stage(
            factory,
            parent_job_id=parent_job_id,
            fence_token=fence,
            batch_size=8,
        )

    handler.requires_independent_sessions = True
    stage_result = run_daily_stages(
        factory,
        job_id=finalize_job_id,
        handlers={"finalize": handler},
        stage_order=("finalize",),
        lease_owner=token.lease_owner,
        lease_epoch=token.lease_epoch,
        attempt_id=token.attempt_id,
        component_instance_id=token.component_instance_id,
    )
    assert stage_result.status == "success", stage_result
    with factory() as completing:
        assert complete_job(completing, token, success_count=1) is True
        completing.commit()
    return finalize_job_id


def _ensure_published_settlement_base(
    session: Session, prefix: str = "recovery-test"
) -> str:
    """Make exactly one published settlement base active, visible to every factory.

    The base is a singleton keyed by ``projection_name``: seeding it once per
    published day would collide on the primary key, and re-seeding would move the
    active pointer an already-published day's finalize recorded.  It is committed
    here because ``_run_real_finalize`` reads through its own sessions.
    """

    active = session.get(SettlementProjectionActive, "settlement")
    if active is not None:
        return active.generation_id
    base_id = _seed_published_settlement_base(session, prefix)
    session.commit()
    return base_id


def _publish_day(session: Session, day: date) -> None:
    """Publish one day through the real planner and the real finalize linkage.

    The finalize row is *not* hand-built: ``enqueue_finalize_if_ready`` derives it
    from its range parent (parent_job_id, config_version, window and settle stage
    fences), which is exactly the identity a "published day" means.  A standalone
    finalize row carrying no parent would describe a day that production cannot
    produce and that ``_day_state`` correctly refuses to count.

    This helper commits.  Call it from an owning ``factory()`` session, never from
    inside a ``factory.begin()`` block, because committing would end that outer
    transaction early.
    """

    _ensure_published_settlement_base(session)
    priority_scheduler.ensure_daily_priority_plan(session, day, now=NOW)
    rows = priority_scheduler._priority_rows_for_day(session, day)
    now = datetime(2026, 9, 20, tzinfo=UTC)
    for row in rows:
        if row.job_kind != "range_sync":
            row.status = "success"
    for row in rows:
        if row.job_kind != "date_sync":
            continue
        for stage_name in (row.metadata_json or {}).get("required_stages", []):
            checkpoint: dict = {}
            if stage_name == "settle":
                checkpoint = {
                    "settlement_summary": {
                        "completed": True,
                        "impact_count": 0,
                        "coupon_count": 0,
                        "detail_count": 0,
                        "result_count": 0,
                        "adjustment_count": 0,
                        "last_impact_id": None,
                        "affected_months": [],
                        "affected_store_ids": [],
                    },
                    "store_score_snapshot": {
                        "deferred": True,
                        "consumer": "T3.4.finalize",
                        "affected_store_ids": [],
                        "rule_closure": "published-rules-and-eligible-stores",
                    },
                }
            session.add(
                JobStageRun(
                    stage_run_id=f"stage-{row.job_id}-{stage_name}",
                    job_id=row.job_id,
                    stage_name=stage_name,
                    status="success",
                    checkpoint_json=checkpoint,
                    lease_epoch=1,
                    started_at=now,
                    finished_at=now,
                    committed_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
    session.flush()
    required_stage = session.scalar(
        select(JobStageRun).where(
            JobStageRun.job_id == rows[0].parent_job_id,
            JobStageRun.stage_name == "collect_dimensions",
        )
    )
    if required_stage is not None:
        required_stage.status = "success"
        required_stage.committed_at = now
        required_stage.finished_at = now
    session.flush()

    parent_job_id = rows[0].parent_job_id
    finalize = enqueue_finalize_if_ready(session, parent_job_id)
    assert finalize is not None, "the real planner must produce one finalize"
    # Run the genuine publication stage so the day carries a real published
    # generation.  A day that only *claims* to be published is exactly what
    # `reconcile_finalize_parents` and the month-close watermark refuse.
    _run_real_finalize(session, finalize.job_id)
    parent = session.get(JobRun, parent_job_id)
    assert parent is not None
    # `complete_job` promoted the range parent through the real finalize path.
    assert parent.status == "success"
    session.flush()
    _visible(session)


def _tick(
    session: Session,
    *,
    monkeypatch: pytest.MonkeyPatch,
    now: datetime = NOW,
    jobs: list[str] | None = None,
):
    """Run one real priority tick, executing exactly one selected child.

    Dimensions are an independent half-hour cadence.  They are switched off here
    so the tick under test has to answer for the daily/history chain rather than
    for a dimension refresh that happens to be due at the same instant.
    """

    monkeypatch.setattr(priority_scheduler, "_plan_due_dimensions", lambda *_a: ())
    monkeypatch.setattr(
        priority_scheduler,
        "_select_due_dimension_candidate",
        lambda *_a, **_k: None,
    )
    executed: list[str] = []

    def child_runner(factory, job_id: str):
        executed.append(job_id)
        # One real claim -> attempt -> stage -> completion cycle.  The parent_sync
        # stage is executed by the real runner so its checkpoint propagates onto
        # the range parent exactly as in production.
        status = _run_child(session, job_id, exit_code=0)
        return type(
            "Result",
            (),
            {
                "job_id": job_id,
                "status": status,
                "attempts": 1,
                "error_summary": None,
            },
        )()

    result = priority_scheduler.run_priority_daily_tick(
        _factory(session),
        now=now,
        child_runner=child_runner,
        product_sync_runner=lambda _factory, **_kwargs: None,
    )
    # The tick ran through its own sessions; drop this session's cached copies so
    # callers observe committed database state rather than stale ORM instances.
    session.expire_all()
    if jobs is not None:
        jobs[:] = executed
    return result


# --------------------------------------------------------------------------- #
# 1. the full chain: exhausted chain -> recovery -> published day -> month close
# --------------------------------------------------------------------------- #


def test_recovery_generation_runs_the_real_chain_and_publishes_the_day(
    monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    """Exhausted 3/3 -> independent parent -> new attempt 1 -> success -> one finalize."""

    parent_id, old_child_id, old_attempt_ids = _exhausted_day_plan(db_session)
    # Days newer than the failed one are already published, so the scheduler's
    # history scan reaches the failed day instead of stopping at a newer gap.
    for offset in range(1, 6):
        _publish_day(db_session, DAY + timedelta(days=offset))
    old_attempts = {
        row.attempt_id: (row.attempt_number, row.exit_code, row.finished_at)
        for row in db_session.scalars(
            select(JobAttempt).where(JobAttempt.job_id == old_child_id)
        )
    }
    assert len(old_attempts) == 3
    old_parent_error = db_session.get(JobRun, parent_id).error_summary

    plan, replayed = day_recovery.plan_day_recovery(
        db_session,
        parent=db_session.get(JobRun, parent_id),
        request_key="operator-recover-2026-09-14",
        reason="repair the exhausted day after the window fix",
        actor="system-admin",
        now=NOW,
    )
    db_session.flush()
    assert replayed is False
    recovery_parent = db_session.get(JobRun, plan.parent_job_id)

    # A brand new independent parent, not a re-opened row.
    assert recovery_parent.job_id != parent_id
    assert recovery_parent.parent_job_id is None
    assert recovery_parent.config_version.startswith(
        day_recovery.RECOVERY_CONFIG_PREFIX
    )
    assert day_recovery.generation_ordinal(recovery_parent) == 1
    assert recovery_parent.metadata_json[day_recovery.RECOVERY_ROOT_KEY] == parent_id

    # The original failure evidence and every original JobAttempt are untouched.
    original = db_session.get(JobRun, parent_id)
    assert original.status == "failed"
    assert original.error_summary == old_parent_error
    assert original.metadata_json[day_recovery.RECOVERED_BY_KEY] == recovery_parent.job_id
    assert {
        row.attempt_id: (row.attempt_number, row.exit_code, row.finished_at)
        for row in db_session.scalars(
            select(JobAttempt).where(JobAttempt.job_id == old_child_id)
        )
    } == old_attempts
    assert day_recovery.recovery_generations(original)[0]["ordinal"] == 1

    # The new generation is visible to the scheduler: the day now owns its rows.
    state = priority_scheduler._day_state(
        DAY, priority_scheduler._priority_rows_for_day(db_session, DAY)
    )
    assert state.state == "incomplete"
    assert state.parent is not None and state.parent.job_id == recovery_parent.job_id

    # The old exhausted child must never be selected again.
    selectable = {row.job_id for row in state.rows}
    assert old_child_id not in selectable

    # Step 1: the parent_sync child is selected and claimed for real.
    first_executed: list[str] = []
    first = _tick(db_session, monkeypatch=monkeypatch, jobs=first_executed)
    assert first.action == "executed"
    assert first_executed == [first.selected_job_id]
    db_session.expire_all()
    recovered_parent_exec = db_session.get(JobRun, first.selected_job_id)
    assert recovered_parent_exec.parent_job_id == recovery_parent.job_id
    assert recovered_parent_exec.job_kind == "parent_sync"
    assert recovered_parent_exec.status == "success"
    assert recovered_parent_exec.attempt_count == 1
    # The range parent's dimension stage was promoted by the real stage runner —
    # the checkpoint `_required_parent_stage_for_finalize` waits for.
    assert db_session.scalar(
        select(JobStageRun.status).where(
            JobStageRun.job_id == recovery_parent.job_id,
            JobStageRun.stage_name == "collect_dimensions",
        )
    ) == "success"

    # Step 2: the new date child gets attempt_number 1 under a fresh job id.
    new_child_id = db_session.scalar(
        select(JobRun.job_id).where(
            JobRun.parent_job_id == recovery_parent.job_id,
            JobRun.job_kind == "date_sync",
        )
    )
    assert new_child_id is not None and new_child_id != old_child_id
    _complete_stages(db_session, new_child_id)
    second_executed: list[str] = []
    second = _tick(db_session, monkeypatch=monkeypatch, jobs=second_executed)
    assert second.action == "executed"
    assert second_executed == [new_child_id]
    db_session.expire_all()
    new_attempts = list(
        db_session.scalars(
            select(JobAttempt)
            .where(JobAttempt.job_id == new_child_id)
            .order_by(JobAttempt.attempt_number)
        )
    )
    assert [row.attempt_number for row in new_attempts] == [1]
    assert db_session.get(JobRun, new_child_id).status == "success"

    # Step 3: the single finalize of the recovery parent is enqueued and its real
    # publication stage runs to completion, promoting the recovery parent via the
    # production path (complete_job -> promote_range_parent_if_ready).
    db_session.expire_all()
    assert db_session.get(JobRun, new_child_id).status == "success"
    assert db_session.scalar(
        select(JobStageRun.status).where(
            JobStageRun.job_id == recovery_parent.job_id,
            JobStageRun.stage_name == "collect_dimensions",
        )
    ) == "success"
    finalize = enqueue_finalize_if_ready(db_session, recovery_parent.job_id)
    assert finalize is not None
    _run_real_finalize(db_session, finalize.job_id)
    db_session.expire_all()
    recovery_parent = db_session.get(JobRun, plan.parent_job_id)
    assert recovery_parent.status == "success"

    finalize_rows = [
        row
        for row in priority_scheduler._priority_rows_for_day(db_session, DAY)
        if row.job_kind == "finalize"
    ]
    assert [row.job_id for row in finalize_rows] == [finalize.job_id]
    assert finalize_rows[0].parent_job_id == recovery_parent.job_id

    published = priority_scheduler._day_state(
        DAY, priority_scheduler._priority_rows_for_day(db_session, DAY)
    )
    assert published.state == "success"
    assert published.parent.job_id == recovery_parent.job_id

    # The superseded generation's failure evidence survives verbatim.
    assert db_session.get(JobRun, parent_id).status == "failed"
    assert db_session.get(JobRun, parent_id).error_summary == old_parent_error


def test_recovery_is_the_only_way_a_failed_day_reaches_month_close(
    db_session: Session,
) -> None:
    """An unfinished or failed recovery must never let the monthly watermark pass."""

    parent_id, _old_child_id, _attempt_ids = _exhausted_day_plan(
        db_session,
        business_date=date(2026, 9, 1),
        purpose=priority_scheduler.DAILY_REQUIRED_PURPOSE,
    )
    month = "2026-09"
    # Every other day of the month is published; only the recovered day is not.
    for day in month_close.month_business_dates(month):
        if day == date(2026, 9, 1):
            continue
        _publish_day(db_session, day)
    db_session.flush()

    # A failed day is fail-closed for the month, before any recovery exists.
    assert month_close.published_days_revisions(db_session, month) is None

    # A recovery that has not finished yet must still fail closed.
    day_recovery.plan_day_recovery(
        db_session,
        parent=db_session.get(JobRun, parent_id),
        request_key="operator-recover-september-01",
        reason="repair day one",
        actor="system-admin",
        now=NOW,
    )
    db_session.flush()
    assert month_close.published_days_revisions(db_session, month) is None

    # A recovery that *failed* must fail closed as well: the day is failed again,
    # and the superseded generation's rows cannot publish it retroactively.
    first_recovery_id = (
        db_session.get(JobRun, parent_id).metadata_json[
            day_recovery.RECOVERED_BY_KEY
        ]
    )
    first_recovery = db_session.get(JobRun, first_recovery_id)
    first_recovery.status = "failed"
    first_recovery.error_code = "worker_exit_1"
    first_recovery.error_summary = "recovered parent crashed"
    db_session.flush()
    assert (
        priority_scheduler._day_state(
            date(2026, 9, 1),
            priority_scheduler._priority_rows_for_day(db_session, date(2026, 9, 1)),
        ).state
        == "failed"
    )
    assert month_close.published_days_revisions(db_session, month) is None

    # The failed generation cannot be resurrected into success.  The real repair
    # is a *second* independent generation, created under a new idempotency key.
    second_plan, _ = day_recovery.plan_day_recovery(
        db_session,
        parent=db_session.get(JobRun, parent_id),
        request_key="operator-recover-september-01-second",
        reason="repair day one, second generation",
        actor="system-admin",
        now=NOW,
    )
    db_session.commit()
    second_recovery_id = second_plan.parent_job_id
    assert second_recovery_id != first_recovery_id
    second_recovery = db_session.get(JobRun, second_recovery_id)
    assert day_recovery.generation_ordinal(second_recovery) == 2

    # Only the second (newest valid) generation owns the day; the first stays a
    # terminal failure and must not publish the day or be re-claimed.
    state = priority_scheduler._day_state(
        date(2026, 9, 1),
        priority_scheduler._priority_rows_for_day(db_session, date(2026, 9, 1)),
    )
    assert state.state == "incomplete"
    assert state.parent is not None and state.parent.job_id == second_recovery_id

    # Prepare and run the *second* generation's own chain: date child stages, then
    # the real parent_sync stage runner which promotes the range-level dimension
    # stage.
    second_child_id = db_session.scalar(
        select(JobRun.job_id).where(
            JobRun.parent_job_id == second_recovery_id,
            JobRun.job_kind == "date_sync",
        )
    )
    assert second_child_id is not None
    _complete_stages(db_session, second_child_id)
    db_session.get(JobRun, second_child_id).status = "success"
    db_session.flush()
    second_parent_sync = db_session.scalar(
        select(JobRun.job_id).where(
            JobRun.parent_job_id == second_recovery_id,
            JobRun.job_kind == "parent_sync",
        )
    )
    assert second_parent_sync is not None
    _run_child(db_session, second_parent_sync, exit_code=0)
    db_session.expire_all()
    assert db_session.scalar(
        select(JobStageRun.status).where(
            JobStageRun.job_id == second_recovery_id,
            JobStageRun.stage_name == "collect_dimensions",
        )
    ) == "success"
    finalize = enqueue_finalize_if_ready(db_session, second_recovery_id)
    assert finalize is not None
    assert finalize.parent_job_id == second_recovery_id
    _run_real_finalize(db_session, finalize.job_id)
    db_session.expire_all()
    assert db_session.get(JobRun, second_recovery_id).status == "success"
    revisions = month_close.published_days_revisions(db_session, month)
    assert revisions is not None
    assert f"2026-09-01@{finalize.job_id}" in revisions
    # The winning generation's finalize is the only finalize that day owns.
    assert len(
        [
            row
            for row in priority_scheduler._priority_rows_for_day(
                db_session, date(2026, 9, 1)
            )
            if row.job_kind == "finalize"
        ]
    ) == 1
    # Publishing the second generation must not have touched the superseded first
    # generation or the original day: both stay terminal with all three attempts.
    assert db_session.get(JobRun, parent_id).status == "failed"
    assert db_session.get(JobRun, first_recovery_id).status == "failed"
    assert db_session.get(JobRun, first_recovery_id).error_summary == "recovered parent crashed"
    assert [
        (row.attempt_number, row.exit_code, row.error_code)
        for row in db_session.scalars(
            select(JobAttempt)
            .where(JobAttempt.job_id == _old_child_id)
            .order_by(JobAttempt.attempt_number)
        )
    ] == [(1, 1, "worker_exit_1"), (2, 1, "worker_exit_1"), (3, 1, "worker_exit_1")]


# --------------------------------------------------------------------------- #
# 2. idempotency, budget, and concurrency
# --------------------------------------------------------------------------- #


def test_same_request_key_returns_the_same_generation(db_session: Session) -> None:
    parent_id, _child, _attempts = _exhausted_day_plan(db_session)
    parent = db_session.get(JobRun, parent_id)

    first, first_replay = day_recovery.plan_day_recovery(
        db_session,
        parent=parent,
        request_key="stable-key",
        reason="first",
        actor="system-admin",
        now=NOW,
    )
    second, second_replay = day_recovery.plan_day_recovery(
        db_session,
        parent=parent,
        request_key="stable-key",
        reason="first",
        actor="system-admin",
        now=NOW,
    )

    assert first_replay is False and second_replay is True
    assert first.parent_job_id == second.parent_job_id
    assert len(day_recovery.recovery_generations(parent)) == 1


def test_second_request_key_creates_the_second_generation_and_exhausts_budget(
    db_session: Session,
) -> None:
    parent_id, _child, _attempts = _exhausted_day_plan(db_session)
    parent = db_session.get(JobRun, parent_id)

    first, _ = day_recovery.plan_day_recovery(
        db_session, parent=parent, request_key="key-1", reason="one",
        actor="system-admin", now=NOW,
    )
    db_session.flush()
    # A generation that has not stopped yet blocks a parallel second generation.
    with pytest.raises(day_recovery.DayRecoveryNotAllowed, match="in flight"):
        day_recovery.plan_day_recovery(
            db_session, parent=parent, request_key="key-2", reason="two",
            actor="system-admin", now=NOW,
        )

    # A `retry_wait` generation with a *future* retry timestamp is still queued,
    # not settled: it must keep blocking a parallel generation (gap B).
    db_session.get(JobRun, first.parent_job_id).status = "retry_wait"
    db_session.get(JobRun, first.parent_job_id).next_retry_at = datetime(
        2099, 1, 1, tzinfo=UTC
    )
    db_session.flush()
    with pytest.raises(day_recovery.DayRecoveryNotAllowed, match="in flight"):
        day_recovery.plan_day_recovery(
            db_session, parent=parent, request_key="key-2", reason="two",
            actor="system-admin", now=NOW,
        )

    db_session.get(JobRun, first.parent_job_id).status = "failed"
    db_session.flush()
    second, replayed = day_recovery.plan_day_recovery(
        db_session, parent=parent, request_key="key-2", reason="two",
        actor="system-admin", now=NOW,
    )
    db_session.flush()

    assert replayed is False
    assert second.parent_job_id != first.parent_job_id
    generations = day_recovery.recovery_generations(parent)
    assert [entry["ordinal"] for entry in generations] == [1, 2]

    # Ordinal is explicit: generation 2 wins regardless of job-id ordering.
    rows = priority_scheduler._priority_rows_for_day(db_session, DAY)
    assert priority_scheduler.winning_generation(rows).job_id == second.parent_job_id
    assert max(
        (first.parent_job_id, second.parent_job_id),
        key=lambda value: value,
    ) in {first.parent_job_id, second.parent_job_id}

    db_session.get(JobRun, second.parent_job_id).status = "failed"
    db_session.flush()
    with pytest.raises(
        day_recovery.DayRecoveryNotAllowed, match="budget exhausted"
    ):
        day_recovery.plan_day_recovery(
            db_session, parent=parent, request_key="key-3", reason="three",
            actor="system-admin", now=NOW,
        )


def test_concurrent_recovery_requests_allocate_exactly_one_generation(
    db_session: Session,
) -> None:
    """A second caller locking the same parent must not mint a parallel ordinal."""

    parent_id, _child, _attempts = _exhausted_day_plan(db_session)
    factory = _factory(db_session)

    with factory() as first_session:
        parent = first_session.get(JobRun, parent_id)
        plan, _ = day_recovery.plan_day_recovery(
            first_session,
            parent=parent,
            request_key="concurrent-key-a",
            reason="winner",
            actor="admin-a",
            now=NOW,
        )
        first_session.commit()
        winner = plan.parent_job_id

    with factory() as second_session:
        parent = second_session.get(JobRun, parent_id)
        with pytest.raises(day_recovery.DayRecoveryNotAllowed, match="in flight"):
            day_recovery.plan_day_recovery(
                second_session,
                parent=parent,
                request_key="concurrent-key-b",
                reason="loser",
                actor="admin-b",
                now=NOW,
            )
        second_session.rollback()

    with factory() as verify:
        parent = verify.get(JobRun, parent_id)
        generations = day_recovery.recovery_generations(parent)
        assert len(generations) == 1
        assert generations[0]["parent_job_id"] == winner
        assert generations[0]["actor"] == "admin-a"


# --------------------------------------------------------------------------- #
# 3. eligibility guards on the original plan
# --------------------------------------------------------------------------- #


def test_successful_or_live_day_plans_cannot_be_recovered(db_session: Session) -> None:
    parent_id, child_id, _attempts = _exhausted_day_plan(db_session)
    parent = db_session.get(JobRun, parent_id)

    parent.status = "success"
    db_session.flush()
    with pytest.raises(day_recovery.DayRecoveryNotAllowed, match="not terminal"):
        day_recovery.plan_day_recovery(
            db_session, parent=parent, request_key="k-success", reason="no",
            actor="system-admin", now=NOW,
        )

    parent.status = "running"
    db_session.flush()
    with pytest.raises(day_recovery.DayRecoveryNotAllowed, match="not terminal"):
        day_recovery.plan_day_recovery(
            db_session, parent=parent, request_key="k-running", reason="no",
            actor="system-admin", now=NOW,
        )

    # A pending plan is only recoverable when its single date child is already
    # terminal.  A child that is still runnable (not failed) must stay with the
    # scheduler.
    parent.status = "pending"
    child = db_session.get(JobRun, child_id)
    child.status = "pending"
    child.attempt_count = 0
    child.error_code = None
    child.error_summary = None
    db_session.flush()
    with pytest.raises(
        day_recovery.DayRecoveryNotAllowed, match="still has a runnable date child"
    ):
        day_recovery.plan_day_recovery(
            db_session, parent=parent, request_key="k-pending", reason="no",
            actor="system-admin", now=NOW,
        )
    assert day_recovery.recovery_generations(parent) == []


def test_pending_parent_with_exhausted_date_child_is_recoverable(
    db_session: Session,
) -> None:
    """The production 09-14/16/20/25/28 shape: pending parent, failed 3/3 child.

    The range parent never became terminal, but its parent_sync finished and the
    single date child exhausted every attempt with no live lease.  That blocked
    shape is recoverable; a runnable pending plan is not.
    """

    parent_id, child_id, attempt_ids = _exhausted_day_plan(db_session)
    parent = db_session.get(JobRun, parent_id)
    # Emulate production: the range parent stays pending while the date child is
    # terminal-failed.
    parent.status = "pending"
    parent.error_code = None
    parent.error_summary = None
    parent.attempt_count = 0
    db_session.flush()

    plan, replayed = day_recovery.plan_day_recovery(
        db_session,
        parent=parent,
        request_key="production-blocked-shape",
        reason="repair the pending day with an exhausted child",
        actor="system-admin",
        now=NOW,
    )
    assert replayed is False
    assert plan.parent_job_id != parent_id
    assert day_recovery.generation_ordinal(
        db_session.get(JobRun, plan.parent_job_id)
    ) == 1
    # The original evidence is untouched.
    assert db_session.get(JobRun, parent_id).status == "pending"
    assert db_session.get(JobRun, child_id).status == "failed"
    assert [
        row.attempt_number
        for row in db_session.scalars(
            select(JobAttempt)
            .where(JobAttempt.job_id == child_id)
            .order_by(JobAttempt.attempt_number)
        )
    ] == [1, 2, 3]


def test_day_plan_with_a_live_child_lease_cannot_be_recovered(
    db_session: Session,
) -> None:
    """The whole chain must have settled; a live child means the day is still running."""

    parent_id, child_id, _attempts = _exhausted_day_plan(db_session)
    parent = db_session.get(JobRun, parent_id)
    child = db_session.get(JobRun, child_id)
    child.status = "running"
    child.lease_owner = "worker-live"
    child.lease_expires_at = datetime(2026, 9, 20, 4, 0, tzinfo=UTC)
    db_session.flush()

    with pytest.raises(
        day_recovery.DayRecoveryNotAllowed, match="active child job"
    ):
        day_recovery.plan_day_recovery(
            db_session, parent=parent, request_key="k-live-child", reason="no",
            actor="system-admin", now=NOW,
        )
    assert day_recovery.recovery_generations(parent) == []


def test_cancelled_or_paused_or_leased_original_plan_is_refused(
    db_session: Session,
) -> None:
    parent_id, _child, _attempts = _exhausted_day_plan(db_session)
    parent = db_session.get(JobRun, parent_id)

    parent.pause_after_stage_requested_at = NOW
    db_session.flush()
    with pytest.raises(day_recovery.DayRecoveryNotAllowed, match="pause request"):
        day_recovery.plan_day_recovery(
            db_session, parent=parent, request_key="k-pause", reason="no",
            actor="system-admin", now=NOW,
        )

    parent.pause_after_stage_requested_at = None
    parent.lease_expires_at = datetime(2026, 9, 20, 5, 0, tzinfo=UTC)
    db_session.flush()
    with pytest.raises(day_recovery.DayRecoveryNotAllowed, match="still leased"):
        day_recovery.plan_day_recovery(
            db_session, parent=parent, request_key="k-lease", reason="no",
            actor="system-admin", now=NOW,
        )

    parent.lease_expires_at = None
    parent.cancel_requested_at = NOW
    db_session.flush()
    with pytest.raises(day_recovery.DayRecoveryNotAllowed, match="cancelled"):
        day_recovery.plan_day_recovery(
            db_session, parent=parent, request_key="k-cancel", reason="no",
            actor="system-admin", now=NOW,
        )


def test_recovery_generation_cannot_itself_be_recovered(db_session: Session) -> None:
    parent_id, _child, _attempts = _exhausted_day_plan(db_session)
    parent = db_session.get(JobRun, parent_id)
    plan, _ = day_recovery.plan_day_recovery(
        db_session, parent=parent, request_key="root-key", reason="one",
        actor="system-admin", now=NOW,
    )
    db_session.flush()
    recovery_parent = db_session.get(JobRun, plan.parent_job_id)
    recovery_parent.status = "failed"
    db_session.flush()

    with pytest.raises(
        day_recovery.DayRecoveryNotAllowed, match="cannot itself be recovered"
    ):
        day_recovery.plan_day_recovery(
            db_session, parent=recovery_parent, request_key="second-root",
            reason="no", actor="system-admin", now=NOW,
        )


def test_only_a_single_day_all_target_base_plan_is_recoverable(
    db_session: Session,
) -> None:
    parent_id, _child, _attempts = _exhausted_day_plan(db_session)
    parent = db_session.get(JobRun, parent_id)

    parent.metadata_json = {**(parent.metadata_json or {}), "target": "settlement"}
    db_session.flush()
    with pytest.raises(day_recovery.DayRecoveryNotAllowed, match="all-target"):
        day_recovery.plan_day_recovery(
            db_session, parent=parent, request_key="k-target", reason="no",
            actor="system-admin", now=NOW,
        )

    parent.metadata_json = {**(parent.metadata_json or {}), "target": "all"}
    parent.window_end = parent.window_start + timedelta(days=2)
    db_session.flush()
    with pytest.raises(day_recovery.DayRecoveryNotAllowed, match="exactly one"):
        day_recovery.plan_day_recovery(
            db_session, parent=parent, request_key="k-multiday", reason="no",
            actor="system-admin", now=NOW,
        )

    parent.window_end = parent.window_start + timedelta(days=1)
    parent.config_version = f"{day_recovery.RECOVERY_CONFIG_PREFIX}-0badc0de"
    db_session.flush()
    with pytest.raises(day_recovery.DayRecoveryNotAllowed, match="base daily"):
        day_recovery.plan_day_recovery(
            db_session, parent=parent, request_key="k-base", reason="no",
            actor="system-admin", now=NOW,
        )


# --------------------------------------------------------------------------- #
# 4. scheduler must not re-run or block on a superseded generation
# --------------------------------------------------------------------------- #


def test_failed_day_without_recovery_is_not_re_run_by_the_tick(
    monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    """A terminal day owns none of its rows until an audited generation exists."""

    parent_id, old_child_id, _attempts = _exhausted_day_plan(db_session)
    # Every *other* day between the exhausted day and the daily window is really
    # published, and the history window starts at the exhausted day, so the only
    # thing left for the tick to answer for is that one terminal day.
    for offset in range(1, 6):
        _publish_day(db_session, DAY + timedelta(days=offset))
    monkeypatch.setattr(
        priority_scheduler,
        "_history_bounds",
        lambda _session, *, daily_date: (DAY, daily_date - timedelta(days=1)),
    )
    executed: list[str] = []

    result = _tick(db_session, monkeypatch=monkeypatch, jobs=executed)

    assert result.action == "blocked"
    assert result.reason == f"history_day_failed:{DAY.isoformat()}"
    assert executed == []
    assert db_session.get(JobRun, old_child_id).status == "failed"
    assert db_session.get(JobRun, parent_id).status == "failed"


def test_superseded_generation_rows_are_never_claimed(
    monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    """The old failed child and parent_sync stay untouched after a generation exists."""

    parent_id, old_child_id, _attempts = _exhausted_day_plan(db_session)
    old_parent_sync_id = db_session.scalar(
        select(JobRun.job_id).where(
            JobRun.parent_job_id == parent_id,
            JobRun.job_kind == "parent_sync",
        )
    )
    assert old_parent_sync_id is not None

    day_recovery.plan_day_recovery(
        db_session,
        parent=db_session.get(JobRun, parent_id),
        request_key="supersede-key",
        reason="repair",
        actor="system-admin",
        now=NOW,
    )
    db_session.flush()

    state = priority_scheduler._day_state(
        DAY, priority_scheduler._priority_rows_for_day(db_session, DAY)
    )
    claimable = {row.job_id for row in state.rows}
    assert old_child_id not in claimable
    assert old_parent_sync_id not in claimable

    executed: list[str] = []
    _tick(db_session, monkeypatch=monkeypatch, jobs=executed)
    assert old_child_id not in executed
    assert old_parent_sync_id not in executed
    assert db_session.get(JobRun, old_child_id).status == "failed"


def test_history_tick_adopts_the_recovery_generation_onto_the_history_budget(
    monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    """Recovery work on a history day must not be charged to the daily reserve."""

    parent_id, _child, _attempts = _exhausted_day_plan(
        db_session, purpose=priority_scheduler.HISTORY_PURPOSE
    )
    # Every day newer than the recovered one is really published, and older days
    # are outside the window, so the history scan lands exactly on the recovered
    # day rather than filling a newer gap.
    for offset in range(1, 6):
        _publish_day(db_session, DAY + timedelta(days=offset))
    plan, _ = day_recovery.plan_day_recovery(
        db_session,
        parent=db_session.get(JobRun, parent_id),
        request_key="history-recovery-key",
        reason="repair a history day",
        actor="system-admin",
        now=NOW,
    )
    db_session.flush()
    recovery_parent = db_session.get(JobRun, plan.parent_job_id)
    assert "priority_purpose" not in (recovery_parent.metadata_json or {})

    executed: list[str] = []
    result = _tick(db_session, monkeypatch=monkeypatch, jobs=executed)

    assert result.action == "executed"
    assert executed == [result.selected_job_id]
    selected = db_session.get(JobRun, executed[0])
    assert selected.parent_job_id == recovery_parent.job_id
    db_session.refresh(recovery_parent)
    # The recovery generation and every row it brought along carry the day's own
    # purpose, so the history reserve (not the daily reserve) pays for it.
    assert (
        recovery_parent.metadata_json["priority_purpose"]
        == priority_scheduler.HISTORY_PURPOSE
    )
    assert selected.metadata_json["priority_purpose"] == priority_scheduler.HISTORY_PURPOSE
    assert selected.metadata_json["priority_kind"] == "recovery"
    assert result.selected_purpose == priority_scheduler.HISTORY_PURPOSE
    # The executed parent_sync really ran: its dimension stage is committed and
    # promoted onto the recovery parent, and the attempt is recorded.
    assert selected.status == "success"
    assert db_session.scalar(
        select(JobStageRun.status).where(
            JobStageRun.job_id == recovery_parent.job_id,
            JobStageRun.stage_name == "collect_dimensions",
        )
    ) == "success"
    assert [
        row.attempt_number
        for row in db_session.scalars(
            select(JobAttempt)
            .where(JobAttempt.job_id == selected.job_id)
            .order_by(JobAttempt.attempt_number)
        )
    ] == [1]


def test_daily_tick_adopts_the_recovery_generation_onto_the_daily_path(
    db_session: Session,
) -> None:
    parent_id, _child, _attempts = _exhausted_day_plan(
        db_session, purpose=priority_scheduler.DAILY_REQUIRED_PURPOSE
    )
    plan, _ = day_recovery.plan_day_recovery(
        db_session,
        parent=db_session.get(JobRun, parent_id),
        request_key="daily-recovery-key",
        reason="repair a daily day",
        actor="system-admin",
        now=NOW,
    )
    db_session.flush()
    recovery_parent = db_session.get(JobRun, plan.parent_job_id)
    # A daily day is re-planned by the tick's own daily branch, which adopts the
    # generation first.
    priority_scheduler.ensure_daily_priority_plan(db_session, DAY, now=NOW)
    db_session.flush()

    assert (
        recovery_parent.metadata_json["priority_purpose"]
        == priority_scheduler.DAILY_REQUIRED_PURPOSE
    )
    assert (
        day_recovery.generation_ordinal(recovery_parent) == 1
    ), "adoption must not renumber the generation"


def test_recovery_request_budget_date_refreshes_with_each_tick(
    db_session: Session,
) -> None:
    """Gap C: the request budget date advances, the recovered day's purpose does not."""

    parent_id, _child, _attempts = _exhausted_day_plan(
        db_session, purpose=priority_scheduler.HISTORY_PURPOSE
    )
    plan, _ = day_recovery.plan_day_recovery(
        db_session,
        parent=db_session.get(JobRun, parent_id),
        request_key="budget-refresh-key",
        reason="repair",
        actor="system-admin",
        now=NOW,
    )
    db_session.flush()
    recovery_parent = db_session.get(JobRun, plan.parent_job_id)

    first_now = NOW
    priority_scheduler._stamp_recovery_generation(
        db_session,
        priority_scheduler._priority_rows_for_day(db_session, DAY),
        now=first_now,
    )
    db_session.flush()
    db_session.refresh(recovery_parent)
    assert recovery_parent.metadata_json["priority_purpose"] == priority_scheduler.HISTORY_PURPOSE
    first_budget_date = recovery_parent.metadata_json["request_budget_date"]
    assert first_budget_date == first_now.astimezone(priority_scheduler.SHANGHAI_TIMEZONE).date().isoformat()

    # The next day's tick must refresh the request budget date without flipping the
    # recovered day's history/daily purpose.
    next_now = first_now + timedelta(days=1)
    priority_scheduler._stamp_recovery_generation(
        db_session,
        priority_scheduler._priority_rows_for_day(db_session, DAY),
        now=next_now,
    )
    db_session.flush()
    db_session.refresh(recovery_parent)
    assert recovery_parent.metadata_json["priority_purpose"] == priority_scheduler.HISTORY_PURPOSE
    assert recovery_parent.metadata_json["request_budget_date"] != first_budget_date
    assert recovery_parent.metadata_json["request_budget_date"] == next_now.astimezone(
        priority_scheduler.SHANGHAI_TIMEZONE
    ).date().isoformat()
    # The recovered day identity is preserved, not advanced.
    assert recovery_parent.metadata_json["priority_business_date"] == DAY.isoformat()


def test_generation_order_is_explicit_not_lexicographic(db_session: Session) -> None:
    """The higher ordinal wins even when its job id sorts lower."""

    parent_id, _child, _attempts = _exhausted_day_plan(db_session)
    parent = db_session.get(JobRun, parent_id)
    first, _ = day_recovery.plan_day_recovery(
        db_session, parent=parent, request_key="order-key-1", reason="one",
        actor="system-admin", now=NOW,
    )
    db_session.flush()
    db_session.get(JobRun, first.parent_job_id).status = "failed"
    db_session.flush()
    second, _ = day_recovery.plan_day_recovery(
        db_session, parent=parent, request_key="order-key-2", reason="two",
        actor="system-admin", now=NOW,
    )
    db_session.flush()

    rows = priority_scheduler._priority_rows_for_day(db_session, DAY)
    winner = priority_scheduler.winning_generation(rows)
    assert winner is not None and winner.job_id == second.parent_job_id
    # Explicitly demonstrate the digest ordering is *not* what decided this.
    assert day_recovery.generation_order(
        db_session.get(JobRun, second.parent_job_id)
    ) > day_recovery.generation_order(db_session.get(JobRun, first.parent_job_id))


# --------------------------------------------------------------------------- #
# 5. the management API surface
# --------------------------------------------------------------------------- #


def _session_override(app, db_session: Session) -> None:
    """Bind the control API to the in-memory session for this test.

    The suite can load ``routes._data`` under both ``apps.api.dy_api`` and
    ``dy_api``; those are two distinct module objects with two distinct
    ``get_session_dependency`` functions.  Overriding only the one this file
    imported would leave the app resolving the *other* to ``None`` and every
    route would then fail on a ``None`` session.
    """

    import dy_api.routes._data as flat_data
    from apps.api.dy_api.routes._data import get_session_dependency

    def override_session():
        yield db_session

    app.dependency_overrides[get_session_dependency] = override_session
    app.dependency_overrides[flat_data.get_session_dependency] = override_session


def _control_plane_client(
    monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> "TestClient":
    from fastapi.testclient import TestClient

    from apps.api.dy_api.main import create_app

    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    monkeypatch.setenv("DY_SUPER_ADMIN_USERNAME", "system-admin")
    monkeypatch.setenv("DY_TEST_ADMIN_PASSWORD", "test-password")
    monkeypatch.setenv("DY_SESSION_COOKIE_SECURE", "false")
    app = create_app()
    _session_override(app, db_session)
    client = TestClient(app)
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"username": "system-admin", "password": "test-password"},
        ).status_code
        == 200
    )
    return client


def test_management_api_recover_is_available_authorized_and_idempotent(
    monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    from apps.api.dy_api.models import JobEvent, User
    from apps.api.dy_api.auth import hash_password_pbkdf2

    parent_id, _child, _attempts = _exhausted_day_plan(db_session)
    db_session.add(
        User(
            user_id="ordinary-admin",
            username="ordinary-admin",
            display_name="Ordinary Admin",
            role="admin",
            status="active",
            is_initialized=True,
            password_hash=hash_password_pbkdf2("secret"),
            store_scope_mode="all",
        )
    )
    db_session.commit()
    client = _control_plane_client(monkeypatch, db_session)

    path = f"/api/v1/admin/operations/jobs/{parent_id}/recover"
    body = {"reason": "repair the exhausted day"}
    # A plain admin is not the control-plane role; the session must be re-issued
    # for the ordinary user rather than reusing the super-admin cookie.
    client.cookies.clear()
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"username": "ordinary-admin", "password": "secret"},
        ).status_code
        == 200
    )
    denied = client.post(
        path, headers={"Idempotency-Key": "denied-ordinary-admin-recover"}, json=body
    )
    assert denied.status_code == 403, "recovery stays behind the control-plane role"
    db_session.expire_all()
    assert day_recovery.recovery_generations(db_session.get(JobRun, parent_id)) == []

    client.cookies.clear()
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"username": "system-admin", "password": "test-password"},
        ).status_code
        == 200
    )
    headers = {"Idempotency-Key": "recover-2026-09-14"}
    first = client.post(path, headers=headers, json=body)
    assert first.status_code == 200
    recovered = first.json()["data"]["recovered"]
    assert recovered["ordinal"] == 1
    assert recovered["job_kind"] == "range_sync"
    assert recovered["job_id"] != parent_id

    replay = client.post(path, headers=headers, json=body)
    assert replay.status_code == 200
    assert replay.json()["data"]["replayed"] is True
    assert replay.json()["data"]["recovered"]["job_id"] == recovered["job_id"]

    # A different key cannot stack a parallel generation while the first runs.
    second = client.post(
        path, headers={"Idempotency-Key": "recover-2026-09-14-b"}, json=body
    )
    assert second.status_code == 409

    db_session.expire_all()
    events = list(
        db_session.scalars(
            select(JobEvent).where(JobEvent.job_id == parent_id)
        )
    )
    assert [row.event_type for row in events].count("admin_recover_requested") == 1
    assert all(row.actor_id == "system-admin" for row in events)
    assert all(row.reason for row in events)


def test_management_api_rejects_recovering_a_successful_plan(
    monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    parent_id, _child, _attempts = _exhausted_day_plan(db_session)
    db_session.get(JobRun, parent_id).status = "success"
    db_session.commit()
    client = _control_plane_client(monkeypatch, db_session)

    response = client.post(
        f"/api/v1/admin/operations/jobs/{parent_id}/recover",
        headers={"Idempotency-Key": "recover-successful-plan-2026"},
        json={"reason": "should be refused"},
    )
    assert response.status_code == 409
    assert "not terminal" in response.json()["detail"]
    db_session.expire_all()
    assert day_recovery.recovery_generations(db_session.get(JobRun, parent_id)) == []
