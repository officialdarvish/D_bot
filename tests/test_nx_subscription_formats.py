import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import select

from test_nx_url_paths import admin
from test_miniapp import client
from app.database.models import Server, ClientService
from app.services.nx_subscription import FORMATS, parse_formats, subscription_links
from app.services.nx_service import NxService


def test_authoritative_urls_force_each_format_and_preserve_private_host_port_query():
    server = SimpleNamespace(meta={'nx_subscription_formats': list(FORMATS)})
    rows = subscription_links(server, 'https://wildcard.test:9443/private/sub/user-token/page?source=bot&format=html')
    assert [row['format'] for row in rows] == list(FORMATS)
    for row in rows:
        parts = urlsplit(row['url'])
        assert parts.netloc == 'wildcard.test:9443'
        assert parts.path == '/private/sub/user-token'
        assert parse_qs(parts.query) == {'source': ['bot'], 'format': [row['format']]}
    # Re-applying settings never appends another suffix or duplicates format.
    assert subscription_links(server, rows[0]['url']) == rows
    assert parse_formats(None) == ['v2ray']


@pytest.mark.parametrize('value', ['', [], 'auto', 'v2ray,html', 'clash,unknown'])
def test_unknown_or_empty_formats_are_rejected(value):
    with pytest.raises(ValueError):parse_formats(value)


def test_current_link_reuses_create_api_response_without_another_request(monkeypatch):
    service = NxService()
    lookup = AsyncMock(side_effect=AssertionError('Unnecessary API request'))
    monkeypatch.setattr(service, 'get_user', lookup)
    server = SimpleNamespace(meta={'nx_subscription_formats': ['singbox', 'clash']})
    data = {'id': 9, 'name': 'buyer', 'subUrl': 'https://api-issued.test/secret/sub/token'}
    link = asyncio.run(service.current_subscription_link(server, 'buyer', data))
    assert link == 'https://api-issued.test/secret/sub/token?format=singbox'
    lookup.assert_not_awaited()


def test_add_edit_preserve_and_validate_subscription_choices(admin):
    api, sessions, calls = admin
    payload = {'server_type': 'nx', 'name': 'NX', 'panel_url': 'https://nx.test', 'api_key': 'dummy-test-token', 'nx_subscription_formats': 'v2ray,clash,singbox'}
    assert api.post('/admin/servers/add', data=payload, headers={'Accept': 'application/json'}).status_code == 200
    async def get():
        async with sessions() as session:
            return (await session.execute(select(Server).where(Server.server_type == 'nx'))).scalar_one()
    row = asyncio.run(get())
    assert row.meta['nx_subscription_formats'] == ['v2ray', 'clash', 'singbox']
    edit = {**payload, 'api_key': '', 'nx_subscription_formats': 'plain,xray'}
    response = api.post(f'/admin/servers/{row.id}/edit', data=edit, headers={'Accept': 'application/json'})
    assert response.status_code == 200, response.text
    assert asyncio.run(get()).meta['nx_subscription_formats'] == ['plain', 'xray']
    edit.pop('nx_subscription_formats')
    assert api.post(f'/admin/servers/{row.id}/edit', data=edit, headers={'Accept': 'application/json'}).status_code == 200
    assert asyncio.run(get()).meta['nx_subscription_formats'] == ['plain', 'xray']
    edit['nx_subscription_formats'] = 'html'
    assert api.post(f'/admin/servers/{row.id}/edit', data=edit, headers={'Accept': 'application/json'}).status_code == 400
    assert asyncio.run(get()).meta['nx_subscription_formats'] == ['plain', 'xray']


