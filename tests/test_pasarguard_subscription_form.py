from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from app.bot.handlers.admin import servers
from app.bot.states.admin_states import AddServer
from app.services.pasarguard_service import PasarGuardService,validate_subscription_base

@pytest.mark.asyncio
async def test_bot_pasarguard_requires_subscription_step(monkeypatch):
 monkeypatch.setattr(servers,'admin',lambda uid:True)
 output=AsyncMock();monkeypatch.setattr(servers,'ui_message',output)
 state=SimpleNamespace(get_data=AsyncMock(return_value={'server_type':'pasarguard'}),update_data=AsyncMock(),set_state=AsyncMock())
 message=SimpleNamespace(from_user=SimpleNamespace(id=1),text='https://panel.example/hub/')
 await servers.server_url(message,state)
 state.set_state.assert_awaited_with(AddServer.subscription_url)
 message.text='https://sub.example/sub/'
 await servers.server_subscription_url(message,state)
 state.update_data.assert_awaited_with(subscription_url='https://sub.example/sub/')
 state.set_state.assert_awaited_with(AddServer.username)
 state.set_state.reset_mock();message.text='invalid'
 await servers.server_subscription_url(message,state)
 state.set_state.assert_not_awaited()

@pytest.mark.asyncio
async def test_relative_panel_url_uses_configured_subscription_origin(monkeypatch):
 api=PasarGuardService();server=SimpleNamespace(subscription_url='https://sub.example/custom/',panel_url='https://dashboard.example/')
 monkeypatch.setattr(api,'get_user',AsyncMock(return_value={'subscription_url':'/sub/opaque?key=1&two=2'}))
 assert await api.current_subscription_link(server,'demo')=='https://sub.example/sub/opaque?key=1&two=2'
 monkeypatch.setattr(api,'get_user',AsyncMock(return_value={'subscription_url':'https://actual.example/different/token'}))
 assert await api.current_subscription_link(server,'demo')=='https://actual.example/different/token'
 assert validate_subscription_base('https://sub.example/custom')=='https://sub.example/custom/'
 for bad in ('', 'not-a-url', 'https://host:invalid/sub', 'https://host/sub?token=secret','https://name:pass@host/sub'):
  with pytest.raises(ValueError):validate_subscription_base(bad)
