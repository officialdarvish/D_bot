"""Authentication, customer isolation, catalogue policy, and bot handoff regressions."""
import asyncio
import hashlib
import hmac
import json
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlencode

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.database.base import Base
from app.database.models import User, Plan, Server, ServerCategory, ClientService, Order
from app.api import miniapp
from app.services.miniapp_auth import validate_init_data

TOKEN = '123456:TEST_TOKEN_FOR_LOCAL_VALIDATION'


def signed(user_id=11, auth_date=None, extra=None):
    data = dict(user=json.dumps({'id': user_id, 'first_name': 'Test'}), auth_date=str(int(time.time()) if auth_date is None else auth_date))
    data.update(extra or {})
    secret = hmac.new(b'WebAppData', TOKEN.encode(), hashlib.sha256).digest()
    check = '\n'.join(f'{k}={v}' for k,v in sorted(data.items()))
    data['hash'] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


def test_signature_timestamp_and_ambiguous_fields():
    assert validate_init_data(signed(), TOKEN)['id'] == 11
    assert validate_init_data(signed(extra={'signature':'telegram-extra-signature'}), TOKEN)['id'] == 11
    for raw in ('', signed().replace('Test', 'Fake'), signed(auth_date=int(time.time())-4000), signed(auth_date=int(time.time())+200), signed()+'&auth_date=1', signed(user_id=-1)):
        with pytest.raises(ValueError): validate_init_data(raw, TOKEN)


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = create_async_engine('sqlite+aiosqlite:///'+str(tmp_path/'miniapp.db'))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async def seed():
        async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
        async with sessions() as s:
            s.add_all([User(id=1,telegram_id=11,full_name='مشتری',wallet_balance=250000,accepted_rules=True), User(id=2,telegram_id=22,full_name='Other'),
                Server(id=1,name='Public',server_type='xui',panel_url='https://example.com',username='private',password_encrypted='private',meta={'scope':'public'}),
                Server(id=2,name='Reseller',server_type='xui',panel_url='https://secret.example.com',username='secret',password_encrypted='secret',meta={'scope':'reseller'}),
                ServerCategory(id=1,name='اقتصادی',server_id=1),ServerCategory(id=2,name='Hidden',server_id=1,is_active=False),
                Plan(id=1,title='۳۰ گیگ',volume_gb=30,duration_days=30,price_irt=139000,server_id=1,category_id=1),
                Plan(id=2,title='Hidden',price_irt=1,server_id=1,category_id=2),Plan(id=3,title='Private',price_irt=1,server_id=2,category_id=1),
                ClientService(id=1,user_id=1,server_id=1,plan_id=1,client_username='mine',xui_email='mine',sub_link='https://example.com/sub/mine',total_bytes=30*1024**3,used_bytes=12*1024**3,expires_at=datetime.utcnow()+timedelta(days=12)),
                ClientService(id=2,user_id=2,server_id=1,plan_id=1,client_username='other',xui_email='other',sub_link='https://example.com/sub/other'),
                Order(id=1,user_id=1,plan_id=1,amount_irt=139000,payment_method='wallet',status='paid')])
            await s.commit()
    asyncio.run(seed())
    monkeypatch.setattr(miniapp, 'SessionLocal', sessions)
    monkeypatch.setattr(miniapp.settings, 'BOT_TOKEN', TOKEN)
    monkeypatch.setattr(miniapp, 'get_setting_value', AsyncMock(side_effect=lambda key, default: default))
    monkeypatch.setattr(miniapp, 'get_user_button', AsyncMock(return_value=('button',True)))
    import app.bot.handlers.public.buy as buy
    monkeypatch.setattr(buy, 'get_public_service_types', AsyncMock(return_value=[('v2ray','VPN','xui')]))
    @asynccontextmanager
    async def fake_bot(): yield SimpleNamespace(get_me=AsyncMock(return_value=SimpleNamespace(username='test_dbot')))
    monkeypatch.setattr(miniapp, 'telegram_bot', fake_bot)
    app = FastAPI(); app.include_router(miniapp.router)
    with TestClient(app) as c: yield c, sessions
    asyncio.run(engine.dispose())


