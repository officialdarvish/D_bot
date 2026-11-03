import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import select, func
from test_miniapp import client
from test_miniapp_native_actions import native as partner_native, action, H
from test_miniapp_pasarguard_wallet import pg_wallet, native
from test_miniapp_checkout import body
from app.bot.handlers.public import buy, reseller
from app.bot.states.public_states import BuyFlow, ResellerCreateUser
from app.services.pasarguard_service import pasarguard_username_error, PasarGuardService
from app.database.models import Server, MiniAppOperation, User, Order, WalletTransaction

REAL_RESELLER_ERROR = reseller.get_reseller_username_error
REAL_PUBLIC_ERROR = buy.get_service_username_error


@pytest.mark.parametrize('name,part', [('a','۳'), ('ab','۳'), ('نام','انگلیسی'),
                                      ('ali user','فاصله'), ('ali__01','پشت سر هم'),
                                      ('ali.-01','پشت سر هم'), ('a'*33,'32')])
def test_shared_rules_have_actionable_errors(name, part):
    assert part in pasarguard_username_error(name)


@pytest.mark.parametrize('name', ['ali', 'Ali_01', 'ali-01', 'ali.01', 'ali@01', 'a'*32])
def test_standard_names_are_accepted(name):
    assert pasarguard_username_error(name) is None


@pytest.mark.parametrize('flow', ['public', 'reseller'])
@pytest.mark.parametrize('case', ['short', 'characters', 'consecutive', 'duplicate', 'offline'])
def test_telegram_remains_at_username_step(monkeypatch, flow, case):
    name = {'short':'ab','characters':'ali user','consecutive':'ali__01'}.get(case, 'AliUser')
    server = SimpleNamespace(id=1,server_type='pasarguard',is_active=True,meta={})
    user = SimpleNamespace(id=1)
    account = SimpleNamespace(id=1,is_active=True)
    session = SimpleNamespace(get=AsyncMock(side_effect=lambda model, ident: server if model is Server else SimpleNamespace(id=1)),
                              execute=AsyncMock(return_value=SimpleNamespace(scalar_one=lambda:user)))
    @asynccontextmanager
    async def sessions():yield session
    module = buy if flow == 'public' else reseller
    monkeypatch.setattr(module,'SessionLocal',sessions)
    exists = AsyncMock(return_value=case=='duplicate',side_effect=RuntimeError('پنل در دسترس نیست') if case=='offline' else None)
    monkeypatch.setattr(module,'service_username_exists' if flow=='public' else 'reseller_username_exists',exists)
    message = SimpleNamespace(text=name,from_user=SimpleNamespace(id=11))
    state = SimpleNamespace(get_data=AsyncMock(return_value={'server_id':1,'plan_id':1,'reseller_target_server_id':1}),
                            set_state=AsyncMock(),update_data=AsyncMock(),clear=AsyncMock())
    shown = AsyncMock()
    monkeypatch.setattr(module,'ui_message',shown)
    if flow == 'public':
        monkeypatch.setattr(buy,'ask_for_another_username',shown)
        awaitable = buy.buy_username(message,state)
    else:
        monkeypatch.setattr(reseller,'get_user_reseller',AsyncMock(return_value=(user,account)))
        monkeypatch.setattr(reseller,'is_reseller_access_active',lambda _:True)
        monkeypatch.setattr(reseller,'resolve_reseller_build_target',AsyncMock(return_value=(server,[7])))
        monkeypatch.setattr(reseller,'reseller_server_policy',lambda *_:('manual',[7]))
        resolver=AsyncMock()
        monkeypatch.setattr(reseller,'resolve_reseller_username',resolver)
        awaitable = reseller.reseller_create_username(message,state)
    asyncio.run(awaitable)
    state.update_data.assert_not_awaited()
    assert shown.await_count == 1
    if case != 'offline' or flow == 'reseller':
        assert state.set_state.await_args.args[0] == (BuyFlow.username if flow=='public' else ResellerCreateUser.username)
    if case=='duplicate':assert 'بیشتری' in shown.await_args.args[1]
    if flow=='reseller':resolver.assert_not_awaited()


