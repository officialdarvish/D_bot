import asyncio,uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select,func
from test_miniapp import client,signed
from app.database.models import (User,Server,PaymentCard,ResellerPackage,ResellerAccount,MiniAppOperation,
    PasarGuardPanelOrder,PasarGuardPanelMeter,ResellerBillingEntry,WalletTransaction)
from app.services import reseller_onboarding as flow
from app.services.reseller_management import profile
from app.api import miniapp_reseller_join as api

@pytest.fixture
def join(client,monkeypatch):
 _,sessions=client
 config={'pasarguard_panel_sales_enabled':'1','pasarguard_panel_sales_server_id':'3',
 'pasarguard_panel_sales_price_irt':'0','pasarguard_panel_sales_gb_price_irt':'20',
 'pasarguard_panel_sales_min_initial_gb':'100','reseller_payg_min_topup_irt':'5000'}
 async def setting(key,default=''):return config.get(key,default)
 monkeypatch.setattr(flow,'get_setting_value',setting)
 monkeypatch.setattr(flow,'get_user_button',AsyncMock(return_value=('request',True)))
 monkeypatch.setattr(api,'SessionLocal',sessions)
 async def seed():
  async with sessions() as s:
   server=await s.get(Server,2);server.meta={'scope':'reseller','reseller_billing_modes':['volume','payg'],'reseller_payg_rate_irt':20}
   s.add(Server(id=3,name='PG',server_type='pasarguard',panel_url='https://panel.example',username='owner',password_encrypted='private',meta={'scope':'reseller','reseller_billing_modes':['volume','payg'],'reseller_payg_rate_irt':20}))
   s.add_all([ResellerPackage(id=1,title='100 GB',server_id=2,volume_gb=100,price_irt=2000,reseller_validity_days=30),ResellerPackage(id=2,title='PG 100 GB',server_id=3,volume_gb=100,price_irt=3000,reseller_validity_days=40),
    PaymentCard(id=1,server_id=2,server_type='reseller',card_number='1111',owner_name='Service seller'),
    PaymentCard(id=2,server_id=3,server_type='panel_reseller',card_number='2222',owner_name='Panel seller')])
   await s.commit()
 asyncio.run(seed())
 app=FastAPI();app.include_router(api.router)
 with TestClient(app) as c:yield c,sessions,config

H={'X-Telegram-Init-Data':signed()}
def request(kind='volume',**kw):return {'kind':kind,'mode':kind,'server_id':2,'package_id':1,**kw}

def test_visibility_auth_and_three_enabled_choices(join,monkeypatch):
 c,sessions,config=join
 assert c.get('/api/miniapp/reseller-join').status_code==401
 r=c.get('/api/miniapp/reseller-join',headers=H)
 assert r.status_code==200,r.text
 assert r.json()['options']==['volume','panel','payg']
 config['reseller_join_volume_enabled']='0'
 assert 'volume' not in c.get('/api/miniapp/reseller-join',headers=H).json()['options']
 monkeypatch.setattr(flow,'get_user_button',AsyncMock(return_value=('request',False)))
 assert c.get('/api/miniapp/reseller-join',headers=H).status_code==409


def test_volume_payment_grants_exact_package_once_and_no_access_before_approval(join):
 c,sessions,config=join;b=request()
 q=c.post('/api/miniapp/reseller-join/quote',headers=H,json={'key':str(uuid.uuid4()),**b}).json()
 assert q['amount']==2000 and q['volume_bytes']==100*1024**3 and q['days']==30
 key=str(uuid.uuid4());body={**b,'key':key,'expected_amount':2000}
 r=c.post('/api/miniapp/reseller-join',headers=H,json=body);assert r.status_code==200,r.text
 oid=r.json()['id']
 assert c.post('/api/miniapp/reseller-join',headers=H,json=body).json()['id']==oid
 assert c.get(f'/api/miniapp/reseller-join/{oid}',headers={'X-Telegram-Init-Data':signed(22)}).status_code==404
 async def run():
  async with sessions() as s:
   assert await s.scalar(select(ResellerAccount)) is None
   op=await s.get(MiniAppOperation,oid)
   with pytest.raises(ValueError):await flow.approve(s,op,99,2,'volume')
   assert await flow.submit(s,op,'receipt') is True
   assert await flow.submit(s,op,'receipt') is False
   await s.commit()
   # A later package edit cannot change the already-paid quota or duration.
   pkg=await s.get(ResellerPackage,1);pkg.volume_gb=900;pkg.reseller_validity_days=3;await s.commit()
   await flow.approve(s,op,99,2,'volume');await s.commit()
   account=await s.scalar(select(ResellerAccount))
   assert account.is_active and account.total_bytes==100*1024**3 and account.billing_mode=='volume'
   assert (account.expires_at-op.created_at).days>=29
   with pytest.raises(ValueError):await flow.approve(s,op,99,2,'volume')
   assert account.total_bytes==100*1024**3
 asyncio.run(run())
 assert c.get('/api/miniapp/reseller-join',headers=H).json()['selected_mode']=='volume'
 assert c.post('/api/miniapp/reseller-join/quote',headers=H,json={'key':str(uuid.uuid4()),**request('payg')}).status_code==409


