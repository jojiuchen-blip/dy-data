#!/usr/bin/env bash
set -Eeuo pipefail
mode="$1"; stage="$2"; image="$3"; archive_bytes="$4"; image_bytes="$5"
[[ "$stage" =~ ^/tmp/account-search-[0-9]+$ ]]
[[ "$image" == dy-dashboard-web:account-search-92a8de3d ]]
[[ "$archive_bytes" =~ ^[0-9]+$ ]]
[[ "$image_bytes" =~ ^[0-9]+$ ]]
cd /opt/dy-dashboard/repo
compose() { sudo docker compose --env-file /opt/dy-dashboard/env/production.env -f deploy/compose.yaml "$@"; }
exec 9>/tmp/dy-account-search-release.lock
flock -n 9
if pgrep -af '[b]ash deploy/tencent/deploy.sh'; then exit 1; fi
docker_root="$(sudo docker info --format '{{.DockerRootDir}}')"
sudo python3 - "$stage" "$archive_bytes" "$image_bytes" "$docker_root" <<'PY'
import json,hashlib,os,sys
from pathlib import Path
stage=Path(sys.argv[1]); size=int(sys.argv[2]); image_size=int(sys.argv[3]); docker_root=sys.argv[4]
release=json.load(open('/opt/dy-dashboard/logs/last-deploy.json'))
assert release['sha']=='fe02e2a829f572cd91ed11e4815fd23a5e3504a0', 'Production baseline changed'
for rel,digest in json.load(open(stage/'manifest.json')).items():
    p=Path(rel)
    assert str(p).startswith('apps/web/') and not p.is_symlink()
    assert hashlib.sha256(p.read_bytes()).hexdigest()==digest, 'Source differs: '+rel
budgets={}
for path,reserve in ((str(stage),size),(docker_root,image_size*2),('/opt/dy-dashboard',0)):
    dev=os.stat(path).st_dev
    if dev not in budgets: budgets[dev]=[path,0]
    budgets[dev][1]+=reserve
for path,reserve in budgets.values():
    s=os.statvfs(path); free=s.f_bavail*s.f_frsize; total=s.f_blocks*s.f_frsize
    assert free-reserve>=max(10*1024**3,total*.15), 'Capacity gate failed: '+path
    print('Capacity gate passed',path,free,reserve)
print('Source baseline verified')
PY
if [ "$mode" = preflight ]; then exit 0; fi
test "$mode" = deploy
test "$(stat -c %s "$stage/web-image.tar.gz")" = "$archive_bytes"
(cd "$stage" && sha256sum -c image.sha256)
before="$(compose ps -q api worker postgres browser ops-agent | sort)"
test -n "$before"
web="$(compose ps -q web)"; test -n "$web"
old_image="$(sudo docker inspect --format '{{.Image}}' "$web")"
old_tag="$(sudo docker inspect --format '{{.Config.Image}}' "$web")"
rollback_tag="dy-dashboard-web:rollback-account-search-${stage##*-}"
sudo docker tag "$old_image" "$rollback_tag"
sudo docker load -i "$stage/web-image.tar.gz"
sudo docker image inspect "$image" >/dev/null
rollback() {
  code=$?
  trap - ERR
  if sudo docker tag "$old_image" "$old_tag" &&
     compose up -d --no-deps --no-build web &&
     test "$(sudo docker inspect --format '{{.Image}}' "$(compose ps -q web)")" = "$old_image" &&
     compose exec -T proxy nginx -s reload &&
     curl --retry 5 --retry-delay 2 --retry-connrefused --fail --silent --show-error --max-time 20 http://127.0.0.1:8080/ >/dev/null; then
    echo 'Web release failed; rollback verified'
  else
    echo 'ROLLBACK_FAILED: manual recovery required'
  fi
  exit "$code"
}
trap rollback ERR
sudo docker tag "$image" "$old_tag"
compose up -d --no-deps --no-build web
compose exec -T web nginx -t
compose exec -T proxy nginx -t
compose exec -T proxy nginx -s reload
curl --retry 5 --retry-delay 2 --retry-connrefused --fail --silent --show-error --max-time 20 http://127.0.0.1:8080/ > "$stage/index.html"
compose exec -T web sh -c 'grep -rl "搜索账号" /usr/share/nginx/html/assets/AdminAccountsPage-*.js' >/dev/null
test "$(curl --silent --show-error --max-time 20 --output /dev/null --write-out '%{http_code}' http://127.0.0.1:8080/api/v1/auth/me)" = 401
test "$before" = "$(compose ps -q api worker postgres browser ops-agent | sort)"
curl --retry 3 --retry-delay 2 --fail --silent --show-error --max-time 20 https://dy-business-engine.com/admin/accounts >/dev/null
trap - ERR
# Keep backend deployment metadata intact; record the frontend overlay separately.
sudo install -m 644 "$stage/AdminAccountsPage.tsx" apps/web/src/pages/AdminAccountsPage.tsx
python3 - "$old_image" "$image" "$rollback_tag" <<'PY'
import json,sys,datetime
from pathlib import Path
p=Path('/opt/dy-dashboard/logs/account-search-web-release.json')
p.write_text(json.dumps(dict(ts=datetime.datetime.now(datetime.timezone.utc).isoformat(),base='fe02e2a829f572cd91ed11e4815fd23a5e3504a0',overlay='92a8de3d279f6dd5d36805eff52579994c2531bd',old_image=sys.argv[1],image=sys.argv[2],rollback_tag=sys.argv[3],backend_unchanged=True)))
print('ACCOUNT_SEARCH_WEB_DEPLOY_SUCCESS')
PY
rm -f -- "$stage/web-image.tar.gz"
