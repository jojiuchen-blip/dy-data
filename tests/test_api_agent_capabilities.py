from __future__ import annotations

import asyncio
import base64
import hashlib
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Generator
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from apps.api.dy_api.models import (  # noqa: E402
    Base,
    DimStore,
    McpAuthorizationRequest,
    User,
    UserStoreScope,
    utcnow,
)
from dy_api.agent_capabilities import (  # noqa: E402
    AgentCapabilityError,
    clues_follow_up_stats,
    stores_list,
)
from dy_api.auth import (  # noqa: E402
    AuthContext,
    create_session_token,
    get_cookie_config,
)
from dy_api.cli_auth import _auth_context_for_user  # noqa: E402
from dy_api.main import create_app  # noqa: E402
from dy_api.mcp_oauth import (  # noqa: E402
    MCP_ACCESS_SCOPE,
    MCP_RESOURCE_URL,
    TEST_ISSUER_URL,
    DatabaseMcpOAuthProvider,
)
from dy_api.routes._data import get_session_dependency  # noqa: E402


class FakeStore:
    available = True

    def __init__(self) -> None:
        self.summary_calls: list[dict[str, Any]] = []
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

    def list_stores(
        self, scope_store_ids: tuple[str, ...] | None = None
    ) -> list[dict[str, str]]:
        allowed = None if scope_store_ids is None else set(scope_store_ids)
        return [
            row.copy()
            for row in self.stores
            if allowed is None or row["store_id"] in allowed
        ]

    def clue_store_follow_up_summary(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.summary_calls.append(kwargs)
        return [self.rows[store_id].copy() for store_id in kwargs["store_ids"]]


def _auth(store_ids: tuple[str, ...] = ("store-a", "store-b")) -> AuthContext:
    return AuthContext(
        user_id="mcp-user-1",
        username="mcp-store-user",
        display_name="MCP Store User",
        role="store",
        store_ids=store_ids,
        auth_type="user",
        store_scope_mode="specified",
    )


def _pkce(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _session_dependency(factory: sessionmaker[Session]):
    def dependency() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    return dependency


@pytest.fixture()
def consent_stack(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    monkeypatch.setenv("DY_SESSION_SECRET", "mcp-consent-session-secret")
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
    app = create_app(mcp_provider=provider, mcp_data_store_factory=lambda _session: FakeStore())
    app.dependency_overrides[get_session_dependency] = _session_dependency(factory)
    client = TestClient(app, base_url=TEST_ISSUER_URL)
    session_cookie = create_session_token(
        "mcp-store-user",
        user_id="mcp-user-1",
        role="store",
        auth_type="user",
    )
    client.cookies.set(get_cookie_config().name, session_cookie)
    with client:
        yield client, provider, factory


def _start_authorization(client: TestClient) -> tuple[str, str]:
    registration = client.post(
        "/register",
        json={
            "redirect_uris": ["https://agent.example/callback"],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "scope": MCP_ACCESS_SCOPE,
            "client_name": "WorkBuddy Read-only Agent",
        },
    ).json()
    response = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": registration["client_id"],
            "redirect_uri": "https://agent.example/callback",
            "scope": MCP_ACCESS_SCOPE,
            "state": "state-123",
            "code_challenge": _pkce("v" * 64),
            "code_challenge_method": "S256",
            "resource": MCP_RESOURCE_URL,
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    request_id = parse_qs(urlsplit(response.headers["location"]).query)["request_id"][0]
    return request_id, registration["client_id"]


def test_shared_capabilities_keep_cli_metric_semantics() -> None:
    store = FakeStore()

    stores = stores_list(
        current_user=_auth(), store=store, request_id="request-stores"
    )
    stats = clues_follow_up_stats(
        current_user=_auth(),
        store=store,
        request_id="request-stats",
        assigned_date_start="2026-07-01",
        assigned_date_end="2026-07-07",
        store_ids=["store-b", "store-a", "store-a"],
    )

    assert [row["store_id"] for row in stores["data"]["stores"]] == [
        "store-a",
        "store-b",
    ]
    assert stores["meta"] == {"partial": False, "request_id": "request-stores"}
    assert "channel" not in stats["meta"]
    assert stats["scope"] == {
        "user_id": "mcp-user-1",
        "requested_store_ids": ["store-a", "store-b"],
        "effective_store_ids": ["store-a", "store-b"],
    }
    assert stats["filters"] == {
        "assigned_date_start": "2026-07-01",
        "assigned_date_end": "2026-07-07",
        "timezone": "Asia/Shanghai",
    }
    assert stats["data"]["totals"] == {
        "total_count": 6,
        "pending_count": 1,
        "followed_count": 3,
        "other_status_count": 2,
        "action_followed_count": 5,
        "effective_followed_count": 3,
        "system_follow_up_rate": 0.5,
        "action_follow_rate": 0.8333,
    }


def test_shared_default_date_window_uses_beijing_calendar_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "dy_api.agent_capabilities.generated_at",
        lambda: datetime(2026, 7, 22, 16, 30, tzinfo=timezone.utc),
    )

    result = clues_follow_up_stats(
        current_user=_auth(),
        store=FakeStore(),
        request_id="request-beijing-date",
    )

    assert result["filters"]["assigned_date_start"] == "2026-07-17"
    assert result["filters"]["assigned_date_end"] == "2026-07-23"


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"assigned_date_start": "2026-07-01"}, "INVALID_ARGUMENT"),
        (
            {
                "assigned_date_start": "2026-07-08",
                "assigned_date_end": "2026-07-01",
            },
            "INVALID_ARGUMENT",
        ),
        ({"store_ids": ["store-a", "outside"]}, "SCOPE_DENIED"),
        ({"store_ids": [" "]}, "INVALID_ARGUMENT"),
    ],
)
def test_shared_capabilities_reject_invalid_ranges_and_scope(
    kwargs: dict[str, Any], code: str
) -> None:
    with pytest.raises(AgentCapabilityError) as exc_info:
        clues_follow_up_stats(
            current_user=_auth(),
            store=FakeStore(),
            request_id="request-error",
            **kwargs,
        )

    assert exc_info.value.code == code


