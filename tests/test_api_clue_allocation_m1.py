from __future__ import annotations

import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from dy_api.main import create_app  # noqa: E402
from dy_api.routes._data import get_session_dependency  # noqa: E402
from apps.api.dy_api.models import (  # noqa: E402
    ClueMasterLead,
    DimStore,
    StoreScoreSnapshot,
    StoreScoreSnapshotRun,
    User,
)
from dy_api.auth import hash_password_pbkdf2  # noqa: E402


def _dt(day: int, hour: int = 10) -> datetime:
    return datetime(2026, 7, day, hour, tzinfo=timezone.utc)


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


def _login(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "system-admin", "password": "test-password"},
    )
    assert response.status_code == 200


def _login_user(client: TestClient, username: str, password: str) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200


def _seed_m1_data(session: Session) -> None:
    session.add(
        DimStore(
            store_id="score-store",
            store_name="Score Store",
            is_active=True,
            standard_province="上海",
            standard_city="上海",
            city_code="上海",
            longitude=Decimal("121.470000"),
            latitude=Decimal("31.230000"),
            is_douyin_clue_applicable=True,
            participates_in_clue_allocation=True,
            location_status="valid",
        )
    )
    session.add(
        ClueMasterLead(
            lead_key="lead-test",
            source_clue_row_key="raw-test",
            source_identity_key="identity-test",
            canonical_clue_id="clue-test",
            order_id="order-test",
            raw_order_status="履约中",
            normalized_order_status="active",
            status_source="clue",
            lifecycle_status="active",
            pool_location=None,
            allocation_state="pending_allocation",
            ended_without_assignment=False,
            first_seen_at=_dt(1),
            last_seen_at=_dt(1),
            anchor_poi_id="poi-test",
            anchor_store_id="score-store",
            anchor_source="douyin_follow_poi",
            anchor_province="上海",
            anchor_city="上海",
            anchor_city_code="上海",
            anchor_longitude=Decimal("121.470000"),
            anchor_latitude=Decimal("31.230000"),
            created_at=_dt(1),
            updated_at=_dt(1),
        )
    )
    session.add(
        StoreScoreSnapshotRun(
            snapshot_run_id="score-run-test",
            snapshot_date=_dt(2).date(),
            run_mode="manual",
            window_start=_dt(1),
            window_end=_dt(2),
            candidate_store_count=1,
            snapshot_count=1,
            config_json={"min_samples": 20},
            computed_at=_dt(2),
        )
    )
    session.add(
        StoreScoreSnapshot(
            snapshot_id="score-run-test-score-store",
            snapshot_run_id="score-run-test",
            snapshot_date=_dt(2).date(),
            run_mode="manual",
            store_id="score-store",
            city_code="上海",
            window_start=_dt(1),
            window_end=_dt(2),
            conversion_numerator=1,
            conversion_denominator=2,
            conversion_rate=Decimal("0.5"),
            conversion_value_source="store",
            follow_24h_numerator=1,
            follow_24h_denominator=2,
            follow_24h_rate=Decimal("0.5"),
            follow_24h_value_source="store",
            conversion_weight=Decimal("0.7"),
            follow_24h_weight=Decimal("0.3"),
            store_weight=Decimal("1"),
            composite_score=Decimal("0.5"),
            config_json={"min_samples": 20},
            computed_at=_dt(2),
        )
    )
    session.commit()


def test_admin_m1_master_pool_contract_is_protected_and_excludes_source_identity(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_m1_data(db_session)

    assert client.get("/api/v1/admin/clue-allocation/master-leads").status_code == 401

    _login(client)
    response = client.get("/api/v1/admin/clue-allocation/master-leads?allocation_state=pending_allocation")

    assert response.status_code == 200
    row = response.json()["data"]["rows"][0]
    assert row["canonical_clue_id"] == "clue-test"
    assert row["pool_location"] is None
    assert row["allocation_state"] == "pending_allocation"
    assert "source_identity_key" not in row
    assert "source_clue_row_key" not in row


def test_admin_can_view_and_manually_refresh_m1_store_score_snapshots(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_m1_data(db_session)
    _login(client)

    view = client.get("/api/v1/admin/clue-allocation/store-scores?snapshot_run_id=score-run-test")
    assert view.status_code == 200
    assert view.json()["data"]["run"]["snapshot_run_id"] == "score-run-test"
    assert view.json()["data"]["rows"][0]["composite_score"] == 0.5

    refresh = client.post(
        "/api/v1/admin/clue-allocation/store-scores/refresh",
        json={"lookback_days": 30, "min_samples": 20},
    )
    assert refresh.status_code == 200
    assert refresh.json()["data"]["snapshot_count"] == 1
    refreshed_run = client.get(
        f"/api/v1/admin/clue-allocation/store-scores?snapshot_run_id={refresh.json()['data']['snapshot_run_id']}"
    )
    assert refreshed_run.json()["data"]["run"]["triggered_by"] == "system-admin"


def test_database_admin_cannot_access_highest_admin_m1_controls(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_m1_data(db_session)
    db_session.add(
        User(
            user_id="database-admin",
            username="database-admin",
            display_name="Database Admin",
            role="admin",
            status="active",
            is_initialized=True,
            password_hash=hash_password_pbkdf2("database-admin-password"),
        )
    )
    db_session.commit()

    _login_user(client, "database-admin", "database-admin-password")

    assert client.get("/api/v1/admin/clue-allocation/master-leads").status_code == 403
    assert client.get("/api/v1/admin/clue-allocation/store-scores").status_code == 403
    assert (
        client.post(
            "/api/v1/admin/clue-allocation/store-scores/refresh",
            json={"lookback_days": 30, "min_samples": 20},
        ).status_code
        == 403
    )
