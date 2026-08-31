from __future__ import annotations

import os
import signal
from pathlib import Path

import pytest


GIB = 1024**3


def test_backend_aweme_export_holds_shared_marker_during_worker_execution(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from apps.worker.browser_exports import active_marker, backend_aweme

    marker = tmp_path / "browser-export.active"
    monkeypatch.setattr(active_marker, "FIXED_BROWSER_EXPORT_ACTIVE_FILE", marker)
    monkeypatch.delenv("BROWSER_EXPORT_ACTIVE_FILE", raising=False)
    observed_tokens: list[str] = []

    def parse_workbook(_path: Path) -> list[dict[str, object]]:
        assert marker.is_file()
        observed_tokens.append(marker.read_text(encoding="ascii"))
        return []

    expected = object()
    monkeypatch.setattr(backend_aweme, "parse_backend_aweme_workbook", parse_workbook)
    monkeypatch.setattr(
        backend_aweme,
        "upsert_backend_aweme_records",
        lambda *_args, **_kwargs: expected,
    )

    result = backend_aweme.run_backend_aweme_export(
        object(),
        source_run_id="worker-export",
        workbook_path=tmp_path / "input.xlsx",
    )

    assert result is expected
    assert observed_tokens and observed_tokens[0].startswith(f"{os.getpid()}:")
    assert not marker.exists()


def test_backend_aweme_export_cleans_shared_marker_after_exception(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from apps.worker.browser_exports import active_marker, backend_aweme

    marker = tmp_path / "browser-export.active"
    monkeypatch.setattr(active_marker, "FIXED_BROWSER_EXPORT_ACTIVE_FILE", marker)
    monkeypatch.setenv("BROWSER_EXPORT_ACTIVE_FILE", str(marker))

    def fail_while_active(_path: Path) -> list[dict[str, object]]:
        assert marker.is_file()
        raise RuntimeError("export failed")

    monkeypatch.setattr(backend_aweme, "parse_backend_aweme_workbook", fail_while_active)

    with pytest.raises(RuntimeError, match="export failed"):
        backend_aweme.run_backend_aweme_export(
            object(),
            source_run_id="worker-export",
            workbook_path=tmp_path / "input.xlsx",
        )

    assert not marker.exists()


def test_browser_export_marker_is_atomic_and_does_not_remove_another_owner(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from apps.worker.browser_exports import active_marker

    marker = tmp_path / "browser-export.active"
    marker.write_text("existing-owner\n", encoding="ascii")
    monkeypatch.setattr(active_marker, "FIXED_BROWSER_EXPORT_ACTIVE_FILE", marker)
    monkeypatch.setenv("BROWSER_EXPORT_ACTIVE_FILE", str(marker))

    with pytest.raises(active_marker.BrowserExportActiveError, match="already active"):
        with active_marker.browser_export_active():
            raise AssertionError("an existing marker must fail closed")

    assert marker.read_text(encoding="ascii") == "existing-owner\n"


def test_browser_export_marker_rejects_non_fixed_override(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from apps.worker.browser_exports import active_marker

    marker = tmp_path / "browser-export.active"
    monkeypatch.setattr(active_marker, "FIXED_BROWSER_EXPORT_ACTIVE_FILE", marker)
    monkeypatch.setenv("BROWSER_EXPORT_ACTIVE_FILE", str(tmp_path / "other.active"))

    with pytest.raises(
        active_marker.BrowserExportMarkerConfigurationError,
        match="must be /run/browser/browser-export.active",
    ):
        with active_marker.browser_export_active():
            raise AssertionError("a non-fixed marker path must fail closed")


def test_browser_export_marker_cleans_on_signal_and_restores_handler(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from apps.worker.browser_exports import active_marker

    marker = tmp_path / "browser-export.active"
    monkeypatch.setattr(active_marker, "FIXED_BROWSER_EXPORT_ACTIVE_FILE", marker)
    monkeypatch.setenv("BROWSER_EXPORT_ACTIVE_FILE", str(marker))
    previous_handler = signal.getsignal(signal.SIGTERM)

    with pytest.raises(SystemExit) as raised:
        with active_marker.browser_export_active():
            installed_handler = signal.getsignal(signal.SIGTERM)
            assert callable(installed_handler)
            installed_handler(signal.SIGTERM, None)

    assert raised.value.code == 128 + signal.SIGTERM
    assert not marker.exists()
    assert signal.getsignal(signal.SIGTERM) == previous_handler


def test_browser_export_marker_preserves_worker_drain_until_export_finishes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from apps.worker.browser_exports import active_marker

    marker = tmp_path / "browser-export.active"
    monkeypatch.setattr(active_marker, "FIXED_BROWSER_EXPORT_ACTIVE_FILE", marker)
    monkeypatch.setenv("BROWSER_EXPORT_ACTIVE_FILE", str(marker))
    original_handler = signal.getsignal(signal.SIGTERM)
    drain_calls: list[int] = []

    def request_drain(signum: int, _frame) -> None:
        drain_calls.append(signum)

    signal.signal(signal.SIGTERM, request_drain)
    try:
        with active_marker.browser_export_active():
            installed_handler = signal.getsignal(signal.SIGTERM)
            assert callable(installed_handler)
            installed_handler(signal.SIGTERM, None)
            assert drain_calls == [signal.SIGTERM]
            assert marker.is_file()
    finally:
        signal.signal(signal.SIGTERM, original_handler)

    assert not marker.exists()


def test_process_tree_rss_includes_children_but_not_unrelated_processes(tmp_path: Path) -> None:
    from apps.ops_agent.resources import read_process_tree_rss_bytes

    statuses = {
        100: "Name:\troot\nPid:\t100\nPPid:\t1\nVmRSS:\t1024 kB\n",
        101: "Name:\tchild\nPid:\t101\nPPid:\t100\nVmRSS:\t2048 kB\n",
        102: "Name:\tgrandchild\nPid:\t102\nPPid:\t101\nVmRSS:\t4096 kB\n",
        200: "Name:\tother\nPid:\t200\nPPid:\t1\nVmRSS:\t8192 kB\n",
    }
    for pid, status in statuses.items():
        directory = tmp_path / str(pid)
        directory.mkdir()
        (directory / "status").write_text(status, encoding="utf-8")

    assert read_process_tree_rss_bytes(100, proc_root=tmp_path) == 7168 * 1024


def test_meminfo_and_cgroup_v2_metrics_are_parsed_without_using_swap_as_capacity(
    tmp_path: Path,
) -> None:
    from apps.ops_agent.resources import parse_meminfo, read_cgroup_memory

    host = parse_meminfo(
        "MemTotal:       8388608 kB\n"
        "MemAvailable:   1572864 kB\n"
        "SwapTotal:      2097152 kB\n"
        "SwapFree:       1048576 kB\n"
    )
    assert host.total_bytes == 8 * GIB
    assert host.available_bytes == 1536 * 1024**2
    assert host.swap_used_bytes == GIB

    (tmp_path / "memory.current").write_text(str(2 * GIB), encoding="ascii")
    (tmp_path / "memory.max").write_text(str(3 * GIB), encoding="ascii")
    (tmp_path / "memory.swap.current").write_text(str(256 * 1024**2), encoding="ascii")
    (tmp_path / "memory.swap.max").write_text("max", encoding="ascii")
    cgroup = read_cgroup_memory(cgroup_root=tmp_path)
    assert cgroup is not None
    assert cgroup.current_bytes == 2 * GIB
    assert cgroup.limit_bytes == 3 * GIB
    assert cgroup.swap_current_bytes == 256 * 1024**2
    assert cgroup.swap_limit_bytes is None


def test_cgroup_v1_swap_is_derived_from_memsw_minus_memory(tmp_path: Path) -> None:
    from apps.ops_agent.resources import read_cgroup_memory

    memory = tmp_path / "memory"
    memory.mkdir()
    (memory / "memory.usage_in_bytes").write_text(str(2 * GIB), encoding="ascii")
    (memory / "memory.limit_in_bytes").write_text(str(3 * GIB), encoding="ascii")
    (memory / "memory.memsw.usage_in_bytes").write_text(
        str(2 * GIB + 256 * 1024**2), encoding="ascii"
    )
    (memory / "memory.memsw.limit_in_bytes").write_text(str(4 * GIB), encoding="ascii")

    cgroup = read_cgroup_memory(cgroup_root=tmp_path)

    assert cgroup is not None
    assert cgroup.current_bytes == 2 * GIB
    assert cgroup.limit_bytes == 3 * GIB
    assert cgroup.swap_current_bytes == 256 * 1024**2
    assert cgroup.swap_limit_bytes == GIB


def test_resource_thresholds_are_configurable_and_require_warn_below_stop() -> None:
    from apps.ops_agent.resources import ResourceThresholds

    thresholds = ResourceThresholds.from_env(
        {
            "WORKER_RESOURCE_WARN_HOST_USED_BYTES": "100",
            "WORKER_RESOURCE_STOP_HOST_USED_BYTES": "200",
            "WORKER_RESOURCE_MAX_PROCESS_TREE_RSS_BYTES": "300",
            "WORKER_RESOURCE_MAX_CGROUP_CURRENT_BYTES": "400",
            "WORKER_RESOURCE_MAX_SWAP_USED_BYTES": "0",
        }
    )
    assert thresholds.warn_host_used_bytes == 100
    assert thresholds.stop_host_used_bytes == 200
    assert thresholds.max_process_tree_rss_bytes == 300
    assert thresholds.max_cgroup_current_bytes == 400
    assert thresholds.max_swap_used_bytes == 0

    with pytest.raises(ValueError, match="below stop"):
        ResourceThresholds.from_env(
            {
                "WORKER_RESOURCE_WARN_HOST_USED_BYTES": "200",
                "WORKER_RESOURCE_STOP_HOST_USED_BYTES": "200",
            }
        )


def test_resource_guard_drains_then_stops_at_configured_host_thresholds() -> None:
    from apps.ops_agent.resources import (
        CgroupMemory,
        HostMemory,
        ResourceAction,
        ResourceSnapshot,
        ResourceThresholds,
        evaluate_resource_guard,
    )

    thresholds = ResourceThresholds(
        warn_host_used_bytes=6 * GIB,
        stop_host_used_bytes=int(6.4 * GIB),
        max_process_tree_rss_bytes=2 * GIB,
        max_cgroup_current_bytes=3 * GIB,
        max_swap_used_bytes=0,
    )
    warn = ResourceSnapshot(
        process_tree_rss_bytes=1 * GIB,
        host=HostMemory(
            total_bytes=8 * GIB,
            available_bytes=int(1.9 * GIB),
            swap_total_bytes=2 * GIB,
            swap_free_bytes=2 * GIB,
        ),
        cgroup=CgroupMemory(2 * GIB, 3 * GIB, 0, None),
    )
    stop = ResourceSnapshot(
        process_tree_rss_bytes=1 * GIB,
        host=HostMemory(
            total_bytes=8 * GIB,
            available_bytes=int(1.5 * GIB),
            swap_total_bytes=2 * GIB,
            swap_free_bytes=2 * GIB,
        ),
        cgroup=CgroupMemory(2 * GIB, 3 * GIB, 0, None),
    )
    swap = ResourceSnapshot(
        process_tree_rss_bytes=1 * GIB,
        host=HostMemory(
            total_bytes=8 * GIB,
            available_bytes=3 * GIB,
            swap_total_bytes=2 * GIB,
            swap_free_bytes=1 * GIB,
        ),
        cgroup=CgroupMemory(2 * GIB, 3 * GIB, 0, None),
    )

    assert evaluate_resource_guard(warn, thresholds).action is ResourceAction.DRAIN
    assert evaluate_resource_guard(stop, thresholds).action is ResourceAction.STOP
    assert evaluate_resource_guard(swap, thresholds).action is ResourceAction.DRAIN


def test_supervisor_resource_guard_stops_claiming_before_child_start(monkeypatch) -> None:
    from apps.ops_agent.resources import ResourceAction, ResourceDecision
    from apps.worker import subprocess_supervisor

    monkeypatch.setenv("WORKER_RESOURCE_GUARD_ENABLED", "true")
    monkeypatch.setattr(
        subprocess_supervisor,
        "worker_resource_decision",
        lambda: ResourceDecision(ResourceAction.STOP, ("host_stop_threshold",)),
    )
    popen_calls = []

    def popen(*_args, **_kwargs):
        popen_calls.append(True)
        raise AssertionError("child must not start")

    supervisor = subprocess_supervisor.SubprocessSupervisor(
        popen_factory=popen,
        poll_interval_seconds=0,
        graceful_timeout_seconds=0.1,
    )
    result = supervisor.run(job_id="job-1", command=["python", "-c", "pass"])

    assert result.status is subprocess_supervisor.ChildRunStatus.CONTROL_ERROR
    assert result.attempts == 0
    assert result.termination_reason is subprocess_supervisor.ChildTerminationReason.RSS_GUARD
    assert popen_calls == []


def test_supervisor_resource_guard_fails_closed_on_invalid_threshold(monkeypatch) -> None:
    from apps.ops_agent.resources import ResourceAction
    from apps.worker import subprocess_supervisor

    monkeypatch.setenv("WORKER_RESOURCE_GUARD_ENABLED", "true")
    monkeypatch.setenv("WORKER_RESOURCE_STOP_HOST_USED_BYTES", "not-a-byte-count")

    decision = subprocess_supervisor.worker_resource_decision()

    assert decision.action is ResourceAction.STOP
    assert decision.reasons == ("resource_guard_configuration_invalid",)
