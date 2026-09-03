from __future__ import annotations

import threading
import time
from datetime import UTC, date, datetime, timedelta
import os
from urllib.parse import urlparse

import pytest
from sqlalchemy import create_engine, delete, func, or_, text, update
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.models import (
    Base,
    ComponentHeartbeat,
    JobAttempt,
    JobEvent,
    JobRun,
    JobStageRun,
)
from apps.worker import scheduler
from apps.worker.daily_windows import plan_daily_sync
from apps.worker import subprocess_supervisor as supervisor_module
from apps.worker.subprocess_supervisor import ChildRunStatus, SubprocessSupervisor
from apps.worker.stage_runner import _record_stage_failure, run_daily_stages
from apps.worker.scheduler import run_daily_child
from apps.worker.task_control import FailureKind, claim_job, fail_job, heartbeat_job, retry_policy


def _seed_job(
    session: Session,
    job_id: str,
    *,
    complete_stages: bool = False,
    parent_job_id: str = "range-parent",
    max_attempts: int = 3,
) -> JobRun:
    del parent_job_id
    day = 5 if job_id.endswith("a") else 6
    business_date = date(2026, 8, day)
    plan = plan_daily_sync(
        session,
        start=business_date,
        end=business_date + timedelta(days=1),
        target="orders",
        requested_by="subprocess-recovery",
        trigger_source="test",
        config_version=f"subprocess-recovery-{time.time_ns()}",
    )
    job = session.get(JobRun, plan.daily_jobs[0].job_id)
    if job is None:
        raise AssertionError("planner did not create subprocess recovery child")
    job.max_attempts = max_attempts
    now = datetime.now(UTC)
    if complete_stages:
        for stage_name in ("collect", "materialize", "settle"):
            session.add(
                JobStageRun(
                    stage_run_id=f"stage-{job.job_id}-{stage_name}",
                    job_id=job.job_id,
                    stage_name=stage_name,
                    status="success",
                    checkpoint_json={"status": "success"},
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


class FakeProcess:
    _next_pid = 1000

    def __init__(self, exit_code: int, *, delay: float = 0.0):
        FakeProcess._next_pid += 1
        self.pid = FakeProcess._next_pid
        self._exit_code = exit_code
        self._ready_at = time.monotonic() + delay
        self.terminated = False
        self.killed = False

    def poll(self):
        if time.monotonic() < self._ready_at:
            return None
        return self._exit_code

    def wait(self, timeout=None):
        return self._exit_code

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


def test_subprocess_exit_rss_and_attempt_are_written_and_scheduler_survives(
    db_session: Session,
) -> None:
    job = _seed_job(db_session, "child-exit")
    job_id = job.job_id
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, future=True)
    processes: list[FakeProcess] = []

    def spawn(*_args, **_kwargs):
        process = FakeProcess(1)
        processes.append(process)
        return process

    supervisor = SubprocessSupervisor(
        control_session_factory=factory,
        popen_factory=spawn,
        rss_reader=lambda _pid: 1234,
        poll_interval_seconds=0,
    )
    result = supervisor.run(
        job_id=job_id,
        command=["python", "-m", "apps.worker.daily_task"],
        max_attempts=2,
    )

    assert result.status is ChildRunStatus.RETRY_WAIT
    assert result.attempts == 2
    assert result.exit_code == 1
    assert result.rss_peak_bytes == 1234
    with factory() as verify:
        attempts = list(verify.scalars(select(JobAttempt).where(JobAttempt.job_id == job_id)))
        assert len(attempts) == 2
        assert [attempt.exit_code for attempt in attempts] == [1, 1]
        assert all(attempt.rss_peak_bytes == 1234 for attempt in attempts)
        job = verify.get(JobRun, job_id)
        # The supervisor's per-invocation bound is lower than the DB policy;
        # T1.2 therefore durably leaves the job retryable for a later claim.
        assert job is not None and job.status == "retry_wait"


def test_oom_exit_is_bounded_and_does_not_raise_into_scheduler(db_session: Session) -> None:
    job = _seed_job(db_session, "child-oom")
    job_id = job.job_id
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, future=True)

    supervisor = SubprocessSupervisor(
        control_session_factory=factory,
        popen_factory=lambda *_args, **_kwargs: FakeProcess(-9),
        rss_reader=lambda _pid: 8 * 1024 * 1024,
        poll_interval_seconds=0,
        rss_limit_bytes=8 * 1024 * 1024,
    )
    result = supervisor.run(
        job_id=job_id,
        command=["python", "-m", "apps.worker.daily_task"],
        max_attempts=2,
    )

    assert result.status is ChildRunStatus.OOM
    assert result.attempts == 2
    with factory() as verify:
        assert verify.scalar(
            select(JobRun.status).where(JobRun.job_id == job_id)
        ) == "failed"


