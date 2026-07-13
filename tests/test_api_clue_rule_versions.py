from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from apps.api.dy_api.models import DimStore, User  # noqa: E402
from dy_api.auth import hash_password_pbkdf2  # noqa: E402
from dy_api.main import create_app  # noqa: E402
from dy_api.routes._data import get_session_dependency  # noqa: E402


def _strategy_configs() -> list[dict]:
    return [
        {
            "strategy_type": "sales_store_priority",
            "enabled": True,
            "execution_order": 1,
            "params": {"max_distance_km": 10},
        },
        {
            "strategy_type": "nearby_city_optimization",
            "enabled": True,
            "execution_order": 2,
            "params": {"max_distance_km": 15},
        },
        {
            "strategy_type": "city_fallback",
            "enabled": True,
            "execution_order": 3,
            "params": {},
        },
    ]


def _version_payload() -> dict:
    return {
        "auto_expiry_enabled": True,
        "first_follow_up_sla_hours": 24,
        "protection_days": 7,
        "conversion_weight": 0.7,
        "follow_24h_weight": 0.3,
        "lookback_days": 30,
        "min_samples": 20,
        "strategy_configs": _strategy_configs(),
    }


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
    session.add(DimStore(store_id="store-1", store_name="Store 1", is_active=True))
    session.commit()


def test_rule_version_apis_enforce_read_and_write_permissions(client: TestClient, db_session: Session) -> None:
    _seed_users(db_session)

    assert client.get("/api/v1/admin/clue-allocation/rules").status_code == 401

    _login(client, "store-user", "store-user-password")
    assert client.get("/api/v1/admin/clue-allocation/rules").status_code == 403

    _login(client, "database-admin", "database-admin-password")
    read_only = client.get("/api/v1/admin/clue-allocation/rules")
    assert read_only.status_code == 200
    assert read_only.json()["data"]["rows"] == []
    assert client.post(
        "/api/v1/admin/clue-allocation/rules",
        json={"name": "Global default", "scope": {"scope_type": "global"}},
    ).status_code == 403

    _login(client, "system-admin", "test-password")
    created_rule = client.post(
        "/api/v1/admin/clue-allocation/rules",
        json={"name": "Global default", "scope": {"scope_type": "global"}},
    )
    assert created_rule.status_code == 201
    assert set(created_rule.json()) == {"data", "meta"}
    rule_id = created_rule.json()["data"]["rule_id"]

    created_version = client.post(
        f"/api/v1/admin/clue-allocation/rules/{rule_id}/versions",
        json=_version_payload(),
    )
    assert created_version.status_code == 201
    version_id = created_version.json()["data"]["rule_version_id"]
    assert created_version.json()["data"]["status"] == "draft"

    published = client.post(f"/api/v1/admin/clue-allocation/rule-versions/{version_id}/publish")
    assert published.status_code == 200
    assert published.json()["data"]["status"] == "published"
    assert {row["strategy_type"] for row in published.json()["data"]["strategy_configs"]} == {
        "sales_store_priority",
        "nearby_city_optimization",
        "city_fallback",
    }
    assert "created_by" not in published.json()["data"]

    _login(client, "database-admin", "database-admin-password")
    assert client.put(
        f"/api/v1/admin/clue-allocation/rule-versions/{version_id}",
        json=_version_payload(),
    ).status_code == 403

    _login(client, "system-admin", "test-password")
    assert client.put(
        f"/api/v1/admin/clue-allocation/rule-versions/{version_id}",
        json=_version_payload(),
    ).status_code == 409
    assert client.delete(f"/api/v1/admin/clue-allocation/rule-versions/{version_id}").status_code == 409


def test_highest_admin_can_manage_store_group_members(client: TestClient, db_session: Session) -> None:
    _seed_users(db_session)
    _login(client, "system-admin", "test-password")

    created = client.post(
        "/api/v1/admin/clue-allocation/store-groups",
        json={"name": "Pilot group", "member_store_ids": ["store-1"]},
    )
    assert created.status_code == 201
    group_id = created.json()["data"]["store_group_id"]
    assert created.json()["data"]["member_store_ids"] == ["store-1"]

    updated = client.put(
        f"/api/v1/admin/clue-allocation/store-groups/{group_id}/members",
        json={"member_store_ids": []},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["member_store_ids"] == []

    _login(client, "database-admin", "database-admin-password")
    listed = client.get("/api/v1/admin/clue-allocation/store-groups")
    assert listed.status_code == 200
    assert listed.json()["data"]["rows"][0]["store_group_id"] == group_id
    assert client.put(
        f"/api/v1/admin/clue-allocation/store-groups/{group_id}/members",
        json={"member_store_ids": ["store-1"]},
    ).status_code == 403
