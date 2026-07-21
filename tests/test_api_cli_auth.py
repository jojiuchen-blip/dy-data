from __future__ import annotations

from datetime import timedelta
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from apps.api.dy_api.models import (  # noqa: E402
    CliDeviceAuthorization,
    CliRefreshToken,
    User,
    UserStoreScope,
    utcnow,
)
from apps.api.dy_api.user_auth_state import replace_user_store_scopes  # noqa: E402
from dy_api.auth import create_session_token  # noqa: E402
from dy_api.cli_auth import hash_cli_secret  # noqa: E402
from dy_api.main import create_app  # noqa: E402
from dy_api.routes._data import get_session_dependency  # noqa: E402


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, db_session) -> TestClient:
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    monkeypatch.setenv("DY_SUPER_ADMIN_USERNAME", "system-admin")
    monkeypatch.setenv("DY_TEST_ADMIN_PASSWORD", "test-password")
    monkeypatch.setenv("DY_SESSION_COOKIE_SECURE", "false")
    monkeypatch.delenv("DY_WEB_BASE_URL", raising=False)
    app = create_app()

    def override_session():
        yield db_session

    app.dependency_overrides[get_session_dependency] = override_session
    return TestClient(app)


def _add_user(db_session) -> User:
    user = User(
        user_id="user-1",
        username="store-user",
        external_account_id="store-1",
        display_name="Store User",
        role="store",
        status="active",
        is_initialized=True,
        password_hash="unused",
    )
    db_session.add_all(
        [
            user,
            UserStoreScope(user_id="user-1", store_id="store-1"),
        ]
    )
    db_session.commit()
    return user


def _set_user_cookie(client: TestClient, user: User) -> None:
    client.cookies.set(
        "dy_session",
        create_session_token(
            user.username,
            user_id=user.user_id,
            role=user.role,
            auth_type="user",
        ),
    )


def _approve_and_exchange(client: TestClient, db_session) -> dict:
    user = _add_user(db_session)
    started = client.post("/api/v1/auth/cli/device/start")
    assert started.status_code == 200
    start_data = started.json()
    _set_user_cookie(client, user)

    spaced_lower_code = " ".join(start_data["user_code"].lower())
    approved = client.post(
        "/api/v1/auth/cli/device/approve",
        json={"user_code": spaced_lower_code},
    )
    assert approved.status_code == 200
    assert approved.json() == {"status": "approved"}

    exchanged = client.post(
        "/api/v1/auth/cli/device/token",
        json={"device_code": start_data["device_code"]},
    )
    assert exchanged.status_code == 200
    return {"started": start_data, "tokens": exchanged.json(), "user": user}


def test_device_start_returns_browser_urls_and_only_persists_hashes(
    client: TestClient, db_session
) -> None:
    response = client.post("/api/v1/auth/cli/device/start")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "device_code",
        "user_code",
        "verification_uri",
        "verification_uri_complete",
        "expires_in",
        "interval",
    }
    assert body["verification_uri"] == "http://testserver/auth/cli/authorize"
    assert body["verification_uri_complete"] == (
        f"http://testserver/auth/cli/authorize?user_code={body['user_code']}"
    )
    assert body["expires_in"] == 600
    assert body["interval"] == 3

    grant = db_session.execute(select(CliDeviceAuthorization)).scalar_one()
    assert grant.device_code_hash == hash_cli_secret(body["device_code"])
    assert grant.user_code_hash == hash_cli_secret(body["user_code"])
    assert grant.device_code_hash != body["device_code"]
    assert grant.user_code_hash != body["user_code"]


