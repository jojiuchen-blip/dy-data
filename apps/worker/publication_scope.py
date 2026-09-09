"""Carry successful same-day domain work into the full day's publication scope."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import JobRun, JobStageRun


def include_completed_domain_scope(
    factory: Callable[[], Session], job: Any, settlement_summary: Mapping[str, Any]
) -> dict[str, Any]:
    """Union rebuild dimensions, never manufacture changes or stage success.

    A prior domain sync may have already consumed the raw change. Re-pulling
    unchanged rows produces no new impact for the all-domain job, but those
    previous changes still need a published projection. Their successful,
    immutable settle checkpoints supply the conservative rebuild scope.
    """
    result = dict(settlement_summary)
    if job.config_version != "priority-daily-v1" or (job.metadata_json or {}).get("target") != "all":
        return result
    months = set(result.get("affected_months", []))
    stores = set(result.get("affected_store_ids", []))
    predecessors = []
    with factory() as session:
        rows = session.execute(
            select(JobRun, JobStageRun)
            .join(JobStageRun, JobStageRun.job_id == JobRun.job_id)
            .where(
                JobRun.job_kind == "date_sync",
                JobRun.job_id != job.job_id,
                JobRun.business_date == job.business_date,
                JobRun.window_start == job.window_start,
                JobRun.window_end == job.window_end,
                JobRun.data_source == job.data_source,
                JobRun.config_version == job.config_version,
                JobRun.metadata_json["target"].as_string().in_(
                    ("orders", "refunds", "clues", "verify_records")
                ),
                JobStageRun.stage_name == "settle",
            ).order_by(JobRun.job_id).limit(33)
        ).all()
        if len(rows) > 32:
            raise RuntimeError("too many same-day domain publication predecessors")
        for source, stage in rows:
            if source.status != "success" or stage.status != "success" or stage.committed_at is None:
                raise RuntimeError("same-day domain settlement must finish before publication")
            summary = (stage.checkpoint_json or {}).get("settlement_summary", {})
            if summary.get("completed") is not True:
                raise RuntimeError("same-day domain settlement checkpoint is incomplete")
            for field, target in (("affected_months", months), ("affected_store_ids", stores)):
                values = summary.get(field)
                if not isinstance(values, list) or any(not isinstance(value, str) or not value for value in values):
                    raise RuntimeError("same-day domain publication scope is malformed")
                target.update(values)
            predecessors.append({
                "job_id": source.job_id,
                "stage_run_id": stage.stage_run_id,
                "lease_epoch": stage.lease_epoch,
                "committed_at": stage.committed_at.isoformat(),
            })
    result["affected_months"] = sorted(months)
    result["affected_store_ids"] = sorted(stores)
    result["publication_predecessors"] = predecessors
    return result
