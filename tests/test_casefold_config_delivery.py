from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendPhoto
from app.xui.client import XUIClient
from app.bot.config_delivery import send_config_photo, telegram_length, send_config_text


def xui():
    return object.__new__(XUIClient)


@pytest.mark.asyncio
@pytest.mark.parametrize('name', ['darvish', 'Darvish', 'darVish', 'DARVISH'])
async def test_panel_name_is_case_insensitive_without_folding_password(name):
    client = xui()
    client._client_api_request = AsyncMock(return_value={'success': True, 'obj': [
        {'email': 'dArViSh', 'password': 'OTHER'}]})
    assert await client.email_exists_casefold(name)


@pytest.mark.asyncio
async def test_paged_names_beyond_first_500_and_clamped_pages():
    client = xui()
    async def request(method, path):
        if path.endswith('/list'):
            raise RuntimeError('unsupported')
        page = int(path.split('page=')[1].split('&')[0])
        if page <= 6:
            return {'success': True, 'obj': {'items': [
                {'email': f'user-{page}-{i}'} for i in range(100)], 'total': 601}}
        return {'success': True, 'obj': {'items': [{'email': 'DaRvIsH'}], 'total': 601}}
    client._client_api_request = AsyncMock(side_effect=request)
    assert await client.email_exists_casefold('darvish')
    assert client._client_api_request.await_count == 8


@pytest.mark.asyncio
async def test_legacy_inbound_email_and_opaque_credentials():
    client = xui()
    client._client_api_request = AsyncMock(return_value={'success': True, 'obj': [
        {'email': 'different', 'password': 'DaRvIsH', 'subId': 'darvish'}]})
    client.get_inbounds = AsyncMock(return_value=[{'settings': '{"clients":[{"email":"DarVish"}]}'}])
    assert await client.email_exists_casefold('darvish')
    client.get_inbounds.assert_awaited_once_with(strict=True)
    client.get_inbounds.return_value = []
    assert not await client.email_exists_casefold('darvish')


@pytest.mark.asyncio
async def test_enumeration_failure_never_means_available():
    client = xui()
    client._client_api_request = AsyncMock(side_effect=RuntimeError('connection unavailable'))
    with pytest.raises(RuntimeError):
        await client.email_exists_casefold('darvish')


@pytest.mark.asyncio
async def test_repeated_pagination_never_means_available():
    client = xui()
    client._client_api_request = AsyncMock(side_effect=[RuntimeError('unsupported'),
        {'success': True, 'obj': [{'email': 'different'}]},
        {'success': True, 'obj': [{'email': 'different'}]}])
    with pytest.raises(RuntimeError, match='did not advance'):
        await client.email_exists_casefold('darvish')


@pytest.mark.asyncio
async def test_inbound_failure_never_means_available():
    client = xui()
    client._client_api_request = AsyncMock(side_effect=[{'success': True, 'obj': []},
        RuntimeError('denied'), RuntimeError('denied')])
    with pytest.raises(RuntimeError, match='inbound client names'):
        await client.email_exists_casefold('darvish')


