from __future__ import annotations

import json
import logging
import re
from time import perf_counter
from typing import Any, Callable, Protocol
from uuid import uuid4

from fastapi import Request, status
from starlette.middleware.base import BaseHTTPMiddleware

from dy_api.cli_contract import (
    cli_command_for_path,
    cli_error,
    cli_error_response,
    cli_operation_for_path,
    is_cli_audit_path,
    request_id_for_header,
)
from dy_api.db import get_session_factory
from apps.api.dy_api.models import CliAuditEvent


logger = logging.getLogger("dy_api.cli_audit")
_SAFE_CLIENT_METADATA = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+:-]{0,63}$")
AUTH_AUDIT_OPERATIONS = {
    "device_start",
    "device_approve",
    "device_exchange",
    "refresh",
    "revoke",
}


class CliAuditUnavailable(RuntimeError):
    """The authoritative CLI audit record could not be committed."""


class CliAuditSink(Protocol):
    def record(self, event: dict[str, Any]) -> None: ...

    def stage(self, session: Any, event: dict[str, Any]) -> None: ...


class DatabaseCliAuditSink:
    """Synchronously persist and confirm one authoritative CLI audit record."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Any | None] | None = None,
    ) -> None:
        self._session_factory = session_factory

    def stage(self, session: Any, event: dict[str, Any]) -> None:
        """Stage and flush an audit row in the caller's open transaction."""
        session.add(
            CliAuditEvent(
                audit_event_id=uuid4().hex,
                event_type=event["event"],
                operation=event["operation"],
                request_id=event["request_id"],
                command=event["command"],
                environment=event.get("environment", "test"),
                channel=event.get("channel", "cli"),
                user_id=event["user_id"],
                auth_type=event["auth_type"],
                authorization_scopes=event.get("authorization_scopes", []),
                cli_version=event["cli_version"],
                schema_version=event["schema_version"],
                date_range=event["date_range"],
                requested_store_ids=event["requested_store_ids"],
                effective_store_ids=event["effective_store_ids"],
                returned_store_count=event["returned_store_count"],
                result_status=event["result"],
                error_code=event["error_code"],
                duration_ms=event["duration_ms"],
            )
        )
        session.flush()

    def record(self, event: dict[str, Any]) -> None:
        factory = self._session_factory or get_session_factory()
        session = factory() if callable(factory) else None
        if session is None:
            raise CliAuditUnavailable("CLI audit storage is unavailable")
        try:
            self.stage(session, event)
            session.commit()
        except Exception:
            session.rollback()
            raise CliAuditUnavailable("CLI audit storage is unavailable") from None
        finally:
            session.close()


def configure_cli_audit_logging() -> None:
    """Keep the non-authoritative JSON mirror visible in default deployments."""
    logger.disabled = False
    logger.setLevel(logging.INFO)


def _safe_client_metadata(value: str | None) -> str | None:
    candidate = (value or "").strip()
    if not candidate or not _SAFE_CLIENT_METADATA.fullmatch(candidate):
        return None
    return candidate


def _observability_log(event: dict[str, Any]) -> None:
    try:
        logger.info(json.dumps(event, ensure_ascii=False, separators=(",", ":")))
    except Exception:
        # The committed audit sink is authoritative; logging is only a mirror.
        return


def _audit_event(
    request: Request,
    *,
    operation: str,
    command: str,
    result_status: int,
    error_code: str | None,
) -> dict[str, Any]:
    started = getattr(request.state, "cli_audit_started", perf_counter())
    return {
        "event": "cli_auth" if operation in AUTH_AUDIT_OPERATIONS else "cli_request",
        "operation": operation,
        "request_id": getattr(request.state, "cli_request_id", None)
        or request_id_for_header(request.headers.get("x-request-id")),
        "environment": "test",
        "channel": "cli",
        "user_id": getattr(request.state, "cli_user_id", None),
        "auth_type": getattr(request.state, "cli_auth_type", None),
        "authorization_scopes": ["cli:read"],
        "cli_version": _safe_client_metadata(
            request.headers.get("x-dydata-cli-version")
        ),
        "command": command,
        "schema_version": _safe_client_metadata(
            request.headers.get("x-dydata-schema-version")
        ),
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
        "result": result_status,
        "error_code": error_code,
        "duration_ms": round((perf_counter() - started) * 1000, 2),
    }


def commit_auth_audit(
    request: Request,
    session: Any,
    *,
    operation: str,
    result_status: int = status.HTTP_200_OK,
    error_code: str | None = None,
) -> None:
    """Commit auth state and its audit row as one database transaction."""
    command = cli_command_for_path(request.url.path) or "unknown"
    event = _audit_event(
        request,
        operation=operation,
        command=command,
        result_status=result_status,
        error_code=error_code,
    )
    request.state.cli_auth_audit_handled = True
    sink: CliAuditSink = getattr(
        request.app.state, "cli_audit_sink", DatabaseCliAuditSink()
    )
    try:
        sink.stage(session, event)
        session.commit()
    except Exception:
        session.rollback()
        cli_error(
            "API_UNAVAILABLE",
            "The audit service is unavailable",
            command=command,
            request_id=event["request_id"],
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    _observability_log(event)


class CliAuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not is_cli_audit_path(request.url.path):
            return await call_next(request)

        started = perf_counter()
        request.state.cli_audit_started = started
        request_id = request_id_for_header(request.headers.get("x-request-id"))
        request.state.cli_request_id = request_id
        command = cli_command_for_path(request.url.path) or "unknown"
        operation = cli_operation_for_path(request.url.path) or "unknown"
        try:
            response = await call_next(request)
        except Exception:
            if command == "unknown":
                raise
            response = cli_error_response(
                request,
                code="INTERNAL_ERROR",
                message="The request could not be completed",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                command=command,
            )

        if operation in AUTH_AUDIT_OPERATIONS and getattr(
            request.state, "cli_auth_audit_handled", False
        ):
            response.headers["X-Request-ID"] = request_id
            return response

        event = _audit_event(
            request,
            operation=operation,
            command=command,
            result_status=response.status_code,
            error_code=getattr(request.state, "cli_error_code", None),
        )
        sink: CliAuditSink = getattr(
            request.app.state, "cli_audit_sink", DatabaseCliAuditSink()
        )
        try:
            sink.record(event)
        except Exception:
            response = cli_error_response(
                request,
                code="API_UNAVAILABLE",
                message="The audit service is unavailable",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                command=command,
            )
        else:
            _observability_log(event)
        response.headers["X-Request-ID"] = request_id
        return response
