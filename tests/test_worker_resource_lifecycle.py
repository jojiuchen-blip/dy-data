from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import io
import sys
import types
import pytest
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.models import JobAttempt, JobRun, JobStageRun
from apps.ops_agent.resources import ResourceAction, ResourceDecision
from apps.worker.daily_windows import plan_daily_sync
from apps.worker import repositories
from apps.worker.subprocess_supervisor import (
    ChildTerminationReason,
    ChildRunStatus,
    SubprocessSupervisor,
    _failure_kind,
    _scheduler_pause_marker,
    worker_resource_decision,
)
from apps.worker.task_control import FailureKind, claim_job, fail_job, retry_policy


def _seed_priority_job(
    session: Session,
    *,
    purpose: str = "daily_required",
    config_version: str = "priority-daily-v1",
    start: date = date(2026, 9, 9),
    complete_stages: bool = False,
) -> JobRun:
    plan = plan_daily_sync(
        session,
        start=start,
        end=start + timedelta(days=1),
        target="orders",
        requested_by="resource-lifecycle-test",
        trigger_source="test",
        config_version=config_version,
    )
    job = session.get(JobRun, plan.daily_jobs[0].job_id)
    assert job is not None
    job.metadata_json = {
        **(job.metadata_json or {}),
        "priority_purpose": purpose,
    }
    if complete_stages:
        now = datetime.now(UTC)
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


def _claim(session: Session, job: JobRun, *, component: str) -> object:
    token = claim_job(
        session,
        job_id=job.job_id,
        lease_owner=f"resource-owner-{component}",
        component_instance_id=component,
        lease_seconds=60,
    )
    assert token is not None
    return token


def _make_retry_ready(session: Session, job_id: str) -> JobRun:
    job = session.get(JobRun, job_id)
    assert job is not None
    job.next_retry_at = datetime.now(UTC) - timedelta(seconds=1)
    session.flush()
    return job


@pytest.mark.parametrize("version", ["priority-daily-v1", "priority-daily-v1-dimensions-2026091310"])
def test_resource_pause_retry_budget_is_separate_from_real_failures(
    db_session: Session,
    version: str,
) -> None:
    job = _seed_priority_job(db_session, config_version=version)

    for pause_number in range(4):
        token = _claim(db_session, job, component=f"resource-pause-{pause_number}")
        decision = fail_job(
            db_session,
            token,
            failure_kind=FailureKind.RESOURCE_PAUSE,
            error_code="ignored-by-classification",
            error_summary="worker_resource_pause retry_after_seconds=60",
            fixed_delay_seconds=60,
        )
        assert decision is not None
        assert decision.status == "retry_wait"
        assert decision.delay_seconds == 60
        assert job.failed_count == 0
        assert job.quota_pause_count == pause_number + 1
        db_session.commit()
        job = _make_retry_ready(db_session, job.job_id)
        db_session.commit()

    decisions: list[str] = []
    for failure_number in range(3):
        token = _claim(
            db_session,
            job,
            component=f"resource-real-failure-{failure_number}",
        )
        decision = fail_job(
            db_session,
            token,
            failure_kind=FailureKind.TRANSIENT,
            error_code="upstream_error",
            error_summary="upstream unavailable",
            fixed_delay_seconds=1,
        )
        assert decision is not None
        decisions.append(decision.status)
        if decision.status == "retry_wait":
            db_session.commit()
            _make_retry_ready(db_session, job.job_id)
            db_session.commit()

    assert decisions == ["retry_wait", "retry_wait", "failed"]
    assert job.attempt_count == 7
    assert job.quota_pause_count == 4
    assert job.failed_count == 1
    assert job.status == "failed"


def test_resource_pause_is_priority_daily_only(db_session: Session) -> None:
    legacy = _seed_priority_job(
        db_session,
        config_version="legacy-sync-v3",
        start=date(2026, 9, 8),
    )
    token = _claim(db_session, legacy, component="legacy-resource-pause")
    assert (
        fail_job(
            db_session,
            token,
            failure_kind=FailureKind.RESOURCE_PAUSE,
            error_code="worker_resource_pause",
            error_summary="worker_resource_pause retry_after_seconds=60",
            fixed_delay_seconds=60,
        )
        is None
    )
    assert legacy.status == "running"
    assert legacy.quota_pause_count == 0


def test_resource_drain_admits_daily_and_blocks_history_and_legacy() -> None:
    decision = ResourceDecision(ResourceAction.DRAIN, ("swap_used",))
    daily = SimpleNamespace(
        config_version="priority-daily-v1",
        metadata_json={"priority_purpose": "daily_required"},
    )
    history = SimpleNamespace(
        config_version="priority-daily-v1",
        metadata_json={"priority_purpose": "history"},
    )
    unmarked = SimpleNamespace(config_version="priority-daily-v1", metadata_json={})
    legacy = SimpleNamespace(
        config_version="legacy-sync-v3",
        metadata_json={"priority_purpose": "daily_required"},
    )

    assert repositories.resource_admission_allows_job(daily, decision) is True
    daily.config_version = "priority-daily-v1-dimensions-2026091310"
    assert repositories.resource_admission_allows_job(daily, decision) is True
    assert repositories.resource_admission_allows_job(history, decision) is False
    assert repositories.resource_admission_allows_job(unmarked, decision) is False
    assert repositories.resource_admission_allows_job(legacy, decision) is False
    assert repositories.resource_admission_allows_job(daily, ResourceDecision(ResourceAction.STOP, ())) is False