def test_database_max_attempts_is_authoritative_when_claim_is_exhausted(
    db_session: Session,
) -> None:
    job = _seed_job(db_session, "child-db-max", max_attempts=1)
    job_id = job.job_id
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, future=True)

    supervisor = SubprocessSupervisor(
        control_session_factory=factory,
        popen_factory=lambda *_args, **_kwargs: FakeProcess(1),
        rss_reader=lambda _pid: 42,
        poll_interval_seconds=0,
    )
    result = supervisor.run(
        job_id=job_id,
        command=["python", "-m", "apps.worker.daily_task"],
        max_attempts=3,
    )

    assert result.status is ChildRunStatus.FAILED
    assert result.attempts == 1
    with factory() as verify:
        job = verify.get(JobRun, job_id)
        assert job is not None
        assert job.status == "failed"
        assert job.error_code == "worker_exit_1"


def test_douyin_rate_limit_process_exit_uses_durable_global_cooldown() -> None:
    summary = (
        "Douyin API error: {'error_code': 2119003, "
        "'description': '请求太过频繁，请稍后再试'}"
    )

    assert supervisor_module._failure_kind(
        1,
        error_summary=summary,
        rss_peak_bytes=None,
        rss_limit_bytes=None,
    ) is FailureKind.TRANSIENT
    assert supervisor_module._failure_error_code(
        1,
        error_summary=summary,
        rss_peak_bytes=None,
        rss_limit_bytes=None,
    ) == "douyin_rate_limited"
    assert supervisor_module._failure_retry_base_delay_seconds(summary) == 1800


def test_proactive_douyin_daily_quota_wait_uses_reported_reset_delay() -> None:
    summary = (
        "douyin_api_quota_exhausted endpoint=refunds "
        "retry_after_seconds=43123"
    )

    assert supervisor_module._failure_kind(
        1,
        error_summary=summary,
        rss_peak_bytes=None,
        rss_limit_bytes=None,
    ) is FailureKind.TRANSIENT
    assert supervisor_module._failure_error_code(
        1,
        error_summary=summary,
        rss_peak_bytes=None,
        rss_limit_bytes=None,
    ) == "douyin_rate_limited"
    assert supervisor_module._failure_retry_base_delay_seconds(summary) == 43123


def test_fixed_quota_retry_delay_is_not_exponentially_increased() -> None:
    decision = retry_policy(
        FailureKind.TRANSIENT,
        attempt_number=2,
        max_attempts=3,
        base_delay_seconds=43123,
        fixed_delay_seconds=43123,
    )

    assert decision.delay_seconds == 43123


def test_only_one_heavy_child_can_run_at_once(db_session: Session) -> None:
    first_job = _seed_job(db_session, "child-a", complete_stages=True)
    second_job = _seed_job(db_session, "child-b", complete_stages=True)
    first_id = first_job.job_id
    second_id = second_job.job_id
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, future=True)
    started = threading.Event()
    release = threading.Event()

    class BlockingProcess(FakeProcess):
        def poll(self):
            started.set()
            release.wait(timeout=2)
            return 0

    supervisor = SubprocessSupervisor(
        control_session_factory=factory,
        popen_factory=lambda *_args, **_kwargs: BlockingProcess(0),
        rss_reader=lambda _pid: 42,
        poll_interval_seconds=0,
    )
    first_result: list[object] = []
    thread = threading.Thread(
        target=lambda: first_result.append(
            supervisor.run(
                job_id=first_id,
                command=["python", "-m", "apps.worker.daily_task"],
                max_attempts=1,
            )
        )
    )
    thread.start()
    assert started.wait(timeout=2)
    second = supervisor.run(
        job_id=second_id,
        command=["python", "-m", "apps.worker.daily_task"],
        max_attempts=1,
    )
    release.set()
    thread.join(timeout=2)

    assert second.status is ChildRunStatus.BUSY
    assert first_result and first_result[0].status is ChildRunStatus.SUCCESS


def test_generic_daily_queue_consumes_api_or_backfill_jobs_one_at_a_time(
    db_session: Session,
) -> None:
    _seed_job(db_session, "queue-a", complete_stages=True)
    _seed_job(db_session, "queue-b", complete_stages=True)
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, future=True)

    first = run_daily_child(
        factory,
        job_id=None,
        max_attempts=1,
        supervisor=SubprocessSupervisor(
            control_session_factory=factory,
            popen_factory=lambda *_args, **_kwargs: FakeProcess(0),
            rss_reader=lambda _pid: 11,
            poll_interval_seconds=0,
        ),
    )
    second = run_daily_child(
        factory,
        job_id=None,
        max_attempts=1,
        supervisor=SubprocessSupervisor(
            control_session_factory=factory,
            popen_factory=lambda *_args, **_kwargs: FakeProcess(0),
            rss_reader=lambda _pid: 12,
            poll_interval_seconds=0,
        ),
    )

    assert first.status is ChildRunStatus.SUCCESS
    assert second.status is ChildRunStatus.SUCCESS
    assert first.job_id != second.job_id
    with factory() as verify:
        assert verify.scalar(select(JobRun.status).where(JobRun.job_id == first.job_id)) == "success"
        assert verify.scalar(select(JobRun.status).where(JobRun.job_id == second.job_id)) == "success"


