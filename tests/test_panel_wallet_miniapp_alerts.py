import asyncio,io,json,uuid
from types import SimpleNamespace
from datetime import datetime,timedelta
from unittest.mock import AsyncMock
from PIL import Image
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select,func
from test_miniapp_native_actions import native,client,H,OTHER
from app.api import miniapp
from app.database.models import User,Server,PasarGuardPanelOrder,PasarGuardPanelMeter,Setting,Order,MiniAppOperation,ResellerAccount
from app.services import panel_wallet_alerts as alerts,pasarguard_panel_meter as metering


def seed(sessions):
 async def run():
  async with sessions() as s:
   server=await s.get(Server,2);server.server_type='pasarguard'
   s.add_all([PasarGuardPanelOrder(id=1,user_id=1,server_id=2,username='PurchasedPanel',amount_irt=90000,receipt_file_id='receipt',status='approved',admin_id=77),PasarGuardPanelOrder(id=2,user_id=2,server_id=2,username='OtherPanel',amount_irt=90000,receipt_file_id='receipt',status='approved',admin_id=88),PasarGuardPanelMeter(order_id=1,gb_price_irt=1000,hourly_price_irt=0,traffic_bytes=1024**3,total_charged_irt=1000)])
   await s.commit()
 asyncio.run(run())


def test_snapshot_shows_purchased_panel_without_configuration_reseller_account(native):
 c,sessions,*_=native;seed(sessions)
 async def remove_account():
  async with sessions() as s:
   a=await s.get(ResellerAccount,1);await s.delete(a);await s.commit()
 asyncio.run(remove_account())
 app=FastAPI();app.include_router(miniapp.router)
 with TestClient(app) as api:
  r=api.get('/api/miniapp/session',headers=H);assert r.status_code==200,r.text
  d=r.json();assert d['reseller'] is None
  assert [p['username'] for p in d['panels']]==['PurchasedPanel']
  assert d['panels'][0]['balance']==250000 and d['panels'][0]['gb_price']==1000
  assert 'password' not in json.dumps(d['panels']) and d['panels'][0]['login_url'].startswith('https://')
  assert api.get('/api/miniapp/panels',headers=OTHER).json()['panels'][0]['username']=='OtherPanel'


def test_panel_wallet_recharge_is_owned_and_credits_actual_meter_wallet_once(native,monkeypatch):
 c,sessions,real,calls,flow,buy=native;seed(sessions)
 from app.bot.handlers.public import account
 from app.services.miniapp_runtime import native_event
 monkeypatch.setattr(account,'SessionLocal',sessions)
 for n in ['notify_paid_order','mark_message_status','send_home','ui_callback_message']:monkeypatch.setattr(account,n,AsyncMock())
 b=dict(key=str(uuid.uuid4()),kind='panel_wallet',panel_id=1,amount=100000,method='card',expected_amount=100000)
 assert c.post('/api/miniapp/funding',headers=OTHER,json=b).status_code==404
 r=c.post('/api/miniapp/funding',headers=H,json=b);assert r.status_code==200,r.text
 oid=r.json()['id'];assert r.json()['kind']=='panel_wallet'
 assert c.post('/api/miniapp/funding',headers=H,json=b).json()['id']==oid
 out=io.BytesIO();Image.new('RGB',(400,600),'white').save(out,'PNG')
 r=c.post(f'/api/miniapp/funding/{oid}/receipt',headers=H,files={'file':('r.png',out.getvalue(),'image/png')});assert r.status_code==200,r.text
 async def approve():
  async with sessions() as s:
   op=await s.get(MiniAppOperation,oid);rid=op.result['target_id'];order=await s.get(Order,rid)
   assert order.pricing_meta['panel_order_id']==1
  _,cb,_=native_event(real,SimpleNamespace(telegram_id=99,full_name='Owner',username='owner'),data=f'wallet_topup:approve:{rid}')
  await account.wallet_topup_approve(cb);await account.wallet_topup_approve(cb)
  async with sessions() as s:
   assert (await s.get(User,1)).wallet_balance==350000
   assert (await s.get(ResellerAccount,1)).wallet_balance_irt==0
 asyncio.run(approve())
 assert c.get(f'/api/miniapp/funding/{oid}',headers=H).json()['status']=='paid'
 assert any(o['kind']=='panel_wallet' for o in c.get('/api/miniapp/tracking',headers=H).json()['orders'] if o.get('kind'))


