from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from apps.api.dy_api.models import CliDeviceAuthorization, CliRefreshToken, User, utcnow


def test_cli_device_authorization_and_refresh_token_persist(db_session) -> None:
    grant = CliDeviceAuthorization(
        device_authorization_id="device-1",
        device_code_hash="device-hash",
        user_code_hash="user-hash",
        status="pending",
        scope="cli:read",
        expires_at=utcnow() + timedelta(minutes=10),
    )
    refresh_token = CliRefreshToken(
        refresh_token_id="refresh-1",
        token_hash="refresh-hash",
        username="admin",
        auth_type="local",
        authorization_fingerprint="fingerprint-1",
        expires_at=utcnow() + timedelta(days=30),
    )

    db_session.add_all([grant, refresh_token])
    db_session.commit()

    persisted_grant = db_session.get(CliDeviceAuthorization, "device-1")
    persisted_refresh_token = db_session.get(CliRefreshToken, "refresh-1")
    assert persisted_grant is not None
    assert persisted_grant.status == "pending"
    assert persisted_grant.user_id is None
    assert persisted_refresh_token is not None
    assert persisted_refresh_token.user_id is None
    assert persisted_refresh_token.token_hash == "refresh-hash"
    assert persisted_refresh_token.authorization_fingerprint == "fingerprint-1"


@pytest.mark.parametrize(
    ("model", "values"),
    [
        (
            CliDeviceAuthorization,
            {
                "device_authorization_id": "device-duplicate",
                "device_code_hash": "device-hash",
                "user_code_hash": "new-user-hash",
                "expires_at": utcnow() + timedelta(minutes=10),
            },
        ),
        (
            CliRefreshToken,
            {
                "refresh_token_id": "refresh-duplicate",
                "token_hash": "refresh-hash",
                "username": "admin",
                "auth_type": "local",
                "authorization_fingerprint": "fingerprint-duplicate",
                "expires_at": utcnow() + timedelta(days=30),
            },
        ),
    ],
)
def test_cli_auth_hashes_are_unique(db_session, model, values) -> None:
    db_session.add(
        CliDeviceAuthorization(
            device_authorization_id="device-1",
            device_code_hash="device-hash",
            user_code_hash="user-hash",
            expires_at=utcnow() + timedelta(minutes=10),
        )
    )
    db_session.add(
        CliRefreshToken(
            refresh_token_id="refresh-1",
            token_hash="refresh-hash",
            username="admin",
            auth_type="local",
            authorization_fingerprint="fingerprint-1",
            expires_at=utcnow() + timedelta(days=30),
        )
    )
    db_session.commit()

    db_session.add(model(**values))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_cli_device_authorization_user_code_hash_is_unique(db_session) -> None:
    db_session.add(
        CliDeviceAuthorization(
            device_authorization_id="device-1",
            device_code_hash="device-hash",
            user_code_hash="user-hash",
            expires_at=utcnow() + timedelta(minutes=10),
        )
    )
    db_session.commit()

    db_session.add(
        CliDeviceAuthorization(
            device_authorization_id="device-2",
            device_code_hash="different-device-hash",
            user_code_hash="user-hash",
            expires_at=utcnow() + timedelta(minutes=10),
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    assert db_session.get(CliDeviceAuthorization, "device-1") is not None
    assert db_session.get(CliDeviceAuthorization, "device-2") is None


def test_cli_refresh_token_authorization_fingerprint_is_required(db_session) -> None:
    db_session.add(
        CliRefreshToken(
            refresh_token_id="refresh-without-fingerprint",
            token_hash="refresh-without-fingerprint-hash",
            username="admin",
            auth_type="env_admin",
            expires_at=utcnow() + timedelta(days=30),
        )
    )

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_user_cli_subject_is_random_unique_and_generation_defaults_to_one(
    db_session,
) -> None:
    first = User(
        user_id="user-1",
        username="first",
        display_name="First",
        role="viewer",
        status="active",
        is_initialized=True,
    )
    second = User(
        user_id="user-2",
        username="second",
        display_name="Second",
        role="viewer",
        status="active",
        is_initialized=True,
    )
    db_session.add_all([first, second])
    db_session.commit()

    assert first.cli_subject
    assert second.cli_subject
    assert first.cli_subject != second.cli_subject
    assert first.cli_subject != first.user_id
    assert first.auth_generation == 1
    assert second.auth_generation == 1

    duplicate = User(
        user_id="user-3",
        username="third",
        display_name="Third",
        role="viewer",
        status="active",
        is_initialized=True,
        cli_subject=first.cli_subject,
    )
    db_session.add(duplicate)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


@pytest.mark.parametrize(
    ("field_name", "changed_value"),
    [
        ("username", "renamed"),
        ("role", "admin"),
        ("status", "disabled"),
        ("is_initialized", False),
        ("password_hash", "new-hash"),
    ],
)
def test_security_sensitive_user_changes_increment_auth_generation(
    db_session, field_name: str, changed_value: object
) -> None:
    user = User(
        user_id="security-user",
        username="security-user",
        display_name="Security User",
        role="viewer",
        status="active",
        is_initialized=True,
        password_hash="old-hash",
    )
    db_session.add(user)
    db_session.commit()
    initial_generation = user.auth_generation

    setattr(user, field_name, changed_value)
    db_session.commit()

    assert user.auth_generation == initial_generation + 1


def test_cli_subject_is_immutable_after_user_is_persisted(db_session) -> None:
    user = User(
        user_id="stable-subject-user",
        username="stable-subject-user",
        display_name="Stable Subject User",
        role="viewer",
        status="active",
        is_initialized=True,
    )
    db_session.add(user)
    db_session.commit()

    with pytest.raises(ValueError, match="cli_subject is immutable"):
        user.cli_subject = "replacement-subject"
