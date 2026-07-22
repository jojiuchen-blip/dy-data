from __future__ import annotations

import asyncio
import base64
import hashlib
import sys
from pathlib import Path
from typing import Any
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
    CliAuditEvent,
    DimStore,
    McpAccessToken,
    User,
    UserStoreScope,
)
from dy_api.auth import AuthContext  # noqa: E402
from dy_api.cli_audit import DatabaseCliAuditSink  # noqa: E402
from dy_api.cli_auth import _auth_context_for_user, get_current_cli_user  # noqa: E402
from dy_api.main import create_app  # noqa: E402
from dy_api.mcp_oauth import (  # noqa: E402
    MCP_ACCESS_SCOPE,
    MCP_RESOURCE_URL,
    TEST_ISSUER_URL,
    DatabaseMcpOAuthProvider,
)
from dy_api.mcp_server import _validate_mcp_binding  # noqa: E402
from dy_api.routes._data import get_data_store  # noqa: E402


class FakeStore:
    available = True

    def __init__(self) -> None:
        self.summary_calls: list[dict[str, Any]] = []
        self.business_session = None
        self.failure: Exception | None = None
        self.stores = [
            {"store_id": "store-b", "store_name": "Beta"},
            {"store_id": "store-a", "store_name": "Alpha"},
        ]
        self.rows = {
            "store-a": {
                "store_id": "store-a",
                "store_name": "Alpha",
                "total_count": 4,
                "pending_count": 1,
                "followed_count": 2,
                "other_status_count": 1,
                "action_followed_count": 3,
                "effective_followed_count": 2,
                "system_follow_up_rate": 0.5,
                "action_follow_rate": 0.75,
            },
            "store-b": {
                "store_id": "store-b",
                "store_name": "Beta",
                "total_count": 2,
                "pending_count": 0,
                "followed_count": 1,
                "other_status_count": 1,
                "action_followed_count": 2,
                "effective_followed_count": 1,
                "system_follow_up_rate": 0.5,
                "action_follow_rate": 1.0,
            },
        }

    def list_stores(self, scope: tuple[str, ...] | None = None):
        allowed = None if scope is None else set(scope)
        return [
            row.copy()
            for row in self.stores
            if allowed is None or row["store_id"] in allowed
        ]

    def clue_store_follow_up_summary(self, **kwargs: Any):
        self.summary_calls.append(kwargs)
        if self.failure is not None:
            raise self.failure
        return [self.rows[store_id].copy() for store_id in kwargs["store_ids"]]


def _pkce(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


@pytest.fixture()
def mcp_tools_stack(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    monkeypatch.setenv("DY_SESSION_SECRET", "mcp-tools-session-secret")
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
        session.add_all(
            [
                DimStore(store_id="store-a", store_name="Alpha"),
                DimStore(store_id="store-b", store_name="Beta"),
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
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                UserStoreScope(user_id="mcp-user-1", store_id="store-a"),
                UserStoreScope(user_id="mcp-user-1", store_id="store-b"),
            ]
        )
        session.commit()

    provider = DatabaseMcpOAuthProvider(session_factory=factory)
    fake_store = FakeStore()
    def data_store_factory(session):
        fake_store.business_session = session
        return fake_store

    app = create_app(
        mcp_provider=provider,
        mcp_data_store_factory=data_store_factory,
    )
    app.state.cli_audit_sink = DatabaseCliAuditSink(session_factory=factory)
    cli_auth = AuthContext(
        user_id="mcp-user-1",
        username="mcp-store-user",
        display_name="MCP Store User",
        role="store",
        store_ids=("store-a", "store-b"),
        auth_type="user",
        store_scope_mode="specified",
    )
    app.dependency_overrides[get_current_cli_user] = lambda: cli_auth
    app.dependency_overrides[get_data_store] = lambda: fake_store

    with TestClient(app, base_url=TEST_ISSUER_URL) as client:
        registration = client.post(
            "/register",
            json={
                "redirect_uris": ["https://agent.example/callback"],
                "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "scope": MCP_ACCESS_SCOPE,
                "client_name": "MCP Tools Test",
            },
        ).json()
        verifier = "v" * 64
        authorization = client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": registration["client_id"],
                "redirect_uri": "https://agent.example/callback",
                "scope": MCP_ACCESS_SCOPE,
                "state": "state-tools",
                "code_challenge": _pkce(verifier),
                "code_challenge_method": "S256",
                "resource": MCP_RESOURCE_URL,
            },
            follow_redirects=False,
        )
        request_id = parse_qs(urlsplit(authorization.headers["location"]).query)[
            "request_id"
        ][0]
        with factory() as session:
            user = session.get(User, "mcp-user-1")
            auth = _auth_context_for_user(session, user)
        callback = asyncio.run(provider.approve_authorization(request_id, auth))
        code = parse_qs(urlsplit(callback).query)["code"][0]
        token_response = client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": registration["client_id"],
                "code": code,
                "redirect_uri": "https://agent.example/callback",
                "code_verifier": verifier,
                "resource": MCP_RESOURCE_URL,
            },
        )
        assert token_response.status_code == 200, token_response.text
        yield client, factory, fake_store, token_response.json()["access_token"]