def test_api_auth_and_customer_isolation(client):
    c,_=client
    assert c.get('/api/miniapp/session').status_code == 401
    assert c.get('/api/miniapp/session',headers={'X-Telegram-Init-Data':signed(user_id=999)}).status_code == 403
    h={'X-Telegram-Init-Data':signed()}
    r=c.get('/api/miniapp/session',headers=h)
    assert r.status_code == 200, r.text
    assert r.headers['cache-control'] == 'no-store, private'
    assert [s['id'] for s in r.json()['services']] == [1]
    assert r.json()['user']['balance'] == 250000
    assert 'password' not in r.text and 'sub_link' not in r.text
    assert c.get('/api/miniapp/services/2/link',headers=h).status_code == 404
    assert c.get('/api/miniapp/services/2/qr',headers=h).status_code == 404
    assert c.post('/api/miniapp/handoff',headers=h,json={'action':'renew','item_id':2}).status_code == 404
    r=c.get('/api/miniapp/services/1/qr',headers=h)
    assert r.status_code==200 and r.content.startswith(b'\x89PNG')
    assert 'no-store' in r.headers['cache-control']


def test_catalog_and_handoff_revalidation(client):
    c,_=client; h={'X-Telegram-Init-Data':signed()}
    r=c.get('/api/miniapp/plans',headers=h)
    assert r.status_code==200,r.text
    assert [p['id'] for p in r.json()['plans']] == [1]
    assert c.post('/api/miniapp/handoff',headers=h,json={'action':'buy','item_id':2}).status_code==404
    r=c.post('/api/miniapp/handoff',headers=h,json={'action':'buy','item_id':1})
    assert r.status_code==200 and r.json()['url']=='https://t.me/test_dbot?start=mini_buy_1'
    assert c.post('/api/miniapp/handoff',headers=h,json={'action':'admin'}).status_code==400


def test_blocked_rules_buttons_and_happ_fail_closed(client,monkeypatch):
    c,sessions=client; h={'X-Telegram-Init-Data':signed()}
    monkeypatch.setattr(miniapp,'get_user_button',AsyncMock(return_value=('button',False)))
    assert c.get('/api/miniapp/plans',headers=h).status_code==403
    monkeypatch.setattr(miniapp,'get_user_button',AsyncMock(return_value=('button',True)))
    from app.services.xui_service import XuiService
    monkeypatch.setattr(XuiService,'service_happ_enabled',AsyncMock(return_value=True))
    monkeypatch.setattr(XuiService,'delivery_subscription_link',AsyncMock(return_value=None))
    r=c.get('/api/miniapp/services/1/link',headers=h)
    assert r.status_code==409 and 'https://example.com/sub/mine' not in r.text
    async def block():
        async with sessions() as s:
            u=await s.get(User,1);u.is_blocked=True;await s.commit()
    asyncio.run(block())
    assert c.get('/api/miniapp/session',headers=h).status_code==403


def test_bot_handoff_starts_existing_plan_flow(client, monkeypatch):
    _, sessions = client
    import app.bot.miniapp as bridge
    monkeypatch.setattr(bridge,'SessionLocal',sessions)
    monkeypatch.setattr(bridge,'get_user_button',AsyncMock(return_value=('button',True)))
    message=SimpleNamespace(from_user=SimpleNamespace(id=11),chat=SimpleNamespace(id=11),answer=AsyncMock(return_value=SimpleNamespace(message_id=501)))
    state=SimpleNamespace(update_data=AsyncMock())
    sent=asyncio.run(bridge.handle_handoff(message,state,'mini_buy_1'))
    assert sent.message_id == 501
    assert state.update_data.await_args.kwargs['server_ids']==[1]
    markup=message.answer.await_args.kwargs['reply_markup']
    assert markup.inline_keyboard[0][0].callback_data=='buy:plan:1'
    message.answer.reset_mock();state.update_data.reset_mock()
    asyncio.run(bridge.handle_handoff(message,state,'mini_buy_3'))
    assert not state.update_data.called
    asyncio.run(bridge.handle_handoff(message,state,'mini_renew_2'))
    assert 'اشتراک پیدا نشد' in message.answer.await_args.args[0]


