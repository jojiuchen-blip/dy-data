"""Strict success-response contracts for approved protected CLI reads."""

from __future__ import annotations

import math
from datetime import date, datetime
import re
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .constants import CLI_SCHEMA_VERSION, CLI_VERSION
from .errors import is_canonical_request_id
from .environments import TEST_ENVIRONMENT
from .url_security import normalize_safe_url


_COUNT_FIELDS = {
    "total_count",
    "pending_count",
    "followed_count",
    "other_status_count",
    "action_followed_count",
    "effective_followed_count",
}
_RATE_FIELDS = {"system_follow_up_rate", "action_follow_rate"}
_METRIC_FIELDS = _COUNT_FIELDS | _RATE_FIELDS
_ROLES = {"highest_admin", "admin", "store"}
_AUTH_TYPES = {"user", "env_admin"}
_URLSAFE_SECRET = re.compile(r"^[A-Za-z0-9_-]{40,128}$")
_USER_CODE = re.compile(r"^[A-Z0-9]{8}$")


class ContractError(ValueError):
    """A protected response does not match its approved success contract."""


def validate_agent_manifest(
    payload: dict[str, Any], _: str | None = None
) -> dict[str, Any]:
    """Validate the fixed public Agent manifest without accepting URL drift."""
    _require_exact_keys(
        payload,
        {
            "name",
            "manifest_version",
            "environment",
            "read_only",
            "service",
            "cli",
            "mcp",
            "authorization",
        },
    )
    if (
        payload["name"] != "dydata-agent"
        or payload["manifest_version"] != "1.0"
        or payload["environment"] != TEST_ENVIRONMENT.name
        or payload["read_only"] is not True
    ):
        raise ContractError("agent manifest identity is incompatible")
    service = _require_mapping(payload["service"])
    _require_exact_keys(
        service,
        {"base_url", "capabilities_url", "agent_guide_url", "skill_url"},
    )
    cli = _require_mapping(payload["cli"])
    _require_exact_keys(
        cli,
        {
            "version",
            "schema_version",
            "install_spec",
            "discovery_command",
            "doctor_command",
        },
    )
    mcp = _require_mapping(payload["mcp"])
    _require_exact_keys(
        mcp,
        {"url", "transport", "oauth_issuer", "protected_resource_metadata"},
    )
    authorization = _require_mapping(payload["authorization"])
    _require_exact_keys(
        authorization,
        {"user_handoff_required", "agent_must_not_handle_credentials", "scope"},
    )
    base_url = TEST_ENVIRONMENT.web_url
    if service != {
        "base_url": base_url,
        "capabilities_url": f"{base_url}/api/v1/agent/capabilities",
        "agent_guide_url": f"{base_url}/agent.md",
        "skill_url": f"{base_url}/agent/SKILL.md",
    }:
        raise ContractError("agent service URLs are incompatible")
    if (
        cli["version"] != CLI_VERSION
        or cli["schema_version"] != CLI_SCHEMA_VERSION
        or cli["discovery_command"] != "dydata commands --json"
        or cli["doctor_command"] != "dydata agent doctor --json"
        or not _require_identifier(cli["install_spec"]).startswith("git+https://")
    ):
        raise ContractError("agent CLI contract is incompatible")
    if mcp != {
        "url": TEST_ENVIRONMENT.mcp_url,
        "transport": "streamable-http",
        "oauth_issuer": base_url,
        "protected_resource_metadata": (
            f"{base_url}/.well-known/oauth-protected-resource/mcp"
        ),
    }:
        raise ContractError("agent MCP contract is incompatible")
    if authorization != {
        "user_handoff_required": True,
        "agent_must_not_handle_credentials": True,
        "scope": "mcp:read",
    }:
        raise ContractError("agent authorization contract is incompatible")
    return payload


