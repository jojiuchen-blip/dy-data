"""Bounded, fail-closed admission for automatic settlement lineage maintenance.

Only projection metadata and the existing compaction JobRun are written.  The
builder remains responsible for full source/checksum validation and publication.
"""

from __future__ import annotations

import logging
import os
import stat
from dataclasses import dataclass, replace

from sqlalchemy import func, literal, select, text
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.db import session_scope
from apps.api.dy_api.models import (
    JobRun,
    SettlementProjectionActive,
    SettlementProjectionGeneration,
    SettlementProjectionPartitionManifest,
)
from apps.worker.legacy_projection_bootstrap import (
    COMPACTION_PROTOCOL,
    ResourceGateConfig,
    _compaction_fingerprint,
    _compaction_resource,
)
from apps.worker import settlement_compaction as runner

LOGGER = logging.getLogger(__name__)
AUTOMATIC_MAINTENANCE_TRIGGER = "automatic_lineage_maintenance"
AUTOMATIC_MAINTENANCE_DEPTH = 48
MAX_DIRECT_LINEAGE_ROWS = 65
DISK_PROBE_ENV = "SETTLEMENT_COMPACTION_DISK_PROBE_PATH"
DISK_PROBE_DEFAULT = "/run/dydata/postgres-capacity"
DISK_PROBE_MARKER = b"dydata-postgres-capacity-v1\n"
GIB = 1024 ** 3
# Conservative metadata-only admission caps, not measured production capacity.
# The final builder applies the same caps to its complete validated plan.
MAX_MANIFEST_ROWS = 100_000
MAX_WRITE_BYTES = 512 * 1024 ** 2
MAX_WAL_BYTES = GIB


class MaintenanceAdmissionError(RuntimeError):
    """Evidence is missing or exceeds a bounded maintenance budget."""


@dataclass(frozen=True)
class MaintenanceEstimate:
    base_generation_id: str
    lineage_depth: int
    closure_rows: int
    manifest_rows: int


