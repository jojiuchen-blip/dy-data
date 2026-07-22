from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from io import StringIO

import httpx

from dydata_cli.client import DyDataClient
from dydata_cli.commands import execute_command
from dydata_cli.credentials import CredentialState
from dydata_cli.parser import parse_args


class FakeCredentialStore:
    def __init__(self, state: CredentialState | None = None) -> None:
        self.state = state

    def load(self) -> CredentialState | None:
        return self.state


def _manifest(*, environment: str = "test") -> dict[str, object]:
    return {
        "name": "dydata-agent",
        "manifest_version": "1.0",
        "environment": environment,
        "read_only": True,
        "service": {
            "base_url": "https://dy-business-engine.com",
            "capabilities_url": "https://dy-business-engine.com/api/v1/agent/capabilities",
            "agent_guide_url": "https://dy-business-engine.com/agent.md",
            "skill_url": "https://dy-business-engine.com/agent/SKILL.md",
        },
        "cli": {
            "version": "0.3.0",
            "schema_version": "1.1",
            "install_spec": "git+https://github.com/jojiuchen-blip/dy-data.git@main#subdirectory=apps/cli",
            "discovery_command": "dydata commands --json",
            "doctor_command": "dydata agent doctor --json",
        },
        "mcp": {
            "url": "https://dy-business-engine.com/mcp",
            "transport": "streamable-http",
            "oauth_issuer": "https://dy-business-engine.com",
            "protected_resource_metadata": "https://dy-business-engine.com/.well-known/oauth-protected-resource/mcp",
        },
        "authorization": {
            "user_handoff_required": True,
            "agent_must_not_handle_credentials": True,
            "scope": "mcp:read",
        },
    }


def _resource_metadata() -> dict[str, object]:
    return {
        "resource": "https://dy-business-engine.com/mcp",
        "authorization_servers": ["https://dy-business-engine.com"],
        "scopes_supported": ["mcp:read"],
        "bearer_methods_supported": ["header"],
    }


def _run_doctor(
    handler,
    *,
    store: FakeCredentialStore | None = None,
) -> tuple[int, dict[str, object], list[str]]:
    requested_paths: list[str] = []

    def recording_handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        return handler(request)

    stream = StringIO()
    exit_code = execute_command(
        parse_args(["agent", "doctor", "--json"]),
        credential_store=store or FakeCredentialStore(),
        client=DyDataClient(transport=httpx.MockTransport(recording_handler)),
        stream=stream,
    )
    return exit_code, json.loads(stream.getvalue()), requested_paths


def test_doctor_treats_missing_credentials_as_a_safe_diagnostic_state() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/dydata-agent.json":
            return httpx.Response(200, json=_manifest())
        if request.url.path == "/.well-known/oauth-protected-resource/mcp":
            return httpx.Response(200, json=_resource_metadata())
        raise AssertionError(request.url)

    exit_code, body, requested_paths = _run_doctor(handler)

    assert exit_code == 0
    assert body["ok"] is True
    assert body["command"] == "agent.doctor"
    assert body["environment"] == "test"
    assert body["schema_version"] == "1.1"
    assert body["data"]["credential"] == {
        "status": "not_configured",
        "identity": None,
        "stores": [],
    }
    assert body["data"]["next_action"] == "dydata auth login"
    assert [check["status"] for check in body["data"]["checks"]] == [
        "pass",
        "pass",
        "not_configured",
    ]
    assert requested_paths == [
        "/.well-known/dydata-agent.json",
        "/.well-known/oauth-protected-resource/mcp",
    ]
    assert "token" not in json.dumps(body).lower()


def test_doctor_rejects_a_manifest_for_another_environment() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/.well-known/dydata-agent.json"
        return httpx.Response(200, json=_manifest(environment="production"))

    exit_code, body, requested_paths = _run_doctor(handler)

    assert exit_code == 6
    assert body["error"]["code"] == "SCHEMA_MISMATCH"
    assert body["environment"] == "test"
    assert requested_paths == ["/.well-known/dydata-agent.json"]
    assert "production" not in json.dumps(body).lower()


def test_doctor_reports_public_endpoint_unavailability_without_secrets() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unsafe refresh-secret", request=request)

    exit_code, body, _ = _run_doctor(handler)

    assert exit_code == 5
    assert body["error"]["code"] == "API_UNAVAILABLE"
    assert "secret" not in json.dumps(body).lower()


def test_doctor_returns_current_identity_and_store_scope_when_authorized() -> None:
    now = datetime.now(timezone.utc)
    state = CredentialState(
        access_token="access-secret",
        access_token_expires_at=now + timedelta(minutes=20),
        refresh_token="refresh-secret",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        request_id = request.headers["X-Request-ID"]
        if request.url.path == "/.well-known/dydata-agent.json":
            return httpx.Response(200, json=_manifest())
        if request.url.path == "/.well-known/oauth-protected-resource/mcp":
            return httpx.Response(200, json=_resource_metadata())
        if request.url.path == "/api/v1/cli/auth/status":
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "command": "auth.status",
                    "environment": "test",
                    "schema_version": "1.1",
                    "data": {
                        "authenticated": True,
                        "user_id": "user-1",
                        "username": "operator",
                        "display_name": "Operator",
                        "role": "store",
                        "auth_type": "user",
                        "store_ids": ["store-a"],
                        "expires_at": (now + timedelta(minutes=20)).isoformat(),
                    },
                    "meta": {"request_id": request_id, "partial": False},
                },
            )
        if request.url.path == "/api/v1/cli/stores":
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "command": "stores.list",
                    "environment": "test",
                    "schema_version": "1.1",
                    "scope": {
                        "user_id": "user-1",
                        "effective_store_ids": ["store-a"],
                    },
                    "data": {
                        "stores": [
                            {"store_id": "store-a", "store_name": "Alpha"}
                        ]
                    },
                    "meta": {"request_id": request_id, "partial": False},
                },
            )
        raise AssertionError(request.url)

    exit_code, body, _ = _run_doctor(handler, store=FakeCredentialStore(state))

    assert exit_code == 0
    assert body["data"]["credential"] == {
        "status": "authenticated",
        "identity": {
            "user_id": "user-1",
            "username": "operator",
            "display_name": "Operator",
            "role": "store",
        },
        "stores": [{"store_id": "store-a", "store_name": "Alpha"}],
    }
    rendered = json.dumps(body)
    assert "access-secret" not in rendered
    assert "refresh-secret" not in rendered
