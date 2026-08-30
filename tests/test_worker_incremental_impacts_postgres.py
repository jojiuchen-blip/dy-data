"""Opt-in PostgreSQL evidence for materialization lease fencing.

The test is intentionally gated to a dedicated loopback database.  It never
falls back to the application's generic database URL.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from time import sleep

import pytest
from sqlalchemy import create_engine, delete, select, update
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.db import normalize_database_url
from apps.api.dy_api.models import (
    Base,
    ComponentHeartbeat,
    ClueMaterializationTarget,
    ClueMaterializationWorkItem,
    JobAttempt,
    JobImpact,
    JobImpactWatermark,
    JobRun,
    JobStageRun,
)
from apps.worker.repositories import (
    begin_clue_materialization_cycle,
    claim_clue_materialization_batch,
    complete_clue_materialization_batch,
    renew_clue_materialization_batch,
)


POSTGRES_ENV_NAME = "DYDATA_T12_TEST_DATABASE_URL"
POSTGRES_URL = os.getenv(POSTGRES_ENV_NAME)
pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason=f"set {POSTGRES_ENV_NAME} to the dedicated disposable PostgreSQL database",
)

CONTROL_TABLES = [
    JobImpact.__table__,
    ClueMaterializationWorkItem.__table__,
    ClueMaterializationTarget.__table__,
    JobImpactWatermark.__table__,
    JobRun.__table__,
    JobStageRun.__table__,
    ComponentHeartbeat.__table__,
    JobAttempt.__table__,
]


def _validated_postgres_url(raw_url: str) -> URL:
    url = make_url(normalize_database_url(raw_url))
    if not url.drivername.startswith("postgresql+"):
        raise RuntimeError("materialization PostgreSQL evidence requires a PostgreSQL driver")
    if url.host not in {"127.0.0.1", "localhost"}:
        raise RuntimeError("materialization test database must use a loopback host")
    if url.port != 55432:
        raise RuntimeError("materialization test database must use the dedicated port 55432")
    if url.database != "dydata_t12":
        raise RuntimeError("materialization test database must be named dydata_t12")
    if url.username != "dydata_t12":
        raise RuntimeError("materialization test database must use the dedicated test role")
    return url


@pytest.fixture(scope="module")
def postgres_stack() -> tuple[object, sessionmaker[Session]]:
    assert POSTGRES_URL is not None
    engine = create_engine(
        _validated_postgres_url(POSTGRES_URL),
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


def _clear_postgres_control_rows(factory: sessionmaker[Session]) -> None:
    """Reset this module's control tables without violating FK dependencies."""

    with factory.begin() as session:
        # ComponentHeartbeat has a deferrable/use_alter reference to the
        # current attempt; clear that binding before deleting attempts.
        session.execute(
            update(ComponentHeartbeat).values(
                current_job_id=None,
                current_attempt_id=None,
            )
        )
        session.execute(delete(JobAttempt))
        session.execute(delete(JobStageRun))
        # Avoid self-referencing parent_job_id preventing a deterministic
        # per-test wipe if a future PG regression adds a parent row.
        session.execute(update(JobRun).values(parent_job_id=None))
        session.execute(delete(JobRun))
        session.execute(delete(ComponentHeartbeat))
        session.execute(delete(ClueMaterializationTarget))
        session.execute(delete(ClueMaterializationWorkItem))
        session.execute(delete(JobImpactWatermark))
        session.execute(delete(JobImpact))


@pytest.fixture(autouse=True)
def isolate_postgres_control_tables(
    postgres_stack: tuple[object, sessionmaker[Session]],
) -> None:
    _engine, factory = postgres_stack
    _clear_postgres_control_rows(factory)
    yield
    _clear_postgres_control_rows(factory)


def test_materialization_complete_uses_statement_clock_after_transaction_start(
    postgres_stack: tuple[object, sessionmaker[Session]],
) -> None:
    _engine, factory = postgres_stack
    with factory() as seed:
        seed.add(
            JobImpact(
                impact_key="pg-materialization-clock-impact",
                entity_type="order",
                entity_key="pg-materialization-clock-order",
                change_kind="insert",
                old_values_json={},
                new_values_json={"order_status_normalized": "paid"},
                affected_closure_json={"order_ids": ["pg-materialization-clock-order"]},
            )
        )
        seed.flush()
        begin_clue_materialization_cycle(seed, scope="pg-clock")
        seed.commit()

    with factory() as session:
        claimed = claim_clue_materialization_batch(
            session,
            scope="pg-clock",
            lease_token="clue-worker:attempt-pg-a",
            lease_seconds=1,
        )
        assert len(claimed) == 1
        assert [item.entity_key for item in claimed] == [
            "pg-materialization-clock-order"
        ]
        # Keep this transaction open across the lease expiry. PostgreSQL
        # transaction-start ``now()`` would incorrectly treat the lease as
        # valid; the repository must use statement-time clock_timestamp().
        sleep(1.2)
        assert (
            complete_clue_materialization_batch(
                session,
                [claimed[0].work_item_id],
                lease_token="clue-worker:attempt-pg-a",
            )
            == 0
        )
        replacement = claim_clue_materialization_batch(
            session,
            scope="pg-clock",
            lease_token="clue-worker:attempt-pg-b",
            lease_seconds=30,
        )
        assert [item.work_item_id for item in replacement] == [claimed[0].work_item_id]
        assert [item.entity_key for item in replacement] == [
            "pg-materialization-clock-order"
        ]
        assert (
            complete_clue_materialization_batch(
                session,
                [replacement[0].work_item_id],
                lease_token="clue-worker:attempt-pg-a",
            )
            == 0
        )
        assert (
            complete_clue_materialization_batch(
                session,
                [replacement[0].work_item_id],
                lease_token="clue-worker:attempt-pg-b",
        )
        == 1
    )
        session.rollback()