def test_mcp_consent_details_approve_and_single_use(consent_stack) -> None:
    client, _, factory = consent_stack
    request_id, _ = _start_authorization(client)

    details = client.get(
        "/api/v1/auth/mcp/request", params={"request_id": request_id}
    )
    assert details.status_code == 200, details.text
    assert details.headers["cache-control"] == "no-store"
    assert details.headers["pragma"] == "no-cache"
    body = details.json()["data"]
    assert body == {
        "request_id": request_id,
        "agent_name": "WorkBuddy Read-only Agent",
        "redirect_uri": "https://agent.example/callback",
        "scopes": [MCP_ACCESS_SCOPE],
        "environment": "test",
        "resource": MCP_RESOURCE_URL,
        "expires_at": body["expires_at"],
        "account": {
            "user_id": "mcp-user-1",
            "username": "mcp-store-user",
            "display_name": "MCP Store User",
        },
        "data_scope": {
            "mode": "specified",
            "stores": [
                {"store_id": "store-a", "store_name": "Alpha"},
                {"store_id": "store-b", "store_name": "Beta"},
            ],
        },
    }
    assert "code_challenge" not in repr(body)
    assert "state-123" not in repr(body)

    approval = client.post(
        "/api/v1/auth/mcp/approve",
        json={"request_id": request_id, "decision": "approve"},
    )
    assert approval.status_code == 200, approval.text
    assert approval.headers["cache-control"] == "no-store"
    assert approval.headers["pragma"] == "no-cache"
    callback = urlsplit(approval.json()["redirect_uri"])
    params = parse_qs(callback.query)
    assert params["state"] == ["state-123"]
    assert len(params["code"][0]) >= 43

    repeated = client.post(
        "/api/v1/auth/mcp/approve",
        json={"request_id": request_id, "decision": "approve"},
    )
    assert repeated.status_code == 400
    with factory() as session:
        grant = session.execute(select(McpAuthorizationRequest)).scalar_one()
        assert grant.status == "approved"


@pytest.mark.parametrize("decision", ["approve", "deny"])
def test_tampered_consent_redirect_fails_without_consuming_grant(
    consent_stack, decision: str
) -> None:
    client, _, factory = consent_stack
    request_id, _ = _start_authorization(client)
    with factory() as session:
        grant = session.execute(select(McpAuthorizationRequest)).scalar_one()
        grant.redirect_uri = "javascript:alert(document.domain)"
        session.commit()

    details = client.get(
        "/api/v1/auth/mcp/request", params={"request_id": request_id}
    )
    decision_response = client.post(
        "/api/v1/auth/mcp/approve",
        json={"request_id": request_id, "decision": decision},
    )

    assert details.status_code == 400
    assert decision_response.status_code == 400
    assert "redirect_uri" not in decision_response.json()
    with factory() as session:
        grant = session.execute(select(McpAuthorizationRequest)).scalar_one()
        assert grant.status == "pending"
        assert grant.code_hash is None
        assert grant.approved_at is None
        assert grant.consumed_at is None


def test_mcp_consent_deny_and_expiry_are_stable(consent_stack) -> None:
    client, _, factory = consent_stack
    denied_request_id, _ = _start_authorization(client)

    denied = client.post(
        "/api/v1/auth/mcp/approve",
        json={"request_id": denied_request_id, "decision": "deny"},
    )
    assert denied.status_code == 200
    denied_params = parse_qs(urlsplit(denied.json()["redirect_uri"]).query)
    assert denied_params == {"error": ["access_denied"], "state": ["state-123"]}
    assert client.get(
        "/api/v1/auth/mcp/request", params={"request_id": denied_request_id}
    ).status_code == 400

    expired_request_id, _ = _start_authorization(client)
    with factory() as session:
        grant = session.execute(
            select(McpAuthorizationRequest).where(
                McpAuthorizationRequest.status == "pending"
            )
        ).scalar_one()
        grant.expires_at = utcnow() - timedelta(seconds=1)
        session.commit()

    assert client.get(
        "/api/v1/auth/mcp/request", params={"request_id": expired_request_id}
    ).status_code == 400


def test_mcp_consent_requires_authenticated_web_session(consent_stack) -> None:
    client, _, _ = consent_stack
    request_id, _ = _start_authorization(client)
    client.cookies.clear()

    assert client.get(
        "/api/v1/auth/mcp/request", params={"request_id": request_id}
    ).status_code == 401
    assert client.post(
        "/api/v1/auth/mcp/approve",
        json={"request_id": request_id, "decision": "approve"},
    ).status_code == 401
