#!/usr/bin/env bash
# Controller-prepared, not executed. Exactly one audited metadata compaction.
set -Eeuo pipefail
export LC_ALL=C
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
for container in "$api" "$worker"; do
  while read -r digest module; do
    actual="$(sudo docker exec "$container" sha256sum "/app/$module")"
    test "${actual%% *}" = "$digest"
  done <<'HASHES'
310a236a90200190bca1dad097160e8b2de949a83dd49f56fc9aafe6517f0086 apps/worker/day_recovery.py
abc2a3d529fbbdcdc969271e0b1aaad426d8092afb79b02a764db39e07bcf63e apps/worker/legacy_projection_bootstrap.py
4869d859dff53f79553cbf88f731218c37099945a3273260fe48b2b88b08386b apps/worker/projection_lineage.py
363da04b3700ba8fbd0e4d2970aef77ca548fb712de4a760043f96eddcc4d5ab apps/worker/settlement.py
020ba1434153461a5c80d20cfb5411ea963f05390e83ffb5dea7e3126d2de1f3 apps/worker/settlement_compaction.py
HASHES
done
printf 'api_and_worker_source_verification=passed\n'
compose exec -T worker python - <<'PY'
from apps.worker.resource_monitor import guard_enabled
assert guard_enabled(), 'resource_guard_disabled_refusing_maintenance'
print('real_resource_guard_enabled=true',flush=True)
PY
test -f /tmp/dydata102-compaction-snapshot.py
sudo docker cp /tmp/dydata102-compaction-snapshot.py "$worker:/tmp/dydata102-compaction-snapshot.py"
compose exec -T worker python /tmp/dydata102-compaction-snapshot.py > /tmp/dydata102-compaction-before.json
compose exec -T worker python - <<'PY' > /tmp/dydata102-compaction-resources.json
import json
from sqlalchemy import select,func,literal,text
from apps.api.dy_api import models as M
from dy_api.pdca_readonly_access import _open_pdca_readonly_session
scope=_open_pdca_readonly_session()
s=next(scope)
try:
    assert s.scalar(text('SHOW transaction_read_only'))=='on'
    active=s.get(M.SettlementProjectionActive,'settlement')
    head=s.get(M.SettlementProjectionGeneration,active.generation_id)
    assert head.state=='published' and head.generation_kind=='lineage' and 48<=head.lineage_depth<=64
    G=M.SettlementProjectionGeneration
    chain=select(G.generation_id,G.base_generation_id,literal(0).label('hop')).where(G.generation_id==head.generation_id).cte('ops_chain',recursive=True)
    chain=chain.union_all(select(G.generation_id,G.base_generation_id,(chain.c.hop+1).label('hop')).join(chain,G.generation_id==chain.c.base_generation_id).where(chain.c.hop<65))
    rows=s.execute(select(chain).order_by(chain.c.hop)).mappings().all()
    ids=[row['generation_id'] for row in rows]
    assert len(set(ids))==len(ids) and 1<=len(ids)<=65 and rows[-1]['base_generation_id'] is None
    P=M.SettlementProjectionPartitionManifest
    partitions=select(P.artifact,P.partition_key).where(P.generation_id.in_(ids)).distinct().subquery()
    count=s.scalar(select(func.count()).select_from(partitions))
    assert count>0
    write=16384+4096*(count+len(ids))
    print(json.dumps({'base':head.generation_id,'max_manifest_rows':count,'max_write':write*2,'max_wal':write*4}))
finally:scope.close()
PY
pg_mount="$(sudo docker inspect --format '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql"}}{{.Type}}|{{.Source}}{{end}}{{end}}' "$postgres")"
IFS='|' read -r pg_type pg_source <<< "$pg_mount"
test "$pg_type" = volume
test "${pg_source#/}" != "$pg_source"
sudo test -d "$pg_source"
read -r total available < <(sudo df -B1 --output=size,avail "$pg_source" | tail -1 | xargs)
[[ "$total" =~ ^[0-9]+$ && "$available" =~ ^[0-9]+$ ]]
minimum=$(((total*15+99)/100))
if ((minimum<10737418240)); then minimum=10737418240; fi
((available>=minimum))
printf 'pg_disk_total=%s pg_disk_available=%s minimum=%s\n' "$total" "$available" "$minimum"
mapfile -t resource_args < <(python3 - <<'PY'
import json
r=json.load(open('/tmp/dydata102-compaction-resources.json'))
for k in ('base','max_manifest_rows','max_write','max_wal'):print(r[k])
PY
)
test "${#resource_args[@]}" -eq 4
compose exec -T worker python scripts/ops/compact_settlement_projection.py \
  --base-generation-id "${resource_args[0]}" --batch-size 200 \
  --max-manifest-rows "${resource_args[1]}" \
  --max-estimated-write-bytes "${resource_args[2]}" \
  --max-estimated-wal-bytes "${resource_args[3]}" \
  --observed-disk-headroom-bytes "$available" --min-disk-headroom-bytes "$minimum" \
  --admission-wait-seconds 1200 > /tmp/dydata102-compaction-result.json
compose exec -T worker python /tmp/dydata102-compaction-snapshot.py > /tmp/dydata102-compaction-after.json
python3 - <<'PY'
import json
before=json.load(open('/tmp/dydata102-compaction-before.json'))
after=json.load(open('/tmp/dydata102-compaction-after.json'))
result=json.load(open('/tmp/dydata102-compaction-result.json'))
assert result.get('status')=='success' and result.get('generation_id'), 'compaction_not_published'
assert after['head']['generation_id']==result['generation_id'] and after['head']['kind']=='compact' and after['head']['depth']==0, 'published_head_mismatch'
assert before['financial_facts']==after['financial_facts'], 'financial_facts_changed_requires_review'
print(json.dumps({'compaction_result':result,'before_head':before['head'],'after_head':after['head'],'financial_facts_unchanged':True,'financial_facts':after['financial_facts']},sort_keys=True))
PY
