"""Production handlers through real aiogram filters, FSM and shared transport."""
import pytest
from unittest.mock import AsyncMock
from aiogram import F
from aiogram.filters import StateFilter
from aiogram.types import InlineKeyboardMarkup,InlineKeyboardButton
from test_unified_bot_navigation import env
from test_miniapp import client
from app.bot import ui_navigation as ui
from app.bot.keyboards.common import private_message_user_actions
from app.bot.states.public_states import PrivateMessageReply
from app.bot.handlers.public import private_messages as private

async def test_private_reply_and_end_controls_are_dispatchable(env,monkeypatch):
 bot,tg,dp,text,click,events=env
 monkeypatch.setattr(private,'is_owner',lambda uid:uid==99)
 monkeypatch.setattr(private,'report_bot_error',AsyncMock())
 router=dp.sub_routers[0]
 router.callback_query.register(private.private_chat_reply_start,F.data.startswith('private_chat:reply:'))
 router.callback_query.register(private.private_chat_end,F.data=='private_chat:end')
 router.message.register(private.private_chat_reply_send,StateFilter(PrivateMessageReply.message))
 await text('/start')
 msg=await bot.send_message(11,'Admin private message',reply_markup=private_message_user_actions(99))
 await click('✍️ پاسخ به پیام',msg=msg)
 state=dp.fsm.get_context(bot,chat_id=11,user_id=11)
 assert await state.get_state()==PrivateMessageReply.message.state
 assert (await state.get_data())['private_message_admin_id']==99
 page=tg.messages[(await ui.load_ui(bot,11))['active']['id']]
 assert any('خاتمه' in b.text for row in page.reply_markup.inline_keyboard for b in row)
 await text('reply to owner',mid=41)
 assert any(m.__api_method__=='sendMessage' and m.chat_id==99 and m.text=='reply to owner' for m in tg.calls)
 # A delivered reply is an ongoing conversation, not the end of that thread.
 assert await state.get_state()==PrivateMessageReply.message.state
 depth=len((await ui.load_ui(bot,11))['history'])
 await click('✍️ پاسخ به پیام')
 assert len((await ui.load_ui(bot,11))['history'])==depth
 await text('second reply',mid=42)
 assert await state.get_state()==PrivateMessageReply.message.state
 await click('✅ خاتمه گفتگو')
 record=await ui.load_ui(bot,11)
 assert await state.get_state() is None and record['active'] is None
 assert tg.messages[record['terminal'][-1]].reply_markup.inline_keyboard[0][0].callback_data=='restart:start'

async def test_empty_ticket_list_is_a_child_with_one_back_and_no_self_button(env,client,monkeypatch):
 from app.bot.handlers.public import tickets
 bot,tg,dp,text,click,events=env;_,sessions=client
 monkeypatch.setattr(tickets,'SessionLocal',sessions)
 router=dp.sub_routers[0]
 router.callback_query.register(tickets.ticket_menu,F.data=='menu:tickets')
 router.callback_query.register(tickets.ticket_list,F.data=='ticket:list')
 await text('/start')
 # A proactive link enters the actual ticket menu, as the bot's main menu does.
 msg=await bot.send_message(11,'Ticket entry',reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='Tickets',callback_data='menu:tickets')]]))
 await click('Tickets',msg=msg);await click('لیست تیکت‌ها 📋')
 record=await ui.load_ui(bot,11);page=tg.messages[record['active']['id']]
 assert 'تیکتی ثبت نشده' in page.text
 assert [b.text for row in page.reply_markup.inline_keyboard for b in row]==['🔙 بازگشت']
 for _ in range(4):
  await click('🔙 بازگشت');await click('لیست تیکت‌ها 📋')
  assert len((await ui.load_ui(bot,11))['history'])==len(record['history'])
 await click('🔙 بازگشت')
 assert tg.messages[(await ui.load_ui(bot,11))['active']['id']].text=='📨 بخش تیکت:'

