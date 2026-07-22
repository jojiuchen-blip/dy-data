from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator
from typing import Any, Callable

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dy_api.agent_environment import validate_agent_environment
from dy_api.cli_audit import (
    CliAuditMiddleware,
    DatabaseCliAuditSink,
    configure_cli_audit_logging,
)
from dy_api.cli_contract import install_cli_exception_handlers
from dy_api.mcp_oauth import DatabaseMcpOAuthProvider
from dy_api.mcp_server import create_mcp_server, install_mcp_public_routes
from dy_api.routes import (
    agent,
    admin,
    auth,
    cli,
    cli_auth,
    clues,
    dashboard,
    feedback,
    jobs,
    mcp_auth,
    meta,
)


def create_app(
    *,
    mcp_provider: DatabaseMcpOAuthProvider | None = None,
    mcp_data_store_factory: Callable[[Any], Any] | None = None,
) -> FastAPI:
    validate_agent_environment()
    configure_cli_audit_logging()
    oauth_provider = mcp_provider or DatabaseMcpOAuthProvider()
    mcp_server = create_mcp_server(
        oauth_provider, data_store_factory=mcp_data_store_factory
    )
    mcp_http_app = mcp_server.streamable_http_app()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        async with mcp_server.session_manager.run():
            yield

    app = FastAPI(
        title="Douyin Laike Dashboard API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.cli_audit_sink = DatabaseCliAuditSink()
    app.state.mcp_oauth_provider = oauth_provider
    app.state.mcp_server = mcp_server

    allowed_origins = [
        origin.strip()
        for origin in os.getenv("DY_API_CORS_ORIGINS", "").split(",")
        if origin.strip()
    ]
    if allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT"],
            allow_headers=["*"],
        )

    app.add_middleware(CliAuditMiddleware)
    install_cli_exception_handlers(app)
    install_mcp_public_routes(app, oauth_provider)

    app.include_router(agent.router, tags=["agent-discovery"])
    app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
    app.include_router(
        cli_auth.router, prefix="/api/v1/auth/cli", tags=["cli-auth"]
    )
    app.include_router(
        mcp_auth.router, prefix="/api/v1/auth/mcp", tags=["mcp-auth"]
    )
    app.include_router(cli.router, prefix="/api/v1", tags=["cli-readonly"])
    app.include_router(admin.router, prefix="/api/v1/admin", tags=["admin"])
    app.include_router(meta.router, prefix="/api/v1", tags=["metadata"])
    app.include_router(dashboard.router, prefix="/api/v1", tags=["dashboard"])
    app.include_router(clues.router, prefix="/api/v1", tags=["clues"])
    app.include_router(feedback.router, prefix="/api/v1", tags=["feedback"])
    app.include_router(jobs.router, prefix="/api/v1", tags=["jobs"])
    app.add_route(
        "/mcp",
        mcp_http_app,
        methods=["GET", "POST", "DELETE"],
        name="mcp",
        include_in_schema=False,
    )
    return app


app = create_app()
