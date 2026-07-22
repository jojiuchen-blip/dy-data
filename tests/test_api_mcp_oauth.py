from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import sys
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from apps.api.dy_api.models import (  # noqa: E402
    Base,
    McpAccessToken,
    McpAuthorizationRequest,
    McpOAuthClient,
    McpRefreshToken,
    User,
    utcnow,
)
from dy_api.cli_auth import _auth_context_for_user, hash_cli_secret  # noqa: E402
from dy_api.cli_auth import create_cli_access_token  # noqa: E402
from dy_api.cli_audit import DatabaseCliAuditSink  # noqa: E402
from dy_api.main import create_app  # noqa: E402
from dy_api.mcp_oauth import (  # noqa: E402
    MCP_ACCESS_SCOPE,
    MCP_RESOURCE_URL,
    TEST_ISSUER_URL,
    DatabaseMcpOAuthProvider,
    McpAccessAuthorizationError,
)
from dy_api.mcp_server import (  # noqa: E402
    DCR_MAX_BODY_BYTES,
    _read_limited_request_body,
)


@pytest.fixture()
def mcp_stack(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    monkeypatch.setenv("DY_SESSION_SECRET", "mcp-test-session-secret")
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )
    with factory() as session:
        session.add(
            User(
                user_id="mcp-user-1",
                username="mcp-store-user",
                external_account_id="mcp-store-1",
                display_name="MCP Store User",
                role="store",
                store_scope_mode="specified",
                status="active",
                is_initialized=True,
                password_hash="unused",
            )
        )
        session.commit()

    provider = DatabaseMcpOAuthProvider(session_factory=factory)
    app = create_app(mcp_provider=provider)
    app.state.cli_audit_sink = DatabaseCliAuditSink(session_factory=factory)
    with TestClient(app, base_url=TEST_ISSUER_URL) as client:
        yield client, provider, factory


def _register_public_client(client: TestClient) -> dict:
    response = client.post(
        "/register",
        json={
            "redirect_uris": ["https://agent.example/callback"],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "scope": MCP_ACCESS_SCOPE,
            "client_name": "Agent Test Client",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["token_endpoint_auth_method"] == "none"
    assert "client_secret" not in body
    return body


def _registration_payload(**overrides) -> dict:
    payload = {
        "redirect_uris": ["https://agent.example/callback"],
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "scope": MCP_ACCESS_SCOPE,
        "client_name": "Agent Test Client",
    }
    payload.update(overrides)
    return payload


def _pkce(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _authorize(
    client: TestClient,
    provider: DatabaseMcpOAuthProvider,
    factory: sessionmaker,
    client_id: str,
    *,
    verifier: str = "v" * 64,
) -> tuple[str, str]:
    response = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": "https://agent.example/callback",
            "scope": MCP_ACCESS_SCOPE,
            "state": "state-123",
            "code_challenge": _pkce(verifier),
            "code_challenge_method": "S256",
            "resource": MCP_RESOURCE_URL,
        },
        follow_redirects=False,
    )
    assert response.status_code == 302, response.text
    approval_url = urlsplit(response.headers["location"])
    assert f"{approval_url.scheme}://{approval_url.netloc}{approval_url.path}" == (
        f"{TEST_ISSUER_URL}/auth/mcp/authorize"
    )
    request_id = parse_qs(approval_url.query)["request_id"][0]

    with factory() as session:
        user = session.get(User, "mcp-user-1")
        assert user is not None
        auth = _auth_context_for_user(session, user)
    callback_url = asyncio.run(provider.approve_authorization(request_id, auth))
    callback = urlsplit(callback_url)
    assert f"{callback.scheme}://{callback.netloc}{callback.path}" == (
        "https://agent.example/callback"
    )
    callback_params = parse_qs(callback.query)
    assert callback_params["state"] == ["state-123"]
    return callback_params["code"][0], verifier


def _exchange_code(
    client: TestClient,
    client_id: str,
    code: str,
    verifier: str,
):
    return client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "redirect_uri": "https://agent.example/callback",
            "code_verifier": verifier,
            "resource": MCP_RESOURCE_URL,
        },
    )


def _issue_tokens(mcp_stack) -> tuple[TestClient, DatabaseMcpOAuthProvider, sessionmaker, str, dict]:
    client, provider, factory = mcp_stack
    registration = _register_public_client(client)
    code, verifier = _authorize(client, provider, factory, registration["client_id"])
    response = _exchange_code(client, registration["client_id"], code, verifier)
    assert response.status_code == 200, response.text
    tokens = response.json()
    assert tokens["token_type"] == "Bearer"
    assert tokens["expires_in"] == 30 * 60
    assert tokens["scope"] == MCP_ACCESS_SCOPE
    assert tokens["refresh_token"]
    return client, provider, factory, registration["client_id"], tokens