def test_rules_and_forced_join_are_enforced(client,monkeypatch):
    c,sessions=client; h={'X-Telegram-Init-Data':signed()}
    async def unaccept():
        async with sessions() as s:
            u=await s.get(User,1);u.accepted_rules=False;await s.commit()
    asyncio.run(unaccept())
    monkeypatch.setattr(miniapp,'get_setting_value',AsyncMock(side_effect=lambda k,d: '1' if k=='rules_enabled' else d))
    assert c.get('/api/miniapp/session',headers=h).status_code==403
    import app.bot.handlers.start as start
    monkeypatch.setattr(start,'check_channel_join',AsyncMock(return_value=(False,'https://t.me/example','')))
    monkeypatch.setattr(miniapp,'get_setting_value',AsyncMock(side_effect=lambda k,d: '1' if k=='force_join_enabled' else d))
    assert c.get('/api/miniapp/session',headers=h).status_code==403


def test_native_menu_requires_https(monkeypatch):
    import app.bot.miniapp as bridge
    from app.services.miniapp_settings import DEFAULTS
    import app.services.miniapp_settings as cfg
    monkeypatch.setattr(cfg,'read_config',AsyncMock(return_value=dict(DEFAULTS)))
    bot=SimpleNamespace(id=123,set_chat_menu_button=AsyncMock(),get_me=AsyncMock(return_value=SimpleNamespace(first_name='فروشگاه تست',username='test_shop_bot')))
    bridge._menu_cache.clear()
    monkeypatch.setattr(bridge,'read_web_access',AsyncMock(return_value=SimpleNamespace(login_url='http://localhost/dbot/login',login_path='/dbot/login')))
    asyncio.run(bridge.sync_menu_button(bot))
    assert bot.set_chat_menu_button.await_args.kwargs['menu_button'].type=='commands'
    monkeypatch.setattr(bridge,'read_web_access',AsyncMock(return_value=SimpleNamespace(login_url='https://shop.example.com/dbot/login',login_path='/dbot/login')))
    asyncio.run(bridge.sync_menu_button(bot))
    menu=bot.set_chat_menu_button.await_args.kwargs['menu_button']
    assert menu.type=='web_app' and menu.web_app.url=='https://shop.example.com/miniapp'
    assert menu.text=='فروشگاه تست'
    count=bot.set_chat_menu_button.await_count
    asyncio.run(bridge.sync_menu_button(bot))
    assert bot.set_chat_menu_button.await_count==count
    bot.get_me.return_value.first_name='نام جدید فروشگاه'
    asyncio.run(bridge.sync_menu_button(bot))
    assert bot.set_chat_menu_button.await_args.kwargs['menu_button'].text=='نام جدید فروشگاه'


def test_config_validation():
    from app.services.miniapp_settings import clean_config,support_username
    assert support_username('@dbot_support',required=True)=='dbot_support'
    assert support_username('https://t.me/dbot_support')=='dbot_support'
    for value in ('','https://evil.example/a','abc','name/path','<script>'):
        with pytest.raises(ValueError): support_username(value,required=True)
    for changes in ({'accent':'red;display:none'},{'links':[{'label':'x','url':'javascript:alert(1)'}]}, {'links':[{'label':'x','url':'https://user:pass@example.com'}]}):
        with pytest.raises(ValueError): clean_config(changes)
    assert clean_config({'show_buy':False})['show_buy'] is False


def test_catalog_contains_only_configured_categories(client,monkeypatch):
    c,sessions=client;h={'X-Telegram-Init-Data':signed()}
    r=c.get('/api/miniapp/plans',headers=h);assert r.status_code==200,r.text
    assert [x['title'] for x in r.json()['categories']]==['اقتصادی']
    assert 'نامحدود' not in json.dumps(r.json()['categories'],ensure_ascii=False)
    import app.bot.handlers.public.buy as buy
    monkeypatch.setattr(buy,'get_public_service_types',AsyncMock(return_value=[]))
    assert c.get('/api/miniapp/plans',headers=h).json()['categories']==[]


