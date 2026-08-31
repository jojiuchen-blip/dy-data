from __future__ import annotations

import hashlib
import json
import math
import os
import signal
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable

from sqlalchemy import case, select, update
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.db import make_engine, make_session_factory
from apps.api.dy_api.models import ComponentHeartbeat, JobRun, OpsCommand
from apps.ops_agent.docker_api import (
    ALLOWED_TARGETS,
    DEFAULT_DOCKER_REQUEST_TIMEOUT_SECONDS,
    DockerAPI,
    DockerAPIError,
    GuardrailViolation,
    RESTART_RESPONSE_PADDING_SECONDS,
    UnixSocketDockerTransport,
)


_STOP = False
_ALLOWED_ACTIONS = frozenset({"restart"})
DEFAULT_COMMAND_TTL_SECONDS = 120
MIN_COMMAND_TTL_SECONDS = 1
MAX_COMMAND_TTL_SECONDS = 3600
DEFAULT_COOLDOWN_SECONDS = 300
_RESTART_GRACE_SECONDS = {"worker": 300, "browser": 30}


def _handle_stop(_signum: int, _frame: object) -> None:
    global _STOP
    _STOP = True


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _canonical_payload_sha(command: OpsCommand | "CommandEnvelope") -> str:
    payload = {
        "command_type": command.command_type,
        "target_component": command.target_component,
        "reason": command.request_reason,
        "related_job_id": command.related_job_id,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class CommandEnvelope:
    command_id: str
    command_type: str
    target_component: str
    request_reason: str
    related_job_id: str | None
    request_payload_sha256: str
    expires_at: datetime
    started_at: datetime
    claimed_by: str
    lease_epoch: int


@dataclass(frozen=True)
class CommandExecutionResult:
    command_id: str
    status: str
    result_code: str


class OpsAgent:
    def __init__(
        self,
        *,
        factory: sessionmaker[Session],
        docker: DockerAPI,
        instance_id: str,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
        heartbeat_timeout_seconds: float = 90,
        heartbeat_poll_seconds: float = 2,
        browser_active_file: Path | str | None = None,
        command_ttl_seconds: int = DEFAULT_COMMAND_TTL_SECONDS,
        cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS,
    ) -> None:
        if not instance_id.strip():
            raise ValueError("ops agent instance_id is required")
        if heartbeat_timeout_seconds < 0 or heartbeat_poll_seconds < 0:
            raise ValueError("heartbeat timing must be non-negative")
        if not MIN_COMMAND_TTL_SECONDS <= command_ttl_seconds <= MAX_COMMAND_TTL_SECONDS:
            raise ValueError(
                "command_ttl_seconds must be between "
                f"{MIN_COMMAND_TTL_SECONDS} and {MAX_COMMAND_TTL_SECONDS}"
            )
        if cooldown_seconds != DEFAULT_COOLDOWN_SECONDS:
            raise ValueError(f"cooldown_seconds must be fixed at {DEFAULT_COOLDOWN_SECONDS}")
        self.factory = factory
        self.docker = docker
        self.instance_id = instance_id.strip()
        self.clock = clock or (lambda: datetime.now(UTC))
        self.monotonic = monotonic or time.monotonic
        self.sleep = sleep or time.sleep
        self.heartbeat_timeout_seconds = heartbeat_timeout_seconds
        self.heartbeat_poll_seconds = heartbeat_poll_seconds
        self.browser_active_file = Path(browser_active_file) if browser_active_file else None
        self.command_ttl_seconds = command_ttl_seconds
        self.cooldown_seconds = cooldown_seconds

    def run_once(self) -> CommandExecutionResult | None:
        claimed = self._claim_next()
        if isinstance(claimed, CommandExecutionResult) or claimed is None:
            return claimed
        command = claimed
        if command.command_type not in _ALLOWED_ACTIONS or command.target_component not in ALLOWED_TARGETS:
            return self._finish(command, "rejected", "command_not_allowlisted")
        if _canonical_payload_sha(command) != command.request_payload_sha256:
            return self._finish(command, "rejected", "command_payload_mismatch")
        if command.target_component == "browser" and self._browser_export_active():
            return self._finish(command, "rejected", "browser_export_active")
        try:
            matches = self.docker.resolve_target(command.target_component)
        except GuardrailViolation:
            return self._finish(command, "rejected", "command_not_allowlisted")
        except DockerAPIError:
            return self._finish(command, "failed", "docker_lookup_failed")
        if len(matches) != 1:
            return self._finish(command, "rejected", "container_match_count")
        before = self._latest_heartbeat(command.target_component)
        grace_seconds = self._restart_grace_seconds(command.target_component)
        try:
            command = self._renew_claim(
                command,
                self._remaining_lease_seconds(command.target_component, include_lookup=True),
            )
        except RuntimeError:
            return CommandExecutionResult(command.command_id, "failed", "command_lease_lost")
        try:
            restart_matches = self.docker.resolve_target(command.target_component)
        except GuardrailViolation:
            return self._finish(command, "rejected", "restart_guardrail_rejected")
        except DockerAPIError:
            return self._finish(command, "failed", "restart_request_failed")
        if len(restart_matches) != 1:
            return self._finish(command, "rejected", "restart_guardrail_rejected")
        try:
            command = self._renew_claim(
                command,
                self._remaining_lease_seconds(command.target_component, include_lookup=False),
            )
        except RuntimeError:
            return CommandExecutionResult(command.command_id, "failed", "command_lease_lost")
        try:
            self.docker.restart(restart_matches[0], grace_seconds=grace_seconds)
        except GuardrailViolation:
            return self._finish(command, "rejected", "restart_guardrail_rejected")
        except DockerAPIError:
            return self._finish(command, "failed", "restart_request_failed")
        if not self._replacement_heartbeat_seen(command, before):
            return self._finish(command, "failed", "replacement_heartbeat_timeout")
        return self._finish(command, "success", "restart_confirmed")

    def _restart_grace_seconds(self, target_component: str) -> int:
        try:
            return _RESTART_GRACE_SECONDS[target_component]
        except KeyError as exc:
            raise GuardrailViolation("target is not allowlisted") from exc

    def _claim_lease_seconds(self, target_component: str) -> int:
        return int(
            math.ceil(
                self.command_ttl_seconds
                + (2 * DEFAULT_DOCKER_REQUEST_TIMEOUT_SECONDS)
                + self._restart_grace_seconds(target_component)
                + RESTART_RESPONSE_PADDING_SECONDS
                + self.heartbeat_timeout_seconds
                + self.heartbeat_poll_seconds
                + 1
            )
        )

    def _remaining_lease_seconds(self, target_component: str, *, include_lookup: bool) -> int:
        lookup_budget = DEFAULT_DOCKER_REQUEST_TIMEOUT_SECONDS if include_lookup else 0
        return int(
            math.ceil(
                lookup_budget
                + self._restart_grace_seconds(target_component)
                + RESTART_RESPONSE_PADDING_SECONDS
                + self.heartbeat_timeout_seconds
                + self.heartbeat_poll_seconds
                + 1
            )
        )

    def _renew_claim(
        self,
        command: CommandEnvelope,
        minimum_remaining_seconds: int,
    ) -> CommandEnvelope:
        now = _as_utc(self.clock())
        assert now is not None
        renewed_until = now + timedelta(seconds=minimum_remaining_seconds)
        with self.factory() as session:
            renewed = session.execute(
                update(OpsCommand)
                .where(
                    OpsCommand.command_id == command.command_id,
                    OpsCommand.status == "running",
                    OpsCommand.claimed_by == command.claimed_by,
                    OpsCommand.lease_epoch == command.lease_epoch,
                    OpsCommand.expires_at > now,
                )
                .values(
                    expires_at=case(
                        (OpsCommand.expires_at < renewed_until, renewed_until),
                        else_=OpsCommand.expires_at,
                    ),
                    updated_at=now,
                )
                .execution_options(synchronize_session=False)
            )
            if renewed.rowcount != 1:
                session.rollback()
                raise RuntimeError("ops command lease was lost before restart")
            session.commit()
        current_expiry = _as_utc(command.expires_at) or renewed_until
        return replace(command, expires_at=max(current_expiry, renewed_until))

    def _claim_next(self) -> CommandEnvelope | CommandExecutionResult | None:
        now = _as_utc(self.clock())
        assert now is not None
        with self.factory() as session:
            dialect = session.get_bind().dialect.name
            if dialect == "sqlite":
                session.connection().exec_driver_sql("BEGIN IMMEDIATE")

            # A running command whose claim lease expired becomes pending again.
            # The epoch is advanced by the subsequent claim, fencing the old owner.
            running_query = (
                select(OpsCommand)
                .where(OpsCommand.status == "running", OpsCommand.expires_at <= now)
                .order_by(OpsCommand.started_at, OpsCommand.command_id)
                .limit(1)
            )
            if dialect == "postgresql":
                running_query = running_query.with_for_update(skip_locked=True)
            expired_running = session.scalar(running_query)
            if expired_running is not None:
                expired_running.status = "pending"
                expired_running.claimed_by = None
                expired_running.started_at = None
                expired_running.finished_at = None
                expired_running.expires_at = now + timedelta(
                    seconds=self._claim_lease_seconds(expired_running.target_component)
                )
                expired_running.result_code = "command_reclaimed"
                expired_running.result_summary = "command claim lease expired and was reclaimed"
                expired_running.updated_at = now
                session.flush()

            expired_query = (
                select(OpsCommand)
                .where(OpsCommand.status == "pending", OpsCommand.expires_at <= now)
                .order_by(OpsCommand.created_at, OpsCommand.command_id)
                .limit(1)
            )
            if dialect == "postgresql":
                expired_query = expired_query.with_for_update(skip_locked=True)
            expired = session.scalar(expired_query)
            if expired is not None:
                expired.status = "expired"
                expired.finished_at = now
                expired.result_code = "command_expired"
                expired.result_summary = "command expired before claim"
                expired.updated_at = now
                self._write_heartbeat(session, now)
                command_id = expired.command_id
                session.commit()
                return CommandExecutionResult(command_id, "expired", "command_expired")

            query = (
                select(OpsCommand)
                .where(OpsCommand.status == "pending", OpsCommand.expires_at > now)
                .order_by(OpsCommand.created_at, OpsCommand.command_id)
                .limit(1)
            )
            if dialect == "postgresql":
                query = query.with_for_update(skip_locked=True)
            row = session.scalar(query)
            if row is None:
                self._write_heartbeat(session, now)
                session.commit()
                return None

            lease_expires_at = now + timedelta(
                seconds=self._claim_lease_seconds(row.target_component)
            )
            next_epoch = (row.lease_epoch or 0) + 1
            claimed = session.execute(
                update(OpsCommand)
                .where(
                    OpsCommand.command_id == row.command_id,
                    OpsCommand.status == "pending",
                    OpsCommand.expires_at > now,
                )
                .values(
                    status="running",
                    claimed_by=self.instance_id,
                    lease_epoch=next_epoch,
                    started_at=now,
                    expires_at=lease_expires_at,
                    finished_at=None,
                    result_code=None,
                    result_summary=None,
                    updated_at=now,
                )
                .execution_options(synchronize_session=False)
            )
            if claimed.rowcount != 1:
                session.rollback()
                return None
            self._write_heartbeat(session, now)
            envelope = CommandEnvelope(
                command_id=row.command_id,
                command_type=row.command_type,
                target_component=row.target_component,
                request_reason=row.request_reason,
                related_job_id=row.related_job_id,
                request_payload_sha256=row.request_payload_sha256,
                expires_at=lease_expires_at,
                started_at=now,
                claimed_by=self.instance_id,
                lease_epoch=next_epoch,
            )
            session.commit()
            return envelope

    def _finish(
        self,
        command: CommandEnvelope,
        status: str,
        result_code: str,
    ) -> CommandExecutionResult:
        if status not in {"success", "failed", "rejected", "expired", "cancelled"}:
            raise ValueError("invalid ops command completion status")
        now = _as_utc(self.clock())
        assert now is not None
        with self.factory() as session:
            finished = session.execute(
                update(OpsCommand)
                .where(
                    OpsCommand.command_id == command.command_id,
                    OpsCommand.status == "running",
                    OpsCommand.claimed_by == command.claimed_by,
                    OpsCommand.lease_epoch == command.lease_epoch,
                    OpsCommand.expires_at > now,
                )
                .values(
                    status=status,
                    finished_at=now,
                    cooldown_until=now + timedelta(seconds=self.cooldown_seconds),
                    result_code=result_code,
                    result_summary=result_code.replace("_", " "),
                    updated_at=now,
                )
                .execution_options(synchronize_session=False)
            )
            if finished.rowcount != 1:
                session.rollback()
                raise RuntimeError("ops command lease was lost before completion")
            self._write_heartbeat(session, now)
            session.commit()
        return CommandExecutionResult(command.command_id, status, result_code)

    def _latest_heartbeat(self, component_type: str) -> ComponentHeartbeat | None:
        with self.factory() as session:
            row = session.scalar(
                select(ComponentHeartbeat)
                .where(ComponentHeartbeat.component_type == component_type)
                .order_by(ComponentHeartbeat.last_heartbeat_at.desc())
                .limit(1)
            )
            if row is not None:
                session.expunge(row)
            return row

    def _browser_export_active(self) -> bool:
        if self.browser_active_file is not None and self.browser_active_file.exists():
            return True
        try:
            with self.factory() as session:
                active_job = session.scalar(
                    select(JobRun.job_id)
                    .where(
                        JobRun.job_name == "backend_aweme_export",
                        JobRun.status.in_(("queued", "running")),
                    )
                    .limit(1)
                )
            if active_job is not None:
                return True
        except Exception:
            # If the dedicated role cannot read the activity signal, fail
            # closed rather than restarting a possibly active export.
            return True
        row = self._latest_heartbeat("browser")
        if row is None:
            return False
        activity = row.activity_json if isinstance(row.activity_json, dict) else {}
        return bool(
            row.current_job_id
            or activity.get("export_active") is True
            or activity.get("state") in {"active", "running", "exporting"}
        )

    def _replacement_heartbeat_seen(
        self,
        command: CommandEnvelope,
        before: ComponentHeartbeat | None,
    ) -> bool:
        deadline = self.monotonic() + self.heartbeat_timeout_seconds
        while True:
            current = self._latest_heartbeat(command.target_component)
            if current is not None:
                heartbeat_at = _as_utc(current.last_heartbeat_at)
                current_started = _as_utc(current.started_at)
                before_started = _as_utc(before.started_at) if before is not None else None
                different_instance = before is None or (
                    current.component_instance_id != before.component_instance_id
                )
                restarted_same_instance = bool(
                    before is not None
                    and current.component_instance_id == before.component_instance_id
                    and current_started is not None
                    and before_started is not None
                    and current_started > before_started
                )
                if (
                    heartbeat_at is not None
                    and heartbeat_at > command.started_at
                    and (different_instance or restarted_same_instance)
                ):
                    return True
            if self.monotonic() >= deadline:
                return False
            self.sleep(self.heartbeat_poll_seconds)

    def _write_heartbeat(self, session: Session, now: datetime) -> None:
        row = session.get(ComponentHeartbeat, self.instance_id)
        if row is None:
            row = ComponentHeartbeat(
                component_instance_id=self.instance_id,
                component_type="ops_agent",
                status="healthy",
                version=os.getenv("OPS_AGENT_VERSION"),
                started_at=now,
                last_heartbeat_at=now,
                current_job_id=None,
                current_attempt_id=None,
                rss_bytes=None,
                rss_peak_bytes=None,
                memory_limit_bytes=None,
                cpu_percent=None,
                queue_depth=0,
                activity_json={},
                queue_summary_json={},
                created_at=now,
                updated_at=now,
            )
            session.add(row)
        else:
            row.status = "healthy"
            row.last_heartbeat_at = now
            row.updated_at = now


def _validate_static_environment() -> tuple[str, str]:
    targets = os.getenv("OPS_AGENT_ALLOWED_TARGETS", "worker,browser")
    actions = os.getenv("OPS_AGENT_ALLOWED_ACTIONS", "restart")
    if targets != "worker,browser" or actions != "restart":
        raise RuntimeError("ops agent allowlist is fixed and cannot be widened")
    database_url = (os.getenv("OPS_AGENT_DATABASE_URL") or "").strip()
    if not database_url:
        raise RuntimeError("OPS_AGENT_DATABASE_URL is required")
    project = (os.getenv("COMPOSE_PROJECT_NAME") or "dy-dashboard").strip()
    if not project:
        raise RuntimeError("COMPOSE_PROJECT_NAME is required")
    return database_url, project


def _command_ttl_from_env() -> int:
    raw = os.getenv("OPS_AGENT_COMMAND_TTL_SECONDS", str(DEFAULT_COMMAND_TTL_SECONDS))
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("OPS_AGENT_COMMAND_TTL_SECONDS must be an integer") from exc
    if not MIN_COMMAND_TTL_SECONDS <= value <= MAX_COMMAND_TTL_SECONDS:
        raise RuntimeError(
            "OPS_AGENT_COMMAND_TTL_SECONDS must be between "
            f"{MIN_COMMAND_TTL_SECONDS} and {MAX_COMMAND_TTL_SECONDS}"
        )
    return value


def _cooldown_seconds_from_env() -> int:
    raw = os.getenv("OPS_AGENT_COOLDOWN_SECONDS", str(DEFAULT_COOLDOWN_SECONDS))
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("OPS_AGENT_COOLDOWN_SECONDS must be an integer") from exc
    if value != DEFAULT_COOLDOWN_SECONDS:
        raise RuntimeError(
            f"OPS_AGENT_COOLDOWN_SECONDS must be fixed at {DEFAULT_COOLDOWN_SECONDS}"
        )
    return value


def _poll_seconds_from_env() -> float:
    raw = os.getenv("OPS_AGENT_POLL_SECONDS", "2")
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("OPS_AGENT_POLL_SECONDS must be a finite number") from exc
    if not math.isfinite(value):
        raise RuntimeError("OPS_AGENT_POLL_SECONDS must be a finite number")
    return max(0.5, min(30, value))


def main() -> None:
    database_url, project = _validate_static_environment()
    factory = make_session_factory(make_engine(database_url))
    socket_path = os.getenv("OPS_AGENT_DOCKER_SOCKET", "/var/run/docker.sock")
    agent = OpsAgent(
        factory=factory,
        docker=DockerAPI(
            transport=UnixSocketDockerTransport(socket_path),
            compose_project=project,
        ),
        instance_id=os.getenv("OPS_AGENT_INSTANCE_ID", f"ops-agent-{os.getpid()}"),
        heartbeat_timeout_seconds=float(os.getenv("OPS_AGENT_HEARTBEAT_TIMEOUT_SECONDS", "90")),
        heartbeat_poll_seconds=float(os.getenv("OPS_AGENT_HEARTBEAT_POLL_SECONDS", "2")),
        browser_active_file=os.getenv(
            "BROWSER_EXPORT_ACTIVE_FILE", "/run/browser/browser-export.active"
        ),
        command_ttl_seconds=_command_ttl_from_env(),
        cooldown_seconds=_cooldown_seconds_from_env(),
    )
    health_file = Path(os.getenv("OPS_AGENT_HEALTH_FILE", "/tmp/ops-agent.healthy"))
    poll_seconds = _poll_seconds_from_env()
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
    while not _STOP:
        agent.run_once()
        health_file.touch()
        time.sleep(poll_seconds)


if __name__ == "__main__":
    main()
