"""Execute deployment warm/restore functions with external commands stubbed."""

import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy/tencent/deploy.sh"


def _bash():
    candidate = Path(r"C:\Program Files\Git\bin\bash.exe")
    return str(candidate) if candidate.exists() else shutil.which("bash")


def _run(tmp_path, function, **overrides):
    (tmp_path / "deploy.sh").write_text(DEPLOY.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    harness = r'''
set -u
APT_MIRROR="https://example.invalid"
DY_WEB_BASE_URL="https://app.example.invalid"
ENV_FILE="test.env"
COMPOSE_FILE="compose.yaml"
log() { printf '%s\n' "$*"; }
timeout() {
  printf 'timeout %s\n' "$*" >> "$WORK/calls"
  case "$*" in
    *"--module ${FAIL_MODULE:-not-selected}"*) return 1 ;;
    *--check-ready*) [ "${FAIL_READY:-0}" != 1 ] || return 1 ;;
  esac
  return 0
}
sudo() { printf 'sudo %s\n' "$*" >> "$WORK/calls"; return 0; }
compose() {
  printf 'compose %s\n' "$*" >> "$WORK/calls"
  if [ "$1" = "-f" ]; then cat "$2" >> "$WORK/calls"; fi
  return 0
}
eval "$(sed -n '/^warm_dashboard_publications() {$/,/^}$/p' "$WORK/deploy.sh")"
eval "$(sed -n '/^restore_publication_worker_before_api() {$/,/^}$/p' "$WORK/deploy.sh")"
"$FUNCTION"
'''
    (tmp_path / "harness.sh").write_text(harness, encoding="utf-8", newline="\n")
    environment = dict(os.environ, WORK=str(tmp_path).replace("\\", "/"), FUNCTION=function)
    environment.update(overrides)
    result = subprocess.run([_bash(), str(tmp_path / "harness.sh")], cwd=tmp_path, env=environment,
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    calls = (tmp_path / "calls").read_text(encoding="utf-8") if (tmp_path / "calls").exists() else ""
    return result, calls


def test_warm_five_modules_then_read_only_gate_all_under_wall_timeout(tmp_path):
    result, calls = _run(tmp_path, "warm_dashboard_publications")
    assert result.returncode == 0, result.stderr
    for module in ("douyin-ranking", "sales", "clue-overview", "settlement", "finance"):
        assert f"--once --require-ready --module {module}" in calls
    assert calls.count("timeout --signal=TERM --kill-after=15s 240") == 6
    assert calls.count("--check-ready") == 1
    assert "--force" not in calls
    assert "up -d" not in calls and "stop worker" not in calls


def test_busy_first_publication_aborts_and_removes_only_named_temporary_container(tmp_path):
    result, calls = _run(tmp_path, "warm_dashboard_publications", FAIL_MODULE="sales")
    assert result.returncode == 1
    assert "existing API and business worker are retained" in result.stdout
    assert "sudo docker rm -f dy-publication-warm-" in calls
    assert "--module clue-overview" not in calls
    assert "up -d" not in calls and "stop worker" not in calls


def test_final_readiness_failure_aborts_and_cleans_readiness_container(tmp_path):
    result, calls = _run(tmp_path, "warm_dashboard_publications", FAIL_READY="1")
    assert result.returncode == 1
    assert "sudo docker rm -f dy-publication-ready-" in calls


def test_warm_timeout_cannot_be_unbounded(tmp_path):
    result, calls = _run(tmp_path, "warm_dashboard_publications", PUBLICATION_WARM_TIMEOUT_SECONDS="0")
    assert result.returncode == 1
    assert calls == ""


def test_pre_api_publisher_failure_restores_immutable_image(tmp_path):
    result, calls = _run(tmp_path, "restore_publication_worker_before_api",
        api_replaced="false", publication_worker_replaced="true",
        previous_publication_image_id="sha256:" + "a" * 64, previous_publication_image_ref="worker:local")
    assert result.returncode == 0
    assert 'image: "sha256:' + "a" * 64 + '"' in calls
    assert "up -d --no-deps --no-build --force-recreate publication-worker" in calls
    assert "docker image tag" not in calls


def test_first_publisher_failure_stops_only_publisher(tmp_path):
    result, calls = _run(tmp_path, "restore_publication_worker_before_api",
        api_replaced="false", publication_worker_replaced="true")
    assert result.returncode == 0
    assert calls.strip() == "compose stop publication-worker"


def test_after_api_switch_requires_explicit_release_rollback(tmp_path):
    result, calls = _run(tmp_path, "restore_publication_worker_before_api",
        api_replaced="true", publication_worker_replaced="true")
    assert result.returncode == 0 and calls == ""


def test_migration_warm_and_publisher_health_precede_api_cutover():
    source = DEPLOY.read_text(encoding="utf-8")
    assert source.index("compose run --rm migrate") < source.index("\nwarm_dashboard_publications\n")
    assert source.index("\nwarm_dashboard_publications\n") < source.index("wait_for_healthy_service publication-worker")
    assert source.index("wait_for_healthy_service publication-worker") < source.index("compose up -d --no-deps --force-recreate api")
    assert "for service in api migrate worker publication-worker web" in source
    assert "compose logs --tail=80 api web proxy ops-agent worker publication-worker" in source


def test_every_release_workflow_runs_publication_postgres_gate_before_deploy():
    import yaml

    for name in ("ci-cd.yml", "tencent-lighthouse-deploy.yml"):
        workflow = yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8"))
        verify = workflow["jobs"]["verify"]
        gates = [step for step in verify["steps"]
                 if "DYDATA_PUBLICATION_TEST_DATABASE_URL" in step.get("env", {})]
        assert len(gates) == 1, name
        gate = gates[0]
        assert "test" in gate["env"]["DYDATA_PUBLICATION_TEST_DATABASE_URL"].rsplit("/", 1)[-1]
        assert "CREATE DATABASE dydata_publication_test" in gate["run"]
        assert "tests/test_dashboard_publications_postgres.py" in gate["run"]
        assert "tests/test_dashboard_publication_*_postgres.py" in gate["run"]
        assert "tests/test_dashboard_publication_migration.py" in gate["run"]
        assert not gate.get("continue-on-error") and not gate.get("if"), name
        assert not verify.get("continue-on-error"), name
        dependencies = workflow["jobs"]["deploy"]["needs"]
        assert "verify" in ([dependencies] if isinstance(dependencies, str) else dependencies), name
