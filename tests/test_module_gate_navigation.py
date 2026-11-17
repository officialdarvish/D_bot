"""Real dispatch: a disabled optional router must not shut down core navigation."""
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Chat, User, Message, Update, CallbackQuery

from app.bot import module_gate
from test_unified_bot_navigation import Telegram


@pytest.fixture
async def dispatch(monkeypatch):
    @asynccontextmanager
    async def session():
        yield object()
    monkeypatch.setattr(module_gate, 'SessionLocal', session)
    capability = AsyncMock(return_value={'resellers': False})
    monkeypatch.setattr(module_gate, 'capabilities', capability)
    telegram = Telegram()
    bot = Bot('123456:TEST_ONLY', session=telegram)
    bot._me = User(id=123456, is_bot=True, first_name='Bot', username='test_bot')
    dp = Dispatcher(storage=MemoryStorage())
    optional, core = Router(), Router()
    module_gate.install_module_gate(optional, 'resellers')
    hits = []

    @optional.message(StateFilter('ResellerInput:amount'))
    @optional.message(F.text == 'Reseller')
    async def reseller_message(message):
        hits.append('module-message')

    @optional.callback_query(StateFilter('ResellerInput:amount'))
    @optional.callback_query(F.data == 'reseller:open')
    async def reseller_callback(callback):
        hits.append('module-callback')

    @core.message(CommandStart())
    async def start(message, state):
        await state.clear()
        hits.append('start')

    @core.message(F.text == 'Support')
    async def support(message):
        hits.append('support')

    @core.callback_query(F.data == 'restart:start')
    async def restart(callback, state):
        await state.clear()
        hits.append('restart')

    dp.include_routers(optional, core)
    user = User(id=11, is_bot=False, first_name='User')
    def message(text):
        return Message(message_id=1, date=datetime.now(timezone.utc), chat=Chat(id=11, type='private'), from_user=user, text=text)
    async def feed(text=None, callback=None):
        update = Update(update_id=1, **({'message': message(text)} if text is not None else {'callback_query': CallbackQuery(id='click', from_user=user, chat_instance='chat', message=message('Menu'), data=callback)}))
        return await dp.feed_update(bot, update)
    state = dp.fsm.get_context(bot=bot, chat_id=11, user_id=11)
    yield feed, state, capability, hits, telegram
    await dp.storage.close()
    await bot.session.close()


@pytest.mark.parametrize('enabled', [False, True])
@pytest.mark.parametrize('active_state', [False, True])
@pytest.mark.parametrize('command', ['/start', '/start referral_42', '/start@test_bot'])
async def test_start_reaches_core_even_with_old_module_state(dispatch, enabled, active_state, command):
    feed, state, capability, hits, telegram = dispatch
    capability.return_value = {'resellers': enabled}
    if active_state:
        await state.set_state('ResellerInput:amount')
    await feed(text=command)
    assert hits == ['start']
    assert await state.get_state() is None
    capability.assert_not_awaited()
    assert not telegram.calls


@pytest.mark.parametrize('enabled', [False, True])
async def test_restart_button_escapes_old_module_state(dispatch, enabled):
    feed, state, capability, hits, telegram = dispatch
    capability.return_value = {'resellers': enabled}
    await state.set_state('ResellerInput:amount')
    await feed(callback='restart:start')
    assert hits == ['restart']
    assert await state.get_state() is None
    capability.assert_not_awaited()


async def test_unrelated_message_is_not_blocked_or_queried(dispatch):
    feed, state, capability, hits, telegram = dispatch
    await feed(text='Support')
    assert hits == ['support']
    capability.assert_not_awaited()


@pytest.mark.parametrize('callback', [False, True])
@pytest.mark.parametrize('enabled', [False, True])
async def test_matching_module_actions_keep_their_switch(dispatch, callback, enabled):
    feed, state, capability, hits, telegram = dispatch
    capability.return_value = {'resellers': enabled}
    await feed(**({'callback': 'reseller:open'} if callback else {'text': 'Reseller'}))
    capability.assert_awaited_once()
    if enabled:
        assert hits == ['module-callback' if callback else 'module-message']
        assert not telegram.calls
    else:
        assert not hits
        assert telegram.calls[-1].text == 'این بخش غیرفعال است.'

@pytest.mark.parametrize('text', ['42', '   '])
async def test_disabled_module_still_blocks_its_state_input(dispatch, text):
    feed, state, capability, hits, telegram = dispatch
    await state.set_state('ResellerInput:amount')
    await feed(text=text)
    assert not hits
    capability.assert_awaited_once()
    assert telegram.calls[-1].text == 'این بخش غیرفعال است.'
