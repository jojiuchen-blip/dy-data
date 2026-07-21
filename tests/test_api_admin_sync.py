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