def validate_mcp_resource_metadata(
    payload: dict[str, Any], _: str | None = None
) -> dict[str, Any]:
    """Validate the required protected-resource metadata fields."""
    if not {
        "resource",
        "authorization_servers",
        "scopes_supported",
        "bearer_methods_supported",
    }.issubset(payload):
        raise ContractError("protected-resource metadata is incomplete")
    if (
        payload["resource"] != TEST_ENVIRONMENT.mcp_url
        or payload["authorization_servers"] != [TEST_ENVIRONMENT.web_url]
        or "mcp:read" not in _require_identifier_list(payload["scopes_supported"])
        or "header"
        not in _require_identifier_list(payload["bearer_methods_supported"])
    ):
        raise ContractError("protected-resource metadata is incompatible")
    return {
        "resource": TEST_ENVIRONMENT.mcp_url,
        "authorization_servers": [TEST_ENVIRONMENT.web_url],
        "scopes_supported": list(payload["scopes_supported"]),
        "bearer_methods_supported": list(payload["bearer_methods_supported"]),
    }


def validate_auth_status(
    payload: dict[str, Any], expected_request_id: str | None = None
) -> dict[str, Any]:
    """Validate and rebuild an auth-status success envelope."""
    _require_envelope(payload, command="auth.status", extra_fields={"data", "meta"})
    data = _require_mapping(payload["data"])
    _require_exact_keys(
        data,
        {
            "authenticated",
            "user_id",
            "username",
            "display_name",
            "role",
            "auth_type",
            "store_ids",
            "expires_at",
        },
    )
    if data["authenticated"] is not True:
        raise ContractError("authenticated must be true")
    user_id = _require_optional_identifier(data["user_id"])
    expires_at = _require_datetime_text(data["expires_at"])
    meta = _validate_basic_meta(payload["meta"], expected_request_id)
    role = _require_identifier(data["role"])
    auth_type = _require_identifier(data["auth_type"])
    store_ids = _require_stable_identifier_list(data["store_ids"])
    if role not in _ROLES or auth_type not in _AUTH_TYPES:
        raise ContractError("authorization identity is incompatible")
    if (auth_type == "user") != (user_id is not None):
        raise ContractError("authorization subject is incompatible")
    return {
        "ok": True,
        "command": "auth.status",
        "environment": TEST_ENVIRONMENT.name,
        "schema_version": CLI_SCHEMA_VERSION,
        "data": {
            "authenticated": True,
            "user_id": user_id,
            "username": _require_identifier(data["username"]),
            "display_name": _require_text(data["display_name"]),
            "role": role,
            "auth_type": auth_type,
            "store_ids": store_ids,
            "expires_at": expires_at,
        },
        "meta": meta,
    }


def validate_stores(
    payload: dict[str, Any], expected_request_id: str | None = None
) -> dict[str, Any]:
    """Validate and rebuild a store-list success envelope."""
    _require_envelope(
        payload,
        command="stores.list",
        extra_fields={"scope", "data", "meta"},
    )
    scope = _require_mapping(payload["scope"])
    _require_exact_keys(scope, {"user_id", "effective_store_ids"})
    data = _require_mapping(payload["data"])
    _require_exact_keys(data, {"stores"})
    rows = _require_list(data["stores"])
    stores: list[dict[str, str]] = []
    for raw_row in rows:
        row = _require_mapping(raw_row)
        _require_exact_keys(row, {"store_id", "store_name"})
        stores.append(
            {
                "store_id": _require_identifier(row["store_id"]),
                "store_name": _require_text(row["store_name"]),
            }
        )
    effective_store_ids = _require_stable_identifier_list(
        scope["effective_store_ids"]
    )
    _require_store_rows_consistent(stores, effective_store_ids)
    return {
        "ok": True,
        "command": "stores.list",
        "environment": TEST_ENVIRONMENT.name,
        "schema_version": CLI_SCHEMA_VERSION,
        "scope": {
            "user_id": _require_optional_identifier(scope["user_id"]),
            "effective_store_ids": effective_store_ids,
        },
        "data": {"stores": stores},
        "meta": _validate_basic_meta(payload["meta"], expected_request_id),
    }


