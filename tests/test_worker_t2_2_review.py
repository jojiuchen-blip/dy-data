from __future__ import annotations

import os
import time
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlparse

import pytest
from sqlalchemy import delete, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.models import (
    Base,
    JobAttempt,
    ComponentHeartbeat,
    JobEvent,
    JobRun,
    JobStageRun,
)
from apps.worker import pipeline, repositories, scheduler
from apps.worker.collectors.types import PhaseStats
from apps.worker.daily_task import default_stage_handlers, execute_daily_task
from apps.worker.daily_windows import plan_daily_sync
from apps.worker.stage_runner import run_daily_stages
from apps.worker.subprocess_supervisor import (
    ChildRunStatus,
    SubprocessSupervisor,
)
from apps.worker.subprocess_supervisor import (
    ChildTerminationReason,
    _failure_error_code,
    _failure_kind,
)
from apps.worker.task_control import (
    FailureKind,
    claim_job,
    claim_next_job,
    complete_job,
    confirm_cancel_job,
    fail_job,
    heartbeat_job,
)


class FakeProcess:
    _next_pid = 9000

    def __init__(self, exit_code: int, *, delay: float = 0.0):
        FakeProcess._next_pid += 1
        self.pid = FakeProcess._next_pid
        self._exit_code = exit_code
        self._ready_at = time.monotonic() + delay

    def poll(self):
        return self._exit_code if time.monotonic() >= self._ready_at else None

    def wait(self, timeout=None):
        return self._exit_code

    def terminate(self):
        return None

    def kill(self):
        return None


def _seed_job(
    session: Session,
    job_id: str,
    *,
    target: str = "all",
    required_stages: tuple[str, ...] = ("collect", "materialize", "settle"),
    current_stage: str = "collect",
    parent_job_id: str = "range-parent",
    business_date: date = date(2026, 8, 5),
    max_attempts: int = 3,
    complete_stages: bool = False,
) -> JobRun:
    """Seed a planner-authoritative child and return its real deterministic id."""

    del job_id, parent_job_id
    plan = plan_daily_sync(
        session,
        start=business_date,
        end=business_date + timedelta(days=1),
        target=target,
        requested_by="review",
        trigger_source="review-test",
        config_version=f"review-seed-{time.time_ns()}",
    )
    job = session.get(JobRun, plan.daily_jobs[0].job_id)
    if job is None:
        raise AssertionError("planner did not create a daily child")
    job.current_stage = current_stage
    job.max_attempts = max_attempts
    now = datetime.now(UTC)
    if complete_stages:
        for stage_name in required_stages:
            session.add(
                JobStageRun(
                    stage_run_id=f"stage-{job.job_id}-{stage_name}",
                    job_id=job.job_id,
                    stage_name=stage_name,
                    status="success",
                    checkpoint_json={"status": "success", "stage": stage_name},
                    lease_epoch=0,
                    started_at=now,
                    finished_at=now,
                    committed_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
    session.commit()
    return job


@pytest.fixture()
def t12_postgres_factory():
    url = os.getenv("DYDATA_T12_TEST_DATABASE_URL")
    if not url:
        pytest.skip("DYDATA_T12_TEST_DATABASE_URL is not configured")
    parsed = urlparse(url)
    if parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.port != 55432:
        pytest.fail("PostgreSQL test must use loopback port 55432")
    engine = __import__("sqlalchemy").create_engine(url, future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, future=True)
    yield factory
    # Keep the dedicated local database reusable between review runs.  Clear
    # component references before deleting attempts because the composite FK
    # intentionally uses RESTRICT semantics.
    with engine.begin() as connection:
        review_ids = [
            row[0]
            for row in connection.execute(
                select(JobRun.job_id).where(
                    or_(
                        JobRun.job_id.like("review-%"),
                        JobRun.config_version.like("review-%"),
                        JobRun.config_version.like("subprocess-recovery%"),
                    )
                )
            )
        ]
        if review_ids:
            connection.execute(
                update(ComponentHeartbeat)
                .where(ComponentHeartbeat.current_job_id.in_(review_ids))
                .values(current_job_id=None, current_attempt_id=None)
            )
            connection.execute(delete(JobEvent).where(JobEvent.job_id.in_(review_ids)))
            connection.execute(delete(JobAttempt).where(JobAttempt.job_id.in_(review_ids)))
            connection.execute(delete(JobStageRun).where(JobStageRun.job_id.in_(review_ids)))
            connection.execute(delete(JobRun).where(JobRun.parent_job_id.in_(review_ids)))
            connection.execute(delete(JobRun).where(JobRun.job_id.in_(review_ids)))
    engine.dispose()


def test_claim_exhausted_expired_attempt_commits_cleanup_and_next_date_is_claimable(
    t12_postgres_factory,
) -> None:
    factory = t12_postgres_factory
    with factory() as session:
        plan = plan_daily_sync(
            session,
            start=date(2026, 8, 5),
            end=date(2026, 8, 7),
            target="orders",
            requested_by="review",
            trigger_source="review-test",
            config_version=f"review-exhausted-{time.time_ns()}",
        )
        children = list(
            session.scalars(
                select(JobRun)
                .where(
                    JobRun.parent_job_id == plan.parent_job_id,
                    JobRun.job_kind == "date_sync",
                )
                .order_by(JobRun.business_date)
            )
        )
        assert len(children) == 2
        first_job, second_job = children
        first_job.max_attempts = 1
        second_job.max_attempts = 1
        first_id, second_id = first_job.job_id, second_job.job_id
        session.flush()
        first = claim_job(
            session,
            job_id=first_id,
            lease_owner="review-old-owner",
            component_instance_id="review-component",
            lease_seconds=10,
        )
        assert first is not None
        session.commit()
        session.execute(
            update(JobRun)
            .where(JobRun.job_id == first_id)
            .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        session.commit()

    supervisor = SubprocessSupervisor(
        control_session_factory=factory,
        popen_factory=lambda *_args, **_kwargs: FakeProcess(0),
        poll_interval_seconds=0,
    )
    assert supervisor._start_attempt(None, attempt_number=1) is None
    with factory() as session:
        exhausted = session.get(JobRun, first_id)
        assert exhausted is not None and exhausted.status == "failed"
        old_attempt = session.scalar(
            select(JobAttempt).where(JobAttempt.job_id == first_id)
        )
        assert old_attempt is not None and old_attempt.finished_at is not None
    next_token = supervisor._start_attempt(None, attempt_number=1)
    assert next_token is not None and next_token.job_id == second_id


def test_parent_heavy_slot_success_unblocks_dates_but_failure_keeps_them_blocked(
    t12_postgres_factory,
) -> None:
    factory = t12_postgres_factory
    with factory() as session:
        _successful_range, successful_execution, successful_children = _seed_planned_parent_range(
            session,
            start=date(2026, 8, 5),
            target="all",
        )
        _failed_range, failed_execution, failed_children = _seed_planned_parent_range(
            session,
            start=date(2026, 8, 7),
            target="all",
        )
        successful_execution.status = "pending"
        successful_execution.success_count = 0
        successful_execution.finished_at = None
        failed_execution.status = "pending"
        failed_execution.success_count = 0
        failed_execution.finished_at = None
        session.commit()
        successful_range = _successful_range.job_id
        successful_parent = successful_execution.job_id
        successful_date = successful_children[0].job_id
        failed_parent = failed_execution.job_id
        failed_date = failed_children[0].job_id

    with factory() as session:
        parent_token = claim_job(
            session,
            job_id=successful_parent,
            lease_owner="review-parent-owner",
            component_instance_id="review-parent-component",
            lease_seconds=30,
        )
        assert parent_token is not None
        assert complete_job(session, parent_token, success_count=1)
        session.commit()
        assert session.get(JobRun, successful_range).status == "pending"
        date_token = claim_job(
            session,
            job_id=successful_date,
            lease_owner="review-date-owner",
            component_instance_id="review-date-component",
            lease_seconds=30,
        )
        assert date_token is not None
        assert fail_job(
            session,
            date_token,
            failure_kind=FailureKind.TRANSIENT,
            error_code="review_release",
            error_summary="release test lease",
        ) is not None
        session.commit()

        failed_parent_token = claim_job(
            session,
            job_id=failed_parent,
            lease_owner="review-failed-owner",
            component_instance_id="review-failed-component",
            lease_seconds=30,
        )
        assert failed_parent_token is not None
        assert fail_job(
            session,
            failed_parent_token,
            failure_kind=FailureKind.DATA_INTEGRITY,
            error_code="review_parent_failed",
            error_summary="parent stage failed",
        ) is not None
        session.commit()
        assert claim_job(
            session,
            job_id=failed_date,
            lease_owner="review-blocked-owner",
            component_instance_id="review-blocked-component",
            lease_seconds=30,
        ) is None


def test_postgres_retry_wait_with_historical_heartbeat_remains_claimable(
    t12_postgres_factory,
) -> None:
    """A completed retry keeps its last observation but is not an active lease."""

    with t12_postgres_factory() as session:
        _parent, _execution, children = _seed_planned_parent_range(
            session,
            start=date(2026, 8, 6),
            target="all",
        )
        job = children[0]
        token = claim_job(
            session,
            job_id=job.job_id,
            lease_owner="review-retry-owner",
            component_instance_id="review-retry-component",
            lease_seconds=30,
        )
        assert token is not None
        assert heartbeat_job(session, token, lease_seconds=30)
        assert fail_job(
            session,
            token,
            failure_kind=FailureKind.TRANSIENT,
            error_code="review_retry",
            error_summary="retry after a transient worker error",
            base_delay_seconds=1,
        ) is not None
        session.flush()
        retrying = session.get(JobRun, job.job_id)
        assert retrying is not None and retrying.status == "retry_wait"
        assert retrying.heartbeat_at is not None

        session.execute(
            update(JobRun)
            .where(JobRun.job_id == job.job_id)
            .values(next_retry_at=text("clock_timestamp() - interval '1 second'"))
        )
        session.commit()

        retry_token = claim_job(
            session,
            job_id=job.job_id,
            lease_owner="review-retry-owner-2",
            component_instance_id="review-retry-component-2",
            lease_seconds=30,
        )
        assert retry_token is not None
        assert retry_token.attempt_number == 2
        assert session.get(JobRun, job.job_id).status == "running"


@pytest.mark.parametrize(
    ("reason", "expected_kind", "expected_code"),
    [
        (ChildTerminationReason.PROCESS_EXIT, "crashed", "worker_exit_9"),
        (ChildTerminationReason.TIMEOUT, "transient", "worker_timeout"),
        (ChildTerminationReason.RSS_GUARD, "memory_guard", "worker_memory_guard"),
        (ChildTerminationReason.LEASE_LOST, "transient", "worker_lease_lost"),
        (ChildTerminationReason.SPAWN, "transient", "worker_spawn_error"),
        (ChildTerminationReason.CONTROL, "transient", "worker_control_error"),
    ],
)
def test_termination_reason_controls_failure_classification(
    reason: ChildTerminationReason,
    expected_kind: str,
    expected_code: str,
) -> None:
    assert _failure_kind(
        -9,
        termination_reason=reason,
        error_summary=None,
        rss_peak_bytes=99,
        rss_limit_bytes=100,
    ).value == expected_kind
    assert (
        _failure_error_code(
            -9,
            termination_reason=reason,
            rss_peak_bytes=99,
            rss_limit_bytes=100,
        )
        == expected_code
    )


def test_required_checkpoints_make_nonzero_child_exit_business_success(
    db_session: Session,
) -> None:
    job = _seed_job(
        db_session,
        "review-checkpoint-success",
        target="orders",
        complete_stages=True,
    )
    job_id = job.job_id
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, future=True)
    supervisor = SubprocessSupervisor(
        control_session_factory=factory,
        popen_factory=lambda *_args, **_kwargs: FakeProcess(7),
        rss_reader=lambda _pid: 123,
        poll_interval_seconds=0,
    )
    result = supervisor.run(
        job_id=job_id,
        command=["python", "-m", "apps.worker.daily_task"],
        max_attempts=1,
    )
    assert result.status is ChildRunStatus.SUCCESS
    with factory() as session:
        job = session.get(JobRun, job_id)
        attempt = session.scalar(
            select(JobAttempt).where(JobAttempt.job_id == job_id)
        )
        assert job is not None and job.status == "success"
        assert attempt is not None and attempt.exit_code == 7


def test_process_exit_minus9_is_not_oom_without_an_rss_guard(db_session: Session) -> None:
    job = _seed_job(
        db_session,
        "review-process-exit-minus9",
        target="orders",
        max_attempts=1,
    )
    job_id = job.job_id
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, future=True)
    supervisor = SubprocessSupervisor(
        control_session_factory=factory,
        popen_factory=lambda *_args, **_kwargs: FakeProcess(-9),
        rss_reader=lambda _pid: 99,
        poll_interval_seconds=0,
    )
    result = supervisor.run(
        job_id=job_id,
        command=["python", "-m", "apps.worker.daily_task"],
        max_attempts=1,
    )
    assert result.status is ChildRunStatus.FAILED
    assert result.termination_reason is ChildTerminationReason.PROCESS_EXIT
    with factory() as session:
        attempt = session.scalar(
            select(JobAttempt).where(JobAttempt.job_id == job_id)
        )
        assert attempt is not None and attempt.error_code == "worker_exit_9"


def test_timeout_reason_wins_even_when_child_exit_code_is_minus9(db_session: Session) -> None:
    job = _seed_job(
        db_session,
        "review-timeout-minus9",
        target="orders",
        max_attempts=1,
    )
    job_id = job.job_id
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, future=True)
    supervisor = SubprocessSupervisor(
        control_session_factory=factory,
        popen_factory=lambda *_args, **_kwargs: FakeProcess(-9, delay=1.0),
        rss_reader=lambda _pid: 99,
        poll_interval_seconds=0,
    )
    result = supervisor.run(
        job_id=job_id,
        command=["python", "-m", "apps.worker.daily_task"],
        max_attempts=1,
        timeout_seconds=0.001,
    )
    assert result.status is ChildRunStatus.TIMEOUT
    assert result.termination_reason is ChildTerminationReason.TIMEOUT
    with factory() as session:
        attempt = session.scalar(
            select(JobAttempt).where(JobAttempt.job_id == job_id)
        )
        assert attempt is not None and attempt.error_code == "worker_timeout"


