import asyncio,io,uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from PIL import Image
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select,func
from test_miniapp import client,signed
from app.api import miniapp_checkout as checkout
from app.database.models import User,Order,Plan,Server,PaymentCard,DiscountCode,DiscountUsage,WalletTransaction,ClientService

@pytest.fixture
def native(client,monkeypatch):
 _,sessions=client
 import app.bot.handlers.public.buy as buy
 monkeypatch.setattr(checkout,'SessionLocal',sessions)
 monkeypatch.setattr(buy,'SessionLocal',sessions)
 monkeypatch.setattr(buy,'get_service_username_error',AsyncMock(return_value=None))
 monkeypatch.setattr(buy.settings,'ADMIN_IDS','99')
 monkeypatch.setattr(buy.settings,'OWNER_IDS','')
 bot=SimpleNamespace(send_photo=AsyncMock(return_value=SimpleNamespace(photo=[SimpleNamespace(file_id='uploaded-receipt')],message_id=123)),send_message=AsyncMock(return_value=SimpleNamespace(message_id=124)),edit_message_reply_markup=AsyncMock())
 @asynccontextmanager
 async def fake_bot():yield bot
 monkeypatch.setattr(checkout,'telegram_bot',fake_bot)
 async def seed():
  async with sessions() as s:
   s.add(PaymentCard(id=1,server_type='xui',server_id=1,card_number='6037000000000001',owner_name='Seller',reviewer_telegram_id=77,is_active=True))
   s.add(DiscountCode(id=1,code='SAVE',discount_type='fixed',value=9000,max_uses=2,per_user_limit=1,is_active=True))
   await s.commit()
 asyncio.run(seed())
 app=FastAPI();app.include_router(checkout.router)
 with TestClient(app) as api:yield api,sessions,bot,buy

H={'X-Telegram-Init-Data':signed()}
def body(method='wallet',**extra):return dict(plan_id=1,username='native_customer',method=method,key=str(uuid.uuid4()),expected_amount_irt=139000,**extra)
def image_bytes():
 out=io.BytesIO();Image.new('RGB',(400,600),'white').save(out,'PNG');return out.getvalue()

def test_quote_auth_live_catalog_and_server_side_totals(native):
 c,sessions,bot,buy=native
 assert c.post('/api/miniapp/checkout/quote',json={'plan_id':1,'username':'native'}).status_code==401
 q=c.post('/api/miniapp/checkout/quote',headers=H,json={'plan_id':1,'username':'native','discount_code':'SAVE'})
 assert q.status_code==200,q.text
 assert q.json()['amount_irt']==130000 and q.json()['methods']==['wallet','card']
 assert c.post('/api/miniapp/checkout/quote',headers=H,json={'plan_id':2,'username':'native'}).status_code==404
 buy.get_service_username_error.return_value='نام تکراری'
 assert c.post('/api/miniapp/checkout/quote',headers=H,json={'plan_id':1,'username':'native'}).status_code==409

def test_wallet_double_submit_charges_and_provisions_once(native,monkeypatch):
 c,sessions,bot,buy=native
 payload=body()
 r=c.post('/api/miniapp/checkout',json=payload,headers=H);assert r.status_code==200,r.text
 oid=r.json()['id'];assert r.json()['status']=='miniapp_queued'
 assert c.post('/api/miniapp/checkout',json=payload,headers=H).json()['id']==oid
 for name in ['send_buyer_notice','notify_paid_order','send_service_card','send_service_success_notice','send_home','send_admin_notice','edit_admin_receipt_keyboard','report_bot_error']:
  monkeypatch.setattr(buy,name,AsyncMock())
 monkeypatch.setattr(buy,'apply_purchase_commission',AsyncMock(return_value=0))
 async def build(s,user,server,plan,name,password=None):
  svc=ClientService(user_id=user.id,server_id=server.id,plan_id=plan.id,client_username=name,xui_email=name,total_bytes=30*1024**3,sub_link='https://example.com/sub/native')
  s.add(svc);await s.flush();return svc,svc.sub_link
 create=AsyncMock(side_effect=build);monkeypatch.setattr(buy,'build_service',create)
 asyncio.run(checkout.process_wallet_queue());asyncio.run(checkout.process_wallet_queue())
 assert create.await_count==1
 result=c.get(f'/api/miniapp/checkout/orders/{oid}',headers=H).json()
 assert result['status']=='paid' and result['service']['username']=='native_customer'
 assert c.post('/api/miniapp/checkout',json=payload,headers=H).json()['status']=='paid'
 async def verify():
  async with sessions() as s:
   assert (await s.get(User,1)).wallet_balance==111000
   assert await s.scalar(select(func.count(WalletTransaction.id)))==1
 asyncio.run(verify())
 assert buy.notify_paid_order.await_count==1

