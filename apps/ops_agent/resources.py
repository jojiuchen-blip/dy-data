from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping


GIB = 1024**3


@dataclass(frozen=True)
class HostMemory:
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


@dataclass(frozen=True)
class ResourceThresholds:
    # Benchmark-tuning defaults, not production-certified constants.
    warn_host_used_bytes: int = 6 * GIB
    stop_host_used_bytes: int = int(6.4 * GIB)
    max_process_tree_rss_bytes: int = 2 * GIB
    max_cgroup_current_bytes: int = 3 * GIB
    max_swap_used_bytes: int = 0

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "ResourceThresholds":
        source = os.environ if env is None else env

        def positive(name: str, default: int, *, allow_zero: bool = False) -> int:
            raw = source.get(name)
            try:
                value = default if raw is None else int(raw)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{name} must be an integer byte threshold") from exc
            minimum = 0 if allow_zero else 1
            if value < minimum:
                raise ValueError(f"{name} must be at least {minimum}")
            return value

        thresholds = cls(
            warn_host_used_bytes=positive(
                "WORKER_RESOURCE_WARN_HOST_USED_BYTES", cls.warn_host_used_bytes
            ),
            stop_host_used_bytes=positive(
                "WORKER_RESOURCE_STOP_HOST_USED_BYTES", cls.stop_host_used_bytes
            ),
            max_process_tree_rss_bytes=positive(
                "WORKER_RESOURCE_MAX_PROCESS_TREE_RSS_BYTES",
                cls.max_process_tree_rss_bytes,
            ),
            max_cgroup_current_bytes=positive(
                "WORKER_RESOURCE_MAX_CGROUP_CURRENT_BYTES",
                cls.max_cgroup_current_bytes,
            ),
            max_swap_used_bytes=positive(
                "WORKER_RESOURCE_MAX_SWAP_USED_BYTES",
                cls.max_swap_used_bytes,
                allow_zero=True,
            ),
        )
        if thresholds.warn_host_used_bytes >= thresholds.stop_host_used_bytes:
            raise ValueError("resource warn threshold must be below stop threshold")
        return thresholds


class ResourceAction(str, Enum):
    ALLOW = "allow"
    DRAIN = "drain"
    STOP = "stop"


@dataclass(frozen=True)
class ResourceDecision:
    action: ResourceAction
    reasons: tuple[str, ...]


def _parse_bytes_value(value: str) -> int | None:
    normalized = value.strip()
    if normalized == "max":
        return None
    parsed = int(normalized)
    if parsed < 0:
        raise ValueError("resource byte value cannot be negative")
    return parsed


def parse_meminfo(source: str) -> HostMemory:
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
        return parse_meminfo(Path(meminfo_path).read_text(encoding="ascii"))
    except (OSError, UnicodeError, ValueError):
        return None


def _read_optional_bytes(path: Path) -> int | None:
    return _parse_bytes_value(path.read_text(encoding="ascii")) if path.exists() else None


def read_cgroup_memory(cgroup_root: Path | str = "/sys/fs/cgroup") -> CgroupMemory | None:
    root = Path(cgroup_root)
    try:
        current_path = root / "memory.current"
        limit_path = root / "memory.max"
        if current_path.exists() and limit_path.exists():
            return CgroupMemory(
                _parse_bytes_value(current_path.read_text(encoding="ascii")),
                _parse_bytes_value(limit_path.read_text(encoding="ascii")),
                _read_optional_bytes(root / "memory.swap.current"),
                _read_optional_bytes(root / "memory.swap.max"),
            )

        # Keep the sampler useful on hosts still exposing cgroup v1.
        memory_root = root / "memory"
        current = _parse_bytes_value(
            (memory_root / "memory.usage_in_bytes").read_text(encoding="ascii")
        )
        limit = _parse_bytes_value(
            (memory_root / "memory.limit_in_bytes").read_text(encoding="ascii")
        )
        memsw_current = _read_optional_bytes(memory_root / "memory.memsw.usage_in_bytes")
        memsw_limit = _read_optional_bytes(memory_root / "memory.memsw.limit_in_bytes")
        return CgroupMemory(
            current,
            limit,
            max(0, memsw_current - current)
            if memsw_current is not None and current is not None
            else None,
            max(0, memsw_limit - limit)
            if memsw_limit is not None and limit is not None
            else None,
        )
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


def read_process_tree_rss_bytes(root_pid: int, *, proc_root: Path | str = "/proc") -> int | None:
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
    return ResourceSnapshot(
        process_tree_rss_bytes=read_process_tree_rss_bytes(root_pid, proc_root=proc_root),
        host=read_host_memory(meminfo_path),
        cgroup=read_cgroup_memory(cgroup_root),
    )


def evaluate_resource_guard(
    snapshot: ResourceSnapshot,
    thresholds: ResourceThresholds,
) -> ResourceDecision:
    stop: list[str] = []
    drain: list[str] = []
    if (
        snapshot.process_tree_rss_bytes is not None
        and snapshot.process_tree_rss_bytes >= thresholds.max_process_tree_rss_bytes
    ):
        stop.append("process_tree_rss_stop_threshold")
    if snapshot.cgroup is not None and snapshot.cgroup.current_bytes is not None:
        if snapshot.cgroup.current_bytes >= thresholds.max_cgroup_current_bytes:
            stop.append("cgroup_memory_stop_threshold")
        if (
            snapshot.cgroup.swap_current_bytes is not None
            and snapshot.cgroup.swap_current_bytes > thresholds.max_swap_used_bytes
        ):
            drain.append("cgroup_swap_used")
    if snapshot.host is not None:
        if snapshot.host.used_bytes >= thresholds.stop_host_used_bytes:
            stop.append("host_memory_stop_threshold")
        elif snapshot.host.used_bytes >= thresholds.warn_host_used_bytes:
            drain.append("host_memory_warn_threshold")
        if snapshot.host.swap_used_bytes > thresholds.max_swap_used_bytes:
            drain.append("swap_used")
    if stop:
        return ResourceDecision(ResourceAction.STOP, tuple(stop + drain))
    if drain:
        return ResourceDecision(ResourceAction.DRAIN, tuple(drain))
    return ResourceDecision(ResourceAction.ALLOW, ())
