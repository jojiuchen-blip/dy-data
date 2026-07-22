"""Opt-in PostgreSQL concurrency evidence for the MCP OAuth token family.

Run against a disposable database only, for example:

    docker run --rm --name dydata-oauth-pg -e POSTGRES_PASSWORD=postgres \
      -e POSTGRES_DB=dydata_oauth_test -p 55432:5432 postgres:18-alpine
    $env:DYDATA_TEST_POSTGRES_URL = \
      "postgresql+psycopg://postgres:postgres@localhost:55432/dydata_oauth_test"
    python -m pytest tests/test_api_mcp_oauth_postgres.py -q
"""

from __future__ import annotations

import asyncio
import os
import secrets
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier

import pytest
from mcp.server.auth.provider import TokenError
from mcp.shared.auth import OAuthClientInformationFull
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from apps.api.dy_api.cli_auth import hash_cli_secret
from apps.api.dy_api.db import normalize_database_url
from apps.api.dy_api.models import (
    AccessPage,
    Base,
    DimStore,
    McpAccessToken,
    McpAuthorizationRequest,
    McpOAuthClient,
    McpRefreshToken,
    RolePagePermission,
    User,
    UserPagePermissionOverride,
    UserStoreScope,
    utcnow,
)
from apps.api.dy_api.mcp_oauth import (
    MCP_ACCESS_SCOPE,
    MCP_RESOURCE_URL,
    DatabaseMcpOAuthProvider,
    DyDataAuthorizationCode,
)


POSTGRES_URL = os.getenv("DYDATA_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="set DYDATA_TEST_POSTGRES_URL to a disposable PostgreSQL database",
)
OAUTH_TABLES = [
    DimStore.__table__,
    User.__table__,
    UserStoreScope.__table__,
    AccessPage.__table__,
    RolePagePermission.__table__,
    UserPagePermissionOverride.__table__,
    McpOAuthClient.__table__,
    McpAuthorizationRequest.__table__,
    McpAccessToken.__table__,
    McpRefreshToken.__table__,
]


@pytest.fixture()
def postgres_oauth_stack(monkeypatch: pytest.MonkeyPatch):
    assert POSTGRES_URL is not None
    monkeypatch.setenv("DY_SESSION_SECRET", "postgres-oauth-concurrency-test")
    engine = create_engine(
        normalize_database_url(POSTGRES_URL),
        connect_args={"options": "-c lock_timeout=5000"},
        future=True,
    )
    Base.metadata.drop_all(engine, tables=OAUTH_TABLES)
    Base.metadata.create_all(engine, tables=OAUTH_TABLES)
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )
    provider = DatabaseMcpOAuthProvider(session_factory=factory)
    client = OAuthClientInformationFull(
        client_id="postgres-concurrency-client",
        redirect_uris=["https://agent.example/callback"],
        token_endpoint_auth_method="none",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        scope=MCP_ACCESS_SCOPE,
        client_name="PostgreSQL Concurrency Test",
    )
    asyncio.run(provider.register_client(client))
    code = secrets.token_urlsafe(32)
    now = utcnow()
    with factory() as session:
        user = User(
            user_id="postgres-mcp-user",
            username="postgres-mcp-user",
            external_account_id="postgres-mcp-user",
            display_name="PostgreSQL MCP User",
            role="store",
            store_scope_mode="specified",
            status="active",
            is_initialized=True,
            password_hash="unused",
        )
        session.add(user)
        session.flush()
        grant = McpAuthorizationRequest(
            authorization_request_id="postgres-authorization-request",
            request_token_hash=hash_cli_secret("postgres-request-token"),
            client_id=client.client_id,
            environment="test",
            redirect_uri="https://agent.example/callback",
            redirect_uri_provided_explicitly=True,
            state="postgres-state",
            scopes=[MCP_ACCESS_SCOPE],
            code_challenge="c" * 43,
            resource=MCP_RESOURCE_URL,
            status="approved",
            code_hash=hash_cli_secret(code),
            subject=user.cli_subject,
            user_id=user.user_id,
            username=user.username,
            auth_type="user",
            authorization_fingerprint="",
            issued_auth_generation=user.auth_generation,
            created_at=now,
            expires_at=now + timedelta(minutes=10),
            approved_at=now,
        )
        session.add(grant)
        session.commit()
        authorization_code = DyDataAuthorizationCode(
            code=code,
            scopes=[MCP_ACCESS_SCOPE],
            expires_at=(now + timedelta(minutes=10)).timestamp(),
            client_id=client.client_id,
            code_challenge=grant.code_challenge,
            redirect_uri=grant.redirect_uri,
            redirect_uri_provided_explicitly=True,
            resource=MCP_RESOURCE_URL,
            subject=user.cli_subject,
            authorization_request_id=grant.authorization_request_id,
        )
    try:
        yield provider, factory, client, authorization_code
    finally:
        Base.metadata.drop_all(engine, tables=OAUTH_TABLES)
        engine.dispose()


def _race(callable_):
    barrier = Barrier(2)

    def invoke():
        barrier.wait()
        try:
            return "ok", asyncio.run(callable_())
        except TokenError as exc:
            return "invalid_grant", exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(invoke), executor.submit(invoke)]
        return [future.result(timeout=15) for future in futures]


def test_postgres_authorization_code_is_consumed_once_under_concurrency(
    postgres_oauth_stack,
) -> None:
    provider, factory, client, authorization_code = postgres_oauth_stack

    results = _race(
        lambda: provider.exchange_authorization_code(client, authorization_code)
    )

    assert sorted(status for status, _ in results) == ["invalid_grant", "ok"]
    with factory() as session:
        grant = session.get(
            McpAuthorizationRequest, authorization_code.authorization_request_id
        )
        assert grant is not None
        assert grant.status == "consumed"
        assert grant.consumed_at is not None
        assert len(session.scalars(select(McpAccessToken)).all()) == 1
        assert len(session.scalars(select(McpRefreshToken)).all()) == 1


def test_postgres_concurrent_refresh_allows_one_rotation_and_revokes_replay_family(
    postgres_oauth_stack,
) -> None:
    provider, factory, client, authorization_code = postgres_oauth_stack
    issued = asyncio.run(provider.exchange_authorization_code(client, authorization_code))
    refresh = asyncio.run(provider.load_refresh_token(client, issued.refresh_token or ""))
    assert refresh is not None

    results = _race(
        lambda: provider.exchange_refresh_token(client, refresh, [MCP_ACCESS_SCOPE])
    )

    assert sorted(status for status, _ in results) == ["invalid_grant", "ok"]
    with factory() as session:
        refresh_rows = session.scalars(select(McpRefreshToken)).all()
        access_rows = session.scalars(select(McpAccessToken)).all()
        assert len(refresh_rows) == 2
        assert len(access_rows) == 2
        assert all(row.revoked_at is not None for row in refresh_rows)
        assert all(row.revoked_at is not None for row in access_rows)
