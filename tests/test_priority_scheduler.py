from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.dy_api.models import Base, DouyinApiQuotaUsage, JobRun, JobStageRun
from apps.worker import priority_scheduler
from apps.worker.daily_windows import enqueue_finalize_if_ready, plan_daily_sync
from apps.worker.subprocess_supervisor import ChildRunResult, ChildRunStatus


@pytest.fixture()
def factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def test_priority_business_date_uses_shanghai_cutoff() -> None:
    before = datetime.fromisoformat("2026-09-10T01:59:59+08:00")
    at_cutoff = datetime.fromisoformat("2026-09-10T02:00:00+08:00")

    assert priority_scheduler.priority_business_date(before).isoformat() == "2026-09-08"
    assert priority_scheduler.priority_business_date(at_cutoff).isoformat() == "2026-09-09"


def test_scheduler_mode_is_explicit_and_independent_from_worker_mode() -> None:
    assert priority_scheduler.resolve_scheduler_mode({}) == "legacy"
    assert (
        priority_scheduler.resolve_scheduler_mode(
            {"WORKER_SCHEDULER_MODE": "PRIORITY_DAILY", "WORKER_MODE": "backfill"}
        )
        == "priority_daily"
    )
    with pytest.raises(ValueError):
        priority_scheduler.resolve_scheduler_mode({"WORKER_SCHEDULER_MODE": "rolling"})


def test_scheduler_main_dispatches_priority_mode_without_legacy_startup_or_drain(
    monkeypatch,
) -> None:
    factory = object()
    calls: list[object] = []

    monkeypatch.setenv("WORKER_SCHEDULER_MODE", "priority_daily")
    monkeypatch.setenv("WORKER_RUN_ONCE", "true")
    monkeypatch.setattr(priority_scheduler, "resolve_scheduler_mode", lambda _env=None: "priority_daily")

    from apps.worker import scheduler

    monkeypatch.setattr(scheduler, "get_session_factory", lambda: factory)
    monkeypatch.setattr(scheduler.signal, "signal", lambda *_args: None)
    monkeypatch.setattr(
        scheduler,
        "_run_priority_daily_mode",
        lambda passed_factory: calls.append(passed_factory),
    )
    monkeypatch.setattr(scheduler, "run_once", lambda: pytest.fail("legacy run_once was called"))
    monkeypatch.setattr(
        scheduler,
        "drain_ready_daily_children",
        lambda _factory: pytest.fail("legacy daily drain was called"),
    )

    scheduler.main()

    assert calls == [factory]


def test_daily_plan_is_idempotent_and_stamps_every_execution_row(factory) -> None:
    target = datetime.fromisoformat("2026-09-09T00:00:00+08:00").date()
    with factory.begin() as session:
        first = priority_scheduler.ensure_daily_priority_plan(
            session,
            target,
            now=datetime.fromisoformat("2026-09-10T02:00:00+08:00"),
        )
        second = priority_scheduler.ensure_daily_priority_plan(
            session,
            target,
            now=datetime.fromisoformat("2026-09-10T02:05:00+08:00"),
        )

        assert first.parent_job_id == second.parent_job_id

    with factory() as session:
        rows = list(
            session.scalars(
                select(JobRun).where(
                    (JobRun.job_id == first.parent_job_id)
                    | (JobRun.parent_job_id == first.parent_job_id)
                )
            )
        )
        assert len([row for row in rows if row.job_kind == "date_sync"]) == 1
        assert {row.metadata_json.get("priority_purpose") for row in rows} == {
            priority_scheduler.DAILY_REQUIRED_PURPOSE
        }
        assert {row.metadata_json.get("request_budget_date") for row in rows} == {
            "2026-09-10"
        }


def test_before_cutoff_recovers_existing_manual_yesterday_plan(factory) -> None:
    target = datetime.fromisoformat("2026-09-09T00:00:00+08:00").date()
    with factory.begin() as session:
        priority_scheduler.ensure_daily_priority_plan(
            session,
            target,
            now=datetime.fromisoformat("2026-09-09T23:00:00+08:00"),
            requested_by="manual",
            trigger_source="manual",
        )

    calls: list[str] = []

    def child_runner(_factory, job_id: str):
        calls.append(job_id)
        return ChildRunResult(job_id=job_id, status=ChildRunStatus.SUCCESS, attempts=1)

    result = priority_scheduler.run_priority_daily_tick(
        factory,
        now=datetime.fromisoformat("2026-09-10T01:00:00+08:00"),
        child_runner=child_runner,
        product_sync_runner=lambda _factory, **_kwargs: None,
    )

    assert result.action == "executed"
    assert result.business_date == target
    assert calls == [result.selected_job_id]
    with factory() as session:
        assert session.query(JobRun).where(JobRun.job_kind == "range_sync").count() == 1


