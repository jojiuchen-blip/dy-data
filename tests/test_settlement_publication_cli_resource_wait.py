"""CLI observation budgets must encompass the real protected-policy dwell."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from apps.ops_agent.resources import (
    GIB, CgroupMemory, HostMemory, PressureThresholds, ResourceAction,
    ResourceDecision, ResourcePressurePolicy, ResourceSnapshot,
)
from apps.worker.resource_monitor import SAMPLE_SECONDS


class ControlledClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        assert seconds == 1
        self.now += seconds


class SampledPolicyMonitor:
    """Drive the unmodified pressure policy with deterministic 5-second samples."""

    def __init__(self, clock: ControlledClock, *, healthy: bool = True) -> None:
        self.clock = clock
        self.healthy = healthy
        self.thresholds = PressureThresholds.from_env()
        self.policy = ResourcePressurePolicy(self.thresholds, initial_state="protected")
        self.next_sample = 0.0
        self.states: list[tuple[float, str]] = []
        self.stopped = 0
        self.latest_state = None

    def decision(self) -> ResourceDecision:
        while self.next_sample <= self.clock.now:
            snapshot = ResourceSnapshot(
                process_tree_rss_bytes=GIB // 4,
                host=HostMemory(8 * GIB, 4 * GIB if self.healthy else GIB // 2, 2 * GIB, 2 * GIB),
                cgroup=CgroupMemory(GIB, 4 * GIB, 0, 2 * GIB),
                swap_activity_bytes_per_second=0,
            )
            self.latest_state = self.policy.update(snapshot, now=self.next_sample)
            self.states.append((self.next_sample, self.latest_state.state))
            self.next_sample += SAMPLE_SECONDS
        assert self.latest_state is not None
        if not self.latest_state.allow_daily:
            return ResourceDecision(ResourceAction.STOP, self.latest_state.reasons)
        if not self.latest_state.allow_history:
            return ResourceDecision(ResourceAction.DRAIN, self.latest_state.reasons)
        return ResourceDecision(ResourceAction.ALLOW, self.latest_state.reasons)

    def stop(self) -> None:
        self.stopped += 1


@pytest.fixture()
def cli_harness(monkeypatch):
    for key in os.environ:
        if key.startswith("WORKER_RESOURCE_PRESSURE_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("WORKER_RESOURCE_GUARD_ENABLED", "true")
    path = Path(__file__).resolve().parents[1] / "scripts/ops/publish_settlement_authority.py"
    spec = importlib.util.spec_from_file_location("publication_cli_resource_wait", path)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    clock = ControlledClock()
    factory = object()
    monitors: list[SampledPolicyMonitor] = []
    calls = []
    behavior = {"healthy": True}
    monkeypatch.setattr(cli, "time", SimpleNamespace(monotonic=clock.monotonic, sleep=clock.sleep))
    monkeypatch.setattr(cli, "get_session_factory", lambda: factory)

    def start_monitor(actual_factory):
        assert actual_factory is factory
        monitor = SampledPolicyMonitor(clock, healthy=behavior["healthy"])
        monitors.append(monitor)
        monitor.decision()
        return monitor

    def formal_service(actual_factory, *, months, preview_hash):
        assert actual_factory is factory
        assert monitors[-1].decision().action is ResourceAction.ALLOW
        calls.append({"at": clock.now, "months": months, "preview_hash": preview_hash})
        return {"protocol": cli.PROTOCOL, "status": "success", "job_id": "synthetic-formal-publication"}

    monkeypatch.setattr(cli, "start_resource_monitor", start_monitor)
    monkeypatch.setattr(cli, "current_resource_decision", lambda: monitors[-1].decision())
    monkeypatch.setattr(cli, "apply_settlement_publication", formal_service)
    return SimpleNamespace(cli=cli, clock=clock, monitors=monitors, calls=calls, behavior=behavior)


def apply_arguments(*extra: str) -> list[str]:
    return ["--month", "2026-08", "--month", "2026-09", "--apply", "--preview-hash", "a" * 64, *extra]


def test_default_wait_admits_only_after_real_default_780_second_healthy_window(cli_harness, capsys):
    harness = cli_harness
    assert harness.cli.main(apply_arguments()) == 0
    assert harness.calls == [{"at": 780.0, "months": ("2026-08", "2026-09"), "preview_hash": "a" * 64}]
    monitor = harness.monitors[0]
    assert monitor.states[0] == (0.0, "protected")
    assert (175.0, "protected") in monitor.states
    assert (180.0, "recovering") in monitor.states
    assert (775.0, "recovering") in monitor.states
    assert monitor.states[-1] == (780.0, "normal")
    assert monitor.stopped == 1
    assert json.loads(capsys.readouterr().out)["status"] == "success"


@pytest.mark.parametrize("wait", [0, 90, 600])
def test_explicit_short_wait_refuses_without_formal_service(cli_harness, capsys, wait):
    harness = cli_harness
    assert harness.cli.main(apply_arguments("--admission-wait-seconds", str(wait))) == 1
    assert harness.clock.now == wait
    assert harness.calls == []
    assert harness.monitors[0].stopped == 1
    assert json.loads(capsys.readouterr().out)["status"] == "not_admitted"


def test_persistently_unhealthy_resources_exhaust_bounded_default_without_service(cli_harness, capsys):
    harness = cli_harness
    harness.behavior["healthy"] = False
    assert harness.cli.main(apply_arguments()) == 1
    assert harness.clock.now == 900
    assert harness.calls == []
    assert all(state == "protected" for _, state in harness.monitors[0].states)
    assert harness.monitors[0].stopped == 1
    assert json.loads(capsys.readouterr().out)["status"] == "not_admitted"


@pytest.mark.parametrize("suffix", ["DURATION_SECONDS", "SECONDS"])
def test_default_wait_honors_configured_recovery_and_stable_windows(cli_harness, monkeypatch, suffix):
    harness = cli_harness
    monkeypatch.setenv(f"WORKER_RESOURCE_PRESSURE_RECOVERY_{suffix}", "240")
    monkeypatch.setenv(f"WORKER_RESOURCE_PRESSURE_STABLE_{suffix}", "960")
    assert harness.cli.main(apply_arguments()) == 0
    assert harness.calls[0]["at"] == 1200
    assert harness.monitors[0].stopped == 1


def test_explicit_maximum_wait_preserves_full_policy_admission(cli_harness):
    harness = cli_harness
    assert harness.cli.main(apply_arguments("--admission-wait-seconds", "1800")) == 0
    assert harness.calls[0]["at"] == 780
    assert harness.monitors[0].stopped == 1


@pytest.mark.parametrize("value", ["-1", "1801", "100000000000000000000", "nan", "1.5"])
def test_invalid_wait_is_rejected_before_monitor_or_service(cli_harness, value):
    harness = cli_harness
    with pytest.raises(SystemExit) as error:
        harness.cli.main(apply_arguments("--admission-wait-seconds", value))
    assert error.value.code == 2
    assert harness.monitors == harness.calls == []
    assert harness.clock.now == 0


def test_oversized_configured_window_fails_before_monitor_without_silent_clamp(cli_harness, monkeypatch):
    harness = cli_harness
    monkeypatch.setenv("WORKER_RESOURCE_PRESSURE_RECOVERY_DURATION_SECONDS", "1000")
    monkeypatch.setenv("WORKER_RESOURCE_PRESSURE_STABLE_DURATION_SECONDS", "1000")
    with pytest.raises(SystemExit) as error:
        harness.cli.main(apply_arguments())
    assert error.value.code == 2
    assert harness.monitors == harness.calls == []


def test_explicit_short_budget_can_refuse_even_when_configured_window_exceeds_cap(cli_harness, monkeypatch, capsys):
    harness = cli_harness
    monkeypatch.setenv("WORKER_RESOURCE_PRESSURE_RECOVERY_DURATION_SECONDS", "1000")
    monkeypatch.setenv("WORKER_RESOURCE_PRESSURE_STABLE_DURATION_SECONDS", "1000")
    assert harness.cli.main(apply_arguments("--admission-wait-seconds", "90")) == 1
    assert harness.clock.now == 90
    assert harness.calls == []
    assert harness.monitors[0].stopped == 1
    assert json.loads(capsys.readouterr().out)["status"] == "not_admitted"


def test_invalid_policy_is_rejected_without_service(cli_harness, monkeypatch, capsys):
    harness = cli_harness
    monkeypatch.setenv("WORKER_RESOURCE_PRESSURE_STABLE_DURATION_SECONDS", "nan")
    assert harness.cli.main(apply_arguments()) == 1
    assert harness.monitors == harness.calls == []
    assert json.loads(capsys.readouterr().err)["error_type"] == "ValueError"


def test_dry_run_does_not_start_monitor_or_read_pressure_windows(cli_harness, monkeypatch, capsys):
    harness = cli_harness
    monkeypatch.setenv("WORKER_RESOURCE_PRESSURE_STABLE_DURATION_SECONDS", "not-a-duration")
    preview_calls = []
    def preview(factory, *, months):
        preview_calls.append(months)
        return {"protocol": harness.cli.PROTOCOL, "preview_hash": "b" * 64}
    monkeypatch.setattr(harness.cli, "preview_settlement_publication", preview)
    assert harness.cli.main(["--month", "2026-08"]) == 0
    assert preview_calls == [("2026-08",)]
    assert harness.monitors == harness.calls == []
    assert json.loads(capsys.readouterr().out)["status"] == "dry_run"
