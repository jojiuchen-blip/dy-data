#!/usr/bin/env bash
# DYDATA-102 Sep14 recovery: controller-prepared, NOT executed.
# Reuses the real /tmp/dydata102-scoped-recovery-driver.py inside the worker;
# this script only checks preconditions, copies the file, and calls it verbatim.
set -Eeuo pipefail
export LC_ALL=C
mode="${1:-dry-run}"
case "$mode" in
  dry-run) apply_args=() ;;
  apply) apply_args=(--apply) ;;
  *) echo "refused mode=$mode must_be_dry-run_or_apply" >&2; exit 2 ;;
esac
expected_revision=fe02e2a829f572cd91ed11e4815fd23a5e3504a0
cd /opt/dy-dashboard/repo
# The standard deploy installs a git archive with SKIP_GIT_SYNC=true. The
# retained .git HEAD is historical; use its completed deploy marker plus the
# actual API/worker file hashes below, never reset Git to manufacture evidence.
python3 - "$expected_revision" <<'PY'
import json,sys
with open('/opt/dy-dashboard/logs/last-deploy.json') as stream:record=json.load(stream)
assert record.get('sha')==sys.argv[1] and record.get('environment')=='production' and record.get('worker_started') is True, 'completed_deployment_revision_mismatch'
print('completed_deployment_revision='+record['sha'],flush=True)
PY
compose() { sudo docker compose --env-file /opt/dy-dashboard/env/production.env -f deploy/compose.yaml "$@"; }
worker="$(compose ps -q worker)"
postgres="$(compose ps -q postgres)"
api="$(compose ps -q api)"
test -n "$worker" && test -n "$postgres" && test -n "$api"
for container in "$api" "$worker" "$postgres"; do
  test "$(sudo docker inspect --format '{{.State.Status}}' "$container")" = running
  test "$(sudo docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container")" = healthy
  sudo docker inspect --format 'service={{.Name}} started_at={{.State.StartedAt}}' "$container"
done
# API/worker key source integrity via sha256sum (no imports, no diagnostic Python in API).
for container in "$api" "$worker"; do
  while read -r digest module; do
    actual="$(sudo docker exec "$container" sha256sum "/app/$module")"
    test "${actual%% *}" = "$digest"
  done <<'HASHES'
310a236a90200190bca1dad097160e8b2de949a83dd49f56fc9aafe6517f0086 apps/worker/day_recovery.py
4869d859dff53f79553cbf88f731218c37099945a3273260fe48b2b88b08386b apps/worker/projection_lineage.py
363da04b3700ba8fbd0e4d2970aef77ca548fb712de4a760043f96eddcc4d5ab apps/worker/settlement.py
020ba1434153461a5c80d20cfb5411ea963f05390e83ffb5dea7e3126d2de1f3 apps/worker/settlement_compaction.py
HASHES
done
printf 'api_and_worker_source_verification=passed\n'
# Real worker resource guard must be enabled (checked in the worker container only).
compose exec -T worker python - <<'PY'
from apps.worker.resource_monitor import guard_enabled
assert guard_enabled(), 'resource_guard_disabled_refusing_recovery'
print('real_resource_guard_enabled=true', flush=True)
PY
# Controller-uploaded driver must exist on the host, then be copied into the worker.
driver=/tmp/dydata102-scoped-recovery-driver.py
test -s "$driver"
sudo docker cp "$driver" "$worker:$driver"
compose exec -T worker test -s "$driver"
set +e
compose exec -T worker python "$driver" \
  --root-job-id 'range-sync-10562f3369ac7d31e9801d42d8db1d60' \
  --request-key 'dydata102-sep14-recovery-20261016-v2' \
  --actor 'dydata102-authorized-ops' \
  --reason 'explaining user-authorized Sep14 recovery after fenced compaction' \
  --max-wait-seconds 7200 "${apply_args[@]}"
rc=$?
set -e
echo "recovery_driver_exit_code=$rc mode=$mode"
exit "$rc"
