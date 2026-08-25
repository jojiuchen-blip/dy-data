from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_nginx_compresses_text_responses_without_caching_private_api_data():
    nginx = (ROOT / "deploy" / "nginx.conf").read_text(encoding="utf-8")
    api_location = nginx.split("location /api/ {", 1)[1].split("}", 1)[0]

    assert "gzip on;" in nginx
    assert "gzip_vary on;" in nginx
    assert "gzip_min_length 1024;" in nginx
    assert "application/json" in nginx
    assert "application/javascript" in nginx
    assert "image/svg+xml" in nginx
    assert "proxy_cache" not in api_location


def test_compose_wires_worker_collection_defaults():
    compose = (ROOT / "deploy" / "compose.yaml").read_text(encoding="utf-8")

    assert "${WORKER_COMMAND:-python -m apps.worker.scheduler}" in compose
    assert "WORKER_MODE: ${WORKER_MODE:-collect_and_settle}" in compose
    assert "mem_limit: ${WORKER_MEMORY_LIMIT:-5g}" in compose
    assert "memswap_limit: ${WORKER_MEMORY_SWAP_LIMIT:-7g}" in compose
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


def test_browser_image_upgrades_pip_before_resolving_shared_requirements():
    dockerfile = (ROOT / "deploy" / "browser" / "Dockerfile").read_text(encoding="utf-8")

    upgrade = dockerfile.index(
        "python3 -m pip install --break-system-packages --no-cache-dir --upgrade pip"
    )
    requirements = dockerfile.index(
        "python3 -m pip install --break-system-packages --no-cache-dir -r requirements.txt"
    )

    assert upgrade < requirements


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


def test_tencent_deploy_uploads_source_from_actions_runner():
    workflow = (ROOT / ".github" / "workflows" / "tencent-lighthouse-deploy.yml").read_text(
        encoding="utf-8"
    )
    deploy_script = (ROOT / "deploy" / "tencent" / "deploy.sh").read_text(encoding="utf-8")
    deploy_step = workflow.split("- name: Deploy on server", 1)[1]

    assert "uses: actions/checkout@v4" in workflow
    assert "timeout-minutes: 30" in workflow
    assert 'git archive --format=tar "$GITHUB_SHA"' in workflow
    assert 'scp -i ~/.ssh/tencent_lighthouse' in workflow
    assert "TENCENT_APT_MIRROR" in workflow
    assert "http://mirrors.tencentyun.com" in workflow
    assert (
        'SKIP_GIT_SYNC=true APT_MIRROR="$apt_mirror" '
        'DY_WEB_BASE_URL="$web_base_url" bash deploy/tencent/deploy.sh'
        in workflow
    )
    assert "fetch_origin" not in deploy_step
    assert "git reset --hard" not in deploy_step

    assert 'SKIP_GIT_SYNC="${SKIP_GIT_SYNC:-false}"' in deploy_script
    assert 'APT_MIRROR="${APT_MIRROR:-http://mirrors.tencentyun.com}"' in deploy_script
    assert (
        'sudo APT_MIRROR="$APT_MIRROR" DY_WEB_BASE_URL="$DY_WEB_BASE_URL" '
        'docker compose'
        in deploy_script
    )
    assert "compose build --progress=plain api web browser worker" in deploy_script
    assert "compose up -d --no-deps --force-recreate worker" in deploy_script
    assert 'if [ "$SKIP_GIT_SYNC" = "true" ]; then' in deploy_script
    assert 'deployed_sha="$TARGET_SHA"' in deploy_script


def test_railway_deploy_fails_closed_when_required_settings_are_missing():
    workflow = (ROOT / ".github" / "workflows" / "ci-cd.yml").read_text(
        encoding="utf-8"
    )
    deploy = workflow.split("  deploy:", 1)[1]
    required = deploy.split("required=(", 1)[1].split(")", 1)[0]

    assert "Skip Railway deployment when token is absent" not in deploy
    for name in (
        "RAILWAY_TOKEN",
        "RAILWAY_PROJECT_ID",
        "RAILWAY_ENVIRONMENT",
        "RAILWAY_API_SERVICE_ID",
        "RAILWAY_WORKER_SERVICE_ID",
        "RAILWAY_BROWSER_SERVICE_ID",
        "RAILWAY_WEB_SERVICE_ID",
        "RAILWAY_WEB_URL",
    ):
        assert name in required
    assert "if: ${{ env.RAILWAY_TOKEN != '' && env.RAILWAY_WEB_URL != '' }}" not in deploy


def test_release_workflow_gates_target_database_and_keeps_migration_explicit():
    workflow = (ROOT / ".github" / "workflows" / "ci-cd.yml").read_text(
        encoding="utf-8"
    )
    verify = workflow.split("  railway_release_gate:", 1)[0]
    target_gate = workflow.split("  railway_release_gate:", 1)[1].split(
        "  deploy:", 1
    )[0]
    api_dockerfile = (ROOT / "apps" / "api" / "Dockerfile").read_text(
        encoding="utf-8"
    )
    compose = (ROOT / "deploy" / "compose.yaml").read_text(encoding="utf-8")

    assert "scripts/verify_postgres_release_gate.py" in verify
    assert "scripts/verify_postgres_populated_release_gate.py" in verify
    assert "scripts/verify_postgres_finance_import_concurrency.py" in verify
    assert "RAILWAY_RELEASE_DATABASE_URL" in target_gate
    assert "scripts/verify_postgres_target_release.py" in target_gate
    assert "needs: [verify, railway_release_gate]" in workflow
    assert "alembic upgrade head" not in api_dockerfile
    assert 'command: ["alembic", "upgrade", "head"]' in compose


