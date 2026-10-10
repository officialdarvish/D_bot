from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.pasarguard_service import PasarGuardService


@pytest.mark.asyncio
async def test_pasarguard_hwid_list_uses_user_id_api_and_normalizes_devices(monkeypatch):
    service = PasarGuardService()
    server = SimpleNamespace()
    monkeypatch.setattr(
        service,
        'get_user',
        AsyncMock(return_value={'id': 42, 'username': 'demo', 'hwid_limit': 2}),
    )
    request = AsyncMock(return_value={
        'count': 1,
        'hwids': [{
            'hwid': 'device-abc',
            'device_os': 'Android',
            'os_version': '14',
            'device_model': 'Pixel 8',
            'first_used_at': '2026-10-07T10:00:00+00:00',
            'last_used_at': '2026-10-07T11:00:00+00:00',
        }],
    })
    monkeypatch.setattr(service, '_request', request)

    result = await service.get_user_hwids(server, 'demo')

    request.assert_awaited_once_with(server, 'GET', '/api/user/42/hwids')
    assert result['limit'] == 2
    assert result['used'] == 1
    assert result['remaining'] == 1
    assert result['devices'][0]['fingerprint'] == 'device-abc'
    assert result['devices'][0]['deviceModel'] == 'Pixel 8'


@pytest.mark.asyncio
async def test_pasarguard_hwid_reset_uses_user_id_api(monkeypatch):
    service = PasarGuardService()
    server = SimpleNamespace()
    monkeypatch.setattr(service, 'get_user', AsyncMock(return_value={'id': 9, 'username': 'demo'}))
    request = AsyncMock(return_value={'detail': 'HWIDs reset'})
    monkeypatch.setattr(service, '_request', request)

    await service.clear_user_hwids(server, 'demo')

    request.assert_awaited_once_with(server, 'POST', '/api/user/9/hwids/reset')


@pytest.mark.asyncio
async def test_template_created_pasarguard_user_is_patched_to_plan_hwid_limit(monkeypatch):
    service = PasarGuardService()
    server = SimpleNamespace(meta={'pasarguard_require_template': True, 'pasarguard_template_id': 7})
    plan = SimpleNamespace(volume_gb=10, duration_days=30, inbound_ids=[1], hwid_limit=2, is_unlimited=False)
    monkeypatch.setattr(service, '_effective_template_id', lambda _server, _plan: 7)
    request = AsyncMock(return_value={'id': 100, 'username': 'demo', 'group_ids': [1], 'hwid_limit': 1, 'subscription_url': 'sub'})
    update_user = AsyncMock(return_value={'id': 100, 'hwid_limit': 2})
    monkeypatch.setattr(service, '_request', request)
    monkeypatch.setattr(service, 'update_user', update_user)

    result = await service.create_user_on_plan(server, plan, 'demo')

    update_user.assert_awaited_once_with(server, 'demo', hwid_limit=2)
    assert result['hwid_limit'] == 2


def test_my_configs_source_enables_pasarguard_hwid_actions():
    source = open('app/bot/handlers/public/my_services.py', encoding='utf-8').read()
    assert "server_type not in {'xui', 'pasarguard'}" in source
    assert "PasarGuardService().get_user_hwids" in source
    assert "PasarGuardService().clear_user_hwids" in source
    assert "if is_xui or is_pasarguard" in source


def test_plan_source_syncs_hwid_policy_to_pasarguard_services():
    source = open('app/api/admin_web.py', encoding='utf-8').read()
    assert 'schedule_pasarguard_plan_hwid_limit_sync(pid)' in source
    assert '_validate_plan_hwid_limit' in source


def test_telegram_admin_plan_editor_allows_pasarguard_hwid_limit():
    source = open('app/bot/handlers/admin/plans.py', encoding='utf-8').read()
    assert "not in {'xui', 'pasarguard'}" in source
    assert 'schedule_pasarguard_plan_hwid_limit_sync(pid)' in source