def test_dimension_refresh_can_start_before_daily_cutoff(factory) -> None:
    now = datetime.fromisoformat("2026-09-10T00:10:00+08:00")
    calls: list[str] = []

    def child_runner(_factory, job_id: str):
        calls.append(job_id)
        return ChildRunResult(job_id=job_id, status=ChildRunStatus.SUCCESS, attempts=1)

    result = priority_scheduler.run_priority_daily_tick(
        factory,
        now=now,
        child_runner=child_runner,
        product_sync_runner=lambda _factory, **_kwargs: None,
    )

    assert result.action == "executed"
    assert result.selected_purpose == priority_scheduler.DAILY_REQUIRED_PURPOSE
    assert calls == [result.selected_job_id]
    with factory() as session:
        selected = session.get(JobRun, result.selected_job_id)
        assert selected is not None
        assert selected.metadata_json.get("priority_kind") == "dimensions"
        assert selected.metadata_json.get("priority_refresh_slot") == "2026091000"


def test_daily_failure_blocks_history_and_does_not_run_child(
    factory,
    monkeypatch,
) -> None:
    target = datetime.fromisoformat("2026-09-09T00:00:00+08:00").date()
    with factory.begin() as session:
        plan = priority_scheduler.ensure_daily_priority_plan(
            session,
            target,
            now=datetime.fromisoformat("2026-09-10T02:00:00+08:00"),
        )
        parent_execution = session.scalar(
            select(JobRun).where(
                JobRun.parent_job_id == plan.parent_job_id,
                JobRun.job_kind == "parent_sync",
            )
        )
        child = session.scalar(
            select(JobRun).where(
                JobRun.parent_job_id == plan.parent_job_id,
                JobRun.job_kind == "date_sync",
            )
        )
        assert parent_execution is not None
        assert child is not None
        parent_execution.status = "success"
        child.status = "failed"

    calls: list[str] = []
    monkeypatch.setattr(priority_scheduler, "_plan_due_dimensions", lambda *_args: ())

    def child_runner(_factory, job_id: str):
        calls.append(job_id)
        return ChildRunResult(job_id=job_id, status=ChildRunStatus.SUCCESS, attempts=1)

    result = priority_scheduler.run_priority_daily_tick(
        factory,
        now=datetime.fromisoformat("2026-09-10T02:10:00+08:00"),
        child_runner=child_runner,
        product_sync_runner=lambda _factory, **_kwargs: None,
    )

    assert result.action == "blocked"
    assert result.reason == "daily_failed"
    assert calls == []
    with factory() as session:
        assert session.query(JobRun).where(JobRun.job_kind == "range_sync").count() == 1


def test_failed_domain_does_not_block_other_manual_domain(factory) -> None:
    target = date(2026, 9, 9)
    now = datetime.fromisoformat("2026-09-10T02:10:00+08:00")
    with factory.begin() as session:
        priority_scheduler.ensure_daily_priority_plan(session, target, now=now)
        failed_plan = plan_daily_sync(
            session,
            start=target,
            end=target + timedelta(days=1),
            target="orders",
            requested_by="manual",
            trigger_source="manual",
            config_version=priority_scheduler.PRIORITY_CONFIG_VERSION,
        )
        pending_plan = plan_daily_sync(
            session,
            start=target,
            end=target + timedelta(days=1),
            target="refunds",
            requested_by="manual",
            trigger_source="manual",
            config_version=priority_scheduler.PRIORITY_CONFIG_VERSION,
        )
        failed_child = session.get(JobRun, failed_plan.daily_jobs[0].job_id)
        pending_child = session.get(JobRun, pending_plan.daily_jobs[0].job_id)
        assert failed_child is not None
        assert pending_child is not None
        failed_child.status = "failed"
        for row in (failed_child, pending_child):
            row.metadata_json = {
                **(row.metadata_json or {}),
                "priority_purpose": priority_scheduler.DAILY_REQUIRED_PURPOSE,
                "priority_mode": priority_scheduler.PRIORITY_DAILY_MODE,
                "priority_business_date": target.isoformat(),
                "request_budget_date": now.date().isoformat(),
            }

    calls: list[str] = []

    def child_runner(_factory, job_id: str):
        calls.append(job_id)
        return ChildRunResult(job_id=job_id, status=ChildRunStatus.SUCCESS, attempts=1)

    result = priority_scheduler.run_priority_daily_tick(
        factory,
        now=now,
        child_runner=child_runner,
        product_sync_runner=lambda _factory, **_kwargs: None,
    )

    assert result.action == "executed"
    assert result.selected_job_id == calls[0]
    with factory() as session:
        selected = session.get(JobRun, result.selected_job_id)
        assert selected is not None
        assert selected.job_kind == "date_sync"
        assert selected.metadata_json.get("target") == "refunds"


