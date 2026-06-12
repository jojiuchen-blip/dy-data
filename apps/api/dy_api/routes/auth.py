from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status

from dy_api.auth import (
    AdminPasswordNotConfigured,
    clear_session_cookie,
    get_current_admin,
    set_session_cookie,
    verify_admin_credentials,
)
from dy_api.routes._data import generated_at
from dy_api.schemas import LoginRequest


router = APIRouter()


def _session_response(username: str) -> dict:
    return {
        "data": {"username": username},
        "meta": {"generated_at": generated_at(), "source": "session"},
    }


@router.post("/login")
def login(payload: LoginRequest, response: Response):
    try:
        valid = verify_admin_credentials(payload.username, payload.password)
    except AdminPasswordNotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    if not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )

    set_session_cookie(response, payload.username)
    return _session_response(payload.username)


@router.get("/me")
def me(username: str = Depends(get_current_admin)):
    return _session_response(username)


@router.post("/logout")
def logout(response: Response, username: str = Depends(get_current_admin)):
    clear_session_cookie(response)
    return _session_response(username)
