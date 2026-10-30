import asyncio,io,uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select,func
from PIL import Image
from test_miniapp_native_actions import native,client,H,OTHER
from test_panel_wallet_miniapp_alerts import seed
from app.api import miniapp_panels as panelapi,miniapp
from app.database.models import User,Server,PasarGuardPanelOrder,MiniAppOperation,Setting
from app.services.pasarguard_service import PasarGuardService
from app.services.pasarguard_panel_meter import PanelMeterAPI
from app.services.reseller_management import save_profile,profile
GB=1024**3

@pytest.fixture
def panels(native,monkeypatch):
 _,sessions,real,calls,*_=native;seed(sessions)
 async def setup():
  async with sessions() as s:
   p=await s.get(PasarGuardPanelOrder,1);p.password_encrypted='encrypted-child-password'
   server=await s.get(Server,2);server.meta={**server.meta,'auth_mode':'api_key','pasarguard_api_key':'owner-secret','pasarguard_allowed_group_ids':[999]};await s.commit()
 asyncio.run(setup())
 monkeypatch.setattr(panelapi,'SessionLocal',sessions)
 monkeypatch.setattr(panelapi,'report_failure',AsyncMock())
 async def identity(self,child):
  assert child.username=='PurchasedPanel' and child.password_encrypted=='encrypted-child-password'
  assert 'auth_mode' not in child.meta and 'pasarguard_api_key' not in child.meta
  return {'id':77,'username':'PurchasedPanel','role':{'is_owner':False}}
 monkeypatch.setattr(PasarGuardService,'get_admin_profile',identity)
 monkeypatch.setattr(PasarGuardService,'list_groups',AsyncMock(return_value=[{'id':5,'name':'Own group'}]))
 monkeypatch.setattr(PasarGuardService,'get_user',AsyncMock(return_value=None))
 remote=AsyncMock(return_value={'id':501,'username':'new_client','admin':{'id':77},'subscription_url':'https://example.com/sub/owned'})
 monkeypatch.setattr(PasarGuardService,'_request',remote)
 monkeypatch.setattr(PasarGuardService,'update_user',AsyncMock(return_value={'subscription_url':'https://example.com/sub/owned'}))
 monkeypatch.setattr(PanelMeterAPI,'list_own_users',AsyncMock(return_value=[]))
 delivery=AsyncMock()
 import app.bot.service_presenter as presenter
 monkeypatch.setattr(presenter,'send_service_info',delivery)
 @asynccontextmanager
 async def bot():yield real
 monkeypatch.setattr(panelapi,'telegram_bot',bot)
 app=FastAPI();app.include_router(panelapi.router)
 with TestClient(app) as c:yield c,sessions,remote,delivery

def payload(**extra):return dict(key=str(uuid.uuid4()),username='new_client',volume=3,days=30,group_ids=[5],hwid_limit=1,confirmed=True,**extra)

def test_owned_panel_create_is_native_and_idempotent(panels):
 c,sessions,remote,delivery=panels
 assert c.get('/api/miniapp/panels/1/catalog',headers=OTHER).status_code==404
 assert c.get('/api/miniapp/panels/1/catalog').status_code==401
 assert c.get('/api/miniapp/panels/1/catalog',headers=H).json()['groups']==[{'id':5,'name':'Own group'}]
 body=payload();r=c.post('/api/miniapp/panels/1/configurations',headers=H,json=body)
 assert r.status_code==200 and r.json()['status']=='done',r.text
 assert r.json()['link']=='https://example.com/sub/owned'
 assert c.post('/api/miniapp/panels/1/configurations',headers=H,json=body).json()['id']==r.json()['id']
 remote.assert_awaited_once();delivery.assert_awaited_once()
 assert remote.call_args.args[0].username=='PurchasedPanel'
 assert remote.call_args.kwargs['json']['status']=='on_hold'
 assert remote.call_args.kwargs['json']['on_hold_expire_duration']==30*86400
 assert 'expire' not in remote.call_args.kwargs['json']
 assert 'password' not in r.text

