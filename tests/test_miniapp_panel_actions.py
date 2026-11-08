import asyncio,uuid
from copy import deepcopy
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import select
from test_miniapp_panel_create_cards import panels,payload,H,OTHER,GB
from test_miniapp_native_actions import native,client
from app.database.models import MiniAppOperation,User,PasarGuardPanelMeter
from app.services.pasarguard_service import PasarGuardService
from app.services.reseller_management import profile,save_profile
from app.services.pasarguard_panel_meter import PanelMeterAPI

@pytest.fixture
def controlled(panels,monkeypatch):
 c,sessions,post,delivery=panels
 created=c.post('/api/miniapp/panels/1/configurations',headers=H,json=payload()).json()
 assert created['status']=='done'
 state={'id':501,'group_ids':[7,9],'proxy_settings':{'vless':{'id':'old-uuid'}},'username':'new_client','admin':{'id':77},'data_limit':3*GB,'used_traffic':GB,'status':'active','expire':'2030-01-01T00:00:00+00:00','subscription_url':'https://example.com/sub/old'}
 deleted=[False];calls=[]
 async def read(*args,**kwargs):return None if deleted[0] else deepcopy(state)
 async def update(*args,**kwargs):
  calls.append(('update',kwargs.copy()))
  if kwargs.get('data_limit_bytes') is not None:state['data_limit']=kwargs['data_limit_bytes']
  if kwargs.get('expire_at') is not None:state['expire']=kwargs['expire_at'].isoformat()
  if kwargs.get('status') is not None:state['status']=kwargs['status']
  return deepcopy(state)
 async def remove(*args,**kwargs):calls.append(('delete',{}));deleted[0]=True
 async def revoke(*args,**kwargs):state['proxy_settings']={'vless':{'id':str(uuid.uuid4())}};calls.append(('revoke',{}));state['subscription_url']='https://example.com/sub/new?x=1&y=2&rotation='+str(sum(k=='revoke' for k,_ in calls));return deepcopy(state)
 async def hwid(*args,**kwargs):calls.append(('hwid',{}));return {'deleted':2}
 monkeypatch.setattr(PasarGuardService,'get_user',read)
 monkeypatch.setattr(PasarGuardService,'update_user',update)
 monkeypatch.setattr(PasarGuardService,'delete_user',remove)
 monkeypatch.setattr(PasarGuardService,'revoke_subscription',revoke)
 monkeypatch.setattr(PasarGuardService,'clear_user_hwids',hwid)
 return c,sessions,created['id'],state,calls,delivery,deleted

def send(f,action,key=None,**extra):
 c,_,oid,*_=f
 return c.post(f'/api/miniapp/panels/1/configurations/{oid}/actions',headers=H,json=dict(key=key or str(uuid.uuid4()),action=action,confirmed=True,**extra))

def test_all_panel_actions_are_native_and_idempotent(controlled):
 f=controlled;c,sessions,oid,state,calls,delivery,deleted=f
 for action in ['hwid','revoke','add_volume','add_days','renew']:
  key=str(uuid.uuid4());r=send(f,action,key,volume=2,days=10)
  assert r.status_code==200 and r.json()['status']=='done',r.text
  count=len(calls);assert send(f,action,key,volume=2,days=10).json()['status']=='done'
  assert len(calls)==count
  assert r.json()['result']['service']['panel_id']==1
 assert state['data_limit']==7*GB and state['used_traffic']==GB
 assert state['subscription_url'].startswith('https://example.com/sub/new?x=1&y=2&rotation=')
 assert delivery.await_count==2 # creation + explicitly requested fresh config after HWID reset
 key=str(uuid.uuid4());r=send(f,'delete',key);assert r.json()['status']=='done'
 assert send(f,'delete',key).json()['status']=='done'
 assert [kind for kind,_ in calls].count('delete')==1
 assert c.get(f'/api/miniapp/panels/1/configurations/{oid}/link',headers=H).status_code==410


