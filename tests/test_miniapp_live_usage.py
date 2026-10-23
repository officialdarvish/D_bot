import asyncio
from datetime import datetime,timedelta
from unittest.mock import AsyncMock
import pytest
from test_miniapp import client,signed
from app.api import miniapp
from app.services import miniapp_usage as usage
from app.database.models import ClientService,Server,ResellerAccount

GB=1024**3
H={'X-Telegram-Init-Data':signed()}


def test_usage_refresh_reads_only_owned_configs_and_keeps_other_fields(client,monkeypatch):
 c,sessions=client;monkeypatch.setattr(usage,'SessionLocal',sessions)
 async def seed():
  async with sessions() as s:
   (await s.get(Server,1)).server_type='pasarguard'
   svc=await s.get(ClientService,1);svc.xui_uuid='keep-uuid';svc.sub_link='happ://crypt5/keep'
   await s.commit()
 asyncio.run(seed())
 read=AsyncMock(return_value={'used_traffic':15*GB,'data_limit':30*GB})
 monkeypatch.setattr(usage.PasarGuardService,'get_user',read)
 assert c.get('/api/miniapp/usage').status_code==401
 r=c.get('/api/miniapp/usage',headers=H);assert r.status_code==200,r.text
 item=next(x for x in r.json()['services'] if x['id']==1)
 assert item['used_bytes']==15*GB and item['remaining_bytes']==15*GB
 assert read.await_count==1 and read.await_args.args[1]=='mine'
 async def verify():
  async with sessions() as s:
   svc=await s.get(ClientService,1);assert svc.xui_uuid=='keep-uuid' and svc.sub_link=='happ://crypt5/keep'
   assert svc.is_active and svc.used_bytes==15*GB
 asyncio.run(verify())
 read.side_effect=TimeoutError('panel offline')
 r=c.get('/api/miniapp/usage',headers=H);item=next(x for x in r.json()['services'] if x['id']==1)
 assert item['used_bytes']==15*GB and item['stale'] and item['active']


def test_reseller_usage_refresh_counts_delta_once_and_excludes_other_resellers(client,monkeypatch):
 c,sessions=client;monkeypatch.setattr(usage,'SessionLocal',sessions)
 async def seed():
  async with sessions() as s:
   s.add_all([ResellerAccount(id=1,user_id=1,server_id=2,total_bytes=100*GB,expires_at=datetime.utcnow()+timedelta(days=30)),ResellerAccount(id=2,user_id=2,server_id=2)])
   s.add_all([ClientService(id=3,user_id=2,reseller_id=1,server_id=2,client_username='owned-customer',xui_email='owned-customer',total_bytes=10*GB),ClientService(id=4,user_id=2,reseller_id=2,server_id=2,client_username='foreign',xui_email='foreign',total_bytes=10*GB)])
   await s.commit()
 asyncio.run(seed())
 async def remote(server,name):return {'client':{'totalGB':10*GB},'traffic':{'up':GB,'down':GB,'total':10*GB}}
 read=AsyncMock(side_effect=remote);monkeypatch.setattr(usage.XuiService,'find_client_any',read)
 for _ in range(2):
  r=c.get('/api/miniapp/usage',headers=H);assert r.status_code==200,r.text
  assert r.json()['reseller']['services'][0]['used_bytes']==2*GB
 assert {a.args[1] for a in read.await_args_list}=={'mine','owned-customer'}
 async def verify():
  async with sessions() as s:
   assert (await s.get(ResellerAccount,1)).used_bytes==2*GB
   assert (await s.get(ClientService,4)).used_bytes==0
 asyncio.run(verify())


def test_usage_does_not_overwrite_concurrent_renewal(client,monkeypatch):
 c,sessions=client;monkeypatch.setattr(usage,'SessionLocal',sessions)
 async def remote(server,name):
  async with sessions() as s:
   svc=await s.get(ClientService,1);svc.total_bytes=60*GB;svc.used_bytes=0;await s.commit()
  return {'traffic':{'up':GB,'down':GB,'total':30*GB},'client':{}}
 monkeypatch.setattr(usage.XuiService,'find_client_any',AsyncMock(side_effect=remote))
 r=c.get('/api/miniapp/usage',headers=H);assert r.status_code==200,r.text
 item=r.json()['services'][0]
 assert item['total_bytes']==60*GB and item['used_bytes']==0 and item['stale']


@pytest.mark.parametrize('provider',['xui','pasarguard'])
async def test_remote_zero_quota_is_unlimited_not_old_quota(provider,monkeypatch):
 from types import SimpleNamespace
 server=SimpleNamespace(server_type=provider)
 service=SimpleNamespace(xui_email='user',client_username='user',total_bytes=30*GB)
 if provider=='xui':monkeypatch.setattr(usage.XuiService,'find_client_any',AsyncMock(return_value={'client':{'totalGB':0},'traffic':{'up':GB,'down':GB,'total':0}}))
 else:monkeypatch.setattr(usage.PasarGuardService,'get_user',AsyncMock(return_value={'used_traffic':2*GB,'data_limit':0}))
 assert await usage.read_usage(server,service)==(2*GB,0)
