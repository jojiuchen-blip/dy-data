from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine, inspect as sa_inspect, select
from sqlalchemy.orm import sessionmaker

from apps.api.dy_api.models import (
    Base,
    ClueAssignmentRound,
    ClueCenterOrder,
    ClueMasterLead,
    RawDouyinClue,
    RawDouyinOrder,
)
from apps.worker.clue_allocation import (
    lock_clue_master_for_update,
    materialize_clue_master_leads,
)
from apps.worker.clue_allocation_engine import allocate_lead
from apps.worker.clue_follow_up_state import apply_follow_up_action
from apps.worker.clue_state_locking import refresh_dirty_rounds_for_locked_leads


def _now() -> datetime:
    return datetime(2026, 8, 24, 8, tzinfo=timezone.utc)


def _factory(tmp_path, *, autoflush: bool = False):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'allocation-locks.sqlite'}",
        connect_args={"timeout": 30},
        future=True,
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=autoflush, expire_on_commit=False, future=True)


def _master(*, current_round_id: str | None = None) -> ClueMasterLead:
    return ClueMasterLead(
        lead_key="lead-locks",
        source_clue_row_key="clue-row-locks",
        source_identity_key="identity-locks",
        canonical_clue_id="clue-locks",
        order_id="order-locks",
        raw_order_status="active",
        normalized_order_status="active",
        status_source="test",
        lifecycle_status="active",
        pool_location="store_follow_up_pool" if current_round_id else None,
        allocation_state="assigned" if current_round_id else "pending_allocation",
        current_assignment_round_id=current_round_id,
        created_at=_now(),
        updated_at=_now(),
    )


def _round(
    round_id: str,
    *,
    lead_key: str = "lead-locks",
    round_no: int = 1,
) -> ClueAssignmentRound:
    return ClueAssignmentRound(
        assignment_round_id=round_id,
        order_id="order-locks",
        lead_key=lead_key,
        round_no=round_no,
        assigned_at=_now(),
        assigned_store_id="store-1",
        assigned_store_name="测试门店",
        round_status="active_unfollowed",
        execution_mode="formal",
    )


_STORE_ACTOR = {
    "role": "store",
    "store_scope_mode": "specified",
    "store_ids": ("store-1",),
}


def _seed_follow_up_round(session) -> None:
    session.add_all(
        [
            RawDouyinOrder(
                order_id="order-locks",
                order_status="201",
                order_status_raw="201",
                order_status_normalized="paid",
                raw_payload={},
            ),
            RawDouyinClue(
                clue_row_key="clue-row-locks",
                clue_id="clue-locks",
                order_id="order-locks",
                order_status="201",
                create_time_detail=_now(),
                fetched_at=_now(),
                imported_at=_now(),
                updated_at=_now(),
                raw_payload={},
            ),
            _master(current_round_id="round-a"),
            _round("round-a"),
            ClueCenterOrder(
                order_id="order-locks",
                lead_status="active",
                current_assignment_round_id="round-a",
                current_round_status="active_unfollowed",
                assigned_store_id="store-1",
            ),
        ]
    )
    session.commit()


def _apply_lost(session) -> None:
    result = apply_follow_up_action(
        session,
        order_id="order-locks",
        assignment_round_id="round-a",
        follow_result="lost",
        actor=_STORE_ACTOR,
        now=_now(),
    )
    assert result.status == "ok"


