"""Disposable localhost PostgreSQL migration, fencing and concurrency evidence."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from types import SimpleNamespace

from alembic import command
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from apps.worker import account_qualification as q
from apps.worker.browser_exports import active_marker, backend_aweme as backend
from test_dashboard_publication_migration import full_pg_stack
from account_qualification_fixtures import binding, observe


def test_real_postgres_migration_atomicity_immutability_and_concurrent_freeze(full_pg_stack, monkeypatch, tmp_path):
    # Keep the real marker protocol while isolating the host's writable path.
    marker = tmp_path / "browser-export.active"
    monkeypatch.setattr(active_marker, "FIXED_BROWSER_EXPORT_ACTIVE_FILE", marker)
    monkeypatch.setenv("BROWSER_EXPORT_ACTIVE_FILE", str(marker))
    config, engine = full_pg_stack
    command.upgrade(config, "head")
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    _, cutoff = q.month_bounds("2026-10")
    with factory.begin() as session:
        observe(session)
    def freeze(_):
        with factory.begin() as session:
            return q.freeze_month(session, "2026-10", now=cutoff).version_id
    with ThreadPoolExecutor(max_workers=4) as pool:
        versions = list(pool.map(freeze, range(4)))
    assert len(set(versions)) == 1
    with factory() as session:
        version = session.scalar(select(q.Version))
        snapshot_hash = version.content_sha256
        observation_id = version.observation_id
        assert session.scalar(text("SELECT generation FROM dashboard_publication_source_counters WHERE source_name='account_qualification_version'")) == 1
    for sql, values in (
        ("UPDATE account_qualification_snapshot SET record_count=0 WHERE content_sha256=:id", {"id": snapshot_hash}),
        ("DELETE FROM account_qualification_version WHERE version_id=:id", {"id": versions[0]}),
        ("UPDATE account_qualification_observation SET state='failed' WHERE observation_id=:id", {"id": observation_id}),
        ("TRUNCATE account_qualification_version", {}),
    ):
        with engine.connect() as connection, connection.begin(), pytest.raises(DBAPIError, match="immutable|foreign key"):
            connection.execute(text(sql), values)
    # A fetch failure is durably recorded despite the caller's rollback.
    monkeypatch.setattr(backend, "datetime", SimpleNamespace(now=lambda _: cutoff-timedelta(minutes=50)))
    monkeypatch.setattr(backend, "export_backend_aweme_records_via_browser",
                        lambda **kwargs: (_ for _ in ()).throw(backend.BrowserExportError("synthetic failure")))
    with factory() as session:
        with pytest.raises(backend.BrowserExportError):
            backend.run_backend_aweme_export(session, source_run_id="failed-fetch")
        session.rollback()
    assert not marker.exists()
    with factory() as session:
        failed = session.scalar(select(q.Observation).where(q.Observation.source_run_id == "failed-fetch"))
        assert failed.state == "failed" and failed.error_code == "backend_collection_failed"
    # If raw ingestion / commit fails, success and content are never committed.
    monkeypatch.setattr(backend, "export_backend_aweme_records_via_browser", lambda **kwargs:
        q.BindingRecords([binding()], source_type="synthetic", proof={"complete": True, "record_count": 1}))
    with factory() as session:
        backend.run_backend_aweme_export(session, source_run_id="rolled-back-success")
        session.rollback()
    assert not marker.exists()
    with factory() as session:
        rolled_back = session.scalar(select(q.Observation).where(q.Observation.source_run_id == "rolled-back-success"))
        assert rolled_back.state == "running" and not rolled_back.complete and rolled_back.content_sha256 is None
        assert q.freeze_month(session, "2026-10", now=cutoff + timedelta(days=1)).version_id == versions[0]
    # Concurrent automatic retries are bounded independently of the old month.
    _, next_cutoff = q.month_bounds("2026-11")
    def admit(index):
        with factory.begin() as session:
            return q.begin_automatic_observation(session, source_run_id=f"budget-concurrency-{index}",
                                                  started_at=next_cutoff-timedelta(minutes=30))
    with ThreadPoolExecutor(max_workers=4) as pool:
        admissions = list(pool.map(admit, range(12)))
    assert sum(row.observation_id is not None for row in admissions) == q.MAX_AUTOMATIC_MONTH_ATTEMPTS
    assert sum(row.blocked_reason == "monthend_capture_budget_exhausted" for row in admissions) == 4
    with factory() as session:
        november = list(session.scalars(select(q.Observation).where(
            q.Observation.started_at >= next_cutoff-q.MAX_AGE, q.Observation.started_at < next_cutoff)))
        assert len(november) == q.MAX_AUTOMATIC_MONTH_ATTEMPTS+1
    # A populated evidence migration is explicitly forward-only.
    with pytest.raises(RuntimeError, match="preserved"):
        command.downgrade(config, "20261023_0065")
