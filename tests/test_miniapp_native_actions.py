import asyncio,uuid,io
from contextlib import asynccontextmanager
from datetime import datetime,timedelta,timezone
from unittest.mock import AsyncMock
import pytest
from PIL import Image
from fastapi import FastAPI
from fastapi.testclient import TestClient
from aiogram import Bot
from aiogram.types import Message,Chat
from sqlalchemy import select,func
from test_miniapp import client,signed,TOKEN
from app.api import miniapp_actions as actions,miniapp_payments as payments,miniapp_checkout as checkout
from app.database.models import User,ResellerAccount,ResellerPackage,PaymentCard,Server,ClientService,MiniAppOperation,ResellerTopupRequest,ResellerWalletReceipt,WalletTransaction,Order,Plan,ResellerServiceActivity

H={'X-Telegram-Init-Data':signed()}
OTHER={'X-Telegram-Init-Data':signed(22)}
GB=1024**3

@pytest.fixture
def native(client,monkeypatch):
 _,sessions=client
 from app.bot.handlers.public import reseller as flow,buy
 from app.bot import service_presenter
 from app.services import reseller_service
 from app.database import session as db_session
 for module in [actions,payments,checkout,flow,buy,db_session]:monkeypatch.setattr(module,'SessionLocal',sessions)
 monkeypatch.setattr(flow,'sync_all_reseller_services',AsyncMock())
 monkeypatch.setattr(flow,'get_reseller_username_error',AsyncMock(return_value=None))
 monkeypatch.setattr(flow,'resolve_reseller_username',AsyncMock(side_effect=lambda s,server,name:(name,False)))
 monkeypatch.setattr(flow.settings,'ADMIN_IDS','99');monkeypatch.setattr(flow.settings,'OWNER_IDS','')
 real=Bot(TOKEN);calls=[]
 async def request(bot,method,timeout=None):
  calls.append(method)
  return Message(message_id=123,date=datetime.now(timezone.utc),chat=Chat(id=int(getattr(method,'chat_id',99)),type='private'),text=getattr(method,'text',None),photo=[dict(file_id='stored-receipt',file_unique_id='unique',width=400,height=600)])
 monkeypatch.setattr(real.session,'make_request',request)
 @asynccontextmanager
 async def bot():yield real
 for module in [actions,payments,checkout]:monkeypatch.setattr(module,'telegram_bot',bot)
 async def seed():
  async with sessions() as s:
   srv=await s.get(Server,2);srv.meta={'scope':'reseller','reseller_billing_modes':['volume','payg'],'reseller_payg_rate_irt':3000}
   s.add_all([ResellerAccount(id=1,user_id=1,server_id=2,allowed_server_ids=[2],total_bytes=100*GB,expires_at=datetime.utcnow()+timedelta(days=30)),
    ResellerPackage(id=1,title='100GB reseller',server_id=2,volume_gb=100,price_irt=90000),
    PaymentCard(id=1,server_type='reseller',card_number='6037000000000001',owner_name='Admin',is_active=True)])
   await s.commit()
 asyncio.run(seed())
 app=FastAPI()
 for router in [actions.router,payments.router,checkout.router]:app.include_router(router)
 with TestClient(app) as c:yield c,sessions,real,calls,flow,buy
 asyncio.run(real.session.close())

def action(kind='create',**kwargs):return dict(key=str(uuid.uuid4()),action=kind,confirmed=True,server_id=2,username='MiniCustomer',volume=20,days=30,hwid_limit=1,**kwargs)

def test_reseller_auth_server_scope_and_idempotency(native):
 c,sessions,real,calls,flow,buy=native
 assert c.get('/api/miniapp/reseller/catalog',headers=H).status_code==200
 assert c.get('/api/miniapp/reseller/catalog',headers=OTHER).status_code==403
 b=action();bad={**b,'server_id':1}
 assert c.post('/api/miniapp/reseller/actions',json=bad,headers=H).status_code==403
 assert c.post('/api/miniapp/reseller/actions',json=b).status_code==401
 r=c.post('/api/miniapp/reseller/actions',json=b,headers=H);assert r.status_code==200,r.text
 oid=r.json()['id']
 assert c.post('/api/miniapp/reseller/actions',json=b,headers=H).json()['id']==oid
 assert c.post('/api/miniapp/reseller/actions',json={**b,'volume':50},headers=H).status_code==409
 assert c.get(f'/api/miniapp/operations/{oid}',headers=OTHER).status_code==404
 assert c.post('/api/miniapp/reseller/actions',json=action(),headers=H).status_code==409
 assert not calls

