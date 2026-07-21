from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from apps.api.dy_api.models import DimStore, User, UserStoreScope  # noqa: E402
from dy_api.auth import hash_password_pbkdf2  # noqa: E402
from dy_api.access_control import required_page_key_for_api_path  # noqa: E402
from dy_api.main import create_app  # noqa: E402
from dy_api.routes._data import get_session_dependency  # noqa: E402


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, db_session: Session) -> TestClient:
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    monkeypatch.setenv("DY_SUPER_ADMIN_USERNAME", "system-admin")
    monkeypatch.setenv("DY_TEST_ADMIN_PASSWORD", "test-password")
    monkeypatch.setenv("DY_SESSION_COOKIE_SECURE", "false")
    db_session.add_all(
        [
            DimStore(store_id="store-1", store_name="Store One", is_active=True),
            DimStore(store_id="store-2", store_name="Store Two", is_active=True),
            User(
                user_id="db-admin",
                username="db-admin",
                display_name="Database Admin",
                role="admin",
                status="active",
                is_initialized=True,
                password_hash=hash_password_pbkdf2("secret"),
                store_scope_mode="all",
            ),
            User(
                user_id="store-user",
                username="store-user",
                display_name="Store User",
                role="store",
                status="active",
                is_initialized=True,
                password_hash=hash_password_pbkdf2("secret"),
                store_scope_mode="specified",
            ),
            UserStoreScope(user_id="store-user", store_id="store-1"),
        ]
    )
    db_session.commit()
    app = create_app()

    def override_session():
        yield db_session

    app.dependency_overrides[get_session_dependency] = override_session
    return TestClient(app)


def _login(client: TestClient, username: str, password: str = "secret") -> None:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200


def test_highest_admin_can_read_page_registry_and_role_defaults(client: TestClient) -> None:
    _login(client, "system-admin", "test-password")

    response = client.get("/api/v1/admin/access-control")

    assert response.status_code == 200
    data = response.json()["data"]
    assert [row["page_key"] for row in data["pages"]] == [
        "A01", "A02", "B01", "B02", "B03", "C01",
        "D01", "D02", "D03", "D04", "D05", "D06", "D07", "D08", "D09", "D10",
    ]
    assert data["role_permissions"]["highest_admin"] == [row["page_key"] for row in data["pages"]]
    assert "D02" in data["role_permissions"]["admin"]
    assert data["role_permissions"]["store"] == ["A01", "A02", "B01", "B02", "B03", "C01"]


def test_admin_can_manage_store_accounts_but_not_admin_accounts(client: TestClient) -> None:
    _login(client, "db-admin")

    created = client.post(
        "/api/v1/admin/accounts",
        json={
            "username": "store-two",
            "display_name": "Store Two",
            "role": "store",
            "status": "active",
            "store_scope_mode": "specified",
            "store_ids": ["store-2"],
            "password": "store-pass",
            "password_confirm": "store-pass",
        },
    )
    assert created.status_code == 200

    forbidden = client.put(
        "/api/v1/admin/accounts/db-admin",
        json={
            "username": "db-admin",
            "display_name": "Database Admin",
            "role": "admin",
            "status": "active",
            "store_scope_mode": "all",
            "store_ids": [],
        },
    )
    assert forbidden.status_code == 403


def test_empty_store_scope_is_never_treated_as_all_stores(client: TestClient) -> None:
    _login(client, "system-admin", "test-password")

    response = client.post(
        "/api/v1/admin/accounts",
        json={
            "username": "empty-scope",
            "display_name": "Empty Scope",
            "role": "store",
            "status": "active",
            "store_scope_mode": "specified",
            "store_ids": [],
            "password": "store-pass",
            "password_confirm": "store-pass",
        },
    )

    assert response.status_code == 422


