"""Opt-in PostgreSQL replay gates, isolated in a random loopback test schema."""

from concurrent.futures import ThreadPoolExecutor
import os
import re
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from apps.api.dy_api.db import normalize_database_url
from apps.api.dy_api.models import Base, DouyinRefundEvent, JobImpact, JobRun, RawDouyinRefundRecord
from apps.worker import refund_replay as replay
from apps.worker.collectors import refunds
from apps.worker.repositories import payload_fingerprint
from tests.test_refund_evidence_replay import apply, evidence, preview, seed, seed_financial


@pytest.fixture()
def pg_engine():
    raw_url = os.getenv("DYDATA_REFUND_REPLAY_TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("set DYDATA_REFUND_REPLAY_TEST_DATABASE_URL to a disposable loopback test database")
    url = make_url(normalize_database_url(raw_url))
    assert url.drivername.startswith("postgresql+")
    assert url.host in {"localhost", "127.0.0.1", "::1"}
    assert url.database and "test" in url.database.lower()
    schema = "refund_replay_test_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-c search_path={schema} -c statement_timeout=5000 -c lock_timeout=1000"})
    try:
        Base.metadata.create_all(engine)
        yield engine
    finally:
        engine.dispose()
        assert re.fullmatch(r"refund_replay_test_[0-9a-f]{32}", schema)
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def test_pg_preview_uses_database_read_only_and_does_not_write(pg_engine, monkeypatch):
    seed(pg_engine)
    inspect = replay._inspect_row

    def check_read_only(session, raw):
        assert session.scalar(text("SHOW transaction_read_only")) == "on"
        assert session.scalar(text("SHOW statement_timeout")) == "3s"
        assert session.scalar(text("SHOW lock_timeout")) == "500ms"
        assert session.scalar(text("SHOW idle_in_transaction_session_timeout")) == "15s"
        return inspect(session, raw)

    monkeypatch.setattr(replay, "_inspect_row", check_read_only)
    result = preview(pg_engine)
    assert result["ready"] == 1 and result["blocked"] == 0
    with Session(pg_engine) as session:
        assert session.scalar(select(func.count(JobRun.job_id))) == 0
        assert session.scalar(select(func.count(DouyinRefundEvent.id))) == 0
    # The guard is enforced by PostgreSQL, independently of Python code paths.
    with pytest.raises(DBAPIError) as caught:
        with replay._transaction(pg_engine, replay.ReplayBounds("source-run", 0, 1, 1), write=False) as (session, _):
            session.execute(text("DELETE FROM raw_douyin_refund_records"))
    assert caught.value.orig.sqlstate == "25006"


def test_pg_apply_commits_once_and_keeps_source_and_success_observation(pg_engine):
    raw_id = seed(pg_engine)
    document = preview(pg_engine)
    result = apply(pg_engine, document)
    assert result["applied"] == result["job_impacts"] == 1
    assert apply(pg_engine, document) == result
    with Session(pg_engine) as session:
        raw = session.get(RawDouyinRefundRecord, raw_id)
        assert raw.raw_payload == evidence() and raw.source_run_id == "source-run"
        assert raw.payload_hash == payload_fingerprint(evidence())
        event = session.scalar(select(DouyinRefundEvent))
        observed_at = event.successful_observed_at
        assert observed_at is not None and event.source_run_id == "repair-run"
        assert session.scalar(select(JobImpact)).source_run_id == "repair-run"
    again = apply(pg_engine, preview(pg_engine), run="repair-again")
    assert again["unchanged"] == 1 and again["applied"] == 0
    with Session(pg_engine) as session:
        assert session.scalar(select(func.count(DouyinRefundEvent.id))) == 1
        assert session.scalar(select(DouyinRefundEvent)).successful_observed_at == observed_at