def test_price_tampering_and_insufficient_wallet_do_not_create_orders(native):
 c,sessions,_,_=native
 payload=body();payload['expected_amount_irt']=1
 assert c.post('/api/miniapp/checkout',headers=H,json=payload).status_code==409
 async def empty():
  async with sessions() as s:
   u=await s.get(User,1);u.wallet_balance=0;await s.commit()
 asyncio.run(empty());payload['expected_amount_irt']=139000
 assert c.post('/api/miniapp/checkout',headers=H,json=payload).status_code==409
 async def verify():
  async with sessions() as s:assert await s.scalar(select(func.count(Order.id)).where(Order.checkout_key.is_not(None)))==0
 asyncio.run(verify())

def test_receipt_upload_is_owned_idempotent_and_never_auto_approves(native):
 c,sessions,bot,buy=native
 r=c.post('/api/miniapp/checkout',headers=H,json=body('card'));assert r.status_code==200,r.text
 order=r.json();oid=order['id'];assert order['card']['number']=='6037000000000001'
 other={'X-Telegram-Init-Data':signed(22)}
 assert c.get(f'/api/miniapp/checkout/orders/{oid}',headers=other).status_code==404
 assert c.post(f'/api/miniapp/checkout/orders/{oid}/receipt',headers=other,files={'file':('a.png',image_bytes(),'image/png')}).status_code==404
 assert c.post(f'/api/miniapp/checkout/orders/{oid}/receipt',headers=H,files={'file':('fake.png',b'not-image','image/png')}).status_code==422
 upload=lambda:c.post(f'/api/miniapp/checkout/orders/{oid}/receipt',headers=H,files={'file':('proof.png',image_bytes(),'image/png')})
 r=upload();assert r.status_code==200,r.text
 assert r.json()['status']=='waiting_receipt' and r.json()['receipt_uploaded'] and not r.json()['service']
 count=bot.send_photo.await_count
 assert upload().json()['receipt_uploaded'] and bot.send_photo.await_count==count
 assert bot.send_photo.await_args_list[0].args[0]==77
 assert 'native_customer' in bot.send_photo.await_args_list[0].kwargs['caption']
 assert '11' in bot.send_photo.await_args_list[0].kwargs['caption']
 assert c.post(f'/api/miniapp/checkout/orders/{oid}/cancel',headers=H,json={}).status_code==409


def test_discount_cancel_releases_exactly_one_reservation(native):
 c,sessions,_,_=native
 payload=body('card',discount_code='SAVE');payload['expected_amount_irt']=130000
 r=c.post('/api/miniapp/checkout',headers=H,json=payload);assert r.status_code==200,r.text
 oid=r.json()['id']
 async def used(n):
  async with sessions() as s:assert (await s.get(DiscountCode,1)).used_count==n
 asyncio.run(used(1))
 for _ in range(2):assert c.post(f'/api/miniapp/checkout/orders/{oid}/cancel',headers=H,json={}).json()['status']=='cancelled'
 asyncio.run(used(0))
 assert c.get('/api/miniapp/checkout/orders',headers={'X-Telegram-Init-Data':signed(22)}).json()['orders']==[]


def test_wallet_provider_failure_keeps_one_debit_and_no_automatic_retry(native,monkeypatch):
 c,sessions,_,buy=native
 payload=body();oid=c.post('/api/miniapp/checkout',headers=H,json=payload).json()['id']
 for name in ['send_buyer_notice','notify_paid_order','send_service_card','send_service_success_notice','send_home','send_admin_notice','edit_admin_receipt_keyboard','report_bot_error']:
  monkeypatch.setattr(buy,name,AsyncMock())
 create=AsyncMock(side_effect=RuntimeError('provider offline'));monkeypatch.setattr(buy,'build_service',create)
 asyncio.run(checkout.process_wallet_queue());asyncio.run(checkout.process_wallet_queue())
 assert create.await_count==1
 result=c.get(f'/api/miniapp/checkout/orders/{oid}',headers=H).json()
 assert result['status']=='failed' and result['service'] is None
 assert c.post('/api/miniapp/checkout',headers=H,json=payload).json()['id']==oid
 async def verify():
  async with sessions() as s:
   assert (await s.get(User,1)).wallet_balance==111000
   assert await s.scalar(select(func.count(WalletTransaction.id)))==1
 asyncio.run(verify())


