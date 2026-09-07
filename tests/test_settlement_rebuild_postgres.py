"""Settlement rebuild fencing against the disposable release PostgreSQL service."""
from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from apps.api.dy_api.models import (
    Base,
    DimStore,
    JobEvent,
    JobRun,
    SettlementProjectionActive,
    SettlementProjectionGeneration,
)
from apps.worker import projection_publish, queued_jobs, settlement_rebuild
from apps.worker.repositories import queue_job_run
from apps.worker.settlement import SettlementStats


@pytest.fixture
def rebuild_pg():
    raw_url = os.getenv("DY_RELEASE_POSTGRES_URL")
    if not raw_url:
        pytest.skip("requires disposable release PostgreSQL service")
    url = make_url(raw_url)
    if (
        not url.drivername.startswith("postgresql")
        or url.host not in {"127.0.0.1", "localhost"}
        or url.database != "dydata_release"
    ):
        pytest.fail("rebuild gate requires loopback dydata_release database")
    schema = f"rebuild_gate_{uuid4().hex}"
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        url,
        connect_args={"options": f"-c search_path={schema} -c lock_timeout=5000 -c statement_timeout=15000"},
    )
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        tables = {
            model.__table__ for model in (
                DimStore, JobRun, JobEvent,
                SettlementProjectionGeneration, SettlementProjectionActive,
            )
        }
        pending = list(tables)
        while pending:
            for foreign_key in pending.pop().foreign_keys:
                dependency = foreign_key.column.table
                if dependency not in tables:
                    tables.add(dependency)
                    pending.append(dependency)
        Base.metadata.create_all(engine, tables=list(tables))
        yield engine, factory
    finally:
        engine.dispose()
        assert re.fullmatch(r"rebuild_gate_[0-9a-f]{32}", schema)
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def test_pg_distinct_rebuilds_have_one_live_claim(rebuild_pg):
    _, factory = rebuild_pg
    with factory.begin() as session:
        for job_id in ("claim-a", "claim-b"):
            queue_job_run(session, job_id, "settlement_rebuild")
    barrier = Barrier(2)

    def claim(job_id):
        barrier.wait(timeout=5)
        return settlement_rebuild.claim_settlement_rebuild_job(factory, job_id=job_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(claim, ("claim-a", "claim-b")))
    assert sum(value is not None for value in results) == 1
    with factory() as session:
        assert len(list(session.scalars(select(JobRun).where(JobRun.status == "running")))) == 1


def test_pg_old_connection_cannot_block_takeover_or_commit(rebuild_pg):
    _, factory = rebuild_pg
    with factory.begin() as session:
        queue_job_run(session, "takeover", "settlement_rebuild")
    old_claim = settlement_rebuild.claim_settlement_rebuild_job(factory, job_id="takeover")
    with factory() as old_connection:
        old_connection.execute(text("SELECT 1"))
        with factory.begin() as session:
            job = session.get(JobRun, "takeover")
            job.lease_expires_at = settlement_rebuild._database_utcnow(session) - timedelta(seconds=1)
        with factory() as session:
            now = settlement_rebuild._database_utcnow(session)
        recovered, failed = queued_jobs._recover_stale_settlement_rebuilds(
            factory, now=now, stale_after=timedelta(seconds=1), max_attempts=3,
        )
        assert recovered == ["takeover"] and failed == []
        new_claim = settlement_rebuild.claim_settlement_rebuild_job(factory, job_id="takeover")
        assert new_claim and new_claim != old_claim
        old_connection.add(DimStore(store_id="stale-write", store_name="Stale"))
        with pytest.raises(settlement_rebuild.SettlementRebuildLeaseLost):
            settlement_rebuild._fence_settlement_rebuild_commit(
                old_connection, job_id="takeover", claim_id=old_claim, stage="settle",
            )
        old_connection.rollback()
    with factory() as session:
        assert session.get(DimStore, "stale-write") is None


def test_pg_watchdog_renews_during_silent_query(rebuild_pg, monkeypatch):
    _, factory = rebuild_pg
    with factory.begin() as session:
        queue_job_run(session, "slow-query", "settlement_rebuild")

    def slow_query(session, **kwargs):
        lease_query = select(JobRun.lease_expires_at).where(JobRun.job_id == "slow-query")
        initial_lease = session.scalar(lease_query)
        # Stay silent beyond two lease windows. Sub-second leases made this
        # scheduling test sensitive to concurrent Windows filesystem flushes.
        session.execute(text("SELECT pg_sleep(4.5)"))
        assert session.scalar(lease_query) > initial_lease + timedelta(seconds=2)
        return SettlementStats(2, 0, 1, 1)

    monkeypatch.setattr(settlement_rebuild, "rebuild_settlement", slow_query)
    assert settlement_rebuild.run_settlement_rebuild_job(
        factory=factory, job_id="slow-query",
        lease_duration=timedelta(seconds=2),
        heartbeat_interval_seconds=0.2,
    )
    with factory() as session:
        job = session.get(JobRun, "slow-query")
        assert job.status == "success" and job.attempt_count == 1
        assert job.metadata_json["settlement_projection"]["status"] == "legacy_root"