def _mcp_call(client: TestClient, token: str, method: str, params: dict[str, Any]):
    return client.post(
        "/mcp",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-06-18",
        },
        json={"jsonrpc": "2.0", "id": 7, "method": method, "params": params},
    )


def test_mcp_binding_validation_closes_public_and_shared_argument_signatures() -> None:
    async def public_handler(context, date_from=None, date_to=None):
        return None

    def shared_capability(
        *, current_user, store, request_id, assigned_date_start=None, assigned_date_end=None
    ):
        return None

    valid = {
        "command": "clues.follow-up-stats",
        "tool": "clues_follow_up_stats",
        "arguments": {
            "date_from": "assigned_date_start",
            "date_to": "assigned_date_end",
        },
    }

    _validate_mcp_binding(valid, public_handler, shared_capability)

    with pytest.raises(RuntimeError, match="public handler"):
        _validate_mcp_binding(
            {**valid, "arguments": {"date_from": "assigned_date_start"}},
            public_handler,
            shared_capability,
        )
    with pytest.raises(RuntimeError, match="shared capability"):
        _validate_mcp_binding(
            {
                **valid,
                "arguments": {
                    "date_from": "assigned_date_start",
                    "date_to": "current_user",
                },
            },
            public_handler,
            shared_capability,
        )


def test_mcp_lists_exactly_the_two_registry_read_only_tools(mcp_tools_stack) -> None:
    client, _, _, token = mcp_tools_stack

    response = _mcp_call(client, token, "tools/list", {})

    assert response.status_code == 200, response.text
    tools = response.json()["result"]["tools"]
    assert [tool["name"] for tool in tools] == [
        "clues_follow_up_stats",
        "stores_list",
    ]
    for tool in tools:
        assert tool["annotations"] == {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        }
    assert tools[0]["inputSchema"] == {
        "properties": {
            "date_from": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Date From",
            },
            "date_to": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Date To",
            },
            "store_ids": {
                "anyOf": [
                    {"items": {"type": "string"}, "type": "array"},
                    {"type": "null"},
                ],
                "default": None,
                "title": "Store Ids",
            },
        },
        "title": "clues_follow_up_statsArguments",
        "type": "object",
    }
    assert tools[1]["inputSchema"] == {
        "properties": {},
        "title": "stores_listArguments",
        "type": "object",
    }
    assert all(
        fragment not in " ".join(tool["name"] for tool in tools)
        for fragment in ("write", "update", "delete", "create")
    )


def test_mcp_and_cli_return_the_same_follow_up_scope_and_metrics(
    mcp_tools_stack,
) -> None:
    client, factory, fake_store, token = mcp_tools_stack

    mcp_response = _mcp_call(
        client,
        token,
        "tools/call",
        {
            "name": "clues_follow_up_stats",
            "arguments": {
                "date_from": "2026-07-01",
                "date_to": "2026-07-07",
                "store_ids": ["store-b", "store-a"],
            },
        },
    )
    cli_response = client.get(
        "/api/v1/clues/store-follow-up-summary",
        params=[
            ("assigned_date_start", "2026-07-01"),
            ("assigned_date_end", "2026-07-07"),
            ("store_id", "store-b"),
            ("store_id", "store-a"),
        ],
    )

    assert mcp_response.status_code == 200, mcp_response.text
    assert cli_response.status_code == 200, cli_response.text
    result = mcp_response.json()["result"]
    assert result["isError"] is False
    mcp_body = result["structuredContent"]
    cli_body = cli_response.json()
    assert mcp_body["meta"]["channel"] == "mcp"
    for key in ("command", "environment", "schema_version", "metric_version"):
        assert mcp_body[key] == cli_body[key]
    for key in ("scope", "filters", "data"):
        assert mcp_body[key] == cli_body[key]
    assert fake_store.summary_calls[0]["assigned_date_start"] == "2026-07-01"
    assert fake_store.summary_calls[0]["assigned_date_end"] == "2026-07-07"

    with factory() as session:
        events = session.scalars(
            select(CliAuditEvent).order_by(CliAuditEvent.created_at)
        ).all()
    mcp_event = next(event for event in events if event.channel == "mcp")
    assert mcp_event.environment == "test"
    assert mcp_event.command == "clues.follow-up-stats"
    assert mcp_event.user_id == "mcp-user-1"
    assert mcp_event.effective_store_ids == ["store-a", "store-b"]
    assert mcp_event.result_status == 200
    assert token not in repr(mcp_event.__dict__)