def test_daily_queue_drain_continues_after_completion_and_yields_on_retry_wait(
    monkeypatch,
) -> None:
    statuses = iter(
        (
            ChildRunStatus.SUCCESS,
            ChildRunStatus.FAILED,
            ChildRunStatus.RETRY_WAIT,
            ChildRunStatus.SUCCESS,
        )
    )
    calls: list[object] = []

    def fake_run_daily_child(factory, **_kwargs):
        calls.append(factory)
        status = next(statuses)
        return scheduler.ChildRunResult(
            job_id=f"queued-{len(calls)}",
            status=status,
            attempts=1,
            exit_code=0 if status is ChildRunStatus.SUCCESS else 1,
        )

    monkeypatch.setenv("WORKER_EXECUTE_DAILY_CHILD", "true")
    monkeypatch.setattr(scheduler, "_STOP", False)
    monkeypatch.setattr(scheduler, "run_daily_child", fake_run_daily_child)

    results = scheduler.drain_ready_daily_children(object())

    assert [result.status for result in results] == [
        ChildRunStatus.SUCCESS,
        ChildRunStatus.FAILED,
        ChildRunStatus.RETRY_WAIT,
    ]
    assert len(calls) == 3


def test_scheduler_main_polls_queued_manual_jobs_when_auto_sync_is_disabled(
    monkeypatch,
) -> None:
    factory = object()
    calls: list[object] = []
    settlement_calls: list[object] = []
    finance_calls: list[object] = []

    monkeypatch.setenv("WORKER_RUN_ON_START", "false")
    monkeypatch.setenv("WORKER_EXECUTE_DAILY_CHILD", "true")
    monkeypatch.setattr(scheduler, "_STOP", False)
    monkeypatch.setattr(scheduler, "get_session_factory", lambda: factory)
    monkeypatch.setattr(scheduler, "_auto_sync_enabled", lambda _factory: False)
    monkeypatch.setattr(
        scheduler,
        "process_queued_settlement_rebuilds",
        lambda passed_factory: settlement_calls.append(passed_factory),
    )
    monkeypatch.setattr(
        scheduler,
        "drain_ready_daily_children",
        lambda passed_factory: (calls.append(passed_factory) or ()),
    )
    monkeypatch.setattr(
        scheduler,
        "process_queued_finance_dispute_detections",
        lambda passed_factory: (finance_calls.append(passed_factory) or ()),
    )
    monkeypatch.setattr(
        scheduler,
        "_sleep_until_stop",
        lambda _seconds: setattr(scheduler, "_STOP", True),
    )
    monkeypatch.setattr(
        scheduler,
        "run_once",
        lambda: pytest.fail("automatic planning must stay paused"),
    )

    scheduler.main()

    assert calls == [factory]
    assert settlement_calls == [factory]
    assert finance_calls == [factory]


def test_scheduler_queue_poll_is_independent_of_long_auto_plan_interval(
    monkeypatch,
) -> None:
    factory = object()
    drain_calls: list[object] = []
    sleep_calls: list[float] = []

    def fake_drain(passed_factory):
        drain_calls.append(passed_factory)
        if len(drain_calls) >= 2:
            monkeypatch.setattr(scheduler, "_STOP", True)
        if len(drain_calls) == 1:
            return (
                scheduler.ChildRunResult(
                    job_id="retrying-date",
                    status=ChildRunStatus.RETRY_WAIT,
                    attempts=1,
                ),
            )
        return ()

    monkeypatch.setenv("WORKER_RUN_ON_START", "false")
    monkeypatch.setattr(scheduler, "_STOP", False)
    monkeypatch.setattr(scheduler, "get_session_factory", lambda: factory)
    monkeypatch.setattr(scheduler, "_auto_sync_enabled", lambda _factory: True)
    monkeypatch.setattr(scheduler, "_configured_interval_seconds", lambda _factory: 3600)
    monkeypatch.setattr(scheduler, "_configured_daily_queue_poll_seconds", lambda: 5.0)
    monkeypatch.setattr(scheduler, "drain_ready_daily_children", fake_drain)
    monkeypatch.setattr(
        scheduler,
        "_sleep_until_stop",
        lambda seconds: sleep_calls.append(seconds),
    )
    monkeypatch.setattr(
        scheduler,
        "run_once",
        lambda: pytest.fail("the long plan timer must not fire during queue polling"),
    )

    scheduler.main()

    assert drain_calls == [factory, factory]
    assert sleep_calls == [5.0]


def test_scheduler_chunk_attempt_configuration_matches_control_plane_limit(monkeypatch) -> None:
    monkeypatch.setenv("WORKER_CHUNK_MAX_ATTEMPTS", "5")
    assert scheduler._configured_chunk_max_attempts() == 3
    monkeypatch.setenv("WORKER_CHUNK_MAX_ATTEMPTS", "0")
    assert scheduler._configured_chunk_max_attempts() == 1


