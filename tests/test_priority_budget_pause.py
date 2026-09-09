from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from apps.api.dy_api.models import JobRun
from apps.worker.daily_windows import plan_daily_sync
from apps.worker.subprocess_supervisor import (
    ChildTerminationReason,
    _is_priority_budget_pause,
)
from apps.worker.task_control import (
    FailureKind,
    claim_job,
    fail_job,
    retry_policy,
)


def _seed_job(session: Session, *, config_version: str = "priority-daily-v1") -> JobRun:
    plan = plan_daily_sync(
        session,
        start=date(2026, 9, 9),
        end=date(2026, 9, 10),
        target="orders",
        requested_by="priority-budget-test",
        trigger_source="test",
        config_version=config_version,
    )
    job = session.get(JobRun, plan.daily_jobs[0].job_id)
    assert job is not None
    return job


def _claim(session: Session, job: JobRun, *, component: str = "budget-worker"):
    token = claim_job(
        session,
        job_id=job.job_id,
        lease_owner=f"budget-owner-{component}",
        component_instance_id=component,
        lease_seconds=60,
    )
    assert token is not None
    return token


def _make_retry_ready(session: Session, job: JobRun) -> None:
    job.next_retry_at = datetime.now(UTC) - timedelta(seconds=1)
    session.flush()


def test_budget_pauses_extend_claim_window_without_consuming_real_attempts(
    db_session: Session,
) -> None:
    job = _seed_job(db_session)

    for _pause_number in range(4):
        token = _claim(db_session, job)
        decision = fail_job(
            db_session,
            token,
            failure_kind=FailureKind.BUDGET_PAUSE,
            error_code="quota_exhausted",
            error_summary="priority_budget_pause retry_after_seconds=60",
            fixed_delay_seconds=60,
        )
        assert decision is not None
        assert decision.status == "retry_wait"
        assert decision.delay_seconds == 60
        db_session.commit()
        job = db_session.get(JobRun, job.job_id)
        assert job is not None
        _make_retry_ready(db_session, job)

    assert job.attempt_count == 4
    assert job.lease_epoch == 4
    assert job.quota_pause_count == 4

    real_decisions = []
    for _failure_number in range(3):
        token = _claim(db_session, job)
        decision = fail_job(
            db_session,
            token,
            failure_kind=FailureKind.TRANSIENT,
            error_code="upstream_error",
            error_summary="upstream unavailable",
            fixed_delay_seconds=1,
        )
        assert decision is not None
        real_decisions.append(decision.status)
        if decision.status == "retry_wait":
            db_session.commit()
            job = db_session.get(JobRun, job.job_id)
            assert job is not None
            _make_retry_ready(db_session, job)

    assert real_decisions == ["retry_wait", "retry_wait", "failed"]
    assert job.attempt_count == 7
    assert job.lease_epoch == 7
    assert job.quota_pause_count == 4
    assert job.status == "failed"


def test_stale_lease_cannot_record_budget_pause(db_session: Session) -> None:
    job = _seed_job(db_session)
    token = _claim(db_session, job)
    job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.flush()

    decision = fail_job(
        db_session,
        token,
        failure_kind=FailureKind.BUDGET_PAUSE,
        error_code="quota_exhausted",
        error_summary="priority_budget_pause retry_after_seconds=60",
        fixed_delay_seconds=60,
    )

    assert decision is None
    assert job.status == "running"
    assert job.quota_pause_count == 0


def test_retry_policy_uses_effective_attempt_count_after_pauses() -> None:
    assert retry_policy(
        FailureKind.TRANSIENT,
        attempt_number=4,
        quota_pause_count=2,
        max_attempts=3,
    ).status == "retry_wait"
    assert retry_policy(
        FailureKind.TRANSIENT,
        attempt_number=4,
        quota_pause_count=2,
        max_attempts=3,
    ).delay_seconds == 60
    assert retry_policy(
        FailureKind.TRANSIENT,
        attempt_number=5,
        quota_pause_count=2,
        max_attempts=3,
    ).status == "failed"
    assert retry_policy(
        FailureKind.BUDGET_PAUSE,
        attempt_number=99,
        quota_pause_count=99,
        max_attempts=3,
        fixed_delay_seconds=200000,
    ).delay_seconds == 172800


def test_supervisor_budget_marker_is_limited_to_priority_process_exit(
    db_session: Session,
) -> None:
    job = _seed_job(db_session)
    summary = "priority_budget_pause retry_after_seconds=60"

    assert _is_priority_budget_pause(
        db_session,
        job_id=job.job_id,
        exit_code=1,
        termination_reason=ChildTerminationReason.PROCESS_EXIT,
        error_summary=summary,
    ) is True
    assert _is_priority_budget_pause(
        db_session,
        job_id=job.job_id,
        exit_code=1,
        termination_reason=ChildTerminationReason.TIMEOUT,
        error_summary=summary,
    ) is False
    assert _is_priority_budget_pause(
        db_session,
        job_id=job.job_id,
        exit_code=1,
        termination_reason=ChildTerminationReason.PROCESS_EXIT,
        error_summary="priority_budget_pause retry_after_seconds=0",
    ) is False

    legacy_job = _seed_job(db_session, config_version="daily-sync-v3")
    assert _is_priority_budget_pause(
        db_session,
        job_id=legacy_job.job_id,
        exit_code=1,
        termination_reason=ChildTerminationReason.PROCESS_EXIT,
        error_summary=summary,
    ) is False


def test_upgrade_from_0052_defaults_pause_counter_and_enforces_new_bound(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "priority-budget-pause.sqlite"
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")

    command.upgrade(config, "20260909_0052")
    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO job_runs "
                "(job_id, job_name, status, started_at, success_count, failed_count, metadata_json) "
                "VALUES ('old-row', 'legacy', 'pending', CURRENT_TIMESTAMP, 0, 0, '{}')"
            )
        )

    command.upgrade(config, "head")
    inspector = inspect(engine)
    columns = {column["name"]: column for column in inspector.get_columns("job_runs")}
    assert columns["quota_pause_count"]["nullable"] is False
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT quota_pause_count FROM job_runs WHERE job_id = 'old-row'")
        ).scalar_one() == 0
        connection.execute(
            text(
                "UPDATE job_runs SET attempt_count=4, max_attempts=3, "
                "quota_pause_count=1 WHERE job_id='old-row'"
            )
        )
        connection.commit()
        try:
            connection.execute(
                text(
                    "UPDATE job_runs SET attempt_count=5, max_attempts=3, "
                    "quota_pause_count=1 WHERE job_id='old-row'"
                )
            )
            connection.commit()
        except Exception:
            connection.rollback()
        else:
            raise AssertionError("new SQLite attempt bound did not reject an overrun")
    engine.dispose()
