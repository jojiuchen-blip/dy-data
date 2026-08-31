from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_benchmark_fixture_is_deterministic_and_records_exact_scale(tmp_path: Path) -> None:
    from scripts.ops.generate_sync_benchmark_fixture import FixtureConfig, generate_fixture

    config = FixtureConfig(days=3, stores=4, orders_per_day=5, seed=58)
    first = generate_fixture(tmp_path / "first", config)
    second = generate_fixture(tmp_path / "second", config)

    assert first.row_count == second.row_count == 60
    assert first.sha256 == second.sha256
    assert first.partition_count == second.partition_count == 12
    assert (tmp_path / "first" / "orders.jsonl").read_bytes() == (
        tmp_path / "second" / "orders.jsonl"
    ).read_bytes()
    persisted = json.loads((tmp_path / "first" / "manifest.json").read_text(encoding="utf-8"))
    assert persisted["config"] == {
        "days": 3,
        "orders_per_day": 5,
        "seed": 58,
        "stores": 4,
    }


def test_fixture_requires_explicit_overwrite(tmp_path: Path) -> None:
    from scripts.ops.generate_sync_benchmark_fixture import FixtureConfig, generate_fixture

    destination = tmp_path / "fixture"
    config = FixtureConfig(days=1, stores=1, orders_per_day=1)
    generate_fixture(destination, config)
    with pytest.raises(FileExistsError, match="overwrite"):
        generate_fixture(destination, config)


def test_incremental_and_shadow_checksums_are_batch_and_order_independent(tmp_path: Path) -> None:
    from scripts.ops.generate_sync_benchmark_fixture import FixtureConfig, generate_fixture
    from scripts.ops.run_sync_benchmark import run_benchmark

    fixture = tmp_path / "fixture"
    generate_fixture(fixture, FixtureConfig(days=4, stores=3, orders_per_day=7, seed=7))

    small = run_benchmark(fixture, batch_size=1)
    large = run_benchmark(fixture, batch_size=17)

    assert small.row_count == large.row_count == 84
    assert small.result_checksum == small.shadow_checksum
    assert large.result_checksum == large.shadow_checksum
    assert small.result_checksum == large.result_checksum
    assert small.input_sha256 == large.input_sha256


def test_crash_checkpoint_resume_matches_uninterrupted_result(tmp_path: Path) -> None:
    from scripts.ops.generate_sync_benchmark_fixture import FixtureConfig, generate_fixture
    from scripts.ops.run_sync_benchmark import BenchmarkInterrupted, run_benchmark

    fixture = tmp_path / "fixture"
    checkpoint = tmp_path / "checkpoint.json"
    generate_fixture(fixture, FixtureConfig(days=5, stores=2, orders_per_day=6, seed=99))
    baseline = run_benchmark(fixture, batch_size=8)

    with pytest.raises(BenchmarkInterrupted, match="injected"):
        run_benchmark(
            fixture,
            batch_size=8,
            checkpoint_path=checkpoint,
            crash_after_batches=2,
        )
    assert checkpoint.exists()

    resumed = run_benchmark(fixture, batch_size=8, checkpoint_path=checkpoint)

    assert resumed.resumed is True
    assert resumed.result_checksum == baseline.result_checksum
    assert resumed.shadow_checksum == baseline.shadow_checksum
    assert resumed.row_count == baseline.row_count
    assert not checkpoint.exists()


def test_acceptance_environment_requires_real_linux_4cpu_8gb() -> None:
    from scripts.ops.run_8gb_acceptance import AcceptanceEnvironment, evaluate_environment

    windows = evaluate_environment(
        AcceptanceEnvironment(
            platform="Windows",
            cpu_count=16,
            total_memory_bytes=32 * 1024**3,
        )
    )
    linux = evaluate_environment(
        AcceptanceEnvironment(
            platform="Linux",
            cpu_count=4,
            total_memory_bytes=8 * 1024**3,
        )
    )
    cloud_8gb = evaluate_environment(
        AcceptanceEnvironment(
            platform="Linux",
            cpu_count=4,
            total_memory_bytes=7_993_516_032,
        )
    )
    undersized = evaluate_environment(
        AcceptanceEnvironment(
            platform="Linux",
            cpu_count=4,
            total_memory_bytes=int(7.3 * 1024**3),
        )
    )

    assert windows.verified is False
    assert set(windows.reasons) == {
        "linux_required",
        "cpu_count_must_equal_4",
        "host_memory_must_be_8gb",
    }
    assert linux.verified is True
    assert linux.reasons == ()
    assert cloud_8gb.verified is True
    assert cloud_8gb.reasons == ()
    assert undersized.verified is False
    assert undersized.reasons == ("host_memory_must_be_8gb",)


