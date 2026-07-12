from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.dy_api.models import Base
from apps.api.dy_api.models import ClueCenterOrder, DimNonCommissionOwnerAccount, JobRun, SettlementOrderDetail
from apps.api.dy_api.rule_utils import normalize_owner_account_name
from apps.worker.backfill import iter_backfill_windows, run_backfill
from apps.worker.collectors.types import CollectionStats, CollectionWindow, PhaseStats
from apps.worker.pipeline import build_douyin_client_from_env, run_collect_and_settle
from apps.worker import scheduler
from apps.worker.scheduler import resolve_worker_mode, run_browser_export_job, run_once
from apps.worker.sync_config import save_sync_config
from apps.worker.repositories import (
    finish_job_run,
    queue_job_run,
    start_job_run,
    upsert_aweme_binding,
    upsert_order_coupon,
    upsert_raw_order,
    upsert_sku_product_rule,
    upsert_store,
    upsert_store_poi_mapping,
    upsert_verify_record,
)
from apps.worker.settlement import run_settlement_job


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


class FakeDefaultCollectionClient:
    def iter_orders(self, start: datetime, end: datetime):
        return iter(())

    def query_shop_pois(self, *, relation_type: int = 0, cursor: str | int | None = None):
        return {"data": {"pois": [], "has_more": False}}

    def query_craftsman_bind_info(self, *, cursor: str | int | None = None, size: int = 50):
        return {"data": {"openapi_merchat_craftsman_info": [], "has_more": False}}

    def query_verify_records(
        self,
        start: datetime,
        end: datetime,
        *,
        poi_id: str | None = None,
        page_size: int = 20,
        cursor: str | int | None = None,
    ):
        return {"data": {"verify_records": [], "has_more": False}}

    def query_clues(
        self,
        start: datetime,
        end: datetime,
        *,
        page: int,
        page_size: int,
    ):
        if page > 1:
            return {"data": {"clue_data": []}}
        return {
            "data": {
                "clue_data": [
                    {
                        "clue_id": "clue-1",
                        "create_time_detail": "2026-01-01 10:00:00",
                        "telephone": "13812345678",
                        "product_id": "sku-1",
                        "product_name": "Service Product",
                        "order_id": "order-1",
                        "order_status": "履约中",
                        "follow_life_account_id": "store-1",
                        "follow_life_account_name": "Store One",
                    }
                ]
            }
        }


def test_default_collect_and_settle_collects_clues_and_rebuilds_clue_center(
    db_session: Session,
):
    def settlement_runner(session: Session, source_run_id: str) -> PhaseStats:
        return PhaseStats(name="settlement", fetched=0, upserted=0)

    stats = run_collect_and_settle(
        db_session,
        client=FakeDefaultCollectionClient(),
        window=window(),
        job_id="collect-clues",
        include_browser_export=False,
        settlement_runner=settlement_runner,
    )

    phase_names = [phase.name for phase in stats.phases]
    assert "clues" in phase_names
    assert "clue_center_rebuild" in phase_names
    assert "clue_master_rebuild" in phase_names
    assert "store_score_snapshot" in phase_names

    order = db_session.get(ClueCenterOrder, "order-1")
    assert order is not None
    assert order.phone_plain == "13812345678"
    assert order.phone_masked == "138****5678"

    job = db_session.get(JobRun, "collect-clues")
    assert job is not None
    assert job.metadata_json["phases"]["clues"]["upserted"] == 1
    assert job.metadata_json["phases"]["clue_center_rebuild"]["upserted"] == 1
    assert job.metadata_json["phases"]["clue_master_rebuild"]["upserted"] == 1


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


def test_scheduler_auto_sync_enabled_reads_database_config(db_session: Session):
    save_sync_config(db_session, {"auto_sync_enabled": False})
    db_session.commit()
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False, future=True)

    assert scheduler._auto_sync_enabled(factory) is False


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


