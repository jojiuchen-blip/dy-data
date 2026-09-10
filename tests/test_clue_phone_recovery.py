from __future__ import annotations

from datetime import datetime, timedelta, timezone

from apps.api.dy_api.models import (
    ClueAssignmentRound,
    ClueCenterOrder,
    ClueMasterLead,
    RawDouyinClue,
    SyncSetting,
)
from apps.worker import clue_phone_recovery as recovery
from src.dy_data.phones import phone_source_fingerprint


NOW = datetime(2026, 9, 10, 3, tzinfo=timezone.utc)


def _factory(db_session):
    from sqlalchemy.orm import sessionmaker

    return sessionmaker(bind=db_session.get_bind(), autoflush=False, future=True)


def _seed(
    session,
    *,
    key: str,
    cipher: str,
    phone_plain: str | None = None,
    source_fingerprint: str | None = None,
) -> tuple[str, str]:
    order_id = f"order-{key}"
    round_id = f"round-{key}"
    lead = ClueMasterLead(
        lead_key=key,
        source_clue_row_key=f"raw-{key}",
        source_identity_key=f"identity-{key}",
        canonical_clue_id=f"clue-{key}",
        order_id=order_id,
        master_kind=1,
        normalized_order_status="active",
        status_source="test",
        lifecycle_status="active",
        allocation_state="assigned",
        current_assignment_round_id=round_id,
    )
    center = ClueCenterOrder(
        order_id=order_id,
        lead_status="assigned",
        current_assignment_round_id=round_id,
        current_round_no=1,
        current_round_status="active_unfollowed",
        assigned_store_id="store-1",
        phone_plain=phone_plain,
        phone_masked=("138****5678" if phone_plain else None),
        phone_source=("enc_telephone" if phone_plain else None),
        phone_source_fingerprint=source_fingerprint,
    )
    round_row = ClueAssignmentRound(
        assignment_round_id=round_id,
        order_id=order_id,
        lead_key=key,
        round_no=1,
        assigned_store_id="store-1",
        assigned_store_name="Store 1",
        round_status="active_unfollowed",
        execution_mode="formal",
        auto_expiry_enabled=False,
    )
    raw = RawDouyinClue(
        clue_row_key=f"raw-{key}",
        clue_id=f"clue-{key}",
        order_id=order_id,
        order_status="201",
        enc_telephone=cipher,
        raw_payload={},
        create_time_detail=NOW,
    )
    # PostgreSQL enforces the lead FK when the round is inserted; flush the
    # parent explicitly because the models intentionally have no ORM relation.
    session.add(lead)
    session.flush()
    session.add_all([center, round_row, raw])
    return order_id, round_id


def test_missing_cipher_phone_is_recovered_without_round_mutation(db_session):
    factory = _factory(db_session)
    order_id, round_id = _seed(db_session, key="lead-a", cipher="Enc.cipher-a")
    db_session.commit()
    calls: list[list[str]] = []

    def resolver(values):
        calls.append(values)
        return {"Enc.cipher-a": "13812345678"}

    result = recovery.run_clue_phone_recovery_batch(
        factory,
        phone_plain_resolver=resolver,
        max_items=50,
        now=NOW,
    )

    assert result["requested"] == 1
    assert result["repaired"] == 1
    assert calls == [["Enc.cipher-a"]]
    with factory() as reader:
        center = reader.get(ClueCenterOrder, order_id)
        round_row = reader.get(ClueAssignmentRound, round_id)
        lead = reader.get(ClueMasterLead, "lead-a")
        assert center.phone_plain == "13812345678"
        assert center.phone_masked == "138****5678"
        assert center.phone_source_fingerprint == phone_source_fingerprint(cipher_text="Enc.cipher-a")
        assert round_row.round_status == "active_unfollowed"
        assert round_row.assigned_store_id == "store-1"
        assert lead.current_assignment_round_id == round_id

    second = recovery.run_clue_phone_recovery_batch(
        factory,
        phone_plain_resolver=lambda values: (_ for _ in ()).throw(AssertionError(values)),
        max_items=50,
        now=NOW + timedelta(seconds=1),
    )
    assert second["requested"] == 0
    assert second["repaired"] == 0


