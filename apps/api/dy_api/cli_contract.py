from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


CLI_SCHEMA_VERSION = "1.0"
CLI_METRIC_VERSION = "clue-follow-up-v1"
CLI_RETRYABLE_ERRORS = {"API_UNAVAILABLE", "RATE_LIMITED"}
CLI_COMMANDS_BY_PATH = {
    "/api/v1/auth/cli/device/start": "auth.login",
    "/api/v1/auth/cli/device/approve": "auth.login",
    "/api/v1/auth/cli/device/token": "auth.login",
    "/api/v1/auth/cli/token/refresh": "auth.refresh",
    "/api/v1/auth/cli/revoke": "auth.logout",
    "/api/v1/cli/auth/status": "auth.status",
    "/api/v1/cli/stores": "stores.list",
    "/api/v1/clues/store-follow-up-summary": "clues.follow-up-stats",
}
CLI_OPERATIONS_BY_PATH = {
    "/api/v1/auth/cli/device/start": "device_start",
    "/api/v1/auth/cli/device/approve": "device_approve",
    "/api/v1/auth/cli/device/token": "device_exchange",
    "/api/v1/auth/cli/token/refresh": "refresh",
    "/api/v1/auth/cli/revoke": "revoke",
    "/api/v1/cli/auth/status": "auth_status",
    "/api/v1/cli/stores": "stores_list",
    "/api/v1/clues/store-follow-up-summary": "follow_up_stats",
}
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def cli_command_for_path(path: str) -> str | None:
    return CLI_COMMANDS_BY_PATH.get(path.rstrip("/") or "/")


def cli_operation_for_path(path: str) -> str | None:
    return CLI_OPERATIONS_BY_PATH.get(path.rstrip("/") or "/")


def is_cli_audit_path(path: str) -> bool:
    normalized = path.rstrip("/") or "/"
    return normalized in CLI_OPERATIONS_BY_PATH


def request_id_for_header(value: str | None) -> str:
    candidate = (value or "").strip()
    if candidate and _SAFE_REQUEST_ID.fullmatch(candidate):
        return candidate
    return f"req_{uuid4().hex}"


def cli_error_payload(
    code: str,
    message: str,
    *,
    command: str,
    request_id: str,
) -> dict[str, Any]:
    return {
        "ok": False,
        "command": command,
        "schema_version": CLI_SCHEMA_VERSION,
        "error": {
            "code": code,
            "message": message,
            "retryable": code in CLI_RETRYABLE_ERRORS,
            "request_id": request_id,
        },
    }


def cli_error(
    code: str,
    message: str,
    *,
    command: str,
    request_id: str,
    status_code: int,
) -> None:
    raise HTTPException(
        status_code=status_code,
        detail=cli_error_payload(
            code,
            message,
            command=command,
            request_id=request_id,
        ),
    )


def cli_error_response(
    request: Request,
    *,
    code: str,
    message: str,
    status_code: int,
    command: str | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    resolved_command = command or cli_command_for_path(request.url.path) or "unknown"
    request_id = getattr(request.state, "cli_request_id", None) or request_id_for_header(
        request.headers.get("x-request-id")
    )
    request.state.cli_request_id = request_id
    request.state.cli_error_code = code
    response_headers = dict(headers or {})
    response_headers["X-Request-ID"] = request_id
    return JSONResponse(
        status_code=status_code,
        content=cli_error_payload(
            code,
            message,
            command=resolved_command,
            request_id=request_id,
        ),
        headers=response_headers,
    )


def _auth_error_code(request: Request) -> tuple[str, str]:
    if request.headers.get("authorization", "").strip():
        return "AUTH_EXPIRED", "CLI authentication is invalid or expired"
    return "AUTH_REQUIRED", "CLI authentication is required"


def install_cli_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def cli_http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ):
        command = cli_command_for_path(request.url.path)
        is_cli_contract_path = is_cli_audit_path(
            request.url.path
        ) or request.url.path.startswith("/api/v1/cli/")
        if not is_cli_contract_path:
            return await http_exception_handler(request, exc)

        if isinstance(exc.detail, dict) and set(exc.detail) == {
            "ok",
            "command",
            "schema_version",
            "error",
        }:
            code = str(exc.detail.get("error", {}).get("code") or "INTERNAL_ERROR")
            request.state.cli_error_code = code
            return JSONResponse(
                status_code=exc.status_code,
                content=exc.detail,
                headers=exc.headers,
            )

        if exc.status_code in {
            status.HTTP_404_NOT_FOUND,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        }:
            code, message = "INVALID_ARGUMENT", "Unknown CLI path or method"
        elif exc.status_code == status.HTTP_401_UNAUTHORIZED:
            code, message = _auth_error_code(request)
        elif exc.status_code == status.HTTP_403_FORBIDDEN:
            code, message = "SCOPE_DENIED", "Requested scope is not permitted"
        elif exc.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
            code, message = "RATE_LIMITED", "Too many requests"
        elif exc.status_code == status.HTTP_503_SERVICE_UNAVAILABLE:
            code, message = "API_UNAVAILABLE", "The data service is unavailable"
        else:
            code, message = "INTERNAL_ERROR", "The request could not be completed"
        return cli_error_response(
            request,
            code=code,
            message=message,
            status_code=exc.status_code,
            command=command or "unknown",
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def cli_validation_exception_handler(
        request: Request, exc: RequestValidationError
    ):
        command = cli_command_for_path(request.url.path)
        if command is None:
            return await request_validation_exception_handler(request, exc)
        return cli_error_response(
            request,
            code="INVALID_ARGUMENT",
            message="Invalid request arguments",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            command=command,
        )
