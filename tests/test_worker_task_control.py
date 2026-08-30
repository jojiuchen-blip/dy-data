from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.api.dy_api.models import JobRun
from apps.worker import repositories
from apps.worker.task_control import (
    JOB_KINDS,
    JOB_STAGES,
    JOB_STATUSES,
    FailureKind,
    claim_next_job,
    retry_policy,
)


def test_control_plane_allowlists_are_explicit_and_legacy_compatible() -> None:
    assert JOB_KINDS == frozenset(
        {"range_sync", "parent_sync", "date_sync", "finalize", "product_sync"}
    )
    assert JOB_STAGES == frozenset(
        {"collect", "collect_dimensions", "materialize", "settle", "finalize"}
    )
    assert JOB_STATUSES == frozenset(
        {
            "pending",
            "queued",
            "running",
            "retry_wait",
            "success",
            "partial",
            "failed",
            "cancelled",
        }
    )


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("job_kind", "arbitrary_job"),
        ("current_stage", "load_everything"),
        ("status", "maybe_done"),
        ("max_attempts", 4),
    ],
)
def test_job_run_database_constraints_reject_unknown_state_machine_values(
    field_name: str,
    invalid_value: object,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    JobRun.__table__.create(engine)
    values: dict[str, object] = {
        "job_id": f"invalid-{field_name}",
        "job_name": "legacy-compatible",
        "status": "pending",
        "started_at": datetime(2026, 8, 6, tzinfo=UTC),
        "metadata_json": {},
    }
    values[field_name] = invalid_value
    with Session(engine) as session:
        with pytest.raises(IntegrityError):
            session.execute(JobRun.__table__.insert().values(**values))
            session.commit()
    engine.dispose()


@pytest.mark.parametrize(
    ("failure_kind", "attempt_number", "previous_exit_type", "status", "delay_seconds"),
    [
        (FailureKind.TRANSIENT, 1, None, "retry_wait", 30),
        (FailureKind.TRANSIENT, 2, None, "retry_wait", 60),
        (FailureKind.TRANSIENT, 3, None, "failed", None),
        (FailureKind.BROWSER, 1, None, "retry_wait", 30),
        (FailureKind.CRASHED, 1, None, "retry_wait", 30),
        (FailureKind.DATA_INTEGRITY, 1, None, "failed", None),
        (FailureKind.MEMORY_GUARD, 1, None, "retry_wait", 30),
        (FailureKind.MEMORY_GUARD, 2, "resource_guard", "failed", None),
    ],
)
def test_retry_policy_classifies_failures_and_caps_attempts(
    failure_kind: FailureKind,
    attempt_number: int,
    previous_exit_type: str | None,
    status: str,
    delay_seconds: int | None,
) -> None:
    decision = retry_policy(
        failure_kind,
        attempt_number=attempt_number,
        max_attempts=3,
        previous_exit_type=previous_exit_type,
        base_delay_seconds=30,
    )

    assert decision.status == status
    assert decision.delay_seconds == delay_seconds


def test_retry_policy_rejects_invalid_attempt_configuration() -> None:
    with pytest.raises(ValueError, match="attempt_number"):
        retry_policy(FailureKind.TRANSIENT, attempt_number=0, max_attempts=3)
    with pytest.raises(ValueError, match="max_attempts"):
        retry_policy(FailureKind.TRANSIENT, attempt_number=1, max_attempts=0)
    with pytest.raises(ValueError, match="max_attempts"):
        retry_policy(FailureKind.TRANSIENT, attempt_number=1, max_attempts=4)


def test_rate_limit_retry_wait_blocks_other_heavy_claims_until_due() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    JobRun.__table__.create(engine)
    now = datetime.now(UTC)
    with Session(engine) as session:
        window_end = now + timedelta(days=1)
        session.add_all(
            [
                JobRun(
                    job_id="rate-limited",
                    job_name="date_sync",
                    job_kind="date_sync",
                    execution_slot="heavy_sync",
                    status="retry_wait",
                    started_at=now,
                    parent_job_id="parent",
                    business_date=date(2026, 8, 1),
                    data_source="douyin",
                    config_version="v1",
                    window_start=now,
                    window_end=window_end,
                    current_stage="collect",
                    attempt_count=1,
                    lease_epoch=1,
                    next_retry_at=now + timedelta(minutes=30),
                    error_code="douyin_rate_limited",
                    metadata_json={},
                ),
                JobRun(
                    job_id="other-pending",
                    job_name="date_sync",
                    job_kind="date_sync",
                    execution_slot="heavy_sync",
                    status="pending",
                    started_at=now,
                    parent_job_id="parent",
                    business_date=date(2026, 8, 2),
                    data_source="douyin",
                    config_version="v1",
                    window_start=window_end,
                    window_end=window_end + timedelta(days=1),
                    current_stage="collect",
                    metadata_json={},
                ),
            ]
        )
        session.flush()

        cooldown = getattr(repositories, "heavy_sync_rate_limit_cooldown_active", None)
        assert callable(cooldown), "global rate-limit cooldown guard is missing"
        assert cooldown(session, now=now) is True
        assert cooldown(session, now=now + timedelta(minutes=31)) is False
    engine.dispose()


def test_claim_refuses_non_postgresql_sessions() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    JobRun.__table__.create(engine)
    now = datetime(2026, 8, 6, tzinfo=UTC)
    with Session(engine) as session:
        parent = JobRun(
            job_id="parent",
            job_name="range_sync",
            job_kind="range_sync",
            status="pending",
            started_at=now,
            metadata_json={},
        )
        child = JobRun(
            job_id="date-2026-08-05",
            parent_job_id="parent",
            job_name="date_sync",
            job_kind="date_sync",
            status="pending",
            execution_slot="heavy_sync",
            business_date=date(2026, 8, 5),
            data_source="douyin",
            config_version="v1",
            window_start=now - timedelta(days=1),
            window_end=now,
            current_stage="collect",
            attempt_count=0,
            max_attempts=3,
            started_at=now,
            metadata_json={},
        )
        session.add_all([parent, child])
        session.commit()

        with pytest.raises(RuntimeError, match="PostgreSQL"):
            claim_next_job(
                session,
                lease_owner="worker-a/process-1",
                component_instance_id="worker-a",
                lease_seconds=60,
            )

    engine.dispose()