def test_plain_source_wins_without_network_call(db_session):
    factory = _factory(db_session)
    order_id, _ = _seed(db_session, key="lead-plain", cipher="Enc.cipher-plain")
    db_session.flush()
    raw = db_session.get(RawDouyinClue, "raw-lead-plain")
    raw.telephone = "+86 139-1234-5678"
    db_session.commit()

    def fail_resolver(_values):
        raise AssertionError("plain sources must not call decrypt")

    result = recovery.run_clue_phone_recovery_batch(
        factory,
        phone_plain_resolver=fail_resolver,
        now=NOW,
    )

    assert result["repaired"] == 1
    with factory() as reader:
        center = reader.get(ClueCenterOrder, order_id)
        assert center.phone_plain == "13912345678"
        assert center.phone_source == "telephone"
        assert center.phone_source_fingerprint == phone_source_fingerprint(plain_phone="13912345678")


def test_source_change_during_network_cannot_write_old_phone(db_session):
    factory = _factory(db_session)
    order_id, _ = _seed(db_session, key="lead-race", cipher="Enc.cipher-old")
    db_session.commit()

    def resolver(_values):
        # This second transaction proves the recovery read transaction is
        # closed before the network boundary.  The re-read must reject the
        # old response because the current source became plaintext.
        with factory() as writer:
            raw = writer.get(RawDouyinClue, "raw-lead-race")
            raw.telephone = "13999999999"
            raw.enc_telephone = None
            writer.commit()
        return {"Enc.cipher-old": "13812345678"}

    result = recovery.run_clue_phone_recovery_batch(
        factory,
        phone_plain_resolver=resolver,
        now=NOW,
    )

    assert result["repaired"] == 0
    assert result["source_changed"] == 1
    with factory() as reader:
        center = reader.get(ClueCenterOrder, order_id)
        assert center.phone_plain is None
        assert center.phone_source_fingerprint is None


def test_failure_cooldown_and_rotating_cursor_avoid_repeating_first_row(db_session):
    factory = _factory(db_session)
    _seed(db_session, key="lead-a", cipher="Enc.cipher-a")
    _seed(db_session, key="lead-b", cipher="Enc.cipher-b")
    db_session.commit()
    calls: list[list[str]] = []

    def fail(values):
        calls.append(values)
        raise RuntimeError("upstream unavailable")

    first = recovery.run_clue_phone_recovery_batch(
        factory,
        phone_plain_resolver=fail,
        max_items=1,
        now=NOW,
    )
    second = recovery.run_clue_phone_recovery_batch(
        factory,
        phone_plain_resolver=fail,
        max_items=1,
        now=NOW + timedelta(seconds=1),
    )

    assert first["failed"] == 1 and second["failed"] == 1
    assert calls == [["Enc.cipher-a"], ["Enc.cipher-b"]]
    with factory() as reader:
        state = reader.get(SyncSetting, recovery.PHONE_RECOVERY_STATE_KEY)
        assert '"missing_cursor": "lead-b"' in state.setting_value

    # The first failure is cooling down and is skipped after the cursor wraps.
    third = recovery.run_clue_phone_recovery_batch(
        factory,
        phone_plain_resolver=fail,
        max_items=1,
        now=NOW + timedelta(seconds=2),
    )
    assert third["requested"] == 0
    assert calls == [["Enc.cipher-a"], ["Enc.cipher-b"]]


