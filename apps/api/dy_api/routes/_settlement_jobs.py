from __future__ import annotations

from sqlalchemy.orm import sessionmaker

from apps.api.dy_api.db import get_session_factory
from apps.worker.settlement_rebuild import (
    refresh_active_settlement_lineage,
    run_settlement_rebuild_job as _run_settlement_rebuild_job,
)


def run_settlement_rebuild_job(
    *,
    job_id: str,
    factory: sessionmaker | None = None,
) -> None:
    """Run the shared worker rebuild from an API background task."""

    session_factory = factory or get_session_factory()
    if session_factory is None:
        return
    _run_settlement_rebuild_job(job_id=job_id, factory=session_factory)


__all__ = ["refresh_active_settlement_lineage", "run_settlement_rebuild_job"]
