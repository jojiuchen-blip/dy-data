"""Synthetic phone selections exercise the authenticated list and export paths."""
import csv
import io
from time import perf_counter

import pytest
from sqlalchemy import select, insert, event

from test_api_clues import client, _seed_clue_center, _login, _login_user
from apps.api.dy_api.models import ClueCenterOrder, RawDouyinClue, User, UserStoreScope
from dy_api.auth import hash_password_pbkdf2
from src.dy_data.phones import phone_source_fingerprint
from apps.worker.order_status import ACTIVE_ORDER_STATUSES, PAID_ORDER_STATUSES

PHONE = "13812345678"


def test_database_errors_do_not_expose_sensitive_query_parameters():
    from dy_api.db import make_engine
    from sqlalchemy import text
    from sqlalchemy.exc import SQLAlchemyError
    engine = make_engine("sqlite+pysqlite:///:memory:")
    with engine.connect() as connection:
        with pytest.raises(SQLAlchemyError) as caught:
            connection.execute(text("SELECT :phone FROM missing_phone_table"), {"phone": PHONE})
    assert PHONE not in str(caught.value)
    engine.dispose()


def _seed(session):
    _seed_clue_center(session)
    for order_id in ("order-1", "order-2"):
        session.add(RawDouyinClue(clue_row_key="phone-filter-" + order_id,
            order_id=order_id, order_status="201", telephone=PHONE, raw_payload={}))
    session.commit()


def test_phone_filter_exact_multi_order_pagination_export(client, db_session, caplog):
    _seed(db_session)
    _login(client)
    filters = {"phone": "  " + PHONE + "  "}
    response = client.post("/api/v1/clues/assignment-rounds", json={"filters": filters, "page_size": 1})
    assert response.status_code == 200
    assert response.json()["data"]["pagination"]["total"] == 2
    page2 = client.post("/api/v1/clues/assignment-rounds", json={"filters": filters, "page_size": 1, "page": 2})
    assert page2.json()["data"]["rows"][0]["order_id"] != response.json()["data"]["rows"][0]["order_id"]
    exported = client.post("/api/v1/clues/assignment-rounds/export", json={"filters": filters})
    assert exported.status_code == 200
    assert PHONE not in str(exported.headers)
    assert {r["order_id"] for r in csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig")))} == {"order-1", "order-2"}
    assert client.post("/api/v1/clues/assignment-rounds", json={"filters": {"phone": "13912345670"}}).json()["data"]["pagination"]["total"] == 0
    assert PHONE not in caplog.text


@pytest.mark.parametrize("phone", ["5678", "138****5678", "+8613812345678", "12812345678", "138 12345678", 13812345678])
def test_phone_filter_invalid_input_is_private(client, db_session, phone):
    _seed(db_session)
    _login(client)
    response = client.post("/api/v1/clues/assignment-rounds", json={"filters": {"phone": phone}})
    assert response.status_code == 422
    assert str(phone) not in response.text


def test_phone_filter_current_source_and_no_decrypt(client, db_session, monkeypatch):
    _seed(db_session)
    from apps.api.dy_api.clue_phone_filters import matching_phone_order_ids
    def forbidden():
        raise AssertionError("Phone searches must never call the remote decrypt client")
    monkeypatch.setattr("apps.api.dy_api.routes._data.build_douyin_client_from_env", forbidden)
    monkeypatch.setattr("dy_api.routes._data.build_douyin_client_from_env", forbidden)
    second = db_session.scalar(select(ClueCenterOrder).where(ClueCenterOrder.order_id == "order-2"))
    raw = db_session.scalar(select(RawDouyinClue).where(RawDouyinClue.order_id == "order-2"))
    raw.telephone = ""
    raw.enc_telephone = "Enc.current-synthetic"
    second.phone_plain = PHONE
    second.phone_source_fingerprint = phone_source_fingerprint(cipher_text="Enc.old-synthetic")
    db_session.commit()
    assert matching_phone_order_ids(db_session, PHONE) == ["order-1"]
    second.phone_source_fingerprint = phone_source_fingerprint(cipher_text=raw.enc_telephone)
    db_session.commit()
    assert set(matching_phone_order_ids(db_session, PHONE)) == {"order-1", "order-2"}


def test_phone_filter_payload_and_masked_current_source(db_session):
    _seed(db_session)
    from apps.api.dy_api.clue_phone_filters import matching_phone_order_ids
    raw = db_session.scalar(select(RawDouyinClue).where(RawDouyinClue.order_id == "order-1"))
    raw.telephone = ""
    raw.raw_payload = {"mobile": "+86 (138) 1234-5678"}
    db_session.commit()
    assert set(matching_phone_order_ids(db_session, PHONE)) == {"order-1", "order-2"}
    raw.raw_payload = {"mobile": "13912345678"}
    # Old cache must not override a newer plaintext source.
    db_session.get(ClueCenterOrder, "order-1").phone_plain = PHONE
    db_session.commit()
    assert matching_phone_order_ids(db_session, PHONE) == ["order-2"]
    raw.raw_payload = {"mobile": "138****5678"}
    raw.enc_telephone = "Enc.synthetic-mask"
    db_session.get(ClueCenterOrder, "order-1").phone_source_fingerprint = phone_source_fingerprint(cipher_text=raw.enc_telephone)
    db_session.commit()
    assert matching_phone_order_ids(db_session, PHONE) == ["order-2"]


def test_phone_filter_preserves_store_scope(client, db_session):
    _seed(db_session)
    db_session.add_all([User(user_id="phone-scope", username="phone-scope", external_account_id="store-1", display_name="Synthetic", role="store", status="active", is_initialized=True, password_hash=hash_password_pbkdf2("secret")), UserStoreScope(user_id="phone-scope", store_id="store-1")])
    db_session.commit()
    _login_user(client, "phone-scope", "secret")
    response = client.post("/api/v1/clues/assignment-rounds", json={"filters": {"phone": PHONE}})
    assert response.status_code == 200
    assert {row["assigned_store_id"] for row in response.json()["data"]["rows"]} == {"store-1"}


def test_phone_filter_batches_candidates_without_truncating(db_session):
    from apps.api.dy_api.clue_phone_filters import matching_phone_order_ids
    # Synthetic only: 10,000 unrelated rows and 401 matches across 3 batches.
    db_session.execute(insert(RawDouyinClue), [dict(clue_row_key=f"bulk-{i:05}",
        order_id=f"bulk-order-{i:05}", order_status="201", telephone=PHONE if i < 401 else "13900000000", raw_payload={}) for i in range(10401)])
    db_session.commit()
    source_batch_sizes = []
    def observe(conn, cursor, statement, parameters, context, executemany):
        if "raw_douyin_clues.order_id IN" in statement:
            # The remaining binds are the status set and COALESCE's empty value.
            source_batch_sizes.append(len(parameters) - len(ACTIVE_ORDER_STATUSES | PAID_ORDER_STATUSES) - 1)
    event.listen(db_session.get_bind(), "before_cursor_execute", observe)
    try:
        started = perf_counter()
        matched = matching_phone_order_ids(db_session, PHONE)
        elapsed = perf_counter() - started
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", observe)
    assert len(matched) == 401
    assert source_batch_sizes == [200, 200, 1]
    print(f"Synthetic phone selection: 10401 source rows, 401 matches, 3 bounded reads, {elapsed:.3f}s")