@pytest.fixture()
def t12_postgres_factory():
    url = os.getenv("DYDATA_T12_TEST_DATABASE_URL")
    if not url:
        pytest.skip("DYDATA_T12_TEST_DATABASE_URL is not configured")
    parsed = urlparse(url)
    if parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.port != 55432:
        pytest.fail("PostgreSQL test must use loopback port 55432")
    engine = create_engine(url, future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, future=True)
    yield factory
    with engine.begin() as connection:
        review_ids = [
            row[0]
            for row in connection.execute(
                select(JobRun.job_id).where(
                    or_(
                        JobRun.config_version.like("subprocess-recovery%"),
                        JobRun.job_id.like("t22-pg%"),
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


def test_postgres_fencing_rejects_second_scheduler_and_old_epoch_checkpoint(
    t12_postgres_factory,
) -> None:
    factory = t12_postgres_factory
    job_id = f"t22-pg-{time.time_ns()}"
    parent_id = f"{job_id}-parent"
    with factory() as session:
        session.add(
            JobRun(
                job_id=parent_id,
                job_name="range_sync",
                status="pending",
                started_at=datetime.now(UTC),
                success_count=0,
                failed_count=0,
                metadata_json={},
                job_kind="range_sync",
                data_source="douyin",
                config_version="v1",
                window_start=datetime(2026, 8, 5, tzinfo=UTC),
                window_end=datetime(2026, 8, 7, tzinfo=UTC),
                attempt_count=0,
                max_attempts=3,
                lease_epoch=0,
            )
        )
        session.commit()
        seeded_job = _seed_job(session, job_id, parent_job_id=parent_id)
        job_id = seeded_job.job_id
    try:
        with factory.begin() as session:
            first = claim_job(
                session,
                job_id=job_id,
                lease_owner="scheduler-a",
                component_instance_id=f"component-{job_id}-a",
                lease_seconds=120,
            )
            assert first is not None
        with factory.begin() as session:
            assert (
                claim_job(
                    session,
                    job_id=job_id,
                    lease_owner="scheduler-b",
                    component_instance_id=f"component-{job_id}-b",
                    lease_seconds=120,
                )
                is None
            )
        with factory.begin() as session:
            assert heartbeat_job(session, first, lease_seconds=120)
        with factory.begin() as session:
            session.execute(
                update(JobRun)
                .where(JobRun.job_id == job_id)
                .values(lease_expires_at=text("clock_timestamp() - interval '1 second'"))
            )
        with factory.begin() as session:
            second = claim_job(
                session,
                job_id=job_id,
                lease_owner="scheduler-b",
                component_instance_id=f"component-{job_id}-b",
                lease_seconds=120,
            )
            assert second is not None and second.lease_epoch > first.lease_epoch
        with factory.begin() as session:
            assert not heartbeat_job(session, first, lease_seconds=120)
        with pytest.raises(RuntimeError, match="lease"):
            run_daily_stages(
                factory,
                job_id=job_id,
                handlers={"collect": lambda _session: None},
                lease_owner=first.lease_owner,
                lease_epoch=first.lease_epoch,
                attempt_id=first.attempt_id,
                component_instance_id=first.component_instance_id,
            )
    finally:
        with factory.begin() as session:
            session.execute(
                text(
                    "UPDATE component_heartbeats SET current_job_id = NULL, "
                    "current_attempt_id = NULL WHERE component_instance_id LIKE :prefix"
                ),
                {"prefix": f"component-{job_id}%"},
            )
            session.execute(JobEvent.__table__.delete().where(JobEvent.job_id == job_id))
            session.execute(
                JobAttempt.__table__.delete().where(JobAttempt.job_id == job_id)
            )
            session.execute(
                JobStageRun.__table__.delete().where(JobStageRun.job_id == job_id)
            )
            session.execute(JobRun.__table__.delete().where(JobRun.job_id == job_id))
            session.execute(JobRun.__table__.delete().where(JobRun.job_id == parent_id))
            session.execute(
                text("DELETE FROM component_heartbeats WHERE component_instance_id LIKE :prefix"),
                {"prefix": f"component-{job_id}%"},
            )


def test_postgres_expired_lease_rejects_stage_checkpoint_before_takeover(
    t12_postgres_factory,
) -> None:
    factory = t12_postgres_factory
    job_id = f"t22-pg-expired-{time.time_ns()}"
    parent_id = f"{job_id}-parent"
    with factory() as session:
        session.add(
            JobRun(
                job_id=parent_id,
                job_name="range_sync",
                status="pending",
                started_at=datetime.now(UTC),
                success_count=0,
                failed_count=0,
                metadata_json={},
                job_kind="range_sync",
                data_source="douyin",
                config_version="v1",
                window_start=datetime(2026, 8, 5, tzinfo=UTC),
                window_end=datetime(2026, 8, 7, tzinfo=UTC),
                attempt_count=0,
                max_attempts=3,
                lease_epoch=0,
            )
        )
        session.commit()
        seeded_job = _seed_job(session, job_id, parent_job_id=parent_id)
        job_id = seeded_job.job_id
    try:
        with factory.begin() as session:
            token = claim_job(
                session,
                job_id=job_id,
                lease_owner="scheduler-expired",
                component_instance_id=f"component-{job_id}",
                lease_seconds=120,
            )
            assert token is not None
        with factory.begin() as session:
            session.execute(
                update(JobRun)
                .where(JobRun.job_id == job_id)
                .values(lease_expires_at=text("clock_timestamp() - interval '1 second'"))
            )
        with pytest.raises(RuntimeError, match="lease"):
            run_daily_stages(
                factory,
                job_id=job_id,
                handlers={"collect": lambda session: session.add(
                    JobEvent(
                        event_id=f"expired-business-{job_id}",
                        job_id=job_id,
                        event_type="business_collect",
                        actor_type="worker",
                        payload_json={},
                        occurred_at=datetime.now(UTC),
                    )
                )},
                lease_owner=token.lease_owner,
                lease_epoch=token.lease_epoch,
                attempt_id=token.attempt_id,
                component_instance_id=token.component_instance_id,
            )
        with factory() as session:
            stage = session.scalar(
                select(JobStageRun).where(
                    JobStageRun.job_id == job_id,
                    JobStageRun.stage_name == "collect",
                )
            )
            assert stage is None or stage.status != "success"
            assert session.scalar(
                select(func.count()).select_from(JobEvent).where(
                    JobEvent.event_id == f"expired-business-{job_id}"
                )
            ) == 0
    finally:
        with factory.begin() as session:
            session.execute(
                text(
                    "UPDATE component_heartbeats SET current_job_id = NULL, "
                    "current_attempt_id = NULL WHERE component_instance_id LIKE :prefix"
                ),
                {"prefix": f"component-{job_id}%"},
            )
            session.execute(JobEvent.__table__.delete().where(JobEvent.job_id == job_id))
            session.execute(JobAttempt.__table__.delete().where(JobAttempt.job_id == job_id))
            session.execute(JobStageRun.__table__.delete().where(JobStageRun.job_id == job_id))
            session.execute(JobRun.__table__.delete().where(JobRun.job_id == job_id))
            session.execute(JobRun.__table__.delete().where(JobRun.job_id == parent_id))
            session.execute(
                text("DELETE FROM component_heartbeats WHERE component_instance_id LIKE :prefix"),
                {"prefix": f"component-{job_id}%"},
            )


def test_postgres_stale_failure_recorder_cannot_overwrite_new_epoch_stage(
    t12_postgres_factory,
) -> None:
    factory = t12_postgres_factory
    job_id = f"t22-pg-failure-cas-{time.time_ns()}"
    parent_id = f"{job_id}-parent"
    with factory() as session:
        session.add(
            JobRun(
                job_id=parent_id,
                job_name="range_sync",
                status="pending",
                started_at=datetime.now(UTC),
                success_count=0,
                failed_count=0,
                metadata_json={},
                job_kind="range_sync",
                data_source="douyin",
                config_version="v1",
                window_start=datetime(2026, 8, 5, tzinfo=UTC),
                window_end=datetime(2026, 8, 7, tzinfo=UTC),
                attempt_count=0,
                max_attempts=3,
                lease_epoch=0,
            )
        )
        session.commit()
        seeded_job = _seed_job(session, job_id, parent_job_id=parent_id)
        job_id = seeded_job.job_id
    try:
        with factory.begin() as session:
            old_token = claim_job(
                session,
                job_id=job_id,
                lease_owner="scheduler-old-failure",
                component_instance_id=f"component-{job_id}-old",
                lease_seconds=120,
            )
        assert old_token is not None
        with factory.begin() as session:
            session.execute(
                update(JobRun)
                .where(JobRun.job_id == job_id)
                .values(lease_expires_at=text("clock_timestamp() - interval '1 second'"))
            )
        with factory.begin() as session:
            new_token = claim_job(
                session,
                job_id=job_id,
                lease_owner="scheduler-new-failure",
                component_instance_id=f"component-{job_id}-new",
                lease_seconds=120,
            )
        assert new_token is not None and new_token.lease_epoch > old_token.lease_epoch
        _record_stage_failure(
            factory,
            job_id=job_id,
            stage_name="collect",
            error=RuntimeError("stale old owner failure"),
            lease_owner=old_token.lease_owner,
            lease_epoch=old_token.lease_epoch,
            attempt_id=old_token.attempt_id,
            component_instance_id=old_token.component_instance_id,
        )
        with factory() as session:
            assert session.get(JobStageRun, f"stage-{job_id}-collect") is None
            job = session.get(JobRun, job_id)
            assert job is not None and job.lease_epoch == new_token.lease_epoch
    finally:
        with factory.begin() as session:
            session.execute(
                text(
                    "UPDATE component_heartbeats SET current_job_id = NULL, "
                    "current_attempt_id = NULL WHERE component_instance_id LIKE :prefix"
                ),
                {"prefix": f"component-{job_id}%"},
            )
            session.execute(JobEvent.__table__.delete().where(JobEvent.job_id == job_id))
            session.execute(JobAttempt.__table__.delete().where(JobAttempt.job_id == job_id))
            session.execute(JobStageRun.__table__.delete().where(JobStageRun.job_id == job_id))
            session.execute(JobRun.__table__.delete().where(JobRun.job_id == job_id))
            session.execute(JobRun.__table__.delete().where(JobRun.job_id == parent_id))
            session.execute(
                text("DELETE FROM component_heartbeats WHERE component_instance_id LIKE :prefix"),
                {"prefix": f"component-{job_id}%"},
            )


def test_postgres_supervisor_closes_attempt_through_task_control_api(
    t12_postgres_factory,
) -> None:
    factory = t12_postgres_factory
    job_id = f"t22-pg-supervisor-{time.time_ns()}"
    parent_id = f"{job_id}-parent"
    with factory() as session:
        session.add(
            JobRun(
                job_id=parent_id,
                job_name="range_sync",
                status="pending",
                started_at=datetime.now(UTC),
                success_count=0,
                failed_count=0,
                metadata_json={},
                job_kind="range_sync",
                data_source="douyin",
                config_version="v1",
                window_start=datetime(2026, 8, 5, tzinfo=UTC),
                window_end=datetime(2026, 8, 7, tzinfo=UTC),
                attempt_count=0,
                max_attempts=3,
                lease_epoch=0,
            )
        )
        session.commit()
        seeded_job = _seed_job(session, job_id, parent_job_id=parent_id, complete_stages=True)
        job_id = seeded_job.job_id
    try:
        supervisor = SubprocessSupervisor(
            control_session_factory=factory,
            popen_factory=lambda *_args, **_kwargs: FakeProcess(0),
            rss_reader=lambda _pid: 1234,
            poll_interval_seconds=0,
            heartbeat_interval_seconds=0.1,
            lease_seconds=10,
        )
        result = supervisor.run(
            job_id=job_id,
            command=["python", "-m", "apps.worker.daily_task"],
            max_attempts=1,
        )
        assert result.status is ChildRunStatus.SUCCESS
        with factory() as session:
            job = session.get(JobRun, job_id)
            assert job is not None and job.status == "success"
            attempt = session.scalar(select(JobAttempt).where(JobAttempt.job_id == job_id))
            assert attempt is not None
            assert attempt.finished_at is not None
            assert attempt.exit_code == 0
            assert attempt.exit_type == "success"
            component = session.scalar(
                select(ComponentHeartbeat).where(
                    ComponentHeartbeat.component_instance_id == supervisor.component_instance_id
                )
            )
            assert component is not None
            assert component.current_job_id is None
            assert session.scalar(
                select(func.count()).select_from(JobEvent).where(
                    JobEvent.job_id == job_id,
                    JobEvent.event_type == "job_succeeded",
                )
            ) == 1
    finally:
        with factory.begin() as session:
            session.execute(
                text(
                    "UPDATE component_heartbeats SET current_job_id = NULL, "
                    "current_attempt_id = NULL WHERE component_instance_id LIKE :prefix"
                ),
                {"prefix": "worker-supervisor-%"},
            )
            session.execute(JobEvent.__table__.delete().where(JobEvent.job_id == job_id))
            session.execute(JobAttempt.__table__.delete().where(JobAttempt.job_id == job_id))
            session.execute(JobStageRun.__table__.delete().where(JobStageRun.job_id == job_id))
            session.execute(JobRun.__table__.delete().where(JobRun.job_id == job_id))
            session.execute(JobRun.__table__.delete().where(JobRun.job_id == parent_id))


def test_postgres_supervisor_failure_uses_fenced_fail_job(
    t12_postgres_factory,
) -> None:
    factory = t12_postgres_factory
    job_id = f"t22-pg-supervisor-fail-{time.time_ns()}"
    parent_id = f"{job_id}-parent"
    with factory() as session:
        session.add(
            JobRun(
                job_id=parent_id,
                job_name="range_sync",
                status="pending",
                started_at=datetime.now(UTC),
                success_count=0,
                failed_count=0,
                metadata_json={},
                job_kind="range_sync",
                data_source="douyin",
                config_version="v1",
                window_start=datetime(2026, 8, 5, tzinfo=UTC),
                window_end=datetime(2026, 8, 7, tzinfo=UTC),
                attempt_count=0,
                max_attempts=3,
                lease_epoch=0,
            )
        )
        session.commit()
        seeded_job = _seed_job(session, job_id, parent_job_id=parent_id, max_attempts=1)
        job_id = seeded_job.job_id
    try:
        supervisor = SubprocessSupervisor(
            control_session_factory=factory,
            popen_factory=lambda *_args, **_kwargs: FakeProcess(1),
            rss_reader=lambda _pid: 4321,
            poll_interval_seconds=0,
            heartbeat_interval_seconds=0.1,
            lease_seconds=10,
        )
        result = supervisor.run(
            job_id=job_id,
            command=["python", "-m", "apps.worker.daily_task"],
            max_attempts=3,
        )
        assert result.status is ChildRunStatus.FAILED
        assert result.attempts == 1
        with factory() as session:
            job = session.get(JobRun, job_id)
            assert job is not None and job.status == "failed"
            attempt = session.scalar(select(JobAttempt).where(JobAttempt.job_id == job_id))
            assert attempt is not None
            assert attempt.finished_at is not None
            assert attempt.exit_code == 1
            assert attempt.exit_type == "crashed"
            component = session.scalar(
                select(ComponentHeartbeat).where(
                    ComponentHeartbeat.component_instance_id == supervisor.component_instance_id
                )
            )
            assert component is not None and component.current_job_id is None
            assert session.scalar(
                select(func.count()).select_from(JobEvent).where(
                    JobEvent.job_id == job_id,
                    JobEvent.event_type == "job_failed",
                )
            ) == 1
    finally:
        with factory.begin() as session:
            session.execute(
                text(
                    "UPDATE component_heartbeats SET current_job_id = NULL, "
                    "current_attempt_id = NULL WHERE component_instance_id LIKE :prefix"
                ),
                {"prefix": "worker-supervisor-%"},
            )
            session.execute(JobEvent.__table__.delete().where(JobEvent.job_id == job_id))
            session.execute(JobAttempt.__table__.delete().where(JobAttempt.job_id == job_id))
            session.execute(JobStageRun.__table__.delete().where(JobStageRun.job_id == job_id))
            session.execute(JobRun.__table__.delete().where(JobRun.job_id == job_id))
            session.execute(JobRun.__table__.delete().where(JobRun.job_id == parent_id))


def test_postgres_retry_wait_is_reported_not_busy_when_db_budget_remains(
    t12_postgres_factory,
) -> None:
    factory = t12_postgres_factory
    job_id = f"t22-pg-retry-wait-{time.time_ns()}"
    parent_id = f"{job_id}-parent"
    with factory() as session:
        session.add(
            JobRun(
                job_id=parent_id,
                job_name="range_sync",
                status="pending",
                started_at=datetime.now(UTC),
                success_count=0,
                failed_count=0,
                metadata_json={},
                job_kind="range_sync",
                data_source="douyin",
                config_version="v1",
                window_start=datetime(2026, 8, 5, tzinfo=UTC),
                window_end=datetime(2026, 8, 7, tzinfo=UTC),
                attempt_count=0,
                max_attempts=3,
                lease_epoch=0,
            )
        )
        session.commit()
        seeded_job = _seed_job(session, job_id, parent_job_id=parent_id, max_attempts=3)
        job_id = seeded_job.job_id
    try:
        supervisor = SubprocessSupervisor(
            control_session_factory=factory,
            popen_factory=lambda *_args, **_kwargs: FakeProcess(1),
            rss_reader=lambda _pid: 1,
            poll_interval_seconds=0,
            heartbeat_interval_seconds=0.1,
            lease_seconds=10,
        )
        result = supervisor.run(
            job_id=job_id,
            command=["python", "-m", "apps.worker.daily_task"],
            max_attempts=3,
        )
        assert result.status is ChildRunStatus.RETRY_WAIT
        assert result.attempts == 1
        with factory() as session:
            job = session.get(JobRun, job_id)
            assert job is not None and job.status == "retry_wait"
            assert job.attempt_count == 1
    finally:
        with factory.begin() as session:
            session.execute(
                text(
                    "UPDATE component_heartbeats SET current_job_id = NULL, "
                    "current_attempt_id = NULL WHERE component_instance_id LIKE :prefix"
                ),
                {"prefix": "worker-supervisor-%"},
            )
            session.execute(JobEvent.__table__.delete().where(JobEvent.job_id == job_id))
            session.execute(JobAttempt.__table__.delete().where(JobAttempt.job_id == job_id))
            session.execute(JobStageRun.__table__.delete().where(JobStageRun.job_id == job_id))
            session.execute(JobRun.__table__.delete().where(JobRun.job_id == job_id))
            session.execute(JobRun.__table__.delete().where(JobRun.job_id == parent_id))


def test_postgres_long_stage_does_not_hold_job_lock_against_heartbeat(
    t12_postgres_factory,
) -> None:
    factory = t12_postgres_factory
    job_id = f"t22-pg-heartbeat-{time.time_ns()}"
    parent_id = f"{job_id}-parent"
    with factory() as session:
        session.add(
            JobRun(
                job_id=parent_id,
                job_name="range_sync",
                status="pending",
                started_at=datetime.now(UTC),
                success_count=0,
                failed_count=0,
                metadata_json={},
                job_kind="range_sync",
                data_source="douyin",
                config_version="v1",
                window_start=datetime(2026, 8, 5, tzinfo=UTC),
                window_end=datetime(2026, 8, 7, tzinfo=UTC),
                attempt_count=0,
                max_attempts=3,
                lease_epoch=0,
            )
        )
        session.commit()
        seeded_job = _seed_job(session, job_id, parent_job_id=parent_id)
        job_id = seeded_job.job_id
    entered = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []

    with factory.begin() as session:
        token = claim_job(
            session,
            job_id=job_id,
            lease_owner="scheduler-long-stage",
            component_instance_id=f"component-{job_id}",
            lease_seconds=10,
        )
    assert token is not None

    def collect(session: Session) -> None:
        entered.set()
        assert release.wait(timeout=5)

    def run_stage() -> None:
        try:
            run_daily_stages(
                factory,
                job_id=job_id,
                handlers={"collect": collect, "materialize": lambda _session: None, "settle": lambda _session: None},
                lease_owner=token.lease_owner,
                lease_epoch=token.lease_epoch,
                attempt_id=token.attempt_id,
                component_instance_id=token.component_instance_id,
            )
        except BaseException as exc:  # noqa: BLE001 - assert thread outcome below
            errors.append(exc)

    thread = threading.Thread(target=run_stage)
    thread.start()
    assert entered.wait(timeout=5)
    started = time.monotonic()
    with factory.begin() as session:
        assert heartbeat_job(session, token, lease_seconds=10)
    assert time.monotonic() - started < 2
    release.set()
    thread.join(timeout=5)
    assert not errors
    with factory.begin() as session:
        fail_job(
            session,
            token,
            failure_kind=FailureKind.TRANSIENT,
            error_code="test_cleanup",
            error_summary="test cleanup",
        )
    with factory.begin() as session:
        session.execute(JobEvent.__table__.delete().where(JobEvent.job_id == job_id))
        session.execute(JobAttempt.__table__.delete().where(JobAttempt.job_id == job_id))
        session.execute(JobStageRun.__table__.delete().where(JobStageRun.job_id == job_id))
        session.execute(JobRun.__table__.delete().where(JobRun.job_id == job_id))
        session.execute(JobRun.__table__.delete().where(JobRun.job_id == parent_id))
        session.execute(
            text("DELETE FROM component_heartbeats WHERE component_instance_id LIKE :prefix"),
            {"prefix": f"component-{job_id}%"},
        )

def test_postgres_stage_precommit_epoch_change_rolls_back_business_writes(
    t12_postgres_factory,
) -> None:
    factory = t12_postgres_factory
    job_id = f"t22-pg-stage-cas-{time.time_ns()}"
    parent_id = f"{job_id}-parent"
    with factory() as session:
        session.add(
            JobRun(
                job_id=parent_id,
                job_name="range_sync",
                status="pending",
                started_at=datetime.now(UTC),
                success_count=0,
                failed_count=0,
                metadata_json={},
                job_kind="range_sync",
                data_source="douyin",
                config_version="v1",
                window_start=datetime(2026, 8, 5, tzinfo=UTC),
                window_end=datetime(2026, 8, 7, tzinfo=UTC),
                attempt_count=0,
                max_attempts=3,
                lease_epoch=0,
            )
        )
        session.commit()
        seeded_job = _seed_job(session, job_id, parent_job_id=parent_id)
        job_id = seeded_job.job_id
    entered = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []
    with factory.begin() as session:
        old_token = claim_job(
            session,
            job_id=job_id,
            lease_owner="scheduler-old-stage",
            component_instance_id=f"component-{job_id}-old",
            lease_seconds=10,
        )
    assert old_token is not None

    def collect(session: Session) -> None:
        session.add(
            JobEvent(
                event_id=f"stage-cas-business-{job_id}",
                job_id=job_id,
                event_type="business_collect",
                actor_type="worker",
                payload_json={"should_rollback": True},
                occurred_at=datetime.now(UTC),
            )
        )
        entered.set()
        assert release.wait(timeout=5)

    def run_stage() -> None:
        try:
            run_daily_stages(
                factory,
                job_id=job_id,
                handlers={"collect": collect, "materialize": lambda _session: None, "settle": lambda _session: None},
                lease_owner=old_token.lease_owner,
                lease_epoch=old_token.lease_epoch,
                attempt_id=old_token.attempt_id,
                component_instance_id=old_token.component_instance_id,
            )
        except BaseException as exc:  # noqa: BLE001 - expected fenced failure
            errors.append(exc)

    thread = threading.Thread(target=run_stage)
    thread.start()
    assert entered.wait(timeout=5)
    with factory.begin() as session:
        session.execute(
            update(JobRun)
            .where(JobRun.job_id == job_id)
            .values(lease_expires_at=text("clock_timestamp() - interval '1 second'"))
        )
    with factory.begin() as session:
        new_token = claim_job(
            session,
            job_id=job_id,
            lease_owner="scheduler-new-stage",
            component_instance_id=f"component-{job_id}-new",
            lease_seconds=10,
        )
    assert new_token is not None and new_token.lease_epoch > old_token.lease_epoch
    release.set()
    thread.join(timeout=5)
    assert errors and isinstance(errors[0], RuntimeError)
    with factory() as session:
        assert session.get(JobEvent, f"stage-cas-business-{job_id}") is None
        stage = session.scalar(
            select(JobStageRun).where(
                JobStageRun.job_id == job_id,
                JobStageRun.stage_name == "collect",
            )
        )
        assert stage is None or stage.status != "success"
    with factory.begin() as session:
        session.execute(
            text(
                "UPDATE component_heartbeats SET current_job_id = NULL, "
                "current_attempt_id = NULL WHERE component_instance_id LIKE :prefix"
            ),
            {"prefix": f"component-{job_id}%"},
        )
        session.execute(JobEvent.__table__.delete().where(JobEvent.job_id == job_id))
        session.execute(JobAttempt.__table__.delete().where(JobAttempt.job_id == job_id))
        session.execute(JobStageRun.__table__.delete().where(JobStageRun.job_id == job_id))
        session.execute(JobRun.__table__.delete().where(JobRun.job_id == job_id))
        session.execute(JobRun.__table__.delete().where(JobRun.job_id == parent_id))
        session.execute(
            text("DELETE FROM component_heartbeats WHERE component_instance_id LIKE :prefix"),
            {"prefix": f"component-{job_id}%"},
        )
