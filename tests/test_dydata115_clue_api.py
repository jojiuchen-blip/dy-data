"""Exercise product follow-up rules through the authenticated application routes."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from apps.api.dy_api.models import (
    ClueAssignmentRound, ClueFollowUpRecord, ClueMasterLead, RawDouyinOrder,
    RawDouyinOrderCoupon, User, UserStoreScope,
)
from test_api_clues import client, _dt, _login, _login_user, _seed_clue_center
from dy_api.auth import hash_password_pbkdf2
from dy_api.routes._data import DashboardDataStore
from test_clue_verification_facts import add_verification


def product_order(session, mode="flow"):
    _seed_clue_center(session)
    lead = session.get(ClueMasterLead, "lead-order-2")
    lead.routing_mode = mode
    session.commit()
    return lead, session.get(ClueAssignmentRound, "order-2-1")


@pytest.mark.parametrize("mode", ["flow", "direct", "original"])
def test_appointment_validation_response_deadline_and_immutable_history(client, db_session, mode):
    _, row = product_order(db_session, mode)
    _login(client)
    path = "/api/v1/clues/orders/order-2/follow-up"
    body = {"assignment_round_id": row.assignment_round_id, "follow_result": "appointment"}
    assert client.post(path, json=body).status_code == 422
    assert client.post(path, json={**body, "appointment_at": "2027-01-01T10:00:00"}).status_code == 422
    assert db_session.scalar(select(func.count()).select_from(ClueFollowUpRecord)) == 0
    response = client.post(path, json={**body, "appointment_at": "2027-01-01T10:00:00+08:00"})
    assert response.status_code == 200, response.text
    record = response.json()["data"]
    assert datetime.fromisoformat(record["appointment_at"]) == datetime(2027, 1, 1, 2, tzinfo=timezone.utc)
    assert record["note"] is None
    detail = client.get("/api/v1/clues/orders/order-2").json()["data"]
    current = detail["rounds"][0]
    assert current["routing_mode"] == mode
    assert current["can_delete_follow_up_records"] is False
    deadline = datetime.fromisoformat(current["protection_expires_at"]).replace(tzinfo=timezone.utc)
    assert deadline == datetime(2027, 1, 4, 2, tzinfo=timezone.utc)
    assert detail["follow_up_records"][0]["appointment_at"]
    deletion = client.delete("/api/v1/clues/follow-up-records/" + record["follow_up_record_id"])
    assert deletion.status_code == 409 and "immutable" in deletion.json()["detail"]
    db_session.expire_all()
    assert db_session.get(ClueFollowUpRecord, record["follow_up_record_id"]).deleted_at is None


@pytest.mark.parametrize("action,reason", [("lost", "follow_lost"), ("request_store_change", "request_store_change")])
def test_closed_business_task_is_read_only_in_list_and_detail(client, db_session, action, reason):
    lead, row = product_order(db_session)
    _login(client)
    path = "/api/v1/clues/orders/order-2/follow-up"
    assert client.post(path, json={"assignment_round_id": row.assignment_round_id, "follow_result": action}).status_code == 200
    assert client.post(path, json={"assignment_round_id": row.assignment_round_id, "follow_result": "further_follow_up"}).status_code == 409
    for current in [client.get("/api/v1/clues/orders/order-2").json()["data"]["rounds"][0],
                    client.get("/api/v1/clues/assignment-rounds", params={"q": "order-2"}).json()["data"]["rows"][0]]:
        assert current["can_operate_current_round"] is False
        assert current["is_current_round"] is False
        assert current["round_effective_status"] == "inactive"
        assert current["terminal_reason"] == reason and current["closed_at"]
    db_session.expire_all()
    assert lead.allocation_state == "closed" and lead.current_assignment_round_id is None


def test_rejected_post_commits_terminal_reconciliation_before_responding(client, db_session):
    lead, row = product_order(db_session)
    db_session.add(RawDouyinOrder(order_id=lead.order_id, order_status="201", updated_at=_dt(1)))
    db_session.add(RawDouyinOrderCoupon(order_id=lead.order_id, coupon_id="terminal-api",
        coupon_status="301", coupon_status_normalized="refunded", latest_refund_at=_dt(2),
        source_observed_at=_dt(3)))
    db_session.commit()
    _login(client)
    response = client.post("/api/v1/clues/orders/order-2/follow-up", json={
        "assignment_round_id": row.assignment_round_id, "follow_result": "further_follow_up"})
    assert response.status_code == 409
    db_session.expire_all()
    assert lead.normalized_order_status == "refunded"
    assert row.round_status == "closed_order_refunded" and row.closed_at is not None
    assert db_session.scalar(select(func.count()).select_from(ClueFollowUpRecord)) == 0


def add_store_user(session):
    session.add(User(user_id="product-store", username="product-store", role="store", status="active",
        display_name="Store One", external_account_id="store-1", is_initialized=True,
        password_hash=hash_password_pbkdf2("store-password")))
    session.add(UserStoreScope(user_id="product-store", store_id="store-1"))
    session.commit()


def test_new_headquarters_handoff_keeps_authorized_past_task_visible_without_phone(client, db_session):
    lead, row = product_order(db_session)
    lead.current_assignment_round_id = None
    lead.pool_location, lead.allocation_state = "headquarters_pool", "headquarters"
    row.round_status, row.closed_at = "closed_reassigned", _dt(3)
    db_session.commit()
    add_store_user(db_session)
    _login_user(client, "product-store", "store-password")
    data = client.get("/api/v1/clues/assignment-rounds", params={"q": "order-2"}).json()["data"]
    assert len(data["rows"]) == 1
    assert data["rows"][0]["can_operate_current_round"] is False
    assert client.get("/api/v1/clues/orders/order-2").status_code == 200
    assert client.get("/api/v1/clues/orders/order-2/phone", params={"assignment_round_id": row.assignment_round_id}).status_code in {403, 404, 409}


def test_cross_round_history_is_limited_to_the_scoped_lead(client, db_session):
    lead, row = product_order(db_session)
    hidden = ClueMasterLead(lead_key="other-order-2", source_clue_row_key="other-raw",
        source_identity_key="other-identity", order_id=lead.order_id, routing_mode="flow",
        normalized_order_status="active", lifecycle_status="active", allocation_state="assigned",
        pool_location="store_follow_up_pool", current_assignment_round_id="hidden-round")
    db_session.add(hidden)
    db_session.flush()
    db_session.add(ClueAssignmentRound(assignment_round_id="hidden-round", order_id=lead.order_id,
        lead_key=hidden.lead_key, round_no=0, assigned_at=_dt(1), assigned_store_id="store-2",
        round_status="active_unfollowed", execution_mode="formal"))
    db_session.add(ClueFollowUpRecord(follow_up_record_id="hidden-record", order_id=lead.order_id,
        assignment_round_id="hidden-round", round_no=0, assigned_store_id="store-2",
        follow_result="further_follow_up", note="other lead", created_at=_dt(2)))
    db_session.commit()
    add_store_user(db_session)
    _login_user(client, "product-store", "store-password")
    response = client.get("/api/v1/clues/orders/order-2")
    assert response.status_code == 200
    assert [r["assignment_round_id"] for r in response.json()["data"]["rounds"]] == [row.assignment_round_id]
    assert response.json()["data"]["follow_up_records"] == []


def test_overview_product_scope_rejects_unknown_enum_before_read(client, db_session):
    _login(client)
    assert client.get("/api/v1/clues/overview", params={"product_scope": "unknown"}).status_code == 422


def test_live_overview_combines_task_counts_and_taskless_actual_store_volume(db_session):
    _seed_clue_center(db_session)
    add_verification(db_session, order_id="no-task", suffix="no-task", when=_dt(2))
    store = DashboardDataStore(db_session)
    counts = ("follow_24h_numerator", "follow_any_numerator", "follow_denominator",
              "verification_numerator", "verification_denominator", "received_task_count",
              "self_store_verification_count")
    all_products = store.clue_overview({})
    jingcheng = store.clue_overview({"product_scope": "jingcheng"})
    byd = store.clue_overview({"product_scope": "byd"})
    assert all(all_products[key] == jingcheng[key] + byd[key] for key in counts)
    assert all_products["self_store_verification_count"] == 1
    same_day = store.clue_overview({"assigned_date_start": "2026-09-02", "assigned_date_end": "2026-09-02"})
    assert same_day["received_task_count"] == 0
    assert same_day["self_store_verification_count"] == 1
    assert store.clue_overview({"assigned_date_start": "2026-09-03", "assigned_date_end": "2026-09-03"})["self_store_verification_count"] == 0
