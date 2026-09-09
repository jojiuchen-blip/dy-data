"""Reuse fresh dimension collection evidence across historical day plans."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import JobRun, JobStageRun


def reusable_dimension_snapshot(session: Session, job: Any, *, now: datetime | None = None) -> dict | None:
    metadata = getattr(job, "metadata_json", None) or {}
    if (
        getattr(job, "config_version", None) != "priority-daily-v1"
        or metadata.get("target") != "all"
        or metadata.get("priority_purpose") != "history"
    ):
        return None
    current = now or datetime.now(UTC)
    cutoff = current - timedelta(hours=2)
    rows = session.execute(
        select(JobRun, JobStageRun)
        .join(JobStageRun, JobStageRun.job_id == JobRun.job_id)
        .where(
            JobRun.job_id != job.job_id,
            JobRun.job_kind == "parent_sync",
            JobRun.status == "success",
            JobRun.data_source == job.data_source,
            JobRun.config_version.like("priority-daily-v1%"),
            JobStageRun.stage_name == "collect_dimensions",
            JobStageRun.status == "success",
            JobStageRun.committed_at >= cutoff,
            JobStageRun.committed_at <= current,
        ).order_by(JobStageRun.committed_at.desc()).limit(100)
    )
    proofs = {}
    for source, stage in rows:
        checkpoint = stage.checkpoint_json or {}
        # Never renew freshness by following another reused checkpoint. Only
        # an actual upstream collection can start a new two-hour interval.
        if checkpoint.get("dimension_snapshot_reused"):
            continue
        phases = checkpoint.get("phases")
        if not isinstance(phases, dict):
            continue
        for target in ("shop_pois", "aweme_bindings"):
            phase = phases.get(target)
            if target not in proofs and isinstance(phase, dict) and phase.get("failed", 0) == 0:
                proofs[target] = {
                    "job_id": source.job_id,
                    "stage_run_id": stage.stage_run_id,
                    "committed_at": stage.committed_at.isoformat(),
                    "lease_epoch": stage.lease_epoch,
                }
        if len(proofs) == 2:
            return {
                "dimension_snapshot_reused": True,
                "dimension_snapshot_sources": proofs,
                "phases": {
                    name: {"name": name, "fetched": 0, "upserted": 0, "failed": 0, "reused": True}
                    for name in proofs
                },
            }
    return None