def _seed_publication(factory, job_id):
    """Create real FK-valid publication inputs, flushing in dependency order."""
    with factory.begin() as session:
        queue_job_run(session, job_id, "settlement_rebuild")
    claim_id = settlement_rebuild.claim_settlement_rebuild_job(factory, job_id=job_id)
    assert claim_id is not None
    with factory.begin() as session:
        session.add(SettlementProjectionGeneration(
            generation_id="race-base",
            generation_kind="legacy_root",
            state="published",
            input_fingerprint="a" * 64,
            lineage_depth=0,
            published_at=settlement_rebuild._database_utcnow(session),
        ))
        session.flush()
        session.add(SettlementProjectionGeneration(
            generation_id="race-target",
            base_generation_id="race-base",
            generation_kind="lineage",
            state="ready",
            input_fingerprint="b" * 64,
            manifest_checksum="c" * 64,
            lineage_depth=1,
            source_job_id=job_id,
        ))
        session.add(SettlementProjectionActive(
            projection_name="settlement", generation_id="race-base",
        ))
    return {
        "job_id": job_id,
        "claim_id": claim_id,
        "generation_id": "race-target",
        "base_generation_id": "race-base",
        "input_fingerprint": "b" * 64,
        "manifest_checksum": "c" * 64,
    }


def _observed_factory(factory):
    """Expose the competing backend PID without changing its SQL behavior."""
    connected = Event()
    backend = {}

    def open_session():
        session = factory()
        try:
            backend["pid"] = session.scalar(text("SELECT pg_backend_pid()"))
        except BaseException:
            session.close()
            raise
        connected.set()
        return session

    return open_session, connected, backend


def _wait_for_database_condition(engine, sql, parameters):
    """Poll a database condition, bounded below the fixture's lock timeout."""
    with engine.connect() as connection:
        deadline = connection.scalar(text("SELECT clock_timestamp()")) + timedelta(seconds=4)
        while not connection.scalar(text(sql), parameters):
            assert connection.scalar(text("SELECT clock_timestamp()")) < deadline, (
                f"PostgreSQL condition was not reached: {sql}"
            )
            # This sleep belongs to a bounded database-condition wait, not to
            # scheduling the race by guessing how quickly another thread runs.
            connection.execute(text("SELECT pg_sleep(0.01)"))


def _wait_for_row_lock(engine, connected, backend, blocker_pid):
    assert connected.wait(timeout=5), "competing database session did not start"
    _wait_for_database_condition(
        engine,
        "SELECT :blocker = ANY(pg_blocking_pids(:waiter))",
        {"blocker": blocker_pid, "waiter": backend["pid"]},
    )


def _set_short_lease(factory, job_id):
    with factory.begin() as session:
        job = session.scalar(select(JobRun).where(JobRun.job_id == job_id).with_for_update())
        expires_at = settlement_rebuild._database_utcnow(session) + timedelta(seconds=2)
        job.lease_expires_at = expires_at
    return expires_at


def test_pg_heartbeat_preserves_publication_metadata_after_row_lock_wait(rebuild_pg):
    """A heartbeat waiting behind publication must merge the committed marker."""
    engine, factory = rebuild_pg
    publication = _seed_publication(factory, "metadata-race")
    heartbeat_factory, connected, backend = _observed_factory(factory)
    marker = {"status": "published", "generation_id": publication["generation_id"]}

    with ThreadPoolExecutor(max_workers=1) as executor:
        # publish_settlement_rebuild holds the real job-row lock. The wrapper
        # normally appends this marker in the same transaction before commit.
        with factory.begin() as publisher:
            blocker_pid = publisher.scalar(text("SELECT pg_backend_pid()"))
            projection_publish.publish_settlement_rebuild(publisher, **publication)
            job = publisher.get(JobRun, publication["job_id"])
            job.metadata_json = {**job.metadata_json, "settlement_projection": marker}
            publisher.flush()
            heartbeat = executor.submit(
                settlement_rebuild.heartbeat_settlement_rebuild_job,
                heartbeat_factory,
                job_id=publication["job_id"],
                claim_id=publication["claim_id"],
                stage="publish_projection",
                progress_current=332019,
                progress_total=332019,
            )
            # Old code blocks on UPDATE after reading stale metadata; corrected
            # code can block earlier on SELECT FOR UPDATE. Both are exercised.
            _wait_for_row_lock(engine, connected, backend, blocker_pid)
        assert heartbeat.result(timeout=10) is True

    with factory() as session:
        job = session.get(JobRun, publication["job_id"])
        assert job.metadata_json.get("settlement_projection") == marker
        assert job.progress_current == 332019
        assert session.get(SettlementProjectionActive, "settlement").generation_id == "race-target"
        assert len(list(session.scalars(select(JobEvent).where(
            JobEvent.job_id == publication["job_id"],
            JobEvent.event_type == "settlement_projection_published",
        )))) == 1


