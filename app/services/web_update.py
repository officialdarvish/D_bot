"""Official update manifest plus a fixed host-side job queue."""
import asyncio,json,os,re,time,uuid
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
def host_ready():
    try:return time.time()-(QUEUE/'ready').stat().st_mtime<60
    except OSError:return False
async def check(force=False):
    global _cache
    async with _lock:
        if _cache and not force and time.monotonic()-_cache[0]<300:return {**_cache[1],'host_ready':host_ready()}
        local=local_manifest();data={'ok':True,'installed':local,'available':False,'host_ready':host_ready()}
        try:
            async with httpx.AsyncClient(timeout=10,follow_redirects=False) as client:
                ref=await client.get(f'https://api.github.com/repos/{REPO}/git/ref/heads/main');ref.raise_for_status();sha=ref.json()['object']['sha']
                if not re.fullmatch('[0-9a-f]{40}',sha):raise ValueError('Invalid commit')
                r=await client.get(f'https://raw.githubusercontent.com/{REPO}/{sha}/update.json');r.raise_for_status();remote=manifest(r.json())
            def rank(m):return tuple(map(int,m['version'].split('.')))+(m['build'],)
            data.update(latest=remote,commit=sha,available=rank(remote)>rank(local))
        except (httpx.HTTPError,ValueError,KeyError,TypeError):data['check_error']='Update check unavailable / بررسی آپدیت در دسترس نیست'
        _cache=(time.monotonic(),data);return data
def status():
    try:
        data=json.loads((QUEUE/'status.json').read_text());return {k:data.get(k) for k in ('id','state','started_at','finished_at','error','backup')}
    except (OSError,ValueError):return {'state':'idle'}
async def enqueue(expected):
    data=await check(force=True)
    if not data['host_ready']:raise ValueError('Run dbot update once on the VPS / یک‌بار dbot update اجرا کنید')
    if not data.get('available') or data.get('commit')!=expected:raise ValueError('Update changed; check again / دوباره بررسی کنید')
    job={'id':str(uuid.uuid4()),'commit':expected,'build':data['latest']['build'],'version':data['latest']['version']}
    try:fd=os.open(QUEUE/'request.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    except FileExistsError:raise ValueError('An update is already queued / آپدیت در صف است')
    with os.fdopen(fd,'w') as f:json.dump(job,f);f.flush();os.fsync(f.fileno())
    return job
