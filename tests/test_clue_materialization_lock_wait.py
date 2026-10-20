"""Bounded-wait regression for the clue master materialization advisory lock.

Production failed six daily plans because one transaction-scoped advisory lock
was busy: the code used a non-blocking ``pg_try_advisory_xact_lock`` and treated
"busy" as a terminal failure.  These tests pin the required semantics instead:

* a holder that releases inside the wait window lets the page proceed;
* a lock that stays busy past the deadline still fails closed, leaving the work
  item pending;
* a page lease that is taken over while the process waits must not be renewed or
  advanced;
* on a disposable PostgreSQL database the real transaction lock is honoured, the
  wait path never issues a blocking advisory lock, and a concurrent holder inside
  the wait window no longer kills the page.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.models import (
    Base,
    ClueMasterLead,
    ClueMaterializationWorkItem,
    JobImpact,
)
from apps.worker import clue_allocation
from apps.worker.clue_allocation import (
    MASTER_MATERIALIZATION_LOCK,
    _advisory_lock_key,
    _wait_for_materialization_lock,
    run_incremental_clue_materialization,
    wait_for_clue_master_materialization_lock,
)
from tests.test_clue_allocation_incremental import _clue, _dt, _factory, _store

POSTGRES_URL = os.getenv("DYDATA_CLUE_TEST_DATABASE_URL")


def _seed_pending_page(session: Session) -> None:
    store, mapping = _store("store-a", "poi-a")
    session.add_all([store, mapping, _clue("raw-1", "clue-1", "order-a", "poi-a")])
    session.commit()
    impact = JobImpact(
        impact_key="lock-wait-page",
        entity_type="clue",
        entity_key="raw-1",
        change_kind="update",
        affected_closure_json={
            "clue_ids": ["clue-1"],
            "order_ids": ["order-a"],
            "poi_ids": ["poi-a"],
        },
    )
    session.add(impact)
    session.commit()
    session.add(
        ClueMaterializationWorkItem(
            scope="clue_materialization",
            impact_id=impact.id,
            entity_type="clue",
            entity_key="raw-1",
        )
    )
    session.commit()


def _locked_result() -> dict[str, object]:
    return {
        "master_leads": 0,
        "closed_leads": 0,
        "headquarters_pool": 0,
        "skipped": "locked",
    }


def _busy_once_stub(original, busy_calls: list[int]):
    """Busy for the first probe, then delegate to the real advisory-lock probe."""

    def probe(session: Session, *, lock_name: str) -> bool:
        if lock_name == MASTER_MATERIALIZATION_LOCK and not busy_calls:
            busy_calls.append(1)
            return False
        return original(session, lock_name=lock_name)

    return probe


def test_lock_busy_then_free_inside_the_wait_window_lets_the_page_proceed(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact production failure must become a retry, not a dead day plan."""
    _seed_pending_page(db_session)
    original_try = clue_allocation._try_transaction_lock
    busy_calls: list[int] = []
    sleeps: list[float] = []
    monkeypatch.setattr(
        clue_allocation,
        "_try_transaction_lock",
        _busy_once_stub(original_try, busy_calls),
    )
    monkeypatch.setenv("DY_CLUE_MATERIALIZATION_LOCK_WAIT_SECONDS", "5")
    monkeypatch.setenv("DY_CLUE_MATERIALIZATION_LOCK_BACKOFF_SECONDS", "0.05")
    monkeypatch.setattr(clue_allocation, "sleep", lambda seconds: sleeps.append(seconds))

    result = run_incremental_clue_materialization(
        _factory(db_session),
        batch_size=1,
        raw_batch_size=1,
        lease_token="attempt-wait-success",
        now=_dt(4),
    )

    assert busy_calls == [1], "the busy lock must be observed"
    assert sleeps == [0.05], "the wait must sleep once before retrying"
    assert result["raw_rows"] >= 1
    db_session.expire_all()
    assert db_session.scalar(select(func.count()).select_from(ClueMasterLead)) == 1
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(ClueMaterializationWorkItem)
            .where(ClueMaterializationWorkItem.state != "pending")
        )
        == 1
    )


