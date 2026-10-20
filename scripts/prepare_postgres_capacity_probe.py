"""Prepare a capacity marker on the running PostgreSQL data filesystem.

Run on the Docker host during deployment. Only this harmless marker is exposed
to the worker, never the database volume or Docker socket.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess


MARKER_NAME = ".dydata-capacity-probe"
MARKER_CONTENT = b"dydata-postgres-capacity-v1\n"


def resolve_data_path(mounts: list[dict], data_directory: str) -> Path:
    """Resolve the most specific Docker mount containing the actual PG directory."""

    data_path = PurePosixPath(data_directory)
    if not data_path.is_absolute() or ".." in data_path.parts:
        raise ValueError("PostgreSQL data directory must be an absolute canonical path")
    candidates = []
    for mount in mounts:
        destination = PurePosixPath(mount.get("Destination", ""))
        if destination.is_absolute() and data_path.is_relative_to(destination):
            candidates.append((destination, mount))
    if not candidates:
        raise ValueError("PostgreSQL data directory is not backed by an inspected mount")
    destination, mount = max(candidates, key=lambda candidate: len(candidate[0].parts))
    if mount.get("Type") not in {"volume", "bind"}:
        raise ValueError("PostgreSQL data mount must be a persistent volume or bind")
    source = Path(mount["Source"])
    if not source.is_absolute() or not source.is_dir():
        raise ValueError("PostgreSQL mount source is not an existing host directory")
    source = source.resolve(strict=True)
    path = source.joinpath(*data_path.relative_to(destination).parts)
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(source) or resolved != path or not resolved.is_dir():
        raise ValueError("PostgreSQL data path crosses a symlink or mount source boundary")
    return resolved


def prepare_marker(directory: Path) -> Path:
    """Create only our marker; reject unexpected contents or non-regular paths."""

    marker = directory / MARKER_NAME
    if any(char in str(marker) for char in "\r\n|$"):
        raise ValueError("Capacity marker path is not safe for the deployment environment")
    try:
        descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    except (FileExistsError, PermissionError):
        if not marker.exists() and not marker.is_symlink():
            raise
        info = marker.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("Capacity marker must be a regular, unlinked file") from None
        if info.st_size != len(MARKER_CONTENT) or marker.read_bytes() != MARKER_CONTENT:
            raise ValueError("Existing capacity marker has unexpected contents") from None
    else:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(MARKER_CONTENT)
            stream.flush()
            os.fsync(stream.fileno())
    return marker


def main() -> None:
    """Inspect the running container and print the verified marker source path."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container-id", required=True)
    arguments = parser.parse_args()
    inspected = json.loads(subprocess.check_output(
        ["docker", "inspect", arguments.container_id], text=True, timeout=15,
    ))
    if len(inspected) != 1 or not inspected[0]["State"]["Running"]:
        raise ValueError("Exactly one running PostgreSQL container is required")
    directory = subprocess.check_output(
        ["docker", "exec", arguments.container_id, "sh", "-c",
         'exec psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SHOW data_directory"'],
        text=True, timeout=15,
    ).strip()
    path = resolve_data_path(inspected[0]["Mounts"], directory)
    print(prepare_marker(path))


if __name__ == "__main__":
    main()