def test_device_start_prefers_configured_web_base_url(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    monkeypatch.setenv("DY_WEB_BASE_URL", "https://portal.example.test/base/")

    body = client.post("/api/v1/auth/cli/device/start").json()

    assert body["verification_uri"] == (
        "https://portal.example.test/base/auth/cli/authorize"
    )


def test_device_start_uses_request_origin_without_proxy_root_path(
    client: TestClient,
) -> None:
    proxy_client = TestClient(
        client.app,
        base_url="https://edge.example.test",
        root_path="/api-proxy",
    )

    body = proxy_client.post("/api/v1/auth/cli/device/start").json()

    assert body["verification_uri"] == (
        "https://edge.example.test/auth/cli/authorize"
    )


def test_device_start_rejects_host_fallback_in_production(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    db_session,
) -> None:
    monkeypatch.setenv("DY_API_TEST_MODE", "false")
    monkeypatch.delenv("DY_WEB_BASE_URL", raising=False)

    response = client.post(
        "/api/v1/auth/cli/device/start",
        headers={"Host": "attacker.example"},
    )

    assert response.status_code == 503
    assert "DY_WEB_BASE_URL" in response.json()["detail"]
    assert (
        db_session.execute(select(CliDeviceAuthorization)).scalar_one_or_none()
        is None
    )


@pytest.mark.parametrize(
    "unsafe_base_url",
    ["http://portal.example.test", "https:///missing-host"],
)
def test_device_start_rejects_unsafe_production_web_base_url(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    unsafe_base_url: str,
) -> None:
    monkeypatch.setenv("DY_API_TEST_MODE", "false")
    monkeypatch.setenv("DY_WEB_BASE_URL", unsafe_base_url)

    response = client.post("/api/v1/auth/cli/device/start")

    assert response.status_code == 503
    assert "https URL with a hostname" in response.json()["detail"]


def test_device_token_pending_then_approved_grant_is_consumed_once(
    client: TestClient, db_session
) -> None:
    user = _add_user(db_session)
    started = client.post("/api/v1/auth/cli/device/start").json()

    pending = client.post(
        "/api/v1/auth/cli/device/token",
        json={"device_code": started["device_code"]},
    )
    assert pending.status_code == 202
    assert pending.json() == {"status": "authorization_pending"}

    _set_user_cookie(client, user)
    approval = client.post(
        "/api/v1/auth/cli/device/approve",
        json={"user_code": started["user_code"]},
    )
    assert approval.status_code == 200

    token_response = client.post(
        "/api/v1/auth/cli/device/token",
        json={"device_code": started["device_code"]},
    )
    assert token_response.status_code == 200
    tokens = token_response.json()
    assert set(tokens) == {
        "access_token",
        "refresh_token",
        "token_type",
        "scope",
        "expires_in",
        "access_token_expires_at",
    }
    assert tokens["token_type"] == "Bearer"
    assert tokens["scope"] == "cli:read"
    assert tokens["expires_in"] == 1800
    assert "store_ids" not in tokens

    grant = db_session.execute(select(CliDeviceAuthorization)).scalar_one()
    db_session.refresh(grant)
    assert grant.status == "consumed"
    assert grant.consumed_at is not None
    refresh = db_session.execute(select(CliRefreshToken)).scalar_one()
    assert refresh.token_hash == hash_cli_secret(tokens["refresh_token"])
    assert refresh.token_hash != tokens["refresh_token"]
    assert refresh.issued_auth_generation == user.auth_generation

    repeated = client.post(
        "/api/v1/auth/cli/device/token",
        json={"device_code": started["device_code"]},
    )
    assert repeated.status_code == 400


def test_expired_and_unknown_device_codes_do_not_issue_tokens(
    client: TestClient, db_session
) -> None:
    started = client.post("/api/v1/auth/cli/device/start").json()
    grant = db_session.execute(select(CliDeviceAuthorization)).scalar_one()
    grant.expires_at = utcnow() - timedelta(seconds=1)
    db_session.commit()

    expired = client.post(
        "/api/v1/auth/cli/device/token",
        json={"device_code": started["device_code"]},
    )
    unknown = client.post(
        "/api/v1/auth/cli/device/token",
        json={"device_code": "not-a-device-code"},
    )

    assert expired.status_code == 400
    assert unknown.status_code == 400
    assert db_session.execute(select(CliRefreshToken)).scalar_one_or_none() is None


def test_approved_device_grant_cannot_move_to_reused_username(
    client: TestClient, db_session
) -> None:
    original_user = _add_user(db_session)
    started = client.post("/api/v1/auth/cli/device/start").json()
    _set_user_cookie(client, original_user)
    approved = client.post(
        "/api/v1/auth/cli/device/approve",
        json={"user_code": started["user_code"]},
    )
    assert approved.status_code == 200

    original_user.username = "renamed-user"
    db_session.commit()
    db_session.add(
        User(
            user_id="user-2",
            username="store-user",
            external_account_id="store-2",
            display_name="Replacement User",
            role="viewer",
            status="active",
            is_initialized=True,
            password_hash="unused",
        )
    )
    db_session.commit()

    response = client.post(
        "/api/v1/auth/cli/device/token",
        json={"device_code": started["device_code"]},
    )

    assert response.status_code == 401
    assert db_session.execute(select(CliRefreshToken)).scalar_one_or_none() is None


def test_refresh_rotates_once_and_reloads_active_user(
    client: TestClient, db_session
) -> None:
    flow = _approve_and_exchange(client, db_session)
    old_refresh_token = flow["tokens"]["refresh_token"]

    response = client.post(
        "/api/v1/auth/cli/token/refresh",
        json={"refresh_token": old_refresh_token},
    )

    assert response.status_code == 200
    replacement = response.json()
    assert replacement["refresh_token"] != old_refresh_token
    assert replacement["scope"] == "cli:read"
    old_row = db_session.execute(
        select(CliRefreshToken).where(
            CliRefreshToken.token_hash == hash_cli_secret(old_refresh_token)
        )
    ).scalar_one()
    db_session.refresh(old_row)
    assert old_row.revoked_at is not None
    assert old_row.replaced_by_token_id is not None

    repeated = client.post(
        "/api/v1/auth/cli/token/refresh",
        json={"refresh_token": old_refresh_token},
    )
    assert repeated.status_code == 401


def test_disabled_user_cannot_refresh(client: TestClient, db_session) -> None:
    flow = _approve_and_exchange(client, db_session)
    flow["user"].status = "disabled"
    db_session.commit()

    response = client.post(
        "/api/v1/auth/cli/token/refresh",
        json={"refresh_token": flow["tokens"]["refresh_token"]},
    )

    assert response.status_code == 401


def test_store_scope_change_revokes_existing_refresh_token(
    client: TestClient, db_session
) -> None:
    flow = _approve_and_exchange(client, db_session)
    refresh_token = flow["tokens"]["refresh_token"]
    replace_user_store_scopes(db_session, flow["user"].user_id, ["store-2"])
    db_session.commit()

    response = client.post(
        "/api/v1/auth/cli/token/refresh",
        json={"refresh_token": refresh_token},
    )

    assert response.status_code == 401
    stored = db_session.execute(
        select(CliRefreshToken).where(
            CliRefreshToken.token_hash == hash_cli_secret(refresh_token)
        )
    ).scalar_one()
    db_session.refresh(stored)
    assert stored.revoked_at is not None


@pytest.mark.parametrize(
    ("field_name", "changed_value"),
    [("role", "viewer"), ("password_hash", "changed-password-hash")],
)
def test_role_or_credential_change_revokes_existing_refresh_token(
    client: TestClient,
    db_session,
    field_name: str,
    changed_value: str,
) -> None:
    flow = _approve_and_exchange(client, db_session)
    refresh_token = flow["tokens"]["refresh_token"]
    setattr(flow["user"], field_name, changed_value)
    db_session.commit()

    response = client.post(
        "/api/v1/auth/cli/token/refresh",
        json={"refresh_token": refresh_token},
    )

    assert response.status_code == 401
    stored = db_session.execute(
        select(CliRefreshToken).where(
            CliRefreshToken.token_hash == hash_cli_secret(refresh_token)
        )
    ).scalar_one()
    db_session.refresh(stored)
    assert stored.revoked_at is not None


def test_failed_disabled_refresh_stays_revoked_after_user_is_reenabled(
    client: TestClient, db_session
) -> None:
    flow = _approve_and_exchange(client, db_session)
    refresh_token = flow["tokens"]["refresh_token"]
    flow["user"].status = "disabled"
    db_session.commit()

    disabled_response = client.post(
        "/api/v1/auth/cli/token/refresh",
        json={"refresh_token": refresh_token},
    )
    assert disabled_response.status_code == 401
    stored = db_session.execute(
        select(CliRefreshToken).where(
            CliRefreshToken.token_hash == hash_cli_secret(refresh_token)
        )
    ).scalar_one()
    db_session.refresh(stored)
    assert stored.revoked_at is not None

    flow["user"].status = "active"
    db_session.commit()
    reenabled_response = client.post(
        "/api/v1/auth/cli/token/refresh",
        json={"refresh_token": refresh_token},
    )
    assert reenabled_response.status_code == 401


def test_disable_then_reenable_before_first_refresh_invalidates_old_token(
    client: TestClient, db_session
) -> None:
    flow = _approve_and_exchange(client, db_session)
    refresh_token = flow["tokens"]["refresh_token"]

    flow["user"].status = "disabled"
    db_session.commit()
    flow["user"].status = "active"
    db_session.commit()

    response = client.post(
        "/api/v1/auth/cli/token/refresh",
        json={"refresh_token": refresh_token},
    )

    assert response.status_code == 401


def test_store_scope_round_trip_before_first_refresh_invalidates_old_token(
    client: TestClient, db_session
) -> None:
    flow = _approve_and_exchange(client, db_session)
    refresh_token = flow["tokens"]["refresh_token"]
    user_id = flow["user"].user_id

    replace_user_store_scopes(db_session, user_id, ["store-2"])
    db_session.commit()
    replace_user_store_scopes(db_session, user_id, ["store-1"])
    db_session.commit()

    response = client.post(
        "/api/v1/auth/cli/token/refresh",
        json={"refresh_token": refresh_token},
    )

    assert response.status_code == 401


def test_revoke_is_idempotent_and_never_echoes_token(
    client: TestClient, db_session
) -> None:
    flow = _approve_and_exchange(client, db_session)
    refresh_token = flow["tokens"]["refresh_token"]

    first = client.post(
        "/api/v1/auth/cli/revoke", json={"refresh_token": refresh_token}
    )
    second = client.post(
        "/api/v1/auth/cli/revoke", json={"refresh_token": refresh_token}
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == {"status": "revoked"}
    assert refresh_token not in first.text
    rejected = client.post(
        "/api/v1/auth/cli/token/refresh",
        json={"refresh_token": refresh_token},
    )
    assert rejected.status_code == 401
