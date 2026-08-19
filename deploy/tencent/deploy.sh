#!/usr/bin/env bash
set -Eeuo pipefail

TARGET_SHA="${1:-origin/main}"
APP_DIR="${APP_DIR:-/opt/dy-dashboard/repo}"
ENV_FILE="${ENV_FILE:-/opt/dy-dashboard/env/production.env}"
COMPOSE_FILE="${COMPOSE_FILE:-deploy/compose.yaml}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8080}"
START_WORKER="${TENCENT_START_WORKER:-false}"
LOG_DIR="${LOG_DIR:-/opt/dy-dashboard/logs}"
SKIP_GIT_SYNC="${SKIP_GIT_SYNC:-false}"
APT_MIRROR="${APT_MIRROR:-http://mirrors.tencentyun.com}"
DY_WEB_BASE_URL="${DY_WEB_BASE_URL:-}"
export APT_MIRROR DY_WEB_BASE_URL

compose() {
  sudo APT_MIRROR="$APT_MIRROR" DY_WEB_BASE_URL="$DY_WEB_BASE_URL" docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

log() {
  printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

fetch_origin() {
  for attempt in 1 2 3 4 5; do
    if git -c http.version=HTTP/1.1 fetch --prune origin; then
      return 0
    fi
    log "git fetch failed on attempt=$attempt; retrying"
    sleep $((attempt * 5))
  done
  log "git fetch failed after retries"
  return 1
}

check_production_migration_lineage() {
  local has_version_table
  local current_revision

  has_version_table="$(
    compose exec -T postgres sh -c \
      'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT to_regclass('\''public.alembic_version'\'')"'
  )"
  has_version_table="${has_version_table//$'\r'/}"
  if [ -z "$has_version_table" ]; then
    log "production database has no alembic_version table; allowing base migration"
    return 0
  fi

  current_revision="$(
    compose exec -T postgres sh -c \
      'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT version_num FROM alembic_version"'
  )"
  current_revision="${current_revision//$'\r'/}"
  if [ -z "$current_revision" ]; then
    log "production alembic_version is empty"
    return 1
  fi
  case "$current_revision" in
    *[!A-Za-z0-9_]*)
      log "production alembic revision contains unexpected characters"
      return 1
      ;;
  esac

  log "production alembic revision=$current_revision"
  if compose run --rm --no-deps migrate alembic show "$current_revision" >/dev/null 2>&1; then
    log "target source contains production revision=$current_revision"
    return 0
  fi

  log "target source is missing production revision=$current_revision"
  log "attempting read-only recovery from the currently running API container"
  if compose exec -T api sh -c '
    set -eu
    revision="$1"
    files="$(grep -RIl --include="*.py" -- "$revision" /app/alembic/versions || true)"
    [ -n "$files" ] || exit 1
    for file in $files; do
      printf "migration-source-begin path=%s revision=%s\n" "$file" "$revision"
      cat "$file"
      printf "\nmigration-source-end path=%s revision=%s\n" "$file" "$revision"
    done
  ' sh "$current_revision"; then
    log "recovered migration source evidence for revision=$current_revision"
  else
    log "current API container does not contain revision=$current_revision"
  fi
  log "blocking deployment before alembic upgrade; restore the migration lineage first"
  return 1
}

on_error() {
  status=$?
  log "deployment failed with status=$status"
  compose ps -a || true
  compose logs --tail=80 api web proxy || true
  exit "$status"
}

trap on_error ERR

cd "$APP_DIR"
mkdir -p "$LOG_DIR"

if [ ! -f "$ENV_FILE" ]; then
  log "missing env file: $ENV_FILE"
  exit 1
fi

if [ "$SKIP_GIT_SYNC" != "true" ] && (! git diff --quiet || ! git diff --cached --quiet); then
  dirty_stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  log "server worktree has local changes; saving diff before reset"
  git status --short > "$LOG_DIR/pre-deploy-dirty-$dirty_stamp.status"
  git diff > "$LOG_DIR/pre-deploy-dirty-$dirty_stamp.patch"
fi

if [ "$SKIP_GIT_SYNC" = "true" ]; then
  log "skipping git sync because SKIP_GIT_SYNC=true"
else
  log "fetching target $TARGET_SHA"
  fetch_origin
  git checkout main
  git reset --hard "$TARGET_SHA"
fi

log "validating compose configuration"
log "using apt mirror $APT_MIRROR"
compose config >/dev/null

log "building images"
compose build --progress=plain api web browser worker

log "starting postgres"
compose up -d postgres

log "checking production migration lineage"
check_production_migration_lineage

log "running migrations"
compose run --rm migrate

log "starting runtime services without worker"
compose up -d --no-deps api web browser

log "recreating proxy so nginx resolves fresh upstream container addresses"
compose up -d --no-deps --force-recreate proxy

if [ "$START_WORKER" = "true" ]; then
  log "starting worker because TENCENT_START_WORKER=true"
  compose up -d --no-deps --force-recreate worker
else
  log "keeping worker stopped because TENCENT_START_WORKER is not true"
  compose stop worker >/dev/null 2>&1 || true
fi

log "running smoke checks"
expected_mcp_url="${DY_WEB_BASE_URL%/}/mcp"
for attempt in $(seq 1 30); do
  if curl --fail --silent --show-error "$HEALTH_URL/" >/dev/null; then
    auth_status="$(curl --silent --show-error --output /dev/null --write-out "%{http_code}" "$HEALTH_URL/api/v1/auth/me")"
    cli_start_status="$(curl --silent --show-error --output /dev/null --write-out "%{http_code}" --request POST "$HEALTH_URL/api/v1/auth/cli/device/start")"
    oauth_status="$(curl --silent --show-error --output /dev/null --write-out "%{http_code}" "$HEALTH_URL/.well-known/oauth-authorization-server")"
    protected_resource_status="$(curl --silent --show-error --output /dev/null --write-out "%{http_code}" "$HEALTH_URL/.well-known/oauth-protected-resource/mcp")"
    agent_doc_status="$(curl --silent --show-error --output /dev/null --write-out "%{http_code}" "$HEALTH_URL/agent.md")"
    mcp_status="$(curl --silent --show-error --output /dev/null --write-out "%{http_code}" --request POST --header "Content-Type: application/json" --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' "$HEALTH_URL/mcp")"
    if agent_manifest="$(curl --fail --silent --show-error "$HEALTH_URL/.well-known/dydata-agent.json")" \
      && [ "$auth_status" = "401" ] \
      && [ "$cli_start_status" = "200" ] \
      && [ "$oauth_status" = "200" ] \
      && [ "$protected_resource_status" = "200" ] \
      && [ "$agent_doc_status" = "200" ] \
      && [ "$mcp_status" = "401" ] \
      && printf '%s' "$agent_manifest" | grep -Fq '"environment":"test"' \
      && printf '%s' "$agent_manifest" | grep -Fq "\"url\":\"$expected_mcp_url\""; then
      break
    fi
  fi
  if [ "$attempt" = "30" ]; then
    log "smoke checks failed after $attempt attempts"
    exit 1
  fi
  sleep 2
done

if [ "$SKIP_GIT_SYNC" = "true" ]; then
  deployed_sha="$TARGET_SHA"
else
  deployed_sha="$(git rev-parse HEAD)"
fi
cat > "$LOG_DIR/last-deploy.json" <<JSON
{"ts":"$(date -u +%Y-%m-%dT%H:%M:%SZ)","sha":"$deployed_sha","worker_started":$([ "$START_WORKER" = "true" ] && echo true || echo false)}
JSON

log "deployment complete sha=$deployed_sha"
compose ps -a
