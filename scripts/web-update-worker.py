#!/usr/bin/env python3
"""Host worker; no Docker socket exposed to the web panel."""
import fcntl,json,os,re,subprocess,sys,time,threading
from pathlib import Path
APP=Path(sys.argv[1]).resolve();QUEUE=APP/'.web-update';QUEUE.mkdir(mode=0o700,exist_ok=True)
lock=(QUEUE/'worker.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
def heartbeat():
    while True:
        (QUEUE/'ready').touch(mode=0o644);time.sleep(10)
threading.Thread(target=heartbeat,daemon=True).start()
def run(args,**kwargs):return subprocess.run(args,cwd=APP,check=True,timeout=kwargs.pop('timeout',1800),**kwargs)
def state(job,status,**extra):
    tmp=QUEUE/'status.tmp';tmp.write_text(json.dumps({**job,'state':status,**extra}));os.chmod(tmp,0o600);tmp.replace(QUEUE/'status.json')
def healthy():
    for _ in range(60):
        try:
            run(['docker','compose','exec','-T','api','curl','-fsS','http://localhost:8000/health'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=15);return True
        except subprocess.SubprocessError:time.sleep(2)
    return False
while True:
    request=QUEUE/'request.json'
    if not request.exists():time.sleep(3);continue
    job={};previous=None;switched=False;started=time.time()
    try:
        job=json.loads(request.read_text());sha=job['commit']
        if set(job)!={'id','commit','build','version'} or not re.fullmatch('[0-9a-f]{40}',sha):raise ValueError('Invalid request')
        state(job,'checking',started_at=started)
        run(['git','fetch','https://github.com/officialdarvish/D_bot.git','main'])
        latest=run(['git','rev-parse','FETCH_HEAD'],capture_output=True,text=True).stdout.strip()
        if latest!=sha:raise ValueError('Official main changed; check again')
        remote=json.loads(run(['git','show',sha+':update.json'],capture_output=True,text=True).stdout)
        if remote.get('schema')!=1 or remote.get('channel')!='main' or remote.get('build')!=job['build'] or remote.get('version')!=job['version']:raise ValueError('Manifest mismatch')
        previous=run(['git','rev-parse','HEAD'],capture_output=True,text=True).stdout.strip()
        if run(['git','status','--porcelain','--untracked-files=no'],capture_output=True,text=True).stdout.strip():raise ValueError('Tracked local edits exist; update manually')
        backup=QUEUE/('database-'+str(int(started))+'.sql')
        state(job,'backing_up',started_at=started)
        with backup.open('wb') as out:
            os.chmod(backup,0o600);run(['docker','compose','exec','-T','db','sh','-c','pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"'],stdout=out)
        run(['git','checkout','--detach',sha]);switched=True
        state(job,'building',started_at=started,backup=backup.name);run(['docker','compose','build'],timeout=3600)
        state(job,'restarting',started_at=started,backup=backup.name);run(['docker','compose','up','-d'])
        if not healthy():raise ValueError('New API health check failed')
        state(job,'completed',started_at=started,finished_at=time.time(),backup=backup.name)
    except Exception:
        # Raw command output stays in the host journal, not in a customer API.
        import traceback;traceback.print_exc()
        recovered=False
        if switched and previous:
            try:
                run(['git','checkout','--detach',previous]);run(['docker','compose','up','-d','--build'],timeout=3600);recovered=healthy()
            except Exception:traceback.print_exc()
        state(job,'failed',started_at=started,finished_at=time.time(),error='Update failed; inspect host journal. Previous source recovery: '+str(recovered))
    finally:request.unlink(missing_ok=True)
