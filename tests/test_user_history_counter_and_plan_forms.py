import asyncio
import importlib.util
from datetime import datetime,timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select,func
from test_miniapp import client
from test_miniapp_native_actions import native,H,funding
from app.api import admin_web as web
from app.database.models import Order,Plan,ClientService,ResellerPackage,ResellerTopupRequest,User,Server
from app.services.custom_tariff import normalize,reseller_selection,reseller_snapshot,package_available

POLICY=dict(enabled=True,min_gb=1,max_gb=100,min_days=1,max_days=90,price_gb=10000,price_day=1000)

@pytest.fixture
def admin(client,monkeypatch):
    _,sessions=client;monkeypatch.setattr(web,'SessionLocal',sessions)
    app=FastAPI();app.include_router(web.router);app.dependency_overrides[web._auth_user]=lambda:'owner'
    with TestClient(app) as c:yield c,sessions

def test_history_pagination_and_secrets(admin):
    c,sessions=admin
    async def seed():
        async with sessions() as s:
            o=await s.get(Order,1);o.service_id=1
            for i in range(51):s.add(Order(user_id=1,plan_id=1,service_id=1,amount_irt=i,payment_method='renew:wallet',status='paid',created_at=datetime(2026,1,1)+timedelta(days=i)))
            # Corrupted legacy cross-user link must never reveal the other config.
            s.add(Order(user_id=1,service_id=2,amount_irt=5,payment_method='wallet',status='paid'))
            await s.commit()
    asyncio.run(seed())
    a=c.get('/admin/api/v2/users/1/history').json();b=c.get('/admin/api/v2/users/1/history?page=2').json()
    assert a['total']==53 and len(a['items'])==50 and len(b['items'])==3
    assert not set(x['id'] for x in a['items'])&set(x['id'] for x in b['items'])
    assert any(x['kind']=='renewal' for x in a['items'])
    assert a['services'][0]['username']=='mine' and a['services_total']==1
    assert 'sub_link' not in str(a) and 'password' not in str(a) and 'other' not in str(a)
    assert c.get('/admin/api/v2/users/999/history').status_code==404

def test_history_and_count_require_auth():
    app=FastAPI();app.include_router(web.router)
    with TestClient(app) as c:
        for url in ['/admin/api/v2/users/1/history','/admin/api/v2/installation-count']:
            assert c.get(url,headers={'Accept':'application/json'}).status_code==401

@pytest.mark.parametrize('kind',['public','reseller'])
def test_custom_plan_without_hidden_fixed_inputs(admin,kind):
    c,sessions=admin
    async def prepare_server():
        async with sessions() as s:
            srv=await s.get(Server,1);srv.meta={**(srv.meta or {}),'inbound_ids':[1]};await s.commit()
    asyncio.run(prepare_server())
    data=dict(plan_kind=kind,title='Custom range',server_id=1,category_id=1,pricing_currency='USD',custom_enabled='yes',**{'custom_'+k:str(v) for k,v in POLICY.items() if k!='enabled'})
    response=c.post('/admin/plans/add',data=data,headers={'Accept':'application/json','X-Requested-With':'fetch'})
    assert response.status_code==200,response.text
    async def verify():
        async with sessions() as s:
            cls=Plan if kind=='public' else ResellerPackage
            row=await s.scalar(select(cls).where(cls.title=='Custom range'))
            assert row.volume_gb==1 and row.price_irt==11000 and row.meta['custom_tariff']==POLICY
            assert (row.duration_days if kind=='public' else row.reseller_validity_days)==1
            assert row.meta['pricing_currency']=='IRT'
    asyncio.run(verify())
    bad={**data,'custom_min_gb':'101'}
    assert c.post('/admin/plans/add',data=bad,headers={'Accept':'application/json'}).status_code==400

