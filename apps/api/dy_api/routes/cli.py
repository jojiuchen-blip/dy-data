from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from dy_api.auth import AuthContext
from dy_api.cli_auth import get_current_cli_user, verify_cli_access_payload
from dy_api.cli_contract import CLI_METRIC_VERSION, CLI_SCHEMA_VERSION, cli_error
from dy_api.routes._data import generated_at, get_data_store
from dy_api.schemas import CliFollowUpData, CliFollowUpMetrics, dump_model


router = APIRouter()
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def beijing_today() -> date:
    return generated_at().astimezone(SHANGHAI_TZ).date()


def _request_id(request: Request) -> str:
    return request.state.cli_request_id


def _stable_ids(values: list[str] | tuple[str, ...]) -> list[str]:
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


def _require_store(request: Request, store, *, command: str):
    if not getattr(store, "available", False):
        cli_error(
            "API_UNAVAILABLE",
            "The data service is unavailable",
            command=command,
            request_id=_request_id(request),
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return store


def get_audited_current_cli_user(
    request: Request,
    current_user: AuthContext = Depends(get_current_cli_user),
) -> AuthContext:
    request.state.cli_user_id = current_user.user_id
    request.state.cli_auth_type = current_user.auth_type
    return current_user


def _meta(request: Request, **values: Any) -> dict[str, Any]:
    return {"partial": False, "request_id": _request_id(request), **values}


def _authorized_stores(
    request: Request,
    current_user: AuthContext,
    store,
    *,
    command: str,
) -> list[dict[str, str]]:
    scope = None if current_user.has_global_data_access else tuple(
        _stable_ids(current_user.store_ids)
    )
    try:
        stores = store.list_stores(scope)
    except HTTPException:
        raise
    except Exception:
        cli_error(
            "API_UNAVAILABLE",
            "The data service is unavailable",
            command=command,
            request_id=_request_id(request),
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return _stable_stores(stores)


@router.get("/cli/auth/status", name="auth.status")
def cli_auth_status(
    request: Request,
    current_user: AuthContext = Depends(get_audited_current_cli_user),
):
    store_ids = _stable_ids(current_user.store_ids)
    request.state.cli_effective_store_ids = store_ids
    authorization = request.headers.get("authorization", "")
    _, _, raw_token = authorization.partition(" ")
    token_payload = verify_cli_access_payload(raw_token.strip())
    data = {
        "authenticated": True,
        "user_id": current_user.user_id,
        "username": current_user.username,
        "display_name": current_user.display_name,
        "role": current_user.role,
        "auth_type": current_user.auth_type,
        "store_ids": store_ids,
    }
    if token_payload is not None:
        data["expires_at"] = datetime.fromtimestamp(
            token_payload["exp"], timezone.utc
        ).isoformat()
    return {
        "ok": True,
        "command": "auth.status",
        "schema_version": CLI_SCHEMA_VERSION,
        "data": data,
        "meta": _meta(request),
    }


@router.get("/cli/stores", name="stores.list")
def cli_stores(
    request: Request,
    current_user: AuthContext = Depends(get_audited_current_cli_user),
    store=Depends(get_data_store),
):
    store = _require_store(request, store, command="stores.list")
    stores = _authorized_stores(
        request, current_user, store, command="stores.list"
    )
    effective_store_ids = sorted(row["store_id"] for row in stores)
    request.state.cli_effective_store_ids = effective_store_ids
    request.state.cli_returned_store_count = len(stores)
    return {
        "ok": True,
        "command": "stores.list",
        "schema_version": CLI_SCHEMA_VERSION,
        "scope": {
            "user_id": current_user.user_id,
            "effective_store_ids": effective_store_ids,
        },
        "data": {"stores": stores},
        "meta": _meta(request),
    }


def _date_range(
    request: Request,
    assigned_date_start: date | None,
    assigned_date_end: date | None,
) -> tuple[date, date]:
    if (assigned_date_start is None) != (assigned_date_end is None):
        cli_error(
            "INVALID_ARGUMENT",
            "assigned_date_start and assigned_date_end must be provided together",
            command="clues.follow-up-stats",
            request_id=_request_id(request),
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    if assigned_date_start is None:
        assigned_date_end = beijing_today()
        assigned_date_start = assigned_date_end - timedelta(days=6)
    if assigned_date_start > assigned_date_end:
        cli_error(
            "INVALID_ARGUMENT",
            "assigned_date_start must not be after assigned_date_end",
            command="clues.follow-up-stats",
            request_id=_request_id(request),
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    if (assigned_date_end - assigned_date_start).days + 1 > 366:
        cli_error(
            "INVALID_ARGUMENT",
            "The date range must not exceed 366 inclusive days",
            command="clues.follow-up-stats",
            request_id=_request_id(request),
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    request.state.cli_date_range = [
        assigned_date_start.isoformat(),
        assigned_date_end.isoformat(),
    ]
    return assigned_date_start, assigned_date_end


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


@router.get("/clues/store-follow-up-summary", name="clues.follow-up-stats")
def cli_store_follow_up_summary(
    request: Request,
    assigned_date_start: date | None = None,
    assigned_date_end: date | None = None,
    store_id: Annotated[list[str] | None, Query()] = None,
    current_user: AuthContext = Depends(get_audited_current_cli_user),
    store=Depends(get_data_store),
):
    store = _require_store(request, store, command="clues.follow-up-stats")
    date_start, date_end = _date_range(
        request, assigned_date_start, assigned_date_end
    )
    requested_store_ids = _stable_ids(store_id or [])
    if store_id is not None and len(requested_store_ids) != len(
        {value.strip() for value in store_id}
    ):
        cli_error(
            "INVALID_ARGUMENT",
            "store_id values must not be blank",
            command="clues.follow-up-stats",
            request_id=_request_id(request),
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    available_stores = _authorized_stores(
        request,
        current_user,
        store,
        command="clues.follow-up-stats",
    )
    if current_user.has_global_data_access:
        authorized_ids = {row["store_id"] for row in available_stores}
    else:
        authorized_ids = set(current_user.store_ids)
    if requested_store_ids and not set(requested_store_ids).issubset(authorized_ids):
        request.state.cli_requested_store_ids = requested_store_ids
        cli_error(
            "SCOPE_DENIED",
            "Requested stores are outside the current account scope",
            command="clues.follow-up-stats",
            request_id=_request_id(request),
            status_code=status.HTTP_403_FORBIDDEN,
        )
    effective_store_ids = requested_store_ids or sorted(authorized_ids)
    request.state.cli_requested_store_ids = requested_store_ids
    request.state.cli_effective_store_ids = effective_store_ids
    try:
        raw_rows = store.clue_store_follow_up_summary(
            store_ids=tuple(effective_store_ids),
            assigned_date_start=date_start.isoformat(),
            assigned_date_end=date_end.isoformat(),
        )
    except Exception:
        cli_error(
            "API_UNAVAILABLE",
            "The data service is unavailable",
            command="clues.follow-up-stats",
            request_id=_request_id(request),
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    rows = sorted(
        (dump_model(CliFollowUpData(**row)) for row in raw_rows),
        key=lambda row: (row["store_name"], row["store_id"]),
    )
    request.state.cli_returned_store_count = len(rows)
    now = generated_at()
    return {
        "ok": True,
        "command": "clues.follow-up-stats",
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
        "meta": _meta(
            request,
            generated_at=now,
            data_as_of=now,
            source="postgres",
        ),
    }