def test_mcp_oauth_metadata_and_protected_resource_are_exact(mcp_stack) -> None:
    client, _, _ = mcp_stack

    authorization = client.get("/.well-known/oauth-authorization-server")
    assert authorization.status_code == 200
    assert authorization.json() == {
        "issuer": TEST_ISSUER_URL,
        "authorization_endpoint": f"{TEST_ISSUER_URL}/authorize",
        "token_endpoint": f"{TEST_ISSUER_URL}/token",
        "registration_endpoint": f"{TEST_ISSUER_URL}/register",
        "revocation_endpoint": f"{TEST_ISSUER_URL}/revoke",
        "scopes_supported": [MCP_ACCESS_SCOPE],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["none"],
        "revocation_endpoint_auth_methods_supported": ["none"],
        "code_challenge_methods_supported": ["S256"],
    }

    resource = client.get("/.well-known/oauth-protected-resource/mcp")
    assert resource.status_code == 200
    assert resource.json() == {
        "resource": MCP_RESOURCE_URL,
        "authorization_servers": [TEST_ISSUER_URL],
        "scopes_supported": [MCP_ACCESS_SCOPE],
        "bearer_methods_supported": ["header"],
    }

    protected = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert protected.status_code == 401
    assert (
        f'resource_metadata="{TEST_ISSUER_URL}/.well-known/oauth-protected-resource/mcp"'
        in protected.headers["www-authenticate"]
    )


def test_dynamic_registration_accepts_only_explicit_public_clients(mcp_stack) -> None:
    client, _, factory = mcp_stack
    registered = _register_public_client(client)
    assert registered["scope"] == MCP_ACCESS_SCOPE

    missing_public_method = client.post(
        "/register",
        json={
            "redirect_uris": ["https://agent.example/default-auth"],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "scope": MCP_ACCESS_SCOPE,
        },
    )
    assert missing_public_method.status_code == 400
    assert missing_public_method.json()["error"] == "invalid_client_metadata"

    confidential = client.post(
        "/register",
        json={
            "redirect_uris": ["https://agent.example/confidential"],
            "token_endpoint_auth_method": "client_secret_post",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "scope": MCP_ACCESS_SCOPE,
        },
    )
    assert confidential.status_code == 400
    assert confidential.json()["error"] == "invalid_client_metadata"

    with factory() as session:
        rows = session.scalars(select(McpOAuthClient)).all()
    assert len(rows) == 1
    assert rows[0].client_id == registered["client_id"]
    assert "client_secret" not in rows[0].metadata_json


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "javascript:alert(document.domain)",
        "data:text/html,<script>alert(document.domain)</script>",
        "file:///tmp/callback",
        "http://agent.example/callback",
        "https://agent.example/callback#fragment",
        "https://user:password@agent.example/callback",
        "https://agent.example:invalid/callback",
    ],
)
def test_dynamic_registration_rejects_unsafe_redirect_uris(
    mcp_stack, redirect_uri: str
) -> None:
    client, _, factory = mcp_stack

    response = client.post(
        "/register",
        json=_registration_payload(redirect_uris=[redirect_uri]),
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_client_metadata"
    with factory() as session:
        assert session.scalars(select(McpOAuthClient)).all() == []


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "https://agent.example/callback",
        "http://127.0.0.1:8765/callback",
        "http://localhost:8765/callback",
        "http://[::1]:8765/callback",
    ],
)
def test_dynamic_registration_accepts_safe_redirect_uris(
    mcp_stack, redirect_uri: str
) -> None:
    client, _, factory = mcp_stack

    response = client.post(
        "/register",
        json=_registration_payload(redirect_uris=[redirect_uri]),
    )

    assert response.status_code == 201, response.text
    assert response.json()["redirect_uris"] == [redirect_uri]
    with factory() as session:
        stored = session.execute(select(McpOAuthClient)).scalar_one()
        assert stored.metadata_json["redirect_uris"] == [redirect_uri]