def test_reseller_create_uses_existing_accounting_once_and_only_delivers_completed_config(native,monkeypatch):
 c,sessions,real,calls,flow,buy=native
 create=AsyncMock(return_value={'sub_link':'https://example.com/sub/new','uuid':'new-uuid','inbound_ids':[1]})
 monkeypatch.setattr(flow.XuiService,'create_client_on_inbounds',create)
 delivery=AsyncMock();monkeypatch.setattr(actions,'deliver_subscription',delivery)
 b=action();r=c.post('/api/miniapp/reseller/actions',json=b,headers=H);oid=r.json()['id']
 asyncio.run(actions.process_operations());asyncio.run(actions.process_operations())
 result=c.get(f'/api/miniapp/operations/{oid}',headers=H).json()
 assert result['status']=='done',result
 assert result['result']['service']['username']=='MiniCustomer'
 assert create.await_count==1 and delivery.await_count==1
 assert all(getattr(m,'chat_id',None)!=11 for m in calls)
 async def check():
  async with sessions() as s:
   account=await s.get(ResellerAccount,1)
   assert account.total_bytes==80*GB and account.reserved_bytes==20*GB
   assert await s.scalar(select(func.count(ResellerServiceActivity.id)).where(ResellerServiceActivity.action=='create'))==1
 asyncio.run(check())
 assert c.post('/api/miniapp/reseller/actions',json=b,headers=H).json()['status']=='done'
 asyncio.run(actions.process_operations());assert create.await_count==1

@pytest.mark.parametrize('kind',['add_volume','add_days','renew'])
def test_reseller_existing_config_mutations_stay_native(native,monkeypatch,kind):
 c,sessions,real,calls,flow,buy=native
 async def seed():
  async with sessions() as s:
   s.add(ClientService(id=3,user_id=1,reseller_id=1,server_id=2,client_username='Customer',xui_email='Customer',total_bytes=30*GB,used_bytes=10*GB,reseller_reserved_bytes=30*GB,expires_at=datetime.utcnow()+timedelta(days=10)))
   await s.commit()
 asyncio.run(seed())
 monkeypatch.setattr(flow.XuiService,'add_client_volume',AsyncMock())
 monkeypatch.setattr(flow.XuiService,'add_client_days',AsyncMock())
 monkeypatch.setattr(flow.XuiService,'renew_reseller_client_any',AsyncMock(return_value={'found':{'traffic':{'up':0,'down':0}}}))
 monkeypatch.setattr(actions,'deliver_subscription',AsyncMock())
 b=action(kind,service_id=3);r=c.post('/api/miniapp/reseller/actions',json=b,headers=H);assert r.status_code==200,r.text
 asyncio.run(actions.process_operations());result=c.get(f"/api/miniapp/operations/{r.json()['id']}",headers=H).json();assert result['status']=='done',result
 assert not any(getattr(m,'chat_id',None)==11 for m in calls)
 async def check():
  async with sessions() as s:
   svc=await s.get(ClientService,3);account=await s.get(ResellerAccount,1)
   if kind=='add_volume':assert svc.total_bytes==50*GB and account.total_bytes==80*GB
   if kind=='renew':assert svc.total_bytes==20*GB and svc.used_bytes==0 and account.total_bytes==100*GB
   if kind=='add_days':assert svc.expires_at>datetime.utcnow()+timedelta(days=39)
 asyncio.run(check())

def test_public_hwid_rotates_and_delivers_once_and_revoke_is_owned(native,monkeypatch):
 c,sessions,real,calls,flow,buy=native
 clear=AsyncMock();revoke=AsyncMock(return_value={'uuid':'new','sub_link':'https://example.com/new'})
 monkeypatch.setattr(flow.XuiService,'clear_client_hwids',clear)
 monkeypatch.setattr(flow.XuiService,'revoke_and_new_link',revoke)
 monkeypatch.setattr(flow.XuiService,'resolve_service_subscription',AsyncMock(return_value='https://example.com/new'))
 delivery=AsyncMock();monkeypatch.setattr(actions,'deliver_subscription',delivery)
 for name,method in [('hwid',clear),('revoke',revoke)]:
  b=action(name)
  assert c.post('/api/miniapp/services/2/actions',headers=H,json=b).status_code==404
  r=c.post('/api/miniapp/services/1/actions',headers=H,json=b);assert r.status_code==200,r.text
  asyncio.run(actions.process_operations());asyncio.run(actions.process_operations())
  assert c.get(f"/api/miniapp/operations/{r.json()['id']}",headers=H).json()['status']=='done'
  assert method.await_count==(1 if name=='hwid' else 2)
 delivery.assert_awaited_once()
 assert not calls