def test_config_payg_credits_minimum_wallet_and_locks_the_selected_mode(join):
 c,sessions,config=join
 async def run():
  async with sessions() as s:
   user=await s.get(User,1)
   q=await flow.quote(s,user,request('payg'));assert q['amount']==5000 and q['initial_credit']==5000
   op=await flow.checkout(s,user,str(uuid.uuid4()),request('payg'),5000)
   await flow.submit(s,op,'receipt');await flow.approve(s,op,99,2,'payg');await s.commit()
   account=await s.scalar(select(ResellerAccount));assert account.billing_mode=='payg' and account.wallet_balance_irt==5000
   assert (await profile(s,f'account:{account.id}'))['payg_rate']==20
   assert await s.scalar(select(func.count()).select_from(ResellerBillingEntry))==1
   with pytest.raises(ValueError):await flow.quote(s,user,request('volume'))
 asyncio.run(run())


@pytest.mark.parametrize('mode,package,amount',[('payg',0,2000),('volume',2,3000)])
def test_panel_invoice_credentials_and_initial_credit_commit_only_after_provisioning(join,monkeypatch,mode,package,amount):
 c,sessions,config=join
 from app.services.pasarguard_panel_sales import PanelResellerProvisioner
 from app.bot.handlers.admin import panel_reseller_sale as review
 monkeypatch.setattr(PanelResellerProvisioner,'username_available',AsyncMock(return_value=True))
 create=AsyncMock(return_value={'admin_id':44,'role_id':4});monkeypatch.setattr(PanelResellerProvisioner,'create_account',create)
 monkeypatch.setattr(review,'SessionLocal',sessions);monkeypatch.setattr(review,'_deliver',AsyncMock(return_value=True))
 monkeypatch.setattr(review,'_owner',lambda callback:True)
 b=request('panel',mode=mode,server_id=3,package_id=package,username='NewReseller',password='AbCd12!secure')
 async def run():
  async with sessions() as s:
   user=await s.get(User,1);q=await flow.quote(s,user,b)
   assert q['amount']==amount and q['setup_amount']==0 and q['card']['number']=='2222'
   op=await flow.checkout(s,user,str(uuid.uuid4()),b,amount)
   assert 'password' not in op.payload['request'] and op.payload['password_encrypted']!=b['password']
   await flow.submit(s,op,'receipt');order=await flow.approve(s,op,99,3,mode);await s.commit()
   assert user.wallet_balance==250000 and op.status=='processing'
   return op.id,order.id
 oid,pid=asyncio.run(run())
 bot=SimpleNamespace(send_message=AsyncMock())
 callback=SimpleNamespace(from_user=SimpleNamespace(id=99),data=f'pgadmin:approve:{pid}',answer=AsyncMock(),message=SimpleNamespace(bot=bot,answer=AsyncMock(),edit_reply_markup=AsyncMock()))
 asyncio.run(review.panel_sale_approve(callback))
 async def check():
  async with sessions() as s:
   op=await s.get(MiniAppOperation,oid);assert op.status=='done',op.result
   user=await s.get(User,1);finance=await profile(s,'panels:1');assert finance['billing_mode']==mode
   if mode=='payg':assert user.wallet_balance==252000
   else:assert user.wallet_balance==250000 and finance['available_bytes']==100*1024**3
 asyncio.run(check());asyncio.run(review.panel_sale_approve(callback));create.assert_awaited_once()


