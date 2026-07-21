"""Strict success-response contracts for approved protected CLI reads."""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

from .constants import CLI_SCHEMA_VERSION
from .errors import is_canonical_request_id


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


class ContractError(ValueError):
    """A protected response does not match its approved success contract."""


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
    return {
        "ok": True,
        "command": "auth.status",
        "schema_version": CLI_SCHEMA_VERSION,
        "data": {
            "authenticated": True,
            "user_id": user_id,
            "username": _require_identifier(data["username"]),
            "display_name": _require_text(data["display_name"]),
            "role": _require_identifier(data["role"]),
            "auth_type": _require_identifier(data["auth_type"]),
            "store_ids": _require_identifier_list(data["store_ids"]),
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
    return {
        "ok": True,
        "command": "stores.list",
        "schema_version": CLI_SCHEMA_VERSION,
        "scope": {
            "user_id": _require_optional_identifier(scope["user_id"]),
            "effective_store_ids": _require_identifier_list(
                scope["effective_store_ids"]
            ),
        },
        "data": {"stores": stores},
        "meta": _validate_basic_meta(payload["meta"], expected_request_id),
    }


def validate_follow_up_stats(
    payload: dict[str, Any], expected_request_id: str | None = None
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

    meta = _require_mapping(payload["meta"])
    _require_exact_keys(
        meta,
        {"partial", "request_id", "generated_at", "data_as_of", "source"},
    )
    if meta["partial"] is not False:
        raise ContractError("partial responses are forbidden")
    request_id = _require_request_id(meta["request_id"], expected_request_id)
    return {
        "ok": True,
        "command": "clues.follow-up-stats",
        "schema_version": CLI_SCHEMA_VERSION,
        "metric_version": "clue-follow-up-v1",
        "scope": {
            "user_id": _require_optional_identifier(scope["user_id"]),
            "requested_store_ids": _require_identifier_list(
                scope["requested_store_ids"]
            ),
            "effective_store_ids": _require_identifier_list(
                scope["effective_store_ids"]
            ),
        },
        "filters": {
            "assigned_date_start": date_start.isoformat(),
            "assigned_date_end": date_end.isoformat(),
            "timezone": "Asia/Shanghai",
        },
        "data": {
            "stores": stores,
            "totals": _validate_metrics(_require_mapping(data["totals"])),
        },
        "meta": {
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
        {"ok", "command", "schema_version"} | extra_fields,
    )
    if (
        payload["ok"] is not True
        or payload["command"] != command
        or payload["schema_version"] != CLI_SCHEMA_VERSION
    ):
        raise ContractError("success envelope is incompatible")


def _validate_basic_meta(
    value: Any, expected_request_id: str | None
) -> dict[str, Any]:
    meta = _require_mapping(value)
    _require_exact_keys(meta, {"partial", "request_id"})
    if meta["partial"] is not False:
        raise ContractError("partial responses are forbidden")
    return {
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
    return metrics


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
