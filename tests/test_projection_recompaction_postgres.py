"""Repeat compaction through real builders with PostgreSQL provenance FKs."""

from copy import deepcopy

import pytest
from sqlalchemy import delete, func, select, text

from apps.api.dy_api.models import (
    JobRun, SettlementMonthlyOverlay, SettlementProjectionActive,
    SettlementProjectionCompactionClosure, SettlementProjectionGeneration,
    SettlementProjectionPartitionManifest,
)
from apps.worker import legacy_projection_bootstrap as bootstrap
from apps.worker import settlement, settlement_maintenance as maintenance
from apps.worker.legacy_projection_bootstrap import certify_legacy_null_root
from apps.worker.projection_lineage import LineageError, resolve_projection_partitions
from apps.worker.projection_publish import publish_settlement_rebuild
from apps.worker.settlement_compaction import (
    claim_settlement_compaction_job,
    enqueue_settlement_compaction_job,
    run_settlement_compaction_job,
    settlement_compaction_job_id,
)
from tests.test_legacy_projection_bootstrap import _limits
from tests.test_settlement_compaction_runner import compaction_pg
from tests.test_settlement_maintenance import _seed_depth
from tests.test_settlement_projection import (
    _finish_job,
    _running_job,
    _seed_fee_month,
)


def _publish_day(factory, *, generation_id, base_generation_id, affected_month):
    fingerprint = (generation_id.encode().hex() + "f" * 64)[:64]
    built = settlement.build_settlement_sparse_overlay(
        factory, generation_id=generation_id, base_generation_id=base_generation_id,
        affected_months=(affected_month,), batch_size=2, input_fingerprint=fingerprint,
    )
    settlement.mark_settlement_sparse_overlay_ready(
        factory, generation_id=generation_id, base_generation_id=base_generation_id,
        input_fingerprint=fingerprint,
    )
    job_id, claim_id = f"job-{generation_id}", f"claim-{generation_id}"
    with factory() as session:
        _running_job(session, job_id=job_id, job_name="settlement_rebuild", claim=claim_id)
        session.commit()
    with factory() as session, session.begin():
        publish_settlement_rebuild(
            session, job_id=job_id, claim_id=claim_id, generation_id=generation_id,
            base_generation_id=base_generation_id, input_fingerprint=fingerprint,
            manifest_checksum=built.manifest_checksum,
        )
        _finish_job(session, job_id)


def _cycle_limits():
    return _limits(rows=50, write=2 * 1024 ** 2, wal=4 * 1024 ** 2, headroom=8 * 1024 ** 2)


def _publish_compact(factory, *, base_generation_id, batch_size=2):
    job_id = enqueue_settlement_compaction_job(
        factory, base_generation_id=base_generation_id, batch_size=batch_size,
        resource_limits=_cycle_limits(),
    )
    claimed = claim_settlement_compaction_job(factory, job_id=job_id)
    assert claimed is not None
    result = run_settlement_compaction_job(job_id=job_id, factory=factory, claim_id=claimed[1])
    assert result["status"] == "success"
    return result["generation_id"]


def _build_compact(factory, base_generation_id, batch_size=2):
    return bootstrap.compact_projection_metadata(
        factory, base_generation_id=base_generation_id,
        threshold_config=bootstrap.CompactionThresholdConfig(1, batch_size),
        resource_limits=_cycle_limits(),
    )


def test_pg_recompaction_preserves_overlay_sources_from_previous_compact(compaction_pg):
    factory = compaction_pg
    with factory() as session:
        constraint = session.execute(text("""
            SELECT oid, contype, convalidated
            FROM pg_constraint
            WHERE conrelid = 'settlement_projection_partition_manifest'::regclass
              AND conname = 'fk_settlement_projection_manifest_compaction_source'
        """)).mappings().one()
        assert constraint["contype"] == "f" and constraint["convalidated"]
        assert session.scalar(text("SHOW session_replication_role")) == "origin"
        triggers = session.execute(text("""
            SELECT count(*) AS total, count(*) FILTER (WHERE tgenabled = 'D') AS disabled
            FROM pg_trigger WHERE tgconstraint = :constraint_oid
        """), {"constraint_oid": constraint["oid"]}).mappings().one()
        assert triggers["total"] > 0 and triggers["disabled"] == 0

    # Certify the empty root, then use normal sparse builders and audited
    # publishers. No synthetic closure or invalid generation metadata is used.
    root = certify_legacy_null_root(factory, batch_size=2, resource_limits=_limits(rows=50))
    assert root.published and root.generation_id is not None
    with factory() as session:
        for index, month in enumerate(("2026-10", "2026-11"), start=1):
            _seed_fee_month(session, prefix="pg-recompact", month=month, index=index)
        session.commit()
    _publish_day(
        factory, generation_id="pg-recompact-l1",
        base_generation_id=root.generation_id, affected_month="2026-10",
    )
    compact1 = _publish_compact(factory, base_generation_id="pg-recompact-l1")
    _publish_day(
        factory, generation_id="pg-recompact-l2",
        base_generation_id=compact1, affected_month="2026-11",
    )
    compact2 = _publish_compact(factory, base_generation_id="pg-recompact-l2")
    with factory() as session:
        assert session.get(SettlementProjectionActive, "settlement").generation_id == compact2
        resolved = resolve_projection_partitions(
            session, artifact="monthly", partition_keys=("2026-10", "2026-11"),
            pinned_generation_id=compact2,
        )
        assert resolved["2026-10"].actual_data_generation_id == "pg-recompact-l1"
        assert resolved["2026-11"].actual_data_generation_id == "pg-recompact-l2"


