from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import sessionmaker

from apps.api.dy_api.models import JobImpact, JobRun, RawAwemeBinding, SettlementProjectionGeneration
from apps.ops_agent.resources import ResourceAction, ResourceDecision
from apps.worker import priority_scheduler, resource_monitor, scheduler, settlement_maintenance
from apps.worker.daily_windows import plan_daily_sync
from apps.worker.subprocess_supervisor import ChildRunResult, ChildRunStatus


NOW = datetime.fromisoformat("2026-11-02T15:00:00+08:00")


@pytest.fixture()
def factory(db_session):
    return sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)


@pytest.fixture(autouse=True)
def healthy_resources(monkeypatch):
    monkeypatch.setattr(resource_monitor, "current_resource_decision",
                        lambda: ResourceDecision(ResourceAction.ALLOW, ()))
    monkeypatch.setattr(priority_scheduler, "_snapshot", lambda result: result)


def account_plan(factory, *, day=None, target="backend_aweme_export", **overrides):
    day = day or NOW.date()
    with factory.begin() as session:
        plan = plan_daily_sync(
            session, start=day, end=day + timedelta(days=1), target=target,
            requested_by="priority-daily-scheduler", trigger_source="dimension_refresh",
            config_version=f"priority-daily-v1-dimensions-{day:%Y%m%d}0000",
        )
        priority_scheduler._stamp_plan_metadata(
            session, parent_job_id=plan.parent_job_id,
            purpose=priority_scheduler.DAILY_REQUIRED_PURPOSE,
            priority_date=day, request_budget_date=day,
        )
        job = session.scalar(select(JobRun).where(
            JobRun.parent_job_id == plan.parent_job_id, JobRun.job_kind == "parent_sync",
        ))
        for key, value in overrides.items():
            setattr(job, key, value)
        return job.job_id


def execute_tick(factory, monkeypatch, **kwargs):
    calls = []

    def supervisor(passed_factory, *, job_id):
        assert passed_factory is factory
        calls.append(job_id)
        return ChildRunResult(job_id, ChildRunStatus.SUCCESS, 1)

    monkeypatch.setattr(scheduler, "run_daily_child", supervisor)
    return priority_scheduler.run_maintenance_safe_account_tick(factory, now=NOW, **kwargs), calls


def test_due_roster_retry_uses_original_supervisor_identity(factory, monkeypatch):
    job_id = account_plan(factory, status="retry_wait", attempt_count=1,
                          next_retry_at=NOW - timedelta(hours=10))
    account_plan(factory, target="shop_pois")
    result, calls = execute_tick(factory, monkeypatch)
    assert result.action == "executed" and calls == [job_id]
    with factory() as session:
        job = session.get(JobRun, job_id)
        assert job.status == "retry_wait" and job.attempt_count == 1
        assert job.metadata_json["request_budget_date"] == "2026-11-02"


def test_old_roster_retry_keeps_original_window_and_refreshes_quota_date(factory, monkeypatch):
    yesterday = NOW.date() - timedelta(days=1)
    job_id = account_plan(factory, day=yesterday, status="retry_wait", attempt_count=1,
                          next_retry_at=NOW - timedelta(hours=1))
    result, calls = execute_tick(factory, monkeypatch)
    assert result.business_date == yesterday and calls == [job_id]
    with factory() as session:
        job = session.get(JobRun, job_id)
        assert job.metadata_json["priority_business_date"] == "2026-11-01"
        assert job.metadata_json["quota_business_date"] == "2026-11-02"


@pytest.mark.parametrize("overrides", [
    {"next_retry_at": NOW + timedelta(hours=1)},
    {"attempt_count": 3},
    {"cancel_requested_at": NOW},
    {"pause_after_stage_requested_at": NOW},
])
def test_ineligible_roster_is_not_dispatched_or_replaced(factory, monkeypatch, overrides):
    changes = dict(status="retry_wait", attempt_count=1,
                   next_retry_at=NOW - timedelta(hours=1))
    changes.update(overrides)
    job_id = account_plan(factory, **changes)
    _, calls = execute_tick(factory, monkeypatch)
    assert calls == []
    with factory() as session:
        assert list(session.scalars(select(JobRun.job_id).where(JobRun.job_kind == "parent_sync"))) == [job_id]


