"""Real aiogram dispatch and a fake Telegram transport, with no network calls."""
from datetime import datetime,timezone
from unittest.mock import AsyncMock
import pytest
from aiogram import Dispatcher,Router,F
from aiogram.client.session.base import BaseSession
from aiogram.types import Message,Chat,User,CallbackQuery,InlineKeyboardMarkup,InlineKeyboardButton,PhotoSize,Update
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State,StatesGroup
from test_miniapp import client
from app.bot import ui_navigation as ui
from app.bot.custom_texts import CustomizableBot
from app.bot import custom_texts
from app.bot.utils import edit_or_answer,ui_message,send_single_message

class Form(StatesGroup):
 name=State();amount=State()

class Telegram(BaseSession):
 def __init__(self):super().__init__();self.calls=[];self.mid=100;self.messages={};self.fail_delete=False
 async def close(self):pass
 async def stream_content(self,*a,**k):
  if False:yield b''
 async def make_request(self,bot,method,timeout=None):
  name=method.__api_method__;self.calls.append(method)
  if name=='answerCallbackQuery':return True
  if name=='deleteMessage':
   if self.fail_delete:
    from aiogram.exceptions import TelegramBadRequest
    raise TelegramBadRequest(method=method,message='message cannot be deleted')
   self.messages.pop(method.message_id,None);return True
  if name.startswith('send'):self.mid+=1;mid=self.mid
  else:mid=method.message_id
  previous=self.messages.get(mid)
  text=getattr(method,'text',None) or getattr(previous,'text',None)
  caption=getattr(method,'caption',None)
  photo=None
  if name=='sendPhoto':photo=[PhotoSize(file_id='photo-id',file_unique_id='photo-u',width=300,height=300)]
  if name=='editMessageMedia':
   caption=method.media.caption;photo=[PhotoSize(file_id='photo-id',file_unique_id='photo-u',width=300,height=300)]
  msg=Message(message_id=mid,date=datetime.now(timezone.utc),chat=Chat(id=method.chat_id,type='private'),text=text,caption=caption,photo=photo,reply_markup=getattr(method,'reply_markup',None)).as_(bot)
  self.messages[mid]=msg;return msg

@pytest.fixture
async def env(monkeypatch):
 ui._memory.clear();ui._locks.clear();ui.configure_ui_storage(None)
 monkeypatch.setattr(custom_texts,'customize_method',AsyncMock(side_effect=lambda m:m))
 tg=Telegram();bot=CustomizableBot('123456:TEST_ONLY',session=tg)
 dp=Dispatcher(storage=MemoryStorage());dp.message.outer_middleware(ui.UnifiedUiMiddleware());dp.callback_query.outer_middleware(ui.UnifiedUiMiddleware())
 router=Router();dp.include_router(router)
 events=[]
 def kb(text,data):return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text,callback_data=data)]])
 @router.message(F.text=='/start')
 async def start(m,state):
  await state.clear();await m.answer('Main',reply_markup=kb('Admin','menu:admin'))
 @router.callback_query(F.data=='menu:admin')
 async def admin(c):events.append('admin');await c.message.answer('Admin',reply_markup=kb('Form','form:open'))
 @router.callback_query(F.data=='form:open')
 async def form(c,state):
  await state.set_state(Form.name);await edit_or_answer(c,'Send name',reply_markup=kb('Back','menu:admin'))
 @router.message(Form.name)
 async def name(m,state):
  await state.update_data(name=m.text);await state.set_state(Form.amount);await ui_message(m,'Send amount',reply_markup=kb('Back','form:open'))
 @router.message(Form.amount)
 async def amount(m,state):
  if not m.text.isdigit():await ui_message(m,'❌ Invalid amount',reply_markup=kb('Back','form:open'));return
  events.append('commit');await state.clear();await ui_message(m,'✅ ذخیره شد.',reply_markup=kb('Wrong old menu','menu:admin'))
 @router.callback_query(F.data=='restart:start')
 async def restart(c,state):
  await state.clear();await send_single_message(bot,11,'Main',reply_markup=kb('Admin','menu:admin'))
 await dp.emit_startup(bot=bot)
 async def feed_text(text,mid=1):
  return await dp.feed_update(bot,Update(update_id=tg.mid,message=Message(message_id=mid,date=datetime.now(timezone.utc),chat=Chat(id=11,type='private'),from_user=User(id=11,is_bot=False,first_name='User'),text=text)))
 async def click(label=None,data=None,msg=None):
  record=await ui.load_ui(bot,11)
  if msg is None:msg=tg.messages[record['active']['id']] if record['active'] else tg.messages[record['terminal'][-1]]
  if data is None:data=next(b.callback_data for row in msg.reply_markup.inline_keyboard for b in row if b.text==label)
  return await dp.feed_update(bot,Update(update_id=tg.mid,callback_query=CallbackQuery(id='click',from_user=User(id=11,is_bot=False,first_name='User'),chat_instance='chat',message=msg,data=data)))
 yield bot,tg,dp,feed_text,click,events
 await dp.emit_shutdown(bot=bot);await bot.session.close()