def test_volume_create_reserves_quota_exactly_once(panels):
 c,sessions,remote,delivery=panels
 async def mode():
  async with sessions() as s:
   await save_profile(s,'panels:1',{'billing_mode':'volume','available_bytes':5*GB});await s.commit()
 asyncio.run(mode());body=payload()
 r=c.post('/api/miniapp/panels/1/configurations',headers=H,json=body);assert r.json()['status']=='done',r.text
 c.post('/api/miniapp/panels/1/configurations',headers=H,json=body)
 async def check():
  async with sessions() as s:
   p=await profile(s,'panels:1');assert p['available_bytes']==2*GB and p['allocations']['panel:1:501']==3*GB
   assert (await s.get(User,1)).wallet_balance==250000
 asyncio.run(check())

def test_scope_group_confirmation_and_credit_are_enforced(panels):
 c,sessions,remote,_=panels
 b=payload();b['group_ids']=[999]
 assert c.post('/api/miniapp/panels/1/configurations',headers=H,json=b).status_code==403
 b=payload();b['confirmed']=False
 assert c.post('/api/miniapp/panels/1/configurations',headers=H,json=b).status_code==409
 async def empty():
  async with sessions() as s:
   u=await s.get(User,1);u.wallet_balance=0;await s.commit()
 asyncio.run(empty())
 assert c.post('/api/miniapp/panels/1/configurations',headers=H,json=payload()).status_code==409
 remote.assert_not_awaited()

def test_timeout_retries_only_after_confirmed_absence(panels):
 c,sessions,remote,_=panels;remote.side_effect=RuntimeError('timeout')
 b=payload();r=c.post('/api/miniapp/panels/1/configurations',headers=H,json=b)
 assert r.status_code==200 and r.json()['status']=='review' and r.json()['retryable']
 remote.side_effect=None
 assert c.post('/api/miniapp/panels/1/configurations',headers=H,json=b).json()['status']=='done'
 assert remote.await_count==2

def test_forged_child_identity_never_falls_back_to_owner(panels,monkeypatch):
 c,_,remote,_=panels
 monkeypatch.setattr(PasarGuardService,'get_admin_profile',AsyncMock(return_value={'id':1,'username':'owner','role':{'is_owner':True}}))
 assert c.post('/api/miniapp/panels/1/configurations',headers=H,json=payload()).status_code==409
 remote.assert_not_awaited()

def test_receipt_photo_is_sent_once_per_admin_even_on_upload_retry(native):
 c,sessions,real,calls,*_=native
 b=dict(key=str(uuid.uuid4()),kind='wallet_topup',amount=100000,expected_amount=100000,method='card')
 r=c.post('/api/miniapp/funding',headers=H,json=b);assert r.status_code==200,r.text
 oid=r.json()['id'];out=io.BytesIO();Image.new('RGB',(300,400),'white').save(out,'PNG')
 for _ in range(2):
  r=c.post(f'/api/miniapp/funding/{oid}/receipt',headers=H,files={'file':('r.png',out.getvalue(),'image/png')});assert r.status_code==200,r.text
 photos=[m for m in calls if type(m).__name__=='SendPhoto' and m.chat_id==99]
 edits=[m for m in calls if type(m).__name__=='EditMessageCaption' and m.chat_id==99]
 assert len(photos)==1 and len(edits)==1
 assert '100,000' in edits[0].caption and 'ID: 11' in edits[0].caption and edits[0].reply_markup

