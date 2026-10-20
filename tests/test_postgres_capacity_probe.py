"""The deploy probe resolves the database mount and never replaces user files."""
import os

import pytest

from scripts.prepare_postgres_capacity_probe import MARKER_CONTENT, MARKER_NAME, prepare_marker, resolve_data_path


def test_probe_uses_most_specific_data_mount(tmp_path):
    outer = tmp_path / "outer"
    inner = tmp_path / "inner"
    outer.mkdir()
    inner.mkdir()
    mounts = [
        {"Destination": "/var/lib/postgresql", "Source": str(outer), "Type": "volume"},
        {"Destination": "/var/lib/postgresql/18/docker", "Source": str(inner), "Type": "bind"},
    ]
    assert resolve_data_path(mounts, "/var/lib/postgresql/18/docker") == inner.resolve()
    marker = prepare_marker(inner)
    assert marker.read_bytes() == MARKER_CONTENT
    assert prepare_marker(inner) == marker
    assert list(outer.iterdir()) == []


@pytest.mark.parametrize("directory", ["/unmounted/data", "relative/data", "/var/lib/postgresql/../other"])
def test_probe_rejects_unverified_directory(tmp_path, directory):
    with pytest.raises(ValueError):
        resolve_data_path([{"Destination": "/var/lib/postgresql", "Source": str(tmp_path), "Type": "volume"}], directory)


def test_probe_preserves_unexpected_existing_file(tmp_path):
    marker = tmp_path / MARKER_NAME
    marker.write_bytes(b"not our file")
    with pytest.raises(ValueError, match="unexpected contents"):
        prepare_marker(tmp_path)
    assert marker.read_bytes() == b"not our file"


def test_probe_rejects_hardlink(tmp_path):
    other = tmp_path / "data"
    other.write_bytes(MARKER_CONTENT)
    os.link(other, tmp_path / MARKER_NAME)
    with pytest.raises(ValueError, match="regular, unlinked"):
        prepare_marker(tmp_path)


def test_probe_rejects_directory_marker(tmp_path):
    (tmp_path / MARKER_NAME).mkdir()
    with pytest.raises(ValueError, match="regular, unlinked"):
        prepare_marker(tmp_path)
