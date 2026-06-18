from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import or_, select

from apps.api.dy_api.models import User, UserStoreScope
from dy_api.routes._data import get_session_dependency


SUPER_ADMIN_USERNAME_ENV = "DY_SUPER_ADMIN_USERNAME"
SUPER_ADMIN_PASSWORD_HASH_ENV = "DY_SUPER_ADMIN_PASSWORD_HASH"
LEGACY_ADMIN_USERNAME_ENV = "DY_ADMIN_USERNAME"
LEGACY_ADMIN_PASSWORD_HASH_ENV = "DY_ADMIN_PASSWORD_HASH"
TEST_ADMIN_PASSWORD_ENV = "DY_TEST_ADMIN_PASSWORD"
DEFAULT_COOKIE_NAME = "dy_session"
DEFAULT_SESSION_TTL_SECONDS = 60 * 60 * 24

_EPHEMERAL_SESSION_SECRET = secrets.token_urlsafe(32)


class AdminPasswordNotConfigured(RuntimeError):
    pass


@dataclass(frozen=True)
class AdminSettings:
    username: str
    password_hash: str | None
    test_mode: bool
    test_password: str


@dataclass(frozen=True)
class SessionCookieConfig:
    name: str
    secure: bool
    samesite: str
    max_age: int


@dataclass(frozen=True)
class AuthContext:
    user_id: str | None
    username: str
    display_name: str
    role: str
    store_ids: tuple[str, ...]
    auth_type: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def normalize_account_value(value: str | None) -> str:
    return " ".join((value or "").strip().split())


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(encoded: str) -> bytes:
    padding = "=" * (-len(encoded) % 4)
    return base64.urlsafe_b64decode((encoded + padding).encode("ascii"))


def hash_password_pbkdf2(
    password: str, *, iterations: int = 260_000, salt: bytes | None = None
) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${_b64encode(salt)}${_b64encode(digest)}"


def get_admin_settings() -> AdminSettings:
    password_hash = (
        os.getenv(SUPER_ADMIN_PASSWORD_HASH_ENV)
        or os.getenv(LEGACY_ADMIN_PASSWORD_HASH_ENV)
        or ""
    ).strip()
    return AdminSettings(
        username=normalize_account_value(
            os.getenv(SUPER_ADMIN_USERNAME_ENV)
            or os.getenv(LEGACY_ADMIN_USERNAME_ENV)
        ),
        password_hash=password_hash or None,
        test_mode=_truthy(os.getenv("DY_API_TEST_MODE")),
        test_password=os.getenv(TEST_ADMIN_PASSWORD_ENV, ""),
    )


def _admin_credentials_configured(settings: AdminSettings) -> bool:
    if not settings.username:
        return False
    return bool(settings.password_hash or (settings.test_mode and settings.test_password))


def get_cookie_config() -> SessionCookieConfig:
    test_mode = _truthy(os.getenv("DY_API_TEST_MODE"))
    default_secure = "false" if test_mode else "true"
    samesite = os.getenv("DY_SESSION_COOKIE_SAMESITE", "lax").strip().lower()
    if samesite not in {"lax", "strict"}:
        samesite = "lax"

    try:
        max_age = int(os.getenv("DY_SESSION_TTL_SECONDS", str(DEFAULT_SESSION_TTL_SECONDS)))
    except ValueError:
        max_age = DEFAULT_SESSION_TTL_SECONDS

    return SessionCookieConfig(
        name=os.getenv("DY_SESSION_COOKIE_NAME", DEFAULT_COOKIE_NAME),
        secure=_truthy(os.getenv("DY_SESSION_COOKIE_SECURE", default_secure)),
        samesite=samesite,
        max_age=max_age,
    )


def verify_password_hash(password: str, password_hash: str) -> bool:
    if password_hash.startswith("pbkdf2_sha256$"):
        try:
            _, iterations_raw, salt_raw, digest_raw = password_hash.split("$", 3)
            iterations = int(iterations_raw)
            salt = _b64decode(salt_raw)
            expected = _b64decode(digest_raw)
        except (ValueError, TypeError):
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, iterations
        )
        return hmac.compare_digest(actual, expected)

    if password_hash.startswith(("$2a$", "$2b$", "$2y$")):
        try:
            import bcrypt
        except ImportError:
            return False
        return bool(
            bcrypt.checkpw(
                password.encode("utf-8"), password_hash.encode("utf-8")
            )
        )

    return False


def verify_admin_credentials(username: str, password: str) -> bool:
    settings = get_admin_settings()
    if not settings.username or not hmac.compare_digest(username, settings.username):
        return False

    if settings.password_hash:
        return verify_password_hash(password, settings.password_hash)

    if settings.test_mode and settings.test_password:
        return hmac.compare_digest(password, settings.test_password)

    raise AdminPasswordNotConfigured(
        "DY_SUPER_ADMIN_PASSWORD_HASH is required for the highest admin account"
    )


