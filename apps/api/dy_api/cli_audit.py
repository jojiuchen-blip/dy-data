from __future__ import annotations

import json
import logging
from time import perf_counter

from fastapi import Request, status
from starlette.middleware.base import BaseHTTPMiddleware

from dy_api.cli_contract import (
    cli_command_for_path,
    cli_error_response,
    is_cli_audit_path,
    request_id_for_header,
)


logger = logging.getLogger("dy_api.cli_audit")


class CliAuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not is_cli_audit_path(request.url.path):
            return await call_next(request)

        started = perf_counter()
        request_id = request_id_for_header(request.headers.get("x-request-id"))
        request.state.cli_request_id = request_id
        try:
            response = await call_next(request)
        except Exception:
            command = cli_command_for_path(request.url.path)
            if command is None:
                raise
            response = cli_error_response(
                request,
                code="INTERNAL_ERROR",
                message="The request could not be completed",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                command=command,
            )

        event = {
            "event": "cli_request",
            "request_id": request_id,
            "user_id": getattr(request.state, "cli_user_id", None),
            "auth_type": getattr(request.state, "cli_auth_type", None),
            "cli_version": request.headers.get("x-dydata-cli-version"),
            "command": request.headers.get("x-dydata-command")
            or cli_command_for_path(request.url.path),
            "schema_version": request.headers.get("x-dydata-schema-version"),
            "date_range": getattr(request.state, "cli_date_range", None),
            "requested_store_ids": getattr(
                request.state, "cli_requested_store_ids", []
            ),
            "effective_store_ids": getattr(
                request.state, "cli_effective_store_ids", []
            ),
            "returned_store_count": getattr(
                request.state, "cli_returned_store_count", 0
            ),
            "result": response.status_code,
            "error_code": getattr(request.state, "cli_error_code", None),
            "duration_ms": round((perf_counter() - started) * 1000, 2),
        }
        logger.info(json.dumps(event, ensure_ascii=False, separators=(",", ":")))
        response.headers["X-Request-ID"] = request_id
        return response

