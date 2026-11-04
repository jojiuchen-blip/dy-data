"""Bounded, fail-closed admission for automatic settlement lineage maintenance.

Only projection metadata and the existing compaction JobRun are written.  The
builder remains responsible for full source/checksum validation and publication.
"""

from __future__ import annotations

import logging
import os
import stat
from collections.abc import Callable
from dataclasses import dataclass, replace

from sqlalchemy import func, literal, select, text
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.db import session_scope
from apps.api.dy_api.models import (
    JobRun,
    SettlementProjectionActive,
    SettlementProjectionGeneration,
    SettlementProjectionCompactionClosure,
    SettlementProjectionPartitionManifest,
)
from apps.worker.legacy_projection_bootstrap import (
    COMPACTION_PROTOCOL,
    COMPACTION_OPERATION,
    ResourceGateConfig,
    _compaction_fingerprint,
    _compaction_provenance_rows,
    _compaction_resource,
    _expanded_provenance_checksum,
    _validate_compaction_checkpoint,
    LegacyProjectionBootstrapError,
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
    provenance_checksum: str | None = None
    direct_sources: tuple[tuple[str, str], ...] = ()
    provenance_sources: tuple[tuple[str, str], ...] = ()


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
    """Count bounded provenance and DISTINCT keys; load no manifest payloads.

    A compact ancestor terminates the direct chain. Its historical provenance
    closure contributes its verified source membership to metadata capacity.
    Tombstones are metadata writes too.
    """
    generation = SettlementProjectionGeneration
    manifest = SettlementProjectionPartitionManifest
    with factory() as session:
        _read_only_budget(session)
        chain = select(
            generation.generation_id, generation.base_generation_id,
            generation.generation_kind, generation.lineage_depth, generation.state,
            generation.manifest_checksum,
            literal(0).label("hop"),
        ).where(generation.generation_id == base_generation_id).cte("maintenance_chain", recursive=True)
        chain = chain.union_all(
            select(
                generation.generation_id, generation.base_generation_id,
                generation.generation_kind, generation.lineage_depth, generation.state,
                generation.manifest_checksum,
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
        direct_rows = [row._mapping for row in rows]
        try:
            closure_rows = _compaction_provenance_rows(session, direct_rows)
        except LegacyProjectionBootstrapError as exc:
            raise MaintenanceAdmissionError("compact_provenance_invalid") from exc
        return MaintenanceEstimate(
            base_generation_id, depth, len(closure_rows), count,
            _expanded_provenance_checksum(direct_rows, closure_rows),
            tuple(sorted((str(row["generation_id"]), str(row["manifest_checksum"]))
                         for row in direct_rows)),
            tuple((row["generation_id"], row["manifest_checksum"]) for row in closure_rows),
        )


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


def _reconcile_pending(factory: sessionmaker) -> bool:
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
                continue
            # The caller's cheap head read may predate a newer publication and
            # its queued job. Re-read the actual pointer after locking the job,
            # in the same JobRun -> active order used by the publisher. NOWAIT
            # makes a conflicting publisher yield this entire transaction to
            # the caller's safe-defer path instead of waiting in a lock cycle.
            active_statement = select(SettlementProjectionActive.generation_id).where(
                SettlementProjectionActive.projection_name == "settlement"
            )
            if session.get_bind().dialect.name == "postgresql":
                active_statement = active_statement.with_for_update(nowait=True)
            current_base = session.scalar(active_statement)
            if base != current_base:
                runner._stale_in_session(session, job, current_base=current_base)
            else:
                # Even if the caller observed depth 47, a newer queued job may
                # now require maintenance. Reserve this tick for that work.
                busy = True
                if int(job.attempt_count or 0) >= min(int(job.max_attempts or 3), 3):
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
        ).limit(3)))
        # One original partial and one current deterministic candidate are the
        # only compatible pair. Read an extra row before filtering, so a third
        # conflicting candidate cannot hide behind an arbitrary LIMIT 2.
        if len(candidates) > 2:
            raise MaintenanceAdmissionError("multiple_compaction_checkpoints")
        current_candidates = []
        original_partials = 0
        effective_checksums: set[str] = set()
        for candidate in candidates:
            checkpoint = candidate.checkpoint_json or {}
            source = candidate.source_input_json or {}
            head = session.get(SettlementProjectionGeneration, base_generation_id)
            effective = checkpoint.get("effective_checksum")
            if (head is None or not isinstance(effective, str) or len(effective) != 64
                    or any(character not in "0123456789abcdef" for character in effective)
                    or candidate.base_generation_id is not None or candidate.lineage_depth != 0
                    or candidate.projection_name != "settlement"
                    or source.get("protocol") != COMPACTION_PROTOCOL
                    or source.get("projection") != "settlement"
                    or source.get("operation") != COMPACTION_OPERATION
                    or source.get("base_generation_id") != base_generation_id
                    or source.get("effective_checksum") != effective
                    or checkpoint.get("protocol") != COMPACTION_PROTOCOL
                    or checkpoint.get("base_generation_id") != base_generation_id
                    or checkpoint.get("batch_size") != batch_size
                    or candidate.generation_id != f"settlement-compact:{candidate.input_fingerprint}"):
                raise MaintenanceAdmissionError("compaction_checkpoint_identity_invalid")
            current_fingerprint = _compaction_fingerprint(
                base_generation_id, str(head.manifest_checksum), effective,
                estimate.provenance_checksum,
            )
            original_fingerprint = _compaction_fingerprint(
                base_generation_id, str(head.manifest_checksum), effective,
            )
            is_current = (candidate.input_fingerprint == current_fingerprint
                          and source.get("provenance_checksum") == estimate.provenance_checksum)
            is_original_partial = (
                estimate.provenance_checksum is not None
                and candidate.input_fingerprint == original_fingerprint
                and source.get("provenance_checksum") is None
                and candidate.state == "staging" and candidate.published_at is None
                and candidate.manifest_checksum is None and checkpoint.get("phase") == "scan"
            )
            if not is_current and not is_original_partial:
                raise MaintenanceAdmissionError("compaction_checkpoint_identity_invalid")
            effective_checksums.add(effective)
            if len(effective_checksums) > 1:
                raise MaintenanceAdmissionError("compaction_checkpoint_identity_invalid")
            expected_sources = estimate.provenance_sources if is_current else estimate.direct_sources
            closure = tuple(session.execute(select(
                SettlementProjectionCompactionClosure.source_generation_id,
                SettlementProjectionCompactionClosure.source_digest,
            ).where(
                SettlementProjectionCompactionClosure.compact_generation_id == candidate.generation_id,
            ).order_by(SettlementProjectionCompactionClosure.source_generation_id)
              .limit(len(expected_sources) + 1)).all())
            if not expected_sources or closure != expected_sources:
                raise MaintenanceAdmissionError("compaction_checkpoint_closure_invalid")
            frozen = checkpoint.get("estimated_disk_headroom_bytes")
            if isinstance(frozen, bool) or not isinstance(frozen, int) or frozen < 0:
                raise MaintenanceAdmissionError("compaction_checkpoint_budget_invalid")
            if is_original_partial:
                original_partials += 1
                if original_partials > 1:
                    raise MaintenanceAdmissionError("multiple_compaction_checkpoints")
                manifest_count = checkpoint.get("estimated_manifest_rows")
                if isinstance(manifest_count, bool) or not isinstance(manifest_count, int) or manifest_count < 0:
                    raise MaintenanceAdmissionError("compaction_checkpoint_budget_invalid")
                original_limits = replace(limits, observed_disk_headroom_bytes=frozen + limits.min_disk_headroom_bytes)
                original_resource, refusal = _compaction_resource(manifest_count, len(expected_sources), original_limits)
                try:
                    original_checkpoint = _validate_compaction_checkpoint(
                        candidate, base_generation_id=base_generation_id,
                        effective_checksum=effective, resource=original_resource,
                        batch_size=batch_size, source_generation_count=len(expected_sources),
                    )
                except LegacyProjectionBootstrapError as exc:
                    raise MaintenanceAdmissionError("compaction_checkpoint_identity_invalid") from exc
                if (refusal is not None
                        or candidate.estimated_write_rows != original_resource[1]
                        or candidate.estimated_write_bytes != original_resource[2]
                        or candidate.estimated_wal_bytes != original_resource[3]
                        or candidate.estimated_disk_headroom_bytes != original_resource[4]):
                    raise MaintenanceAdmissionError("compaction_checkpoint_budget_invalid")
                partial_count = original_checkpoint["partition_count"]
                bounded_rows = select(SettlementProjectionPartitionManifest.partition_key).where(
                    SettlementProjectionPartitionManifest.generation_id == candidate.generation_id,
                ).limit(partial_count + 1).subquery()
                actual_count = session.scalar(select(func.count()).select_from(bounded_rows))
                if actual_count != partial_count:
                    raise MaintenanceAdmissionError("compaction_checkpoint_identity_invalid")
                # The original partial remains immutable audit evidence. Its
                # frozen capacity does not belong to the new fingerprint.
                continue
            current_candidates.append((candidate, frozen))
        if len(current_candidates) > 1:
            raise MaintenanceAdmissionError("multiple_compaction_checkpoints")
        if current_candidates:
            _candidate, frozen = current_candidates[0]
            # Only the accounting budget is frozen. Actual free space was
            # independently re-read and admitted above on every execution.
            limits = replace(limits, observed_disk_headroom_bytes=frozen + limits.min_disk_headroom_bytes)
            _check_estimate(estimate, limits)
    return limits


