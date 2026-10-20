"""Explicit background publication steps for legacy API regression fixtures."""
from datetime import datetime, timezone
from calendar import monthrange

from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import func, select
from unittest.mock import patch

from apps.api.dy_api.dashboard_publications import clues, finance, sales
from apps.api.dy_api.dashboard_publications.lifecycle import Builder, Publication, publish_module
from apps.api.dy_api.dashboard_publications.schema import metadata


def ready_periods_fixture(session, cutoff):
    """Explicit complete collection evidence for synthetic financial fixtures.

    These fixtures test historical financial facts, not the real daily job
    graph. Production capture is separately tested with real daily plans.
    """
    from apps.api.dy_api.models import SettlementStatement
    latest = session.scalar(select(func.max(SettlementStatement.statement_month)))
    through = max(cutoff.strftime("%Y-%m"), latest or "2026-08")
    return {"schema_version": 1, "formal_start_month": "2026-08", "months": {
        month: {"ready": True, "success_days": monthrange(*map(int, month.split("-")))[1],
            "total_days": monthrange(*map(int, month.split("-")))[1], "revision": "fixture"}
        for month in finance.period_readiness.formal_months(through)}}


def publish_fixture(
    session: Session, module: str, *, builder: Builder | None = None,
) -> Publication:
    """Commit seeded facts and freeze one complete version before analytical reads."""
    session.commit()
    metadata.create_all(session.get_bind())
    builders = {
        "clue-overview": clues.build,
        "finance": finance.build_finance,
        "settlement": finance.build_settlement,
        "sales": sales.build,
    }
    with patch.object(finance.period_readiness, "capture", ready_periods_fixture):
        publication = publish_module(
            sessionmaker(bind=session.get_bind(), autoflush=False), module, builder or builders[module],
            now=datetime(2026, 10, 19, tzinfo=timezone.utc), force=True,
        )
    assert publication is not None
    session.expire_all()
    return publication
