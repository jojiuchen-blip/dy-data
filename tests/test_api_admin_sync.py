from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from dy_api.main import create_app  # noqa: E402
from dy_api.routes import admin as admin_routes  # noqa: E402
from dy_api.routes._data import get_session_dependency  # noqa: E402
from apps.worker.collectors.types import CollectionWindow  # noqa: E402
from apps.worker.repositories import finish_job_run, start_job_run  # noqa: E402


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, db_session: Session) -> TestClient:
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
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
        json={"username": "admin", "password": "test-password"},
    )
    assert response.status_code == 200


def _window(start: str, end: str) -> CollectionWindow:
    return CollectionWindow(
        start=datetime.fromisoformat(start),
        end=datetime.fromisoformat(end),
        timezone_name="Asia/Shanghai",
    )


def _record_successful_collect_window(
    session: Session,
    *,
    job_id: str,
    window: CollectionWindow,
) -> None:
    start_job_run(
        session,
        job_id,
        "collect_and_settle",
        metadata_json={
            "source_window": window.as_metadata(),
            "phases": {
                "orders": {
                    "name": "orders",
                    "fetched": 10,
                    "upserted": 10,
                    "skipped": 0,
                    "failed": 0,
                }
            },
        },
        started_at=window.start.astimezone(timezone.utc),
    )
    finish_job_run(
        session,
        job_id,
        status="success",
        success_count=10,
        finished_at=window.end.astimezone(timezone.utc),
    )
    session.commit()


def test_admin_sync_requires_login(client: TestClient) -> None:
    response = client.get("/api/v1/admin/sync")

    assert response.status_code == 401


def test_admin_can_read_and_update_sync_config(client: TestClient) -> None:
    _login(client)

    response = client.get("/api/v1/admin/sync")
    assert response.status_code == 200
    assert response.json()["data"]["config"]["rolling_days"] == 30

    response = client.put(
        "/api/v1/admin/sync/config",
        json={
            "history_start": "2026-01-01",
            "history_end": "2026-06-16",
            "history_chunk_days": 2,
            "rolling_days": 14,
            "interval_seconds": 1800,
            "auto_sync_enabled": False,
        },
    )

    assert response.status_code == 200
    config = response.json()["data"]["config"]
    assert config["history_start"] == "2026-01-01"
    assert config["history_end"] == "2026-06-16"
    assert config["history_chunk_days"] == 2
    assert config["rolling_days"] == 14
    assert config["interval_seconds"] == 1800
    assert config["auto_sync_enabled"] is False

    response = client.get("/api/v1/admin/sync")
    assert response.json()["data"]["config"] == config


def test_admin_sync_exposes_schedule_status(
    client: TestClient,
    db_session: Session,
) -> None:
    finished_at = datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc)
    start_job_run(
        db_session,
        "collect-success",
        "collect_and_settle",
        metadata_json={"phases": {}},
        started_at=finished_at - timedelta(minutes=5),
    )
    finish_job_run(
        db_session,
        "collect-success",
        status="success",
        success_count=1,
        finished_at=finished_at,
    )
    db_session.commit()
    _login(client)
    client.put(
        "/api/v1/admin/sync/config",
        json={
            "rolling_days": 30,
            "interval_seconds": 3600,
            "auto_sync_enabled": True,
        },
    )

    response = client.get("/api/v1/admin/sync")

    assert response.status_code == 200
    schedule = response.json()["data"]["schedule"]
    assert schedule["auto_sync_enabled"] is True
    assert schedule["latest_successful_sync_at"].startswith("2026-06-01T08:00:00")
    assert schedule["next_scheduled_sync_at"].startswith("2026-06-01T09:00:00")


def test_admin_sync_progress_counts_completed_backfill_windows(
    client: TestClient,
    db_session: Session,
) -> None:
    _record_successful_collect_window(
        db_session,
        job_id="backfill-1",
        window=_window("2026-01-01T00:00:00+08:00", "2026-01-02T00:00:00+08:00"),
    )
    _record_successful_collect_window(
        db_session,
        job_id="backfill-2",
        window=_window("2026-01-02T00:00:00+08:00", "2026-01-03T00:00:00+08:00"),
    )
    _login(client)
    client.put(
        "/api/v1/admin/sync/config",
        json={
            "history_start": "2026-01-01",
            "history_end": "2026-01-04",
            "history_chunk_days": 1,
            "rolling_days": 30,
            "interval_seconds": 3600,
        },
    )

    response = client.get("/api/v1/admin/sync")

    assert response.status_code == 200
    progress = response.json()["data"]["progress"]
    assert progress["total_windows"] == 3
    assert progress["completed_windows"] == 2
    assert progress["latest_completed_window"]["end"] == "2026-01-03T00:00:00+08:00"


def test_admin_can_queue_manual_sync_target(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, str]] = []

    def fake_manual_sync_job(**kwargs):
        calls.append(
            {
                "job_id": kwargs["job_id"],
                "target": kwargs["target"],
                "start": kwargs["start"].isoformat(),
                "end": kwargs["end"].isoformat(),
            }
        )

    monkeypatch.setattr(admin_routes, "run_manual_sync_job", fake_manual_sync_job)
    _login(client)

    response = client.post(
        "/api/v1/admin/sync/run",
        json={"target": "orders", "days": 7},
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["target"] == "orders"
    assert payload["job_id"].startswith("manual-orders-")
    assert calls[0]["job_id"] == payload["job_id"]
    assert calls[0]["target"] == "orders"
