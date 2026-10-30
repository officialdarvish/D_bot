import asyncio
import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.base import StorageKey
from sqlalchemy import select, func
from test_miniapp import client, signed
from app.database.models import User, ClientService, Setting, Order, ResellerAccount, ServiceDeletionTask, ServiceConversion
from app.services import service_ownership as ownership
from app.bot.handlers.public import my_services as flow
from app.bot.states.public_states import ServiceOwnershipTransfer

@pytest.fixture
def owned(client, monkeypatch):
    c, sessions = client
    monkeypatch.setattr(ownership.settings,'OWNER_IDS','11')
    monkeypatch.setattr(ownership.settings,'ADMIN_IDS','11')
    monkeypatch.setattr(ownership.settings,'SELLER_IDS','22')
    monkeypatch.setattr(flow,'SessionLocal',sessions)
    monkeypatch.setattr(flow,'ui_message',AsyncMock())
    monkeypatch.setattr(flow,'edit_or_answer',AsyncMock())
    monkeypatch.setattr(flow,'sync_service_from_panel',AsyncMock(side_effect=AssertionError('Transfer must not contact the panel')))
    return c, sessions


def callback(actor=11,data='svc:transfer:1'):
    return SimpleNamespace(from_user=SimpleNamespace(id=actor),data=data,message=SimpleNamespace(chat=SimpleNamespace(id=actor),message_id=100),answer=AsyncMock())


def message(text='22',actor=11):
    return SimpleNamespace(from_user=SimpleNamespace(id=actor),text=text,chat=SimpleNamespace(id=actor),bot=SimpleNamespace(send_message=AsyncMock()))


def state(actor=11):
    return FSMContext(storage=MemoryStorage(),key=StorageKey(bot_id=123,chat_id=actor,user_id=actor))


async def do_transfer(sessions,target=22,actor=11,sid=1):
    async with sessions() as s:
        async with s.begin():return await ownership.transfer_service_ownership(s,sid,actor,target)


@pytest.mark.parametrize('value',['','0','-22','@user','https://t.me/user','1.5','1e5','+22','22 33',str(2**52)])
def test_reject_invalid_telegram_id(value):
    with pytest.raises(ownership.OwnershipTransferError):ownership.recipient_telegram_id(value)

@pytest.mark.parametrize('value',['22',' 22 ','۲۲','٢٢'])
def test_accept_numeric_ids(value):assert ownership.recipient_telegram_id(value)==22


@pytest.mark.parametrize('provider',['xui','pasarguard','mikrotik'])
def test_transfer_preserves_every_service_field_and_financial_history(owned,provider):
    c,sessions=owned
    async def run():
        async with sessions() as s:
            from app.database.models import Server
            server=await s.get(Server,1);server.server_type=provider
            svc=await s.get(ClientService,1);svc.xui_uuid='unchanged-uuid';svc.inbound_ids=[3,7]
            order=await s.get(Order,1);order.service_id=1;order.receipt_file_id='telegram-receipt-preserved'
            await s.commit()
            before={column.name:getattr(svc,column.name) for column in ClientService.__table__.columns}
            order_before={column.name:getattr(order,column.name) for column in Order.__table__.columns}
            balances={u.id:(u.wallet_balance,u.wallet_v2ray_balance,u.wallet_openvpn_balance) for u in (await s.scalars(select(User))).all()}
        outcome=await do_transfer(sessions)
        assert outcome.recipient_telegram_id==22 and outcome.service_id==1
        async with sessions() as s:
            svc=await s.get(ClientService,1)
            assert svc.user_id==2
            after={column.name:getattr(svc,column.name) for column in ClientService.__table__.columns}
            assert {k:v for k,v in before.items() if k!='user_id'}=={k:v for k,v in after.items() if k!='user_id'}
            order=await s.get(Order,1)
            assert order_before=={column.name:getattr(order,column.name) for column in Order.__table__.columns}
            assert balances=={u.id:(u.wallet_balance,u.wallet_v2ray_balance,u.wallet_openvpn_balance) for u in (await s.scalars(select(User))).all()}
            audits=(await s.scalars(select(Setting).where(Setting.key.startswith('service_ownership_transfer:')))).all()
            assert len(audits)==1
            audit=json.loads(audits[0].value);assert audit['from_telegram_id']==11 and audit['to_telegram_id']==22 and audit['service_id']==1
            assert not (await flow._owned_public_service(s,svc,11))[0]
            assert (await flow._owned_public_service(s,svc,22))[0]
    asyncio.run(run())
    # The actual MiniApp ownership boundary observes the same update immediately.
    assert c.get('/api/miniapp/services/1/link',headers={'X-Telegram-Init-Data':signed(11)}).status_code==404
    assert c.get('/api/miniapp/services/1/link',headers={'X-Telegram-Init-Data':signed(22)}).status_code==200