def funding(kind='reseller_package',method='wallet'):
 return dict(key=str(uuid.uuid4()),kind=kind,package_id=1,amount=100000,method=method,expected_amount=90000 if kind=='reseller_package' else 100000)

def test_volume_package_wallet_payment_is_idempotent(native):
 c,sessions,real,calls,flow,buy=native
 b=funding();r=c.post('/api/miniapp/funding',headers=H,json=b);assert r.status_code==200,r.text
 assert r.json()['status']=='paid'
 assert c.post('/api/miniapp/funding',headers=H,json=b).json()['id']==r.json()['id']
 assert c.get(f"/api/miniapp/funding/{r.json()['id']}",headers=OTHER).status_code==404
 async def check():
  async with sessions() as s:
   assert (await s.get(User,1)).wallet_balance==160000
   assert (await s.get(ResellerAccount,1)).total_bytes==200*GB
   assert await s.scalar(select(func.count(WalletTransaction.id)))==1
 asyncio.run(check())
 assert all(getattr(m,'chat_id',None)!=11 for m in calls)

def test_payg_transfer_credits_separate_wallet_once(native):
 c,sessions,real,calls,flow,buy=native
 async def change():
  async with sessions() as s:
   a=await s.get(ResellerAccount,1);a.billing_mode='payg';await s.commit()
 asyncio.run(change())
 b=funding('reseller_wallet');r=c.post('/api/miniapp/funding',headers=H,json=b);assert r.status_code==200,r.text
 assert c.post('/api/miniapp/funding',headers=H,json=b).status_code==200
 async def check():
  async with sessions() as s:
   assert (await s.get(User,1)).wallet_balance==150000
   assert (await s.get(ResellerAccount,1)).wallet_balance_irt==100000
 asyncio.run(check())

def test_native_receipt_tracking_resend_and_approval(native):
 c,sessions,real,calls,flow,buy=native
 b=funding(method='card');r=c.post('/api/miniapp/funding',headers=H,json=b);assert r.status_code==200,r.text
 oid=r.json()['id'];url=f'/api/miniapp/funding/{oid}/receipt'
 out=io.BytesIO();Image.new('RGB',(400,600),'white').save(out,'PNG')
 assert c.post(url,headers=OTHER,files={'file':('r.png',out.getvalue(),'image/png')}).status_code==404
 r=c.post(url,headers=H,files={'file':('r.png',out.getvalue(),'image/png')});assert r.status_code==200,r.text
 assert r.json()['status']=='waiting_approval'
 assert any('resadmin:req_approve:' in str(getattr(m,'reply_markup',None)) for m in calls)
 assert c.post(url,headers=H,files={'file':('r.png',out.getvalue(),'image/png')}).status_code==200
 track=c.get('/api/miniapp/tracking',headers=H).json()['orders'];o=next(o for o in track if o['track_kind']=='funding');assert o['can_resend']
 resend=f'/api/miniapp/tracking/funding/{oid}/resend'
 assert c.post(resend,headers=H,json={}).status_code==200
 assert c.post(resend,headers=H,json={}).status_code==429
 async def approve():
  async with sessions() as s:
   op=await s.get(MiniAppOperation,oid);req=await s.get(ResellerTopupRequest,op.result['target_id'])
   from app.services.reseller_service import apply_package
   await apply_package(s,req);await s.commit()
   assert await s.scalar(select(func.count(ResellerTopupRequest.id)))==1
 asyncio.run(approve())
 assert c.get(f'/api/miniapp/funding/{oid}',headers=H).json()['status']=='paid'
 assert c.post(resend,headers=H,json={}).status_code==409
 assert all(getattr(m,'chat_id',None)!=11 for m in calls)

