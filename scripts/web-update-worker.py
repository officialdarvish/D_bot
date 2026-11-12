#!/usr/bin/env python3
"""Host worker; no Docker socket exposed to the web panel."""
import fcntl,json,os,re,subprocess,sys,time,threading,stat,tempfile,hashlib
from pathlib import Path
APP=None
QUEUE=None
JOB_LOG=None
PRIVATE=None

def configure(app,private_root=None):
    global APP,QUEUE,PRIVATE
    APP=Path(app).resolve();QUEUE=APP/'.web-update'
    QUEUE.mkdir(mode=0o700,exist_ok=True)
    PRIVATE=Path(private_root) if private_root else Path('/var/lib/dbot-web-updater')/hashlib.sha256(str(APP).encode()).hexdigest()[:20]
    PRIVATE.mkdir(mode=0o700,parents=True,exist_ok=True)
    os.chmod(PRIVATE,0o700)

def read_json(path):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'r') as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):raise ValueError('Not a regular queue file')
        data=source.read(8193)
        if len(data)>8192:raise ValueError('Queue file too large')
        return json.loads(data)
def write_json(path,data):
    fd,name=tempfile.mkstemp(prefix='.worker-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as out:
            json.dump(data,out);out.flush();os.fsync(out.fileno())
        os.replace(name,path)
    finally:Path(name).unlink(missing_ok=True)
def heartbeat():
    while True:
        fd=os.open(QUEUE/'ready',os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW,0o644)
        try:os.utime(fd,None)
        finally:os.close(fd)
        time.sleep(10)
def append_job_log(payload):
    if JOB_LOG is None:return
    try:
        fd=os.open(JOB_LOG,os.O_WRONLY|os.O_APPEND|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(fd,'ab') as log:
            if stat.S_ISREG(os.fstat(log.fileno()).st_mode):log.write(payload)
    except OSError:pass

def run(args,**kwargs):
    env={**os.environ,'COMPOSE_PARALLEL_LIMIT':'1'}
    timeout=kwargs.pop('timeout',1800)
    if JOB_LOG is None or kwargs.get('capture_output'):
        return subprocess.run(args,cwd=APP,check=True,timeout=timeout,env=env,**kwargs)
    # Keep command output even if journald is empty; drain to disk, not RAM.
    with tempfile.TemporaryFile(mode='w+b') as output:
        kwargs.setdefault('stdout',output);kwargs.setdefault('stderr',output)
        try:return subprocess.run(args,cwd=APP,check=True,timeout=timeout,env=env,**kwargs)
        finally:
            output.seek(0,2);length=output.tell();output.seek(max(0,length-65536))
            append_job_log(('\n$ '+str(args[0])+' '+str(args[1] if len(args)>1 else '')+'\n').encode()+output.read(65536))

def failure_reason(exc):
    # Only static reason codes reach the web panel; raw build output stays local.
    text=''
    if JOB_LOG:
        try:
            fd=os.open(JOB_LOG,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
            with os.fdopen(fd,'rb') as source:
                if stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                    source.seek(0,2);size=source.tell();source.seek(max(0,size-65536));text=source.read(65536).decode('utf8','replace').lower()
        except OSError:pass
    if getattr(exc,'returncode',None)==137 or any(t in text for t in ('out of memory','cannot allocate memory','heap limit')):return 'possible_memory_pressure','Memory pressure or process termination suspected / احتمال کمبود حافظه یا متوقف‌شدن پردازش'
    if 'no space left on device' in text:return 'disk_full','VPS disk is full / فضای دیسک VPS پر است'
    if any(t in text for t in ('could not resolve host','temporary failure in name resolution')):return 'dns_failure','VPS DNS lookup failed / ترجمه دامنه روی VPS ناموفق بود'
    if any(t in text for t in ('connection timed out','failed to connect','tls handshake timeout')):return 'network_failure','VPS connection to update source failed / اتصال VPS به منبع آپدیت ناموفق بود'
    return 'host_command_failed','Host command failed / اجرای فرمان میزبان ناموفق بود'

def state(job,status,**extra):
    write_json(QUEUE/'status.json',{**job,'state':status,**extra})
def healthy(expected=None):
    for _ in range(60):
        try:
            result=run(['docker','compose','exec','-T','api','curl','-fsS','--max-time','10','http://localhost:8000/health'],capture_output=True,text=True,timeout=15)
            if expected is None:return True
            payload=json.loads(result.stdout)
            if payload.get('version')==expected['version'] and payload.get('build')==expected['build']:return True
        except (subprocess.SubprocessError,ValueError,TypeError):pass
        time.sleep(2)
    return False
def write_env(content):
    fd,name=tempfile.mkstemp(prefix='.runtime-env-',dir=APP)
    try:
        with os.fdopen(fd,'w') as out:out.write(content);out.flush();os.fsync(out.fileno())
        os.replace(name,APP/'.env')
    finally:Path(name).unlink(missing_ok=True)
def apply_runtime():
    desired=QUEUE/'desired-runtime.json'
    if not desired.exists():return
    value=read_json(desired)
    if set(value)!={'id','xray'} or type(value['xray']) is not bool or not re.fullmatch('[0-9a-f]{32}',str(value['id'])):raise ValueError('Invalid runtime selection')
    applied=QUEUE/'applied-runtime.json'
    if applied.exists() and read_json(applied).get('id')==value['id']:return
    old=(APP/'.env').read_text();source='image' if value['xray'] else 'disabled'
    line='XRAY_SOURCE='+source
    existing=re.search(r'^XRAY_SOURCE=(.*)$',old,re.M)
    changed=not existing or existing.group(1)!=source
    state({'id':value['id'],'kind':'runtime'},'building')
    try:
        if changed:
            content=re.sub(r'^XRAY_SOURCE=.*$',line,old,flags=re.M) if existing else old.rstrip()+'\n'+line+'\n'
            write_env(content)
            run(['docker','compose','build'],timeout=3600);run(['docker','compose','up','-d'])
            if not healthy():raise RuntimeError('Optional runtime health check failed')
        write_json(applied,value)
        state({'id':value['id'],'kind':'runtime'},'completed',finished_at=time.time())
    except Exception:
        write_env(old)
        try:run(['docker','compose','up','-d','--build'],timeout=3600)
        finally:
            # Do not rebuild endlessly after a failed selection; the admin can submit again.
            write_json(applied,value)
            state({'id':value['id'],'kind':'runtime'},'failed',error='Optional runtime failed; inspect the host journal.',finished_at=time.time())
        raise

def snapshot_images(job):
    images={}
    for service in ('api','bot'):
        container=run(['docker','compose','ps','-q',service],capture_output=True,text=True).stdout.strip()
        if not re.fullmatch('[0-9a-f]{12,64}',container):raise ValueError('Running container unavailable')
        image=run(['docker','inspect','--format','{{.Image}}',container],capture_output=True,text=True).stdout.strip()
        if not re.fullmatch('sha256:[0-9a-f]{64}',image):raise ValueError('Running image unavailable')
        tag='dbot-recovery-'+service+':'+job['id'].replace('-','')
        run(['docker','image','tag',image,tag]);images[service]={'image':tag,'pull_policy':'never'}
    path=PRIVATE/('recovery-'+job['id']+'.json')
    write_json(path,{'services':images})
    return path


def process_update():
    """Back up, build once and recover using retained images, never rebuilding."""
    global JOB_LOG
    request=QUEUE/'request.json'
    job={};previous=None;switched=False;started=time.time();refresh=False;phase='request';recovery=None
    def progress(value,**extra):
        nonlocal phase
        phase=value;state(job,value,started_at=started,**extra)
    try:
        incoming=read_json(request)
        if not isinstance(incoming,dict) or set(incoming)!={'id','commit','build','version'} or not re.fullmatch('[0-9a-f]{40}',str(incoming.get('commit',''))):raise ValueError('Invalid request')
        if not re.fullmatch('[0-9a-f-]{36}',str(incoming.get('id',''))) or type(incoming.get('build')) is not int or incoming['build']<1 or not re.fullmatch(r'\d+\.\d+\.\d+',str(incoming.get('version',''))):raise ValueError('Invalid update identity')
        job=incoming;sha=job['commit'];candidate=QUEUE/('update-'+job['id']+'.log')
        fd=os.open(candidate,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);os.close(fd);JOB_LOG=candidate
        progress('checking')
        run(['git','fetch','https://github.com/officialdarvish/D_bot.git','main'])
        latest=run(['git','rev-parse','FETCH_HEAD'],capture_output=True,text=True).stdout.strip()
        if latest!=sha:raise ValueError('Official main changed; check again')
        remote=json.loads(run(['git','show',sha+':update.json'],capture_output=True,text=True).stdout)
        if remote.get('schema')!=1 or remote.get('channel')!='main' or remote.get('build')!=job['build'] or remote.get('version')!=job['version']:raise ValueError('Manifest mismatch')
        previous=run(['git','rev-parse','HEAD'],capture_output=True,text=True).stdout.strip()
        if run(['git','-c','core.fileMode=false','status','--porcelain','--untracked-files=no'],capture_output=True,text=True).stdout.strip():raise ValueError('Tracked local edits exist; update manually')
        progress('preparing_recovery')
        recovery=snapshot_images(job)
        backup=QUEUE/('database-'+job['id']+'.sql')
        progress('backing_up')
        with os.fdopen(os.open(backup,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'wb') as out:
            run(['docker','compose','exec','-T','db','sh','-c','pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"'],stdout=out)
        progress('switching_source',backup=backup.name);switched=True
        run(['git','-c','core.fileMode=false','checkout','--detach',sha])
        progress('building',backup=backup.name);run(['docker','compose','build'],timeout=3600)
        progress('restarting',backup=backup.name);run(['docker','compose','up','-d','--no-build','--pull','never'])
        if not healthy(job):raise ValueError('New API health check failed')
        progress('refreshing_agent',backup=backup.name)
        installer=APP/'scripts/install-web-updater.sh'
        if installer.is_file():run(['bash',str(installer),'--defer-restart'],timeout=60);refresh=True
        state(job,'completed',started_at=started,finished_at=time.time(),backup=backup.name)
    except Exception as exc:
        import traceback;traceback.print_exc()
        append_job_log(traceback.format_exc().encode())
        recovered=None
        if switched and previous:
            try:
                run(['git','-c','core.fileMode=false','checkout','--detach',previous])
                if recovery is None:raise ValueError('No retained recovery images')
                run(['docker','compose','-f','docker-compose.yml','-f',str(recovery),'up','-d','--no-build','--pull','never'])
                recovered=healthy()
            except Exception:
                traceback.print_exc();recovered=False
                append_job_log(traceback.format_exc().encode())
        known={'Official main changed; check again':'Official main changed; check again / نسخه گیت‌هاب تغییر کرده؛ دوباره بررسی کنید',
               'Tracked local edits exist; update manually':'Tracked local edits prevent update / تغییرات محلی سورس مانع آپدیت است',
               'Manifest mismatch':'Update manifest mismatch / مشخصات نسخه مطابقت ندارد',
               'New API health check failed':'New API health check failed / نسخه جدید سالم راه‌اندازی نشد'}
        reason,detail=failure_reason(exc)
        if str(exc) in known:reason=str(exc);detail=known[str(exc)]
        code=getattr(exc,'returncode',None)
        if code is not None:detail+=' (exit '+str(code)+')'
        recovery_state='not_needed' if not switched else 'restored' if recovered else 'failed'
        recovery_text={'not_needed':'Previous containers were not replaced / کانتینرهای قبلی جایگزین نشدند',
                       'restored':'Previous images restored without rebuild / نسخه قبلی بدون ساخت مجدد بازیابی شد',
                       'failed':'Recovery could not be verified / بازیابی نسخه قبلی تأیید نشد'}[recovery_state]
        state(job,'failed',started_at=started,finished_at=time.time(),phase=phase,exit_code=code,reason=reason,
              recovery=recovery_state,log_file=JOB_LOG.name if JOB_LOG else None,
              error=detail+'; phase='+phase+'; '+recovery_text)
    finally:
        JOB_LOG=None;request.unlink(missing_ok=True)
    return refresh


def main():
    configure(sys.argv[1])
    lock=os.fdopen(os.open(QUEUE/'worker.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600),'r+')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    threading.Thread(target=heartbeat,daemon=True).start()
    while True:
        refresh=False
        with os.fdopen(os.open(PRIVATE/'operation.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600),'r+') as operation:
            fcntl.flock(operation,fcntl.LOCK_EX)
            if (QUEUE/'request.json').exists() or (QUEUE/'request.json').is_symlink():
                refresh=process_update()
            else:
                try:apply_runtime()
                except Exception:
                    import traceback;traceback.print_exc()
        if refresh:
            run(['systemctl','restart','--no-block','dbot-web-update.service'],timeout=30)
            return
        time.sleep(3)


if __name__=='__main__':main()
