"""Real PostgreSQL locks around rescheduling, due consumption and terminal facts."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.models import (
    Base, ClueAssignmentRound, ClueFollowUpRecord, ClueMasterLead,
    RawDouyinOrder, RawDouyinOrderCoupon,
)
from apps.worker import clue_allocation_engine, clue_follow_up_state
from test_clue_follow_up_postgres import _assert_waiting
from test_dydata115_follow_up import START, next_store, seed_product_task, submit


@pytest.fixture()
def product_postgres_engine():
    url = os.getenv("DYDATA_CLUE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set DYDATA_CLUE_TEST_DATABASE_URL to an isolated local PostgreSQL test database")
    parsed = make_url(url)
    assert parsed.host in {"localhost", "127.0.0.1"} and parsed.database.endswith("_test")
    schema = "followup_115_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-c search_path={schema} -c lock_timeout=5000"})
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            seed_product_task(session)
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def test_reschedule_holding_master_lock_prevents_stale_due_handoff(product_postgres_engine, monkeypatch):
    engine = product_postgres_engine
    factory = sessionmaker(bind=engine, autoflush=False)
    monkeypatch.setattr(clue_allocation_engine, "continue_product_routing", next_store, raising=False)
    now = START + timedelta(days=2)
    with Session(engine) as rescheduler:
        row = rescheduler.get(ClueAssignmentRound, "round-one")
        result = submit(rescheduler, row, "appointment", appointment_at=START + timedelta(days=20), now=now)
        assert result.status == "ok"
        # A due consumer skips the uncommitted owner instead of acting on its
        # stale pre-reschedule deadline or blocking the entire batch.
        with ThreadPoolExecutor(max_workers=1) as executor:
            assert executor.submit(clue_follow_up_state.run_product_follow_up_batch, factory, now=now).result(timeout=5)["processed"] == 0
        rescheduler.commit()
    assert clue_follow_up_state.run_product_follow_up_batch(factory, now=now)["processed"] == 0
    with Session(engine) as check:
        assert check.scalar(select(func.count()).select_from(ClueAssignmentRound)) == 1
        assert check.get(ClueAssignmentRound, "round-one").round_status == "active_followed"


def pause_due(monkeypatch):
    locked, release = Event(), Event()
    original = clue_follow_up_state._process_product_due_round
    def paused(session, lead, row, now):
        locked.set()
        assert release.wait(5), "due transaction was not released"
        return original(session, lead, row, now)
    monkeypatch.setattr(clue_follow_up_state, "_process_product_due_round", paused)
    return locked, release


def test_due_winner_rejects_waiting_reschedule_and_only_one_consumer_allocates(product_postgres_engine, monkeypatch):
    engine = product_postgres_engine
    factory = sessionmaker(bind=engine, autoflush=False)
    monkeypatch.setattr(clue_allocation_engine, "continue_product_routing", next_store, raising=False)
    locked, release = pause_due(monkeypatch)
    ready, pids = Event(), []
    now = START + timedelta(days=2)
    def reschedule():
        with Session(engine, autoflush=False) as session:
            row = session.get(ClueAssignmentRound, "round-one")
            session.get(ClueMasterLead, "lead-one")  # deliberately cache old ownership
            pids.append(session.execute(text("SELECT pg_backend_pid()")).scalar_one())
            ready.set()
            result = submit(session, row, "appointment", appointment_at=START + timedelta(days=20), now=now)
            session.commit()
            return result.status
    with ThreadPoolExecutor(max_workers=2) as executor:
        due = executor.submit(clue_follow_up_state.run_product_follow_up_batch, factory, now=now)
        assert locked.wait(5)
        waiting_submit = executor.submit(reschedule)
        assert ready.wait(5)
        _assert_waiting(engine, pids[0])
        assert clue_follow_up_state.run_product_follow_up_batch(factory, now=now)["processed"] == 0
        release.set()
        assert due.result(timeout=5)["assigned"] == 1
        assert waiting_submit.result(timeout=5) == "conflict"
    assert clue_follow_up_state.run_product_follow_up_batch(factory, now=now)["processed"] == 0
    with Session(engine) as check:
        rows = check.scalars(select(ClueAssignmentRound)).all()
        assert len(rows) == 2
        assert sum(row.round_status in {"active_unfollowed", "active_followed"} for row in rows) == 1
        assert check.scalar(select(func.count()).select_from(ClueFollowUpRecord)) == 0


def test_terminal_committed_after_due_selection_wins_before_continuation(product_postgres_engine, monkeypatch):
    engine = product_postgres_engine
    factory = sessionmaker(bind=engine, autoflush=False)
    monkeypatch.setattr(clue_allocation_engine, "continue_product_routing", lambda *a, **k: pytest.fail("terminal order was reassigned"), raising=False)
    locked, release = pause_due(monkeypatch)
    now = START + timedelta(days=2)
    with ThreadPoolExecutor(max_workers=1) as executor:
        due = executor.submit(clue_follow_up_state.run_product_follow_up_batch, factory, now=now)
        assert locked.wait(5)
        # Source collection commits independently of master/task locks.
        with Session(engine) as source:
            source.add(RawDouyinOrder(order_id="order-one", order_status="201", updated_at=START))
            source.flush()
            source.add(RawDouyinOrderCoupon(order_id="order-one", coupon_id="full-refund",
                coupon_status="301", coupon_status_normalized="refunded",
                latest_refund_at=START + timedelta(hours=2), source_observed_at=START + timedelta(hours=3)))
            source.commit()
        release.set()
        assert due.result(timeout=5)["terminal_closed"] == 1
    with Session(engine) as check:
        assert check.get(ClueMasterLead, "lead-one").normalized_order_status == "refunded"
        row = check.get(ClueAssignmentRound, "round-one")
        assert row.round_status == "closed_order_refunded"
        assert row.closed_at == START + timedelta(hours=2)
        assert check.scalar(select(func.count()).select_from(ClueAssignmentRound)) == 1