@pytest.mark.parametrize("unsafe", ["legacy", "stages", "impact", "parent_identity"])
def test_unsafe_roster_scope_cannot_enter_maintenance_lane(factory, monkeypatch, unsafe):
    job_id = account_plan(factory)
    with factory.begin() as session:
        job = session.get(JobRun, job_id)
        if unsafe == "legacy":
            job.metadata_json = {**job.metadata_json, "settlement_mode": "legacy"}
        elif unsafe == "stages":
            job.metadata_json = {**job.metadata_json, "required_stages": ["collect_dimensions", "materialize", "settle"]}
        elif unsafe == "impact":
            session.add(JobImpact(impact_key="unexpected", entity_type="order", entity_key="test",
                                  source_run_id=job_id))
        else:
            session.get(JobRun, job.parent_job_id).config_version = "changed"
    _, calls = execute_tick(factory, monkeypatch)
    assert calls == []


def test_maintenance_lane_plans_only_roster_and_reuses_current_slot(factory, monkeypatch):
    first, calls = execute_tick(factory, monkeypatch)
    repeated, repeated_calls = execute_tick(factory, monkeypatch)
    assert calls == repeated_calls == [first.selected_job_id]
    assert repeated.selected_job_id == first.selected_job_id
    with factory() as session:
        jobs = list(session.scalars(select(JobRun).where(JobRun.job_kind == "parent_sync")))
        assert len(jobs) == 1
        assert jobs[0].metadata_json["target"] == "backend_aweme_export"
        assert jobs[0].metadata_json["priority_refresh_slot"] == "202611021500"


def test_recent_success_waits_until_roster_refresh_interval(factory, monkeypatch):
    account_plan(factory, status="success", finished_at=NOW - timedelta(minutes=5))
    result, calls = execute_tick(factory, monkeypatch)
    assert calls == [] and result.reason == "account_refresh_not_due"


def test_idle_roster_cadence_reads_one_timestamp_row(factory):
    account_plan(factory, status="success", finished_at=NOW - timedelta(minutes=5))
    statements = []
    engine = factory.kw["bind"]

    def capture(_conn, _cursor, statement, parameters, _context, _many):
        statements.append((statement, parameters))

    event.listen(engine, "before_cursor_execute", capture)
    try:
        with factory() as session:
            assert priority_scheduler._dimension_refresh_due(
                session, NOW, targets=("backend_aweme_export",),
            ) is False
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(statements) == 1
    query, parameters = statements[0]
    assert query.split("FROM")[0].strip() == "SELECT job_runs.finished_at, job_runs.started_at"
    assert "backend_aweme_export" in parameters and parameters[-2:] == (1, 0)


def test_expired_other_heavy_writer_still_blocks_roster(factory, monkeypatch):
    account_plan(factory)
    with factory.begin() as session:
        session.add(JobRun(job_id="old-writer", job_name="settlement_rebuild", status="running",
                           started_at=NOW - timedelta(hours=1),
                           lease_expires_at=NOW - timedelta(minutes=1)))
    result, calls = execute_tick(factory, monkeypatch)
    assert calls == [] and result.reason == "heavy_slot_busy"


def test_resource_stop_prevents_even_roster_planning(factory, monkeypatch):
    monkeypatch.setattr(resource_monitor, "current_resource_decision",
                        lambda: ResourceDecision(ResourceAction.STOP, ("pressure",)))
    result, calls = execute_tick(factory, monkeypatch)
    assert calls == [] and result.status == "resource_wait"
    with factory() as session:
        assert session.scalar(select(JobRun.job_id).limit(1)) is None


@pytest.fixture()
def manifest_limited(monkeypatch):
    monkeypatch.setattr(settlement_maintenance, "_active_head", lambda _factory: ("base", 48, "lineage"))
    monkeypatch.setattr(settlement_maintenance, "_reconcile_pending", lambda _factory: False)
    limits = SimpleNamespace(min_disk_headroom_bytes=10, max_estimated_write_bytes=2,
                             max_estimated_wal_bytes=4, observed_disk_headroom_bytes=16)
    monkeypatch.setattr(settlement_maintenance, "disk_capacity_limits", lambda: limits)
    monkeypatch.setattr(settlement_maintenance, "estimate_automatic_compaction", lambda *_args, **_kwargs: object())
    def limited(*_args):
        raise settlement_maintenance.MaintenanceAdmissionError("manifest_rows_exceed_limit")
    monkeypatch.setattr(settlement_maintenance, "_check_estimate", limited)
    return limits


