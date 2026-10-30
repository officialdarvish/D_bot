import asyncio
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from test_miniapp import client
from app.api import admin_web as web
from app.bot.keyboards import common
from app.bot.handlers.public import panel_reseller_sale as sale
from app.database import defaults
from app.database.models import Setting

HEADERS = {'Accept': 'application/json'}


@pytest.fixture
def settings_api(client, monkeypatch):
    _, sessions = client
    monkeypatch.setattr(web, 'SessionLocal', sessions)
    monkeypatch.setattr(defaults, 'SessionLocal', sessions)
    monkeypatch.setattr(common, 'SessionLocal', sessions)
    defaults.invalidate_settings_cache()
    common.invalidate_button_settings_cache()
    app = FastAPI()
    app.include_router(web.router)
    async def seed():
        async with sessions() as s:
            s.add_all([Setting(key='welcome_text', value='Original home'),
                       Setting(key='bot_name', value='My Bot'),
                       Setting(key='rules_enabled', value='1'),
                       Setting(key='rules_text', value='Existing rules'),
                       Setting(key='force_join_enabled', value='1'),
                       Setting(key='channel_url', value='@existing'),
                       Setting(key='pasarguard_panel_sales_enabled', value='1')])
            await s.commit()
    asyncio.run(seed())
    with TestClient(app, follow_redirects=False) as c:
        yield app, c, sessions
    defaults.invalidate_settings_cache()
    common.invalidate_button_settings_cache()


def test_new_settings_require_admin(settings_api):
    _, c, _ = settings_api
    for path, data in [('/admin/settings/home-message', {'welcome_text': 'New home'}),
                       ('/admin/settings/panel-sales-button', {'enabled': '0'})]:
        assert c.post(path, data=data, headers=HEADERS).status_code in {401, 303}


def test_home_message_roundtrip_and_unrelated_settings_preserved(settings_api):
    app, c, sessions = settings_api
    app.dependency_overrides[web._auth_user] = lambda: 'owner'
    # Warm the live bot cache before saving from the web.
    assert asyncio.run(defaults.get_setting_value('welcome_text')) == 'Original home'
    text = 'سلام به {bot_name} 👋\n\nپیام جدید صفحه اصلی'
    r = c.post('/admin/settings/home-message', data={'welcome_text': text}, headers=HEADERS)
    assert r.status_code == 200, r.text
    saved = c.get('/admin/api/v2/settings').json()
    mapping = {v['key']: v['value'] for v in saved['items']}
    assert mapping['welcome_text'] == text
    assert mapping['rules_text'] == 'Existing rules'
    assert mapping['rules_enabled'] == mapping['force_join_enabled'] == '1'
    assert mapping['channel_url'] == '@existing'
    assert asyncio.run(defaults.get_setting_value('welcome_text')) == text.replace('{bot_name}', 'My Bot')
    for bad in ['   ', 'a' * 4097, '😀' * 2049]:
        assert c.post('/admin/settings/home-message', data={'welcome_text': bad}, headers=HEADERS).status_code == 400
    assert c.get('/admin/api/v2/settings').json()['ok']
    assert asyncio.run(defaults.get_setting_value('welcome_text')) == text.replace('{bot_name}', 'My Bot')


def test_panel_button_toggle_cached_menu_and_old_callback(settings_api, monkeypatch):
    app, c, sessions = settings_api
    app.dependency_overrides[web._auth_user] = lambda: 'owner'
    # This key controls visibility only; it must not bypass/overwrite panel provisioning settings.
    def menu_has_sale():
        menu = asyncio.run(common.main_menu_inline())
        return any(b.callback_data == 'pgsale:shop' for row in menu.inline_keyboard for b in row)
    assert menu_has_sale()
    assert c.post('/admin/settings/panel-sales-button', data={'enabled': '0'}, headers=HEADERS).status_code == 200
    assert not menu_has_sale()
    forbidden_session = Mock()
    forbidden_session.get.side_effect = AssertionError('Disabled sale must not load a panel')
    assert asyncio.run(sale._configuration(forbidden_session)) is None
    mapping = {v['key']: v['value'] for v in c.get('/admin/api/v2/settings').json()['items']}
    assert mapping['button_panel_sales_enabled'] == '0'
    assert mapping['pasarguard_panel_sales_enabled'] == '1'
    # Legacy settings forms must not reset the new toggle when its field is omitted.
    assert c.post('/admin/settings/buttons', data={}, headers=HEADERS).status_code == 200
    assert not menu_has_sale()
    assert c.post('/admin/settings/panel-sales-button', data={'enabled': 'invalid'}, headers=HEADERS).status_code == 422
    assert not menu_has_sale()
    assert c.post('/admin/settings/panel-sales-button', data={'enabled': '1'}, headers=HEADERS).status_code == 200
    assert menu_has_sale()
    asyncio.run(defaults.set_setting_value('pasarguard_panel_sales_enabled', '0'))
    assert not menu_has_sale()