def test_history_checkpoint_uses_request_governor_after_daily_reserve(
    factory,
    monkeypatch,
) -> None:
    target = date(2026, 9, 9)
    now = datetime.fromisoformat("2026-09-10T02:10:00+08:00")
    with factory.begin() as session:
        plan = priority_scheduler.ensure_daily_priority_plan(session, target, now=now)
        parent_execution = session.scalar(
            select(JobRun).where(
                JobRun.parent_job_id == plan.parent_job_id,
                JobRun.job_kind == "parent_sync",
            )
        )
        child = session.scalar(
            select(JobRun).where(
                JobRun.parent_job_id == plan.parent_job_id,
                JobRun.job_kind == "date_sync",
            )
        )
        parent_stage = session.scalar(
            select(JobStageRun).where(
                JobStageRun.job_id == plan.parent_job_id,
                JobStageRun.stage_name == "collect_dimensions",
            )
        )
        assert parent_execution is not None
        assert child is not None
        assert parent_stage is not None
        parent_execution.status = "success"
        child.status = "success"
        parent_stage.committed_at = now
        parent_stage.status = "success"
        for stage_name in ("collect", "materialize", "settle"):
            checkpoint = {}
            if stage_name == "settle":
                checkpoint = {
                    "settlement_summary": {
                        "mode": "incremental",
                        "completed": True,
                        "impact_count": 0,
                        "coupon_count": 0,
                        "detail_count": 0,
                        "result_count": 0,
                        "adjustment_count": 0,
                        "affected_months": [],
                        "affected_store_ids": [],
                    },
                    "store_score_snapshot": {
                        "deferred": True,
                        "consumer": "T3.4.finalize",
                        "affected_store_ids": [],
                        "rule_closure": "published-rules-and-eligible-stores",
                    },
                }
            session.add(
                JobStageRun(
                    stage_run_id=f"stage-{child.job_id}-{stage_name}",
                    job_id=child.job_id,
                    stage_name=stage_name,
                    status="success",
                    checkpoint_json=checkpoint,
                    lease_epoch=1,
                    started_at=now,
                    finished_at=now,
                    committed_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
        session.flush()
        finalize = enqueue_finalize_if_ready(session, plan.parent_job_id)
        assert finalize is not None
        finalize.status = "success"
        range_parent = session.get(JobRun, plan.parent_job_id)
        assert range_parent is not None
        range_parent.status = "success"
        session.add(
            DouyinApiQuotaUsage(
                environment="test",
                app_id="app",
                account_id="account",
                endpoint_key="/goodlife/refunds/list",
                business_date=now.date(),
                request_count=70,
                effective_limit=80,
                reset_at=datetime.fromisoformat("2026-09-11T00:00:00+08:00"),
            )
        )

    monkeypatch.setattr(priority_scheduler, "_plan_due_dimensions", lambda *_args: ())
    calls: list[str] = []

    def child_runner(_factory, job_id: str):
        calls.append(job_id)
        return ChildRunResult(job_id=job_id, status=ChildRunStatus.SUCCESS, attempts=1)

    result = priority_scheduler.run_priority_daily_tick(
        factory,
        now=now,
        child_runner=child_runner,
        product_sync_runner=lambda _factory, **_kwargs: None,
    )

    assert result.action == "executed"
    assert result.selected_purpose == priority_scheduler.HISTORY_PURPOSE
    assert calls == [result.selected_job_id]


def test_priority_tick_executes_one_exact_job_without_legacy_drain(factory) -> None:
    target = datetime.fromisoformat("2026-09-09T00:00:00+08:00").date()
    with factory.begin() as session:
        priority_scheduler.ensure_daily_priority_plan(
            session,
            target,
            now=datetime.fromisoformat("2026-09-10T02:00:00+08:00"),
        )

    calls: list[str] = []

    def child_runner(_factory, job_id: str):
        calls.append(job_id)
        return ChildRunResult(job_id=job_id, status=ChildRunStatus.SUCCESS, attempts=1)

    result = priority_scheduler.run_priority_daily_tick(
        factory,
        now=datetime.fromisoformat("2026-09-10T02:01:00+08:00"),
        child_runner=child_runner,
        product_sync_runner=lambda _factory, **_kwargs: None,
    )

    assert result.action == "executed"
    assert calls == [result.selected_job_id]
    assert result.selected_purpose == priority_scheduler.DAILY_REQUIRED_PURPOSE


def test_manual_domain_child_precedes_all_daily_rows(factory) -> None:
    target = date(2026, 9, 9)
    now = datetime.fromisoformat("2026-09-10T02:10:00+08:00")
    with factory.begin() as session:
        priority_scheduler.ensure_daily_priority_plan(session, target, now=now)
        manual = plan_daily_sync(
            session,
            start=target,
            end=target + timedelta(days=1),
            target="orders",
            requested_by="manual",
            trigger_source="manual",
            config_version=priority_scheduler.PRIORITY_CONFIG_VERSION,
        )
        for planned in manual.daily_jobs:
            row = session.get(JobRun, planned.job_id)
            assert row is not None
            row.metadata_json = {
                **(row.metadata_json or {}),
                "priority_purpose": priority_scheduler.DAILY_REQUIRED_PURPOSE,
                "priority_mode": priority_scheduler.PRIORITY_DAILY_MODE,
                "priority_business_date": target.isoformat(),
                "request_budget_date": now.date().isoformat(),
            }

    calls: list[str] = []

    def child_runner(_factory, job_id: str):
        calls.append(job_id)
        return ChildRunResult(job_id=job_id, status=ChildRunStatus.SUCCESS, attempts=1)

    result = priority_scheduler.run_priority_daily_tick(
        factory,
        now=now,
        child_runner=child_runner,
        product_sync_runner=lambda _factory, **_kwargs: None,
    )

    assert result.action == "executed"
    assert result.selected_purpose == priority_scheduler.DAILY_REQUIRED_PURPOSE
    assert result.selected_job_id == calls[0]
    with factory() as session:
        selected = session.get(JobRun, result.selected_job_id)
        assert selected is not None
        assert selected.metadata_json.get("target") == "orders"
        assert selected.job_kind == "date_sync"


def test_parent_gate_blocks_date_child_before_daily_history_gate(factory, monkeypatch) -> None:
    target = date(2026, 9, 9)
    now = datetime.fromisoformat("2026-09-10T02:10:00+08:00")
    with factory.begin() as session:
        plan = priority_scheduler.ensure_daily_priority_plan(session, target, now=now)
        parent_execution = session.scalar(
            select(JobRun).where(
                JobRun.parent_job_id == plan.parent_job_id,
                JobRun.job_kind == "parent_sync",
            )
        )
        assert parent_execution is not None
        parent_execution.status = "partial"

    monkeypatch.setattr(priority_scheduler, "_plan_due_dimensions", lambda *_args: ())
    calls: list[str] = []

    def child_runner(_factory, job_id: str):
        calls.append(job_id)
        return ChildRunResult(job_id=job_id, status=ChildRunStatus.SUCCESS, attempts=1)

    result = priority_scheduler.run_priority_daily_tick(
        factory,
        now=now,
        child_runner=child_runner,
        product_sync_runner=lambda _factory, **_kwargs: None,
    )

    assert result.action == "waiting"
    assert result.reason == "daily_incomplete"
    assert calls == []


def test_daily_failure_still_allows_independent_dimension_refresh(factory) -> None:
    target = date(2026, 9, 9)
    now = datetime.fromisoformat("2026-09-10T02:10:00+08:00")
    with factory.begin() as session:
        plan = priority_scheduler.ensure_daily_priority_plan(session, target, now=now)
        parent_execution = session.scalar(
            select(JobRun).where(
                JobRun.parent_job_id == plan.parent_job_id,
                JobRun.job_kind == "parent_sync",
            )
        )
        child = session.scalar(
            select(JobRun).where(
                JobRun.parent_job_id == plan.parent_job_id,
                JobRun.job_kind == "date_sync",
            )
        )
        assert parent_execution is not None
        assert child is not None
        # Keep the all-domain parent closure out of the candidate set so this
        # test exercises an independent dimension refresh after a failed
        # daily child.  The scheduler may still execute a healthy parent when
        # it is the only remaining daily-required candidate.
        parent_execution.status = "success"
        child.status = "failed"

    calls: list[str] = []

    def child_runner(_factory, job_id: str):
        calls.append(job_id)
        return ChildRunResult(job_id=job_id, status=ChildRunStatus.SUCCESS, attempts=1)

    result = priority_scheduler.run_priority_daily_tick(
        factory,
        now=now,
        child_runner=child_runner,
        product_sync_runner=lambda _factory, **_kwargs: None,
    )

    assert result.action == "executed"
    assert result.selected_purpose == priority_scheduler.DAILY_REQUIRED_PURPOSE
    assert calls == [result.selected_job_id]
    with factory() as session:
        selected = session.get(JobRun, result.selected_job_id)
        assert selected is not None
        assert selected.metadata_json.get("priority_kind") == "dimensions"
        assert selected.metadata_json.get("priority_dimension_target") in (
            "shop_pois",
            "aweme_bindings",
            "backend_aweme_export",
        )


def test_current_day_filter_is_applied_before_priority_row_limit(factory) -> None:
    target = date(2026, 9, 9)
    other_day = date(2026, 9, 8)
    with factory.begin() as session:
        session.add_all(
            JobRun(
                job_id=f"noise-{index:04d}",
                job_name="range_sync",
                status="pending",
                job_kind="range_sync",
                config_version=priority_scheduler.PRIORITY_CONFIG_VERSION,
                data_source="douyin",
                metadata_json={"target": "all"},
                window_start=datetime.combine(other_day, datetime.min.time()),
                window_end=datetime.combine(other_day + timedelta(days=1), datetime.min.time()),
            )
            for index in range(priority_scheduler.MAX_PRIORITY_ROWS + 50)
        )
        plan = priority_scheduler.ensure_daily_priority_plan(
            session,
            target,
            now=datetime.fromisoformat("2026-09-10T02:00:00+08:00"),
        )
        parent_job_id = plan.parent_job_id
        rows = priority_scheduler._priority_rows_for_day(session, target)
        row_ids = {row.job_id for row in rows}
        row_dates = {
            priority_scheduler._job_business_date(row) for row in rows
        }

    assert parent_job_id in row_ids
    assert row_dates == {target}


def test_history_range_query_is_bounded_without_global_row_truncation(factory) -> None:
    target = date(2026, 9, 9)
    other_day = date(2026, 9, 8)
    with factory.begin() as session:
        session.add_all(
            JobRun(
                job_id=f"history-noise-{index:04d}",
                job_name="range_sync",
                status="pending",
                job_kind="range_sync",
                config_version=priority_scheduler.PRIORITY_CONFIG_VERSION,
                data_source="douyin",
                metadata_json={"target": "all"},
                window_start=datetime.combine(other_day, datetime.min.time()),
                window_end=datetime.combine(other_day + timedelta(days=1), datetime.min.time()),
            )
            for index in range(priority_scheduler.MAX_PRIORITY_ROWS + 50)
        )
        plan = priority_scheduler.ensure_history_priority_plan(
            session,
            target,
            now=datetime.fromisoformat("2026-09-10T02:00:00+08:00"),
        )
        parent_job_id = plan.parent_job_id
        rows = priority_scheduler._all_priority_rows(
            session,
            lower_date=target,
            upper_date=target,
        )
        row_ids = {row.job_id for row in rows}
        row_dates = {
            priority_scheduler._job_business_date(row) for row in rows
        }

    assert parent_job_id in row_ids
    assert row_dates == {target}