@pytest.mark.asyncio
async def test_provision_race_retries_duplicate_only_and_saves_final_name():
    from app.bot.handlers.public import buy
    session = SimpleNamespace(add=Mock(), flush=AsyncMock())
    server = SimpleNamespace(id=2, server_type='xui')
    plan = SimpleNamespace(id=3, category_id=4, inbound_ids=[2, 4], volume_gb=10, duration_days=30)
    api = SimpleNamespace(create_client_on_plan=AsyncMock(side_effect=[
        RuntimeError('Something went wrong (inbound 2: Duplicate email: darvish\n inbound 4: Duplicate email: darvish)'),
        {'sub_link': 'https://sub.test/new', 'uuid': 'new-uuid'}]))
    with patch.object(buy, 'resolve_service_username', AsyncMock(side_effect=[('darvish', False), ('darvish_000001', True)])) as resolve, \
         patch.object(buy, 'XuiService', return_value=api):
        service, link = await buy.build_service(session, SimpleNamespace(id=1), server, plan, 'darvish')
    assert api.create_client_on_plan.await_args_list[1].args[-1] == 'darvish_000001'
    assert resolve.await_args_list[1].kwargs == {'force_duplicate': True}
    assert service.client_username == service.xui_email == 'darvish_000001'
    assert service.xui_uuid == 'new-uuid' and link == 'https://sub.test/new'
    session.add.assert_called_once_with(service)
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_provision_never_retries_ambiguous_timeout():
    from app.bot.handlers.public import buy
    api = SimpleNamespace(create_client_on_plan=AsyncMock(side_effect=RuntimeError('ReadTimeout')))
    session = SimpleNamespace(add=Mock(), flush=AsyncMock())
    plan = SimpleNamespace(id=3, category_id=4, inbound_ids=[2], volume_gb=10, duration_days=30)
    with patch.object(buy, 'resolve_service_username', AsyncMock(return_value=('darvish', False))), \
         patch.object(buy, 'XuiService', return_value=api):
        with pytest.raises(RuntimeError, match='ReadTimeout'):
            await buy.build_service(session, SimpleNamespace(id=1), SimpleNamespace(id=2, server_type='xui'), plan, 'darvish')
    assert api.create_client_on_plan.await_count == 1
    session.add.assert_not_called()


def bot():
    return SimpleNamespace(send_photo=AsyncMock(), send_message=AsyncMock(), send_document=AsyncMock())


@pytest.mark.asyncio
async def test_long_happ_caption_keeps_qr_and_full_copyable_link():
    api = bot()
    uri = 'happ://crypt5/' + 'A' * 1800
    caption = f'✅ لینک جدید\n<code>{uri}</code>'
    await send_config_photo(api, 1, 'photo', caption, reply_markup='controls')
    assert telegram_length(api.send_photo.await_args.kwargs['caption']) <= 1024
    assert api.send_message.await_args.args[1] == caption
    assert api.send_message.await_args.kwargs['reply_markup'] == 'controls'
    api.send_document.assert_not_awaited()


@pytest.mark.asyncio
async def test_huge_uri_remains_whole_in_utf8_file():
    api = bot()
    uri = 'happ://crypt5/' + 'A' * 5000
    await send_config_text(api, 1, f'<code>{uri}</code>', reply_markup='controls')
    assert api.send_document.await_args.args[1].data.decode() == uri
    api.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_caption_rejected_after_customization_preserves_photo_and_text():
    api = bot()
    api.send_photo.side_effect = [TelegramBadRequest(method=SendPhoto(chat_id=1, photo='photo'),
        message='Bad Request: message caption is too long'), None]
    await send_config_photo(api, 1, 'photo', '<code>full-link</code>')
    assert api.send_photo.await_count == 2
    assert api.send_message.await_args.args[1] == '<code>full-link</code>'


def test_length_counts_entities_and_emoji_safely():
    assert telegram_length('<code>&amp;</code>😀') == 3


@pytest.mark.asyncio
async def test_generic_exhaustive_lookup_folds_email_but_not_credentials():
    client = xui()
    client._get_client_api = AsyncMock(return_value=None)
    client._list_clients_api = AsyncMock(return_value=[{'email': 'DarVish', 'password': 'SeCrEt'}])
    assert (await client.find_client('darvish', exhaustive=True))['client']['email'] == 'DarVish'
    assert await client.find_client('secret', exhaustive=True) is None


@pytest.mark.asyncio
async def test_short_caption_remains_single_photo_with_controls():
    api = bot()
    await send_config_photo(api, 1, 'photo', '<code>full-link</code>', reply_markup='controls')
    assert api.send_photo.await_args.kwargs['reply_markup'] == 'controls'
    api.send_message.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('size', [1800, 5000])
