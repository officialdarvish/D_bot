import asyncio,json
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import select,func
from test_miniapp import client
from test_unified_bot_navigation import env
from app.database.models import Order,User,ClientService,ResellerTopupRequest,PasarGuardPanelOrder,Setting,PaymentCard
from app.services import receipt_inbox as archives
from app.bot.handlers.admin import pending_receipts as inbox
from aiogram import F
from aiogram.types import InlineKeyboardMarkup,InlineKeyboardButton
from app.bot import ui_navigation as ui

@pytest.fixture
def receipts(client,monkeypatch):
 _,sessions=client
 monkeypatch.setattr(inbox,'SessionLocal',sessions)
 monkeypatch.setattr(inbox.settings,'OWNER_IDS','11');monkeypatch.setattr(inbox.settings,'ADMIN_IDS','11')
 async def seed():
  async with sessions() as s:
   s.add(PaymentCard(id=1,server_type='xui',server_id=1,card_number='test',owner_name='Reviewer',reviewer_telegram_id=22,is_active=True))
   s.add(Order(id=10,user_id=1,plan_id=1,amount_irt=100000,payment_method='card',status='waiting_receipt',receipt_file_id='receipt-order',receipt_reviewer_telegram_id=22))
   s.add(PasarGuardPanelOrder(id=10,user_id=1,server_id=1,card_id=1,username='panel_user',amount_irt=100000,receipt_file_id='receipt-panel',status='pending'))
   s.add(ResellerTopupRequest(id=10,user_id=1,amount_irt=100000,volume_bytes=10*1024**3,receipt_file_id='receipt-reseller',status='pending'))
   await s.commit()
 asyncio.run(seed());return sessions

@pytest.mark.parametrize('kind',['order','panel','reseller'])
def test_archive_is_idempotent_and_only_hides_inbox_not_financial_records(receipts,kind):
 sessions=receipts;model=archives.MODELS[kind][0]
 async def run():
  async with sessions() as s:
   row=await s.get(model,10);before={c.name:getattr(row,c.name) for c in model.__table__.columns}
   user=await s.get(User,1);balance=user.wallet_balance
   service=await s.get(ClientService,1);before_service={c.name:getattr(service,c.name) for c in ClientService.__table__.columns}
   assert await archives.archive_receipt(s,kind,10,11);await s.commit()
   assert not await archives.archive_receipt(s,kind,10,11);await s.commit()
  async with sessions() as s:
   row=await s.get(model,10)
   assert before=={c.name:getattr(row,c.name) for c in model.__table__.columns}
   assert (await s.get(User,1)).wallet_balance==balance
   service=await s.get(ClientService,1);assert before_service=={c.name:getattr(service,c.name) for c in ClientService.__table__.columns}
   assert await s.scalar(select(func.count()).select_from(Setting).where(Setting.key==f'{archives.PREFIX}{kind}:10'))==1
   assert await archives.is_archived(s,kind,10)
  groups=await inbox._visible_receipts(11)
  assert all(x.id!=10 for x in groups[['order','panel','reseller'].index(kind)])
 asyncio.run(run())

@pytest.mark.parametrize('status',['paid','rejected','cancelled','processing'])
def test_processed_or_processing_receipts_cannot_be_archived(receipts,status):
 sessions=receipts
 async def run():
  async with sessions() as s:
   row=await s.get(Order,10);row.status=status;await s.commit()
   with pytest.raises(ValueError):await archives.archive_receipt(s,'order',10,11)
 asyncio.run(run())

def test_reviewer_can_read_but_not_delete_and_rollback_preserves_inbox(receipts):
 sessions=receipts
 async def run():
  groups=await inbox._visible_receipts(22);assert any(o.id==10 for o in groups[0])
  async with sessions() as s:
   with pytest.raises(ValueError):await archives.archive_receipt(s,'order',10,22)
   await archives.archive_receipt(s,'order',10,11);await s.rollback()
  assert any(o.id==10 for o in (await inbox._visible_receipts(11))[0])
 asyncio.run(run())

async def test_receipt_list_detail_back_and_archive_are_one_coherent_path(env,receipts):
 bot,tg,dp,text,click,events=env
 router=dp.sub_routers[0]
 router.callback_query.register(inbox.pending_receipts_list,F.data=='pending_receipts:list')
 router.callback_query.register(inbox.pending_receipts_detail,F.data.startswith('pending_receipts:order:'))
 router.callback_query.register(inbox.pending_receipt_delete_prompt,F.data.startswith('pending_receipts:delete:'))
 router.callback_query.register(inbox.pending_receipt_delete_confirm,F.data.startswith('pending_receipts:delete_confirm:'))
 await text('/start')
 msg=await bot.send_message(11,'Receipt parent',reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='Receipts',callback_data='pending_receipts:list')]]))
 await click('Receipts',msg=msg);depth=len((await ui.load_ui(bot,11))['history'])
 for _ in range(3):
  record=await ui.load_ui(bot,11);page=tg.messages[record['active']['id']]
  label=next(b.text for row in page.reply_markup.inline_keyboard for b in row if '#10' in b.text and 'پنل' not in b.text and not b.text.startswith('🤝'))
  await click(label)
  record=await ui.load_ui(bot,11);page=tg.messages[record['active']['id']]
  assert sum(b.text=='🔙 بازگشت' for row in page.reply_markup.inline_keyboard for b in row)==1
  assert any('حذف رسید' in b.text for row in page.reply_markup.inline_keyboard for b in row)
  await click('🔙 بازگشت')
  assert len((await ui.load_ui(bot,11))['history'])==depth
 record=await ui.load_ui(bot,11);page=tg.messages[record['active']['id']]
 label=next(b.text for row in page.reply_markup.inline_keyboard for b in row if '#10' in b.text and not b.text.startswith('🤝') and 'پنل' not in b.text)
 await click(label);await click('🗑 حذف رسید از فهرست')
 async with receipts() as s:assert not await archives.is_archived(s,'order',10)
 await click('تأیید حذف از فهرست')
 record=await ui.load_ui(bot,11);assert record['active'] is None
 assert tg.messages[record['terminal'][-1]].reply_markup.inline_keyboard[0][0].callback_data=='restart:start'
 async with receipts() as s:assert await archives.is_archived(s,'order',10)

async def test_receipt_command_and_refresh_share_one_list_page(env,receipts):
 from aiogram.filters import Command
 bot,tg,dp,text,click,events=env
 router=dp.sub_routers[0]
 router.message.register(inbox.pending_receipts_command,Command('pending_receipts'))
 router.callback_query.register(inbox.pending_receipts_list,F.data=='pending_receipts:list')
 await text('/start');await text('/pending_receipts',mid=75)
 record=await ui.load_ui(bot,11);depth=len(record['history'])
 for _ in range(3):await click('🔄 بروزرسانی')
 assert len((await ui.load_ui(bot,11))['history'])==depth
 await click('🔙 بازگشت')
 assert tg.messages[(await ui.load_ui(bot,11))['active']['id']].text=='Main'
