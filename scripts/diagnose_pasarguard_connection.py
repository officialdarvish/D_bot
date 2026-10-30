#!/usr/bin/env python3
"""Unauthenticated, read-only connectivity check from the D Bot container."""
import argparse
import asyncio
import json
import os
import socket
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
import httpx

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))


def origin(url):
    parts=urlsplit(url)
    host=parts.hostname or ''
    if ':' in host:host=f'[{host}]'
    if parts.port:host+=f':{parts.port}'
    return urlunsplit((parts.scheme,host,'','',''))


async def diagnose(server,timeout=8):
    from app.services.pasarguard_service import PasarGuardService
    results=[]
    # No decryption, API key or authentication headers are used here.
    async with httpx.AsyncClient(timeout=timeout,follow_redirects=False,verify=True) as client:
        for base in PasarGuardService._candidate_api_bases(server):
            parts=urlsplit(base)
            base=origin(base)+parts.path.rstrip('/')
            port=parts.port or (443 if parts.scheme=='https' else 80)
            result={'origin':origin(base),'dns':[]}
            try:
                records=await asyncio.wait_for(asyncio.to_thread(socket.getaddrinfo,parts.hostname,port,type=socket.SOCK_STREAM),timeout=timeout)
                result['dns']=sorted({row[4][0] for row in records})
            except (OSError,asyncio.TimeoutError) as exc:
                result['dns_error']=type(exc).__name__
            try:
                response=await client.get(base+'/api/admin')
                result.update(http_status=response.status_code,content_type=response.headers.get('content-type',''),connected=True)
            except httpx.HTTPError as exc:
                result.update(connected=False,error=type(exc).__name__)
            results.append(result)
    return {'checks':results,'proxy_environment_present':[key for key in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY','http_proxy','https_proxy','all_proxy','no_proxy') if os.environ.get(key)],
        'note':'No panel passwords or API tokens were used. An HTTP response proves reachability only; 401/403 may be API authentication or a proxy/WAF response. DNS is resolved inside this container.'}


async def run(args):
    from app.database.models import PasarGuardPanelOrder,Server
    from app.database.session import SessionLocal,engine
    try:
        async with SessionLocal() as s:
            if args.order_id:
                order=await s.get(PasarGuardPanelOrder,args.order_id)
                if not order:raise ValueError('Panel order not found')
                sid=order.server_id
            else:sid=args.server_id
            server=await s.get(Server,sid)
            if not server or server.server_type!='pasarguard':raise ValueError('PasarGuard server not found')
        result=await diagnose(server,args.timeout)
        result['server_id']=server.id
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0 if any(c.get('connected') for c in result['checks']) else 1
    finally:await engine.dispose()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    target=parser.add_mutually_exclusive_group(required=True)
    target.add_argument('--order-id',type=int)
    target.add_argument('--server-id',type=int)
    parser.add_argument('--timeout',type=float,default=8)
    args=parser.parse_args()
    if not 0<args.timeout<=30:parser.error('--timeout must be between 0 and 30 seconds')
    try:return asyncio.run(run(args))
    except ValueError as exc:
        print(str(exc),file=sys.stderr);return 2

if __name__=='__main__':raise SystemExit(main())