@pytest.mark.parametrize('case',['short','characters','consecutive','duplicate','offline'])
def test_reseller_miniapp_cannot_enqueue_invalid_name(partner_native,monkeypatch,case):
    c,sessions,_,_,flow,_=partner_native
    monkeypatch.setattr(flow,'get_reseller_username_error',REAL_RESELLER_ERROR)
    async def seed():
        async with sessions() as s:
            server=await s.get(Server,2);server.server_type='pasarguard';await s.commit()
    asyncio.run(seed())
    exists=AsyncMock(return_value=case=='duplicate',side_effect=RuntimeError('بررسی نام انجام نشد') if case=='offline' else None)
    monkeypatch.setattr(flow,'reseller_username_exists',exists)
    payload=action();payload['username']={'short':'ab','characters':'ali user','consecutive':'ali__01'}.get(case,'AliUser')
    result=c.post('/api/miniapp/reseller/actions',json=payload,headers=H)
    assert result.status_code == (503 if case=='offline' else 422),result.text
    if case=='duplicate':assert 'بیشتری' in result.json()['detail']
    async def verify():
        async with sessions() as s:
            assert await s.scalar(select(func.count(MiniAppOperation.id)))==0
    asyncio.run(verify())
    # User can correct the same unsubmitted request; a rejected name consumes no key.
    if case!='offline':
        exists.return_value=False
        payload['username']='AliUser2026'
        corrected=c.post('/api/miniapp/reseller/actions',json=payload,headers=H)
        assert corrected.status_code==200,corrected.text
        assert corrected.json()['status']=='queued'


def test_reseller_remote_outage_is_never_treated_as_available(monkeypatch):
    monkeypatch.setattr(PasarGuardService,'get_user',AsyncMock(side_effect=RuntimeError('timeout')))
    session=SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda:None)))
    with pytest.raises(RuntimeError,match='بررسی نام'):
        asyncio.run(reseller.reseller_username_exists(session,SimpleNamespace(server_type='pasarguard'),'AliUser'))


@pytest.mark.parametrize('case',['short','characters','consecutive','duplicate','offline'])
def test_public_miniapp_rejects_before_quote_payment_and_order(pg_wallet,monkeypatch,case):
    c,sessions,_,flow=pg_wallet
    monkeypatch.setattr(flow,'get_service_username_error',REAL_PUBLIC_ERROR)
    exists=AsyncMock(return_value=case=='duplicate',side_effect=RuntimeError('پنل در دسترس نیست') if case=='offline' else None)
    monkeypatch.setattr(flow,'service_username_exists',exists)
    payload=body();payload['username']={'short':'ab','characters':'ali user','consecutive':'ali__01'}.get(case,'AliUser')
    expected=503 if case=='offline' else 409
    quote=c.post('/api/miniapp/checkout/quote',json={'plan_id':1,'username':payload['username']},headers=H)
    assert quote.status_code==expected,quote.text
    rejected=c.post('/api/miniapp/checkout',json=payload,headers=H)
    assert rejected.status_code==expected,rejected.text
    if case=='duplicate':assert 'بیشتری' in rejected.json()['detail']
    async def verify():
        async with sessions() as s:
            assert (await s.get(User,1)).wallet_balance==250000
            assert await s.scalar(select(func.count(WalletTransaction.id)))==0
            assert await s.scalar(select(func.count(Order.id)).where(Order.checkout_key.is_not(None)))==0
    asyncio.run(verify())
    exists.side_effect=None;exists.return_value=False
    payload['username']='AliUser2026'
    assert c.post('/api/miniapp/checkout/quote',json={'plan_id':1,'username':payload['username']},headers=H).status_code==200
    assert c.post('/api/miniapp/checkout',json=payload,headers=H).status_code==200
