"""Explicit background publication steps for legacy API regression fixtures."""
from datetime import datetime, timezone

from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.dashboard_publications import clues, finance, sales
from apps.api.dy_api.dashboard_publications.lifecycle import Builder, Publication, publish_module
from apps.api.dy_api.dashboard_publications.schema import metadata


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
    publication = publish_module(
        sessionmaker(bind=session.get_bind(), autoflush=False), module, builder or builders[module],
        now=datetime(2026, 10, 19, tzinfo=timezone.utc), force=True,
    )
    assert publication is not None
    session.expire_all()
    return publication
