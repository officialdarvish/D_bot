"""Catalogue bindings must distinguish services using the same panel provider."""
import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.api import admin_web as web
from app.api import main as main_api
from app.bot.handlers.public import buy
from app.database.base import Base
from app.database.models import Setting, Server, ServerCategory, Plan
from app.services.catalog_settings import category_service_bindings, categories_for_service, service_badges
from app.services.miniapp_catalog import public_catalog, public_plans

A = 'service_type:custom:economy'
B = 'service_type:custom:premium'


@pytest.fixture
def catalogue(tmp_path, monkeypatch):
    engine = create_async_engine('sqlite+aiosqlite:///' + str(tmp_path / 'catalog.db'))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async def seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with sessions() as s:
            s.add_all([
                Setting(key=A, value='اقتصادی'), Setting(key=B, value='ویژه'),
                Setting(key='service_type_provider:economy', value='v2ray'),
                Setting(key='service_type_provider:premium', value='v2ray'),
                Setting(key='web_credentials_updated_at', value='v1'),
                Server(id=1, name='Sanaei', server_type='xui', panel_url='https://panel.example', username='u', password_encrypted='p', is_active=True, meta={'scope':'public'}),
                ServerCategory(id=1, name='Germany', server_ids=[1], server_id=1, is_active=True),
                ServerCategory(id=2, name='Legacy', server_ids=[1], server_id=1, is_active=True),
                Plan(id=1, title='Germany 20G', volume_gb=20, duration_days=30, price_irt=10000, server_id=1, category_id=1, is_active=True),
                Plan(id=2, title='Legacy 10G', volume_gb=10, duration_days=30, price_irt=5000, server_id=1, category_id=2, is_active=True),
            ])
            await s.commit()
    asyncio.run(seed())
    for module in (web, main_api, buy):
        monkeypatch.setattr(module, 'SessionLocal', sessions)
    monkeypatch.setattr(web, '_sessions', {'valid': {'username':'owner', 'expires_at':datetime.utcnow()+timedelta(hours=1), 'credential_version':'v1', 'csrf':'csrf'}})
    app = FastAPI(); app.include_router(web.router)
    app.get('/admin/api/v2/service-types', dependencies=[])(main_api.api_service_types)
    with TestClient(app) as c:
        c.cookies.set('dbot_admin_token', 'valid')
        c.headers.update({'Accept':'application/json', 'X-CSRF-Token':'csrf'})
        yield c, sessions
    asyncio.run(engine.dispose())


def run_catalog(sessions):
    async def read():
        async with sessions() as s:
            return await public_catalog(s)
    return asyncio.run(read())


def test_binding_routes_one_category_to_one_service_and_switches_without_plan_changes(catalogue):
    c, sessions = catalogue
    def assign(key):
        r = c.post('/admin/categories/1/edit', data={'name':'Germany','server_ids':'1','service_type_key':key})
        assert r.status_code == 200, r.text
    assign(A)
    listed = c.get('/admin/api/v2/categories').json()['items']
    germany = next(x for x in listed if x['id']==1)
    assert germany['service_type_key']==A and germany['service_type_name']=='اقتصادی'
    catalog = run_catalog(sessions)
    assert [g['type_key'] for g in catalog['categories'] if 1 in g['plan_ids']] == ['economy']
    assert {g['type_key'] for g in catalog['categories'] if 2 in g['plan_ids']} == {'economy','premium'}
    assign(B)
    assert [g['type_key'] for g in run_catalog(sessions)['categories'] if 1 in g['plan_ids']] == ['premium']
    # Omitted by legacy clients: preserve the explicit setting.
    assert c.post('/admin/categories/1/edit',data={'name':'Germany renamed','server_ids':'1'}).status_code==200
    assert [g['type_key'] for g in run_catalog(sessions)['categories'] if 1 in g['plan_ids']] == ['premium']
    async def unchanged():
        async with sessions() as s:
            plan = await s.get(Plan, 1)
            assert (plan.server_id,plan.volume_gb,plan.price_irt)==(1,20,10000)
    asyncio.run(unchanged())
    assign('')
    assert {g['type_key'] for g in run_catalog(sessions)['categories'] if 1 in g['plan_ids']} == {'economy','premium'}


def test_create_validation_missing_service_and_hidden_bound_type(catalogue):
    c, sessions = catalogue
    for key in ('service_type:custom:missing', 'web_admin_password', A+':active'):
        r=c.post('/admin/categories/add',data={'name':'New','server_ids':'1','service_type_key':key})
        assert r.status_code==400
    assert c.post('/admin/categories/add',data={'name':'New','server_ids':'1','service_type_key':A}).status_code==200
    new=next(x for x in c.get('/admin/api/v2/categories').json()['items'] if x['name']=='New')
    assert new['service_type_key']==A
    assert c.post('/admin/categories/1/edit',data={'name':'Germany','server_ids':'1','service_type_key':A}).status_code==200
    assert c.post('/admin/service-types/toggle',params={'key':A}).status_code==200
    assert all(1 not in g['plan_ids'] for g in run_catalog(sessions)['categories'])
    async def hidden():
        async with sessions() as s:
            assert 1 not in {p.id for p,_,_ in await public_plans(s)}
    asyncio.run(hidden())