def find_user_by_identifier(session: Any | None, identifier: str) -> User | None:
    if session is None:
        return None
    normalized = normalize_account_value(identifier)
    if not normalized:
        return None
    return session.execute(
        select(User).where(
            or_(User.username == normalized, User.external_account_id == normalized)
        )
    ).scalar_one_or_none()


def verify_user_credentials(
    session: Any | None, identifier: str, password: str
) -> User | None:
    user = find_user_by_identifier(session, identifier)
    if user is None:
        return None
    if user.status != "active" or not user.is_initialized or not user.password_hash:
        return None
    if not verify_password_hash(password, user.password_hash):
        return None
    return user


def user_store_ids(session: Any | None, user_id: str | None) -> tuple[str, ...]:
    if session is None or not user_id:
        return ()
    rows = session.execute(
        select(UserStoreScope.store_id)
        .where(UserStoreScope.user_id == user_id)
        .order_by(UserStoreScope.store_id)
    ).all()
    return tuple(row[0] for row in rows if row[0])


def _session_secret() -> bytes:
    configured = os.getenv("DY_SESSION_SECRET", "").strip()
    if configured:
        return configured.encode("utf-8")

    if _truthy(os.getenv("DY_API_TEST_MODE")):
        return _EPHEMERAL_SESSION_SECRET.encode("utf-8")

    raise AdminPasswordNotConfigured("DY_SESSION_SECRET is required")


def _sign_payload(encoded_payload: str) -> str:
    digest = hmac.new(
        _session_secret(), encoded_payload.encode("ascii"), hashlib.sha256
    ).digest()
    return _b64encode(digest)


def create_session_token(
    username: str,
    now: int | None = None,
    *,
    user_id: str | None = None,
    role: str = "admin",
    auth_type: str = "env_admin",
) -> str:
    issued_at = now or int(time.time())
    ttl = get_cookie_config().max_age
    payload: dict[str, Any] = {
        "sub": username,
        "iat": issued_at,
        "exp": issued_at + ttl,
        "role": role,
        "auth_type": auth_type,
    }
    if user_id:
        payload["uid"] = user_id
    encoded_payload = _b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    return f"{encoded_payload}.{_sign_payload(encoded_payload)}"


def verify_session_payload(token: str | None, now: int | None = None) -> dict[str, Any] | None:
    if not token or "." not in token:
        return None

    encoded_payload, signature = token.rsplit(".", 1)
    if not hmac.compare_digest(signature, _sign_payload(encoded_payload)):
        return None

    try:
        payload = json.loads(_b64decode(encoded_payload).decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return None

    username = payload.get("sub")
    expires_at = payload.get("exp")
    if not isinstance(username, str) or not isinstance(expires_at, int):
        return None

    if expires_at < (now or int(time.time())):
        return None
    return payload


def verify_session_token(token: str | None, now: int | None = None) -> str | None:
    payload = verify_session_payload(token, now)
    if payload is None:
        return None
    username = payload.get("sub")
    return username if isinstance(username, str) else None


def set_session_cookie(
    response: Response,
    username: str,
    *,
    user_id: str | None = None,
    role: str = "admin",
    auth_type: str = "env_admin",
) -> None:
    config = get_cookie_config()
    response.set_cookie(
        key=config.name,
        value=create_session_token(
            username,
            user_id=user_id,
            role=role,
            auth_type=auth_type,
        ),
        max_age=config.max_age,
        httponly=True,
        secure=config.secure,
        samesite=config.samesite,
        path="/",
    )


def set_auth_cookie(response: Response, auth: AuthContext) -> None:
    set_session_cookie(
        response,
        auth.username,
        user_id=auth.user_id,
        role=auth.role,
        auth_type=auth.auth_type,
    )


def clear_session_cookie(response: Response) -> None:
    config = get_cookie_config()
    response.delete_cookie(
        key=config.name,
        path="/",
        secure=config.secure,
        httponly=True,
        samesite=config.samesite,
    )


def get_current_user(
    request: Request, session: Any | None = Depends(get_session_dependency)
) -> AuthContext:
    config = get_cookie_config()
    payload = verify_session_payload(request.cookies.get(config.name))
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        )

    username = payload.get("sub")
    if not isinstance(username, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        )

    auth_type = str(payload.get("auth_type") or "env_admin")
    if auth_type == "env_admin":
        settings = get_admin_settings()
        if (
            not _admin_credentials_configured(settings)
            or not hmac.compare_digest(username, settings.username)
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
            )
        return AuthContext(
            user_id=None,
            username=username,
            display_name=username,
            role="admin",
            store_ids=(),
            auth_type="env_admin",
        )

    user_id = payload.get("uid")
    if not isinstance(user_id, str) or session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        )
    user = session.get(User, user_id)
    if user is None or user.status != "active" or not user.is_initialized:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        )
    return AuthContext(
        user_id=user.user_id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        store_ids=user_store_ids(session, user.user_id),
        auth_type="user",
    )


def get_current_admin(
    current_user: AuthContext = Depends(get_current_user),
) -> str:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )
    return current_user.username
