import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, func

from app.bot.handlers.public import buy, reseller
from app.bot.handlers.public.buy import get_service_username_error as real_username_error
from app.services.pasarguard_service import PasarGuardService
from app.api import miniapp_checkout as checkout
from app.database.models import User, Order, ClientService, WalletTransaction
from test_miniapp_pasarguard_wallet import pg_wallet, native, client
from test_miniapp_checkout import H, body


@pytest.mark.parametrize('name', ['a', 'ab'])
def test_short_pasarguard_names_rejected_before_remote_checks(monkeypatch, name):
    public = AsyncMock(return_value=False)
    partner = AsyncMock(return_value=False)
    monkeypatch.setattr(buy, 'service_username_exists', public)
    monkeypatch.setattr(reseller, 'reseller_username_exists', partner)
    server = SimpleNamespace(server_type='pasarguard')
    assert '۳' in asyncio.run(real_username_error(None, server, name))
    assert '۳' in asyncio.run(reseller.get_reseller_username_error(None, server, name))
    public.assert_not_awaited()
    partner.assert_not_awaited()
    assert asyncio.run(real_username_error(None, SimpleNamespace(server_type='xui'), name)) is None


@pytest.mark.parametrize('name', ['ali', 'a' * 32])
def test_valid_pasarguard_names_preserved(monkeypatch, name):
    monkeypatch.setattr(buy, 'service_username_exists', AsyncMock(return_value=False))
    server = SimpleNamespace(server_type='pasarguard')
    assert asyncio.run(real_username_error(None, server, name)) is None
    assert asyncio.run(buy.resolve_service_username(None, server, name)) == (name, False)


def test_old_short_names_resolve_to_unique_names_for_both_flows(monkeypatch):
    monkeypatch.setattr(buy, '_next_duplicate_username_number', AsyncMock(side_effect=[1, 2]))
    # The first generated name may already belong to someone else.
    monkeypatch.setattr(buy, 'service_username_exists', AsyncMock(side_effect=[True, False]))
    monkeypatch.setattr(reseller, '_next_reseller_duplicate_number', AsyncMock(return_value=1))
    monkeypatch.setattr(reseller, 'reseller_username_exists', AsyncMock(return_value=False))
    server = SimpleNamespace(server_type='pasarguard')
    assert asyncio.run(buy.resolve_service_username(None, server, 'ab')) == ('ab_000002', True)
    assert asyncio.run(reseller.resolve_reseller_username(None, server, 'ab')) == ('ab_0001', True)


@pytest.mark.parametrize('name', ['a', 'ab', 'a' * 129])
def test_provider_rejects_invalid_lengths_without_create(monkeypatch, name):
    api = PasarGuardService()
    request = AsyncMock()
    monkeypatch.setattr(api, '_request', request)
    with pytest.raises(ValueError):
        asyncio.run(api.create_user_on_plan(SimpleNamespace(), SimpleNamespace(), name))
    request.assert_not_awaited()


def test_miniapp_rejects_short_name_before_wallet_debit(pg_wallet, monkeypatch):
    c, sessions, _, module = pg_wallet
    monkeypatch.setattr(module, 'get_service_username_error', real_username_error)
    payload = body()
    payload['username'] = 'ab'
    assert c.post('/api/miniapp/checkout/quote', headers=H, json={'plan_id': 1, 'username': 'ab'}).status_code == 409
    r = c.post('/api/miniapp/checkout', headers=H, json=payload)
    assert r.status_code == 409 and '۳' in r.json()['detail']
    async def verify():
        async with sessions() as s:
            assert (await s.get(User, 1)).wallet_balance == 250000
            assert await s.scalar(select(func.count(WalletTransaction.id))) == 0
            assert await s.scalar(select(func.count(Order.id)).where(Order.checkout_key.is_not(None))) == 0
    asyncio.run(verify())


def test_old_paid_short_name_order_can_be_completed_without_second_debit(pg_wallet, monkeypatch):
    c, sessions, _, module = pg_wallet
    payload = body()
    payload['username'] = 'ab'
    # Emulate an order already accepted and debited by an older release.
    oid = c.post('/api/miniapp/checkout', headers=H, json=payload).json()['id']
    monkeypatch.setattr(module, '_next_duplicate_username_number', AsyncMock(return_value=1))
    created_names = []
    async def request(self, server, method, path, **kw):
        if method == 'POST':
            name = kw['json']['username']
            assert len(name) >= 3
            created_names.append(name)
        return {'id': 77, 'username': created_names[0], 'hwid_limit': 0,
                'subscription_url': 'https://example.com/sub/repaired', 'group_ids': [7]}
    monkeypatch.setattr(PasarGuardService, '_request', request)
    asyncio.run(checkout.process_wallet_queue())
    asyncio.run(checkout.process_wallet_queue())
    result = c.get(f'/api/miniapp/checkout/orders/{oid}', headers=H).json()
    assert result['status'] == 'paid'
    assert result['username'] == result['service']['username'] == 'ab_000001'
    assert created_names == ['ab_000001']
    assert c.post('/api/miniapp/checkout', headers=H, json=payload).json()['id'] == oid
    async def verify():
        async with sessions() as s:
            assert (await s.get(User, 1)).wallet_balance == 111000
            assert await s.scalar(select(func.count(WalletTransaction.id))) == 1
            order = await s.get(Order, oid)
            service = await s.get(ClientService, order.service_id)
            assert service.client_username == 'ab_000001'
    asyncio.run(verify())
