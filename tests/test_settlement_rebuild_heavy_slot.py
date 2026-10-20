"""Shared heavy-slot admission for current and legacy settlement rebuilds."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.models import Base, JobRun
from apps.ops_agent.resources import ResourceAction, ResourceDecision
from apps.worker import repositories, settlement_rebuild


ALLOW = ResourceDecision(ResourceAction.ALLOW, ())


@pytest.fixture(autouse=True)
def resource_allow(monkeypatch):
    monkeypatch.setenv("WORKER_RESOURCE_GUARD_ENABLED", "false")


def _factory(session: Session) -> sessionmaker:
    return sessionmaker(bind=session.get_bind(), autoflush=False, expire_on_commit=False)


def _queue(session: Session, job_id: str = "rebuild", **values) -> JobRun:
    job = repositories.queue_job_run(session, job_id, "settlement_rebuild")
    for key, value in values.items():
        setattr(job, key, value)
    session.commit()
    return job


def _claim(factory, mode: str, *, job_id: str = "rebuild"):
    if mode == "latest":
        return settlement_rebuild.claim_latest_settlement_rebuild_job(factory)
    return settlement_rebuild.claim_settlement_rebuild_job(factory, job_id=job_id)


@pytest.mark.parametrize("mode", ["latest", "specific"])
def test_rebuild_claim_sets_the_shared_heavy_slot(db_session, mode):
    _queue(db_session)
    assert _claim(_factory(db_session), mode) is not None
    db_session.expire_all()
    job = db_session.get(JobRun, "rebuild")
    assert job.status == "running"
    assert job.execution_slot == "heavy_sync"
    assert job.attempt_count == 1


@pytest.mark.parametrize("mode", ["latest", "specific"])
@pytest.mark.parametrize("legacy_rebuild", [False, True])
def test_rebuild_claim_refuses_other_running_heavy_or_legacy_rebuild(
    db_session, mode, legacy_rebuild
):
    _queue(db_session)
    blocker = _queue(
        db_session,
        "blocker",
        job_name="settlement_rebuild" if legacy_rebuild else "settlement_compaction",
        execution_slot=None if legacy_rebuild else "heavy_sync",
        status="running",
        # Even an expired row remains a writer until its recovery protocol acts.
        lease_expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    assert _claim(_factory(db_session), mode) is None
    db_session.expire_all()
    assert db_session.get(JobRun, "rebuild").status == "queued"
    assert db_session.get(JobRun, "rebuild").attempt_count in {None, 0}
    assert db_session.get(JobRun, blocker.job_id).execution_slot == (
        None if legacy_rebuild else "heavy_sync"
    )


@pytest.mark.parametrize("mode", ["latest", "specific"])
@pytest.mark.parametrize("action", [ResourceAction.STOP, ResourceAction.DRAIN])
def test_resource_rejection_does_not_consume_attempt_or_supersede(
    db_session, monkeypatch, mode, action
):
    now = datetime.now(timezone.utc)
    _queue(db_session, "older", started_at=now - timedelta(seconds=1))
    _queue(db_session, started_at=now)
    decision = ResourceDecision(action, ("synthetic_pressure",))
    monkeypatch.setattr(
        settlement_rebuild, "current_resource_decision", lambda: decision, raising=False
    )
    assert _claim(_factory(db_session), mode) is None
    db_session.expire_all()
    for job_id in ("older", "rebuild"):
        job = db_session.get(JobRun, job_id)
        assert job.status == "queued"
        assert job.attempt_count in {None, 0}
        assert "superseded_by" not in (job.metadata_json or {})


@pytest.mark.parametrize("mode", ["latest", "specific"])
def test_missing_real_monitor_fails_closed(db_session, monkeypatch, mode):
    from apps.worker import resource_monitor

    _queue(db_session)
    monkeypatch.setenv("WORKER_RESOURCE_GUARD_ENABLED", "true")
    monkeypatch.setattr(resource_monitor, "_monitor", None)
    assert _claim(_factory(db_session), mode) is None
    db_session.expire_all()
    assert db_session.get(JobRun, "rebuild").attempt_count in {None, 0}


@pytest.mark.parametrize("mode", ["latest", "specific"])
@pytest.mark.parametrize("legacy_slot", [False, True])
def test_rate_limit_cooldown_blocks_rebuild_without_consuming_attempt(
    db_session, mode, legacy_slot
):
    _queue(db_session)
    _queue(
        db_session,
        "cooldown",
        job_name="settlement_rebuild" if legacy_slot else "date_sync",
        execution_slot=None if legacy_slot else "heavy_sync",
        status="retry_wait",
        error_code=repositories.DOUYIN_RATE_LIMIT_ERROR_CODE,
        next_retry_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    assert _claim(_factory(db_session), mode) is None
    db_session.expire_all()
    assert db_session.get(JobRun, "rebuild").status == "queued"
    assert db_session.get(JobRun, "rebuild").attempt_count in {None, 0}


@pytest.fixture
def heavy_pg():
    raw_url = os.getenv("DYDATA_HEAVY_CLAIM_TEST_DATABASE_URL") or os.getenv(
        "DY_RELEASE_POSTGRES_URL"
    )
    if not raw_url:
        pytest.skip("requires isolated loopback PostgreSQL test database")
    url = make_url(raw_url)
    if (
        not url.drivername.startswith("postgresql")
        or url.host not in {"127.0.0.1", "localhost"}
        or url.database not in {"dydata_release", "dydata104_test"}
    ):
        pytest.fail("heavy claim gate requires the disposable loopback test database")
    schema = f"heavy_claim_{uuid4().hex}"
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        url,
        connect_args={
            "options": f"-c search_path={schema} -c lock_timeout=5000 -c statement_timeout=15000"
        },
    )
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        Base.metadata.create_all(engine)
        yield factory
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def _date_job(factory):
    from apps.worker.daily_windows import plan_daily_sync

    with factory() as session:
        plan = plan_daily_sync(
            session,
            start=date(2026, 9, 14),
            end=date(2026, 9, 15),
            target="orders",
            requested_by="test",
            trigger_source="manual",
        )
        candidate = next(job for job in plan.daily_jobs if job.job_id.startswith("date-sync-"))
        session.commit()
        return candidate.job_id


def _claim_date(factory, job_id):
    with factory() as session:
        token = repositories.claim_next_heavy_job(
            session,
            lease_owner="heavy-slot-test",
            component_instance_id=f"test-instance-{uuid4().hex}",
            lease_seconds=300,
            job_id=job_id,
            resource_decision=ALLOW,
        )
        session.commit()
        return token


def _compaction_job(factory):
    from apps.api.dy_api.models import SettlementProjectionActive, SettlementProjectionGeneration
    from apps.worker.legacy_projection_bootstrap import ResourceGateConfig
    from apps.worker.settlement_compaction import enqueue_settlement_compaction_job

    with factory() as session:
        session.add(SettlementProjectionGeneration(
            generation_id="root", generation_kind="legacy_root", projection_name="settlement",
            state="published", input_fingerprint="a" * 64, lineage_depth=0,
            checkpoint_json={}, manifest_checksum="1" * 64, source_input_json={},
        ))
        session.flush()
        session.add(SettlementProjectionGeneration(
            generation_id="head", generation_kind="lineage", projection_name="settlement",
            state="published", input_fingerprint="b" * 64, lineage_depth=1,
            base_generation_id="root", checkpoint_json={}, manifest_checksum="2" * 64,
            source_input_json={},
        ))
        session.flush()
        session.add(SettlementProjectionActive(projection_name="settlement", generation_id="head"))
        session.commit()
    return enqueue_settlement_compaction_job(
        factory, base_generation_id="head", batch_size=2,
        resource_limits=ResourceGateConfig(100, 1024**2, 2 * 1024**2, 100 * 1024**2, 0),
    )


@pytest.mark.parametrize("mode", ["latest", "specific"])
@pytest.mark.parametrize("opponent", ["date", "compaction"])
def test_pg_rebuild_and_heavy_claim_race_has_one_winner(heavy_pg, mode, opponent):
    from apps.worker.settlement_compaction import claim_settlement_compaction_job

    factory = heavy_pg
    with factory() as session:
        _queue(session)
    other_id = _date_job(factory) if opponent == "date" else _compaction_job(factory)
    barrier = Barrier(2)

    def claim_rebuild():
        barrier.wait(timeout=10)
        return _claim(factory, mode)

    def claim_other():
        barrier.wait(timeout=10)
        if opponent == "date":
            return _claim_date(factory, other_id)
        return claim_settlement_compaction_job(factory, job_id=other_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(claim_rebuild), executor.submit(claim_other)]
        results = [future.result(timeout=30) for future in futures]
    assert sum(result is not None for result in results) == 1
    with factory() as session:
        running = list(session.scalars(select(JobRun).where(JobRun.status == "running")))
        assert len(running) == 1
        assert running[0].execution_slot == "heavy_sync"


def test_pg_legacy_null_running_rebuild_blocks_date_without_rewriting_it(heavy_pg):
    factory = heavy_pg
    with factory() as session:
        _queue(session, "legacy", status="running", execution_slot=None)
    date_id = _date_job(factory)
    assert _claim_date(factory, date_id) is None
    with factory() as session:
        legacy = session.get(JobRun, "legacy")
        assert legacy.status == "running"
        assert legacy.execution_slot is None
        assert session.get(JobRun, date_id).attempt_count == 0


@pytest.mark.parametrize("mode", ["latest", "specific"])
def test_pg_rebuild_claim_uses_shared_nonblocking_mutex(heavy_pg, mode):
    factory = heavy_pg
    with factory() as session:
        _queue(session)
    with factory() as held:
        held.execute(select(text("pg_advisory_xact_lock(:key)")), {
            "key": repositories.HEAVY_SYNC_CLAIM_LOCK_KEY
        })
        assert _claim(factory, mode) is None
        with factory() as session:
            assert session.get(JobRun, "rebuild").attempt_count in {None, 0}
    assert _claim(factory, mode) is not None


def test_pg_expired_legacy_rebuild_reclaims_only_through_existing_recovery(heavy_pg):
    from apps.worker.queued_jobs import _recover_stale_settlement_rebuilds

    factory = heavy_pg
    now = datetime.now(timezone.utc)
    with factory() as session:
        _queue(
            session, status="running", execution_slot=None, claim_token="old-claim",
            attempt_count=1, max_attempts=3, heartbeat_at=now - timedelta(hours=1),
            lease_expires_at=now - timedelta(minutes=1),
        )
    assert _claim(factory, "specific") is None
    recovered, failed = _recover_stale_settlement_rebuilds(
        factory, now=now, stale_after=timedelta(minutes=5), max_attempts=3
    )
    assert recovered == ["rebuild"] and failed == []
    token = _claim(factory, "specific")
    assert token is not None and token != "old-claim"
    assert not settlement_rebuild.heartbeat_settlement_rebuild_job(
        factory, job_id="rebuild", claim_id="old-claim", stage="stale"
    )
    with factory() as session:
        job = session.get(JobRun, "rebuild")
        assert job.execution_slot == "heavy_sync"
        assert job.attempt_count == 2
        assert job.metadata_json["recoveryState"] == "REQUEUED_STALE_CLAIM"


@pytest.mark.parametrize("mode", ["latest", "specific"])
@pytest.mark.parametrize("blocker", ["stop", "drain", "cooldown"])
def test_pg_admission_rejection_preserves_attempts_and_supersede_queue(
    heavy_pg, monkeypatch, mode, blocker
):
    factory = heavy_pg
    now = datetime.now(timezone.utc)
    with factory() as session:
        _queue(session, "older", started_at=now - timedelta(seconds=1))
        _queue(session, started_at=now)
        if blocker == "cooldown":
            _queue(
                session, "cooldown", job_name="date_sync", execution_slot="heavy_sync",
                status="retry_wait", error_code=repositories.DOUYIN_RATE_LIMIT_ERROR_CODE,
                next_retry_at=now + timedelta(minutes=5),
            )
    if blocker in {"stop", "drain"}:
        decision = ResourceDecision(ResourceAction(blocker), ("synthetic_pressure",))
        monkeypatch.setattr(settlement_rebuild, "current_resource_decision", lambda: decision)
    assert _claim(factory, mode) is None
    with factory() as session:
        for job_id in ("older", "rebuild"):
            job = session.get(JobRun, job_id)
            assert job.status == "queued"
            assert job.attempt_count in {None, 0}
            assert "superseded_by" not in (job.metadata_json or {})


def test_pg_unique_index_is_the_final_heavy_slot_backstop(heavy_pg):
    factory = heavy_pg
    with factory() as session:
        _queue(session)
        _queue(session, "other")
    assert _claim(factory, "specific") is not None
    with pytest.raises(IntegrityError):
        with factory() as session:
            session.execute(update(JobRun).where(JobRun.job_id == "other").values(
                status="running", execution_slot="heavy_sync"
            ))
            session.commit()
