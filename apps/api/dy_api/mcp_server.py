"""Remote MCP transport and OAuth discovery wiring."""

from __future__ import annotations

import os
import re
import json
from time import perf_counter
from types import SimpleNamespace
from typing import Any, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from mcp.server.auth.handlers.authorize import AuthorizationHandler
from mcp.server.auth.handlers.register import RegistrationHandler
from mcp.server.auth.handlers.token import TokenHandler
from mcp.server.auth.middleware.client_auth import ClientAuthenticator
from mcp.server.auth.settings import (
    AuthSettings,
    ClientRegistrationOptions,
    RevocationOptions,
)
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp import Context
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from fastapi.encoders import jsonable_encoder

from apps.api.dy_api.cli_audit import DatabaseCliAuditSink
from apps.cli.src.dydata_cli.constants import CLI_SCHEMA_VERSION
from apps.cli.src.dydata_cli.registry import command_catalog, mcp_capability_catalog
from dy_api.agent_capabilities import (
    AgentCapabilityError,
    clues_follow_up_stats as shared_clues_follow_up_stats,
    stores_list as shared_stores_list,
)
from dy_api.cli_contract import cli_error_payload, request_id_for_header
from dy_api.routes._data import DashboardDataStore

from dy_api.mcp_oauth import (
    MCP_ACCESS_SCOPE,
    MCP_RESOURCE_URL,
    TEST_ISSUER_URL,
    DatabaseMcpOAuthProvider,
    McpAccessAuthorizationError,
)


PKCE_VERIFIER_PATTERN = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def authorization_server_metadata() -> dict[str, Any]:
    """Advertise the public-client-only OAuth surface used by MCP Agents."""
    return {
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


def protected_resource_metadata() -> dict[str, Any]:
    """Return RFC 9728 metadata for the single fixed MCP audience."""
    return {
        "resource": MCP_RESOURCE_URL,
        "authorization_servers": [TEST_ISSUER_URL],
        "scopes_supported": [MCP_ACCESS_SCOPE],
        "bearer_methods_supported": ["header"],
    }


def create_mcp_server(
    provider: DatabaseMcpOAuthProvider,
    *,
    data_store_factory: Callable[[Any], Any] | None = None,
) -> FastMCP:
    """Create the stateless Streamable HTTP server for the test environment."""
    allowed_hosts = ["dy-business-engine.com", "dy-business-engine.com:*"]
    allowed_origins = [TEST_ISSUER_URL]
    if _truthy(os.getenv("DY_API_TEST_MODE")):
        allowed_hosts.extend(["testserver", "testserver:*"])
        allowed_origins.append("https://testserver")
    server = FastMCP(
        name="dydata-read-only",
        instructions=(
            "Read-only access to the current user's authorized stores and clue "
            "follow-up statistics."
        ),
        website_url=TEST_ISSUER_URL,
        auth_server_provider=provider,
        auth=AuthSettings(
            issuer_url=TEST_ISSUER_URL,
            resource_server_url=MCP_RESOURCE_URL,
            required_scopes=[MCP_ACCESS_SCOPE],
            client_registration_options=ClientRegistrationOptions(
                enabled=True,
                valid_scopes=[MCP_ACCESS_SCOPE],
                default_scopes=[MCP_ACCESS_SCOPE],
            ),
            revocation_options=RevocationOptions(enabled=True),
        ),
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts,
            allowed_origins=allowed_origins,
        ),
    )
    _install_read_only_tools(
        server,
        provider,
        data_store_factory=data_store_factory or DashboardDataStore,
    )
    return server


def _tool_request_id(context: Context) -> str:
    return request_id_for_header(str(context.request_id))


def _with_mcp_channel(payload: dict[str, Any]) -> dict[str, Any]:
    encoded = jsonable_encoder(payload)
    encoded["meta"] = {**encoded.get("meta", {}), "channel": "mcp"}
    return encoded


def _tool_result(payload: dict[str, Any], *, is_error: bool) -> CallToolResult:
    encoded = _with_mcp_channel(payload)
    return CallToolResult(
        content=[
            TextContent(
                type="text",
                text=json.dumps(encoded, ensure_ascii=False, separators=(",", ":")),
            )
        ],
        structuredContent=encoded,
        isError=is_error,
    )


