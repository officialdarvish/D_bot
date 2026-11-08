"""Wallet checkout through real order/build/provider code; only external APIs mocked."""
import asyncio
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, func
from fastapi import FastAPI
from fastapi.testclient import TestClient

from test_miniapp_checkout import native, body, H
from test_miniapp import client, signed
from app.api import miniapp, miniapp_checkout as checkout
from app.database.models import User, Server, Plan, Order, ClientService, WalletTransaction
from app.services.pasarguard_service import PasarGuardService, PasarGuardUsernameConflict


@pytest.fixture
def pg_wallet(native, monkeypatch):
    c, sessions, bot, buy = native
    async def seed():
        async with sessions() as s:
            server = await s.get(Server, 1)
            server.server_type = 'pasarguard'
            server.meta = {'scope': 'public'}
            plan = await s.get(Plan, 1)
            plan.inbound_ids = [7]
            await s.commit()
    asyncio.run(seed())
    monkeypatch.setattr(buy, 'get_public_service_types', AsyncMock(return_value=[('v2ray', 'VPN', 'pasarguard')]))
    monkeypatch.setattr(buy, 'service_username_exists', AsyncMock(return_value=False))
    for name in ['send_buyer_notice', 'notify_paid_order', 'send_service_card',
                 'send_home', 'send_admin_notice', 'edit_admin_receipt_keyboard', 'report_bot_error']:
        monkeypatch.setattr(buy, name, AsyncMock())
    monkeypatch.setattr(buy, 'apply_purchase_commission', AsyncMock(return_value=0))
    app = FastAPI()
    app.include_router(checkout.router)
    app.include_router(miniapp.router)
    with TestClient(app) as api:
        yield api, sessions, bot, buy


@pytest.mark.parametrize('mode', ['direct', 'template', 'duplicate', 'missing_link', 'timeout', 'delivery_error'])
def test_pasarguard_wallet_purchase_and_replay(pg_wallet, monkeypatch, mode):
    c, sessions, bot, buy = pg_wallet
    saved = {}
    calls = []
    exact_link = 'https://sub.example/sub/opaque?token=a%2Bb&source=panel'
    if mode == 'template':
        async def template():
            async with sessions() as s:
                server = await s.get(Server, 1)
                server.meta = {'scope': 'public', 'pasarguard_require_template': True,
                               'pasarguard_allowed_template_ids': [9]}
                await s.commit()
        asyncio.run(template())
    if mode == 'duplicate':
        monkeypatch.setattr(buy, '_next_duplicate_username_number', AsyncMock(return_value=1))
    if mode == 'delivery_error':
        buy.send_service_card.side_effect = RuntimeError('Telegram unavailable')

    async def request(self, server, method, path, **kwargs):
        calls.append((method, path, kwargs.get('json')))
        if method == 'POST':
            if mode == 'timeout':
                raise RuntimeError('Create outcome unknown: ReadTimeout')
            name = kwargs['json']['username']
            if mode == 'duplicate' and name == 'native_customer':
                raise PasarGuardUsernameConflict('User already exists')
            if mode == 'template':
                name = 'prefix_' + name
            saved.update(id=88, username=name, data_limit=30*1024**3,
                         hwid_limit=0, group_ids=[7], status='active',
                         subscription_url='' if mode == 'missing_link' else exact_link)
            return dict(saved)
        if method == 'GET':
            if path != '/api/user/by-username/' + saved['username']:
                raise RuntimeError('PasarGuard API failed (404): user not found')
            return dict(saved)
        raise AssertionError((method, path))
    monkeypatch.setattr(PasarGuardService, '_request', request)

    payload = body()
    quote = c.post('/api/miniapp/checkout/quote', headers=H,
                   json={'plan_id': 1, 'username': payload['username']})
    assert quote.status_code == 200, quote.text
    first = c.post('/api/miniapp/checkout', headers=H, json=payload)
    assert first.status_code == 200, first.text
    oid = first.json()['id']
    assert first.json()['provider'] == 'pasarguard'
    assert c.post('/api/miniapp/checkout', headers=H, json=payload).json()['id'] == oid
    asyncio.run(checkout.process_wallet_queue())
    asyncio.run(checkout.process_wallet_queue())
    result = c.get(f'/api/miniapp/checkout/orders/{oid}', headers=H).json()
    failed = mode in {'missing_link', 'timeout'}
    assert result['status'] == ('failed' if failed else 'paid')
    post_count = sum(call[0] == 'POST' for call in calls)
    assert post_count == (2 if mode == 'duplicate' else 1)
    assert c.post('/api/miniapp/checkout', headers=H, json=payload).json()['id'] == oid

    async def verify():
        async with sessions() as s:
            assert (await s.get(User, 1)).wallet_balance == 111000
            assert await s.scalar(select(func.count(WalletTransaction.id))) == 1
            order = await s.get(Order, oid)
            if failed:
                assert order.service_id is None
                assert await s.scalar(select(func.count(ClientService.id))) == 2
            else:
                service = await s.get(ClientService, order.service_id)
                assert service.client_username == service.xui_email == saved['username']
                assert service.xui_uuid == '88'
                assert service.sub_link == exact_link
                assert service.inbound_ids == [7]
                assert service.total_bytes == 30*1024**3
                return service.id
    sid = asyncio.run(verify())
    if not failed:
        assert result['username'] == saved['username']
        assert result['service']['username'] == saved['username']
        assert result['service']['provider'] == 'pasarguard'
        link = c.get(f'/api/miniapp/services/{sid}/link', headers=H)
        assert link.status_code == 200, link.text
        assert link.json()['link'] == exact_link
        assert all(path == '/api/user/by-username/' + saved['username']
                   for method, path, _ in calls if method == 'GET')
        assert buy.notify_paid_order.await_count == 1
    else:
        assert result['service'] is None
        buy.send_service_card.assert_not_awaited()
    assert c.get(f'/api/miniapp/checkout/orders/{oid}',
                 headers={'X-Telegram-Init-Data': signed(22)}).status_code == 404