def test_controls_enforce_owner_confirmation_and_remote_identity(controlled):
 f=controlled;c,sessions,oid,state,calls,*_=f
 path=f'/api/miniapp/panels/1/configurations/{oid}/actions';body=dict(key=str(uuid.uuid4()),action='delete',confirmed=True)
 assert c.post(path,json=body).status_code==401
 assert c.post(path,headers=OTHER,json=body).status_code==404
 assert c.post(path,headers=H,json={**body,'confirmed':False}).status_code==422
 state['admin']={'id':999};assert send(f,'delete').status_code==403
 state['admin']={'id':77};state['id']=999;assert send(f,'delete').status_code==409
 assert not calls


def volume_mode(sessions,available=10*GB,pauses=False):
 async def seed():
  async with sessions() as s:
   p=await profile(s,'panels:1');p.update(billing_mode='volume',available_bytes=available,allocations={'panel:1:501':3*GB},quota_limits={'panel:1:501':3*GB},manual_pauses=['panel:1:501'] if pauses else [])
   await save_profile(s,'panels:1',p);await s.commit()
 asyncio.run(seed())

def finance(sessions):
 async def get():
  async with sessions() as s:return await profile(s,'panels:1')
 return asyncio.run(get())

def test_prepaid_add_and_delete_credit_unused_once(controlled,monkeypatch):
 f=controlled;c,sessions,oid,state,calls,*_=f;volume_mode(sessions)
 key=str(uuid.uuid4());assert send(f,'add_volume',key,volume=2).json()['status']=='done'
 assert finance(sessions)['available_bytes']==8*GB
 assert send(f,'add_volume',key,volume=2).json()['status']=='done'
 assert finance(sessions)['available_bytes']==8*GB
 assert finance(sessions)['quota_limits']['panel:1:501']==5*GB
 key=str(uuid.uuid4());assert send(f,'delete',key).json()['status']=='done'
 assert finance(sessions)['available_bytes']==12*GB
 assert send(f,'delete',key).json()['status']=='done'
 assert finance(sessions)['available_bytes']==12*GB
 assert 'panel:1:501' not in finance(sessions)['allocations']
 from app.services import reseller_management as management
 monkeypatch.setattr(management,'SessionLocal',sessions)
 monkeypatch.setattr(management,'panel_account_limits',AsyncMock())
 monkeypatch.setattr(PanelMeterAPI,'list_own_users',AsyncMock(return_value=[deepcopy(state)]))
 asyncio.run(management.poll_volume_panel(1))
 assert finance(sessions)['available_bytes']==12*GB # stale remote pages cannot re-reserve a deleted config


def test_insufficient_volume_and_admin_manual_pause_block_growth(controlled):
 f=controlled;volume_mode(f[1],available=GB)
 assert send(f,'add_volume',volume=2).status_code==409
 assert not f[4]
 volume_mode(f[1],pauses=True)
 for action in ['renew','add_volume','add_days']:assert send(f,action).status_code==409
 assert not f[4]
 assert send(f,'hwid').json()['status']=='done'


def test_unknown_update_resumes_absolute_target_without_double_debit(controlled,monkeypatch):
 f=controlled;c,sessions,oid,state,calls,*_=f;volume_mode(sessions)
 async def uncertain(*args,**kwargs):state['data_limit']=kwargs['data_limit_bytes'];raise RuntimeError('timeout after successful write')
 monkeypatch.setattr(PasarGuardService,'update_user',uncertain)
 key=str(uuid.uuid4());r=send(f,'add_volume',key,volume=2)
 assert r.json()['status']=='review'
 restored=c.get(f'/api/miniapp/panels/1/configurations/{oid}/actions/{key}',headers=H)
 assert restored.json()['request']['volume']==2 and restored.json()['status']=='review'
 assert c.get(f'/api/miniapp/panels/1/configurations/{oid}/actions/{key}',headers=OTHER).status_code==404
 assert finance(sessions)['available_bytes']==8*GB
 assert send(f,'add_days').status_code==409
 assert c.post('/api/miniapp/panels/1/configurations',headers=H,json=payload()).status_code==409
 async def update(*args,**kwargs):state['data_limit']=kwargs['data_limit_bytes'];return deepcopy(state)
 monkeypatch.setattr(PasarGuardService,'update_user',update)
 assert send(f,'add_volume',key,volume=2).json()['status']=='done'
 assert state['data_limit']==5*GB and finance(sessions)['available_bytes']==8*GB
 assert send(f,'add_volume',key,volume=3).status_code==409


