from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from dy_api.routes import admin, auth, clues, dashboard, fee_admin, feedback, jobs, meta


def create_app() -> FastAPI:
    app = FastAPI(title="Douyin Laike Dashboard API", version="0.1.0")

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

    app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
    app.include_router(fee_admin.router, prefix="/api/v1/admin", tags=["fee-admin"])
    app.include_router(admin.router, prefix="/api/v1/admin", tags=["admin"])
    app.include_router(meta.router, prefix="/api/v1", tags=["metadata"])
    app.include_router(dashboard.router, prefix="/api/v1", tags=["dashboard"])
    app.include_router(clues.router, prefix="/api/v1", tags=["clues"])
    app.include_router(feedback.router, prefix="/api/v1", tags=["feedback"])
    app.include_router(jobs.router, prefix="/api/v1", tags=["jobs"])
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
