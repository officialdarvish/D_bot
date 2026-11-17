import asyncio
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, func
from sqlalchemy.ext.asyncio import create_async_engine
from test_miniapp import client
from test_miniapp_checkout import native, H, body
from app.api import admin_web as web
from app.database.models import DiscountCode, Plan, User, Order
from app.database.discount_scope import ensure_discount_scope_columns
from app.services.discount_service import apply_discount_amount


@pytest.fixture
def admin(client, monkeypatch):
    _, sessions = client
    monkeypatch.setattr(web, 'SessionLocal', sessions)
    app = FastAPI()
    app.include_router(web.router)
    app.dependency_overrides[web._auth_user] = lambda: 'owner'
    with TestClient(app) as api:
        yield api, sessions


def form(**extra):
    return dict(code='SCOPED', discount_type='percent', value='20', max_uses='10', per_user_limit='2', allowed_server_ids='1', allowed_category_ids='1', allowed_plan_ids='1', **extra)


def test_admin_create_roundtrip_clear_and_legacy_edit_preserves_scope(admin):
    api, sessions = admin
    response = api.post('/admin/discounts/add', data=form(), headers={'Accept':'application/json'})
    assert response.status_code == 200, response.text
    data = api.get('/admin/api/v2/discounts').json()
    d = data['items'][0]
    assert d['allowed_category_ids'] == [1] and d['allowed_plan_ids'] == [1]
    assert d['allowed_category_names'] == ['اقتصادی'] and d['allowed_plan_names'] == ['۳۰ گیگ']
    assert data['categories'] and data['plans']
    legacy = form()
    del legacy['allowed_category_ids']; del legacy['allowed_plan_ids']
    assert api.post(f"/admin/discounts/{d['id']}/edit", data=legacy, headers={'Accept':'application/json'}).status_code == 200
    assert api.get('/admin/api/v2/discounts').json()['items'][0]['allowed_plan_ids'] == [1]
    clear = form(); clear.update(allowed_category_ids='', allowed_plan_ids='')
    assert api.post(f"/admin/discounts/{d['id']}/edit", data=clear, headers={'Accept':'application/json'}).status_code == 200
    updated = api.get('/admin/api/v2/discounts').json()['items'][0]
    assert updated['allowed_plan_ids'] == updated['allowed_category_ids'] == []


@pytest.mark.parametrize('field,value', [('allowed_category_ids','999'),('allowed_plan_ids','999'),('allowed_category_ids','oops'),('allowed_plan_ids','[1, "bad"]')])
def test_unknown_or_malformed_ids_do_not_create_unrestricted_code(admin, field, value):
    api, _ = admin
    payload = form(); payload[field] = value
    assert api.post('/admin/discounts/add', data=payload, headers={'Accept':'application/json'}).status_code == 400
    assert api.get('/admin/api/v2/discounts').json()['items'] == []


@pytest.mark.parametrize('cats,plans,server,plan,accepted', [([],[],1,None,True),([1],[],1,1,True),([2],[],1,1,False),([],[2],1,1,False),([1],[1],1,1,True),([2],[1],1,1,False),([1],[1],2,1,False),([1],[1],1,None,False)])
def test_shared_validation_intersection_and_unrestricted_legacy(client, cats, plans, server, plan, accepted):
    _, sessions = client
    async def run():
        async with sessions() as s:
            d = DiscountCode(code='SCOPED',discount_type='percent',value=20,max_uses=20,per_user_limit=2,allowed_server_ids=[1],allowed_category_ids=cats,allowed_plan_ids=plans)
            s.add(d); await s.commit()
            amount,error,obj = await apply_discount_amount(s,'scoped',100000,1,'renew',server,plan_id=plan)
            assert (error is None) == accepted
            assert amount == (80000 if accepted else 100000)
            assert d.used_count == 0  # validation must never reserve a usage
    asyncio.run(run())


def test_miniapp_quote_and_final_purchase_recheck_target_plan(native):
    api,sessions,_,_ = native
    async def restrict(plans):
        async with sessions() as s:
            d=await s.get(DiscountCode,1); d.allowed_category_ids=[1]; d.allowed_plan_ids=plans
            await s.commit()
    asyncio.run(restrict([1]))
    assert api.post('/api/miniapp/checkout/quote',headers=H,json={'plan_id':1,'username':'native','discount_code':'SAVE'}).status_code == 200
    asyncio.run(restrict([2]))
    async def order_count():
        async with sessions() as s:
            return await s.scalar(select(func.count(Order.id)))
    before = asyncio.run(order_count())
    payload=body(discount_code='SAVE'); payload['expected_amount_irt']=130000
    r=api.post('/api/miniapp/checkout',headers=H,json=payload)
    assert r.status_code == 409, r.text
    async def verify():
        async with sessions() as s:
            assert (await s.scalar(select(func.count(Order.id)))) == before
            assert (await s.get(User,1)).wallet_balance == 250000
    asyncio.run(verify())


def test_additive_existing_schema_migration_is_idempotent(tmp_path):
    async def run():
        engine=create_async_engine('sqlite+aiosqlite:///'+str(tmp_path/'old.db'))
        async with engine.begin() as conn:
            await conn.exec_driver_sql('CREATE TABLE discount_codes (id INTEGER PRIMARY KEY, code TEXT)')
            await conn.exec_driver_sql("INSERT INTO discount_codes VALUES (1,'OLD')")
            await ensure_discount_scope_columns(conn)
            await ensure_discount_scope_columns(conn)
            row=(await conn.exec_driver_sql('SELECT code, allowed_category_ids, allowed_plan_ids FROM discount_codes')).one()
            assert tuple(row) == ('OLD','[]','[]')
        await engine.dispose()
    asyncio.run(run())
