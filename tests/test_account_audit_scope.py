"""Real-route regressions for historical account audit scope boundaries."""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from test_api_access_control import _login, client
from apps.api.dy_api.models import AccountPermissionAuditLog, User


INITIAL_PASSWORD = "AuditInitial123!"
RESET_PASSWORD = "AuditReset456!"


def _create_account(api: TestClient, username: str, store_id: str, *, role: str = "store") -> str:
    response = api.post("/api/v1/admin/accounts", json={
        "username": username, "display_name": username, "role": role,
        "status": "active", "store_scope_mode": "specified", "store_ids": [store_id],
        "password": INITIAL_PASSWORD, "password_confirm": INITIAL_PASSWORD,
    })
    assert response.status_code == 200, response.text
    return response.json()["data"]["user_id"]


def _reset_password(api: TestClient, user_id: str) -> None:
    response = api.post(f"/api/v1/admin/accounts/{user_id}/reset-password", json={
        "password": RESET_PASSWORD, "password_confirm": RESET_PASSWORD,
    })
    assert response.status_code == 200, response.text


def _audit_rows(api: TestClient, user_id: str) -> list[dict]:
    response = api.get("/api/v1/admin/access-control/audit-logs", params={"target_user_id": user_id})
    assert response.status_code == 200, response.text
    return response.json()["data"]["rows"]


def _legacy_reset(session: Session, user_id: str, username: str) -> str:
    audit_id = f"legacy-reset-{user_id}"
    session.add(AccountPermissionAuditLog(
        audit_id=audit_id, action="account.password_reset", result="success",
        actor_username="legacy-global", actor_role="admin",
        target_user_id=user_id, target_username=username,
        before_json={}, after_json={"password_reset": True},
    ))
    session.commit()
    return audit_id


@pytest.fixture()
def audit_api(client: TestClient) -> TestClient:
    """Create a real scoped administrator while retaining the global login."""
    _login(client, "system-admin", "test-password")
    _create_account(client, "audit-scoped", "store-1", role="admin")
    return client


def test_reset_before_store_transfer_is_hidden_from_new_scope(audit_api: TestClient) -> None:
    """Current management rights do not expose a reset in the previous store."""
    user_id = _create_account(audit_api, "transferred", "store-2")
    _reset_password(audit_api, user_id)
    original = next(row for row in _audit_rows(audit_api, user_id) if row["action"] == "account.password_reset")
    assert original["before"]["store_ids"] == original["after"]["store_ids"] == ["store-2"]
    response = audit_api.put(f"/api/v1/admin/accounts/{user_id}", json={
        "username": "transferred", "display_name": "transferred", "role": "store",
        "status": "active", "store_scope_mode": "specified", "store_ids": ["store-1"],
    })
    assert response.status_code == 200, response.text
    _login(audit_api, "audit-scoped", INITIAL_PASSWORD)
    directory = audit_api.get("/api/v1/admin/accounts")
    assert directory.status_code == 200
    assert user_id in {row["user_id"] for row in directory.json()["data"]["rows"]}
    assert original["audit_id"] not in {row["audit_id"] for row in _audit_rows(audit_api, user_id)}


def test_legacy_reset_without_scope_snapshot_is_hidden(audit_api: TestClient, db_session: Session) -> None:
    """An unknown historical scope cannot inherit the account's current scope."""
    user_id = _create_account(audit_api, "legacy-target", "store-1")
    legacy_id = _legacy_reset(db_session, user_id, "legacy-target")
    _login(audit_api, "audit-scoped", INITIAL_PASSWORD)
    assert legacy_id not in {row["audit_id"] for row in _audit_rows(audit_api, user_id)}


def test_same_store_reset_is_visible_with_complete_secret_free_snapshots(
    audit_api: TestClient, db_session: Session,
) -> None:
    """Authorized resets retain enough history without storing passwords or hashes."""
    user_id = _create_account(audit_api, "same-store", "store-1")
    old_hash = db_session.get(User, user_id).password_hash
    _login(audit_api, "audit-scoped", INITIAL_PASSWORD)
    _reset_password(audit_api, user_id)
    rows = _audit_rows(audit_api, user_id)
    reset = next(row for row in rows if row["action"] == "account.password_reset")
    for snapshot in (reset["before"], reset["after"]):
        assert snapshot["role"] == "store"
        assert snapshot["store_scope_mode"] == "specified"
        assert snapshot["store_ids"] == ["store-1"]
        assert snapshot["org_scope"] is None
    assert reset["after"]["password_reset"] is True
    db_session.refresh(db_session.get(User, user_id))
    new_hash = db_session.get(User, user_id).password_hash
    assert new_hash and new_hash != old_hash
    snapshots = json.dumps([(row["before"], row["after"]) for row in rows])
    for secret in (INITIAL_PASSWORD, RESET_PASSWORD, old_hash, new_hash):
        assert secret not in snapshots


def test_store_creation_with_empty_before_remains_visible(audit_api: TestClient) -> None:
    """A genuine creation has no prior scope and is visible from its after-image."""
    user_id = _create_account(audit_api, "created-in-scope", "store-1")
    _login(audit_api, "audit-scoped", INITIAL_PASSWORD)
    creation = next(row for row in _audit_rows(audit_api, user_id) if row["action"] == "account.created")
    assert creation["before"] == {}
    assert creation["after"]["store_ids"] == ["store-1"]


def test_global_admin_retains_all_complete_and_legacy_audits(
    audit_api: TestClient, db_session: Session,
) -> None:
    """Global history remains complete, including unknown and outside scopes."""
    user_id = _create_account(audit_api, "global-history", "store-2")
    _reset_password(audit_api, user_id)
    legacy_id = _legacy_reset(db_session, user_id, "global-history")
    expected = set(db_session.scalars(select(AccountPermissionAuditLog.audit_id).where(
        AccountPermissionAuditLog.target_user_id == user_id,
    )).all())
    _login(audit_api, "audit-scoped", INITIAL_PASSWORD)
    assert _audit_rows(audit_api, user_id) == []
    _login(audit_api, "system-admin", "test-password")
    rows = _audit_rows(audit_api, user_id)
    assert {row["audit_id"] for row in rows} == expected
    assert legacy_id in expected and len(expected) == 3