def test_queued_settlement_rebuild_applies_current_non_commission_rules(db_session: Session):
    from apps.worker.queued_jobs import process_queued_settlement_rebuilds

    upsert_store(db_session, "store-sale", "Sale Store")
    upsert_store(db_session, "store-verify", "Verify Store")
    upsert_store_poi_mapping(db_session, "store-verify", "poi-verify", mapping_source="fixture")
    upsert_aweme_binding(
        db_session,
        "store-sale:dy-sale:poi-sale",
        douyin_id="dy-sale",
        douyin_nickname="Official Seller",
        account_id="store-sale",
        account_name="Sale Store",
        poi_id="poi-sale",
        binding_status="认证成功",
    )
    upsert_sku_product_rule(
        db_session,
        "sku-service",
        "service",
        product_name="Service SKU",
        commission_rate=Decimal("0.1000"),
        is_service_product=True,
    )
    upsert_raw_order(
        db_session,
        "order-cross",
        order_status="paid",
        sku_id="sku-service",
        pay_time=datetime.fromisoformat("2026-06-01T10:00:00+08:00"),
        paid_amount_cent=10000,
        owner_account_name="Official Seller",
    )
    upsert_order_coupon(db_session, "coupon-cross", "order-cross", coupon_status="fulfilled")
    upsert_verify_record(
        db_session,
        "verify-cross",
        coupon_id="coupon-cross",
        verify_status="valid",
        verify_time=datetime.fromisoformat("2026-06-01T11:00:00+08:00"),
        poi_id="poi-verify",
        sku_id="sku-service",
        paid_amount_cent=10000,
    )
    run_settlement_job(db_session, job_id="initial-rebuild", source_run_id="initial-rebuild")
    before = db_session.get(SettlementOrderDetail, "coupon-cross")
    assert before is not None
    assert before.is_commissionable is True
    assert before.receivable_commission_cent == 1000

    db_session.merge(
        DimNonCommissionOwnerAccount(
            normalized_owner_account_name=normalize_owner_account_name("Official Seller"),
            owner_account_name="Official Seller",
            is_active=True,
        )
    )
    queue_job_run(
        db_session,
        "queued-admin-rules",
        "settlement_rebuild",
        metadata_json={"trigger": "admin_non_commission_owner_accounts"},
    )
    db_session.commit()

    result = process_queued_settlement_rebuilds(
        sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False, future=True)
    )

    db_session.expire_all()
    job = db_session.get(JobRun, "queued-admin-rules")
    assert result.processed_job_id == "queued-admin-rules"
    assert job is not None
    assert job.status == "success"
    detail = db_session.get(SettlementOrderDetail, "coupon-cross")
    assert detail is not None
    assert detail.source_run_id == "queued-admin-rules"
    assert detail.is_commissionable is False
    assert detail.commission_rate == Decimal("0.0000")
    assert detail.receivable_commission_cent == 0
    assert detail.payable_commission_cent == 0


def test_queued_settlement_rebuild_coalesces_older_jobs_after_latest_success(
    db_session: Session,
    monkeypatch,
):
    from apps.worker import queued_jobs

    queue_job_run(
        db_session,
        "queued-old",
        "settlement_rebuild",
        metadata_json={"trigger": "admin_sku_rules"},
        started_at=datetime.fromisoformat("2026-06-17T05:00:00+00:00"),
    )
    queue_job_run(
        db_session,
        "queued-new",
        "settlement_rebuild",
        metadata_json={"trigger": "admin_non_commission_owner_accounts"},
        started_at=datetime.fromisoformat("2026-06-17T05:30:00+00:00"),
    )
    db_session.commit()
    calls: list[tuple[str, str]] = []

    def fake_run_settlement_job(session: Session, *, job_id: str, source_run_id: str):
        calls.append((job_id, source_run_id))
        start_job_run(session, job_id, "settlement_rebuild", metadata_json={"source_run_id": source_run_id})
        finish_job_run(session, job_id, status="success", success_count=1)

    monkeypatch.setattr(queued_jobs, "run_settlement_job", fake_run_settlement_job)

    result = queued_jobs.process_queued_settlement_rebuilds(
        sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False, future=True)
    )

    db_session.expire_all()
    old_job = db_session.get(JobRun, "queued-old")
    new_job = db_session.get(JobRun, "queued-new")
    assert result.processed_job_id == "queued-new"
    assert result.superseded_job_ids == ("queued-old",)
    assert calls == [("queued-new", "queued-new")]
    assert old_job is not None
    assert old_job.status == "success"
    assert old_job.success_count == 0
    assert old_job.metadata_json["superseded_by"] == "queued-new"
    assert new_job is not None
    assert new_job.status == "success"
    assert new_job.success_count == 1


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