async def test_forward_input_error_back_and_final_restart(env):
 bot,tg,dp,text,click,events=env
 await text('/start');root=(await ui.load_ui(bot,11))['active']['id']
 await click('Admin');await click('Form')
 assert (await ui.load_ui(bot,11))['active']['id']==root
 await text('Alice',mid=2);assert tg.messages[root].text=='Send amount'
 before=(await ui.load_ui(bot,11));history=len(before['history'])
 await text('bad',mid=3)
 assert (await ui.load_ui(bot,11))['active']['id']==root
 assert len((await ui.load_ui(bot,11))['history'])==history
 await click('🔙 بازگشت');assert tg.messages[root].text=='Send name'
 await text('Bob',mid=4);old=tg.messages[root]
 await text('5',mid=5)
 record=await ui.load_ui(bot,11);assert record['active'] is None and not record['history']
 result=tg.messages[record['terminal'][-1]]
 assert result.message_id!=root and root not in tg.messages
 assert [[b.callback_data for b in r] for r in result.reply_markup.inline_keyboard]==[['restart:start']]
 assert events.count('commit')==1
 await click('Back',data='form:open',msg=old);assert events.count('commit')==1
 await click('🔄 شروع مجدد ربات',msg=result)
 record=await ui.load_ui(bot,11)
 assert record['active']['id']!=result.message_id and result.message_id in tg.messages
 assert tg.messages[record['active']['id']].text=='Main'
 deletes=[m.message_id for m in tg.calls if m.__api_method__=='deleteMessage']
 assert all(mid in deletes for mid in (1,2,3,4,5))

async def test_revoked_button_nonce_on_same_message_never_runs(env):
 bot,tg,dp,text,click,events=env
 await text('/start');old=tg.messages[(await ui.load_ui(bot,11))['active']['id']]
 await click('Admin',msg=old);count=events.count('admin')
 await click('Admin',msg=old);assert events.count('admin')==count
 assert any('منقضی' in (getattr(m,'text',None) or '') for m in tg.calls if m.__api_method__=='answerCallbackQuery')

async def test_back_restores_snapshot_not_side_effect_handler(env):
 bot,tg,dp,text,click,events=env
 await text('/start');await click('Admin');await click('Form');await click('🔙 بازگشت')
 assert events.count('admin')==1
 assert tg.messages[(await ui.load_ui(bot,11))['active']['id']].text=='Admin'

async def test_terminal_delete_failure_removes_old_keyboard(env):
 bot,tg,dp,text,click,events=env
 await text('/start');await click('Admin');await click('Form');await text('x',mid=6)
 old=(await ui.load_ui(bot,11))['active']['id'];tg.fail_delete=True
 await text('7',mid=7)
 assert any(m.__api_method__=='editMessageReplyMarkup' and m.message_id==old and m.reply_markup is None for m in tg.calls)

