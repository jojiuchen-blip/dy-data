from __future__ import annotations

from datetime import datetime, timezone
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from apps.api.dy_api.models import User, UserStoreScope

from dy_api.auth import AuthContext, create_session_token
from dy_api.cli_auth import (
    create_cli_access_token,
    get_current_cli_user,
    hash_cli_secret,
    verify_cli_access_payload,
)
from dy_api.main import create_app


def _request(*, authorization: str | None = None, cookie: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if authorization is not None:
        headers.append((b"authorization", authorization.encode("ascii")))
    if cookie is not None:
        headers.append((b"cookie", cookie.encode("ascii")))
    return Request({"type": "http", "headers": headers})


def _active_user(db_session, *, status: str = "active") -> User:
    user = User(
        user_id="user-1",
        username="store-user",
        external_account_id="store-1",
        display_name="Store User",
        role="store",
        status=status,
        is_initialized=True,
        password_hash="unused",
    )
    db_session.add_all(
        [
            user,
            UserStoreScope(user_id="user-1", store_id="current-store"),
        ]
    )
    db_session.commit()
    return user


def test_cli_access_token_reloads_current_user_scope(monkeypatch, db_session) -> None:
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    _active_user(db_session)
    issued_auth = AuthContext(
        user_id="user-1",
        username="store-user",
        display_name="Stale Name",
        role="admin",
        store_ids=("historic-store",),
        auth_type="user",
    )
    access_token, _ = create_cli_access_token(issued_auth)

    current_auth = get_current_cli_user(
        _request(authorization=f"Bearer {access_token}"), db_session
    )

    assert current_auth == AuthContext(
        user_id="user-1",
        username="store-user",
        display_name="Store User",
        role="store",
        store_ids=("current-store",),
        auth_type="user",
    )


def test_disabled_user_cli_token_is_rejected(monkeypatch, db_session) -> None:
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    user = _active_user(db_session)
    access_token, _ = create_cli_access_token(
        AuthContext(
            user_id=user.user_id,
            username=user.username,
            display_name=user.display_name,
            role=user.role,
            store_ids=("current-store",),
            auth_type="user",
        )
    )
    user.status = "disabled"
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        get_current_cli_user(
            _request(authorization=f"Bearer {access_token}"), db_session
        )

    assert exc_info.value.status_code == 401


def test_web_session_dependency_rejects_cli_bearer(monkeypatch) -> None:
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    access_token, _ = create_cli_access_token(
        AuthContext(
            user_id=None,
            username="system-admin",
            display_name="system-admin",
            role="admin",
            store_ids=(),
            auth_type="env_admin",
        )
    )

    response = TestClient(create_app()).get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"}
    )

    assert response.status_code == 401


def test_web_session_dependency_rejects_cli_token_cookie(monkeypatch) -> None:
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    monkeypatch.setenv("DY_SUPER_ADMIN_USERNAME", "system-admin")
    monkeypatch.setenv("DY_TEST_ADMIN_PASSWORD", "test-password")
    access_token, _ = create_cli_access_token(
        AuthContext(
            user_id=None,
            username="system-admin",
            display_name="system-admin",
            role="admin",
            store_ids=(),
            auth_type="env_admin",
        )
    )
    client = TestClient(create_app())
    client.cookies.set("dy_session", access_token)

    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401


def test_cli_dependency_rejects_web_cookie(monkeypatch, db_session) -> None:
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    session_token = create_session_token("system-admin", auth_type="env_admin")

    with pytest.raises(HTTPException) as exc_info:
        get_current_cli_user(
            _request(cookie=f"dy_session={session_token}"), db_session
        )

    assert exc_info.value.status_code == 401


def test_cli_access_payload_has_fixed_type_scope_and_expiry(monkeypatch) -> None:
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    now = datetime(2026, 7, 21, 8, 0, tzinfo=timezone.utc)
    access_token, expires_at = create_cli_access_token(
        AuthContext(
            user_id="user-1",
            username="store-user",
            display_name="Store User",
            role="store",
            store_ids=("must-not-be-stored",),
            auth_type="user",
        ),
        now=now,
    )

    payload = verify_cli_access_payload(access_token, now=now)

    assert payload is not None
    assert payload["typ"] == "cli_access"
    assert payload["scope"] == "cli:read"
    assert "uid" not in payload
    assert "user_id" not in payload
    assert "user-1" not in payload.values()
    assert isinstance(payload["jti"], str) and payload["jti"]
    assert "store_ids" not in payload
    assert expires_at == datetime(2026, 7, 21, 8, 30, tzinfo=timezone.utc)
    assert verify_cli_access_payload(access_token, now=expires_at) is None


def test_environment_admin_cli_token_revalidates_current_username(
    monkeypatch, db_session
) -> None:
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    monkeypatch.setenv("DY_SUPER_ADMIN_USERNAME", "system-admin")
    monkeypatch.setenv("DY_TEST_ADMIN_PASSWORD", "test-password")
    access_token, _ = create_cli_access_token(
        AuthContext(
            user_id=None,
            username="system-admin",
            display_name="system-admin",
            role="admin",
            store_ids=(),
            auth_type="env_admin",
        )
    )
    request = _request(authorization=f"Bearer {access_token}")

    current_auth = get_current_cli_user(request, db_session)
    assert current_auth.auth_type == "env_admin"
    assert current_auth.is_highest_admin

    monkeypatch.setenv("DY_SUPER_ADMIN_USERNAME", "new-admin")
    with pytest.raises(HTTPException) as exc_info:
        get_current_cli_user(request, db_session)
    assert exc_info.value.status_code == 401


def test_hash_cli_secret_is_stable_sha256() -> None:
    assert hash_cli_secret("secret") == (
        "2bb80d537b1da3e38bd30361aa855686bde0eacd7"
        "162fef6a25fe97bf527a25b"
    )