def test_backfill_skips_successful_completed_windows(db_session: Session):
    completed = CollectionWindow(
        start=datetime.fromisoformat("2026-01-01T00:00:00+08:00"),
        end=datetime.fromisoformat("2026-01-02T00:00:00+08:00"),
        timezone_name="Asia/Shanghai",
    )
    start_job_run(
        db_session,
        "previous-backfill",
        "collect_and_settle",
        metadata_json={
            "source_window": completed.as_metadata(),
            "phases": {"orders": {"name": "orders", "fetched": 1, "upserted": 1, "skipped": 0, "failed": 0}},
        },
    )
    finish_job_run(db_session, "previous-backfill", status="success", success_count=1)
    db_session.commit()

    calls: list[str] = []

    def runner(session: Session, *, window: CollectionWindow, job_id: str, include_browser_export: bool | None):
        calls.append(window.start.isoformat())
        stats = CollectionStats(run_id=job_id, source_window=window)
        stats.add_phase(PhaseStats(name="orders", upserted=1))
        return stats

    run_backfill(
        factory=sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False, future=True),
        start="2026-01-01",
        end="2026-01-03",
        chunk_days=1,
        runner=runner,
    )

    assert calls == ["2026-01-02T00:00:00+08:00"]


def test_backfill_runs_queued_job_runner_before_each_executed_chunk(db_session: Session):
    calls: list[str] = []

    def queued_job_runner() -> None:
        calls.append("queued")

    def runner(session: Session, *, window: CollectionWindow, job_id: str, include_browser_export: bool | None):
        calls.append(window.start.isoformat())
        stats = CollectionStats(run_id=job_id, source_window=window)
        stats.add_phase(PhaseStats(name="orders", upserted=1))
        return stats

    run_backfill(
        factory=sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False, future=True),
        start="2026-01-01",
        end="2026-01-03",
        chunk_days=1,
        runner=runner,
        queued_job_runner=queued_job_runner,
    )

    assert calls == [
        "queued",
        "2026-01-01T00:00:00+08:00",
        "queued",
        "2026-01-02T00:00:00+08:00",
    ]


