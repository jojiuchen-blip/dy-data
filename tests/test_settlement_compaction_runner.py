"""Claimable settlement compaction runner tests.

SQLite covers the deterministic identity, claim exclusivity, end-to-end
publication and fail-closed behaviour.  PostgreSQL claim concurrency is gated
on the disposable release database exactly like the rebuild gate; it is never
simulated on SQLite.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    JobEvent,
    JobRun,
    SettlementProjectionActive,
    SettlementProjectionGeneration,
)
from apps.worker.legacy_projection_bootstrap import (
    CompactionThresholdConfig,
    ResourceGateConfig,
    compact_projection_metadata,
)
from apps.worker.settlement_compaction import (
    SETTLEMENT_COMPACTION_JOB_NAME,
    SettlementCompactionLeaseLost,
    claim_settlement_compaction_job,
    enqueue_settlement_compaction_job,
    run_settlement_compaction_job,
    settlement_compaction_job_id,
)
from tests.test_legacy_projection_bootstrap import (
    _factory,
    _limits,
    _seed_task3c_lineage,
)


def _ready_compact_head(db_session: Session) -> tuple[str, str]:
    ids = _seed_task3c_lineage(db_session, prefix="cmp-runner")
    result = compact_projection_metadata(
        _factory(db_session),
        base_generation_id=ids["head"],
        threshold_config=CompactionThresholdConfig(minimum_lineage_depth=1, batch_size=2),
        resource_limits=_limits(rows=10),
    )
    assert result.status == "ready"
    db_session.expire_all()
    return ids["head"], result.generation_id


def test_enqueue_is_deterministic_and_reuses_identity(db_session: Session) -> None:
    ids = _seed_task3c_lineage(db_session, prefix="cmp-enqueue")
    job_id = settlement_compaction_job_id(ids["head"])
    first = enqueue_settlement_compaction_job(
        _factory(db_session),
        base_generation_id=ids["head"],
        batch_size=2,
        resource_limits=_limits(rows=10),
    )
    second = enqueue_settlement_compaction_job(
        _factory(db_session),
        base_generation_id=ids["head"],
        batch_size=2,
        resource_limits=_limits(rows=10),
    )
    assert first == second == job_id
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(JobRun)
            .where(JobRun.job_name == SETTLEMENT_COMPACTION_JOB_NAME)
        )
        == 1
    )
    job = db_session.get(JobRun, job_id)
    assert job is not None and job.status == "queued"
    assert job.job_kind is None and job.execution_slot == "heavy_sync"

    with pytest.raises(ValueError, match="not the active settlement generation"):
        enqueue_settlement_compaction_job(
            _factory(db_session),
            base_generation_id="cmp-enqueue-unrelated",
            batch_size=2,
            resource_limits=_limits(rows=10),
        )


def test_enqueue_refuses_already_compact_head(db_session: Session) -> None:
    _head, compact_id = _ready_compact_head(db_session)
    # Publish through the runner to reach the compact-head state.
    job_id = enqueue_settlement_compaction_job(
        _factory(db_session),
        base_generation_id=_head,
        batch_size=2,
        resource_limits=_limits(rows=10),
    )
    claimed = claim_settlement_compaction_job(_factory(db_session))
    assert claimed is not None and claimed[0] == job_id
    result = run_settlement_compaction_job(
        job_id=job_id,
        factory=_factory(db_session),
        claim_id=claimed[1],
    )
    assert result["status"] == "success" and result["outcome"] == "published"

    db_session.expire_all()
    active = db_session.get(SettlementProjectionActive, "settlement")
    assert active is not None and active.generation_id == compact_id
    with pytest.raises(ValueError, match="already compact"):
        enqueue_settlement_compaction_job(
            _factory(db_session),
            base_generation_id=compact_id,
            batch_size=2,
            resource_limits=_limits(rows=10),
        )


def test_claim_is_exclusive_while_running(db_session: Session) -> None:
    ids = _seed_task3c_lineage(db_session, prefix="cmp-claim")
    enqueue_settlement_compaction_job(
        _factory(db_session),
        base_generation_id=ids["head"],
        batch_size=2,
        resource_limits=_limits(rows=10),
    )
    first = claim_settlement_compaction_job(_factory(db_session))
    assert first is not None
    assert claim_settlement_compaction_job(_factory(db_session)) is None


def test_claim_respects_global_heavy_slot(db_session: Session) -> None:
    from datetime import datetime, timezone

    ids = _seed_task3c_lineage(db_session, prefix="cmp-heavy")
    job_id = enqueue_settlement_compaction_job(
        _factory(db_session),
        base_generation_id=ids["head"],
        batch_size=2,
        resource_limits=_limits(rows=10),
    )
    blocker = JobRun(
        job_id="cmp-heavy-blocker",
        job_name="settlement-lineage:blocker",
        job_kind="finalize",
        status="running",
        execution_slot="heavy_sync",
        started_at=datetime.now(timezone.utc),
        claim_token="blocker-claim",
        lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        attempt_count=1,
        max_attempts=3,
    )
    db_session.add(blocker)
    db_session.flush()
    # Another running heavy_sync job holds the global slot.
    assert claim_settlement_compaction_job(_factory(db_session)) is None
    blocker.status = "success"
    db_session.flush()
    claimed = claim_settlement_compaction_job(_factory(db_session))
    assert claimed is not None and claimed[0] == job_id


def test_reclaim_after_lease_expiry_recovers_already_published(
    db_session: Session,
) -> None:
    from apps.api.dy_api.db import session_scope
    from apps.worker.projection_publish import publish_settlement_compaction
    from datetime import datetime, timezone

    ids = _seed_task3c_lineage(db_session, prefix="cmp-recover")
    head = ids["head"]
    job_id = enqueue_settlement_compaction_job(
        _factory(db_session),
        base_generation_id=head,
        batch_size=2,
        resource_limits=_limits(rows=10),
    )
    claimed = claim_settlement_compaction_job(_factory(db_session))
    assert claimed is not None and claimed[0] == job_id
    built = compact_projection_metadata(
        _factory(db_session),
        base_generation_id=head,
        threshold_config=CompactionThresholdConfig(
            minimum_lineage_depth=1, batch_size=2
        ),
        resource_limits=_limits(rows=10),
    )
    assert built.status == "ready" and built.generation_id is not None
    db_session.expire_all()
    factory = _factory(db_session)
    with session_scope(factory) as session:
        compact = session.get(SettlementProjectionGeneration, built.generation_id)
        assert compact is not None
        publish_settlement_compaction(
            session,
            job_id=job_id,
            claim_id=claimed[1],
            generation_id=built.generation_id,
            input_fingerprint=compact.input_fingerprint,
            manifest_checksum=built.manifest_checksum,
        )
    db_session.expire_all()
    job = db_session.get(JobRun, job_id)
    assert job is not None and job.status == "running"
    # Crash window: pointer published, job still running. Expire the lease.
    # Commit: the expiry simulates wall-clock passage and must survive the
    # following claim/run sessions on the shared connection.
    job.lease_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()

    reclaimed = claim_settlement_compaction_job(_factory(db_session))
    assert reclaimed is not None and reclaimed[0] == job_id
    outcome = run_settlement_compaction_job(
        job_id=job_id,
        factory=_factory(db_session),
        claim_id=reclaimed[1],
    )
    assert outcome["status"] == "success"
    assert outcome["outcome"] == "already_published"

    db_session.expire_all()
    job = db_session.get(JobRun, job_id)
    assert job is not None and job.status == "success"
    active = db_session.get(SettlementProjectionActive, "settlement")
    assert active is not None and active.generation_id == built.generation_id
    event_types = sorted(
        event.event_type
        for event in db_session.scalars(
            select(JobEvent).where(JobEvent.job_id == job_id)
        )
    )
    assert event_types == [
        "settlement_compaction_completed",
        "settlement_projection_published",
    ]


def test_fail_does_not_overwrite_expired_lease_state(db_session: Session) -> None:
    from datetime import datetime, timezone

    ids = _seed_task3c_lineage(db_session, prefix="cmp-expire")
    job_id = enqueue_settlement_compaction_job(
        _factory(db_session),
        base_generation_id=ids["head"],
        batch_size=2,
        resource_limits=_limits(rows=10),
    )
    claimed = claim_settlement_compaction_job(_factory(db_session))
    assert claimed is not None
    job = db_session.get(JobRun, job_id)
    assert job is not None
    # Commit the simulated clock passage so it survives the run/claim sessions
    # sharing this connection.
    job.lease_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()

    with pytest.raises(SettlementCompactionLeaseLost):
        run_settlement_compaction_job(
            job_id=job_id,
            factory=_factory(db_session),
            claim_id=claimed[1],
        )

    db_session.expire_all()
    job = db_session.get(JobRun, job_id)
    # An executor with an expired lease must not touch the job at all.
    assert job is not None and job.status == "running"
    assert job.claim_token == claimed[1]
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(JobEvent)
            .where(JobEvent.job_id == job_id)
        )
        == 0
    )
    # The expired row is reclaimable for a fresh, audited attempt.
    reclaimed = claim_settlement_compaction_job(_factory(db_session))
    assert reclaimed is not None and reclaimed[0] == job_id


def test_runner_publishes_and_audits_end_to_end(db_session: Session) -> None:
    ids = _seed_task3c_lineage(db_session, prefix="cmp-e2e")
    head = ids["head"]
    job_id = enqueue_settlement_compaction_job(
        _factory(db_session),
        base_generation_id=head,
        batch_size=2,
        resource_limits=_limits(rows=10),
    )
    claimed = claim_settlement_compaction_job(_factory(db_session))
    assert claimed is not None
    result = run_settlement_compaction_job(
        job_id=job_id,
        factory=_factory(db_session),
        claim_id=claimed[1],
    )

    assert result["status"] == "success"
    assert result["outcome"] == "published"
    db_session.expire_all()
    job = db_session.get(JobRun, job_id)
    assert job is not None and job.status == "success"
    compact_id = result["generation_id"]
    assert isinstance(compact_id, str)
    compact = db_session.get(SettlementProjectionGeneration, compact_id)
    assert compact is not None
    assert compact.generation_kind == "compact"
    assert compact.lineage_depth == 0
    assert compact.state == "published"
    active = db_session.get(SettlementProjectionActive, "settlement")
    assert active is not None and active.generation_id == compact_id
    events = list(
        db_session.scalars(select(JobEvent).where(JobEvent.job_id == job_id))
    )
    assert [event.event_type for event in events] == [
        "settlement_projection_published",
        "settlement_compaction_completed",
    ]
    assert db_session.scalar(
        select(func.count()).select_from(SettlementProjectionGeneration)
    ) == 3  # root + head + compact


def test_runner_fails_closed_without_touching_active_pointer(
    db_session: Session,
) -> None:
    from apps.api.dy_api.models import SettlementProjectionPartitionManifest

    head, compact_id = _ready_compact_head(db_session)
    job_id = enqueue_settlement_compaction_job(
        _factory(db_session),
        base_generation_id=head,
        batch_size=2,
        resource_limits=_limits(rows=10),
    )
    # Make this run the final attempt so a failure is terminal, not a retry.
    job_row = db_session.get(JobRun, job_id)
    assert job_row is not None
    job_row.attempt_count = 2
    db_session.flush()
    claimed = claim_settlement_compaction_job(_factory(db_session))
    assert claimed is not None
    # The compact head is already built and ready; tamper its actual manifest
    # so the publication evidence check must refuse while metadata looks fine.
    row = db_session.scalar(
        select(SettlementProjectionPartitionManifest)
        .where(
            SettlementProjectionPartitionManifest.generation_id == compact_id,
            SettlementProjectionPartitionManifest.owner_state == "owned",
        )
        .limit(1)
    )
    assert row is not None
    row.checksum = "f" * 64
    db_session.flush()

    with pytest.raises(RuntimeError, match="compaction"):
        run_settlement_compaction_job(
            job_id=job_id,
            factory=_factory(db_session),
            claim_id=claimed[1],
        )

    db_session.expire_all()
    job = db_session.get(JobRun, job_id)
    assert job is not None and job.status == "failed"
    active = db_session.get(SettlementProjectionActive, "settlement")
    assert active is not None and active.generation_id == head
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(JobEvent)
            .where(
                JobEvent.job_id == job_id,
                JobEvent.event_type == "settlement_compaction_failed",
            )
        )
        == 1
    )


def test_run_refuses_without_a_live_claim(db_session: Session) -> None:
    ids = _seed_task3c_lineage(db_session, prefix="cmp-noclaim")
    job_id = enqueue_settlement_compaction_job(
        _factory(db_session),
        base_generation_id=ids["head"],
        batch_size=2,
        resource_limits=_limits(rows=10),
    )
    with pytest.raises(SettlementCompactionLeaseLost):
        run_settlement_compaction_job(
            job_id=job_id,
            factory=_factory(db_session),
            claim_id=f"settlement-compaction-{uuid4().hex}",
        )
    db_session.expire_all()
    job = db_session.get(JobRun, job_id)
    assert job is not None and job.status == "queued"


@pytest.fixture
def compaction_pg():
    import os

    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import sessionmaker

    from apps.api.dy_api.models import Base

    raw_url = os.getenv("DY_RELEASE_POSTGRES_URL")
    if not raw_url:
        pytest.skip("requires disposable release PostgreSQL service")
    url = make_url(raw_url)
    if (
        not url.drivername.startswith("postgresql")
        or url.host not in {"127.0.0.1", "localhost"}
        or url.database != "dydata_release"
    ):
        pytest.fail("compaction gate requires loopback dydata_release database")
    schema = f"compaction_gate_{uuid4().hex}"
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
        # Real tables with every model constraint (checks, uniques, FKs) so the
        # runner exercises the production schema, including the unique running
        # heavy-slot index.
        Base.metadata.create_all(engine)
        yield factory
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def test_pg_concurrent_claims_are_exclusive(compaction_pg) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    factory = compaction_pg
    with factory() as session:
        # Flush order matters: the head's base_generation_id is a self-referential
        # FK and there is no ORM relationship, so the root must be flushed before
        # the head, and the active pointer after both.
        session.add(
            SettlementProjectionGeneration(
                generation_id="pg-compaction-root",
                generation_kind="legacy_root",
                projection_name="settlement",
                state="published",
                input_fingerprint="a" * 64,
                lineage_depth=0,
                checkpoint_json={},
                manifest_checksum="1" * 64,
                source_input_json={},
            )
        )
        session.flush()
        session.add(
            SettlementProjectionGeneration(
                generation_id="pg-compaction-head",
                generation_kind="lineage",
                projection_name="settlement",
                state="published",
                input_fingerprint="b" * 64,
                lineage_depth=1,
                base_generation_id="pg-compaction-root",
                checkpoint_json={},
                manifest_checksum="2" * 64,
                source_input_json={},
            )
        )
        session.flush()
        session.add(
            SettlementProjectionActive(
                projection_name="settlement",
                generation_id="pg-compaction-head",
            )
        )
        session.commit()
    job_id = enqueue_settlement_compaction_job(
        factory,
        base_generation_id="pg-compaction-head",
        batch_size=2,
        resource_limits=_limits(rows=10),
    )
    barrier = Barrier(2)
    results: list[object] = []

    def _claim() -> object:
        barrier.wait()
        return claim_settlement_compaction_job(factory)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_claim) for _ in range(2)]
        results = [future.result(timeout=30) for future in futures]

    winners = [claim for claim in results if claim is not None]
    assert len(winners) == 1
    assert winners[0][0] == job_id

    # App-level shared mutex: while the compaction job holds the heavy slot,
    # the heavy worker cannot claim any other heavy job.
    from datetime import datetime, timezone

    from apps.worker.repositories import claim_next_heavy_job

    with factory() as session:
        session.add(
            JobRun(
                job_id="pg-heavy-fixture",
                job_name="settlement-lineage:pg-fixture",
                job_kind="finalize",
                status="pending",
                execution_slot="heavy_sync",
                started_at=datetime.now(timezone.utc),
                attempt_count=0,
                max_attempts=3,
            )
        )
        session.commit()
    with factory() as session:
        assert (
            claim_next_heavy_job(
                session,
                lease_owner="test-worker",
                component_instance_id="test-instance",
                lease_seconds=300,
            )
            is None
        )
    # Database backstop: the unique running-slot index refuses a second
    # running heavy_sync row outright.
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        with factory() as session:
            session.execute(
                update(JobRun)
                .where(JobRun.job_id == "pg-heavy-fixture")
                .values(
                    status="running",
                    claim_token="fixture-claim",
                    lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
                )
            )
            session.commit()

    # Reverse direction: requeue the compaction job, hold the slot with the
    # running heavy fixture, and the compaction claim must be refused; with
    # the slot free the same job claims fine.
    with factory() as session:
        session.execute(
            update(JobRun)
            .where(JobRun.job_id == job_id)
            .values(
                status="queued",
                claim_token=None,
                lease_expires_at=None,
                attempt_count=0,
            )
        )
        session.execute(
            update(JobRun)
            .where(JobRun.job_id == "pg-heavy-fixture")
            .values(
                status="running",
                claim_token="fixture-claim",
                lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            )
        )
        session.commit()
    assert claim_settlement_compaction_job(factory, job_id=job_id) is None
    with factory() as session:
        session.execute(
            update(JobRun)
            .where(JobRun.job_id == "pg-heavy-fixture")
            .values(status="pending", claim_token=None, lease_expires_at=None)
        )
        session.commit()
    assert claim_settlement_compaction_job(factory, job_id=job_id) is not None


def test_builder_commits_are_refused_after_claim_loss(db_session: Session) -> None:
    from datetime import datetime, timezone

    from apps.worker.settlement_compaction import _claim_fenced_builder_factory

    ids = _seed_task3c_lineage(db_session, prefix="cmp-fence")
    job_id = enqueue_settlement_compaction_job(
        _factory(db_session),
        base_generation_id=ids["head"],
        batch_size=2,
        resource_limits=_limits(rows=10),
    )
    claimed = claim_settlement_compaction_job(_factory(db_session))
    assert claimed is not None
    job = db_session.get(JobRun, job_id)
    assert job is not None
    job.lease_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()
    fenced = _claim_fenced_builder_factory(
        _factory(db_session), job_id=job_id, claim_id=claimed[1]
    )
    before = db_session.scalar(
        select(func.count()).select_from(SettlementProjectionGeneration)
    )
    with pytest.raises(Exception) as excinfo:
        compact_projection_metadata(
            fenced,
            base_generation_id=ids["head"],
            threshold_config=CompactionThresholdConfig(
                minimum_lineage_depth=1, batch_size=2
            ),
            resource_limits=_limits(rows=10),
        )
    # The builder wrapper reports the refusal; the root cause is the lost claim.
    assert isinstance(
        excinfo.value.__cause__, SettlementCompactionLeaseLost
    ) or isinstance(excinfo.value, SettlementCompactionLeaseLost)
    db_session.expire_all()
    assert (
        db_session.scalar(
            select(func.count()).select_from(SettlementProjectionGeneration)
        )
        == before
    )
    # Positive control: a fresh claim fences through and builds.
    reclaimed = claim_settlement_compaction_job(_factory(db_session), job_id=job_id)
    assert reclaimed is not None and reclaimed[0] == job_id
    rebuilt = compact_projection_metadata(
        _claim_fenced_builder_factory(
            _factory(db_session), job_id=job_id, claim_id=reclaimed[1]
        ),
        base_generation_id=ids["head"],
        threshold_config=CompactionThresholdConfig(
            minimum_lineage_depth=1, batch_size=2
        ),
        resource_limits=_limits(rows=10),
    )
    assert rebuilt.status == "ready"


def test_claim_stops_when_monitor_unavailable(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.worker import resource_monitor

    ids = _seed_task3c_lineage(db_session, prefix="cmp-guard-missing")
    job_id = enqueue_settlement_compaction_job(
        _factory(db_session),
        base_generation_id=ids["head"],
        batch_size=2,
        resource_limits=_limits(rows=10),
    )
    monkeypatch.setenv("WORKER_RESOURCE_GUARD_ENABLED", "1")
    monkeypatch.setattr(resource_monitor, "_monitor", None)
    # Guard on but no live monitor must STOP, never implicitly allow.
    assert claim_settlement_compaction_job(_factory(db_session)) is None
    db_session.expire_all()
    job = db_session.get(JobRun, job_id)
    assert job is not None and job.status == "queued"


def test_claim_refuses_stop_decision(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.ops_agent.resources import ResourceAction, ResourceDecision

    ids = _seed_task3c_lineage(db_session, prefix="cmp-guard-stop")
    enqueue_settlement_compaction_job(
        _factory(db_session),
        base_generation_id=ids["head"],
        batch_size=2,
        resource_limits=_limits(rows=10),
    )
    monkeypatch.setattr(
        "apps.worker.settlement_compaction.current_resource_decision",
        lambda: ResourceDecision(ResourceAction.STOP, ("pressure-stop",)),
    )
    assert claim_settlement_compaction_job(_factory(db_session)) is None


def test_claim_refuses_drain_for_maintenance_job(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.ops_agent.resources import ResourceAction, ResourceDecision

    ids = _seed_task3c_lineage(db_session, prefix="cmp-guard-drain")
    enqueue_settlement_compaction_job(
        _factory(db_session),
        base_generation_id=ids["head"],
        batch_size=2,
        resource_limits=_limits(rows=10),
    )
    monkeypatch.setattr(
        "apps.worker.settlement_compaction.current_resource_decision",
        lambda: ResourceDecision(ResourceAction.DRAIN, ("history-paused",)),
    )
    # DRAIN only admits priority-daily daily_required work; the maintenance job
    # carries neither, so it must wait instead of faking its purpose.
    assert claim_settlement_compaction_job(_factory(db_session)) is None


def test_claim_proceeds_on_allow_decision(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.ops_agent.resources import ResourceAction, ResourceDecision

    ids = _seed_task3c_lineage(db_session, prefix="cmp-guard-allow")
    job_id = enqueue_settlement_compaction_job(
        _factory(db_session),
        base_generation_id=ids["head"],
        batch_size=2,
        resource_limits=_limits(rows=10),
    )
    monkeypatch.setattr(
        "apps.worker.settlement_compaction.current_resource_decision",
        lambda: ResourceDecision(ResourceAction.ALLOW, ()),
    )
    claimed = claim_settlement_compaction_job(_factory(db_session))
    assert claimed is not None and claimed[0] == job_id


def test_pg_runner_publishes_end_to_end(compaction_pg) -> None:
    from sqlalchemy.orm import Session as SASession

    factory = compaction_pg
    seed_session = SASession(bind=factory.kw["bind"])
    try:
        ids = _seed_task3c_lineage(seed_session, prefix="pg-cmp-e2e")
    finally:
        seed_session.close()
    job_id = enqueue_settlement_compaction_job(
        factory,
        base_generation_id=ids["head"],
        batch_size=2,
        resource_limits=_limits(rows=10),
    )
    claimed = claim_settlement_compaction_job(factory)
    assert claimed is not None and claimed[0] == job_id
    result = run_settlement_compaction_job(
        job_id=job_id,
        factory=factory,
        claim_id=claimed[1],
    )
    assert result["status"] == "success"
    assert result["outcome"] == "published"
    with factory() as session:
        active = session.get(SettlementProjectionActive, "settlement")
        compact = session.get(
            SettlementProjectionGeneration, result["generation_id"]
        )
        assert compact is not None
        assert active is not None and active.generation_id == compact.generation_id
        assert compact.generation_kind == "compact"
        assert compact.lineage_depth == 0
        assert compact.state == "published"
        job = session.get(JobRun, job_id)
        assert job is not None and job.status == "success"
        event_types = sorted(
            event.event_type
            for event in session.scalars(
                select(JobEvent).where(JobEvent.job_id == job_id)
            )
        )
        assert event_types == [
            "settlement_compaction_completed",
            "settlement_projection_published",
        ]


def test_pg_caller_rollback_refuses_publication(compaction_pg) -> None:
    from sqlalchemy.orm import Session as SASession

    from apps.worker.projection_publish import publish_settlement_compaction

    factory = compaction_pg
    seed_session = SASession(bind=factory.kw["bind"])
    try:
        ids = _seed_task3c_lineage(seed_session, prefix="pg-cmp-rollback")
    finally:
        seed_session.close()
    job_id = enqueue_settlement_compaction_job(
        factory,
        base_generation_id=ids["head"],
        batch_size=2,
        resource_limits=_limits(rows=10),
    )
    claimed = claim_settlement_compaction_job(factory)
    assert claimed is not None
    built = compact_projection_metadata(
        factory,
        base_generation_id=ids["head"],
        threshold_config=CompactionThresholdConfig(
            minimum_lineage_depth=1, batch_size=2
        ),
        resource_limits=_limits(rows=10),
    )
    assert built.status == "ready" and built.generation_id is not None
    with factory() as session:
        compact = session.get(SettlementProjectionGeneration, built.generation_id)
        assert compact is not None
        publish_settlement_compaction(
            session,
            job_id=job_id,
            claim_id=claimed[1],
            generation_id=built.generation_id,
            input_fingerprint=compact.input_fingerprint,
            manifest_checksum=built.manifest_checksum,
        )
        session.rollback()
    with factory() as session:
        active = session.get(SettlementProjectionActive, "settlement")
        assert active is not None and active.generation_id == ids["head"]
        generation = session.get(
            SettlementProjectionGeneration, built.generation_id
        )
        assert generation is not None and generation.state != "published"
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobEvent)
                .where(JobEvent.job_id == job_id)
            )
            == 0
        )
    # A live-claim run still publishes the ready head.
    result = run_settlement_compaction_job(
        job_id=job_id,
        factory=factory,
        claim_id=claimed[1],
    )
    assert result["outcome"] == "published"


def test_pg_expired_lease_refuses_run(compaction_pg) -> None:
    from datetime import datetime, timezone

    from sqlalchemy.orm import Session as SASession

    factory = compaction_pg
    seed_session = SASession(bind=factory.kw["bind"])
    try:
        ids = _seed_task3c_lineage(seed_session, prefix="pg-cmp-lease")
    finally:
        seed_session.close()
    job_id = enqueue_settlement_compaction_job(
        factory,
        base_generation_id=ids["head"],
        batch_size=2,
        resource_limits=_limits(rows=10),
    )
    claimed = claim_settlement_compaction_job(factory)
    assert claimed is not None
    with factory() as session:
        session.execute(
            update(JobRun)
            .where(JobRun.job_id == job_id)
            .values(
                lease_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)
            )
        )
        session.commit()
    with pytest.raises(SettlementCompactionLeaseLost):
        run_settlement_compaction_job(
            job_id=job_id,
            factory=factory,
            claim_id=claimed[1],
        )
    with factory() as session:
        job = session.get(JobRun, job_id)
        assert job is not None and job.status == "running"
        assert job.claim_token == claimed[1]
    # The expired row is reclaimable for a fresh audited attempt.
    reclaimed = claim_settlement_compaction_job(factory, job_id=job_id)
    assert reclaimed is not None and reclaimed[0] == job_id
