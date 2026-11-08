import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import select, func
from test_miniapp import client
from app.bot.handlers.admin import pending_receipts as inbox
from app.bot.handlers.public import buy
from app.database.models import Order, ClientService, User, PaymentCard, PasarGuardPanelOrder
from app.services.receipt_status import receipt_failure_reason

@pytest.fixture
def receipts(client,monkeypatch):
    _,sessions=client
    for module in [inbox,buy]:monkeypatch.setattr(module,'SessionLocal',sessions)
    monkeypatch.setattr(inbox.settings,'OWNER_IDS','99');monkeypatch.setattr(inbox.settings,'ADMIN_IDS','99')
    for name in ['send_admin_notice','send_buyer_notice','send_home','send_service_card','notify_paid_order','report_bot_error']:
        monkeypatch.setattr(buy,name,AsyncMock())
    monkeypatch.setattr(buy,'apply_purchase_commission',AsyncMock(return_value=0))
    bot=SimpleNamespace(send_photo=AsyncMock(),send_document=AsyncMock(),send_message=AsyncMock(),edit_message_reply_markup=AsyncMock())
    async def seed():
        async with sessions() as s:
            s.add(PaymentCard(id=1,server_type='xui',server_id=1,card_number='test',owner_name='Vendor',reviewer_telegram_id=77,is_active=True))
            s.add(Order(id=10,user_id=1,plan_id=1,amount_irt=100000,payment_method='card:receipt_user',status='waiting_receipt',receipt_file_id='telegram-receipt',receipt_reviewer_telegram_id=77,pricing_meta={'price_snapshot':'preserved'}))
            await s.commit()
    asyncio.run(seed())
    return sessions,bot


def callback(bot,uid=99,data='pending_receipts:order:10'):
    return SimpleNamespace(from_user=SimpleNamespace(id=uid),data=data,answer=AsyncMock(),message=SimpleNamespace(bot=bot,chat=SimpleNamespace(id=uid),message_id=5,edit_reply_markup=AsyncMock()))


def codes(keyboard):return [button.callback_data for row in keyboard.inline_keyboard for button in row]


def test_inbound_failure_remains_in_inbox_and_can_be_retried_once(receipts,monkeypatch):
    sessions,bot=receipts
    build=AsyncMock(side_effect=RuntimeError('Required inbound memberships are missing: 999'))
    monkeypatch.setattr(buy,'build_service',build)
    async def run():
        await buy.process_approved_order_background(10,bot,admin_chat_id=99)
        async with sessions() as s:
            order=await s.get(Order,10)
            assert order.status=='failed' and order.receipt_file_id=='telegram-receipt'
            assert order.pricing_meta['price_snapshot']=='preserved'
            assert 'اینباند' in order.pricing_meta['receipt_last_failure']['reason']
        for reviewer in [99,77]:
            keyboard=await inbox.pending_receipts_keyboard(reviewer)
            assert 'pending_receipts:order:10' in codes(keyboard)
            event=callback(bot,reviewer);await inbox.pending_receipts_detail(event)
            sent=bot.send_photo.await_args.kwargs
            assert 'order:approve:10' in codes(sent['reply_markup'])
            assert 'اینباند' in sent['caption'] and 'خطای' in sent['caption']
        async def successful(session,user,server,plan,username,password=None):
            svc=ClientService(user_id=user.id,server_id=server.id,plan_id=plan.id,client_username=username,xui_email=username,sub_link='https://example.com/sub/retry',total_bytes=plan.volume_gb*1024**3)
            session.add(svc);await session.flush();return svc,svc.sub_link
        build.side_effect=successful
        queued=[]
        def queue(coro):queued.append(coro);return None
        monkeypatch.setattr(buy,'asyncio',SimpleNamespace(create_task=queue))
        await buy.approve_order_cb(callback(bot,data='order:approve:10'))
        await buy.approve_order_cb(callback(bot,data='order:approve:10'))
        assert len(queued)==1
        await queued[0]
        await buy.process_approved_order_background(10,bot)
        assert build.await_count==2  # one failed attempt, one successful attempt
        async with sessions() as s:
            order=await s.get(Order,10)
            assert order.status=='paid' and order.service_id
            assert 'receipt_last_failure' not in order.pricing_meta
            assert order.pricing_meta['price_snapshot']=='preserved'
            assert await s.scalar(select(func.count(ClientService.id)).where(ClientService.client_username=='receipt_user'))==1
            assert (await s.get(User,1)).wallet_balance==250000
        assert 'pending_receipts:order:10' not in codes(await inbox.pending_receipts_keyboard(99))
    asyncio.run(run())


@pytest.mark.parametrize('status,visible,approve',[
    ('waiting_receipt',True,True),('failed',True,True),('processing',True,False),
    ('paid',False,False),('rejected',False,False),('cancelled',False,False)])
