"""Details must explain ranking verification even when round projections lag."""
import csv
import io
from datetime import datetime, timezone

import pytest

from test_api_clues import client, _dt, _login, _seed_clue_center
from apps.api.dy_api.models import (
    ClueAssignmentRound, DimStorePoiMapping, RawDouyinOrder,
    RawDouyinOrderCoupon, RawDouyinVerifyRecord,
)


def add_verification(session, *, order_id="order-1", suffix="1", store="store-1",
                     when=None, status="success", cancel=None):
    if session.query(RawDouyinOrder).filter_by(order_id=order_id).first() is None:
        session.add(RawDouyinOrder(order_id=order_id, sku_id="sku-1"))
        session.flush()
    coupon = RawDouyinOrderCoupon(coupon_id="coupon-" + suffix, order_id=order_id)
    session.add(coupon)
    if store and session.query(DimStorePoiMapping).filter_by(poi_id="poi-" + store).first() is None:
        session.add(DimStorePoiMapping(poi_id="poi-" + store, store_id=store))
    session.add(RawDouyinVerifyRecord(verify_id="verify-" + suffix,
        coupon_id=coupon.coupon_id, verify_time=when or _dt(2), verify_status=status,
        poi_id="poi-" + store if store else "unknown-poi", cancel_time=cancel))
    session.commit()


def test_missing_round_projection_uses_raw_facts_for_list_export_and_detail(client, db_session):
    _seed_clue_center(db_session)
    row = db_session.get(ClueAssignmentRound, "order-1-1")
    row.verified_at = row.verified_store_id = row.verified_store_name = None
    row.is_follow_success = row.is_self_store_verified = False
    add_verification(db_session)
    _login(client)
    url = "/api/v1/clues/assignment-rounds"
    filters = {"verification_status": "self_store_verified",
               "assigned_date_start": "2026-09-01", "assigned_date_end": "2026-09-07"}
    body = client.post(url, json={"filters": filters}).json()["data"]
    assert body["pagination"]["total"] == 1
    assert body["rows"][0]["verified_store_id"] == "store-1"
    assert body["rows"][0]["verified_at"]
    assert body["rows"][0]["is_self_store_verified"] is False  # retain scoring field
    exported = client.post(url + "/export", json={"filters": filters})
    records = list(csv.DictReader(io.StringIO(exported.text.lstrip("\ufeff"))))
    assert [x["order_id"] for x in records] == ["order-1"]
    assert records[0]["verified_store_id"] == "store-1"
    detail = client.get("/api/v1/clues/orders/order-1").json()["data"]
    assert detail["rounds"][0]["verified_store_id"] == "store-1"
    db_session.refresh(row)
    assert row.verified_at is None  # read path does not rewrite business history


@pytest.mark.parametrize("condition,kind", [
    ("self", "self_store_verified"), ("other", "other_store_verified"),
    ("cancelled", "unverified"), ("before", "unverified"),
    ("failed", "unverified"), ("future", "unverified"), ("unknown", None),
])
def test_verification_filters_use_success_time_cancellation_and_mapping(client, db_session, condition, kind):
    _seed_clue_center(db_session)
    kwargs = {}
    if condition == "other": kwargs["store"] = "store-2"
    if condition == "cancelled": kwargs["cancel"] = _dt(3)
    if condition == "before": kwargs["when"] = datetime(2026, 8, 31, tzinfo=timezone.utc)
    if condition == "failed": kwargs["status"] = "failed"
    if condition == "future": kwargs["when"] = datetime(2099, 1, 1, tzinfo=timezone.utc)
    if condition == "unknown": kwargs["store"] = None
    add_verification(db_session, **kwargs)
    _login(client)
    for candidate in ["self_store_verified", "other_store_verified", "unverified"]:
        rows = client.get("/api/v1/clues/assignment-rounds", params={
            "verification_status": candidate, "q": "order-1"}).json()["data"]["rows"]
        assert bool(rows) is (candidate == kind)


def test_multi_coupon_self_wins_without_double_counting(client, db_session):
    _seed_clue_center(db_session)
    add_verification(db_session, suffix="other", store="store-2")
    add_verification(db_session, suffix="self")
    _login(client)
    url = "/api/v1/clues/assignment-rounds"
    assert client.get(url, params={"verification_status": "self_store_verified"}).json()["data"]["pagination"]["total"] == 1
    assert client.get(url, params={"verification_status": "other_store_verified"}).json()["data"]["pagination"]["total"] == 0


def test_self_filter_counts_order_store_once_and_respects_selected_assignment_week(client, db_session):
    _seed_clue_center(db_session)
    original = db_session.get(ClueAssignmentRound, "order-1-1")
    db_session.add(ClueAssignmentRound(assignment_round_id="order-1-later", order_id="order-1",
        round_no=2, assigned_at=_dt(8), assigned_store_id="store-1", execution_mode="formal",
        round_status="closed_order_verified", created_at=_dt(8), updated_at=_dt(8)))
    add_verification(db_session, when=_dt(9))
    _login(client)
    url = "/api/v1/clues/assignment-rounds"
    filters = {"verification_status": "self_store_verified", "q": "order-1"}
    response = client.post(url, json={"filters": filters}).json()["data"]
    assert response["pagination"]["total"] == 1
    assert response["rows"][0]["assignment_round_id"] == original.assignment_round_id
    filters.update(assigned_date_start="2026-09-08", assigned_date_end="2026-09-14")
    response = client.post(url, json={"filters": filters}).json()["data"]
    assert response["pagination"]["total"] == 1
    assert response["rows"][0]["assignment_round_id"] == "order-1-later"
