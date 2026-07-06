from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_compose_wires_worker_collection_defaults():
    compose = (ROOT / "deploy" / "compose.yaml").read_text(encoding="utf-8")

    assert "${WORKER_COMMAND:-python -m apps.worker.scheduler}" in compose
    assert "WORKER_MODE: ${WORKER_MODE:-collect_and_settle}" in compose
    assert "DOUYIN_COLLECT_START: ${DOUYIN_COLLECT_START:-2026-01-01}" in compose
    assert "DOUYIN_COLLECT_OVERLAP_DAYS: ${DOUYIN_COLLECT_OVERLAP_DAYS:-7}" in compose
    assert "DOUYIN_VERIFY_CHUNK_DAYS: ${DOUYIN_VERIFY_CHUNK_DAYS:-7}" in compose
    assert (
        "BROWSER_EXPORT_COMMAND: ${BROWSER_EXPORT_COMMAND:-python -m apps.worker.browser_exports.backend_aweme}"
        in compose
    )
    assert "BACKEND_AWEME_EXPORT_URL: ${BACKEND_AWEME_EXPORT_URL:-https://life.douyin.com/}" in compose


def test_browser_profile_and_downloads_are_private_volumes():
    compose = (ROOT / "deploy" / "compose.yaml").read_text(encoding="utf-8")
    dockerfile = (ROOT / "deploy" / "browser" / "Dockerfile").read_text(encoding="utf-8")
    nginx = (ROOT / "deploy" / "nginx.conf").read_text(encoding="utf-8")
    entrypoint = (ROOT / "deploy" / "browser" / "entrypoint.sh").read_text(encoding="utf-8")

    assert "browser-profile:/home/browser/.config/chromium" in compose
    assert "browser-downloads:/home/browser/Downloads" in compose
    assert "dockerfile: deploy/browser/Dockerfile" in compose
    assert "BROWSER_EXPORT_SCHEDULER_ENABLED: ${BROWSER_EXPORT_SCHEDULER_ENABLED:-false}" in compose
    assert "BROWSER_EXPORT_INTERVAL_SECONDS: ${BROWSER_EXPORT_INTERVAL_SECONDS:-86400}" in compose
    assert "gosu" in dockerfile
    assert "USER root" in dockerfile
    assert 'exec gosu browser "$0" "$@"' in entrypoint
    assert "chown -R browser:browser" in entrypoint
    assert 'BROWSER_CDP_URL="http://127.0.0.1:${CHROMIUM_REMOTE_DEBUGGING_INTERNAL_PORT}"' in entrypoint
    assert 'export XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"' in entrypoint
    assert 'export XDG_CACHE_HOME="${XDG_CACHE_HOME:-$HOME/.cache}"' in entrypoint
    assert '"$XDG_CONFIG_HOME/chromium/Crash Reports"' in entrypoint
    assert '"$XDG_CONFIG_HOME/chromium/Crashpad"' in entrypoint
    assert '"$XDG_CACHE_HOME/chromium"' in entrypoint
    assert "--disable-crash-reporter" in entrypoint
    assert "--disable-breakpad" in entrypoint
    assert "--crash-dumps-dir=/tmp/chromium-crashes" in entrypoint
    assert '--user-data-dir="$XDG_CONFIG_HOME/chromium"' in entrypoint
    assert '"$XDG_CONFIG_HOME/chromium/SingletonLock"' in entrypoint
    assert "ports:" not in compose.split("  browser:", 1)[1].split("  proxy:", 1)[0]
    assert "location /browser/" in nginx
    assert "auth_request" not in nginx
    assert "return 302 /browser/vnc.html;" in nginx
    assert "location /websockify" in nginx
    assert "absolute_redirect off;" in nginx


def test_docker_builds_do_not_force_ci_to_use_regional_apt_mirror():
    compose = (ROOT / "deploy" / "compose.yaml").read_text(encoding="utf-8")
    dockerfiles = [
        ROOT / "apps" / "api" / "Dockerfile",
        ROOT / "apps" / "worker" / "Dockerfile",
        ROOT / "deploy" / "browser" / "Dockerfile",
    ]

    for dockerfile in dockerfiles:
        source = dockerfile.read_text(encoding="utf-8")
        assert "ARG APT_MIRROR=" in source
        assert "mirrors.tuna.tsinghua.edu.cn/debian" not in source

    assert "APT_MIRROR: ${APT_MIRROR:-}" in compose