def test_pg_recompaction_closure_exceeds_direct_depth_and_replays_ready(compaction_pg):
    factory = compaction_pg
    with factory() as session:
        # Existing, checksum-consistent depth-64 fixture; real PostgreSQL FKs
        # remain enabled throughout both normal compaction publications.
        head = _seed_depth(session, 64)
        _seed_fee_month(session, prefix="pg-over65", month="2026-10", index=1)
        session.commit()
    compact1 = _publish_compact(factory, base_generation_id=head)
    _publish_day(factory, generation_id="pg-over65-next", base_generation_id=compact1,
                 affected_month="2026-10")
    estimate = maintenance.estimate_automatic_compaction(factory, base_generation_id="pg-over65-next")
    assert estimate.lineage_depth == 1 and estimate.closure_rows == 67
    with factory() as session:
        before = session.scalar(select(func.count()).select_from(SettlementMonthlyOverlay))
    ready = _build_compact(factory, "pg-over65-next")
    replay = _build_compact(factory, "pg-over65-next")
    assert ready.status == "ready" and replay.status == "already_ready"
    assert ready.generation_id == replay.generation_id and ready.source_generation_count == 67
    compact2 = _publish_compact(factory, base_generation_id="pg-over65-next")
    assert compact2 == ready.generation_id
    with factory() as session:
        resolved = resolve_projection_partitions(
            session, artifact="monthly", partition_keys=("2026-09", "2026-10"),
            pinned_generation_id=compact2,
        )
        assert resolved["2026-09"].actual_data_generation_id == "auto-64-head"
        assert resolved["2026-10"].actual_data_generation_id == "pg-over65-next"
        assert session.scalar(select(func.count()).select_from(SettlementMonthlyOverlay)) == before
        # The inherited closure still participates in validation after the new
        # compact gains a direct leaf membership; flattening must not hide drift.
        inherited = session.get(SettlementProjectionCompactionClosure, (compact1, "auto-64-head"))
        inherited.source_digest = "0" * 64
        session.commit()
        with pytest.raises(LineageError, match="source metadata"):
            resolve_projection_partitions(session, artifact="monthly", partition_keys=("2026-09",),
                                         pinned_generation_id=compact2)


def _partial_cycle(factory):
    root = certify_legacy_null_root(factory, batch_size=2, resource_limits=_cycle_limits())
    with factory() as session:
        for index, month in enumerate(("2026-09", "2026-10"), start=1):
            _seed_fee_month(session, prefix="pg-partial", month=month, index=index,
                            amounts=(index * 100, index * 10))
        session.commit()
    _publish_day(factory, generation_id="pg-partial-first", base_generation_id=root.generation_id,
                 affected_month="2026-10")
    compact1 = _publish_compact(factory, base_generation_id="pg-partial-first")
    # The new September partition sorts before the inherited October leaf,
    # so the original algorithm commits one page before the real FK fails.
    _publish_day(factory, generation_id="pg-partial-next", base_generation_id=compact1,
                 affected_month="2026-09")
    return "pg-partial-next"