def test_tampered_client_redirect_cannot_emit_unsafe_authorize_location(
    mcp_stack,
) -> None:
    client, _, factory = mcp_stack
    registration = _register_public_client(client)
    unsafe_redirect = "javascript:alert(document.domain)"
    with factory() as session:
        stored = session.get(McpOAuthClient, registration["client_id"])
        assert stored is not None
        stored.metadata_json = {
            **stored.metadata_json,
            "redirect_uris": [unsafe_redirect],
        }
        session.commit()

    response = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": registration["client_id"],
            "redirect_uri": unsafe_redirect,
            "scope": MCP_ACCESS_SCOPE,
            "state": "state-123",
            "code_challenge": _pkce("v" * 64),
            "code_challenge_method": "S256",
            "resource": MCP_RESOURCE_URL,
        },
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert "location" not in response.headers
    with factory() as session:
        assert session.scalars(select(McpAuthorizationRequest)).all() == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"client_name": "n" * 129},
        {"redirect_uris": []},
        {"redirect_uris": [f"https://agent.example/callback/{i}" for i in range(11)]},
        {"redirect_uris": ["https://agent.example/" + "r" * 2027]},
        {"contacts": [f"ops{i}@example.com" for i in range(6)]},
        {"contacts": ["c" * 255]},
        {"jwks_uri": "https://agent.example/jwks.json"},
        {"jwks": {"keys": []}},
    ],
)
def test_dynamic_registration_rejects_oversized_client_metadata(
    mcp_stack, overrides: dict
) -> None:
    client, _, factory = mcp_stack

    response = client.post("/register", json=_registration_payload(**overrides))

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_client_metadata"
    assert response.headers["cache-control"] == "no-store"
    with factory() as session:
        assert session.scalars(select(McpOAuthClient)).all() == []


