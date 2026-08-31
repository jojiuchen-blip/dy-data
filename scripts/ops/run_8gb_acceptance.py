from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ops.run_sync_benchmark import (  # noqa: E402
    BenchmarkReport,
    GIB,
    read_host_memory,
    run_benchmark,
)


MIN_VISIBLE_8GB_BYTES = int(7.4 * GIB)
MAX_VISIBLE_8GB_BYTES = int(8.5 * GIB)


@dataclass(frozen=True)
class AcceptanceEnvironment:
    platform: str
    cpu_count: int
    total_memory_bytes: int

    @classmethod
    def current(cls) -> "AcceptanceEnvironment":
        host = read_host_memory()
        return cls(
            platform=platform.system(),
            cpu_count=os.cpu_count() or 0,
            total_memory_bytes=host.total_bytes if host is not None else 0,
        )


@dataclass(frozen=True)
class EnvironmentGate:
    verified: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class AcceptanceReport:
    protocol: str
    status: str
    release_blocker: bool
    environment: AcceptanceEnvironment
    environment_reasons: tuple[str, ...]
    runs: tuple[BenchmarkReport, ...]
    checks: dict[str, bool]

    def as_json(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["runs"] = [run.as_json() for run in self.runs]
        return payload


class AcceptanceBlocked(RuntimeError):
    """Raised before benchmark execution when the host gate is not verified."""

    def __init__(self, environment: AcceptanceEnvironment, gate: EnvironmentGate) -> None:
        self.environment = environment
        self.gate = gate
        super().__init__("4C/8GB Linux acceptance environment is required")


def evaluate_environment(environment: AcceptanceEnvironment) -> EnvironmentGate:
    reasons: list[str] = []
    if environment.platform.lower() != "linux":
        reasons.append("linux_required")
    if environment.cpu_count != 4:
        reasons.append("cpu_count_must_equal_4")
    if not MIN_VISIBLE_8GB_BYTES <= environment.total_memory_bytes <= MAX_VISIBLE_8GB_BYTES:
        reasons.append("host_memory_must_be_8gb")
    return EnvironmentGate(not reasons, tuple(reasons))


def _write_json(path: Path | str, payload: dict[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def run_acceptance(
    fixture_dir: Path | str,
    *,
    environment: AcceptanceEnvironment | None = None,
    runs: int = 3,
    batch_size: int = 1000,
    permit_unverified_environment: bool = False,
    report_path: Path | str | None = None,
) -> AcceptanceReport:
    if isinstance(runs, bool) or runs != 3:
        raise ValueError("release acceptance requires exactly three runs")
    active_environment = environment or AcceptanceEnvironment.current()
    gate = evaluate_environment(active_environment)
    if not gate.verified and not permit_unverified_environment:
        raise AcceptanceBlocked(active_environment, gate)

    benchmark_runs = tuple(
        run_benchmark(fixture_dir, batch_size=batch_size)
        for _index in range(runs)
    )
    checks = {
        "three_runs": len(benchmark_runs) == 3,
        "checksum_stable": len({run.result_checksum for run in benchmark_runs}) == 1,
        "shadow_equivalent": all(
            run.result_checksum == run.shadow_checksum for run in benchmark_runs
        ),
        "worker_peak_at_most_2gb": all(
            run.process_tree_rss_peak_bytes is not None
            and run.process_tree_rss_peak_bytes <= 2 * GIB
            for run in benchmark_runs
        ),
        "host_peak_at_most_6_4gb": all(
            run.host_used_peak_bytes is not None
            and run.host_used_peak_bytes <= int(6.4 * GIB)
            for run in benchmark_runs
        ),
        "swap_not_growing": all(
            run.swap_used_start_bytes is not None
            and run.swap_used_start_bytes >= 0
            and run.swap_used_peak_bytes is not None
            and run.swap_used_peak_bytes <= run.swap_used_start_bytes
            for run in benchmark_runs
        ),
        "swap_headroom_at_least_10_percent": all(
            run.swap_total_bytes is not None
            and run.swap_total_bytes >= 0
            and run.swap_used_peak_bytes is not None
            and run.swap_used_peak_bytes >= 0
            and (
                (run.swap_total_bytes == 0 and run.swap_used_peak_bytes == 0)
                or (
                    run.swap_total_bytes > 0
                    and run.swap_used_peak_bytes <= run.swap_total_bytes
                    and (run.swap_total_bytes - run.swap_used_peak_bytes) * 10
                    >= run.swap_total_bytes
                )
            )
            for run in benchmark_runs
        ),
    }
    data_checks = (
        checks["three_runs"]
        and checks["checksum_stable"]
        and checks["shadow_equivalent"]
    )
    resource_checks = all(checks.values())
    status = "GREEN" if gate.verified and resource_checks else (
        "UNVERIFIED" if not gate.verified and data_checks else "FAILED"
    )
    report = AcceptanceReport(
        protocol="dydata-8gb-acceptance-v2",
        status=status,
        release_blocker=status != "GREEN",
        environment=active_environment,
        environment_reasons=gate.reasons,
        runs=benchmark_runs,
        checks=checks,
    )
    if report_path is not None:
        _write_json(report_path, report.as_json())
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the three-pass 4C/8GB Linux release acceptance gate on a local fixture. "
            "This command does not connect to a database or deploy services."
        )
    )
    parser.add_argument("--fixture-dir", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--permit-unverified-environment",
        action="store_true",
        help="Run functional checks but retain an explicit release blocker.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        report = run_acceptance(
            args.fixture_dir,
            runs=args.runs,
            batch_size=args.batch_size,
            permit_unverified_environment=args.permit_unverified_environment,
            report_path=args.report,
        )
    except AcceptanceBlocked as exc:
        payload = {
            "protocol": "dydata-8gb-acceptance-v2",
            "status": "UNVERIFIED",
            "release_blocker": True,
            "environment": asdict(exc.environment),
            "environment_reasons": list(exc.gate.reasons),
            "runs": [],
            "checks": {},
            "reason": str(exc),
        }
        if args.report is not None:
            _write_json(args.report, payload)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 3
    print(json.dumps(report.as_json(), ensure_ascii=False, sort_keys=True))
    return 0 if report.status == "GREEN" else 3


if __name__ == "__main__":
    raise SystemExit(main())
