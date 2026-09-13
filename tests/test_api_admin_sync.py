from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from dy_api.main import create_app  # noqa: E402
from dy_api.routes import admin as admin_routes  # noqa: E402
from dy_api.routes._data import get_session_dependency  # noqa: E402
from apps.worker.collectors.types import CollectionWindow  # noqa: E402
from apps.worker.repositories import finish_job_run, queue_job_run, start_job_run  # noqa: E402
from dy_api.models import (  # noqa: E402
    ComponentHeartbeat,
    DataQualityIssue,
    DimSkuProductRule,
    JobRun,
    SkuProductSyncHistory,
)


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


def test_admin_sync_exposes_login_recovery_reason(client: TestClient, db_session: Session):
    start_job_run(db_session, "expired-browser", "backend_aweme_export")
    finish_job_run(
        db_session, "expired-browser", status="failed", failed_count=1,
        error_message="douyin_backend_login_required",
    )
    db_session.commit()
    _login(client)
    response = client.get("/api/v1/admin/sync")
    assert response.status_code == 200
    failure = response.json()["data"]["worker_status"]["latest_failure"]
    assert failure["job_id"] == "expired-browser"
    assert failure["error_message"] == "douyin_backend_login_required"


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


def test_priority_mode_reports_calendar_schedule_and_published_daily_coverage(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORKER_SCHEDULER_MODE", "priority_daily")
    _login(client)
    response = client.put("/api/v1/admin/sync/config", json={
        "auto_sync_enabled": False, "history_start": "2026-09-01",
        "history_end": "2026-09-10", "history_chunk_days": 3,
    })
    assert response.status_code == 200
    job = start_job_run(db_session, "priority-published", "range_sync", metadata_json={"target": "all"})
    job.job_kind = "range_sync"
    job.config_version = "priority-daily-v1"
    job.window_start = datetime.fromisoformat("2026-09-09T00:00:00+08:00").astimezone(timezone.utc)
    job.window_end = datetime.fromisoformat("2026-09-10T00:00:00+08:00").astimezone(timezone.utc)
    finish_job_run(db_session, job.job_id, status="success")
    db_session.commit()
    response = client.get("/api/v1/admin/sync")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["config"]["auto_sync_enabled"] is False  # legacy setting is preserved
    assert data["schedule"]["auto_sync_enabled"] is True
    assert data["worker_status"]["mode"] == "priority_daily"
    assert data["worker_status"]["auto_sync_enabled"] is True
    assert data["progress"]["total_windows"] == 9
    assert data["progress"]["completed_windows"] == 1
    next_due = datetime.fromisoformat(data["schedule"]["next_scheduled_sync_at"])
    assert next_due.astimezone(admin_routes.SHANGHAI_TZ).hour == 2


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


def test_admin_sync_exposes_worker_runtime_status(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORKER_MODE", "collect_and_settle")
    monkeypatch.setenv("WORKER_RUN_ON_START", "false")
    monkeypatch.setenv("WORKER_RUN_ONCE", "true")
    monkeypatch.setenv("WORKER_CHUNK_MAX_ATTEMPTS", "4")
    start_job_run(
        db_session,
        "running-window",
        "collect_and_settle",
        metadata_json={
            "source_window": _window(
                "2026-06-12T00:00:00+08:00",
                "2026-06-13T00:00:00+08:00",
            ).as_metadata(),
            "phases": {},
        },
        started_at=datetime(2026, 6, 12, 16, 0, tzinfo=timezone.utc),
    )
    _record_successful_collect_window(
        db_session,
        job_id="successful-window",
        window=_window("2026-06-13T00:00:00+08:00", "2026-06-14T00:00:00+08:00"),
    )
    start_job_run(
        db_session,
        "failed-window",
        "collect_and_settle",
        metadata_json={
            "source_window": _window(
                "2026-06-14T00:00:00+08:00",
                "2026-06-15T00:00:00+08:00",
            ).as_metadata(),
            "phases": {},
        },
        started_at=datetime(2026, 6, 14, 16, 0, tzinfo=timezone.utc),
    )
    finish_job_run(
        db_session,
        "failed-window",
        status="failed",
        failed_count=1,
        error_message="open api returned 0 rows",
        finished_at=datetime(2026, 6, 14, 16, 10, tzinfo=timezone.utc),
    )
    db_session.commit()
    _login(client)
    client.put(
        "/api/v1/admin/sync/config",
        json={
            "rolling_days": 30,
            "history_chunk_days": 1,
            "interval_seconds": 1800,
            "auto_sync_enabled": True,
        },
    )

    response = client.get("/api/v1/admin/sync")

    assert response.status_code == 200
    worker_status = response.json()["data"]["worker_status"]
    assert worker_status["mode"] == "collect_and_settle"
    assert worker_status["auto_sync_enabled"] is True
    assert worker_status["rolling_days"] == 30
    assert worker_status["interval_seconds"] == 1800
    assert worker_status["run_on_start"] is False
    assert worker_status["run_once"] is True
    assert worker_status["chunk_max_attempts"] == 4
    assert worker_status["active_job"]["job_id"] == "running-window"
    assert worker_status["latest_success"]["job_id"] == "successful-window"
    assert worker_status["latest_failure"]["job_id"] == "failed-window"
    assert worker_status["latest_failure"]["error_message"] == "open api returned 0 rows"


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


def test_product_sync_admin_endpoints_require_login(client: TestClient) -> None:
    assert client.get("/api/v1/admin/product-sync-runs").status_code == 401
    assert (
        client.post(
            "/api/v1/admin/product-sync-runs",
            headers={"Idempotency-Key": "product-sync-key-0001"},
            json={"mode": "FULL", "reason": "首次全量同步"},
        ).status_code
        == 401
    )
    assert client.get("/api/v1/admin/product-sync-runs/missing").status_code == 401
    assert client.get("/api/v1/admin/sku-products/sku-1/sync-history").status_code == 401


def test_admin_can_trigger_product_sync_idempotently(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_product_sync_job(*, job_id: str) -> None:
        calls.append(job_id)

    monkeypatch.setattr(admin_routes, "run_product_sync_job", fake_product_sync_job)
    _login(client)
    headers = {"Idempotency-Key": "product-sync-key-0001"}
    request = {"mode": "FULL", "reason": "首次全量同步"}

    first = client.post("/api/v1/admin/product-sync-runs", headers=headers, json=request)
    second = client.post("/api/v1/admin/product-sync-runs", headers=headers, json=request)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["data"] == second.json()["data"]
    assert first.json()["data"]["status"] == "QUEUED"
    assert first.json()["data"]["mode"] == "FULL"
    assert calls == [first.json()["data"]["syncRunId"]]

    completed = db_session.get(JobRun, first.json()["data"]["syncRunId"])
    assert completed is not None
    completed.status = "success"
    completed.finished_at = datetime.now(timezone.utc)
    db_session.commit()

    completed_replay = client.post(
        "/api/v1/admin/product-sync-runs",
        headers=headers,
        json=request,
    )

    assert completed_replay.status_code == 200
    assert completed_replay.json()["data"] == first.json()["data"]


def test_product_sync_trigger_rejects_same_key_with_different_request(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(admin_routes, "run_product_sync_job", lambda **_: None)
    _login(client)
    headers = {"Idempotency-Key": "product-sync-key-0001"}
    first = client.post(
        "/api/v1/admin/product-sync-runs",
        headers=headers,
        json={"mode": "FULL", "reason": "首次全量同步"},
    )
    conflict = client.post(
        "/api/v1/admin/product-sync-runs",
        headers=headers,
        json={"mode": "INCREMENTAL", "reason": "改成增量"},
    )

    assert first.status_code == 200
    assert conflict.status_code == 409
    assert "Idempotency-Key" in conflict.json()["detail"]["message"]


def test_product_sync_trigger_requires_foundation_idempotency_key_length(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(admin_routes, "run_product_sync_job", lambda **_: None)
    _login(client)

    response = client.post(
        "/api/v1/admin/product-sync-runs",
        headers={"Idempotency-Key": "too-short"},
        json={"mode": "INCREMENTAL", "reason": "验证幂等键长度"},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "VALIDATION_FAILED"
    assert response.json()["detail"]["requestId"]


def test_product_sync_invalid_filter_uses_structured_contract_error(
    client: TestClient,
) -> None:
    _login(client)

    response = client.get(
        "/api/v1/admin/product-sync-runs",
        params={"status": "not-a-status"},
        headers={"X-Request-ID": "req-product-sync-invalid"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "VALIDATION_FAILED",
        "message": "Invalid product sync status",
        "errors": [],
        "requestId": "req-product-sync-invalid",
    }


def test_product_sync_trigger_rejects_a_second_active_run(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(admin_routes, "run_product_sync_job", lambda **_: None)
    _login(client)
    first = client.post(
        "/api/v1/admin/product-sync-runs",
        headers={"Idempotency-Key": "product-sync-key-0001"},
        json={"mode": "FULL", "reason": "首次全量同步"},
    )
    blocked = client.post(
        "/api/v1/admin/product-sync-runs",
        headers={"Idempotency-Key": "product-sync-key-0002"},
        json={"mode": "INCREMENTAL", "reason": "第二次同步"},
    )

    assert first.status_code == 200
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "PRODUCT_SYNC_ALREADY_ACTIVE"
    assert blocked.json()["detail"]["message"] == "A product sync run is already queued or running"


def test_product_sync_active_slot_is_protected_by_database_constraint(
    db_session: Session,
) -> None:
    queue_job_run(
        db_session,
        "product-sync-db-guard-1",
        "product_sync",
        metadata_json={"mode": "FULL"},
    )
    db_session.flush()
    db_session.add(
        JobRun(
            job_id="product-sync-db-guard-2",
            job_name="product_sync",
            status="queued",
            metadata_json={"mode": "INCREMENTAL"},
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_product_sync_idempotency_key_is_unique_after_run_completion(
    db_session: Session,
) -> None:
    first = queue_job_run(
        db_session,
        "product-sync-idempotency-guard-1",
        "product_sync",
        metadata_json={"mode": "FULL"},
    )
    first.idempotency_key_hash = "a" * 64
    first.status = "success"
    db_session.flush()

    second = queue_job_run(
        db_session,
        "product-sync-idempotency-guard-2",
        "product_sync",
        metadata_json={"mode": "FULL"},
    )
    second.idempotency_key_hash = "a" * 64

    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_product_sync_active_slot_race_returns_stable_conflict(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def collide(*_args, **_kwargs):
        raise IntegrityError("active slot", {}, Exception("unique conflict"))

    monkeypatch.setattr(admin_routes, "queue_job_run", collide)
    no_raise_client = TestClient(client.app, raise_server_exceptions=False)
    _login(no_raise_client)

    response = no_raise_client.post(
        "/api/v1/admin/product-sync-runs",
        headers={"Idempotency-Key": "product-sync-race-key-0001"},
        json={"mode": "FULL", "reason": "模拟并发抢占"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "PRODUCT_SYNC_ALREADY_ACTIVE"


def test_product_sync_active_slot_race_replays_same_committed_request(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    winner = JobRun(
        job_id="product-sync-race-winner",
        job_name="product_sync",
        status="queued",
        metadata_json={"mode": "FULL"},
    )

    def collide(*_args, **_kwargs):
        raise IntegrityError("active slot", {}, Exception("unique conflict"))

    lookup_count = 0

    def find_winner(_session, key_hash: str):
        nonlocal lookup_count
        lookup_count += 1
        if lookup_count == 1:
            return None
        winner.metadata_json = {
            "mode": "FULL",
            "idempotency_key_hash": key_hash,
            "request_payload_sha256": admin_routes._canonical_payload_sha256(
                {"mode": "FULL", "reason": "模拟同请求并发抢占"}
            ),
        }
        return winner

    monkeypatch.setattr(admin_routes, "queue_job_run", collide)
    monkeypatch.setattr(
        admin_routes,
        "_find_product_sync_job_by_idempotency_hash",
        find_winner,
    )
    no_raise_client = TestClient(client.app, raise_server_exceptions=False)
    _login(no_raise_client)

    response = no_raise_client.post(
        "/api/v1/admin/product-sync-runs",
        headers={"Idempotency-Key": "product-sync-race-key-0002"},
        json={"mode": "FULL", "reason": "模拟同请求并发抢占"},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "syncRunId": "product-sync-race-winner",
        "mode": "FULL",
        "status": "QUEUED",
    }
    assert lookup_count == 2


def test_product_sync_lists_use_foundation_default_page_size(
    client: TestClient,
) -> None:
    _login(client)

    response = client.get("/api/v1/admin/product-sync-runs")

    assert response.status_code == 200
    assert response.json()["data"]["pageSize"] == 20


def test_admin_product_sync_list_and_detail_hide_cursor_and_raw_payload(
    client: TestClient,
    db_session: Session,
) -> None:
    job = queue_job_run(
        db_session,
        "product-sync-existing",
        "product_sync",
        metadata_json={
            "mode": "INCREMENTAL",
            "observed_count": 2,
            "inserted_count": 1,
            "updated_count": 1,
            "unchanged_count": 0,
            "phase_counts": {"fetch": 2, "validate": 2, "snapshot": 2, "current": 2},
            "next_cursor_masked": "sha256:abc123",
            "error_code": None,
            "retryable": True,
        },
    )
    job.status = "success"
    job.success_count = 2
    job.finished_at = datetime(2026, 7, 20, 9, 0, tzinfo=timezone.utc)
    db_session.add_all(
        [
            DimSkuProductRule(
                sku_id="sku-1",
                sku_name="商品一",
                product_scope="人工范围",
                product_type="人工类型",
                sync_run_id=job.job_id,
                last_synced_at=datetime(2026, 7, 20, 8, 59, tzinfo=timezone.utc),
            ),
            SkuProductSyncHistory(
                snapshot_id="snapshot-1",
                sync_run_id=job.job_id,
                sku_id="sku-1",
                sku_name="商品一",
                payload_sha256="a" * 64,
                observed_at=datetime(2026, 7, 20, 8, 58, tzinfo=timezone.utc),
                raw_payload={"secret": "must-not-leak"},
            ),
            DataQualityIssue(
                issue_id="dqi-product-1",
                issue_type="product_sync_unknown_status",
                message="未知状态",
                source_run_id=job.job_id,
            ),
        ]
    )
    db_session.commit()
    _login(client)

    listing = client.get(
        "/api/v1/admin/product-sync-runs",
        params={"page": 1, "pageSize": 20, "mode": "INCREMENTAL"},
    )
    detail = client.get(f"/api/v1/admin/product-sync-runs/{job.job_id}")

    assert listing.status_code == 200
    assert listing.json()["data"]["total"] == 1
    assert listing.json()["data"]["page"] == 1
    assert listing.json()["data"]["pageSize"] == 20
    assert "pagination" not in listing.json()["data"]
    assert listing.json()["meta"]["generatedAt"]
    assert listing.json()["meta"]["requestId"]
    assert "generated_at" not in listing.json()["meta"]
    item = listing.json()["data"]["list"][0]
    assert item["syncRunId"] == job.job_id
    assert item["status"] == "SUCCESS"
    assert item["nextCursorMasked"] == "sha256:abc123"
    assert "secret" not in str(listing.json())
    assert detail.status_code == 200
    assert detail.json()["meta"]["generatedAt"]
    assert detail.json()["meta"]["requestId"]
    detail_data = detail.json()["data"]
    assert detail_data["run"]["syncRunId"] == job.job_id
    assert detail_data["phaseCounts"]["fetch"] == 2
    assert detail_data["affectedSkuSample"] == ["sku-1"]
    assert detail_data["dataQualityIssueCount"] == 1
    assert detail_data["retryable"] is True
    assert "must-not-leak" not in str(detail.json())


def test_admin_can_page_sku_product_sync_history_without_raw_payload(
    client: TestClient,
    db_session: Session,
) -> None:
    db_session.add_all(
        [
            SkuProductSyncHistory(
                snapshot_id="snapshot-old",
                sync_run_id="product-sync-old",
                sku_id="sku-1",
                sku_name="旧名称",
                product_status_raw="online",
                product_status_normalized="ACTIVE",
                payload_sha256="a" * 64,
                observed_at=datetime(2026, 7, 19, 8, 0, tzinfo=timezone.utc),
                raw_payload={"cookie": "must-not-leak"},
            ),
            SkuProductSyncHistory(
                snapshot_id="snapshot-new",
                sync_run_id="product-sync-new",
                sku_id="sku-1",
                sku_name="新名称",
                product_status_raw="offline",
                product_status_normalized="INACTIVE",
                payload_sha256="b" * 64,
                observed_at=datetime(2026, 7, 20, 8, 0, tzinfo=timezone.utc),
                raw_payload={"token": "must-not-leak"},
            ),
        ]
    )
    db_session.commit()
    _login(client)

    response = client.get(
        "/api/v1/admin/sku-products/sku-1/sync-history",
        params={"page": 1, "pageSize": 1},
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["total"] == 2
    assert payload["pageSize"] == 1
    assert payload["list"][0]["snapshotId"] == "snapshot-new"
    assert payload["list"][0]["productStatus"] == "INACTIVE"
    assert "raw_payload" not in str(response.json())
    assert "must-not-leak" not in str(response.json())


def _resource_heartbeat(
    session: Session,
    *,
    state: str = "normal",
    last_heartbeat_at: datetime | None = None,
    sampled_at: datetime | None = None,
    allow_daily: bool = True,
    allow_history: bool = True,
    reasons: list[str] | None = None,
    guard_overrides: dict[str, object] | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    guard_payload: dict[str, object] = {
        "state": state,
        "reasons": reasons or [],
        "allow_daily": allow_daily,
        "allow_history": allow_history,
        "since": (now - timedelta(minutes=2)).isoformat(),
        "duration_seconds": 120,
        "recovery_condition": "连续稳定 180 秒",
        "sampled_at": (sampled_at or now).isoformat(),
        "host_available_bytes": 3 * 1024**3,
        "cgroup_used_ratio": 0.62,
        "swap_used_bytes": 553 * 1024**2,
        "swap_activity_bytes_per_second": 32 * 1024**2,
    }
    guard_payload.update(guard_overrides or {})
    session.add(
        ComponentHeartbeat(
            component_instance_id="worker-resource-monitor-test",
            component_type="worker",
            status="healthy",
            started_at=now - timedelta(minutes=5),
            last_heartbeat_at=last_heartbeat_at or now,
            activity_json={
                "resource_guard": guard_payload,
            },
            queue_summary_json={},
        )
    )
    session.commit()


def _priority_job(
    job_id: str,
    job_kind: str,
    status: str,
    *,
    started_at: datetime,
    window_start: datetime,
    window_end: datetime,
    parent_job_id: str | None = None,
    business_date=None,
    priority_purpose: str = "daily_required",
) -> JobRun:
    return JobRun(
        job_id=job_id,
        job_name=job_kind,
        job_kind=job_kind,
        parent_job_id=parent_job_id,
        execution_slot="heavy_sync" if job_kind != "range_sync" else None,
        status=status,
        started_at=started_at,
        finished_at=started_at + timedelta(minutes=5) if status == "success" else None,
        metadata_json={
            "target": "all",
            "priority_purpose": priority_purpose,
        },
        data_source="douyin",
        config_version="priority-daily-v1",
        business_date=business_date if job_kind == "date_sync" else None,
        window_start=window_start,
        window_end=window_end,
    )


def test_admin_sync_exposes_fresh_worker_resource_guard(client: TestClient, db_session: Session):
    _resource_heartbeat(db_session)
    _login(client)

    response = client.get("/api/v1/admin/sync")

    assert response.status_code == 200
    guard = response.json()["data"]["resource_guard"]
    assert guard["state"] == "normal"
    assert guard["allow_daily"] is True
    assert guard["allow_history"] is True
    assert guard["duration_seconds"] == 120
    assert guard["host_available_bytes"] == 3 * 1024**3
    assert guard["cgroup_used_ratio"] == 0.62
    assert guard["swap_activity_bytes_per_second"] == 32 * 1024**2


def test_admin_sync_exposes_protected_worker_resource_guard(
    client: TestClient,
    db_session: Session,
):
    _resource_heartbeat(
        db_session,
        state="protected",
        allow_daily=False,
        allow_history=False,
        reasons=["host_available_low", "unknown_pressure_code"],
        guard_overrides={"cgroup_used_ratio": 1.2},
    )
    _login(client)

    response = client.get("/api/v1/admin/sync")

    assert response.status_code == 200
    guard = response.json()["data"]["resource_guard"]
    assert guard["state"] == "protected"
    assert guard["allow_daily"] is False
    assert guard["allow_history"] is False
    assert guard["reasons"] == ["host_available_low", "unknown_pressure_code"]
    assert guard["cgroup_used_ratio"] == 1.2


def test_admin_sync_fails_closed_for_missing_or_stale_resource_guard(
    client: TestClient,
    db_session: Session,
):
    _login(client)
    missing = client.get("/api/v1/admin/sync")
    assert missing.status_code == 200
    missing_guard = missing.json()["data"]["resource_guard"]
    assert missing_guard["state"] == "unknown"
    assert missing_guard["allow_daily"] is False
    assert missing_guard["allow_history"] is False
    assert "resource_guard_heartbeat_missing" in missing_guard["reasons"]

    _resource_heartbeat(
        db_session,
        last_heartbeat_at=datetime.now(timezone.utc) - timedelta(seconds=31),
    )
    stale = client.get("/api/v1/admin/sync")
    assert stale.status_code == 200
    stale_guard = stale.json()["data"]["resource_guard"]
    assert stale_guard["state"] == "unknown"
    assert stale_guard["allow_daily"] is False
    assert stale_guard["allow_history"] is False
    assert "resource_guard_heartbeat_stale" in stale_guard["reasons"]


def test_admin_sync_fails_closed_for_stale_sample_and_invalid_resource_state(
    client: TestClient,
    db_session: Session,
):
    now = datetime.now(timezone.utc)
    _resource_heartbeat(
        db_session,
        sampled_at=now - timedelta(seconds=31),
    )
    _login(client)

    stale_sample = client.get("/api/v1/admin/sync")

    assert stale_sample.status_code == 200
    stale_guard = stale_sample.json()["data"]["resource_guard"]
    assert stale_guard["state"] == "unknown"
    assert stale_guard["allow_daily"] is False
    assert "resource_guard_sampled_at_stale" in stale_guard["reasons"]

    db_session.query(ComponentHeartbeat).delete()
    db_session.commit()
    _resource_heartbeat(
        db_session,
        state="unexpected_state",
        allow_daily=True,
        allow_history=True,
        guard_overrides={
            "duration_seconds": "NaN",
            "cgroup_used_ratio": "Infinity",
            "swap_activity_bytes_per_second": "Infinity",
        },
    )
    invalid_state = client.get("/api/v1/admin/sync")

    assert invalid_state.status_code == 200
    invalid_guard = invalid_state.json()["data"]["resource_guard"]
    assert invalid_guard["state"] == "unknown"
    assert invalid_guard["allow_daily"] is False
    assert invalid_guard["allow_history"] is False
    assert "resource_guard_state_invalid" in invalid_guard["reasons"]
    assert invalid_guard["duration_seconds"] == 0
    assert invalid_guard["cgroup_used_ratio"] is None
    assert invalid_guard["swap_activity_bytes_per_second"] is None


def test_admin_sync_reports_priority_daily_freshness_from_job_runs(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("WORKER_SCHEDULER_MODE", "priority_daily")
    local_now = datetime.now(admin_routes.SHANGHAI_TZ)
    business_date = local_now.date() - timedelta(days=1 if local_now.hour >= 2 else 2)
    window_start = datetime(
        business_date.year,
        business_date.month,
        business_date.day,
        tzinfo=admin_routes.SHANGHAI_TZ,
    )
    window_end = window_start + timedelta(days=1)
    started_at = window_start.astimezone(timezone.utc)
    jobs = [
        JobRun(
            job_id="freshness-range",
            job_name="range_sync",
            job_kind="range_sync",
            status="success",
            started_at=started_at,
            finished_at=started_at + timedelta(minutes=20),
            metadata_json={"target": "all"},
            data_source="douyin",
            config_version="priority-daily-v1",
            window_start=window_start,
            window_end=window_end,
        ),
        JobRun(
            job_id="freshness-parent",
            job_name="parent_sync",
            job_kind="parent_sync",
            parent_job_id="freshness-range",
            execution_slot="heavy_sync",
            status="success",
            started_at=started_at,
            finished_at=started_at + timedelta(minutes=10),
            metadata_json={"target": "all"},
            data_source="douyin",
            config_version="priority-daily-v1",
            window_start=window_start,
            window_end=window_end,
        ),
        JobRun(
            job_id="freshness-date",
            job_name="date_sync",
            job_kind="date_sync",
            parent_job_id="freshness-range",
            execution_slot="heavy_sync",
            business_date=business_date,
            status="success",
            started_at=started_at,
            finished_at=started_at + timedelta(minutes=15),
            metadata_json={"target": "all"},
            data_source="douyin",
            config_version="priority-daily-v1",
            window_start=window_start,
            window_end=window_end,
        ),
        JobRun(
            job_id="freshness-finalize",
            job_name="finalize",
            job_kind="finalize",
            parent_job_id="freshness-range",
            execution_slot="heavy_sync",
            status="success",
            started_at=started_at,
            finished_at=started_at + timedelta(minutes=20),
            metadata_json={"target": "all"},
            data_source="douyin",
            config_version="priority-daily-v1",
            window_start=window_start,
            window_end=window_end,
        ),
    ]
    db_session.add_all(jobs)
    db_session.commit()
    _login(client)

    response = client.get("/api/v1/admin/sync")

    assert response.status_code == 200
    freshness = response.json()["data"]["sync_freshness"]
    assert freshness["latest_successful_sync_job_id"] == "freshness-range"
    assert freshness["latest_successful_sync_business_date"] == business_date.isoformat()
    assert freshness["latest_successful_sync_window_start"] is not None
    assert freshness["latest_successful_sync_window_end"] is not None
    assert freshness["latest_completed_business_date"] == business_date.isoformat()
    assert freshness["daily_batch"]["business_date"] == business_date.isoformat()
    assert freshness["daily_batch"]["status"] == "success"
    assert freshness["daily_batch"]["is_overdue"] is False
    assert freshness["daily_batch"]["deadline_local_time"] == "06:00"
    assert freshness["daily_batch"]["deadline_configurable"] is True

    # Collection completion cannot advance freshness before its range publishes.
    db_session.add_all([
        JobRun(
            job_id="unpublished-range", job_name="range_sync", job_kind="range_sync",
            status="running", started_at=started_at + timedelta(days=1),
            metadata_json={"target": "all"}, data_source="douyin",
            config_version="priority-daily-v1",
            window_start=window_end, window_end=window_end + timedelta(days=1),
        ),
        JobRun(
            job_id="unpublished-date", job_name="date_sync", job_kind="date_sync",
            parent_job_id="unpublished-range", status="success",
            business_date=business_date + timedelta(days=1),
            started_at=started_at + timedelta(days=1),
            finished_at=started_at + timedelta(days=1, minutes=15),
            metadata_json={"target": "all"}, data_source="douyin",
            config_version="priority-daily-v1",
            window_start=window_end, window_end=window_end + timedelta(days=1),
        ),
    ])
    db_session.commit()
    freshness = client.get("/api/v1/admin/sync").json()["data"]["sync_freshness"]
    assert freshness["latest_completed_business_date"] == business_date.isoformat()


def test_admin_sync_uses_newest_formal_daily_root_and_ignores_old_cancelled_plan(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("WORKER_SCHEDULER_MODE", "priority_daily")
    local_now = datetime.now(admin_routes.SHANGHAI_TZ)
    business_date = local_now.date() - timedelta(days=1 if local_now.hour >= 2 else 2)
    window_start = datetime(
        business_date.year,
        business_date.month,
        business_date.day,
        tzinfo=admin_routes.SHANGHAI_TZ,
    )
    window_end = window_start + timedelta(days=1)
    old_started_at = window_start.astimezone(timezone.utc)
    new_started_at = old_started_at + timedelta(hours=1)
    old_root = _priority_job(
        "old-daily-root",
        "range_sync",
        "cancelled",
        started_at=old_started_at,
        window_start=window_start,
        window_end=window_end,
    )
    old_child = _priority_job(
        "old-daily-date",
        "date_sync",
        "cancelled",
        started_at=old_started_at,
        window_start=window_start,
        window_end=window_end,
        parent_job_id=old_root.job_id,
        business_date=business_date,
    )
    new_root = _priority_job(
        "new-daily-root",
        "range_sync",
        "success",
        started_at=new_started_at,
        window_start=window_start,
        window_end=window_end,
    )
    new_parent = _priority_job(
        "new-daily-parent",
        "parent_sync",
        "success",
        started_at=new_started_at,
        window_start=window_start,
        window_end=window_end,
        parent_job_id=new_root.job_id,
    )
    new_date = _priority_job(
        "new-daily-date",
        "date_sync",
        "success",
        started_at=new_started_at,
        window_start=window_start,
        window_end=window_end,
        parent_job_id=new_root.job_id,
        business_date=business_date,
    )
    new_finalize = _priority_job(
        "new-daily-finalize",
        "finalize",
        "success",
        started_at=new_started_at,
        window_start=window_start,
        window_end=window_end,
        parent_job_id=new_root.job_id,
    )
    db_session.add_all([old_root, old_child, new_root, new_parent, new_date, new_finalize])
    db_session.commit()
    _login(client)

    response = client.get("/api/v1/admin/sync")

    assert response.status_code == 200
    daily_batch = response.json()["data"]["sync_freshness"]["daily_batch"]
    assert daily_batch["status"] == "success"
    assert daily_batch["job_id"] == new_root.job_id


def test_admin_sync_does_not_mark_daily_batch_success_without_required_child_kind(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("WORKER_SCHEDULER_MODE", "priority_daily")
    local_now = datetime.now(admin_routes.SHANGHAI_TZ)
    business_date = local_now.date() - timedelta(days=1 if local_now.hour >= 2 else 2)
    window_start = datetime(
        business_date.year,
        business_date.month,
        business_date.day,
        tzinfo=admin_routes.SHANGHAI_TZ,
    )
    window_end = window_start + timedelta(days=1)
    started_at = window_start.astimezone(timezone.utc)
    root = _priority_job(
        "missing-parent-root",
        "range_sync",
        "success",
        started_at=started_at,
        window_start=window_start,
        window_end=window_end,
    )
    date_job = _priority_job(
        "missing-parent-date",
        "date_sync",
        "success",
        started_at=started_at,
        window_start=window_start,
        window_end=window_end,
        parent_job_id=root.job_id,
        business_date=business_date,
    )
    finalize = _priority_job(
        "missing-parent-finalize",
        "finalize",
        "success",
        started_at=started_at,
        window_start=window_start,
        window_end=window_end,
        parent_job_id=root.job_id,
    )
    db_session.add_all([root, date_job, finalize])
    db_session.commit()
    _login(client)

    response = client.get("/api/v1/admin/sync")

    assert response.status_code == 200
    daily_batch = response.json()["data"]["sync_freshness"]["daily_batch"]
    assert daily_batch["status"] == "incomplete"
    assert "parent_sync" in daily_batch["incomplete_task_types"]