def test_strict_acceptance_blocks_before_running_unverified_host(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts.ops.generate_sync_benchmark_fixture import FixtureConfig, generate_fixture
    from scripts.ops import run_8gb_acceptance as acceptance

    fixture = tmp_path / "fixture"
    generate_fixture(fixture, FixtureConfig(days=1, stores=1, orders_per_day=1))
    monkeypatch.setattr(
        acceptance,
        "run_benchmark",
        lambda *_args, **_kwargs: pytest.fail("unverified host must fail closed"),
    )

    with pytest.raises(acceptance.AcceptanceBlocked, match="4C/8GB Linux"):
        acceptance.run_acceptance(
            fixture,
            environment=acceptance.AcceptanceEnvironment(
                platform="Windows",
                cpu_count=16,
                total_memory_bytes=32 * 1024**3,
            ),
        )


def test_benchmark_report_records_swap_baseline_total_and_peak(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts.ops.run_sync_benchmark import HostMemory, ResourceSnapshot
    from scripts.ops.generate_sync_benchmark_fixture import FixtureConfig, generate_fixture
    from scripts.ops import run_sync_benchmark as benchmark

    fixture = tmp_path / "fixture"
    generate_fixture(fixture, FixtureConfig(days=1, stores=1, orders_per_day=2, seed=3))
    snapshots = iter(
        (
            ResourceSnapshot(
                process_tree_rss_bytes=20_000_000,
                host=HostMemory(
                    total_bytes=7_993_516_032,
                    available_bytes=3_600_000_000,
                    swap_total_bytes=2 * 1024**3,
                    swap_free_bytes=1_300_000_000,
                ),
                cgroup=None,
            ),
            ResourceSnapshot(
                process_tree_rss_bytes=21_000_000,
                host=HostMemory(
                    total_bytes=7_993_516_032,
                    available_bytes=3_500_000_000,
                    swap_total_bytes=2 * 1024**3,
                    swap_free_bytes=1_290_000_000,
                ),
                cgroup=None,
            ),
        )
    )
    monkeypatch.setattr(benchmark, "collect_resource_snapshot", lambda _pid: next(snapshots))

    report = benchmark.run_benchmark(fixture, batch_size=2)

    assert report.swap_total_bytes == 2 * 1024**3
    assert report.swap_used_start_bytes == 2 * 1024**3 - 1_300_000_000
    assert report.swap_used_peak_bytes == 2 * 1024**3 - 1_290_000_000


@pytest.mark.parametrize(
    ("swap_start", "swap_peak", "swap_total", "expected_status", "growth", "headroom"),
    (
        (768 * 1024**2, 768 * 1024**2, 2 * 1024**3, "GREEN", True, True),
        (768 * 1024**2, 769 * 1024**2, 2 * 1024**3, "FAILED", False, True),
        (1900 * 1024**2, 1900 * 1024**2, 2 * 1024**3, "FAILED", True, False),
        (0, 0, 0, "GREEN", True, True),
    ),
)
def test_acceptance_uses_swap_growth_and_headroom_not_absolute_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    swap_start: int,
    swap_peak: int,
    swap_total: int,
    expected_status: str,
    growth: bool,
    headroom: bool,
) -> None:
    from scripts.ops.generate_sync_benchmark_fixture import FixtureConfig, generate_fixture
    from scripts.ops.run_sync_benchmark import run_benchmark
    from scripts.ops import run_8gb_acceptance as acceptance

    fixture = tmp_path / "fixture"
    generate_fixture(fixture, FixtureConfig(days=1, stores=1, orders_per_day=2, seed=5))
    baseline = run_benchmark(fixture, batch_size=2)
    bounded = replace(
        baseline,
        process_tree_rss_peak_bytes=64 * 1024**2,
        host_used_peak_bytes=4 * 1024**3,
        swap_used_start_bytes=swap_start,
        swap_used_peak_bytes=swap_peak,
        swap_total_bytes=swap_total,
    )
    monkeypatch.setattr(acceptance, "run_benchmark", lambda *_args, **_kwargs: bounded)

    report = acceptance.run_acceptance(
        fixture,
        environment=acceptance.AcceptanceEnvironment(
            platform="Linux",
            cpu_count=4,
            total_memory_bytes=7_993_516_032,
        ),
        runs=3,
        batch_size=2,
    )

    assert report.status == expected_status
    assert report.checks["swap_not_growing"] is growth
    assert report.checks["swap_headroom_at_least_10_percent"] is headroom


def test_acceptance_requires_three_identical_runs_and_preserves_unverified_blocker(
    tmp_path: Path,
) -> None:
    from scripts.ops.generate_sync_benchmark_fixture import FixtureConfig, generate_fixture
    from scripts.ops.run_8gb_acceptance import AcceptanceEnvironment, run_acceptance

    fixture = tmp_path / "fixture"
    generate_fixture(fixture, FixtureConfig(days=2, stores=2, orders_per_day=4, seed=1))

    report = run_acceptance(
        fixture,
        environment=AcceptanceEnvironment(
            platform="Windows",
            cpu_count=8,
            total_memory_bytes=16 * 1024**3,
        ),
        runs=3,
        batch_size=3,
        permit_unverified_environment=True,
    )

    assert report.status == "UNVERIFIED"
    assert report.release_blocker is True
    assert len(report.runs) == 3
    assert len({run.result_checksum for run in report.runs}) == 1
    assert all(run.result_checksum == run.shadow_checksum for run in report.runs)


def test_candidate_acceptance_rejects_collecting_targets() -> None:
    from scripts.ops.run_daily_candidate_acceptance import parse_candidate_targets

    with pytest.raises(
        ValueError,
        match="targets must be clue_center and/or settlement",
    ):
        parse_candidate_targets("all")


def test_candidate_database_url_requires_explicit_safe_test_target() -> None:
    from scripts.ops.run_daily_candidate_acceptance import (
        get_test_database_url,
        validated_test_database_url,
    )

    with pytest.raises(RuntimeError, match="explicit T5.2 test database"):
        get_test_database_url({"DATABASE_URL": "postgresql+psycopg://app:secret@127.0.0.1:55432/test"})
    with pytest.raises(RuntimeError, match="loopback"):
        validated_test_database_url(
            "postgresql+psycopg://dydata_t52:secret@db.example.com:55432/dydata_t52"
        )
    with pytest.raises(RuntimeError, match="dedicated local port"):
        validated_test_database_url(
            "postgresql+psycopg://dydata_t52:secret@127.0.0.1:5432/dydata_t52"
        )
    with pytest.raises(RuntimeError, match="not disposable"):
        validated_test_database_url(
            "postgresql+psycopg://postgres:secret@127.0.0.1:55432/dy_dashboard"
        )
    accepted = validated_test_database_url(
        "postgresql+psycopg://dydata_t52:secret@127.0.0.1:55432/dydata_t52"
    )
    assert accepted.host == "127.0.0.1"
    assert accepted.port == 55432


def test_candidate_session_factory_preserves_internal_database_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts.ops import run_daily_candidate_acceptance as candidate

    database_url = (
        "postgresql+psycopg://dydata_t52:local-secret@"
        "127.0.0.1:55432/dydata_t52"
    )
    captured: dict[str, object] = {}
    monkeypatch.setenv("DYDATA_T52_TEST_DATABASE_URL", database_url)
    monkeypatch.setattr(
        candidate,
        "make_engine",
        lambda normalized_url: captured.setdefault("engine_url", normalized_url),
    )
    monkeypatch.setattr(
        candidate,
        "make_session_factory",
        lambda engine: ("factory", engine),
    )

    factory, normalized_url = candidate.get_test_session_factory()

    assert normalized_url == database_url
    assert "***" not in normalized_url
    assert captured["engine_url"] == database_url
    assert factory == ("factory", database_url)


def test_candidate_acceptance_runs_only_exact_planned_children_and_writes_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.worker.subprocess_supervisor import ChildRunResult, ChildRunStatus
    from scripts.ops.run_daily_candidate_acceptance import run_candidate_acceptance

    sessions: list[SimpleNamespace] = []
    planned_targets: list[str] = []
    executed_job_ids: list[str] = []

    class FakeSession:
        def __init__(self) -> None:
            self.committed = False
            self.rolled_back = False
            self.closed = False

        def commit(self) -> None:
            self.committed = True

        def rollback(self) -> None:
            self.rolled_back = True

        def close(self) -> None:
            self.closed = True

    def factory() -> FakeSession:
        session = FakeSession()
        sessions.append(session)  # type: ignore[arg-type]
        return session

    def fake_plan(_session: FakeSession, **kwargs: object) -> SimpleNamespace:
        target = str(kwargs["target"])
        planned_targets.append(target)
        return SimpleNamespace(
            parent_job_id=f"parent-{target}",
            daily_jobs=(
                SimpleNamespace(
                    job_id=f"child-{target}",
                    disposition="ready",
                ),
            ),
        )

    def fake_run(_factory: object, *, job_id: str) -> ChildRunResult:
        assert os.environ["DY_WORKER_FAKE_DOUYIN"] == "true"
        executed_job_ids.append(job_id)
        rss = 128 * 1024**2 if job_id.endswith("clue_center") else 256 * 1024**2
        return ChildRunResult(
            job_id=job_id,
            status=ChildRunStatus.SUCCESS,
            attempts=1,
            exit_code=0,
            rss_peak_bytes=rss,
            heartbeat_seen=True,
            lease_seen=True,
        )

    monkeypatch.setenv("DY_WORKER_FAKE_DOUYIN", "existing-value")
    report_path = tmp_path / "candidate.json"
    report = run_candidate_acceptance(
        factory,
        start="2026-08-01",
        end="2026-08-02",
        targets=("clue_center", "settlement"),
        max_children=2,
        report_path=report_path,
        plan_fn=fake_plan,
        run_fn=fake_run,
    )

    assert report.protocol == "dydata-daily-candidate-acceptance-v1"
    assert report.status == "GREEN"
    assert report.child_count == 2
    assert report.rss_peak_bytes == 256 * 1024**2
    assert planned_targets == ["clue_center", "settlement"]
    assert executed_job_ids == ["child-clue_center", "child-settlement"]
    assert os.environ["DY_WORKER_FAKE_DOUYIN"] == "existing-value"
    assert all(session.committed and session.closed for session in sessions)
    assert all(not session.rolled_back for session in sessions)
    persisted = json.loads(report_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "GREEN"
    assert persisted["targets"] == ["clue_center", "settlement"]
    assert "database_url" not in report_path.read_text(encoding="utf-8").lower()


def test_candidate_acceptance_fails_closed_on_incomplete_child(tmp_path: Path) -> None:
    from apps.worker.subprocess_supervisor import ChildRunResult, ChildRunStatus
    from scripts.ops.run_daily_candidate_acceptance import run_candidate_acceptance

    class FakeSession:
        def commit(self) -> None:
            return None

        def rollback(self) -> None:
            return None

        def close(self) -> None:
            return None

    def fake_plan(_session: FakeSession, **kwargs: object) -> SimpleNamespace:
        target = str(kwargs["target"])
        return SimpleNamespace(
            parent_job_id=f"parent-{target}",
            daily_jobs=(SimpleNamespace(job_id=f"child-{target}", disposition="ready"),),
        )

    def fake_run(_factory: object, *, job_id: str) -> ChildRunResult:
        return ChildRunResult(
            job_id=job_id,
            status=ChildRunStatus.RETRY_WAIT,
            attempts=1,
            exit_code=None,
            rss_peak_bytes=64 * 1024**2,
        )

    report = run_candidate_acceptance(
        lambda: FakeSession(),
        start="2026-08-01",
        end="2026-08-02",
        targets=("clue_center",),
        max_children=1,
        report_path=tmp_path / "failed.json",
        plan_fn=fake_plan,
        run_fn=fake_run,
    )

    assert report.status == "FAILED"
    assert report.release_blocker is True
    assert report.children[0].status == "retry_wait"


def test_cli_help_is_side_effect_free_and_available_for_all_t52_scripts() -> None:
    scripts = (
        "scripts/ops/generate_sync_benchmark_fixture.py",
        "scripts/ops/run_sync_benchmark.py",
        "scripts/ops/run_8gb_acceptance.py",
        "scripts/ops/run_daily_candidate_acceptance.py",
    )
    for script in scripts:
        completed = subprocess.run(
            [sys.executable, script, "--help"],
            check=False,
            capture_output=True,
            text=True,
            env={key: value for key, value in os.environ.items() if key not in {
                "DY_DATABASE_URL",
                "DATABASE_URL",
                "DYDATA_T52_TEST_DATABASE_URL",
                "DYDATA_T12_TEST_DATABASE_URL",
            }},
        )
        assert completed.returncode == 0, f"{script}: {completed.stderr}"
        assert "usage:" in completed.stdout.lower()
