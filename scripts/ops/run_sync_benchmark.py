from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ops.generate_sync_benchmark_fixture import FIXTURE_PROTOCOL  # noqa: E402


GIB = 1024**3


@dataclass(frozen=True)
class HostMemory:
    """A small, dependency-free view of Linux ``/proc/meminfo``."""

    total_bytes: int
    available_bytes: int
    swap_total_bytes: int
    swap_free_bytes: int

    @property
    def used_bytes(self) -> int:
        return max(0, self.total_bytes - self.available_bytes)

    @property
    def swap_used_bytes(self) -> int:
        return max(0, self.swap_total_bytes - self.swap_free_bytes)


@dataclass(frozen=True)
class CgroupMemory:
    current_bytes: int | None
    limit_bytes: int | None
    swap_current_bytes: int | None
    swap_limit_bytes: int | None


@dataclass(frozen=True)
class ResourceSnapshot:
    process_tree_rss_bytes: int | None
    host: HostMemory | None
    cgroup: CgroupMemory | None


def _parse_meminfo(source: str) -> HostMemory:
    values: dict[str, int] = {}
    for raw_line in source.splitlines():
        if ":" not in raw_line:
            continue
        key, raw_value = raw_line.split(":", 1)
        fields = raw_value.strip().split()
        if not fields:
            continue
        multiplier = 1024 if len(fields) > 1 and fields[1].lower() == "kb" else 1
        values[key] = int(fields[0]) * multiplier
    required = ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree")
    if any(key not in values for key in required):
        raise ValueError("meminfo is missing required fields")
    return HostMemory(
        total_bytes=values["MemTotal"],
        available_bytes=values["MemAvailable"],
        swap_total_bytes=values["SwapTotal"],
        swap_free_bytes=values["SwapFree"],
    )


def read_host_memory(meminfo_path: Path | str = "/proc/meminfo") -> HostMemory | None:
    try:
        return _parse_meminfo(Path(meminfo_path).read_text(encoding="ascii"))
    except (OSError, UnicodeError, ValueError):
        return None


def _parse_bytes_value(value: str) -> int | None:
    normalized = value.strip()
    if normalized == "max":
        return None
    parsed = int(normalized)
    if parsed < 0:
        raise ValueError("resource byte value cannot be negative")
    return parsed


def read_cgroup_memory(cgroup_root: Path | str = "/sys/fs/cgroup") -> CgroupMemory | None:
    root = Path(cgroup_root)
    try:
        current = _parse_bytes_value((root / "memory.current").read_text(encoding="ascii"))
        limit = _parse_bytes_value((root / "memory.max").read_text(encoding="ascii"))
        swap_current_path = root / "memory.swap.current"
        swap_limit_path = root / "memory.swap.max"
        swap_current = (
            _parse_bytes_value(swap_current_path.read_text(encoding="ascii"))
            if swap_current_path.exists()
            else None
        )
        swap_limit = (
            _parse_bytes_value(swap_limit_path.read_text(encoding="ascii"))
            if swap_limit_path.exists()
            else None
        )
        return CgroupMemory(current, limit, swap_current, swap_limit)
    except (OSError, UnicodeError, ValueError):
        return None


def _process_statuses(proc_root: Path) -> dict[int, tuple[int, int]]:
    statuses: dict[int, tuple[int, int]] = {}
    for child in proc_root.iterdir():
        if not child.name.isdigit():
            continue
        try:
            text = (child / "status").read_text(encoding="ascii", errors="replace")
        except OSError:
            continue
        fields: dict[str, str] = {}
        for line in text.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                fields[key] = value.strip()
        try:
            pid = int(fields["Pid"])
            parent = int(fields["PPid"])
            rss_fields = fields.get("VmRSS", "0 kB").split()
            rss = int(rss_fields[0]) * (1024 if len(rss_fields) > 1 else 1)
        except (KeyError, ValueError):
            continue
        statuses[pid] = (parent, max(0, rss))
    return statuses


