#!/usr/bin/env bash
set -Eeuo pipefail
mode="$1"; stage="$2"; image="$3"; archive_bytes="$4"; image_bytes="$5"
[[ "$stage" =~ ^/tmp/clue-web-[0-9]+$ ]]
[[ "$image" == dy-dashboard-web:clue-f9320d788e81 ]]
[[ "$archive_bytes" =~ ^[0-9]+$ && "$image_bytes" =~ ^[0-9]+$ ]]
cd /opt/dy-dashboard/repo
compose() { sudo docker compose --env-file /opt/dy-dashboard/env/production.env -f deploy/compose.yaml "$@"; }
exec 9>/tmp/dy-clue-web-release.lock
flock -n 9
if pgrep -af '[b]ash deploy/tencent/deploy.sh'; then exit 1; fi
web="$(compose ps -q web)"; test -n "$web"
old_image="$(sudo docker inspect --format '{{.Image}}' "$web")"
test "$old_image" = sha256:bd8e7a3ad95f748ae03cbe98d2bfb8bb9c44267f63f8597ea727b0f8af47632e
docker_root="$(sudo docker info --format '{{.DockerRootDir}}')"
sudo python3 - "$stage" "$archive_bytes" "$image_bytes" "$docker_root" <<'PY'
import json,hashlib,os,sys
from pathlib import Path
stage=Path(sys.argv[1]); size=int(sys.argv[2]); image_size=int(sys.argv[3]); docker_root=sys.argv[4]
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
    print('CAPACITY_OK',free,reserve)
print('SOURCE_BASELINE_OK')
PY
if [ "$mode" = preflight ]; then
  compose exec -T api python - < "$stage/verify-readonly.py"
  exit 0
fi
test "$mode" = deploy
test "$(stat -c %s "$stage/web-image.tar.gz")" = "$archive_bytes"
(cd "$stage" && sha256sum -c image.sha256)
services=(api worker publication-worker postgres browser ops-agent)
before="$(compose ps -q "${services[@]}" | sort)"
test "$(printf '%s\n' "$before" | wc -l)" = 6
rollback_tag="dy-dashboard-web:rollback-clue-${stage##*-}"
sudo docker tag "$old_image" "$rollback_tag"
sudo docker load -i "$stage/web-image.tar.gz"
expected_image="$(cat "$stage/image-id.txt")"
test "$(sudo docker image inspect --format '{{.Id}}' "$image")" = "$expected_image"
backup="/opt/dy-dashboard/backups/clue-web-${stage##*-}"
sudo install -d -m 700 "$backup"
sudo install -m 600 /opt/dy-dashboard/env/production.env "$backup/production.env"
files=(src/pages/ClueCenterPage.tsx src/types/dashboard.ts src/demo/clueDemoRepository.ts src/styles.css)
for file in "${files[@]}"; do
  sudo install -D -m 600 "apps/web/$file" "$backup/$file"
done
rollback() {
  code="${1:-1}"; trap - ERR HUP INT TERM
  sudo install -m 600 "$backup/production.env" /opt/dy-dashboard/env/production.env
  for file in "${files[@]}"; do sudo install -m 644 "$backup/$file" "apps/web/$file"; done
  if sudo env WEB_IMAGE="$rollback_tag" docker compose --env-file /opt/dy-dashboard/env/production.env -f deploy/compose.yaml up -d --no-deps --no-build web &&
     test "$(sudo docker inspect --format '{{.Image}}' "$(compose ps -q web)")" = "$old_image" &&
     compose exec -T proxy nginx -s reload &&
     curl --retry 5 --retry-delay 2 --retry-connrefused --fail --silent --show-error --max-time 20 http://127.0.0.1:8080/ >/dev/null; then
    echo 'ROLLBACK_VERIFIED'
  else
    echo 'ROLLBACK_FAILED'; exit 90
  fi
  exit "$code"
}
trap 'rollback $?' ERR
trap 'rollback 129' HUP
trap 'rollback 130' INT
trap 'rollback 143' TERM
sudo python3 - "$image" <<'PY'
from pathlib import Path
import sys
p=Path('/opt/dy-dashboard/env/production.env')
lines=[x for x in p.read_text().splitlines() if not x.startswith('WEB_IMAGE=')]
p.write_text('\n'.join(lines+['WEB_IMAGE='+sys.argv[1]])+'\n')
PY
for file in "${files[@]}"; do sudo install -m 644 "$stage/source/$file" "apps/web/$file"; done
compose up -d --no-deps --no-build web
test "$(sudo docker inspect --format '{{.Image}}' "$(compose ps -q web)")" = "$expected_image"
compose exec -T web nginx -t
compose exec -T proxy nginx -t
compose exec -T proxy nginx -s reload
curl --retry 5 --retry-delay 2 --retry-connrefused --fail --silent --show-error --max-time 20 http://127.0.0.1:8080/ > "$stage/index.html"
compose exec -T web sh -c 'grep -rl "仅看自店核销" /usr/share/nginx/html/assets/ClueCenterPage-*.js' >/dev/null
compose exec -T web sh -c 'grep -rl "核销门店" /usr/share/nginx/html/assets/ClueCenterPage-*.js' >/dev/null
test "$(curl --silent --show-error --max-time 20 --output /dev/null --write-out '%{http_code}' http://127.0.0.1:8080/api/v1/auth/me)" = 401
test "$before" = "$(compose ps -q "${services[@]}" | sort)"
curl --retry 3 --retry-delay 2 --fail --silent --show-error --max-time 20 https://dy-business-engine.com/clues/details >/dev/null
compose exec -T api python - < "$stage/verify-readonly.py"
sudo python3 - "$old_image" "$expected_image" "$rollback_tag" "$backup" <<'PY'
import json,sys,datetime,os
from pathlib import Path
p=Path('/opt/dy-dashboard/logs/clue-verification-web-release.json')
s=os.statvfs('/opt/dy-dashboard')
p.write_text(json.dumps(dict(ts=datetime.datetime.now(datetime.timezone.utc).isoformat(),source='f9320d788e815dc6ed6fcc95eb0e9c16144456b2',old_image=sys.argv[1],image=sys.argv[2],rollback_tag=sys.argv[3],backup=sys.argv[4],backend_unchanged=True,free_bytes=s.f_bavail*s.f_frsize)))
print('CLUE_VERIFICATION_WEB_DEPLOY_SUCCESS',s.f_bavail*s.f_frsize)
PY
trap - ERR HUP INT TERM
# Only the exact uploaded disposable archive is removed after successful cutover.
rm -f -- "$stage/web-image.tar.gz"