def test_parent_dimension_stage_is_consumed_once_and_promotes_range_checkpoint(
    db_session: Session,
) -> None:
    now = datetime.now(UTC)
    range_parent_id = "review-range-parent"
    execution_id = "review-parent-execution"
    db_session.add(
        JobRun(
            job_id=range_parent_id,
            job_name="range_sync",
            status="pending",
            started_at=now,
            success_count=0,
            failed_count=0,
            metadata_json={"target": "all"},
            job_kind="range_sync",
            data_source="douyin",
            config_version="v1",
            window_start=datetime(2026, 8, 5, tzinfo=UTC),
            window_end=datetime(2026, 8, 6, tzinfo=UTC),
            attempt_count=0,
            max_attempts=3,
        )
    )
    db_session.add(
        JobRun(
            job_id=execution_id,
            job_name="parent_sync",
            status="running",
            started_at=now,
            success_count=0,
            failed_count=0,
            metadata_json={"target": "all", "required_stages": ["collect_dimensions"]},
            parent_job_id=range_parent_id,
            job_kind="parent_sync",
            execution_slot="heavy_sync",
            data_source="douyin",
            config_version="v1",
            window_start=datetime(2026, 8, 5, tzinfo=UTC),
            window_end=datetime(2026, 8, 6, tzinfo=UTC),
            current_stage="collect_dimensions",
            attempt_count=1,
            max_attempts=3,
            lease_epoch=1,
        )
    )
    db_session.commit()
    calls: list[str] = []
    handlers = {
        "collect_dimensions": lambda _session, _job: calls.append("dimensions") or {"rows": 1}
    }
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, future=True)
    first = run_daily_stages(factory, job_id=execution_id, handlers=handlers)
    second = run_daily_stages(factory, job_id=execution_id, handlers=handlers)
    with factory() as session:
        range_stage = session.scalar(
            select(JobStageRun).where(
                JobStageRun.job_id == range_parent_id,
                JobStageRun.stage_name == "collect_dimensions",
            )
        )
        assert range_stage is not None and range_stage.status == "success"
        range_parent = session.get(JobRun, range_parent_id)
        assert range_parent is not None and range_parent.status == "pending"
    assert first.completed_stages == ("collect_dimensions",)
    assert second.skipped_stages == ("collect_dimensions",)
    assert calls == ["dimensions"]


def test_daily_target_handlers_do_not_collect_or_settle_unrelated_targets(
    monkeypatch,
    db_session: Session,
) -> None:
    job = _seed_job(
        db_session,
        "review-settlement-only",
        target="settlement",
        required_stages=("settle",),
        current_stage="settle",
    )
    # This test exercises the legacy target-isolation compatibility branch.
    # Planner-created jobs now opt into incremental settlement by default; an
    # explicit unmarked row is required to retain the legacy contract here.
    job.metadata_json = {
        key: value
        for key, value in (job.metadata_json or {}).items()
        if key != "settlement_mode"
    }
    db_session.commit()
    calls: list[str] = []

    class FakeStats:
        detail_count = 1

    monkeypatch.setattr(pipeline, "default_collectors", lambda: [])
    monkeypatch.setattr(
        "apps.worker.daily_task.rebuild_settlement",
        lambda session, source_run_id: (calls.append("settle") or FakeStats()),
    )
    handlers = default_stage_handlers(client=object())
    execute_daily_task(
        job.job_id,
        session_factory=sessionmaker(bind=db_session.get_bind(), autoflush=False, future=True),
        handlers=handlers,
        allow_unfenced_test=True,
    )
    assert calls == ["settle"]


@pytest.mark.parametrize(
    ("target", "expected_phases"),
    [
        ("all", ("orders", "refunds", "clues", "verify_records")),
        ("orders", ("orders",)),
        ("verify_records", ("verify_records",)),
    ],
)
def test_collect_target_semantics_exclude_dimension_and_unrelated_collectors(
    monkeypatch,
    db_session: Session,
    target: str,
    expected_phases: tuple[str, ...],
) -> None:
    calls: list[str] = []

    def make_collector(name: str):
        def collect(_session, _client, _window, _source_run_id):
            calls.append(name)
            return PhaseStats(name=name, fetched=1)

        return collect

    collector_names = (
        "shop_pois",
        "aweme_bindings",
        "orders",
        "refunds",
        "clues",
        "verify_records",
    )
    monkeypatch.setattr(
        pipeline,
        "default_collectors",
        lambda: [make_collector(name) for name in collector_names],
    )
    handlers = default_stage_handlers(client=object())
    job = type(
        "TargetJob",
        (),
        {
            "job_id": f"review-target-{target}",
            "metadata_json": {"target": target},
            "window_start": datetime(2026, 8, 5, tzinfo=UTC),
            "window_end": datetime(2026, 8, 6, tzinfo=UTC),
        },
    )()
    metadata = handlers["collect"](db_session, job)
    assert tuple(metadata["phases"]) == expected_phases
    assert tuple(calls) == expected_phases


def test_planner_enqueues_a_parent_execution_job_for_parent_targets(db_session: Session) -> None:
    plan = plan_daily_sync(
        db_session,
        start="2026-08-05",
        end="2026-08-07",
        target="shop_pois",
        requested_by="review",
        trigger_source="review",
    )
    parent_jobs = list(
        db_session.scalars(
            select(JobRun).where(
                JobRun.parent_job_id == plan.parent_job_id,
                JobRun.job_kind == "parent_sync",
            )
        )
    )
    assert len(parent_jobs) == 1
    assert parent_jobs[0].execution_slot == "heavy_sync"
    assert parent_jobs[0].status == "pending"


def test_clue_center_materialize_runs_master_and_center_without_collect_or_settle(
    monkeypatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "apps.worker.daily_task.materialize_clue_master_leads",
        lambda _session: (calls.append("master") or {"updated": 1}),
    )
    monkeypatch.setattr(
        "apps.worker.daily_task.refresh_clue_center_projection",
        lambda _session, **_kwargs: (calls.append("center") or {"updated": 1}),
    )
    handlers = default_stage_handlers(client=object())
    job = type(
        "ClueCenterJob",
        (),
        {"job_id": "review-clue-center", "metadata_json": {"target": "clue_center"}},
    )()

    result = handlers["materialize"](object(), job)

    assert result == {
        "master": {"updated": 1},
        "center": {"updated": 1},
    }
    assert calls == ["master", "center"]


@pytest.mark.parametrize(
    ("target", "expected_required_stages", "expected_daily_targets"),
    [
        ("all", ["collect_dimensions"], ["orders", "refunds", "clues", "verify_records", "clue_center", "settlement"]),
        ("shop_pois", ["collect_dimensions", "materialize", "settle"], []),
        ("aweme_bindings", ["collect_dimensions", "materialize", "settle"], []),
        ("backend_aweme_export", ["collect_dimensions", "settle"], []),
    ],
)
def test_parent_execution_required_stages_preserve_single_target_semantics(
    db_session: Session,
    target: str,
    expected_required_stages: list[str],
    expected_daily_targets: list[str],
) -> None:
    plan = plan_daily_sync(
        db_session,
        start="2026-08-05",
        end="2026-08-07",
        target=target,
        requested_by="review",
        trigger_source="review",
    )
    execution = db_session.scalar(
        select(JobRun).where(
            JobRun.parent_job_id == plan.parent_job_id,
            JobRun.job_kind == "parent_sync",
        )
    )
    assert execution is not None
    assert execution.metadata_json["required_stages"] == expected_required_stages
    assert execution.metadata_json["daily_targets"] == expected_daily_targets
    assert execution.current_stage == "collect_dimensions"


def test_all_parent_collects_only_dimensions_once(db_session: Session, monkeypatch) -> None:
    calls: list[str] = []

    def make_collector(name: str):
        def collect(_session, _client, _window, _source_run_id):
            calls.append(name)
            return PhaseStats(name=name, fetched=1)

        return collect

    monkeypatch.setattr(
        pipeline,
        "default_collectors",
        lambda: [make_collector(name) for name in (
            "shop_pois",
            "aweme_bindings",
            "orders",
            "clues",
            "verify_records",
            "refunds",
        )],
    )
    handlers = default_stage_handlers(client=object())
    job = type(
        "AllParentJob",
        (),
        {
            "job_id": "review-all-parent",
            "metadata_json": {"target": "all"},
            "window_start": datetime(2026, 8, 5, tzinfo=UTC),
            "window_end": datetime(2026, 8, 6, tzinfo=UTC),
        },
    )()

    handlers["collect_dimensions"](db_session, job)

    assert calls == ["shop_pois", "aweme_bindings"]


def test_backend_parent_exports_then_settles_without_unrelated_refresh(
    monkeypatch,
    db_session: Session,
) -> None:
    calls: list[str] = []

    class FakeStats:
        detail_count = 2

        def as_metadata(self):
            return {"name": "backend_aweme_export", "upserted": 2}

    monkeypatch.setattr(
        "apps.worker.browser_exports.backend_aweme.run_backend_aweme_export",
        lambda _session, source_run_id: (calls.append("export") or FakeStats()),
    )
    monkeypatch.setattr(
        "apps.worker.daily_task.rebuild_settlement",
        lambda _session, source_run_id: (calls.append("settlement") or FakeStats()),
    )
    monkeypatch.setattr(
        "apps.worker.daily_task.materialize_clue_master_leads",
        lambda _session: (calls.append("master") or {}),
    )
    monkeypatch.setattr(
        "apps.worker.daily_task.refresh_clue_center_projection",
        lambda _session, **_kwargs: (calls.append("center") or {}),
    )
    handlers = default_stage_handlers(client=object())
    job = type(
        "BackendParentJob",
        (),
        {"job_id": "review-backend-parent", "metadata_json": {"target": "backend_aweme_export"}},
    )()

    handlers["collect_dimensions"](db_session, job)
    handlers["settle"](db_session, job)

    assert calls == ["export", "settlement"]


def test_parent_range_checkpoint_waits_for_all_required_stages_and_fails_late(
    db_session: Session,
) -> None:
    now = datetime.now(UTC)
    range_id = "review-parent-range-aggregate"
    execution_id = "review-parent-execution-aggregate"
    db_session.add(
        JobRun(
            job_id=range_id,
            job_name="range_sync",
            status="pending",
            started_at=now,
            success_count=0,
            failed_count=0,
            metadata_json={"target": "shop_pois", "parent_targets": ["shop_pois"], "daily_targets": []},
            job_kind="range_sync",
            data_source="douyin",
            config_version="v1",
            window_start=datetime(2026, 8, 5, tzinfo=UTC),
            window_end=datetime(2026, 8, 6, tzinfo=UTC),
            attempt_count=0,
            max_attempts=3,
        )
    )
    db_session.add(
        JobRun(
            job_id=execution_id,
            job_name="parent_sync",
            status="running",
            started_at=now,
            success_count=0,
            failed_count=0,
            metadata_json={
                "target": "shop_pois",
                "parent_targets": ["shop_pois"],
                "daily_targets": [],
                "required_stages": ["collect_dimensions", "materialize", "settle"],
            },
            parent_job_id=range_id,
            job_kind="parent_sync",
            execution_slot="heavy_sync",
            data_source="douyin",
            config_version="v1",
            window_start=datetime(2026, 8, 5, tzinfo=UTC),
            window_end=datetime(2026, 8, 6, tzinfo=UTC),
            current_stage="collect_dimensions",
            attempt_count=1,
            max_attempts=3,
            lease_epoch=1,
        )
    )
    db_session.commit()
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, future=True)

    run_daily_stages(
        factory,
        job_id=execution_id,
        handlers={"collect_dimensions": lambda _session, _job: {"rows": 1}},
        stage_order=("collect_dimensions",),
    )
    with factory() as session:
        range_stage = session.scalar(
            select(JobStageRun).where(
                JobStageRun.job_id == range_id,
                JobStageRun.stage_name == "collect_dimensions",
            )
        )
        assert range_stage is not None and range_stage.status != "success"

    with pytest.raises(RuntimeError, match="materialize failed"):
        run_daily_stages(
            factory,
            job_id=execution_id,
            handlers={
                "collect_dimensions": lambda _session, _job: {"rows": 1},
                "materialize": lambda _session, _job: (_ for _ in ()).throw(
                    RuntimeError("materialize failed")
                ),
                "settle": lambda _session, _job: {"rows": 1},
            },
            stage_order=("collect_dimensions", "materialize", "settle"),
        )
    with factory() as session:
        range_stage = session.scalar(
            select(JobStageRun).where(
                JobStageRun.job_id == range_id,
                JobStageRun.stage_name == "collect_dimensions",
            )
        )
        assert range_stage is not None and range_stage.status == "failed"


def test_parent_execution_replay_rejects_tampered_identity_without_resetting_state(
    db_session: Session,
) -> None:
    plan = plan_daily_sync(
        db_session,
        start="2026-08-05",
        end="2026-08-07",
        target="shop_pois",
        requested_by="review",
        trigger_source="review",
    )
    execution = db_session.scalar(
        select(JobRun).where(
            JobRun.parent_job_id == plan.parent_job_id,
            JobRun.job_kind == "parent_sync",
        )
    )
    assert execution is not None
    execution.job_name = "tampered-parent"
    execution.status = "running"
    execution.attempt_count = 2
    execution.lease_epoch = 2
    db_session.commit()

    with pytest.raises(RuntimeError, match="parent execution identity"):
        plan_daily_sync(
            db_session,
            start="2026-08-05",
            end="2026-08-07",
            target="shop_pois",
            requested_by="replay",
            trigger_source="replay",
        )
    preserved = db_session.get(JobRun, execution.job_id)
    assert preserved is not None
    assert (preserved.job_name, preserved.status, preserved.attempt_count, preserved.lease_epoch) == (
        "tampered-parent",
        "running",
        2,
        2,
    )


def test_daily_child_replay_rejects_tampered_required_stages_without_resetting_state(
    db_session: Session,
) -> None:
    plan = plan_daily_sync(
        db_session,
        start="2026-08-05",
        end="2026-08-07",
        target="orders",
        requested_by="review",
        trigger_source="review",
    )
    child = db_session.get(JobRun, plan.daily_jobs[0].job_id)
    assert child is not None
    child.metadata_json = {**child.metadata_json, "required_stages": ["settle"]}
    child.status = "running"
    child.attempt_count = 2
    child.lease_epoch = 2
    db_session.commit()

    with pytest.raises(RuntimeError, match="daily child identity"):
        plan_daily_sync(
            db_session,
            start="2026-08-05",
            end="2026-08-07",
            target="orders",
            requested_by="replay",
            trigger_source="replay",
        )
    preserved = db_session.get(JobRun, child.job_id)
    assert preserved is not None
    assert preserved.metadata_json["required_stages"] == ["settle"]
    assert (preserved.status, preserved.attempt_count, preserved.lease_epoch) == (
        "running",
        2,
        2,
    )


