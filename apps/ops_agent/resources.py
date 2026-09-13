from __future__ import annotations

import math
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
    swap_activity_bytes_per_second: float | None = None


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
    """Evaluate the legacy instantaneous guard.

    The stateful monitor below owns the 30/60 second pressure windows.  This
    compatibility function keeps the existing host-used decision for direct
    legacy callers, while static swap occupancy is deliberately ignored.  A
    caller wiring the new monitor must consume :class:`ResourcePressurePolicy`
    directly so the legacy host-used cutoff cannot bypass the pressure window.
    """

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
    if snapshot.host is not None:
        if snapshot.host.used_bytes >= thresholds.stop_host_used_bytes:
            stop.append("host_memory_stop_threshold")
        elif snapshot.host.used_bytes >= thresholds.warn_host_used_bytes:
            drain.append("host_memory_warn_threshold")
        # Residual swap occupancy is not an instantaneous pressure signal.
        # It is intentionally excluded from the decision.
    if stop:
        return ResourceDecision(ResourceAction.STOP, tuple(stop + drain))
    if drain:
        return ResourceDecision(ResourceAction.DRAIN, tuple(drain))
    return ResourceDecision(ResourceAction.ALLOW, ())


@dataclass(frozen=True)
class PressureThresholds:
    """Thresholds for the stateful resource pressure policy.

    These settings are separate from :class:`ResourceThresholds`.  The old
    host-used and swap variables remain compatibility inputs for the legacy
    guard only; they cannot change the 80/90/75 percent pressure bands or
    their continuity windows.
    """

    constrained_available_bytes: int = 2 * GIB
    protected_available_bytes: int = 1 * GIB
    recovery_available_bytes: int = int(2.5 * GIB)
    constrained_cgroup_ratio: float = 0.80
    protected_cgroup_ratio: float = 0.90
    recovery_cgroup_ratio: float = 0.75
    constrained_duration_seconds: float = 60.0
    protected_duration_seconds: float = 30.0
    recovery_duration_seconds: float = 180.0
    stable_duration_seconds: float = 600.0
    max_sample_gap_seconds: float = 15.0
    swap_activity_threshold_bytes_per_second: float = 32 * 1024**2
    hard_process_tree_rss_bytes: int = 2 * GIB
    hard_cgroup_current_bytes: int = 3 * GIB

    def __post_init__(self) -> None:
        byte_fields = (
            "constrained_available_bytes",
            "protected_available_bytes",
            "recovery_available_bytes",
            "hard_process_tree_rss_bytes",
            "hard_cgroup_current_bytes",
        )
        if any(
            isinstance(getattr(self, name), bool)
            or not isinstance(getattr(self, name), int)
            or getattr(self, name) <= 0
            for name in byte_fields
        ):
            raise ValueError("byte thresholds must be positive integers")
        if not (
            self.protected_available_bytes
            < self.constrained_available_bytes
            < self.recovery_available_bytes
        ):
            raise ValueError(
                "available thresholds must satisfy protected < constrained < recovery"
            )

        ratio_fields = (
            "constrained_cgroup_ratio",
            "protected_cgroup_ratio",
            "recovery_cgroup_ratio",
        )
        if any(
            isinstance(getattr(self, name), bool)
            or not isinstance(getattr(self, name), (int, float))
            or not math.isfinite(float(getattr(self, name)))
            or not 0 < float(getattr(self, name)) < 1
            for name in ratio_fields
        ):
            raise ValueError("cgroup ratios must be finite numbers between 0 and 1")
        if not (
            self.recovery_cgroup_ratio
            < self.constrained_cgroup_ratio
            < self.protected_cgroup_ratio
        ):
            raise ValueError(
                "cgroup ratios must satisfy recovery < constrained < protected"
            )

        duration_fields = (
            "constrained_duration_seconds",
            "protected_duration_seconds",
            "recovery_duration_seconds",
            "stable_duration_seconds",
            "max_sample_gap_seconds",
        )
        if any(
            isinstance(getattr(self, name), bool)
            or not isinstance(getattr(self, name), (int, float))
            or not math.isfinite(float(getattr(self, name)))
            or float(getattr(self, name)) <= 0
            for name in duration_fields
        ):
            raise ValueError("durations must be finite positive numbers")
        if self.protected_duration_seconds > self.constrained_duration_seconds:
            raise ValueError(
                "protected duration must not exceed constrained duration"
            )
        rate = self.swap_activity_threshold_bytes_per_second
        if (
            isinstance(rate, bool)
            or not isinstance(rate, (int, float))
            or not math.isfinite(float(rate))
            or float(rate) <= 0
        ):
            raise ValueError(
                "swap_activity_threshold_bytes_per_second must be finite and positive"
            )

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "PressureThresholds":
        """Load only namespaced pressure settings from ``env``.

        Legacy ``WORKER_RESOURCE_WARN_*`` and
        ``WORKER_RESOURCE_MAX_SWAP_USED_BYTES`` settings are intentionally
        ignored here so a stale deployment setting cannot alter the new
        pressure bands.
        """

        source = os.environ if env is None else env

        def read(field: str, default: int | float, cast: type, *aliases: str):
            names = [f"WORKER_RESOURCE_PRESSURE_{field.upper()}"]
            names.extend(
                f"WORKER_RESOURCE_PRESSURE_{alias.upper()}" for alias in aliases
            )
            name = names[0]
            value = next((source.get(candidate) for candidate in names if candidate in source), None)
            try:
                return default if value is None else cast(value)
            except (TypeError, ValueError) as exc:
                kind = "integer byte threshold" if cast is int else "numeric threshold"
                raise ValueError(f"{name} must be an {kind}") from exc

        integer_fields = (
            "constrained_available_bytes",
            "protected_available_bytes",
            "recovery_available_bytes",
            "hard_process_tree_rss_bytes",
            "hard_cgroup_current_bytes",
        )
        values = {
            name: read(name, getattr(cls, name), int) for name in integer_fields
        }
        duration_aliases = {
            "constrained_duration_seconds": "CONSTRAINED_SECONDS",
            "protected_duration_seconds": "PROTECTED_SECONDS",
            "recovery_duration_seconds": "RECOVERY_SECONDS",
            "stable_duration_seconds": "STABLE_SECONDS",
        }
        for name in (
            "constrained_cgroup_ratio",
            "protected_cgroup_ratio",
            "recovery_cgroup_ratio",
            "constrained_duration_seconds",
            "protected_duration_seconds",
            "recovery_duration_seconds",
            "stable_duration_seconds",
            "max_sample_gap_seconds",
            "swap_activity_threshold_bytes_per_second",
        ):
            alias = duration_aliases.get(name)
            values[name] = read(name, getattr(cls, name), float, alias) if alias else read(
                name, getattr(cls, name), float
            )
        return cls(**values)