def read_process_tree_rss_bytes(
    root_pid: int,
    *,
    proc_root: Path | str = "/proc",
) -> int | None:
    if root_pid <= 0:
        raise ValueError("root_pid must be positive")
    root = Path(proc_root)
    try:
        statuses = _process_statuses(root)
    except OSError:
        return None
    if root_pid not in statuses:
        return None
    descendants = {root_pid}
    changed = True
    while changed:
        changed = False
        for pid, (parent, _rss) in statuses.items():
            if parent in descendants and pid not in descendants:
                descendants.add(pid)
                changed = True
    return sum(statuses[pid][1] for pid in descendants)


def collect_resource_snapshot(
    root_pid: int,
    *,
    proc_root: Path | str = "/proc",
    meminfo_path: Path | str = "/proc/meminfo",
    cgroup_root: Path | str = "/sys/fs/cgroup",
) -> ResourceSnapshot:
    """Collect Linux evidence, returning ``None`` fields on unsupported hosts."""

    return ResourceSnapshot(
        process_tree_rss_bytes=read_process_tree_rss_bytes(root_pid, proc_root=proc_root),
        host=read_host_memory(meminfo_path),
        cgroup=read_cgroup_memory(cgroup_root),
    )


class BenchmarkInterrupted(RuntimeError):
    """Deterministic crash injection after a durable batch checkpoint."""


@dataclass(frozen=True)
class BenchmarkReport:
    protocol: str
    input_sha256: str
    row_count: int
    partition_count: int
    batch_size: int
    batches: int
    resumed: bool
    elapsed_seconds: float
    result_checksum: str
    shadow_checksum: str
    process_tree_rss_peak_bytes: int | None
    host_used_peak_bytes: int | None
    swap_used_start_bytes: int | None
    swap_used_peak_bytes: int | None
    swap_total_bytes: int | None
    cgroup_current_peak_bytes: int | None

    def as_json(self) -> dict[str, Any]:
        return asdict(self)


def _iter_rows(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"fixture row {line_number} is invalid JSON") from exc
            if not isinstance(row, dict):
                raise ValueError(f"fixture row {line_number} is not an object")
            yield row


def _aggregate(aggregate: dict[str, dict[str, int]], row: dict[str, Any]) -> None:
    try:
        business_date = row["business_date"]
        store_id = row["store_id"]
        paid = row["paid_amount_cent"]
        verified_amount = row["verified_amount_cent"]
        verified = row["verified"]
    except KeyError as exc:
        raise ValueError("fixture row is missing a required field") from exc
    if not isinstance(business_date, str) or not isinstance(store_id, str):
        raise ValueError("fixture partition identity is invalid")
    if not isinstance(paid, int) or isinstance(paid, bool) or paid < 0:
        raise ValueError("fixture paid amount is invalid")
    if (
        not isinstance(verified_amount, int)
        or isinstance(verified_amount, bool)
        or verified_amount < 0
    ):
        raise ValueError("fixture verified amount is invalid")
    if not isinstance(verified, bool):
        raise ValueError("fixture verified flag is invalid")
    if verified_amount > paid:
        raise ValueError("fixture verified amount exceeds paid amount")
    key = f"{business_date}|{store_id}"
    current = aggregate.setdefault(
        key,
        {"orders": 0, "paid_amount_cent": 0, "verified": 0, "verified_amount_cent": 0},
    )
    current["orders"] += 1
    current["paid_amount_cent"] += paid
    current["verified"] += int(verified)
    current["verified_amount_cent"] += verified_amount