def test_renewal_catalog_and_queued_renewal_do_not_create_second_client(native,monkeypatch):
 c,sessions,real,calls,flow,buy=native
 monkeypatch.setattr(buy,'get_service_username_error',AsyncMock(side_effect=AssertionError('No duplicate check on renewal')))
 for n in ['send_buyer_notice','notify_paid_order','send_service_success_notice','send_home','send_admin_notice','edit_admin_receipt_keyboard','report_bot_error','send_service_card','send_renewal_confirmation']:
  monkeypatch.setattr(buy,n,AsyncMock())
 monkeypatch.setattr(buy,'apply_purchase_commission',AsyncMock(return_value=0))
 renew=AsyncMock(return_value={'inbound_ids':[1]});monkeypatch.setattr(buy.XuiService,'renew_client_on_plan',renew)
 r=c.get('/api/miniapp/services/1/renewal-plans',headers=H);assert r.status_code==200,r.text
 assert [p['id'] for p in r.json()['plans']]==[1]
 assert c.get('/api/miniapp/services/2/renewal-plans',headers=H).status_code==404
 b=dict(key=str(uuid.uuid4()),plan_id=1,service_id=1,username='mine',expected_amount_irt=139000,method='wallet')
 r=c.post('/api/miniapp/checkout',headers=H,json=b);assert r.status_code==200,r.text
 asyncio.run(checkout.process_wallet_queue());asyncio.run(checkout.process_wallet_queue())
 assert renew.await_count==1
 result=c.get(f"/api/miniapp/checkout/orders/{r.json()['id']}",headers=H).json();assert result['status']=='paid' and result['service']['id']==1,result
 assert buy.send_buyer_notice.await_count==0 and buy.send_service_success_notice.await_count==0
 assert buy.send_service_card.await_count==1
 async def check():
  async with sessions() as s:
   assert await s.scalar(select(func.count(ClientService.id)))==2
   assert (await s.get(User,1)).wallet_balance==111000
 asyncio.run(check())


def test_failed_remote_action_never_retries_automatically(native,monkeypatch):
 c,sessions,real,calls,flow,buy=native
 remote=AsyncMock(side_effect=TimeoutError('ambiguous panel response'))
 monkeypatch.setattr(flow.XuiService,'clear_client_hwids',remote)
 b=action('hwid');r=c.post('/api/miniapp/services/1/actions',headers=H,json=b)
 asyncio.run(actions.process_operations());asyncio.run(actions.process_operations())
 assert remote.await_count==1
 assert c.post('/api/miniapp/services/1/actions',headers=H,json=b).json()['status']=='failed'
 assert not calls


def test_stalled_operations_require_review_not_remote_retry(native):
 c,sessions,real,calls,flow,buy=native
 async def seed():
  async with sessions() as s:
   s.add(MiniAppOperation(id=99,user_id=1,key='stalled',kind='reseller_create',status='processing',updated_at=datetime.utcnow()-timedelta(minutes=20)))
   await s.commit()
 asyncio.run(seed());asyncio.run(actions.recover_operations());asyncio.run(actions.process_operations())
 assert c.get('/api/miniapp/operations/99',headers=H).json()['status']=='failed'
 assert not calls


def test_legacy_pending_receipt_resend_works_when_newer_order_is_paid(native):
 c,sessions,real,calls,flow,buy=native
 async def seed():
  async with sessions() as s:
   s.add_all([Order(id=10,user_id=1,plan_id=1,payment_method='card:Pending',amount_irt=100,status='waiting_receipt',receipt_file_id='old'),Order(id=11,user_id=1,plan_id=1,payment_method='wallet',amount_irt=100,status='paid')]);await s.commit()
 asyncio.run(seed())
 rows=c.get('/api/miniapp/tracking',headers=H).json()['orders']
 assert any(o['id']==10 and o['can_resend'] for o in rows)
 assert c.post('/api/miniapp/tracking/order/10/resend',headers=H,json={}).status_code==200
 assert c.post('/api/miniapp/tracking/order/10/resend',headers=OTHER,json={}).status_code==404
 assert not any(getattr(m,'chat_id',None)==11 for m in calls)