def test_card_color_is_random_once_and_persisted_per_user(native,monkeypatch):
 _,sessions,*_=native;seed(sessions)
 import secrets
 chosen=iter(['red','green']);monkeypatch.setattr(secrets,'choice',lambda options:next(chosen))
 async def run():
  async with sessions() as s:
   u=await s.get(User,1);v=await s.get(User,2)
   assert (await miniapp.panel_snapshot(s,u))[0]['theme']=='red'
   assert (await miniapp.panel_snapshot(s,u))[0]['theme']=='red'
   assert (await miniapp.panel_snapshot(s,v))[0]['theme']=='green'
   assert await s.scalar(select(func.count(Setting.key)).where(Setting.key.like('panel_wallet_theme:%')))==2
 asyncio.run(run())

def test_remote_owner_mismatch_never_activates_or_deducts_quota(panels,monkeypatch):
 c,sessions,remote,delivery=panels
 remote.return_value={'id':501,'admin':{'id':88},'subscription_url':'https://example.com/sub/other'}
 activate=AsyncMock();monkeypatch.setattr(PasarGuardService,'update_user',activate)
 r=c.post('/api/miniapp/panels/1/configurations',headers=H,json=payload())
 assert r.json()['status']=='review' and r.json()['link'] is None
 activate.assert_not_awaited();delivery.assert_not_awaited()


def test_multi_group_payload_matches_upstream_create_status_contract(panels,monkeypatch):
 c,sessions,remote,_=panels
 monkeypatch.setattr(PasarGuardService,'list_groups',AsyncMock(return_value=[{'id':5,'name':'A'},{'id':6,'name':'B'},{'id':7,'name':'C'}]))
 async def upstream(child,method,path,**kw):
  data=kw['json']
  if data['status'] not in {'active','on_hold'}:raise RuntimeError('PasarGuard API POST /api/user failed (422): invalid status')
  if data['status']=='on_hold' and (data.get('expire') or not data.get('on_hold_expire_duration')):raise RuntimeError('(422): invalid on_hold fields')
  assert data['group_ids']==[5,6,7]
  return {'id':502,'username':data['username'],'admin':{'id':77},'subscription_url':'https://example.com/sub/groups','note':data['note']}
 remote.side_effect=upstream
 b=payload();b['group_ids']=[7,5,6,5]
 r=c.post('/api/miniapp/panels/1/configurations',headers=H,json=b)
 assert r.json()['status']=='done',r.text


def test_old_absent_review_is_recovered_and_no_longer_blocks_creation(panels):
 c,sessions,remote,_=panels
 old=payload();old_request={k:v for k,v in old.items() if k!='key'};old_request['panel_id']=1
 async def setup():
  async with sessions() as s:
   s.add(MiniAppOperation(user_id=1,key=old['key'],kind='panel_create',status='review',payload=old_request,result={'username':old['username']}));await s.commit()
 asyncio.run(setup())
 pending=c.get('/api/miniapp/panels/1/configurations/pending',headers=H).json()['operation']
 assert pending['status']=='failed' and pending['retryable'] and pending['request']['username']=='new_client'
 r=c.post('/api/miniapp/panels/1/configurations',headers=H,json=payload());assert r.json()['status']=='done',r.text
 remote.assert_awaited_once()


def test_partial_creation_is_adopted_on_retry_without_second_create(panels,monkeypatch):
 c,sessions,remote,_=panels;state={}
 async def get(self,child,name):return state.get('created')
 async def post(child,method,path,**kw):
  state['created']={'id':503,'username':kw['json']['username'],'admin':{'id':77},'group_ids':[5],'data_limit':3*GB,'status':'on_hold','note':kw['json']['note'],'subscription_url':'https://example.com/sub/recovered'}
  return state['created']
 monkeypatch.setattr(PasarGuardService,'get_user',get);remote.side_effect=post
 update=AsyncMock(side_effect=RuntimeError('connection lost after POST'))
 monkeypatch.setattr(PasarGuardService,'update_user',update)
 b=payload();first=c.post('/api/miniapp/panels/1/configurations',headers=H,json=b)
 assert first.json()['status']=='review'
 update.side_effect=None;update.return_value={}
 second=c.post('/api/miniapp/panels/1/configurations',headers=H,json=b)
 assert second.json()['status']=='done' and second.json()['link']=='https://example.com/sub/recovered',second.text
 remote.assert_awaited_once()


