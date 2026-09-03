from __future__ import annotations

from apps.worker import scheduler


def test_scheduler_consumes_settlement_queue_when_auto_sync_is_paused(
    monkeypatch,
) -> None:
    factory = object()
    calls: list[str] = []

    monkeypatch.setattr(scheduler, "get_session_factory", lambda: factory)
    monkeypatch.setattr(scheduler, "_auto_sync_enabled", lambda _factory: False)
    monkeypatch.setattr(
        scheduler,
        "process_queued_settlement_rebuilds",
        lambda _factory: calls.append("settlement"),
    )
    monkeypatch.setattr(
        scheduler,
        "process_queued_finance_dispute_detections",
        lambda _factory: calls.append("finance"),
    )
    monkeypatch.setattr(scheduler, "drain_ready_daily_children", lambda _factory: ())

    def stop_after_sleep(_seconds: float) -> None:
        scheduler._STOP = True

    monkeypatch.setattr(scheduler, "_sleep_until_stop", stop_after_sleep)
    monkeypatch.setattr(scheduler, "_STOP", False)
    monkeypatch.delenv("WORKER_RUN_ONCE", raising=False)

    scheduler.main()

    assert calls == ["settlement", "finance"]
