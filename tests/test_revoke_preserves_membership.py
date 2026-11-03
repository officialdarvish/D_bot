"""Rotations invalidate old credentials without ever changing membership."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from app.xui.client import XUIClient
from app.services.pasarguard_service import PasarGuardService
from test_miniapp_panel_actions import controlled,send,panels,native,client


@pytest.mark.parametrize('alias',['uuid','clientUuid','client_uuid'])
async def test_sanaei_rotation_uses_one_credential_update_without_membership_parameters(alias):
 api=object.__new__(XUIClient)
 state={'email':'client','id':407,alias:'old-uuid','sub_id':'old-sub','subscription_id':'old-sub',
        'totalGB':100,'expiryTime':9999,'enable':False,'inboundIds':[12,24]}
 async def read(email):return {'client':api._normalize_client_record(deepcopy(state)),'inbound_ids':[12,24]}
 calls=[]
 async def request(method,path,**kwargs):
  calls.append((method,path,deepcopy(kwargs)))
  assert method=='POST' and path=='/panel/api/clients/update/client'
  data=kwargs['json'];assert not {'inboundIds','inbound_ids','inbounds','inboundId','inbound_id'} & data.keys()
  state.update({k:v for k,v in data.items() if k!='id'});state[alias]=data['id'];state['sub_id']=state['subscription_id']=data['subId'];return {'success':True}
 api.find_client=read;api._client_api_request=request
 result=await api.rotate_client_uuid('client')
 assert len(calls)==1
 assert state[alias]!='old-uuid' and state['id']==407
 assert state['subId']==state['sub_id']==state['subscription_id']!='old-sub'
 assert state['inboundIds']==[12,24] and state['totalGB']==100 and state['expiryTime']==9999 and state['enable'] is False
 assert result['client']['id']==state[alias]


async def test_sanaei_detects_membership_change_without_attempting_attach_or_detach():
 api=object.__new__(XUIClient)
 before={'client':{'id':'old','subId':'old-sub'},'inbound_ids':[1,2]}
 after={'client':{'id':'new','subId':'new-sub'},'inbound_ids':[1,3]}
 api.find_client=AsyncMock(side_effect=[before,after]);api._update_client=AsyncMock()
 api.attach_client=AsyncMock();api.detach_client=AsyncMock()
 with pytest.raises(RuntimeError,match='membership'):await api.rotate_client_uuid('client')
 api.attach_client.assert_not_awaited();api.detach_client.assert_not_awaited()


def pg_state():
 return dict(id=71,username='client',subscription_url='https://sub.example/old',group_ids=[3,8],
             proxy_settings={'vless':{'id':'old-vless'},'vmess':{'id':'old-vmess'}},data_limit=900,used_traffic=200,expire='2030-01-01',status='disabled')


async def test_pasarguard_revoke_reads_back_both_uuids_and_token_with_no_group_write():
 api=PasarGuardService();before=pg_state();after=deepcopy(before)
 after.update(subscription_url='https://sub.example/new',proxy_settings={'vless':{'id':'new-vless'},'vmess':{'id':'new-vmess'}})
 api.get_user=AsyncMock(side_effect=[before,after]);api._request=AsyncMock(return_value={'subscription_url':'https://sub.example/stale'})
 result=await api.revoke_subscription(SimpleNamespace(panel_url='https://panel.example'),'client')
 api._request.assert_awaited_once_with(SimpleNamespace(panel_url='https://panel.example'),'POST','/api/user/by-username/client/revoke_sub')
 assert result['uuid']=='new-vless' and result['sub_link']=='https://sub.example/new' and result['id']==71
 assert all(result[k]==before[k] for k in ('group_ids','data_limit','used_traffic','expire','status'))


@pytest.mark.parametrize('bad',['vless','vmess','token','groups','identity','missing_readback'])
async def test_pasarguard_never_reports_partial_rotation_as_success(bad):
 api=PasarGuardService();before=pg_state();after=deepcopy(before)
 after.update(subscription_url='https://sub.example/new',proxy_settings={'vless':{'id':'new-vless'},'vmess':{'id':'new-vmess'}})
 if bad in {'vless','vmess'}:after['proxy_settings'][bad]['id']=before['proxy_settings'][bad]['id']
 if bad=='token':after['subscription_url']=before['subscription_url']
 if bad=='groups':after['group_ids']=[3,9]
 if bad=='identity':after['id']=72
 if bad=='missing_readback':after=None
 api.get_user=AsyncMock(side_effect=[before,after]);api._request=AsyncMock(return_value={'subscription_url':'https://sub.example/new'})
 with pytest.raises(RuntimeError):await api.revoke_subscription(SimpleNamespace(panel_url='https://panel.example'),'client')
 assert api._request.await_count==1 # No repair PUT, delete/recreate or group assignment.


def test_panel_retry_rejects_token_only_rotation(controlled,monkeypatch):
 f=controlled;state=f[3]
 async def partial(*a,**k):
  state['subscription_url']='https://example.com/sub/token-only'
  raise TimeoutError('ack lost')
 monkeypatch.setattr(PasarGuardService,'revoke_subscription',partial)
 import uuid
 key=str(uuid.uuid4())
 assert send(f,'revoke',key).json()['status']=='review'
 assert send(f,'revoke',key).json()['status']=='review' # UUID is still old.
 assert state['group_ids']==[7,9]


@pytest.mark.parametrize('reseller',[False,True])
@pytest.mark.parametrize('surface',['bot','miniapp'])
def test_pasarguard_public_and_reseller_controls_persist_native_credentials(native,monkeypatch,reseller,surface):
 import asyncio
 from app.api import miniapp_actions as actions
 from app.bot.handlers.public import my_services, reseller as reseller_bot
 from app.services.xui_service import XuiService
 from app.database.models import Server,ClientService,User
 _,sessions,real,_,_,_=native
 rotated=AsyncMock(return_value={'uuid':'rotated-protocol-uuid','sub_link':'https://sub.example/new'})
 sanaei=AsyncMock(side_effect=AssertionError('PasarGuard routed to Sanaei'))
 monkeypatch.setattr(PasarGuardService,'revoke_subscription',rotated)
 monkeypatch.setattr(PasarGuardService,'get_user',AsyncMock(return_value={'subscription_url':'https://sub.example/new'}))
 monkeypatch.setattr(XuiService,'revoke_and_new_link',sanaei)
 monkeypatch.setattr(my_services,'SessionLocal',sessions)
 monkeypatch.setattr(reseller_bot,'SessionLocal',sessions)
 monkeypatch.setattr(reseller_bot,'send_service_card',AsyncMock())
 monkeypatch.setattr(reseller_bot,'edit_or_answer',AsyncMock())
 async def run():
  async with sessions() as s:
   server=await s.get(Server,1);server.server_type='pasarguard'
   svc=await s.get(ClientService,1);svc.reseller_id=1 if reseller else None
   old_quota=svc.total_bytes;old_usage=svc.used_bytes;old_expiry=svc.expires_at
   await s.commit()
   if surface=='miniapp':
    user=await s.get(User,1)
    await actions.configuration_control(s,user,1,'revoke',reseller=reseller)
  if surface=='bot':
   cb=SimpleNamespace(data=('reseller:revoke:1' if reseller else 'svc:revoke:1'),from_user=SimpleNamespace(id=11),
       message=SimpleNamespace(bot=real) if reseller else None,answer=AsyncMock())
   if reseller:await reseller_bot.reseller_revoke(cb)
   else:await my_services.revoke_service(cb)
  async with sessions() as s:
   svc=await s.get(ClientService,1)
   assert svc.xui_uuid=='rotated-protocol-uuid' and svc.sub_link=='https://sub.example/new'
   assert (svc.total_bytes,svc.used_bytes,svc.expires_at)==(old_quota,old_usage,old_expiry)
 asyncio.run(run())
 rotated.assert_awaited_once();sanaei.assert_not_awaited()
