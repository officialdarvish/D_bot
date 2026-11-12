"""Official update manifest plus a fixed host-side job queue."""
import asyncio,json,os,re,time,uuid,stat,tempfile
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[2]
QUEUE=Path(os.environ.get('DBOT_UPDATE_DIR','/var/lib/dbot/update'))
REPO='officialdarvish/D_bot'
_cache=None
_lock=asyncio.Lock()
def manifest(value):
    if not isinstance(value,dict) or value.get('schema')!=1 or value.get('channel')!='main':raise ValueError('Invalid update manifest')
    if not re.fullmatch(r'\d+\.\d+\.\d+',str(value.get('version',''))):raise ValueError('Invalid version')
    if type(value.get('build')) is not int or not 0<value['build']<2**53:raise ValueError('Invalid build')
    return {k:value[k] for k in ('schema','version','build','channel')}|{'notes':{k:str((value.get('notes') or {}).get(k,''))[:2000] for k in ('fa','en')}}
def local_manifest():return manifest(json.loads((ROOT/'update.json').read_text()))
def host_connection():
    """Report the host worker independently of GitHub update availability."""
    result={'ready':False,'reason':'worker_missing','bootstrap_command':'sudo dbot update'}
    try:
        modified=(QUEUE/'ready').stat().st_mtime
        result['last_seen']=modified
        if not 0<=time.time()-modified<60:
            result['reason']='worker_offline';return result
        if not os.access(QUEUE,os.W_OK|os.X_OK):
            result['reason']='queue_not_writable';return result
        return {**result,'ready':True,'reason':'connected'}
    except OSError:return result

def host_ready():return host_connection()['ready']

async def check(force=False):
    global _cache
    async with _lock:
        if _cache and not force and time.monotonic()-_cache[0]<300:return {**_cache[1],'host_ready':host_ready(),'host':host_connection()}
        local=local_manifest();data={'ok':True,'installed':local,'available':False,'host_ready':host_ready(),'host':host_connection()}
        try:
            async with httpx.AsyncClient(timeout=10,follow_redirects=False) as client:
                ref=await client.get(f'https://api.github.com/repos/{REPO}/git/ref/heads/main');ref.raise_for_status();sha=ref.json()['object']['sha']
                if not re.fullmatch('[0-9a-f]{40}',sha):raise ValueError('Invalid commit')
                r=await client.get(f'https://raw.githubusercontent.com/{REPO}/{sha}/update.json');r.raise_for_status();remote=manifest(r.json())
            def rank(m):return tuple(map(int,m['version'].split('.')))+(m['build'],)
            data.update(latest=remote,commit=sha,available=rank(remote)>rank(local))
        except (httpx.HTTPError,ValueError,KeyError,TypeError):data['check_error']='Update check unavailable / بررسی آپدیت در دسترس نیست'
        _cache=(time.monotonic(),data);return data
def queue_json(path):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'r') as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):raise ValueError('Invalid queue file')
        value=source.read(8193)
        if len(value)>8192:raise ValueError('Queue file too large')
        result=json.loads(value)
        if not isinstance(result,dict):raise ValueError('Invalid queue object')
        return result

def status():
    try:
        data=queue_json(QUEUE/'status.json')
        current={k:data.get(k) for k in ('id','state','started_at','finished_at','error','backup')}
    except (OSError,ValueError):current={'state':'idle'}
    try:
        pending=queue_json(QUEUE/'request.json')
        if pending.get('id') and pending['id']!=current.get('id'):
            return {'id':pending['id'],'state':'queued'}
    except (OSError,ValueError):pass
    return current

async def enqueue(expected):
    if not re.fullmatch('[0-9a-f]{40}',expected or ''):raise ValueError('Invalid update commit / شناسه آپدیت نامعتبر است')
    data=await check(force=True)
    if not data['host_ready']:raise ValueError('VPS updater is offline. Run sudo dbot update once on this VPS / اجراکننده VPS آماده نیست؛ یک‌بار sudo dbot update را روی همین سرور اجرا کنید')
    if not data.get('available') or data.get('commit')!=expected:raise ValueError('Update changed; check again / دوباره بررسی کنید')
    job={'id':str(uuid.uuid4()),'commit':expected,'build':data['latest']['build'],'version':data['latest']['version']}
    name=None
    try:
        # Publish the complete request atomically. The host must never see partial
        # JSON or lose a second request while building/restarting the containers.
        fd,name=tempfile.mkstemp(prefix='.request-',dir=QUEUE)
        with os.fdopen(fd,'w') as out:json.dump(job,out);out.flush();os.fsync(out.fileno())
        os.link(name,QUEUE/'request.json',follow_symlinks=False)
    except FileExistsError:raise ValueError('An update is already queued / آپدیت در صف است') from None
    except OSError:raise ValueError('Cannot send the update to the VPS worker. Check the shared update directory and service / ارسال آپدیت به VPS انجام نشد؛ سرویس و پوشه مشترک آپدیت را بررسی کنید') from None
    finally:
        if name:Path(name).unlink(missing_ok=True)
    return {**job,'state':'queued'}