def validate_follow_up_stats(
    payload: dict[str, Any],
    expected_request_id: str | None = None,
    *,
    expected_store_ids: list[str] | None = None,
    expected_date_start: date | None = None,
    expected_date_end: date | None = None,
) -> dict[str, Any]:
    """Validate and rebuild a clue follow-up aggregate success envelope."""
    _require_envelope(
        payload,
        command="clues.follow-up-stats",
        extra_fields={"metric_version", "scope", "filters", "data", "meta"},
    )
    if payload["metric_version"] != "clue-follow-up-v1":
        raise ContractError("metric_version is incompatible")

    scope = _require_mapping(payload["scope"])
    _require_exact_keys(
        scope,
        {"user_id", "requested_store_ids", "effective_store_ids"},
    )
    filters = _require_mapping(payload["filters"])
    _require_exact_keys(
        filters,
        {"assigned_date_start", "assigned_date_end", "timezone"},
    )
    date_start = _require_date_text(filters["assigned_date_start"])
    date_end = _require_date_text(filters["assigned_date_end"])
    if date_start > date_end or filters["timezone"] != "Asia/Shanghai":
        raise ContractError("filters are incompatible")
    if (expected_date_start is None) != (expected_date_end is None):
        raise ContractError("expected date scope is incomplete")
    if expected_date_start is not None and (
        type(expected_date_start) is not date
        or type(expected_date_end) is not date
        or date_start != expected_date_start
        or date_end != expected_date_end
    ):
        raise ContractError("response date scope does not match the request")

    data = _require_mapping(payload["data"])
    _require_exact_keys(data, {"stores", "totals"})
    stores: list[dict[str, Any]] = []
    for raw_row in _require_list(data["stores"]):
        row = _require_mapping(raw_row)
        _require_exact_keys(row, {"store_id", "store_name"} | _METRIC_FIELDS)
        stores.append(
            {
                "store_id": _require_identifier(row["store_id"]),
                "store_name": _require_text(row["store_name"]),
                **_validate_metrics({field: row[field] for field in _METRIC_FIELDS}),
            }
        )

    requested_store_ids = _require_stable_identifier_list(
        scope["requested_store_ids"]
    )
    effective_store_ids = _require_stable_identifier_list(
        scope["effective_store_ids"]
    )
    if expected_store_ids is not None:
        normalized_expected = normalize_store_ids(expected_store_ids)
        if requested_store_ids != normalized_expected:
            raise ContractError("requested store scope does not match the request")
        if normalized_expected and effective_store_ids != normalized_expected:
            raise ContractError("effective store scope does not match the request")
    _require_store_rows_consistent(stores, effective_store_ids)
    totals = _validate_metrics(_require_mapping(data["totals"]))
    if totals != _summed_metrics(stores):
        raise ContractError("aggregate totals are inconsistent")

    meta = _require_mapping(payload["meta"])
    _require_exact_keys(
        meta,
        {"channel", "partial", "request_id", "generated_at", "data_as_of", "source"},
    )
    if meta["channel"] != "cli" or meta["partial"] is not False:
        raise ContractError("partial responses are forbidden")
    request_id = _require_request_id(meta["request_id"], expected_request_id)
    return {
        "ok": True,
        "command": "clues.follow-up-stats",
        "environment": TEST_ENVIRONMENT.name,
        "schema_version": CLI_SCHEMA_VERSION,
        "metric_version": "clue-follow-up-v1",
        "scope": {
            "user_id": _require_optional_identifier(scope["user_id"]),
            "requested_store_ids": requested_store_ids,
            "effective_store_ids": effective_store_ids,
        },
        "filters": {
            "assigned_date_start": date_start.isoformat(),
            "assigned_date_end": date_end.isoformat(),
            "timezone": "Asia/Shanghai",
        },
        "data": {
            "stores": stores,
            "totals": totals,
        },
        "meta": {
            "channel": "cli",
            "partial": False,
            "request_id": request_id,
            "generated_at": _require_datetime_text(meta["generated_at"]),
            "data_as_of": _require_datetime_text(meta["data_as_of"]),
            "source": _require_identifier(meta["source"]),
        },
    }


def _require_envelope(
    payload: dict[str, Any], *, command: str, extra_fields: set[str]
) -> None:
    _require_exact_keys(
        payload,
        {"ok", "command", "environment", "schema_version"} | extra_fields,
    )
    if (
        payload["ok"] is not True
        or payload["command"] != command
        or payload["environment"] != TEST_ENVIRONMENT.name
        or payload["schema_version"] != CLI_SCHEMA_VERSION
    ):
        raise ContractError("success envelope is incompatible")


