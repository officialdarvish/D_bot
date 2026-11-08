import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError
from aiogram.methods import GetChatMember
from app.bot.handlers import start


@pytest.fixture
def gate(monkeypatch):
    async def setting(key, default=''):
        return {'force_join_enabled': '1', 'channel_url': '@channel'}.get(key, default)
    monkeypatch.setattr(start, 'get_setting_value', setting)
    monkeypatch.setattr(start, 'report_bot_error', AsyncMock())
    monkeypatch.setattr(start.asyncio, 'sleep', AsyncMock())
    return SimpleNamespace(get_chat_member=AsyncMock())


def network_error():
    return TelegramNetworkError(method=GetChatMember(chat_id='@channel', user_id=11), message='Connection reset by peer')


async def test_transient_read_recovers_without_error_report(gate):
    gate.get_chat_member.side_effect = [network_error(), SimpleNamespace(status='member')]
    assert await start.check_channel_join(gate, 11) == (True, '@channel', '')
    assert gate.get_chat_member.await_count == 2
    gate.get_chat_member.assert_awaited_with('@channel', 11, request_timeout=4)
    start.report_bot_error.assert_not_awaited()


@pytest.mark.parametrize('error', [network_error, TimeoutError])
async def test_network_failure_is_bounded_and_does_not_claim_nonmembership(gate, error):
    gate.get_chat_member.side_effect = error()
    ok, url, text = await start.check_channel_join(gate, 11)
    assert not ok and url == '@channel'
    assert 'هنوز بررسی نشده' in text and 'هنوز عضو کانال نیستید' not in text
    assert gate.get_chat_member.await_count == 2
    start.report_bot_error.assert_awaited_once()


@pytest.mark.parametrize('exc', [TelegramBadRequest, TelegramForbiddenError])
async def test_configuration_errors_are_not_retried(gate, exc):
    gate.get_chat_member.side_effect = exc(method=GetChatMember(chat_id='@channel', user_id=11), message='chat not found')
    assert (await start.check_channel_join(gate, 11))[0] is False
    assert gate.get_chat_member.await_count == 1


@pytest.mark.parametrize('status,is_member,expected', [
    ('member', False, True), ('administrator', False, True), ('creator', False, True),
    ('restricted', True, True), ('restricted', False, False), ('left', False, False), ('kicked', False, False),
])
async def test_statuses_preserve_membership_gate(gate, status, is_member, expected):
    gate.get_chat_member.return_value = SimpleNamespace(status=status, is_member=is_member)
    assert (await start.check_channel_join(gate, 11))[0] is expected


async def test_cancellation_is_not_retried_or_reported(gate):
    gate.get_chat_member.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await start.check_channel_join(gate, 11)
    assert gate.get_chat_member.await_count == 1
    start.report_bot_error.assert_not_awaited()


async def test_hung_read_is_actually_cancelled_at_attempt_deadline(gate, monkeypatch):
    original_wait_for = asyncio.wait_for
    cancelled = []
    async def hung(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)
    async def shortened_wait_for(awaitable, timeout):
        assert timeout == 4
        return await original_wait_for(awaitable, timeout=0.01)
    gate.get_chat_member.side_effect = hung
    monkeypatch.setattr(start.asyncio, 'wait_for', shortened_wait_for)
    result = await start.check_channel_join(gate, 11)
    assert not result[0] and 'هنوز بررسی نشده' in result[2]
    assert len(cancelled) == 2


async def test_channel_check_acknowledges_before_network(gate, monkeypatch):
    events = []
    callback = SimpleNamespace(answer=AsyncMock(side_effect=lambda *a, **k: events.append('ack')),
        message=SimpleNamespace(bot=gate), from_user=SimpleNamespace(id=11))
    async def check(*args):
        events.append('check')
        return False, '@channel', 'temporary error'
    monkeypatch.setattr(start, 'check_channel_join', check)
    monkeypatch.setattr(start, 'edit_or_answer', AsyncMock())
    await start.channel_check(callback)
    assert events == ['ack', 'check']
    callback.answer.assert_awaited_once()
    assert start.edit_or_answer.call_args.args[1] == 'temporary error'
