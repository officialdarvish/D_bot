import uuid
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import select,func
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_reseller_payg import finance
from app.services import reseller_management as management,reseller_billing as billing
from app.database.models import ResellerAccount,ClientService,User,Server,ResellerBillingEntry,PasarGuardPanelOrder,PasarGuardPanelMeter,ResellerAccessRequest
GB=1024**3

@pytest.fixture
async def managed(finance,monkeypatch):
 monkeypatch.setattr(management,'SessionLocal',finance)
 monkeypatch.setattr(management,'panel_account_limits',AsyncMock())
 async def rows(s,kind,obj):
  if kind=='panel':return [dict(key='panel:1:71',order_id=1,remote_id=71,server_id=2,username='panel_client',used=0)]
  services=(await s.execute(select(ClientService).where(ClientService.reseller_id==obj.id))).scalars().all()
  return [dict(key=f'service:{v.id}',service_id=v.id,server_id=v.server_id,username=v.client_username,used=int(v.used_bytes or 0)) for v in services if not v.client_username.startswith('deleted_')]
 monkeypatch.setattr(management,'own_rows',rows)
 remote=AsyncMock();monkeypatch.setattr(management,'freeze_remote',remote)
 async with finance() as s:
  a=await s.get(ResellerAccount,1);a.wallet_balance_irt=100000;a.total_bytes=0
  for sid in [1,2]:
   svc=await s.get(ClientService,sid);svc.used_bytes=svc.reseller_lifetime_used_bytes=0
  await s.commit()
 yield finance,remote

async def test_swap_reserves_one_gb_per_client_once(managed):
 sessions,remote=managed;k=str(uuid.uuid4())
 result=await management.start_switch('account',1,'volume',10000,k,100000,2)
 assert result['status']=='paid',result
 assert remote.await_count==2
 async with sessions() as s:
  a=await s.get(ResellerAccount,1);assert a.total_bytes==8*GB and a.wallet_balance_irt==0 and a.billing_mode=='volume' and a.is_active
  for sid in [1,2]:
   svc=await s.get(ClientService,sid);assert svc.total_bytes==GB and not svc.is_active and svc.disabled_reason=='mode_switch_manual' and svc.reseller_reserved_bytes==GB
  assert (await s.get(ClientService,3)).is_active
 await management.start_switch('account',1,'volume',10000,k,100000,2)
 async with sessions() as s:
  assert (await s.get(ResellerAccount,1)).total_bytes==8*GB
  assert await s.scalar(select(func.count(ResellerBillingEntry.id)).where(ResellerBillingEntry.kind=='volume_swap'))==1

async def test_failed_freeze_retry_preserves_wallet_and_completed_steps(managed):
 sessions,remote=managed;remote.side_effect=[None,RuntimeError('timeout')]
 r=await management.start_switch('account',1,'volume',10000,str(uuid.uuid4()),100000,2)
 assert r['status']=='processing'
 async with sessions() as s:
  a=await s.get(ResellerAccount,1);assert a.wallet_balance_irt==100000 and a.billing_mode=='payg' and not a.is_active
 remote.side_effect=None
 r=await management.run_switch(r['id']);assert r['status']=='paid',r
 assert remote.await_count==3
 async with sessions() as s:assert (await s.get(ResellerAccount,1)).total_bytes==8*GB

async def test_insufficient_and_stale_preview_do_not_touch_panels(managed):
 _,remote=managed
 with pytest.raises(ValueError,match='کافی نیست'):await management.start_switch('account',1,'volume',100000,str(uuid.uuid4()),100000,2)
 with pytest.raises(ValueError,match='تغییر'):await management.start_switch('account',1,'volume',10000,str(uuid.uuid4()),90000,2)
 remote.assert_not_awaited()

async def test_personal_sanaei_rate_is_used_and_manual_pause_not_auto_resumed(managed):
 sessions,_=managed
 async with sessions() as s:
  await management.save_rates(s,'account',1,5000,10000);await s.commit()
  svc=await s.get(ClientService,1);svc.used_bytes=svc.reseller_lifetime_used_bytes=GB
  a=await s.get(ResellerAccount,1);await billing.settle(s,a);await s.commit();assert a.wallet_balance_irt==95000
  assert await billing.rate_for(s,a,await s.get(Server,1))==5000
  svc.disabled_reason='mode_switch_manual';svc.is_active=False;await s.commit()
 await billing.reconcile_suspensions()
 async with sessions() as s:assert not (await s.get(ClientService,1)).is_active

