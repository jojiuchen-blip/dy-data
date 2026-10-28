"""Disposable-schema PostgreSQL transaction and actual lock concurrency tests."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import os
from threading import Barrier, Event
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from apps.api.dy_api.models import Base, FinanceOperationAudit, SettlementStatement, SettlementStatementConfirmation
from apps.worker import historical_fee_correction as correction
from test_historical_fee_correction import apply, fingerprint, seed


@pytest.fixture
def correction_pg():
    raw_url = os.getenv("DYDATA_HISTORICAL_FEE_TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("requires disposable local historical-fee PostgreSQL service")
    url = make_url(raw_url)
    if (not url.drivername.startswith("postgresql") or url.host not in {"127.0.0.1","localhost"}
            or url.database != "dydata_delivery_test"):
        pytest.fail("correction gate requires loopback dydata_delivery_test")
    schema = "historical_fee_test_"+uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url,connect_args={"options":f"-c search_path={schema} -c lock_timeout=10000 -c statement_timeout=30000"})
    factory = sessionmaker(bind=engine,autoflush=False,expire_on_commit=False)
    try:
        Base.metadata.create_all(engine)
        yield factory
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def test_pg_commit_roundtrip_and_whole_transaction_rollback(correction_pg,monkeypatch):
    with correction_pg() as session:
        manifest,sources = seed(session)
        preview = correction.preview_correction(session,manifest,source_documents=sources)
        before = fingerprint(session)
        original = correction._clone_bill
        def injected(*args,**kwargs):
            original(*args,**kwargs)
            raise RuntimeError("pg injected failure")
        with monkeypatch.context() as patch:
            patch.setattr(correction,"_clone_bill",injected)
            with pytest.raises(RuntimeError,match="injected"):
                apply(session,manifest,sources,preview)
        session.commit()
        assert fingerprint(session) == before
        result = apply(session,manifest,sources,preview)
        session.commit()
        assert len(result["new_statement_ids"]) == 7
    with correction_pg() as session:
        before = fingerprint(session)
        assert apply(session,manifest,sources,preview)["already_applied"]
        session.commit()
        assert fingerprint(session) == before


def test_pg_concurrent_same_request_creates_one_result(correction_pg):
    with correction_pg() as session:
        manifest,sources = seed(session)
        preview = correction.preview_correction(session,manifest,source_documents=sources)
    barrier = Barrier(2)
    def run():
        with correction_pg() as session:
            barrier.wait(timeout=10)
            result = apply(session,manifest,sources,preview)
            session.commit()
            return result
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run) for _ in range(2)]
        results = [future.result(timeout=30) for future in futures]
    assert sorted(row["already_applied"] for row in results) == [False,True]
    with correction_pg() as session:
        assert session.scalar(select(func.count()).select_from(FinanceOperationAudit)) == 16
        assert session.scalar(select(func.count()).select_from(SettlementStatement)) == 16


def test_pg_two_requests_same_slot_cannot_double_post(correction_pg):
    with correction_pg() as session:
        manifest,sources = seed(session)
        preview = correction.preview_correction(session,manifest,source_documents=sources)
        other = deepcopy(manifest)
        other["request_id"] = "second-request"
        other_preview = correction.preview_correction(session,other,source_documents=sources)
    barrier = Barrier(2)
    def run(payload,expected):
        with correction_pg() as session:
            barrier.wait(timeout=10)
            try:
                result = apply(session,payload,sources,expected)
                session.commit()
                return result
            except correction.HistoricalFeeCorrectionError as exc:
                session.rollback()
                return str(exc)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run,manifest,preview),pool.submit(run,other,other_preview)]
        results = [future.result(timeout=30) for future in futures]
    assert sum(isinstance(result,dict) for result in results) == 1
    assert any(isinstance(result,str) and "EXISTING_ADJUSTMENT" in result for result in results)
    with correction_pg() as session:
        assert session.scalar(select(func.count()).select_from(FinanceOperationAudit)) == 16


def test_pg_concurrent_confirmation_wins_and_correction_fails_closed(correction_pg,monkeypatch):
    with correction_pg() as session:
        manifest,sources = seed(session)
        preview = correction.preview_correction(session,manifest,source_documents=sources)
    started = Event()
    original = correction._request_lock
    def signal(session,request_id):
        original(session,request_id)
        started.set()
    monkeypatch.setattr(correction,"_request_lock",signal)
    with correction_pg() as confirmer,ThreadPoolExecutor(max_workers=1) as pool:
        correction._lock_settlement_slot(confirmer,"sale-store","2026-09")
        bill = confirmer.scalar(select(SettlementStatement).where(SettlementStatement.statement_id == "bill-sale-store").with_for_update())
        def run():
            with correction_pg() as session:
                try:
                    apply(session,manifest,sources,preview)
                except correction.HistoricalFeeCorrectionError as exc:
                    session.rollback()
                    return str(exc)
                pytest.fail("correction overwrote a concurrent confirmation")
        future = pool.submit(run)
        assert started.wait(timeout=10)
        assert not future.done()
        confirmer.add(SettlementStatementConfirmation(confirmation_id="concurrent-confirmation",statement_id=bill.statement_id,
            fee_direction=1,confirmation_status=1,confirmed_amount_cent=bill.promotion_net_fee_cent,confirmed_by="synthetic-admin"))
        confirmer.commit()
        assert future.result(timeout=30) == "PROTECTED_CONFIRMATIONS"
    with correction_pg() as session:
        assert session.scalar(select(func.count()).select_from(FinanceOperationAudit)) == 0


def test_pg_apply_refuses_repeatable_read_snapshot(correction_pg):
    with correction_pg() as session:
        manifest,sources = seed(session)
        preview = correction.preview_correction(session,manifest,source_documents=sources)
        session.rollback()
        session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
        with pytest.raises(correction.HistoricalFeeCorrectionError,match="READ_COMMITTED"):
            apply(session,manifest,sources,preview)
        session.rollback()
        assert session.scalar(select(func.count()).select_from(FinanceOperationAudit)) == 0
