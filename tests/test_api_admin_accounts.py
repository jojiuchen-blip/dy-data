from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from apps.api.dy_api.models import DimStore  # noqa: E402
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
            DimStore(
                store_id="store-1",
                store_name="Store One",
                certified_subject_name="Subject One",
                is_active=True,
            ),
            DimStore(
                store_id="store-2",
                store_name="Store Two",
                certified_subject_name="Subject Two",
                is_active=True,
            ),
        ]
    )
    db_session.commit()
    app = create_app()

    def override_session():
        yield db_session

    app.dependency_overrides[get_session_dependency] = override_session
    return TestClient(app)


def _login_admin(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "system-admin", "password": "test-password"},
    )
    assert response.status_code == 200


def test_admin_can_manage_store_account(client: TestClient) -> None:
    assert client.get("/api/v1/admin/accounts").status_code == 401
    _login_admin(client)

    created = client.post(
        "/api/v1/admin/accounts",
        json={
            "username": "store-one",
            "external_account_id": "store-1",
            "display_name": "Store One",
            "role": "store",
            "status": "active",
            "store_ids": ["store-1"],
            "password": "first-pass",
            "password_confirm": "first-pass",
        },
    )
    assert created.status_code == 200
    user_id = created.json()["data"]["user_id"]
    assert created.json()["data"]["stores"] == [
        {"store_id": "store-1", "store_name": "Store One"}
    ]

    updated = client.put(
        f"/api/v1/admin/accounts/{user_id}",
        json={
            "username": "store-one",
            "external_account_id": "store-1",
            "display_name": "Store One Multi",
            "role": "store",
            "status": "active",
            "store_ids": ["store-1", "store-2"],
        },
    )
    assert updated.status_code == 200
    assert [row["store_id"] for row in updated.json()["data"]["stores"]] == [
        "store-1",
        "store-2",
    ]

    reset = client.post(
        f"/api/v1/admin/accounts/{user_id}/reset-password",
        json={"password": "second-pass", "password_confirm": "second-pass"},
    )
    assert reset.status_code == 200

    client.post("/api/v1/auth/logout")
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "store-one", "password": "second-pass"},
    )
    assert login.status_code == 200
    assert login.json()["data"]["store_ids"] == ["store-1", "store-2"]


def test_admin_can_create_global_viewer_without_store_scopes(client: TestClient) -> None:
    _login_admin(client)

    created = client.post(
        "/api/v1/admin/accounts",
        json={
            "username": "viewer-one",
            "external_account_id": None,
            "display_name": "Viewer One",
            "role": "viewer",
            "status": "active",
            "store_ids": ["store-1"],
            "password": "viewer-pass",
            "password_confirm": "viewer-pass",
        },
    )

    assert created.status_code == 200
    assert created.json()["data"]["role"] == "viewer"
    assert created.json()["data"]["stores"] == []

    client.post("/api/v1/auth/logout")
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "viewer-one", "password": "viewer-pass"},
    )
    assert login.status_code == 200
    assert login.json()["data"]["role"] == "viewer"