def test_inbox_statuses_and_reviewer_isolation(receipts,status,visible,approve):
    sessions,bot=receipts
    async def run():
        async with sessions() as s:(await s.get(Order,10)).status=status;await s.commit()
        assert ('pending_receipts:order:10' in codes(await inbox.pending_receipts_keyboard(99)))==visible
        assert ('pending_receipts:order:10' in codes(await inbox.pending_receipts_keyboard(77)))==visible
        assert 'pending_receipts:order:10' not in codes(await inbox.pending_receipts_keyboard(88))
        await inbox.pending_receipts_detail(callback(bot))
        if visible:
            buttons=codes(bot.send_photo.await_args.kwargs['reply_markup'])
            assert ('order:approve:10' in buttons)==approve
            assert ('order:reject:10' in buttons)==approve
        else:bot.send_photo.assert_not_awaited()
    asyncio.run(run())


def test_old_failed_receipt_is_recovered_without_mutating_status(receipts):
    sessions,_=receipts
    async def run():
        async with sessions() as s:
            order=await s.get(Order,10);order.status='failed';order.pricing_meta={};await s.commit()
        assert 'pending_receipts:order:10' in codes(await inbox.pending_receipts_keyboard(99))
        async with sessions() as s:assert (await s.get(Order,10)).status=='failed'
    asyncio.run(run())


def test_reviewer_filter_applies_before_limit(receipts):
    sessions,_=receipts
    async def run():
        async with sessions() as s:
            for index in range(100,210):
                s.add(Order(id=index,user_id=2,plan_id=1,amount_irt=1,payment_method='card:other',status='waiting_receipt',receipt_file_id='other-receipt',receipt_reviewer_telegram_id=88))
            await s.commit()
        assert 'pending_receipts:order:10' in codes(await inbox.pending_receipts_keyboard(77))
    asyncio.run(run())


def test_failed_without_receipt_is_excluded(receipts):
    sessions,_=receipts
    async def run():
        async with sessions() as s:
            order=await s.get(Order,10);order.status='failed';order.receipt_file_id=None;await s.commit()
        assert 'pending_receipts:order:10' not in codes(await inbox.pending_receipts_keyboard(99))
    asyncio.run(run())


def test_media_failure_falls_back_with_complete_details(receipts):
    _,bot=receipts
    bot.send_photo.side_effect=RuntimeError('missing photo');bot.send_document.side_effect=RuntimeError('missing file')
    asyncio.run(inbox.pending_receipts_detail(callback(bot)))
    sent=bot.send_message.await_args
    assert 'فایل رسید در دسترس نیست' in sent.args[1]
    assert 'order:approve:10' in codes(sent.kwargs['reply_markup'])


def test_failure_explanation_never_contains_provider_credentials():
    reason=receipt_failure_reason(RuntimeError('inbound missing https://secret:password@panel.invalid token=verysecret'))
    assert 'اینباند' in reason
    assert not any(word in reason for word in ['https','password','verysecret','panel.invalid'])


@pytest.mark.parametrize('status,expected',[
    ('pending','pgadmin:approve:30'),('processing',None),('review_required',None),
    ('delivery_pending','pgadmin:deliver:30'),('approved',False),('rejected',False)])
def test_panel_receipt_workflow_states_do_not_allow_duplicate_creation(receipts,status,expected):
    sessions,bot=receipts
    async def run():
        async with sessions() as s:
            s.add(PasarGuardPanelOrder(id=30,user_id=1,server_id=1,card_id=1,username='panel_customer',password_encrypted='encrypted',amount_irt=100,status=status,receipt_file_id='panel-receipt'))
            await s.commit()
        keyboard=await inbox.pending_receipts_keyboard(99)
        assert ('pending_receipts:panel:30' in codes(keyboard))==(expected is not False)
        await inbox.pending_receipts_detail(callback(bot,data='pending_receipts:panel:30'))
        if expected is False:bot.send_photo.assert_not_awaited();return
        buttons=codes(bot.send_photo.await_args.kwargs['reply_markup'])
        if expected:assert expected in buttons
        if status!='pending':assert 'pgadmin:approve:30' not in buttons
    asyncio.run(run())


def test_long_receipt_details_are_not_lost_in_media_caption(receipts,monkeypatch):
    _,bot=receipts
    long='<b>Buyer</b>\n'+('details '*180)
    monkeypatch.setattr(inbox,'order_summary',lambda *args,**kwargs:long)
    asyncio.run(inbox.pending_receipts_detail(callback(bot)))
    assert len(bot.send_photo.await_args.kwargs['caption'])<1000
    assert bot.send_photo.await_args.kwargs['reply_markup'] is None
    assert long in bot.send_message.await_args.args[1]
    assert 'order:approve:10' in codes(bot.send_message.await_args.kwargs['reply_markup'])
