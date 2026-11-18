"""Product deadlines remain wired in both scheduler modes and one-shot runs."""

import pytest

from apps.worker import clue_follow_up_state, scheduler


@pytest.mark.parametrize("mode", ["legacy", "priority_daily"])
def test_main_starts_independent_follow_up_consumer_in_each_scheduler_mode(monkeypatch, mode):
    threads = []
    class Thread:
        def __init__(self, **kwargs):
            self.options = kwargs
            self.started = False
            threads.append(self)
        def start(self):
            self.started = True
        def is_alive(self):
            return False
    monkeypatch.setattr(scheduler, "Thread", Thread)
    monkeypatch.setattr(scheduler.signal, "signal", lambda *_: None)
    monkeypatch.setattr(scheduler, "get_session_factory", lambda: object())
    monkeypatch.setattr(scheduler, "resolve_scheduler_mode", lambda: mode)
    monkeypatch.setattr(scheduler, "_run_priority_daily_mode", lambda *_: None)
    monkeypatch.setattr(scheduler, "_run_legacy_scheduler", lambda *_, **__: None)
    from apps.worker import resource_monitor
    monkeypatch.setattr(resource_monitor, "start_resource_monitor", lambda *_: None)
    monkeypatch.delenv("WORKER_RUN_ONCE", raising=False)
    scheduler.main()
    assert len(threads) == 1 and threads[0].started
    assert threads[0].options["target"] is scheduler._clue_follow_up_loop
    assert threads[0].options["name"] == "clue-follow-up-transitions"
    assert threads[0].options["args"][1].is_set()


def test_deadline_loop_consumes_a_bounded_batch_before_waiting(monkeypatch):
    calls = []
    class Stop:
        stopped = False
        def is_set(self):
            return self.stopped
        def wait(self, seconds):
            calls.append(seconds)
            self.stopped = True
    factory = object()
    monkeypatch.setattr(scheduler, "_STOP", False)
    monkeypatch.setattr(clue_follow_up_state, "run_product_follow_up_batch",
                        lambda passed: calls.append(passed) or {"processed": 0})
    scheduler._clue_follow_up_loop(factory, Stop())
    assert calls == [factory, 60]


@pytest.mark.parametrize("mode", ["legacy", "priority_daily"])
def test_one_shot_scheduler_runs_product_deadlines_once(monkeypatch, mode):
    calls = []
    factory = object()
    monkeypatch.setenv("WORKER_RUN_ONCE", "true")
    monkeypatch.setattr(clue_follow_up_state, "run_product_follow_up_batch",
                        lambda passed: calls.append(("follow_up", passed)) or {"processed": 0, "failed": 0})
    monkeypatch.setattr(scheduler, "run_once", lambda: calls.append(("legacy", factory)))
    monkeypatch.setattr(scheduler, "_run_priority_tick_with_maintenance", lambda passed: calls.append(("priority_daily", passed)))
    if mode == "legacy":
        scheduler._run_legacy_scheduler(factory, run_once_only=True, run_on_start=False)
    else:
        scheduler._run_priority_daily_ticks(factory)
    assert calls == [("follow_up", factory), (mode, factory)]


@pytest.mark.parametrize("mode", ["legacy", "priority_daily"])
@pytest.mark.parametrize("error_type", [RuntimeError, TypeError])
@pytest.mark.parametrize("maintenance_consumed", [False, True])
def test_one_shot_deadline_failure_is_logged_without_aborting_maintenance_budget(
    monkeypatch, capsys, mode, error_type, maintenance_consumed,
):
    from apps.ops_agent.resources import ResourceAction, ResourceDecision
    from apps.worker import priority_scheduler, resource_monitor

    factory = object()
    calls = []
    def broken(passed):
        assert passed is factory
        calls.append("follow_up")
        raise error_type("private database token must not be logged")
    monkeypatch.setenv("WORKER_RUN_ONCE", "true")
    monkeypatch.setattr(clue_follow_up_state, "run_product_follow_up_batch", broken)
    monkeypatch.setattr(resource_monitor, "current_resource_decision", lambda: ResourceDecision(ResourceAction.ALLOW, ()))
    monkeypatch.setattr(scheduler, "_process_queued_jobs", lambda _factory: calls.append("maintenance") or maintenance_consumed)
    monkeypatch.setattr(priority_scheduler, "run_priority_daily_tick", lambda _factory: calls.append("priority"))
    monkeypatch.setattr(scheduler, "run_once", lambda: calls.append("legacy"))
    if mode == "legacy":
        scheduler._run_legacy_scheduler(factory, run_once_only=True, run_on_start=False)
        assert calls == ["follow_up", "legacy"]
    else:
        scheduler._run_priority_daily_ticks(factory)
        assert calls == (["follow_up", "maintenance"] if maintenance_consumed
                         else ["follow_up", "maintenance", "priority"])
    output = capsys.readouterr().out
    assert output.count(f"clue_follow_up_failed type={error_type.__name__}") == 1
    assert "private database token" not in output
    assert "clue_follow_up_result" not in output