@pytest.mark.parametrize(
    "invalid_values",
    [
        {"parent_job_id": None},
        {"execution_slot": None},
        {"business_date": date(2026, 8, 5)},
        {"data_source": None},
        {"config_version": None},
        {"window_start": None},
        {"window_end": datetime(2026, 8, 5, tzinfo=UTC)},
    ],
)
def test_parent_sync_model_constraints_reject_incomplete_rows(
    db_session: Session,
    invalid_values: dict[str, object],
) -> None:
    now = datetime(2026, 8, 5, tzinfo=UTC)
    values = {
        "job_id": f"review-invalid-parent-{time.time_ns()}",
        "job_name": "parent_sync",
        "status": "pending",
        "started_at": now,
        "success_count": 0,
        "failed_count": 0,
        "metadata_json": {"target": "shop_pois", "required_stages": ["collect_dimensions"]},
        "parent_job_id": "review-range-reference",
        "job_kind": "parent_sync",
        "execution_slot": "heavy_sync",
        "business_date": None,
        "data_source": "douyin",
        "config_version": "v1",
        "window_start": now,
        "window_end": datetime(2026, 8, 6, tzinfo=UTC),
        "current_stage": "collect_dimensions",
        "attempt_count": 0,
        "max_attempts": 3,
        **invalid_values,
    }
    with pytest.raises(IntegrityError):
        db_session.add(JobRun(**values))
        db_session.flush()
    db_session.rollback()


def test_parent_sync_postgres_constraints_reject_incomplete_rows(
    t12_postgres_factory,
) -> None:
    factory = t12_postgres_factory
    suffix = str(time.time_ns())
    range_id = f"review-pg-parent-range-{suffix}"
    with factory.begin() as session:
        session.add(
            JobRun(
                job_id=range_id,
                job_name="range_sync",
                status="pending",
                started_at=datetime.now(UTC),
                success_count=0,
                failed_count=0,
                metadata_json={"target": "shop_pois"},
                job_kind="range_sync",
                data_source="douyin",
                config_version="v1",
                window_start=datetime(2026, 8, 5, tzinfo=UTC),
                window_end=datetime(2026, 8, 6, tzinfo=UTC),
                attempt_count=0,
                max_attempts=3,
            )
        )

    base_values = {
        "job_name": "parent_sync",
        "status": "pending",
        "started_at": datetime.now(UTC),
        "success_count": 0,
        "failed_count": 0,
        "metadata_json": {"target": "shop_pois", "required_stages": ["collect_dimensions"]},
        "parent_job_id": range_id,
        "job_kind": "parent_sync",
        "execution_slot": "heavy_sync",
        "business_date": None,
        "data_source": "douyin",
        "config_version": "v1",
        "window_start": datetime(2026, 8, 5, tzinfo=UTC),
        "window_end": datetime(2026, 8, 6, tzinfo=UTC),
        "current_stage": "collect_dimensions",
        "attempt_count": 0,
        "max_attempts": 3,
        "lease_epoch": 0,
    }
    for index, invalid in enumerate(
        (
            {"parent_job_id": None},
            {"execution_slot": None},
            {"business_date": date(2026, 8, 5)},
            {"data_source": None},
            {"config_version": None},
            {"window_start": None},
            {"window_end": datetime(2026, 8, 5, tzinfo=UTC)},
        )
    ):
        values = {
            **base_values,
            "job_id": f"review-pg-invalid-parent-{suffix}-{index}",
            **invalid,
        }
        with pytest.raises(IntegrityError):
            with factory.begin() as session:
                session.add(JobRun(**values))


def _seed_parent_required_date_job(
    session: Session,
    *,
    range_id: str,
    job_id: str,
    target: str,
    parent_status: str | None = None,
) -> tuple[str, str, str | None]:
    del range_id, job_id
    plan = plan_daily_sync(
        session,
        start=date(2026, 8, 5),
        end=date(2026, 8, 6),
        target=target,
        requested_by="review",
        trigger_source="review-test",
        config_version=f"review-parent-required-{time.time_ns()}",
    )
    parent = session.get(JobRun, plan.parent_job_id)
    child = session.scalar(
        select(JobRun).where(
            JobRun.parent_job_id == plan.parent_job_id,
            JobRun.job_kind == "date_sync",
        )
    )
    execution = session.scalar(
        select(JobRun).where(
            JobRun.parent_job_id == plan.parent_job_id,
            JobRun.job_kind == "parent_sync",
        )
    )
    assert parent is not None and child is not None
    if parent_status is None and execution is not None:
        session.delete(execution)
        execution_id = None
    elif execution is not None:
        execution.status = parent_status
        execution.success_count = 1 if parent_status == "success" else 0
        execution.attempt_count = 1
        execution.lease_epoch = 1
        execution_id = execution.job_id
    else:
        execution_id = None
    session.commit()
    return parent.job_id, child.job_id, execution_id


def _seed_planned_parent_range(
    session: Session,
    *,
    start: date = date(2026, 1, 1),
    days: int = 1,
    target: str = "all",
) -> tuple[JobRun, JobRun, list[JobRun]]:
    """Create planner-authoritative range/parent/date rows for identity tests."""

    plan = plan_daily_sync(
        session,
        start=start,
        end=start + timedelta(days=days),
        target=target,
        requested_by="review",
        trigger_source="review",
        config_version=f"review-t22-{time.time_ns()}",
    )
    parent = session.get(JobRun, plan.parent_job_id)
    execution = session.scalar(
        select(JobRun).where(
            JobRun.parent_job_id == plan.parent_job_id,
            JobRun.job_kind == "parent_sync",
        )
    )
    children = list(
        session.scalars(
            select(JobRun)
            .where(
                JobRun.parent_job_id == plan.parent_job_id,
                JobRun.job_kind == "date_sync",
            )
            .order_by(JobRun.business_date, JobRun.job_id)
        )
    )
    assert parent is not None
    assert execution is not None
    assert children
    execution.status = "success"
    execution.success_count = 1
    execution.finished_at = datetime.now(UTC)
    execution.lease_owner = None
    execution.lease_expires_at = None
    session.flush()
    return parent, execution, children


@pytest.mark.parametrize("mutation", ["missing", "empty"])
def test_parent_gate_rejects_child_parent_targets_removed_from_range_plan_sqlite(
    db_session: Session,
    mutation: str,
) -> None:
    _parent, _execution, children = _seed_planned_parent_range(db_session, target="all")
    child = children[0]
    child_metadata = dict(child.metadata_json or {})
    if mutation == "missing":
        child_metadata.pop("parent_targets", None)
    else:
        child_metadata["parent_targets"] = []
    child.metadata_json = child_metadata
    db_session.commit()
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, future=True)
    with factory.begin() as session:
        assert claim_job(
            session,
            job_id=child.job_id,
            lease_owner=f"review-child-parent-targets-{mutation}",
            component_instance_id=f"review-child-parent-targets-{mutation}-component",
            lease_seconds=30,
        ) is None


@pytest.mark.parametrize("mutation", ["missing", "empty"])
def test_parent_gate_rejects_child_parent_targets_removed_from_range_plan_postgres(
    t12_postgres_factory,
    mutation: str,
) -> None:
    with t12_postgres_factory.begin() as session:
        _parent, _execution, children = _seed_planned_parent_range(
            session,
            target="all",
        )
        child = children[0]
        child_metadata = dict(child.metadata_json or {})
        if mutation == "missing":
            child_metadata.pop("parent_targets", None)
        else:
            child_metadata["parent_targets"] = []
        child.metadata_json = child_metadata
        child_id = child.job_id
    with t12_postgres_factory.begin() as session:
        assert claim_job(
            session,
            job_id=child_id,
            lease_owner=f"review-pg-child-parent-targets-{mutation}",
            component_instance_id=f"review-pg-child-parent-targets-{mutation}-component",
            lease_seconds=30,
        ) is None


def test_parent_gate_rejects_range_plan_identity_mismatch_sqlite(
    db_session: Session,
) -> None:
    parent, _execution, children = _seed_planned_parent_range(db_session, target="all")
    parent.metadata_json = {**(parent.metadata_json or {}), "timezone": "UTC"}
    db_session.commit()
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, future=True)
    with factory.begin() as session:
        assert claim_job(
            session,
            job_id=children[0].job_id,
            lease_owner="review-range-identity-owner",
            component_instance_id="review-range-identity-component",
            lease_seconds=30,
        ) is None


def test_parent_gate_rejects_range_plan_identity_mismatch_postgres(
    t12_postgres_factory,
) -> None:
    with t12_postgres_factory.begin() as session:
        parent, _execution, children = _seed_planned_parent_range(session, target="all")
        parent.metadata_json = {**(parent.metadata_json or {}), "timezone": "UTC"}
        child_id = children[0].job_id
    with t12_postgres_factory.begin() as session:
        assert claim_job(
            session,
            job_id=child_id,
            lease_owner="review-pg-range-identity-owner",
            component_instance_id="review-pg-range-identity-component",
            lease_seconds=30,
        ) is None


@pytest.mark.parametrize(
    "field",
    [
        "job_name",
        "idempotency_key_hash",
        "data_source",
        "config_version",
        "window_start",
        "window_end",
        "target",
        "parent_targets",
        "daily_targets",
        "required_stages",
        "timezone",
        "source_window",
    ],
)
def test_parent_gate_rejects_parent_execution_identity_mismatch_sqlite(
    db_session: Session,
    field: str,
) -> None:
    _parent, execution, children = _seed_planned_parent_range(db_session, target="all")
    metadata = dict(execution.metadata_json or {})
    if field == "job_name":
        execution.job_name = "wrong_parent"
    elif field == "idempotency_key_hash":
        execution.idempotency_key_hash = "wrong-idempotency"
    elif field == "data_source":
        execution.data_source = "other-source"
    elif field == "config_version":
        execution.config_version = "other-config"
    elif field == "window_start":
        execution.window_start = execution.window_start + timedelta(hours=1)
    elif field == "window_end":
        execution.window_end = execution.window_end - timedelta(hours=1)
    elif field == "target":
        metadata["target"] = "orders"
    elif field == "parent_targets":
        metadata["parent_targets"] = []
    elif field == "daily_targets":
        metadata["daily_targets"] = []
    elif field == "required_stages":
        metadata["required_stages"] = ["settle"]
    elif field == "timezone":
        metadata["timezone"] = "UTC"
    elif field == "source_window":
        metadata["source_window"] = {
            **metadata["source_window"],
            "timezone": "UTC",
        }
    execution.metadata_json = metadata
    db_session.commit()
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, future=True)
    with factory.begin() as session:
        assert claim_job(
            session,
            job_id=children[0].job_id,
            lease_owner=f"review-parent-identity-{field}",
            component_instance_id=f"review-parent-identity-{field}-component",
            lease_seconds=30,
        ) is None


@pytest.mark.parametrize(
    "field",
    [
        "job_name",
        "idempotency_key_hash",
        "data_source",
        "config_version",
        "window_start",
        "window_end",
        "target",
        "parent_targets",
        "daily_targets",
        "required_stages",
        "timezone",
        "source_window",
    ],
)
def test_parent_gate_rejects_parent_execution_identity_mismatch_postgres(
    t12_postgres_factory,
    field: str,
) -> None:
    with t12_postgres_factory.begin() as session:
        _parent, execution, children = _seed_planned_parent_range(session, target="all")
        metadata = dict(execution.metadata_json or {})
        if field == "job_name":
            execution.job_name = "wrong_parent"
        elif field == "idempotency_key_hash":
            execution.idempotency_key_hash = "wrong-idempotency"
        elif field == "data_source":
            execution.data_source = "other-source"
        elif field == "config_version":
            execution.config_version = "other-config"
        elif field == "window_start":
            execution.window_start = execution.window_start + timedelta(hours=1)
        elif field == "window_end":
            execution.window_end = execution.window_end - timedelta(hours=1)
        elif field == "target":
            metadata["target"] = "orders"
        elif field == "parent_targets":
            metadata["parent_targets"] = []
        elif field == "daily_targets":
            metadata["daily_targets"] = []
        elif field == "required_stages":
            metadata["required_stages"] = ["settle"]
        elif field == "timezone":
            metadata["timezone"] = "UTC"
        elif field == "source_window":
            metadata["source_window"] = {
                **metadata["source_window"],
                "timezone": "UTC",
            }
        execution.metadata_json = metadata
        child_id = children[0].job_id
    with t12_postgres_factory.begin() as session:
        assert claim_job(
            session,
            job_id=child_id,
            lease_owner=f"review-pg-parent-identity-{field}",
            component_instance_id=f"review-pg-parent-identity-{field}-component",
            lease_seconds=30,
        ) is None


def test_pending_parent_sync_identity_tamper_is_explicitly_blocked_sqlite(
    db_session: Session,
) -> None:
    _parent, execution, _children = _seed_planned_parent_range(
        db_session,
        start=date(1900, 1, 1),
        target="all",
    )
    execution.metadata_json = {
        **(execution.metadata_json or {}),
        "timezone": "UTC",
    }
    execution.status = "pending"
    db_session.commit()
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, future=True)
    with factory.begin() as session:
        assert claim_job(
            session,
            job_id=execution.job_id,
            lease_owner="review-pending-parent-tamper-owner",
            component_instance_id="review-pending-parent-tamper-component",
            lease_seconds=30,
        ) is None


def test_pending_parent_sync_identity_tamper_is_skipped_by_generic_postgres(
    t12_postgres_factory,
) -> None:
    suffix = str(time.time_ns())
    seed_session = t12_postgres_factory()
    try:
        _parent, execution, _children = _seed_planned_parent_range(
            seed_session,
            start=date(1800, 1, 1),
            target="all",
        )
        execution.metadata_json = {
            **(execution.metadata_json or {}),
            "timezone": "UTC",
        }
        execution.status = "pending"
        independent_plan = plan_daily_sync(
            seed_session,
            start=date(1800, 3, 1),
            end=date(1800, 3, 2),
            target="orders",
            requested_by="review",
            trigger_source="review",
            config_version=f"review-t22-pending-parent-independent-{suffix}",
        )
        independent_id = independent_plan.daily_jobs[0].job_id
        execution_id = execution.job_id
        seed_session.commit()
    finally:
        seed_session.close()

    with t12_postgres_factory.begin() as session:
        claimed = claim_next_job(
            session,
            lease_owner=f"review-pending-parent-generic-owner-{suffix}",
            component_instance_id=f"review-pending-parent-generic-component-{suffix}",
            lease_seconds=30,
        )
        assert claimed is not None and claimed.job_id == independent_id
        assert complete_job(session, claimed, success_count=0) is True

    with t12_postgres_factory.begin() as session:
        assert claim_job(
            session,
            job_id=execution_id,
            lease_owner=f"review-pending-parent-explicit-owner-{suffix}",
            component_instance_id=f"review-pending-parent-explicit-component-{suffix}",
            lease_seconds=30,
        ) is None


