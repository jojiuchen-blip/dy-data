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

compose() {
  sudo docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
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
compose config >/dev/null

log "building images"
compose build api web browser

log "starting postgres"
compose up -d postgres

log "running migrations"
compose run --rm migrate

log "starting runtime services without worker"
compose up -d --no-deps api web browser

log "recreating proxy so nginx resolves fresh upstream container addresses"
compose up -d --no-deps --force-recreate proxy

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
