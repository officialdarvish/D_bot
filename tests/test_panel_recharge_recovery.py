import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from sqlalchemy import select,func
from test_miniapp_native_actions import native,client
from test_panel_wallet_miniapp_alerts import seed
from app.database.models import Order,User,MiniAppOperation,PasarGuardPanelMeter
from app.services import panel_wallet_recharge as recovery,pasarguard_panel_meter as metering
from app.services.reseller_management import save_profile

def prepare(sessions,suspended=True):
 seed(sessions)
 async def setup():
  async with sessions() as s:
   meter=await s.scalar(select(PasarGuardPanelMeter).where(PasarGuardPanelMeter.order_id==1))
   meter.suspended=suspended;meter.auto_disabled_user_ids=[71]
   s.add(Order(id=900,user_id=1,status='paid',amount_irt=100000,payment_method='wallet_topup:all',pricing_meta={'miniapp_source':True,'panel_order_id':1}))
   await s.flush();await recovery.enqueue_panel_recharge(s,await s.get(Order,900));await s.commit()
 asyncio.run(setup())

def test_native_recharge_notifies_once_and_recovers_only_credit_suspensions(native,monkeypatch):
 _,sessions,*_=native;prepare(sessions)
 bot=SimpleNamespace(send_message=AsyncMock())
 async def resume(oid):
  async with sessions() as s:
   m=await s.scalar(select(PasarGuardPanelMeter).where(PasarGuardPanelMeter.order_id==oid));m.suspended=False;await s.commit()
  return 1
 restored=AsyncMock(side_effect=resume);monkeypatch.setattr(metering.PanelMeterAPI,'resume',restored)
 async def run():
  await recovery.process_panel_recharges(bot);await recovery.process_panel_recharges(bot)
  async with sessions() as s:
   op=await s.scalar(select(MiniAppOperation).where(MiniAppOperation.kind=='panel_recharge_notice'));assert op.status=='done'
   assert (await s.get(User,1)).wallet_balance==250000
  restored.assert_awaited_once_with(1);bot.send_message.assert_awaited_once()
  assert bot.send_message.call_args.args[0]==11 and 'کیف پول پنل نمایندگی شما شارژ شد' in bot.send_message.call_args.args[1]
 asyncio.run(run())

def test_remote_failure_retries_recovery_without_duplicate_credit_or_notice(native,monkeypatch):
 _,sessions,*_=native;prepare(sessions)
 restored=AsyncMock(side_effect=RuntimeError('timeout'));monkeypatch.setattr(metering.PanelMeterAPI,'resume',restored)
 bot=SimpleNamespace(send_message=AsyncMock())
 async def run():
  await recovery.process_panel_recharges(bot)
  async with sessions() as s:
   op=await s.scalar(select(MiniAppOperation).where(MiniAppOperation.kind=='panel_recharge_notice'));assert op.status=='queued' and op.result['notified']
  restored.side_effect=None;restored.return_value=1
  await recovery.process_panel_recharges(bot)
  async with sessions() as s:
   op=await s.scalar(select(MiniAppOperation).where(MiniAppOperation.kind=='panel_recharge_notice'));assert op.status=='done'
   assert (await s.get(User,1)).wallet_balance==250000
  assert restored.await_count==2 and bot.send_message.await_count==1
 asyncio.run(run())

def test_telegram_failure_leaves_notice_pending_for_next_worker(native,monkeypatch):
 _,sessions,*_=native;prepare(sessions,False)
 bot=SimpleNamespace(send_message=AsyncMock(side_effect=RuntimeError('offline')))
 async def run():
  await recovery.process_panel_recharges(bot)
  async with sessions() as s:assert (await s.scalar(select(MiniAppOperation).where(MiniAppOperation.kind=='panel_recharge_notice'))).status=='queued'
  bot.send_message.side_effect=None;await recovery.process_panel_recharges(bot)
  async with sessions() as s:assert (await s.scalar(select(MiniAppOperation).where(MiniAppOperation.kind=='panel_recharge_notice'))).status=='done'
 asyncio.run(run())

def test_volume_or_tariff_conversion_does_not_auto_resume_manual_pauses(native,monkeypatch):
 _,sessions,*_=native;prepare(sessions)
 restored=AsyncMock();monkeypatch.setattr(metering.PanelMeterAPI,'resume',restored)
 monkeypatch.setattr(metering.PanelMeterAPI,'poll',AsyncMock())
 async def run():
  async with sessions() as s:
   await save_profile(s,'panels:1',{'billing_mode':'volume','available_bytes':1024**3,'manual_pauses':['panel:1:71']});await s.commit()
  bot=SimpleNamespace(send_message=AsyncMock());await recovery.process_panel_recharges(bot)
  restored.assert_not_awaited();assert 'اعتبار حجمی' in bot.send_message.call_args.args[1]
 asyncio.run(run())

def test_approval_enqueues_same_transaction_and_duplicate_approval_stays_idempotent(native,monkeypatch):
 _,sessions,real,calls,*_=native;seed(sessions)
 from app.bot.handlers.public import account
 from app.services.miniapp_runtime import native_event
 monkeypatch.setattr(account,'SessionLocal',sessions)
 for n in ['notify_paid_order','mark_message_status','send_home','ui_callback_message']:monkeypatch.setattr(account,n,AsyncMock())
 async def run():
  async with sessions() as s:
   s.add(Order(id=901,user_id=1,status='waiting_receipt',amount_irt=100000,payment_method='wallet_topup:all',pricing_meta={'miniapp_source':True,'panel_order_id':1}));await s.commit()
  _,cb,_=native_event(real,SimpleNamespace(telegram_id=99,full_name='Admin',username='owner'),data='wallet_topup:approve:901')
  await account.wallet_topup_approve(cb);await account.wallet_topup_approve(cb)
  async with sessions() as s:
   assert (await s.get(User,1)).wallet_balance==350000
   assert await s.scalar(select(func.count(MiniAppOperation.id)).where(MiniAppOperation.kind=='panel_recharge_notice'))==1
  messages=[m for m in calls if getattr(m,'chat_id',None)==11 and 'کیف پول پنل نمایندگی شما شارژ شد' in str(getattr(m,'text',''))]
  assert len(messages)==1
 asyncio.run(run())
