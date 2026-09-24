"""Isolated PDCA authorization and rollback-only, database-enforced reads.

Existing login, permission initialization and session dependencies are unchanged.
"""
from collections.abc import Iterator
import hmac

from fastapi import Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from apps.api.dy_api.models import User
from dy_api.auth import (
    _admin_credentials_configured,
    get_admin_settings,
    get_cookie_config,
    verify_session_payload,
)
from dy_api.db import get_engine


def get_pdca_readonly_session() -> Iterator[Session]:
    """Sanitize failures across connection, authentication query and teardown."""
    try:
        yield from _open_pdca_readonly_session()
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail='Source database unavailable') from None


def _open_pdca_readonly_session() -> Iterator[Session]:
    """Open a dedicated read-only transaction; never commit or seed defaults."""
    engine = get_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail='Source database unavailable')
    if engine.dialect.name not in {'postgresql', 'sqlite'}:
        raise HTTPException(status_code=503, detail='Read-only isolation unavailable')
    with engine.connect() as connection:
        sqlite_query_only = None
        session = None
        try:
            if engine.dialect.name == 'postgresql':
                connection.execute(text('SET TRANSACTION READ ONLY'))
                connection.execute(text("SET LOCAL statement_timeout = '8s'"))
                connection.execute(text("SET LOCAL lock_timeout = '1s'"))
            else:
                sqlite_query_only = connection.scalar(text('PRAGMA query_only'))
                connection.execute(text('PRAGMA query_only = ON'))
            session = Session(bind=connection, autoflush=False)
            yield session
        finally:
            if session is not None:
                session.close()
            connection.rollback()
            if sqlite_query_only is not None:
                try:
                    connection.execute(text('PRAGMA query_only = ON' if sqlite_query_only else 'PRAGMA query_only = OFF'))
                    connection.rollback()
                except Exception:
                    connection.invalidate()
                    raise


def require_pdca_super_admin(
    request: Request,
    session: Session = Depends(get_pdca_readonly_session),
) -> str:
    """Validate the existing signed session without permission seed side effects.

    Database users must remain initialized, active, highest-admin and at the
    token's current auth version. Token role claims never grant authority.
    """
    payload = verify_session_payload(request.cookies.get(get_cookie_config().name))
    if payload is None:
        raise HTTPException(status_code=401, detail='Not authenticated')
    username = payload.get('sub')
    if not isinstance(username, str):
        raise HTTPException(status_code=401, detail='Not authenticated')
    auth_type = payload.get('auth_type') or 'env_admin'
    if auth_type == 'env_admin':
        settings = get_admin_settings()
        if not _admin_credentials_configured(settings) or not hmac.compare_digest(username, settings.username):
            raise HTTPException(status_code=401, detail='Not authenticated')
        return username
    if auth_type != 'user' or not isinstance(payload.get('uid'), str):
        raise HTTPException(status_code=401, detail='Not authenticated')
    with session.no_autoflush:
        user = session.get(User, payload['uid'])
    version = payload.get('auth_version', 1)
    if (user is None or user.status != 'active' or not user.is_initialized
            or type(version) is not int or version != user.auth_version):
        raise HTTPException(status_code=401, detail='Session is no longer valid')
    if user.role != 'highest_admin':
        raise HTTPException(status_code=403, detail='Highest administrator access required')
    return user.username