def test_lock_busy_past_the_deadline_fails_closed_and_leaves_work_pending(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_pending_page(db_session)
    sleeps: list[float] = []

    def always_busy(session: Session, *, lock_name: str) -> bool:
        _ = session
        return lock_name != MASTER_MATERIALIZATION_LOCK

    monkeypatch.setattr(clue_allocation, "_try_transaction_lock", always_busy)
    monkeypatch.setenv("DY_CLUE_MATERIALIZATION_LOCK_WAIT_SECONDS", "0.2")
    monkeypatch.setenv("DY_CLUE_MATERIALIZATION_LOCK_BACKOFF_SECONDS", "0.05")
    monkeypatch.setattr(clue_allocation, "sleep", lambda seconds: sleeps.append(seconds))

    with pytest.raises(RuntimeError, match="lock unavailable"):
        run_incremental_clue_materialization(
            _factory(db_session),
            batch_size=1,
            raw_batch_size=1,
            lease_token="attempt-wait-exhausted",
            now=_dt(4),
        )

    assert sleeps, "exhausting the bounded wait must be observable"
    db_session.expire_all()
    pending = db_session.scalar(
        select(func.count())
        .select_from(ClueMaterializationWorkItem)
        .where(ClueMaterializationWorkItem.state == "pending")
    )
    assert pending == 1, "a failed lock wait must leave the work item pending"
    assert not db_session.scalars(select(ClueMasterLead)).all()


def test_zero_wait_budget_keeps_the_old_fail_closed_behaviour(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_pending_page(db_session)
    sleeps: list[float] = []

    def always_busy(session: Session, *, lock_name: str) -> bool:
        _ = session
        return lock_name != MASTER_MATERIALIZATION_LOCK

    monkeypatch.setattr(clue_allocation, "_try_transaction_lock", always_busy)
    monkeypatch.setenv("DY_CLUE_MATERIALIZATION_LOCK_WAIT_SECONDS", "0")
    monkeypatch.setattr(clue_allocation, "sleep", lambda seconds: sleeps.append(seconds))

    with pytest.raises(RuntimeError, match="lock unavailable"):
        run_incremental_clue_materialization(
            _factory(db_session),
            batch_size=1,
            raw_batch_size=1,
            lease_token="attempt-no-wait",
            now=_dt(4),
        )
    assert sleeps == [], "a zero budget must not sleep at all"


def test_backoff_floor_prevents_tight_polling(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DY_CLUE_MATERIALIZATION_LOCK_BACKOFF_SECONDS", "0")
    sleeps: list[float] = []

    def always_busy(session: Session, *, lock_name: str) -> bool:
        _ = session
        return lock_name != MASTER_MATERIALIZATION_LOCK

    monkeypatch.setattr(clue_allocation, "_try_transaction_lock", always_busy)
    monkeypatch.setattr(clue_allocation, "sleep", lambda seconds: sleeps.append(seconds))

    assert (
        _wait_for_materialization_lock(
            db_session, lock_name=MASTER_MATERIALIZATION_LOCK, timeout=0.15
        )
        is False
    )
    # A configured 0 must be clamped up to the floor, and each sleep stays a
    # single bounded interval (the last one may be shortened by the deadline).
    assert sleeps and sleeps[0] == clue_allocation.MATERIALIZATION_LOCK_BACKOFF_MIN_SECONDS
    assert max(sleeps) <= clue_allocation.MATERIALIZATION_LOCK_BACKOFF_MAX_SECONDS
    assert (
        clue_allocation._env_float(
            "DY_CLUE_MATERIALIZATION_LOCK_BACKOFF_SECONDS",
            clue_allocation.MATERIALIZATION_LOCK_BACKOFF_SECONDS_DEFAULT,
            minimum=clue_allocation.MATERIALIZATION_LOCK_BACKOFF_MIN_SECONDS,
            maximum=clue_allocation.MATERIALIZATION_LOCK_BACKOFF_MAX_SECONDS,
        )
        == clue_allocation.MATERIALIZATION_LOCK_BACKOFF_MIN_SECONDS
    )


def test_page_lease_taken_over_while_waiting_does_not_renew_or_advance(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_pending_page(db_session)
    original_try = clue_allocation._try_transaction_lock
    busy_calls: list[int] = []
    state = {"stolen": False}
    taken_over: list[str] = []

    def busy_once(session: Session, *, lock_name: str) -> bool:
        if lock_name == MASTER_MATERIALIZATION_LOCK and not busy_calls:
            busy_calls.append(1)
            return False
        return original_try(session, lock_name=lock_name)

    def steal_lease(_seconds: float) -> None:
        # Another worker reclaims the page lease while this process waits.
        state["stolen"] = True
        with _factory(db_session)() as competitor:
            item = competitor.scalars(select(ClueMaterializationWorkItem)).one()
            taken_over.append(str(item.lease_owner))
            item.lease_owner = "competitor-token"
            competitor.commit()

    monkeypatch.setattr(clue_allocation, "_try_transaction_lock", busy_once)
    monkeypatch.setattr(
        clue_allocation,
        "materialize_clue_master_leads",
        lambda *args, **kwargs: {
            "master_leads": 1,
            "closed_leads": 0,
            "headquarters_pool": 0,
        },
    )
    monkeypatch.setenv("DY_CLUE_MATERIALIZATION_LOCK_WAIT_SECONDS", "5")
    monkeypatch.setenv("DY_CLUE_MATERIALIZATION_LOCK_BACKOFF_SECONDS", "0.05")
    monkeypatch.setattr(clue_allocation, "sleep", steal_lease)

    with pytest.raises(RuntimeError, match="lease"):
        run_incremental_clue_materialization(
            _factory(db_session),
            batch_size=1,
            raw_batch_size=1,
            lease_token="attempt-lease-stolen",
            now=_dt(4),
        )

    assert state["stolen"] is True
    assert taken_over == ["attempt-lease-stolen"]
    db_session.expire_all()
    item = db_session.scalars(select(ClueMaterializationWorkItem)).one()
    assert item.lease_owner == "competitor-token"
    assert item.raw_cursor is None and item.center_cursor is None
    assert not db_session.scalars(select(ClueMasterLead)).all()


def test_shared_wait_helper_is_a_noop_on_sqlite(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-PostgreSQL bindings have no advisory lock and must not sleep."""
    sleeps: list[float] = []
    monkeypatch.setattr(clue_allocation, "sleep", lambda seconds: sleeps.append(seconds))
    assert wait_for_clue_master_materialization_lock(db_session) is True
    assert sleeps == []


@pytest.mark.skipif(
    not POSTGRES_URL,
    reason="set DYDATA_CLUE_TEST_DATABASE_URL to a disposable local PostgreSQL database",
)
def test_wait_helper_honours_the_real_postgresql_transaction_lock() -> None:
    assert POSTGRES_URL is not None
    parsed = make_url(POSTGRES_URL)
    assert parsed.host in {"localhost", "127.0.0.1"}
    assert parsed.database and parsed.database.endswith("_test")
    schema = "clue_lock_wait_test_" + uuid4().hex
    admin = create_engine(POSTGRES_URL)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        POSTGRES_URL, connect_args={"options": f"-c search_path={schema}"}
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    key = _advisory_lock_key(MASTER_MATERIALIZATION_LOCK)
    try:
        Base.metadata.create_all(engine)
        holder = factory()
        holder.begin()
        assert holder.scalar(select(func.pg_try_advisory_xact_lock(key)))
        try:
            waiter = factory()
            waiter.begin()
            try:
                assert (
                    _wait_for_materialization_lock(
                        waiter,
                        lock_name=MASTER_MATERIALIZATION_LOCK,
                        timeout=0.2,
                    )
                    is False
                )
            finally:
                waiter.rollback()
                waiter.close()
        finally:
            holder.commit()
            holder.close()

        after = factory()
        after.begin()
        try:
            assert (
                _wait_for_materialization_lock(
                    after,
                    lock_name=MASTER_MATERIALIZATION_LOCK,
                    timeout=0.2,
                )
                is True
            )
        finally:
            after.rollback()
            after.close()
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.mark.skipif(
    not POSTGRES_URL,
    reason="set DYDATA_CLUE_TEST_DATABASE_URL to a disposable local PostgreSQL database",
)
def test_wait_helper_never_issues_a_blocking_advisory_lock() -> None:
    assert POSTGRES_URL is not None
    parsed = make_url(POSTGRES_URL)
    assert parsed.host in {"localhost", "127.0.0.1"}
    schema = "clue_lock_sql_test_" + uuid4().hex
    admin = create_engine(POSTGRES_URL)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        POSTGRES_URL, connect_args={"options": f"-c search_path={schema}"}
    )
    statements: list[str] = []

    def collect(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", collect)
    try:
        with Session(engine) as session:
            session.begin()
            assert _wait_for_materialization_lock(
                session, lock_name=MASTER_MATERIALIZATION_LOCK, timeout=0.05
            )
            session.rollback()
    finally:
        event.remove(engine, "before_cursor_execute", collect)
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()

    issued = " ".join(statements).lower()
    assert "pg_try_advisory_xact_lock" in issued
    assert "pg_advisory_lock(" not in issued
    assert "pg_advisory_unlock" not in issued


@pytest.mark.skipif(
    not POSTGRES_URL,
    reason="set DYDATA_CLUE_TEST_DATABASE_URL to a disposable local PostgreSQL database",
)
def test_incremental_page_waits_for_a_concurrent_holder_then_completes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: a concurrent holder inside the wait window no longer kills the page."""
    assert POSTGRES_URL is not None
    parsed = make_url(POSTGRES_URL)
    assert parsed.host in {"localhost", "127.0.0.1"}
    schema = "clue_lock_page_test_" + uuid4().hex
    admin = create_engine(POSTGRES_URL)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        POSTGRES_URL, connect_args={"options": f"-c search_path={schema}"}
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    key = _advisory_lock_key(MASTER_MATERIALIZATION_LOCK)
    try:
        Base.metadata.create_all(engine)
        with factory() as seed:
            _seed_pending_page(seed)

        holder = factory()
        holder.begin()
        assert holder.scalar(select(func.pg_try_advisory_xact_lock(key)))
        released = {"done": False}
        observed_sleeps: list[float] = []

        def release_holder(seconds: float) -> None:
            observed_sleeps.append(seconds)
            if not released["done"]:
                released["done"] = True
                holder.commit()

        monkeypatch.setenv("DY_CLUE_MATERIALIZATION_LOCK_WAIT_SECONDS", "10")
        monkeypatch.setenv("DY_CLUE_MATERIALIZATION_LOCK_BACKOFF_SECONDS", "0.02")
        monkeypatch.setattr(clue_allocation, "sleep", release_holder)

        try:
            result = run_incremental_clue_materialization(
                factory,
                batch_size=1,
                raw_batch_size=1,
                lease_token="attempt-real-lock",
                now=datetime(2026, 7, 4, 9, tzinfo=timezone.utc),
            )
        finally:
            if not released["done"]:
                holder.commit()
            holder.close()

        assert observed_sleeps, "the concurrent holder must have been waited on"
        assert result["raw_rows"] >= 1
        with factory() as check:
            assert check.scalar(select(func.count()).select_from(ClueMasterLead)) == 1
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