def test_initial_charge_math_price_change_and_cancel_releases_mode(join):
 c,sessions,config=join
 config['pasarguard_panel_sales_min_initial_gb']='150';config['pasarguard_panel_sales_price_irt']='500'
 async def run():
  async with sessions() as s:
   user=await s.get(User,1)
   q=await flow.quote(s,user,request('panel',mode='payg',server_id=3,package_id=0))
   assert q['amount']==3500 and q['initial_credit']==3000
   with pytest.raises(ValueError,match='قیمت'):
    await flow.checkout(s,user,str(uuid.uuid4()),request(),100)
 asyncio.run(run())
 key=str(uuid.uuid4());r=c.post('/api/miniapp/reseller-join',headers=H,json={'key':key,**request(),'expected_amount':2000})
 oid=r.json()['id'];assert c.post(f'/api/miniapp/reseller-join/{oid}/cancel',headers=H,json={}).status_code==200
 assert 'payg' in c.get('/api/miniapp/reseller-join',headers=H).json()['options']


def test_pending_panel_name_reserved_across_users_and_not_exposed(join,monkeypatch):
 _,sessions,_=join
 from app.services.pasarguard_panel_sales import PanelResellerProvisioner
 monkeypatch.setattr(PanelResellerProvisioner,'username_available',AsyncMock(return_value=True))
 async def run():
  async with sessions() as s:
   user=await s.get(User,1);other=await s.get(User,2)
   b=request('panel',mode='payg',server_id=3,username='NewReseller',password='AbCd12!secure')
   op=await flow.checkout(s,user,str(uuid.uuid4()),b,2000);await s.commit()
   data=flow.view(op)
   assert 'password_encrypted' not in data['quote'] and 'request' not in data['quote']
   assert b['password'] not in str(data)
   with pytest.raises(ValueError,match='رزرو'):
    await flow.checkout(s,other,str(uuid.uuid4()),{**b,'username':'newreseller'},2000)
 asyncio.run(run())


def test_receipt_upload_stays_native_and_only_submitted_receipts_await_approval(join,monkeypatch):
 import io
 from contextlib import asynccontextmanager
 from PIL import Image
 c,sessions,_=join
 from app.core.config import settings
 monkeypatch.setattr(settings,'OWNER_IDS','99')
 bot=SimpleNamespace(send_photo=AsyncMock(return_value=SimpleNamespace(photo=[SimpleNamespace(file_id='uploaded-receipt')],message_id=42)),send_message=AsyncMock(),send_document=AsyncMock())
 @asynccontextmanager
 async def fake_bot():yield bot
 monkeypatch.setattr(api,'telegram_bot',fake_bot)
 body={'key':str(uuid.uuid4()),**request(),'expected_amount':2000}
 op=c.post('/api/miniapp/reseller-join',headers=H,json=body).json()
 assert op['status']=='waiting_receipt' and not bot.send_message.called
 out=io.BytesIO();Image.new('RGB',(300,400),'white').save(out,'PNG')
 endpoint=f"/api/miniapp/reseller-join/{op['id']}/receipt"
 assert c.post(endpoint,headers=H,files={'file':('invalid.txt',b'invalid','text/plain')}).status_code==422
 r=c.post(endpoint,headers=H,files={'file':('receipt.png',out.getvalue(),'image/png')})
 assert r.status_code==200 and r.json()['status']=='pending',r.text
 assert all(call.args[0]==99 for call in bot.send_photo.call_args_list)
 # The user cannot alter or cancel a submitted financial request.
 assert c.post(f"/api/miniapp/reseller-join/{op['id']}/cancel",headers=H,json={}).status_code==409
 before=bot.send_photo.await_count
 assert c.post(endpoint,headers=H,files={'file':('receipt.png',out.getvalue(),'image/png')}).json()['status']=='pending'
 assert bot.send_photo.await_count==before


