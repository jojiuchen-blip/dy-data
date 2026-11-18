from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from apps.api.dy_api.models import ClueAllocationAuditLog, ClueProductRoutingConfig, DimSkuProductRule, DimStore, User
from dy_api.auth import hash_password_pbkdf2
from dy_api.main import create_app
from dy_api.routes._data import get_session_dependency


BASE = "/api/v1/admin/clue-routing"


@pytest.fixture()
def client(monkeypatch, db_session):
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    monkeypatch.setenv("DY_SUPER_ADMIN_USERNAME", "routing-admin")
    monkeypatch.setenv("DY_TEST_ADMIN_PASSWORD", "test-routing-password")
    monkeypatch.setenv("DY_SESSION_COOKIE_SECURE", "false")
    db_session.add_all([
        DimSkuProductRule(sku_id="jc-sku", product_id="jc-product", product_name="JC", product_scope="精诚养车"),
        DimSkuProductRule(sku_id="byd-sku", product_id="byd-product", product_name="BYD", product_scope="比亚迪"),
        DimStore(store_id="0001", store_name="Store One"),
        User(user_id="product-owner", username="owner", display_name="Owner", role="store", store_scope_mode="none",
             status="active", is_initialized=True, password_hash=hash_password_pbkdf2("owner-password")),
    ])
    db_session.commit()
    app = create_app()
    def override_session():
        yield db_session
    app.dependency_overrides[get_session_dependency] = override_session
    return TestClient(app)


def _login(client, username="routing-admin", password="test-routing-password"):
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return response


def test_cookie_manager_can_reach_own_products_without_global_rule_write(client, db_session):
    _login(client)
    assert client.put(f"{BASE}/products/jc-product/grants", json={"user_ids": ["product-owner"]}).status_code == 200
    login = _login(client, "owner", "owner-password")
    assert "D05" in login.json()["data"]["page_keys"]
    response = client.get(f"{BASE}/products")
    assert response.status_code == 200
    assert [row["product_id"] for row in response.json()["data"]["rows"]] == ["jc-product"]
    assert not response.json()["data"]["can_manage_grants"]
    assert client.put(f"{BASE}/products/jc-product/grants", json={"user_ids": []}).status_code == 403
    assert client.get(f"{BASE}/shared-rule").status_code == 403
    old_global_write = client.post("/api/v1/admin/clue-allocation/rules", json={"name": "No", "scope": {"scope_type": "global"}})
    assert old_global_write.status_code == 403
    result = client.post(f"{BASE}/products/batch", json={"product_ids": ["jc-product", "byd-product"],
        "action": "publish_list", "store_ids": ["0001"], "preview": False})
    assert result.status_code == 200
    data = result.json()["data"]
    assert data["succeeded"] == data["failed"] == 1
    assert next(row for row in data["results"] if row["product_id"] == "byd-product")["before"] == {}
    db_session.expire_all()
    assert db_session.get(ClueProductRoutingConfig, "jc-product").routing_enabled is False


def test_list_publish_default_off_enable_needs_authorization_and_readback(client, db_session):
    _login(client)
    body = {"product_ids": ["byd-product"], "action": "publish_list", "store_ids": ["0001"], "preview": True}
    preview = client.post(f"{BASE}/products/batch", json=body)
    assert preview.status_code == 200
    assert preview.json()["data"]["results"][0]["status"] == "preview"
    assert db_session.get(ClueProductRoutingConfig, "byd-product") is None
    body["preview"] = False
    first = client.post(f"{BASE}/products/batch", json=body, headers={"Idempotency-Key": "api-list-v1"})
    assert first.status_code == 200
    again = client.post(f"{BASE}/products/batch", json=body, headers={"Idempotency-Key": "api-list-v1"})
    assert again.json()["data"] == first.json()["data"]
    assert db_session.scalar(select(func.count()).select_from(ClueAllocationAuditLog)) == 1
    assert client.get(f"{BASE}/products").json()["data"]["rows"][0]["routing_enabled"] is False
    failed = client.post(f"{BASE}/products/batch", json={"product_ids": ["byd-product"], "action": "enable", "preview": False})
    assert failed.json()["data"]["results"][0]["error"]["code"] == "AUTHORIZATION_REQUIRED"
    enabled = client.post(f"{BASE}/products/batch", json={"product_ids": ["byd-product"], "action": "enable", "preview": False,
        "authorization_note": "业务负责人核对有效名单并授权开启",
        "expected_list_versions": {"byd-product": first.json()["data"]["results"][0]["after"]["list_version"]}})
    assert enabled.json()["data"]["results"][0]["after"]["routing_enabled"] is True
    db_session.expire_all()
    assert db_session.get(ClueProductRoutingConfig, "byd-product").routing_enabled is True