def test_mark_attempt_started_uses_postgres_clock_and_never_moves_heartbeat_back(
    t12_postgres_factory,
) -> None:
    suffix = str(time.time_ns())
    component_id = f"review-db-clock-component-{suffix}"
    seed_session = t12_postgres_factory()
    try:
        job = _seed_job(
            seed_session,
            f"review-db-clock-date-{suffix}",
            target="orders",
        )
        job_id = job.job_id
    finally:
        seed_session.close()
    with t12_postgres_factory.begin() as session:
        token = claim_job(
            session,
            job_id=job_id,
            lease_owner=f"review-db-clock-owner-{suffix}",
            component_instance_id=component_id,
            lease_seconds=30,
        )
        assert token is not None
    with t12_postgres_factory.begin() as session:
        session.execute(
            update(ComponentHeartbeat)
            .where(ComponentHeartbeat.component_instance_id == component_id)
            .values(
                last_heartbeat_at=text("clock_timestamp() + interval '1 hour'"),
                updated_at=text("clock_timestamp() + interval '1 hour'"),
            )
        )
    with t12_postgres_factory() as session:
        heartbeat_before = session.get(ComponentHeartbeat, component_id)
        assert heartbeat_before is not None
        heartbeat_floor = heartbeat_before.last_heartbeat_at
    supervisor = SubprocessSupervisor(control_session_factory=t12_postgres_factory)
    assert supervisor._mark_attempt_started(token, process_id=9191) is True
    with t12_postgres_factory() as session:
        attempt = session.get(JobAttempt, token.attempt_id)
        heartbeat_after = session.get(ComponentHeartbeat, component_id)
        assert attempt is not None and attempt.process_id == 9191
        assert heartbeat_after is not None
        assert heartbeat_after.last_heartbeat_at >= heartbeat_floor
        assert heartbeat_after.updated_at >= heartbeat_floor


def test_generic_claim_progresses_past_more_than_max_identity_mismatch_children_postgres(
    t12_postgres_factory,
) -> None:
    suffix = str(time.time_ns())
    seed_session = t12_postgres_factory()
    try:
        _parent, execution, blocked_children = _seed_planned_parent_range(
            seed_session,
            start=date(1900, 1, 1),
            days=40,
            target="all",
        )
        assert len(blocked_children) > 32
        for child in blocked_children:
            child.metadata_json = {
                **(child.metadata_json or {}),
                "required_stages": ["settle"],
            }
        blocked_id = blocked_children[0].job_id
        independent_plan = plan_daily_sync(
            seed_session,
            start="1900-03-01",
            end="1900-03-02",
            target="orders",
            requested_by="review",
            trigger_source="review",
            config_version=f"review-t22-independent-{suffix}",
        )
        independent_id = independent_plan.daily_jobs[0].job_id
        seed_session.commit()
    finally:
        seed_session.close()

    with t12_postgres_factory.begin() as session:
        claimed = claim_next_job(
            session,
            lease_owner=f"review-identity-scan-owner-{suffix}",
            component_instance_id=f"review-identity-scan-component-{suffix}",
            lease_seconds=30,
        )
        assert claimed is not None and claimed.job_id == independent_id
        assert complete_job(session, claimed, success_count=0) is True

    with t12_postgres_factory.begin() as session:
        assert claim_job(
            session,
            job_id=blocked_id,
            lease_owner=f"review-identity-scan-explicit-owner-{suffix}",
            component_instance_id=f"review-identity-scan-explicit-component-{suffix}",
            lease_seconds=30,
        ) is None


def test_parent_gate_missing_execution_is_fail_closed_in_sqlite(db_session: Session) -> None:
    _seed_parent_required_date_job(
        db_session,
        range_id="review-parent-gate-range-missing",
        job_id="review-parent-gate-date-missing",
        target="all",
    )
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, future=True)
    with factory.begin() as session:
        assert claim_job(
            session,
            job_id="review-parent-gate-date-missing",
            lease_owner="review-parent-gate-owner",
            component_instance_id="review-parent-gate-component",
            lease_seconds=30,
        ) is None


def test_parent_gate_success_unblocks_and_no_parent_target_is_unaffected_in_sqlite(
    db_session: Session,
) -> None:
    _parent, _execution, children = _seed_planned_parent_range(
        db_session,
        target="all",
    )
    date_id = children[0].job_id
    independent_job = _seed_job(
        db_session,
        "review-parent-gate-orders",
        target="orders",
        parent_job_id="review-no-parent-range",
    )
    independent_id = independent_job.job_id
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, future=True)
    with factory.begin() as session:
        unblocked = claim_job(
            session,
            job_id=date_id,
            lease_owner="review-parent-gate-owner",
            component_instance_id="review-parent-gate-component",
            lease_seconds=30,
        )
        assert unblocked is not None
        assert complete_job(session, unblocked, success_count=0) is True
        independent = claim_job(
            session,
            job_id=independent_id,
            lease_owner="review-parent-orders-owner",
            component_instance_id="review-parent-orders-component",
            lease_seconds=30,
        )
        assert independent is not None


def test_parent_gate_identity_mismatch_is_fail_closed_in_sqlite(
    db_session: Session,
) -> None:
    range_id, date_id, execution_id = _seed_parent_required_date_job(
        db_session,
        range_id="review-parent-gate-range-mismatch",
        job_id="review-parent-gate-date-mismatch",
        target="all",
        parent_status="success",
    )
    assert execution_id is not None
    parent = db_session.get(JobRun, execution_id)
    assert parent is not None
    parent.metadata_json = {
        **(parent.metadata_json or {}),
        "target": "shop_pois",
    }
    db_session.commit()
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, future=True)
    with factory.begin() as session:
        assert claim_job(
            session,
            job_id=date_id,
            lease_owner="review-parent-gate-mismatch-owner",
            component_instance_id="review-parent-gate-mismatch-component",
            lease_seconds=30,
        ) is None


def test_parent_gate_missing_execution_is_fail_closed_in_postgres(t12_postgres_factory) -> None:
    suffix = str(time.time_ns())
    seed_session = t12_postgres_factory()
    try:
        _range_id, date_id, _execution_id = _seed_parent_required_date_job(
            seed_session,
            range_id=f"review-parent-gate-pg-range-{suffix}",
            job_id=f"review-parent-gate-pg-date-{suffix}",
            target="all",
        )
    finally:
        seed_session.close()
    with t12_postgres_factory.begin() as session:
        assert claim_job(
            session,
            job_id=date_id,
            lease_owner="review-parent-gate-pg-owner",
            component_instance_id=f"review-parent-gate-pg-component-{suffix}",
            lease_seconds=30,
        ) is None


def test_parent_gate_identity_mismatch_is_fail_closed_in_postgres(
    t12_postgres_factory,
) -> None:
    suffix = str(time.time_ns())
    seed_session = t12_postgres_factory()
    try:
        _range_id, date_id, execution_id = _seed_parent_required_date_job(
            seed_session,
            range_id=f"review-parent-gate-pg-mismatch-range-{suffix}",
            job_id=f"review-parent-gate-pg-mismatch-date-{suffix}",
            target="all",
            parent_status="success",
        )
    finally:
        seed_session.close()
    with t12_postgres_factory.begin() as session:
        assert execution_id is not None
        parent = session.get(JobRun, execution_id)
        assert parent is not None
        parent.metadata_json = {
            **(parent.metadata_json or {}),
            "target": "shop_pois",
        }
    with t12_postgres_factory.begin() as session:
        assert claim_job(
            session,
            job_id=date_id,
            lease_owner=f"review-parent-gate-pg-mismatch-owner-{suffix}",
            component_instance_id=f"review-parent-gate-pg-mismatch-component-{suffix}",
            lease_seconds=30,
        ) is None


def test_parent_gate_success_unblocks_and_no_parent_target_is_unaffected_in_postgres(
    t12_postgres_factory,
) -> None:
    suffix = str(time.time_ns())
    with t12_postgres_factory.begin() as session:
        _parent, _execution, children = _seed_planned_parent_range(
            session,
            target="all",
        )
        date_id = children[0].job_id
        independent_plan = plan_daily_sync(
            session,
            start=date(2090, 1, 1),
            end=date(2090, 1, 2),
            target="orders",
            requested_by="review",
            trigger_source="review-test",
            config_version=f"review-parent-gate-pg-independent-{suffix}",
        )
        independent_id = independent_plan.daily_jobs[0].job_id
    with t12_postgres_factory() as session:
        unblocked = claim_job(
            session,
            job_id=date_id,
            lease_owner="review-parent-gate-pg-success-owner",
            component_instance_id=f"review-parent-gate-pg-success-component-{suffix}",
            lease_seconds=30,
        )
        assert unblocked is not None
        assert complete_job(session, unblocked, success_count=0) is True
        session.commit()
        independent = claim_job(
            session,
            job_id=independent_id,
            lease_owner="review-parent-gate-pg-independent-owner",
            component_instance_id=f"review-parent-gate-pg-independent-component-{suffix}",
            lease_seconds=30,
        )
        assert independent is not None


def test_generic_heavy_claim_skips_blocked_parent_gate_head_postgres(
    t12_postgres_factory,
) -> None:
    suffix = str(time.time_ns())
    blocked_id: str | None = None
    seed_session = t12_postgres_factory()
    try:
        blocked_count = 40
        for index in range(blocked_count):
            _range_id, child_id, _execution_id = _seed_parent_required_date_job(
                seed_session,
                range_id=f"review-generic-blocked-range-{suffix}-{index}",
                job_id=f"review-generic-blocked-date-{suffix}-{index}",
                target="all",
            )
            if index == 0:
                blocked_id = child_id
        independent_plan = plan_daily_sync(
            seed_session,
            start=date(2090, 2, 1),
            end=date(2090, 2, 2),
            target="orders",
            requested_by="review",
            trigger_source="review-test",
            config_version=f"review-generic-orders-{suffix}",
        )
        independent_id = independent_plan.daily_jobs[0].job_id
        seed_session.commit()
    finally:
        seed_session.close()

    with t12_postgres_factory.begin() as session:
        claimed = claim_next_job(
            session,
            lease_owner=f"review-generic-owner-{suffix}",
            component_instance_id=f"review-generic-component-{suffix}",
            lease_seconds=30,
        )
        assert claimed is not None
        assert claimed.job_id == independent_id
        assert claimed.job_id != blocked_id
        assert complete_job(session, claimed, success_count=0) is True

    with t12_postgres_factory.begin() as session:
        assert blocked_id is not None
        explicitly_blocked = claim_job(
            session,
            job_id=blocked_id,
            lease_owner=f"review-generic-explicit-owner-{suffix}",
            component_instance_id=f"review-generic-explicit-component-{suffix}",
            lease_seconds=30,
        )
        assert explicitly_blocked is None


def test_malformed_parent_targets_fail_closed_without_starving_independent_postgres(
    t12_postgres_factory,
) -> None:
    suffix = str(time.time_ns())
    seed_session = t12_postgres_factory()
    try:
        _blocked_range_id, blocked_id, _execution_id = _seed_parent_required_date_job(
            seed_session,
            range_id=f"review-malformed-parent-range-{suffix}",
            job_id=f"review-malformed-parent-date-{suffix}",
            target="all",
            parent_status="success",
        )
        blocked = seed_session.get(JobRun, blocked_id)
        assert blocked is not None
        blocked.metadata_json = {
            **(blocked.metadata_json or {}),
            "parent_targets": "corrupt-not-a-list",
        }
        independent_plan = plan_daily_sync(
            seed_session,
            start=date(2090, 3, 1),
            end=date(2090, 3, 2),
            target="orders",
            requested_by="review",
            trigger_source="review-test",
            config_version=f"review-malformed-orders-{suffix}",
        )
        independent_id = independent_plan.daily_jobs[0].job_id
        seed_session.commit()
    finally:
        seed_session.close()

    with t12_postgres_factory.begin() as session:
        claimed = claim_next_job(
            session,
            lease_owner=f"review-malformed-owner-{suffix}",
            component_instance_id=f"review-malformed-component-{suffix}",
            lease_seconds=30,
        )
        assert claimed is not None and claimed.job_id == independent_id
        assert complete_job(session, claimed, success_count=0) is True

    with t12_postgres_factory.begin() as session:
        assert claim_job(
            session,
            job_id=blocked_id,
            lease_owner=f"review-malformed-explicit-owner-{suffix}",
            component_instance_id=f"review-malformed-explicit-component-{suffix}",
            lease_seconds=30,
        ) is None


def test_mark_attempt_started_requires_current_fenced_identity_postgres(
    t12_postgres_factory,
) -> None:
    suffix = str(time.time_ns())
    component_id = f"review-mark-start-component-{suffix}"
    seed_session = t12_postgres_factory()
    try:
        job = _seed_job(seed_session, f"review-mark-start-date-{suffix}", target="orders")
        job_id = job.job_id
    finally:
        seed_session.close()
    with t12_postgres_factory.begin() as session:
        old_token = claim_job(
            session,
            job_id=job_id,
            lease_owner="review-old-owner",
            component_instance_id=component_id,
            lease_seconds=30,
        )
        assert old_token is not None
    with t12_postgres_factory.begin() as session:
        session.execute(
            update(JobRun)
            .where(JobRun.job_id == job_id)
            .values(lease_expires_at=text("clock_timestamp() - interval '1 second'"))
        )
    with t12_postgres_factory.begin() as session:
        new_token = claim_job(
            session,
            job_id=job_id,
            lease_owner="review-new-owner",
            component_instance_id=component_id,
            lease_seconds=30,
        )
        assert new_token is not None and new_token.lease_epoch > old_token.lease_epoch
    with t12_postgres_factory() as session:
        new_attempt_before = session.get(JobAttempt, new_token.attempt_id)
        heartbeat_before = session.get(ComponentHeartbeat, component_id)
        assert new_attempt_before is not None and heartbeat_before is not None
        new_attempt_snapshot = {
            "process_id": new_attempt_before.process_id,
            "finished_at": new_attempt_before.finished_at,
        }
        heartbeat_snapshot = {
            "last_heartbeat_at": heartbeat_before.last_heartbeat_at,
            "updated_at": heartbeat_before.updated_at,
            "current_job_id": heartbeat_before.current_job_id,
            "current_attempt_id": heartbeat_before.current_attempt_id,
            "status": heartbeat_before.status,
        }
    supervisor = SubprocessSupervisor(control_session_factory=t12_postgres_factory)
    assert supervisor._mark_attempt_started(old_token, process_id=111) is False
    with t12_postgres_factory() as session:
        old_attempt = session.get(JobAttempt, old_token.attempt_id)
        new_attempt_after = session.get(JobAttempt, new_token.attempt_id)
        heartbeat = session.get(ComponentHeartbeat, component_id)
        assert old_attempt is not None and old_attempt.process_id is None
        assert new_attempt_after is not None
        assert heartbeat is not None and heartbeat.current_attempt_id == new_token.attempt_id
        assert {
            "process_id": new_attempt_after.process_id,
            "finished_at": new_attempt_after.finished_at,
        } == new_attempt_snapshot
        assert {
            "last_heartbeat_at": heartbeat.last_heartbeat_at,
            "updated_at": heartbeat.updated_at,
            "current_job_id": heartbeat.current_job_id,
            "current_attempt_id": heartbeat.current_attempt_id,
            "status": heartbeat.status,
        } == heartbeat_snapshot
        heartbeat_at = heartbeat.last_heartbeat_at
    assert supervisor._mark_attempt_started(new_token, process_id=222) is True
    with t12_postgres_factory() as session:
        new_attempt = session.get(JobAttempt, new_token.attempt_id)
        heartbeat = session.get(ComponentHeartbeat, component_id)
        assert new_attempt is not None and new_attempt.process_id == 222
        assert heartbeat is not None and heartbeat.current_attempt_id == new_token.attempt_id
        assert heartbeat.last_heartbeat_at >= heartbeat_at