def test_validation_error_is_specific_and_retryable_instead_of_dead_end(panels):
 c,sessions,remote,_=panels;remote.side_effect=RuntimeError('PasarGuard API POST /api/user failed (422): rejected')
 r=c.post('/api/miniapp/panels/1/configurations',headers=H,json=payload())
 assert r.json()['status']=='failed' and r.json()['retryable']
 assert 'مشخصات' in r.json()['message'] and 'نیازمند بررسی پشتیبانی' not in r.json()['message']

def test_more_than_twenty_five_selected_groups_are_supported(panels,monkeypatch):
 c,sessions,remote,_=panels
 many=[{'id':i,'name':f'Group {i}'} for i in range(1,46)]
 monkeypatch.setattr(PasarGuardService,'list_groups',AsyncMock(return_value=many))
 b=payload();b['group_ids']=list(range(1,46))
 r=c.post('/api/miniapp/panels/1/configurations',headers=H,json=b)
 assert r.status_code==200 and r.json()['status']=='done',r.text
 assert len(remote.call_args.kwargs['json']['group_ids'])==45

def test_panel_configs_join_main_list_without_retail_records(panels,monkeypatch):
 c,sessions,remote,delivery=panels
 body=payload();made=c.post('/api/miniapp/panels/1/configurations',headers=H,json=body).json()
 assert made['status']=='done'
 rows=AsyncMock(return_value=[{'id':32,'username':body['username'],'admin':{'id':77},'used_traffic':GB,'data_limit':3*GB,'status':'active','expire':'2030-01-01T00:00:00Z'}])
 # The fixture's create response defines the real ID; use the persisted value.
 async def remote_id():
  async with sessions() as s:return (await s.get(MiniAppOperation,made['id'])).result['remote_id']
 rid=asyncio.run(remote_id());rows.return_value[0]['id']=rid
 monkeypatch.setattr(PanelMeterAPI,'list_own_users',rows)
 main=FastAPI();main.include_router(miniapp.router)
 with TestClient(main) as http:
  result=http.get('/api/miniapp/session',headers=H)
  assert result.status_code==200,result.text
  services=result.json()['services'];item=next(x for x in services if x.get('panel_id')==1)
  assert item['source']=='panel_reseller' and item['source_label']=='نمایندگی'
  assert item['used_bytes']==GB and item['remaining_bytes']==2*GB
  assert any(x['source']=='public' and x['source_label']=='خرید عمومی' for x in services)
  assert not any(x.get('panel_id')==1 for x in http.get('/api/miniapp/session',headers=OTHER).json()['services'])
  assert len([x for x in http.get('/api/miniapp/session',headers=H).json()['services'] if x.get('panel_id')==1])==1
 monkeypatch.setattr(PasarGuardService,'get_user',AsyncMock(return_value={**rows.return_value[0],'subscription_url':'https://actual.example/sub/opaque?one=1&two=2'}))
 link=c.get(f"/api/miniapp/panels/1/configurations/{made['id']}/link",headers=H)
 assert link.status_code==200 and link.json()['link']=='https://actual.example/sub/opaque?one=1&two=2'
 assert c.get(f"/api/miniapp/panels/1/configurations/{made['id']}/link",headers=OTHER).status_code==404
 assert c.get(f"/api/miniapp/panels/1/configurations/{made['id']}/qr",headers=H).headers['content-type']=='image/png'
 monkeypatch.setattr(PasarGuardService,'get_user',AsyncMock(return_value={**rows.return_value[0],'admin':{'id':999},'subscription_url':'https://wrong.example/sub/other'}))
 assert c.get(f"/api/miniapp/panels/1/configurations/{made['id']}/link",headers=H).status_code>=400
