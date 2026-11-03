"""Persisted PasarGuard quotas must be verified before delivering trial links."""
import asyncio
from types import SimpleNamespace

import pytest

from app.services.pasarguard_service import PasarGuardService
from app.services.traffic_units import gb_to_bytes


@pytest.mark.parametrize('template', [False, True])
@pytest.mark.parametrize('volume', [0.1, 0.2, 0.5, 1, 1.5, 5])
def test_repairs_unlimited_creation_and_verifies_persisted_quota(monkeypatch, template, volume):
    svc = PasarGuardService()
    saved = {'id': 8, 'username': 'trial', 'data_limit': 0, 'hwid_limit': 0,
             'subscription_url': 'https://example.com/sub/opaque'}
    calls = []

    async def request(server, method, path, **kwargs):
        calls.append((method, path, kwargs.get('json')))
        if method == 'PUT':
            saved.update(kwargs['json'])
        return dict(saved)

    monkeypatch.setattr(svc, '_request', request)
    monkeypatch.setattr(svc, '_effective_template_id', lambda *_: 7 if template else 0)
    server = SimpleNamespace(meta={})
    plan = SimpleNamespace(volume_gb=volume, duration_days=1, inbound_ids=[2],
                           hwid_limit=0, is_test_account=True)
    result = asyncio.run(svc.create_user_on_plan(server, plan, 'trial'))
    assert saved['data_limit'] == result['data_limit'] == gb_to_bytes(volume) > 0
    put_index = next(i for i, call in enumerate(calls) if call[0] == 'PUT')
    assert calls[put_index + 1][0] == 'GET'
    assert result['sub_link'] == saved['subscription_url']
    assert not any(call[0] == 'DELETE' for call in calls)


@pytest.mark.parametrize('template', [False, True])
@pytest.mark.parametrize('failure', ['ignored', 'missing', 'read_error', 'put_error', 'delete_error'])
def test_never_delivers_unverified_or_unlimited_trial(monkeypatch, template, failure):
    svc = PasarGuardService()
    saved = {'id': 8, 'username': 'trial', 'data_limit': 0, 'hwid_limit': 0}
    calls = []

    async def request(server, method, path, **kwargs):
        calls.append((method, path, kwargs.get('json')))
        if method == 'GET' and failure == 'read_error':
            raise RuntimeError('Read failed')
        if method == 'PUT' and failure == 'put_error':
            raise RuntimeError('Write denied')
        if method == 'DELETE' and failure == 'delete_error':
            raise RuntimeError('Delete denied')
        if method == 'PUT':
            # Echo the requested quota without persisting it, as a broken API might.
            return {**saved, **kwargs['json']}
        result = dict(saved)
        if method == 'GET' and failure == 'missing':
            result.pop('data_limit')
        return result

    monkeypatch.setattr(svc, '_request', request)
    monkeypatch.setattr(svc, '_effective_template_id', lambda *_: 7 if template else 0)
    plan = SimpleNamespace(volume_gb=0.2, duration_days=1, inbound_ids=[2],
                           hwid_limit=0, is_test_account=True)
    with pytest.raises(RuntimeError):
        asyncio.run(svc.create_user_on_plan(SimpleNamespace(meta={}), plan, 'trial'))
    assert any(call[0] == 'DELETE' for call in calls)
    if failure == 'delete_error':
        assert calls[-1] == ('PUT', '/api/user/by-username/trial/disabled', {'disabled': True})


@pytest.mark.parametrize('volume', [0, -0.1, float('nan')])
def test_invalid_trial_quota_rejected_before_remote_creation(monkeypatch, volume):
    svc = PasarGuardService()

    async def request(*args, **kwargs):
        raise AssertionError('Invalid quota must not reach the panel')

    monkeypatch.setattr(svc, '_request', request)
    plan = SimpleNamespace(volume_gb=volume, is_test_account=True)
    with pytest.raises(ValueError):
        asyncio.run(svc.create_user_on_plan(SimpleNamespace(meta={}), plan, 'trial'))