def test_actual_reseller_receipt_approval_does_not_send_chat_prompt_to_native_buyer(native,monkeypatch):
 c,sessions,real,calls,flow,buy=native
 from app.bot.handlers.admin import resellers as admin
 from app.services.miniapp_runtime import native_event
 from types import SimpleNamespace
 monkeypatch.setattr(admin,'SessionLocal',sessions)
 for n in ['mark_message_status','notify_receipt_review','send_reseller_home','edit_or_answer']:monkeypatch.setattr(admin,n,AsyncMock())
 b=funding(method='card');oid=c.post('/api/miniapp/funding',headers=H,json=b).json()['id']
 out=io.BytesIO();Image.new('RGB',(400,600),'white').save(out,'PNG')
 c.post(f'/api/miniapp/funding/{oid}/receipt',headers=H,files={'file':('r.png',out.getvalue(),'image/png')})
 async def approve():
  async with sessions() as s:
   op=await s.get(MiniAppOperation,oid);rid=op.result['target_id']
  # Native event only suppresses the admin's own UI, never the buyer's chat.
  _,cb,_=native_event(real,SimpleNamespace(telegram_id=99,full_name='Owner',username='Owner'),data=f'resadmin:req_approve:{rid}')
  await admin.reseller_request_approve(cb)
 asyncio.run(approve())
 assert c.get(f'/api/miniapp/funding/{oid}',headers=H).json()['status']=='paid'
 assert not any(getattr(m,'chat_id',None)==11 for m in calls)


@pytest.mark.parametrize('inactive',[False,True])
def test_reseller_delete_returns_unused_quota_without_chat_messages(native,monkeypatch,inactive):
 c,sessions,real,calls,flow,buy=native
 async def seed():
  async with sessions() as s:
   if inactive:(await s.get(ResellerAccount,1)).expires_at=datetime.utcnow()-timedelta(days=1)
   s.add(ClientService(id=3,user_id=1,reseller_id=1,server_id=2,client_username='DeleteMe',xui_email='DeleteMe',total_bytes=30*GB,used_bytes=10*GB,reseller_reserved_bytes=30*GB,is_active=True))
   await s.commit()
 asyncio.run(seed())
 monkeypatch.setattr(flow,'sync_reseller_service_panel_snapshot',AsyncMock(return_value=True))
 monkeypatch.setattr(flow,'notify_service_deletion_task_admin',AsyncMock())
 remote=AsyncMock();monkeypatch.setattr(flow.XuiService,'delete_client',remote)
 r=c.post('/api/miniapp/reseller/actions',headers=H,json=action('delete',service_id=3));assert r.status_code==200,r.text
 asyncio.run(actions.process_operations());asyncio.run(actions.process_operations())
 assert c.get(f"/api/miniapp/operations/{r.json()['id']}",headers=H).json()['status']=='done'
 assert remote.await_count==1
 async def check():
  async with sessions() as s:assert (await s.get(ResellerAccount,1)).total_bytes==120*GB
 asyncio.run(check())
 assert not any(getattr(m,'chat_id',None)==11 for m in calls)


def test_conversion_handoff_enters_existing_bot_flow_immediately(native,monkeypatch):
 c,sessions,real,calls,flow,buy=native
 from app.bot import miniapp
 from app.bot.handlers.public import convert
 from app.services.miniapp_runtime import NativeState
 from types import SimpleNamespace
 monkeypatch.setattr(miniapp,'SessionLocal',sessions)
 monkeypatch.setattr(miniapp,'get_user_button',AsyncMock(return_value=('button',True)))
 converted=AsyncMock();monkeypatch.setattr(convert,'convert_choose_category',converted)
 sent=SimpleNamespace(edit_text=AsyncMock())
 message=SimpleNamespace(from_user=SimpleNamespace(id=11),bot=real,answer=AsyncMock(return_value=sent))
 asyncio.run(miniapp.handle_handoff(message,NativeState(),'mini_convert_1'))
 assert converted.await_count==1
 assert converted.call_args.args[0].data=='svcconvert:source:1'
 assert message.answer.await_count==1


def test_renewal_accepts_active_categories_only_on_same_public_panel(native,monkeypatch):
 c,sessions,real,calls,flow,buy=native
 from app.database.models import ServerCategory
 async def seed():
  async with sessions() as s:
   cat=await s.get(ServerCategory,2);cat.is_active=True
   await s.commit()
 asyncio.run(seed())
 monkeypatch.setattr(buy,'get_service_username_error',AsyncMock(side_effect=AssertionError('must not check duplicate for renewal')))
 r=c.get('/api/miniapp/services/1/renewal-plans',headers=H);assert r.status_code==200
 assert {p['id'] for p in r.json()['plans']}=={1,2}
 q=c.post('/api/miniapp/checkout/quote',headers=H,json={'plan_id':2,'service_id':1,'username':'mine'});assert q.status_code==200,q.text
 # A plan on a reseller-only/different panel never becomes a public renewal option.
 assert c.post('/api/miniapp/checkout/quote',headers=H,json={'plan_id':3,'service_id':1,'username':'mine'}).status_code==404
