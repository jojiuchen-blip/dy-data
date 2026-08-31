from __future__ import annotations

import http.client
import json
import re
import socket
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote, urlencode


ALLOWED_TARGETS = frozenset({"worker", "browser"})
DEFAULT_DOCKER_REQUEST_TIMEOUT_SECONDS = 10
RESTART_RESPONSE_PADDING_SECONDS = 15
_CONTAINER_ID = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


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
            return response.status, response.read()
        except OSError as exc:
            raise DockerAPIError("docker socket request failed") from exc
        finally:
            connection.close()


class DockerAPI:
    """Expose exactly compose-label lookup and restart for worker/browser."""

    def __init__(
        self,
        *,
        transport: DockerTransport | None = None,
        compose_project: str,
        api_version: str = "v1.45",
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

    def resolve_target(self, target: str) -> list[ContainerRef]:
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
        status, body = self._transport.request("GET", path)
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