def test_scheduler_daily_child_timeout_defaults_and_is_explicitly_forwarded(monkeypatch) -> None:
    monkeypatch.delenv("WORKER_DAILY_CHILD_TIMEOUT_SECONDS", raising=False)
    assert scheduler._configured_daily_child_timeout_seconds() == 21600.0

    monkeypatch.setenv("WORKER_DAILY_CHILD_TIMEOUT_SECONDS", "42.5")
    assert scheduler._configured_daily_child_timeout_seconds() == 42.5

    class CaptureSupervisor:
        timeout_seconds = None

        def run(self, **kwargs):
            self.timeout_seconds = kwargs["timeout_seconds"]
            return scheduler.ChildRunResult(
                job_id=kwargs["job_id"] or "captured",
                status=ChildRunStatus.SUCCESS,
                attempts=1,
            )

    capture = CaptureSupervisor()
    scheduler.run_daily_child(object(), job_id="review-timeout-forward", supervisor=capture, max_attempts=1)
    assert capture.timeout_seconds == 42.5


@pytest.mark.parametrize("raw", ["", "invalid", "0", "-1", "nan", "inf"])
def test_scheduler_daily_child_timeout_invalid_values_fail_closed(monkeypatch, raw: str) -> None:
    monkeypatch.setenv("WORKER_DAILY_CHILD_TIMEOUT_SECONDS", raw)
    with pytest.raises(ValueError):
        scheduler._configured_daily_child_timeout_seconds()


def test_hung_child_timeout_records_worker_timeout_and_releases_heavy_slot(
    db_session: Session,
) -> None:
    hung_job = _seed_job(
        db_session,
        "review-hung-timeout",
        target="orders",
        max_attempts=1,
    )
    after_job = _seed_job(
        db_session,
        "review-after-timeout",
        target="orders",
        max_attempts=1,
        business_date=date(2026, 8, 6),
    )
    hung_id = hung_job.job_id
    after_id = after_job.job_id
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, future=True)
    supervisor = SubprocessSupervisor(
        control_session_factory=factory,
        popen_factory=lambda *_args, **_kwargs: FakeProcess(0, delay=1.0),
        rss_reader=lambda _pid: 99,
        poll_interval_seconds=0.001,
        heartbeat_interval_seconds=0.001,
        lease_seconds=10,
    )
    result = supervisor.run(
        job_id=hung_id,
        command=["python", "-m", "apps.worker.daily_task"],
        max_attempts=1,
        timeout_seconds=0.02,
    )
    assert result.status is ChildRunStatus.TIMEOUT
    assert result.heartbeat_seen is True
    with factory.begin() as session:
        attempt = session.scalar(
            select(JobAttempt).where(JobAttempt.job_id == hung_id)
        )
        component = session.scalar(
            select(ComponentHeartbeat).where(
                ComponentHeartbeat.current_job_id == hung_id
            )
        )
        assert attempt is not None and attempt.error_code == "worker_timeout"
        assert component is None
        assert session.scalar(select(JobRun.status).where(JobRun.job_id == hung_id)) == "failed"
        next_token = claim_job(
            session,
            job_id=after_id,
            lease_owner="review-after-timeout-owner",
            component_instance_id="review-after-timeout-component",
            lease_seconds=30,
        )
        assert next_token is not None


@pytest.mark.parametrize(
    ("stage_statuses", "expected_calls"),
    [
        ({"collect": "success", "materialize": "pending", "settle": "success"}, ["materialize"]),
        ({"collect": "success", "materialize": "failed", "settle": "pending"}, ["materialize", "settle"]),
        ({}, ["collect", "materialize", "settle"]),
    ],
)
def test_checkpoint_scan_ignores_ahead_current_stage_pointer(
    db_session: Session,
    stage_statuses: dict[str, str],
    expected_calls: list[str],
) -> None:
    job_id = f"review-checkpoint-pointer-{time.time_ns()}"
    job = _seed_job(
        db_session,
        job_id,
        current_stage="settle",
        required_stages=("collect", "materialize", "settle"),
    )
    job_id = job.job_id
    now = datetime.now(UTC)
    for stage_name, status in stage_statuses.items():
        db_session.add(
            JobStageRun(
                stage_run_id=f"stage-{job_id}-{stage_name}",
                job_id=job_id,
                stage_name=stage_name,
                status=status,
                checkpoint_json={"status": status, "stage": stage_name},
                lease_epoch=0,
                started_at=now,
                finished_at=now if status in {"success", "failed"} else None,
                committed_at=now if status == "success" else None,
                created_at=now,
                updated_at=now,
            )
        )
    db_session.commit()
    calls: list[str] = []
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, future=True)
    handlers = {
        stage_name: (lambda _session, _job, stage_name=stage_name: calls.append(stage_name))
        for stage_name in ("collect", "materialize", "settle")
    }
    run_daily_stages(
        factory,
        job_id=job_id,
        handlers=handlers,
        stage_order=("collect", "materialize", "settle"),
    )
    assert calls == expected_calls


def _seed_expired_invalid_running_pair(
    factory: sessionmaker[Session],
    suffix: str,
    *,
    tamper_identity: bool = True,
    expire_lease: bool = True,
) -> tuple[str, str, object, str]:
    seed_session = factory()
    try:
        head = _seed_job(
            seed_session,
            f"review-quarantine-head-{suffix}",
            target="orders",
            business_date=date(1900, 1, 1),
        )
        tail = _seed_job(
            seed_session,
            f"review-quarantine-tail-{suffix}",
            target="orders",
            business_date=date(1900, 1, 2),
        )
        head_id = head.job_id
        tail_id = tail.job_id
    finally:
        seed_session.close()

    component_id = f"review-quarantine-head-component-{suffix}"
    with factory.begin() as session:
        old_token = claim_job(
            session,
            job_id=head_id,
            lease_owner=f"review-quarantine-old-owner-{suffix}",
            component_instance_id=component_id,
            lease_seconds=30,
        )
        assert old_token is not None

    with factory.begin() as session:
        head_row = session.get(JobRun, head_id)
        assert head_row is not None
        if tamper_identity:
            head_row.metadata_json = {
                **(head_row.metadata_json or {}),
                "target": "settlement",
            }
        if expire_lease:
            head_row.lease_expires_at = text(
                "clock_timestamp() - interval '1 second'"
            )

    return head_id, tail_id, old_token, component_id


def _quarantine_control_snapshot(
    factory: sessionmaker[Session],
    *,
    job_ids: tuple[str, ...],
    component_ids: tuple[str, ...],
) -> tuple[tuple[object, ...], ...]:
    with factory() as session:
        jobs = tuple(
            session.execute(
                select(
                    JobRun.job_id,
                    JobRun.status,
                    JobRun.error_code,
                    JobRun.error_summary,
                    JobRun.lease_owner,
                    JobRun.lease_epoch,
                    JobRun.lease_expires_at,
                    JobRun.attempt_count,
                )
                .where(JobRun.job_id.in_(job_ids))
                .order_by(JobRun.job_id)
            ).all()
        )
        attempts = tuple(
            session.execute(
                select(
                    JobAttempt.attempt_id,
                    JobAttempt.job_id,
                    JobAttempt.lease_epoch,
                    JobAttempt.finished_at,
                    JobAttempt.exit_type,
                    JobAttempt.error_code,
                    JobAttempt.error_summary,
                )
                .where(JobAttempt.job_id.in_(job_ids))
                .order_by(JobAttempt.attempt_id)
            ).all()
        )
        events = tuple(
            session.execute(
                select(
                    JobEvent.event_id,
                    JobEvent.job_id,
                    JobEvent.attempt_id,
                    JobEvent.event_type,
                    JobEvent.from_status,
                    JobEvent.to_status,
                    JobEvent.reason,
                    JobEvent.payload_json,
                )
                .where(JobEvent.job_id.in_(job_ids))
                .order_by(JobEvent.event_id)
            ).all()
        )
        components = tuple(
            session.execute(
                select(
                    ComponentHeartbeat.component_instance_id,
                    ComponentHeartbeat.component_type,
                    ComponentHeartbeat.status,
                    ComponentHeartbeat.current_job_id,
                    ComponentHeartbeat.current_attempt_id,
                )
                .where(ComponentHeartbeat.component_instance_id.in_(component_ids))
                .order_by(ComponentHeartbeat.component_instance_id)
            ).all()
        )
    return jobs, attempts, events, components


def test_postgres_expired_invalid_running_head_is_quarantined_and_tail_claimed(
    t12_postgres_factory,
) -> None:
    suffix = str(time.time_ns())
    factory = t12_postgres_factory
    head_id, tail_id, _old_token, _component_id = _seed_expired_invalid_running_pair(
        factory, suffix
    )

    with factory.begin() as session:
        tail_token = claim_next_job(
            session,
            lease_owner=f"review-quarantine-tail-owner-{suffix}",
            component_instance_id=f"review-quarantine-tail-component-{suffix}",
            lease_seconds=30,
        )
        assert tail_token is not None and tail_token.job_id == tail_id
        assert complete_job(session, tail_token, success_count=0) is True

    with factory() as session:
        head = session.get(JobRun, head_id)
        assert head is not None
        assert head.status == "failed"
        assert head.error_code == "control_plane_identity_invalid"
        attempt = session.scalar(select(JobAttempt).where(JobAttempt.job_id == head_id))
        assert attempt is not None and attempt.finished_at is not None
        event = session.scalar(
            select(JobEvent).where(
                JobEvent.job_id == head_id,
                JobEvent.event_type == "job_quarantined",
            )
        )
        assert event is not None and event.to_status == "failed"


def test_postgres_quarantine_fences_all_old_token_writes(
    t12_postgres_factory,
) -> None:
    suffix = str(time.time_ns())
    factory = t12_postgres_factory
    head_id, tail_id, old_token, _component_id = _seed_expired_invalid_running_pair(
        factory, suffix
    )
    with factory.begin() as session:
        tail_token = claim_next_job(
            session,
            lease_owner=f"review-quarantine-fence-tail-owner-{suffix}",
            component_instance_id=f"review-quarantine-fence-tail-component-{suffix}",
            lease_seconds=30,
        )
        assert tail_token is not None and tail_token.job_id == tail_id
        assert complete_job(session, tail_token, success_count=0) is True
        assert heartbeat_job(session, old_token, lease_seconds=30) is False
        assert complete_job(session, old_token, success_count=1) is False
        assert (
            fail_job(
                session,
                old_token,
                failure_kind=FailureKind.TRANSIENT,
                error_code="stale",
                error_summary="stale token",
            )
            is None
        )
        assert confirm_cancel_job(session, old_token, reason="stale token") is False

    supervisor = SubprocessSupervisor(control_session_factory=factory)
    assert supervisor._mark_attempt_started(old_token, process_id=991) is False
    with factory() as session:
        head = session.get(JobRun, head_id)
        assert head is not None and head.status == "failed"


def test_postgres_explicit_invalid_expired_claim_maps_to_failed_not_busy(
    t12_postgres_factory,
) -> None:
    suffix = str(time.time_ns())
    factory = t12_postgres_factory
    head_id, _tail_id, _old_token, _component_id = _seed_expired_invalid_running_pair(
        factory, suffix
    )
    supervisor = SubprocessSupervisor(control_session_factory=factory)
    result = supervisor.run(
        job_id=head_id,
        command=["not-started"],
        max_attempts=1,
    )
    assert result.status is ChildRunStatus.FAILED
    with factory() as session:
        head = session.get(JobRun, head_id)
        assert head is not None and head.status == "failed"


def test_postgres_missing_attempt_quarantine_releases_slot_and_audits(
    t12_postgres_factory,
) -> None:
    suffix = str(time.time_ns())
    factory = t12_postgres_factory
    head_id, tail_id, _old_token, component_id = _seed_expired_invalid_running_pair(
        factory, suffix
    )
    with factory.begin() as session:
        session.execute(
            update(ComponentHeartbeat)
            .where(ComponentHeartbeat.component_instance_id == component_id)
            .values(current_job_id=None, current_attempt_id=None)
        )
        session.execute(
            update(JobEvent)
            .where(JobEvent.job_id == head_id)
            .values(attempt_id=None)
        )
        session.execute(delete(JobAttempt).where(JobAttempt.job_id == head_id))

    with factory.begin() as session:
        tail_token = claim_next_job(
            session,
            lease_owner=f"review-quarantine-missing-tail-owner-{suffix}",
            component_instance_id=f"review-quarantine-missing-tail-component-{suffix}",
            lease_seconds=30,
        )
        assert tail_token is not None and tail_token.job_id == tail_id
        assert complete_job(session, tail_token, success_count=0) is True

    with factory() as session:
        head = session.get(JobRun, head_id)
        assert head is not None and head.status == "failed"
        assert session.scalar(
            select(JobEvent.attempt_id).where(
                JobEvent.job_id == head_id,
                JobEvent.event_type == "job_quarantined",
            )
        ) is None