@dataclass(frozen=True)
class ResourcePressureState:
    """Serializable result of one pressure policy sample."""

    state: str
    reasons: tuple[str, ...]
    allow_daily: bool
    allow_history: bool
    since: float
    healthy_since: float | None

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "reasons": list(self.reasons),
            "allow_daily": self.allow_daily,
            "allow_history": self.allow_history,
            "since": self.since,
            "healthy_since": self.healthy_since,
        }


@dataclass(frozen=True)
class _PressureObservation:
    constrained: bool
    protected: bool
    healthy: bool
    reasons: tuple[str, ...]
    missing_reasons: tuple[str, ...]
    hard_reasons: tuple[str, ...]


class ResourcePressurePolicy:
    """Pure, stateful pressure classifier with monotonic-clock semantics.

    ``update`` never reads the process, host, environment, or wall clock.  A
    caller supplies a :class:`ResourceSnapshot` and monotonic timestamp, so
    the state machine is deterministic in production and tests.  The policy
    does not claim jobs or alter retry state; its admission flags are consumed
    by the worker monitor.
    """

    NORMAL = "normal"
    CONSTRAINED = "constrained"
    PROTECTED = "protected"
    RECOVERING = "recovering"
    _STATES = {NORMAL, CONSTRAINED, PROTECTED, RECOVERING}

    def __init__(
        self,
        thresholds: PressureThresholds | None = None,
        *,
        initial_state: str | ResourcePressureState | Mapping[str, object] = NORMAL,
        initial_since: float | None = None,
        initial_healthy_since: float | None = None,
    ) -> None:
        self.thresholds = thresholds or PressureThresholds()
        state, state_since, healthy_since = self._parse_initial_state(initial_state)
        if initial_since is not None:
            state_since = float(initial_since)
        if initial_healthy_since is not None:
            healthy_since = float(initial_healthy_since)
        self._state = state
        self._state_since = state_since
        self._healthy_since = healthy_since
        self._constrained_started: float | None = None
        self._protected_started: float | None = None
        self._recovering_stable_since: float | None = None
        self._last_sample_at: float | None = None
        for name, value in (
            ("initial_since", state_since),
            ("initial_healthy_since", healthy_since),
        ):
            if value is not None and not math.isfinite(float(value)):
                raise ValueError(f"{name} must be a finite timestamp")

    @classmethod
    def _parse_initial_state(
        cls, value: str | ResourcePressureState | Mapping[str, object]
    ) -> tuple[str, float | None, float | None]:
        state_since: float | None = None
        healthy_since: float | None = None
        if isinstance(value, ResourcePressureState):
            state = value.state
            state_since = value.since
            healthy_since = value.healthy_since
        elif isinstance(value, Mapping):
            state = value.get("state", cls.NORMAL)
            raw_since = value.get("since")
            raw_healthy_since = value.get("healthy_since")
            state_since = float(raw_since) if raw_since is not None else None
            healthy_since = (
                float(raw_healthy_since) if raw_healthy_since is not None else None
            )
        else:
            state = value
        state = getattr(state, "value", state)
        if not isinstance(state, str) or state not in cls._STATES:
            raise ValueError(f"initial_state must be one of {sorted(cls._STATES)}")
        return state, state_since, healthy_since

    @property
    def current_state(self) -> str:
        return self._state

    @staticmethod
    def _cgroup_ratio(cgroup: CgroupMemory | None) -> float | None:
        if cgroup is None:
            return None
        current = cgroup.current_bytes
        limit = cgroup.limit_bytes
        if (
            current is None
            or limit is None
            or limit <= 0
            or current < 0
            or current > limit
        ):
            return None
        return current / limit

    def _observe(self, snapshot: ResourceSnapshot) -> _PressureObservation:
        thresholds = self.thresholds
        reasons: list[str] = []
        missing: list[str] = []

        host_available = snapshot.host.available_bytes if snapshot.host is not None else None
        if host_available is None:
            missing.append("host_memory_unavailable")
        elif host_available < thresholds.protected_available_bytes:
            reasons.append("host_available_below_protected_threshold")
        elif host_available < thresholds.constrained_available_bytes:
            reasons.append("host_available_below_constrained_threshold")

        swap_activity = snapshot.swap_activity_bytes_per_second
        swap_activity_protected = (
            host_available is not None
            and host_available < thresholds.constrained_available_bytes
            and swap_activity is not None
            and math.isfinite(float(swap_activity))
            and swap_activity > thresholds.swap_activity_threshold_bytes_per_second
        )
        if swap_activity_protected:
            reasons.append("swap_activity_above_threshold")

        cgroup_ratio = self._cgroup_ratio(snapshot.cgroup)
        if cgroup_ratio is None:
            missing.append("cgroup_memory_ratio_unavailable")
        elif cgroup_ratio > thresholds.protected_cgroup_ratio:
            reasons.append("cgroup_usage_above_protected_ratio")
        elif cgroup_ratio > thresholds.constrained_cgroup_ratio:
            reasons.append("cgroup_usage_above_constrained_ratio")

        protected = (
            host_available is not None
            and host_available < thresholds.protected_available_bytes
        ) or (
            cgroup_ratio is not None
            and cgroup_ratio > thresholds.protected_cgroup_ratio
        ) or swap_activity_protected
        constrained = (
            host_available is not None
            and host_available < thresholds.constrained_available_bytes
        ) or (
            cgroup_ratio is not None
            and cgroup_ratio > thresholds.constrained_cgroup_ratio
        )
        healthy = (
            host_available is not None
            and host_available > thresholds.recovery_available_bytes
            and cgroup_ratio is not None
            and cgroup_ratio < thresholds.recovery_cgroup_ratio
        )

        hard: list[str] = []
        if (
            snapshot.process_tree_rss_bytes is not None
            and snapshot.process_tree_rss_bytes >= thresholds.hard_process_tree_rss_bytes
        ):
            hard.append("process_tree_rss_hard_limit")
        if (
            snapshot.cgroup is not None
            and snapshot.cgroup.current_bytes is not None
            and snapshot.cgroup.current_bytes >= thresholds.hard_cgroup_current_bytes
        ):
            hard.append("cgroup_memory_hard_limit")
        return _PressureObservation(
            constrained=constrained,
            protected=protected,
            healthy=healthy,
            reasons=tuple(reasons),
            missing_reasons=tuple(missing),
            hard_reasons=tuple(hard),
        )

    def _reset_continuity(self, now: float) -> None:
        self._constrained_started = None
        self._protected_started = None
        self._healthy_since = None
        if self._state == self.RECOVERING:
            self._recovering_stable_since = now

    def _enter(self, state: str, now: float) -> None:
        if self._state != state or self._state_since is None:
            self._state = state
            self._state_since = now
        if state == self.RECOVERING:
            self._recovering_stable_since = now
        else:
            self._recovering_stable_since = None
        if state in {self.CONSTRAINED, self.PROTECTED}:
            self._healthy_since = None

    def _result(self, reasons: tuple[str, ...] = ()) -> ResourcePressureState:
        if self._state_since is None:
            raise RuntimeError("resource pressure state has not been sampled")
        allow_daily = self._state in {self.NORMAL, self.CONSTRAINED, self.RECOVERING}
        allow_history = self._state == self.NORMAL
        return ResourcePressureState(
            state=self._state,
            reasons=reasons,
            allow_daily=allow_daily,
            allow_history=allow_history,
            since=self._state_since,
            healthy_since=self._healthy_since,
        )

    def _handle_missing(
        self, observation: _PressureObservation, now: float
    ) -> ResourcePressureState:
        self._constrained_started = None
        self._protected_started = None
        self._healthy_since = None
        self._recovering_stable_since = None
        # Unknown host/cgroup pressure is not a safe admission posture.  A
        # single missing sample enters or keeps protected until both metrics
        # are present and the healthy window completes.
        self._enter(self.PROTECTED, now)
        return self._result(observation.missing_reasons + ("resource_metrics_missing",))

    def _update_normal(
        self, observation: _PressureObservation, now: float
    ) -> ResourcePressureState:
        thresholds = self.thresholds
        if observation.protected:
            if self._protected_started is None:
                self._protected_started = now
            if self._constrained_started is None:
                self._constrained_started = now
            if now - self._protected_started >= thresholds.protected_duration_seconds:
                self._enter(self.PROTECTED, now)
                return self._result(observation.reasons)
        else:
            self._protected_started = None

        if observation.constrained:
            if self._constrained_started is None:
                self._constrained_started = now
            if now - self._constrained_started >= thresholds.constrained_duration_seconds:
                self._enter(self.CONSTRAINED, now)
                return self._result(observation.reasons)
        else:
            self._constrained_started = None

        if observation.healthy:
            if self._healthy_since is None:
                self._healthy_since = now
        else:
            self._healthy_since = None
        return self._result(observation.reasons)

    def _update_restricted(
        self, observation: _PressureObservation, now: float
    ) -> ResourcePressureState:
        thresholds = self.thresholds
        if self._state == self.CONSTRAINED and observation.protected:
            if self._protected_started is None:
                self._protected_started = now
            if now - self._protected_started >= thresholds.protected_duration_seconds:
                self._enter(self.PROTECTED, now)
                return self._result(observation.reasons)
        else:
            self._protected_started = None

        if observation.healthy:
            self._constrained_started = None
            self._protected_started = None
            if self._healthy_since is None:
                self._healthy_since = now
            if now - self._healthy_since >= thresholds.recovery_duration_seconds:
                self._enter(self.RECOVERING, now)
                return self._result(("recovery_window_complete",))
            return self._result(("awaiting_recovery_window",))

        self._healthy_since = None
        self._recovering_stable_since = None
        if observation.constrained:
            if self._constrained_started is None:
                self._constrained_started = now
        else:
            self._constrained_started = None
        return self._result(observation.reasons)

    def _update_recovering(
        self, observation: _PressureObservation, now: float
    ) -> ResourcePressureState:
        thresholds = self.thresholds
        if observation.protected:
            if self._protected_started is None:
                self._protected_started = now
            if self._constrained_started is None:
                self._constrained_started = now
            self._healthy_since = None
            self._recovering_stable_since = None
            if now - self._protected_started >= thresholds.protected_duration_seconds:
                self._enter(self.PROTECTED, now)
                return self._result(observation.reasons)
            return self._result(observation.reasons + ("pressure_reappeared",))
        self._protected_started = None

        if observation.constrained:
            if self._constrained_started is None:
                self._constrained_started = now
            self._healthy_since = None
            self._recovering_stable_since = None
            if now - self._constrained_started >= thresholds.constrained_duration_seconds:
                self._enter(self.CONSTRAINED, now)
                return self._result(observation.reasons)
            return self._result(observation.reasons + ("pressure_reappeared",))
        self._constrained_started = None

        if not observation.healthy:
            self._healthy_since = None
            self._recovering_stable_since = None
            return self._result(("awaiting_healthy_window",))

        if self._healthy_since is None:
            self._healthy_since = now
        if self._recovering_stable_since is None:
            self._recovering_stable_since = now
        if now - self._recovering_stable_since >= thresholds.stable_duration_seconds:
            self._enter(self.NORMAL, now)
            return self._result(())
        return self._result(("stabilizing_after_recovery",))

    def update(self, snapshot: ResourceSnapshot, now: float) -> ResourcePressureState:
        """Consume one sample using the caller supplied monotonic timestamp."""

        if not isinstance(now, (int, float)) or isinstance(now, bool):
            raise ValueError("now must be a finite timestamp")
        now = float(now)
        if not math.isfinite(now):
            raise ValueError("now must be a finite timestamp")
        if self._last_sample_at is not None:
            if now < self._last_sample_at:
                raise ValueError("now must not move backwards")
            if now - self._last_sample_at > self.thresholds.max_sample_gap_seconds:
                self._reset_continuity(now)
        self._last_sample_at = now
        if self._state_since is None:
            self._state_since = now

        observation = self._observe(snapshot)
        if observation.hard_reasons:
            self._constrained_started = None
            self._protected_started = None
            self._healthy_since = None
            self._enter(self.PROTECTED, now)
            return self._result(observation.hard_reasons)
        if observation.missing_reasons:
            return self._handle_missing(observation, now)
        if self._state == self.NORMAL:
            return self._update_normal(observation, now)
        if self._state in {self.CONSTRAINED, self.PROTECTED}:
            return self._update_restricted(observation, now)
        return self._update_recovering(observation, now)