def _mcp_audit_event(
    *,
    token: Any,
    auth: Any,
    request_id: str,
    command: str,
    operation: str,
    result_status: int,
    error_code: str | None,
    started: float,
    requested_store_ids: list[str],
    effective_store_ids: list[str],
    date_range: list[str] | None,
    returned_store_count: int,
) -> dict[str, Any]:
    return {
        "event": "mcp_request",
        "operation": operation,
        "request_id": request_id,
        "environment": "test",
        "channel": "mcp",
        "user_id": auth.user_id,
        "auth_type": auth.auth_type,
        "authorization_scopes": list(token.scopes),
        "cli_version": None,
        "command": command,
        "schema_version": CLI_SCHEMA_VERSION,
        "date_range": date_range,
        "requested_store_ids": requested_store_ids,
        "effective_store_ids": effective_store_ids,
        "returned_store_count": returned_store_count,
        "result": result_status,
        "error_code": error_code,
        "duration_ms": round((perf_counter() - started) * 1000, 2),
    }


def _install_read_only_tools(
    server: FastMCP,
    provider: DatabaseMcpOAuthProvider,
    *,
    data_store_factory: Callable[[Any], Any],
) -> None:
    catalog = {item["command"]: item for item in command_catalog()}
    bindings = mcp_capability_catalog()
    if {binding["tool"] for binding in bindings} != {
        "stores_list",
        "clues_follow_up_stats",
    } or not all(binding["read_only"] for binding in bindings):
        raise RuntimeError("The MCP registry must contain exactly two read-only tools")

    annotations = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )

    async def run_capability(
        *,
        context: Context,
        command: str,
        operation: str,
        arguments: dict[str, Any],
    ) -> CallToolResult:
        started = perf_counter()
        request_id = _tool_request_id(context)
        token = get_access_token()
        if token is None or not hasattr(token, "access_token_id"):
            return _tool_result(
                cli_error_payload(
                    "AUTH_EXPIRED",
                    "MCP authorization is no longer valid",
                    command=command,
                    request_id=request_id,
                ),
                is_error=True,
            )

        with provider.session() as session:
            try:
                auth = provider.current_auth_for_access_token(session, token)
            except McpAccessAuthorizationError:
                claims = token.claims or {}
                auth = SimpleNamespace(
                    user_id=claims.get("user_id"),
                    auth_type=claims.get("auth_type"),
                )
                payload = cli_error_payload(
                    "AUTH_EXPIRED",
                    "MCP authorization is no longer valid",
                    command=command,
                    request_id=request_id,
                )
                DatabaseCliAuditSink().stage(
                    session,
                    _mcp_audit_event(
                        token=token,
                        auth=auth,
                        request_id=request_id,
                        command=command,
                        operation=operation,
                        result_status=401,
                        error_code="AUTH_EXPIRED",
                        started=started,
                        requested_store_ids=[],
                        effective_store_ids=[],
                        date_range=None,
                        returned_store_count=0,
                    ),
                )
                return _tool_result(payload, is_error=True)
            store = data_store_factory(session)
            try:
                if command == "stores.list":
                    payload = shared_stores_list(
                        current_user=auth,
                        store=store,
                        request_id=request_id,
                    )
                else:
                    payload = shared_clues_follow_up_stats(
                        current_user=auth,
                        store=store,
                        request_id=request_id,
                        **arguments,
                    )
            except AgentCapabilityError as exc:
                requested = exc.requested_store_ids
                effective = exc.effective_store_ids
                date_range = exc.date_range
                result_status = exc.status_code
                error_code = exc.code
                payload = cli_error_payload(
                    exc.code,
                    exc.message,
                    command=command,
                    request_id=request_id,
                )
                returned_count = 0
                is_error = True
            else:
                scope = payload.get("scope", {})
                requested = list(scope.get("requested_store_ids", []))
                effective = list(scope.get("effective_store_ids", []))
                filters = payload.get("filters")
                date_range = (
                    [
                        filters["assigned_date_start"],
                        filters["assigned_date_end"],
                    ]
                    if filters
                    else None
                )
                result_status = 200
                error_code = None
                returned_count = len(payload["data"]["stores"])
                is_error = False

            DatabaseCliAuditSink().stage(
                session,
                _mcp_audit_event(
                    token=token,
                    auth=auth,
                    request_id=request_id,
                    command=command,
                    operation=operation,
                    result_status=result_status,
                    error_code=error_code,
                    started=started,
                    requested_store_ids=requested,
                    effective_store_ids=effective,
                    date_range=date_range,
                    returned_store_count=returned_count,
                ),
            )
        return _tool_result(payload, is_error=is_error)

    async def clues_follow_up_stats(
        context: Context,
        assigned_date_start: str | None = None,
        assigned_date_end: str | None = None,
        store_ids: list[str] | None = None,
    ) -> CallToolResult:
        """Read clue follow-up statistics for stores authorized to the current account."""
        return await run_capability(
            context=context,
            command="clues.follow-up-stats",
            operation="follow_up_stats",
            arguments={
                "assigned_date_start": assigned_date_start,
                "assigned_date_end": assigned_date_end,
                "store_ids": store_ids,
            },
        )

    async def stores_list(context: Context) -> CallToolResult:
        """Read the complete store scope authorized to the current account."""
        return await run_capability(
            context=context,
            command="stores.list",
            operation="stores_list",
            arguments={},
        )

    handlers = {
        "clues_follow_up_stats": clues_follow_up_stats,
        "stores_list": stores_list,
    }
    for binding in bindings:
        item = catalog[binding["command"]]
        server.tool(
            name=binding["tool"],
            description=item["purpose"],
            annotations=annotations,
            structured_output=False,
        )(handlers[binding["tool"]])


