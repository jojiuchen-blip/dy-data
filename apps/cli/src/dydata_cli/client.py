"""Strict HTTP client for the approved read-only dydata API surface."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from datetime import date
from typing import Any
from uuid import uuid4

import httpx

from .constants import CLI_SCHEMA_VERSION, CLI_VERSION, ERROR_CONTRACTS
from .contracts import (
    ContractError,
    validate_authorization_pending,
    validate_auth_status,
    validate_device_start,
    validate_follow_up_stats,
    validate_revoke_response,
    validate_stores,
    validate_token_response,
    normalize_store_ids,
)
from .errors import error_message, error_retryable, safe_request_id
from .url_security import normalize_safe_url


DEFAULT_API_URL = "http://127.0.0.1:8000/api/v1"
_RETRYABLE_STATUS_CODES = {429}


class CliError(Exception):
    """A sanitized, stable CLI error suitable for output mapping."""

    def __init__(
        self,
        code: str,
        *,
        request_id: str | None = None,
        retryable: bool | None = None,
    ) -> None:
        self.code = code if code in ERROR_CONTRACTS else "INTERNAL_ERROR"
        self.request_id = safe_request_id(request_id)
        self.retryable = error_retryable(self.code, retryable)
        super().__init__(error_message(self.code))


def _normalize_base_url(value: str) -> str:
    try:
        return normalize_safe_url(value, trailing_slash=True)
    except ValueError:
        raise CliError("INVALID_ARGUMENT") from None


class DyDataClient:
    """Call only the explicitly approved authentication and read-only APIs."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 10.0,
        max_attempts: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        configured_url = base_url or os.getenv("DYDATA_API_URL") or DEFAULT_API_URL
        normalized_url = _normalize_base_url(configured_url)
        self._http = httpx.Client(
            base_url=normalized_url,
            timeout=timeout,
            transport=transport,
        )
        self._max_attempts = max(1, max_attempts)
        self._sleep = sleep

    def start_device_authorization(self) -> dict[str, Any]:
        """Start an anonymous browser/device authorization flow."""
        return self._request(
            "POST",
            "auth/cli/device/start",
            command="auth.login",
            validator=validate_device_start,
        )

    def poll_device_token(self, device_code: str) -> dict[str, Any]:
        """Poll an authorization request for a token response."""
        return self._request(
            "POST",
            "auth/cli/device/token",
            command="auth.login",
            json_body={"device_code": device_code},
            allow_pending=True,
            validator=validate_token_response,
            pending_validator=validate_authorization_pending,
        )

    def refresh(self, refresh_token: str) -> dict[str, Any]:
        """Rotate a refresh credential and return fresh token material."""
        return self._request(
            "POST",
            "auth/cli/token/refresh",
            command="auth.refresh",
            json_body={"refresh_token": refresh_token},
            validator=validate_token_response,
        )

    def revoke(self, refresh_token: str) -> None:
        """Revoke a refresh credential without returning server content."""
        self._request(
            "POST",
            "auth/cli/revoke",
            command="auth.logout",
            json_body={"refresh_token": refresh_token},
            validator=validate_revoke_response,
        )

    def auth_status(self, access_token: str) -> dict[str, Any]:
        """Return the authenticated identity and current authorization scope."""
        return self._request(
            "GET",
            "cli/auth/status",
            command="auth.status",
            access_token=access_token,
            validator=validate_auth_status,
        )

    def list_stores(self, access_token: str) -> dict[str, Any]:
        """List stores in the current server-evaluated authorization scope."""
        return self._request(
            "GET",
            "cli/stores",
            command="stores.list",
            access_token=access_token,
            validator=validate_stores,
        )

    def follow_up_stats(
        self,
        access_token: str,
        *,
        date_from: date,
        date_to: date,
        store_ids: list[str],
    ) -> dict[str, Any]:
        """Return aggregate clue follow-up statistics for authorized stores."""
        normalized_store_ids = normalize_store_ids(store_ids)
        params = [
            ("assigned_date_start", date_from.isoformat()),
            ("assigned_date_end", date_to.isoformat()),
            *(("store_id", store_id) for store_id in normalized_store_ids),
        ]
        return self._request(
            "GET",
            "clues/store-follow-up-summary",
            command="clues.follow-up-stats",
            access_token=access_token,
            params=params,
            validator=lambda payload, request_id: validate_follow_up_stats(
                payload,
                request_id,
                expected_store_ids=normalized_store_ids,
                expected_date_start=date_from,
                expected_date_end=date_to,
            ),
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        command: str,
        access_token: str | None = None,
        json_body: dict[str, str] | None = None,
        params: list[tuple[str, str]] | None = None,
        validator: Callable[
            [dict[str, Any], str | None], dict[str, Any]
        ] | None = None,
        allow_pending: bool = False,
        pending_validator: Callable[
            [dict[str, Any], str | None], dict[str, Any]
        ] | None = None,
    ) -> dict[str, Any]:
        # One logical call keeps one correlation ID across every retry attempt.
        request_id = f"req_{uuid4().hex}"
        headers = {
            "X-DyData-CLI-Version": CLI_VERSION,
            "X-DyData-Command": command,
            "X-DyData-Schema-Version": CLI_SCHEMA_VERSION,
            "X-Request-ID": request_id,
        }
        if access_token is not None:
            headers["Authorization"] = f"Bearer {access_token}"

        response: httpx.Response | None = None
        max_attempts = self._max_attempts if method.upper() == "GET" else 1
        for attempt in range(max_attempts):
            try:
                response = self._http.request(
                    method,
                    path,
                    headers=headers,
                    json=json_body,
                    params=params,
                )
            except httpx.RequestError:
                if attempt + 1 >= max_attempts:
                    raise CliError("API_UNAVAILABLE", request_id=request_id) from None
                self._backoff(attempt)
                continue
            if self._is_retryable_status(response.status_code):
                if attempt + 1 < max_attempts:
                    self._backoff(attempt)
                    continue
            break

        if response is None:
            raise CliError("API_UNAVAILABLE", request_id=request_id)
        if allow_pending and response.status_code == 202:
            payload = self._json_object(response, request_id=request_id)
            return self._validated_payload(payload, pending_validator, request_id)
        if 200 <= response.status_code < 300:
            payload = self._json_object(response, request_id=request_id)
            return self._validated_payload(payload, validator, request_id)
        raise self._response_error(response, fallback_request_id=request_id)

    @staticmethod
    def _validated_payload(
        payload: dict[str, Any],
        validator: Callable[[dict[str, Any], str | None], dict[str, Any]] | None,
        request_id: str,
    ) -> dict[str, Any]:
        if validator is None:
            return payload
        try:
            return validator(payload, request_id)
        except ContractError:
            raise CliError("SCHEMA_MISMATCH", request_id=request_id) from None

    def _backoff(self, attempt: int) -> None:
        self._sleep(min(0.1 * (2**attempt), 1.0))

    @staticmethod
    def _is_retryable_status(status_code: int) -> bool:
        return status_code in _RETRYABLE_STATUS_CODES or status_code >= 500

    @staticmethod
    def _json_object(
        response: httpx.Response, *, request_id: str
    ) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError:
            raise CliError("SCHEMA_MISMATCH", request_id=request_id) from None
        if not isinstance(payload, dict):
            raise CliError("SCHEMA_MISMATCH", request_id=request_id)
        return payload

    @staticmethod
    def _response_error(
        response: httpx.Response, *, fallback_request_id: str
    ) -> CliError:
        request_id = fallback_request_id
        server_code: str | None = None
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                candidate = error.get("code")
                if isinstance(candidate, str) and candidate in ERROR_CONTRACTS:
                    server_code = candidate
                candidate_request_id = error.get("request_id")
                if candidate_request_id == fallback_request_id:
                    request_id = candidate_request_id
        if server_code is not None:
            return CliError(
                server_code,
                request_id=request_id,
            )
        status_code = response.status_code
        if status_code == 401:
            code = "AUTH_EXPIRED"
        elif status_code == 403:
            code = "SCOPE_DENIED"
        elif status_code == 429:
            code = "RATE_LIMITED"
        elif status_code in {400, 404, 405, 422}:
            code = "INVALID_ARGUMENT"
        elif status_code >= 500:
            code = "API_UNAVAILABLE"
        else:
            code = "INTERNAL_ERROR"
        return CliError(code, request_id=request_id)
