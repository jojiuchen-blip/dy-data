"""The account data migration preserves scopes and revokes old credentials."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from apps.api.dy_api.access_control import ensure_access_control_seed
from apps.api.dy_api.models import AccountPermissionAuditLog, DimStore, User, UserPagePermissionOverride, UserStoreScope


def test_unification_migration_preserves_scope_password_status_and_history(db_session, monkeypatch):
    ensure_access_control_seed(db_session)
    db_session.add(DimStore(store_id="isolated-store", store_name="Isolated", is_active=True))
    for identifier, role, mode in (("highest", "highest_admin", "specified"), ("admin", "admin", "all"), ("shop", "store", "specified")):
        db_session.add(User(user_id=identifier, username=identifier, display_name=identifier, role=role,
                            status="disabled", is_initialized=True, password_hash="unchanged-hash",
                            store_scope_mode=mode, org_scope=None, auth_version=5, auth_generation=7))
        db_session.add(UserStoreScope(user_id=identifier, store_id="isolated-store"))
        db_session.add(UserPagePermissionOverride(user_id=identifier, page_key="B03", effect="deny", updated_by="prior-admin"))
    db_session.add(AccountPermissionAuditLog(audit_id="existing", action="account.updated", result="success",
                                           actor_username="prior-admin", actor_role="highest_admin",
                                           before_json={}, after_json={}))
    db_session.commit()
    before = {row.user_id: (row.password_hash, row.status, row.store_scope_mode, row.org_scope,
                            row.auth_version, row.auth_generation)
              for row in db_session.scalars(select(User))}
    path = Path(__file__).resolve().parents[1] / "alembic/versions/20261022_0064_unify_administrators.py"
    spec = importlib.util.spec_from_file_location("migration_0064", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "op", SimpleNamespace(get_bind=lambda: db_session.connection()))
    module.upgrade()
    module.upgrade()  # Safe to resume after an interrupted migration transaction.
    db_session.expire_all()
    for user in db_session.scalars(select(User)):
        assert (user.password_hash, user.status, user.store_scope_mode, user.org_scope) == before[user.user_id][:4]
        assert db_session.scalars(select(UserStoreScope.store_id).where(UserStoreScope.user_id == user.user_id)).all() == ["isolated-store"]
        expected_bump = 0 if user.user_id == "shop" else 1
        assert user.auth_version == before[user.user_id][4] + expected_bump
        assert user.auth_generation == before[user.user_id][5] + expected_bump
        assert user.role == ("store" if user.user_id == "shop" else "admin")
    overrides = db_session.scalars(select(UserPagePermissionOverride)).all()
    assert [(row.user_id, row.page_key, row.effect) for row in overrides] == [("shop", "B03", "deny")]
    history = db_session.scalars(select(AccountPermissionAuditLog)).all()
    assert len(history) == 3
    migrated = next(row for row in history if row.target_user_id == "highest")
    assert migrated.before_json["role"] == "highest_admin"
    assert migrated.before_json["page_overrides"][0]["effect"] == "deny"
    assert "unchanged-hash" not in repr(migrated.before_json)
    with pytest.raises(RuntimeError, match="reviewed backup recovery"):
        module.downgrade()
