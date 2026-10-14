"""Behavioural tests for the pre-build running-image backup in the Tencent deploy."""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOY_SCRIPT = ROOT / "deploy" / "tencent" / "deploy.sh"
FULL_IMAGE_ID = "sha256:" + "a1b2c3d4" * 8
OTHER_IMAGE_ID = "sha256:" + "ffffffff" * 8


def _bash() -> str:
    """Locate a bash that can run the deploy function on this host."""
    for candidate in (
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
        "/bin/bash",
        "/usr/bin/bash",
    ):
        if Path(candidate).exists():
            return candidate
    return shutil.which("bash") or "bash"

HARNESS = r"""set -u
export BACKUP_DIR="$WORK/backups"
export TARGET_SHA="deadbeef"
mkdir -p "$BACKUP_DIR"
# Freeze the stamp so a pre-created manifest path really collides with the path
# the function computes, on every host shell.
date() { printf '%s\n' "20261014T010203Z"; }
compose() {
  if [ "${STUB_NO_CONTAINERS:-0}" = "1" ]; then
    return 0
  fi
  if [ "${STUB_PS_FAILS:-0}" = "1" ]; then
    echo "Cannot connect to the Docker daemon" >&2
    return 1
  fi
  if [ "$1" = "ps" ] && [ "$2" = "-q" ]; then
    case "$3" in
      api|worker|web|browser|ops-agent|proxy|postgres) printf 'cid-%s\n' "$3" ;;
      *) return 0 ;;
    esac
  fi
  return 0
}
log() { printf '%s\n' "$*" >&2; }
eval "$(sed -n '/^backup_running_images() {$/,/^}$/p' "$WORK/deploy.sh")"
backup_running_images
echo "FUNCTION_STATUS=$?"
"""

DOCKER_STUB = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >> "$WORK/docker.calls"
if [ "$1" = "inspect" ]; then
  case "$*" in
    *"{{.Image}}"*) printf '%s\n' "${FULL_IMAGE_ID:-}"; exit 0 ;;
    *"{{.Config.Image}}"*) printf 'dy-dashboard-%s:local\n' "${4#cid-}"; exit 0 ;;
    *"{{.State.Health}}"*) printf 'healthy\n'; exit 0 ;;
  esac
  exit 0
fi
if [ "$1" = "image" ] && [ "$2" = "tag" ]; then
  if [ "${STUB_TAG_FAILS:-0}" = "1" ]; then
    echo "tag failed" >&2
    exit 1
  fi
  exit 0
fi
if [ "$1" = "image" ] && [ "$2" = "inspect" ]; then
  if [ "${STUB_VERIFY_MISMATCH:-0}" = "1" ]; then
    printf '%s\n' "$OTHER_IMAGE_ID"
  else
    printf '%s\n' "${FULL_IMAGE_ID:-}"
  fi
  exit 0
