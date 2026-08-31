"""Opt-in PostgreSQL evidence for the T1.2 lease state machine.

The tests accept only ``DYDATA_T12_TEST_DATABASE_URL`` and reject URLs that are
not the dedicated loopback disposable database. They never fall back to the
application's generic database environment variables.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from threading import Event
from time import monotonic

import pytest
from sqlalchemy import create_engine, func, select, text, update
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql.dml import Update

from apps.api.dy_api.db import normalize_database_url
from apps.api.dy_api.models import (
    Base,
    ComponentMetricSample,
    ComponentHeartbeat,
    JobAttempt,
    JobEvent,
    JobRun,
    JobStageRun,
    OpsCommand,
)
from apps.worker import repositories
from apps.worker.daily_windows import plan_daily_sync
from apps.worker.repositories import HEAVY_SYNC_CLAIM_LOCK_KEY
from apps.worker.task_control import (
    FailureKind,
    advisory_lock_key,
    claim_next_job,
    complete_job,
    confirm_cancel_job,
    fail_job,
    heartbeat_job,
)


POSTGRES_ENV_NAME = "DYDATA_T12_TEST_DATABASE_URL"
POSTGRES_URL = os.getenv(POSTGRES_ENV_NAME)
pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason=f"set {POSTGRES_ENV_NAME} to the dedicated disposable PostgreSQL database",
)
CONTROL_TABLES = [
    JobRun.__table__,
    JobStageRun.__table__,
    ComponentHeartbeat.__table__,
    JobAttempt.__table__,
    JobEvent.__table__,
    ComponentMetricSample.__table__,
    OpsCommand.__table__,
]


def _validated_postgres_url(raw_url: str) -> URL:
    url = make_url(normalize_database_url(raw_url))
    if not url.drivername.startswith("postgresql+"):
        raise RuntimeError("T1.2 PostgreSQL evidence requires a PostgreSQL driver")
    if url.host not in {"127.0.0.1", "localhost"}:
        raise RuntimeError("T1.2 test database must use a loopback host")
    if url.port != 55432:
        raise RuntimeError("T1.2 test database must use the dedicated port 55432")
    if url.database != "dydata_t12":
        raise RuntimeError("T1.2 test database must be named dydata_t12")
    if url.username != "dydata_t12":
        raise RuntimeError("T1.2 test database must use the dedicated test role")
    return url


@pytest.mark.parametrize(
    "unsafe_url",
    [
        "postgresql+psycopg://dydata_t12:secret@db.example.com:55432/dydata_t12",
        "postgresql+psycopg://dydata_t12:secret@127.0.0.1:5432/dydata_t12",
        "postgresql+psycopg://dydata_t12:secret@127.0.0.1:55432/other_database",
        "postgresql+psycopg://postgres:secret@127.0.0.1:55432/dydata_t12",
    ],
)
def test_test_database_url_gate_rejects_non_dedicated_targets(
    unsafe_url: str,
) -> None:
    with pytest.raises(RuntimeError):
        _validated_postgres_url(unsafe_url)


@pytest.fixture(scope="module")
def postgres_stack() -> tuple[object, sessionmaker[Session]]:
    assert POSTGRES_URL is not None
    url = _validated_postgres_url(POSTGRES_URL)
    engine = create_engine(
        url,
        connect_args={"options": "-c lock_timeout=1000 -c statement_timeout=5000"},
        future=True,
    )
    Base.metadata.drop_all(engine, tables=CONTROL_TABLES)
    Base.metadata.create_all(engine, tables=CONTROL_TABLES)
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )
    try:
        yield engine, factory
    finally:
        Base.metadata.drop_all(engine, tables=CONTROL_TABLES)
        engine.dispose()


@pytest.fixture(autouse=True)
def clear_control_plane(postgres_stack: tuple[object, sessionmaker[Session]]) -> None:
    engine, _factory = postgres_stack
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE TABLE job_events, job_attempts, component_heartbeats, "
                "job_stage_runs, job_runs CASCADE"
            )
        )


def _seed_date_job(
    factory: sessionmaker[Session],
    *,
    job_id: str = "date-2026-08-05",
    business_date_value: date = date(2026, 8, 5),
    status: str = "pending",
    max_attempts: int = 3,
) -> JobRun:
    with factory.begin() as session:
        plan = plan_daily_sync(
            session,
            start=business_date_value,
            end=business_date_value + timedelta(days=1),
            target="orders",
            requested_by=job_id,
            trigger_source="test",
            data_source="douyin",
            config_version="v1",
        )
        child_id = plan.daily_jobs[0].job_id
        child = session.get(JobRun, child_id)
        if child is None:
            raise AssertionError("planner did not create a deterministic date child")
        child.status = status
        child.max_attempts = max_attempts
        child.current_stage = "collect"
        session.flush()
        return child


def _claim(
    session: Session,
    *,
    owner: str,
    component: str,
    lease_seconds: int = 60,
):
    return claim_next_job(
        session,
        lease_owner=owner,
        component_instance_id=component,
        lease_seconds=lease_seconds,
    )


CONTROL_PLANE_SNAPSHOT_KEYS = {
    "job_runs": "job_id",
    "job_stage_runs": "stage_run_id",
    "component_heartbeats": "component_instance_id",
    "job_attempts": "attempt_id",
    "job_events": "event_id",
    "component_metric_samples": "metric_sample_id",
    "ops_commands": "command_id",
}


def _control_plane_snapshot(factory: sessionmaker[Session]) -> dict[str, tuple[str, ...]]:
    with factory() as session:
        return {
            table_name: tuple(
                session.scalars(
                    text(
                        f"SELECT to_jsonb(snapshot_row)::text "
                        f"FROM {table_name} AS snapshot_row ORDER BY {primary_key}"
                    )
                )
            )
            for table_name, primary_key in CONTROL_PLANE_SNAPSHOT_KEYS.items()
        }


def _seed_other_running_worker_binding(
    factory: sessionmaker[Session],
    *,
    component_instance_id: str,
) -> tuple[str, str]:
    job_id = "other-running-job"
    attempt_id = "other-running-attempt"
    with factory.begin() as session:
        database_now = session.scalar(select(func.clock_timestamp()))
        assert database_now is not None
        component = ComponentHeartbeat(
            component_instance_id=component_instance_id,
            component_type="worker",
            status="healthy",
            started_at=database_now,
            last_heartbeat_at=database_now,
            activity_json={},
            queue_summary_json={},
            created_at=database_now,
            updated_at=database_now,
        )
        session.add_all(
            [
                JobRun(
                    job_id=job_id,
                    job_name="product_sync",
                    job_kind="product_sync",
                    status="running",
                    attempt_count=1,
                    max_attempts=3,
                    lease_owner="other-worker/process-1",
                    lease_epoch=1,
                    lease_expires_at=database_now + timedelta(minutes=5),
                    heartbeat_at=database_now,
                    started_at=database_now,
                    metadata_json={},
                ),
                component,
            ]
        )
        session.flush()
        session.add(
            JobAttempt(
                attempt_id=attempt_id,
                job_id=job_id,
                stage_run_id=None,
                attempt_number=1,
                lease_epoch=1,
                component_type="worker",
                component_instance_id=component_instance_id,
                started_at=database_now,
                created_at=database_now,
            )
        )
        session.flush()
        component.current_job_id = job_id
        component.current_attempt_id = attempt_id
    return job_id, attempt_id


def test_second_claim_does_not_block_or_duplicate_while_first_claim_is_open(
    postgres_stack: tuple[object, sessionmaker[Session]],
) -> None:
    _engine, factory = postgres_stack
    seeded = _seed_date_job(factory)

    first = factory()
    first.begin()
    first_token = _claim(first, owner="worker-a/process-1", component="worker-a")
    assert first_token is not None

    def claim_from_second_worker():
        with factory.begin() as second:
            return _claim(second, owner="worker-b/process-1", component="worker-b")

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            second_token = executor.submit(claim_from_second_worker).result(timeout=2)
        assert second_token is None
        first.commit()
    finally:
        first.close()

    with factory() as session:
        assert session.scalar(select(func.count()).select_from(JobAttempt)) == 1
        job = session.get(JobRun, seeded.job_id)
        assert job is not None
        assert job.status == "running"
        assert job.lease_owner == "worker-a/process-1"


def test_second_claim_does_not_block_when_pollers_share_component_identity(
    postgres_stack: tuple[object, sessionmaker[Session]],
) -> None:
    _engine, factory = postgres_stack
    _seed_date_job(factory)
    first = factory()
    first.begin()
    assert _claim(
        first,
        owner="worker-a/process-1",
        component="worker-a",
    ) is not None

    def poll_from_same_component():
        with factory.begin() as second:
            return _claim(
                second,
                owner="worker-a/process-2",
                component="worker-a",
            )

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            second_token = executor.submit(poll_from_same_component).result(timeout=2)
        assert second_token is None
        first.commit()
    finally:
        first.close()


def test_global_claim_lock_precedes_candidate_lock_under_two_date_race(
    postgres_stack: tuple[object, sessionmaker[Session]],
) -> None:
    engine, factory = postgres_stack
    _seed_date_job(factory, job_id="date-a", business_date_value=date(2026, 8, 4))
    _seed_date_job(factory, job_id="date-b", business_date_value=date(2026, 8, 5))
    candidate_locked = Event()
    winner_committed = Event()

    class PauseAfterCandidateSession(Session):
        def scalar(self, statement, *args, **kwargs):  # type: ignore[no-untyped-def]
            result = super().scalar(statement, *args, **kwargs)
            for_update = getattr(statement, "_for_update_arg", None)
            if for_update is not None and bool(for_update.skip_locked):
                candidate_locked.set()
                if not winner_committed.wait(timeout=5):
                    raise TimeoutError("winner did not finish while candidate row was held")
            return result

    paused_factory = sessionmaker(
        bind=engine,
        class_=PauseAfterCandidateSession,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )

    def delayed_claim():
        try:
            with paused_factory.begin() as session:
                token = _claim(
                    session,
                    owner="worker-a/process-1",
                    component="worker-a",
                )
            return token, None
        except Exception as exc:  # noqa: BLE001 - the race must surface any DB error
            return None, exc

    def competing_claim():
        if not candidate_locked.wait(timeout=5):
            return None, TimeoutError("delayed claimant never locked a candidate")
        try:
            with factory.begin() as session:
                token = _claim(
                    session,
                    owner="worker-b/process-1",
                    component="worker-b",
                )
            return token, None
        except Exception as exc:  # noqa: BLE001 - assertion reports exact race failure
            return None, exc
        finally:
            winner_committed.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        delayed_future = executor.submit(delayed_claim)
        competing_future = executor.submit(competing_claim)
        delayed_token, delayed_error = delayed_future.result(timeout=8)
        competing_token, competing_error = competing_future.result(timeout=8)

    assert delayed_error is None
    assert competing_error is None
    assert sum(token is not None for token in (delayed_token, competing_token)) == 1
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(JobAttempt)) == 1
        assert session.scalar(
            select(func.count()).select_from(JobRun).where(JobRun.status == "running")
        ) == 1


def test_skip_locked_is_exercised_after_global_lock_when_candidate_row_is_held(
    postgres_stack: tuple[object, sessionmaker[Session]],
) -> None:
    _engine, factory = postgres_stack
    seeded = _seed_date_job(factory)
    row_holder = factory()
    claimant = factory()
    row_holder.begin()
    claimant.begin()
    try:
        locked = row_holder.scalar(
            select(JobRun)
            .where(JobRun.job_id == seeded.job_id)
            .with_for_update()
        )
        assert locked is not None

        started = monotonic()
        assert _claim(
            claimant,
            owner="worker-a/process-1",
            component="worker-a",
        ) is None
        assert monotonic() - started < 1

        with factory.begin() as probe:
            assert not probe.scalar(
                select(func.pg_try_advisory_xact_lock(HEAVY_SYNC_CLAIM_LOCK_KEY))
            )
    finally:
        claimant.rollback()
        claimant.close()
        row_holder.rollback()
        row_holder.close()


def test_valid_lease_cannot_be_stolen_and_success_is_never_reclaimed(
    postgres_stack: tuple[object, sessionmaker[Session]],
) -> None:
    _engine, factory = postgres_stack
    _seed_date_job(factory)
    with factory.begin() as session:
        token = _claim(session, owner="worker-a/process-1", component="worker-a")
    assert token is not None

    with factory.begin() as session:
        assert _claim(session, owner="worker-b/process-1", component="worker-b") is None
        assert complete_job(session, token, success_count=11)

    with factory.begin() as session:
        assert _claim(session, owner="worker-b/process-2", component="worker-b") is None


def test_expired_lease_is_taken_over_with_new_epoch_and_old_epoch_is_fenced(
    postgres_stack: tuple[object, sessionmaker[Session]],
) -> None:
    _engine, factory = postgres_stack
    _seed_date_job(factory)
    with factory.begin() as session:
        old_token = _claim(session, owner="worker-a/process-1", component="worker-a")
    assert old_token is not None

    with factory.begin() as session:
        known_heartbeat = datetime(2026, 8, 1, tzinfo=UTC)
        session.execute(
            update(JobRun)
            .where(JobRun.job_id == old_token.job_id)
            .values(
                heartbeat_at=known_heartbeat,
                lease_expires_at=func.now() - text("INTERVAL '1 second'"),
            )
        )
        session.execute(
            update(ComponentHeartbeat)
            .where(ComponentHeartbeat.component_instance_id == "worker-a")
            .values(last_heartbeat_at=known_heartbeat)
        )

    with factory.begin() as session:
        new_token = _claim(session, owner="worker-b/process-1", component="worker-b")
    assert new_token is not None
    assert new_token.lease_epoch == old_token.lease_epoch + 1
    assert new_token.attempt_number == old_token.attempt_number + 1

    with factory.begin() as session:
        assert not heartbeat_job(session, old_token, lease_seconds=60)
        assert not complete_job(session, old_token)
        assert fail_job(
            session,
            old_token,
            failure_kind=FailureKind.TRANSIENT,
            error_code="late-worker",
            error_summary="old owner returned late",
        ) is None
        assert not confirm_cancel_job(session, old_token, reason="late cancel")

    with factory() as session:
        attempts = list(
            session.scalars(
                select(JobAttempt)
                .where(JobAttempt.job_id == old_token.job_id)
                .order_by(JobAttempt.attempt_number)
            )
        )
        assert [attempt.exit_type for attempt in attempts] == ["crashed", None]
        job = session.get(JobRun, old_token.job_id)
        assert job is not None and job.lease_owner == new_token.lease_owner
        old_worker = session.get(ComponentHeartbeat, "worker-a")
        assert job.heartbeat_at == known_heartbeat
        assert old_worker is not None
        assert old_worker.last_heartbeat_at == known_heartbeat


def test_expired_takeover_component_type_conflict_cannot_commit_partial_recovery(
    postgres_stack: tuple[object, sessionmaker[Session]],
) -> None:
    _engine, factory = postgres_stack
    _seed_date_job(factory)
    with factory.begin() as session:
        old_token = _claim(session, owner="worker-a/process-1", component="worker-a")
    assert old_token is not None

    with factory.begin() as session:
        database_now = session.scalar(select(func.clock_timestamp()))
        assert database_now is not None
        session.execute(
            update(JobRun)
            .where(JobRun.job_id == old_token.job_id)
            .values(
                lease_expires_at=func.clock_timestamp() - text("INTERVAL '1 second'")
            )
        )
        session.add(
            ComponentHeartbeat(
                component_instance_id="conflict",
                component_type="browser",
                status="healthy",
                started_at=database_now,
                last_heartbeat_at=database_now,
                activity_json={},
                queue_summary_json={},
                created_at=database_now,
                updated_at=database_now,
            )
        )

    before = _control_plane_snapshot(factory)
    with factory.begin() as session:
        try:
            _claim(
                session,
                owner="worker-b/process-1",
                component="conflict",
            )
        except RuntimeError:
            pass

    assert _control_plane_snapshot(factory) == before


def test_claim_cannot_rebind_worker_active_on_another_job_even_when_error_is_caught(
    postgres_stack: tuple[object, sessionmaker[Session]],
) -> None:
    _engine, factory = postgres_stack
    _seed_date_job(factory)
    _seed_other_running_worker_binding(
        factory,
        component_instance_id="busy-worker",
    )
    before = _control_plane_snapshot(factory)

    claimed = None
    with factory.begin() as session:
        try:
            claimed = _claim(
                session,
                owner="busy-worker/process-2",
                component="busy-worker",
            )
        except RuntimeError:
            pass

    assert _control_plane_snapshot(factory) == before
    assert claimed is None


def test_claim_cannot_rebind_worker_with_partial_current_job_binding(
    postgres_stack: tuple[object, sessionmaker[Session]],
) -> None:
    _engine, factory = postgres_stack
    seeded = _seed_date_job(factory)
    with factory.begin() as session:
        database_now = session.scalar(select(func.clock_timestamp()))
        assert database_now is not None
        session.add(
            ComponentHeartbeat(
                component_instance_id="partially-bound-worker",
                component_type="worker",
                status="degraded",
                started_at=database_now,
                last_heartbeat_at=database_now,
                current_job_id=seeded.parent_job_id,
                current_attempt_id=None,
                activity_json={},
                queue_summary_json={},
                created_at=database_now,
                updated_at=database_now,
            )
        )
    before = _control_plane_snapshot(factory)

    claimed = None
    with factory.begin() as session:
        try:
            claimed = _claim(
                session,
                owner="partially-bound-worker/process-1",
                component="partially-bound-worker",
            )
        except RuntimeError:
            pass

    assert _control_plane_snapshot(factory) == before
    assert claimed is None


def test_expired_takeover_missing_old_attempt_quarantines_without_new_component(
    postgres_stack: tuple[object, sessionmaker[Session]],
) -> None:
    _engine, factory = postgres_stack
    seeded = _seed_date_job(factory, status="running")
    with factory.begin() as session:
        session.execute(
            update(JobRun)
            .where(JobRun.job_id == seeded.job_id)
            .values(
                attempt_count=1,
                lease_owner="worker-a/process-1",
                lease_epoch=1,
                lease_expires_at=func.clock_timestamp() - text("INTERVAL '1 second'"),
            )
        )

    with factory.begin() as session:
        claimed = _claim(
            session,
            owner="worker-b/process-1",
            component="new-worker",
        )

    assert claimed is None
    with factory() as session:
        job = session.get(JobRun, seeded.job_id)
        assert job is not None
        assert job.status == "failed"
        assert job.error_code == "control_plane_identity_invalid"
        assert job.lease_owner is None
        assert job.lease_expires_at is None
        event = session.scalar(
            select(JobEvent).where(
                JobEvent.job_id == seeded.job_id,
                JobEvent.event_type == "job_quarantined",
            )
        )
        assert event is not None
        assert event.attempt_id is None
        assert (event.payload_json or {}).get("missing_attempt") is True
        assert session.get(ComponentHeartbeat, "new-worker") is None


def test_expired_takeover_allows_the_component_bound_to_that_exact_attempt(
    postgres_stack: tuple[object, sessionmaker[Session]],
) -> None:
    _engine, factory = postgres_stack
    _seed_date_job(factory)
    with factory.begin() as session:
        old_token = _claim(
            session,
            owner="worker-a/process-1",
            component="worker-a",
        )
    assert old_token is not None
    with factory.begin() as session:
        session.execute(
            update(JobRun)
            .where(JobRun.job_id == old_token.job_id)
            .values(
                lease_expires_at=func.clock_timestamp() - text("INTERVAL '1 second'")
            )
        )

    with factory.begin() as session:
        new_token = _claim(
            session,
            owner="worker-a/process-2",
            component="worker-a",
        )

    assert new_token is not None
    assert new_token.job_id == old_token.job_id
    assert new_token.attempt_number == old_token.attempt_number + 1
    assert new_token.lease_epoch == old_token.lease_epoch + 1
    with factory() as session:
        old_attempt = session.get(JobAttempt, old_token.attempt_id)
        component = session.get(ComponentHeartbeat, "worker-a")
        assert old_attempt is not None and old_attempt.exit_type == "crashed"
        assert component is not None
        assert component.current_job_id == new_token.job_id
        assert component.current_attempt_id == new_token.attempt_id


def test_expired_last_attempt_is_failed_atomically_without_creating_an_extra_attempt(
    postgres_stack: tuple[object, sessionmaker[Session]],
) -> None:
    _engine, factory = postgres_stack
    _seed_date_job(factory, max_attempts=1)
    with factory.begin() as session:
        token = _claim(session, owner="worker-a/process-1", component="worker-a")
    assert token is not None and token.attempt_number == 1
    with factory.begin() as session:
        known_heartbeat = datetime(2026, 8, 1, tzinfo=UTC)
        session.execute(
            update(JobRun)
            .where(JobRun.job_id == token.job_id)
            .values(
                heartbeat_at=known_heartbeat,
                lease_expires_at=func.now() - text("INTERVAL '1 second'"),
            )
        )
        session.execute(
            update(ComponentHeartbeat)
            .where(ComponentHeartbeat.component_instance_id == "worker-a")
            .values(last_heartbeat_at=known_heartbeat)
        )

    with factory.begin() as session:
        assert _claim(
            session,
            owner="worker-b/process-1",
            component="worker-b",
        ) is None

    with factory() as session:
        job = session.get(JobRun, token.job_id)
        attempt = session.get(JobAttempt, token.attempt_id)
        worker_a = session.get(ComponentHeartbeat, "worker-a")
        worker_b = session.get(ComponentHeartbeat, "worker-b")
        events = list(
            session.scalars(
                select(JobEvent)
                .where(JobEvent.job_id == token.job_id)
                .order_by(JobEvent.occurred_at, JobEvent.event_id)
            )
        )
        assert job is not None and job.status == "failed"
        assert job.attempt_count == 1
        assert job.lease_owner is None and job.lease_expires_at is None
        assert job.heartbeat_at == known_heartbeat
        assert attempt is not None and attempt.exit_type == "crashed"
        assert worker_a is not None and worker_a.current_attempt_id is None
        assert worker_a.last_heartbeat_at == known_heartbeat
        assert worker_b is None
        assert {event.event_type for event in events} >= {
            "lease_expired",
            "job_failed",
        }
        assert session.scalar(
            select(func.count()).select_from(JobAttempt).where(
                JobAttempt.job_id == token.job_id
            )
        ) == 1


def test_expired_current_token_cannot_mutate_without_takeover(
    postgres_stack: tuple[object, sessionmaker[Session]],
) -> None:
    _engine, factory = postgres_stack
    _seed_date_job(factory)
    with factory.begin() as session:
        token = _claim(session, owner="worker-a/process-1", component="worker-a")
    assert token is not None
    with factory.begin() as session:
        session.execute(
            update(JobRun)
            .where(JobRun.job_id == token.job_id)
            .values(lease_expires_at=func.now() - text("INTERVAL '1 second'"))
        )
    with factory.begin() as session:
        assert not heartbeat_job(session, token, lease_seconds=60)
        assert not complete_job(session, token)
        assert fail_job(
            session,
            token,
            failure_kind=FailureKind.TRANSIENT,
            error_code="expired",
            error_summary="expired",
        ) is None


@pytest.mark.parametrize("operation", ["heartbeat", "complete", "fail", "cancel"])
def test_mutations_use_actual_database_time_after_transaction_crosses_lease_expiry(
    postgres_stack: tuple[object, sessionmaker[Session]],
    operation: str,
) -> None:
    _engine, factory = postgres_stack
    _seed_date_job(factory)
    with factory.begin() as session:
        token = _claim(session, owner="worker-a/process-1", component="worker-a")
    assert token is not None

    with factory.begin() as session:
        transaction_started_at = session.scalar(select(func.now()))
        values: dict[str, object] = {
            "lease_expires_at": func.clock_timestamp()
            + text("INTERVAL '200 milliseconds'")
        }
        if operation == "cancel":
            values["cancel_requested_at"] = func.clock_timestamp()
        session.execute(
            update(JobRun).where(JobRun.job_id == token.job_id).values(**values)
        )
        session.execute(text("SELECT pg_sleep(0.35)"))
        actual_database_time = session.scalar(select(func.clock_timestamp()))
        job = session.get(JobRun, token.job_id)
        assert job is not None and job.lease_expires_at is not None
        assert transaction_started_at < job.lease_expires_at < actual_database_time

        if operation == "heartbeat":
            result = heartbeat_job(session, token, lease_seconds=60)
            assert result is False
        elif operation == "complete":
            assert complete_job(session, token) is False
        elif operation == "fail":
            assert fail_job(
                session,
                token,
                failure_kind=FailureKind.TRANSIENT,
                error_code="too_late",
                error_summary="lease expired while transaction remained open",
            ) is None
        else:
            assert confirm_cancel_job(session, token, reason="too late") is False


def test_expired_running_claim_uses_actual_database_time_not_transaction_start(
    postgres_stack: tuple[object, sessionmaker[Session]],
) -> None:
    _engine, factory = postgres_stack
    _seed_date_job(factory)
    with factory.begin() as session:
        old_token = _claim(session, owner="worker-a/process-1", component="worker-a")
    assert old_token is not None

    challenger = factory()
    challenger.begin()
    challenger.scalar(select(func.now()))
    try:
        with factory.begin() as updater:
            updater.execute(
                update(JobRun)
                .where(JobRun.job_id == old_token.job_id)
                .values(
                    lease_expires_at=func.clock_timestamp()
                    + text("INTERVAL '200 milliseconds'")
                )
            )
        challenger.execute(text("SELECT pg_sleep(0.35)"))
        new_token = _claim(
            challenger,
            owner="worker-b/process-1",
            component="worker-b",
        )
        assert new_token is not None
        assert new_token.lease_epoch == old_token.lease_epoch + 1
        challenger.commit()
    finally:
        challenger.close()


def test_due_retry_claim_uses_actual_database_time_not_transaction_start(
    postgres_stack: tuple[object, sessionmaker[Session]],
) -> None:
    _engine, factory = postgres_stack
    seeded = _seed_date_job(factory)

    challenger = factory()
    challenger.begin()
    challenger.scalar(select(func.now()))
    try:
        with factory.begin() as updater:
            updater.execute(
                update(JobRun)
                .where(JobRun.job_id == seeded.job_id)
                .values(
                    status="retry_wait",
                    next_retry_at=func.clock_timestamp()
                    + text("INTERVAL '200 milliseconds'"),
                )
            )
        challenger.execute(text("SELECT pg_sleep(0.35)"))
        token = _claim(
            challenger,
            owner="worker-a/process-1",
            component="worker-a",
        )
        assert token is not None
        challenger.commit()
    finally:
        challenger.close()


def test_cancel_confirmation_requires_a_recorded_control_intent(
    postgres_stack: tuple[object, sessionmaker[Session]],
) -> None:
    _engine, factory = postgres_stack
    _seed_date_job(factory)
    with factory.begin() as session:
        token = _claim(session, owner="worker-a/process-1", component="worker-a")
    assert token is not None

    with factory.begin() as session:
        assert not confirm_cancel_job(session, token, reason="no request exists")
    with factory() as session:
        job = session.get(JobRun, token.job_id)
        assert job is not None and job.status == "running"

    with factory.begin() as session:
        session.execute(
            update(JobRun)
            .where(JobRun.job_id == token.job_id)
            .values(cancel_requested_at=func.now())
        )
        assert confirm_cancel_job(session, token, reason="administrator requested cancel")
    with factory() as session:
        job = session.get(JobRun, token.job_id)
        assert job is not None and job.status == "cancelled"


@pytest.mark.parametrize(
    ("operation", "forged_field"),
    [
        ("heartbeat", "component"),
        ("complete", "attempt"),
        ("fail", "component"),
        ("cancel", "attempt"),
    ],
)
def test_forged_execution_token_cannot_leave_partial_state_when_error_is_caught(
    postgres_stack: tuple[object, sessionmaker[Session]],
    operation: str,
    forged_field: str,
) -> None:
    _engine, factory = postgres_stack
    _seed_date_job(factory)
    with factory.begin() as session:
        token = _claim(session, owner="worker-a/process-1", component="worker-a")
    assert token is not None
    if operation == "cancel":
        with factory.begin() as session:
            session.execute(
                update(JobRun)
                .where(JobRun.job_id == token.job_id)
                .values(cancel_requested_at=func.clock_timestamp())
            )

    forged_token = replace(
        token,
        attempt_id="forged-attempt" if forged_field == "attempt" else token.attempt_id,
        component_instance_id=(
            "forged-component"
            if forged_field == "component"
            else token.component_instance_id
        ),
    )
    before = _control_plane_snapshot(factory)

    with factory.begin() as session:
        try:
            if operation == "heartbeat":
                heartbeat_job(session, forged_token, lease_seconds=120)
            elif operation == "complete":
                complete_job(session, forged_token, success_count=7)
            elif operation == "fail":
                fail_job(
                    session,
                    forged_token,
                    failure_kind=FailureKind.TRANSIENT,
                    error_code="forged",
                    error_summary="forged execution identity",
                )
            else:
                confirm_cancel_job(session, forged_token, reason="forged cancel")
        except RuntimeError:
            pass

    assert _control_plane_snapshot(factory) == before


def test_claim_event_failure_rolls_back_transition_when_caller_commits(
    postgres_stack: tuple[object, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _engine, factory = postgres_stack
    _seed_date_job(factory)
    before = _control_plane_snapshot(factory)
    seen_events: list[str] = []

    def raise_at_event(*_args: object, **kwargs: object) -> None:
        seen_events.append(str(kwargs["event_type"]))
        raise RuntimeError("injected claim event failure")

    monkeypatch.setattr(repositories, "_add_job_event", raise_at_event)
    caught = False
    with factory.begin() as session:
        try:
            _claim(
                session,
                owner="worker-a/process-1",
                component="worker-a",
            )
        except RuntimeError:
            caught = True

    assert caught
    assert seen_events == ["job_claimed"]
    assert _control_plane_snapshot(factory) == before


def test_heartbeat_post_update_failure_rolls_back_transition_when_caller_commits(
    postgres_stack: tuple[object, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _engine, factory = postgres_stack
    _seed_date_job(factory)
    with factory.begin() as session:
        token = _claim(session, owner="worker-a/process-1", component="worker-a")
    assert token is not None
    before = _control_plane_snapshot(factory)

    injected = False
    caught = False
    with factory.begin() as session:
        original_execute = session.execute

        def execute_with_fault(statement: object, *args: object, **kwargs: object):
            nonlocal injected
            result = original_execute(statement, *args, **kwargs)
            if (
                not injected
                and isinstance(statement, Update)
                and statement.table.name == JobRun.__tablename__
            ):
                injected = True
                raise RuntimeError("injected failure after heartbeat JobRun update")
            return result

        monkeypatch.setattr(session, "execute", execute_with_fault)
        try:
            heartbeat_job(session, token, lease_seconds=120)
        except RuntimeError:
            caught = True

    assert injected and caught
    assert _control_plane_snapshot(factory) == before


@pytest.mark.parametrize("operation", ["complete", "fail", "cancel"])
def test_terminal_transition_event_failure_rolls_back_all_writes_when_caller_commits(
    postgres_stack: tuple[object, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    _engine, factory = postgres_stack
    _seed_date_job(factory)
    with factory.begin() as session:
        token = _claim(session, owner="worker-a/process-1", component="worker-a")
    assert token is not None
    if operation == "cancel":
        with factory.begin() as session:
            session.execute(
                update(JobRun)
                .where(JobRun.job_id == token.job_id)
                .values(cancel_requested_at=func.clock_timestamp())
            )
    before = _control_plane_snapshot(factory)
    seen_events: list[str] = []

    def raise_at_event(*_args: object, **kwargs: object) -> None:
        seen_events.append(str(kwargs["event_type"]))
        raise RuntimeError(f"injected {operation} event failure")

    monkeypatch.setattr(repositories, "_add_job_event", raise_at_event)
    caught = False
    with factory.begin() as session:
        try:
            if operation == "complete":
                complete_job(session, token, success_count=7)
            elif operation == "fail":
                fail_job(
                    session,
                    token,
                    failure_kind=FailureKind.TRANSIENT,
                    error_code="injected_failure",
                    error_summary="injected post-write failure",
                )
            else:
                confirm_cancel_job(session, token, reason="injected cancel failure")
        except RuntimeError:
            caught = True

    expected_event = {
        "complete": "job_succeeded",
        "fail": "job_retry_scheduled",
        "cancel": "job_cancelled",
    }[operation]
    assert caught
    assert seen_events == [expected_event]
    assert _control_plane_snapshot(factory) == before


def test_expired_final_attempt_event_failure_rolls_back_recovery_when_caller_commits(
    postgres_stack: tuple[object, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _engine, factory = postgres_stack
    _seed_date_job(factory, max_attempts=1)
    with factory.begin() as session:
        token = _claim(session, owner="worker-a/process-1", component="worker-a")
    assert token is not None
    with factory.begin() as session:
        session.execute(
            update(JobRun)
            .where(JobRun.job_id == token.job_id)
            .values(
                lease_expires_at=func.clock_timestamp() - text("INTERVAL '1 second'")
            )
        )
    before = _control_plane_snapshot(factory)
    original_add_job_event = repositories._add_job_event
    seen_events: list[str] = []

    def raise_at_terminal_event(*args: object, **kwargs: object) -> None:
        event_type = str(kwargs["event_type"])
        seen_events.append(event_type)
        if event_type == "job_failed":
            raise RuntimeError("injected final-attempt terminal event failure")
        original_add_job_event(*args, **kwargs)

    monkeypatch.setattr(repositories, "_add_job_event", raise_at_terminal_event)
    caught = False
    with factory.begin() as session:
        try:
            _claim(
                session,
                owner="worker-b/process-1",
                component="worker-b",
            )
        except RuntimeError:
            caught = True

    assert caught
    assert seen_events == ["lease_expired", "job_failed"]
    assert _control_plane_snapshot(factory) == before


def test_claim_savepoint_preserves_caller_pending_event_without_leaking_transition(
    postgres_stack: tuple[object, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _engine, factory = postgres_stack
    seeded = _seed_date_job(factory)
    before = _control_plane_snapshot(factory)

    def raise_at_event(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("injected claim event failure with caller pending state")

    monkeypatch.setattr(repositories, "_add_job_event", raise_at_event)
    caught = False
    with factory.begin() as session:
        database_now = session.scalar(select(func.clock_timestamp()))
        assert database_now is not None
        session.add(
            JobEvent(
                event_id="caller-pending-event",
                job_id=seeded.parent_job_id,
                stage_run_id=None,
                attempt_id=None,
                event_type="caller_pending",
                from_status=None,
                to_status=None,
                actor_type="system",
                actor_id=None,
                reason=None,
                payload_json={},
                occurred_at=database_now,
            )
        )
        try:
            _claim(
                session,
                owner="worker-a/process-1",
                component="worker-a",
            )
        except RuntimeError:
            caught = True

    after = _control_plane_snapshot(factory)
    assert caught
    for table_name in CONTROL_PLANE_SNAPSHOT_KEYS:
        if table_name != "job_events":
            assert after[table_name] == before[table_name]
    caller_events = tuple(
        row for row in after["job_events"] if '"event_id": "caller-pending-event"' in row
    )
    non_caller_events = tuple(
        row for row in after["job_events"] if row not in caller_events
    )
    assert len(caller_events) == 1
    assert non_caller_events == before["job_events"]


def test_legacy_running_row_with_null_lease_is_not_recovered(
    postgres_stack: tuple[object, sessionmaker[Session]],
) -> None:
    _engine, factory = postgres_stack
    _seed_date_job(factory, status="running")
    with factory.begin() as session:
        assert _claim(session, owner="worker-a/process-1", component="worker-a") is None
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(JobAttempt)) == 0


def test_failure_transition_writes_attempt_event_and_retry_in_one_transaction(
    postgres_stack: tuple[object, sessionmaker[Session]],
) -> None:
    _engine, factory = postgres_stack
    _seed_date_job(factory)
    with factory.begin() as session:
        token = _claim(session, owner="worker-a/process-1", component="worker-a")
    assert token is not None

    with factory.begin() as session:
        decision = fail_job(
            session,
            token,
            failure_kind=FailureKind.TRANSIENT,
            error_code="network_timeout",
            error_summary="upstream timed out",
            base_delay_seconds=30,
        )
        assert decision is not None and decision.status == "retry_wait"

    with factory() as session:
        job = session.get(JobRun, token.job_id)
        attempt = session.get(JobAttempt, token.attempt_id)
        event = session.scalar(
            select(JobEvent).where(JobEvent.event_type == "job_retry_scheduled")
        )
        database_now = session.scalar(select(func.now()))
        assert job is not None and job.status == "retry_wait"
        assert job.next_retry_at is not None and job.next_retry_at > database_now
        assert attempt is not None and attempt.exit_type == "retryable_failure"
        assert event is not None and event.attempt_id == token.attempt_id


def test_fail_uses_locked_database_retry_limit_not_stale_token_snapshot(
    postgres_stack: tuple[object, sessionmaker[Session]],
) -> None:
    _engine, factory = postgres_stack
    _seed_date_job(factory, max_attempts=3)
    with factory.begin() as session:
        token = _claim(session, owner="worker-a/process-1", component="worker-a")
    assert token is not None and token.attempt_number == 1

    with factory.begin() as session:
        session.execute(
            update(JobRun)
            .where(JobRun.job_id == token.job_id)
            .values(max_attempts=1)
        )

    with factory.begin() as session:
        decision = fail_job(
            session,
            token,
            failure_kind=FailureKind.TRANSIENT,
            error_code="temporary",
            error_summary="retry limit was reduced while the lease was active",
        )

    assert decision is not None and decision.status == "failed"
    with factory() as session:
        job = session.get(JobRun, token.job_id)
        assert job is not None and job.status == "failed"
        assert job.attempt_count == job.max_attempts == 1
        assert job.next_retry_at is None


def test_claim_persists_default_stage_and_clears_stale_current_errors(
    postgres_stack: tuple[object, sessionmaker[Session]],
) -> None:
    _engine, factory = postgres_stack
    seeded = _seed_date_job(factory)
    with factory.begin() as session:
        session.execute(
            update(JobRun)
            .where(JobRun.job_id == seeded.job_id)
            .values(
                current_stage=None,
                error_code="old_code",
                error_summary="old summary",
                error_message="old failure",
            )
        )

    with factory.begin() as session:
        token = _claim(session, owner="worker-a/process-1", component="worker-a")
    assert token is not None and token.current_stage == "collect"

    with factory() as session:
        job = session.get(JobRun, token.job_id)
        assert job is not None and job.current_stage == "collect"
        assert job.error_code is None
        assert job.error_summary is None
        assert job.error_message is None


def test_retry_claim_clears_all_previous_current_error_fields(
    postgres_stack: tuple[object, sessionmaker[Session]],
) -> None:
    _engine, factory = postgres_stack
    _seed_date_job(factory)
    with factory.begin() as session:
        first = _claim(session, owner="worker-a/process-1", component="worker-a")
    assert first is not None
    with factory.begin() as session:
        decision = fail_job(
            session,
            first,
            failure_kind=FailureKind.TRANSIENT,
            error_code="temporary",
            error_summary="first attempt failed",
        )
        assert decision is not None and decision.status == "retry_wait"
        session.execute(
            update(JobRun)
            .where(JobRun.job_id == first.job_id)
            .values(next_retry_at=func.now() - text("INTERVAL '1 second'"))
        )

    with factory.begin() as session:
        second = _claim(session, owner="worker-b/process-1", component="worker-b")
    assert second is not None

    with factory() as session:
        job = session.get(JobRun, second.job_id)
        assert job is not None and job.status == "running"
        assert job.error_code is None
        assert job.error_summary is None
        assert job.error_message is None


def test_consecutive_memory_guard_failure_becomes_fatal_on_second_attempt(
    postgres_stack: tuple[object, sessionmaker[Session]],
) -> None:
    _engine, factory = postgres_stack
    _seed_date_job(factory)
    with factory.begin() as session:
        first = _claim(session, owner="worker-a/process-1", component="worker-a")
    assert first is not None
    with factory.begin() as session:
        first_decision = fail_job(
            session,
            first,
            failure_kind=FailureKind.MEMORY_GUARD,
            error_code="rss_guard",
            error_summary="memory protection stopped the batch",
        )
    assert first_decision is not None and first_decision.status == "retry_wait"

    with factory.begin() as session:
        session.execute(
            update(JobRun)
            .where(JobRun.job_id == first.job_id)
            .values(next_retry_at=func.now() - text("INTERVAL '1 second'"))
        )
    with factory.begin() as session:
        second = _claim(session, owner="worker-b/process-1", component="worker-b")
    assert second is not None
    with factory.begin() as session:
        second_decision = fail_job(
            session,
            second,
            failure_kind=FailureKind.MEMORY_GUARD,
            error_code="rss_guard",
            error_summary="memory protection stopped the batch again",
        )
    assert second_decision is not None and second_decision.status == "failed"


def test_job_specific_retry_limit_cannot_leave_an_unclaimable_retry_wait_row(
    postgres_stack: tuple[object, sessionmaker[Session]],
) -> None:
    _engine, factory = postgres_stack
    _seed_date_job(factory, max_attempts=2)
    with factory.begin() as session:
        first = _claim(session, owner="worker-a/process-1", component="worker-a")
    assert first is not None
    with factory.begin() as session:
        first_decision = fail_job(
            session,
            first,
            failure_kind=FailureKind.TRANSIENT,
            error_code="temporary",
            error_summary="first temporary failure",
        )
    assert first_decision is not None and first_decision.status == "retry_wait"
    with factory.begin() as session:
        session.execute(
            update(JobRun)
            .where(JobRun.job_id == first.job_id)
            .values(next_retry_at=func.now() - text("INTERVAL '1 second'"))
        )
    with factory.begin() as session:
        second = _claim(session, owner="worker-b/process-1", component="worker-b")
    assert second is not None
    with factory.begin() as session:
        second_decision = fail_job(
            session,
            second,
            failure_kind=FailureKind.TRANSIENT,
            error_code="temporary",
            error_summary="second temporary failure",
        )
    assert second_decision is not None and second_decision.status == "failed"


def test_transaction_advisory_lock_blocks_claim_then_releases_at_transaction_end(
    postgres_stack: tuple[object, sessionmaker[Session]],
) -> None:
    _engine, factory = postgres_stack
    _seed_date_job(factory)
    key = advisory_lock_key(
        business_date=date(2026, 8, 5),
        data_source="douyin",
        config_version="v1",
    )
    lock_holder = factory()
    lock_holder.begin()
    assert lock_holder.scalar(select(func.pg_try_advisory_xact_lock(key)))
    try:
        with factory.begin() as session:
            assert _claim(session, owner="worker-a/process-1", component="worker-a") is None
    finally:
        lock_holder.commit()
        lock_holder.close()

    with factory.begin() as session:
        assert _claim(session, owner="worker-a/process-2", component="worker-a") is not None


def test_postgresql_unique_constraint_is_authoritative_for_heavy_running_slot(
    postgres_stack: tuple[object, sessionmaker[Session]],
) -> None:
    _engine, factory = postgres_stack
    first_seeded = _seed_date_job(
        factory, job_id="date-a", business_date_value=date(2026, 8, 4)
    )
    second_seeded = _seed_date_job(
        factory, job_id="date-b", business_date_value=date(2026, 8, 5)
    )
    with factory.begin() as session:
        first = session.get(JobRun, first_seeded.job_id)
        second = session.get(JobRun, second_seeded.job_id)
        assert first is not None and second is not None
        first.status = "running"
        session.flush()
        second.status = "running"
        with pytest.raises(IntegrityError):
            session.flush()
