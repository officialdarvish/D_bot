"""v1.3.0: Fractional and above-one-GB trial quotas across entrypoints/providers."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.traffic_units import (
    format_gb_decimal,
    gb_to_bytes,
    parse_positive_trial_gb,
)
from app.services.pasarguard_service import PasarGuardService
from app.xui.client import XuiClientPayload

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('raw,expected', [
    ('0.1', '0.1'), ('0.2', '0.2'), ('0,5', '0.5'),
    ('1', '1'), ('2.5', '2.5'), ('5', '5'), ('10', '10'),
])
def test_trial_volume_accepts_decimals_and_above_one_gb(raw, expected):
    assert format_gb_decimal(parse_positive_trial_gb(raw)) == expected
    assert gb_to_bytes(parse_positive_trial_gb(raw)) > 0


@pytest.mark.parametrize('raw', ['', 'nan', 'NaN', 'Infinity', '-1', '0', 'abc', '1e-99'])
def test_trial_volume_rejects_zero_and_invalid_values(raw):
    with pytest.raises(ValueError):
        parse_positive_trial_gb(raw)


@pytest.mark.parametrize('volume_gb', ['0.1', '0.2', '1.5', '2', '5'])
def test_xui_and_database_byte_limits_match_fractional_quota(volume_gb):
    expected = gb_to_bytes(volume_gb)
    assert expected == int(float(volume_gb) * (1024 ** 3))
    assert XuiClientPayload(email='test_01', total_gb=float(volume_gb)).total_bytes == expected


@pytest.mark.parametrize('volume_gb', [0.1, 0.2, 1.5, 2, 5])
def test_pasarguard_direct_create_preserves_fractional_and_large_quotas(monkeypatch, volume_gb):
    svc = PasarGuardService()
    calls = []

    async def fake_request(server, method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {'id': 12, 'username': 'test_000001', 'data_limit': gb_to_bytes(volume_gb), 'subscription_url': 'https://example.com/sub/xyz'}

    async def fake_link(server, username, *responses):
        return 'https://example.com/sub/xyz'

    monkeypatch.setattr(svc, '_request', fake_request)
    monkeypatch.setattr(svc, 'current_subscription_link', fake_link)
    server = SimpleNamespace(meta={}, name='test', panel_url='https://example.com')
    plan = SimpleNamespace(volume_gb=volume_gb, duration_days=1, inbound_ids=[5], hwid_limit=0, is_test_account=True)
    result = asyncio.run(svc.create_user_on_plan(server, plan, 'test_000001'))
    assert result['sub_link'] == 'https://example.com/sub/xyz'
    assert calls[0][0:2] == ('POST', '/api/user')
    assert calls[0][2]['json']['data_limit'] == gb_to_bytes(volume_gb)
    assert calls[0][2]['json']['data_limit'] > 0


def test_pasarguard_template_based_trial_overrides_template_quota(monkeypatch):
    svc = PasarGuardService()
    calls = []
    saved = {'id': 42, 'username': 'test_000001', 'data_limit': 0, 'hwid_limit': 0}

    async def fake_request(server, method, path, **kwargs):
        calls.append((method, path, kwargs))
        if method == 'POST':
            return {'id': 42, 'username': 'test_000001', 'data_limit': 0, 'hwid_limit': 0}
        if method == 'PUT':
            saved.update(kwargs['json'])
        return {**saved, 'subscription_url': 'https://example.com/sub/xyz'}

    async def fake_link(server, username, *responses):
        return 'https://example.com/sub/xyz'

    monkeypatch.setattr(svc, '_request', fake_request)
    monkeypatch.setattr(svc, 'current_subscription_link', fake_link)
    server = SimpleNamespace(meta={
        'pasarguard_require_template': True,
        'pasarguard_allowed_template_ids': [8],
        'pasarguard_templates': [{'id': 8, 'name': 'trial'}],
    })
    plan = SimpleNamespace(volume_gb=0.2, duration_days=1, inbound_ids=[5], hwid_limit=0, is_test_account=True)
    asyncio.run(svc.create_user_on_plan(server, plan, 'test_000001'))
    writes = [request for request in calls if request[0] == 'PUT']
    assert len(writes) == 1
    assert writes[0][2]['json']['data_limit'] == gb_to_bytes('0.2')
    assert writes[0][2]['json']['data_limit'] > 0
    assert writes[0][2]['json']['hwid_limit'] == 0


def test_trial_admin_ui_and_api_provide_fractional_input_and_validation():
    ui = (ROOT / 'frontend/components/admin-dashboard.tsx').read_text()
    api = (ROOT / 'app/api/admin_web.py').read_text()
    bot = (ROOT / 'app/bot/handlers/admin/settings.py').read_text()
    assert 'step="any"' in ui
    assert 'parse_positive_trial_gb(volume_gb)' in api
    assert "parse_positive_trial_gb(message.text or '')" in bot
    assert (ROOT / 'VERSION').read_text().strip() == '1.3.0'