def process_automatic_settlement_maintenance(
    factory: sessionmaker,
    *,
    on_manifest_limit: Callable[[sessionmaker], object] | None = None,
) -> bool:
    """Return True when this tick must reserve its heavy-work opportunity.

    Resource/estimate failures, disabled maintenance at the threshold, and an
    exhausted fixed job all defer safely; the caller must not grow the lineage.
    Genuine runner failures propagate after its existing attempt accounting.
    A manifest-only admission failure may offer the explicit no-lineage roster
    callback after a fresh disk check, while still reserving the entire tick.
    """
    try:
        head = _active_head(factory)
        busy = _reconcile_pending(factory)
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
        if reason == "manifest_rows_exceed_limit" and on_manifest_limit is not None:
            # The manifest limit is checked before disk headroom. Re-read the
            # actual PG filesystem so that this exception cannot conceal a
            # missing marker or exhausted disk reserve. Keep the existing
            # conservative write/WAL allowance for the independent roster job.
            try:
                capacity = disk_capacity_limits()
                required = (
                    capacity.min_disk_headroom_bytes
                    + capacity.max_estimated_write_bytes
                    + capacity.max_estimated_wal_bytes
                )
                if capacity.observed_disk_headroom_bytes < required:
                    raise MaintenanceAdmissionError("disk_headroom_insufficient")
            except Exception:
                LOGGER.warning("settlement_maintenance_account_refresh_deferred reason=disk_headroom_unavailable")
                return True
            on_manifest_limit(factory)
        return True
    runner.run_settlement_compaction_job(job_id=claimed[0], factory=factory, claim_id=claimed[1])
    return True
