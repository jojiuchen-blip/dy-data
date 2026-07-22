"""Shared read-only capability service used by CLI and MCP transports."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from fastapi import status

from dy_api.auth import AuthContext
from dy_api.cli_contract import (
    CLI_ENVIRONMENT,
    CLI_METRIC_VERSION,
    CLI_SCHEMA_VERSION,
)
from dy_api.routes._data import generated_at
from dy_api.schemas import CliFollowUpData, CliFollowUpMetrics, dump_model


SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


class AgentCapabilityError(RuntimeError):
    """Stable transport-neutral failure from a read-only Agent capability."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int,
        requested_store_ids: Iterable[str] = (),
        effective_store_ids: Iterable[str] = (),
        date_range: tuple[date, date] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.requested_store_ids = list(requested_store_ids)
        self.effective_store_ids = list(effective_store_ids)
        self.date_range = (
            [date_range[0].isoformat(), date_range[1].isoformat()]
            if date_range is not None
            else None
        )


def _stable_ids(values: Iterable[str]) -> list[str]:
    return sorted({str(value).strip() for value in values if str(value).strip()})


def _stable_stores(stores: list[dict[str, Any]]) -> list[dict[str, str]]:
    normalized = [
        {
            "store_id": str(store.get("store_id") or ""),
            "store_name": str(store.get("store_name") or ""),
        }
        for store in stores
        if str(store.get("store_id") or "")
    ]
    return sorted(normalized, key=lambda store: (store["store_name"], store["store_id"]))


