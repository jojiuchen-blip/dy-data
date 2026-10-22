"""Destructive test fixtures are restricted to the dedicated DYDATA-105 local DB."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import os
from pathlib import Path
import sys
from threading import Barrier, Event
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from apps.api.dy_api.account_permissions import begin_account_mutation, protect_last_global_admin
from apps.api.dy_api.access_control import ensure_access_control_seed
from apps.api.dy_api.models import (
    AccessPage, AccountPermissionAuditLog, Base, DimStore, RolePagePermission,
    User, UserPagePermissionOverride, UserStoreScope,
)
from dy_api.auth import AuthContext, hash_password_pbkdf2
from dy_api.main import create_app
from dy_api.routes._data import get_session_dependency


@pytest.fixture()
def pg_factory(monkeypatch):
    value = os.getenv("DYDATA105_AUTH_TEST_DATABASE_URL")
    if not value:
        pytest.skip("Dedicated DYDATA105_AUTH_TEST_DATABASE_URL is not configured")
    url = make_url(value)
    if url.host not in {"127.0.0.1", "localhost"} or url.port != 55435 or url.database != "dydata105_auth":
        pytest.fail("Refusing a database outside the dedicated local DYDATA-105 auth instance")
    engine = create_engine(url)
    schema = "auth105_" + uuid4().hex
    with engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    scoped = engine.execution_options(schema_translate_map={None: schema})
    tables = [model.__table__ for model in (
        User, DimStore, UserStoreScope, AccessPage, RolePagePermission,
        UserPagePermissionOverride, AccountPermissionAuditLog,
    )]
    Base.metadata.create_all(scoped, tables=tables)
    factory = sessionmaker(bind=scoped, autoflush=False, expire_on_commit=False)
    with factory.begin() as session:
        ensure_access_control_seed(session)
        for identifier in ("alpha", "beta"):
            session.add(User(user_id=identifier, username=identifier, display_name=identifier,
                             role="admin", status="active", store_scope_mode="all",
                             is_initialized=True, password_hash=hash_password_pbkdf2("test-secret")))
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    monkeypatch.setenv("DY_SESSION_COOKIE_SECURE", "false")
    try:
        yield factory
    finally:
        scoped.dispose()
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()


def test_concurrent_administrators_cannot_disable_each_other(pg_factory):
    app = create_app()

    def session_dependency():
        with pg_factory() as session:
            yield session

    app.dependency_overrides[get_session_dependency] = session_dependency
    clients = []
    for identifier in ("alpha", "beta"):
        client = TestClient(app)
        result = client.post("/api/v1/auth/login", json={"username": identifier, "password": "test-secret"})
        assert result.status_code == 200
        clients.append(client)
    barrier = Barrier(2)

    def disable(index):
        barrier.wait(timeout=5)
        target = "beta" if index == 0 else "alpha"
        return clients[index].put(f"/api/v1/admin/accounts/{target}", json={
            "username": target, "display_name": target, "role": "admin", "status": "disabled",
            "store_scope_mode": "all", "store_ids": [],
        }).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(disable, range(2)))
    assert statuses.count(200) == 1
    assert all(code in {200, 401, 409} for code in statuses)
    with pg_factory() as session:
        assert session.scalar(select(func.count()).select_from(User).where(User.status == "active")) == 1
        assert session.scalar(select(func.count()).select_from(AccountPermissionAuditLog).where(
            AccountPermissionAuditLog.action == "account.updated")) == 1
    for client in clients:
        client.close()


def test_waiting_account_writer_rechecks_revoked_actor_after_lock(pg_factory):
    started = Event()
    actor = AuthContext(user_id="beta", username="beta", display_name="beta", role="admin",
                        store_ids=(), auth_type="user", store_scope_mode="all", auth_version=1)
    environment = replace(actor, user_id=None, auth_type="env_admin", username="environment")

    def queued_write():
        with pg_factory() as session:
            # Load the old row into this session as get_current_user would do.
            assert session.get(User, "beta").status == "active"
            started.set()
            with pytest.raises(HTTPException) as error:
                begin_account_mutation(session, actor)
            assert error.value.status_code == 401

    with pg_factory() as first:
        begin_account_mutation(first, environment)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(queued_write)
            assert started.wait(timeout=5)
            target = first.get(User, "beta")
            protect_last_global_admin(first, target, role="admin", status="disabled", scope_mode="all")
            target.status = "disabled"
            target.auth_version += 1
            first.commit()
            future.result(timeout=10)
