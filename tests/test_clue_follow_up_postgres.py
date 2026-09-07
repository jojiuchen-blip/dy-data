"""Opt-in real row-lock tests; each case owns a disposable PostgreSQL schema."""

import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from apps.api.dy_api.models import Base, ClueAssignmentRound, ClueCenterOrder, ClueFollowUpRecord, ClueMasterLead, RawDouyinClue
from apps.worker.clue_follow_up_state import process_due_transitions, soft_delete_follow_up_record
from test_clue_follow_up_atomicity import ADMIN_ACTOR, apply_action, seed_active_round


@pytest.fixture()
def postgres_engine():
    url = os.getenv("DYDATA_CLUE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set DYDATA_CLUE_TEST_DATABASE_URL to a disposable local PostgreSQL database")
    parsed = make_url(url)
    assert parsed.host in {"localhost", "127.0.0.1"} and parsed.database.endswith("_test")
    schema = "clue_test_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-c search_path={schema} -c lock_timeout=5000"})
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            seed_active_round(session)
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def _assert_waiting(engine, pid: int) -> None:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        with engine.connect() as connection:
            waiting = connection.execute(text(
                "SELECT wait_event_type FROM pg_stat_activity WHERE pid=:pid"
            ), {"pid": pid}).scalar()
        if waiting == "Lock":
            return
        time.sleep(0.02)
    pytest.fail("competing transaction never waited on a PostgreSQL row lock")


@pytest.mark.parametrize("closure", ["lost", "request_store_change", "due"])
def test_follow_up_waits_and_rechecks_committed_closure(postgres_engine, closure):
    ready = Event()
    pids = []

    def follow():
        with Session(postgres_engine) as session:
            held = [session.get(ClueMasterLead, "audit-lead"), session.get(ClueAssignmentRound, "audit-round")]
            assert all(held)
            pids.append(session.execute(text("SELECT pg_backend_pid()")).scalar_one())
            ready.set()
            result = apply_action(session, "appointment")
            session.commit()
            return result.status

    with ThreadPoolExecutor(max_workers=1) as executor, Session(postgres_engine) as closer:
        closer.execute(select(ClueMasterLead).where(ClueMasterLead.lead_key == "audit-lead").with_for_update())
        future = executor.submit(follow)
        assert ready.wait(3)
        _assert_waiting(postgres_engine, pids[0])
        if closure == "due":
            assert process_due_transitions(closer, now=datetime(2026, 9, 3, tzinfo=timezone.utc))["sla_expired"] == 1
        else:
            assert apply_action(closer, closure).status == "ok"
        closer.commit()
        assert future.result(timeout=5) == "conflict"
    with Session(postgres_engine) as verify:
        assert verify.get(ClueMasterLead, "audit-lead").current_assignment_round_id is None
        assert verify.get(ClueAssignmentRound, "audit-round").round_status == "closed_reassigned"
        assert len(verify.scalars(select(ClueFollowUpRecord)).all()) == (0 if closure == "due" else 1)


def test_concurrent_delete_rechecks_record_after_lock(postgres_engine):
    with Session(postgres_engine) as setup:
        record_id = apply_action(setup, "appointment").record.follow_up_record_id
        setup.commit()
    ready = Event()
    pids = []

    def delete_again():
        with Session(postgres_engine) as session:
            held = session.get(ClueFollowUpRecord, record_id)
            assert held.deleted_at is None
            pids.append(session.execute(text("SELECT pg_backend_pid()")).scalar_one())
            ready.set()
            result = soft_delete_follow_up_record(session, follow_up_record_id=record_id, actor=ADMIN_ACTOR, reason="second")
            session.commit()
            return result.status

    with ThreadPoolExecutor(max_workers=1) as executor, Session(postgres_engine) as first:
        first.execute(select(ClueMasterLead).where(ClueMasterLead.lead_key == "audit-lead").with_for_update())
        future = executor.submit(delete_again)
        assert ready.wait(3)
        _assert_waiting(postgres_engine, pids[0])
        assert soft_delete_follow_up_record(first, follow_up_record_id=record_id, actor=ADMIN_ACTOR, reason="first").status == "ok"
        first.commit()
        assert future.result(timeout=5) == "conflict"
    with Session(postgres_engine) as verify:
        assert verify.get(ClueFollowUpRecord, record_id).deletion_reason == "first"


@pytest.mark.parametrize("writer", ["projection", "materialization", "allocation"])
@pytest.mark.parametrize("dirty_round", [False, True])
def test_worker_writer_waits_for_follow_up_transaction(postgres_engine, writer, dirty_round):
    from apps.worker.clue_allocation import materialize_clue_master_leads
    from apps.worker.clue_allocation_engine import allocate_lead
    from apps.worker.clue_center import refresh_clue_center_projection

    ready = Event()
    pids = []

    def run_writer():
        with Session(postgres_engine, autoflush=False) as session:
            held = [session.get(ClueMasterLead, "audit-lead"), session.get(ClueAssignmentRound, "audit-round"),
                    session.get(ClueCenterOrder, "audit-order")]
            raw = session.get(RawDouyinClue, "audit-raw")
            assert all(held) and raw is not None
            if dirty_round:
                held[1].round_status = "active_followed"
            pids.append(session.execute(text("SELECT pg_backend_pid()")).scalar_one())
            ready.set()
            if writer == "projection":
                result = refresh_clue_center_projection(session, order_ids={"audit-order"})
            elif writer == "materialization":
                result = materialize_clue_master_leads(session, raw_clues=[raw])
            else:
                result = allocate_lead(session, "audit-lead")
                assert result.reason == "lead_not_active"
            session.commit()
            return result

    with ThreadPoolExecutor(max_workers=1) as executor, Session(postgres_engine) as closer:
        lead = closer.scalar(select(ClueMasterLead).where(ClueMasterLead.lead_key == "audit-lead").with_for_update())
        future = executor.submit(run_writer)
        assert ready.wait(3)
        _assert_waiting(postgres_engine, pids[0])
        assert apply_action(closer, "lost").status == "ok"
        if writer == "allocation":
            lead.lifecycle_status = "closed_refunded"
            lead.normalized_order_status = "refunded"
        closer.commit()
        future.result(timeout=10)
    with Session(postgres_engine) as verify:
        assert verify.get(ClueAssignmentRound, "audit-round").round_status == "closed_reassigned"
        assert verify.get(ClueMasterLead, "audit-lead").current_assignment_round_id is None
        assert verify.get(ClueCenterOrder, "audit-order").current_round_status not in {"active_followed", "active_unfollowed"}