def test_postgres_inconsistent_binding_quarantine_does_not_release_unrelated_component(
    t12_postgres_factory,
) -> None:
    suffix = str(time.time_ns())
    factory = t12_postgres_factory
    head_id, tail_id, _old_token, component_id = _seed_expired_invalid_running_pair(
        factory, suffix
    )
    unrelated_id = f"review-quarantine-unrelated-{suffix}"
    with factory.begin() as session:
        session.add(
            JobRun(
                job_id=unrelated_id,
                job_name="product_sync",
                job_kind="product_sync",
                status="pending",
                started_at=datetime.now(UTC),
                metadata_json={},
            )
        )
        session.flush()
        session.execute(
            update(ComponentHeartbeat)
            .where(ComponentHeartbeat.component_instance_id == component_id)
            .values(current_job_id=unrelated_id, current_attempt_id=None)
        )

    with factory.begin() as session:
        tail_token = claim_next_job(
            session,
            lease_owner=f"review-quarantine-binding-tail-owner-{suffix}",
            component_instance_id=f"review-quarantine-binding-tail-component-{suffix}",
            lease_seconds=30,
        )
        assert tail_token is not None and tail_token.job_id == tail_id
        assert complete_job(session, tail_token, success_count=0) is True

    with factory() as session:
        head = session.get(JobRun, head_id)
        assert head is not None and head.status == "failed"
        component = session.get(ComponentHeartbeat, component_id)
        assert component is not None
        assert component.current_job_id == unrelated_id
        assert component.current_attempt_id is None


