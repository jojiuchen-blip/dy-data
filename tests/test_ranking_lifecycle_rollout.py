"""First rollout preserves historical checkpoints before enabling retention."""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from apps.api.dy_api.ranking_schema_v1 import metadata, runs
from apps.api.dy_api.ranking_lifecycle_schema import snapshot_lifecycle
from apps.api.dy_api.ranking_lifecycle import cleanup_snapshots


def test_migration_pins_existing_successes_but_not_future_runs():
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=40)
    def row(run_id, status="success"):
        return dict(run_id=run_id, period_start=old-timedelta(days=2), period_end=old,
                    observed_through=old, roster_at=old-timedelta(days=2),
                    eligibility_version="test", metric_version="legacy", data_mode="business",
                    status=status, quality_json={}, created_at=old)
    with engine.begin() as connection:
        connection.execute(runs.insert(), [row("historical"), row("incomplete", "building")])
    path = Path(__file__).resolve().parents[1] / "alembic/versions/20261009_0062_ranking_lifecycle.py"
    spec = importlib.util.spec_from_file_location("rollout_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        connection.execute(runs.insert(), row("after-rollout"))
    with Session(engine) as session:
        protected = session.execute(select(snapshot_lifecycle)).mappings().all()
        assert [r["run_id"] for r in protected] == ["historical"]
        assert protected[0]["pinned_at"] is not None
        assert protected[0]["source_fingerprint"] is None
        assert protected[0]["pinned_by"] == "migration:20261009_0062"
        result = cleanup_snapshots(session, dry_run=False, now=now)
        assert [r["run_id"] for r in result["planned"]] == ["after-rollout"]
        assert set(session.scalars(select(runs.c.run_id))) == {"historical", "incomplete"}
    engine.dispose()
