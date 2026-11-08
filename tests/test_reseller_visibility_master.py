"""The reseller-menu switch applies to ordinary customers as well as resellers/admins."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from test_miniapp import client
from app.bot.keyboards import common
from app.bot.handlers.public import reseller as handler
from app.bot.handlers import user_content as controls
from app.database.models import Setting, ResellerAccount


@pytest.fixture
def visibility(client, monkeypatch):
    _, sessions = client
    monkeypatch.setattr(common, 'SessionLocal', sessions)
    monkeypatch.setattr(handler, 'SessionLocal', sessions)
    monkeypatch.setattr(common, 'get_setting_value', AsyncMock(side_effect=lambda key, default: default))
    common.invalidate_button_settings_cache()
    yield sessions
    common.invalidate_button_settings_cache()


@pytest.mark.parametrize('master,request_enabled', [(True, True), (False, True), (True, False), (False, False)])
@pytest.mark.parametrize('role', ['customer', 'reseller', 'admin'])
def test_master_switch_and_independent_request_switch(visibility, role, master, request_enabled):
    async def run():
        async with visibility() as s:
            s.add_all([Setting(key='button_reseller_menu_enabled', value=str(int(master))),
                       Setting(key='button_reseller_request_enabled', value=str(int(request_enabled)))])
            await s.commit()
        menu = await common.main_menu_inline(is_admin=role == 'admin', is_reseller=role == 'reseller')
        shown = any(b.callback_data == common.CB_RESELLER for row in menu.inline_keyboard for b in row)
        assert shown == (master and (request_enabled if role == 'customer' else True))
        _, enabled = await common.get_user_button('reseller_request' if role == 'customer' else 'reseller_menu')
        assert enabled == shown
    asyncio.run(run())


@pytest.mark.parametrize('approved', [False, True])
def test_old_menu_callback_is_blocked_for_customers_and_resellers(visibility, monkeypatch, approved):
    async def run():
        async with visibility() as s:
            s.add(Setting(key='button_reseller_menu_enabled', value='0'))
            if approved:
                s.add(ResellerAccount(user_id=1, is_active=True))
            await s.commit()
        monkeypatch.setattr(handler.settings, 'ADMIN_IDS', '99')
        monkeypatch.setattr(handler.settings, 'OWNER_IDS', '')
        edit = AsyncMock()
        monkeypatch.setattr(handler, 'edit_or_answer', edit)
        cb = SimpleNamespace(from_user=SimpleNamespace(id=11, username='customer', full_name='Customer'),
                             data='menu:reseller', answer=AsyncMock())
        await handler.reseller_home(cb, SimpleNamespace(clear=AsyncMock()))
        assert cb.answer.await_args.kwargs.get('show_alert') is True
        assert 'غیرفعال' in edit.await_args.args[1]
    asyncio.run(run())


def test_admin_toggle_immediately_updates_cached_customer_menu(visibility, monkeypatch):
    async def write(key, value):
        async with visibility() as s:
            await s.merge(Setting(key=key, value=value))
            await s.commit()
    monkeypatch.setattr(controls, 'set_setting_value', write)
    monkeypatch.setattr(controls, 'is_owner', lambda _: True)
    monkeypatch.setattr(controls, 'reseller_visibility', AsyncMock())
    async def run():
        cb = SimpleNamespace(from_user=SimpleNamespace(id=99))
        assert (await common.get_user_button('reseller_request'))[1]
        await controls.reseller_toggle(cb)
        assert not (await common.get_user_button('reseller_request'))[1]
        menu = await common.main_menu_inline()
        assert all(b.callback_data != common.CB_RESELLER for row in menu.inline_keyboard for b in row)
        await controls.reseller_toggle(cb)
        assert (await common.get_user_button('reseller_request'))[1]
    asyncio.run(run())
