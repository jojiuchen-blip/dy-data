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

from fastapi import HTTPException, Request, Response, status


DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_TEST_ADMIN_PASSWORD = "admin"
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


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


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
    return AdminSettings(
        username=os.getenv("DY_ADMIN_USERNAME", DEFAULT_ADMIN_USERNAME),
        password_hash=os.getenv("DY_ADMIN_PASSWORD_HASH"),
        test_mode=_truthy(os.getenv("DY_API_TEST_MODE")),
        test_password=os.getenv("DY_TEST_ADMIN_PASSWORD", DEFAULT_TEST_ADMIN_PASSWORD),
    )


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
    if not hmac.compare_digest(username, settings.username):
        return False

    if settings.password_hash:
        return verify_password_hash(password, settings.password_hash)

    if settings.test_mode:
        return hmac.compare_digest(password, settings.test_password)

    raise AdminPasswordNotConfigured("DY_ADMIN_PASSWORD_HASH is required")


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


def create_session_token(username: str, now: int | None = None) -> str:
    issued_at = now or int(time.time())
    ttl = get_cookie_config().max_age
    payload: dict[str, Any] = {
        "sub": username,
        "iat": issued_at,
        "exp": issued_at + ttl,
    }
    encoded_payload = _b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    return f"{encoded_payload}.{_sign_payload(encoded_payload)}"


def verify_session_token(token: str | None, now: int | None = None) -> str | None:
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
    return username


def set_session_cookie(response: Response, username: str) -> None:
    config = get_cookie_config()
    response.set_cookie(
        key=config.name,
        value=create_session_token(username),
        max_age=config.max_age,
        httponly=True,
        secure=config.secure,
        samesite=config.samesite,
        path="/",
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


def get_current_admin(request: Request) -> str:
    config = get_cookie_config()
    username = verify_session_token(request.cookies.get(config.name))
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        )

    settings = get_admin_settings()
    if not hmac.compare_digest(username, settings.username):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        )

    return username
