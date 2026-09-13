from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from apps.api.dy_api.models import Base, ComponentHeartbeat, JobRun
from apps.ops_agent.resources import CgroupMemory, HostMemory, ResourceAction, ResourceDecision, ResourceSnapshot
from apps.worker import priority_scheduler, resource_monitor
from apps.worker.pipeline import sanitize_error_message


@pytest.fixture()
def factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'resource.db'}")
    Base.metadata.create_all(engine)
    yield sessionmaker(engine, expire_on_commit=False)
    engine.dispose()


def write_heartbeat(factory, monkeypatch, *, age=0, daily=True, history=False):
    monkeypatch.setenv("WORKER_RESOURCE_GUARD_ENABLED", "true")
    monkeypatch.setenv("DY_WORKER_RESOURCE_MONITOR_ID", "worker-resource-monitor-test")
    with factory() as session:
        session.add(ComponentHeartbeat(
            component_instance_id="worker-resource-monitor-test", component_type="worker",
            status="draining", last_heartbeat_at=datetime.now(UTC) - timedelta(seconds=age),
            activity_json={"resource_guard": {"allow_daily": daily, "allow_history": history}},
        ))
        session.commit()


@pytest.mark.parametrize("purpose,allowed", [("daily_required", True), ("history", False)])
@pytest.mark.parametrize("version", ["priority-daily-v1", "priority-daily-v1-dimensions-2026091310"])
def test_child_obeys_shared_monitor_without_starting_a_new_policy(factory, monkeypatch, purpose, allowed, version):
    write_heartbeat(factory, monkeypatch)
    job = SimpleNamespace(config_version=version, metadata_json={"priority_purpose": purpose})
    with factory() as session:
        if allowed:
            resource_monitor.require_resource_admission(session, job)
        else:
            with pytest.raises(resource_monitor.ResourcePauseError):
                resource_monitor.require_resource_admission(session, job)


@pytest.mark.parametrize("version", ["priority-daily-v1", "priority-daily-v1-dimensions-2026091310"])
def test_stale_healthy_monitor_does_not_admit_child(factory, monkeypatch, version):
    write_heartbeat(factory, monkeypatch, age=31, daily=True, history=True)
    job = SimpleNamespace(config_version=version, metadata_json={})
    with factory() as session, pytest.raises(resource_monitor.ResourcePauseError):
        resource_monitor.require_resource_admission(session, job)


def test_missing_monitor_yields_instead_of_consuming_upstream_requests(factory, monkeypatch):
    monkeypatch.setenv("WORKER_RESOURCE_GUARD_ENABLED", "true")
    monkeypatch.delenv("DY_WORKER_RESOURCE_MONITOR_ID", raising=False)
    with factory() as session, pytest.raises(resource_monitor.ResourcePauseError):
        resource_monitor.require_resource_admission(
            session, SimpleNamespace(config_version="priority-daily-v1", metadata_json={})
        )


def test_pause_marker_survives_long_sensitive_traceback_without_exposing_it():
    message = "cookie=private\n" + "frame\n" * 1000 + "ResourcePauseError: worker_resource_pause retry_after_seconds=60\n"
    assert sanitize_error_message(message) == "worker_resource_pause retry_after_seconds=60"


def test_protected_daily_plan_is_queued_without_attempt_then_runs_after_recovery(factory, monkeypatch):
    from apps.worker.subprocess_supervisor import ChildRunResult, ChildRunStatus

    monkeypatch.setattr(resource_monitor, "current_resource_decision", lambda: ResourceDecision(ResourceAction.STOP, ("pressure",)))
    calls = []
    def runner(_factory, job_id):
        calls.append(job_id)
        return ChildRunResult(job_id=job_id, status=ChildRunStatus.SUCCESS, attempts=1)

    now = datetime(2026, 9, 13, 2, tzinfo=priority_scheduler.SHANGHAI_TIMEZONE)
    result = priority_scheduler.run_priority_daily_tick(factory, now=now, child_runner=runner)
    assert result.status == "resource_wait"
    assert calls == []
    with factory() as session:
        job = session.get(JobRun, result.selected_job_id)
        assert job.status == "pending" and (job.attempt_count or 0) == 0
    monkeypatch.setattr(resource_monitor, "current_resource_decision", lambda: ResourceDecision(ResourceAction.DRAIN, ("recovery",)))
    recovered = priority_scheduler.run_priority_daily_tick(factory, now=now, child_runner=runner)
    assert recovered.selected_job_id == result.selected_job_id
    assert calls == [result.selected_job_id]
    assert priority_scheduler._resource_wait(date(2026, 8, 21), "history-job", "history") is not None


def test_monitor_publishes_even_without_a_running_job(factory, monkeypatch):
    # A deterministic policy clock keeps this test about production heartbeat
    # persistence rather than duplicating the policy transition tests.
    state = SimpleNamespace(state="protected", reasons=("host_available_low",),
                            allow_daily=False, allow_history=False, since=0)
    policy = SimpleNamespace(update=lambda _snapshot, now: state)
    snapshot = ResourceSnapshot(100, HostMemory(8 << 30, 500 << 20, 2 << 30, 1 << 30), CgroupMemory(1 << 30, 3 << 30, 0, None))
    monkeypatch.setattr(resource_monitor.time, "monotonic", lambda: 60)
    monitor = resource_monitor.ResourceMonitor(factory, policy=policy, sampler=lambda: snapshot)
    payload = monitor.sample()
    assert payload["duration_seconds"] == 60
    with factory() as session:
        row = session.get(ComponentHeartbeat, monitor.instance_id)
        assert row.current_job_id is None
        assert row.activity_json["resource_guard"]["state"] == "protected"
        assert row.activity_json["resource_guard"]["host_available_bytes"] == 500 << 20
    monkeypatch.setenv("WORKER_RESOURCE_GUARD_ENABLED", "true")
    monkeypatch.setattr(resource_monitor, "_monitor", monitor)
    assert resource_monitor.current_resource_decision().action is ResourceAction.STOP
    monkeypatch.setattr(resource_monitor.time, "monotonic", lambda: 91)
    assert resource_monitor.current_resource_decision().reasons == ("resource_monitor_stale",)


def test_resource_heartbeat_does_not_hide_active_child_in_component_room(factory):
    from apps.api.dy_api.routes.operations import _component_rows

    now = datetime.now(UTC)
    with factory() as session:
        session.add(JobRun(job_id="active", job_name="date_sync", status="running", started_at=now))
        session.flush()
        session.add_all([
            ComponentHeartbeat(component_instance_id="supervisor", component_type="worker", status="healthy",
                               last_heartbeat_at=now - timedelta(seconds=1), current_job_id="active", rss_bytes=123),
            ComponentHeartbeat(component_instance_id="worker-resource-monitor-new", component_type="worker", status="draining",
                               last_heartbeat_at=now, activity_json={"resource_guard": {"state": "protected"}}),
        ])
        session.commit()
        worker = next(row for row in _component_rows(session, now) if row["component_type"] == "worker")
        assert worker["current_job_id"] == "active"
        assert worker["resources"]["rss_bytes"] == 123
        assert worker["observed_status"] == "draining"