def test_pg_publication_rechecks_lease_after_waiting_for_pointer_lock(rebuild_pg):
    """A valid initial lease cannot authorize publication after a lock wait."""
    engine, factory = rebuild_pg
    publication = _seed_publication(factory, "publish-expiry-race")
    expires_at = _set_short_lease(factory, publication["job_id"])
    publisher_factory, connected, backend = _observed_factory(factory)

    def publish():
        with publisher_factory() as session:
            try:
                result = projection_publish.publish_settlement_rebuild(session, **publication)
                session.commit()
                return result
            except BaseException:
                session.rollback()
                raise

    with ThreadPoolExecutor(max_workers=1) as executor:
        with factory.begin() as blocker:
            blocker_pid = blocker.scalar(text("SELECT pg_backend_pid()"))
            blocker.scalar(select(SettlementProjectionActive).where(
                SettlementProjectionActive.projection_name == "settlement",
            ).with_for_update())
            pending = executor.submit(publish)
            _wait_for_row_lock(engine, connected, backend, blocker_pid)
            _wait_for_database_condition(
                engine, "SELECT clock_timestamp() >= :expires_at", {"expires_at": expires_at},
            )
        with pytest.raises(RuntimeError, match="(?i)claim|lease"):
            pending.result(timeout=10)

    with factory() as session:
        assert session.get(SettlementProjectionActive, "settlement").generation_id == "race-base"
        generation = session.get(SettlementProjectionGeneration, "race-target")
        assert generation.state == "ready" and generation.published_at is None
        assert list(session.scalars(select(JobEvent).where(
            JobEvent.job_id == publication["job_id"],
            JobEvent.event_type == "settlement_projection_published",
        ))) == []


@pytest.mark.parametrize("transition", ["heartbeat", "finish", "fail"])
def test_pg_heartbeat_cannot_revive_lease_expired_during_row_lock_wait(rebuild_pg, transition):
    """Renewal must use database time after its blocking row lock is acquired."""
    engine, factory = rebuild_pg
    publication = _seed_publication(factory, "heartbeat-expiry-race")
    expires_at = _set_short_lease(factory, publication["job_id"])
    heartbeat_factory, connected, backend = _observed_factory(factory)

    def transition_job():
        if transition == "finish":
            try:
                settlement_rebuild._finish_claimed_settlement_rebuild(
                    heartbeat_factory, job_id=publication["job_id"],
                    claim_id=publication["claim_id"], stats=SettlementStats(1, 0, 1, 1),
                )
            except settlement_rebuild.SettlementRebuildLeaseLost:
                return False
            return True
        if transition == "fail":
            return settlement_rebuild._fail_claimed_settlement_rebuild(
                heartbeat_factory, job_id=publication["job_id"],
                claim_id=publication["claim_id"], error_message="test failure",
            ) is not None
        return settlement_rebuild.heartbeat_settlement_rebuild_job(
            heartbeat_factory, job_id=publication["job_id"],
            claim_id=publication["claim_id"], stage="must_not_be_written", progress_current=999,
        )
    with factory() as session:
        before = session.get(JobRun, publication["job_id"])
        original_heartbeat = before.heartbeat_at
        original_metadata = dict(before.metadata_json)

    with ThreadPoolExecutor(max_workers=1) as executor:
        with factory.begin() as blocker:
            blocker_pid = blocker.scalar(text("SELECT pg_backend_pid()"))
            blocker.scalar(select(JobRun).where(
                JobRun.job_id == publication["job_id"],
            ).with_for_update())
            heartbeat = executor.submit(transition_job)
            _wait_for_row_lock(engine, connected, backend, blocker_pid)
            _wait_for_database_condition(
                engine, "SELECT clock_timestamp() >= :expires_at", {"expires_at": expires_at},
            )
        assert heartbeat.result(timeout=10) is False

    with factory() as session:
        job = session.get(JobRun, publication["job_id"])
        assert job.claim_token == publication["claim_id"]
        assert job.lease_expires_at == expires_at
        assert job.heartbeat_at == original_heartbeat
        assert job.metadata_json == original_metadata


