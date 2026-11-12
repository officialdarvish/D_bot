"""NX stable API v1 adapter. Template IDs map to the existing plan selection model.

Contract: https://docs.nx-panel.org/reference/api (OpenAPI /openapi.yaml).
Mutations are never retried automatically. PATCH retains unrelated fields and uses
updatedAt optimistic concurrency; ambiguous creates require attributable readback.
"""
from datetime import datetime,timedelta,timezone
import base64
import re
import secrets
import uuid
from urllib.parse import urlsplit
import httpx
from app.core.security import decrypt_text
from app.services.traffic_units import gb_to_bytes
from app.services.pasarguard_service import PasarGuardCreateUnconfirmed,PasarGuardUsernameConflict


class NxCreateUnconfirmed(PasarGuardCreateUnconfirmed):
    user_message='⏳ نتیجه ساخت اکانت NX هنوز تأیید نشده است؛ برای جلوگیری از ساخت تکراری، مدیر باید وضعیت سفارش را بررسی کند.'


class NxService:
    def __init__(self,timeout=None):self.timeout=timeout or 30

    async def _request(self,server,method,path,**kwargs):
        base=str(server.panel_url).rstrip('/')
        parts=urlsplit(base)
        if parts.scheme not in {'http','https'} or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:raise ValueError('Invalid NX base URL')
        headers={'Authorization':'Bearer '+decrypt_text(server.password_encrypted),'Accept':'application/json',**kwargs.pop('headers',{})}
        async with httpx.AsyncClient(timeout=httpx.Timeout(self.timeout,connect=8),follow_redirects=False) as client:
            response=await client.request(method,base+'/api/v1'+path,headers=headers,**kwargs)
            if response.status_code>=400:raise RuntimeError(f'NX API {method} {path.split("?")[0]} failed ({response.status_code})')
            if response.is_redirect:raise RuntimeError('NX redirects are not allowed; use the exact panel base path')
            return response.json() if response.content else {}

    async def _list(self,server,path,**filters):
        rows=[]
        for offset in range(0,100000,100):
            data=await self._request(server,'GET',path,params={**filters,'limit':100,'offset':offset})
            items=data if isinstance(data,list) else data.get('items',[])
            if not isinstance(items,list):raise RuntimeError('Invalid NX list response')
            rows.extend(items)
            if len(items)<100 or isinstance(data,dict) and offset+len(items)>=int(data.get('total',100001)):return rows
        raise RuntimeError('NX result exceeds safe paging limit')

    def normalize(self,server,data):
        if not data:return None
        used=int(data.get('up') or 0)+int(data.get('down') or 0)
        total=int(data.get('volume') or 0);expiry=int(data.get('expiry') or 0)
        enabled=bool(data.get('enable',True))
        status='disabled' if not enabled else 'expired' if expiry and expiry<=datetime.now(timezone.utc).timestamp() else 'limited' if total and used>=total else 'active'
        # subUrl is authoritative for wildcard subscription domains.
        link=data.get('subUrl') or ((str(server.subscription_url).rstrip('/')+'/'+str(data['subId'])) if server.subscription_url and data.get('subId') else (str(server.panel_url).rstrip('/')+'/sub/'+str(data['subId']) if data.get('subId') else ''))
        return {**data,'username':data.get('name'),'used_traffic':used,'data_limit':total,'total_bytes':total,'expire':expiry,'status':status,'disabled':not enabled,'hwid_limit':int(data.get('deviceLimit') or 0),'inbound_ids':data.get('templateIds') or [],'group_ids':data.get('templateIds') or [],'sub_link':link,'subscription_url':link,'uuid':(data.get('config') or {}).get('uuid') or str(data.get('id') or '')}

    async def list_groups(self,server):return await self._list(server,'/templates')
    async def list_templates(self,server):return await self.list_groups(server)
    async def probe_server(self,server):
        groups=await self.list_groups(server)
        await self._request(server,'GET','/users',params={'limit':1,'offset':0})
        return {'ok':bool(groups),'groups':groups,'templates':groups,'missing':[] if groups else ['templates'],'access':{'role_name':'NX API token','require_template':False},'api_base':'/api/v1'}
    async def test_server(self,server):
        probe=await self.probe_server(server)
        return probe['ok'],probe['groups']
    async def get_user(self,server,username):
        rows=await self._list(server,'/users',q=username)
        matches=[r for r in rows if str(r.get('name') or '').casefold()==username.casefold()]
        if len(matches)>1:raise RuntimeError('NX username is ambiguous')
        return self.normalize(server,matches[0]) if matches else None
    async def current_subscription_link(self,server,username,*responses):
        user=await self.get_user(server,username)
        if not user or not user['sub_link']:raise RuntimeError('NX subscription URL unavailable')
        return user['sub_link']

    async def create_user_on_plan(self,server,plan,username):
        if await self.get_user(server,username):raise PasarGuardUsernameConflict('NX username already exists')
        ids=[int(x) for x in (plan.inbound_ids or (server.meta or {}).get('inbound_ids') or []) if int(x)>0]
        if not ids:raise ValueError('Select an NX template first')
        marker='dbot:'+uuid.uuid4().hex
        volume=0 if getattr(plan,'is_unlimited',False) else gb_to_bytes(plan.volume_gb)
        expiry=int((datetime.now(timezone.utc)+timedelta(days=plan.duration_days)).timestamp()) if plan.duration_days else 0
        payload={'name':username,'enable':True,'desc':marker,'volume':volume,'expiry':expiry,'deviceLimit':int(getattr(plan,'hwid_limit',0) or 0),'allTemplates':False,'templateIds':ids}
        try:data=await self._request(server,'POST','/users',json=payload,headers={'Idempotency-Key':marker})
        except httpx.TransportError as exc:
            try:
                found=await self.get_user(server,username)
                if found and found.get('desc')==marker and found['data_limit']==volume and set(found['inbound_ids'])==set(ids):return found
            except Exception:pass
            raise NxCreateUnconfirmed(exc) from exc
        result=self.normalize(server,data)
        if not result or result.get('name')!=username or result['data_limit']!=volume or set(result['inbound_ids'])!=set(ids):
            raise NxCreateUnconfirmed(httpx.ReadError('NX create readback mismatch'))
        return result

    async def _patch(self,server,user,payload):
        if not user:raise RuntimeError('NX user not found')
        data=await self._request(server,'PATCH',f'/users/{int(user["id"])}',json={**payload,'version':int(user['updatedAt'])})
        return self.normalize(server,data)

    async def update_user(self,server,username,*,data_limit_bytes=None,expire_at=None,expire_days=None,group_ids=None,hwid_limit=None,status='active'):
        user=await self.get_user(server,username);payload={}
        if data_limit_bytes is not None:payload['volume']=max(0,int(data_limit_bytes))
        if expire_at is not None:payload['expiry']=int(expire_at.replace(tzinfo=timezone.utc).timestamp() if expire_at.tzinfo is None else expire_at.timestamp())
        elif expire_days is not None:payload['expiry']=int((datetime.now(timezone.utc)+timedelta(days=expire_days)).timestamp()) if expire_days else 0
        if group_ids is not None:payload.update(templateIds=[int(x) for x in group_ids],allTemplates=False)
        if hwid_limit is not None:payload['deviceLimit']=int(hwid_limit)
        if status is not None:payload['enable']=status=='active'
        return await self._patch(server,user,payload)

    async def renew_user_on_plan(self,server,plan,username):
        user=await self.get_user(server,username)
        if not user:raise RuntimeError('NX user not found')
        volume=0 if getattr(plan,'is_unlimited',False) else user['used_traffic']+gb_to_bytes(plan.volume_gb)
        expiry=int((datetime.now(timezone.utc)+timedelta(days=plan.duration_days)).timestamp()) if plan.duration_days else 0
        return await self._patch(server,user,{'volume':volume,'expiry':expiry,'duration':0,'enable':True,'templateIds':list(plan.inbound_ids or user['inbound_ids']),'allTemplates':False,'deviceLimit':int(getattr(plan,'hwid_limit',0) or 0)})
    async def add_volume(self,server,username,add_bytes):
        user=await self.get_user(server,username)
        return await self._patch(server,user,{'volume':user['data_limit']+max(0,int(add_bytes))})
    async def add_days(self,server,username,days):
        user=await self.get_user(server,username)
        expiry=max(user['expire'],int(datetime.now(timezone.utc).timestamp()))+max(0,int(days))*86400
        return await self._patch(server,user,{'expiry':expiry})
    async def set_enabled(self,server,username,enabled):
        return await self._patch(server,await self.get_user(server,username),{'enable':bool(enabled)})
    async def delete_user(self,server,username):
        user=await self.get_user(server,username)
        if user:await self._request(server,'DELETE',f'/users/{int(user["id"])}')
    async def get_user_hwids(self,server,username):
        user=await self.get_user(server,username)
        data=await self._request(server,'GET',f'/users/{int(user["id"])}/devices')
        devices=[{**r,'deviceModel':r.get('model',''),'deviceOs':r.get('platform','')} for r in data['devices']]
        limit=int(data['limit']);used=len(devices)
        return {'limit':limit,'limit_raw':limit,'used':used,'remaining':max(0,limit-used) if limit else None,'devices':devices,'user_id':user['id']}
    async def clear_user_hwids(self,server,username):
        user=await self.get_user(server,username)
        return await self._request(server,'POST','/users/bulk/reset-devices',json={'ids':[int(user['id'])]})
    async def revoke_subscription(self,server,username):
        user=await self.get_user(server,username)
        config={**(user.get('config') or {}),'uuid':str(uuid.uuid4()),'password':secrets.token_urlsafe(24),'ss16':base64.b64encode(secrets.token_bytes(16)).decode(),'ss32':base64.b64encode(secrets.token_bytes(32)).decode()}
        result=await self._patch(server,user,{'subId':secrets.token_urlsafe(24),'config':config})
        if result['sub_link']==user['sub_link'] or (result.get('config') or {}).get('uuid')==user.get('config',{}).get('uuid'):raise RuntimeError('NX rotation not confirmed')
        return result
    async def reset_hwid_and_rotate(self,server,username):
        await self.clear_user_hwids(server,username)
        return await self.revoke_subscription(server,username)
    async def app_configs(self,server,username):
        user=await self.get_user(server,username)
        if not user:raise RuntimeError('NX user not found')
        data=await self._request(server,'GET',f'/users/{int(user["id"])}/app-configs')
        result=[]
        for row in data.get('configs',[])[:100]:
            if row.get('type') not in {'openvpn','openconnect','wireguard'} or not isinstance(row.get('content'),str):continue
            name=re.sub(r'[^A-Za-z0-9._-]','_',str(row.get('fileName') or row['type']+'.conf'))[:100].strip('.') or 'config.conf'
            if len(row['content'])>1024*1024:raise RuntimeError('NX profile too large')
            result.append({'name':str(row.get('name') or row['type'])[:150],'type':row['type'],'file_name':name,'content':row['content']})
        return result
