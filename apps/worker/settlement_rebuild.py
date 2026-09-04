from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.orm import sessionmaker

from apps.api.dy_api.db import session_scope
from apps.api.dy_api.models import (
    JobRun,
    SettlementProjectionActive,
    SettlementProjectionGeneration,
    SettlementProjectionPartitionManifest,
    SettlementStatement,
    utcnow,
)
from apps.worker.projection_publish import publish_settlement_rebuild
from apps.worker.repositories import finish_job_run
from apps.worker.settlement import (
    FORMAL_SETTLEMENT_START,
    _projection_months,
    _sparse_base_chain,
    build_settlement_sparse_overlay,
    mark_settlement_sparse_overlay_ready,
    run_settlement_job,
)


SETTLEMENT_REBUILD_SPARSE_BATCH_SIZE = 200
SETTLEMENT_REBUILD_JOB_NAME = "settlement_rebuild"


@dataclass(frozen=True)
class _LineageRefreshPlan:
    job_id: str
    generation_id: str
    base_generation_id: str
    affected_months: tuple[str, ...]
    input_fingerprint: str


def _lineage_refresh_plan(
    factory: sessionmaker, *, job_id: str
) -> _LineageRefreshPlan | None:
    with session_scope(factory) as session:
        generation_id = f"settlement-admin-rebuild:{job_id}"
        existing_generation = session.get(
            SettlementProjectionGeneration, generation_id
        )
        if (
            existing_generation is not None
            and existing_generation.state == "published"
            and existing_generation.source_job_id in {None, job_id}
        ):
            # The rebuild can be retried after the worker has already
            # published its overlay.  Treat the durable published generation
            # as the idempotency record and do not use it as its own base.
            return None

        active = session.get(SettlementProjectionActive, "settlement")
        if active is None or active.generation_id is None:
            # A nullable pointer means the legacy root is authoritative. The
            # full rebuild already refreshed that root, so no overlay is needed.
            return None

        base_generation_id = active.generation_id
        _base, lineage_ids = _sparse_base_chain(session, base_generation_id)
        candidate_months = set(_projection_months(session))
        manifest_keys = session.scalars(
            select(SettlementProjectionPartitionManifest.partition_key).where(
                SettlementProjectionPartitionManifest.generation_id.in_(lineage_ids),
                SettlementProjectionPartitionManifest.artifact == "monthly",
            )
        )
        formal_start = FORMAL_SETTLEMENT_START.strftime("%Y-%m")
        for partition_key in manifest_keys:
            value = str(partition_key)
            if value >= formal_start:
                candidate_months.add(value)

        locked_months = set(
            session.scalars(
                select(SettlementStatement.statement_month).where(
                    SettlementStatement.statement_status == 4
                )
            )
        )
        affected_months = tuple(
            sorted(month for month in candidate_months if month not in locked_months)
        )
        if not affected_months:
            return None

        fingerprint_payload = {
            "protocol": "settlement-admin-rebuild-lineage-v1",
            "job_id": job_id,
            "base_generation_id": base_generation_id,
            "affected_months": list(affected_months),
        }
        input_fingerprint = hashlib.sha256(
            json.dumps(
                fingerprint_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return _LineageRefreshPlan(
            job_id=job_id,
            generation_id=generation_id,
            base_generation_id=base_generation_id,
            affected_months=affected_months,
            input_fingerprint=input_fingerprint,
        )


def refresh_active_settlement_lineage(
    factory: sessionmaker, *, job_id: str
) -> dict[str, object] | None:
    """Build and publish the active settlement overlay after a full rebuild."""

    plan = _lineage_refresh_plan(factory, job_id=job_id)
    if plan is None:
        return None

    build_settlement_sparse_overlay(
        factory,
        generation_id=plan.generation_id,
        base_generation_id=plan.base_generation_id,
        affected_months=plan.affected_months,
        batch_size=SETTLEMENT_REBUILD_SPARSE_BATCH_SIZE,
        input_fingerprint=plan.input_fingerprint,
        source_job_id=job_id,
    )
    manifest = mark_settlement_sparse_overlay_ready(
        factory,
        generation_id=plan.generation_id,
        base_generation_id=plan.base_generation_id,
        input_fingerprint=plan.input_fingerprint,
    )
    with session_scope(factory) as session:
        publication = publish_settlement_rebuild(
            session,
            job_id=job_id,
            generation_id=plan.generation_id,
            base_generation_id=plan.base_generation_id,
            input_fingerprint=plan.input_fingerprint,
            manifest_checksum=manifest.manifest_checksum,
        )
        job = session.get(JobRun, job_id)
        if job is None:  # pragma: no cover - guarded by publication validation
            raise RuntimeError("settlement rebuild job disappeared before metadata update")
        metadata = dict(job.metadata_json or {})
        metadata["settlement_projection"] = {
            "status": "published",
            "generation_id": plan.generation_id,
            "base_generation_id": plan.base_generation_id,
            "input_fingerprint": plan.input_fingerprint,
            "manifest_checksum": manifest.manifest_checksum,
            "affected_months": list(plan.affected_months),
            "manifest_count": manifest.manifest_count,
            "row_count": manifest.row_count,
        }
        job.metadata_json = metadata
        return publication


def claim_settlement_rebuild_job(
    factory: sessionmaker,
    *,
    job_id: str,
) -> bool:
    """Atomically claim one queued rebuild before starting expensive work."""

    claimed_at = utcnow()
    with session_scope(factory) as session:
        result = session.execute(
            update(JobRun)
            .where(
                JobRun.job_id == job_id,
                JobRun.job_name == SETTLEMENT_REBUILD_JOB_NAME,
                JobRun.status == "queued",
            )
            .values(
                status="running",
                started_at=claimed_at,
                finished_at=None,
                success_count=0,
                failed_count=0,
                error_message=None,
                state_updated_at=claimed_at,
            )
            .execution_options(synchronize_session=False)
        )
        return result.rowcount == 1


def run_settlement_rebuild_job(
    *,
    job_id: str,
    factory: sessionmaker,
    source_run_id: str | None = None,
) -> bool:
    """Run a settlement rebuild and publish its active lineage overlay."""

    if factory is None:
        raise RuntimeError("settlement rebuild requires a database session factory")
    if not claim_settlement_rebuild_job(factory, job_id=job_id):
        return False
    try:
        # The legacy rebuild owns one transaction. Sparse overlay partitions
        # intentionally use independent transactions, so they start only after
        # the authoritative fee results are committed and visible.
        with session_scope(factory) as session:
            run_settlement_job(
                session,
                job_id=job_id,
                source_run_id=source_run_id or job_id,
            )
        refresh_active_settlement_lineage(factory, job_id=job_id)
    except Exception as exc:
        # The legacy tables may already be rebuilt, but the active pointer
        # remains unchanged until the overlay is certified and published.
        with session_scope(factory) as session:
            try:
                finish_job_run(
                    session,
                    job_id,
                    status="failed",
                    failed_count=1,
                    error_message=str(exc),
                )
            except ValueError:
                pass
        raise
    return True


__all__ = [
    "SETTLEMENT_REBUILD_JOB_NAME",
    "SETTLEMENT_REBUILD_SPARSE_BATCH_SIZE",
    "claim_settlement_rebuild_job",
    "refresh_active_settlement_lineage",
    "run_settlement_rebuild_job",
]
