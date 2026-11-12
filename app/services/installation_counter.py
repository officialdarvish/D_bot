"""Opt-in anonymous installation heartbeat and cached public aggregate."""
import os
import re
import secrets
import time
from pathlib import Path
from urllib.parse import urlsplit
import httpx

_cache=(0.0,None)
def endpoint():
    raw=os.environ.get('DBOT_COUNTER_URL','').strip().rstrip('/')
    parsed=urlsplit(raw)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:return ''
    return raw

def installation_token():
    root=Path(os.environ.get('DBOT_INSTALLATION_DIR','/var/lib/dbot/installation'))
    root.mkdir(mode=0o700,parents=True,exist_ok=True)
    path=root/'token'
    try:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    except FileExistsError:pass
    else:
        with os.fdopen(fd,'w') as stream:stream.write(secrets.token_hex(32))
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd) as stream:value=stream.read(65)
    if not re.fullmatch(r'[a-f0-9]{64}',value):raise ValueError('Invalid installation token')
    return value

async def heartbeat():
    if os.environ.get('DBOT_COUNTER_ENABLED','').lower() not in {'1','true','yes'} or not endpoint():return
    try:
        token=installation_token()
        async with httpx.AsyncClient(timeout=8,follow_redirects=False) as client:
            await client.post(endpoint()+'/heartbeat',content=token,headers={'Content-Type':'text/plain'})
    except Exception:
        # Optional statistics must never interrupt the bot or notify Telegram.
        pass

async def aggregate():
    global _cache
    now=time.monotonic()
    if now-_cache[0]<60:return _cache[1]
    result=None
    if endpoint():
        try:
            async with httpx.AsyncClient(timeout=5,follow_redirects=False) as client:
                response=await client.get(endpoint()+'/count');response.raise_for_status()
                if len(response.content)>1024:raise ValueError('Invalid response')
                value=response.json().get('count')
                if type(value) is int and 0<=value<=10**9:result=value
        except Exception:pass
    _cache=(now,result)
    return result
