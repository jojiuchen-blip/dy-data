from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.exc import StaleDataError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from apps.api.dy_api.models import (  # noqa: E402
    Base,
    CliRefreshToken,
    DimStore,
    User,
    UserStoreScope,
)
from apps.api.dy_api.user_auth_state import replace_user_store_scopes  # noqa: E402
from dy_api.auth import AuthContext  # noqa: E402
from dy_api.cli_auth import issue_refresh_token, rotate_refresh_token  # noqa: E402


def _session_factory(tmp_path: Path) -> sessionmaker[Session]:
    database_path = tmp_path / "cli-auth-concurrency.sqlite"
    engine = create_engine(f"sqlite:///{database_path.as_posix()}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def _add_user(session: Session, *, user_id: str = "user-1") -> User:
    user = User(
        user_id=user_id,
        username=user_id,
        display_name="Concurrent User",
        role="viewer",
        status="active",
        is_initialized=True,
        password_hash="initial-hash",
    )
    session.add(user)
    session.commit()
    return user


def test_stale_security_update_cannot_reuse_auth_generation(tmp_path: Path) -> None:
    factory = _session_factory(tmp_path)
    with factory() as setup_session:
        _add_user(setup_session)

    with factory() as session_a, factory() as session_b:
        user_a = session_a.get(User, "user-1")
        user_b = session_b.get(User, "user-1")
        assert user_a is not None and user_b is not None
        assert user_a.auth_generation == user_b.auth_generation == 1

        user_a.role = "admin"
        session_a.commit()
        assert user_a.auth_generation == 2
        refresh_token, stored = issue_refresh_token(
            session_a,
            AuthContext(
                user_id=user_a.user_id,
                username=user_a.username,
                display_name=user_a.display_name,
                role=user_a.role,
                store_ids=(),
                auth_type="user",
            ),
        )
        session_a.commit()
        assert stored.issued_auth_generation == 2

        user_b.password_hash = "stale-change"
        with pytest.raises(StaleDataError):
            session_b.commit()
        session_b.rollback()

        retried_user = session_b.get(User, "user-1")
        assert retried_user is not None
        assert retried_user.auth_generation == 2
        retried_user.password_hash = "retried-change"
        session_b.commit()
        assert retried_user.auth_generation == 3

    with factory() as verification_session:
        with pytest.raises(HTTPException) as exc_info:
            rotate_refresh_token(verification_session, refresh_token)
        assert exc_info.value.status_code == 401
        persisted = verification_session.get(
            CliRefreshToken, stored.refresh_token_id
        )
        assert persisted is not None
        assert persisted.revoked_at is not None


def test_scope_replacement_atomically_bumps_stale_user_once_and_noop_does_not(
    tmp_path: Path,
) -> None:
    factory = _session_factory(tmp_path)
    with factory() as setup_session:
        setup_session.add(DimStore(store_id="store-a", store_name="Store A"))
        _add_user(setup_session, user_id="scope-user")
        setup_session.add(
            UserStoreScope(user_id="scope-user", store_id="store-a")
        )
        setup_session.commit()

    with factory() as stale_session, factory() as concurrent_session:
        stale_user = stale_session.get(User, "scope-user")
        concurrent_user = concurrent_session.get(User, "scope-user")
        assert stale_user is not None and concurrent_user is not None
        initial_generation = stale_user.auth_generation
        assert concurrent_user.auth_generation == initial_generation

        concurrent_user.role = "admin"
        concurrent_session.commit()
        assert concurrent_user.auth_generation == initial_generation + 1

        replace_user_store_scopes(stale_session, "scope-user", [])
        stale_session.commit()
        assert stale_user.auth_generation == initial_generation + 2

        replace_user_store_scopes(stale_session, "scope-user", [])
        stale_session.commit()
        assert stale_user.auth_generation == initial_generation + 2