def test_support_and_feature_settings_are_live(client):
    from app.database.models import Setting
    c,sessions=client;h={'X-Telegram-Init-Data':signed()}
    async def change():
        async with sessions() as s:
            s.add(Setting(key='support_username',value='dbot_support'))
            s.add(Setting(key='miniapp_config',value=json.dumps({'show_buy':False})))
            await s.commit()
    asyncio.run(change())
    r=c.get('/api/miniapp/session',headers=h)
    assert r.json()['buttons']['buy'] is False
    assert r.json()['config']['support_url']=='https://t.me/dbot_support'
    assert c.get('/api/miniapp/plans',headers=h).status_code==403
    assert c.post('/api/miniapp/handoff',headers=h,json={'action':'support'}).json()['url']=='https://t.me/dbot_support'
    assert c.post('/api/miniapp/handoff',headers=h,json={'action':'buy','item_id':1}).status_code==403


@pytest.fixture
def reseller_data(client):
    from app.database.models import ResellerAccount
    c,sessions=client
    async def add():
        async with sessions() as s:
            s.add_all([ResellerAccount(id=1,user_id=1,server_id=1,total_bytes=80*1024**3,is_active=True),
                ResellerAccount(id=2,user_id=2,server_id=1,total_bytes=40*1024**3,is_active=True),
                ClientService(id=3,user_id=1,reseller_id=1,server_id=1,client_username='customer_mine',xui_email='customer_mine',sub_link='https://example.com/reseller/mine'),
                ClientService(id=4,user_id=2,reseller_id=2,server_id=1,client_username='customer_other',xui_email='customer_other',sub_link='https://example.com/reseller/other')])
            await s.commit()
    asyncio.run(add());return c,sessions


def test_reseller_isolation_and_all_management_handoffs(reseller_data):
    c,_=reseller_data;h={'X-Telegram-Init-Data':signed()}
    r=c.get('/api/miniapp/session',headers=h)
    assert [s['id'] for s in r.json()['services']]==[1]
    assert [s['id'] for s in r.json()['reseller']['services']]==[3]
    assert r.json()['reseller']['active'] is True
    assert c.get('/api/miniapp/reseller/services/4/link',headers=h).status_code==404
    assert c.get('/api/miniapp/services/3/link',headers=h).status_code==404
    assert c.get('/api/miniapp/reseller/services/3/link',headers=h).json()['link'].endswith('/mine')
    for action in ('rmanage','rvol','rdays','rrenew','rdelete','rrevoke'):
        assert c.post('/api/miniapp/handoff',headers=h,json={'action':action,'item_id':4}).status_code==404
        result=c.post('/api/miniapp/handoff',headers=h,json={'action':action,'item_id':3})
        assert result.status_code==200,result.text
        assert result.json()['url'].endswith(f'mini_{action}_3')


def test_expired_reseller_remains_visible_but_cannot_mutate(reseller_data):
    from app.database.models import ResellerAccount
    c,sessions=reseller_data;h={'X-Telegram-Init-Data':signed()}
    async def expire():
        async with sessions() as s:
            r=await s.get(ResellerAccount,1);r.expires_at=datetime.utcnow()-timedelta(days=1);await s.commit()
    asyncio.run(expire())
    assert c.get('/api/miniapp/session',headers=h).json()['reseller']['active'] is False
    assert c.post('/api/miniapp/handoff',headers=h,json={'action':'rvol','item_id':3}).status_code==403


def test_non_reseller_has_no_partner_access(client):
    c,_=client;h={'X-Telegram-Init-Data':signed()}
    assert c.get('/api/miniapp/session',headers=h).json()['reseller'] is None
    assert c.get('/api/miniapp/reseller',headers=h).status_code==403
    assert c.post('/api/miniapp/handoff',headers=h,json={'action':'rcreate'}).status_code==403


