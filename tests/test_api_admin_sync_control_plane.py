from __future__ import annotations

import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from apps.api.dy_api.models import (  # noqa: E402
    ComponentHeartbeat,
    JobAttempt,
    JobEvent,
    JobRun,
    JobStageRun,
    OpsCommand,
    User,
)
from dy_api.access_control import (  # noqa: E402
    effective_page_keys,
    required_page_key_for_api_path,
    role_default_page_keys,
)
from dy_api.auth import hash_password_pbkdf2  # noqa: E402
from dy_api.main import create_app  # noqa: E402
from dy_api.routes._data import get_session_dependency  # noqa: E402


@pytest.fixture()
def control_client(monkeypatch: pytest.MonkeyPatch, db_session: Session) -> TestClient:
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    monkeypatch.setenv("DY_SUPER_ADMIN_USERNAME", "system-admin")
    monkeypatch.setenv("DY_TEST_ADMIN_PASSWORD", "test-password")
    monkeypatch.setenv("DY_SESSION_COOKIE_SECURE", "false")
    db_session.add(
        User(
            user_id="ordinary-admin",
            username="ordinary-admin",
            display_name="Ordinary Admin",
            role="admin",
            status="active",
            is_initialized=True,
            password_hash=hash_password_pbkdf2("secret"),
            store_scope_mode="all",
        )
    )
    db_session.commit()
    app = create_app()

    def override_session():
        yield db_session

    app.dependency_overrides[get_session_dependency] = override_session
    return TestClient(app)


def _login(client: TestClient, username: str, password: str = "secret") -> None:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200


def _seed_observability(session: Session) -> None:
    now = datetime.now(UTC)
    parent = JobRun(
        job_id="range-observe",
        job_name="range_sync",
        job_kind="range_sync",
        status="running",
        started_at=now - timedelta(minutes=5),
        metadata_json={"target": "settlement"},
        progress_current=2,
        progress_total=4,
    )
    child = JobRun(
        job_id="date-observe",
        job_name="date_sync",
        job_kind="date_sync",
        parent_job_id=parent.job_id,
        execution_slot="heavy_sync",
        business_date=date(2026, 8, 8),
        data_source="douyin",
        config_version="v1",
        window_start=now - timedelta(days=1),
        window_end=now,
        current_stage="collect",
        status="running",
        started_at=now - timedelta(minutes=2),
        attempt_count=1,
        max_attempts=3,
        progress_current=25,
        progress_total=100,
        rows_read=25,
        rows_written=10,
        rows_affected=8,
        rss_peak_bytes=64 * 1024 * 1024,
        heartbeat_at=now,
        metadata_json={},
    )
    session.add_all([parent, child])
    session.flush()
    component = ComponentHeartbeat(
        component_instance_id="worker-observe",
        component_type="worker",
        status="healthy",
        started_at=now - timedelta(hours=1),
        last_heartbeat_at=now,
        rss_bytes=32 * 1024 * 1024,
        rss_peak_bytes=64 * 1024 * 1024,
        memory_limit_bytes=2 * 1024 * 1024 * 1024,
        cpu_percent=12.5,
        queue_depth=1,
        activity_json={"summary": "collecting", "token": "must-not-leak"},
        queue_summary_json={"pending": 1},
    )
    stale = ComponentHeartbeat(
        component_instance_id="browser-stale",
        component_type="browser",
        status="healthy",
        last_heartbeat_at=now - timedelta(minutes=10),
        activity_json={},
        queue_summary_json={},
    )
    session.add_all([component, stale])
    session.flush()
    stage = JobStageRun(
        stage_run_id="stage-observe",
        job_id=child.job_id,
        stage_name="collect",
        status="running",
        checkpoint_json={"cursor": 25},
        lease_epoch=1,
        started_at=child.started_at,
        created_at=child.started_at,
        updated_at=now,
    )
    session.add(stage)
    session.flush()
    attempt = JobAttempt(
        attempt_id="attempt-observe",
        job_id=child.job_id,
        stage_run_id=stage.stage_run_id,
        attempt_number=1,
        lease_epoch=1,
        component_type="worker",
        component_instance_id=component.component_instance_id,
        started_at=child.started_at,
        rss_peak_bytes=64 * 1024 * 1024,
        error_summary="Authorization: Bearer must-not-leak",
    )
    session.add(attempt)
    session.flush()
    session.add(
        JobEvent(
            event_id="event-observe",
            job_id=child.job_id,
            stage_run_id=stage.stage_run_id,
            attempt_id=attempt.attempt_id,
            event_type="stage_progress",
            actor_type="worker",
            actor_id="worker-observe",
            reason="C:/Users/operator/private.log",
            payload_json={"cookie": "must-not-leak", "progress": 25},
            occurred_at=now,
        )
    )
    session.commit()


