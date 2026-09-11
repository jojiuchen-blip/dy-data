"""Exercise the real route/auth/serialization against synthetic snapshots."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
from dy_api.main import create_app
from dy_api.auth import AuthContext, get_current_user
from dy_api.routes._data import get_session_dependency
from apps.api.dy_api.ranking_schema_v1 import metadata, runs
from apps.api.dy_api.ranking_snapshots import calculate_snapshot
from apps.worker.ranking_preview_fixture import seed_preview, START, END, CUTOFF, ELIGIBILITY_VERSION


@pytest.fixture()
def preview_client(db_session, monkeypatch):
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    monkeypatch.setenv("DY_SUPER_ADMIN_USERNAME", "ranking_test_admin")
    monkeypatch.setenv("DY_TEST_ADMIN_PASSWORD", "synthetic-test-only")
    monkeypatch.setenv("DY_SESSION_COOKIE_SECURE", "false")
    metadata.create_all(db_session.bind)
    seed_preview(db_session)
    calculate_snapshot(db_session, run_id="baseline", period_start=START, period_end=END,
                       observed_through=CUTOFF, roster_at=START, eligibility_version=ELIGIBILITY_VERSION)
    db_session.commit()
    app = create_app()
    app.state.ranking_snapshot_preview = True

    def session_override():
        yield db_session

    app.dependency_overrides[get_session_dependency] = session_override
    return TestClient(app)


PARAMS = {"periodStart": "2026-09-01", "periodEnd": "2026-09-30", "level": "store"}


def login(client):
    assert client.post("/api/v1/auth/login", json={"username": "ranking_test_admin",
        "password": "synthetic-test-only"}).status_code == 200


def test_preview_route_reads_snapshot_not_legacy_table(preview_client):
    login(preview_client)
    response = preview_client.get("/api/v1/dashboard/douyin-ranking", params=PARAMS)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["dataMode"] == "synthetic"
    assert data["snapshotId"] == "baseline"
    assert data["totals"]["storeCount"] == 3
    assert data["totals"]["orderAverage"] == 3.333333
    assert data["totals"]["follow24hRate"] == .3
    assert data["totals"]["verificationRate"] == .5
    assert "虚拟测试" in data["previewNote"]


def test_missing_period_is_explicit_error_without_mock_fallback(preview_client):
    login(preview_client)
    response = preview_client.get("/api/v1/dashboard/douyin-ranking",
        params={**PARAMS, "periodStart": "2026-08-01", "periodEnd": "2026-08-31"})
    assert response.status_code == 422


def test_preview_still_requires_login(preview_client):
    assert preview_client.get("/api/v1/dashboard/douyin-ranking", params=PARAMS).status_code == 401


def test_preview_store_scope_applied_before_aggregation(preview_client):
    auth = AuthContext(user_id=None, username="store-a", display_name="A", role="store",
        store_ids=("A",), auth_type="env_admin", store_scope_mode="explicit", page_keys=("A03",))
    preview_client.app.dependency_overrides[get_current_user] = lambda: auth
    response = preview_client.get("/api/v1/dashboard/douyin-ranking", params=PARAMS)
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data["rows"]) == 1 and data["rows"][0]["key"] == "A"
    assert data["totals"]["orderCount"] == 4
    assert data["totals"]["verificationRate"] == .5


def test_snapshot_read_never_creates_another_batch(preview_client, db_session):
    login(preview_client)
    before = db_session.scalar(select(func.count()).select_from(runs))
    for _ in range(2):
        assert preview_client.get("/api/v1/dashboard/douyin-ranking", params=PARAMS).status_code == 200
    assert db_session.scalar(select(func.count()).select_from(runs)) == before
