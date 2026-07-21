"""Device authorization lifecycle endpoints for the read-only CLI."""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlsplit, urlunsplit
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import CliDeviceAuthorization, utcnow
from dy_api.auth import AuthContext, get_current_user
from dy_api.cli_auth import (
    CLI_ACCESS_SCOPE,
    _current_auth,
    create_cli_access_token,
    hash_cli_secret,
    issue_refresh_token,
    revoke_refresh_token,
    rotate_refresh_token,
)
from dy_api.routes._data import get_session_dependency
from dy_api.schemas import (
    CliAuthorizationStatusResponse,
    CliDeviceApproveRequest,
    CliDeviceStartResponse,
    CliDeviceTokenRequest,
    CliRefreshTokenRequest,
    CliTokenResponse,
)


router = APIRouter()
DEVICE_AUTHORIZATION_TTL_SECONDS = 10 * 60
DEVICE_POLL_INTERVAL_SECONDS = 3
USER_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _require_session(session: Session | None) -> Session:
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is not available",
        )
    return session


def _invalid_device_code() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Invalid or expired device code",
    )


def _verification_uri(request: Request) -> str:
    configured = os.getenv("DY_WEB_BASE_URL", "").strip().rstrip("/")
    test_mode = os.getenv("DY_API_TEST_MODE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if not test_mode:
        if not configured:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="DY_WEB_BASE_URL is required for CLI authorization",
            )
        parsed_configured = urlsplit(configured)
        try:
            hostname = parsed_configured.hostname
        except ValueError:
            hostname = None
        if parsed_configured.scheme.lower() != "https" or not hostname:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="DY_WEB_BASE_URL must be an https URL with a hostname",
            )
        base_url = configured
    elif configured:
        base_url = configured
    else:
        parsed_base_url = urlsplit(str(request.base_url))
        base_url = urlunsplit(
            (parsed_base_url.scheme, parsed_base_url.netloc, "", "", "")
        )
    return f"{base_url}/auth/cli/authorize"


def _token_response(
    access_token: str,
    refresh_token: str,
    access_token_expires_at: datetime,
) -> CliTokenResponse:
    return CliTokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        access_token_expires_at=access_token_expires_at,
    )


@router.post("/device/start", response_model=CliDeviceStartResponse)
def start_device_authorization(
    request: Request,
    session: Session | None = Depends(get_session_dependency),
) -> CliDeviceStartResponse:
    """Create an anonymous, short-lived device authorization request."""
    active_session = _require_session(session)
    current_time = utcnow()
    device_code = secrets.token_urlsafe(32)
    user_code = "".join(secrets.choice(USER_CODE_ALPHABET) for _ in range(8))
    verification_uri = _verification_uri(request)
    grant = CliDeviceAuthorization(
        device_authorization_id=uuid4().hex,
        device_code_hash=hash_cli_secret(device_code),
        user_code_hash=hash_cli_secret(user_code),
        status="pending",
        scope=CLI_ACCESS_SCOPE,
        created_at=current_time,
        expires_at=current_time
        + timedelta(seconds=DEVICE_AUTHORIZATION_TTL_SECONDS),
    )
    active_session.add(grant)
    active_session.commit()
    return CliDeviceStartResponse(
        device_code=device_code,
        user_code=user_code,
        verification_uri=verification_uri,
        verification_uri_complete=(
            f"{verification_uri}?user_code={quote(user_code, safe='')}"
        ),
        expires_in=DEVICE_AUTHORIZATION_TTL_SECONDS,
        interval=DEVICE_POLL_INTERVAL_SECONDS,
    )


@router.post("/device/approve", response_model=CliAuthorizationStatusResponse)
def approve_device_authorization(
    payload: CliDeviceApproveRequest,
    current_user: AuthContext = Depends(get_current_user),
    session: Session | None = Depends(get_session_dependency),
) -> CliAuthorizationStatusResponse:
    """Approve one pending user code using the existing Web cookie session."""
    active_session = _require_session(session)
    current_time = utcnow()
    grant = active_session.execute(
        select(CliDeviceAuthorization)
        .where(
            CliDeviceAuthorization.user_code_hash
            == hash_cli_secret(payload.user_code)
        )
        .with_for_update()
    ).scalar_one_or_none()
    if (
        grant is None
        or grant.scope != CLI_ACCESS_SCOPE
        or grant.status != "pending"
        or _as_utc(grant.expires_at) <= current_time
    ):
        raise _invalid_device_code()

    grant.status = "approved"
    grant.user_id = current_user.user_id
    grant.username = current_user.username
    grant.auth_type = current_user.auth_type
    grant.approved_at = current_time
    active_session.commit()
    return CliAuthorizationStatusResponse(status="approved")


@router.post(
    "/device/token",
    response_model=CliTokenResponse,
    responses={202: {"model": CliAuthorizationStatusResponse}},
)
def exchange_device_code(
    payload: CliDeviceTokenRequest,
    session: Session | None = Depends(get_session_dependency),
) -> CliTokenResponse | JSONResponse:
    """Poll a device request and consume an approved grant exactly once."""
    active_session = _require_session(session)
    current_time = utcnow()
    grant = active_session.execute(
        select(CliDeviceAuthorization)
        .where(
            CliDeviceAuthorization.device_code_hash
            == hash_cli_secret(payload.device_code)
        )
        .with_for_update()
    ).scalar_one_or_none()
    if (
        grant is None
        or grant.scope != CLI_ACCESS_SCOPE
        or _as_utc(grant.expires_at) <= current_time
    ):
        raise _invalid_device_code()
    if grant.status == "pending":
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={"status": "authorization_pending"},
        )
    if (
        grant.status != "approved"
        or grant.consumed_at is not None
        or not grant.username
        or not grant.auth_type
    ):
        raise _invalid_device_code()

    auth = _current_auth(
        active_session,
        username=grant.username,
        auth_type=grant.auth_type,
        user_id=grant.user_id,
    )
    access_token, access_expires_at = create_cli_access_token(
        auth, session=active_session, now=current_time
    )
    refresh_token, _ = issue_refresh_token(
        active_session, auth, now=current_time
    )
    grant.status = "consumed"
    grant.consumed_at = current_time
    active_session.commit()
    return _token_response(access_token, refresh_token, access_expires_at)


@router.post("/token/refresh", response_model=CliTokenResponse)
def refresh_cli_tokens(
    payload: CliRefreshTokenRequest,
    session: Session | None = Depends(get_session_dependency),
) -> CliTokenResponse:
    """Rotate one valid refresh credential and issue a fresh access token."""
    active_session = _require_session(session)
    access_token, refresh_token, access_expires_at = rotate_refresh_token(
        active_session, payload.refresh_token
    )
    active_session.commit()
    return _token_response(access_token, refresh_token, access_expires_at)


@router.post("/revoke", response_model=CliAuthorizationStatusResponse)
def revoke_cli_tokens(
    payload: CliRefreshTokenRequest,
    session: Session | None = Depends(get_session_dependency),
) -> CliAuthorizationStatusResponse:
    """Revoke a refresh credential without echoing any secret."""
    active_session = _require_session(session)
    revoke_refresh_token(active_session, payload.refresh_token)
    active_session.commit()
    return CliAuthorizationStatusResponse(status="revoked")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
