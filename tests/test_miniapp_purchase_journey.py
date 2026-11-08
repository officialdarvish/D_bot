import asyncio
from unittest.mock import AsyncMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select,func
from test_miniapp_checkout import native,client,H,body,image_bytes
from test_miniapp import signed
from app.api import miniapp,miniapp_checkout as checkout,miniapp_payments as payments
from app.database.models import User,Order,WalletTransaction,DiscountCode,DiscountUsage,Server,ClientService

@pytest.fixture
def journey(native,monkeypatch):
    _,sessions,bot,buy=native
    monkeypatch.setattr(payments,'SessionLocal',sessions)
    app=FastAPI();app.include_router(checkout.router);app.include_router(payments.router);app.include_router(miniapp.router)
    with TestClient(app) as c:yield c,sessions,bot,buy


def test_draft_hidden_everywhere_and_cancel_deletes_it(journey):
    c,sessions,bot,buy=journey
    payload=body('card',discount_code='SAVE');payload['expected_amount_irt']=130000
    created=c.post('/api/miniapp/checkout',headers=H,json=payload).json();oid=created['id']
    assert oid not in [o['id'] for o in c.get('/api/miniapp/tracking',headers=H).json()['orders']]
    assert oid not in [o['id'] for o in c.get('/api/miniapp/checkout/orders',headers=H).json()['orders']]
    assert oid not in [o['id'] for o in c.get('/api/miniapp/session',headers=H).json()['orders']]
    assert c.get(f'/api/miniapp/checkout/orders/{oid}',headers=H).status_code==200
    other={'X-Telegram-Init-Data':signed(22)}
    assert c.post(f'/api/miniapp/checkout/orders/{oid}/cancel',headers=other,json={}).status_code==404
    for _ in range(2):assert c.post(f'/api/miniapp/checkout/orders/{oid}/cancel',headers=H,json={}).json()['deleted']
    assert c.get(f'/api/miniapp/checkout/orders/{oid}',headers=H).status_code==404
    async def verify():
        async with sessions() as s:
            assert await s.get(Order,oid) is None
            assert (await s.get(DiscountCode,1)).used_count==0
            assert await s.scalar(select(func.count(DiscountUsage.id)))==0
            assert (await s.get(User,1)).wallet_balance==250000
    asyncio.run(verify())


def test_submitted_receipt_visible_with_rejection_reason_and_not_cancellable(journey):
    c,sessions,bot,buy=journey
    oid=c.post('/api/miniapp/checkout',headers=H,json=body('card')).json()['id']
    uploaded=c.post(f'/api/miniapp/checkout/orders/{oid}/receipt',headers=H,files={'file':('r.png',image_bytes(),'image/png')})
    assert uploaded.status_code==200
    assert oid in [o['id'] for o in c.get('/api/miniapp/tracking',headers=H).json()['orders']]
    assert c.post(f'/api/miniapp/checkout/orders/{oid}/cancel',headers=H,json={}).status_code==409
    async def reject():
        async with sessions() as s:
            o=await s.get(Order,oid);o.status='rejected';o.rejection_reason='مبلغ رسید صحیح نیست';await s.commit()
    asyncio.run(reject())
    tracked=next(o for o in c.get('/api/miniapp/tracking',headers=H).json()['orders'] if o['id']==oid)
    assert tracked['status']=='rejected' and tracked['rejection_reason']=='مبلغ رسید صحیح نیست'
    assert not tracked['can_resend']
    assert c.get('/api/miniapp/tracking',headers={'X-Telegram-Init-Data':signed(22)}).json()['orders']==[]


def test_wallet_payment_is_submitted_and_cannot_be_deleted(journey):
    c,sessions,bot,buy=journey
    oid=c.post('/api/miniapp/checkout',headers=H,json=body()).json()['id']
    assert oid in [o['id'] for o in c.get('/api/miniapp/tracking',headers=H).json()['orders']]
    assert c.post(f'/api/miniapp/checkout/orders/{oid}/cancel',headers=H,json={}).status_code==409
    async def check():
        async with sessions() as s:
            assert (await s.get(User,1)).wallet_balance==111000
            assert await s.scalar(select(func.count(WalletTransaction.id)))==1
    asyncio.run(check())


@pytest.mark.parametrize('provider',['xui','pasarguard','mikrotik'])
def test_admin_free_quote_create_queue_and_duplicate_submit(journey,monkeypatch,provider):
    c,sessions,bot,buy=journey
    monkeypatch.setattr(checkout.settings,'OWNER_IDS','11')
    monkeypatch.setattr(buy,'get_public_service_types',AsyncMock(return_value=[('v2ray','VPN',provider)]))
    monkeypatch.setattr(checkout,'quote_plan',AsyncMock(side_effect=AssertionError('Free owners need no FX price')))
    async def zero():
        async with sessions() as s:
            (await s.get(User,1)).wallet_balance=0
            (await s.get(Server,1)).server_type=provider
            await s.commit()
    asyncio.run(zero())
    payload=body('admin_free',password='Secure123',discount_code='SAVE');payload['expected_amount_irt']=0
    quote=c.post('/api/miniapp/checkout/quote',headers=H,json=payload)
    assert quote.status_code==200,quote.text
    assert quote.json()['amount_irt']==0 and quote.json()['methods']==['admin_free']
    created=c.post('/api/miniapp/checkout',headers=H,json=payload);assert created.status_code==200,created.text
    oid=created.json()['id']
    assert created.json()['status']=='miniapp_queued' and created.json()['amount_irt']==0
    assert c.post('/api/miniapp/checkout',headers=H,json=payload).json()['id']==oid
    for name in ['send_buyer_notice','notify_paid_order','send_service_card','send_home','send_admin_notice','edit_admin_receipt_keyboard','report_bot_error']:
        monkeypatch.setattr(buy,name,AsyncMock())
    monkeypatch.setattr(buy,'apply_purchase_commission',AsyncMock(return_value=0))
    async def build(session,user,server,plan,name,password=None):
        service=ClientService(user_id=user.id,server_id=server.id,plan_id=plan.id,client_username=name,xui_email=name,sub_link='https://example.com/free')
        session.add(service);await session.flush();return service,service.sub_link
    create=AsyncMock(side_effect=build);monkeypatch.setattr(buy,'build_service',create)
    asyncio.run(checkout.process_wallet_queue());asyncio.run(checkout.process_wallet_queue())
    assert create.await_count==1
    final=c.get(f'/api/miniapp/checkout/orders/{oid}',headers=H).json();assert final['status']=='paid' and final['service']
    async def unchanged():
        async with sessions() as s:
            assert (await s.get(User,1)).wallet_balance==0
            assert await s.scalar(select(func.count(WalletTransaction.id)))==0
            assert (await s.get(DiscountCode,1)).used_count==0
    asyncio.run(unchanged())


def test_non_owner_cannot_request_free_method(journey,monkeypatch):
    c,_,_,_=journey
    monkeypatch.setattr(checkout.settings,'SELLER_IDS','11')
    payload=body('admin_free');payload['expected_amount_irt']=0
    assert c.post('/api/miniapp/checkout',headers=H,json=payload).status_code==403


def test_unsubmitted_funding_does_not_appear_in_tracking(journey):
    c,_,_,_=journey
    import uuid
    draft=c.post('/api/miniapp/funding',headers=H,json={'key':str(uuid.uuid4()),'kind':'wallet_topup','amount':100000,'method':'card','expected_amount':100000})
    assert draft.status_code==200,draft.text
    assert all(o.get('track_kind')!='funding' for o in c.get('/api/miniapp/tracking',headers=H).json()['orders'])