def test_admin_miniapp_settings_and_separate_rule_cards(client,monkeypatch):
    from app.api import miniapp_admin
    from app.database.models import Setting
    import app.bot.miniapp as bridge
    _,sessions=client;app=FastAPI();app.include_router(miniapp_admin.router)
    monkeypatch.setattr(miniapp_admin,'SessionLocal',sessions)
    c=TestClient(app)
    assert c.get('/admin/api/v2/miniapp').status_code==401
    app.dependency_overrides[miniapp_admin._auth_user]=lambda:'admin'
    monkeypatch.setattr(bridge,'sync_menu_button',AsyncMock())
    bad=c.post('/admin/miniapp/save',data={'config_json':json.dumps({'support_username':'bad/path'})})
    assert bad.status_code==400
    r=c.post('/admin/miniapp/save',data={'config_json':json.dumps({'support_username':'dbot_support','title':'My D Bot','reseller_requests':False,'links':[{'label':'آموزش','url':'https://example.com/help'}]})})
    assert r.status_code==200,r.text
    draft=c.get('/admin/api/v2/miniapp').json()['config']
    assert draft['title']=='My D Bot' and draft['support_username']=='dbot_support' and draft['reseller_requests'] is False
    assert c.post('/admin/settings/rules',data={'enabled':'1','rules_text':'قوانین تازه'}).status_code==200
    monkeypatch.setattr(miniapp_admin,'_telegram_validate_destination',AsyncMock(return_value={'ok':True}))
    assert c.post('/admin/settings/force-join',data={'enabled':'1','channel_url':'@required_channel'}).status_code==200
    async def check():
        async with sessions() as s:
            assert (await s.get(Setting,'rules_text')).value=='قوانین تازه'
            assert (await s.get(Setting,'force_join_enabled')).value=='1'
            assert (await s.get(Setting,'support_username')).value=='dbot_support'
            assert (await s.get(User,1)).accepted_rules is False
    asyncio.run(check())


def test_reseller_deeplink_rechecks_owner_before_exposing_actions(reseller_data,monkeypatch):
    import app.bot.miniapp as bridge
    import app.services.miniapp_settings as cfg
    _,sessions=reseller_data
    monkeypatch.setattr(bridge,'SessionLocal',sessions)
    monkeypatch.setattr(cfg,'read_config',AsyncMock(return_value=dict(cfg.DEFAULTS)))
    message=SimpleNamespace(from_user=SimpleNamespace(id=11),chat=SimpleNamespace(id=11),answer=AsyncMock(return_value=SimpleNamespace(message_id=502)))
    state=SimpleNamespace(update_data=AsyncMock())
    asyncio.run(bridge.handle_handoff(message,state,'mini_rvol_4'))
    assert 'پیدا نشد' in message.answer.await_args.args[0]
    assert not message.answer.await_args.kwargs.get('reply_markup')
    asyncio.run(bridge.handle_handoff(message,state,'mini_rvol_3'))
    markup=message.answer.await_args.kwargs['reply_markup']
    assert markup.inline_keyboard[0][0].callback_data=='reseller:addvol:3'