def _validate_basic_meta(
    value: Any, expected_request_id: str | None
) -> dict[str, Any]:
    meta = _require_mapping(value)
    _require_exact_keys(meta, {"channel", "partial", "request_id"})
    if meta["channel"] != "cli" or meta["partial"] is not False:
        raise ContractError("partial responses are forbidden")
    return {
        "channel": "cli",
        "partial": False,
        "request_id": _require_request_id(meta["request_id"], expected_request_id),
    }


def _require_request_id(value: Any, expected_request_id: str | None) -> str:
    request_id = _require_identifier(value)
    if not is_canonical_request_id(request_id):
        raise ContractError("request_id is not canonical")
    if expected_request_id is not None and request_id != expected_request_id:
        raise ContractError("request_id does not match the request")
    return request_id


def _validate_metrics(value: dict[str, Any]) -> dict[str, int | float]:
    _require_exact_keys(value, _METRIC_FIELDS)
    metrics: dict[str, int | float] = {}
    for field in _COUNT_FIELDS:
        count = value[field]
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ContractError("metric count is invalid")
        metrics[field] = count
    for field in _RATE_FIELDS:
        rate = value[field]
        if (
            isinstance(rate, bool)
            or not isinstance(rate, (int, float))
            or not math.isfinite(rate)
            or not 0 <= rate <= 1
        ):
            raise ContractError("metric rate is invalid")
        metrics[field] = rate
    total = int(metrics["total_count"])
    if (
        int(metrics["pending_count"])
        + int(metrics["followed_count"])
        + int(metrics["other_status_count"])
        != total
        or int(metrics["action_followed_count"]) > total
        or int(metrics["effective_followed_count"]) > total
    ):
        raise ContractError("metric counts are inconsistent")
    expected_system_rate = (
        round(int(metrics["effective_followed_count"]) / total, 4)
        if total
        else 0.0
    )
    expected_action_rate = (
        round(int(metrics["action_followed_count"]) / total, 4)
        if total
        else 0.0
    )
    if (
        metrics["system_follow_up_rate"] != expected_system_rate
        or metrics["action_follow_rate"] != expected_action_rate
    ):
        raise ContractError("metric rates are inconsistent")
    return metrics


def _summed_metrics(stores: list[dict[str, Any]]) -> dict[str, int | float]:
    counts = {
        field: sum(int(store[field]) for store in stores) for field in _COUNT_FIELDS
    }
    total = counts["total_count"]
    return {
        **counts,
        "system_follow_up_rate": (
            round(counts["effective_followed_count"] / total, 4) if total else 0.0
        ),
        "action_follow_rate": (
            round(counts["action_followed_count"] / total, 4) if total else 0.0
        ),
    }


def _require_store_rows_consistent(
    stores: list[dict[str, Any]], effective_store_ids: list[str]
) -> None:
    store_ids = [store["store_id"] for store in stores]
    if len(store_ids) != len(set(store_ids)) or set(store_ids) != set(
        effective_store_ids
    ):
        raise ContractError("store scope is inconsistent")
    if stores != sorted(
        stores, key=lambda store: (store["store_name"], store["store_id"])
    ):
        raise ContractError("store rows are not stable")


def validate_device_start(payload: dict[str, Any], _: str | None = None) -> dict[str, Any]:
    """Validate the anonymous device-authorization response."""
    _require_exact_keys(
        payload,
        {
            "device_code",
            "user_code",
            "verification_uri",
            "verification_uri_complete",
            "expires_in",
            "interval",
        },
    )
    device_code = _require_identifier(payload["device_code"])
    user_code = _require_identifier(payload["user_code"])
    if not _URLSAFE_SECRET.fullmatch(device_code) or not _USER_CODE.fullmatch(user_code):
        raise ContractError("device authorization code is incompatible")
    verification_uri = _require_web_url(payload["verification_uri"])
    verification_uri_complete = _require_web_url(
        payload["verification_uri_complete"], allow_query=True
    )
    complete = urlsplit(verification_uri_complete)
    base = urlsplit(verification_uri)
    if (
        (complete.scheme, complete.netloc, complete.path)
        != (base.scheme, base.netloc, base.path)
        or parse_qs(complete.query, strict_parsing=True) != {"user_code": [user_code]}
        or base.query
    ):
        raise ContractError("device authorization URL is incompatible")
    if payload["expires_in"] != 600 or payload["interval"] != 3:
        raise ContractError("device authorization timing is incompatible")
    return {
        "device_code": device_code,
        "user_code": user_code,
        "verification_uri": verification_uri,
        "verification_uri_complete": verification_uri_complete,
        "expires_in": 600,
        "interval": 3,
    }