async def test_media_delivery_has_only_restart_and_is_not_edited_by_restart(env):
 bot,tg,dp,text,click,events=env
 await text('/start');await click('Admin')
 @dp.callback_query(F.data=='deliver')
 async def deliver(c):
  with ui.output_role('delivery'):
   await bot.send_photo(11,'photo-id',caption='Configuration',reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='Home',callback_data='home:main')]]))
 # Exercise the same outbound lifecycle under an explicit event context.
 record=await ui.load_ui(bot,11);active=record['active']['id']
 ctx=ui.UiContext(bot,11,None,None,record)
 token=ui._context.set(ctx)
 try:
  with ui.output_role('delivery'):result=await bot.send_photo(11,'photo-id',caption='Configuration')
 finally:ctx.closed=True;ui._context.reset(token)
 assert active not in tg.messages and result.photo
 assert result.reply_markup.inline_keyboard[0][0].callback_data=='restart:start'
 await click('🔄 شروع مجدد ربات',msg=result)
 assert tg.messages[result.message_id].caption=='Configuration'

@pytest.mark.parametrize('text,expected',[
 ('✅ ذخیره شد.',True),('✅ کارت حذف شد.',True),('❌ مقدار نامعتبر است.',False),
 ('⚠️ ابتدا مقدار را وارد کنید.',False),('✅ گیرنده: کاربر\n\nحالا متن را بفرستید.',False),
 ('✅ مرحله ۳ ذخیره شد.\n\nمتن مرحله بعد را ارسال کنید.',False),
 ('✅ کانفیگ با مشخصات زیر پیدا شد',False),('پیش‌نمایش تبدیل تعرفه',False),
])
def test_completion_adapter_preserves_prompts(text,expected):assert ui.completion_text(text)==expected

async def test_copied_content_survives_deleted_user_input_and_keeps_caption_override(env):
 bot,tg,dp,text,click,events=env
 await text('/start');await click('Admin');await click('Form')
 await text('private body',mid=17)
 copied=await bot.copy_message(22,11,17)
 assert tg.calls[-1].__api_method__=='sendMessage' and tg.calls[-1].text=='private body'
 assert copied.chat.id==22
 record=await ui.load_ui(bot,11)
 record['inputs']['18']={'media':{'type':'photo','file_id':'receipt-file'},'caption':'original'}
 await ui.save_ui(bot,11,record)
 await bot.copy_message(22,11,18,caption='Review this receipt',message_thread_id=42)
 assert tg.calls[-1].__api_method__=='sendPhoto' and tg.calls[-1].caption=='Review this receipt'
 assert tg.calls[-1].message_thread_id==42

async def test_independent_receipt_notification_keeps_review_controls_and_current_form(env):
 bot,tg,dp,text,click,events=env
 await text('/start');record=await ui.load_ui(bot,11);mid=record['active']['id']
 ctx=ui.UiContext(bot,11,None,None,record)
 token=ui._context.set(ctx)
 try:
  approval=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='Approve',callback_data='order:approve:1')]])
  sent=await bot.send_message(11,'Receipt received',reply_markup=approval)
 finally:ctx.closed=True;ui._context.reset(token)
 assert sent.message_id!=mid and tg.messages[mid].text=='Main'
 assert (await ui.load_ui(bot,11))['active']['id']==mid
 assert sent.reply_markup.inline_keyboard[0][0].callback_data=='order:approve:1'

