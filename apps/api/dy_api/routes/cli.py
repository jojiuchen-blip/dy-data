from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from dy_api.auth import AuthContext
from dy_api.agent_capabilities import (
    AgentCapabilityError,
    clues_follow_up_stats,
    stores_list,
)
from dy_api.cli_auth import get_current_cli_user, verify_cli_access_payload
from dy_api.cli_contract import (
    CLI_ENVIRONMENT,
    CLI_METRIC_VERSION,
    CLI_SCHEMA_VERSION,
    cli_error,
)
from dy_api.routes._data import generated_at, get_data_store


router = APIRouter()
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def beijing_today() -> date:
    return generated_at().astimezone(SHANGHAI_TZ).date()


def _request_id(request: Request) -> str:
    return request.state.cli_request_id


def _stable_ids(values: list[str] | tuple[str, ...]) -> list[str]:
    return sorted({str(value).strip() for value in values if str(value).strip()})


def get_audited_current_cli_user(
    request: Request,
    current_user: AuthContext = Depends(get_current_cli_user),
) -> AuthContext:
    request.state.cli_user_id = current_user.user_id
    request.state.cli_auth_type = current_user.auth_type
    return current_user


def _meta(request: Request, **values):
    return {"partial": False, "request_id": _request_id(request), **values}


def _raise_cli_capability_error(
    request: Request, exc: AgentCapabilityError, *, command: str
) -> None:
    request.state.cli_requested_store_ids = exc.requested_store_ids
    request.state.cli_effective_store_ids = exc.effective_store_ids
    request.state.cli_date_range = exc.date_range
    cli_error(
        exc.code,
        exc.message,
        command=command,
        request_id=_request_id(request),
        status_code=exc.status_code,
    )


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
        "environment": CLI_ENVIRONMENT,
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
    try:
        payload = stores_list(
            current_user=current_user,
            store=store,
            request_id=_request_id(request),
        )
    except AgentCapabilityError as exc:
        _raise_cli_capability_error(request, exc, command="stores.list")
    request.state.cli_effective_store_ids = payload["scope"]["effective_store_ids"]
    request.state.cli_returned_store_count = len(payload["data"]["stores"])
    return payload


@router.get("/clues/store-follow-up-summary", name="clues.follow-up-stats")
def cli_store_follow_up_summary(
    request: Request,
    assigned_date_start: date | None = None,
    assigned_date_end: date | None = None,
    store_id: Annotated[list[str] | None, Query()] = None,
    current_user: AuthContext = Depends(get_audited_current_cli_user),
    store=Depends(get_data_store),
):
    try:
        payload = clues_follow_up_stats(
            current_user=current_user,
            store=store,
            request_id=_request_id(request),
            assigned_date_start=assigned_date_start,
            assigned_date_end=assigned_date_end,
            store_ids=store_id,
            today=beijing_today(),
        )
    except AgentCapabilityError as exc:
        _raise_cli_capability_error(
            request, exc, command="clues.follow-up-stats"
        )
    request.state.cli_requested_store_ids = payload["scope"][
        "requested_store_ids"
    ]
    request.state.cli_effective_store_ids = payload["scope"][
        "effective_store_ids"
    ]
    request.state.cli_date_range = [
        payload["filters"]["assigned_date_start"],
        payload["filters"]["assigned_date_end"],
    ]
    request.state.cli_returned_store_count = len(payload["data"]["stores"])
    return payload
