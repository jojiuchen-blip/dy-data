"""Opt-in PostgreSQL lifecycle contracts in a disposable local test database."""
import importlib.util
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from apps.api.dy_api.ranking_schema_v1 import metadata, runs
from apps.api.dy_api.ranking_lifecycle_schema import SOURCE_TABLES, snapshot_lifecycle
from apps.api.dy_api.ranking_lifecycle import (
    archive_snapshot, backfill_lifecycle_metadata, cleanup_snapshots, hold_snapshot_read, record_snapshot_access,
    register_snapshot, reusable_business_snapshot, source_fingerprint,
)


@pytest.fixture
def pg():
    raw = os.getenv("DYDATA_RANKING_TEST_DATABASE_URL")
    if not raw:
        pytest.skip("set DYDATA_RANKING_TEST_DATABASE_URL to a disposable local PostgreSQL test database")
    url = make_url(raw)
    assert url.host in {"localhost", "127.0.0.1", "::1"}
    assert "test" in (url.database or "").lower()
    schema = "ranking_retention_test_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        metadata.create_all(engine)
        with engine.begin() as connection:
            for name in SOURCE_TABLES:
                if name not in metadata.tables:
                    connection.execute(text(f'CREATE TABLE "{name}" (order_id text PRIMARY KEY, value text)'))
        path = Path(__file__).resolve().parents[1] / "alembic/versions/20261009_0062_ranking_lifecycle.py"
        spec = importlib.util.spec_from_file_location("ranking_migration_under_test", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
        yield engine, migration
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def add_run(session, run_id, created):
    session.execute(runs.insert().values(
        run_id=run_id, period_start=created-timedelta(days=2), period_end=created-timedelta(days=1),
        observed_through=created, roster_at=created-timedelta(days=2), eligibility_version="test",
        metric_version="test-v1", data_mode="business", status="success", quality_json={}, created_at=created,
    ))


def test_statement_counters_cover_all_dependencies_and_rollback(pg):
    engine, migration = pg
    with Session(engine) as session:
        before = source_fingerprint(session)  # verifies every installed source trigger
        tokens = [before]
        for sql in (
            "INSERT INTO raw_douyin_orders VALUES ('test-order','one')",
            "UPDATE raw_douyin_orders SET value='two'",
            "DELETE FROM raw_douyin_orders",
            "TRUNCATE raw_douyin_orders",
        ):
            session.execute(text(sql))
            tokens.append(source_fingerprint(session))
        assert len(set(tokens)) == 5
        session.rollback()
        assert source_fingerprint(session) == before
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
            migration.upgrade()
    with Session(engine) as session:
        assert source_fingerprint(session) == before


def test_cache_hit_holds_parent_before_idle_cleanup(pg):
    engine, _ = pg
    created = datetime.now(timezone.utc)-timedelta(days=31)
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        add_run(session, "cached", created)
        register_snapshot(session, run_id="cached", source_token="unchanged", now=created)
        session.commit()
    with Session(engine) as reader:
        assert reusable_business_snapshot(
            reader, period_start=created-timedelta(days=2), period_end=created-timedelta(days=1),
            metric_version="test-v1", source_token="unchanged", now=now,
        ) == "cached"
        with Session(engine) as cleaner:
            result = cleanup_snapshots(cleaner, now=now, dry_run=False)
            cleaner.commit()
            assert result["deleted"] == 0
            assert cleaner.scalar(select(func.count()).select_from(runs)) == 1
        reader.commit()


def test_concurrent_first_export_access_is_durable_and_preserves_pin(pg):
    engine, _ = pg
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        add_run(session, "legacy-export", now)
        session.commit()
    barrier = Barrier(2)
    def export_access(_):
        with Session(engine) as session:
            hold_snapshot_read(session, "legacy-export")
            barrier.wait(timeout=20)
            record_snapshot_access(session, "legacy-export")
            session.commit()
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(export_access, range(2)))
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(snapshot_lifecycle)) == 1
        assert session.scalar(select(func.count()).select_from(runs)) == 1
        archive_snapshot(session, "legacy-export", reason="confirmed milestone")
        session.commit()
        record_snapshot_access(session, "legacy-export")
        session.commit()
    with Session(engine) as session:
        row = session.execute(select(snapshot_lifecycle)).mappings().one()
        assert row["pin_reason"] == "confirmed milestone"
        assert row["last_accessed_at"] >= now
        assert row["source_fingerprint"] is None


def test_concurrent_legacy_backfills_do_not_fail_or_overwrite(pg):
    engine, _ = pg
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        add_run(session, "rollout-window", now)
        session.commit()
    barrier = Barrier(2)
    def before_insert(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO ranking_snapshot_lifecycle"):
            barrier.wait(timeout=20)
    event.listen(engine, "before_cursor_execute", before_insert)
    def backfill(_):
        with Session(engine) as session:
            inserted = backfill_lifecycle_metadata(session)
            session.commit()
            return inserted
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(backfill, range(2))) == [0, 1]
    finally:
        event.remove(engine, "before_cursor_execute", before_insert)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(snapshot_lifecycle)) == 1
        archive_snapshot(session, "rollout-window", reason="confirmed rollout checkpoint")
        session.commit()
        assert backfill_lifecycle_metadata(session) == 0
        row = session.execute(select(snapshot_lifecycle)).mappings().one()
        assert row["pin_reason"] == "confirmed rollout checkpoint"