fi
exit 0
"""

# ``sudo`` and ``date`` are stubbed so the harness behaves the same on a Windows
# runner without real privilege escalation and with a deterministic stamp.
SUDO_STUB = """#!/usr/bin/env bash
exec "$@"
"""

DATE_STUB = """#!/usr/bin/env bash
printf '%s\\n' "20261014T010203Z"
"""


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8", newline="\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _run_backup(tmp_path: Path, **env_overrides: str) -> subprocess.CompletedProcess[str]:
    work = tmp_path
    (work / "deploy.sh").write_text(
        DEPLOY_SCRIPT.read_text(encoding="utf-8"), encoding="utf-8", newline="\n"
    )
    (work / "harness.sh").write_text(HARNESS, encoding="utf-8", newline="\n")
    bin_dir = work / "bin"
    bin_dir.mkdir()
    _write_executable(bin_dir / "docker", DOCKER_STUB)
    _write_executable(bin_dir / "sudo", SUDO_STUB)
    _write_executable(bin_dir / "date", DATE_STUB)
    env = dict(os.environ)
    env["WORK"] = str(work).replace("\\", "/")
    env["PATH"] = os.pathsep.join(
        [str(bin_dir), str(Path(_bash()).parent), env["PATH"]]
    )
    env["FULL_IMAGE_ID"] = FULL_IMAGE_ID
    env["OTHER_IMAGE_ID"] = OTHER_IMAGE_ID
    env.update(env_overrides)
    return subprocess.run(
        [_bash(), str(work / "harness.sh")],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(work),
        encoding="utf-8",
        errors="replace",
    )


def test_image_backup_tags_the_full_immutable_id_and_verifies_it(tmp_path: Path) -> None:
    result = _run_backup(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "FUNCTION_STATUS=0" in result.stdout

    calls = (tmp_path / "docker.calls").read_text(encoding="utf-8")
    # The rollback tag must use the complete immutable id, never a short prefix.
    assert f"image tag {FULL_IMAGE_ID} dy-dashboard-rollback:" in calls
    for service in ("api", "worker", "web", "browser", "ops-agent", "proxy", "postgres"):
        assert f"dy-dashboard-rollback:" in calls
        assert f"-{service}" in calls
    # Every rollback tag is re-inspected and compared with the running image id.
    assert calls.count("image inspect -f {{.Id}}") >= 7

    manifests = list((tmp_path / "backups").glob("images-*.manifest"))
    assert len(manifests) == 1
    if os.name != "nt":
        # Windows stat cannot express POSIX permission bits.
        assert stat.S_IMODE(manifests[0].stat().st_mode) == 0o600
    body = manifests[0].read_text(encoding="utf-8")
    assert f"|{FULL_IMAGE_ID}|dy-dashboard-rollback:" in body
    assert "migrate|-|-|-|no-container" in body.splitlines()
    assert not list((tmp_path / "backups").glob("*.partial"))


def test_image_backup_stops_the_deploy_when_tagging_fails(tmp_path: Path) -> None:
    result = _run_backup(tmp_path, STUB_TAG_FAILS="1")
    assert result.returncode == 0, result.stderr
    assert "FUNCTION_STATUS=1" in result.stdout
    assert "refusing to deploy" in result.stderr
    # A failed tag must not leave a manifest behind.
    assert not list((tmp_path / "backups").glob("*.manifest"))
    assert not list((tmp_path / "backups").glob("*.partial"))


def test_image_backup_stops_the_deploy_when_the_rollback_tag_mismatches(
    tmp_path: Path,
) -> None:
    result = _run_backup(tmp_path, STUB_VERIFY_MISMATCH="1")
    assert result.returncode == 0, result.stderr
    assert "FUNCTION_STATUS=1" in result.stdout
    assert "does not match the running image id" in result.stderr
    assert not list((tmp_path / "backups").glob("*.manifest"))


def test_image_backup_refuses_to_overwrite_an_existing_manifest(tmp_path: Path) -> None:
    backups = tmp_path / "backups"
    backups.mkdir()
    existing = backups / "images-20261014T010203Z.manifest"
    existing.write_text("keep-me\n", encoding="utf-8")

    result = _run_backup(tmp_path)
    assert "FUNCTION_STATUS=1" in result.stdout
    assert "refusing to overwrite" in result.stderr
    assert existing.read_text(encoding="utf-8") == "keep-me\n"


def test_image_backup_refuses_to_overwrite_a_partial_manifest(tmp_path: Path) -> None:
    backups = tmp_path / "backups"
    backups.mkdir()
    partial = backups / "images-20261014T010203Z.manifest.partial"
    partial.write_text("in-progress\n", encoding="utf-8")

    result = _run_backup(tmp_path)
    assert "FUNCTION_STATUS=1" in result.stdout
    assert "refusing to overwrite" in result.stderr
    assert partial.read_text(encoding="utf-8") == "in-progress\n"


def test_image_backup_allows_a_first_deploy_without_any_container(tmp_path: Path) -> None:
    """An absent service is recorded, never treated as a rollback failure."""
    result = _run_backup(tmp_path, STUB_NO_CONTAINERS="1")
    assert "FUNCTION_STATUS=0" in result.stdout
    body = next((tmp_path / "backups").glob("images-*.manifest")).read_text(
        encoding="utf-8"
    )
    for service in ("api", "worker", "web", "browser", "ops-agent", "proxy", "postgres"):
        assert f"{service}|-|-|-|no-container" in body
    # No container existed, so no inspect or tag call happened at all.
    calls = tmp_path / "docker.calls"
    assert not calls.exists() or calls.read_text(encoding="utf-8") == ""


def test_image_backup_stops_the_deploy_when_the_container_query_fails(
    tmp_path: Path,
) -> None:
    """A failed compose/docker query is not the same as an absent container."""
    result = _run_backup(tmp_path, STUB_PS_FAILS="1")
    assert "FUNCTION_STATUS=1" in result.stdout
    assert "cannot query the running container" in result.stderr
    assert not list((tmp_path / "backups").glob("*.manifest"))
    assert not list((tmp_path / "backups").glob("*.partial"))


def test_image_backup_source_keeps_the_fail_closed_contract() -> None:
    source = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert source.index('log "recording running images before any build"') < source.index(
        "compose build --progress=plain"
    )
    assert "cut -c1-12" not in source
    assert "retag-failed" not in source
    assert "best-effort" not in source
    assert re.search(r'if ! sudo docker image tag "\$image_id"', source)
    assert 'sudo mv "$tmp_manifest" "$manifest"' in source
