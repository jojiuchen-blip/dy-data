from __future__ import annotations

import hashlib
import http.client
import json
import math
import re
import socket
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable, Protocol
from urllib.parse import quote, urlencode


ALLOWED_TARGETS = frozenset({"worker", "browser"})
DEFAULT_DOCKER_REQUEST_TIMEOUT_SECONDS = 10
RESTART_RESPONSE_PADDING_SECONDS = 15
BROWSER_OBSERVATION_TIMEOUT_SECONDS = 2 * DEFAULT_DOCKER_REQUEST_TIMEOUT_SECONDS
BROWSER_HEALTH_MAX_AGE_SECONDS = 90
_CONTAINER_ID = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_OBSERVED_CONTAINER_ID = re.compile(r"^[a-f0-9]{64}$")
_DOCKER_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|\+00:00)$")


class GuardrailViolation(RuntimeError):
    """Raised when a request falls outside the fixed Docker allowlist."""


class DockerAPIError(RuntimeError):
    """Raised for a bounded Docker Engine API failure."""


class DockerTransport(Protocol):
    def request(
        self,
        method: str,
        path: str,
        *,
        timeout: float | None = None,
    ) -> tuple[int, bytes]: ...


@dataclass(frozen=True)
class ContainerRef:
    container_id: str
    service: str


@dataclass(frozen=True)
class BrowserObservation:
    """Selected Docker facts, with no environment or health-output payload."""

    container_id: str
    started_at: datetime
    observed_at: datetime
    health_checked_at: datetime | None
    status: str
    started_at_raw: str | None = None

    @property
    def instance_id(self) -> str:
        """Identify the actual container start, including Docker nanoseconds."""
        stamp = self.started_at_raw or self.started_at.isoformat()
        digest = hashlib.sha256(f"{self.container_id}|{stamp}".encode()).hexdigest()
        return "ops-observed-browser-" + digest


def _docker_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not _DOCKER_TIMESTAMP.fullmatch(value):
        raise DockerAPIError("browser observation has an invalid timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DockerAPIError("browser observation has an invalid timestamp") from exc
    if parsed.year <= 1:
        raise DockerAPIError("browser observation has an unset timestamp")
    return parsed.astimezone(UTC)


class _UnixSocketConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str, *, timeout: float) -> None:
        super().__init__("localhost", timeout=timeout)
        self._socket_path = socket_path

    def connect(self) -> None:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(self.timeout)
        connection.connect(self._socket_path)
        self.sock = connection