def test_materialization_refreshes_stale_master_before_terminal_closure(tmp_path) -> None:
    factory = _factory(tmp_path, autoflush=True)
    seed = factory()
    seed.add_all(
        [
            RawDouyinOrder(
                order_id="order-locks",
                order_status="active",
                order_status_raw="active",
                order_status_normalized="active",
                raw_payload={},
            ),
            RawDouyinClue(
                clue_row_key="clue-row-locks",
                clue_id="clue-locks",
                order_id="order-locks",
                order_status="active",
                create_time_detail=_now(),
                fetched_at=_now(),
                imported_at=_now(),
                updated_at=_now(),
                raw_payload={},
            ),
            _master(current_round_id="round-a"),
            _round("round-a"),
            ClueCenterOrder(
                order_id="order-locks",
                lead_status="active",
                current_assignment_round_id="round-a",
                current_round_status="active_unfollowed",
            ),
        ]
    )
    seed.commit()
    seed.close()

    stale = factory()
    stale_master = stale.get(ClueMasterLead, "lead-locks")
    assert stale_master is not None
    # Leave a stale local edit pending.  The materializer must not autoflush it
    # before its master lock refreshes the writer's newer current-round pointer.
    stale_master.pool_location = "headquarters_pool"
    stale_clue = stale.get(RawDouyinClue, "clue-row-locks")
    assert stale_clue is not None
    # SQLite's rollback journal cannot let a read transaction and the writer
    # commit overlap.  Keep the stale dirty identity, but release that read
    # transaction before the writer advances the pointer.
    stale.expunge_all()
    stale.close()

    writer = factory()
    writer_master = writer.get(ClueMasterLead, "lead-locks")
    writer_center = writer.get(ClueCenterOrder, "order-locks")
    writer_order = writer.scalar(
        select(RawDouyinOrder).where(RawDouyinOrder.order_id == "order-locks")
    )
    assert writer_master is not None and writer_center is not None and writer_order is not None
    writer.add(_round("round-b", round_no=2))
    writer_master.current_assignment_round_id = "round-b"
    writer_master.pool_location = "store_follow_up_pool"
    writer_master.allocation_state = "assigned"
    writer_center.current_assignment_round_id = "round-b"
    writer_order.order_status = "refunded"
    writer_order.order_status_raw = "refunded"
    writer_order.order_status_normalized = "refunded"
    writer.commit()
    writer.close()

    stale = factory()
    stale.add(stale_master)
    materialize_clue_master_leads(stale, raw_clues=[stale_clue], now=_now())
    stale.commit()
    stale.close()

    verify = factory()
    refreshed_master = verify.get(ClueMasterLead, "lead-locks")
    round_a = verify.get(ClueAssignmentRound, "round-a")
    round_b = verify.get(ClueAssignmentRound, "round-b")
    refreshed_center = verify.get(ClueCenterOrder, "order-locks")
    assert refreshed_master is not None
    assert round_a is not None and round_b is not None and refreshed_center is not None
    assert refreshed_master.current_assignment_round_id == "round-b"
    assert round_a.round_status == "active_unfollowed"
    assert round_b.round_status == "closed_order_refunded"
    assert refreshed_center.current_assignment_round_id == "round-b"
    assert refreshed_center.current_round_status == "closed_order_refunded"


def test_allocate_lead_refreshes_stale_master_before_creating_round(tmp_path) -> None:
    factory = _factory(tmp_path, autoflush=True)
    seed = factory()
    seed.add(_master())
    seed.commit()
    seed.close()

    stale = factory()
    stale_master = stale.get(ClueMasterLead, "lead-locks")
    assert stale_master is not None
    stale_master.pool_location = "headquarters_pool"

    writer = factory()
    writer_master = writer.get(ClueMasterLead, "lead-locks")
    assert writer_master is not None
    writer.add(_round("round-b"))
    writer_master.current_assignment_round_id = "round-b"
    writer_master.pool_location = "store_follow_up_pool"
    writer_master.allocation_state = "assigned"
    writer.commit()
    writer.close()

    result = allocate_lead(stale, "lead-locks", execution_mode="formal", now=_now())
    assert result.status == "assigned"
    assert result.assignment_round_id == "round-b"
    assert result.reason == "current_self_owned_round_exists"
    assert stale.scalar(select(ClueAssignmentRound.assignment_round_id)) == "round-b"
    stale.close()


