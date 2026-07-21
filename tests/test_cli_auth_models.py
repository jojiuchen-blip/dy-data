from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from apps.api.dy_api.models import CliDeviceAuthorization, CliRefreshToken, utcnow


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
            expires_at=utcnow() + timedelta(days=30),
        )
    )
    db_session.commit()

    db_session.add(model(**values))
    with pytest.raises(IntegrityError):
        db_session.commit()