def test_mcp_store_scope_violation_is_structured_and_not_queried(
    mcp_tools_stack,
) -> None:
    client, factory, store, token = mcp_tools_stack

    response = _mcp_call(
        client,
        token,
        "tools/call",
        {
            "name": "clues_follow_up_stats",
            "arguments": {
                "date_from": "2026-07-01",
                "date_to": "2026-07-07",
                "store_ids": ["outside-store"],
            },
        },
    )

    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["isError"] is True
    assert result["structuredContent"]["error"]["code"] == "SCOPE_DENIED"
    assert result["structuredContent"]["meta"]["channel"] == "mcp"
    assert store.summary_calls == []
    with factory() as session:
        event = session.scalars(
            select(CliAuditEvent).where(CliAuditEvent.channel == "mcp")
        ).one()
    assert event.result_status == 403
    assert event.error_code == "SCOPE_DENIED"


def test_mcp_business_and_audit_use_distinct_sessions(
    mcp_tools_stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, store, token = mcp_tools_stack
    original_stage = DatabaseCliAuditSink.stage
    compared_sessions: list[tuple[Any, Any]] = []

    def stage(self, session, event):
        compared_sessions.append((store.business_session, session))
        return original_stage(self, session, event)

    monkeypatch.setattr(DatabaseCliAuditSink, "stage", stage)

    response = _mcp_call(
        client,
        token,
        "tools/call",
        {"name": "stores_list", "arguments": {}},
    )

    assert response.status_code == 200, response.text
    assert response.json()["result"]["isError"] is False
    assert len(compared_sessions) == 1
    business_session, audit_session = compared_sessions[0]
    assert business_session is not audit_session
    assert not business_session.in_transaction()


def test_mcp_unexpected_failure_is_sanitized_and_audited(mcp_tools_stack) -> None:
    client, factory, store, token = mcp_tools_stack
    secret_marker = "internal-token-like-marker"
    store.rows["store-a"]["total_count"] = secret_marker

    response = _mcp_call(
        client,
        token,
        "tools/call",
        {
            "name": "clues_follow_up_stats",
            "arguments": {
                "date_from": "2026-07-01",
                "date_to": "2026-07-07",
            },
        },
    )

    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["isError"] is True
    assert result["structuredContent"]["error"]["code"] == "INTERNAL_ERROR"
    assert result["structuredContent"]["meta"]["channel"] == "mcp"
    assert secret_marker not in response.text
    with factory() as session:
        event = session.scalars(
            select(CliAuditEvent).where(CliAuditEvent.channel == "mcp")
        ).one()
    assert event.result_status == 500
    assert event.error_code == "INTERNAL_ERROR"
    assert secret_marker not in repr(event.__dict__)


def test_mcp_audit_failure_fails_closed_without_returning_business_data(
    mcp_tools_stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, _, token = mcp_tools_stack
    secret_marker = "audit-database-secret-marker"

    def fail_record(self, event):
        raise RuntimeError(secret_marker)

    monkeypatch.setattr(DatabaseCliAuditSink, "record", fail_record)

    response = _mcp_call(
        client,
        token,
        "tools/call",
        {"name": "stores_list", "arguments": {}},
    )

    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["isError"] is True
    assert result["structuredContent"]["error"]["code"] == "API_UNAVAILABLE"
    assert "data" not in result["structuredContent"]
    assert secret_marker not in response.text


def test_mcp_rejects_disabled_account_and_environment_mismatch(
    mcp_tools_stack,
) -> None:
    client, factory, _, token = mcp_tools_stack
    with factory() as session:
        access = session.execute(select(McpAccessToken)).scalar_one()
        access.environment = "production"
        session.commit()

    environment_mismatch = _mcp_call(client, token, "tools/list", {})
    assert environment_mismatch.status_code == 401

    with factory() as session:
        access = session.execute(select(McpAccessToken)).scalar_one()
        access.environment = "test"
        user = session.get(User, "mcp-user-1")
        user.status = "disabled"
        session.commit()

    disabled = _mcp_call(client, token, "tools/list", {})
    assert disabled.status_code == 401
