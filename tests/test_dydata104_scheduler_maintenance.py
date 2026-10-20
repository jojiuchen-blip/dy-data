"""A scheduler tick has one heavy-work budget, including all startup paths."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from apps.api.dy_api.models import JobRun
from apps.ops_agent.resources import ResourceAction, ResourceDecision
from apps.worker import priority_scheduler, resource_monitor, scheduler
from apps.worker.queued_jobs import QueuedFinanceDisputeDetectionResult, QueuedSettlementRebuildResult
from apps.worker.subprocess_supervisor import ChildRunResult, ChildRunStatus


@pytest.fixture
def queue_calls(monkeypatch):
    from apps.worker import settlement_maintenance

    calls = []
    monkeypatch.setattr(resource_monitor, "current_resource_decision", lambda: ResourceDecision(ResourceAction.ALLOW, ()))
    monkeypatch.setattr(settlement_maintenance, "process_automatic_settlement_maintenance", lambda _factory: calls.append("maintenance") or False)
    monkeypatch.setattr(scheduler, "ensure_month_close_job", lambda _factory: calls.append("month"))
    monkeypatch.setattr(scheduler, "process_queued_settlement_rebuilds", lambda _factory: calls.append("rebuild") or QueuedSettlementRebuildResult())
    monkeypatch.setattr(scheduler, "process_queued_finance_dispute_detections", lambda _factory, *, max_jobs: calls.append(("detection", max_jobs)) or QueuedFinanceDisputeDetectionResult())
    return calls


def test_pending_maintenance_defers_other_work(monkeypatch, queue_calls):
    from apps.worker import settlement_maintenance

    monkeypatch.setattr(settlement_maintenance, "process_automatic_settlement_maintenance", lambda _factory: True)
    assert scheduler._process_queued_jobs(object()) is True
    assert queue_calls == []


def test_executed_rebuild_yields_before_detection(monkeypatch, queue_calls):
    monkeypatch.setattr(scheduler, "process_queued_settlement_rebuilds", lambda _factory: QueuedSettlementRebuildResult(processed_job_id="rebuilt"))
    assert scheduler._process_queued_jobs(object()) is True
    assert queue_calls == ["maintenance", "month"]


def test_detection_batch_is_one(queue_calls):
    assert scheduler._process_queued_jobs(object()) is False
    assert queue_calls == ["maintenance", "month", "rebuild", ("detection", 1)]


@pytest.mark.parametrize("action,consumed,expected", [(ResourceAction.STOP, True, []), (ResourceAction.DRAIN, False, ["maintenance"])])
def test_resource_pressure_never_runs_monthly_or_finance_work(monkeypatch, queue_calls, action, consumed, expected):
    monkeypatch.setattr(resource_monitor, "current_resource_decision", lambda: ResourceDecision(action, ()))
    assert scheduler._process_queued_jobs(object()) is consumed
    assert queue_calls == expected


@pytest.mark.parametrize("entry", ["once", "start", "poll"])
@pytest.mark.parametrize("consumed", [True, False])
def test_priority_startup_and_poll_share_budget(monkeypatch, entry, consumed):
    calls = []
    monkeypatch.setenv("WORKER_RUN_ONCE", str(entry == "once"))
    monkeypatch.setenv("WORKER_RUN_ON_START", str(entry == "start"))
    monkeypatch.setattr(scheduler, "_STOP", False)
    monkeypatch.setattr(resource_monitor, "current_resource_decision", lambda: ResourceDecision(ResourceAction.ALLOW, ()))

    def queue(_factory):
        calls.append("maintenance")
        scheduler._STOP = True
        return consumed

    monkeypatch.setattr(scheduler, "_process_queued_jobs", queue)
    monkeypatch.setattr(priority_scheduler, "run_priority_daily_tick", lambda _factory: calls.append("priority"))
    monkeypatch.setattr(scheduler, "_sleep_until_stop", lambda _seconds: None)
    scheduler._run_priority_daily_ticks(object())
    assert calls == (["maintenance"] if consumed else ["maintenance", "priority"])


def test_legacy_run_once_stops_after_durable_work(monkeypatch):
    monkeypatch.setattr(scheduler, "get_session_factory", lambda: object())
    monkeypatch.setattr(scheduler, "_process_queued_jobs", lambda _factory: True)
    monkeypatch.setattr(scheduler, "run_backfill", lambda **_kwargs: pytest.fail("second heavy job"))
    monkeypatch.setenv("WORKER_MODE", "backfill")
    scheduler.run_once()


def test_legacy_poll_never_drains_after_maintenance(monkeypatch):
    monkeypatch.setattr(scheduler, "_STOP", False)
    monkeypatch.setattr(scheduler, "_auto_sync_enabled", lambda _factory: False)
    monkeypatch.setattr(scheduler, "_process_queued_jobs", lambda _factory: True)
    monkeypatch.setattr(scheduler, "drain_ready_daily_children", lambda *args, **kwargs: pytest.fail("second heavy job"))
    monkeypatch.setattr(scheduler, "_sleep_until_stop", lambda _seconds: setattr(scheduler, "_STOP", True))
    scheduler._run_legacy_scheduler(object(), run_once_only=False, run_on_start=False)


def test_daily_drain_is_limited_to_one_child(monkeypatch):
    limits = []
    child = ChildRunResult("one", ChildRunStatus.SUCCESS, 1)
    monkeypatch.setattr(scheduler, "drain_ready_daily_children", lambda _factory, *, max_children: limits.append(max_children) or (child,))
    assert scheduler.execute_ready_daily_child(object(), SimpleNamespace()) is child
    assert limits == [1]


@pytest.mark.parametrize("mode", ["settlement_only", "browser_export_only", "collect_and_settle"])
def test_legacy_drain_never_executes_direct_heavy_work(monkeypatch, mode):
    monkeypatch.setenv("WORKER_MODE", mode)
    monkeypatch.setattr(scheduler, "get_session_factory", lambda: object())
    monkeypatch.setattr(scheduler, "_process_queued_jobs", lambda _factory: False)
    monkeypatch.setattr(resource_monitor, "current_resource_decision", lambda: ResourceDecision(ResourceAction.DRAIN, ()))
    plans = []
    monkeypatch.setattr(scheduler, "_plan_legacy_sources", lambda _factory, mode: plans.append(mode))
    for name in ("run_settlement_job", "run_browser_export_once", "execute_ready_daily_child", "run_scheduled_product_sync"):
        monkeypatch.setattr(scheduler, name, lambda *args, **kwargs: pytest.fail("direct heavy work during DRAIN"))
    scheduler.run_once()
    assert plans == [mode]


@pytest.mark.parametrize("consumed,mode,expected", [
    (True, "collect_and_settle", ["plan", "plan"]),
    (False, "settlement_only", ["run", "child", "run"]),
])
def test_legacy_due_planning_and_interval_survive_backlog(monkeypatch, consumed, mode, expected):
    calls = []
    clock = [0.0]
    sleeps = []
    monkeypatch.setattr(scheduler, "_STOP", False)
    monkeypatch.setattr(scheduler.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(scheduler, "_auto_sync_enabled", lambda _factory: True)
    monkeypatch.setattr(scheduler, "_configured_interval_seconds", lambda _factory: 20)
    monkeypatch.setattr(scheduler, "_configured_daily_queue_poll_seconds", lambda: 10)
    monkeypatch.setattr(scheduler, "resolve_worker_mode", lambda: mode)
    monkeypatch.setattr(scheduler, "_process_queued_jobs", lambda _factory: consumed)
    monkeypatch.setattr(scheduler, "_plan_legacy_sources", lambda *args: calls.append("plan"))
    monkeypatch.setattr(scheduler, "run_once", lambda: calls.append("run"))
    monkeypatch.setattr(scheduler, "drain_ready_daily_children", lambda *args, **kwargs: calls.append("child"))

    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds
        if len(sleeps) == 5:
            scheduler._STOP = True

    monkeypatch.setattr(scheduler, "_sleep_until_stop", sleep)
    scheduler._run_legacy_scheduler(object(), run_once_only=False, run_on_start=False)
    # Ticks at 0, 10, 20, 30, 40; planning remains due at 20 and 40.
    assert sleeps == [10] * 5
    assert calls == (expected if consumed else ["child", "child", *expected])


def test_legacy_slotless_rebuild_blocks_priority_product_refresh(db_session):
    now = datetime.now(timezone.utc)
    db_session.add(JobRun(job_id="legacy-rebuild", job_name="settlement_rebuild", status="running", started_at=now, execution_slot=None, lease_expires_at=now - timedelta(hours=1)))
    db_session.commit()
    assert priority_scheduler._live_heavy_job(db_session, now).job_id == "legacy-rebuild"