def test_delivery_qr_payload_and_caption_match_each_selected_format(client, monkeypatch, tmp_path):
    from app.bot import service_presenter as presenter
    from app.database import session as database_session
    from app.services import user_content
    _, sessions = client
    async def setup():
        async with sessions() as session:
            server = await session.get(Server, 1)
            server.server_type = 'nx'
            server.meta = {'nx_subscription_formats': ['clash', 'singbox', 'v2ray']}
            svc = await session.get(ClientService, 1)
            svc.sub_link = 'https://wildcard.test/sub/token/page'
            await session.commit()
    asyncio.run(setup())
    monkeypatch.setattr(database_session, 'SessionLocal', sessions)
    monkeypatch.setattr(user_content, 'background_bytes', AsyncMock(return_value=None))
    monkeypatch.setattr(presenter, 'build_delivery_caption', AsyncMock(side_effect=lambda **kw: '<code>' + kw['sub_link'] + '</code>'))
    qrs, sent = [], []
    def qr(value, **kw):
        qrs.append((value, kw['subtitle']))
        path = tmp_path / f'qr-{len(qrs)}.png'
        path.write_bytes(b'test')
        return str(path)
    async def photo(bot, chat, image, caption, **kw):
        assert Path(image.path).exists()
        sent.append((caption, kw['reply_markup']))
    monkeypatch.setattr(presenter, 'make_qr_card', qr)
    monkeypatch.setattr(presenter, 'send_config_photo', photo)
    asyncio.run(presenter.send_service_info(None, 11, 'buyer', 'NX', 20, 30, 'https://wildcard.test/sub/token/page', service_id=1, server_type='nx'))
    assert len(qrs) == len(sent) == 3
    for (url, label), (caption, markup) in zip(qrs, sent):
        assert url in caption and label in caption
        assert '/page' not in url
        assert 'restart:start' in [b.callback_data for row in markup.inline_keyboard for b in row]
    assert [parse_qs(urlsplit(url).query)['format'][0] for url, label in qrs] == ['clash', 'singbox', 'v2ray']
    assert not list(tmp_path.glob('qr-*.png'))

@pytest.mark.parametrize('actor_id', [11, 22])
def test_existing_service_can_be_redelivered_only_by_its_owner(client, monkeypatch, actor_id):
    from app.bot.handlers.public import my_services
    from app.bot import service_presenter
    _, sessions = client
    async def setup():
        async with sessions() as session:
            server = await session.get(Server, 1)
            server.server_type = 'nx'
            await session.commit()
    asyncio.run(setup())
    monkeypatch.setattr(my_services, 'SessionLocal', sessions)
    current = AsyncMock(return_value='https://wildcard.test/sub/token?format=v2ray')
    monkeypatch.setattr(NxService, 'current_subscription_link', current)
    delivered = AsyncMock()
    monkeypatch.setattr(service_presenter, 'send_service_info', delivered)
    callback = SimpleNamespace(data='svc:nx-sub:1', from_user=SimpleNamespace(id=actor_id), answer=AsyncMock(), bot=None)
    asyncio.run(my_services.send_nx_subscriptions(callback))
    if actor_id == 11:
        current.assert_awaited_once()
        delivered.assert_awaited_once()
        assert delivered.call_args.args[1] == 11
    else:
        current.assert_not_awaited()
        delivered.assert_not_awaited()
        assert callback.answer.call_args.kwargs['show_alert'] is True

@pytest.mark.parametrize('actor_id,feature,active,allowed', [(11,True,True,True),(22,True,True,False),(11,False,True,False),(11,True,False,False)])
def test_reseller_redelivery_enforces_ownership_feature_and_active_account(client, monkeypatch, actor_id, feature, active, allowed):
    from app.bot.handlers.public import my_services
    from app.bot import service_presenter
    from app.database.models import ResellerAccount, Setting
    _, sessions = client
    async def setup():
        async with sessions() as session:
            server = await session.get(Server, 1)
            server.server_type = 'nx'
            session.add(ResellerAccount(id=1, user_id=1, server_id=1, is_active=active))
            svc = await session.get(ClientService, 1)
            svc.reseller_id = 1
            await session.merge(Setting(key='feature_resellers', value='1' if feature else '0'))
            await session.commit()
    asyncio.run(setup())
    monkeypatch.setattr(my_services, 'SessionLocal', sessions)
    current = AsyncMock(return_value='https://wildcard.test/sub/token?format=v2ray')
    monkeypatch.setattr(NxService, 'current_subscription_link', current)
    delivered = AsyncMock()
    monkeypatch.setattr(service_presenter, 'send_service_info', delivered)
    callback = SimpleNamespace(data='svc:nx-sub:1', from_user=SimpleNamespace(id=actor_id), answer=AsyncMock(), bot=None)
    asyncio.run(my_services.send_nx_subscriptions(callback))
    assert current.await_count == delivered.await_count == int(allowed)
