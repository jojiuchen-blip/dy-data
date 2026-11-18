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
                        lambda passed: calls.append(("follow_up", passed)))
    monkeypatch.setattr(scheduler, "run_once", lambda: calls.append(("legacy", factory)))
    monkeypatch.setattr(scheduler, "_run_priority_tick_with_maintenance", lambda passed: calls.append(("priority_daily", passed)))
    if mode == "legacy":
        scheduler._run_legacy_scheduler(factory, run_once_only=True, run_on_start=False)
    else:
        scheduler._run_priority_daily_ticks(factory)
    assert calls == [("follow_up", factory), (mode, factory)]
