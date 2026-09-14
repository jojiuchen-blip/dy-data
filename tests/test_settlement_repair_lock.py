"""R87-L: unit contracts plus opt-in disposable PostgreSQL lock contention."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import importlib
import importlib.util
import os
from threading import Event
from time import monotonic, sleep
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, SessionTransactionOrigin, sessionmaker

from apps.api.dy_api import models


def _repair_lock():
    name = "apps.worker.settlement_repair_lock"
    assert importlib.util.find_spec(name) is not None, "R87-L lock implementation is missing"
    return importlib.import_module(name)


def _recording_session():
    session = MagicMock(spec=Session)
    session.get_bind.return_value.dialect.name = "postgresql"
    session.is_active = True
    session.in_transaction.return_value = True
    session.in_nested_transaction.return_value = False
    session.get_transaction.return_value.origin = SessionTransactionOrigin.BEGIN
    session.new = session.dirty = session.deleted = frozenset()
    session.identity_map = {}
    session.connection.return_value.get_isolation_level.return_value = "READ COMMITTED"
    return session


def test_non_postgresql_fails_closed_without_sql(db_session):
    repair_lock = _repair_lock()
    statements = []
    event.listen(db_session.get_bind(), "before_cursor_execute", lambda *args: statements.append(args[2]))
    with pytest.raises(ValueError, match="PostgreSQL"):
        repair_lock.acquire_settlement_repair_lock(db_session)
    assert statements == []


def test_fixed_metadata_inventory_covers_sources_finance_and_lineage():
    repair_lock = _repair_lock()
    # Explicit review baseline, including indirect repository/lineage readers.
    required_models = (
        models.RawDouyinOrder, models.RawDouyinOrderCoupon, models.RawDouyinVerifyRecord,
        models.DouyinRefundEvent, models.RawAwemeBinding, models.DimAwemeAccount,
        models.DimNonCommissionOwnerAccount, models.DimSkuProductRule, models.DimStore,
        models.DimStorePoiMapping, models.SkuFeeRule, models.SettlementScopeRule,
        models.SettlementOrderDetail, models.SettlementFeeResult, models.SettlementFeeResultCurrent,
        models.SettlementFeeAdjustment, models.SettlementCarryforwardSource,
        models.SettlementCarryforwardApplication, models.SettlementStatement,
        models.SettlementStatementEntry, models.SettlementStatementLine,
        models.SettlementStatementConfirmation, models.InvoiceRecord,
        models.PromotionInvoiceAllocation, models.SettlementDispute, models.StoreFinanceProfile,
        models.AggStoreMonthlySettlement, models.AggStoreRanking,
        models.SettlementProjectionActive, models.SettlementProjectionGeneration,
        models.SettlementProjectionPartitionManifest, models.SettlementProjectionCompactionClosure,
        models.SettlementMonthlyOverlay, models.SettlementRankingOverlay,
        models.SettlementBillingSourceBundle, models.JobEvent, models.JobImpact,
        models.ClueMaterializationWorkItem, models.FinanceOperationAudit, models.DataQualityIssue,
    )
    names = repair_lock.SETTLEMENT_REPAIR_LOCK_TABLES
    assert isinstance(names, tuple)
    assert names == tuple(sorted({model.__table__.name for model in required_models}))
    assert "job_runs" not in names
    assert all(name in models.Base.metadata.tables for name in names)


def test_fixed_lock_statement_and_local_timeouts_without_commit():
    repair_lock = _repair_lock()
    session = _recording_session()
    names = repair_lock.acquire_settlement_repair_lock(
        session, lock_timeout_ms=500, statement_timeout_ms=2500,
    )
    calls = session.execute.call_args_list
    assert len(calls) == 2
    assert "set_config('lock_timeout'" in str(calls[0].args[0])
    assert "set_config('statement_timeout'" in str(calls[0].args[0])
    assert "true" in str(calls[0].args[0])
    assert calls[0].args[1] == {"lock_timeout": "500ms", "statement_timeout": "2500ms"}
    assert str(calls[1].args[0]) == (
        "LOCK TABLE " + ", ".join('"' + name + '"' for name in names)
        + " IN SHARE ROW EXCLUSIVE MODE"
    )
    session.commit.assert_not_called()
    session.flush.assert_not_called()
    session.rollback.assert_not_called()


@pytest.mark.parametrize("options", [
    {"lock_timeout_ms": 0}, {"lock_timeout_ms": True}, {"lock_timeout_ms": 5001},
    {"lock_timeout_ms": "1; SELECT 1"}, {"statement_timeout_ms": 0},
    {"statement_timeout_ms": 60001}, {"statement_timeout_ms": False},
    {"lock_timeout_ms": 2000, "statement_timeout_ms": 1000},
])
def test_invalid_timeouts_do_not_issue_sql(options):
    repair_lock = _repair_lock()
    session = _recording_session()
    with pytest.raises(ValueError):
        repair_lock.acquire_settlement_repair_lock(session, **options)
    session.execute.assert_not_called()


@pytest.mark.parametrize("state", ["no_transaction", "nested", "autobegin", "dirty", "loaded", "failed"])
def test_requires_fresh_explicit_transaction_before_business_access(state):
    repair_lock = _repair_lock()
    session = _recording_session()
    if state == "no_transaction":
        session.in_transaction.return_value = False
    elif state == "nested":
        session.in_nested_transaction.return_value = True
    elif state == "autobegin":
        session.get_transaction.return_value.origin = SessionTransactionOrigin.AUTOBEGIN
    elif state == "dirty":
        session.new = {object()}
    elif state == "loaded":
        session.identity_map = {"loaded": object()}
    else:
        session.is_active = False
    with pytest.raises(ValueError):
        repair_lock.acquire_settlement_repair_lock(session)
    session.execute.assert_not_called()


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE", "AUTOCOMMIT"])
def test_rejects_prelock_snapshot_isolation(isolation):
    repair_lock = _repair_lock()
    session = _recording_session()
    session.connection.return_value.get_isolation_level.return_value = isolation
    with pytest.raises(ValueError, match="READ COMMITTED"):
        repair_lock.acquire_settlement_repair_lock(session)
    session.execute.assert_not_called()


def test_lock_failure_rolls_back_entire_transaction_without_retry():
    repair_lock = _repair_lock()
    session = _recording_session()
    failure = OperationalError("LOCK", {}, RuntimeError("lock timeout"))
    session.execute.side_effect = [None, failure]
    with pytest.raises(OperationalError) as raised:
        repair_lock.acquire_settlement_repair_lock(session)
    assert raised.value is failure
    session.rollback.assert_called_once_with()
    assert session.execute.call_count == 2
    session.commit.assert_not_called()


def test_rejects_models_routed_to_a_different_database():
    repair_lock = _repair_lock()
    session = _recording_session()
    primary = session.get_bind.return_value
    other = object()
    session.get_bind.side_effect = lambda **kw: other if kw.get("clause") is models.InvoiceRecord.__table__ else primary
    with pytest.raises(ValueError, match="single bind"):
        repair_lock.acquire_settlement_repair_lock(session)
    session.execute.assert_not_called()


@pytest.fixture
def repair_pg():
    raw_url = os.getenv("DY_RELEASE_POSTGRES_URL")
    if not raw_url:
        pytest.skip("requires disposable loopback dydata_release PostgreSQL; not production")
    repair_lock = _repair_lock()
    url = make_url(raw_url)
    if (url.drivername not in {"postgresql", "postgresql+psycopg", "postgresql+psycopg2"}
            or url.host not in {"127.0.0.1", "localhost"}
            or url.database != "dydata_release" or url.query):
        pytest.fail("repair gate requires loopback dydata_release without URL query overrides")
    schema = "repair_lock_" + uuid4().hex
    admin = create_engine(url, connect_args={"connect_timeout": 5})
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={
        "connect_timeout": 5,
        "options": f"-c search_path={schema} -c lock_timeout=6000 -c statement_timeout=10000",
    })
    try:
        tables = {models.Base.metadata.tables[name] for name in repair_lock.SETTLEMENT_REPAIR_LOCK_TABLES}
        tables.add(models.JobRun.__table__)
        while True:
            parents = {fk.column.table for table in tables for fk in table.foreign_keys}
            if parents.issubset(tables):
                break
            tables |= parents
        models.Base.metadata.create_all(engine, tables=sorted(tables, key=lambda table: table.name))
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        with factory.begin() as session:
            session.add(models.DimStore(store_id="existing", store_name="Before"))
            session.add(models.JobRun(
                job_id="repair-heartbeat", job_name="settlement_rebuild", status="running",
                claim_token="repair-claim",
                lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            ))
        yield factory, engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def _wait_for_block(engine, pid, owner_pid, future):
    deadline = monotonic() + 3
    with engine.connect() as observer:
        while monotonic() < deadline:
            blockers = observer.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": pid})
            if owner_pid in blockers:
                return
            assert not future.done(), "contender completed without waiting for the repair"
            sleep(0.02)
    pytest.fail("contender did not block on the repair backend")


@pytest.mark.parametrize("release", ["commit", "rollback"])
@pytest.mark.parametrize("operation", ["insert", "update", "delete", "second_repair"])
def test_pg_blocks_ordinary_writes_and_serializes_repairs(repair_pg, release, operation):
    repair_lock = _repair_lock()
    factory, engine = repair_pg
    entered = Event()
    pids = []

    def contender():
        with factory.begin() as session:
            pids.append(session.scalar(text("SELECT pg_backend_pid()")))
            entered.set()
            if operation == "second_repair":
                repair_lock.acquire_settlement_repair_lock(session, lock_timeout_ms=5000)
            else:
                statement = {
                    "insert": "INSERT INTO dim_stores (store_id, store_name) VALUES ('phantom', 'After')",
                    "update": "UPDATE dim_stores SET store_name='After' WHERE store_id='existing'",
                    "delete": "DELETE FROM dim_stores WHERE store_id='existing'",
                }[operation]
                session.execute(text(statement))
            # In particular, the second repair must be able to upgrade to DML.
            if operation == "second_repair":
                session.execute(text("UPDATE dim_stores SET store_name='After' WHERE store_id='existing'"))

    with ThreadPoolExecutor(max_workers=1) as pool, factory() as owner:
        owner.begin()
        repair_lock.acquire_settlement_repair_lock(owner)
        owner_pid = owner.scalar(text("SELECT pg_backend_pid()"))
        future = pool.submit(contender)
        try:
            assert entered.wait(3)
            _wait_for_block(engine, pids[0], owner_pid, future)
            # Ordinary reads remain available while the repair holds its lock.
            with engine.connect() as reader:
                assert reader.scalar(text("SELECT count(*) FROM dim_stores")) == 1
            assert owner.scalar(text("SELECT count(*) FROM dim_stores")) == 1
        finally:
            getattr(owner, release)()
        future.result(timeout=8)
    with engine.connect() as reader:
        if operation == "insert":
            assert reader.scalar(text("SELECT count(*) FROM dim_stores")) == 2
        elif operation == "delete":
            assert reader.scalar(text("SELECT count(*) FROM dim_stores")) == 0
        else:
            assert reader.scalar(text("SELECT store_name FROM dim_stores")) == "After"


def test_pg_lock_inventory_and_independent_real_heartbeat(repair_pg):
    repair_lock = _repair_lock()
    from apps.worker.settlement_rebuild import heartbeat_settlement_rebuild_job

    factory, engine = repair_pg
    with factory.begin() as session:
        names = repair_lock.acquire_settlement_repair_lock(session)
        actual = set(session.scalars(text(
            "SELECT c.relname FROM pg_locks l JOIN pg_class c ON c.oid=l.relation "
            "WHERE l.pid=pg_backend_pid() AND l.mode='ShareRowExclusiveLock' AND l.granted"
        )))
        assert set(names) <= actual
        assert "job_runs" not in actual
        assert heartbeat_settlement_rebuild_job(
            factory, job_id="repair-heartbeat", claim_id="repair-claim", stage="lock-test",
        )


def test_pg_timeout_releases_partial_locks_and_local_settings(repair_pg):
    repair_lock = _repair_lock()
    factory, engine = repair_pg
    last = repair_lock.SETTLEMENT_REPAIR_LOCK_TABLES[-1]
    with engine.connect() as blocker, factory() as session:
        blocker.begin()
        # Constant inventory only, never a user-provided identifier.
        blocker.execute(text(f'LOCK TABLE "{last}" IN ROW EXCLUSIVE MODE'))
        session.begin()
        with pytest.raises(OperationalError):
            repair_lock.acquire_settlement_repair_lock(session, lock_timeout_ms=100, statement_timeout_ms=1000)
        assert not session.in_transaction()
        with engine.begin() as probe:
            probe.execute(text("SET LOCAL lock_timeout='200ms'"))
            first = repair_lock.SETTLEMENT_REPAIR_LOCK_TABLES[0]
            probe.execute(text(f'LOCK TABLE "{first}" IN ROW EXCLUSIVE MODE'))
        blocker.rollback()
        with session.begin():
            assert session.scalar(text("SHOW lock_timeout")) == "6s"
            assert session.scalar(text("SHOW statement_timeout")) == "10s"