def _require_store(store: Any) -> Any:
    if not getattr(store, "available", False):
        raise AgentCapabilityError(
            "API_UNAVAILABLE",
            "The data service is unavailable",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return store


def _authorized_stores(
    current_user: AuthContext,
    store: Any,
) -> list[dict[str, str]]:
    scope = (
        None
        if current_user.has_global_data_access
        else tuple(_stable_ids(current_user.store_ids))
    )
    try:
        return _stable_stores(store.list_stores(scope))
    except AgentCapabilityError:
        raise
    except Exception:
        raise AgentCapabilityError(
            "API_UNAVAILABLE",
            "The data service is unavailable",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from None


def _parse_date(value: date | str | None, field_name: str) -> date | None:
    if value is None or isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise AgentCapabilityError(
            "INVALID_ARGUMENT",
            f"{field_name} must use YYYY-MM-DD",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        ) from None


def _date_range(
    assigned_date_start: date | str | None,
    assigned_date_end: date | str | None,
    *,
    today: date | None,
) -> tuple[date, date]:
    date_start = _parse_date(assigned_date_start, "assigned_date_start")
    date_end = _parse_date(assigned_date_end, "assigned_date_end")
    if (date_start is None) != (date_end is None):
        raise AgentCapabilityError(
            "INVALID_ARGUMENT",
            "assigned_date_start and assigned_date_end must be provided together",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    if date_start is None:
        date_end = today or generated_at().astimezone(SHANGHAI_TZ).date()
        date_start = date_end - timedelta(days=6)
    if date_end is None:
        raise RuntimeError("date range normalization invariant failed")
    if date_start > date_end:
        raise AgentCapabilityError(
            "INVALID_ARGUMENT",
            "assigned_date_start must not be after assigned_date_end",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            date_range=(date_start, date_end),
        )
    if (date_end - date_start).days + 1 > 366:
        raise AgentCapabilityError(
            "INVALID_ARGUMENT",
            "The date range must not exceed 366 inclusive days",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            date_range=(date_start, date_end),
        )
    return date_start, date_end


def _totals(rows: list[dict[str, Any]]) -> CliFollowUpMetrics:
    count_fields = (
        "total_count",
        "pending_count",
        "followed_count",
        "other_status_count",
        "action_followed_count",
        "effective_followed_count",
    )
    values = {
        field: sum(int(row.get(field) or 0) for row in rows) for field in count_fields
    }
    total = values["total_count"]
    values["system_follow_up_rate"] = (
        round(values["effective_followed_count"] / total, 4) if total else 0
    )
    values["action_follow_rate"] = (
        round(values["action_followed_count"] / total, 4) if total else 0
    )
    return CliFollowUpMetrics(**values)


def stores_list(
    *,
    current_user: AuthContext,
    store: Any,
    request_id: str,
) -> dict[str, Any]:
    """List only the stores currently visible to the authenticated identity."""
    store = _require_store(store)
    stores = _authorized_stores(current_user, store)
    effective_store_ids = sorted(row["store_id"] for row in stores)
    return {
        "ok": True,
        "command": "stores.list",
        "environment": CLI_ENVIRONMENT,
        "schema_version": CLI_SCHEMA_VERSION,
        "scope": {
            "user_id": current_user.user_id,
            "effective_store_ids": effective_store_ids,
        },
        "data": {"stores": stores},
        "meta": {"partial": False, "request_id": request_id},
    }


def clues_follow_up_stats(
    *,
    current_user: AuthContext,
    store: Any,
    request_id: str,
    assigned_date_start: date | str | None = None,
    assigned_date_end: date | str | None = None,
    store_ids: Iterable[str] | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Return the existing system follow-up metrics for an authorized subset."""
    store = _require_store(store)
    date_start, date_end = _date_range(
        assigned_date_start,
        assigned_date_end,
        today=today,
    )
    raw_store_ids = list(store_ids) if store_ids is not None else []
    requested_store_ids = _stable_ids(raw_store_ids)
    if any(not str(value).strip() for value in raw_store_ids):
        raise AgentCapabilityError(
            "INVALID_ARGUMENT",
            "store_id values must not be blank",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            requested_store_ids=requested_store_ids,
            date_range=(date_start, date_end),
        )

    available_stores = _authorized_stores(current_user, store)
    authorized_ids = (
        {row["store_id"] for row in available_stores}
        if current_user.has_global_data_access
        else set(current_user.store_ids)
    )
    if requested_store_ids and not set(requested_store_ids).issubset(authorized_ids):
        raise AgentCapabilityError(
            "SCOPE_DENIED",
            "Requested stores are outside the current account scope",
            status_code=status.HTTP_403_FORBIDDEN,
            requested_store_ids=requested_store_ids,
            date_range=(date_start, date_end),
        )

    effective_store_ids = requested_store_ids or sorted(authorized_ids)
    try:
        raw_rows = store.clue_store_follow_up_summary(
            store_ids=tuple(effective_store_ids),
            assigned_date_start=date_start.isoformat(),
            assigned_date_end=date_end.isoformat(),
        )
    except Exception:
        raise AgentCapabilityError(
            "API_UNAVAILABLE",
            "The data service is unavailable",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            requested_store_ids=requested_store_ids,
            effective_store_ids=effective_store_ids,
            date_range=(date_start, date_end),
        ) from None

    rows = sorted(
        (dump_model(CliFollowUpData(**row)) for row in raw_rows),
        key=lambda row: (row["store_name"], row["store_id"]),
    )
    now = generated_at()
    return {
        "ok": True,
        "command": "clues.follow-up-stats",
        "environment": CLI_ENVIRONMENT,
        "schema_version": CLI_SCHEMA_VERSION,
        "metric_version": CLI_METRIC_VERSION,
        "scope": {
            "user_id": current_user.user_id,
            "requested_store_ids": requested_store_ids,
            "effective_store_ids": effective_store_ids,
        },
        "filters": {
            "assigned_date_start": date_start.isoformat(),
            "assigned_date_end": date_end.isoformat(),
            "timezone": "Asia/Shanghai",
        },
        "data": {
            "stores": rows,
            "totals": dump_model(_totals(rows)),
        },
        "meta": {
            "partial": False,
            "request_id": request_id,
            "generated_at": now,
            "data_as_of": now,
            "source": "postgres",
        },
    }