def test_pg_obsolete_generation_cleanup_rolls_back_after_lease_expires_in_lock_wait(rebuild_pg):
    """Cleanup must fence after its generation writes finish waiting on locks."""
    engine, factory = rebuild_pg
    publication = _seed_publication(factory, "cleanup-expiry-race")
    expires_at = _set_short_lease(factory, publication["job_id"])
    cleanup_factory, connected, backend = _observed_factory(factory)

    with ThreadPoolExecutor(max_workers=1) as executor:
        with factory.begin() as blocker:
            blocker_pid = blocker.scalar(text("SELECT pg_backend_pid()"))
            blocker.scalar(select(SettlementProjectionGeneration).where(
                SettlementProjectionGeneration.generation_id == "race-target",
            ).with_for_update())
            pending = executor.submit(
                settlement_rebuild._supersede_obsolete_settlement_generations,
                cleanup_factory,
                job_id=publication["job_id"],
                claim_id=publication["claim_id"],
                generation_id="replacement-generation",
                lease_duration=timedelta(seconds=2),
            )
            _wait_for_row_lock(engine, connected, backend, blocker_pid)
            _wait_for_database_condition(
                engine, "SELECT clock_timestamp() >= :expires_at", {"expires_at": expires_at},
            )
        # Capture only the expected lease rejection, so the fresh read below
        # also demonstrates the erroneous committed supersession on the red run.
        rejected_expired_claim = False
        try:
            pending.result(timeout=10)
        except settlement_rebuild.SettlementRebuildLeaseLost:
            rejected_expired_claim = True

    with factory() as session:
        generation = session.get(SettlementProjectionGeneration, "race-target")
        assert generation.state == "ready", "expired cleanup committed supersession"
        assert generation.failure_code is None
        assert generation.failure_reason is None
        assert generation.manifest_checksum == publication["manifest_checksum"]
        assert session.get(SettlementProjectionActive, "settlement").generation_id == "race-base"
    assert rejected_expired_claim, "cleanup did not reject its expired claim"


def test_pg_stale_reconciliation_does_not_clear_replacement_claim(rebuild_pg):
    """A delayed reconciler must not flush terminal state over a newer owner."""
    _, factory = rebuild_pg
    publication = _seed_publication(factory, "reconcile-race")
    with factory.begin() as session:
        projection_publish.publish_settlement_rebuild(session, **publication)
    with factory.begin() as session:
        job = session.get(JobRun, publication["job_id"])
        stale_time = settlement_rebuild._database_utcnow(session)
        job.lease_expires_at = stale_time - timedelta(seconds=1)
    snapshot_loaded = Event()
    replacement_committed = Event()

    def reconcile_stale_snapshot():
        with factory.begin() as session:
            job = session.get(JobRun, publication["job_id"])
            assert job.claim_token == publication["claim_id"]
            # Retain the identity-map objects, matching a paused reconciler
            # that already observed J's publication before pointer drift.
            active = session.get(SettlementProjectionActive, "settlement")
            generation = session.get(SettlementProjectionGeneration, active.generation_id)
            assert generation.source_job_id == job.job_id
            snapshot_loaded.set()
            assert replacement_committed.wait(timeout=10), "replacement claim did not commit"
            return settlement_rebuild.reconcile_published_settlement_rebuild(
                session, job=job, reconciled_at=stale_time,
            )

    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(reconcile_stale_snapshot)
        try:
            assert snapshot_loaded.wait(timeout=5), "reconciler did not read its snapshot"
            with factory.begin() as session:
                job = session.scalar(select(JobRun).where(
                    JobRun.job_id == publication["job_id"],
                ).with_for_update())
                # Model the committed recovery transition explicitly so this
                # ownership test is independent of publication-discovery fixes.
                session.get(SettlementProjectionActive, "settlement").generation_id = "race-base"
                job.status = "queued"
                job.claim_token = None
                job.lease_expires_at = None
            replacement_claim = settlement_rebuild.claim_settlement_rebuild_job(
                factory, job_id=publication["job_id"],
            )
            assert replacement_claim and replacement_claim != publication["claim_id"]
            with factory() as session:
                replacement = session.get(JobRun, publication["job_id"])
                replacement_lease = replacement.lease_expires_at
                replacement_metadata = dict(replacement.metadata_json)
        finally:
            replacement_committed.set()
        assert pending.result(timeout=10) is False

    with factory() as session:
        job = session.get(JobRun, publication["job_id"])
        assert job.status == "running"
        assert job.claim_token == replacement_claim
        assert job.lease_expires_at == replacement_lease
        assert job.metadata_json == replacement_metadata
        assert job.attempt_count == 2
        assert job.finished_at is None
