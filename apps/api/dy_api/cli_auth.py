"""Authentication primitives for the isolated read-only CLI channel."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import CliRefreshToken, User, utcnow
from dy_api.auth import (
    AuthContext,
    _admin_credentials_configured,
    _b64decode,
    _b64encode,
    _sign_payload,
    get_admin_settings,
    user_store_ids,
)
from dy_api.routes._data import get_session_dependency


CLI_ACCESS_SCOPE = "cli:read"
CLI_ACCESS_TOKEN_TYPE = "cli_access"
CLI_ACCESS_TOKEN_PREFIX = "cli."
CLI_ACCESS_TTL_SECONDS = 30 * 60
CLI_REFRESH_TTL_SECONDS = 30 * 24 * 60 * 60


def _utc(value: datetime | None = None) -> datetime:
    current = value or utcnow()
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _current_auth(
    session: Session | None,
    *,
    username: str,
    auth_type: str,
) -> AuthContext:
    if auth_type == "env_admin":
        settings = get_admin_settings()
        if (
            not _admin_credentials_configured(settings)
            or not hmac.compare_digest(username, settings.username)
        ):
            raise _unauthorized()
        return AuthContext(
            user_id=None,
            username=username,
            display_name=username,
            role="admin",
            store_ids=(),
            auth_type="env_admin",
        )

    if auth_type != "user" or session is None:
        raise _unauthorized()
    user = session.execute(
        select(User).where(User.username == username)
    ).scalar_one_or_none()
    if user is None or user.status != "active" or not user.is_initialized:
        raise _unauthorized()
    return AuthContext(
        user_id=user.user_id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        store_ids=user_store_ids(session, user.user_id),
        auth_type="user",
    )


def hash_cli_secret(value: str) -> str:
    """Return the SHA-256 digest used for persisted CLI secrets."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _authorization_fingerprint(session: Session, auth: AuthContext) -> str:
    if auth.auth_type == "env_admin":
        settings = get_admin_settings()
        if settings.password_hash:
            credential_kind = "password_hash"
            credential_value = settings.password_hash
        elif settings.test_mode and settings.test_password:
            credential_kind = "test_password"
            credential_value = settings.test_password
        else:
            credential_kind = "unconfigured"
            credential_value = ""
        state: dict[str, Any] = {
            "auth_type": "env_admin",
            "username": settings.username,
            "configured": _admin_credentials_configured(settings),
            "credential_kind": credential_kind,
            "credential_state": hash_cli_secret(credential_value),
        }
    else:
        user = session.get(User, auth.user_id) if auth.user_id else None
        if user is None:
            raise _unauthorized()
        state = {
            "auth_type": "user",
            "username": user.username,
            "role": user.role,
            "status": user.status,
            "is_initialized": bool(user.is_initialized),
            "password_credential_state": hash_cli_secret(user.password_hash or ""),
            "store_ids": sorted(user_store_ids(session, user.user_id)),
        }
    encoded_state = json.dumps(
        state, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    return hash_cli_secret(encoded_state)


def create_cli_access_token(
    auth: AuthContext, *, now: datetime | None = None
) -> tuple[str, datetime]:
    """Create a signed, short-lived token restricted to the CLI read scope."""
    issued_at = _utc(now)
    expires_at = issued_at + timedelta(seconds=CLI_ACCESS_TTL_SECONDS)
    payload: dict[str, Any] = {
        "sub": auth.username,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
        "typ": CLI_ACCESS_TOKEN_TYPE,
        "scope": CLI_ACCESS_SCOPE,
        "auth_type": auth.auth_type,
        "jti": uuid4().hex,
    }
    encoded_payload = _b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signed_payload = f"{CLI_ACCESS_TOKEN_PREFIX}{encoded_payload}"
    return f"{signed_payload}.{_sign_payload(signed_payload)}", expires_at


def verify_cli_access_payload(
    token: str | None, *, now: datetime | None = None
) -> dict[str, Any] | None:
    """Verify a CLI access token and return its isolated payload."""
    if not token or "." not in token:
        return None
    signed_payload, signature = token.rsplit(".", 1)
    if not signed_payload.startswith(CLI_ACCESS_TOKEN_PREFIX):
        return None
    if not hmac.compare_digest(signature, _sign_payload(signed_payload)):
        return None
    encoded_payload = signed_payload.removeprefix(CLI_ACCESS_TOKEN_PREFIX)
    try:
        payload = json.loads(_b64decode(encoded_payload).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None

    if (
        payload.get("typ") != CLI_ACCESS_TOKEN_TYPE
        or payload.get("scope") != CLI_ACCESS_SCOPE
        or payload.get("auth_type") not in {"user", "env_admin"}
        or not isinstance(payload.get("sub"), str)
        or not isinstance(payload.get("exp"), int)
        or not isinstance(payload.get("jti"), str)
        or not payload["jti"]
        or "uid" in payload
        or "user_id" in payload
    ):
        return None
    if payload["exp"] <= int(_utc(now).timestamp()):
        return None
    return payload


def issue_refresh_token(
    session: Session, auth: AuthContext, *, now: datetime | None = None
) -> tuple[str, CliRefreshToken]:
    """Create a persisted refresh credential without storing its raw secret."""
    created_at = _utc(now)
    raw_token = secrets.token_urlsafe(48)
    token = CliRefreshToken(
        refresh_token_id=uuid4().hex,
        token_hash=hash_cli_secret(raw_token),
        user_id=auth.user_id,
        username=auth.username,
        auth_type=auth.auth_type,
        authorization_fingerprint=_authorization_fingerprint(session, auth),
        scope=CLI_ACCESS_SCOPE,
        created_at=created_at,
        expires_at=created_at + timedelta(seconds=CLI_REFRESH_TTL_SECONDS),
    )
    session.add(token)
    return raw_token, token


def _revoke_invalid_refresh(
    session: Session, stored: CliRefreshToken, current_time: datetime
) -> None:
    stored.last_used_at = current_time
    stored.revoked_at = current_time
    session.commit()


def rotate_refresh_token(
    session: Session, raw_token: str, *, now: datetime | None = None
) -> tuple[str, str, datetime]:
    """Consume one refresh credential and stage its replacement atomically."""
    current_time = _utc(now)
    stored = session.execute(
        select(CliRefreshToken)
        .where(CliRefreshToken.token_hash == hash_cli_secret(raw_token))
        .with_for_update()
    ).scalar_one_or_none()
    if (
        stored is None
        or stored.scope != CLI_ACCESS_SCOPE
        or stored.revoked_at is not None
        or _utc(stored.expires_at) <= current_time
    ):
        raise _unauthorized()

    try:
        auth = _current_auth(
            session,
            username=stored.username,
            auth_type=stored.auth_type,
        )
        current_fingerprint = _authorization_fingerprint(session, auth)
    except HTTPException:
        _revoke_invalid_refresh(session, stored, current_time)
        raise
    if auth.user_id != stored.user_id or not hmac.compare_digest(
        stored.authorization_fingerprint, current_fingerprint
    ):
        _revoke_invalid_refresh(session, stored, current_time)
        raise _unauthorized()
    access_token, access_expires_at = create_cli_access_token(auth, now=current_time)
    replacement_raw, replacement = issue_refresh_token(
        session, auth, now=current_time
    )
    stored.last_used_at = current_time
    stored.revoked_at = current_time
    stored.replaced_by_token_id = replacement.refresh_token_id
    session.flush()
    return access_token, replacement_raw, access_expires_at


def revoke_refresh_token(session: Session, raw_token: str) -> None:
    """Revoke a refresh credential when it exists; repeated calls are safe."""
    stored = session.execute(
        select(CliRefreshToken)
        .where(CliRefreshToken.token_hash == hash_cli_secret(raw_token))
        .with_for_update()
    ).scalar_one_or_none()
    if stored is not None and stored.revoked_at is None:
        stored.revoked_at = utcnow()
        session.flush()


def get_current_cli_user(
    request: Request,
    session: Session | None = Depends(get_session_dependency),
) -> AuthContext:
    """Authenticate only a Bearer CLI token and reload current account scope."""
    authorization = request.headers.get("authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.strip():
        raise _unauthorized()
    payload = verify_cli_access_payload(token.strip())
    if payload is None:
        raise _unauthorized()

    return _current_auth(
        session,
        username=payload["sub"],
        auth_type=payload["auth_type"],
    )