def _aggregate_checksum(aggregate: dict[str, dict[str, int]]) -> str:
    encoded = json.dumps(
        aggregate,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _verify_fixture(fixture_dir: Path) -> tuple[dict[str, Any], dict[str, dict[str, int]]]:
    manifest_path = fixture_dir / "manifest.json"
    data_path = fixture_dir / "orders.jsonl"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("fixture manifest is unreadable") from exc
    if not isinstance(manifest, dict) or manifest.get("protocol") != FIXTURE_PROTOCOL:
        raise ValueError("fixture manifest protocol is invalid")
    row_count_manifest = manifest.get("row_count")
    partition_count_manifest = manifest.get("partition_count")
    expected_sha256 = manifest.get("sha256")
    if (
        not isinstance(row_count_manifest, int)
        or isinstance(row_count_manifest, bool)
        or row_count_manifest < 0
        or not isinstance(partition_count_manifest, int)
        or isinstance(partition_count_manifest, bool)
        or partition_count_manifest < 0
        or not isinstance(expected_sha256, str)
    ):
        raise ValueError("fixture manifest fields are invalid")

    digest = hashlib.sha256()
    row_count = 0
    shadow: dict[str, dict[str, int]] = {}
    try:
        handle = data_path.open("rb")
    except OSError as exc:
        raise ValueError("fixture data is unreadable") from exc
    with handle:
        for raw_line in handle:
            digest.update(raw_line)
            row_count += 1
            try:
                row = json.loads(raw_line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"fixture row {row_count} is invalid") from exc
            if not isinstance(row, dict):
                raise ValueError(f"fixture row {row_count} is not an object")
            _aggregate(shadow, row)
    if row_count != row_count_manifest:
        raise ValueError("fixture row count does not match manifest")
    if len(shadow) != partition_count_manifest:
        raise ValueError("fixture partition count does not match manifest")
    if digest.hexdigest() != expected_sha256:
        raise ValueError("fixture checksum does not match manifest")
    return manifest, shadow


def _sample_peaks(
    peaks: dict[str, int | None],
    snapshot: ResourceSnapshot | None = None,
) -> ResourceSnapshot:
    active_snapshot = snapshot or collect_resource_snapshot(os.getpid())
    values = {
        "process": active_snapshot.process_tree_rss_bytes,
        "host": active_snapshot.host.used_bytes if active_snapshot.host is not None else None,
        "swap": (
            active_snapshot.host.swap_used_bytes
            if active_snapshot.host is not None
            else None
        ),
        "cgroup": (
            active_snapshot.cgroup.current_bytes
            if active_snapshot.cgroup is not None
            else None
        ),
    }
    for key, value in values.items():
        if value is not None:
            peaks[key] = max(peaks[key] or 0, value)
    return active_snapshot


def _load_checkpoint(
    checkpoint: Path,
    *,
    input_sha256: str,
    batch_size: int,
    row_count: int,
) -> tuple[dict[str, dict[str, int]], int, int]:
    try:
        state = json.loads(checkpoint.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("benchmark checkpoint is unreadable") from exc
    if not isinstance(state, dict):
        raise ValueError("benchmark checkpoint is invalid")
    if (
        state.get("protocol") != "dydata-sync-benchmark-checkpoint-v1"
        or state.get("input_sha256") != input_sha256
        or state.get("batch_size") != batch_size
        or not isinstance(state.get("aggregate"), dict)
    ):
        raise ValueError("benchmark checkpoint is incompatible")
    aggregate = state["aggregate"]
    for key, values in aggregate.items():
        if not isinstance(key, str) or not isinstance(values, dict):
            raise ValueError("benchmark checkpoint aggregate is invalid")
        required = {"orders", "paid_amount_cent", "verified", "verified_amount_cent"}
        if set(values) != required or any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in values.values()
        ):
            raise ValueError("benchmark checkpoint aggregate is invalid")
    next_row = state.get("next_row")
    completed_batches = state.get("completed_batches")
    if (
        not isinstance(next_row, int)
        or isinstance(next_row, bool)
        or not 0 <= next_row <= row_count
        or not isinstance(completed_batches, int)
        or isinstance(completed_batches, bool)
        or completed_batches < 0
    ):
        raise ValueError("benchmark checkpoint counters are invalid")
    return aggregate, next_row, completed_batches


def run_benchmark(
    fixture_dir: Path | str,
    *,
    batch_size: int,
    checkpoint_path: Path | str | None = None,
    crash_after_batches: int | None = None,
    report_path: Path | str | None = None,
) -> BenchmarkReport:
    """Run a bounded aggregate and compare it with a single-pass shadow result."""

    if isinstance(batch_size, bool) or batch_size <= 0 or batch_size > 1_000_000:
        raise ValueError("batch_size must be between 1 and 1000000")
    if crash_after_batches is not None and (
        isinstance(crash_after_batches, bool) or crash_after_batches <= 0
    ):
        raise ValueError("crash_after_batches must be positive")
    if crash_after_batches is not None and checkpoint_path is None:
        raise ValueError("crash injection requires checkpoint_path")

    directory = Path(fixture_dir)
    manifest, shadow = _verify_fixture(directory)
    checkpoint = Path(checkpoint_path) if checkpoint_path is not None else None
    aggregate: dict[str, dict[str, int]] = {}
    next_row = 0
    completed_batches = 0
    resumed = False
    if checkpoint is not None and checkpoint.exists():
        aggregate, next_row, completed_batches = _load_checkpoint(
            checkpoint,
            input_sha256=str(manifest["sha256"]),
            batch_size=batch_size,
            row_count=int(manifest["row_count"]),
        )
        resumed = True

    started_at = time.perf_counter()
    peaks: dict[str, int | None] = {"process": None, "host": None, "swap": None, "cgroup": None}
    initial_snapshot = collect_resource_snapshot(os.getpid())
    _sample_peaks(peaks, initial_snapshot)
    swap_used_start_bytes = (
        initial_snapshot.host.swap_used_bytes
        if initial_snapshot.host is not None
        else None
    )
    swap_total_bytes = (
        initial_snapshot.host.swap_total_bytes
        if initial_snapshot.host is not None
        else None
    )
    batch: list[dict[str, Any]] = []
    invocation_batches = 0

    def commit_batch(rows: list[dict[str, Any]], cursor: int) -> None:
        nonlocal completed_batches, invocation_batches
        for row in rows:
            _aggregate(aggregate, row)
        completed_batches += 1
        invocation_batches += 1
        _sample_peaks(peaks)
        if checkpoint is not None:
            checkpoint.parent.mkdir(parents=True, exist_ok=True)
            checkpoint.write_text(
                json.dumps(
                    {
                        "aggregate": aggregate,
                        "batch_size": batch_size,
                        "completed_batches": completed_batches,
                        "input_sha256": manifest["sha256"],
                        "next_row": cursor,
                        "protocol": "dydata-sync-benchmark-checkpoint-v1",
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n",
                encoding="utf-8",
            )
        if crash_after_batches is not None and invocation_batches >= crash_after_batches:
            raise BenchmarkInterrupted("injected crash after durable batch checkpoint")

    cursor = next_row
    for index, row in enumerate(_iter_rows(directory / "orders.jsonl")):
        if index < next_row:
            continue
        batch.append(row)
        cursor = index + 1
        if len(batch) >= batch_size:
            commit_batch(batch, cursor)
            batch = []
    if batch:
        commit_batch(batch, cursor)

    result_checksum = _aggregate_checksum(aggregate)
    shadow_checksum = _aggregate_checksum(shadow)
    if result_checksum != shadow_checksum:
        raise AssertionError("incremental and shadow aggregate checksums differ")
    if checkpoint is not None and checkpoint.exists():
        checkpoint.unlink()
    report = BenchmarkReport(
        protocol="dydata-sync-benchmark-report-v2",
        input_sha256=str(manifest["sha256"]),
        row_count=int(manifest["row_count"]),
        partition_count=len(aggregate),
        batch_size=batch_size,
        batches=completed_batches,
        resumed=resumed,
        elapsed_seconds=round(time.perf_counter() - started_at, 6),
        result_checksum=result_checksum,
        shadow_checksum=shadow_checksum,
        process_tree_rss_peak_bytes=peaks["process"],
        host_used_peak_bytes=peaks["host"],
        swap_used_start_bytes=swap_used_start_bytes,
        swap_used_peak_bytes=peaks["swap"],
        swap_total_bytes=swap_total_bytes,
        cgroup_current_peak_bytes=peaks["cgroup"],
    )
    if report_path is not None:
        destination = Path(report_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(report.as_json(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a bounded incremental/shadow checksum benchmark."
    )
    parser.add_argument("--fixture-dir", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--crash-after-batches", type=int)
    parser.add_argument("--report", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = run_benchmark(
        args.fixture_dir,
        batch_size=args.batch_size,
        checkpoint_path=args.checkpoint,
        crash_after_batches=args.crash_after_batches,
        report_path=args.report,
    )
    print(json.dumps(report.as_json(), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