def test_card_receipt_approval_provisions_and_returns_native_service(native,monkeypatch):
 c,sessions,bot,buy=native
 oid=c.post('/api/miniapp/checkout',headers=H,json=body('card')).json()['id']
 for name in ['send_buyer_notice','notify_paid_order','send_service_card','send_service_success_notice','send_home','send_admin_notice','edit_admin_receipt_keyboard','report_bot_error']:
  monkeypatch.setattr(buy,name,AsyncMock())
 monkeypatch.setattr(buy,'apply_purchase_commission',AsyncMock(return_value=0))
 async def build(s,user,server,plan,name,password=None):
  svc=ClientService(user_id=user.id,server_id=server.id,plan_id=plan.id,client_username=name,xui_email=name,sub_link='happ://crypt5/native')
  s.add(svc);await s.flush();return svc,svc.sub_link
 create=AsyncMock(side_effect=build);monkeypatch.setattr(buy,'build_service',create)
 callback=SimpleNamespace(data=f'order:approve:{oid}',from_user=SimpleNamespace(id=99),message=SimpleNamespace(bot=bot,chat=SimpleNamespace(id=99),message_id=123),answer=AsyncMock())
 monkeypatch.setattr(buy,'safe_callback_answer',AsyncMock())
 asyncio.run(buy.approve_order_cb(callback))
 assert buy.safe_callback_answer.await_args.args[1]=='هنوز رسیدی برای این سفارش ارسال نشده است.'
 assert create.await_count==0
 assert c.post(f'/api/miniapp/checkout/orders/{oid}/receipt',headers=H,files={'file':('a.png',image_bytes(),'image/png')}).status_code==200
 # This is the existing owner approval's provisioning path, not a customer action.
 asyncio.run(buy.process_approved_order_background(oid,bot))
 asyncio.run(buy.process_approved_order_background(oid,bot))
 result=c.get(f'/api/miniapp/checkout/orders/{oid}',headers=H).json()
 assert result['status']=='paid' and result['service']['username']=='native_customer'
 assert create.await_count==1


def test_interrupted_wallet_mutation_requires_review_not_automatic_recreation(native):
 from datetime import datetime,timedelta
 c,sessions,bot,buy=native
 oid=c.post('/api/miniapp/checkout',headers=H,json=body()).json()['id']
 async def interrupted():
  async with sessions() as s:
   o=await s.get(Order,oid);o.status='processing';o.pricing_meta={**o.pricing_meta,'miniapp_processing_at':(datetime.utcnow()-timedelta(minutes=16)).isoformat()};await s.commit()
 asyncio.run(interrupted());asyncio.run(checkout.recover_stalled_wallet_orders());asyncio.run(checkout.process_wallet_queue())
 assert c.get(f'/api/miniapp/checkout/orders/{oid}',headers=H).json()['status']=='failed'
 assert bot.send_message.await_count==1
 async def verify():
  async with sessions() as s:assert await s.scalar(select(func.count(WalletTransaction.id)))==1
 asyncio.run(verify())


def test_pending_service_password_is_portable_between_installation_keys(native,monkeypatch):
 from cryptography.fernet import Fernet
 from app.core import security
 from app.api import admin_web as web
 c,sessions,_,_=native
 monkeypatch.setattr(web,'SessionLocal',sessions)
 source=Fernet(Fernet.generate_key());destination=Fernet(Fernet.generate_key())
 monkeypatch.setattr(security,'fernet',source)
 oid=c.post('/api/miniapp/checkout',headers=H,json=body('card')).json()['id']
 async def store():
  async with sessions() as s:
   order=await s.get(Order,oid);order.pricing_meta={**order.pricing_meta,'miniapp_password':security.encrypt_text('NativePassword!')};await s.commit()
 asyncio.run(store())
 payload=asyncio.run(web._export_backup_payload())
 exported=next(o for o in payload['orders'] if o['id']==oid)
 assert exported['pricing_meta']['miniapp_password'].startswith('dbot-portable-v1:')
 monkeypatch.setattr(security,'fernet',destination)
 restored=web._prepare_backup_for_restore(payload)
 order=next(o for o in restored['orders'] if o['id']==oid)
 assert security.decrypt_text(order['pricing_meta']['miniapp_password'])=='NativePassword!'