def test_uncertain_delete_reconciles_absence_and_refunds_once(controlled,monkeypatch):
 f=controlled;c,sessions,oid,state,calls,delivery,deleted=f;volume_mode(sessions)
 async def remove(*args,**kwargs):deleted[0]=True;calls.append(('delete',{}));raise RuntimeError('lost acknowledgement')
 monkeypatch.setattr(PasarGuardService,'delete_user',remove)
 key=str(uuid.uuid4());assert send(f,'delete',key).json()['status']=='review'
 assert finance(sessions)['available_bytes']==10*GB
 assert send(f,'delete',key).json()['status']=='done'
 assert finance(sessions)['available_bytes']==12*GB
 assert len(calls)==1


def test_uncertain_revoke_adopts_rotated_url(controlled,monkeypatch):
 f=controlled;state=f[3];calls=f[4]
 async def rotate(*args,**kwargs):state['proxy_settings']={'vless':{'id':'recovered-uuid'}};state['subscription_url']='https://example.com/sub/recovered';calls.append(('revoke',{}));raise RuntimeError('ack lost')
 monkeypatch.setattr(PasarGuardService,'revoke_subscription',rotate)
 key=str(uuid.uuid4());assert send(f,'revoke',key).json()['status']=='review'
 assert send(f,'revoke',key).json()['status']=='done'
 assert len(calls)==1


def test_payg_delete_preserves_last_usage_checkpoint(controlled):
 f=controlled;assert send(f,'delete').json()['status']=='done'
 async def get():
  async with f[1]() as s:return await s.scalar(select(PasarGuardPanelMeter).where(PasarGuardPanelMeter.order_id==1))
 meter=asyncio.run(get());assert meter.traffic_bytes>=GB and meter.usage_offsets['501']==GB


def test_renamed_remote_user_cannot_be_treated_as_deleted(controlled,monkeypatch):
 f=controlled;c,sessions,oid,state,calls,delivery,deleted=f;volume_mode(sessions)
 async def unknown(*args,**kwargs):raise RuntimeError('delete response lost')
 monkeypatch.setattr(PasarGuardService,'delete_user',unknown)
 key=str(uuid.uuid4());assert send(f,'delete',key).json()['status']=='review'
 deleted[0]=True # Lookup by the original username now returns 404.
 monkeypatch.setattr(PanelMeterAPI,'list_own_users',AsyncMock(return_value=[{**state,'username':'renamed'}]))
 assert send(f,'delete',key).status_code==409
 assert finance(sessions)['available_bytes']==10*GB


def test_hwid_same_key_recovers_rotated_link_without_second_reset(controlled,monkeypatch):
 f=controlled;c,sessions,oid,state,calls,delivery,deleted=f
 async def uncertain(*a,**k):
  calls.append(('revoke',{}));state['proxy_settings']={'vless':{'id':'rotated-once-uuid'}};state['subscription_url']='https://example.com/sub/rotated-once'
  raise TimeoutError('reply lost after commit')
 monkeypatch.setattr(PasarGuardService,'revoke_subscription',uncertain)
 key=str(uuid.uuid4());first=send(f,'hwid',key)
 assert first.json()['status']=='review'
 second=send(f,'hwid',key);assert second.json()['status']=='done',second.text
 assert [k for k,v in calls].count('hwid')==1 and [k for k,v in calls].count('revoke')==1
 assert delivery.await_count==2
 assert send(f,'hwid',key).json()['status']=='done' and delivery.await_count==2