async def test_reverse_preserves_gb_without_minting_credit(managed):
 sessions,_=managed
 await management.start_switch('account',1,'volume',10000,str(uuid.uuid4()),100000,2)
 r=await management.start_switch('account',1,'payg',10000,str(uuid.uuid4()),0,2);assert r['status']=='paid',r
 async with sessions() as s:
  a=await s.get(ResellerAccount,1);assert a.billing_mode=='payg' and a.wallet_balance_irt==0 and a.total_bytes>=8*GB
  assert (await s.get(ClientService,1)).disabled_reason=='mode_switch_manual'

async def test_union_includes_payg_requests_and_dashboard_panels(managed,monkeypatch):
 sessions,_=managed
 import app.api.admin_web as admin
 monkeypatch.setattr(admin,'SessionLocal',sessions)
 async with sessions() as s:
  s.add_all([User(id=3,telegram_id=33,full_name='Request'),User(id=4,telegram_id=44,full_name='Panel'),ResellerAccessRequest(user_id=3,status='approved_payg'),PasarGuardPanelOrder(user_id=4,server_id=2,username='purchased',status='approved',admin_id=55,amount_irt=100,receipt_file_id='file')]);await s.commit()
 data=await admin.api_v2_resellers('owner')
 assert {x['entry_kind'] for x in data['items']}=={'account','request','panel'}

async def test_panel_swap_cannot_create_a_second_billing_model(managed):
 sessions,_=managed
 async with sessions() as s:
  u=await s.get(User,1);u.wallet_balance=100000
  s.add_all([PasarGuardPanelOrder(id=1,user_id=1,server_id=2,username='panel',amount_irt=1,receipt_file_id='file',status='approved',admin_id=55),PasarGuardPanelMeter(order_id=1,gb_price_irt=0,hourly_price_irt=0)]);await s.commit()
 with pytest.raises(ValueError,match='یک مدل تعرفه'):
  await management.start_switch('panel',1,'volume',10000,str(uuid.uuid4()),100000,1)
 async with sessions() as s:
  assert (await s.get(User,1)).wallet_balance==100000 and (await s.get(ResellerAccount,1)).wallet_balance_irt==100000

async def test_request_can_enable_sanaei_payg(managed,monkeypatch):
 sessions,_=managed
 from app.api import reseller_finance as api
 monkeypatch.setattr(api,'SessionLocal',sessions)
 async with sessions() as s:
  s.add(User(id=3,telegram_id=33,full_name='Sanaei'));s.add(ResellerAccessRequest(id=1,user_id=3,status='pending'));await s.commit()
 result=await api.configure_request(1,1,'payg',3500,2000,'owner');assert result['ok']
 async with sessions() as s:
  a=await s.scalar(select(ResellerAccount).where(ResellerAccount.user_id==3));assert a.billing_mode=='payg' and a.server_id==1
  assert (await management.profile(s,f'account:{a.id}'))['payg_rate']==3500

async def test_manual_renewal_uses_only_quota_delta_once(managed,monkeypatch):
 sessions,_=managed
 from app.api import reseller_finance as api
 monkeypatch.setattr(api,'SessionLocal',sessions)
 await management.start_switch('account',1,'volume',10000,str(uuid.uuid4()),100000,2)
 key=str(uuid.uuid4());r=await api.renew_managed_service('account',1,'service:1',4,30,key,'owner');assert r['ok']
 await api.renew_managed_service('account',1,'service:1',4,30,key,'owner')
 async with sessions() as s:
  a=await s.get(ResellerAccount,1);svc=await s.get(ClientService,1)
  assert a.total_bytes==5*GB and svc.client_username=='client1' and svc.is_active and svc.disabled_reason is None and svc.reseller_reserved_bytes==4*GB

async def test_admin_endpoints_require_auth(managed):
 from app.api.reseller_finance import router
 app=FastAPI();app.include_router(router)
 with TestClient(app) as c:
  assert c.get('/admin/api/v2/resellers/account/1/settings').status_code in {401,403}
  r=c.post('/admin/resellers/account/1/switch',follow_redirects=False)
  assert r.status_code in {401,403} or (r.status_code in {303,307} and '/login' in r.headers.get('location',''))

async def test_volume_observer_reserves_new_users_once_and_blocks_overdraft(managed,monkeypatch):
 sessions,freeze=managed
 from app.services.pasarguard_panel_meter import PanelMeterAPI
 async with sessions() as s:
  s.add(PasarGuardPanelOrder(id=1,user_id=1,server_id=2,username='panel',amount_irt=1,receipt_file_id='f',status='approved',admin_id=7))
  await management.save_profile(s,'panels:1',{'billing_mode':'volume','available_bytes':2*GB,'allocations':{},'manual_pauses':[]});await s.commit()
 monkeypatch.setattr(PanelMeterAPI,'list_own_users',AsyncMock(return_value=[{'id':71,'username':'one','data_limit':GB,'used_traffic':0},{'id':72,'username':'over','data_limit':3*GB,'used_traffic':0}]))
 await management.poll_volume_panel(1);await management.poll_volume_panel(1)
 async with sessions() as s:
  p=await management.profile(s,'panels:1');assert p['available_bytes']==GB and p['allocations']=={'panel:1:71':GB}
 assert all(call.args[1]['username']=='over' for call in freeze.call_args_list)

