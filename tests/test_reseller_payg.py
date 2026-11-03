import asyncio
import hashlib
import hmac
import json
import time
from datetime import datetime,timedelta
from types import SimpleNamespace
from urllib.parse import urlencode
from unittest.mock import AsyncMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select,func
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
from app.database.base import Base
from app.database.models import User,Server,ResellerAccount,ClientService,ResellerUsageMeter,ResellerBillingEntry,ResellerWalletReceipt,WalletTransaction
from app.services import reseller_billing as billing
GB=1024**3

@pytest.fixture
async def finance(tmp_path,monkeypatch):
 engine=create_async_engine('sqlite+aiosqlite:///'+str(tmp_path/'billing.db'))
 sessions=async_sessionmaker(engine,expire_on_commit=False)
 async with engine.begin() as conn:await conn.run_sync(Base.metadata.create_all)
 async with sessions() as s:
  s.add_all([User(id=1,telegram_id=11,full_name='Partner',wallet_balance=10000),User(id=2,telegram_id=22,full_name='Other'),
   Server(id=1,name='X-UI',server_type='xui',panel_url='https://example.com',username='x',password_encrypted='x',meta={'scope':'reseller','reseller_billing_modes':['volume','payg'],'reseller_payg_rate_irt':10}),
   Server(id=2,name='PasarGuard',server_type='pasarguard',panel_url='https://example.com',username='x',password_encrypted='x',meta={'scope':'reseller','reseller_billing_modes':['volume','payg'],'reseller_payg_rate_irt':30}),
   ResellerAccount(id=1,user_id=1,server_id=1,allowed_server_ids=[1,2],billing_mode='payg',wallet_balance_irt=100,total_bytes=20*GB,is_active=True),
   ResellerAccount(id=2,user_id=2,server_id=1,allowed_server_ids=[1],billing_mode='payg',wallet_balance_irt=100,is_active=True),
   ClientService(id=1,user_id=1,reseller_id=1,server_id=1,client_username='client1',xui_email='client1',total_bytes=10*GB,used_bytes=GB,reseller_lifetime_used_bytes=GB,is_active=True),
   ClientService(id=2,user_id=1,reseller_id=1,server_id=2,client_username='client2',xui_email='client2',total_bytes=10*GB,used_bytes=GB//2,reseller_lifetime_used_bytes=GB//2,is_active=True),
   ClientService(id=3,user_id=2,reseller_id=2,server_id=1,client_username='other',xui_email='other',total_bytes=10*GB,used_bytes=GB,reseller_lifetime_used_bytes=GB,is_active=True)])
  await s.commit()
 monkeypatch.setattr(billing,'SessionLocal',sessions)
 monkeypatch.setattr(billing,'set_remote',AsyncMock())
 import app.bot.handlers.public.reseller as reseller
 monkeypatch.setattr(reseller,'sync_all_reseller_services',AsyncMock())
 yield sessions
 await engine.dispose()

async def test_integer_usage_multi_server_and_idempotent_retry(finance):
 async with finance() as s:
  a=await s.get(ResellerAccount,1,with_for_update=True)
  result=await billing.settle(s,a);await s.commit()
  assert result=={'cost':25,'bytes':GB+GB//2} and a.wallet_balance_irt==75
  assert (await billing.settle(s,a))['cost']==0;await s.commit()
  assert await s.scalar(select(func.count(ResellerBillingEntry.id)))==2
  assert (await s.get(ResellerAccount,2)).wallet_balance_irt==100

async def test_fractional_carry_is_conserved_across_intervals(finance):
 async with finance() as s:
  a=await s.get(ResellerAccount,1,with_for_update=True)
  svc=await s.get(ClientService,1);other=await s.get(ClientService,2)
  svc.used_bytes=svc.reseller_lifetime_used_bytes=0;other.used_bytes=other.reseller_lifetime_used_bytes=0
  a.wallet_balance_irt=100
  for n in [GB//3,2*(GB//3),GB]:
   svc.used_bytes=svc.reseller_lifetime_used_bytes=n
   await billing.settle(s,a);await s.commit()
  assert a.wallet_balance_irt==90
  meter=await s.scalar(select(ResellerUsageMeter).where(ResellerUsageMeter.service_id==1))
  assert meter.remainder==0 and meter.checkpoint_bytes==GB

async def test_counter_reset_bills_new_traffic_without_losing_lifetime(finance):
 from app.services.reseller_service import apply_reseller_usage_delta
 async with finance() as s:
  svc=await s.get(ClientService,1)
  svc.used_bytes=svc.reseller_lifetime_used_bytes=10*GB;await s.commit()
  a=await s.get(ResellerAccount,1,with_for_update=True)
  meter=await billing.meter_for(s,a,svc,baseline=True);await s.commit()
  svc.total_bytes=99*GB
  await apply_reseller_usage_delta(s,svc,2*GB)
  assert svc.reseller_lifetime_used_bytes==12*GB and svc.total_bytes==99*GB
  await billing.settle(s,a);await s.commit()
  entry=await s.scalar(select(ResellerBillingEntry).where(ResellerBillingEntry.service_id==1))
  assert entry.usage_bytes==2*GB and entry.amount_irt==-20

async def test_wallet_debt_and_retry_checkpoint_are_not_forgiven(finance):
 async with finance() as s:
  a=await s.get(ResellerAccount,1,with_for_update=True);a.wallet_balance_irt=1
  await billing.settle(s,a);await s.commit()
  assert a.wallet_balance_irt==-24
  await billing.settle(s,a);await s.commit();assert a.wallet_balance_irt==-24
  with pytest.raises(ValueError,match='debt'):await billing.configure_mode(s,a,'volume')

async def test_mode_switch_preserves_inventory_and_never_bills_old_history(finance,monkeypatch):
 import app.services.reseller_service as rs
 monkeypatch.setattr(rs,'sync_reseller_service_panel_snapshot',AsyncMock())
 async with finance() as s:
  a=await s.get(ResellerAccount,1,with_for_update=True);a.billing_mode='volume'
  svc=await s.get(ClientService,1);svc.used_bytes=svc.reseller_lifetime_used_bytes=4*GB;svc.reseller_reserved_bytes=10*GB
  other=await s.get(ClientService,2);other.client_username='deleted_other'
  await s.commit()
  await billing.configure_mode(s,a,'payg');await s.commit()
  assert a.total_bytes==26*GB
  assert (await billing.settle(s,a))['cost']==0
  svc.used_bytes=svc.reseller_lifetime_used_bytes=5*GB
  assert (await billing.settle(s,a))['cost']==10
  await billing.configure_mode(s,a,'volume');await s.commit()
  assert a.total_bytes==21*GB and svc.reseller_reserved_used_baseline==5*GB
  svc.used_bytes=6*GB
  assert await rs.release_reserved_volume(s,svc,a)==4*GB
  assert a.total_bytes==25*GB

async def test_roll_back_debit_rolls_back_checkpoint(finance):
 async with finance() as s:
  a=await s.get(ResellerAccount,1,with_for_update=True)
  await billing.settle(s,a);await s.rollback()
 async with finance() as s:
  a=await s.get(ResellerAccount,1,with_for_update=True)
  assert a.wallet_balance_irt==100
  await billing.settle(s,a);await s.commit();assert a.wallet_balance_irt==75
  assert await s.scalar(select(func.count(ResellerBillingEntry.id)))==2

async def test_only_billing_suspended_services_resume_after_recharge(finance):
 async with finance() as s:
  a=await s.get(ResellerAccount,1);a.wallet_balance_irt=-1
  manual=await s.get(ClientService,2);manual.is_active=False;await s.commit()
 await billing.reconcile_suspensions()
 async with finance() as s:
  a=await s.get(ResellerAccount,1,with_for_update=True)
  assert (await s.get(ClientService,1)).is_active is False
  await billing.credit(s,a,100,key='test-topup');await s.commit()
 await billing.reconcile_suspensions()
 async with finance() as s:
  assert (await s.get(ClientService,1)).is_active is True
  assert (await s.get(ClientService,2)).is_active is False

async def test_provider_failure_keeps_pending_pause_and_retries(finance,monkeypatch):
 async with finance() as s:
  a=await s.get(ResellerAccount,1);a.wallet_balance_irt=-1;await s.commit()
 monkeypatch.setattr(billing,'set_remote',AsyncMock(side_effect=RuntimeError('offline')))
 await billing.reconcile_suspensions()
 async with finance() as s:
  meter=await s.scalar(select(ResellerUsageMeter).where(ResellerUsageMeter.service_id==1))
  assert meter.suspension_pending is True and meter.last_error=='offline'
 monkeypatch.setattr(billing,'set_remote',AsyncMock())
 await billing.reconcile_suspensions()
 async with finance() as s:
  meter=await s.scalar(select(ResellerUsageMeter).where(ResellerUsageMeter.service_id==1))
  assert meter.suspended is True and meter.suspension_pending is False

async def test_billing_interval_persists_across_worker_restarts(finance):
 async with finance() as s:
  a=await s.get(ResellerAccount,1);a.billing_last_run_at=datetime.utcnow()-timedelta(minutes=29)
  other=await s.get(ResellerAccount,2);other.billing_last_run_at=datetime.utcnow();await s.commit()
 await billing.billing_cycle()
 async with finance() as s:
  a=await s.get(ResellerAccount,1);assert a.wallet_balance_irt==100
  a.billing_last_run_at=datetime.utcnow()-timedelta(minutes=31);await s.commit()
 await billing.billing_cycle();await billing.billing_cycle()
 async with finance() as s:assert (await s.get(ResellerAccount,1)).wallet_balance_irt==75

async def test_tariff_change_settles_old_rate_before_new_rate(finance):
 async with finance() as s:
  server=await s.get(Server,1)
  await billing.update_server_policy(s,server,['volume','payg'],20);await s.commit()
  svc=await s.get(ClientService,1);svc.used_bytes=svc.reseller_lifetime_used_bytes=2*GB
  account=await s.get(ResellerAccount,1,with_for_update=True)
  await billing.settle(s,account);await s.commit()
  entries=(await s.execute(select(ResellerBillingEntry).where(ResellerBillingEntry.service_id==1).order_by(ResellerBillingEntry.id))).scalars().all()
  assert [(e.usage_bytes,e.amount_irt,e.rate_irt_per_gb) for e in entries]==[(GB,-10,10),(GB,-20,20)]
  with pytest.raises(ValueError):await billing.update_server_policy(s,server,['volume'],0)

async def test_receipt_approval_and_credit_are_single_use(finance):
 async with finance() as s:
  s.add(ResellerWalletReceipt(id=1,reseller_id=1,amount_irt=10000,file_id='receipt',status='pending'));await s.commit()
  result=await billing.review_receipt(s,1,11,True);assert result is not None;await s.commit()
  assert await billing.review_receipt(s,1,11,True) is None
  assert (await s.get(ResellerAccount,1)).wallet_balance_irt==10100
  assert await s.scalar(select(func.count(ResellerBillingEntry.id)).where(ResellerBillingEntry.event_key=='receipt:1'))==1

async def test_internal_wallet_transfer_retries_do_not_double_debit(finance,monkeypatch):
 from app.bot.handlers.public import reseller_wallet as wallet
 monkeypatch.setattr(wallet,'SessionLocal',finance);monkeypatch.setattr(wallet,'edit_or_answer',AsyncMock())
 callback=SimpleNamespace(from_user=SimpleNamespace(id=11),answer=AsyncMock(),bot=SimpleNamespace(send_message=AsyncMock()))
 state=SimpleNamespace(get_data=AsyncMock(return_value={'payg_amount':5000,'payg_operation':'same-attempt'}),clear=AsyncMock())
 await wallet.from_personal(callback,state);await wallet.from_personal(callback,state)
 async with finance() as s:
  assert (await s.get(User,1)).wallet_balance==5000
  assert (await s.get(ResellerAccount,1)).wallet_balance_irt==5100
  assert await s.scalar(select(func.count(WalletTransaction.id)))==1


def test_policy_validation_and_volume_compatibility():
 from app.services.reseller_billing import validate_policy,server_allows
 volume=SimpleNamespace(billing_mode='volume');payg=SimpleNamespace(billing_mode='payg')
 server=SimpleNamespace(meta={},server_type='xui')
 assert server_allows(volume,server) and not server_allows(payg,server)
 assert validate_policy('volume,payg',100,'xui')['reseller_payg_rate_irt']==100
 for modes,rate,provider in [('payg',0,'xui'),('payg',100,'mikrotik'),('other',100,'xui')]:
  with pytest.raises(ValueError):validate_policy(modes,rate,provider)


def test_owner_miniapp_rejects_non_owner_and_mints_csrf_session(monkeypatch):
 from app.api import admin_miniapp
 from app.core.config import settings
 token='123456:TEST_TOKEN_FOR_LOCAL_VALIDATION'
 monkeypatch.setattr(settings,'BOT_TOKEN',token);monkeypatch.setattr(settings,'ADMIN_IDS','11');monkeypatch.setattr(settings,'OWNER_IDS','')
 monkeypatch.setattr(admin_miniapp,'db_setting',AsyncMock(side_effect=lambda k,d:'1' if k=='initial_setup_done' else 'v1'))
 monkeypatch.setattr(admin_miniapp,'read_web_path',AsyncMock(return_value='dbot-private'))
 def signed(uid):
  fields={'auth_date':str(int(time.time())),'user':json.dumps({'id':uid})};secret=hmac.new(b'WebAppData',token.encode(),hashlib.sha256).digest()
  fields['hash']=hmac.new(secret,'\n'.join(f'{k}={v}' for k,v in sorted(fields.items())).encode(),hashlib.sha256).hexdigest();return urlencode(fields)
 app=FastAPI();app.include_router(admin_miniapp.router);c=TestClient(app)
 assert c.post('/api/miniapp/admin-session').status_code==401
 assert c.post('/api/miniapp/admin-session',headers={'X-Telegram-Init-Data':signed(22)}).status_code==403
 r=c.post('/api/miniapp/admin-session',headers={'X-Telegram-Init-Data':signed(11)})
 assert r.status_code==200 and r.json()['url']=='/dbot-private/admin?miniapp=1'
 assert 'dbot_admin_token' in r.cookies and 'dbot_csrf_token' in r.cookies
 assert 'HttpOnly' in r.headers.get('set-cookie','')

async def test_billing_pause_is_released_after_switch_to_funded_volume(finance):
 async with finance() as s:
  account=await s.get(ResellerAccount,1);account.wallet_balance_irt=0
  await s.commit()
 await billing.reconcile_suspensions()
 async with finance() as s:
  account=await s.get(ResellerAccount,1,with_for_update=True)
  # Fund settlement debt, then reserve the existing configs from prepaid GB.
  await billing.credit(s,account,100,key='switch-topup')
  await billing.configure_mode(s,account,'volume');await s.commit()
 await billing.reconcile_suspensions()
 async with finance() as s:
  assert (await s.get(ClientService,1)).is_active is True
  assert (await s.get(ClientService,2)).is_active is True
  assert (await s.get(ResellerAccount,1)).billing_mode=='volume'

async def test_admin_edit_wallet_is_idempotent_and_preserves_fractional_inventory(finance,monkeypatch):
 import httpx
 from app.api import admin_web as web
 monkeypatch.setattr(web,'SessionLocal',finance)
 app=FastAPI();app.include_router(web.router)
 async def owner():return 'telegram-owner:11'
 app.dependency_overrides[web._auth_user]=owner
 async with finance() as s:
  account=await s.get(ResellerAccount,1);account.total_bytes=20*GB+12345;await s.commit()
 async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
  form={'billing_mode':'payg','wallet_adjustment_irt':'5000','billing_operation_id':'same-edit','billing_note':'Owner credit'}
  for _ in range(2):
   response=await client.post('/admin/resellers/1/edit',data=form,headers={'Accept':'application/json'})
   assert response.status_code==200,response.text
  response=await client.post('/admin/resellers/1/edit',data={'billing_mode':'invalid','wallet_adjustment_irt':'9000','billing_operation_id':'invalid-edit','billing_note':'Must roll back'},headers={'Accept':'application/json'})
  assert response.status_code==400
 async with finance() as s:
  account=await s.get(ResellerAccount,1)
  assert account.wallet_balance_irt==5100 and account.total_bytes==20*GB+12345
  assert await s.scalar(select(func.count(ResellerBillingEntry.id)))==1