def test_interrupted_panel_provisioning_is_held_for_review_without_replay(join):
 from datetime import datetime,timedelta
 _,sessions,_=join
 async def run():
  async with sessions() as s:
   panel=PasarGuardPanelOrder(user_id=1,server_id=3,username='pending',password_encrypted='encrypted',amount_irt=2000,receipt_file_id='receipt',status='processing')
   s.add(panel);await s.flush()
   op=MiniAppOperation(user_id=1,key=str(uuid.uuid4()),kind=flow.KIND,status='processing',payload={'mode':'payg'},result={'panel_id':panel.id},updated_at=datetime.utcnow()-timedelta(minutes=16))
   s.add(op);await s.commit()
   await flow.recover(s);await s.commit()
   assert op.status=='review' and panel.status=='review_required'
   assert (await s.get(User,1)).wallet_balance==250000
   assert await s.scalar(select(func.count()).select_from(ResellerBillingEntry))==0
 asyncio.run(run())


def test_admin_review_lists_persisted_receipts_and_activates_without_quota_or_date_inputs(join,monkeypatch):
 from contextlib import asynccontextmanager
 from app.api import admin_web
 from app.services import reseller_billing
 from app.core.config import settings
 _,sessions,_=join
 monkeypatch.setattr(admin_web,'SessionLocal',sessions);monkeypatch.setattr(reseller_billing,'SessionLocal',sessions)
 monkeypatch.setattr(admin_web,'_settings_map',AsyncMock(return_value={}))
 monkeypatch.setattr(settings,'OWNER_IDS','99')
 bot=SimpleNamespace(send_message=AsyncMock())
 @asynccontextmanager
 async def fake_bot():yield bot
 import app.api.miniapp as main
 monkeypatch.setattr(main,'telegram_bot',fake_bot)
 async def seed():
  async with sessions() as s:
   user=await s.get(User,1);op=await flow.checkout(s,user,str(uuid.uuid4()),request(),2000)
   await flow.submit(s,op,'receipt');await s.commit();return op.id
 oid=asyncio.run(seed())
 app=FastAPI();app.include_router(admin_web.router);app.dependency_overrides[admin_web._auth_user]=lambda:'admin'
 with TestClient(app) as c:
  r=c.get('/admin/api/v2/reseller-onboarding')
  assert r.status_code==200 and r.json()['ok'] and r.json()['requests'][0]['id']==oid,r.text
  headers={'Accept':'application/json'}
  bad=c.post(f'/admin/reseller-onboarding/{oid}/approve',headers=headers,data={'server_id':3,'mode':'volume'})
  assert bad.status_code==409,bad.text
  r=c.post(f'/admin/reseller-onboarding/{oid}/approve',headers=headers,data={'server_id':2,'mode':'volume'})
  assert r.status_code==200,r.text
  assert not c.get('/admin/api/v2/reseller-onboarding').json()['requests']
  assert c.post(f'/admin/reseller-onboarding/{oid}/approve',headers=headers,data={'server_id':2,'mode':'volume'}).status_code==409
 bot.send_message.assert_awaited_once()


def test_pending_panel_password_survives_portable_backup_to_a_new_installation(join,monkeypatch):
 from app.api import admin_web
 from app.core import security
 from cryptography.fernet import Fernet
 _,sessions,_=join
 monkeypatch.setattr(admin_web,'SessionLocal',sessions)
 async def run():
  async with sessions() as s:
   op=MiniAppOperation(user_id=1,key=str(uuid.uuid4()),kind=flow.KIND,status='waiting_receipt',payload={'password_encrypted':security.encrypt_text('AbCd12!secure'),'request':{'username':'newpanel'}})
   s.add(op);await s.commit();return op.id,op.payload['password_encrypted']
 oid,source_cipher=asyncio.run(run())
 backup=asyncio.run(admin_web._export_backup_payload())
 pending=next(row for row in backup['miniapp_operations'] if row['id']==oid)
 assert pending['payload']['password_encrypted']!=source_cipher and 'AbCd12!secure' not in str(backup)
 monkeypatch.setattr(security,'fernet',Fernet(Fernet.generate_key()))
 restored=admin_web._prepare_backup_for_restore(backup)
 pending=next(row for row in restored['miniapp_operations'] if row['id']==oid)
 assert security.decrypt_text(pending['payload']['password_encrypted'])=='AbCd12!secure'
