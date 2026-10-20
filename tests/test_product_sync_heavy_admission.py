"""Product wrapper admission must precede all source and adapter work."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from apps.api.dy_api.db import session_scope
from apps.api.dy_api.models import Base, JobRun, SkuProductSyncHistory, SyncSetting
from apps.ops_agent.resources import ResourceAction, ResourceDecision
from apps.worker import product_sync, scheduler, settlement_compaction
from apps.worker.repositories import HEAVY_SYNC_CLAIM_LOCK_KEY, queue_job_run

ALLOW = ResourceDecision(ResourceAction.ALLOW, ())


@pytest.fixture(autouse=True)
def allow_resources(monkeypatch):
    monkeypatch.setattr(product_sync, "current_resource_decision", lambda: ALLOW)
    monkeypatch.setenv("WORKER_RESOURCE_GUARD_ENABLED", "false")


def _factory(session):
    return sessionmaker(bind=session.get_bind(), autoflush=False, expire_on_commit=False)


def _queue(factory, *, job_id="product-heavy", mode="INCREMENTAL", started_at=None):
    with session_scope(factory) as session:
        queue_job_run(session, job_id, product_sync.PRODUCT_SYNC_JOB_NAME,
            metadata_json={"mode": mode, "phase_counts": {}, "request_marker": "preserved"},
            started_at=started_at)
        if session.get(SyncSetting, product_sync.PRODUCT_SYNC_CURSOR_SETTING_KEY) is None:
            session.add(SyncSetting(setting_key=product_sync.PRODUCT_SYNC_CURSOR_SETTING_KEY,
                                    setting_value="existing-cursor"))
    return job_id


def _empty_adapter(calls=None):
    def page(*, mode, cursor):
        if calls is not None:
            calls.append((mode, cursor))
        return {"items": [], "hasMore": False, "nextCursor": None}
    return product_sync.NormalizedProductSyncAdapter(page)


def _forbid_source_or_adapter(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("rejected product admission reached source scan or adapter initialization")
    monkeypatch.setattr(product_sync, "extract_known_order_products", forbidden)
    monkeypatch.setattr("apps.worker.pipeline.build_douyin_client_from_env", forbidden)


def _assert_untouched(factory, job_id):
    with factory() as session:
        job = session.get(JobRun, job_id)
        assert job.status == "queued" and job.execution_slot is None
        assert job.attempt_count in {None, 0} and job.error_message is None
        assert job.metadata_json == {
            "mode": "INCREMENTAL", "phase_counts": {}, "request_marker": "preserved",
        }
        assert session.get(SyncSetting, product_sync.PRODUCT_SYNC_CURSOR_SETTING_KEY).setting_value == "existing-cursor"
        assert session.scalar(select(func.count()).select_from(SkuProductSyncHistory)) == 0


@pytest.mark.parametrize("action", [ResourceAction.STOP, ResourceAction.DRAIN])
def test_resource_refusal_never_scans_or_initializes(db_session, monkeypatch, action):
    factory = _factory(db_session)
    job_id = _queue(factory)
    _forbid_source_or_adapter(monkeypatch)
    monkeypatch.setattr(product_sync, "current_resource_decision",
                        lambda: ResourceDecision(action, ("synthetic_pressure",)))
    result = product_sync.run_product_sync_job(job_id=job_id, factory=factory)
    assert result.status == "DEFERRED" and result.error_code == "RESOURCE_NOT_ALLOW"
    _assert_untouched(factory, job_id)


def test_missing_resource_evidence_defers_without_source_reads(db_session, monkeypatch):
    factory = _factory(db_session)
    job_id = _queue(factory)
    _forbid_source_or_adapter(monkeypatch)
    def unavailable():
        raise RuntimeError("synthetic missing evidence")
    monkeypatch.setattr(product_sync, "current_resource_decision", unavailable)
    result = product_sync.run_product_sync_job(job_id=job_id, factory=factory)
    assert result.status == "DEFERRED" and result.error_code == "RESOURCE_UNAVAILABLE"
    _assert_untouched(factory, job_id)


@pytest.mark.parametrize("name,slot", [
    ("settlement_compaction", "heavy_sync"),
    ("settlement_rebuild", None),
])
def test_running_writer_refuses_product_before_source_scan(db_session, monkeypatch, name, slot):
    factory = _factory(db_session)
    job_id = _queue(factory)
    with session_scope(factory) as session:
        session.add(JobRun(job_id="other-writer", job_name=name, status="running", execution_slot=slot))
    _forbid_source_or_adapter(monkeypatch)
    statements = []
    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)
    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = product_sync.run_product_sync_job(job_id=job_id, factory=factory)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert result.status == "DEFERRED" and result.error_code == "HEAVY_SLOT_BUSY"
    assert not any("raw_douyin_order" in statement.lower() for statement in statements)
    _assert_untouched(factory, job_id)


def test_global_rate_limit_cooldown_defers_product(db_session, monkeypatch):
    factory = _factory(db_session)
    job_id = _queue(factory)
    with session_scope(factory) as session:
        session.add(JobRun(job_id="cooldown", job_name="daily", status="retry_wait",
            execution_slot="heavy_sync", error_code="douyin_rate_limited",
            next_retry_at=datetime.now(timezone.utc) + timedelta(minutes=5)))
    _forbid_source_or_adapter(monkeypatch)
    result = product_sync.run_product_sync_job(job_id=job_id, factory=factory)
    assert result.status == "DEFERRED" and result.error_code == "RATE_LIMIT_COOLDOWN"
    _assert_untouched(factory, job_id)


@pytest.mark.parametrize("status", ["running", "success", "failed"])
def test_nonqueued_product_is_not_executed_again(db_session, monkeypatch, status):
    factory = _factory(db_session)
    job_id = _queue(factory)
    with session_scope(factory) as session:
        session.get(JobRun, job_id).status = status
    _forbid_source_or_adapter(monkeypatch)
    result = product_sync.run_product_sync_job(job_id=job_id, factory=factory)
    assert result.status == "DEFERRED" and result.error_code == "JOB_NOT_QUEUED"
    with factory() as session:
        job = session.get(JobRun, job_id)
        assert job.status == status and job.execution_slot is None
        assert job.attempt_count in {None, 0}


@pytest.mark.parametrize("failing", [False, True])
def test_admitted_wrapper_preserves_slot_through_success_and_failure(db_session, failing):
    factory = _factory(db_session)
    job_id = _queue(factory)
    class Adapter:
        def fetch_page(self, **kwargs):
            if failing:
                raise RuntimeError("synthetic upstream failure")
            return _empty_adapter().fetch_page(**kwargs)
    result = product_sync.run_product_sync_job(job_id=job_id, factory=factory, adapter=Adapter())
    assert result.status == ("FAILED" if failing else "SUCCESS")
    with factory() as session:
        job = session.get(JobRun, job_id)
        assert job.execution_slot == "heavy_sync"
        assert job.status == ("failed" if failing else "success")
        assert session.get(SyncSetting, product_sync.PRODUCT_SYNC_CURSOR_SETTING_KEY).setting_value == "existing-cursor"


def _configure_scheduler(monkeypatch):
    monkeypatch.setenv("DOUYIN_PRODUCT_SYNC_ENABLED", "true")
    monkeypatch.setenv("DOUYIN_PRODUCT_SYNC_INTERVAL_SECONDS", "3600")
    for name in ("douyin_app_id", "douyin_app_secret", "douyin_account_id"):
        monkeypatch.setattr(scheduler, name, lambda: "synthetic-configured")


def test_scheduler_recovers_deferred_queue_with_original_identity_mode_and_interval(db_session, monkeypatch):
    factory = _factory(db_session)
    _configure_scheduler(monkeypatch)
    now = datetime.now(timezone.utc)
    job_id = _queue(factory, mode="FULL", started_at=now)
    monkeypatch.setattr(product_sync, "current_resource_decision",
                        lambda: ResourceDecision(ResourceAction.STOP, ()))
    assert product_sync.run_product_sync_job(job_id=job_id, factory=factory).status == "DEFERRED"
    monkeypatch.setattr(product_sync, "current_resource_decision", lambda: ALLOW)
    calls = []
    monkeypatch.setattr(scheduler, "run_product_sync_job", lambda *, job_id, factory:
        product_sync.run_product_sync_job(job_id=job_id, factory=factory, adapter=_empty_adapter(calls)))
    assert scheduler.run_scheduled_product_sync(factory, now=now + timedelta(seconds=1)) == job_id
    assert calls == [("FULL", None)]
    assert scheduler.run_scheduled_product_sync(factory, now=now + timedelta(seconds=2)) is None
    with factory() as session:
        job = session.get(JobRun, job_id)
        assert job.status == "success" and job.metadata_json["mode"] == "FULL"
        assert job.metadata_json["request_marker"] == "preserved"
        assert session.scalar(select(func.count()).select_from(JobRun)) == 1


def test_scheduler_new_success_respects_interval(db_session, monkeypatch):
    factory = _factory(db_session)
    _configure_scheduler(monkeypatch)
    monkeypatch.setattr(scheduler, "run_product_sync_job", lambda *, job_id, factory:
        product_sync.run_product_sync_job(job_id=job_id, factory=factory, adapter=_empty_adapter()))
    now = datetime.now(timezone.utc)
    first = scheduler.run_scheduled_product_sync(factory, now=now)
    assert first is not None
    assert scheduler.run_scheduled_product_sync(factory, now=now + timedelta(seconds=10)) is None
    with factory() as session:
        assert session.get(JobRun, first).status == "success"
        assert session.scalar(select(func.count()).select_from(JobRun)) == 1


@pytest.mark.parametrize("blocker", ["disabled", "credentials", "running"])
def test_scheduler_retains_existing_skip_conditions(db_session, monkeypatch, blocker):
    factory = _factory(db_session)
    _configure_scheduler(monkeypatch)
    if blocker == "disabled":
        monkeypatch.setenv("DOUYIN_PRODUCT_SYNC_ENABLED", "false")
    elif blocker == "credentials":
        monkeypatch.setattr(scheduler, "douyin_app_id", lambda: "")
    else:
        queued = _queue(factory)
        with session_scope(factory) as session:
            session.get(JobRun, queued).status = "running"
    monkeypatch.setattr(scheduler, "run_product_sync_job", lambda **kwargs: pytest.fail("must remain skipped"))
    assert scheduler.run_scheduled_product_sync(factory) is None
    if blocker == "running":
        with factory() as session:
            assert session.get(JobRun, queued).status == "running"


@pytest.fixture
def product_pg():
    raw_url = os.getenv("DY_MAINTENANCE_POSTGRES_URL") or os.getenv("DY_RELEASE_POSTGRES_URL")
    if not raw_url:
        pytest.skip("requires disposable maintenance/release PostgreSQL")
    url = make_url(raw_url)
    if (not url.drivername.startswith("postgresql")
            or url.host not in {"127.0.0.1", "localhost"}
            or url.database not in {"dydata104_test", "dydata_release"}):
        pytest.fail("product admission tests require an explicitly named loopback disposable database")
    schema = f"product_admission_{uuid4().hex}"
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-c search_path={schema} -c statement_timeout=10000"})
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        Base.metadata.create_all(engine)
        yield factory
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def test_pg_shared_lock_refuses_product_without_source_work_then_resumes(product_pg, monkeypatch):
    factory = product_pg
    job_id = _queue(factory)
    _forbid_source_or_adapter(monkeypatch)
    with factory() as holder:
        holder.scalar(select(func.pg_advisory_xact_lock(HEAVY_SYNC_CLAIM_LOCK_KEY)))
        result = product_sync.run_product_sync_job(job_id=job_id, factory=factory)
        assert result.status == "DEFERRED" and result.error_code == "HEAVY_SLOT_BUSY"
        _assert_untouched(factory, job_id)
    result = product_sync.run_product_sync_job(job_id=job_id, factory=factory, adapter=_empty_adapter())
    assert result.status == "SUCCESS"


@pytest.mark.parametrize("name,slot", [("settlement_compaction", "heavy_sync"), ("settlement_rebuild", None)])
def test_pg_running_compaction_or_legacy_rebuild_refuses_product(product_pg, monkeypatch, name, slot):
    factory = product_pg
    job_id = _queue(factory)
    with session_scope(factory) as session:
        session.add(JobRun(job_id="pg-other-writer", job_name=name, status="running", execution_slot=slot))
    _forbid_source_or_adapter(monkeypatch)
    result = product_sync.run_product_sync_job(job_id=job_id, factory=factory)
    assert result.status == "DEFERRED" and result.error_code == "HEAVY_SLOT_BUSY"
    _assert_untouched(factory, job_id)
    with session_scope(factory) as session:
        session.get(JobRun, "pg-other-writer").status = "success"
    assert product_sync.run_product_sync_job(job_id=job_id, factory=factory, adapter=_empty_adapter()).status == "SUCCESS"


def test_pg_product_transaction_blocks_compaction_claim_until_commit(product_pg):
    factory = product_pg
    job_id = _queue(factory)
    with session_scope(factory) as session:
        session.add(JobRun(job_id="pg-compaction-queued", job_name="settlement_compaction",
            status="queued", execution_slot="heavy_sync", metadata_json={}))
    product_started = Event()
    release_product = Event()
    class PausedAdapter:
        def fetch_page(self, **kwargs):
            product_started.set()
            assert release_product.wait(10), "product transaction was not released"
            return _empty_adapter().fetch_page(**kwargs)
    with ThreadPoolExecutor(max_workers=1) as executor:
        running = executor.submit(product_sync.run_product_sync_job,
            job_id=job_id, factory=factory, adapter=PausedAdapter())
        try:
            assert product_started.wait(10), "product was not admitted"
            with factory() as observer:
                # The product's running mutation is uncommitted. The shared
                # xact lock, rather than an accidentally visible row, blocks
                # this other executor's compaction claim.
                assert observer.get(JobRun, job_id).status == "queued"
            assert settlement_compaction.claim_settlement_compaction_job(
                factory, job_id="pg-compaction-queued", resource_decision=ALLOW) is None
        finally:
            release_product.set()
        assert running.result(timeout=10).status == "SUCCESS"
    claimed = settlement_compaction.claim_settlement_compaction_job(
        factory, job_id="pg-compaction-queued", resource_decision=ALLOW)
    assert claimed is not None
    with factory() as session:
        assert session.get(JobRun, job_id).execution_slot == "heavy_sync"
        assert session.get(JobRun, job_id).status == "success"


def test_pg_product_rollback_releases_shared_lock_and_restores_queue(product_pg):
    factory = product_pg
    job_id = _queue(factory, mode="INVALID")
    with pytest.raises(ValueError, match="Invalid product sync mode"):
        product_sync.run_product_sync_job(job_id=job_id, factory=factory, adapter=_empty_adapter())
    with factory() as session:
        job = session.get(JobRun, job_id)
        assert job.status == "queued" and job.execution_slot is None
        assert job.attempt_count in {None, 0} and job.metadata_json["mode"] == "INVALID"
        assert session.scalar(select(func.pg_try_advisory_xact_lock(HEAVY_SYNC_CLAIM_LOCK_KEY))) is True