def test_d10_is_fixed_to_highest_admin_and_control_api_rechecks_role(
    control_client: TestClient, db_session: Session
) -> None:
    admin = db_session.scalar(select(User).where(User.username == "ordinary-admin"))
    assert admin is not None
    assert "D10" not in role_default_page_keys(db_session, "admin")
    assert "D10" not in effective_page_keys(db_session, admin)
    assert required_page_key_for_api_path("/api/v1/admin/operations/overview") == "D10"

    _login(control_client, "ordinary-admin")
    assert control_client.get("/api/v1/admin/operations/overview").status_code == 403
    control_client.post("/api/v1/auth/logout")

    _login(control_client, "system-admin", "test-password")
    denied = control_client.put(
        f"/api/v1/admin/accounts/{admin.user_id}/page-permissions",
        json={"extra_allow": ["D10"], "extra_deny": []},
    )
    assert denied.status_code == 422


def test_overview_and_job_detail_are_factual_lost_aware_and_redacted(
    control_client: TestClient, db_session: Session
) -> None:
    _seed_observability(db_session)
    _login(control_client, "system-admin", "test-password")

    overview = control_client.get("/api/v1/admin/operations/overview")
    assert overview.status_code == 200
    data = overview.json()["data"]
    components = {row["component_type"]: row for row in data["components"]}
    assert components["worker"]["observed_status"] == "healthy"
    assert components["browser"]["observed_status"] == "lost"
    assert components["api"]["observed_status"] == "unknown"
    assert components["worker"]["allow_restart"] is True
    assert components["api"]["allow_restart"] is False
    assert "must-not-leak" not in str(data)

    detail = control_client.get("/api/v1/admin/operations/jobs/date-observe")
    assert detail.status_code == 200
    detail_data = detail.json()["data"]
    assert detail_data["job"]["current_stage"] == "collect"
    assert detail_data["eta"]["state"] == "available"
    assert detail_data["eta"]["remaining_seconds"] > 0
    assert len(detail_data["attempts"]) == 1
    assert len(detail_data["events"]) == 1
    assert "must-not-leak" not in str(detail_data)
    assert "C:/Users" not in str(detail_data)


def test_create_and_control_job_write_only_idempotent_audited_intents(
    control_client: TestClient, db_session: Session
) -> None:
    _login(control_client, "system-admin", "test-password")
    headers = {"Idempotency-Key": "create-range-20260808"}
    request = {
        "start": "2026-08-08",
        "end": "2026-08-09",
        "target": "settlement",
        "reason": "repair the missed day",
    }
    first = control_client.post("/api/v1/admin/operations/jobs", headers=headers, json=request)
    second = control_client.post("/api/v1/admin/operations/jobs", headers=headers, json=request)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["data"]["job_id"] == first.json()["data"]["job_id"]
    parent_id = first.json()["data"]["job_id"]

    pause_headers = {"Idempotency-Key": "pause-range-20260808"}
    paused = control_client.post(
        f"/api/v1/admin/operations/jobs/{parent_id}/pause",
        headers=pause_headers,
        json={"reason": "maintenance window"},
    )
    replay = control_client.post(
        f"/api/v1/admin/operations/jobs/{parent_id}/pause",
        headers=pause_headers,
        json={"reason": "maintenance window"},
    )
    assert paused.status_code == replay.status_code == 200

    resumed = control_client.post(
        f"/api/v1/admin/operations/jobs/{parent_id}/resume",
        headers={"Idempotency-Key": "resume-range-20260808"},
        json={"reason": "maintenance completed"},
    )
    assert resumed.status_code == 200
    db_session.expire_all()
    parent = db_session.get(JobRun, parent_id)
    assert parent is not None and parent.pause_after_stage_requested_at is None
    events = list(
        db_session.scalars(
            select(JobEvent).where(JobEvent.job_id == parent_id).order_by(JobEvent.occurred_at)
        )
    )
    assert [row.event_type for row in events].count("admin_pause_requested") == 1
    assert [row.event_type for row in events].count("admin_resume_requested") == 1
    assert all(row.actor_type == "user" for row in events)
    assert all(row.actor_id == "system-admin" for row in events)


def test_ops_command_is_allowlisted_idempotent_and_never_executes_docker(
    control_client: TestClient, db_session: Session
) -> None:
    _login(control_client, "system-admin", "test-password")
    headers = {"Idempotency-Key": "restart-worker-20260809"}
    payload = {
        "command_type": "restart",
        "target_component": "worker",
        "reason": "worker heartbeat is stale",
        "confirmed": True,
    }
    created = control_client.post(
        "/api/v1/admin/operations/commands", headers=headers, json=payload
    )
    replay = control_client.post(
        "/api/v1/admin/operations/commands", headers=headers, json=payload
    )
    assert created.status_code == replay.status_code == 200
    assert replay.json()["data"]["command_id"] == created.json()["data"]["command_id"]
    assert replay.json()["data"]["status"] == "pending"

    forbidden_target = control_client.post(
        "/api/v1/admin/operations/commands",
        headers={"Idempotency-Key": "restart-api-20260809"},
        json={**payload, "target_component": "api"},
    )
    arbitrary_parameter = control_client.post(
        "/api/v1/admin/operations/commands",
        headers={"Idempotency-Key": "restart-args-20260809"},
        json={**payload, "args": ["docker", "rm"]},
    )
    assert forbidden_target.status_code == 422
    assert arbitrary_parameter.status_code == 422
    assert db_session.scalar(select(OpsCommand).where(OpsCommand.command_id == created.json()["data"]["command_id"])) is not None
    assert len(list(db_session.scalars(select(OpsCommand)))) == 1
