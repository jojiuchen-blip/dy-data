from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy.orm import Session

from apps.api.dy_api.models import JobRun
from apps.worker.collectors.types import CollectionWindow, PhaseStats
from apps.worker.pipeline import build_douyin_client_from_env, run_collect_and_settle
from apps.worker.scheduler import resolve_worker_mode


def window() -> CollectionWindow:
    return CollectionWindow(
        start=datetime.fromisoformat("2026-01-01T00:00:00+08:00"),
        end=datetime.fromisoformat("2026-01-02T00:00:00+08:00"),
        timezone_name="Asia/Shanghai",
    )


def collector(name: str, calls: list[str]):
    def run(session: Session, client: object, source_window: CollectionWindow, source_run_id: str) -> PhaseStats:
        assert session.get(JobRun, source_run_id).status == "running"
        calls.append(name)
        return PhaseStats(name=name, fetched=1, upserted=1)

    return run


def test_run_collect_and_settle_records_success_job_and_phase_order(db_session: Session):
    calls: list[str] = []

    def settlement_runner(session: Session, source_run_id: str) -> PhaseStats:
        calls.append("settlement")
        return PhaseStats(name="settlement", fetched=0, upserted=3)

    stats = run_collect_and_settle(
        db_session,
        client=object(),
        window=window(),
        job_id="collect-1",
        collectors=[
            collector("shop_pois", calls),
            collector("aweme_bindings", calls),
            collector("orders", calls),
            collector("verify_records", calls),
        ],
        settlement_runner=settlement_runner,
    )

    assert calls == ["shop_pois", "aweme_bindings", "orders", "verify_records", "settlement"]
    assert stats.success_count == 7

    job = db_session.get(JobRun, "collect-1")
    assert job is not None
    assert job.status == "success"
    assert job.success_count == 7
    assert job.failed_count == 0
    assert job.metadata_json["phases"]["orders"]["upserted"] == 1
    assert job.metadata_json["source_window"]["timezone"] == "Asia/Shanghai"


def test_run_collect_and_settle_marks_failed_and_skips_settlement(db_session: Session):
    calls: list[str] = []

    def failing_collector(session: Session, client: object, source_window: CollectionWindow, source_run_id: str):
        calls.append("orders")
        raise RuntimeError("client_secret=secret-token failed")

    def settlement_runner(session: Session, source_run_id: str) -> PhaseStats:
        calls.append("settlement")
        return PhaseStats(name="settlement", upserted=1)

    with pytest.raises(RuntimeError):
        run_collect_and_settle(
            db_session,
            client=object(),
            window=window(),
            job_id="collect-fail",
            collectors=[failing_collector],
            settlement_runner=settlement_runner,
        )

    assert calls == ["orders"]
    job = db_session.get(JobRun, "collect-fail")
    assert job is not None
    assert job.status == "failed"
    assert job.failed_count == 1
    assert "secret-token" not in job.error_message
    assert "[redacted" in job.error_message


def test_scheduler_worker_mode_defaults_to_collect_and_settle():
    assert resolve_worker_mode({}) == "collect_and_settle"
    assert resolve_worker_mode({"WORKER_MODE": "settlement_only"}) == "settlement_only"


def test_fake_douyin_client_allows_offline_worker_smoke(monkeypatch):
    monkeypatch.setenv("DY_WORKER_FAKE_DOUYIN", "true")

    client = build_douyin_client_from_env()

    assert list(client.iter_orders(window().start, window().end)) == []
    assert client.query_shop_pois()["data"]["pois"] == []
    assert client.query_verify_records(window().start, window().end)["data"]["verify_records"] == []
    assert client.query_craftsman_bind_info()["data"]["openapi_merchat_craftsman_info"] == []