def _seed_persisted_attempt(
    session: Session,
    *,
    attempt_id: str,
    finished_at: datetime | None,
) -> None:
    now = datetime.now(UTC)
    job_id = f"job-{attempt_id}"
    stage_run_id = f"stage-{attempt_id}"
    component_id = f"component-{attempt_id}"
    session.add(
        JobRun(
            job_id=job_id,
            job_name=f"materialization-{attempt_id}",
            status="running",
            started_at=now,
            metadata_json={},
            current_stage="materialize",
            attempt_count=1,
            max_attempts=3,
            lease_epoch=1,
        )
    )
    session.add(
        JobStageRun(
            stage_run_id=stage_run_id,
            job_id=job_id,
            stage_name="materialize",
            status="running",
            checkpoint_json={},
            lease_epoch=1,
            started_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    session.add(
        ComponentHeartbeat(
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
    )
    session.flush()
    session.add(
        JobAttempt(
            attempt_id=attempt_id,
            job_id=job_id,
            stage_run_id=stage_run_id,
            attempt_number=1,
            lease_epoch=1,
            component_type="worker",
            component_instance_id=component_id,
            started_at=now - timedelta(seconds=1),
            finished_at=finished_at,
            exit_type="crashed" if finished_at is not None else None,
            created_at=now - timedelta(seconds=1),
        )
    )


def test_finished_attempt_reclaims_future_lease_and_fences_old_token_on_postgres(
    postgres_stack: tuple[object, sessionmaker[Session]],
) -> None:
    _engine, factory = postgres_stack
    scope = "pg-finished-attempt-reclaim"
    with factory.begin() as seed:
        _seed_persisted_attempt(
            seed,
            attempt_id="pg-attempt-finished",
            finished_at=datetime.now(UTC),
        )
        seed.add(
            JobImpact(
                impact_key="pg-finished-attempt-impact",
                entity_type="order",
                entity_key="pg-finished-attempt-order",
                change_kind="insert",
                old_values_json={},
                new_values_json={},
                affected_closure_json={},
            )
        )
        seed.flush()
        begin_clue_materialization_cycle(seed, scope=scope)

    with factory.begin() as session:
        first = claim_clue_materialization_batch(
            session,
            scope=scope,
            lease_token="pg-attempt-finished",
            lease_seconds=300,
        )
        assert len(first) == 1
        assert [item.entity_key for item in first] == ["pg-finished-attempt-order"]

    with factory.begin() as session:
        replacement = claim_clue_materialization_batch(
            session,
            scope=scope,
            lease_token="pg-attempt-recovery",
            lease_seconds=300,
        )
        assert [item.work_item_id for item in replacement] == [first[0].work_item_id]
        assert [item.entity_key for item in replacement] == [
            "pg-finished-attempt-order"
        ]
        assert (
            complete_clue_materialization_batch(
                session,
                [first[0].work_item_id],
                lease_token="pg-attempt-finished",
            )
            == 0
        )
        assert (
            renew_clue_materialization_batch(
                session,
                [first[0].work_item_id],
                lease_token="pg-attempt-finished",
                lease_seconds=300,
            )
            == 0
        )
        assert (
            complete_clue_materialization_batch(
                session,
                [first[0].work_item_id],
                lease_token="pg-attempt-recovery",
            )
            == 1
        )


def test_unfinished_attempt_blocks_future_lease_reclaim_on_postgres(
    postgres_stack: tuple[object, sessionmaker[Session]],
) -> None:
    _engine, factory = postgres_stack
    scope = "pg-active-attempt-block"
    with factory.begin() as seed:
        _seed_persisted_attempt(
            seed,
            attempt_id="pg-attempt-active",
            finished_at=None,
        )
        seed.add(
            JobImpact(
                impact_key="pg-active-attempt-impact",
                entity_type="order",
                entity_key="pg-active-attempt-order",
                change_kind="insert",
                old_values_json={},
                new_values_json={},
                affected_closure_json={},
            )
        )
        seed.flush()
        begin_clue_materialization_cycle(seed, scope=scope)

    with factory.begin() as session:
        first = claim_clue_materialization_batch(
            session,
            scope=scope,
            lease_token="pg-attempt-active",
            lease_seconds=300,
        )
        assert len(first) == 1
        assert [item.entity_key for item in first] == ["pg-active-attempt-order"]

    with factory.begin() as session:
        assert (
            claim_clue_materialization_batch(
                session,
                scope=scope,
                lease_token="pg-attempt-blocked",
                lease_seconds=300,
            )
            == []
        )