def test_pg_original_partial_is_preserved_and_fixed_job_recovers(compaction_pg, monkeypatch):
    factory = compaction_pg
    base = _partial_cycle(factory)
    job_id = settlement_compaction_job_id(base)
    with monkeypatch.context() as original:
        original.setattr(bootstrap, "_load_compaction_provenance", lambda _factory, rows: [
            {"generation_id": row["generation_id"], "manifest_checksum": row["manifest_checksum"]}
            for row in rows
        ])
        with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="metadata compaction failed"):
            _publish_compact(factory, base_generation_id=base, batch_size=1)
    with factory() as session:
        old = session.scalar(select(SettlementProjectionGeneration).where(
            SettlementProjectionGeneration.compaction_base_generation_id == base,
        ))
        old_id, old_checkpoint = old.generation_id, deepcopy(old.checkpoint_json)
        assert old.state == "staging" and old_checkpoint["partition_count"] == 1
        job = session.get(JobRun, job_id)
        assert job.status == "queued" and job.attempt_count == 1 and job.max_attempts == 3

    fresh_limits = _limits(rows=50, write=2 * 1024 ** 2, wal=4 * 1024 ** 2, headroom=32 * 1024 ** 2)
    monkeypatch.setattr(maintenance, "disk_capacity_limits", lambda: fresh_limits)
    admitted = maintenance.automatic_runner_resource_limits(factory, base_generation_id=base, batch_size=1)
    assert admitted.observed_disk_headroom_bytes == fresh_limits.observed_disk_headroom_bytes
    ready = _build_compact(factory, base, batch_size=1)
    assert ready.status == "ready" and ready.generation_id != old_id
    admitted = maintenance.automatic_runner_resource_limits(factory, base_generation_id=base, batch_size=1)
    assert admitted.observed_disk_headroom_bytes == _cycle_limits().observed_disk_headroom_bytes

    # The only tolerated pair is the original partial and its current
    # deterministic replacement, sharing the unchanged effective checksum.
    with factory() as session:
        current = session.get(SettlementProjectionGeneration, ready.generation_id)
        current.state = "failed"
        session.commit()
    for use_current_identity in (False, True):
        with factory() as session:
            template_id = ready.generation_id if use_current_identity else old_id
            template = session.get(SettlementProjectionGeneration, template_id)
            values = {column.key: deepcopy(getattr(template, column.key))
                      for column in SettlementProjectionGeneration.__table__.columns}
            changed_effective = "e" * 64
            checksum = (values["source_input_json"].get("provenance_checksum")
                        if use_current_identity else None)
            head = session.get(SettlementProjectionGeneration, base)
            changed_fingerprint = bootstrap._compaction_fingerprint(
                base, head.manifest_checksum, changed_effective, checksum,
            )
            clone_id = f"settlement-compact:{changed_fingerprint}"
            values.update(generation_id=clone_id, input_fingerprint=changed_fingerprint,
                          state="staging", manifest_checksum=None, last_key=None)
            values["source_input_json"]["effective_checksum"] = changed_effective
            values["checkpoint_json"].update(
                phase="scan", partition_count=0, batch_count=0, cursor=None,
                effective_checksum=changed_effective,
            )
            session.add(SettlementProjectionGeneration(**values))
            session.flush()
            for source in session.scalars(select(SettlementProjectionCompactionClosure).where(
                SettlementProjectionCompactionClosure.compact_generation_id == template_id,
            )).all():
                session.add(SettlementProjectionCompactionClosure(
                    compact_generation_id=clone_id, source_generation_id=source.source_generation_id,
                    source_digest=source.source_digest,
                ))
            session.commit()
        with pytest.raises(maintenance.MaintenanceAdmissionError,
                           match="identity_invalid|multiple_compaction_checkpoints"):
            maintenance.automatic_runner_resource_limits(factory, base_generation_id=base, batch_size=1)
        with factory() as session:
            session.execute(delete(SettlementProjectionCompactionClosure).where(
                SettlementProjectionCompactionClosure.compact_generation_id == clone_id,
            ))
            session.execute(delete(SettlementProjectionGeneration).where(
                SettlementProjectionGeneration.generation_id == clone_id,
            ))
            session.commit()
    with factory() as session:
        session.get(SettlementProjectionGeneration, ready.generation_id).state = "ready"
        unknown = SettlementProjectionGeneration(
            generation_id="unknown-third-checkpoint", generation_kind="compact",
            compaction_base_generation_id=base, state="staging", lineage_depth=0,
            input_fingerprint="9" * 64, checkpoint_json={}, source_input_json={},
        )
        session.add(unknown)
        session.commit()
    with pytest.raises(maintenance.MaintenanceAdmissionError, match="multiple_compaction_checkpoints"):
        maintenance.automatic_runner_resource_limits(factory, base_generation_id=base, batch_size=1)
    with factory() as session:
        session.delete(session.get(SettlementProjectionGeneration, "unknown-third-checkpoint"))
        session.commit()

    recovered = _publish_compact(factory, base_generation_id=base, batch_size=1)
    assert recovered == ready.generation_id
    with factory() as session:
        old = session.get(SettlementProjectionGeneration, old_id)
        assert old.state == "staging" and old.checkpoint_json == old_checkpoint
        assert session.scalar(select(func.count()).select_from(SettlementProjectionPartitionManifest).where(
            SettlementProjectionPartitionManifest.generation_id == old_id,
        )) == 1
        job = session.get(JobRun, job_id)
        assert job.status == "success" and job.attempt_count == 2 and job.max_attempts == 3


def test_pg_expanded_closure_capacity_refuses_before_candidate_write(compaction_pg, monkeypatch):
    factory = compaction_pg
    base = _partial_cycle(factory)
    with factory() as session:
        before = session.scalar(select(func.count()).select_from(SettlementProjectionGeneration))
    # A reduced policy budget makes this real four-source union exceed the
    # guard without constructing invalid metadata or disabling any FK.
    monkeypatch.setattr(bootstrap, "MAX_COMPACT_PROVENANCE_SOURCES", 3)
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="maximum source count"):
        _build_compact(factory, base)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(SettlementProjectionGeneration)) == before
        assert session.get(SettlementProjectionActive, "settlement").generation_id == base
