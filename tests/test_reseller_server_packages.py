"""Purchases cannot select another server's lower-priced package."""
import asyncio,uuid
from types import SimpleNamespace
import pytest
from sqlalchemy import select
from test_miniapp import client,signed
from test_miniapp_native_actions import native
from test_reseller_onboarding import join,request,H
from app.database.models import Server,ResellerPackage,ResellerAccount,MiniAppOperation
from app.services.reseller_service import apply_package_inbound_policy,package_inbound_policy
from app.services import reseller_onboarding as flow


def test_package_checkout_catalog_and_forged_server(native):
 c,sessions,*_=native
 async def seed():
  async with sessions() as s:
   s.add_all([Server(id=3,name='Second',server_type='pasarguard',panel_url='https://second.example',username='x',password_encrypted='x',meta={'scope':'reseller','reseller_billing_modes':['volume']}),
    ResellerPackage(id=2,title='Cheap other server',server_id=3,volume_gb=100,price_irt=10),ResellerPackage(id=3,title='Unbound',volume_gb=100,price_irt=1)])
   await s.commit()
 asyncio.run(seed())
 assert [p['id'] for p in c.get('/api/miniapp/reseller/catalog',headers=H).json()['packages']]==[1]
 def quote(pid,sid):return c.post('/api/miniapp/funding/quote',headers=H,json={'key':str(uuid.uuid4()),'kind':'reseller_package','server_id':sid,'package_id':pid})
 assert quote(2,2).status_code==403
 assert quote(2,3).status_code==403
 assert quote(3,2).status_code==403
 async def grant():
  async with sessions() as s:
   account=await s.get(ResellerAccount,1);account.allowed_server_ids=[2,3];await s.commit()
 asyncio.run(grant())
 assert {p['server_id'] for p in c.get('/api/miniapp/reseller/catalog',headers=H).json()['packages']}=={2,3}
 assert quote(2,2).status_code==403
 assert quote(2,3).json()['amount']==10
 assert quote(1,3).status_code==403
 assert quote(1,2).json()['amount']==90000
 # A forged paid request cannot bypass quote validation or debit the wallet.
 r=c.post('/api/miniapp/funding',headers=H,json={'key':str(uuid.uuid4()),'kind':'reseller_package','server_id':2,'package_id':2,'method':'wallet','expected_amount':10})
 assert r.status_code==403


def test_onboarding_rejects_unbound_and_wrong_server_packages(join):
 c,sessions,_=join
 async def seed():
  async with sessions() as s:s.add(ResellerPackage(id=3,title='Unbound',volume_gb=100,price_irt=1));await s.commit()
 asyncio.run(seed())
 assert 3 not in [p['id'] for p in c.get('/api/miniapp/reseller-join',headers=H).json()['packages']]
 for pid in [2,3]:
  assert c.post('/api/miniapp/reseller-join/quote',headers=H,json={'key':str(uuid.uuid4()),**request(package_id=pid)}).status_code==409


def test_paid_onboarding_keeps_package_inbound_restrictions(join):
 c,sessions,_=join
 async def seed():
  async with sessions() as s:
   p=await s.get(ResellerPackage,1);p.meta={'inbound_mode':'manual','inbound_ids':[12,14]};await s.commit()
 asyncio.run(seed())
 r=c.post('/api/miniapp/reseller-join',headers=H,json={'key':str(uuid.uuid4()),**request(),'expected_amount':2000});assert r.status_code==200,r.text
 async def approve():
  async with sessions() as s:
   op=await s.get(MiniAppOperation,r.json()['id']);await flow.submit(s,op,'receipt');await s.commit()
   p=await s.get(ResellerPackage,1);p.meta={'inbound_mode':'automatic','inbound_ids':[]};await s.commit()
   await flow.approve(s,op,99,2,'volume');await s.commit()
   a=await s.scalar(select(ResellerAccount));assert a.inbound_policies['2']=={'mode':'manual','inbound_ids':[12,14]}
 asyncio.run(approve())


def test_package_policy_never_widens_admin_restrictions():
 a=SimpleNamespace(server_id=2,inbound_mode='manual',inbound_ids=[12],inbound_policies={'2':{'mode':'manual','inbound_ids':[12],'group_name':'VIP'}})
 apply_package_inbound_policy(a,2,{'mode':'manual','inbound_ids':[12,14]})
 assert a.inbound_policies['2']=={'mode':'manual','inbound_ids':[12],'group_name':'VIP'}
 apply_package_inbound_policy(a,2,{'mode':'automatic','inbound_ids':[]})
 assert a.inbound_ids==[12]
 apply_package_inbound_policy(a,2,{'mode':'manual','inbound_ids':[14]})
 assert a.inbound_policies['2']['inbound_ids']==[] # fail closed; no automatic fallback


@pytest.mark.parametrize('provider',['xui','pasarguard'])
def test_admin_package_restriction_validates_selected_server(provider):
 from app.api.admin_web import _reseller_package_inbound_meta
 from unittest.mock import AsyncMock
 request=SimpleNamespace(form=AsyncMock(return_value={'inbound_mode':'manual','inbound_ids':'12,14'}))
 server=Server(id=2,name='Restricted',server_type=provider,meta={'inbounds':[{'id':12},{'id':14}]})
 assert asyncio.run(_reseller_package_inbound_meta(request,server,{}))=={'inbound_mode':'manual','inbound_ids':[12,14]}
 request.form.return_value={'inbound_mode':'manual','inbound_ids':'99'}
 with pytest.raises(ValueError):asyncio.run(_reseller_package_inbound_meta(request,server,{}))
 request.form.return_value={'inbound_mode':'manual','inbound_ids':''}
 with pytest.raises(ValueError):asyncio.run(_reseller_package_inbound_meta(request,server,{}))


def test_home_hides_request_for_approved_reseller_even_when_workspace_hidden(client):
 c,sessions=client
 from app.services.miniapp_settings import clean_config
 from app.database.models import Setting
 import json
 assert c.get('/api/miniapp/session',headers=H).json()['buttons']['reseller_request'] is True
 async def approve():
  async with sessions() as s:
   s.add(ResellerAccount(user_id=1,server_id=2,is_active=True))
   s.add(Setting(key='miniapp_config',value=json.dumps(clean_config({'reseller_enabled':False}))))
   await s.commit()
 asyncio.run(approve())
 assert c.get('/api/miniapp/session',headers=H).json()['buttons']['reseller_request'] is False

@pytest.mark.parametrize('provider',['xui','pasarguard'])
def test_build_uses_only_package_allowed_inbounds(provider):
 from app.bot.handlers.public.reseller import resolve_reseller_build_target,reseller_server_policy
 from unittest.mock import AsyncMock
 server=Server(id=2,name='Restricted',server_type=provider,is_active=True,meta={'scope':'reseller','inbound_ids':[12,14,99]})
 account=ResellerAccount(server_id=2,allowed_server_ids=[2],billing_mode='volume',inbound_policies={})
 apply_package_inbound_policy(account,2,{'mode':'manual','inbound_ids':[12,14]})
 session=SimpleNamespace(get=AsyncMock(return_value=server))
 target,ids=asyncio.run(resolve_reseller_build_target(session,account,2))
 assert target is server and ids==[12,14]
 assert reseller_server_policy(account,server)==('manual',[12,14])