def test_custom_reseller_checkout_immutable_price_and_replay(native):
    c,sessions,*_=native
    async def setup():
        async with sessions() as s:
            p=await s.get(ResellerPackage,1);p.meta={'custom_tariff':POLICY};await s.commit()
    asyncio.run(setup())
    body={**funding(), 'volume_gb':20,'duration_days':30,'expected_amount':230000}
    quote=c.post('/api/miniapp/funding/quote',headers=H,json=body)
    assert quote.status_code==200,quote.text
    assert quote.json()['amount']==230000
    assert c.post('/api/miniapp/funding/quote',headers=H,json={**body,'volume_gb':101}).status_code==422
    result=c.post('/api/miniapp/funding',headers=H,json=body);assert result.status_code==200,result.text
    assert c.post('/api/miniapp/funding',headers=H,json=body).json()['id']==result.json()['id']
    assert c.post('/api/miniapp/funding',headers=H,json={**body,'duration_days':31}).status_code==409
    async def verify():
        async with sessions() as s:
            req=await s.scalar(select(ResellerTopupRequest));p=await s.get(ResellerPackage,req.package_id)
            assert p.id!=1 and p.volume_gb==20 and p.reseller_validity_days==30 and p.price_irt==230000
            assert package_available(p,11) and not package_available(p,22)
            assert (await s.get(User,1)).wallet_balance==20000
            original=await s.get(ResellerPackage,1);original.meta={};original.volume_gb=999;await s.commit()
            assert p.volume_gb==20 and p.reseller_validity_days==30
    asyncio.run(verify())

def test_anonymous_counter_deduplicates_expires_and_never_lists(tmp_path,monkeypatch):
    path=Path(__file__).parents[1]/'integrations/installation_counter/service.py'
    spec=importlib.util.spec_from_file_location('anonymous_counter_service',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setattr(module,'DATABASE',tmp_path/'count.sqlite');clock=[100000];monkeypatch.setattr(module.time,'time',lambda:clock[0])
    with TestClient(module.app) as c:
        assert c.post('/heartbeat',content='a'*64).status_code==200
        assert c.post('/heartbeat',content='a'*64).status_code==200
        assert c.post('/heartbeat',content='b'*64).status_code==200
        assert c.get('/count').json()['count']==2
        assert c.post('/heartbeat',content='x'*129).status_code==413
        assert c.post('/heartbeat',content='email@example.com').status_code==422
        for url in ['/installations','/users','/docs','/openapi.json']:assert c.get(url).status_code==404
        clock[0]+=901;assert c.get('/count').json()['count']==0
        c.post('/heartbeat',content='a'*64);assert c.get('/count').json()['count']==1
    import sqlite3
    with sqlite3.connect(tmp_path/'count.sqlite') as db:
        assert [row[1] for row in db.execute('PRAGMA table_info(installations)')]==['token_hash','seen']
        assert all(row[0] not in {'a'*64,'b'*64} for row in db.execute('SELECT token_hash FROM installations'))

def test_counter_disabled_by_default_and_token_stable(tmp_path,monkeypatch):
    from app.services import installation_counter as counter
    monkeypatch.delenv('DBOT_COUNTER_ENABLED',raising=False);monkeypatch.setenv('DBOT_COUNTER_URL','https://count.example.com');monkeypatch.setenv('DBOT_INSTALLATION_DIR',str(tmp_path/'identity'))
    monkeypatch.setattr(counter.httpx,'AsyncClient',lambda **kw:pytest.fail('Disabled counter must not report'))
    asyncio.run(counter.heartbeat());assert not (tmp_path/'identity').exists()
    token=counter.installation_token();assert counter.installation_token()==token and len(token)==64
    assert (tmp_path/'identity/token').stat().st_mode&0o777==0o600

def test_home_message_save_persists_in_custom(admin,monkeypatch):
    from app.bot import custom_texts
    from app.database.models import Setting
    c,sessions=admin;monkeypatch.setattr(custom_texts,'SessionLocal',sessions)
    response=c.post('/admin/settings/home-message',data={'welcome_text':'خانه جدید / New home'},headers={'Accept':'application/json'})
    assert response.status_code==200,response.text
    async def verify():
        async with sessions() as s:
            assert (await s.get(Setting,'welcome_text')).value=='خانه جدید / New home'
    asyncio.run(verify());custom_texts.invalidate_custom_text_cache()
