from unittest.mock import AsyncMock
from aiogram import F
from aiogram.filters import StateFilter
from test_unified_bot_navigation import env
from app.bot import ui_navigation as ui
from app.bot.handlers.public import private_messages as private
from app.bot.keyboards.common import private_message_user_actions
from app.bot.states.public_states import PrivateMessageReply

async def setup(env,monkeypatch):
 bot,tg,dp,text,click,events=env
 monkeypatch.setattr(private,'is_owner',lambda uid:uid==99)
 monkeypatch.setattr(private,'report_bot_error',AsyncMock())
 router=dp.sub_routers[0]
 router.callback_query.register(private.private_chat_reply_start,F.data.startswith('private_chat:reply:'))
 router.callback_query.register(private.private_chat_end,F.data=='private_chat:end')
 router.message.register(private.private_chat_reply_send,StateFilter(PrivateMessageReply.message))
 await text('/start')
 note=await bot.send_message(11,'Admin message',reply_markup=private_message_user_actions(99))
 await click('✍️ پاسخ به پیام',msg=note);await text('My reply',mid=45)
 return dp.fsm.get_context(bot,chat_id=11,user_id=11)

async def test_reply_footer_has_three_controls_and_restart_opens_new_main(env,monkeypatch):
 state=await setup(env,monkeypatch)
 bot,tg,dp,text,click,events=env
 record=await ui.load_ui(bot,11);page=tg.messages[record['active']['id']]
 assert [b.text for row in page.reply_markup.inline_keyboard for b in row]==['✍️ پاسخ به پیام','✅ خاتمه گفتگو','🔄 شروع مجدد ربات']
 assert ui.BACK not in record['active']['callbacks']
 await click('🔄 شروع مجدد ربات')
 record=await ui.load_ui(bot,11)
 assert await state.get_state() is None
 assert record['active']['id']!=page.message_id
 assert tg.messages[record['active']['id']].text=='Main' and not record['history']

async def test_reply_and_end_keep_working_with_restart_footer(env,monkeypatch):
 state=await setup(env,monkeypatch)
 bot,tg,dp,text,click,events=env
 await click('✍️ پاسخ به پیام');await text('Second reply',mid=46)
 assert await state.get_state()==PrivateMessageReply.message.state
 page=tg.messages[(await ui.load_ui(bot,11))['active']['id']]
 assert all(b.text!='🔙 بازگشت' for row in page.reply_markup.inline_keyboard for b in row)
 await click('✅ خاتمه گفتگو')
 assert await state.get_state() is None
 assert (await ui.load_ui(bot,11))['active'] is None