def test_postgres_quarantine_post_write_failure_rolls_back_savepoint(
    t12_postgres_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = str(time.time_ns())
    factory = t12_postgres_factory
    head_id, tail_id, _old_token, component_id = _seed_expired_invalid_running_pair(
        factory, suffix
    )
    before = _quarantine_control_snapshot(
        factory,
        job_ids=(head_id, tail_id),
        component_ids=(component_id,),
    )

    def injected_event_failure(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("injected quarantine event failure")

    monkeypatch.setattr(repositories, "_add_job_event", injected_event_failure)
    with factory.begin() as session:
        caught = False
        try:
            claim_next_job(
                session,
                lease_owner=f"review-quarantine-failure-owner-{suffix}",
                component_instance_id=f"review-quarantine-failure-component-{suffix}",
                lease_seconds=30,
            )
        except RuntimeError as exc:
            caught = "injected quarantine event failure" in str(exc)
        assert caught is True

    after = _quarantine_control_snapshot(
        factory,
        job_ids=(head_id, tail_id),
        component_ids=(component_id,),
    )
    assert after == before


def test_postgres_unexpired_invalid_running_job_remains_busy_not_quarantined(
    t12_postgres_factory,
) -> None:
    suffix = str(time.time_ns())
    factory = t12_postgres_factory
    head_id, tail_id, _old_token, _component_id = _seed_expired_invalid_running_pair(
        factory, suffix
    )
    with factory.begin() as session:
        session.execute(
            update(JobRun)
            .where(JobRun.job_id == head_id)
            .values(lease_expires_at=text("clock_timestamp() + interval '1 hour'"))
        )
        assert (
            claim_next_job(
                session,
                lease_owner=f"review-quarantine-unexpired-owner-{suffix}",
                component_instance_id=f"review-quarantine-unexpired-component-{suffix}",
                lease_seconds=30,
            )
            is None
        )

    with factory() as session:
        head = session.get(JobRun, head_id)
        tail = session.get(JobRun, tail_id)
        assert head is not None and head.status == "running"
        assert head.error_code is None
        assert tail is not None and tail.status == "pending"


def test_postgres_valid_expired_running_job_is_taken_over_normally(
    t12_postgres_factory,
) -> None:
    suffix = str(time.time_ns())
    factory = t12_postgres_factory
    head_id, _tail_id, old_token, _component_id = _seed_expired_invalid_running_pair(
        factory, suffix, tamper_identity=False
    )
    with factory.begin() as session:
        new_token = claim_job(
            session,
            job_id=head_id,
            lease_owner=f"review-quarantine-takeover-owner-{suffix}",
            component_instance_id=f"review-quarantine-takeover-component-{suffix}",
            lease_seconds=30,
        )
        assert new_token is not None
        assert new_token.lease_epoch == old_token.lease_epoch + 1

    with factory() as session:
        old_attempt = session.get(JobAttempt, old_token.attempt_id)
        assert old_attempt is not None and old_attempt.finished_at is not None
        head = session.get(JobRun, head_id)
        assert head is not None and head.status == "running"


def test_postgres_repeated_generic_claim_leaves_no_heavy_slot_residue(
    t12_postgres_factory,
) -> None:
    suffix = str(time.time_ns())
    factory = t12_postgres_factory
    head_id, tail_id, _old_token, _component_id = _seed_expired_invalid_running_pair(
        factory, suffix
    )
    with factory.begin() as session:
        token = claim_next_job(
            session,
            lease_owner=f"review-quarantine-repeat-owner-{suffix}",
            component_instance_id=f"review-quarantine-repeat-component-{suffix}",
            lease_seconds=30,
        )
        assert token is not None and token.job_id == tail_id
        assert complete_job(session, token, success_count=0) is True

    with factory.begin() as session:
        assert (
            claim_next_job(
                session,
                lease_owner=f"review-quarantine-repeat-owner-2-{suffix}",
                component_instance_id=f"review-quarantine-repeat-component-2-{suffix}",
                lease_seconds=30,
            )
            is None
        )
        assert session.scalar(
            select(JobRun.status).where(JobRun.job_id == head_id)
        ) == "failed"
        assert session.scalar(
            select(JobRun.status).where(JobRun.job_id == tail_id)
        ) == "success"
        assert session.scalar(
            select(JobRun.job_id).where(
                JobRun.execution_slot == "heavy_sync",
                JobRun.status == "running",
            )
        ) is None


def test_postgres_explicit_tail_cannot_bypass_expired_running_slot(
    t12_postgres_factory,
) -> None:
    suffix = str(time.time_ns())
    factory = t12_postgres_factory
    head_id, tail_id, _old_token, _component_id = _seed_expired_invalid_running_pair(
        factory,
        suffix,
    )

    with factory.begin() as session:
        assert (
            claim_job(
                session,
                job_id=tail_id,
                lease_owner=f"review-explicit-tail-bypass-owner-{suffix}",
                component_instance_id=f"review-explicit-tail-bypass-component-{suffix}",
                lease_seconds=30,
            )
            is None
        )

    with factory.begin() as session:
        token = claim_next_job(
            session,
            lease_owner=f"review-explicit-tail-after-quarantine-owner-{suffix}",
            component_instance_id=f"review-explicit-tail-after-quarantine-component-{suffix}",
            lease_seconds=30,
        )
        assert token is not None and token.job_id == tail_id
        assert complete_job(session, token, success_count=0) is True

    with factory() as session:
        head = session.get(JobRun, head_id)
        assert head is not None and head.status == "failed"


@pytest.mark.parametrize("status", ["pending", "retry_wait"])
def test_postgres_pending_negative_epoch_generic_quarantines_and_continues(
    t12_postgres_factory,
    status: str,
) -> None:
    suffix = str(time.time_ns())
    factory = t12_postgres_factory
    seed_session = factory()
    try:
        head = _seed_job(
            seed_session,
            f"review-negative-epoch-head-{suffix}",
            target="orders",
            business_date=date(1900, 1, 1),
        )
        tail = _seed_job(
            seed_session,
            f"review-negative-epoch-tail-{suffix}",
            target="orders",
            business_date=date(1900, 1, 2),
        )
        head_id, tail_id = head.job_id, tail.job_id
        seed_session.commit()
    finally:
        seed_session.close()

    with factory.begin() as session:
        session.execute(
            update(JobRun)
            .where(JobRun.job_id == head_id)
            .values(
                lease_epoch=-1,
                status=status,
                next_retry_at=(
                    text("clock_timestamp() - interval '1 second'")
                    if status == "retry_wait"
                    else None
                ),
            )
        )

    with factory.begin() as session:
        token = claim_next_job(
            session,
            lease_owner=f"review-negative-epoch-generic-owner-{suffix}",
            component_instance_id=f"review-negative-epoch-generic-component-{suffix}",
            lease_seconds=30,
        )
        assert token is not None and token.job_id == tail_id
        assert complete_job(session, token, success_count=0) is True

    with factory() as session:
        head_row = session.get(JobRun, head_id)
        assert head_row is not None and head_row.status == "failed"
        event = session.scalar(
            select(JobEvent).where(
                JobEvent.job_id == head_id,
                JobEvent.event_type == "job_quarantined",
            )
        )
        assert event is not None and event.from_status == status
        assert set((event.payload_json or {}).get("control_state_reasons", [])) >= {
            "lease_owner_missing",
            "lease_epoch_invalid",
            "unfinished_attempt_missing",
            "current_token_attempt_missing",
        }


def test_postgres_pending_negative_epoch_explicit_claim_reports_failed(
    t12_postgres_factory,
) -> None:
    suffix = str(time.time_ns())
    factory = t12_postgres_factory
    seed_session = factory()
    try:
        head = _seed_job(
            seed_session,
            f"review-negative-epoch-explicit-{suffix}",
            target="orders",
            business_date=date(1900, 1, 1),
        )
        head_id = head.job_id
        seed_session.commit()
    finally:
        seed_session.close()

    with factory.begin() as session:
        session.execute(
            update(JobRun)
            .where(JobRun.job_id == head_id)
            .values(lease_epoch=-1)
        )

    supervisor = SubprocessSupervisor(control_session_factory=factory)
    result = supervisor.run(
        job_id=head_id,
        command=["not-started"],
        max_attempts=1,
    )
    assert result.status is ChildRunStatus.FAILED


def test_postgres_expired_current_attempt_counter_anomaly_quarantines_and_fences_old_token(
    t12_postgres_factory,
) -> None:
    suffix = str(time.time_ns())
    factory = t12_postgres_factory
    head_id, tail_id, old_token, _component_id = _seed_expired_invalid_running_pair(
        factory,
        suffix,
        tamper_identity=False,
    )
    with factory.begin() as session:
        session.execute(
            update(JobRun)
            .where(JobRun.job_id == head_id)
            .values(attempt_count=0)
        )

    with factory.begin() as session:
        tail_token = claim_next_job(
            session,
            lease_owner=f"review-counter-current-tail-owner-{suffix}",
            component_instance_id=f"review-counter-current-tail-component-{suffix}",
            lease_seconds=30,
        )
        assert tail_token is not None and tail_token.job_id == tail_id
        assert complete_job(session, tail_token, success_count=0) is True
        assert heartbeat_job(session, old_token, lease_seconds=30) is False
        assert complete_job(session, old_token, success_count=1) is False

    with factory() as session:
        head = session.get(JobRun, head_id)
        assert head is not None and head.status == "failed"
        event = session.scalar(
            select(JobEvent).where(
                JobEvent.job_id == head_id,
                JobEvent.event_type == "job_quarantined",
            )
        )
        assert event is not None
        payload = event.payload_json or {}
        assert payload.get("counter_anomaly") is True
        assert payload.get("observed_attempt_count") == 1
        assert payload.get("observed_max_lease_epoch") == old_token.lease_epoch


def test_postgres_expired_counter_anomaly_explicit_claim_reports_failed(
    t12_postgres_factory,
) -> None:
    suffix = str(time.time_ns())
    factory = t12_postgres_factory
    head_id, _tail_id, _old_token, _component_id = _seed_expired_invalid_running_pair(
        factory,
        suffix,
        tamper_identity=False,
    )
    with factory.begin() as session:
        session.execute(
            update(JobRun)
            .where(JobRun.job_id == head_id)
            .values(attempt_count=0)
        )

    supervisor = SubprocessSupervisor(control_session_factory=factory)
    result = supervisor.run(
        job_id=head_id,
        command=["not-started"],
        max_attempts=1,
    )
    assert result.status is ChildRunStatus.FAILED


def test_postgres_expired_history_counter_anomaly_quarantines_without_duplicate_attempt(
    t12_postgres_factory,
) -> None:
    suffix = str(time.time_ns())
    factory = t12_postgres_factory
    head_id, tail_id, old_token, component_one = _seed_expired_invalid_running_pair(
        factory,
        suffix,
        tamper_identity=False,
    )
    with factory.begin() as session:
        old_attempt = session.get(JobAttempt, old_token.attempt_id)
        assert old_attempt is not None
        old_attempt.finished_at = old_attempt.started_at
        old_attempt.exit_type = "crashed"
        old_attempt.error_code = "lease_expired"
        session.execute(
            update(ComponentHeartbeat)
            .where(ComponentHeartbeat.component_instance_id == component_one)
            .values(current_job_id=None, current_attempt_id=None)
        )

    attempt_two, _component_two = _add_unfinished_attempt_for_review(
        factory,
        job_id=head_id,
        attempt_number=2,
        lease_epoch=2,
        component_id=f"review-history-counter-component-{suffix}",
    )
    with factory.begin() as session:
        session.execute(
            update(JobAttempt)
            .where(JobAttempt.attempt_id == old_token.attempt_id)
            .values(attempt_number=3, lease_epoch=3)
        )

    with factory.begin() as session:
        tail_token = claim_next_job(
            session,
            lease_owner=f"review-history-counter-tail-owner-{suffix}",
            component_instance_id=f"review-history-counter-tail-component-{suffix}",
            lease_seconds=30,
        )
        assert tail_token is not None and tail_token.job_id == tail_id
        assert complete_job(session, tail_token, success_count=0) is True

    with factory() as session:
        attempts = list(
            session.scalars(select(JobAttempt).where(JobAttempt.job_id == head_id))
        )
        assert {attempt.attempt_id for attempt in attempts} >= {
            old_token.attempt_id,
            attempt_two,
        }
        assert all(attempt.finished_at is not None for attempt in attempts)
        event = session.scalar(
            select(JobEvent).where(
                JobEvent.job_id == head_id,
                JobEvent.event_type == "job_quarantined",
            )
        )
        assert event is not None
        payload = event.payload_json or {}
        assert payload.get("history_anomaly") is True
        assert payload.get("observed_attempt_count") == 2
        assert payload.get("observed_max_attempt_number") == 3
        assert payload.get("observed_max_lease_epoch") == 3


@pytest.mark.parametrize("status", ["pending", "retry_wait"])
def test_postgres_pending_history_counter_anomaly_quarantines_and_continues(
    t12_postgres_factory,
    status: str,
) -> None:
    suffix = str(time.time_ns())
    factory = t12_postgres_factory
    seed_session = factory()
    try:
        head = _seed_job(
            seed_session,
            f"review-pending-history-head-{suffix}",
            target="orders",
            business_date=date(1900, 1, 1),
        )
        tail = _seed_job(
            seed_session,
            f"review-pending-history-tail-{suffix}",
            target="orders",
            business_date=date(1900, 1, 2),
        )
        head_id, tail_id = head.job_id, tail.job_id
        seed_session.commit()
    finally:
        seed_session.close()

    component_id = f"review-pending-history-component-{suffix}"
    now = datetime.now(UTC)
    with factory.begin() as session:
        session.add(
            ComponentHeartbeat(
                component_instance_id=component_id,
                component_type="worker",
                status="degraded",
                started_at=now,
                last_heartbeat_at=now,
                activity_json={},
                queue_summary_json={},
                created_at=now,
                updated_at=now,
            )
        )
        session.flush()
        session.add(
            JobAttempt(
                attempt_id=f"review-pending-history-attempt-{suffix}",
                job_id=head_id,
                stage_run_id=None,
                attempt_number=1,
                lease_epoch=1,
                component_type="worker",
                component_instance_id=component_id,
                started_at=now,
                finished_at=now,
                exit_type="success",
                created_at=now,
            )
        )
        session.flush()
        session.execute(
            update(JobRun)
            .where(JobRun.job_id == head_id)
            .values(
                status=status,
                attempt_count=0,
                lease_epoch=0,
                next_retry_at=(
                    text("clock_timestamp() - interval '1 second'")
                    if status == "retry_wait"
                    else None
                ),
            )
        )

    with factory.begin() as session:
        tail_token = claim_next_job(
            session,
            lease_owner=f"review-pending-history-tail-owner-{suffix}",
            component_instance_id=f"review-pending-history-tail-component-{suffix}",
            lease_seconds=30,
        )
        assert tail_token is not None and tail_token.job_id == tail_id
        assert complete_job(session, tail_token, success_count=0) is True

    with factory() as session:
        head_row = session.get(JobRun, head_id)
        assert head_row is not None and head_row.status == "failed"
        event = session.scalar(
            select(JobEvent).where(
                JobEvent.job_id == head_id,
                JobEvent.event_type == "job_quarantined",
            )
        )
        assert event is not None and event.from_status == status
        assert (event.payload_json or {}).get("history_anomaly") is True


@pytest.mark.parametrize("status", ["pending", "retry_wait"])
def test_postgres_pending_residual_unfinished_attempt_quarantines_and_continues(
    t12_postgres_factory,
    status: str,
) -> None:
    suffix = str(time.time_ns())
    factory = t12_postgres_factory
    head_id, tail_id, _old_token, _component_id = _seed_expired_invalid_running_pair(
        factory,
        suffix,
        tamper_identity=False,
        expire_lease=False,
    )
    with factory.begin() as session:
        session.execute(
            update(JobRun)
            .where(JobRun.job_id == head_id)
            .values(
                status=status,
                lease_expires_at=None,
                next_retry_at=(
                    text("clock_timestamp() - interval '1 second'")
                    if status == "retry_wait"
                    else None
                ),
            )
        )

    with factory.begin() as session:
        tail_token = claim_next_job(
            session,
            lease_owner=f"review-pending-residual-tail-owner-{suffix}",
            component_instance_id=f"review-pending-residual-tail-component-{suffix}",
            lease_seconds=30,
        )
        assert tail_token is not None and tail_token.job_id == tail_id
        assert complete_job(session, tail_token, success_count=0) is True

    with factory() as session:
        head_row = session.get(JobRun, head_id)
        assert head_row is not None and head_row.status == "failed"
        event = session.scalar(
            select(JobEvent).where(
                JobEvent.job_id == head_id,
                JobEvent.event_type == "job_quarantined",
            )
        )
        assert event is not None and event.from_status == status
        assert "unfinished_attempt_unexpected" in (event.payload_json or {}).get(
            "control_state_reasons", []
        )


def test_postgres_expired_browser_attempt_quarantines_instead_of_takeover(
    t12_postgres_factory,
) -> None:
    suffix = str(time.time_ns())
    factory = t12_postgres_factory
    head_id, tail_id, old_token, worker_component = _seed_expired_invalid_running_pair(
        factory,
        suffix,
        tamper_identity=False,
    )
    browser_component = f"review-browser-attempt-component-{suffix}"
    now = datetime.now(UTC)
    with factory.begin() as session:
        worker = session.get(ComponentHeartbeat, worker_component)
        assert worker is not None
        worker.current_job_id = None
        worker.current_attempt_id = None
        session.add(
            ComponentHeartbeat(
                component_instance_id=browser_component,
                component_type="browser",
                status="healthy",
                started_at=now,
                last_heartbeat_at=now,
                activity_json={},
                queue_summary_json={},
                created_at=now,
                updated_at=now,
            )
        )
        session.flush()
        session.execute(
            update(JobAttempt)
            .where(JobAttempt.attempt_id == old_token.attempt_id)
            .values(component_instance_id=browser_component, component_type="browser")
        )
        session.flush()
        session.execute(
            update(ComponentHeartbeat)
            .where(
                ComponentHeartbeat.component_instance_id == browser_component,
                ComponentHeartbeat.component_type == "browser",
            )
            .values(current_job_id=head_id, current_attempt_id=old_token.attempt_id)
        )

    with factory.begin() as session:
        tail_token = claim_next_job(
            session,
            lease_owner=f"review-browser-attempt-tail-owner-{suffix}",
            component_instance_id=f"review-browser-attempt-tail-component-{suffix}",
            lease_seconds=30,
        )
        assert tail_token is not None and tail_token.job_id == tail_id
        assert complete_job(session, tail_token, success_count=0) is True

    with factory() as session:
        head = session.get(JobRun, head_id)
        browser = session.get(ComponentHeartbeat, browser_component)
        assert head is not None and head.status == "failed"
        assert browser is not None
        assert browser.current_job_id is None
        assert browser.current_attempt_id is None
        event = session.scalar(
            select(JobEvent).where(
                JobEvent.job_id == head_id,
                JobEvent.event_type == "job_quarantined",
            )
        )
        assert event is not None
        assert "component_type_invalid" in (event.payload_json or {}).get(
            "control_state_reasons", []
        )


def test_postgres_expired_more_than_bounded_attempt_history_closes_every_unfinished(
    t12_postgres_factory,
) -> None:
    suffix = str(time.time_ns())
    factory = t12_postgres_factory
    head_id, tail_id, old_token, component_one = _seed_expired_invalid_running_pair(
        factory,
        suffix,
        tamper_identity=False,
    )
    component_ids = [component_one]
    for attempt_number in (2, 3):
        _attempt_id, component_id = _add_unfinished_attempt_for_review(
            factory,
            job_id=head_id,
            attempt_number=attempt_number,
            lease_epoch=attempt_number,
            component_id=f"review-history-overflow-component-{suffix}-{attempt_number}",
        )
        component_ids.append(component_id)
    for attempt_number in (4, 5):
        component_id = _add_overflow_unfinished_attempt_for_review(
            factory,
            job_id=head_id,
            attempt_number=attempt_number,
            lease_epoch=attempt_number,
            component_id=f"review-history-overflow-component-{suffix}-{attempt_number}",
        )
        component_ids.append(component_id)

    with factory.begin() as session:
        tail_token = claim_next_job(
            session,
            lease_owner=f"review-history-overflow-tail-owner-{suffix}",
            component_instance_id=f"review-history-overflow-tail-component-{suffix}",
            lease_seconds=30,
        )
        assert tail_token is not None and tail_token.job_id == tail_id
        assert complete_job(session, tail_token, success_count=0) is True

    with factory() as session:
        attempts = list(
            session.scalars(select(JobAttempt).where(JobAttempt.job_id == head_id))
        )
        assert len(attempts) == 5
        assert all(attempt.finished_at is not None for attempt in attempts)
        for component_id in component_ids:
            component = session.scalar(
                select(ComponentHeartbeat).where(
                    ComponentHeartbeat.component_instance_id == component_id,
                    ComponentHeartbeat.component_type == "worker",
                )
            )
            assert component is not None
            assert component.current_job_id is None
            assert component.current_attempt_id is None
        event = session.scalar(
            select(JobEvent).where(
                JobEvent.job_id == head_id,
                JobEvent.event_type == "job_quarantined",
            )
        )
        assert event is not None
        assert (event.payload_json or {}).get("closed_attempt_count") == 5


@pytest.mark.parametrize("status", ["pending", "retry_wait"])
def test_postgres_non_running_stale_active_lease_fields_quarantine_and_continue(
    t12_postgres_factory,
    status: str,
) -> None:
    suffix = str(time.time_ns())
    factory = t12_postgres_factory
    seed_session = factory()
    try:
        head = _seed_job(
            seed_session,
            f"review-stale-active-head-{suffix}",
            target="orders",
            business_date=date(1900, 1, 1),
        )
        tail = _seed_job(
            seed_session,
            f"review-stale-active-tail-{suffix}",
            target="orders",
            business_date=date(1900, 1, 2),
        )
        head_id, tail_id = head.job_id, tail.job_id
        seed_session.commit()
    finally:
        seed_session.close()

    with factory.begin() as session:
        session.execute(
            update(JobRun)
            .where(JobRun.job_id == head_id)
            .values(
                status=status,
                lease_owner=f"stale-active-owner-{suffix}",
                lease_expires_at=text("clock_timestamp() + interval '1 hour'"),
                heartbeat_at=text("clock_timestamp() + interval '1 hour'"),
                next_retry_at=(
                    text("clock_timestamp() - interval '1 second'")
                    if status == "retry_wait"
                    else None
                ),
            )
        )

    with factory.begin() as session:
        tail_token = claim_next_job(
            session,
            lease_owner=f"review-stale-active-tail-owner-{suffix}",
            component_instance_id=f"review-stale-active-tail-component-{suffix}",
            lease_seconds=30,
        )
        assert tail_token is not None and tail_token.job_id == tail_id
        assert complete_job(session, tail_token, success_count=0) is True

    with factory() as session:
        head_row = session.get(JobRun, head_id)
        assert head_row is not None and head_row.status == "failed"
        event = session.scalar(
            select(JobEvent).where(
                JobEvent.job_id == head_id,
                JobEvent.event_type == "job_quarantined",
            )
        )
        assert event is not None
        assert "active_lease_on_non_running" in (event.payload_json or {}).get(
            "control_state_reasons", []
        )


def test_postgres_finished_non_worker_history_quarantines_instead_of_takeover(
    t12_postgres_factory,
) -> None:
    suffix = str(time.time_ns())
    factory = t12_postgres_factory
    seed_session = factory()
    try:
        head = _seed_job(
            seed_session,
            f"review-history-browser-head-{suffix}",
            target="orders",
            business_date=date(1900, 1, 1),
        )
        tail = _seed_job(
            seed_session,
            f"review-history-browser-tail-{suffix}",
            target="orders",
            business_date=date(1900, 1, 2),
        )
        head_id, tail_id = head.job_id, tail.job_id
        seed_session.commit()
    finally:
        seed_session.close()

    component_id = f"review-history-browser-component-{suffix}"
    now = datetime.now(UTC)
    with factory.begin() as session:
        session.add(
            ComponentHeartbeat(
                component_instance_id=component_id,
                component_type="browser",
                status="healthy",
                started_at=now,
                last_heartbeat_at=now,
                activity_json={},
                queue_summary_json={},
                created_at=now,
                updated_at=now,
            )
        )
        session.flush()
        session.add(
            JobAttempt(
                attempt_id=f"review-history-browser-attempt-{suffix}",
                job_id=head_id,
                stage_run_id=None,
                attempt_number=1,
                lease_epoch=1,
                component_type="browser",
                component_instance_id=component_id,
                started_at=now,
                finished_at=now,
                exit_type="success",
                created_at=now,
            )
        )
        session.flush()
        session.execute(
            update(JobRun)
            .where(JobRun.job_id == head_id)
            .values(attempt_count=1, lease_epoch=1)
        )

    with factory.begin() as session:
        tail_token = claim_next_job(
            session,
            lease_owner=f"review-history-browser-tail-owner-{suffix}",
            component_instance_id=f"review-history-browser-tail-component-{suffix}",
            lease_seconds=30,
        )
        assert tail_token is not None and tail_token.job_id == tail_id
        assert complete_job(session, tail_token, success_count=0) is True

    with factory() as session:
        head_row = session.get(JobRun, head_id)
        assert head_row is not None and head_row.status == "failed"
        event = session.scalar(
            select(JobEvent).where(
                JobEvent.job_id == head_id,
                JobEvent.event_type == "job_quarantined",
            )
        )
        assert event is not None
        assert "history_component_type_invalid" in (event.payload_json or {}).get(
            "control_state_reasons", []
        )


def test_postgres_finished_history_exact_stale_component_binding_quarantines_and_releases(
    t12_postgres_factory,
) -> None:
    suffix = str(time.time_ns())
    factory = t12_postgres_factory
    seed_session = factory()
    try:
        head = _seed_job(
            seed_session,
            f"review-history-stale-binding-head-{suffix}",
            target="orders",
            business_date=date(1900, 1, 1),
        )
        tail = _seed_job(
            seed_session,
            f"review-history-stale-binding-tail-{suffix}",
            target="orders",
            business_date=date(1900, 1, 2),
        )
        head_id, tail_id = head.job_id, tail.job_id
        seed_session.commit()
    finally:
        seed_session.close()

    component_id = f"review-history-stale-binding-component-{suffix}"
    attempt_id = f"review-history-stale-binding-attempt-{suffix}"
    now = datetime.now(UTC)
    with factory.begin() as session:
        component = ComponentHeartbeat(
            component_instance_id=component_id,
            component_type="worker",
            status="healthy",
            started_at=now,
            last_heartbeat_at=now,
            activity_json={},
            queue_summary_json={},
            created_at=now,
            updated_at=now,
        )
        session.add(component)
        session.flush()
        session.add(
            JobAttempt(
                attempt_id=attempt_id,
                job_id=head_id,
                stage_run_id=None,
                attempt_number=1,
                lease_epoch=1,
                component_type="worker",
                component_instance_id=component_id,
                started_at=now,
                finished_at=now,
                exit_type="success",
                created_at=now,
            )
        )
        session.flush()
        component.current_job_id = head_id
        component.current_attempt_id = attempt_id
        session.execute(
            update(JobRun)
            .where(JobRun.job_id == head_id)
            .values(attempt_count=1, lease_epoch=1)
        )

    with factory.begin() as session:
        tail_token = claim_next_job(
            session,
            lease_owner=f"review-history-stale-binding-tail-owner-{suffix}",
            component_instance_id=f"review-history-stale-binding-tail-component-{suffix}",
            lease_seconds=30,
        )
        assert tail_token is not None and tail_token.job_id == tail_id
        assert complete_job(session, tail_token, success_count=0) is True

    with factory() as session:
        head_row = session.get(JobRun, head_id)
        attempt = session.get(JobAttempt, attempt_id)
        component = session.get(ComponentHeartbeat, component_id)
        assert head_row is not None and head_row.status == "failed"
        assert attempt is not None
        assert attempt.exit_type == "success"
        assert attempt.finished_at == now
        assert component is not None
        assert component.current_job_id is None
        assert component.current_attempt_id is None
        event = session.scalar(
            select(JobEvent).where(
                JobEvent.job_id == head_id,
                JobEvent.event_type == "job_quarantined",
            )
        )
        assert event is not None
        payload = event.payload_json or {}
        assert "finished_attempt_component_binding_stale" in payload.get(
            "control_state_reasons", []
        )
        assert payload.get("released_component_count") == 1


@pytest.mark.parametrize(
    "corruption", ["owner_null", "epoch_null", "epoch_zero", "epoch_negative"]
)
def test_postgres_expired_corrupt_lease_identity_generic_and_explicit_failed(
    t12_postgres_factory,
    corruption: str,
) -> None:
    suffix = f"{corruption}-{time.time_ns()}"
    factory = t12_postgres_factory
    head_id, tail_id, _old_token, _component_id = _seed_expired_invalid_running_pair(
        factory,
        suffix,
        tamper_identity=False,
    )
    with factory.begin() as session:
        values = {
            "lease_owner": None,
            "lease_epoch": None,
        }
        if corruption == "epoch_zero":
            values = {"lease_epoch": 0}
        elif corruption == "epoch_negative":
            values = {"lease_epoch": -1}
        session.execute(
            update(JobRun)
            .where(JobRun.job_id == head_id)
            .values(**values)
        )

    generic_token = None
    with factory.begin() as session:
        generic_token = claim_next_job(
            session,
            lease_owner=f"review-corrupt-generic-owner-{suffix}",
            component_instance_id=f"review-corrupt-generic-component-{suffix}",
            lease_seconds=30,
        )
        if generic_token is not None:
            assert generic_token.job_id == tail_id
            assert complete_job(session, generic_token, success_count=0) is True

    supervisor = SubprocessSupervisor(control_session_factory=factory)
    explicit_result = supervisor.run(
        job_id=head_id,
        command=["not-started"],
        max_attempts=1,
    )
    assert generic_token is not None and generic_token.job_id == tail_id
    assert explicit_result.status is ChildRunStatus.FAILED


def test_postgres_invalid_quarantine_future_attempt_timestamp_is_audited_and_ordered(
    t12_postgres_factory,
) -> None:
    suffix = str(time.time_ns())
    factory = t12_postgres_factory
    head_id, tail_id, _old_token, _component_id = _seed_expired_invalid_running_pair(
        factory, suffix
    )
    with factory.begin() as session:
        session.execute(
            update(JobAttempt)
            .where(JobAttempt.job_id == head_id)
            .values(started_at=text("clock_timestamp() + interval '1 hour'"))
        )

    with factory.begin() as session:
        tail_token = claim_next_job(
            session,
            lease_owner=f"review-future-quarantine-tail-owner-{suffix}",
            component_instance_id=f"review-future-quarantine-tail-component-{suffix}",
            lease_seconds=30,
        )
        assert tail_token is not None and tail_token.job_id == tail_id
        assert complete_job(session, tail_token, success_count=0) is True

    with factory() as session:
        attempt = session.scalar(select(JobAttempt).where(JobAttempt.job_id == head_id))
        assert attempt is not None
        assert attempt.finished_at is not None and attempt.finished_at >= attempt.started_at
        event = session.scalar(
            select(JobEvent).where(
                JobEvent.job_id == head_id,
                JobEvent.event_type == "job_quarantined",
            )
        )
        assert event is not None
        assert (event.payload_json or {}).get("timestamp_anomaly") is True


def test_postgres_valid_takeover_future_attempt_timestamp_is_audited_and_ordered(
    t12_postgres_factory,
) -> None:
    suffix = str(time.time_ns())
    factory = t12_postgres_factory
    head_id, _tail_id, old_token, _component_id = _seed_expired_invalid_running_pair(
        factory,
        suffix,
        tamper_identity=False,
    )
    with factory.begin() as session:
        session.execute(
            update(JobAttempt)
            .where(JobAttempt.job_id == head_id)
            .values(started_at=text("clock_timestamp() + interval '1 hour'"))
        )

    with factory.begin() as session:
        new_token = claim_job(
            session,
            job_id=head_id,
            lease_owner=f"review-future-takeover-owner-{suffix}",
            component_instance_id=f"review-future-takeover-component-{suffix}",
            lease_seconds=30,
        )
        assert new_token is not None
        assert new_token.lease_epoch == old_token.lease_epoch + 1

    with factory() as session:
        old_attempt = session.get(JobAttempt, old_token.attempt_id)
        assert old_attempt is not None
        assert old_attempt.finished_at is not None
        assert old_attempt.finished_at >= old_attempt.started_at
        event = session.scalar(
            select(JobEvent).where(
                JobEvent.job_id == head_id,
                JobEvent.event_type == "lease_expired",
            )
        )
        assert event is not None
        assert (event.payload_json or {}).get("timestamp_anomaly") is True


def _add_unfinished_attempt_for_review(
    factory: sessionmaker[Session],
    *,
    job_id: str,
    attempt_number: int,
    lease_epoch: int,
    component_id: str,
) -> tuple[str, str]:
    attempt_id = f"review-extra-attempt-{time.time_ns()}"
    started_at = datetime.now(UTC)
    with factory.begin() as session:
        component = ComponentHeartbeat(
            component_instance_id=component_id,
            component_type="worker",
            status="healthy",
            started_at=started_at,
            last_heartbeat_at=started_at,
            activity_json={},
            queue_summary_json={},
            created_at=started_at,
            updated_at=started_at,
        )
        session.add(component)
        session.flush()
        attempt = JobAttempt(
            attempt_id=attempt_id,
            job_id=job_id,
            stage_run_id=None,
            attempt_number=attempt_number,
            lease_epoch=lease_epoch,
            component_type="worker",
            component_instance_id=component_id,
            started_at=started_at,
            created_at=started_at,
        )
        session.add(attempt)
        session.flush()
        component.current_job_id = job_id
        component.current_attempt_id = attempt_id
        session.execute(
            update(JobRun)
            .where(JobRun.job_id == job_id)
            .values(
                attempt_count=attempt_number,
                lease_epoch=lease_epoch,
                lease_owner=f"review-extra-owner-{attempt_id}",
                lease_expires_at=text("clock_timestamp() - interval '1 second'"),
            )
        )
    return attempt_id, component_id


def _add_overflow_unfinished_attempt_for_review(
    factory: sessionmaker[Session],
    *,
    job_id: str,
    attempt_number: int,
    lease_epoch: int,
    component_id: str,
) -> str:
    attempt_id = f"review-overflow-attempt-{time.time_ns()}"
    started_at = datetime.now(UTC)
    with factory.begin() as session:
        component = ComponentHeartbeat(
            component_instance_id=component_id,
            component_type="worker",
            status="healthy",
            started_at=started_at,
            last_heartbeat_at=started_at,
            activity_json={},
            queue_summary_json={},
            created_at=started_at,
            updated_at=started_at,
        )
        session.add(component)
        session.flush()
        session.add(
            JobAttempt(
                attempt_id=attempt_id,
                job_id=job_id,
                stage_run_id=None,
                attempt_number=attempt_number,
                lease_epoch=lease_epoch,
                component_type="worker",
                component_instance_id=component_id,
                started_at=started_at,
                created_at=started_at,
            )
        )
        session.flush()
        component.current_job_id = job_id
        component.current_attempt_id = attempt_id
    return component_id


def test_postgres_valid_expired_multiple_attempts_close_all_and_release_exact_components(
    t12_postgres_factory,
) -> None:
    suffix = str(time.time_ns())
    factory = t12_postgres_factory
    head_id, tail_id, old_token, component_one = _seed_expired_invalid_running_pair(
        factory,
        suffix,
        tamper_identity=False,
    )
    attempt_two, component_two = _add_unfinished_attempt_for_review(
        factory,
        job_id=head_id,
        attempt_number=2,
        lease_epoch=2,
        component_id=f"review-extra-component-{suffix}",
    )

    with factory.begin() as session:
        tail_token = claim_next_job(
            session,
            lease_owner=f"review-extra-tail-owner-{suffix}",
            component_instance_id=f"review-extra-tail-component-{suffix}",
            lease_seconds=30,
        )
        assert tail_token is not None and tail_token.job_id == tail_id
        assert complete_job(session, tail_token, success_count=0) is True

    with factory() as session:
        attempts = list(
            session.scalars(select(JobAttempt).where(JobAttempt.job_id == head_id))
        )
        assert {attempt.attempt_id for attempt in attempts} >= {
            old_token.attempt_id,
            attempt_two,
        }
        assert all(attempt.finished_at is not None for attempt in attempts)
        for component_id in (component_one, component_two):
            component = session.get(ComponentHeartbeat, component_id)
            assert component is not None
            assert component.current_job_id is None
            assert component.current_attempt_id is None


def test_postgres_valid_expired_missing_attempt_quarantine_preserves_browser_api_bindings(
    t12_postgres_factory,
) -> None:
    suffix = str(time.time_ns())
    factory = t12_postgres_factory
    head_id, tail_id, _old_token, worker_component = _seed_expired_invalid_running_pair(
        factory,
        suffix,
        tamper_identity=False,
    )
    browser_id = f"review-missing-browser-{suffix}"
    api_id = f"review-missing-api-{suffix}"
    now = datetime.now(UTC)
    with factory.begin() as session:
        session.execute(
            update(ComponentHeartbeat)
            .where(ComponentHeartbeat.component_instance_id == worker_component)
            .values(current_job_id=None, current_attempt_id=None)
        )
        session.execute(
            update(JobEvent)
            .where(JobEvent.job_id == head_id)
            .values(attempt_id=None)
        )
        session.execute(delete(JobAttempt).where(JobAttempt.job_id == head_id))
        session.add_all(
            [
                ComponentHeartbeat(
                    component_instance_id=browser_id,
                    component_type="browser",
                    status="healthy",
                    started_at=now,
                    last_heartbeat_at=now,
                    current_job_id=head_id,
                    current_attempt_id=None,
                    activity_json={},
                    queue_summary_json={},
                    created_at=now,
                    updated_at=now,
                ),
                ComponentHeartbeat(
                    component_instance_id=api_id,
                    component_type="api",
                    status="healthy",
                    started_at=now,
                    last_heartbeat_at=now,
                    current_job_id=head_id,
                    current_attempt_id=None,
                    activity_json={},
                    queue_summary_json={},
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )

    with factory.begin() as session:
        tail_token = claim_next_job(
            session,
            lease_owner=f"review-missing-tail-owner-{suffix}",
            component_instance_id=f"review-missing-tail-component-{suffix}",
            lease_seconds=30,
        )
        assert tail_token is not None and tail_token.job_id == tail_id
        assert complete_job(session, tail_token, success_count=0) is True

    with factory() as session:
        browser = session.get(ComponentHeartbeat, browser_id)
        api = session.get(ComponentHeartbeat, api_id)
        assert browser is not None and browser.current_job_id == head_id
        assert api is not None and api.current_job_id == head_id
        assert browser.current_attempt_id is None and api.current_attempt_id is None


def test_postgres_valid_expired_attempt_binding_mismatch_quarantines_not_takeover(
    t12_postgres_factory,
) -> None:
    suffix = str(time.time_ns())
    factory = t12_postgres_factory
    head_id, tail_id, _old_token, worker_component = _seed_expired_invalid_running_pair(
        factory,
        suffix,
        tamper_identity=False,
    )
    unrelated_id = f"review-binding-mismatch-unrelated-{suffix}"
    with factory.begin() as session:
        session.add(
            JobRun(
                job_id=unrelated_id,
                job_name="product_sync",
                job_kind="product_sync",
                status="pending",
                started_at=datetime.now(UTC),
                metadata_json={},
            )
        )
        session.flush()
        session.execute(
            update(ComponentHeartbeat)
            .where(ComponentHeartbeat.component_instance_id == worker_component)
            .values(current_job_id=unrelated_id, current_attempt_id=None)
        )

    with factory.begin() as session:
        tail_token = claim_next_job(
            session,
            lease_owner=f"review-binding-mismatch-tail-owner-{suffix}",
            component_instance_id=f"review-binding-mismatch-tail-component-{suffix}",
            lease_seconds=30,
        )
        assert tail_token is not None and tail_token.job_id == tail_id
        assert complete_job(session, tail_token, success_count=0) is True

    with factory() as session:
        head = session.get(JobRun, head_id)
        component = session.get(ComponentHeartbeat, worker_component)
        assert head is not None and head.status == "failed"
        assert component is not None and component.current_job_id == unrelated_id


def test_postgres_multi_attempt_quarantine_event_failure_rolls_back_everything(
    t12_postgres_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = str(time.time_ns())
    factory = t12_postgres_factory
    head_id, _tail_id, _old_token, _component_one = _seed_expired_invalid_running_pair(
        factory,
        suffix,
        tamper_identity=False,
    )
    _add_unfinished_attempt_for_review(
        factory,
        job_id=head_id,
        attempt_number=2,
        lease_epoch=2,
        component_id=f"review-failure-extra-component-{suffix}",
    )
    before = _quarantine_control_snapshot(
        factory,
        job_ids=(head_id,),
        component_ids=(
            f"review-quarantine-head-component-{suffix}",
            f"review-failure-extra-component-{suffix}",
        ),
    )

    def injected_event_failure(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("injected multi-attempt quarantine event failure")

    monkeypatch.setattr(repositories, "_add_job_event", injected_event_failure)
    with factory.begin() as session:
        caught = False
        try:
            claim_next_job(
                session,
                lease_owner=f"review-multi-failure-owner-{suffix}",
                component_instance_id=f"review-multi-failure-component-{suffix}",
                lease_seconds=30,
            )
        except RuntimeError as exc:
            caught = "injected multi-attempt quarantine event failure" in str(exc)
        assert caught is True

    after = _quarantine_control_snapshot(
        factory,
        job_ids=(head_id,),
        component_ids=(
            f"review-quarantine-head-component-{suffix}",
            f"review-failure-extra-component-{suffix}",
        ),
    )
    assert after == before
