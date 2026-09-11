"""Bounded read-only source export, independently of settlement materialization."""
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api"))
from dy_api.main import create_app
from dy_api.auth import AuthContext, get_current_user
from dy_api.routes._data import get_session_dependency
from apps.api.dy_api.models import (
    DimSkuProductRule, RawDouyinOrder, RawDouyinOrderCoupon,
    RawDouyinVerifyRecord, ClueAssignmentRound,
)

URL = "/api/v1/admin/ranking-source-evidence"
PARAMS = dict(dataset="orders", periodStart="2026-09-04", periodEnd="2026-09-10",
              observedThrough="2026-09-11T00:00:00+08:00")


@pytest.fixture
def client(db_session, monkeypatch):
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    monkeypatch.setenv("DY_SUPER_ADMIN_USERNAME", "source_test_admin")
    monkeypatch.setenv("DY_TEST_ADMIN_PASSWORD", "synthetic-test-only")
    app = create_app()
    app.dependency_overrides[get_session_dependency] = lambda: db_session
    c = TestClient(app)
    assert c.post("/api/v1/auth/login", json={"username": "source_test_admin", "password": "synthetic-test-only"}).status_code == 200
    return c


@pytest.fixture
def evidence(db_session):
    at = datetime(2026, 9, 4, tzinfo=timezone.utc)
    db_session.add(DimSkuProductRule(sku_id="JC", product_id="JC-P", product_scope="精诚养车"))
    for oid, sku, sale in [("A", "JC", at), ("B", "JC", at + timedelta(days=1)),
                            ("OLD", "JC", at-timedelta(days=20)), ("OTHER", "NO", at)]:
        db_session.add(RawDouyinOrder(order_id=oid, sku_id=sku, sale_time=sale,
            sale_channel="搜索", owner_account_id="craftsman", raw_payload={"phone": "never-export"}))
    db_session.flush()
    db_session.add(ClueAssignmentRound(assignment_round_id="R", order_id="OLD", assigned_store_id="STORE",
        assigned_at=at, execution_mode="formal", round_status="active"))
    db_session.add(RawDouyinOrderCoupon(coupon_id="C", order_id="OLD"))
    db_session.flush()
    db_session.add(RawDouyinVerifyRecord(verify_id="V", coupon_id="C", verify_time=at,
        verify_status="success", cancel_time=at+timedelta(days=1), poi_id="POI"))
    db_session.commit()


def test_cohort_includes_old_assigned_order_and_excludes_other_skus(client, evidence):
    response = client.get(URL, params=PARAMS)
    assert response.status_code == 200
    data = response.json()
    assert {r["order_id"] for r in data["data"]["rows"]} == {"A", "B", "OLD"}
    assert "never-export" not in response.text and "raw_payload" not in response.text
    assert data["meta"]["consistent_snapshot"] is False
    assert data["meta"]["read_only"] is True


def test_keyset_pages_and_cursor_context(client, evidence):
    first = client.get(URL, params={**PARAMS, "pageSize": 1}).json()["data"]
    cursor = first["next_cursor"]
    second = client.get(URL, params={**PARAMS, "pageSize": 1, "cursor": cursor}).json()["data"]
    assert first["rows"][0]["order_id"] != second["rows"][0]["order_id"]
    assert client.get(URL, params={**PARAMS, "dataset": "coupons", "cursor": cursor}).status_code == 422


def test_coupons_and_revocation_fields_are_raw(client, evidence):
    coupons = client.get(URL, params={**PARAMS, "dataset": "coupons"}).json()["data"]["rows"]
    assert coupons[0]["order_id"] == "OLD"
    events = client.get(URL, params={**PARAMS, "dataset": "verifications"}).json()["data"]["rows"]
    assert events[0]["cancel_time"] is not None  # must not hide canceled events


@pytest.mark.parametrize("change", [dict(periodEnd="2026-09-11"), dict(pageSize=501),
    dict(dataset="users"), dict(cursor="invalid"), dict(observedThrough="2026-09-11T00:00:00"),
    dict(observedThrough="2099-01-01T00:00:00+08:00")])
def test_reject_unbounded_or_invalid_requests(client, change):
    assert client.get(URL, params={**PARAMS, **change}).status_code == 422


@pytest.mark.parametrize("role", ["store", "admin"])
def test_store_user_cannot_export_global_sources(client, role):
    client.app.dependency_overrides[get_current_user] = lambda: AuthContext(
        user_id="regular-user", username="store", display_name="store", role=role, store_ids=("STORE",),
        auth_type="user", store_scope_mode="explicit", page_keys=("A03",))
    assert client.get(URL, params=PARAMS).status_code == 403


def test_anonymous_cannot_export(client):
    client.cookies.clear()
    assert client.get(URL, params=PARAMS).status_code == 401


@pytest.mark.parametrize("dataset", ["cohort", "assignment_rounds", "follow_records", "bindings", "accounts", "poi_mappings", "sku_rules"])
def test_all_datasets_have_bounded_read_contract(client, evidence, dataset):
    response = client.get(URL, params={**PARAMS, "dataset": dataset, "pageSize": 1})
    assert response.status_code == 200, response.text
    assert len(response.json()["data"]["rows"]) <= 1


def test_source_reader_does_not_flush_pending_writes(evidence, db_session):
    # The existing auth layer seeds access-control defaults and explicitly flushes.
    # Test the export reader itself rather than attributing auth behavior to it.
    from dy_api.ranking_source_evidence import read_source_page
    from datetime import date
    pending = RawDouyinOrder(order_id="pending-write", sku_id="JC", sale_time=datetime(2026,9,5,tzinfo=timezone.utc))
    db_session.add(pending)
    result = read_source_page(db_session, dataset="orders", period_start=date(2026,9,4),
        period_end=date(2026,9,10), observed_through=datetime(2026,9,11,tzinfo=timezone.utc))
    assert "pending-write" not in {row["order_id"] for row in result["data"]["rows"]}
    assert pending in db_session.new


def test_dimensions_never_export_raw_payload_or_nicknames(client, db_session):
    from apps.api.dy_api.models import RawAwemeBinding
    db_session.add(RawAwemeBinding(binding_key="test", account_id="settlement", poi_id="POI",
        douyin_nickname="private-name", raw_payload={"craftsman_uid":"craft", "account_id_for_settlement":"settlement", "phone":"never-export"}))
    db_session.commit()
    response = client.get(URL, params={**PARAMS, "dataset":"bindings"})
    assert response.status_code == 200
    assert response.json()["data"]["rows"][0]["source_craftsman_uid"] == "craft"
    assert "never-export" not in response.text and "private-name" not in response.text


def test_sale_time_precedence_and_shanghai_boundaries(client, evidence, db_session):
    start = datetime(2026, 9, 3, 16, tzinfo=timezone.utc)
    end = start + timedelta(days=7)
    for oid, sale, pay in [("fallback", None, start), ("at-start", start, None),
                            ("at-end", end, start), ("before", start-timedelta(seconds=1), start)]:
        db_session.add(RawDouyinOrder(order_id=oid, sku_id="JC", sale_time=sale, pay_time=pay))
    db_session.commit()
    rows = client.get(URL, params=PARAMS).json()["data"]["rows"]
    ids = {row["order_id"] for row in rows}
    assert {"fallback", "at-start"} <= ids
    assert not {"at-end", "before"} & ids
