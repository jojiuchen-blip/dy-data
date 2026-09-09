"""PostgreSQL evidence for bounded priority budget pauses.

The gate reads only ``DY_RELEASE_POSTGRES_URL``.  It accepts the disposable
loopback ``dydata_release`` database used by the release workflow, creates a
random schema for every module run, and drops that schema during teardown.
Application tables and generic database URL environment variables are never
used.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.db import normalize_database_url
from apps.api.dy_api.models import (
    Base,
    ComponentHeartbeat,
    JobAttempt,
    JobEvent,
    JobRun,
    JobStageRun,
)
from apps.worker.daily_windows import plan_daily_sync
from apps.worker.task_control import FailureKind, claim_job, fail_job


POSTGRES_ENV_NAME = "DY_RELEASE_POSTGRES_URL"
POSTGRES_URL = os.getenv(POSTGRES_ENV_NAME)
pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason=f"set {POSTGRES_ENV_NAME} to the disposable release PostgreSQL database",
)

CONTROL_TABLES = [
    JobRun.__table__,
    JobStageRun.__table__,
    ComponentHeartbeat.__table__,
    JobAttempt.__table__,
    JobEvent.__table__,
]


def _validated_postgres_url(raw_url: str) -> URL:
    """Allow only the loopback release gate database for this integration test."""

    url = make_url(normalize_database_url(raw_url))
    if not url.drivername.startswith("postgresql"):
        raise RuntimeError("budget-pause PostgreSQL evidence requires a PostgreSQL driver")
    if url.host not in {"127.0.0.1", "localhost"} or url.database != "dydata_release":
        raise RuntimeError(
            "budget-pause test requires the loopback dydata_release database"
        )
    return url


@pytest.fixture(scope="module")
def postgres_stack() -> tuple[object, sessionmaker[Session]]:
    """Create control-plane tables in one disposable random schema."""

    assert POSTGRES_URL is not None
    url = _validated_postgres_url(POSTGRES_URL)
    schema = f"budget_pause_gate_{uuid4().hex}"
    admin_engine = create_engine(url, future=True)
    engine = None
    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_engine(
            url,
            connect_args={
                "options": (
                    f"-c search_path={schema} "
                    "-c lock_timeout=5000 "
                    "-c statement_timeout=15000"
                )
            },
            future=True,
        )
        Base.metadata.create_all(engine, tables=CONTROL_TABLES)
        factory = sessionmaker(
            bind=engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            future=True,
        )
        yield engine, factory
    finally:
        if engine is not None:
            engine.dispose()
        admin_engine.dispose()
        cleanup_engine = create_engine(url, future=True)
        try:
            with cleanup_engine.begin() as connection:
                connection.execute(
                    text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
                )
        finally:
            cleanup_engine.dispose()


@pytest.fixture(autouse=True)
def clear_control_plane(
    postgres_stack: tuple[object, sessionmaker[Session]],
) -> None:
    engine, _factory = postgres_stack
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE TABLE job_events, job_attempts, component_heartbeats, "
                "job_stage_runs, job_runs CASCADE"
            )
        )


def _seed_priority_job(factory: sessionmaker[Session]) -> str:
    with factory.begin() as session:
        plan = plan_daily_sync(
            session,
            start=date(2026, 9, 9),
            end=date(2026, 9, 10),
            target="orders",
            requested_by="priority-budget-postgres-test",
            trigger_source="test",
            config_version="priority-daily-v1",
        )
        job = session.get(JobRun, plan.daily_jobs[0].job_id)
        assert job is not None
        return job.job_id


def _claim(
    factory: sessionmaker[Session],
    job_id: str,
    *,
    component: str = "budget-pause-postgres-worker",
):
    with factory.begin() as session:
        token = claim_job(
            session,
            job_id=job_id,
            lease_owner=f"budget-pause-owner-{component}",
            component_instance_id=component,
            lease_seconds=60,
        )
        assert token is not None
        return token


def _make_retry_ready(factory: sessionmaker[Session], job_id: str) -> None:
    with factory.begin() as session:
        job = session.get(JobRun, job_id)
        assert job is not None
        job.next_retry_at = datetime.now(UTC) - timedelta(seconds=1)
        session.flush()


def _pause(factory: sessionmaker[Session], token) -> None:
    with factory.begin() as session:
        decision = fail_job(
            session,
            token,
            failure_kind=FailureKind.BUDGET_PAUSE,
            error_code="quota_exhausted",
            error_summary="priority_budget_pause retry_after_seconds=60",
            fixed_delay_seconds=60,
        )
        assert decision is not None
        assert decision.status == "retry_wait"
        assert decision.delay_seconds == 60


def _run_budget_pauses(
    factory: sessionmaker[Session],
    job_id: str,
    *,
    count: int,
) -> None:
    for _ in range(count):
        _pause(factory, _claim(factory, job_id))
        _make_retry_ready(factory, job_id)


def _job_snapshot(
    factory: sessionmaker[Session],
    job_id: str,
) -> tuple[str, int, int, int]:
    with factory() as session:
        job = session.get(JobRun, job_id)
        assert job is not None
        return (
            job.status,
            int(job.attempt_count or 0),
            int(job.lease_epoch or 0),
            int(job.quota_pause_count or 0),
        )


def test_postgres_four_budget_pauses_still_allow_a_claim(
    postgres_stack: tuple[object, sessionmaker[Session]],
) -> None:
    _engine, factory = postgres_stack
    job_id = _seed_priority_job(factory)

    _run_budget_pauses(factory, job_id, count=4)

    status, attempt_count, lease_epoch, pause_count = _job_snapshot(factory, job_id)
    assert (status, attempt_count, lease_epoch, pause_count) == (
        "retry_wait",
        4,
        4,
        4,
    )
    token = _claim(factory, job_id)
    assert token.attempt_number == 5


def test_postgres_three_genuine_failures_eventually_fail_after_pauses(
    postgres_stack: tuple[object, sessionmaker[Session]],
) -> None:
    _engine, factory = postgres_stack
    job_id = _seed_priority_job(factory)
    _run_budget_pauses(factory, job_id, count=4)

    decisions = []
    for failure_number in range(3):
        token = _claim(factory, job_id)
        with factory.begin() as session:
            decision = fail_job(
                session,
                token,
                failure_kind=FailureKind.TRANSIENT,
                error_code="upstream_error",
                error_summary="upstream unavailable",
                fixed_delay_seconds=1,
            )
            assert decision is not None
            decisions.append(decision.status)
        if failure_number < 2:
            _make_retry_ready(factory, job_id)

    assert decisions == ["retry_wait", "retry_wait", "failed"]
    assert _job_snapshot(factory, job_id) == ("failed", 7, 7, 4)
    with factory() as session:
        attempts = list(
            session.scalars(
                select(JobAttempt)
                .where(JobAttempt.job_id == job_id)
                .order_by(JobAttempt.attempt_number)
            )
        )
        assert [attempt.error_code for attempt in attempts[:4]] == [
            "priority_budget_pause"
        ] * 4
        assert [attempt.error_code for attempt in attempts[4:]] == [
            "upstream_error"
        ] * 3


def test_postgres_expired_lease_rejects_budget_pause_counter_change(
    postgres_stack: tuple[object, sessionmaker[Session]],
) -> None:
    _engine, factory = postgres_stack
    job_id = _seed_priority_job(factory)
    token = _claim(factory, job_id)

    with factory.begin() as session:
        job = session.get(JobRun, job_id)
        assert job is not None
        job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.flush()
        decision = fail_job(
            session,
            token,
            failure_kind=FailureKind.BUDGET_PAUSE,
            error_code="quota_exhausted",
            error_summary="priority_budget_pause retry_after_seconds=60",
            fixed_delay_seconds=60,
        )
        assert decision is None

    assert _job_snapshot(factory, job_id) == ("running", 1, 1, 0)
