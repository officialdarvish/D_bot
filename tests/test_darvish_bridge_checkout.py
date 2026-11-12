import asyncio,hashlib,hmac,json,time
from unittest.mock import AsyncMock
import pytest
from fastapi import HTTPException
from test_miniapp import client
from test_miniapp_checkout import native,H,body
from app.services import darvish_bridge as bridge
from app.database.models import Setting,User,Order,Plan
from app.core.security import encrypt_text,decrypt_text
from app.api import miniapp_checkout as checkout

CONNECTION={'enabled':True,'url':'https://bridge.test','bot_username':'bridge_bot','currency':'IRT','key':'merchant-key','secret':'s'*32}


def configure(sessions,monkeypatch):
    async def save():
        async with sessions() as session:
            await session.merge(Setting(key=bridge.KEY,value=encrypt_text(json.dumps(CONNECTION))));await session.commit()
    asyncio.run(save())


def mock_invoices(monkeypatch):
    invoices={};calls=[]
    async def request(connection,method,path,**kwargs):
        calls.append((connection.copy(),method,path,kwargs))
        if method=='POST' and path=='/orders':
            payload=kwargs['json'];external=payload['external_order_id']
            if external not in invoices:invoices[external]={'id':'inv-'+external.split(':')[1],**payload,'status':'awaiting_receipt'}
            return {'order':invoices[external]}
        if method=='POST' and path.endswith('/delivery'):return {'status':'fulfilled'}
        return next(v for v in invoices.values() if path.endswith('/'+v['id']))
    monkeypatch.setattr(bridge,'request',request)
    return invoices,calls


def sign(data,*,timestamp=None,secret=CONNECTION['secret']):
    raw=json.dumps(data,separators=(',',':')).encode();timestamp=timestamp or str(int(time.time()))
    return raw,timestamp,hmac.new(secret.encode(),timestamp.encode()+b'.'+raw,hashlib.sha256).hexdigest()


def test_bridge_quote_invoice_no_wallet_debit_and_immutable_connection(native,monkeypatch):
    c,sessions,bot,buy=native;configure(sessions,monkeypatch);invoices,calls=mock_invoices(monkeypatch)
    quote=c.post('/api/miniapp/checkout/quote',headers=H,json={'plan_id':1,'username':'native_customer'}).json()
    assert 'bridge' in quote['methods'] and quote['bridge']['amount_minor']==139000 and 'connection' not in quote['bridge']
    payload=body('bridge',expected_bridge_minor=139000)
    result=c.post('/api/miniapp/checkout',headers=H,json=payload)
    assert result.status_code==200,result.text
    order=result.json();assert order['status']=='waiting_bridge'
    assert order['bridge']['url']==f'https://t.me/bridge_bot?start=order_inv-{order["id"]}'
    again=c.post('/api/miniapp/checkout',headers=H,json=payload).json()
    assert again['id']==order['id'] and len(invoices)==1
    async def verify():
        async with sessions() as session:
            assert (await session.get(User,1)).wallet_balance==250000
            row=await session.get(Order,order['id']);snapshot=bridge.order_connection(row)
            assert snapshot==CONNECTION and CONNECTION['secret'] not in row.pricing_meta['bridge_connection']
    asyncio.run(verify())
    tamper=body('bridge',expected_bridge_minor=1)
    assert c.post('/api/miniapp/checkout',headers=H,json=tamper).status_code==409


def test_webhook_requires_signature_amount_remote_verification_and_does_not_requeue(native,monkeypatch):
    c,sessions,bot,buy=native;configure(sessions,monkeypatch);invoices,calls=mock_invoices(monkeypatch)
    order=c.post('/api/miniapp/checkout',headers=H,json=body('bridge',expected_bridge_minor=139000)).json();oid=order['id'];invoice=invoices[f'dbot:{oid}']
    event={'event':'order.approved','event_id':'event-1','external_order_id':f'dbot:{oid}','order_id':invoice['id'],'amount_minor':139000,'currency':'IRT'}
    async def receive(raw,ts,sig,event_id='event-1'):
        async with sessions() as session:return await bridge.receive_event(session,raw,ts,sig,event_id)
    raw,ts,sig=sign(event)
    with pytest.raises(ValueError):asyncio.run(receive(raw,ts,'a'*64))
    with pytest.raises(ValueError):asyncio.run(receive(*sign(event,timestamp=str(int(time.time())-301))))
    with pytest.raises(ValueError):asyncio.run(receive(raw,ts,sig)) # Bridge still waiting for receipt.
    invoice['status']='fulfillment_pending'
    bad={**event,'amount_minor':1}
    with pytest.raises(ValueError):asyncio.run(receive(*sign(bad)))
    # Rotating the current connection does not invalidate pending invoices.
    async def rotate():
        async with sessions() as session:
            await session.merge(Setting(key=bridge.KEY,value=encrypt_text(json.dumps({**CONNECTION,'secret':'new'*12,'key':'new'}))));await session.commit()
    asyncio.run(rotate())
    assert asyncio.run(receive(raw,ts,sig))=={'ok':True}
    assert asyncio.run(receive(raw,ts,sig))['duplicate']
    async def processing():
        async with sessions() as session:
            row=await session.get(Order,oid);assert row.status=='miniapp_queued';row.status='paid';await session.commit()
    asyncio.run(processing())
    new={**event,'event_id':'event-2'}
    asyncio.run(receive(*sign(new),event_id='event-2'))
    async def verify():
        async with sessions() as session:assert (await session.get(Order,oid)).status=='paid'
    asyncio.run(verify())


