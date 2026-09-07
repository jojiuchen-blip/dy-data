"""Source invalidation and bounded batch work for clue phone reads."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import event

from apps.api.dy_api.models import ClueCenterOrder, RawDouyinClue
from test_api_clues import data_module
from src.dy_data.phones import phone_source_fingerprint


def _source(session, order_id, *, telephone=None, cipher=None):
    row = RawDouyinClue(
        clue_row_key=order_id, order_id=order_id, telephone=telephone,
        enc_telephone=cipher, raw_payload={}, order_status="201",
        imported_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    session.add(row)
    return row


@pytest.mark.parametrize("order_count", [200, 401])
def test_orders_use_bounded_queries_and_batches(db_session, monkeypatch, order_count):
    ids = [f"phone-{index}" for index in range(order_count)]
    batches = (order_count + 199) // 200
    for order_id in ids:
        db_session.add(ClueCenterOrder(lead_status="active", current_round_status="active_unfollowed", order_id=order_id))
        _source(db_session, order_id, cipher="Enc." + order_id)
    db_session.commit()
    calls = []
    queries = []

    class Client:
        def decrypt_cipher_texts(self, values):
            calls.append(values)
            return {value: "13812345678" for value in values}

    monkeypatch.setattr(data_module, "build_douyin_client_from_env", Client)
    engine = db_session.get_bind()

    def record_query(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    event.listen(engine, "before_cursor_execute", record_query)
    try:
        store = data_module.DashboardDataStore(db_session)
        result = store._clue_order_phones(ids)
        assert len(queries) == 2 * batches
        assert len(calls) == batches and max(map(len, calls)) <= 200
        assert sum(map(len, calls)) == order_count
        assert all(result[order_id] == ("13812345678", "138****5678") for order_id in ids)
        assert store._clue_order_phones(ids) == result
        assert len(queries) == 4 * batches and len(calls) == batches
    finally:
        event.remove(engine, "before_cursor_execute", record_query)


def test_source_change_cannot_reuse_old_database_or_memory_phone(db_session, monkeypatch):
    old_cipher = "Enc.old.13812345678"
    center = ClueCenterOrder(lead_status="active", current_round_status="active_unfollowed",
        order_id="changed", phone_plain="13812345678", phone_masked="138****5678",
        phone_source_fingerprint=phone_source_fingerprint(cipher_text=old_cipher),
    )
    db_session.add(center)
    raw = _source(db_session, "changed", cipher=old_cipher)
    db_session.commit()
    calls = []

    class Client:
        def decrypt_cipher_texts(self, values):
            calls.append(values)
            raise RuntimeError("unavailable")

    monkeypatch.setattr(data_module, "build_douyin_client_from_env", Client)
    store = data_module.DashboardDataStore(db_session)
    assert store._clue_order_phones(["changed"])["changed"][0] == "13812345678"
    assert not calls
    raw.enc_telephone = "Enc.new.13999999999"
    db_session.commit()
    assert store._clue_order_phones(["changed"])["changed"] == ("", "")
    assert store._clue_order_phones(["changed"])["changed"] == ("", "")
    assert len(calls) == 1
    raw.telephone = "+86 139-1234-5678"
    db_session.commit()
    assert store._clue_order_phones(["changed"])["changed"] == ("13912345678", "139****5678")
    db_session.delete(raw)
    db_session.commit()
    assert store._clue_order_phones(["changed"])["changed"] == ("", "")


@pytest.mark.parametrize("value", ["Enc.abc13812345678", "text13812345678", "138****5678", "00013812345678"])
def test_cipher_and_non_phone_values_never_become_plain_phone(db_session, monkeypatch, value):
    db_session.add(ClueCenterOrder(lead_status="active", current_round_status="active_unfollowed", order_id="invalid", phone_plain="13812345678"))
    _source(db_session, "invalid", telephone=value)
    db_session.commit()
    monkeypatch.setattr(data_module, "build_douyin_client_from_env", None)
    result = data_module.DashboardDataStore(db_session)._clue_order_phones(["invalid"])
    assert result["invalid"][0] == ""


def test_removed_source_and_legacy_cache_are_not_trusted(db_session):
    db_session.add(ClueCenterOrder(lead_status="active", current_round_status="active_unfollowed", order_id="orphan", phone_plain="13812345678", phone_masked="138****5678"))
    db_session.commit()
    assert data_module.DashboardDataStore(db_session)._clue_order_phones(["orphan"])["orphan"] == ("", "")


def test_phone_memory_cache_is_bounded_and_failures_expire(db_session, monkeypatch):
    from dy_api import clue_phone_cache as cache

    clock = [100.0]
    monkeypatch.setattr(cache, "monotonic", lambda: clock[0])
    engine = db_session.get_bind()
    for index in range(cache.MAX_ENTRIES + 1):
        cache.put_phone(engine, str(index), "13812345678")
    assert cache.get_phone(engine, "0") is None
    assert cache.get_phone(engine, str(cache.MAX_ENTRIES)) == "13812345678"
    cache.put_phone(engine, "failed", "")
    assert cache.get_phone(engine, "failed") == ""
    clock[0] += cache.FAILURE_TTL_SECONDS + 1
    assert cache.get_phone(engine, "failed") is None
    assert cache.get_phone(engine, str(cache.MAX_ENTRIES)) == "13812345678"
    clock[0] += cache.SUCCESS_TTL_SECONDS
    assert cache.get_phone(engine, str(cache.MAX_ENTRIES)) is None