@pytest.mark.asyncio
@pytest.mark.parametrize('target,actor,sid',[(22,22,1),(11,11,1),(999,11,1),(22,11,2),(22,11,999)])
async def test_invalid_or_forged_transfer_never_updates_owner(owned,target,actor,sid):
    _,sessions=owned
    with pytest.raises(ownership.OwnershipTransferError):await do_transfer(sessions,target,actor,sid)
    async with sessions() as s:
        assert (await s.get(ClientService,1)).user_id==1
        assert (await s.scalar(select(func.count(Setting.key)).where(Setting.key.startswith('service_ownership_transfer:'))))==0


@pytest.mark.asyncio
@pytest.mark.parametrize('reason',['blocked','reseller','deleted','expired','deletion','conversion','pending_renewal'])
async def test_unsafe_services_or_recipients_are_rejected(owned,reason):
    _,sessions=owned
    async with sessions() as s:
        svc=await s.get(ClientService,1)
        if reason=='blocked':(await s.get(User,2)).is_blocked=True
        if reason=='reseller':
            s.add(ResellerAccount(id=1,user_id=1,server_id=2,total_bytes=100));await s.flush();svc.reseller_id=1
        if reason=='deleted':svc.client_username='deleted_old'
        if reason=='expired':svc.is_active=False;svc.disabled_at=datetime.utcnow()-timedelta(days=4);svc.disabled_reason='expired';svc.expires_at=datetime.utcnow()-timedelta(days=4)
        if reason=='deletion':s.add(ServiceDeletionTask(source_service_id=1,user_id=1,status='pending'))
        if reason=='conversion':s.add(ServiceConversion(source_service_id=1,user_id=1,target_plan_id=1,status='reserved'))
        if reason=='pending_renewal':
            order=await s.get(Order,1);order.service_id=1;order.status='waiting_receipt'
        await s.commit()
    with pytest.raises(ownership.OwnershipTransferError):await do_transfer(sessions)
    async with sessions() as s:assert (await s.get(ClientService,1)).user_id==1


@pytest.mark.asyncio
async def test_replay_cannot_transfer_a_service_twice(owned):
    _,sessions=owned
    await do_transfer(sessions)
    with pytest.raises(ownership.OwnershipTransferError):await do_transfer(sessions)
    async with sessions() as s:
        assert (await s.get(ClientService,1)).user_id==2
        assert await s.scalar(select(func.count(Setting.key)).where(Setting.key.startswith('service_ownership_transfer:')))==1


@pytest.mark.asyncio
async def test_failed_audit_rolls_back_ownership(owned,monkeypatch):
    _,sessions=owned
    async with sessions() as s:
        with pytest.raises(RuntimeError):
            async with s.begin():
                monkeypatch.setattr(s,'flush',AsyncMock(side_effect=RuntimeError('audit storage failed')))
                await ownership.transfer_service_ownership(s,1,11,22)
    async with sessions() as s:assert (await s.get(ClientService,1)).user_id==1


@pytest.mark.asyncio
async def test_keyboard_and_interaction_shortcut_are_admin_only(owned):
    _,sessions=owned
    async with sessions() as s:
        svc=await s.get(ClientService,1)
        for actor,expected in [(11,True),(22,False),(None,False)]:
            keyboard=flow.detail_kb(svc,None,'pasarguard',actor_telegram_id=actor)
            assert any(b.callback_data=='svc:transfer:1' for row in keyboard.inline_keyboard for b in row)==expected
    event=callback(22,'admin:ownership_services')
    await flow.my_services(event,state())
    assert event.answer.await_args.kwargs['show_alert'] is True


