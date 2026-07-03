#!/usr/bin/env bash
set -Eeuo pipefail

TARGET_SHA="${1:-origin/main}"
APP_DIR="${APP_DIR:-/opt/dy-dashboard/repo}"
ENV_FILE="${ENV_FILE:-/opt/dy-dashboard/env/production.env}"
COMPOSE_FILE="${COMPOSE_FILE:-deploy/compose.yaml}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8080}"
START_WORKER="${TENCENT_START_WORKER:-false}"
LOG_DIR="${LOG_DIR:-/opt/dy-dashboard/logs}"

compose() {
  sudo docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

log() {
  printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
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

if ! git diff --quiet || ! git diff --cached --quiet; then
  dirty_stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  log "server worktree has local changes; saving diff before reset"
  git status --short > "$LOG_DIR/pre-deploy-dirty-$dirty_stamp.status"
  git diff > "$LOG_DIR/pre-deploy-dirty-$dirty_stamp.patch"
fi

log "fetching target $TARGET_SHA"
git fetch --prune origin
git checkout main
git reset --hard "$TARGET_SHA"

log "validating compose configuration"
compose config >/dev/null

log "building images"
compose build api web browser

log "starting postgres"
compose up -d postgres

log "running migrations"
compose run --rm migrate

log "starting runtime services without worker"
compose up -d --no-deps api web browser proxy

if [ "$START_WORKER" = "true" ]; then
  log "starting worker because TENCENT_START_WORKER=true"
  compose up -d --no-deps worker
else
  log "keeping worker stopped because TENCENT_START_WORKER is not true"
  compose stop worker >/dev/null 2>&1 || true
fi

log "running smoke checks"
for attempt in $(seq 1 30); do
  if curl --fail --silent --show-error "$HEALTH_URL/" >/dev/null; then
    auth_status="$(curl --silent --show-error --output /dev/null --write-out "%{http_code}" "$HEALTH_URL/api/v1/auth/me")"
    if [ "$auth_status" = "401" ]; then
      break
    fi
  fi
  if [ "$attempt" = "30" ]; then
    log "smoke checks failed after $attempt attempts"
    exit 1
  fi
  sleep 2
done

deployed_sha="$(git rev-parse HEAD)"
cat > "$LOG_DIR/last-deploy.json" <<JSON
{"ts":"$(date -u +%Y-%m-%dT%H:%M:%SZ)","sha":"$deployed_sha","worker_started":$([ "$START_WORKER" = "true" ] && echo true || echo false)}
JSON

log "deployment complete sha=$deployed_sha"
compose ps -a