def test_github_workflows_bound_playwright_setup_and_use_stable_ubuntu_mirror():
    workflows = [
        ROOT / ".github" / "workflows" / "ci-cd.yml",
        ROOT / ".github" / "workflows" / "tencent-lighthouse-deploy.yml",
    ]

    for workflow_path in workflows:
        workflow = workflow_path.read_text(encoding="utf-8")
        assert "/etc/apt/apt-mirrors.txt" in workflow
        assert "https://archive.ubuntu.com/ubuntu" in workflow
        assert "timeout 10m python -m playwright install chromium --with-deps" in workflow


def test_tencent_deploy_recovers_missing_production_revision_before_migration():
    deploy_script = (ROOT / "deploy" / "tencent" / "deploy.sh").read_text(
        encoding="utf-8"
    )

    preflight = deploy_script.index('log "checking production migration lineage"')
    migration = deploy_script.index('log "running migrations"')

    assert preflight < migration
    assert "SELECT to_regclass" in deploy_script
    assert "public.alembic_version" in deploy_script
    assert 'SELECT version_num FROM alembic_version' in deploy_script
    assert 'compose run --rm --no-deps migrate alembic show "$current_revision"' in deploy_script
    assert 'compose exec -T api sh -c' in deploy_script
    assert "migration-source-begin" in deploy_script
    assert "migration-source-end" in deploy_script
    assert "target source is missing production revision" in deploy_script
    assert "alembic stamp" not in deploy_script


def test_tencent_deploy_writes_deploy_record_with_privileged_write():
    deploy_script = (ROOT / "deploy" / "tencent" / "deploy.sh").read_text(
        encoding="utf-8"
    )

    assert 'sudo tee "$LOG_DIR/last-deploy.json" >/dev/null <<JSON' in deploy_script
    assert 'cat > "$LOG_DIR/last-deploy.json"' not in deploy_script


def test_tencent_deploy_requires_and_smoke_tests_cli_web_authorization_base():
    compose = (ROOT / "deploy" / "compose.yaml").read_text(encoding="utf-8")
    env_example = (ROOT / "deploy" / ".env.example").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "tencent-lighthouse-deploy.yml").read_text(
        encoding="utf-8"
    )
    deploy_script = (ROOT / "deploy" / "tencent" / "deploy.sh").read_text(
        encoding="utf-8"
    )

    assert "DY_WEB_BASE_URL: ${DY_WEB_BASE_URL:?DY_WEB_BASE_URL is required}" in compose
    assert "DY_WEB_BASE_URL=https://dy-business-engine.com" in env_example
    assert "DY_WEB_BASE_URL: ${{ vars.DY_WEB_BASE_URL }}" in workflow
    assert "DY_WEB_BASE_URL" in workflow.split("required=(", 1)[1].split(")", 1)[0]
    assert 'web_base_url="$3"' in workflow
    assert 'DY_WEB_BASE_URL="$web_base_url" bash deploy/tencent/deploy.sh' in workflow
    assert 'DY_WEB_BASE_URL="${DY_WEB_BASE_URL:-}"' in deploy_script
    assert 'DY_WEB_BASE_URL="$DY_WEB_BASE_URL" docker compose' in deploy_script
    assert '"$HEALTH_URL/api/v1/auth/cli/device/start"' in deploy_script
    assert '[ "$auth_status" = "401" ]' in deploy_script
    assert '[ "$cli_start_status" = "200" ]' in deploy_script
    assert '[ "$mcp_status" = "401" ]' in deploy_script


def test_tencent_deploy_rejects_placeholder_secrets_before_building_images():
    deploy_script = (ROOT / "deploy" / "tencent" / "deploy.sh").read_text(encoding="utf-8")

    validation = deploy_script.index('grep -q "CHANGE_ME_"')
    build = deploy_script.index('log "building images"')

    assert validation < build
    assert 'log "deployment configuration still contains CHANGE_ME placeholders"' in deploy_script


def test_tencent_deploy_backs_up_postgres_before_running_migrations():
    deploy_script = (ROOT / "deploy" / "tencent" / "deploy.sh").read_text(encoding="utf-8")

    backup = deploy_script.index("pg_dump")
    migration = deploy_script.index('log "running migrations"')

    assert backup < migration
    assert 'test -s "$backup_file"' in deploy_script
    assert 'chmod 600 "$backup_file"' in deploy_script


def test_tencent_deploy_blocks_unresolved_statement_snapshot_migration_exceptions():
    deploy_script = (ROOT / "deploy" / "tencent" / "deploy.sh").read_text(encoding="utf-8")

    migration = deploy_script.index('log "running migrations"')
    exception_gate = deploy_script.index(
        'log "checking unresolved statement snapshot migration exceptions"'
    )
    runtime_start = deploy_script.index('log "starting runtime services without worker"')

    assert migration < exception_gate < runtime_start
    assert "settlement_statement_snapshot_migration_exception" in deploy_script
    assert "settlement_statement_entry_snapshot_migration_exception" in deploy_script
    assert 'if [ "$unresolved_snapshot_exceptions" -ne 0 ]' in deploy_script
    assert "snapshot exception gate returned an invalid count" in deploy_script
    assert "deployment blocked by unresolved statement snapshot migration exceptions" in deploy_script