def test_thresholds_send_once_across_panels_and_rearm_after_credit(native,monkeypatch):
 _,sessions,*_=native;seed(sessions);monkeypatch.setattr(alerts,'SessionLocal',sessions)
 bot=SimpleNamespace(send_message=AsyncMock())
 async def balance(n):
  async with sessions() as s:
   u=await s.get(User,1,with_for_update=True);u.wallet_balance=n;await alerts.rearm_wallet_alerts(s,u);await s.commit()
 async def run():
  for n in [299,199,99,49]:
   await balance(n);await alerts.notify_panel_wallet(bot,1,1);await alerts.notify_panel_wallet(bot,1,1)
  assert bot.send_message.await_count==4
  texts=[call.args[1] for call in bot.send_message.call_args_list]
  for level,text in zip(alerts.THRESHOLDS,texts):assert f'{level:,}' in text
  assert 'pgsale:topup:1' in str(bot.send_message.call_args.kwargs['reply_markup'])
  await balance(500);await alerts.notify_panel_wallet(bot,1,1);assert bot.send_message.await_count==4
  await balance(299);await alerts.notify_panel_wallet(bot,1,1);assert bot.send_message.await_count==5
  # An order belonging to another user cannot trigger a notification.
  await alerts.notify_panel_wallet(bot,1,2);assert bot.send_message.await_count==5
 asyncio.run(run())


def test_skipped_thresholds_coalesce_and_failed_delivery_retries(native,monkeypatch):
 _,sessions,*_=native;seed(sessions);monkeypatch.setattr(alerts,'SessionLocal',sessions)
 bot=SimpleNamespace(send_message=AsyncMock(side_effect=RuntimeError('offline')))
 async def run():
  async with sessions() as s:
   u=await s.get(User,1);u.wallet_balance=40;await s.commit()
  try:await alerts.notify_panel_wallet(bot,1,1)
  except RuntimeError:pass
  bot.send_message.side_effect=None
  await alerts.notify_panel_wallet(bot,1,1);await alerts.notify_panel_wallet(bot,1,1)
  assert bot.send_message.await_count==2 and '50' in bot.send_message.call_args.args[1]
 asyncio.run(run())


def test_proactive_shop_and_topup_callbacks_bypass_stale_guard_but_not_ownership(native,monkeypatch):
 _,sessions,*_=native;seed(sessions)
 from app.main import FreshCallbackOnlyMiddleware
 from app.bot.handlers.public import panel_reseller_sale as sale
 from app.services.miniapp_runtime import NativeState
 monkeypatch.setattr(sale,'SessionLocal',sessions)
 async def run():
  handler=AsyncMock(return_value='handled')
  for data in ['pgsale:shop','pgsale:topup:1']:
   event=SimpleNamespace(data=data,message=SimpleNamespace(chat=SimpleNamespace(id=11),message_id=2,edit_reply_markup=AsyncMock()),answer=AsyncMock())
   assert await FreshCallbackOnlyMiddleware()(handler,event,{})=='handled'
   event.message.edit_reply_markup.assert_not_awaited()
  cb=SimpleNamespace(data='pgsale:topup:1',from_user=SimpleNamespace(id=22),answer=AsyncMock())
  state=NativeState();await sale.panel_wallet_topup(cb,state)
  assert state.data=={} and cb.answer.call_args.kwargs['show_alert']
 asyncio.run(run())


def test_meter_poll_invokes_threshold_notification(native,monkeypatch):
 _,sessions,*_=native;seed(sessions)
 monkeypatch.setattr(metering,'SessionLocal',sessions)
 notify=AsyncMock();monkeypatch.setattr(alerts,'notify_panel_wallet',notify)
 api=metering.PanelMeterAPI();monkeypatch.setattr(api,'list_own_users',AsyncMock(return_value=[]))
 bot=SimpleNamespace(send_message=AsyncMock())
 result=asyncio.run(api.poll(1,bot=bot));assert result['remaining']>0
 assert notify.await_count==1 and notify.call_args.args==(bot,1,1)