@pytest.mark.parametrize("version", ["priority-daily-v1", "priority-daily-v1-dimensions-2026091310"])
def test_scheduler_marker_classification_keeps_hard_rss_as_memory_guard(
    db_session: Session,
    version: str,
) -> None:
    job = _seed_priority_job(db_session, start=date(2026, 9, 7), config_version=version)
    summary = "worker_resource_pause retry_after_seconds=60"
    assert (
        _scheduler_pause_marker(
            db_session,
            job_id=job.job_id,
            exit_code=1,
            termination_reason=ChildTerminationReason.PROCESS_EXIT,
            error_summary=summary,
        )
        == "worker_resource_pause"
    )
    assert (
        _scheduler_pause_marker(
            db_session,
            job_id=job.job_id,
            exit_code=-9,
            termination_reason=ChildTerminationReason.RSS_GUARD,
            error_summary=summary,
        )
        is None
    )
    assert (
        _failure_kind(
            -9,
            termination_reason=ChildTerminationReason.RSS_GUARD,
            error_summary=summary,
            rss_peak_bytes=8,
            rss_limit_bytes=8,
        )
        is FailureKind.MEMORY_GUARD
    )
    assert retry_policy(
        FailureKind.RESOURCE_PAUSE,
        attempt_number=99,
        quota_pause_count=99,
        max_attempts=3,
        fixed_delay_seconds=60,
    ).delay_seconds == 60


@pytest.mark.parametrize("version", ["priority-daily-v1", "priority-daily-v1-dimensions-2026091310"])
def test_supervisor_persists_resource_pause_as_a_scheduler_yield(
    db_session: Session,
    monkeypatch,
    version: str,
) -> None:
    job = _seed_priority_job(db_session, start=date(2026, 9, 5), config_version=version)
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, future=True)
    monkeypatch.delenv("WORKER_RESOURCE_GUARD_ENABLED", raising=False)

    class Process:
        pid = 54322
        stdout = None
        stderr = io.StringIO(
            "worker_resource_pause retry_after_seconds=60\n"
        )

        def poll(self):
            return 1

        def wait(self, timeout=None):
            return 1

        def terminate(self):
            return None

        def kill(self):
            return None

    supervisor = SubprocessSupervisor(
        control_session_factory=factory,
        popen_factory=lambda *_args, **_kwargs: Process(),
        rss_reader=lambda _pid: 1,
        poll_interval_seconds=0,
    )
    result = supervisor.run(
        job_id=job.job_id,
        command=["python", "-m", "apps.worker.daily_task"],
        max_attempts=1,
    )

    assert result.status is ChildRunStatus.RETRY_WAIT
    with factory() as session:
        stored = session.get(JobRun, job.job_id)
        assert stored is not None
        assert stored.status == "retry_wait"
        assert stored.error_code == "worker_resource_pause"
        assert stored.quota_pause_count == 1
        assert stored.failed_count == 0
        attempt = session.scalar(
            select(JobAttempt).where(JobAttempt.job_id == job.job_id)
        )
        assert attempt is not None
        assert attempt.error_code == "worker_resource_pause"
        assert attempt.exit_type == "retryable_failure"


def test_worker_resource_decision_delegates_to_scheduler_monitor(monkeypatch) -> None:
    expected = ResourceDecision(ResourceAction.DRAIN, ("host_memory_warn",))
    monitor = types.ModuleType("apps.worker.resource_monitor")
    monitor.current_resource_decision = lambda: expected
    monkeypatch.setitem(sys.modules, "apps.worker.resource_monitor", monitor)
    monkeypatch.setenv("WORKER_RESOURCE_GUARD_ENABLED", "true")
    assert worker_resource_decision() is expected


def test_child_environment_preserves_resource_monitor_identity(
    db_session: Session,
    monkeypatch,
) -> None:
    job = _seed_priority_job(
        db_session,
        start=date(2026, 9, 6),
        complete_stages=True,
    )
    job_id = job.job_id
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, future=True)
    monkeypatch.setenv("DY_WORKER_RESOURCE_MONITOR_ID", "monitor-test-id")
    monkeypatch.delenv("WORKER_RESOURCE_GUARD_ENABLED", raising=False)
    captured: dict[str, str] = {}

    class Process:
        pid = 54321
        stdout = None
        stderr = None

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

        def terminate(self):
            return None

        def kill(self):
            return None

    def spawn(_command, *, env, **_kwargs):
        captured.update(env)
        return Process()

    supervisor = SubprocessSupervisor(
        control_session_factory=factory,
        popen_factory=spawn,
        rss_reader=lambda _pid: 1,
        poll_interval_seconds=0,
    )
    result = supervisor.run(
        job_id=job_id,
        command=["python", "-m", "apps.worker.daily_task"],
        max_attempts=1,
    )

    assert result.status is ChildRunStatus.SUCCESS
    assert captured["DY_WORKER_RESOURCE_MONITOR_ID"] == "monitor-test-id"
