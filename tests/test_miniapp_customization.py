import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import miniapp, miniapp_admin
from app.bot import miniapp as launcher
from app.services import miniapp_settings
from test_miniapp import client, signed


def test_admin_edits_reach_the_customer_snapshot_and_can_be_reset(client, monkeypatch):
    customer_api, sessions = client
    monkeypatch.setattr(miniapp_admin, 'SessionLocal', sessions)
    web = FastAPI()
    web.include_router(miniapp_admin.router)
    admin = TestClient(web)
    path = '/admin/api/v2/miniapp/texts'
    greeting = 'home.text.greeting'
    buy = 'home.button.tab_buy'
    auth = {'X-Telegram-Init-Data': signed()}

    def save(changes):
        return admin.post(path, data={'texts_json': json.dumps(changes)})

    assert admin.get(path).status_code == 401
    assert save({buy: 'سفارش'}).status_code == 401
    web.dependency_overrides[miniapp_admin._auth_user] = lambda: 'owner'
    assert save({greeting: 'درود {name}', 'title': 'Other brand'}).status_code == 400
    assert save({greeting: 'بدون متغیر'}).status_code == 400
    assert save({buy: 'x' * 97}).status_code == 400
    assert admin.get(path).json()['overrides'] == {}

    assert save({greeting: 'درود {name}'}).status_code == 200
    assert save({buy: 'سفارش'}).status_code == 200
    payload = customer_api.get('/api/miniapp/session', headers=auth).json()
    assert payload['text_overrides'] == {greeting: 'درود {name}', buy: 'سفارش'}
    assert payload['config']['title'] == 'D BOT' and payload['config']['accent'] == '#12b9f5'

    assert save({buy: ''}).json()['changes'] == {buy: ''}
    assert admin.get(path).json()['overrides'] == {greeting: 'درود {name}'}
    assert customer_api.get('/api/miniapp/session', headers=auth).json()['text_overrides'] == {greeting: 'درود {name}'}


def test_miniapp_visibility_settings_round_trip_without_rebranding(client, monkeypatch):
    customer_api, sessions = client
    monkeypatch.setattr(miniapp_admin, 'SessionLocal', sessions)
    monkeypatch.setattr(launcher, 'sync_menu_button', AsyncMock())
    web = FastAPI()
    web.include_router(miniapp_admin.router)
    web.dependency_overrides[miniapp_admin._auth_user] = lambda: 'owner'
    admin = TestClient(web)
    settings = {'show_rules': False, 'show_trial': False, 'show_tutorials': False, 'title': 'Other brand',
                'support_username': '', 'welcome': 'به فروشگاه خوش آمدید'}
    reply = admin.post('/admin/miniapp/save', data={'config_json': json.dumps(settings)})
    assert reply.status_code == 200, reply.text
    payload = customer_api.get('/api/miniapp/session', headers={'X-Telegram-Init-Data': signed()}).json()
    assert payload['config']['welcome'] == settings['welcome']
    assert payload['config']['title'] == 'D BOT'
    assert all(not payload['buttons'][button] for button in ('rules', 'test_account', 'tutorials'))
    assert admin.get('/admin/api/v2/miniapp').json()['config']['show_trial'] is False


def test_launcher_label_updates_telegram_and_can_restore_default(client, monkeypatch):
    customer_api, sessions = client
    monkeypatch.setattr(miniapp_admin, 'SessionLocal', sessions)
    monkeypatch.setattr(miniapp_settings, 'SessionLocal', sessions)
    monkeypatch.setattr(launcher, '_menu_cache', {})
    access = SimpleNamespace(login_url='https://shop.example.com/dbot/login', login_path='/dbot/login')
    monkeypatch.setattr(launcher, 'read_web_access', AsyncMock(return_value=access))
    bot = SimpleNamespace(id=555, set_chat_menu_button=AsyncMock(return_value=True))

    @asynccontextmanager
    async def fake_bot():
        yield bot

    monkeypatch.setattr(miniapp, 'telegram_bot', fake_bot)
    web = FastAPI()
    web.include_router(miniapp_admin.router)
    web.dependency_overrides[miniapp_admin._auth_user] = lambda: 'owner'
    admin = TestClient(web)

    def save(**settings):
        return admin.post('/admin/miniapp/save', data={'config_json': json.dumps(settings)})

    def menu():
        return bot.set_chat_menu_button.await_args.kwargs['menu_button']

    label = '🛍 فروشگاه اشتراک'
    assert save(launcher_label='  ' + label + '  ', title='Other brand', accent='#ff0000').status_code == 200
    assert menu().text == label and menu().web_app.url == 'https://shop.example.com/miniapp'
    snapshot = customer_api.get('/api/miniapp/session', headers={'X-Telegram-Init-Data': signed()}).json()
    assert snapshot['config']['title'] == 'D BOT' and snapshot['config']['accent'] == '#12b9f5'
    assert admin.get('/admin/api/v2/miniapp').json()['config']['launcher_label'] == label
    assert save(welcome='متن جدید').status_code == 200 and menu().text == label
    assert save(launcher_label='x' * 33).status_code == 400
    assert save(launcher_label='line\nline').status_code == 400
    assert admin.get('/admin/api/v2/miniapp').json()['config']['launcher_label'] == label
    assert save(launcher_label='New label', enabled=False).status_code == 200 and menu().type == 'commands'
    assert save().status_code == 200 and menu().text == 'New label'
    assert save(launcher_label='   ').status_code == 200 and menu().text == 'D BOT'
