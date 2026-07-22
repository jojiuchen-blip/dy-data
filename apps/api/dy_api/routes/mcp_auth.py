"""Authenticated browser consent endpoints for remote MCP clients."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict

from dy_api.agent_capabilities import AgentCapabilityError, stores_list
from dy_api.auth import AuthContext, get_current_user
from dy_api.mcp_oauth import (
    McpAuthorizationRequestError,
    DatabaseMcpOAuthProvider,
)
from dy_api.routes._data import generated_at, get_data_store


router = APIRouter()


class McpAuthorizationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    decision: Literal["approve", "deny"]


def _provider(request: Request) -> DatabaseMcpOAuthProvider:
    return request.app.state.mcp_oauth_provider


def _invalid_request(exc: McpAuthorizationRequestError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=str(exc),
    )


@router.get("/request")
async def mcp_authorization_request(
    request: Request,
    request_id: str,
    current_user: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    try:
        details = await _provider(request).authorization_request_details(request_id)
        scope = stores_list(
            current_user=current_user,
            store=store,
            request_id=request_id,
        )
    except McpAuthorizationRequestError as exc:
        raise _invalid_request(exc) from exc
    except AgentCapabilityError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    details.update(
        {
            "account": {
                "user_id": current_user.user_id,
                "username": current_user.username,
                "display_name": current_user.display_name,
            },
            "data_scope": {
                "mode": current_user.store_scope_mode,
                "stores": scope["data"]["stores"],
            },
        }
    )
    return {
        "data": details,
        "meta": {"generated_at": generated_at(), "source": "mcp_oauth"},
    }


@router.post("/approve")
async def decide_mcp_authorization(
    request: Request,
    payload: McpAuthorizationDecision,
    current_user: AuthContext = Depends(get_current_user),
):
    provider = _provider(request)
    try:
        if payload.decision == "approve":
            redirect_uri = await provider.approve_authorization(
                payload.request_id, current_user
            )
        else:
            redirect_uri = await provider.deny_authorization(payload.request_id)
    except McpAuthorizationRequestError as exc:
        raise _invalid_request(exc) from exc
    return {"redirect_uri": redirect_uri}