def test_full_materialization_reuses_one_locked_master_for_multiple_raw_rows(tmp_path) -> None:
    factory = _factory(tmp_path, autoflush=True)
    session = factory()
    first_seen = _now()
    later_seen = first_seen.replace(hour=10)
    session.add_all(
        [
            RawDouyinOrder(
                order_id="order-locks",
                order_status="active",
                order_status_raw="active",
                order_status_normalized="active",
                raw_payload={},
            ),
            RawDouyinClue(
                clue_row_key="clue-row-a",
                clue_id="clue-a",
                order_id="order-locks",
                telephone="13800000000",
                order_status="active",
                create_time_detail=first_seen,
                fetched_at=first_seen,
                imported_at=first_seen,
                updated_at=first_seen,
                raw_payload={},
            ),
            RawDouyinClue(
                clue_row_key="clue-row-b",
                clue_id="clue-b",
                order_id="order-locks",
                telephone="13800000000",
                order_status="active",
                create_time_detail=later_seen,
                fetched_at=later_seen,
                imported_at=later_seen,
                updated_at=later_seen,
                raw_payload={},
            ),
            ClueMasterLead(
                lead_key="lead-locks",
                source_clue_row_key="clue-row-a",
                source_identity_key="identity-old",
                order_id="order-locks",
                raw_order_status="active",
                normalized_order_status="active",
                status_source="test",
                lifecycle_status="active",
                allocation_state="pending_allocation",
                created_at=first_seen,
                first_seen_at=None,
            ),
        ]
    )
    session.commit()
    stale_master = session.get(ClueMasterLead, "lead-locks")
    assert stale_master is not None
    stale_master.first_seen_at = later_seen

    result = materialize_clue_master_leads(session, now=later_seen)
    session.commit()
    refreshed = session.get(ClueMasterLead, "lead-locks")
    assert result["master_leads"] == 1
    assert refreshed is not None
    assert refreshed.first_seen_at.replace(tzinfo=timezone.utc) == first_seen
    session.close()


def test_terminal_sync_skips_master_reactivated_while_waiting_for_lock(tmp_path, monkeypatch):
    from apps.worker import clue_allocation as allocation

    factory = _factory(tmp_path)
    with factory() as seed:
        lead = _master(current_round_id="round-a")
        lead.lifecycle_status = "status_review"
        seed.add_all([lead, _round("round-a"), ClueCenterOrder(
            order_id="order-locks", lead_status="active", current_assignment_round_id="round-a",
            current_round_status="active_unfollowed",
        )])
        seed.commit()
    original_lock = allocation.lock_clue_masters_for_update

    def restore_then_lock(session, keys):
        keys = list(keys)
        with factory() as writer:
            writer.get(ClueMasterLead, "lead-locks").lifecycle_status = "active"
            writer.commit()
        return original_lock(session, keys)

    monkeypatch.setattr(allocation, "lock_clue_masters_for_update", restore_then_lock)
    with factory() as stale:
        allocation.synchronize_non_active_clue_states(stale)
    with factory() as verify:
        assert verify.get(ClueMasterLead, "lead-locks").lifecycle_status == "active"
        assert verify.get(ClueAssignmentRound, "round-a").round_status == "active_unfollowed"
        assert verify.get(ClueCenterOrder, "order-locks").current_round_status == "active_unfollowed"


def test_headquarters_projection_never_locks_another_masters_round(db_session, monkeypatch):
    from types import SimpleNamespace
    from apps.worker import clue_allocation_engine as engine

    owner = _master(current_round_id="round-a")
    other = _master()
    other.lead_key = "lead-other"
    other.source_identity_key = "identity-other"
    other.source_clue_row_key = "raw-other"
    center = ClueCenterOrder(
        order_id="order-locks", lead_status="active", current_assignment_round_id="round-a",
        current_round_status="active_unfollowed",
    )
    db_session.add_all([owner, other, _round("round-a"), center])
    db_session.commit()

    def forbidden_child_lock(*args):
        raise AssertionError("cannot lock another master's round while holding only this master")

    monkeypatch.setattr(engine, "lock_clue_assignment_round_for_update", forbidden_child_lock)
    monkeypatch.setattr(engine, "enter_headquarters_pool", lambda *args, **kwargs: None)
    engine._project_headquarters(
        other, _now(), db_session,
        decision=SimpleNamespace(allocation_cycle_id=None, reason="no_candidates"),
    )
    assert center.current_assignment_round_id == "round-a"


