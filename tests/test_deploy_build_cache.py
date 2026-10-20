"""Check opt-in cache cleanup without contacting a Docker daemon."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest


DEPLOY = Path(__file__).resolve().parents[1] / "deploy/tencent/deploy.sh"


def _run(tmp_path, enabled=None, fail_prune=False, fail_build=False):
    source = DEPLOY.read_text(encoding="utf-8")
    function = source.split("prune_build_cache_after_build() {", 1)[1].split("\n}", 1)[0]
    start = source.index('log "building images"\n')
    end = source.index('log "starting postgres"\n', start)
    initialization = next(
        line for line in source.splitlines()
        if line.startswith("DEPLOY_PRUNE_BUILD_CACHE_AFTER_BUILD=")
    )
    harness = """
set -Eeuo pipefail
""" + initialization + """
log() { printf '%s\\n' "$*"; }
sudo() {
  printf 'sudo %s\\n' "$*" >> "$CALLS"
  [ "$FAIL_PRUNE" = false ]
}
compose() {
  printf 'compose %s\\n' "$*" >> "$CALLS"
  [ "$FAIL_BUILD" = false ]
}
""" + "prune_build_cache_after_build() {" + function + "\n}\n" + source[start:end] + """
printf 'capacity-gate-next\\n' >> "$CALLS"
"""
    script = tmp_path / "harness.sh"
    script.write_text(harness, encoding="utf-8", newline="\n")
    windows_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
    bash = str(windows_bash) if windows_bash.exists() else shutil.which("bash")
    calls_file = tmp_path / "calls"
    environment = dict(
        os.environ, CALLS=str(calls_file).replace("\\", "/"),
        FAIL_PRUNE=str(fail_prune).lower(), FAIL_BUILD=str(fail_build).lower(),
    )
    environment.pop("DEPLOY_PRUNE_BUILD_CACHE_AFTER_BUILD", None)
    if enabled is not None:
        environment["DEPLOY_PRUNE_BUILD_CACHE_AFTER_BUILD"] = enabled
    result = subprocess.run(
        [bash, str(script)],
        env=environment,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    calls = calls_file.read_text(encoding="utf-8").splitlines()
    return result, calls


@pytest.mark.parametrize("enabled", [None, "false"])
def test_default_keeps_build_cache(tmp_path, enabled):
    result, calls = _run(tmp_path, enabled=enabled)
    assert result.returncode == 0, result.stderr
    assert len(calls) == 2
    assert calls[0].startswith("compose build ")
    assert calls[-1] == "capacity-gate-next"


def test_opt_in_cleans_only_build_cache_after_build(tmp_path):
    result, calls = _run(tmp_path, enabled="true")
    assert result.returncode == 0, result.stderr
    assert calls[0].startswith("compose build ")
    assert calls[1:] == ["sudo docker builder prune --force", "capacity-gate-next"]
    source = DEPLOY.read_text(encoding="utf-8")
    assert source.index("\nprune_build_cache_after_build\n") < source.index(
        'log "starting postgres"\n'
    ) < source.index('\ncheck_backup_capacity\n') < source.index('\nbackup_database\n')


def test_cleanup_failure_stops_before_backup_or_cutover(tmp_path):
    result, calls = _run(tmp_path, enabled="true", fail_prune=True)
    assert result.returncode != 0
    assert calls[-1] == "sudo docker builder prune --force"
    assert "capacity-gate-next" not in calls


def test_build_failure_does_not_prune_or_continue(tmp_path):
    result, calls = _run(tmp_path, enabled="true", fail_build=True)
    assert result.returncode != 0
    assert len(calls) == 1 and calls[0].startswith("compose build ")


@pytest.mark.parametrize("enabled", ["", "1", "TRUE"])
def test_invalid_explicit_value_fails_closed(tmp_path, enabled):
    result, calls = _run(tmp_path, enabled=enabled)
    assert result.returncode != 0
    assert all(not call.startswith("sudo ") for call in calls)