def test_happ_plan_without_linked_order_delivers_same_native_link_to_copy_qr_and_bot(client,monkeypatch):
    from unittest.mock import Mock
    from app.services.xui_service import XuiService
    from app.bot import service_presenter
    import app.database.session as db_session
    c,sessions=client;h={'X-Telegram-Init-Data':signed()}
    encrypted='happ://crypt5/panel-native-payload'
    async def configure():
        async with sessions() as s:
            p=await s.get(Plan,1);p.meta={'happ_encrypted_sub':True}
            # The fixture has an imported paid order with no service_id.
            await s.commit()
    asyncio.run(configure())
    generate=AsyncMock(return_value=encrypted)
    monkeypatch.setattr(XuiService,'delivery_subscription_link',generate)
    response=c.get('/api/miniapp/services/1/link',headers=h)
    assert response.status_code==200 and response.json()=={'link':encrypted,'happ_url':encrypted}
    qr_make=Mock(wraps=miniapp.qrcode.make);monkeypatch.setattr(miniapp.qrcode,'make',qr_make)
    response=c.get('/api/miniapp/services/1/qr',headers=h)
    assert response.status_code==200 and response.content.startswith(b'\x89PNG')
    qr_make.assert_called_once_with(encrypted)
    monkeypatch.setattr(db_session,'SessionLocal',sessions)
    card=Mock(return_value='/tmp/dbot-qr-test-not-written.png');monkeypatch.setattr(service_presenter,'make_qr_card',card)
    bot=SimpleNamespace(send_photo=AsyncMock(),send_message=AsyncMock())
    asyncio.run(service_presenter.send_service_info(bot,11,'mine','۳۰ گیگ',30,30,'https://example.com/raw',allow_happ=True,service_id=1))
    assert card.call_args.args[0]==encrypted
    assert encrypted in bot.send_photo.await_args.kwargs['caption']
    assert 'https://example.com/raw' not in bot.send_photo.await_args.kwargs['caption']
    # An existing encrypted cache must not hide a panel generation failure.
    generate.return_value=None
    response=c.get('/api/miniapp/services/1/link',headers=h)
    assert response.status_code==409 and encrypted not in response.text
    bot.send_photo.reset_mock();bot.send_message.reset_mock()
    asyncio.run(service_presenter.send_service_info(bot,11,'mine','۳۰ گیگ',30,30,'https://example.com/raw',allow_happ=True,service_id=1))
    assert bot.send_photo.await_count==0
    assert 'https://example.com/raw' not in bot.send_message.await_args.args[1]


def test_normal_happ_import_does_not_encode_the_embedded_subscription(client):
    c,_=client
    result=c.get('/api/miniapp/services/1/link',headers={'X-Telegram-Init-Data':signed()}).json()
    assert result['happ_url']=='happ://add/'+result['link']
    assert result['happ_url'].startswith('happ://add/https://')


def test_plan_edit_preserves_happ_if_older_form_omits_field(client,monkeypatch):
    from app.api import admin_web as web
    c,sessions=client
    monkeypatch.setattr(web,'SessionLocal',sessions)
    app=FastAPI();app.include_router(web.router)
    async def owner():return 'owner'
    app.dependency_overrides[web._auth_user]=owner
    admin=TestClient(app)
    async def server_ready():
        async with sessions() as s:
            server=await s.get(Server,1);server.meta={**(server.meta or {}),'inbound_ids':[1]};await s.commit()
    asyncio.run(server_ready())
    form={'title':'Happ Plan','volume_gb':'30','duration_days':'30','price_irt':'100','server_id':'1','category_id':'1','happ_encrypted_sub':'yes'}
    r=admin.post('/admin/plans/1/edit',data=form,headers={'Accept':'application/json'})
    assert r.status_code==200,r.text
    form.pop('happ_encrypted_sub')
    r=admin.post('/admin/plans/1/edit',data=form,headers={'Accept':'application/json'})
    assert r.status_code==200,r.text
    async def verify():
        async with sessions() as s:assert (await s.get(Plan,1)).meta['happ_encrypted_sub'] is True
    asyncio.run(verify())


@pytest.mark.parametrize('unlimited,total,used,remaining',[(True,100,12,None),(False,0,12,None),(False,100,12,88),(False,100,120,0)])
def test_unlimited_traffic_uses_plan_flag_even_with_panel_cap(unlimited,total,used,remaining):
 svc=SimpleNamespace(id=1,client_username='mine',total_bytes=total,used_bytes=used,is_active=True,expires_at=None,created_at=None)
 data=miniapp.service_data(svc,SimpleNamespace(title='Plan',is_unlimited=unlimited),None)
 assert data['remaining_bytes']==remaining
 assert data['unlimited']==(unlimited or total==0)
 assert data['used_bytes']==used and data['total_bytes']==total
