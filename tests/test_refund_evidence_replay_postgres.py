"""Opt-in PostgreSQL replay gates, isolated in a random loopback test schema."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
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
from apps.worker.repositories import HEAVY_SYNC_CLAIM_LOCK_KEY, payload_fingerprint
from test_refund_evidence_replay import apply, evidence, preview, seed, seed_financial


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
        assert session.get(JobRun, "repair-run").metadata_json["needs_downstream_processing"] is True
    with pytest.raises(replay.RefundReplayError, match="source_jobs_or_repairs_not_ready"):
        apply(pg_engine, preview(pg_engine), run="repair-again")
    # Simulate the separate downstream acceptance workflow in this disposable
    # fixture. The replay tool itself must never clear this flag.
    with Session(pg_engine) as session, session.begin():
        job = session.get(JobRun, "repair-run")
        job.metadata_json = {**job.metadata_json, "needs_downstream_processing": False,
                             "downstream_acceptance": "synthetic test receipt"}
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


@pytest.mark.parametrize("status", ["running", "retry_wait"])
def test_pg_running_source_jobs_block_even_with_expired_lease(pg_engine, status):
    seed(pg_engine)
    document = preview(pg_engine)
    with Session(pg_engine) as session, session.begin():
        session.add(JobRun(job_id="existing-source-writer", job_name="collect_once", status=status,
                           lease_expires_at=datetime(2020, 1, 1, tzinfo=timezone.utc)))
    with pytest.raises(replay.RefundReplayError, match="source_jobs_or_repairs_not_ready"):
        apply(pg_engine, document)
    with Session(pg_engine) as session:
        assert session.scalar(select(func.count(DouyinRefundEvent.id))) == 0
        assert session.scalar(select(func.count(JobImpact.id))) == 0
        assert session.get(JobRun, "repair-run") is None
    with Session(pg_engine) as session, session.begin():
        session.get(JobRun, "existing-source-writer").status = "success"
    assert apply(pg_engine, document)["applied"] == 1


def test_pg_claim_mutex_blocks_all_writes_and_release_allows_apply(pg_engine):
    seed(pg_engine)
    document = preview(pg_engine)
    with Session(pg_engine) as claimant:
        assert claimant.scalar(select(func.pg_try_advisory_xact_lock(HEAVY_SYNC_CLAIM_LOCK_KEY)))
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(apply, pg_engine, document)
            with pytest.raises(replay.RefundReplayError, match="heavy_sync_claim_lock_busy"):
                future.result(timeout=5)
        with Session(pg_engine) as session:
            assert session.scalar(select(func.count(DouyinRefundEvent.id))) == 0
            assert session.scalar(select(func.count(JobImpact.id))) == 0
            assert session.get(JobRun, "repair-run") is None
        claimant.rollback()
    assert apply(pg_engine, document)["applied"] == 1


def test_pg_new_source_job_between_batches_preserves_durable_partial_progress(pg_engine, monkeypatch):
    seed(pg_engine)
    seed(pg_engine, number=2)
    document = replay.preview_refunds(pg_engine, replay.ReplayBounds("source-run", 0, 1, 2))
    transaction = replay._transaction
    writes = 0

    @contextmanager
    def new_claim_after_first_batch(engine, bounds, **kwargs):
        nonlocal writes
        with transaction(engine, bounds, **kwargs) as context:
            yield context
        if kwargs.get("write"):
            writes += 1
            if writes == 2:  # Initial audit + first successful batch committed.
                with Session(engine) as claimant, claimant.begin():
                    assert claimant.scalar(select(func.pg_try_advisory_xact_lock(HEAVY_SYNC_CLAIM_LOCK_KEY)))
                    claimant.add(JobRun(job_id="new-source-job", job_name="collect_once", status="running"))

    monkeypatch.setattr(replay, "_transaction", new_claim_after_first_batch)
    result = apply(pg_engine, document)
    assert result["status"] == "partial" and result["audit_finalized"] is False
    assert result["applied"] == result["blocked"] == result["job_impacts"] == 1
    assert result["needs_downstream_processing"] is True
    assert result["rows"][1]["reasons"] == ["source_jobs_or_repairs_not_ready"]
    with Session(pg_engine) as session:
        job = session.get(JobRun, "repair-run")
        assert job.status == "running" and job.metadata_json["progress"]["applied"] == 1
        assert job.metadata_json["needs_downstream_processing"] is True
        assert session.scalar(select(func.count(DouyinRefundEvent.id))) == 1