async def test_conversion_list_refresh_and_archive_tabs_do_not_grow_history(env,client,monkeypatch):
 from app.bot.handlers.admin import conversion_requests as conv
 bot,tg,dp,text,click,events=env;_,sessions=client
 monkeypatch.setattr(conv,'SessionLocal',sessions);monkeypatch.setattr(conv,'settings',type('S',(),{'admin_ids':[11]})())
 router=dp.sub_routers[0];router.callback_query.register(conv.conversion_requests,F.data.startswith('admin:conversions'))
 await text('/start');msg=await bot.send_message(11,'Admin entry',reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='Conversions',callback_data='admin:conversions')]]))
 await click('Conversions',msg=msg);count=len((await ui.load_ui(bot,11))['history'])
 for _ in range(5):
  await click('🔄 بروزرسانی فهرست');await click('📂 درخواست‌های حذف‌شده');await click('📋 درخواست‌های خطادار')
  record=await ui.load_ui(bot,11)
  assert len(record['history'])==count
  assert sum(b.text=='🔙 بازگشت' for row in tg.messages[record['active']['id']].reply_markup.inline_keyboard for b in row)==1
 await click('🔙 بازگشت')
 assert tg.messages[(await ui.load_ui(bot,11))['active']['id']].text=='Admin entry'

async def test_empty_popup_becomes_editable_child_and_noop_is_plain_text(env):
 bot,tg,dp,text,click,events=env
 router=dp.sub_routers[0]
 @router.callback_query(F.data=='empty:list')
 async def empty(c):await c.answer('هیچ موردی ثبت نشده است.',show_alert=True)
 @router.callback_query(F.data=='placeholder:list')
 async def placeholder(c):
  await c.message.answer('List',reply_markup=InlineKeyboardMarkup(inline_keyboard=[
   [InlineKeyboardButton(text='هنوز موردی ثبت نشده',callback_data='noop')],
   [InlineKeyboardButton(text='Back',callback_data='back:main')]]))
 await text('/start')
 for data in ('empty:list','placeholder:list'):
  msg=await bot.send_message(11,'List parent',reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='List',callback_data=data)]]))
  await click('List',msg=msg);record=await ui.load_ui(bot,11)
  page=tg.messages[record['active']['id']]
  assert 'ثبت نشده' in page.text
  assert [b.text for row in page.reply_markup.inline_keyboard for b in row]==['🔙 بازگشت']
  await click('🔙 بازگشت')
  assert tg.messages[(await ui.load_ui(bot,11))['active']['id']].text=='List parent'

async def test_completed_receipt_status_keyboard_does_not_grow_a_back_button(env):
 bot,tg,dp,text,click,events=env
 await text('/start');await click('Admin')
 record=await ui.load_ui(bot,11);mid=record['active']['id']
 markup=InlineKeyboardMarkup(inline_keyboard=[
  [InlineKeyboardButton(text='✅ رسید تایید شد.',callback_data='noop')],
  [InlineKeyboardButton(text='Home',callback_data='report:home')]])
 await bot.edit_message_reply_markup(chat_id=11,message_id=mid,reply_markup=markup)
 record=await ui.load_ui(bot,11)
 assert record['active'] is None and not record['history']
 assert [b.callback_data for row in tg.messages[mid].reply_markup.inline_keyboard for b in row]==['restart:start']

@pytest.mark.parametrize('same_order',[True,False])
async def test_late_receipt_completion_only_closes_its_own_order_page(env,same_order):
 bot,tg,dp,text,click,events=env
 await text('/start');record=await ui.load_ui(bot,11)
 record['active']['route']='pending_receipts:order:'+('10' if same_order else '20')
 mid=record['active']['id'];await ui.save_ui(bot,11,record)
 markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='✅ رسید تایید شد.',callback_data='noop:closed:order:10')]])
 await bot.edit_message_reply_markup(chat_id=11,message_id=mid,reply_markup=markup)
 record=await ui.load_ui(bot,11)
 if same_order:
  assert record['active'] is None and mid not in tg.messages
  assert tg.messages[record['terminal'][-1]].reply_markup.inline_keyboard[0][0].callback_data=='restart:start'
 else:
  assert record['active']['id']==mid and tg.messages[mid].text=='Main'

async def test_private_notification_does_not_inherit_an_unrelated_form_state(env,monkeypatch):
 bot,tg,dp,text,click,events=env
 monkeypatch.setattr(private,'is_owner',lambda uid:uid==99)
 router=dp.sub_routers[0]
 router.callback_query.register(private.private_chat_reply_start,F.data.startswith('private_chat:reply:'))
 await text('/start');await click('Admin');await click('Form')
 state=dp.fsm.get_context(bot,chat_id=11,user_id=11)
 assert await state.get_state() is not None
 msg=await bot.send_message(11,'Private notification',reply_markup=private_message_user_actions(99))
 await click('✍️ پاسخ به پیام',msg=msg)
 assert await state.get_state()==PrivateMessageReply.message.state
 await click('🔙 بازگشت')
 assert await state.get_state() is None
 assert tg.messages[(await ui.load_ui(bot,11))['active']['id']].text=='Private notification'
