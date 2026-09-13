"""Continuously sample scheduler pressure, including while a child is busy.

The scheduler owns the policy clock. Children only consume its fresh heartbeat,
so starting a child cannot reset pressure/recovery dwell times.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from apps.api.dy_api.models import ComponentHeartbeat
from apps.ops_agent.resources import ResourceAction, ResourceDecision, collect_resource_snapshot
from apps.worker.repositories import is_priority_resource_config

LOGGER = logging.getLogger(__name__)
SAMPLE_SECONDS = 5
STALE_SECONDS = 30
_monitor: ResourceMonitor | None = None


def read_swap_activity_bytes() -> int | None:
    """Read cumulative actual swap IO, not occupied swap space."""
    try:
        values = {}
        for line in Path("/proc/vmstat").read_text(encoding="ascii").splitlines():
            key, value = line.split()
            if key in {"pswpin", "pswpout"}:
                values[key] = int(value)
        if len(values) != 2:
            return None
        return sum(values.values()) * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, AttributeError):
        return None


def guard_enabled() -> bool:
    return os.getenv("WORKER_RESOURCE_GUARD_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


class ResourcePauseError(RuntimeError):
    """A checkpoint yield, distinct from a real memory-limit failure."""

    def __init__(self) -> None:
        super().__init__("worker_resource_pause retry_after_seconds=60")


class ResourceMonitor:
    def __init__(self, factory, *, policy=None, sampler=None) -> None:
        self.factory = factory
        # A process restart must not bypass an in-flight recovery dwell. Start
        # protected and establish a fresh continuous healthy observation.
        if policy is None:
            from apps.ops_agent.resources import PressureThresholds, ResourcePressurePolicy

            policy = ResourcePressurePolicy(PressureThresholds.from_env(), initial_state="protected")
        self.policy = policy
        self.sampler = sampler or (lambda: collect_resource_snapshot(os.getpid()))
        self.instance_id = f"worker-resource-monitor-{socket.gethostname()}-{os.getpid()}-{uuid4().hex}"
        self.started_at = datetime.now(UTC)
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.payload: dict[str, Any] | None = None
        self.sample_monotonic: float | None = None
        self.thread: threading.Thread | None = None
        self.previous_swap_activity: tuple[float, int] | None = None

    def sample(self) -> dict[str, Any]:
        now = datetime.now(UTC)
        clock = time.monotonic()
        try:
            snapshot = self.sampler()
            activity = read_swap_activity_bytes()
            previous = self.previous_swap_activity
            rate = None
            if activity is not None:
                if previous and 0 < clock - previous[0] <= 15 and activity >= previous[1]:
                    rate = (activity - previous[1]) / (clock - previous[0])
                self.previous_swap_activity = (clock, activity)
            else:
                self.previous_swap_activity = None
            snapshot = replace(snapshot, swap_activity_bytes_per_second=rate)
            state = self.policy.update(snapshot, now=clock)
            state_name = getattr(state.state, "value", state.state)
            since = now - timedelta(seconds=max(0, clock - state.since))
            cgroup = snapshot.cgroup
            ratio = (cgroup.current_bytes / cgroup.limit_bytes
                     if cgroup and cgroup.current_bytes is not None and cgroup.limit_bytes else None)
            payload = {
                "state": state_name, "reasons": list(state.reasons),
                "allow_daily": state.allow_daily, "allow_history": state.allow_history,
                "since": since.isoformat(), "sampled_at": now.isoformat(),
                "duration_seconds": max(0, int(clock - state.since)),
                "recovery_condition": self.recovery_condition(),
                "host_available_bytes": snapshot.host.available_bytes if snapshot.host else None,
                "swap_used_bytes": snapshot.host.swap_used_bytes if snapshot.host else None,
                "cgroup_used_ratio": ratio,
                "swap_activity_bytes_per_second": rate,
            }
        except Exception:
            # Never log the exception: environment/sampler errors can include
            # deployment details. Unknown pressure must not admit heavy work.
            with self.lock:
                previous_payload = dict(self.payload or {})
            unknown_since = (
                datetime.fromisoformat(previous_payload["since"])
                if previous_payload.get("state") == "unknown" else now
            )
            payload = {
                "state": "unknown", "reasons": ["resource_sample_unavailable"],
                "allow_daily": False, "allow_history": False,
                "since": unknown_since.isoformat(), "sampled_at": now.isoformat(),
                "duration_seconds": max(0, int((now - unknown_since).total_seconds())),
                "recovery_condition": "等待资源采样恢复",
                "host_available_bytes": None, "swap_used_bytes": None, "cgroup_used_ratio": None,
            }
        with self.lock:
            old_state = self.payload.get("state") if self.payload else None
            self.payload = payload
            self.sample_monotonic = clock
        if old_state != payload["state"]:
            LOGGER.info("worker_resource_state state=%s reasons=%s", payload["state"], payload["reasons"])
        try:
            self.publish(payload, now=now)
        except Exception:
            LOGGER.warning("worker_resource_heartbeat_write_failed")
        return payload

    def recovery_condition(self) -> str:
        thresholds = getattr(self.policy, "thresholds", None)
        if thresholds is None:
            return "等待连续健康资源样本"
        return (
            f"可用内存超过 {thresholds.recovery_available_bytes / 1024**3:g} GiB，"
            f"容器内存低于 {thresholds.recovery_cgroup_ratio:.0%}，"
            f"连续 {thresholds.recovery_duration_seconds:g} 秒后恢复日批；"
            f"再稳定 {thresholds.stable_duration_seconds:g} 秒恢复历史补拉"
        )

    def publish(self, payload: dict[str, Any], *, now: datetime) -> None:
        if self.factory is None:
            return
        with self.factory() as session:
            row = session.get(ComponentHeartbeat, self.instance_id)
            if row is None:
                row = ComponentHeartbeat(
                    component_instance_id=self.instance_id, component_type="worker",
                    started_at=self.started_at, last_heartbeat_at=now, status="starting",
                )
                session.add(row)
            row.last_heartbeat_at = now
            row.updated_at = now
            row.status = "healthy" if payload["state"] == "normal" else "draining"
            row.activity_json = {"resource_guard": payload}
            session.commit()

    def start(self) -> None:
        os.environ["DY_WORKER_RESOURCE_MONITOR_ID"] = self.instance_id
        self.sample()
        self.thread = threading.Thread(target=self._run, name="worker-resource-monitor", daemon=True)
        self.thread.start()

    def _run(self) -> None:
        while not self.stop_event.wait(SAMPLE_SECONDS):
            self.sample()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)


def start_resource_monitor(factory) -> ResourceMonitor | None:
    global _monitor
    if not guard_enabled():
        return None
    _monitor = ResourceMonitor(factory)
    _monitor.start()
    return _monitor


def current_resource_decision() -> ResourceDecision:
    if not guard_enabled():
        return ResourceDecision(ResourceAction.ALLOW, ())
    monitor = _monitor
    if monitor is None:
        return ResourceDecision(ResourceAction.STOP, ("resource_monitor_unavailable",))
    with monitor.lock:
        payload = dict(monitor.payload or {})
        sampled = monitor.sample_monotonic
    if sampled is None or time.monotonic() - sampled > STALE_SECONDS:
        return ResourceDecision(ResourceAction.STOP, ("resource_monitor_stale",))
    if not payload.get("allow_daily"):
        return ResourceDecision(ResourceAction.STOP, tuple(payload.get("reasons", ())))
    if not payload.get("allow_history"):
        return ResourceDecision(ResourceAction.DRAIN, tuple(payload.get("reasons", ())))
    return ResourceDecision(ResourceAction.ALLOW, ())


def require_resource_admission(session, job) -> None:
    """Check only at page/stage transaction boundaries; never kill a writer."""
    if not guard_enabled() or not is_priority_resource_config(job.config_version):
        return
    monitor_id = os.getenv("DY_WORKER_RESOURCE_MONITOR_ID")
    statement = select(ComponentHeartbeat.last_heartbeat_at, ComponentHeartbeat.activity_json).where(
        ComponentHeartbeat.component_instance_id == monitor_id,
        ComponentHeartbeat.component_type == "worker",
    )
    row = session.execute(statement).first() if monitor_id else None
    if row is None:
        raise ResourcePauseError()
    heartbeat, activity = row
    heartbeat = heartbeat.replace(tzinfo=UTC) if heartbeat.tzinfo is None else heartbeat
    if (datetime.now(UTC) - heartbeat).total_seconds() > STALE_SECONDS:
        raise ResourcePauseError()
    payload = (activity or {}).get("resource_guard") or {}
    purpose = (job.metadata_json or {}).get("priority_purpose", "daily_required")
    allowed = payload.get("allow_history" if purpose == "history" else "allow_daily")
    if allowed is not True:
        raise ResourcePauseError()
