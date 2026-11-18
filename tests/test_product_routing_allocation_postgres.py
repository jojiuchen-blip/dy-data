"""Disposable PostgreSQL proof of real product-routing lock and retry behavior."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import os
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from apps.api.dy_api.models import (
    Base, ClueAssignmentRound, ClueHeadquartersPoolEntry, ClueMasterLead,
    RawDouyinOrder,
)
from apps.worker import clue_allocation_engine as engine
from apps.worker.clue_allocation import lock_clue_master_for_update
from test_product_routing_allocation import NOW, _expire, _flow


@pytest.fixture
def product_factory(monkeypatch):
    url = os.getenv("DYDATA_CLUE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("requires disposable local PostgreSQL")
    parsed = make_url(url)
    assert parsed.host in {"127.0.0.1", "localhost"} and parsed.database.endswith("_test")
    schema = "product_routing_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    db = create_engine(url, connect_args={"options": f"-c search_path={schema} -c lock_timeout=5000"})
    try:
        Base.metadata.create_all(db)
        factory = sessionmaker(bind=db, expire_on_commit=False)
        state = {"published": True, "stores": {"near", "far"}}
        monkeypatch.setattr(engine, "has_published_product_store_list", lambda *_: state["published"])
        monkeypatch.setattr(engine, "load_product_store_ids", lambda *_: set(state["stores"]))
        with factory() as session:
            _flow(session)
            session.commit()
        yield factory, state
    finally:
        db.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def test_competing_handoffs_serialize_and_create_only_one_next_task(product_factory):
    factory, _state = product_factory
    with factory() as session:
        first = engine.allocate_lead(session, "lead-1", now=NOW)
        session.commit()
    locked, release, second_started = Event(), Event(), Event()
    due_at = NOW + timedelta(days=1)

    def first_worker():
        with factory() as session:
            lead = lock_clue_master_for_update(session, "lead-1")
            _expire(session, lead, due_at)
            locked.set()
            assert release.wait(10)
            result = engine.continue_product_routing(session, "lead-1", now=due_at, transition_key="due:first")
            session.commit()
            return result

    def second_worker():
        second_started.set()
        with factory() as session:
            result = engine.continue_product_routing(session, "lead-1", now=due_at, transition_key="due:first")
            session.commit()
            return result

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(first_worker)
        assert locked.wait(10)
        second_future = executor.submit(second_worker)
        assert second_started.wait(10)
        try:
            with pytest.raises(TimeoutError):
                second_future.result(timeout=0.2)
        finally:
            release.set()
        next_result, replay = first_future.result(timeout=10), second_future.result(timeout=10)
    assert next_result.assignment_round_id == replay.assignment_round_id
    assert next_result.assignment_round_id != first.assignment_round_id
    with factory() as session:
        rows = list(session.scalars(select(ClueAssignmentRound).order_by(ClueAssignmentRound.round_no)))
        assert [row.round_no for row in rows] == [1, 2]
        assert rows[0].closed_at == due_at
        assert rows[0].round_status == "closed_follow_up_expired"
        assert rows[1].round_status == "active_unfollowed"
        assert rows[0].assigned_store_id != rows[1].assigned_store_id


def test_failed_handoff_rolls_back_old_close_and_next_retry_succeeds(product_factory):
    factory, _state = product_factory
    with factory() as session:
        original = engine.allocate_lead(session, "lead-1", now=NOW)
        session.commit()
    due_at = NOW + timedelta(days=1)
    with pytest.raises(RuntimeError, match="simulated transaction failure"):
        with factory() as session:
            lead = lock_clue_master_for_update(session, "lead-1")
            _expire(session, lead, due_at)
            assert engine.continue_product_routing(session, "lead-1", now=due_at, transition_key="retry").status == "assigned"
            raise RuntimeError("simulated transaction failure")
    with factory() as session:
        lead = session.get(ClueMasterLead, "lead-1")
        assert lead.current_assignment_round_id == original.assignment_round_id
        assert session.query(ClueAssignmentRound).count() == 1
        assert session.get(ClueAssignmentRound, original.assignment_round_id).round_status == "active_unfollowed"
        lead = lock_clue_master_for_update(session, "lead-1")
        _expire(session, lead, due_at)
        result = engine.continue_product_routing(session, "lead-1", now=due_at, transition_key="retry")
        session.commit()
    with factory() as session:
        assert session.query(ClueAssignmentRound).count() == 2
        assert session.get(ClueMasterLead, "lead-1").current_assignment_round_id == result.assignment_round_id


def test_waiting_headquarters_resume_sees_refund_committed_before_lock_release(product_factory):
    factory, state = product_factory
    state["published"] = False
    with factory() as session:
        assert engine.allocate_lead(session, "lead-1", now=NOW).status == "headquarters"
        entry_id = session.query(ClueHeadquartersPoolEntry).filter_by(status="active").one().headquarters_pool_entry_id
        session.commit()
    state["published"] = True
    locked, release, resume_started = Event(), Event(), Event()

    def blocker():
        with factory() as session:
            lock_clue_master_for_update(session, "lead-1")
            locked.set()
            assert release.wait(10)
            session.commit()

    def resume():
        resume_started.set()
        with factory() as session:
            result = engine.resume_product_routing(session, "lead-1", now=NOW + timedelta(hours=1),
                actor="hq-operator", expected_entry_id=entry_id)
            session.commit()
            return result

    with ThreadPoolExecutor(max_workers=2) as executor:
        blocker_future = executor.submit(blocker)
        assert locked.wait(10)
        resume_future = executor.submit(resume)
        assert resume_started.wait(10)
        try:
            with pytest.raises(TimeoutError):
                resume_future.result(timeout=0.2)
            with factory() as session:
                session.add(RawDouyinOrder(order_id="order-1", order_status="已退款",
                    source_observed_at=NOW + timedelta(minutes=30), raw_payload={}))
                session.commit()
        finally:
            release.set()
        blocker_future.result(timeout=10)
        assert resume_future.result(timeout=10).status == "skipped"
    with factory() as session:
        assert session.get(ClueMasterLead, "lead-1").normalized_order_status == "refunded"
        assert session.query(ClueAssignmentRound).count() == 0
        assert session.query(ClueHeadquartersPoolEntry).filter_by(status="active").count() == 0