def test_pg_batch_rolls_back_events_and_impacts_on_collector_failure(pg_engine, monkeypatch):
    seed(pg_engine)
    seed(pg_engine, number=2)
    document = preview(pg_engine)
    process = refunds._process_refund

    def reject_second(session, payload, **kwargs):
        if payload["refund_event_id"] == "refund-2":
            return False
        return process(session, payload, **kwargs)

    monkeypatch.setattr(refunds, "_process_refund", reject_second)
    result = apply(pg_engine, document)
    assert result["applied"] == result["job_impacts"] == 0 and result["blocked"] == 2
    with Session(pg_engine) as session:
        assert session.scalar(select(func.count(DouyinRefundEvent.id))) == 0
        assert session.scalar(select(func.count(JobImpact.id))) == 0
        assert session.get(JobRun, "repair-run").status == "failed"


def test_pg_hash_is_checked_after_row_lock_and_new_financial_projection_blocks(pg_engine):
    raw_id = seed(pg_engine)
    document = preview(pg_engine)
    with Session(pg_engine) as writer:
        raw = writer.scalar(select(RawDouyinRefundRecord).where(RawDouyinRefundRecord.id == raw_id).with_for_update())
        raw.raw_payload = {**raw.raw_payload, "refund_amount_cent": 2000}
        raw.payload_hash = payload_fingerprint(raw.raw_payload)
        writer.commit()
    result = apply(pg_engine, document)
    assert result["reasons"] == {"snapshot_changed_since_preview": 1}
    # Restore a valid accepted current snapshot, then introduce a fee after preview.
    with Session(pg_engine) as writer, writer.begin():
        raw = writer.get(RawDouyinRefundRecord, raw_id)
        raw.refund_amount_cent = 2000
    refreshed = preview(pg_engine)
    assert refreshed["ready"] == 1
    with Session(pg_engine) as writer, writer.begin():
        seed_financial(writer, "result")
    blocked = apply(pg_engine, refreshed, run="repair-with-projection")
    assert "existing_financial_projection_requires_reconciliation" in blocked["reasons"]
    assert blocked["applied"] == 0 and blocked["blocked"] == 1


def test_pg_financial_table_lock_contention_fails_closed_with_timeout(pg_engine):
    seed(pg_engine)
    document = preview(pg_engine)
    with Session(pg_engine) as writer:
        writer.execute(text("LOCK TABLE settlement_fee_result IN ROW EXCLUSIVE MODE"))
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(apply, pg_engine, document)
            with pytest.raises(DBAPIError) as caught:
                future.result(timeout=5)
            assert caught.value.orig.sqlstate == "55P03"
        writer.rollback()
    with Session(pg_engine) as session:
        assert session.scalar(select(func.count(DouyinRefundEvent.id))) == 0
        assert session.scalar(select(func.count(JobRun.job_id))) == 0


def test_pg_raw_row_lock_contention_blocks_without_events(pg_engine):
    raw_id = seed(pg_engine)
    document = preview(pg_engine)
    with Session(pg_engine) as writer:
        writer.scalar(select(RawDouyinRefundRecord).where(RawDouyinRefundRecord.id == raw_id).with_for_update())
        with ThreadPoolExecutor(max_workers=1) as executor:
            result = executor.submit(apply, pg_engine, document).result(timeout=5)
        assert result["applied"] == 0 and result["blocked"] == 1
        assert result["reasons"] == {"transaction_timeout_or_database_error": 1}
        writer.rollback()
    with Session(pg_engine) as session:
        assert session.scalar(select(func.count(DouyinRefundEvent.id))) == 0
        assert session.get(JobRun, "repair-run").status == "failed"


def test_pg_database_statement_timeout_is_bounded(pg_engine):
    bounds = replay.ReplayBounds("source-run", 0, 1, 1, statement_timeout_ms=50, lock_timeout_ms=25)
    with pytest.raises(DBAPIError) as caught:
        with replay._transaction(pg_engine, bounds, write=False) as (session, _):
            session.execute(text("SELECT pg_sleep(1)"))
    assert caught.value.orig.sqlstate == "57014"