@pytest.mark.asyncio
async def test_complete_fsm_input_flow_and_old_callbacks(owned):
    _,sessions=owned;fsm=state();event=callback()
    await flow.begin_ownership_transfer(event,fsm)
    assert await fsm.get_state()==ServiceOwnershipTransfer.recipient.state
    assert (await fsm.get_data())['transfer_service_id']==1
    for invalid in ['not-an-id','999','11']:
        await flow.receive_ownership_recipient(message(invalid),fsm)
        assert await fsm.get_state()==ServiceOwnershipTransfer.recipient.state
        async with sessions() as s:assert (await s.get(ClientService,1)).user_id==1
    await flow.receive_ownership_recipient(message('۲۲'),fsm)
    assert await fsm.get_state() is None
    assert 'مالکیت کانفیگ منتقل شد' in flow.ui_message.await_args.args[1]
    # An old transfer callback from the same admin cannot reopen the transferred config.
    stale=callback();await flow.begin_ownership_transfer(stale,fsm)
    assert stale.answer.await_args.kwargs['show_alert'] is True
    assert await fsm.get_state() is None


@pytest.mark.asyncio
@pytest.mark.parametrize('kind',['expired','wrong_actor','cancel','nonadmin','malformed_callback','back_to_list'])
async def test_flow_cancel_expiry_and_permission_recheck(owned,kind):
    _,sessions=owned;fsm=state();await flow.begin_ownership_transfer(callback(),fsm)
    if kind=='expired':
        await fsm.update_data(transfer_started_at=(datetime.utcnow()-timedelta(hours=1)).timestamp())
        await flow.receive_ownership_recipient(message(),fsm)
    elif kind=='wrong_actor':
        await fsm.update_data(transfer_actor_id=99);await flow.receive_ownership_recipient(message(),fsm)
    elif kind=='cancel':await flow.receive_ownership_recipient(message('/cancel'),fsm)
    elif kind=='nonadmin':await flow.receive_ownership_recipient(message(actor=22),fsm)
    elif kind=='back_to_list':await flow.my_services(callback(data='menu:my_services'),fsm)
    else:
        await fsm.clear();event=callback(data='svc:transfer:bad')
        await flow.begin_ownership_transfer(event,fsm);assert event.answer.await_args.kwargs['show_alert'] is True
    assert await fsm.get_state() is None
    async with sessions() as s:assert (await s.get(ClientService,1)).user_id==1


@pytest.mark.asyncio
async def test_recipient_notification_is_sent_only_after_commit_and_with_navigation(owned):
    _,sessions=owned;fsm=state();msg=message()
    async with sessions() as s:
        (await s.get(ClientService,1)).client_username='config <one> & two'
        await s.commit()
    async def send(chat_id,text,**kwargs):
        # A different database session must already observe the completed transfer.
        async with sessions() as s:assert (await s.get(ClientService,1)).user_id==2
        assert chat_id==22
        assert 'مدیر ربات کانفیگ' in text and 'config &lt;one&gt; &amp; two' in text
        assert '<one>' not in text and 'وضعیت' in text
        assert kwargs['parse_mode']=='HTML'
        assert kwargs['reply_markup'].inline_keyboard[0][0].callback_data=='menu:my_services'
    msg.bot.send_message.side_effect=send
    await flow.begin_ownership_transfer(callback(),fsm)
    await flow.receive_ownership_recipient(msg,fsm)
    msg.bot.send_message.assert_awaited_once()
    assert 'پیام انتقال مالکیت برای کاربر ارسال شد' in flow.ui_message.await_args.args[1]
    # Replaying the same input cannot send a second notification or repeat the transfer.
    await flow.receive_ownership_recipient(msg,fsm)
    msg.bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('error',[RuntimeError('bot blocked'),TimeoutError('delivery unconfirmed')])
async def test_notification_failure_preserves_transfer_and_informs_admin(owned,error):
    _,sessions=owned;fsm=state();msg=message();msg.bot.send_message.side_effect=error
    await flow.begin_ownership_transfer(callback(),fsm)
    await flow.receive_ownership_recipient(msg,fsm)
    async with sessions() as s:
        assert (await s.get(ClientService,1)).user_id==2
        assert await s.scalar(select(func.count(Setting.key)).where(Setting.key.startswith('service_ownership_transfer:')))==1
    assert await fsm.get_state() is None
    result=flow.ui_message.await_args.args[1]
    assert 'مالکیت کانفیگ منتقل شد' in result and 'ارسال پیام به کاربر تأیید نشد' in result
    msg.bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('input_value',['invalid','999','11','/cancel'])
async def test_no_recipient_notification_on_invalid_or_cancelled_transfer(owned,input_value):
    _,sessions=owned;fsm=state();msg=message(input_value)
    await flow.begin_ownership_transfer(callback(),fsm)
    await flow.receive_ownership_recipient(msg,fsm)
    msg.bot.send_message.assert_not_awaited()
    async with sessions() as s:assert (await s.get(ClientService,1)).user_id==1
