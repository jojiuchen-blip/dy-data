from __future__ import annotations

from sqlalchemy.orm import sessionmaker

from apps.api.dy_api.db import get_session_factory
from apps.worker.settlement_rebuild import (
    run_settlement_rebuild_job as _run_settlement_rebuild_job,
)


def run_settlement_rebuild_job(
    *,
    job_id: str,
    factory: sessionmaker | None = None,
) -> None:
    """Run the shared durable rebuild for explicit internal maintenance."""

    session_factory = factory or get_session_factory()
    if session_factory is None:
        return
    _run_settlement_rebuild_job(job_id=job_id, factory=session_factory)


__all__ = ["run_settlement_rebuild_job"]