def test_dynamic_registration_rejects_body_larger_than_16_kib(mcp_stack) -> None:
    client, _, factory = mcp_stack
    secret_marker = "registration-secret-marker"
    body = json.dumps(
        {
            **_registration_payload(),
            "software_statement": secret_marker + "x" * 17_000,
        }
    ).encode("utf-8")

    response = client.post(
        "/register",
        content=body,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json() == {
        "error": "invalid_client_metadata",
        "error_description": "Client metadata is too large",
    }
    assert response.headers["cache-control"] == "no-store"
    assert secret_marker not in response.text
    with factory() as session:
        assert session.scalars(select(McpOAuthClient)).all() == []


def test_dynamic_registration_chunked_body_is_read_with_bounded_memory() -> None:
    class ChunkedRequest:
        def __init__(self) -> None:
            self.yielded_chunks: list[bytes] = []

        async def stream(self):
            for chunk in (
                b"a" * (DCR_MAX_BODY_BYTES // 2),
                b"b" * (DCR_MAX_BODY_BYTES // 2),
                b"c",
                b"d" * DCR_MAX_BODY_BYTES,
            ):
                self.yielded_chunks.append(chunk)
                yield chunk

    request = ChunkedRequest()

    body, too_large = asyncio.run(
        _read_limited_request_body(request, max_bytes=DCR_MAX_BODY_BYTES)
    )

    assert too_large is True
    assert len(body) <= DCR_MAX_BODY_BYTES
    assert len(request.yielded_chunks) == 3


def test_authorization_code_pkce_is_single_use_and_secrets_are_hashed(mcp_stack) -> None:
    client, provider, factory = mcp_stack
    registration = _register_public_client(client)
    client_id = registration["client_id"]
    code, verifier = _authorize(client, provider, factory, client_id)

    wrong_verifier = _exchange_code(client, client_id, code, "x" * 64)
    assert wrong_verifier.status_code == 400
    assert wrong_verifier.json()["error"] == "invalid_grant"

    exchanged = _exchange_code(client, client_id, code, verifier)
    assert exchanged.status_code == 200, exchanged.text
    tokens = exchanged.json()

    reused = _exchange_code(client, client_id, code, verifier)
    assert reused.status_code == 400
    assert reused.json()["error"] == "invalid_grant"

    with factory() as session:
        grant = session.execute(select(McpAuthorizationRequest)).scalar_one()
        access = session.execute(select(McpAccessToken)).scalar_one()
        refresh = session.execute(select(McpRefreshToken)).scalar_one()
        persisted = repr(
            {
                "request": grant.__dict__,
                "access": access.__dict__,
                "refresh": refresh.__dict__,
            }
        )
    assert grant.code_hash == hash_cli_secret(code)
    assert access.token_hash == hash_cli_secret(tokens["access_token"])
    assert refresh.token_hash == hash_cli_secret(tokens["refresh_token"])
    assert code not in persisted
    assert tokens["access_token"] not in persisted
    assert tokens["refresh_token"] not in persisted


@pytest.mark.parametrize(
    ("overrides", "expected_error"),
    [
        ({"resource": "https://evil.example/mcp"}, "invalid_request"),
        ({"scope": "cli:read"}, "invalid_scope"),
        ({"code_challenge_method": "plain"}, "invalid_request"),
        ({"code_challenge": "weak"}, "invalid_request"),
    ],
)
def test_authorize_rejects_wrong_resource_scope_and_plain_pkce(
    mcp_stack, overrides: dict[str, str], expected_error: str
) -> None:
    client, _, factory = mcp_stack
    registration = _register_public_client(client)
    params = {
        "response_type": "code",
        "client_id": registration["client_id"],
        "redirect_uri": "https://agent.example/callback",
        "scope": MCP_ACCESS_SCOPE,
        "state": "state-123",
        "code_challenge": _pkce("v" * 64),
        "code_challenge_method": "S256",
        "resource": MCP_RESOURCE_URL,
    }
    params.update(overrides)

    response = client.get("/authorize", params=params, follow_redirects=False)
    if "location" in response.headers:
        error = parse_qs(urlsplit(response.headers["location"]).query)["error"][0]
    else:
        error = response.json()["error"]
    assert error == expected_error
    with factory() as session:
        assert session.scalars(select(McpAuthorizationRequest)).all() == []


def test_token_endpoint_rejects_wrong_or_missing_resource(mcp_stack) -> None:
    client, provider, factory = mcp_stack
    registration = _register_public_client(client)
    code, verifier = _authorize(client, provider, factory, registration["client_id"])
    base_data = {
        "grant_type": "authorization_code",
        "client_id": registration["client_id"],
        "code": code,
        "redirect_uri": "https://agent.example/callback",
        "code_verifier": verifier,
    }

    missing = client.post("/token", data=base_data)
    wrong = client.post(
        "/token", data={**base_data, "resource": "https://evil.example/mcp"}
    )
    assert missing.status_code == 400
    assert missing.json()["error"] == "invalid_request"
    assert wrong.status_code == 400
    assert wrong.json()["error"] == "invalid_request"

    valid = client.post("/token", data={**base_data, "resource": MCP_RESOURCE_URL})
    assert valid.status_code == 200


def test_token_endpoint_rejects_malformed_pkce_verifier_without_consuming_code(
    mcp_stack,
) -> None:
    client, provider, factory = mcp_stack
    registration = _register_public_client(client)
    code, verifier = _authorize(client, provider, factory, registration["client_id"])

    malformed = _exchange_code(client, registration["client_id"], code, "short")
    assert malformed.status_code == 400
    assert malformed.json()["error"] == "invalid_request"

    valid = _exchange_code(client, registration["client_id"], code, verifier)
    assert valid.status_code == 200


def test_authorize_rejects_missing_pkce_challenge(mcp_stack) -> None:
    client, _, factory = mcp_stack
    registration = _register_public_client(client)

    response = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": registration["client_id"],
            "redirect_uri": "https://agent.example/callback",
            "scope": MCP_ACCESS_SCOPE,
            "resource": MCP_RESOURCE_URL,
        },
        follow_redirects=False,
    )

    error = parse_qs(urlsplit(response.headers["location"]).query)["error"][0]
    assert error == "invalid_request"
    with factory() as session:
        assert session.scalars(select(McpAuthorizationRequest)).all() == []


def test_expired_authorization_code_is_rejected(mcp_stack) -> None:
    client, provider, factory = mcp_stack
    registration = _register_public_client(client)
    code, verifier = _authorize(client, provider, factory, registration["client_id"])
    with factory() as session:
        grant = session.execute(select(McpAuthorizationRequest)).scalar_one()
        grant.expires_at = utcnow() - timedelta(seconds=1)
        session.commit()

    expired = _exchange_code(client, registration["client_id"], code, verifier)

    assert expired.status_code == 400
    assert expired.json()["error"] == "invalid_grant"


def test_refresh_rotation_and_replay_revoke_the_entire_family(mcp_stack) -> None:
    client, provider, factory, client_id, tokens = _issue_tokens(mcp_stack)

    rotated = client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": tokens["refresh_token"],
            "scope": MCP_ACCESS_SCOPE,
            "resource": MCP_RESOURCE_URL,
        },
    )
    assert rotated.status_code == 200, rotated.text
    next_tokens = rotated.json()
    assert next_tokens["refresh_token"] != tokens["refresh_token"]
    assert asyncio.run(provider.load_access_token(tokens["access_token"])) is None
    assert asyncio.run(provider.load_access_token(next_tokens["access_token"])) is not None

    replay = client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": tokens["refresh_token"],
            "scope": MCP_ACCESS_SCOPE,
            "resource": MCP_RESOURCE_URL,
        },
    )
    assert replay.status_code == 400
    assert replay.json()["error"] == "invalid_grant"
    assert asyncio.run(provider.load_access_token(next_tokens["access_token"])) is None

    successor = client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": next_tokens["refresh_token"],
            "scope": MCP_ACCESS_SCOPE,
            "resource": MCP_RESOURCE_URL,
        },
    )
    assert successor.status_code == 400
    assert successor.json()["error"] == "invalid_grant"
    with factory() as session:
        assert all(
            row.revoked_at is not None
            for row in session.scalars(select(McpRefreshToken)).all()
        )
        assert all(
            row.revoked_at is not None
            for row in session.scalars(select(McpAccessToken)).all()
        )