def install_mcp_public_routes(
    app: FastAPI, provider: DatabaseMcpOAuthProvider
) -> None:
    """Install deterministic discovery and resource-bound token handling."""
    registration_options = ClientRegistrationOptions(
        enabled=True,
        valid_scopes=[MCP_ACCESS_SCOPE],
        default_scopes=[MCP_ACCESS_SCOPE],
    )
    registration_handler = RegistrationHandler(provider, options=registration_options)
    authorization_handler = AuthorizationHandler(provider)
    token_handler = TokenHandler(provider, ClientAuthenticator(provider))

    @app.get(
        "/.well-known/oauth-authorization-server", include_in_schema=False
    )
    async def oauth_authorization_server_metadata() -> JSONResponse:
        return JSONResponse(
            authorization_server_metadata(),
            headers={"Access-Control-Allow-Origin": "*"},
        )

    @app.get(
        "/.well-known/oauth-protected-resource/mcp", include_in_schema=False
    )
    async def oauth_protected_resource_metadata() -> JSONResponse:
        return JSONResponse(
            protected_resource_metadata(),
            headers={"Access-Control-Allow-Origin": "*"},
        )

    @app.post("/register", include_in_schema=False)
    async def oauth_register(request: Request) -> Response:
        response = await registration_handler.handle(request)
        response.headers["Access-Control-Allow-Origin"] = "*"
        return response

    @app.options("/register", include_in_schema=False)
    async def oauth_register_options() -> Response:
        return Response(
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
            },
        )

    @app.api_route(
        "/authorize", methods=["GET", "POST"], include_in_schema=False
    )
    async def oauth_authorize(request: Request) -> Response:
        return await authorization_handler.handle(request)

    @app.post("/token", include_in_schema=False)
    async def oauth_token(request: Request) -> Response:
        form = await request.form()
        if str(form.get("resource") or "") != MCP_RESOURCE_URL:
            return JSONResponse(
                {
                    "error": "invalid_request",
                    "error_description": f"resource must be {MCP_RESOURCE_URL}",
                },
                status_code=400,
                headers={
                    "Cache-Control": "no-store",
                    "Pragma": "no-cache",
                    "Access-Control-Allow-Origin": "*",
                },
            )
        if str(form.get("grant_type") or "") == "authorization_code":
            verifier = str(form.get("code_verifier") or "")
            if PKCE_VERIFIER_PATTERN.fullmatch(verifier) is None:
                return JSONResponse(
                    {
                        "error": "invalid_request",
                        "error_description": "code_verifier is malformed",
                    },
                    status_code=400,
                    headers={
                        "Cache-Control": "no-store",
                        "Pragma": "no-cache",
                        "Access-Control-Allow-Origin": "*",
                    },
                )
        response = await token_handler.handle(request)
        response.headers["Access-Control-Allow-Origin"] = "*"
        return response

    @app.options("/token", include_in_schema=False)
    async def oauth_token_options() -> Response:
        return Response(
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, MCP-Protocol-Version",
            },
        )

    @app.post("/revoke", include_in_schema=False)
    async def oauth_revoke(request: Request) -> Response:
        form = await request.form()
        client_id = str(form.get("client_id") or "")
        raw_token = str(form.get("token") or "")
        client = await provider.get_client(client_id) if client_id else None
        if client is None or client.token_endpoint_auth_method != "none":
            return JSONResponse(
                {
                    "error": "unauthorized_client",
                    "error_description": "Invalid public client",
                },
                status_code=401,
                headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
            )
        if not raw_token:
            return JSONResponse(
                {
                    "error": "invalid_request",
                    "error_description": "token is required",
                },
                status_code=400,
                headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
            )
        token = await provider.load_access_token(raw_token)
        if token is None:
            token = await provider.load_refresh_token(client, raw_token)
        if token is not None and token.client_id == client_id:
            await provider.revoke_token(token)
        return Response(
            status_code=200,
            headers={
                "Cache-Control": "no-store",
                "Pragma": "no-cache",
                "Access-Control-Allow-Origin": "*",
            },
        )

    @app.options("/revoke", include_in_schema=False)
    async def oauth_revoke_options() -> Response:
        return Response(
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
            },
        )