class UnixSocketDockerTransport:
    """Minimal Docker Engine transport with no shell or generic action surface."""

    def __init__(
        self,
        socket_path: str = "/var/run/docker.sock",
        *,
        timeout: float = DEFAULT_DOCKER_REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self.socket_path = socket_path
        self.timeout = timeout

    def request(
        self,
        method: str,
        path: str,
        *,
        timeout: float | None = None,
    ) -> tuple[int, bytes]:
        effective_timeout = self.timeout if timeout is None else timeout
        connection = _UnixSocketConnection(self.socket_path, timeout=effective_timeout)
        try:
            connection.request(method, path, headers={"Host": "docker"})
            response = connection.getresponse()
            body = response.read(1024*1024+1)
            if len(body) > 1024*1024:
                raise DockerAPIError("docker response exceeds observation limit")
            return response.status, body
        except OSError as exc:
            raise DockerAPIError("docker socket request failed") from exc
        finally:
            connection.close()


class DockerAPI:
    """Expose fixed labelled restarts and read-only browser health observation."""

    def __init__(
        self,
        *,
        transport: DockerTransport | None = None,
        compose_project: str,
        api_version: str = "v1.45",
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        normalized_project = compose_project.strip()
        if not normalized_project or len(normalized_project) > 128:
            raise GuardrailViolation("compose project is invalid")
        normalized_api_version = api_version.strip("/")
        if not re.fullmatch(r"v[0-9]+(?:\.[0-9]+)?", normalized_api_version):
            raise GuardrailViolation("docker API version is invalid")
        self._transport = transport or UnixSocketDockerTransport()
        self._compose_project = normalized_project
        self._api_prefix = "/" + normalized_api_version
        self._clock = clock or (lambda: datetime.now(UTC))
        self._monotonic = monotonic or time.monotonic

    def resolve_target(self, target: str, *, timeout: float | None = None) -> list[ContainerRef]:
        if target not in ALLOWED_TARGETS:
            raise GuardrailViolation("target is not allowlisted")
        filters = json.dumps(
            {
                "label": [
                    f"com.docker.compose.project={self._compose_project}",
                    f"com.docker.compose.service={target}",
                ]
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        path = f"{self._api_prefix}/containers/json?" + urlencode(
            {"all": "1", "filters": filters}
        )
        if timeout is None:
            status, body = self._transport.request("GET", path)
        else:
            status, body = self._transport.request("GET", path, timeout=timeout)
        if status != 200:
            raise DockerAPIError(f"container lookup failed with status {status}")
        try:
            rows = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DockerAPIError("container lookup returned invalid JSON") from exc
        if not isinstance(rows, list):
            raise DockerAPIError("container lookup returned an invalid envelope")
        refs: list[ContainerRef] = []
        for row in rows:
            if not isinstance(row, dict):
                raise DockerAPIError("container lookup returned an invalid row")
            container_id = row.get("Id")
            labels = row.get("Labels")
            if not isinstance(container_id, str) or _CONTAINER_ID.fullmatch(container_id) is None:
                raise DockerAPIError("container lookup returned an invalid identifier")
            if not isinstance(labels, dict):
                raise DockerAPIError("container lookup omitted compose labels")
            if labels.get("com.docker.compose.project") != self._compose_project:
                continue
            if labels.get("com.docker.compose.service") != target:
                continue
            refs.append(ContainerRef(container_id=container_id, service=target))
        return refs

    def observe_browser(
        self, *, timeout_seconds: float = BROWSER_OBSERVATION_TIMEOUT_SECONDS,
    ) -> BrowserObservation:
        """Observe only the uniquely labelled browser within a shared time budget.

        No caller can choose a container, service, Docker path or action. The
        selected inspect must independently match its lookup identity/labels.
        A healthy signal needs a recent completed check from this actual start.
        """
        if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0
                or timeout_seconds > BROWSER_OBSERVATION_TIMEOUT_SECONDS):
            raise GuardrailViolation("browser observation budget is invalid")
        deadline = self._monotonic() + timeout_seconds

        def remaining() -> float:
            budget = min(DEFAULT_DOCKER_REQUEST_TIMEOUT_SECONDS, deadline-self._monotonic())
            if budget <= 0:
                raise DockerAPIError("browser observation timed out")
            return budget

        try:
            matches = self.resolve_target("browser", timeout=remaining())
        except OSError as exc:
            raise DockerAPIError("browser lookup request failed") from exc
        if len(matches) != 1:
            raise GuardrailViolation("browser container match count is not exactly one")
        container = matches[0]
        if not _OBSERVED_CONTAINER_ID.fullmatch(container.container_id):
            raise GuardrailViolation("browser lookup did not return a canonical container ID")
        path = f"{self._api_prefix}/containers/{quote(container.container_id, safe='')}/json"
        try:
            status, body = self._transport.request("GET", path, timeout=remaining())
        except OSError as exc:
            raise DockerAPIError("browser inspect request failed") from exc
        if self._monotonic() > deadline:
            raise DockerAPIError("browser observation timed out")
        if status != 200 or len(body) > 1024*1024:
            raise DockerAPIError("browser inspect response is unavailable or too large")
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DockerAPIError("browser inspect returned invalid JSON") from exc
        if not isinstance(payload, dict) or payload.get("Id") != container.container_id:
            raise GuardrailViolation("browser inspect identity does not match lookup")
        config = payload.get("Config")
        labels = config.get("Labels") if isinstance(config, dict) else None
        if (not isinstance(labels, dict)
                or labels.get("com.docker.compose.project") != self._compose_project
                or labels.get("com.docker.compose.service") != "browser"):
            raise GuardrailViolation("browser inspect compose labels do not match")
        state = payload.get("State")
        if not isinstance(state, dict) or type(state.get("Running")) is not bool:
            raise DockerAPIError("browser inspect omitted its running state")
        running = state["Running"]
        if ((running and state.get("Status") != "running")
                or (not running and state.get("Status") not in {"exited", "dead"})):
            raise DockerAPIError("browser inspect has inconsistent running state")
        observed_at = self._clock()
        if observed_at.tzinfo is None:
            raise DockerAPIError("browser observation clock must be timezone-aware")
        observed_at = observed_at.astimezone(UTC)
        started_at = _docker_timestamp(state.get("StartedAt"))
        if started_at > observed_at:
            raise DockerAPIError("browser start time is in the future")
        health = state.get("Health")
        if not isinstance(health, dict) or health.get("Status") not in {"healthy", "starting", "unhealthy"}:
            raise DockerAPIError("browser inspect omitted valid health facts")
        health_status = health["Status"]
        checked_at = None
        if running:
            logs = health.get("Log")
            if not isinstance(logs, list) or not logs:
                if health_status != "starting":
                    raise DockerAPIError("browser health has no completed check")
            else:
                last = logs[-1]
                if not isinstance(last, dict) or type(last.get("ExitCode")) is not int:
                    raise DockerAPIError("browser health has no valid check result")
                check_start = _docker_timestamp(last.get("Start"))
                checked_at = _docker_timestamp(last.get("End"))
                if (check_start < started_at or checked_at < check_start or checked_at > observed_at
                        or (observed_at-checked_at).total_seconds() > BROWSER_HEALTH_MAX_AGE_SECONDS
                        or (health_status == "healthy" and last["ExitCode"] != 0)):
                    raise DockerAPIError("browser health check is stale or inconsistent")
        if self._monotonic() > deadline:
            raise DockerAPIError("browser observation timed out")
        return BrowserObservation(container_id=container.container_id, started_at=started_at,
            observed_at=observed_at, health_checked_at=checked_at,
            status=health_status if running else "stopped", started_at_raw=state["StartedAt"])

    def restart_target(self, target: str, *, grace_seconds: int) -> None:
        """Resolve a single labelled target immediately before restarting it."""
        matches = self.resolve_target(target)
        if len(matches) != 1:
            raise GuardrailViolation("container match count is not exactly one")
        self.restart(matches[0], grace_seconds=grace_seconds)

    def restart(self, container: ContainerRef, *, grace_seconds: int) -> None:
        if container.service not in ALLOWED_TARGETS:
            raise GuardrailViolation("target is not allowlisted")
        if _CONTAINER_ID.fullmatch(container.container_id) is None:
            raise GuardrailViolation("container identifier is invalid")
        if not 1 <= grace_seconds <= 600:
            raise GuardrailViolation("restart grace period is invalid")
        path = (
            f"{self._api_prefix}/containers/{quote(container.container_id, safe='')}/restart?"
            + urlencode({"t": str(grace_seconds)})
        )
        status, _body = self._transport.request(
            "POST",
            path,
            timeout=grace_seconds + RESTART_RESPONSE_PADDING_SECONDS,
        )
        if status not in {204, 304}:
            raise DockerAPIError(f"container restart failed with status {status}")