def test_resident_deadline_consumer_retries_after_an_observable_failure(monkeypatch, capsys):
    calls, waits = [], []
    class Stop:
        def is_set(self):
            return len(waits) == 2
        def wait(self, seconds):
            waits.append(seconds)
    def recover(passed):
        calls.append(passed)
        if len(calls) == 1:
            raise RuntimeError("private source payload")
        return {"processed": 1, "failed": 0}
    factory = object()
    monkeypatch.setattr(scheduler, "_STOP", False)
    monkeypatch.setattr(clue_follow_up_state, "run_product_follow_up_batch", recover)
    scheduler._clue_follow_up_loop(factory, Stop())
    assert calls == [factory, factory] and waits == [60, 60]
    output = capsys.readouterr().out
    assert output.count("clue_follow_up_failed type=RuntimeError") == 1
    assert 'clue_follow_up_result {"failed": 0, "processed": 1}' in output
    assert "private source payload" not in output


@pytest.mark.parametrize("action", ["drain", "stop"])
def test_deadline_failure_does_not_override_resource_pressure_rules(monkeypatch, capsys, action):
    from apps.ops_agent.resources import ResourceAction, ResourceDecision
    from apps.worker import priority_scheduler, resource_monitor, settlement_maintenance

    calls = []
    def fail(_factory):
        raise RuntimeError("private connection failure")
    monkeypatch.setenv("WORKER_RUN_ONCE", "true")
    monkeypatch.setattr(clue_follow_up_state, "run_product_follow_up_batch", fail)
    monkeypatch.setattr(resource_monitor, "current_resource_decision", lambda: ResourceDecision(ResourceAction(action), ()))
    monkeypatch.setattr(settlement_maintenance, "process_automatic_settlement_maintenance", lambda *_args, **_kwargs: calls.append("maintenance") or False)
    monkeypatch.setattr(scheduler, "ensure_month_close_job", lambda *_: pytest.fail("monthly work during resource pressure"))
    monkeypatch.setattr(scheduler, "process_queued_settlement_rebuilds", lambda *_: pytest.fail("rebuild during resource pressure"))
    monkeypatch.setattr(scheduler, "process_queued_finance_dispute_detections", lambda *_, **__: pytest.fail("finance detection during resource pressure"))
    monkeypatch.setattr(priority_scheduler, "run_priority_daily_tick", lambda _factory: calls.append("priority_admission"))
    scheduler._run_priority_daily_ticks(object())
    assert calls == (["maintenance", "priority_admission"] if action == "drain" else [])
    assert "clue_follow_up_failed type=RuntimeError" in capsys.readouterr().out


@pytest.mark.parametrize("mode", ["legacy", "priority_daily"])
def test_main_once_keeps_maintenance_running_after_real_batch_factory_failure(monkeypatch, capsys, mode):
    from apps.ops_agent.resources import ResourceAction, ResourceDecision
    from apps.worker import resource_monitor

    calls = []
    class UnavailableDatabase:
        def __call__(self):
            calls.append("follow_up")
            raise OSError("private database credentials")
    class Thread:
        def __init__(self, **_kwargs):
            pass
        def start(self):
            pytest.fail("once mode must not start resident consumers")
        def is_alive(self):
            return False
    factory = UnavailableDatabase()
    monkeypatch.setenv("WORKER_RUN_ONCE", "true")
    monkeypatch.setenv("WORKER_RUN_ON_START", "false")
    monkeypatch.setattr(scheduler.signal, "signal", lambda *_args: None)
    monkeypatch.setattr(scheduler, "Thread", Thread)
    monkeypatch.setattr(scheduler, "get_session_factory", lambda: factory)
    monkeypatch.setattr(scheduler, "resolve_scheduler_mode", lambda: mode)
    monkeypatch.setattr(resource_monitor, "start_resource_monitor", lambda _factory: None)
    monkeypatch.setattr(resource_monitor, "current_resource_decision", lambda: ResourceDecision(ResourceAction.ALLOW, ()))
    monkeypatch.setattr(scheduler, "_process_queued_jobs", lambda _factory: calls.append("maintenance") or True)
    # The real product batch calls the unavailable session factory. Both
    # production dispatch paths must still reach the original queue budget.
    scheduler.main()
    assert calls == ["follow_up", "maintenance"]
    output = capsys.readouterr().out
    assert output.count("clue_follow_up_failed type=OSError") == 1
    assert "private database credentials" not in output
