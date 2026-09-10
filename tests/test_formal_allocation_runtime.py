from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from apps.api.dy_api.models import ClueAssignmentRound, ClueCenterOrder, RawDouyinClue, RawDouyinOrder, SyncSetting
from apps.worker import formal_allocation_runtime as runtime
from test_clue_allocation_engine import _lead, _store, _publish_global_rule

NOW = datetime(2026, 9, 10, tzinfo=timezone.utc)


def seed(session, key="lead-1", status="201"):
    lead = _lead(key, order_id=f"order-{key}")
    session.add_all([
        lead,
        RawDouyinClue(clue_row_key=lead.source_clue_row_key, clue_id=lead.canonical_clue_id,
                      order_id=lead.order_id, order_status=status, raw_payload={}),
        ClueCenterOrder(order_id=lead.order_id, lead_status="pending_allocation",
                        current_round_status="pending_allocation"),
    ])
    return lead


def setup(session):
    session.add(_store("anchor"))
    _publish_global_rule(session)
    return sessionmaker(bind=session.get_bind(), expire_on_commit=False)


def test_first_allocation_is_committed_visible_idempotent_and_expiry_off(db_session):
    factory = setup(db_session)
    lead = seed(db_session)
    db_session.commit()
    assert runtime.run_formal_allocation_batch(factory, now=NOW)["assigned"] == 1
    with factory() as reader:
        round_row = reader.query(ClueAssignmentRound).one()
        assert round_row.execution_mode == "formal"
        assert round_row.auto_expiry_enabled is False
        assert round_row.assigned_at.replace(tzinfo=timezone.utc) == NOW
        assert reader.get(ClueCenterOrder, lead.order_id).current_assignment_round_id == round_row.assignment_round_id
    assert runtime.run_formal_allocation_batch(factory, order_ids=[lead.order_id], now=NOW)["assigned"] == 0


@pytest.mark.parametrize("status", ["支付成功", "200", "已退款", "已核销", "101", "unknown"])
def test_stale_active_master_does_not_override_latest_source(db_session, status):
    factory = setup(db_session)
    seed(db_session, status=status)
    db_session.commit()
    result = runtime.run_formal_allocation_batch(factory, now=NOW)
    assert result["skipped"] == 1
    assert db_session.query(ClueAssignmentRound).count() == 0


def test_cursor_advances_past_invalid_lead_and_wraps_durably(db_session):
    factory = setup(db_session)
    seed(db_session, "a", "200")
    seed(db_session, "b", "201")
    db_session.commit()
    assert runtime.run_formal_allocation_batch(factory, max_items=1)["skipped"] == 1
    assert runtime.run_formal_allocation_batch(factory, max_items=1)["assigned"] == 1
    assert runtime.run_formal_allocation_batch(factory, max_items=1)["scanned"] == 0
    with factory() as reader:
        assert reader.get(SyncSetting, runtime.CURSOR_KEY).setting_value == ""
    assert runtime.run_formal_allocation_batch(factory, max_items=1)["skipped"] == 1


@pytest.mark.parametrize("order_status,expected", [("支付成功", 1), ("已退款", 0)])
def test_current_order_and_coupon_evidence_override_clue_label(db_session, order_status, expected):
    factory = setup(db_session)
    lead = seed(db_session)
    db_session.add(RawDouyinOrder(
        order_id=lead.order_id, order_status=order_status,
        raw_payload={"certificate": [{"item_status": 400}]},
    ))
    db_session.commit()
    assert runtime.run_formal_allocation_batch(factory)["assigned"] == expected


@pytest.mark.parametrize("field,value", [
    ("pool_location", "headquarters_pool"), ("allocation_state", "assigned"),
    ("lifecycle_status", "review"), ("master_kind", 2),
])
def test_excludes_non_first_allocation_population(db_session, field, value):
    factory = setup(db_session)
    lead = seed(db_session)
    setattr(lead, field, value)
    db_session.commit()
    assert runtime.run_formal_allocation_batch(factory)["scanned"] == 0


def test_item_failure_rolls_back_and_does_not_starve_next_lead(db_session, monkeypatch):
    factory = setup(db_session)
    seed(db_session, "a")
    seed(db_session, "b")
    db_session.commit()
    original = runtime.allocate_lead

    def failing(session, key, **kwargs):
        if key == "a":
            original(session, key, **kwargs)
            raise RuntimeError("failure before commit")
        return original(session, key, **kwargs)

    monkeypatch.setattr(runtime, "allocate_lead", failing)
    result = runtime.run_formal_allocation_batch(factory)
    assert result["failed"] == 1 and result["assigned"] == 1
    with factory() as reader:
        assert [r.lead_key for r in reader.query(ClueAssignmentRound)] == ["b"]


def test_legacy_history_without_lead_link_cannot_be_first_allocated_again(db_session):
    factory = setup(db_session)
    lead = seed(db_session)
    db_session.add(ClueAssignmentRound(
        assignment_round_id="legacy", order_id=lead.order_id,
        execution_mode="legacy", round_status="closed_reassigned",
    ))
    db_session.commit()
    assert runtime.run_formal_allocation_batch(factory)["scanned"] == 0


def test_daily_materialization_notifies_formal_allocator_before_settlement(db_session, monkeypatch):
    from types import SimpleNamespace
    from apps.worker import daily_task
    calls = []
    monkeypatch.setenv("DY_WORKER_ATTEMPT_ID", "test-attempt")
    monkeypatch.setattr(daily_task, "_daily_page_fence", lambda *args: None)
    monkeypatch.setattr(daily_task, "notify_formal_allocation", lambda factory, ids: calls.append(ids))

    def materialize(factory, **kwargs):
        kwargs["on_center_batch"](("a", "b"))
        return {"center_orders": 2}

    monkeypatch.setattr(daily_task, "run_incremental_clue_materialization", materialize)
    job = SimpleNamespace(metadata_json={"clue_materialization_mode": "incremental"})
    daily_task.default_stage_handlers(client=object())["materialize"](db_session, job)
    assert calls == [("a", "b")]


def test_independent_compensation_stops_cleanly_and_respects_pause(monkeypatch):
    from threading import Event
    from apps.worker import scheduler
    stop = Event()
    calls = []
    monkeypatch.setattr(scheduler, "_STOP", False)
    monkeypatch.setattr(scheduler, "_auto_sync_enabled", lambda factory: True)
    monkeypatch.setattr(runtime, "run_formal_allocation_batch", lambda factory: (calls.append(factory), stop.set()))
    scheduler._formal_compensation_loop("factory", stop)
    assert calls == ["factory"]