def test_page_override_is_effective_immediately_and_is_audited(client: TestClient) -> None:
    _login(client, "system-admin", "test-password")
    updated = client.put(
        "/api/v1/admin/accounts/store-user/page-permissions",
        json={"extra_allow": ["D09"], "extra_deny": ["B03"]},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["effective_page_keys"] == [
        "A01", "A02", "B01", "B02", "C01", "D09"
    ]

    audits = client.get(
        "/api/v1/admin/access-control/audit-logs",
        params={"target_user_id": "store-user"},
    )
    assert audits.status_code == 200
    assert audits.json()["data"]["rows"][0]["action"] == "account.page_permissions.updated"

    client.post("/api/v1/auth/logout")
    _login(client, "store-user")
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["data"]["page_keys"] == ["A01", "A02", "B01", "B02", "C01", "D09"]
    assert client.get("/api/v1/order-details").status_code == 403


def test_highest_admin_cannot_disable_or_downgrade_self(client: TestClient) -> None:
    _login(client, "system-admin", "test-password")
    response = client.put(
        "/api/v1/admin/accounts/environment-admin",
        json={
            "username": "system-admin",
            "display_name": "System Admin",
            "role": "admin",
            "status": "disabled",
            "store_scope_mode": "all",
            "store_ids": [],
        },
    )
    assert response.status_code in {403, 404}


def test_all_current_business_api_families_are_registered_and_unknown_defaults_to_deny() -> None:
    assert required_page_key_for_api_path("/api/v1/clues/overview") == "A01"
    assert required_page_key_for_api_path("/api/v1/clues/orders/1") == "A02"
    assert required_page_key_for_api_path("/api/v1/dashboard/store-ranking") == "B01"
    assert required_page_key_for_api_path("/api/v1/commission-rules/summary") is None
    assert required_page_key_for_api_path("/api/v1/stores/1/monthly-settlement") == "B02"
    assert required_page_key_for_api_path("/api/v1/order-details/export") == "B03"
    assert required_page_key_for_api_path("/api/v1/dashboard/sales") == "C01"
    assert required_page_key_for_api_path("/api/v1/admin/accounts") == "D02"
    assert required_page_key_for_api_path("/api/v1/future-business-page") == "__UNREGISTERED__"


def test_role_default_change_updates_inheritors_and_preserves_customized_effective_permissions(
    client: TestClient,
) -> None:
    _login(client, "system-admin", "test-password")
    customized_before = client.put(
        "/api/v1/admin/accounts/store-user/page-permissions",
        json={"extra_allow": [], "extra_deny": ["B03"]},
    )
    assert customized_before.status_code == 200
    expected_effective = customized_before.json()["data"]["effective_page_keys"]

    preview = client.post(
        "/api/v1/admin/access-control/roles/store/preview",
        json={"page_keys": ["A01", "B01", "D09"], "confirmed": False},
    )
    assert preview.status_code == 200
    assert preview.json()["data"] == {
        "role": "store",
        "page_keys": ["A01", "B01", "D09"],
        "inheriting_user_count": 0,
        "customized_user_count": 1,
    }

    updated = client.put(
        "/api/v1/admin/access-control/roles/store",
        json={"page_keys": ["A01", "B01", "D09"], "confirmed": True},
    )
    assert updated.status_code == 200
    accounts = client.get("/api/v1/admin/accounts").json()["data"]["rows"]
    store_user = next(row for row in accounts if row["user_id"] == "store-user")
    assert store_user["effective_page_keys"] == expected_effective
    assert store_user["extra_allow"] == ["A02", "B02", "C01"]
    assert store_user["extra_deny"] == ["D09"]


def test_admin_with_specified_store_scope_does_not_receive_global_data_access(
    client: TestClient,
) -> None:
    _login(client, "system-admin", "test-password")
    updated = client.put(
        "/api/v1/admin/accounts/db-admin",
        json={
            "username": "db-admin",
            "display_name": "Database Admin",
            "role": "admin",
            "status": "active",
            "store_scope_mode": "specified",
            "store_ids": ["store-1"],
        },
    )
    assert updated.status_code == 200
    client.post("/api/v1/auth/logout")
    _login(client, "db-admin")

    filters = client.get("/api/v1/meta/filters")

    assert filters.status_code == 200
    assert filters.json()["data"]["stores"] == [
        {"store_id": "store-1", "store_name": "Store One"}
    ]
