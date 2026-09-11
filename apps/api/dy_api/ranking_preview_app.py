"""Explicit, local-only synthetic snapshot preview entry point."""
import os
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url

from apps.api.dy_api.ranking_schema_v1 import runs


def create_app():
    url = make_url(os.environ["DY_DATABASE_URL"])
    if os.getenv("DY_API_TEST_MODE", "").lower() != "true" or url.get_backend_name() != "sqlite":
        raise RuntimeError("Ranking preview requires explicit test mode and a local SQLite database")
    if not url.database or not Path(url.database).is_file():
        raise RuntimeError("Prepare the dedicated synthetic database before starting preview")
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            modes = set(connection.scalars(select(runs.c.data_mode)))
            if modes != {"synthetic"}:
                raise RuntimeError("Preview database must contain only synthetic snapshot runs")
    finally:
        engine.dispose()
    from dy_api.main import create_app as main_app
    app = main_app()
    app.state.ranking_snapshot_preview = True
    return app
