"""Guarded API-only deployment runner for the verified two-file candidate.

Uses the exact tested local image containing two verified Python files, retains
the previous image and an exact environment backup, and rolls back on startup
failure. Does not migrate, back up, rewrite, or delete database/business data.
"""
import hashlib,json,os,re,subprocess,time,fcntl
from pathlib import Path

ROOT=Path('/opt/dy-dashboard'); REPO=ROOT/'repo'; ENV=ROOT/'env/production.env'
SHA='393e3dab77f229840f6127e4d15fcd77939e471e'
BASE='fe02e2a829f572cd91ed11e4815fd23a5e3504a0'
OLD_HASH='0f1fcc5427fb1df082e0e438320e46e6b4e860824b8e713c20a42c53ef5738d4'
NEW_HASH='38d17e1d3f5c4474e4ae53bcdc48ee26c44abc0a6ada8206c079e3b4a5d2a2bf'
MODULE='/app/apps/api/dy_api/ranking_snapshots.py'
LIFECYCLE='/app/apps/api/dy_api/ranking_lifecycle.py'
OLD_LIFECYCLE='e85cb7c05c32c79d5b0f1d3c96af2def3161d1edca80d6c53d02ff3f4162adf3'
NEW_LIFECYCLE='999aba3e6c60613cc3d2d8800ed002cc906d9494d49f2f2273ff06794b823f1f'
IMAGE='dy-dashboard-api:pdca-ranking-'+SHA[:8]

def run(args,**kw): return subprocess.check_output(args,text=True,**kw).strip()
def compose(*args,image=None):
    environment=os.environ.copy()
    if image:environment['API_IMAGE']=image
    return run(['docker','compose','--env-file',str(ENV),'-f',str(REPO/'deploy/compose.yaml'),*args],cwd=REPO,env=environment)

def wait_healthy(image):
    for _ in range(30):
        current=compose('ps','-q','api')
        if current:
            info=json.loads(run(['docker','inspect',current]))[0]
            assert info['Image']==image,'Unexpected API image'
            if info['State']['Running'] and info['State'].get('Health',{}).get('Status')=='healthy':return current
        time.sleep(2)
    raise RuntimeError('API failed health check')

def with_image(data,image):
    text=data.decode();line='API_IMAGE='+image
    return (re.sub(r'^API_IMAGE=.*$',line,text,flags=re.M) if re.search(r'^API_IMAGE=',text,re.M) else text.rstrip()+'\n'+line+'\n').encode()
def atomic(path,data,mode=0o600):
    previous=path.stat() if path.exists() else None
    tmp=path.with_name(path.name+'.pdca-tmp')
    with tmp.open('xb') as f:f.write(data)
    if previous:os.chown(tmp,previous.st_uid,previous.st_gid)
    os.chmod(tmp,mode);os.replace(tmp,path)
def main():
    assert os.geteuid()==0
    lock=(ROOT/'logs/pdca-ranking-deploy.lock').open('a')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    record=json.loads((ROOT/'logs/last-deploy.json').read_text())
    assert record['sha']==BASE,'Production deployment changed; stop and rebase'
    container=compose('ps','-q','api'); assert container and '\n' not in container
    state=json.loads(run(['docker','inspect',container]))[0]
    assert state['State']['Running'] and state['State'].get('Health',{}).get('Status')=='healthy'
    assert run(['docker','exec',container,'sha256sum',MODULE]).split()[0]==OLD_HASH,'Running source drift'
    assert run(['docker','exec',container,'sha256sum',LIFECYCLE]).split()[0]==OLD_LIFECYCLE,'Running lifecycle drift'
    source=Path('/tmp/pdca-ranking-'+SHA[:8]+'/ranking_snapshots.py')
    assert hashlib.sha256(source.read_bytes()).hexdigest()==NEW_HASH
    stat=os.statvfs(ROOT);free=stat.f_bavail*stat.f_frsize;total=stat.f_blocks*stat.f_frsize
    assert free>=10*1024**3 and free/total>=.15,'Insufficient disk headroom'
    report=ROOT/('logs/pdca-ranking-'+SHA[:8]+'.json')
    assert not report.exists(),'Existing deployment record requires inspection'
    original_env=ENV.read_bytes(); old_image=state['Image']; rollback='dy-dashboard-api:rollback-pdca-'+SHA[:8]
    # Use the exact immutable candidate already exercised under the 768MB cap.
    proof=json.loads((ROOT/('logs/pdca-ranking-candidate-'+SHA[:8]+'.json')).read_text())
    assert proof['patch_sha']==SHA and proof['base_image']==old_image and proof['all_pages_verified'] is True
    image_id=proof['image_id'];assert re.fullmatch(r'sha256:[0-9a-f]{64}',image_id)
    assert run(['docker','image','inspect','--format','{{index .Config.Labels "pdca.ranking.patch"}}',image_id])==SHA
    assert run(['docker','run','--rm',image_id,'sha256sum',MODULE]).split()[0]==NEW_HASH
    assert run(['docker','run','--rm',image_id,'sha256sum',LIFECYCLE]).split()[0]==NEW_LIFECYCLE
    run(['docker','tag',old_image,rollback])
    backup=ROOT/('logs/backups/pre-pdca-ranking-'+SHA[:8]+'.env')
    with backup.open('xb') as f:f.write(original_env)
    os.chmod(backup,0o600)
    result={'base':BASE,'patch_sha':SHA,'old_image':old_image,'rollback_tag':rollback,'new_image':image_id,'environment_backup':str(backup),'state':'prepared'}
    atomic(report,json.dumps(result,indent=2).encode())
    updated=with_image(original_env,image_id)
    assert ENV.read_bytes()==original_env and compose('ps','-q','api')==container,'Concurrent deployment detected'
    try:
        atomic(ENV,updated,ENV.stat().st_mode&0o777)
        compose('up','-d','--no-deps','--no-build','--pull','never','api',image=image_id)
        current=wait_healthy(image_id)
        assert run(['docker','exec',current,'sha256sum',MODULE]).split()[0]==NEW_HASH
        assert run(['docker','exec',current,'sha256sum',LIFECYCLE]).split()[0]==NEW_LIFECYCLE
        result['state']='healthy_pending_business_verification'
    except BaseException:
        try:
            # Preserve all previous settings while pinning the actual original image.
            atomic(ENV,with_image(original_env,old_image),ENV.stat().st_mode&0o777)
            compose('up','-d','--no-deps','--no-build','--pull','never','api',image=old_image)
            wait_healthy(old_image)
            result['state']='rolled_back'
        except BaseException:
            result['state']='rollback_failed'
            raise
        finally:
            atomic(report,json.dumps(result,indent=2).encode())
        raise
    atomic(report,json.dumps(result,indent=2).encode());print(json.dumps(result))

if __name__=='__main__': main()
