#!/usr/bin/env python3
"""45-day maintenance of disposable caches. Never prune containers or volumes."""
import fcntl,hashlib,json,os,re,stat,subprocess,sys,tempfile,time
from pathlib import Path
INTERVAL=45*86400


def atomic(path,value):
    fd,name=tempfile.mkstemp(prefix='.maintenance-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as stream:json.dump(value,stream);stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
    finally:Path(name).unlink(missing_ok=True)


def read(path):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd) as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):raise ValueError('Unsafe maintenance metadata')
        return json.loads(stream.read(8192))


def maintain(app,private,runner,now=None):
    now=time.time() if now is None else now
    stamp=private/'maintenance.json'
    try:
        if now-read(stamp)['at']<INTERVAL:return {'due':False}
    except (OSError,ValueError,KeyError,TypeError):pass
    result={'due':True,'at':now,'retired_recovery_files':0,'errors':[]}
    def run(args):
        try:runner(args);return True
        except Exception:result['errors'].append(args[:3]);return False
    # Retain the two most recent recovery sets, regardless of their age.
    candidates=sorted([p for p in private.glob('recovery-*.json') if not p.is_symlink()],key=lambda p:p.stat().st_mtime,reverse=True)
    for path in candidates[2:]:
        if not re.fullmatch(r'recovery-[a-f0-9-]{36}\.json',path.name) or max(path.stat().st_mtime,path.stat().st_ctime)>now-INTERVAL:continue
        try:
            config=read(path);images=[]
            for service,value in config['services'].items():
                tag=value['image']
                if service not in {'api','bot'} or not re.fullmatch('dbot-recovery-'+service+':[a-f0-9]{32}',tag):raise ValueError('Invalid recovery image')
                images.append(tag)
            if all([run(['docker','image','rm',tag]) for tag in images]):path.unlink();result['retired_recovery_files']+=1
        except (OSError,ValueError,KeyError,TypeError):result['errors'].append(['recovery_metadata'])
    # Only disposable build cache and dangling images over 45 days old.
    run(['docker','builder','prune','--force','--filter','until=1080h'])
    run(['docker','image','prune','--force','--filter','until=1080h'])
    run(['docker','compose','exec','-T','api','python','-c','from app.services.disk_cleanup import cleanup_artifacts; print(cleanup_artifacts(delete=True))'])
    # Old update transcripts can accumulate; active/current requests are untouched.
    queue=app/'.web-update'
    for path in queue.glob('update-*.log'):
        try:
            info=path.lstat()
            if re.fullmatch(r'update-[a-f0-9-]{36}\.log',path.name) and stat.S_ISREG(info.st_mode) and info.st_nlink==1 and max(info.st_ctime,info.st_mtime)<now-INTERVAL:path.unlink()
        except OSError:pass
    # Retry next daily timer on an error instead of suppressing failures for 45 days.
    if not result['errors']:atomic(stamp,result)
    atomic(private/'maintenance-last-result.json',result)
    return result


def main():
    app=Path(sys.argv[1]).resolve();queue=app/'.web-update';queue.mkdir(mode=0o700,exist_ok=True)
    private=Path('/var/lib/dbot-web-updater')/hashlib.sha256(str(app).encode()).hexdigest()[:20]
    private.mkdir(mode=0o700,parents=True,exist_ok=True)
    if (queue/'request.json').exists():return
    lock=os.fdopen(os.open(private/'operation.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600),'r+')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:return
    def run(args):return subprocess.run(args,cwd=app,check=True,timeout=600,stdout=subprocess.DEVNULL)
    print(json.dumps(maintain(app,private,run)))


if __name__=='__main__':main()