def validate_authorization_pending(
    payload: dict[str, Any], _: str | None = None
) -> dict[str, Any]:
    """Validate the only accepted HTTP 202 device-poll response."""
    _require_exact_keys(payload, {"status"})
    if payload["status"] != "authorization_pending":
        raise ContractError("authorization state is incompatible")
    return {"status": "authorization_pending"}


def validate_token_response(
    payload: dict[str, Any], _: str | None = None
) -> dict[str, Any]:
    """Validate a device exchange or refresh token response."""
    _require_exact_keys(
        payload,
        {
            "access_token",
            "refresh_token",
            "token_type",
            "scope",
            "expires_in",
            "access_token_expires_at",
        },
    )
    access_token = _require_identifier(payload["access_token"])
    refresh_token = _require_identifier(payload["refresh_token"])
    if (
        not access_token.startswith("cli.")
        or not _URLSAFE_SECRET.fullmatch(refresh_token)
        or payload["token_type"] != "Bearer"
        or payload["scope"] != "cli:read"
        or payload["expires_in"] != 1800
    ):
        raise ContractError("token response is incompatible")
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "Bearer",
        "scope": "cli:read",
        "expires_in": 1800,
        "access_token_expires_at": _require_datetime_text(
            payload["access_token_expires_at"]
        ),
    }


def validate_revoke_response(
    payload: dict[str, Any], _: str | None = None
) -> dict[str, Any]:
    """Validate a successful refresh-family revocation response."""
    _require_exact_keys(payload, {"status"})
    if payload["status"] != "revoked":
        raise ContractError("revocation state is incompatible")
    return {"status": "revoked"}


def _require_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError("object is required")
    return value


def _require_list(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise ContractError("array is required")
    return value


def _require_exact_keys(value: dict[str, Any], expected: set[str]) -> None:
    if set(value) != expected:
        raise ContractError("object fields are incompatible")


def _require_text(value: Any) -> str:
    if not isinstance(value, str):
        raise ContractError("string is required")
    return value


def _require_identifier(value: Any) -> str:
    text = _require_text(value)
    if not text:
        raise ContractError("non-empty string is required")
    return text


def _require_optional_identifier(value: Any) -> str | None:
    if value is None:
        return None
    return _require_identifier(value)


def _require_identifier_list(value: Any) -> list[str]:
    return [_require_identifier(item) for item in _require_list(value)]


def normalize_store_ids(values: list[str]) -> list[str]:
    """Normalize the caller's requested store scope for request/response binding."""
    normalized: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ContractError("store identifier is invalid")
        normalized.add(value.strip())
    return sorted(normalized)


def _require_stable_identifier_list(value: Any) -> list[str]:
    identifiers = _require_identifier_list(value)
    if len(identifiers) != len(set(identifiers)) or identifiers != sorted(identifiers):
        raise ContractError("identifier list is not stable")
    return identifiers


def _require_web_url(value: Any, *, allow_query: bool = False) -> str:
    text = _require_identifier(value)
    try:
        return normalize_safe_url(text, allow_query=allow_query)
    except ValueError:
        raise ContractError("web URL is required")


def _require_date_text(value: Any) -> date:
    text = _require_identifier(value)
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ContractError("ISO date is required") from None


def _require_datetime_text(value: Any) -> str:
    text = _require_identifier(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise ContractError("ISO datetime is required") from None
    if parsed.tzinfo is None:
        raise ContractError("timezone-aware datetime is required")
    return text