def test_only_manifest_limit_offers_independent_account_opportunity(factory, manifest_limited):
    calls = []
    assert settlement_maintenance.process_automatic_settlement_maintenance(
        factory, on_manifest_limit=lambda passed_factory: calls.append(passed_factory),
    ) is True
    assert calls == [factory]


def test_manifest_error_does_not_conceal_disk_pressure(factory, manifest_limited):
    manifest_limited.observed_disk_headroom_bytes = 15
    assert settlement_maintenance.process_automatic_settlement_maintenance(
        factory, on_manifest_limit=lambda _factory: pytest.fail("disk reserve must block roster"),
    ) is True


@pytest.mark.parametrize("error", ["disk_probe_unavailable", "disabled", "estimated_write_bytes_exceed_limit"])
def test_other_maintenance_blocks_never_offer_roster(factory, manifest_limited, monkeypatch, error):
    def blocked(*_args):
        raise settlement_maintenance.MaintenanceAdmissionError(error)
    monkeypatch.setattr(settlement_maintenance, "_check_estimate", blocked)
    assert settlement_maintenance.process_automatic_settlement_maintenance(
        factory, on_manifest_limit=lambda _factory: pytest.fail("unrelated maintenance block"),
    ) is True


def test_unknown_error_text_cannot_offer_roster(factory, manifest_limited, monkeypatch):
    def unknown(*_args):
        raise RuntimeError("manifest_rows_exceed_limit")
    monkeypatch.setattr(settlement_maintenance, "_check_estimate", unknown)
    assert settlement_maintenance.process_automatic_settlement_maintenance(
        factory, on_manifest_limit=lambda _factory: pytest.fail("unknown error must remain closed"),
    ) is True


def test_priority_maintenance_callback_never_releases_other_work(factory, manifest_limited, monkeypatch):
    monkeypatch.setenv("WORKER_SCHEDULER_MODE", "priority_daily")
    calls = []
    monkeypatch.setattr(priority_scheduler, "run_maintenance_safe_account_tick",
                        lambda passed_factory: calls.append(passed_factory))
    monkeypatch.setattr(scheduler, "ensure_month_close_job", lambda _factory: pytest.fail("month close"))
    monkeypatch.setattr(scheduler, "process_queued_settlement_rebuilds", lambda _factory: pytest.fail("rebuild"))
    assert scheduler._process_queued_jobs(factory) is True
    assert calls == [factory]


def test_actual_roster_ingestion_and_incremental_settle_create_no_lineage(factory, monkeypatch):
    from apps.worker import daily_task
    from apps.worker.browser_exports import backend_aweme

    job_id = account_plan(factory)

    def ingest(session, *, source_run_id):
        return backend_aweme.upsert_backend_aweme_records(session, [{
            "douyin_id": "test-douyin", "account_id": "test-account",
            "account_name": "Test store", "binding_status": "active",
        }], source_run_id=source_run_id)

    # Browser IO and the already-tested lease fence are the two external edges.
    # Exercise the real dimension writes and real no-impact settlement handler.
    monkeypatch.setattr(backend_aweme, "run_backend_aweme_export", ingest)
    monkeypatch.setattr(daily_task, "_daily_page_fence", lambda *_args: lambda _session: True)
    handlers = daily_task.default_stage_handlers(client=object())
    with factory.begin() as session:
        job = session.get(JobRun, job_id)
        assert handlers["collect_dimensions"](session, job)["fetched"] == 1
    with factory() as session:
        result = handlers["settle"](session, session.get(JobRun, job_id))
        assert result["detail_count"] == 0
        assert result["settlement_summary"]["completed"] is True
        assert session.scalar(select(func.count()).select_from(RawAwemeBinding)) == 1
        assert session.scalar(select(JobImpact.id).limit(1)) is None
        assert session.scalar(select(SettlementProjectionGeneration.generation_id).limit(1)) is None