def disk_capacity_limits(path: str | None = None) -> ResourceGateConfig:
    """Read the explicit PG filesystem marker, never a worker-root fallback.

    The marker must be a regular, non-symlink file with exactly the protocol
    bytes.  Opening is nonblocking so an accidentally supplied special device
    cannot hang admission.  Identity checks reject replacement during the read.
    """
    probe_path = path if path is not None else os.getenv(DISK_PROBE_ENV, DISK_PROBE_DEFAULT)
    try:
        before = os.lstat(probe_path)
        if not stat.S_ISREG(before.st_mode):
            raise MaintenanceAdmissionError("disk_probe_not_regular")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(probe_path, flags)
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
                before.st_dev, before.st_ino
            ):
                raise MaintenanceAdmissionError("disk_probe_changed")
            if os.read(descriptor, len(DISK_PROBE_MARKER) + 1) != DISK_PROBE_MARKER:
                raise MaintenanceAdmissionError("disk_probe_marker_invalid")
            capacity = os.statvfs(probe_path)
            after = os.lstat(probe_path)
            if (after.st_dev, after.st_ino) != (opened.st_dev, opened.st_ino):
                raise MaintenanceAdmissionError("disk_probe_changed")
        finally:
            os.close(descriptor)
    except (OSError, AttributeError, ValueError) as exc:
        raise MaintenanceAdmissionError("disk_probe_unavailable") from exc
    total = int(capacity.f_blocks) * int(capacity.f_frsize)
    available = int(capacity.f_bavail) * int(capacity.f_frsize)
    if total <= 0 or available < 0 or available > total:
        raise MaintenanceAdmissionError("disk_probe_capacity_invalid")
    reserve = max(10 * GIB, (total * 15 + 99) // 100)
    return ResourceGateConfig(
        max_manifest_rows=MAX_MANIFEST_ROWS,
        max_estimated_write_bytes=MAX_WRITE_BYTES,
        max_estimated_wal_bytes=MAX_WAL_BYTES,
        observed_disk_headroom_bytes=available,
        min_disk_headroom_bytes=reserve,
    )


def _read_only_budget(session: Session) -> None:
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SET TRANSACTION READ ONLY"))
        session.execute(text("SET LOCAL statement_timeout = '8s'"))
        session.execute(text("SET LOCAL lock_timeout = '1s'"))


def _active_head(factory: sessionmaker) -> tuple[str, int, str] | None:
    with factory() as session:
        _read_only_budget(session)
        row = session.execute(
            select(
                SettlementProjectionActive.generation_id,
                SettlementProjectionGeneration.lineage_depth,
                SettlementProjectionGeneration.generation_kind,
                SettlementProjectionGeneration.state,
            )
            .select_from(SettlementProjectionActive)
            .outerjoin(SettlementProjectionGeneration, SettlementProjectionActive.generation_id
                  == SettlementProjectionGeneration.generation_id)
            .where(SettlementProjectionActive.projection_name == "settlement")
        ).one_or_none()
        if row is None or row[0] is None:
            return None
        if row[3] != "published":
            raise MaintenanceAdmissionError("active_generation_not_published")
        return str(row[0]), int(row[1]), str(row[2])


def estimate_automatic_compaction(
    factory: sessionmaker, *, base_generation_id: str
) -> MaintenanceEstimate:
    """Count direct lineage and DISTINCT keys in SQL; load no manifest payloads.

    A compact ancestor terminates the direct chain. Its historical provenance
    closure is deliberately not expanded. Tombstones are metadata writes too.
    """
    generation = SettlementProjectionGeneration
    manifest = SettlementProjectionPartitionManifest
    with factory() as session:
        _read_only_budget(session)
        chain = select(
            generation.generation_id, generation.base_generation_id,
            generation.generation_kind, generation.lineage_depth, generation.state,
            literal(0).label("hop"),
        ).where(generation.generation_id == base_generation_id).cte("maintenance_chain", recursive=True)
        chain = chain.union_all(
            select(
                generation.generation_id, generation.base_generation_id,
                generation.generation_kind, generation.lineage_depth, generation.state,
                (chain.c.hop + 1).label("hop"),
            ).join(chain, generation.generation_id == chain.c.base_generation_id)
            .where(chain.c.hop < MAX_DIRECT_LINEAGE_ROWS - 1)
        )
        rows = session.execute(select(chain).order_by(chain.c.hop)).all()
        if not rows or rows[-1].base_generation_id is not None:
            raise MaintenanceAdmissionError("direct_lineage_incomplete_or_too_deep")
        depth = int(rows[0].lineage_depth)
        if depth != len(rows) - 1 or len({row.generation_id for row in rows}) != len(rows):
            raise MaintenanceAdmissionError("direct_lineage_invalid")
        for hop, row in enumerate(rows):
            if (int(row.lineage_depth) != depth - hop
                    or row.state not in ({"published"} if hop == 0 else {"published", "superseded"})
                    or row.generation_kind not in {"lineage", "compact", "legacy_root"}):
                raise MaintenanceAdmissionError("direct_lineage_invalid")
        direct_ids = [row.generation_id for row in rows if row.generation_kind != "legacy_root"]
        # LIMIT caps the aggregate result at the first over-budget key. This
        # still counts DISTINCT across the whole direct chain, not per-page sums.
        keys = select(manifest.artifact, manifest.partition_key).where(
            manifest.generation_id.in_(direct_ids), manifest.source_kind != "legacy_root",
        ).distinct().limit(MAX_MANIFEST_ROWS + 1).subquery()
        count = int(session.scalar(select(func.count()).select_from(keys)) or 0)
        return MaintenanceEstimate(base_generation_id, depth, len(rows), count)


def _check_estimate(estimate: MaintenanceEstimate, limits: ResourceGateConfig) -> None:
    _resource, reason = _compaction_resource(estimate.manifest_rows, estimate.closure_rows, limits)
    if reason is not None:
        raise MaintenanceAdmissionError(reason)


def _record_blocked(session: Session, job: JobRun, reason: str) -> None:
    metadata = dict(job.metadata_json or {})
    metadata["maintenance_blocked_reason"] = reason
    job.metadata_json = metadata
    runner._record_compaction_event(
        session, job=job, event_type=f"settlement_compaction_blocked_{reason}",
        reason="automatic settlement maintenance is blocked",
        payload={"reason": reason, "base_generation_id": metadata.get("base_generation_id")},
    )


def _existing_job_blocks(session: Session, job: JobRun) -> bool:
    if (job.metadata_json or {}).get("trigger") != AUTOMATIC_MAINTENANCE_TRIGGER:
        _record_blocked(session, job, "manual_job_requires_operator")
        return True
    exhausted = int(job.attempt_count or 0) >= min(int(job.max_attempts or 3), 3)
    if job.status not in {"queued", "running"} or exhausted:
        reason = "attempts_exhausted" if exhausted else "terminal_job"
        _record_blocked(session, job, reason)
        return True
    return False


def _reconcile_pending(factory: sessionmaker, current_base: str | None) -> bool:
    """Recover publish receipts before marking expired/queued old bases stale."""
    busy = False
    with session_scope(factory) as session:
        statement = select(JobRun).where(
            JobRun.job_name == runner.SETTLEMENT_COMPACTION_JOB_NAME,
            JobRun.metadata_json["trigger"].as_string() == AUTOMATIC_MAINTENANCE_TRIGGER,
            JobRun.status.in_(("queued", "running")),
        ).order_by(JobRun.started_at, JobRun.job_id).limit(32)
        if session.get_bind().dialect.name == "postgresql":
            statement = statement.with_for_update(skip_locked=True)
        now = runner._database_utcnow(session)
        for job in session.scalars(statement):
            if job.status == "running" and (
                job.lease_expires_at is None or runner._as_utc(job.lease_expires_at) > now
            ):
                busy = True
                continue
            base = (job.metadata_json or {}).get("base_generation_id")
            if not isinstance(base, str) or not base:
                raise MaintenanceAdmissionError("automatic_job_base_invalid")
            receipt = runner._find_publication_evidence(session, job_id=job.job_id, base_generation_id=base)
            if receipt is not None:
                runner._finish_in_session(session, job, outcome="already_published", generation_id=receipt)
            elif base != current_base:
                runner._stale_in_session(session, job, current_base=current_base)
            elif int(job.attempt_count or 0) >= min(int(job.max_attempts or 3), 3):
                job.status = "failed"
                job.finished_at = now
                job.claim_token = None
                job.lease_expires_at = None
                _record_blocked(session, job, "attempts_exhausted")
    return busy


def automatic_runner_resource_limits(
    factory: sessionmaker, *, base_generation_id: str, batch_size: int
) -> ResourceGateConfig:
    """Refresh real admission while preserving a resumable checkpoint budget."""
    limits = disk_capacity_limits()
    estimate = estimate_automatic_compaction(factory, base_generation_id=base_generation_id)
    _check_estimate(estimate, limits)
    with factory() as session:
        _read_only_budget(session)
        active = session.get(SettlementProjectionActive, "settlement")
        if active is None or active.generation_id != base_generation_id:
            raise MaintenanceAdmissionError("base_changed")
        candidates = list(session.scalars(select(SettlementProjectionGeneration).where(
            SettlementProjectionGeneration.generation_kind == "compact",
            SettlementProjectionGeneration.compaction_base_generation_id == base_generation_id,
            SettlementProjectionGeneration.state.in_(("staging", "ready")),
        ).limit(2)))
        if len(candidates) > 1:
            raise MaintenanceAdmissionError("multiple_compaction_checkpoints")
        if candidates:
            candidate = candidates[0]
            checkpoint = candidate.checkpoint_json or {}
            source = candidate.source_input_json or {}
            head = session.get(SettlementProjectionGeneration, base_generation_id)
            effective = checkpoint.get("effective_checksum")
            if (head is None or not isinstance(effective, str)
                    or source.get("protocol") != COMPACTION_PROTOCOL
                    or source.get("base_generation_id") != base_generation_id
                    or source.get("effective_checksum") != effective
                    or checkpoint.get("protocol") != COMPACTION_PROTOCOL
                    or checkpoint.get("base_generation_id") != base_generation_id
                    or checkpoint.get("batch_size") != batch_size
                    or candidate.input_fingerprint != _compaction_fingerprint(
                        base_generation_id, str(head.manifest_checksum), effective)
                    or candidate.generation_id != f"settlement-compact:{candidate.input_fingerprint}"):
                raise MaintenanceAdmissionError("compaction_checkpoint_identity_invalid")
            frozen = checkpoint.get("estimated_disk_headroom_bytes")
            if isinstance(frozen, bool) or not isinstance(frozen, int) or frozen < 0:
                raise MaintenanceAdmissionError("compaction_checkpoint_budget_invalid")
            # Only the accounting budget is frozen. Actual free space was
            # independently re-read and admitted above on every execution.
            limits = replace(limits, observed_disk_headroom_bytes=frozen + limits.min_disk_headroom_bytes)
            _check_estimate(estimate, limits)
    return limits


def process_automatic_settlement_maintenance(factory: sessionmaker) -> bool:
    """Return True when this tick must reserve its heavy-work opportunity.

    Resource/estimate failures, disabled maintenance at the threshold, and an
    exhausted fixed job all defer safely; the caller must not grow the lineage.
    Genuine runner failures propagate after its existing attempt accounting.
    """
    try:
        head = _active_head(factory)
        busy = _reconcile_pending(factory, head[0] if head is not None else None)
        if head is None or head[2] == "compact" or head[1] < AUTOMATIC_MAINTENANCE_DEPTH:
            return busy
        if os.getenv("SETTLEMENT_AUTOMATIC_MAINTENANCE_ENABLED", "true").strip().lower() in {
            "0", "false", "no", "off",
        }:
            LOGGER.warning("settlement_maintenance_deferred reason=disabled")
            return True
        with session_scope(factory) as session:
            existing = session.get(JobRun, runner.settlement_compaction_job_id(head[0]))
            if existing is not None and _existing_job_blocks(session, existing):
                return True
        limits = disk_capacity_limits()
        estimate = estimate_automatic_compaction(factory, base_generation_id=head[0])
        _check_estimate(estimate, limits)
        job_id = runner.enqueue_settlement_compaction_job(
            factory, base_generation_id=head[0], batch_size=400,
            resource_limits=limits, trigger=AUTOMATIC_MAINTENANCE_TRIGGER,
        )
        with session_scope(factory) as session:
            job = session.get(JobRun, job_id)
            if job is None:
                raise MaintenanceAdmissionError("automatic_job_missing")
            if _existing_job_blocks(session, job):
                return True
        claimed = runner.claim_settlement_compaction_job(factory, job_id=job_id)
        if claimed is None:
            return True
    except Exception as exc:
        # Admission has not started a builder. Inability to prove safety must
        # reserve the tick too; no exception text/connection details are logged.
        reason = str(exc) if isinstance(exc, MaintenanceAdmissionError) else type(exc).__name__
        LOGGER.warning("settlement_maintenance_deferred reason=%s", reason)
        return True
    runner.run_settlement_compaction_job(job_id=claimed[0], factory=factory, claim_id=claimed[1])
    return True
