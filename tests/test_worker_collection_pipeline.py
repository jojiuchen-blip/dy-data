from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.dy_api.models import Base
from apps.api.dy_api.models import JobRun
from apps.worker.backfill import iter_backfill_windows
from apps.worker.collectors.types import CollectionWindow, PhaseStats
from apps.worker.pipeline import build_douyin_client_from_env, run_collect_and_settle
from apps.worker import scheduler
from apps.worker.scheduler import resolve_worker_mode, run_browser_export_job, run_once


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
        include_browser_export=False,
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
            include_browser_export=False,
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
    assert resolve_worker_mode({"WORKER_MODE": "backfill"}) == "backfill"
    assert resolve_worker_mode({"WORKER_MODE": "browser_export_only"}) == "browser_export_only"


def test_browser_export_only_records_success_job(db_session: Session):
    calls: list[str] = []

    def runner(session: Session, source_run_id: str) -> PhaseStats:
        assert session.get(JobRun, source_run_id).status == "running"
        calls.append(source_run_id)
        return PhaseStats(name="backend_aweme_export", fetched=2, upserted=3)

    stats = run_browser_export_job(db_session, job_id="browser-export-1", runner=runner)

    assert calls == ["browser-export-1"]
    assert stats.success_count == 3
    job = db_session.get(JobRun, "browser-export-1")
    assert job is not None
    assert job.job_name == "backend_aweme_export"
    assert job.status == "success"
    assert job.success_count == 3
    assert job.failed_count == 0
    assert job.metadata_json["phases"]["backend_aweme_export"]["fetched"] == 2


def test_browser_export_only_failure_persists_when_run_once_rethrows(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    def failing_runner(session: Session, source_run_id: str) -> PhaseStats:
        assert session.get(JobRun, source_run_id).status == "running"
        raise RuntimeError("CDP endpoint unavailable")

    monkeypatch.setenv("WORKER_MODE", "browser_export_only")
    monkeypatch.setattr(scheduler, "get_session_factory", lambda: factory)
    monkeypatch.setattr(scheduler, "_run_backend_aweme_export", failing_runner)

    with pytest.raises(RuntimeError, match="CDP endpoint unavailable"):
        run_once()

    with factory() as session:
        job = session.scalar(select(JobRun).where(JobRun.job_name == "backend_aweme_export"))
        assert job is not None
        assert job.status == "failed"
        assert job.failed_count == 1
        assert job.error_message == "CDP endpoint unavailable"


def test_backfill_splits_windows_by_chunk_days():
    source = CollectionWindow(
        start=datetime.fromisoformat("2026-01-01T00:00:00+08:00"),
        end=datetime.fromisoformat("2026-01-03T12:00:00+08:00"),
        timezone_name="Asia/Shanghai",
    )

    chunks = list(iter_backfill_windows(source, chunk_days=1))

    assert [chunk.start.isoformat() for chunk in chunks] == [
        "2026-01-01T00:00:00+08:00",
        "2026-01-02T00:00:00+08:00",
        "2026-01-03T00:00:00+08:00",
    ]
    assert [chunk.end.isoformat() for chunk in chunks] == [
        "2026-01-02T00:00:00+08:00",
        "2026-01-03T00:00:00+08:00",
        "2026-01-03T12:00:00+08:00",
    ]


def test_fake_douyin_client_allows_offline_worker_smoke(monkeypatch):
    monkeypatch.setenv("DY_WORKER_FAKE_DOUYIN", "true")

    client = build_douyin_client_from_env()

    assert list(client.iter_orders(window().start, window().end)) == []
    assert client.query_shop_pois()["data"]["pois"] == []
    assert client.query_verify_records(window().start, window().end)["data"]["verify_records"] == []
    assert client.query_craftsman_bind_info()["data"]["openapi_merchat_craftsman_info"] == []


def test_run_collect_and_settle_runs_browser_export_before_settlement(db_session: Session):
    calls: list[str] = []

    def browser_export_runner(session: Session, source_run_id: str) -> PhaseStats:
        calls.append("browser_export")
        return PhaseStats(name="backend_aweme_export", fetched=1, upserted=2)

    def settlement_runner(session: Session, source_run_id: str) -> PhaseStats:
        calls.append("settlement")
        return PhaseStats(name="settlement", fetched=0, upserted=3)

    stats = run_collect_and_settle(
        db_session,
        client=object(),
        window=window(),
        job_id="collect-browser",
        collectors=[collector("orders", calls)],
        browser_export_runner=browser_export_runner,
        settlement_runner=settlement_runner,
    )

    assert calls == ["orders", "browser_export", "settlement"]
    assert stats.success_count == 6
    job = db_session.get(JobRun, "collect-browser")
    assert job is not None
    assert job.metadata_json["phases"]["backend_aweme_export"]["upserted"] == 2
