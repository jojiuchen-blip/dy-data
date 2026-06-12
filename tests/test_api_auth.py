from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from dy_api.auth import hash_password_pbkdf2  # noqa: E402
from dy_api.main import create_app  # noqa: E402


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    monkeypatch.setenv("DY_TEST_ADMIN_PASSWORD", "test-password")
    monkeypatch.setenv("DY_SESSION_COOKIE_SECURE", "false")
    monkeypatch.setenv("DY_SESSION_COOKIE_SAMESITE", "lax")
    monkeypatch.delenv("DY_ADMIN_PASSWORD_HASH", raising=False)
    return TestClient(create_app())


def test_login_sets_http_only_cookie_and_logout_clears_session(client: TestClient):
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "test-password"},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {"username": "admin"}
    set_cookie = response.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "secure" not in set_cookie

    assert client.get("/api/v1/auth/me").status_code == 200

    logout = client.post("/api/v1/auth/logout")
    assert logout.status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401


def test_login_rejects_wrong_password(client: TestClient):
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "wrong"},
    )

    assert response.status_code == 401


def test_password_hash_env_is_supported_without_test_fallback(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("DY_API_TEST_MODE", "false")
    monkeypatch.setenv("DY_SESSION_COOKIE_SECURE", "false")
    monkeypatch.setenv("DY_SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("DY_ADMIN_PASSWORD_HASH", hash_password_pbkdf2("s3cret"))

    client = TestClient(create_app())

    wrong = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin"}
    )
    assert wrong.status_code == 401

    ok = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "s3cret"}
    )
    assert ok.status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 200


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v1/auth/me"),
        ("post", "/api/v1/auth/logout"),
        ("get", "/api/v1/meta/filters"),
        ("get", "/api/v1/dashboard/store-ranking?month=2026-05"),
        ("get", "/api/v1/stores/store_001/monthly-settlement?month=2026-05"),
        ("get", "/api/v1/order-details"),
        ("get", "/api/v1/order-details/export"),
        ("get", "/api/v1/jobs/recent"),
    ],
)
def test_protected_endpoints_return_401_without_session(
    client: TestClient, method: str, path: str
):
    response = getattr(client, method)(path)

    assert response.status_code == 401
