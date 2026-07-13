from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from apps.api.dy_api.models import ClueAllocationDecision, User  # noqa: E402
from dy_api.auth import hash_password_pbkdf2  # noqa: E402
from dy_api.main import create_app  # noqa: E402
from dy_api.routes._data import get_session_dependency  # noqa: E402


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, db_session: Session) -> TestClient:
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    monkeypatch.setenv("DY_SUPER_ADMIN_USERNAME", "system-admin")
    monkeypatch.setenv("DY_TEST_ADMIN_PASSWORD", "test-password")
    monkeypatch.setenv("DY_SESSION_COOKIE_SECURE", "false")
    app = create_app()

    def override_session():
        yield db_session

    app.dependency_overrides[get_session_dependency] = override_session
    return TestClient(app)


def _login(client: TestClient, username: str, password: str) -> None:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200


def _seed_users(session: Session) -> None:
    session.add_all(
        [
            User(
                user_id="database-admin",
                username="database-admin",
                display_name="Database Admin",
                role="admin",
                status="active",
                is_initialized=True,
                password_hash=hash_password_pbkdf2("database-admin-password"),
            ),
            User(
                user_id="store-user",
                username="store-user",
                display_name="Store User",
                role="store",
                status="active",
                is_initialized=True,
                password_hash=hash_password_pbkdf2("store-user-password"),
            ),
        ]
    )
    session.add(
        ClueAllocationDecision(
            decision_id="decision-1",
            attempt_key="clue-allocation:test",
            lead_key="lead-1",
            order_id="order-1",
            rule_id="rule-1",
            rule_version_id="version-1",
            scope_type="global",
            scope_key="global",
            strategy_type="nearby_city_optimization",
            execution_order=2,
            execution_mode="formal",
            decision_status="selected",
            reason="selected",
            decision_snapshot={
                "anchor": {"poi_id": "poi-1"},
                "phone_plain": "13812345678",
                "candidate": {"mobile": "13912345678"},
            },
            actor="test-admin",
            executed_at=datetime(2026, 7, 12, tzinfo=timezone.utc),
        )
    )
    session.commit()


def test_decision_list_is_read_only_admin_data_and_redacts_phone_payloads(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_users(db_session)

    assert client.get("/api/v1/admin/clue-allocation/decisions").status_code == 401

    _login(client, "store-user", "store-user-password")
    assert client.get("/api/v1/admin/clue-allocation/decisions").status_code == 403

    _login(client, "database-admin", "database-admin-password")
    response = client.get("/api/v1/admin/clue-allocation/decisions")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"data", "meta"}
    assert body["data"]["pagination"]["total"] == 1
    row = body["data"]["rows"][0]
    assert row["decision_id"] == "decision-1"
    assert row["payload"] == {"anchor": {"poi_id": "poi-1"}, "candidate": {}}
    assert "13812345678" not in json.dumps(body, ensure_ascii=False)
    assert "13912345678" not in json.dumps(body, ensure_ascii=False)