async def test_background_refresh_cannot_edit_terminal_or_retired_page(env):
 bot,tg,dp,text,click,events=env
 await text('/start');await click('Admin');await click('Form');await text('name',mid=21)
 old=(await ui.load_ui(bot,11))['active']['id'];await text('1',mid=22)
 count=len(tg.calls)
 await bot.edit_message_text(chat_id=11,message_id=old,text='Stale refresh')
 assert len(tg.calls)==count and old not in tg.messages
 result=(await ui.load_ui(bot,11))['terminal'][-1]
 await bot.edit_message_text(chat_id=11,message_id=result,text='Stale result edit')
 assert tg.messages[result].text=='✅ ذخیره شد.'

async def test_background_refresh_preserves_valid_callback_capabilities(env):
 bot,tg,dp,text,click,events=env
 await text('/start');record=await ui.load_ui(bot,11);old=tg.messages[record['active']['id']]
 markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='Admin',callback_data='menu:admin')]])
 await bot.edit_message_text(chat_id=11,message_id=old.message_id,text='Main updated',reply_markup=markup)
 await click('Admin',msg=old)
 assert events.count('admin')==1

async def test_popup_only_success_becomes_separate_final_result(env):
 bot,tg,dp,text,click,events=env
 router=dp.sub_routers[0]
 @router.callback_query(F.data=='popup:save')
 async def save(c):events.append('saved');await c.answer('✅ تنظیمات ذخیره شد.')
 await text('/start');record=await ui.load_ui(bot,11);mid=record['active']['id']
 ctx=ui.UiContext(bot,11,None,None,record)
 token=ui._context.set(ctx)
 try:
  with ui.output_role('page'):await bot.send_message(11,'Settings',reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='Save',callback_data='popup:save')]]))
 finally:ctx.closed=True;ui._context.reset(token)
 await click('Save')
 record=await ui.load_ui(bot,11)
 assert record['active'] is None and events.count('saved')==1
 assert tg.messages[record['terminal'][-1]].text=='✅ تنظیمات ذخیره شد.'

async def test_actual_service_list_removal_is_one_page_until_confirm_then_terminal(env,client,monkeypatch):
 from app.bot.handlers.admin import service_list_removal as flow
 from app.services import service_list_removal as service
 from app.database.models import ClientService
 from aiogram.filters import StateFilter
 from app.bot.states.admin_states import RemoveServiceFromList
 from types import SimpleNamespace
 _,sessions=client
 bot,tg,dp,text,click,events=env
 monkeypatch.setattr(flow,'SessionLocal',sessions)
 monkeypatch.setattr(flow,'settings',SimpleNamespace(admin_ids=[11]))
 monkeypatch.setattr(service,'settings',SimpleNamespace(admin_ids=[11]))
 router=dp.sub_routers[0]
 router.callback_query.register(flow.begin,F.data=='admin:unlink_service')
 router.message.register(flow.receive_link,StateFilter(RemoveServiceFromList.link,RemoveServiceFromList.confirm))
 router.callback_query.register(flow.confirm,F.data.startswith('admin:unlink_confirm:'))
 await text('/start');record=await ui.load_ui(bot,11);ctx=ui.UiContext(bot,11,None,None,record)
 token=ui._context.set(ctx)
 try:
  with ui.output_role('page'):
   await bot.send_message(11,'User interaction',reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='Remove locally',callback_data='admin:unlink_service')]]))
 finally:ctx.closed=True;ui._context.reset(token)
 mid=(await ui.load_ui(bot,11))['active']['id']
 await click('Remove locally');await text('https://example.com/sub/other',mid=55)
 record=await ui.load_ui(bot,11);assert record['active']['id']==mid
 assert 'Other' in tg.messages[mid].text
 old=tg.messages[mid];button=next(b for row in old.reply_markup.inline_keyboard for b in row if 'تأیید حذف' in b.text)
 await click(data=button.callback_data,msg=old)
 record=await ui.load_ui(bot,11);assert record['active'] is None and mid not in tg.messages
 assert tg.messages[record['terminal'][-1]].reply_markup.inline_keyboard[0][0].callback_data=='restart:start'
 async with sessions() as s:assert (await s.get(ClientService,2)).hidden_from_owner