def test_delivery_report_requires_actual_buyer_delivery(native,monkeypatch):
    c,sessions,_,_=native;configure(sessions,monkeypatch);invoices,calls=mock_invoices(monkeypatch)
    oid=c.post('/api/miniapp/checkout',headers=H,json=body('bridge',expected_bridge_minor=139000)).json()['id']
    async def scenario():
        async with sessions() as session:
            order=await session.get(Order,oid);order.status='paid';await session.commit()
            await bridge.report_deliveries(session)
            assert not [x for x in calls if x[2].endswith('/delivery')]
            order.pricing_meta={**order.pricing_meta,'buyer_delivery_done':True};await session.commit()
            await bridge.report_deliveries(session);await bridge.report_deliveries(session)
    asyncio.run(scenario())
    assert len([x for x in calls if x[2].endswith('/delivery')])==1


def test_config_requires_https_and_keeps_blank_credentials():
    assert bridge.normalize({'key':'','secret':''},CONNECTION)==CONNECTION
    for values in [{'url':'http://bridge.test'},{'currency':'USDT'},{'bot_username':'https://attacker.test'}]:
        with pytest.raises(ValueError):bridge.normalize(values,CONNECTION)


def test_bridge_settings_are_authenticated_mask_secrets_and_precede_admin_catchall(native,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api import darvish_bridge as api
    c,sessions,_,_=native;configure(sessions,monkeypatch)
    monkeypatch.setattr(api,'SessionLocal',sessions)
    app=FastAPI();app.include_router(api.router)
    with TestClient(app) as client:
        assert client.get('/admin/api/v2/darvish-bridge',headers={'X-Requested-With':'fetch'}).status_code==401
        app.dependency_overrides[api._auth_user]=lambda:'owner'
        response=client.get('/admin/api/v2/darvish-bridge').json()
        assert response['key_saved'] and response['secret_saved']
        assert CONNECTION['key'] not in json.dumps(response) and CONNECTION['secret'] not in json.dumps(response)
    from pathlib import Path
    source=Path('app/api/main.py').read_text()
    assert source.index('app.include_router(darvish_bridge_router)')<source.index("@app.get('/admin/{path:path}'")


def test_payment_settings_connect_validate_encrypt_and_sync_checkout(native,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api import darvish_bridge as api
    c,sessions,_,_=native
    monkeypatch.setattr(api,'SessionLocal',sessions)
    remote=AsyncMock(return_value={'product_kinds':['digital'],'currencies':{'IRT':0}})
    monkeypatch.setattr(bridge,'request',remote)
    app=FastAPI();app.include_router(api.router)
    values={**CONNECTION,'enabled':'1'}
    with TestClient(app) as admin:
        assert admin.post('/admin/darvish-bridge/save',data=values,headers={'X-Requested-With':'fetch'}).status_code==401
        app.dependency_overrides[api._auth_user]=lambda:'owner'
        result=admin.post('/admin/darvish-bridge/save',data=values)
        assert result.status_code==200,result.text
        remote.assert_awaited_once()
        assert remote.await_args.args[1:]==('GET','/capabilities')
        data=admin.get('/admin/api/v2/darvish-bridge').json()
        assert data['config']['enabled'] and data['key_saved'] and data['secret_saved']
        assert CONNECTION['secret'] not in json.dumps(data) and CONNECTION['key'] not in json.dumps(data)
        async def stored():
            async with sessions() as session:
                from app.database.models import Setting
                row=await session.get(Setting,bridge.KEY)
                assert CONNECTION['secret'] not in row.value and CONNECTION['key'] not in row.value
                assert (await bridge.config(session))['key']==CONNECTION['key']
        asyncio.run(stored())
        quote=c.post('/api/miniapp/checkout/quote',headers=H,json={'plan_id':1,'username':'bridgeconfig'}).json()
        assert 'bridge' in quote['methods'],quote
        # Reject unsupported connection changes without replacing the working config.
        remote.return_value={'product_kinds':[],'currencies':{'IRT':0}}
        assert admin.post('/admin/darvish-bridge/save',data={**values,'url':'https://wrong.example.com','key':'','secret':''}).status_code==422
        assert admin.get('/admin/api/v2/darvish-bridge').json()['config']['url']==CONNECTION['url']
        assert admin.post('/admin/darvish-bridge/save',data={**values,'enabled':'0','key':'','secret':''}).status_code==200
        data=admin.get('/admin/api/v2/darvish-bridge').json()
        assert not data['config']['enabled'] and data['key_saved'] and data['secret_saved']
        quote=c.post('/api/miniapp/checkout/quote',headers=H,json={'plan_id':1,'username':'bridgeconfig'}).json()
        assert 'bridge' not in quote['methods']

def test_toman_amounts_are_exact_without_exchange_lookup(native,monkeypatch):
    c,sessions,_,_=native;configure(sessions,monkeypatch)
    from app.services import live_pricing
    rate=AsyncMock(side_effect=AssertionError('Bridge must not fetch exchange rates'))
    monkeypatch.setattr(live_pricing,'wallex_usdt_tmn_rate',rate)
    async def check():
        async with sessions() as session:
            for amount in [1,280000,10**16]:
                q=await bridge.quote(session,amount)
                assert q['amount_minor']==amount and q['currency']=='IRT' and q['scale']==0
            for bad in [0,-1,True,1.5,'280000',10**16+1]:
                with pytest.raises(ValueError):await bridge.quote(session,bad)
    asyncio.run(check());rate.assert_not_awaited()
    for currency in ['USD','USDT','IRR']:
        with pytest.raises(ValueError):bridge.normalize({'currency':currency,'enabled':'0'})


def test_legacy_currency_requires_revalidation_and_keeps_old_invoice_snapshot(native,monkeypatch):
    c,sessions,_,_=native;configure(sessions,monkeypatch);invoices,_=mock_invoices(monkeypatch)
    order=c.post('/api/miniapp/checkout',headers=H,json=body('bridge',expected_bridge_minor=139000)).json();oid=order['id']
    legacy={**CONNECTION,'currency':'USDT'}
    invoice=invoices[f'dbot:{oid}'];invoice.update(currency='USDT',amount_minor=1390000,status='fulfillment_pending')
    async def migrate():
        async with sessions() as session:
            row=await session.get(Order,oid)
            row.pricing_meta={**row.pricing_meta,'bridge_currency':'USDT','bridge_amount_minor':1390000,'bridge_connection':encrypt_text(json.dumps(legacy))}
            await session.merge(Setting(key=bridge.KEY,value=encrypt_text(json.dumps(legacy))));await session.commit()
            settings=await bridge.config(session)
            assert not settings['enabled'] and settings['currency']=='IRT' and settings['requires_toman_setup']
            assert settings['key']==CONNECTION['key'] and settings['secret']==CONNECTION['secret']
            assert await bridge.quote(session,280000) is None
            event={'event':'order.approved','event_id':'legacy-event','external_order_id':f'dbot:{oid}','order_id':invoice['id'],'amount_minor':1390000,'currency':'USDT'}
            raw,ts,sig=sign(event)
            assert await bridge.receive_event(session,raw,ts,sig,'legacy-event')=={'ok':True}
            assert row.pricing_meta['bridge_currency']=='USDT' and row.status=='miniapp_queued'
    asyncio.run(migrate())


def test_capabilities_require_zero_scale_toman(native,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api import darvish_bridge as api
    _,sessions,_,_=native;monkeypatch.setattr(api,'SessionLocal',sessions)
    remote=AsyncMock();monkeypatch.setattr(bridge,'request',remote)
    app=FastAPI();app.include_router(api.router);app.dependency_overrides[api._auth_user]=lambda:'owner'
    with TestClient(app) as c:
        for currencies in [{'USDT':6},{'IRT':2},{'IRT':False},{'IRT':'0'}]:
            remote.return_value={'product_kinds':['digital'],'currencies':currencies}
            assert c.post('/admin/darvish-bridge/save',data={**CONNECTION,'enabled':'1'}).status_code==422
        remote.return_value={'product_kinds':['digital'],'currencies':{'IRT':0}}
        assert c.post('/admin/darvish-bridge/save',data={**CONNECTION,'enabled':'1'}).status_code==200
