"""Control origins across an HTTPS public site and an HTTP internal proxy."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from test_api_admin_sync_control_plane import _login, control_client  # noqa: F401
from apps.api.dy_api.models import OpsCommand, User
from dy_api.routes import operations


PUBLIC_ORIGIN = "https://control.example.invalid"
COMMAND_PATH = "/api/v1/admin/operations/commands"
PAYLOAD = {
    "command_type": "restart",
    "target_component": "browser",
    "reason": "synthetic origin contract verification",
    "confirmed": True,
}


@pytest.fixture()
def origin_client(control_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.delenv("DY_API_CORS_ORIGINS", raising=False)
    monkeypatch.delenv("DY_WEB_BASE_URL", raising=False)
    _login(control_client, "system-admin", "test-password")
    return control_client


def _post(client: TestClient, **headers: str):
    return client.post(COMMAND_PATH, json=PAYLOAD, headers={
        "Idempotency-Key": "synthetic-origin-restart-browser",
        "Sec-Fetch-Site": "same-origin",
        **headers,
    })


def _command_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(OpsCommand))


@pytest.mark.parametrize(("configured", "origin"), [
    (PUBLIC_ORIGIN, PUBLIC_ORIGIN),
    ("https://CONTROL.example.invalid:443/dashboard/", PUBLIC_ORIGIN),
    ("https://control.example.invalid:8443/dashboard", PUBLIC_ORIGIN + ":8443"),
])
def test_proxied_https_public_origin_creates_one_idempotent_command(
    origin_client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch,
    configured: str, origin: str,
) -> None:
    monkeypatch.setenv("DY_WEB_BASE_URL", configured)
    assert str(origin_client.base_url) == "http://testserver"
    first = _post(origin_client, Origin=origin)
    replay = _post(origin_client, Origin=origin)
    assert first.status_code == replay.status_code == 200
    assert first.json()["data"]["status"] == "pending"
    assert replay.json()["data"]["command_id"] == first.json()["data"]["command_id"]
    assert replay.json()["data"]["replayed"] is True
    assert _command_count(db_session) == 1


@pytest.mark.parametrize("origin", [
    "http://control.example.invalid",
    "https://other.example.invalid",
    PUBLIC_ORIGIN + ":8443",
    PUBLIC_ORIGIN + ".attacker.invalid",
    "https://control-example.invalid",
    "https://control.example.invalid@attacker.invalid",
    "null",
])
def test_nonallowed_origin_and_forwarded_spoof_create_no_command(
    origin_client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch,
    origin: str,
) -> None:
    monkeypatch.setenv("DY_WEB_BASE_URL", PUBLIC_ORIGIN)
    response = _post(origin_client, Origin=origin, **{
        "X-Forwarded-Host": origin.removeprefix("https://"),
        "X-Forwarded-Proto": "https",
    })
    assert response.status_code == 403
    assert response.json()["detail"] == "Control request origin denied"
    assert _command_count(db_session) == 0


@pytest.mark.parametrize("configured", [
    "http://control.example.invalid", "//control.example.invalid", "https://",
    "https://user@control.example.invalid", "https://user:secret@control.example.invalid",
    "https://control.example.invalid:bad", "https://control.example.invalid:65536",
    "https://control.example.invalid:0", "https://bad host.invalid",
    "https://bad_host.invalid", "https://-bad.invalid", "https://bad..invalid",
    "https://127.0.0.999", "https://control.example.invalid\\attacker",
    "https://[fe80::1%25eth0]", "https://[2001:db8::1",
    "https://control.example.invalid\n", "https://control.example.invalid\t",
    "https://control.example.invalid?target=attacker", "https://control.example.invalid#fragment",
])
def test_invalid_server_origin_configuration_fails_closed_without_command(
    origin_client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch,
    configured: str,
) -> None:
    monkeypatch.setenv("DY_WEB_BASE_URL", configured)
    response = _post(origin_client, Origin=PUBLIC_ORIGIN)
    assert response.status_code == 503
    assert response.json()["detail"] == "Control origin configuration invalid"
    assert _command_count(db_session) == 0


def test_cross_site_remains_denied_for_configured_public_origin(
    origin_client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DY_WEB_BASE_URL", PUBLIC_ORIGIN)
    response = _post(origin_client, Origin=PUBLIC_ORIGIN, **{"Sec-Fetch-Site": "cross-site"})
    assert response.status_code == 403
    assert response.json()["detail"] == "Cross-site control request denied"
    assert _command_count(db_session) == 0


def test_public_origin_does_not_grant_limited_administrator_global_control(
    origin_client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = db_session.scalar(select(User).where(User.username == "ordinary-admin"))
    admin.store_scope_mode = "specified"
    db_session.commit()
    _login(origin_client, "ordinary-admin")
    monkeypatch.setenv("DY_WEB_BASE_URL", PUBLIC_ORIGIN)
    response = _post(origin_client, Origin=PUBLIC_ORIGIN)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "GLOBAL_WRITE_REQUIRED"
    assert _command_count(db_session) == 0


def test_public_origin_does_not_grant_anonymous_control(
    origin_client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    origin_client.cookies.clear()
    monkeypatch.setenv("DY_WEB_BASE_URL", PUBLIC_ORIGIN)
    assert _post(origin_client, Origin=PUBLIC_ORIGIN).status_code == 401
    assert _command_count(db_session) == 0


@pytest.mark.parametrize("configured", [None, "not-a-valid-server-origin"])
def test_existing_no_origin_compatibility_is_unchanged(
    origin_client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch,
    configured: str | None,
) -> None:
    if configured is not None:
        monkeypatch.setenv("DY_WEB_BASE_URL", configured)
    assert _post(origin_client).status_code == 200
    assert _command_count(db_session) == 1


def test_existing_explicit_cors_allowlist_remains_supported(
    origin_client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DY_API_CORS_ORIGINS", PUBLIC_ORIGIN)
    assert _post(origin_client, Origin=PUBLIC_ORIGIN).status_code == 200
    assert _command_count(db_session) == 1


@pytest.mark.parametrize(("configured", "expected"), [
    ("https://[2001:db8::1]:443/prefix", "https://[2001:db8::1]"),
    ("https://127.0.0.1:8443/prefix", "https://127.0.0.1:8443"),
    ("https://CONTROL.example.invalid:443/prefix", PUBLIC_ORIGIN),
])
def test_configured_origin_normalizes_valid_host_port_and_path(
    monkeypatch: pytest.MonkeyPatch, configured: str, expected: str,
) -> None:
    monkeypatch.setenv("DY_WEB_BASE_URL", configured)
    assert operations._configured_control_origin() == expected