def test_materialization_cannot_replay_lost_round_from_stale_dirty_session(tmp_path) -> None:
    factory = _factory(tmp_path, autoflush=True)
    with factory() as seed:
        _seed_follow_up_round(seed)

    stale = factory()
    stale_master = stale.get(ClueMasterLead, "lead-locks")
    stale_round = stale.get(ClueAssignmentRound, "round-a")
    stale_clue = stale.get(RawDouyinClue, "clue-row-locks")
    assert stale_master is not None and stale_round is not None and stale_clue is not None
    stale_round.round_status = "active_followed"
    stale_round.follow_result = "appointment"
    stale.expunge_all()
    stale.close()

    with factory() as writer:
        _apply_lost(writer)
        writer.commit()

    stale = factory()
    stale.add_all([stale_master, stale_round, stale_clue])
    materialize_clue_master_leads(stale, raw_clues=[stale_clue], now=_now())
    stale.commit()
    stale.close()

    with factory() as verify:
        master = verify.get(ClueMasterLead, "lead-locks")
        round_row = verify.get(ClueAssignmentRound, "round-a")
        center = verify.get(ClueCenterOrder, "order-locks")
        assert master is not None and round_row is not None and center is not None
        assert master.current_assignment_round_id is None
        assert round_row.round_status == "closed_reassigned"
        assert center.current_assignment_round_id == "round-a"
        assert center.current_round_status == "closed_reassigned"
        assert center.lead_status == "pending_reassign"


def test_allocation_cannot_replay_lost_round_from_stale_dirty_session(tmp_path) -> None:
    factory = _factory(tmp_path, autoflush=True)
    with factory() as seed:
        _seed_follow_up_round(seed)

    stale = factory()
    stale_master = stale.get(ClueMasterLead, "lead-locks")
    stale_round = stale.get(ClueAssignmentRound, "round-a")
    assert stale_master is not None and stale_round is not None
    stale_round.round_status = "active_followed"
    stale_round.follow_result = "appointment"
    stale.expunge_all()
    stale.close()

    with factory() as writer:
        _apply_lost(writer)
        writer.commit()

    stale = factory()
    stale.add_all([stale_master, stale_round])
    result = allocate_lead(stale, "lead-locks", execution_mode="formal", now=_now())
    assert result.status in {"headquarters", "assigned"}
    stale.commit()
    stale.close()

    with factory() as verify:
        master = verify.get(ClueMasterLead, "lead-locks")
        round_row = verify.get(ClueAssignmentRound, "round-a")
        assert master is not None and round_row is not None
        assert round_row.round_status == "closed_reassigned"
        assert master.current_assignment_round_id is None


def test_dirty_round_refresh_uses_db_owner_and_covers_earlier_history(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as seed:
        lead_a = _master()
        lead_a.lead_key = "lead-a"
        lead_a.source_clue_row_key = "raw-a"
        lead_a.source_identity_key = "identity-a"
        lead_a.order_id = "order-a"
        lead_b = _master()
        lead_b.lead_key = "lead-b"
        lead_b.source_clue_row_key = "raw-b"
        lead_b.source_identity_key = "identity-b"
        lead_b.order_id = "order-b"
        old_a = _round("round-a-old", lead_key="lead-a")
        old_a.order_id = "order-a"
        old_a.round_status = "closed_reassigned"
        other_b = _round("round-b", lead_key="lead-b")
        other_b.order_id = "order-b"
        seed.add_all([lead_a, lead_b, old_a, other_b])
        seed.commit()

    with factory() as session:
        dirty_a = session.get(ClueAssignmentRound, "round-a-old")
        dirty_b = session.get(ClueAssignmentRound, "round-b")
        assert dirty_a is not None and dirty_b is not None
        dirty_a.round_status = "active_followed"
        dirty_a.lead_key = "lead-b"
        dirty_b.round_status = "active_followed"

        locked_master = lock_clue_master_for_update(session, "lead-a")
        assert locked_master is not None
        refreshed = refresh_dirty_rounds_for_locked_leads(session, ("lead-a",))

        assert sorted(refreshed) == ["round-a-old"]
        assert dirty_a.lead_key == "lead-a"
        assert dirty_a.round_status == "closed_reassigned"
        assert not sa_inspect(dirty_a).modified
        assert dirty_b.round_status == "active_followed"
        assert sa_inspect(dirty_b).modified
        session.rollback()

    with factory() as verify:
        assert verify.get(ClueAssignmentRound, "round-a-old").round_status == "closed_reassigned"
        assert verify.get(ClueAssignmentRound, "round-b").round_status == "active_unfollowed"
