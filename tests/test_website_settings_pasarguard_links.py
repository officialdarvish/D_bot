from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.pasarguard_service import PasarGuardService
from app.services.xui_service import XuiService
from app.bot.handlers.admin import settings as menus
from app.bot.service_presenter import build_service_caption
from app.bot.config_delivery import plain_html


@pytest.mark.asyncio
async def test_website_menu_displays_active_credentials_and_login_button(monkeypatch):
    url = 'https://site.example:8443/private-path/login'
    monkeypatch.setattr(menus, 'read_web_access', AsyncMock(return_value=SimpleNamespace(login_url=url,prefix='/private-path')))
    monkeypatch.setattr(menus, 'read_web_credentials', AsyncMock(return_value=SimpleNamespace(username='owner',password='A<&secret',password_available=True)))
    monkeypatch.setattr(menus, 'get_setting_value', AsyncMock(side_effect=lambda key, default: default))
    text = await menus._get_web_settings_text()
    assert url in text and '/private-path' in text
    assert '<code>owner</code>' in text
    assert '<code>A&lt;&amp;secret</code>' in text
    keyboard = await menus._website_kb()
    assert keyboard.inline_keyboard[0][0].url == url


@pytest.mark.asyncio
async def test_website_menu_hash_only_and_unconfigured_address(monkeypatch):
    monkeypatch.setattr(menus, 'read_web_access', AsyncMock(return_value=SimpleNamespace(login_url='http://SERVER_IP:8000/dbot/login',prefix='/dbot')))
    monkeypatch.setattr(menus, 'read_web_credentials', AsyncMock(return_value=SimpleNamespace(username='admin',password='',password_available=False)))
    monkeypatch.setattr(menus, 'get_setting_value', AsyncMock(side_effect=lambda key, default: default))
    assert 'تغییر Password' in await menus._get_web_settings_text()
    assert all(button.url is None for row in (await menus._website_kb()).inline_keyboard for button in row)


@pytest.mark.asyncio
async def test_website_credentials_are_owner_only(monkeypatch):
    monkeypatch.setattr(menus, 'admin', lambda uid: False)
    reader = AsyncMock(); monkeypatch.setattr(menus, 'read_web_credentials', reader)
    await menus.website_settings_menu(SimpleNamespace(from_user=SimpleNamespace(id=99)))
    reader.assert_not_awaited()


@pytest.mark.asyncio
async def test_pasarguard_creation_uses_final_panel_url_verbatim(monkeypatch):
    api = PasarGuardService()
    exact = 'https://subscriptions.example/custom/token%2Fxyz?key=A%2BB&copy;=1#section'
    async def request(server, method, path, **kwargs):
        return {'id': 12, 'username':'demo', 'subscription_url': exact if method=='GET' else 'https://old.example/sub/wrong'}
    monkeypatch.setattr(api, '_request', request)
    server=SimpleNamespace(panel_url='https://dashboard.example/hub/',subscription_url='https://wrong.example/sub/',meta={})
    plan=SimpleNamespace(volume_gb=25,duration_days=30,inbound_ids=[4],hwid_limit=2)
    result=await api.create_user_on_plan(server,plan,'demo')
    assert result['sub_link']==exact
    assert result['subscription_url']==exact
    caption=build_service_caption(username='demo',title='Plan',volume_gb=25,duration_days=30,sub_link=exact,server_type='pasarguard')
    assert exact in plain_html(caption)


@pytest.mark.asyncio
async def test_pasarguard_existing_service_repairs_stored_url(monkeypatch):
    exact='https://subscriptions.example/s/opaque?one=1&two=2'
    monkeypatch.setattr(PasarGuardService,'get_user',AsyncMock(return_value={'subscription_url':exact}))
    service=SimpleNamespace(sub_link='https://incorrect.example/sub/123',xui_email='demo',client_username='demo',plan_id=None)
    link=await XuiService().resolve_service_subscription(None,SimpleNamespace(server_type='pasarguard'),service)
    assert link==exact and service.sub_link==exact


@pytest.mark.asyncio
async def test_pasarguard_partial_update_and_read_outage_keep_panel_issued_link(monkeypatch):
    api=PasarGuardService();exact='https://subscriptions.example/s/opaque'
    monkeypatch.setattr(api,'get_user',AsyncMock(side_effect=RuntimeError('read unavailable')))
    assert await api.current_subscription_link(None,'demo',{'subscription_url':exact},{'subscription_url':None})==exact
    assert await api.current_subscription_link(None,'demo',{})==''
