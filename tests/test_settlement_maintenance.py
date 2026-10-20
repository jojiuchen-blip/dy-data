"""Automatic maintenance admission, bounded SQL, and retry recovery evidence."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import os
from types import SimpleNamespace
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.db import session_scope
from apps.api.dy_api.models import (
    Base, JobEvent, JobRun, SettlementProjectionActive, SettlementProjectionGeneration,
    SettlementProjectionPartitionManifest,
)
from apps.worker import legacy_projection_bootstrap as bootstrap
from apps.worker import settlement_compaction as runner
from apps.worker import settlement_maintenance as maintenance
from apps.worker.projection_publish import publish_settlement_compaction
from tests.test_legacy_projection_bootstrap import _factory, _limits, _seed_task3c_lineage


def _seed_depth(session: Session, depth: int = 48) -> str:
    ids = _seed_task3c_lineage(session, prefix=f"auto-{depth}")
    previous = ids["head"]
    for step in range(2, depth + 1):
        session.get(SettlementProjectionGeneration, previous).state = "superseded"
        generation_id = f"auto-{depth}-{step}"
        session.add(SettlementProjectionGeneration(
            generation_id=generation_id, base_generation_id=previous,
            generation_kind="lineage", state="published", lineage_depth=step,
            input_fingerprint=sha256(generation_id.encode()).hexdigest(),
            manifest_checksum=bootstrap._manifest_checksum([]),
        ))
        session.flush()
        previous = generation_id
    session.get(SettlementProjectionActive, "settlement").generation_id = previous
    session.commit()
    return previous


@pytest.fixture
def real_probe(tmp_path, monkeypatch):
    marker = tmp_path / "postgres-capacity"
    marker.write_bytes(maintenance.DISK_PROBE_MARKER)
    monkeypatch.setenv(maintenance.DISK_PROBE_ENV, str(marker))
    monkeypatch.setattr(maintenance.os, "statvfs", lambda _path: SimpleNamespace(
        f_blocks=100 * maintenance.GIB, f_bavail=30 * maintenance.GIB, f_frsize=1,
    ), raising=False)
    return marker


@pytest.mark.parametrize("total,available,reserve", [
    (100 * maintenance.GIB, 30 * maintenance.GIB, 15 * maintenance.GIB),
    (20 * maintenance.GIB, 12 * maintenance.GIB, 10 * maintenance.GIB),
    (100 * maintenance.GIB + 1, 30 * maintenance.GIB, 15 * maintenance.GIB + 1),
])
def test_disk_capacity_reserves_percent_and_absolute(real_probe, monkeypatch, total, available, reserve):
    monkeypatch.setattr(maintenance.os, "statvfs", lambda _path: SimpleNamespace(
        f_blocks=total, f_bavail=available, f_frsize=1,
    ))
    limits = maintenance.disk_capacity_limits()
    assert limits.min_disk_headroom_bytes == reserve
    assert limits.observed_disk_headroom_bytes == available
    assert limits.max_manifest_rows == 100_000
    assert limits.max_estimated_write_bytes == 512 * 1024 ** 2
    assert limits.max_estimated_wal_bytes == maintenance.GIB


@pytest.mark.parametrize("kind", ["missing", "directory", "wrong", "extra", "symlink", "devnull"])
def test_disk_probe_rejects_untrusted_evidence(tmp_path, monkeypatch, kind):
    probe = tmp_path / "probe"
    if kind == "directory":
        probe.mkdir()
    elif kind == "wrong":
        probe.write_bytes(b"wrong\n")
    elif kind == "extra":
        probe.write_bytes(maintenance.DISK_PROBE_MARKER + b"extra")
    elif kind == "symlink":
        target = tmp_path / "target"
        target.write_bytes(maintenance.DISK_PROBE_MARKER)
        try:
            probe.symlink_to(target)
        except OSError:
            pytest.skip("symlink creation unavailable to current Windows account")
    elif kind == "devnull":
        probe = maintenance.os.devnull
    monkeypatch.setattr(maintenance.os, "statvfs", lambda _path: pytest.fail("must reject before statvfs"), raising=False)
    with pytest.raises(maintenance.MaintenanceAdmissionError):
        maintenance.disk_capacity_limits(str(probe))


@pytest.mark.parametrize("depth", [0, 1, 47])
def test_threshold_before_48_does_not_probe_or_allocate(db_session, monkeypatch, depth):
    if depth:
        _seed_depth(db_session, depth)
    monkeypatch.setattr(maintenance, "disk_capacity_limits", lambda: pytest.fail("threshold must be cheap"))
    monkeypatch.setattr(maintenance, "estimate_automatic_compaction", lambda *args, **kwargs: pytest.fail("no estimate"))
    assert maintenance.process_automatic_settlement_maintenance(_factory(db_session)) is False
    assert db_session.scalar(select(func.count()).select_from(JobRun)) == 0


def test_disabled_at_threshold_reserves_tick(db_session, monkeypatch):
    _seed_depth(db_session)
    monkeypatch.setenv("SETTLEMENT_AUTOMATIC_MAINTENANCE_ENABLED", "false")
    monkeypatch.setattr(maintenance, "disk_capacity_limits", lambda: pytest.fail("disabled"))
    assert maintenance.process_automatic_settlement_maintenance(_factory(db_session)) is True
    assert db_session.scalar(select(func.count()).select_from(JobRun)) == 0


def test_missing_probe_at_threshold_reserves_tick(db_session, monkeypatch, tmp_path):
    _seed_depth(db_session)
    monkeypatch.setenv(maintenance.DISK_PROBE_ENV, str(tmp_path / "missing"))
    assert maintenance.process_automatic_settlement_maintenance(_factory(db_session)) is True
    assert db_session.scalar(select(func.count()).select_from(JobRun)) == 0


def test_invalid_active_publication_defers_safely(db_session):
    head = _seed_depth(db_session)
    db_session.get(SettlementProjectionGeneration, head).state = "superseded"
    db_session.commit()
    assert maintenance.process_automatic_settlement_maintenance(_factory(db_session)) is True
    assert db_session.scalar(select(func.count()).select_from(JobRun)) == 0


def test_estimate_is_direct_distinct_and_includes_tombstones(db_session):
    head = _seed_depth(db_session)
    # Duplicate the existing tombstone on another direct generation. DISTINCT
    # must count the logical partition once, including deleted partitions.
    db_session.add(SettlementProjectionPartitionManifest(
        generation_id=head, artifact="ranking", partition_key="monthly:2026-09",
        owner_state="tombstone", source_kind="tombstone", row_count=0,
    ))
    db_session.commit()
    queries = []
    engine = db_session.get_bind()
    def capture(_connection, _cursor, statement, _params, _context, _many):
        queries.append(statement)
    event.listen(engine, "before_cursor_execute", capture)
    try:
        estimate = maintenance.estimate_automatic_compaction(_factory(db_session), base_generation_id=head)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert estimate.closure_rows == 49
    assert estimate.manifest_rows == 2  # overlay + tombstone; legacy root excluded
    assert len(queries) == 2
    assert "DISTINCT" in queries[-1] and "count(" in queries[-1].lower()
    assert all("compaction_closure" not in query and "checksum" not in query for query in queries)


def test_estimate_stops_at_compact_ancestor(db_session):
    head = _seed_depth(db_session)
    terminal = db_session.get(SettlementProjectionGeneration, "auto-48-root")
    terminal.generation_kind = "compact"
    terminal.compaction_base_generation_id = "historic-provenance-not-traversed"
    db_session.commit()
    estimate = maintenance.estimate_automatic_compaction(_factory(db_session), base_generation_id=head)
    assert estimate.closure_rows == 49 and estimate.manifest_rows == 2


def test_estimate_refuses_chain_beyond_hard_64(db_session):
    head = _seed_depth(db_session, 65)
    with pytest.raises(maintenance.MaintenanceAdmissionError, match="too_deep"):
        maintenance.estimate_automatic_compaction(_factory(db_session), base_generation_id=head)


@pytest.mark.parametrize("failure", ["manifest", "write", "wal", "disk"])
def test_each_resource_budget_is_enforced(failure):
    estimate = maintenance.MaintenanceEstimate("head", 48, 49, 100)
    limits = dict(max_manifest_rows=100, max_estimated_write_bytes=10_000_000,
                  max_estimated_wal_bytes=20_000_000,
                  observed_disk_headroom_bytes=100_000_000, min_disk_headroom_bytes=10_000_000)
    key = {"manifest": "max_manifest_rows", "write": "max_estimated_write_bytes",
           "wal": "max_estimated_wal_bytes", "disk": "observed_disk_headroom_bytes"}[failure]
    limits[key] = 0
    with pytest.raises(maintenance.MaintenanceAdmissionError):
        maintenance._check_estimate(estimate, bootstrap.ResourceGateConfig(**limits))


def test_same_base_reuses_job_and_runs_full_publication(db_session, real_probe):
    head = _seed_depth(db_session)
    factory = _factory(db_session)
    assert maintenance.process_automatic_settlement_maintenance(factory) is True
    db_session.expire_all()
    job = db_session.get(JobRun, runner.settlement_compaction_job_id(head))
    assert job.status == "success" and job.attempt_count == 1 and job.max_attempts == 3
    assert job.metadata_json["trigger"] == maintenance.AUTOMATIC_MAINTENANCE_TRIGGER
    assert maintenance.process_automatic_settlement_maintenance(factory) is False
    assert db_session.scalar(select(func.count()).select_from(JobRun)) == 1
    compact = db_session.get(SettlementProjectionGeneration, job.metadata_json["result"]["generationId"])
    assert compact.generation_kind == "compact" and compact.lineage_depth == 0


def test_queued_same_base_and_terminal_exhaustion_never_reset(db_session, real_probe, monkeypatch):
    head = _seed_depth(db_session)
    factory = _factory(db_session)
    monkeypatch.setattr(runner, "claim_settlement_compaction_job", lambda *args, **kwargs: None)
    for _tick in range(3):
        assert maintenance.process_automatic_settlement_maintenance(factory) is True
    db_session.expire_all()
    job = db_session.get(JobRun, runner.settlement_compaction_job_id(head))
    assert job.attempt_count == 0
    job.status = "failed"
    job.attempt_count = 3
    db_session.commit()
    for _tick in range(3):
        assert maintenance.process_automatic_settlement_maintenance(factory) is True
    db_session.expire_all()
    job = db_session.get(JobRun, job.job_id)
    assert job.status == "failed" and job.attempt_count == 3
    assert job.metadata_json["maintenance_blocked_reason"] == "attempts_exhausted"
    assert db_session.scalar(select(func.count()).select_from(JobRun)) == 1
    assert db_session.scalar(select(func.count()).select_from(JobEvent)) == 1


def test_expired_same_base_reclaims_existing_identity(db_session, real_probe):
    head = _seed_depth(db_session)
    factory = _factory(db_session)
    job_id = runner.enqueue_settlement_compaction_job(factory, base_generation_id=head,
        batch_size=400, resource_limits=maintenance.disk_capacity_limits(),
        trigger=maintenance.AUTOMATIC_MAINTENANCE_TRIGGER)
    first_claim = runner.claim_settlement_compaction_job(factory, job_id=job_id)
    assert first_claim is not None
    db_session.expire_all()
    job = db_session.get(JobRun, job_id)
    job.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    assert maintenance.process_automatic_settlement_maintenance(factory) is True
    db_session.expire_all()
    job = db_session.get(JobRun, job_id)
    assert job.status == "success" and job.attempt_count == 2
    assert db_session.scalar(select(func.count()).select_from(JobRun)) == 1


def test_stale_base_has_failed_audit_and_no_fake_success(db_session, real_probe):
    ids = _seed_task3c_lineage(db_session, prefix="auto-stale")
    factory = _factory(db_session)
    job_id = runner.enqueue_settlement_compaction_job(factory, base_generation_id=ids["head"], batch_size=2,
        resource_limits=_limits(), trigger=maintenance.AUTOMATIC_MAINTENANCE_TRIGGER)
    db_session.expire_all()
    db_session.get(SettlementProjectionActive, "settlement").generation_id = ids["root"]
    db_session.get(SettlementProjectionGeneration, ids["root"]).state = "published"
    db_session.commit()
    assert maintenance.process_automatic_settlement_maintenance(factory) is False
    db_session.expire_all()
    job = db_session.get(JobRun, job_id)
    assert job.status == "failed" and job.success_count == 0
    assert job.error_code == "settlement_compaction_stale_base"
    audit = db_session.scalar(select(JobEvent).where(JobEvent.job_id == job_id))
    assert audit.payload_json == {"base_generation_id": ids["head"], "current_base": ids["root"]}


def test_publication_receipt_recovers_before_stale_and_resource_probe(db_session, monkeypatch):
    ids = _seed_task3c_lineage(db_session, prefix="auto-receipt")
    factory = _factory(db_session)
    job_id = runner.enqueue_settlement_compaction_job(factory, base_generation_id=ids["head"],
        batch_size=2, resource_limits=_limits(), trigger=maintenance.AUTOMATIC_MAINTENANCE_TRIGGER)
    # Simulate the pre-publication automatic admission, then a committed publish
    # followed by a process crash before the JobRun success transition.
    monkeypatch.setattr(maintenance, "automatic_runner_resource_limits", lambda *args, **kwargs: _limits())
    claimed = runner.claim_settlement_compaction_job(factory, job_id=job_id)
    assert claimed is not None
    built = bootstrap.compact_projection_metadata(factory, base_generation_id=ids["head"],
        threshold_config=bootstrap.CompactionThresholdConfig(1, 2), resource_limits=_limits())
    with session_scope(factory) as session:
        compact = session.get(SettlementProjectionGeneration, built.generation_id)
        publish_settlement_compaction(session, job_id=job_id, claim_id=claimed[1],
            generation_id=built.generation_id, input_fingerprint=compact.input_fingerprint,
            manifest_checksum=built.manifest_checksum)
        job = session.get(JobRun, job_id)
        job.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        job.attempt_count = 3  # receipt recovery needs no fourth attempt
    monkeypatch.setattr(maintenance, "disk_capacity_limits", lambda: pytest.fail("receipt must win"))
    assert maintenance.process_automatic_settlement_maintenance(factory) is False
    db_session.expire_all()
    job = db_session.get(JobRun, job_id)
    assert job.status == "success" and job.attempt_count == 3
    assert job.metadata_json["result"]["outcome"] == "already_published"


def test_resource_change_before_claim_preserves_attempt_budget(db_session, real_probe, monkeypatch):
    head = _seed_depth(db_session)
    factory = _factory(db_session)
    job_id = runner.enqueue_settlement_compaction_job(factory, base_generation_id=head,
        batch_size=400, resource_limits=maintenance.disk_capacity_limits(),
        trigger=maintenance.AUTOMATIC_MAINTENANCE_TRIGGER)
    monkeypatch.setattr(maintenance, "disk_capacity_limits", lambda: (_ for _ in ()).throw(
        maintenance.MaintenanceAdmissionError("capacity_changed")))
    assert runner.claim_settlement_compaction_job(factory, job_id=job_id) is None
    db_session.expire_all()
    assert db_session.get(JobRun, job_id).attempt_count == 0


def test_post_claim_resource_race_refunds_claim_without_builder(db_session, real_probe, monkeypatch):
    head = _seed_depth(db_session)
    factory = _factory(db_session)
    job_id = runner.enqueue_settlement_compaction_job(factory, base_generation_id=head,
        batch_size=400, resource_limits=maintenance.disk_capacity_limits(),
        trigger=maintenance.AUTOMATIC_MAINTENANCE_TRIGGER)
    claimed = runner.claim_settlement_compaction_job(factory, job_id=job_id)
    assert claimed is not None
    monkeypatch.setattr(maintenance, "disk_capacity_limits", lambda: (_ for _ in ()).throw(
        maintenance.MaintenanceAdmissionError("capacity_changed")))
    monkeypatch.setattr(runner, "compact_projection_metadata", lambda *args, **kwargs: pytest.fail("no builder"))
    assert runner.run_settlement_compaction_job(job_id=job_id, factory=factory, claim_id=claimed[1])["status"] == "deferred"
    db_session.expire_all()
    job = db_session.get(JobRun, job_id)
    assert job.status == "queued" and job.attempt_count == 0


def test_changed_disk_observation_does_not_invalidate_ready_checkpoint(db_session, real_probe, monkeypatch):
    ids = _seed_task3c_lineage(db_session, prefix="auto-resume")
    factory = _factory(db_session)
    first_limits = maintenance.disk_capacity_limits()
    built = bootstrap.compact_projection_metadata(factory, base_generation_id=ids["head"],
        threshold_config=bootstrap.CompactionThresholdConfig(1, 2), resource_limits=first_limits)
    assert built.status == "ready"
    monkeypatch.setattr(maintenance.os, "statvfs", lambda _path: SimpleNamespace(
        f_blocks=100 * maintenance.GIB, f_bavail=25 * maintenance.GIB, f_frsize=1))
    job_id = runner.enqueue_settlement_compaction_job(factory, base_generation_id=ids["head"], batch_size=2,
        resource_limits=first_limits, trigger=maintenance.AUTOMATIC_MAINTENANCE_TRIGGER)
    claimed = runner.claim_settlement_compaction_job(factory, job_id=job_id)
    assert claimed is not None
    result = runner.run_settlement_compaction_job(job_id=job_id, factory=factory, claim_id=claimed[1])
    assert result["outcome"] == "published"
    db_session.expire_all()
    compact = db_session.get(SettlementProjectionGeneration, built.generation_id)
    assert compact.estimated_disk_headroom_bytes == 15 * maintenance.GIB


def test_genuine_builder_failure_keeps_three_attempt_budget(db_session, real_probe, monkeypatch):
    head = _seed_depth(db_session)
    def fail(*args, **kwargs):
        raise RuntimeError("builder failure evidence")
    monkeypatch.setattr(runner, "compact_projection_metadata", fail)
    for attempt in range(1, 4):
        with pytest.raises(RuntimeError, match="builder failure evidence"):
            maintenance.process_automatic_settlement_maintenance(_factory(db_session))
        db_session.expire_all()
        job = db_session.get(JobRun, runner.settlement_compaction_job_id(head))
        assert job.attempt_count == attempt
    assert job.status == "failed"
    assert maintenance.process_automatic_settlement_maintenance(_factory(db_session)) is True
    db_session.expire_all()
    assert db_session.get(JobRun, job.job_id).attempt_count == 3


def test_checkpoint_rejects_unrelated_identity_and_still_checks_live_space(db_session, real_probe, monkeypatch):
    ids = _seed_task3c_lineage(db_session, prefix="auto-corrupt")
    factory = _factory(db_session)
    built = bootstrap.compact_projection_metadata(factory, base_generation_id=ids["head"],
        threshold_config=bootstrap.CompactionThresholdConfig(1, 2),
        resource_limits=maintenance.disk_capacity_limits())
    db_session.expire_all()
    compact = db_session.get(SettlementProjectionGeneration, built.generation_id)
    source = dict(compact.source_input_json)
    source["protocol"] = "unrelated"
    compact.source_input_json = source
    db_session.commit()
    with pytest.raises(maintenance.MaintenanceAdmissionError, match="identity_invalid"):
        maintenance.automatic_runner_resource_limits(factory, base_generation_id=ids["head"], batch_size=2)
    # A perfectly valid old checkpoint cannot stand in for current disk space.
    compact.source_input_json = {**source, "protocol": bootstrap.COMPACTION_PROTOCOL}
    db_session.commit()
    monkeypatch.setattr(maintenance.os, "statvfs", lambda _path: SimpleNamespace(
        f_blocks=100 * maintenance.GIB, f_bavail=15 * maintenance.GIB, f_frsize=1))
    with pytest.raises(maintenance.MaintenanceAdmissionError, match="disk_headroom"):
        maintenance.automatic_runner_resource_limits(factory, base_generation_id=ids["head"], batch_size=2)


def test_resource_policy_and_cooldown_prevent_attempts(db_session, real_probe, monkeypatch):
    head = _seed_depth(db_session)
    factory = _factory(db_session)
    job_id = runner.enqueue_settlement_compaction_job(factory, base_generation_id=head,
        batch_size=400, resource_limits=maintenance.disk_capacity_limits(),
        trigger=maintenance.AUTOMATIC_MAINTENANCE_TRIGGER)
    assert runner.claim_settlement_compaction_job(factory, job_id=job_id, resource_decision="stop") is None
    monkeypatch.setattr(runner, "heavy_sync_rate_limit_cooldown_active", lambda session: True)
    assert runner.claim_settlement_compaction_job(factory, job_id=job_id, resource_decision="allow") is None
    db_session.expire_all()
    assert db_session.get(JobRun, job_id).attempt_count == 0


def test_quota_pause_does_not_allow_fourth_compaction_attempt(db_session):
    ids = _seed_task3c_lineage(db_session, prefix="auto-hard-budget")
    factory = _factory(db_session)
    job_id = runner.enqueue_settlement_compaction_job(factory, base_generation_id=ids["head"],
        batch_size=2, resource_limits=_limits())
    db_session.expire_all()
    job = db_session.get(JobRun, job_id)
    job.attempt_count = 3
    job.max_attempts = 3
    job.quota_pause_count = 3
    db_session.commit()
    assert runner.claim_settlement_compaction_job(factory, job_id=job_id) is None


def test_manual_identity_is_not_automatically_taken_over(db_session, real_probe):
    head = _seed_depth(db_session)
    job_id = runner.enqueue_settlement_compaction_job(_factory(db_session), base_generation_id=head,
        batch_size=2, resource_limits=_limits())
    assert maintenance.process_automatic_settlement_maintenance(_factory(db_session)) is True
    db_session.expire_all()
    job = db_session.get(JobRun, job_id)
    assert job.status == "queued" and job.attempt_count == 0
    assert "trigger" not in job.metadata_json


def test_old_head_snapshot_does_not_stale_new_active_queued_job(db_session, real_probe, monkeypatch):
    current = _seed_depth(db_session)
    factory = _factory(db_session)
    job_id = runner.enqueue_settlement_compaction_job(factory, base_generation_id=current,
        batch_size=400, resource_limits=maintenance.disk_capacity_limits(),
        trigger=maintenance.AUTOMATIC_MAINTENANCE_TRIGGER)
    old = db_session.get(SettlementProjectionGeneration, current).base_generation_id
    monkeypatch.setattr(maintenance, "_active_head", lambda factory: (old, 47, "lineage"))
    assert maintenance.process_automatic_settlement_maintenance(factory) is True
    db_session.expire_all()
    job = db_session.get(JobRun, job_id)
    assert job.status == "queued" and job.attempt_count == 0 and job.error_code is None
    assert db_session.scalar(select(func.count()).select_from(JobEvent)) == 0


@pytest.fixture
def maintenance_pg():
    """Explicit disposable DB only; every invocation owns a unique schema."""
    raw_url = os.getenv("DY_MAINTENANCE_POSTGRES_URL")
    if not raw_url:
        pytest.skip("requires disposable maintenance PostgreSQL")
    url = make_url(raw_url)
    if (not url.drivername.startswith("postgresql")
            or url.host not in {"127.0.0.1", "localhost"}
            or url.database not in {"dydata104_test", "dydata_release"}):
        pytest.fail("maintenance tests require an explicitly named loopback disposable database")
    schema = f"maintenance_gate_{uuid4().hex}"
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-c search_path={schema}"})
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        Base.metadata.create_all(engine)
        yield factory
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def test_pg_direct_distinct_estimate_and_full_automatic_publication(maintenance_pg, real_probe):
    factory = maintenance_pg
    empty_checksum = bootstrap._manifest_checksum([])
    with factory() as session:
        previous = None
        for depth in range(49):
            generation_id = f"pg-auto-{depth}"
            manifests = [] if depth == 0 else [{
                "artifact": "ranking", "partition_key": "monthly:2026-09",
                "owner_state": "tombstone", "source_kind": "tombstone",
                "data_generation_id": None, "base_generation_id": previous,
                "row_count": 0, "amount_total_cent": 0,
                "status_counts_json": {}, "checksum": None, "last_key": None,
            }]
            session.add(SettlementProjectionGeneration(
                generation_id=generation_id, base_generation_id=previous,
                generation_kind="legacy_root" if depth == 0 else "lineage",
                state="published" if depth == 48 else "superseded", lineage_depth=depth,
                input_fingerprint=sha256(generation_id.encode()).hexdigest(),
                manifest_checksum=empty_checksum if depth == 0 else bootstrap._manifest_checksum(manifests),
            ))
            session.flush()
            for manifest in manifests:
                session.add(SettlementProjectionPartitionManifest(generation_id=generation_id, **manifest))
            session.flush()
            previous = generation_id
        session.add(SettlementProjectionActive(projection_name="settlement", generation_id=previous))
        session.commit()
    estimate = maintenance.estimate_automatic_compaction(factory, base_generation_id=previous)
    assert estimate.closure_rows == 49 and estimate.manifest_rows == 1
    assert maintenance.process_automatic_settlement_maintenance(factory) is True
    with factory() as session:
        job = session.get(JobRun, runner.settlement_compaction_job_id(previous))
        assert job.status == "success" and job.attempt_count == 1
        active = session.get(SettlementProjectionActive, "settlement")
        compact = session.get(SettlementProjectionGeneration, active.generation_id)
        assert compact.lineage_depth == 0 and compact.generation_kind == "compact"
        assert session.scalar(select(func.count()).select_from(SettlementProjectionPartitionManifest).where(
            SettlementProjectionPartitionManifest.generation_id == compact.generation_id)) == 1


def test_pg_manifest_aggregate_stops_at_first_over_budget_key(maintenance_pg):
    """Representative 100k scale: one server aggregate, zero payload loading."""
    factory = maintenance_pg
    with factory() as session:
        session.add(SettlementProjectionGeneration(
            generation_id="pg-scale", generation_kind="lineage", state="published",
            lineage_depth=0, input_fingerprint="c" * 64,
            manifest_checksum=bootstrap._manifest_checksum([]),
        ))
        session.flush()
        session.execute(text("""
            INSERT INTO settlement_projection_partition_manifest
                (generation_id, artifact, partition_key, owner_state, source_kind,
                 row_count, amount_total_cent, status_counts_json, created_at)
            SELECT 'pg-scale', 'ranking', 'test-key-' || item::text,
                   'tombstone', 'tombstone', 0, 0, '{}'::jsonb, clock_timestamp()
            FROM generate_series(1, 100100) AS item
        """))
        session.commit()
    estimate = maintenance.estimate_automatic_compaction(factory, base_generation_id="pg-scale")
    assert estimate.manifest_rows == 100_001 and estimate.closure_rows == 1
    with pytest.raises(maintenance.MaintenanceAdmissionError, match="manifest_rows"):
        maintenance._check_estimate(estimate, _limits(rows=maintenance.MAX_MANIFEST_ROWS))


def _seed_pg_reconcile_head(factory, *, generation_id="pg-reconcile-old", depth=47):
    with session_scope(factory) as session:
        session.add(SettlementProjectionGeneration(
            generation_id=generation_id, generation_kind="lineage", state="published",
            lineage_depth=depth, input_fingerprint=sha256(generation_id.encode()).hexdigest(),
            manifest_checksum=bootstrap._manifest_checksum([]),
        ))
        session.flush()
        session.add(SettlementProjectionActive(projection_name="settlement", generation_id=generation_id))
    return generation_id


def test_pg_head_advances_between_snapshot_and_reconciliation(maintenance_pg, monkeypatch):
    """Two physical connections reproduce the reviewed publication interleave."""
    factory = maintenance_pg
    old = _seed_pg_reconcile_head(factory)
    current = "pg-reconcile-current"
    snapshot_read = Event()
    publication_committed = Event()
    original_head = maintenance._active_head
    backend_ids = {}

    def pause_after_head(thread_factory):
        head = original_head(thread_factory)
        with thread_factory() as session:
            backend_ids["snapshot"] = session.scalar(select(func.pg_backend_pid()))
        snapshot_read.set()
        assert publication_committed.wait(10), "publication interleave did not complete"
        return head

    monkeypatch.setattr(maintenance, "_active_head", pause_after_head)

    def reconcile_on_held_connection():
        # Keep A's physical connection checked out while B commits the pointer
        # and new job, so this cannot accidentally be a one-connection test.
        with factory.kw["bind"].connect() as connection:
            thread_factory = sessionmaker(bind=connection, autoflush=False, expire_on_commit=False)
            return maintenance.process_automatic_settlement_maintenance(thread_factory)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(reconcile_on_held_connection)
        try:
            assert snapshot_read.wait(10), "old snapshot was not read"
            with session_scope(factory) as session:
                backend_ids["publisher"] = session.scalar(select(func.pg_backend_pid()))
                session.get(SettlementProjectionGeneration, old).state = "superseded"
                session.add(SettlementProjectionGeneration(
                    generation_id=current, base_generation_id=old,
                    generation_kind="lineage", state="published", lineage_depth=48,
                    input_fingerprint=sha256(current.encode()).hexdigest(),
                    manifest_checksum=bootstrap._manifest_checksum([]),
                ))
                session.flush()
                session.get(SettlementProjectionActive, "settlement").generation_id = current
            job_id = runner.enqueue_settlement_compaction_job(factory, base_generation_id=current,
                batch_size=400, resource_limits=_limits(),
                trigger=maintenance.AUTOMATIC_MAINTENANCE_TRIGGER)
        finally:
            publication_committed.set()
        assert future.result(timeout=10) is True
    assert backend_ids["snapshot"] != backend_ids["publisher"]
    with factory() as session:
        assert session.get(SettlementProjectionActive, "settlement").generation_id == current
        job = session.get(JobRun, job_id)
        assert job.status == "queued" and job.attempt_count == 0 and job.error_code is None
        assert session.scalar(select(func.count()).select_from(JobEvent)) == 0


def test_pg_active_lock_conflict_defers_and_releases_job_for_claim(maintenance_pg, monkeypatch):
    """A publisher's active lock must not leave reconciliation holding a job."""
    factory = maintenance_pg
    current = _seed_pg_reconcile_head(factory, generation_id="pg-reconcile-locked", depth=48)
    job_id = runner.enqueue_settlement_compaction_job(factory, base_generation_id=current,
        batch_size=400, resource_limits=_limits(), trigger=maintenance.AUTOMATIC_MAINTENANCE_TRIGGER)
    # This test isolates lock order. SQL estimation and real resource admission
    # are exercised by the separate complete PG publication test above.
    monkeypatch.setattr(maintenance, "automatic_runner_resource_limits", lambda *args, **kwargs: _limits())
    with factory() as publisher:
        publisher.scalar(select(SettlementProjectionActive).where(
            SettlementProjectionActive.projection_name == "settlement").with_for_update())
        with ThreadPoolExecutor(max_workers=1) as executor:
            deferred = executor.submit(maintenance.process_automatic_settlement_maintenance, factory)
            assert deferred.result(timeout=5) is True
        with factory() as session:
            job = session.get(JobRun, job_id)
            assert job.status == "queued" and job.attempt_count == 0
            assert session.scalar(select(func.count()).select_from(JobEvent)) == 0
        # Still holding active on the publisher connection: the failed NOWAIT
        # path must have rolled back and released its JobRun lock, admitting a
        # concurrent claim without any lock cycle or consumed failed attempt.
        claimed = runner.claim_settlement_compaction_job(factory, job_id=job_id, resource_decision="allow")
        assert claimed is not None
        with factory() as session:
            job = session.get(JobRun, job_id)
            assert job.status == "running" and job.attempt_count == 1