def test_readonly_cli_and_mcp_bearers_cannot_manage_products(client):
    for token in ("readonly-cli-token", "readonly-mcp-token"):
        response = client.post(f"{BASE}/products/batch", headers={"Authorization": f"Bearer {token}"},
            json={"product_ids": ["jc-product"], "action": "disable", "preview": False})
        assert response.status_code == 401


def test_strict_field_patch_and_shared_base_contract(client):
    _login(client)
    assert client.put(f"{BASE}/shared-rule", json={"rules": {"first_follow_up_sla_hours": True}, "preview": True}).status_code == 422
    assert client.post(f"{BASE}/products/batch", json={"product_ids": ["jc-product"], "action": "publish_rule",
        "rules": {"arbitrary": 1}}).status_code == 422
    preview = client.put(f"{BASE}/shared-rule", json={"rules": {"first_follow_up_sla_hours": 48,
        "follow_up_policy": {"unreachable_action": "next"}}, "preview": True})
    assert preview.status_code == 200
    assert preview.json()["data"]["after"]["follow_up_policy"]["unreachable_action"] == "next"
    assert client.get(f"{BASE}/shared-rule").json()["data"]["rule_version_id"] is None
    publish = client.put(f"{BASE}/shared-rule", json={"rules": {"first_follow_up_sla_hours": 48}, "preview": False})
    assert publish.status_code == 200
    assert publish.json()["data"]["after"]["rule_version_id"]


def test_shared_maintainer_human_session_has_page_but_no_products_or_grant_management(client, db_session):
    _login(client)
    assert client.get(f"{BASE}/shared-rule/grants").json()["data"]["user_ids"] == []
    grants = client.put(f"{BASE}/shared-rule/grants", json={"user_ids": ["product-owner"]})
    assert grants.status_code == 200
    assert grants.json()["data"]["user_ids"] == ["product-owner"]
    assert "product_id" not in grants.json()["data"]
    identity = _login(client, "owner", "owner-password").json()["data"]
    assert identity["role"] == "store"
    assert "D05" in identity["page_keys"]
    listing = client.get(f"{BASE}/products")
    assert listing.status_code == 200
    data = listing.json()["data"]
    assert data["rows"] == [] and data["total"] == 0
    assert data["can_manage_shared_rule"] is True
    assert data["can_manage_grants"] is False
    assert client.get(f"{BASE}/shared-rule").json()["data"]["can_manage"] is True
    preview = client.put(f"{BASE}/shared-rule", json={"rules": {"first_follow_up_sla_hours": 48}, "preview": True})
    assert preview.status_code == 200 and preview.json()["data"]["status"] == "preview"
    assert client.get(f"{BASE}/shared-rule").json()["data"]["rule_version_id"] is None
    published = client.put(f"{BASE}/shared-rule", json={"rules": {"first_follow_up_sla_hours": 48}, "preview": False})
    assert published.status_code == 200
    assert published.json()["data"]["after"]["first_follow_up_sla_hours"] == 48
    assert client.get(f"{BASE}/shared-rule/grants").status_code == 403
    assert client.put(f"{BASE}/shared-rule/grants", json={"user_ids": []}).status_code == 403
    assert client.get(f"{BASE}/products/jc-product/grants").status_code == 403
    assert client.post("/api/v1/admin/clue-allocation/rules", json={"name": "No", "scope": {"scope_type": "global"}}).status_code == 403
    denied = client.post(f"{BASE}/products/batch", json={"product_ids": ["jc-product"], "action": "disable", "preview": False})
    assert denied.json()["data"]["results"][0]["error"]["code"] == "PRODUCT_FORBIDDEN"
    assert db_session.get(User, "product-owner").store_scope_mode == "none"
    _login(client)
    assert client.put(f"{BASE}/shared-rule/grants", json={"user_ids": []}).status_code == 200
    _login(client, "owner", "owner-password")
    assert client.get(f"{BASE}/shared-rule").status_code == 403
