"""Isolated Web-session bridge for human-controlled terminal login."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

import httpx

from .client import CliError
from .constants import CLI_SCHEMA_VERSION, CLI_VERSION
from .environments import EnvironmentConfig, resolve_environment
from .url_security import normalize_safe_url


_LOGIN_DATA_FIELDS = {
    "display_name",
    "is_highest_admin",
    "is_initialized",
    "page_keys",
    "role",
    "status",
    "store_ids",
    "store_scope_mode",
    "user_id",
    "username",
}
_ROLES = {"highest_admin", "admin", "store"}
_STORE_SCOPE_MODES = {"all", "specified", "none"}


@dataclass(frozen=True)
class LoginIdentity:
    """Non-secret identity summary returned by the existing Web login."""

    username: str
    role: str
    store_scope_mode: str
    store_ids: tuple[str, ...]


class InteractiveAuthSession:
    """Keep the temporary Web cookie separate from the CLI business client."""

    def __init__(
        self,
        *,
        environment: EnvironmentConfig | None = None,
        base_url: str | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.environment = environment or resolve_environment()
        configured_url = base_url or self.environment.api_url
        try:
            normalized_url = normalize_safe_url(configured_url, trailing_slash=True)
        except ValueError:
            raise CliError("INVALID_ARGUMENT") from None
        self._http = httpx.Client(
            base_url=normalized_url,
            timeout=timeout,
            transport=transport,
        )

    def __enter__(self) -> "InteractiveAuthSession":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def login(self, username: str, password: str) -> LoginIdentity:
        """Create a temporary Web session and return only safe identity fields."""
        payload = self._post(
            "auth/login",
            json_body={"username": username, "password": password},
            unauthorized_code="AUTH_FAILED",
        )
        try:
            return _validate_login_identity(payload)
        except (KeyError, TypeError, ValueError):
            raise CliError("SCHEMA_MISMATCH") from None

    def approve_device_authorization(self, user_code: str) -> None:
        """Approve one device code with the temporary Web session cookie."""
        payload = self._post(
            "auth/cli/device/approve",
            json_body={"user_code": user_code},
            unauthorized_code="AUTH_FAILED",
        )
        try:
            _validate_approval(payload, expected_user_code=user_code)
        except (KeyError, TypeError, ValueError):
            raise CliError("SCHEMA_MISMATCH") from None

    def close(self) -> None:
        """Remove the temporary Web cookie and close the HTTP session."""
        self._http.cookies.clear()
        self._http.close()

    def _post(
        self,
        path: str,
        *,
        json_body: dict[str, str],
        unauthorized_code: str,
    ) -> dict[str, Any]:
        request_id = f"req_{uuid4().hex}"
        headers = {
            "X-DyData-CLI-Version": CLI_VERSION,
            "X-DyData-Command": "auth.login",
            "X-DyData-Schema-Version": CLI_SCHEMA_VERSION,
            "X-Request-ID": request_id,
        }
        try:
            response = self._http.post(path, headers=headers, json=json_body)
        except httpx.RequestError:
            raise CliError("API_UNAVAILABLE", request_id=request_id) from None
        if 200 <= response.status_code < 300:
            try:
                payload = response.json()
            except ValueError:
                raise CliError("SCHEMA_MISMATCH", request_id=request_id) from None
            if not isinstance(payload, dict):
                raise CliError("SCHEMA_MISMATCH", request_id=request_id)
            return payload
        raise CliError(
            _error_code(response.status_code, unauthorized_code=unauthorized_code),
            request_id=request_id,
        )


def _error_code(status_code: int, *, unauthorized_code: str) -> str:
    if status_code == 401:
        return unauthorized_code
    if status_code == 403:
        return "SCOPE_DENIED"
    if status_code == 429:
        return "RATE_LIMITED"
    if status_code in {400, 404, 405, 422}:
        return "INVALID_ARGUMENT"
    if status_code >= 500:
        return "API_UNAVAILABLE"
    return "INTERNAL_ERROR"


def _validate_login_identity(payload: dict[str, Any]) -> LoginIdentity:
    _require_exact_keys(payload, {"data", "meta"})
    data = _require_mapping(payload["data"])
    _require_exact_keys(data, _LOGIN_DATA_FIELDS)
    meta = _require_mapping(payload["meta"])
    _require_exact_keys(meta, {"generated_at", "source"})
    _require_aware_datetime(meta["generated_at"])
    if meta["source"] != "session":
        raise ValueError("invalid session source")

    username = _require_terminal_safe_text(data["username"])
    role = _require_non_empty_text(data["role"])
    scope_mode = _require_non_empty_text(data["store_scope_mode"])
    if role not in _ROLES or scope_mode not in _STORE_SCOPE_MODES:
        raise ValueError("invalid authorization identity")
    if data["status"] != "active" or data["is_initialized"] is not True:
        raise ValueError("inactive authorization identity")
    is_highest_admin = data["is_highest_admin"]
    if not isinstance(is_highest_admin, bool):
        raise TypeError("invalid highest-admin flag")
    user_id = data["user_id"]
    if user_id is not None:
        _require_non_empty_text(user_id)
    if data["display_name"] is not None:
        _require_text(data["display_name"])
    _require_text_list(data["page_keys"], stable=False)
    store_ids = _require_text_list(data["store_ids"], stable=True)
    effective_store_ids = _validate_role_scope(
        role=role,
        scope_mode=scope_mode,
        store_ids=store_ids,
        is_highest_admin=is_highest_admin,
        user_id=user_id,
    )
    return LoginIdentity(
        username=username,
        role=role,
        store_scope_mode=scope_mode,
        store_ids=tuple(effective_store_ids),
    )


def _validate_role_scope(
    *,
    role: str,
    scope_mode: str,
    store_ids: list[str],
    is_highest_admin: bool,
    user_id: Any,
) -> list[str]:
    if is_highest_admin != (role == "highest_admin"):
        raise ValueError("highest-admin identity mismatch")
    if role == "highest_admin":
        if scope_mode != "all":
            raise ValueError("highest administrators require all-store scope")
        return []
    if user_id is None:
        raise ValueError("managed users require a user identifier")
    if role == "admin":
        if scope_mode == "all":
            return []
        if scope_mode == "specified" and store_ids:
            return store_ids
        raise ValueError("administrator store scope is invalid")
    if role == "store" and scope_mode == "specified" and store_ids:
        return store_ids
    raise ValueError("store account scope is invalid")


def _validate_approval(
    payload: dict[str, Any], *, expected_user_code: str
) -> None:
    _require_exact_keys(payload, {"expires_at", "status", "user_code"})
    if payload["status"] != "approved":
        raise ValueError("authorization was not approved")
    if payload["user_code"] != expected_user_code:
        raise ValueError("authorization code mismatch")
    _require_aware_datetime(payload["expires_at"])


def _require_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError("mapping required")
    return value


def _require_exact_keys(value: dict[str, Any], expected: set[str]) -> None:
    if set(value) != expected:
        raise ValueError("unexpected response fields")


def _require_text(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError("text required")
    return value


def _require_non_empty_text(value: Any) -> str:
    text = _require_text(value)
    if not text or text != text.strip():
        raise ValueError("normalized text required")
    return text


def _require_terminal_safe_text(value: Any) -> str:
    text = _require_non_empty_text(value)
    if not text.isprintable():
        raise ValueError("terminal-safe text required")
    return text


def _require_text_list(value: Any, *, stable: bool) -> list[str]:
    if not isinstance(value, list):
        raise TypeError("list required")
    items = [_require_non_empty_text(item) for item in value]
    if len(items) != len(set(items)):
        raise ValueError("unique values required")
    if stable and items != sorted(items):
        raise ValueError("stable values required")
    return items


def _require_aware_datetime(value: Any) -> datetime:
    text = _require_non_empty_text(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("ISO datetime required") from None
    if parsed.tzinfo is None:
        raise ValueError("timezone-aware datetime required")
    return parsed