async def test_xui_freeze_preserves_identity_links_and_expiry(monkeypatch):
 from app.services import xui_service
 client=AsyncMock();client.login.return_value=True
 client.find_client.return_value={'client':{'id':'original-uuid','email':'existing','subId':'same-link','expiryTime':123400,'totalGB':99*GB,'enable':True},'inbound_ids':[4,9]}
 monkeypatch.setattr(xui_service,'XUIClient',lambda *a:client);monkeypatch.setattr(xui_service,'decrypt_text',lambda x:x)
 from types import SimpleNamespace
 await xui_service.XuiService().set_client_quota(SimpleNamespace(panel_url='https://example.com',username='x',password_encrypted='x'),'existing',GB,False)
 args=client.update_client.call_args
 assert args.args[1]=={'id':'original-uuid','email':'existing','subId':'same-link','expiryTime':123400,'totalGB':GB,'enable':False}
 assert args.kwargs['inbound_ids']==[4,9];client.update_client_traffic.assert_not_awaited()

async def test_panel_reverse_refunds_unused_volume_without_creating_money(managed):
 sessions,_=managed
 async with sessions() as s:
  s.add_all([PasarGuardPanelOrder(id=1,user_id=1,server_id=2,username='panel',amount_irt=1,receipt_file_id='f',status='approved',admin_id=7),PasarGuardPanelMeter(order_id=1,gb_price_irt=0,hourly_price_irt=0)])
  await management.save_profile(s,'panels:1',{'billing_mode':'volume','available_bytes':9*GB,'allocations':{'panel:1:71':GB},'quota_limits':{'panel:1:71':GB},'manual_pauses':['panel:1:71']});await s.commit()
 r=await management.start_switch('panel',1,'payg',10000,str(uuid.uuid4()),10000,1);assert r['status']=='paid',r
 async with sessions() as s:
  p=await management.profile(s,'panels:1');assert p['available_bytes']==10*GB and p['allocations']=={} and p['manual_pauses']==['panel:1:71']
  assert (await s.get(User,1)).wallet_balance==10000

async def test_panel_cap_update_preserves_overrides_and_targets_verified_admin(finance,monkeypatch):
 from app.services.pasarguard_service import PasarGuardService
 async with finance() as s:
  s.add_all([PasarGuardPanelOrder(id=1,user_id=1,server_id=2,username='panel1',amount_irt=1,receipt_file_id='f',status='approved',admin_id=7),PasarGuardPanelOrder(id=2,user_id=1,server_id=2,username='panel2',amount_irt=1,receipt_file_id='f',status='approved',admin_id=8)]);await s.commit()
  async def request(server,method,path,**kw):
   if method=='GET':return {'admins':[{'id':7,'username':'panel1','permission_overrides':{'read_only':False,'limit':9}}]}
   return {}
  mocked=AsyncMock(side_effect=request);monkeypatch.setattr(PasarGuardService,'_request',mocked)
  await management.panel_account_limits(s,1,[{'order_id':1}],3*GB,only_order=1)
  assert mocked.await_count==2
  args=mocked.call_args;assert args.args[2]=='/api/admin/by-id/7'
  assert args.kwargs['json']['permission_overrides']=={'read_only':False,'limit':9,'max_users':4}

async def test_switch_waits_for_pending_wallet_receipts(managed):
 sessions,remote=managed
 from app.database.models import ResellerWalletReceipt
 async with sessions() as s:
  s.add(ResellerWalletReceipt(reseller_id=1,amount_irt=1000,file_id='receipt',status='pending'));await s.commit()
 with pytest.raises(ValueError,match='رسیدهای'):await management.start_switch('account',1,'volume',10000,str(uuid.uuid4()),100000,2)
 remote.assert_not_awaited()

async def test_volume_tariff_applies_to_future_package_purchases(managed):
 from types import SimpleNamespace
 sessions,_=managed
 async with sessions() as s:
  a=await s.get(ResellerAccount,1)
  await management.save_profile(s,'account:1',{'volume_rate':2500})
  quote=await management.quote_package(s,a,SimpleNamespace(volume_gb=20,price_irt=999999,meta={}))
  assert quote.amount_irt==50000 and quote.currency=='IRT'