def test_run_once_processes_queued_rebuilds_before_and_during_backfill(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    calls: list[str] = []

    def queued_runner(factory_arg):
        assert factory_arg is factory
        calls.append("queued")

    def fake_backfill(**kwargs):
        calls.append("backfill")
        assert kwargs["factory"] is factory
        assert callable(kwargs["queued_job_runner"])
        kwargs["queued_job_runner"]()

    monkeypatch.setenv("WORKER_MODE", "backfill")
    monkeypatch.setattr(scheduler, "get_session_factory", lambda: factory)
    monkeypatch.setattr(scheduler, "process_queued_settlement_rebuilds", queued_runner, raising=False)
    monkeypatch.setattr(scheduler, "run_backfill", fake_backfill)

    run_once()

    assert calls == ["queued", "backfill", "queued"]


def test_run_once_chunks_incremental_collection_by_configured_chunk_days(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    with factory() as session:
        save_sync_config(
            session,
            {
                "rolling_days": 2,
                "history_chunk_days": 1,
            },
        )
        session.commit()

    source_window = CollectionWindow(
        start=datetime.fromisoformat("2026-06-01T00:00:00+08:00"),
        end=datetime.fromisoformat("2026-06-03T00:00:00+08:00"),
        timezone_name="Asia/Shanghai",
    )
    calls: list[tuple[str, str, str, bool]] = []

    def fake_runner(
        session: Session,
        *,
        job_id: str,
        window: CollectionWindow,
        include_browser_export: bool,
        include_materialization: bool = True,
        collectors: list | None = None,
    ):
        assert include_browser_export is False
        if include_materialization:
            assert collectors == []
        else:
            assert collectors is None
        calls.append((job_id, window.start.isoformat(), window.end.isoformat(), include_materialization))
        stats = CollectionStats(run_id=job_id, source_window=window)
        stats.add_phase(PhaseStats(name="orders", upserted=1))
        return stats

    monkeypatch.setenv("WORKER_MODE", "collect_and_settle")
    monkeypatch.setattr(scheduler, "get_session_factory", lambda: factory)
    monkeypatch.setattr(scheduler, "resolve_incremental_collection_window", lambda env=None: source_window)
    monkeypatch.setattr(scheduler, "run_collect_and_settle", fake_runner)
    monkeypatch.setattr(scheduler, "process_queued_settlement_rebuilds", lambda factory_arg: None)

    run_once()

    assert [(start, end, materialize) for _job_id, start, end, materialize in calls] == [
        ("2026-06-01T00:00:00+08:00", "2026-06-02T00:00:00+08:00", False),
        ("2026-06-02T00:00:00+08:00", "2026-06-03T00:00:00+08:00", False),
        ("2026-06-01T00:00:00+08:00", "2026-06-03T00:00:00+08:00", True),
    ]
    assert calls[0][0].startswith("collect_0001_")
    assert calls[1][0].startswith("collect_0002_")
    assert calls[2][0].startswith("collect_materialize_")


def test_run_once_skips_successful_incremental_chunks(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    completed = CollectionWindow(
        start=datetime.fromisoformat("2026-06-01T00:00:00+08:00"),
        end=datetime.fromisoformat("2026-06-02T00:00:00+08:00"),
        timezone_name="Asia/Shanghai",
    )
    with factory() as session:
        save_sync_config(session, {"rolling_days": 2, "history_chunk_days": 1})
        start_job_run(
            session,
            "previous-incremental",
            "collect_and_settle",
            started_at=datetime.fromisoformat("2026-06-03T01:00:00+08:00"),
            metadata_json={
                "source_window": completed.as_metadata(),
                "phases": {"orders": {"name": "orders", "upserted": 1}},
            },
        )
        finish_job_run(session, "previous-incremental", status="success", success_count=1)
        session.commit()

    source_window = CollectionWindow(
        start=datetime.fromisoformat("2026-06-01T00:00:00+08:00"),
        end=datetime.fromisoformat("2026-06-03T00:00:00+08:00"),
        timezone_name="Asia/Shanghai",
    )
    calls: list[tuple[str, str, bool]] = []

    def fake_runner(
        session: Session,
        *,
        job_id: str,
        window: CollectionWindow,
        include_browser_export: bool,
        include_materialization: bool = True,
        collectors: list | None = None,
    ):
        calls.append((job_id, window.start.isoformat(), include_materialization))
        stats = CollectionStats(run_id=job_id, source_window=window)
        stats.add_phase(PhaseStats(name="orders", upserted=1))
        return stats

    monkeypatch.setenv("WORKER_MODE", "collect_and_settle")
    monkeypatch.setattr(scheduler, "get_session_factory", lambda: factory)
    monkeypatch.setattr(scheduler, "resolve_incremental_collection_window", lambda env=None: source_window)
    monkeypatch.setattr(scheduler, "run_collect_and_settle", fake_runner)
    monkeypatch.setattr(scheduler, "process_queued_settlement_rebuilds", lambda factory_arg: None)

    run_once()

    assert [(start, materialize) for _job_id, start, materialize in calls] == [
        ("2026-06-02T00:00:00+08:00", False),
        ("2026-06-01T00:00:00+08:00", True),
    ]


def test_run_once_continues_after_failed_incremental_chunk(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    with factory() as session:
        save_sync_config(session, {"rolling_days": 3, "history_chunk_days": 1})
        session.commit()

    source_window = CollectionWindow(
        start=datetime.fromisoformat("2026-06-01T00:00:00+08:00"),
        end=datetime.fromisoformat("2026-06-04T00:00:00+08:00"),
        timezone_name="Asia/Shanghai",
    )
    calls: list[tuple[str, str, bool]] = []

    def fake_runner(
        session: Session,
        *,
        job_id: str,
        window: CollectionWindow,
        include_browser_export: bool,
        include_materialization: bool = True,
        collectors: list | None = None,
    ):
        calls.append((job_id, window.start.isoformat(), include_materialization))
        if not include_materialization and window.start.isoformat() == "2026-06-02T00:00:00+08:00":
            raise RuntimeError("temporary Douyin API error")
        stats = CollectionStats(run_id=job_id, source_window=window)
        stats.add_phase(PhaseStats(name="orders", upserted=1))
        return stats

    monkeypatch.setenv("WORKER_MODE", "collect_and_settle")
    monkeypatch.setattr(scheduler, "get_session_factory", lambda: factory)
    monkeypatch.setattr(scheduler, "resolve_incremental_collection_window", lambda env=None: source_window)
    monkeypatch.setattr(scheduler, "run_collect_and_settle", fake_runner)
    monkeypatch.setattr(scheduler, "process_queued_settlement_rebuilds", lambda factory_arg: None)

    run_once()

    assert [(start, materialize) for _job_id, start, materialize in calls] == [
        ("2026-06-01T00:00:00+08:00", False),
        ("2026-06-02T00:00:00+08:00", False),
        ("2026-06-02T00:00:00+08:00", False),
        ("2026-06-03T00:00:00+08:00", False),
        ("2026-06-01T00:00:00+08:00", True),
    ]
    with factory() as session:
        failed = session.scalar(
            select(JobRun).where(
                JobRun.status == "failed",
                JobRun.error_message == "temporary Douyin API error",
            )
        )
        assert failed is not None
        assert failed.metadata_json["source_window"]["start"] == "2026-06-02T00:00:00+08:00"


def test_run_once_retries_transient_incremental_chunk_failure(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    with factory() as session:
        save_sync_config(session, {"rolling_days": 2, "history_chunk_days": 1})
        session.commit()

    source_window = CollectionWindow(
        start=datetime.fromisoformat("2026-06-01T00:00:00+08:00"),
        end=datetime.fromisoformat("2026-06-03T00:00:00+08:00"),
        timezone_name="Asia/Shanghai",
    )
    attempts_by_call: dict[tuple[str, bool], int] = {}

    def fake_runner(
        session: Session,
        *,
        job_id: str,
        window: CollectionWindow,
        include_browser_export: bool,
        include_materialization: bool = True,
        collectors: list | None = None,
    ):
        start = window.start.isoformat()
        call_key = (start, include_materialization)
        attempts_by_call[call_key] = attempts_by_call.get(call_key, 0) + 1
        if (
            not include_materialization
            and start == "2026-06-02T00:00:00+08:00"
            and attempts_by_call[call_key] == 1
        ):
            raise RuntimeError("temporary Douyin API error")
        stats = CollectionStats(run_id=job_id, source_window=window)
        stats.add_phase(PhaseStats(name="orders", upserted=1))
        return stats

    monkeypatch.setenv("WORKER_MODE", "collect_and_settle")
    monkeypatch.setattr(scheduler, "get_session_factory", lambda: factory)
    monkeypatch.setattr(scheduler, "resolve_incremental_collection_window", lambda env=None: source_window)
    monkeypatch.setattr(scheduler, "run_collect_and_settle", fake_runner)
    monkeypatch.setattr(scheduler, "process_queued_settlement_rebuilds", lambda factory_arg: None)

    run_once()

    assert attempts_by_call[("2026-06-01T00:00:00+08:00", False)] == 1
    assert attempts_by_call[("2026-06-02T00:00:00+08:00", False)] == 2
    assert attempts_by_call[("2026-06-01T00:00:00+08:00", True)] == 1
    with factory() as session:
        failed_count = session.query(JobRun).where(JobRun.status == "failed").count()
        assert failed_count == 0


def test_incremental_collection_window_defaults_to_recent_30_days():
    window = scheduler.resolve_incremental_collection_window(
        now=datetime.fromisoformat("2026-06-16T15:30:00+08:00"),
        env={
            "DOUYIN_COLLECT_START": "2026-01-26",
            "DOUYIN_COLLECT_END": "2026-06-15",
        },
    )

    assert window.start.isoformat() == "2026-05-17T00:00:00+08:00"
    assert window.end.isoformat() == "2026-06-16T15:30:00+08:00"


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
