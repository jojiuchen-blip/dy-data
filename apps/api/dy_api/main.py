from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator
from typing import Any, Callable

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

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
    fee_admin,
    feedback,
    jobs,
    mcp_auth,
    meta,
    operations,
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

    @app.exception_handler(StarletteHTTPException)
    async def structured_fee_admin_http_error(
        request: Request, exc: StarletteHTTPException
    ):
        if not _is_structured_contract_path(request.url.path):
            return await http_exception_handler(request, exc)
        if isinstance(exc.detail, dict) and exc.detail.get("code"):
            detail = exc.detail
        else:
            detail = {
                "code": _fee_admin_http_error_code(exc.status_code),
                "message": str(exc.detail or "请求失败"),
                "errors": [],
                "requestId": fee_admin._request_id(request),
            }
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": detail},
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def structured_fee_admin_validation_error(
        request: Request, exc: RequestValidationError
    ):
        if not _is_structured_contract_path(request.url.path):
            return await request_validation_exception_handler(request, exc)
        errors = []
        for item in exc.errors():
            location = item.get("loc") or ()
            errors.append(
                {
                    "field": str(location[-1]) if location else "request",
                    "reason": str(item.get("msg") or "字段不合法"),
                }
            )
        return JSONResponse(
            status_code=422,
            content={
                "detail": {
                    "code": "VALIDATION_FAILED",
                    "message": "请求字段校验失败",
                    "errors": errors,
                    "requestId": fee_admin._request_id(request),
                }
            },
        )

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
    install_cli_exception_handlers(
        app,
        http_fallback=structured_fee_admin_http_error,
        validation_fallback=structured_fee_admin_validation_error,
    )
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
    app.include_router(fee_admin.router, prefix="/api/v1/admin", tags=["fee-admin"])
    app.include_router(admin.router, prefix="/api/v1/admin", tags=["admin"])
    app.include_router(
        operations.router,
        prefix="/api/v1/admin/operations",
        tags=["admin-operations"],
    )
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


def _is_structured_contract_path(path: str) -> bool:
    return path.startswith(
        (
            "/api/v1/admin/sku-products",
            "/api/v1/admin/sku-fee-rules",
            "/api/v1/admin/sku-fee-rule-imports",
            "/api/v1/admin/settlement-scope-rules",
            "/api/v1/admin/product-sync-runs",
            "/api/v1/meta/filters",
            "/api/v1/dashboard/store-ranking",
            "/api/v1/order-fee-details",
            "/api/v1/store-settlements",
            "/api/v1/store-invoice-status",
            "/api/v1/promotion-invoices",
            "/api/v1/disputes",
            "/api/v1/admin/disputes",
            "/api/v1/admin/finance",
            "/api/v1/stores/",
        )
    )


def _fee_admin_http_error_code(status_code: int) -> str:
    return {
        400: "INVALID_REQUEST",
        401: "AUTH_REQUIRED",
        403: "DATA_SCOPE_FORBIDDEN",
        404: "RESOURCE_NOT_FOUND",
        409: "CONFLICT",
        422: "VALIDATION_FAILED",
        429: "RATE_LIMITED",
        500: "INTERNAL_ERROR",
        502: "DOUYIN_UPSTREAM_FAILED",
        503: "DATABASE_UNAVAILABLE",
    }.get(status_code, "REQUEST_FAILED")


app = create_app()