def test_completed_purchase_link_is_delivered_even_when_service_tab_is_hidden(native,monkeypatch):
 from fastapi import HTTPException
 from app.api import miniapp
 c,sessions,_,_=native
 oid=c.post('/api/miniapp/checkout',headers=H,json=body('card')).json()['id']
 async def paid():
  async with sessions() as s:
   order=await s.get(Order,oid);order.status='paid';order.service_id=1;await s.commit()
 asyncio.run(paid())
 monkeypatch.setattr(miniapp,'require_button',AsyncMock(side_effect=HTTPException(403,'hidden')))
 app=FastAPI();app.include_router(miniapp.router)
 with TestClient(app) as api:
  assert api.get('/api/miniapp/services/1/link',headers=H).json()['link']=='https://example.com/sub/mine'
  assert api.get('/api/miniapp/services/1/link',headers={'X-Telegram-Init-Data':signed(22)}).status_code==403


def test_latest_order_includes_chat_orders_and_is_private(native):
 c,sessions,bot,buy=native
 assert c.get('/api/miniapp/orders/latest').status_code==401
 assert c.get('/api/miniapp/orders/latest',headers=H).json()['order']['id']==1
 assert c.get('/api/miniapp/orders/latest',headers={'X-Telegram-Init-Data':signed(22)}).json()['order'] is None
 created=c.post('/api/miniapp/checkout',headers=H,json=body('card')).json()
 # A card checkout is private draft state until its receipt reaches the reviewer.
 assert c.get('/api/miniapp/orders/latest',headers=H).json()['order']['id']==1
 assert c.post(f'/api/miniapp/checkout/orders/{created["id"]}/receipt',headers=H,files={'file':('receipt.png',image_bytes(),'image/png')}).status_code==200
 assert c.get('/api/miniapp/orders/latest',headers=H).json()['order']['id']==created['id']


def test_resend_only_pending_receipt_owned_order_without_recharging(native):
 c,sessions,bot,buy=native
 created=c.post('/api/miniapp/checkout',headers=H,json=body('card')).json();oid=created['id']
 url=f'/api/miniapp/orders/{oid}/resend'
 assert c.post(url,headers=H,json={}).status_code==409
 assert c.post(url,headers={'X-Telegram-Init-Data':signed(22)},json={}).status_code==404
 assert c.post(url,json={}).status_code==401
 assert c.post(f'/api/miniapp/checkout/orders/{oid}/receipt',headers=H,files={'file':('receipt.png',image_bytes(),'image/png')}).status_code==200
 bot.send_photo.reset_mock();bot.send_message.reset_mock()
 r=c.post(url,headers=H,json={});assert r.status_code==200,r.text
 assert r.json()['order']['status']=='waiting_receipt'
 assert bot.send_photo.await_count>0
 assert bot.send_photo.call_args.args[1]=='uploaded-receipt'
 assert 'order:approve:'+str(oid) in str(bot.send_message.call_args.kwargs['reply_markup'])
 calls=bot.send_photo.await_count
 assert c.post(url,headers=H,json={}).status_code==429
 assert bot.send_photo.await_count==calls
 async def check():
  async with sessions() as s:
   assert (await s.get(User,1)).wallet_balance==250000
   assert await s.scalar(select(func.count(WalletTransaction.id)))==0
   order=await s.get(Order,oid);order.status='paid';await s.commit()
 asyncio.run(check())
 assert c.post(url,headers=H,json={}).status_code==409


def test_resend_failure_is_retryable_and_chat_order_supported(native):
 c,sessions,bot,buy=native
 async def seed():
  async with sessions() as s:
   s.add(Order(id=99,user_id=1,plan_id=1,amount_irt=139000,payment_method='card:ChatBuyer',status='waiting_receipt',receipt_file_id='chat-receipt'))
   await s.commit()
 asyncio.run(seed())
 bot.send_photo.side_effect=RuntimeError('offline')
 url='/api/miniapp/orders/99/resend'
 assert c.post(url,headers=H,json={}).status_code==503
 bot.send_photo.side_effect=None
 assert c.post(url,headers=H,json={}).status_code==200
 assert c.get('/api/miniapp/orders/latest',headers=H).json()['order']['id']==99