def test_access_token_survives_provider_restart_and_revocation_is_persistent(
    mcp_stack,
) -> None:
    client, _, factory, client_id, tokens = _issue_tokens(mcp_stack)
    restarted = DatabaseMcpOAuthProvider(session_factory=factory)
    loaded = asyncio.run(restarted.load_access_token(tokens["access_token"]))
    assert loaded is not None
    assert loaded.resource == MCP_RESOURCE_URL
    assert loaded.scopes == [MCP_ACCESS_SCOPE]

    revoked = client.post(
        "/revoke",
        data={
            "client_id": client_id,
            "token": tokens["access_token"],
            "token_type_hint": "access_token",
        },
    )
    assert revoked.status_code == 200, revoked.text
    assert asyncio.run(restarted.load_access_token(tokens["access_token"])) is None

    refresh_after_revoke = client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": tokens["refresh_token"],
            "scope": MCP_ACCESS_SCOPE,
            "resource": MCP_RESOURCE_URL,
        },
    )
    assert refresh_after_revoke.status_code == 400
    assert refresh_after_revoke.json()["error"] == "invalid_grant"


def test_authorized_mcp_streamable_http_transport_initializes(mcp_stack) -> None:
    client, _, _, _, tokens = _issue_tokens(mcp_stack)

    response = client.post(
        "/mcp",
        headers={
            "Authorization": f"Bearer {tokens['access_token']}",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-06-18",
        },
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "dydata-test", "version": "1.0"},
            },
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["result"]["serverInfo"]["name"] == "dydata-read-only"


def test_cli_and_mcp_access_tokens_are_rejected_across_channels(mcp_stack) -> None:
    client, _, factory, _, mcp_tokens = _issue_tokens(mcp_stack)
    with factory() as session:
        user = session.get(User, "mcp-user-1")
        assert user is not None
        cli_auth = _auth_context_for_user(session, user)
        cli_access_token, _ = create_cli_access_token(cli_auth, session=session)

    cli_token_on_mcp = client.post(
        "/mcp",
        headers={
            "Authorization": f"Bearer {cli_access_token}",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-06-18",
        },
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )
    mcp_token_on_cli = client.get(
        "/api/v1/cli/stores",
        headers={"Authorization": f"Bearer {mcp_tokens['access_token']}"},
    )

    assert cli_token_on_mcp.status_code == 401
    assert mcp_token_on_cli.status_code == 401
    assert mcp_token_on_cli.json()["error"]["code"] == "AUTH_EXPIRED"
    assert mcp_token_on_cli.json()["meta"]["channel"] == "cli"


def test_disabled_account_invalidates_persisted_mcp_tokens(mcp_stack) -> None:
    client, provider, factory, client_id, tokens = _issue_tokens(mcp_stack)
    with factory() as session:
        user = session.get(User, "mcp-user-1")
        assert user is not None
        user.status = "disabled"
        session.commit()

    assert asyncio.run(provider.load_access_token(tokens["access_token"])) is None
    refreshed = client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": tokens["refresh_token"],
            "scope": MCP_ACCESS_SCOPE,
            "resource": MCP_RESOURCE_URL,
        },
    )
    assert refreshed.status_code == 400
    assert refreshed.json()["error"] == "invalid_grant"


def test_tool_transaction_revalidation_uses_non_frozen_internal_error(
    mcp_stack,
) -> None:
    _, provider, factory, _, tokens = _issue_tokens(mcp_stack)
    loaded = asyncio.run(provider.load_access_token(tokens["access_token"]))
    assert loaded is not None
    with factory() as session:
        user = session.get(User, "mcp-user-1")
        assert user is not None
        user.status = "disabled"
        session.commit()

    with pytest.raises(McpAccessAuthorizationError):
        with provider.session() as session:
            provider.current_auth_for_access_token(session, loaded)


def test_mcp_dependency_is_locked_to_stable_v1() -> None:
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "mcp>=1.27,<2" in requirements.splitlines()