def test_missing_row_cannot_starve_stale_fingerprint_row(db_session):
    factory = _factory(db_session)
    _seed(db_session, key="lead-missing", cipher="Enc.permanent-missing")
    stale_order_id, _ = _seed(
        db_session,
        key="lead-stale",
        cipher="Enc.current-stale",
        phone_plain="13812345678",
        source_fingerprint=phone_source_fingerprint(cipher_text="Enc.old-stale"),
    )
    db_session.commit()
    calls: list[list[str]] = []

    def resolver(values):
        calls.append(values)
        return {"Enc.current-stale": "13912345678"}

    first = recovery.run_clue_phone_recovery_batch(
        factory,
        phone_plain_resolver=resolver,
        max_items=1,
        now=NOW,
    )
    second = recovery.run_clue_phone_recovery_batch(
        factory,
        phone_plain_resolver=resolver,
        max_items=1,
        now=NOW + timedelta(seconds=1),
    )

    assert first["unresolved"] == 1
    assert second["repaired"] == 1
    assert calls == [["Enc.permanent-missing"], ["Enc.current-stale"]]
    with factory() as reader:
        assert reader.get(ClueCenterOrder, stale_order_id).phone_plain == "13912345678"


def test_recovery_lock_has_one_consumer(db_session):
    factory = _factory(db_session)
    with recovery._phone_recovery_lock(factory) as first:
        assert first is True
        with recovery._phone_recovery_lock(factory) as second:
            assert second is False


def test_scheduler_phone_recovery_runs_in_independent_loop(monkeypatch):
    from apps.worker import scheduler

    calls: list[object] = []

    monkeypatch.setattr(scheduler, "_STOP", False)
    monkeypatch.setattr(scheduler, "resolve_scheduler_mode", lambda: "priority_daily")
    monkeypatch.setattr(
        recovery,
        "run_clue_phone_recovery_batch",
        lambda factory: calls.append(factory),
    )

    class StopAfterFirstWait:
        stopped = False

        def is_set(self) -> bool:
            return self.stopped

        def wait(self, _seconds: int) -> None:
            self.stopped = True

    scheduler._clue_phone_recovery_loop("factory", StopAfterFirstWait())

    assert calls == ["factory"]


def test_targeted_repair_does_not_move_background_cursors(db_session):
    import json
    order_id, _ = _seed(db_session, key="target", cipher="Enc.target")
    db_session.add(SyncSetting(setting_key=recovery.PHONE_RECOVERY_STATE_KEY, setting_value=json.dumps({"missing_cursor":"keep-missing", "stale_cursor":"keep-stale", "phase":"stale", "cooldowns":{}})))
    db_session.commit()
    result = recovery.run_clue_phone_recovery_batch(_factory(db_session), order_ids=[order_id], phone_plain_resolver=lambda values: {"Enc.target":"13812345678"}, now=NOW)
    assert result["repaired"] == 1
    db_session.expire_all()
    state=json.loads(db_session.get(SyncSetting,recovery.PHONE_RECOVERY_STATE_KEY).setting_value)
    assert state["missing_cursor"] == "keep-missing"
    assert state["stale_cursor"] == "keep-stale"
    assert state["phase"] == "stale"


def test_elapsed_network_budget_does_not_write_phone(db_session, monkeypatch):
    order_id, _ = _seed(db_session, key="deadline", cipher="Enc.deadline")
    db_session.commit()
    clock=[100.0]
    monkeypatch.setattr(recovery,"monotonic",lambda:clock[0])
    def resolver(values):
        clock[0]+=11
        return {"Enc.deadline":"13812345678"}
    result=recovery.run_clue_phone_recovery_batch(_factory(db_session), order_ids=[order_id],phone_plain_resolver=resolver, max_seconds=10,now=NOW)
    assert result["repaired"] == 0
    assert result["deferred"] == 1
    db_session.expire_all()
    assert db_session.get(ClueCenterOrder,order_id).phone_plain is None


def test_scheduler_phone_recovery_reports_aggregate_result(monkeypatch):
    from threading import Event
    from apps.worker import scheduler
    stop=Event(); messages=[]
    def run(factory):
        stop.set()
        return {"requested":1,"repaired":1}
    monkeypatch.setattr(recovery,"run_clue_phone_recovery_batch",run)
    monkeypatch.setattr(scheduler,"_STOP",False)
    monkeypatch.setattr(scheduler,"resolve_scheduler_mode",lambda:"priority_daily")
    monkeypatch.setattr(scheduler,"_log",messages.append)
    scheduler._clue_phone_recovery_loop(object(),stop)
    assert len(messages)==1
    assert '"repaired": 1' in messages[0]