async def test_revoke_long_happ_delivers_after_single_rotation_and_cleans_qr(size):
    from pathlib import Path
    from app.bot.handlers.public import my_services as mod
    from app.database.models import ClientService, Server, Plan
    uri = 'happ://crypt5/' + 'A' * size
    svc = SimpleNamespace(id=3, server_id=2, plan_id=1, client_username='Amirm1',
                          xui_email='Amirm1', sub_link=None)
    server = SimpleNamespace(server_type='xui')
    plan = SimpleNamespace(id=1)
    session = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())
    async def get(model, key):
        return {ClientService: svc, Server: server, Plan: plan}[model]
    session.get = get
    class DB:
        async def __aenter__(self): return session
        async def __aexit__(self, *args): pass
    provider = SimpleNamespace(revoke_and_new_link=AsyncMock(return_value={'uuid': 'rotated', 'sub_link': uri}))
    callback = SimpleNamespace(data='svc:revoke:3', from_user=SimpleNamespace(id=10),
        message=SimpleNamespace(chat=SimpleNamespace(id=10), message_id=100), bot=bot(), answer=AsyncMock())
    with patch.object(mod, 'SessionLocal', return_value=DB()), \
         patch.object(mod, '_owned_public_service', AsyncMock(return_value=(True, None))), \
         patch.object(mod, 'XuiService', return_value=provider) as provider_class, \
         patch.object(mod, 'service_detail_text', return_value='<code>'+uri+'</code>'), \
         patch.object(mod, 'detail_kb', return_value='controls'):
        provider_class.service_happ_enabled = AsyncMock(return_value=True)
        await mod.revoke_service(callback)
    provider.revoke_and_new_link.assert_awaited_once()
    session.commit.assert_awaited_once()
    assert svc.sub_link == uri
    if size == 1800:
        photo = callback.bot.send_photo.await_args.args[1]
        assert not Path(photo.path).exists()
        delivered = callback.bot.send_message.await_args_list
        assert uri in delivered[0].args[1] and uri in delivered[1].args[1]
        assert telegram_length(callback.bot.send_photo.await_args.kwargs['caption']) <= 1024
    else:
        callback.bot.send_photo.assert_not_awaited()
        for call in callback.bot.send_document.await_args_list:
            assert uri in call.args[1].data.decode()
        assert callback.bot.send_document.await_count == 2
    callback.answer.assert_awaited_once_with('✅ انجام شد')


@pytest.mark.asyncio
async def test_local_names_are_case_insensitive_in_public_and_reseller(tmp_path):
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from app.database.base import Base
    from app.database.models import ClientService
    from app.bot.handlers.public.buy import service_username_exists
    from app.bot.handlers.public.reseller import reseller_username_exists
    engine = create_async_engine('sqlite+aiosqlite:///'+str(tmp_path/'names.db'))
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine)() as session:
            session.add(ClientService(user_id=1, server_id=2, client_username='DaRvIsH', xui_email='OtherName'))
            await session.commit()
            for check in (service_username_exists, reseller_username_exists):
                for name in ('darvish', 'DARVISH', 'darVish', 'othername'):
                    assert await check(session, None, name)
                assert not await check(session, None, 'free_name')
    finally:
        await engine.dispose()


@pytest.mark.parametrize('message,expected', [
    ('Something went wrong (inbound 2: Duplicate email: darvish\ninbound 4: Duplicate email: darvish)', True),
    ('Duplicate email: darvish', True),
    ('inbound 2: Duplicate email: darvish\ninbound 4: Permission denied', False),
    ('ReadTimeout', False),
])
def test_duplicate_retry_requires_explicit_duplicate_rejection(message, expected):
    from app.bot.handlers.public.buy import is_duplicate_service_username_error
    assert is_duplicate_service_username_error(RuntimeError(message)) is expected
