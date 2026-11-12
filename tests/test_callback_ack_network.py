import asyncio
from unittest.mock import AsyncMock
import pytest
from aiogram.exceptions import TelegramNetworkError, TelegramBadRequest, TelegramServerError, TelegramRetryAfter
from aiogram.methods import AnswerCallbackQuery, SendMessage
from test_unified_bot_navigation import env
from app.bot import ui_navigation as ui


def error(method,kind='network'):
 if kind=='timeout':return TimeoutError('Telegram timeout')
 if kind=='server':return TelegramServerError(method=method,message='Bad Gateway')
 if kind=='rate':return TelegramRetryAfter(method=method,message='rate limit',retry_after=30)
 return TelegramNetworkError(method=method,message='Connection reset by peer')

@pytest.mark.parametrize('kind',['network','timeout','server','rate'])
async def test_ack_failure_does_not_abort_handler_or_lose_back_navigation(env,monkeypatch,kind):
 bot,tg,dp,text,click,events=env
 original=tg.make_request;acks=[]
 async def failing(bot,method,timeout=None):
  if method.__api_method__=='answerCallbackQuery':acks.append(method);raise error(method,kind)
  return await original(bot,method,timeout)
 monkeypatch.setattr(tg,'make_request',failing)
 await text('/start');await click('Admin');await click('Form');await text('Name');await text('10')
 assert events.count('admin')==1 and events.count('commit')==1
 assert len(acks)==2  # Only initial acknowledgements, no replay loop.
 assert (await ui.load_ui(bot,11))['active'] is None

async def test_expired_callback_is_not_revived_when_ack_fails(env,monkeypatch):
 bot,tg,dp,text,click,events=env
 await text('/start')
 record=await ui.load_ui(bot,11);old=tg.messages[record['active']['id']]
 await click('Admin');await click('Form');await text('Name');await text('10')
 original=tg.make_request
 async def failing(bot,method,timeout=None):
  if method.__api_method__=='answerCallbackQuery':raise error(method)
  return await original(bot,method,timeout)
 monkeypatch.setattr(tg,'make_request',failing)
 await click('Admin',msg=old)
 assert events.count('admin')==1 and events.count('commit')==1

async def test_hung_ack_is_cancelled_and_handler_continues(env,monkeypatch):
 bot,tg,dp,text,click,events=env
 monkeypatch.setattr(ui,'CALLBACK_ACK_TIMEOUT',0.01)
 original=tg.make_request;cancelled=[]
 async def hanging(bot,method,timeout=None):
  if method.__api_method__=='answerCallbackQuery':
   try:await asyncio.Event().wait()
   finally:cancelled.append(True)
  return await original(bot,method,timeout)
 monkeypatch.setattr(tg,'make_request',hanging)
 await text('/start');await click('Admin')
 assert events==['admin'] and cancelled==[True]

async def test_busy_button_stays_blocked_when_acknowledgement_fails(env,monkeypatch):
 bot,tg,dp,text,click,events=env
 await text('/start')
 original=tg.make_request
 async def failing(bot,method,timeout=None):
  if method.__api_method__=='answerCallbackQuery':raise error(method)
  return await original(bot,method,timeout)
 monkeypatch.setattr(tg,'make_request',failing)
 lock=ui._locks.setdefault(ui._key(bot,11),asyncio.Lock())
 async with lock:await click('Admin')
 assert events==[]
 await click('Admin')
 assert events==['admin']

@pytest.mark.parametrize('bypass',[False,True])
async def test_ack_without_live_context_and_internal_bypass_are_best_effort(bypass):
 method=AnswerCallbackQuery(callback_query_id='old')
 send=AsyncMock(side_effect=error(method));token=ui._bypass.set(bypass)
 try:assert await ui.dispatch_ui_method(None,method,send) is False
 finally:ui._bypass.reset(token)
 send.assert_awaited_once()

async def test_unrelated_telegram_failures_and_cancellation_are_not_swallowed():
 method=SendMessage(chat_id=11,text='result')
 with pytest.raises(TelegramNetworkError):
  await ui.dispatch_ui_method(None,method,AsyncMock(side_effect=error(method)))
 ack=AnswerCallbackQuery(callback_query_id='x')
 with pytest.raises(asyncio.CancelledError):
  await ui._send_callback_answer(ack,AsyncMock(side_effect=asyncio.CancelledError()))
 with pytest.raises(TelegramBadRequest):
  await ui._send_callback_answer(ack,AsyncMock(side_effect=TelegramBadRequest(method=ack,message='unexpected bad request')))
 for message in ['query is too old','query ID is invalid']:
  assert await ui._send_callback_answer(ack,AsyncMock(side_effect=TelegramBadRequest(method=ack,message=message))) is True
