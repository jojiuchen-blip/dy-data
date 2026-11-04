"""Repeat compaction through real builders with PostgreSQL provenance FKs."""

from sqlalchemy import text

from apps.api.dy_api.models import SettlementProjectionActive
from apps.worker import settlement
from apps.worker.legacy_projection_bootstrap import certify_legacy_null_root
from apps.worker.projection_lineage import resolve_projection_partitions
from apps.worker.projection_publish import publish_settlement_rebuild
from apps.worker.settlement_compaction import (
    claim_settlement_compaction_job,
    enqueue_settlement_compaction_job,
    run_settlement_compaction_job,
)
from tests.test_legacy_projection_bootstrap import _limits
from tests.test_settlement_compaction_runner import compaction_pg
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


def _publish_compact(factory, *, base_generation_id):
    job_id = enqueue_settlement_compaction_job(
        factory, base_generation_id=base_generation_id, batch_size=2,
        resource_limits=_limits(rows=50),
    )
    claimed = claim_settlement_compaction_job(factory, job_id=job_id)
    assert claimed is not None
    result = run_settlement_compaction_job(job_id=job_id, factory=factory, claim_id=claimed[1])
    assert result["status"] == "success"
    return result["generation_id"]


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