def test_duplicate_legacy_ids_get_same_binding_and_keep_their_plan(catalogue):
    c,sessions=catalogue
    async def seed():
        async with sessions() as s:
            s.add(ServerCategory(id=3,name='Germany',server_id=1,is_active=False))
            s.add(Plan(id=3,title='Old plan',price_irt=9000,server_id=1,category_id=3,is_active=True))
            await s.commit()
    asyncio.run(seed())
    assert c.post('/admin/categories/1/edit',data={'name':'Germany','server_ids':'1','service_type_key':B}).status_code==200
    async def verify():
        async with sessions() as s:
            mappings=await category_service_bindings(s)
            assert mappings[1]==B and mappings[3]==B
            assert (await s.get(Plan,3)).category_id==1
    asyncio.run(verify())
    assert {g['type_key'] for g in run_catalog(sessions)['categories'] if 3 in g['plan_ids']}=={'premium'}


def test_service_color_roundtrip_rename_and_invalid_input_are_safe(catalogue):
    c,sessions=catalogue
    payload={'key':A,'name':'Economic renamed','server_type':'v2ray','badge_color':'#AA00FF'}
    assert c.post('/admin/service-types/edit',data=payload).status_code==200
    item=next(x for x in c.get('/admin/api/v2/service-types').json()['items'] if x['key']==A)
    assert item['badge_color']=='#aa00ff' and item['badge_emoji']=='🟣' and item['value']=='Economic renamed'
    assert next(t for t in run_catalog(sessions)['service_types'] if t['key']=='economy')['badge_color']=='#aa00ff'
    for bad in ('red', '#xyzxyz', '#fff;display:none', 'url(example)'):
        assert c.post('/admin/service-types/edit',data={**payload,'badge_color':bad}).status_code==400
    payload.pop('badge_color')
    assert c.post('/admin/service-types/edit',data=payload).status_code==200
    assert next(x for x in c.get('/admin/api/v2/service-types').json()['items'] if x['key']==A)['badge_color']=='#aa00ff'
    assert c.post('/admin/service-types/add',data={'name':'New Service','server_type':'xui','badge_color':'#ff0000'}).status_code==200
    assert next(x for x in c.get('/admin/api/v2/service-types').json()['items'] if x['value']=='New Service')['badge_emoji']=='🔴'


def test_bot_menu_color_and_category_binding_match_miniapp(catalogue, monkeypatch):
    c,sessions=catalogue
    assert c.post('/admin/categories/1/edit',data={'name':'Germany','server_ids':'1','service_type_key':A}).status_code==200
    assert c.post('/admin/service-types/edit',data={'key':A,'name':'Economy','server_type':'v2ray','badge_color':'#ff0000'}).status_code==200
    output=AsyncMock(); monkeypatch.setattr(buy,'edit_or_answer',output)
    monkeypatch.setattr(buy,'safe_callback_answer',AsyncMock())
    state=SimpleNamespace(clear=AsyncMock(),update_data=AsyncMock())
    asyncio.run(buy.buy_start(SimpleNamespace(),state))
    rows=output.await_args.kwargs['reply_markup'].inline_keyboard
    assert rows[0][0].text.startswith('🔴 Economy')
    output.reset_mock()
    asyncio.run(buy.buy_type(SimpleNamespace(data='buy:type:premium'),state))
    labels=[button.text for row in output.await_args.kwargs['reply_markup'].inline_keyboard for button in row]
    assert 'Germany' not in labels and 'Legacy' in labels
    # Stale category buttons cannot reveal plans after the category moves services.
    output.reset_mock()
    state.get_data=AsyncMock(return_value={'kind':'premium','server_ids':[1],'category_groups':{'0':[1]}})
    asyncio.run(buy.buy_category(SimpleNamespace(data='buy:catgrp:0'),state))
    assert output.await_args.args[1].startswith('این دسته غیرفعال')


def test_write_requires_valid_session_and_csrf(catalogue):
    c,_=catalogue
    assert c.post('/admin/categories/1/edit',data={'name':'Germany','server_ids':'1','service_type_key':A},headers={'X-CSRF-Token':'wrong'}).status_code==403
    c.cookies.clear()
    assert c.post('/admin/service-types/edit',data={'key':A,'name':'Rename','badge_color':'#ff0000'}).status_code==401