async def test_expired_page_has_restart_escape_after_ui_storage_expiration(env):
 bot,tg,dp,text,click,events=env
 await text('/start');record=await ui.load_ui(bot,11);old=tg.messages[record['active']['id']]
 ui._memory.clear()
 await click('Admin',msg=old)
 assert not events
 assert tg.messages[old.message_id].reply_markup.inline_keyboard[0][0].callback_data=='restart:start'
 await click('🔄 شروع مجدد ربات',msg=tg.messages[old.message_id])
 assert (await ui.load_ui(bot,11))['active']['id']!=old.message_id

async def test_ui_snapshot_and_capabilities_survive_process_cache_loss(env):
 bot,tg,dp,text,click,events=env
 class Store:
  def __init__(self):self.values={}
  async def get(self,k):return self.values.get(k)
  async def set(self,k,v,ex):self.values[k]=v
 store=Store();ui.configure_ui_storage(store)
 # Only exercise repository roundtrip here; dispatch locks are covered by the
 # real Redis lock API in production, not a fake with different semantics.
 record={'active':{'id':999,'nonce':'valid','callbacks':['menu:admin'],'data':{'name':'kept'}},'history':[],'terminal':[]}
 await ui.save_ui(bot,11,record);ui._memory.clear()
 restored=await ui.load_ui(bot,11)
 assert restored['active']==record['active']
 ui.configure_ui_storage(None)

async def test_uneditable_page_fallback_sends_new_then_removes_old(env,monkeypatch):
 bot,tg,dp,text,click,events=env
 await text('/start');old=(await ui.load_ui(bot,11))['active']['id']
 original=tg.make_request
 async def fail_edit(bot,method,timeout=None):
  if method.__api_method__=='editMessageText':
   from aiogram.exceptions import TelegramBadRequest
   raise TelegramBadRequest(method=method,message='message cannot be edited')
  return await original(bot,method,timeout)
 monkeypatch.setattr(tg,'make_request',fail_edit)
 await click('Admin')
 new=(await ui.load_ui(bot,11))['active']['id']
 assert new!=old and old not in tg.messages and tg.messages[new].text=='Admin'

async def test_intermediate_success_with_next_fsm_step_keeps_back_and_same_page(env):
 bot,tg,dp,text,click,events=env
 router=dp.sub_routers[0]
 @router.callback_query(F.data=='stage:next')
 async def step(c,state):
  await state.set_state(Form.amount)
  await edit_or_answer(c,'✅ نام ثبت شد.',reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='Back',callback_data='menu:admin')]]))
 await text('/start');record=await ui.load_ui(bot,11);ctx=ui.UiContext(bot,11,None,None,record)
 token=ui._context.set(ctx)
 try:
  with ui.output_role('page'):
   await bot.send_message(11,'Input step',reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='Next',callback_data='stage:next')]]))
 finally:ctx.closed=True;ui._context.reset(token)
 mid=(await ui.load_ui(bot,11))['active']['id'];await click('Next')
 record=await ui.load_ui(bot,11)
 assert record['active']['id']==mid and not record['terminal']
 assert any(b.text=='🔙 بازگشت' for row in tg.messages[mid].reply_markup.inline_keyboard for b in row)

async def test_proactive_completed_notice_has_only_restart_without_interrupting_form(env):
 bot,tg,dp,text,click,events=env
 await text('/start');mid=(await ui.load_ui(bot,11))['active']['id']
 markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='Back',callback_data='back:main')],[InlineKeyboardButton(text='Home',callback_data='home:main')]])
 notice=await bot.send_message(11,'✅ پرداخت تأیید شد.',reply_markup=markup)
 assert notice.reply_markup.inline_keyboard[0][0].callback_data=='restart:start'
 assert len(notice.reply_markup.inline_keyboard)==1
 assert (await ui.load_ui(bot,11))['active']['id']==mid
