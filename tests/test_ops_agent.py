from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from apps.api.dy_api.models import Base, ComponentHeartbeat, JobRun, OpsCommand


def _payload_sha(*, target: str, reason: str, related_job_id: str | None = None) -> str:
    payload = {
        "command_type": "restart",
        "target_component": target,
        "reason": reason,
        "related_job_id": related_job_id,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@pytest.fixture
def factory(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'ops-agent.sqlite'}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    engine.dispose()


def _seed_command(
    factory,
    *,
    now: datetime,
    target: str = "worker",
    status: str = "pending",
    expires_at: datetime | None = None,
    payload_sha: str | None = None,
) -> str:
    command_id = f"ops-{target}-{now:%H%M%S%f}"
    reason = f"restart {target} after a stale heartbeat"
    with factory() as session:
        session.add(
            OpsCommand(
                command_id=command_id,
                command_type="restart",
                target_component=target,
                requested_by="system-admin",
                request_reason=reason,
                confirmed_at=now,
                status=status,
                idempotency_key_hash=hashlib.sha256(command_id.encode()).hexdigest(),
                request_payload_sha256=payload_sha
                or _payload_sha(target=target, reason=reason),
                related_job_id=None,
                claimed_by=None,
                lease_epoch=None,
                created_at=now,
                started_at=None,
                finished_at=None,
                expires_at=expires_at or now + timedelta(minutes=2),
                cooldown_until=now + timedelta(minutes=5),
                result_code=None,
                result_summary=None,
                updated_at=now,
            )
        )
        session.commit()
    return command_id


def _seed_heartbeat(
    factory,
    *,
    component_type: str,
    instance_id: str,
    now: datetime,
    started_at: datetime,
    activity: dict | None = None,
) -> None:
    with factory() as session:
        session.add(
            ComponentHeartbeat(
                component_instance_id=instance_id,
                component_type=component_type,
                status="healthy",
                version="test",
                started_at=started_at,
                last_heartbeat_at=now,
                current_job_id=None,
                current_attempt_id=None,
                rss_bytes=1,
                rss_peak_bytes=1,
                memory_limit_bytes=1024,
                cpu_percent=0,
                queue_depth=0,
                activity_json=activity or {},
                queue_summary_json={},
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()


class FakeDocker:
    def __init__(self, refs, *, on_restart=None):
        self.refs = list(refs)
        self.on_restart = on_restart
        self.resolve_calls: list[str] = []
        self.restart_calls: list[tuple[str, str, int]] = []

    def resolve_target(self, target: str):
        self.resolve_calls.append(target)
        return list(self.refs)

    def restart(self, container, *, grace_seconds: int) -> None:
        self.restart_calls.append((container.service, container.container_id, grace_seconds))
        if self.on_restart is not None:
            self.on_restart()


def _agent(
    factory,
    docker,
    now: datetime,
    *,
    instance_id: str = "ops-agent-test",
    clock=None,
    browser_active_file: Path | None = None,
    command_ttl_seconds: int = 120,
):
    from apps.ops_agent.main import OpsAgent

    return OpsAgent(
        factory=factory,
        docker=docker,
        instance_id=instance_id,
        clock=clock or (lambda: now),
        sleep=lambda _seconds: None,
        heartbeat_timeout_seconds=0,
        heartbeat_poll_seconds=0,
        browser_active_file=browser_active_file,
        command_ttl_seconds=command_ttl_seconds,
    )


def test_expired_command_never_reaches_docker(factory) -> None:
    from apps.ops_agent.docker_api import ContainerRef

    now = datetime(2026, 8, 9, 1, 0, tzinfo=UTC)
    command_id = _seed_command(
        factory,
        now=now - timedelta(minutes=3),
        expires_at=now - timedelta(minutes=1),
    )
    docker = FakeDocker([ContainerRef(container_id="worker-1", service="worker")])

    result = _agent(factory, docker, now).run_once()

    assert result is not None and result.status == "expired"
    assert docker.resolve_calls == []
    with factory() as session:
        command = session.get(OpsCommand, command_id)
        assert command is not None and command.status == "expired"
        assert command.result_code == "command_expired"


def test_payload_tampering_is_rejected_before_container_lookup(factory) -> None:
    from apps.ops_agent.docker_api import ContainerRef

    now = datetime(2026, 8, 9, 1, 5, tzinfo=UTC)
    command_id = _seed_command(factory, now=now, payload_sha="0" * 64)
    docker = FakeDocker([ContainerRef(container_id="worker-1", service="worker")])

    result = _agent(factory, docker, now).run_once()

    assert result is not None and result.status == "rejected"
    assert result.result_code == "command_payload_mismatch"
    assert docker.resolve_calls == []
    with factory() as session:
        assert session.get(OpsCommand, command_id).status == "rejected"


@pytest.mark.parametrize("match_count", [0, 2])
def test_zero_or_multiple_container_matches_fail_closed(factory, match_count: int) -> None:
    from apps.ops_agent.docker_api import ContainerRef

    now = datetime(2026, 8, 9, 1, 10, tzinfo=UTC)
    _seed_command(factory, now=now)
    docker = FakeDocker(
        [ContainerRef(container_id=f"worker-{index}", service="worker") for index in range(match_count)]
    )

    result = _agent(factory, docker, now).run_once()

    assert result is not None and result.status == "rejected"
    assert result.result_code == "container_match_count"
    assert docker.restart_calls == []


def test_browser_restart_is_rejected_while_export_is_active(factory) -> None:
    from apps.ops_agent.docker_api import ContainerRef

    now = datetime(2026, 8, 9, 1, 15, tzinfo=UTC)
    _seed_command(factory, now=now, target="browser")
    _seed_heartbeat(
        factory,
        component_type="browser",
        instance_id="browser-old",
        now=now,
        started_at=now - timedelta(hours=1),
        activity={"export_active": True, "job_kind": "backend_aweme_export"},
    )
    docker = FakeDocker([ContainerRef(container_id="browser-1", service="browser")])

    result = _agent(factory, docker, now).run_once()

    assert result is not None and result.status == "rejected"
    assert result.result_code == "browser_export_active"
    assert docker.restart_calls == []


def test_browser_restart_is_rejected_when_export_job_is_running(factory) -> None:
    from apps.ops_agent.docker_api import ContainerRef

    now = datetime(2026, 8, 9, 1, 16, tzinfo=UTC)
    _seed_command(factory, now=now, target="browser")
    with factory() as session:
        session.add(
            JobRun(
                job_id="export-job-1",
                job_name="backend_aweme_export",
                status="running",
                started_at=now,
                metadata_json={},
            )
        )
        session.commit()
    docker = FakeDocker([ContainerRef(container_id="browser-1", service="browser")])

    result = _agent(factory, docker, now).run_once()

    assert result is not None and result.status == "rejected"
    assert result.result_code == "browser_export_active"
    assert docker.restart_calls == []


def test_browser_restart_is_rejected_when_active_marker_exists(factory, tmp_path: Path) -> None:
    from apps.ops_agent.docker_api import ContainerRef

    now = datetime(2026, 8, 9, 1, 17, tzinfo=UTC)
    _seed_command(factory, now=now, target="browser")
    marker = tmp_path / "browser-export.active"
    marker.touch()
    docker = FakeDocker([ContainerRef(container_id="browser-1", service="browser")])

    result = _agent(factory, docker, now, browser_active_file=marker).run_once()

    assert result is not None and result.status == "rejected"
    assert result.result_code == "browser_export_active"
    assert docker.restart_calls == []


def test_worker_restart_is_graceful_and_requires_replacement_heartbeat(factory) -> None:
    from apps.ops_agent.docker_api import ContainerRef

    now = datetime(2026, 8, 9, 1, 20, tzinfo=UTC)
    command_id = _seed_command(factory, now=now)
    _seed_heartbeat(
        factory,
        component_type="worker",
        instance_id="worker-old",
        now=now - timedelta(seconds=5),
        started_at=now - timedelta(hours=1),
    )

    def publish_replacement() -> None:
        _seed_heartbeat(
            factory,
            component_type="worker",
            instance_id="worker-new",
            now=now + timedelta(seconds=1),
            started_at=now + timedelta(seconds=1),
        )

    docker = FakeDocker(
        [ContainerRef(container_id="worker-1", service="worker")],
        on_restart=publish_replacement,
    )

    result = _agent(factory, docker, now).run_once()

    assert result is not None and result.status == "success"
    assert result.result_code == "restart_confirmed"
    assert docker.restart_calls == [("worker", "worker-1", 300)]
    with factory() as session:
        command = session.get(OpsCommand, command_id)
        assert command is not None and command.status == "success"
        assert command.finished_at is not None
        assert command.finished_at.replace(tzinfo=UTC) == now


def test_restart_without_replacement_heartbeat_is_not_reported_success(factory) -> None:
    from apps.ops_agent.docker_api import ContainerRef

    now = datetime(2026, 8, 9, 1, 25, tzinfo=UTC)
    _seed_command(factory, now=now)
    _seed_heartbeat(
        factory,
        component_type="worker",
        instance_id="worker-old",
        now=now,
        started_at=now - timedelta(hours=1),
    )
    docker = FakeDocker([ContainerRef(container_id="worker-1", service="worker")])

    result = _agent(factory, docker, now).run_once()

    assert result is not None and result.status == "failed"
    assert result.result_code == "replacement_heartbeat_timeout"


def test_expired_running_command_is_reclaimed_and_old_owner_is_fenced(factory) -> None:
    from apps.ops_agent.docker_api import ContainerRef
    from apps.ops_agent.main import CommandEnvelope

    now = datetime(2026, 8, 9, 1, 27, tzinfo=UTC)
    command_id = _seed_command(factory, now=now)
    old_agent = _agent(factory, FakeDocker([]), now, instance_id="ops-agent-old")
    old_claim = old_agent._claim_next()
    assert isinstance(old_claim, CommandEnvelope)

    with factory() as session:
        command = session.get(OpsCommand, command_id)
        assert command is not None
        command.created_at = now - timedelta(minutes=10)
        command.expires_at = now - timedelta(seconds=1)
        command.started_at = now - timedelta(seconds=2)
        session.commit()

    new_now = now + timedelta(seconds=3)
    new_agent = _agent(
        factory,
        FakeDocker([ContainerRef(container_id="worker-1", service="worker")]),
        new_now,
        instance_id="ops-agent-new",
    )
    new_claim = new_agent._claim_next()
    assert isinstance(new_claim, CommandEnvelope)
    assert new_claim.claimed_by == "ops-agent-new"
    assert new_claim.lease_epoch == old_claim.lease_epoch + 1

    with pytest.raises(RuntimeError, match="lease"):
        old_agent._finish(old_claim, "success", "restart_confirmed")

    with factory() as session:
        command = session.get(OpsCommand, command_id)
        assert command is not None
        assert command.status == "running"
        assert command.claimed_by == "ops-agent-new"
        assert command.lease_epoch == new_claim.lease_epoch


def test_expired_claim_cannot_complete_before_another_owner_reclaims(factory) -> None:
    from apps.ops_agent.main import CommandEnvelope

    now = datetime(2026, 8, 9, 1, 29, tzinfo=UTC)
    command_id = _seed_command(factory, now=now)
    clock = [now]
    agent = _agent(
        factory,
        FakeDocker([]),
        now,
        clock=lambda: clock[0],
        command_ttl_seconds=2,
    )
    claim = agent._claim_next()
    assert isinstance(claim, CommandEnvelope)
    with factory() as session:
        command = session.get(OpsCommand, command_id)
        assert command is not None
        command.created_at = now - timedelta(minutes=10)
        command.expires_at = now - timedelta(seconds=1)
        session.commit()
    clock[0] = now + timedelta(seconds=3)

    with pytest.raises(RuntimeError, match="lease"):
        agent._finish(claim, "success", "restart_confirmed")
    with factory() as session:
        command = session.get(OpsCommand, command_id)
        assert command is not None and command.status == "running"


def test_docker_api_uses_compose_labels_and_exposes_no_generic_action() -> None:
    from apps.ops_agent.docker_api import DockerAPI, GuardrailViolation

    class Transport:
        def __init__(self):
            self.requests: list[tuple[str, str]] = []

        def request(self, method: str, path: str):
            self.requests.append((method, path))
            return 200, json.dumps(
                [
                    {
                        "Id": "worker-container-id",
                        "Labels": {
                            "com.docker.compose.project": "dy-dashboard",
                            "com.docker.compose.service": "worker",
                        },
                    }
                ]
            ).encode()

    transport = Transport()
    api = DockerAPI(transport=transport, compose_project="dy-dashboard")

    refs = api.resolve_target("worker")

    assert [ref.container_id for ref in refs] == ["worker-container-id"]
    assert transport.requests[0][0] == "GET"
    assert "com.docker.compose.project" in transport.requests[0][1]
    assert "com.docker.compose.service" in transport.requests[0][1]
    with pytest.raises(GuardrailViolation, match="target"):
        api.resolve_target("api")
    assert not hasattr(api, "exec")
    assert not hasattr(api, "stop")
    assert not hasattr(api, "remove")
    assert not hasattr(api, "scale")


@pytest.mark.parametrize("grace_seconds", [30, 300])
def test_docker_restart_response_timeout_covers_the_grace_period(grace_seconds: int) -> None:
    from apps.ops_agent.docker_api import ContainerRef, DockerAPI

    class Transport:
        def __init__(self) -> None:
            self.requests: list[tuple[str, str, float | None]] = []

        def request(
            self,
            method: str,
            path: str,
            *,
            timeout: float | None = None,
        ) -> tuple[int, bytes]:
            self.requests.append((method, path, timeout))
            return 204, b""

    transport = Transport()
    api = DockerAPI(transport=transport, compose_project="dy-dashboard")

    api.restart(
        ContainerRef(container_id="worker-container-id", service="worker"),
        grace_seconds=grace_seconds,
    )

    method, path, timeout = transport.requests[0]
    assert method == "POST"
    assert "/restart?" in path
    assert timeout is not None
    assert timeout > grace_seconds
    assert timeout <= grace_seconds + 30


def test_static_environment_cannot_widen_ops_agent_allowlist(monkeypatch) -> None:
    from apps.ops_agent.main import _validate_static_environment

    monkeypatch.setenv(
        "OPS_AGENT_DATABASE_URL",
        "postgresql+psycopg://dy_ops_agent:secret@postgres:5432/dy_dashboard",
    )
    monkeypatch.delenv("COMPOSE_PROJECT_NAME", raising=False)
    monkeypatch.delenv("OPS_AGENT_ALLOWED_TARGETS", raising=False)
    monkeypatch.delenv("OPS_AGENT_ALLOWED_ACTIONS", raising=False)
    assert _validate_static_environment() == (
        "postgresql+psycopg://dy_ops_agent:secret@postgres:5432/dy_dashboard",
        "dy-dashboard",
    )

    monkeypatch.setenv("OPS_AGENT_ALLOWED_TARGETS", "worker,browser,api")
    with pytest.raises(RuntimeError, match="allowlist"):
        _validate_static_environment()


def test_claim_is_atomic_and_a_command_executes_once(factory) -> None:
    from apps.ops_agent.docker_api import ContainerRef

    now = datetime(2026, 8, 9, 1, 30, tzinfo=UTC)
    _seed_command(factory, now=now)

    def publish_replacement() -> None:
        _seed_heartbeat(
            factory,
            component_type="worker",
            instance_id="worker-new",
            now=now + timedelta(seconds=1),
            started_at=now + timedelta(seconds=1),
        )

    docker = FakeDocker(
        [ContainerRef(container_id="worker-1", service="worker")],
        on_restart=publish_replacement,
    )
    first = _agent(factory, docker, now).run_once()
    second = _agent(factory, docker, now, instance_id="ops-agent-second").run_once()

    assert first is not None and first.status == "success"
    assert second is None
    assert docker.restart_calls == [("worker", "worker-1", 300)]
    with factory() as session:
        assert len(list(session.scalars(select(OpsCommand)))) == 1
