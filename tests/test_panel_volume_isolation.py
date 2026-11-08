"""A public/reseller volume server must never activate wallet PAYG metering."""
import json
import logging
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import select
from app.database.models import Server, Setting, PasarGuardPanelMeter, User
from app.services import pasarguard_panel_meter as meter, payg_scheduler as gate
from app.services import reseller_management as management
from app.services.panel_billing_policy import panel_billing_mode
from test_reseller_payg import finance
from test_payg_scheduler import add_panel


@pytest.mark.parametrize('meta,gb,hour,profile,expected', [
    ({'scope':'all'},1000,0,{},None),
    ({'scope':'all','reseller_billing_modes':['volume']},1000,0,{},None),
    ({'reseller_billing_modes':['volume']},1000,0,{'billing_mode':'payg'},None),
    ({'reseller_billing_modes':['volume']},1000,0,{'billing_mode':'volume'},'volume'),
    ({'reseller_billing_modes':['volume','payg']},1000,0,{},'payg'),
    ({'reseller_billing_modes':['payg']},0,100,{},'payg'),
    ({'reseller_billing_modes':['payg']},0,0,{'billing_mode':'payg'},None),
    ({'reseller_billing_modes':['volume','payg']},1000,0,{'billing_mode':'volume'},'volume'),
    ({'reseller_billing_modes':['volume','payg']},1000,0,{'billing_mode':'payg','transition':'hold'},None),
    ({'reseller_billing_modes':'volume, payg'},1000,0,{},'payg'),
])
def test_panel_financial_policy(meta,gb,hour,profile,expected):
    assert panel_billing_mode(meta,gb,hour,profile)==expected


@pytest.mark.parametrize('explicit_payg',[False,True])
async def test_volume_only_server_skips_legacy_payg_order_everywhere(finance,monkeypatch,explicit_payg):
    await add_panel(finance)
    monkeypatch.setattr(meter,'SessionLocal',finance)
    monkeypatch.setattr(management,'SessionLocal',finance)
    remote=AsyncMock(side_effect=AssertionError('Volume server must not fetch PAYG usage'))
    monkeypatch.setattr(meter.PanelMeterAPI,'list_own_users',remote)
    async with finance() as s:
        server=await s.get(Server,2)
        server.meta={'scope':'all','reseller_billing_modes':['volume']}
        if explicit_payg:s.add(Setting(key='reseller_finance:panels:1',value=json.dumps({'billing_mode':'payg'})))
        await s.commit()
        assert await gate.panel_order_ids(s,'payg')==[]
        assert await gate.panel_order_ids(s,'volume')==[]  # No invented prepaid ledger.
        before=(await s.get(User,1)).wallet_balance
    await meter.sync_panel_payg()
    assert await meter.PanelMeterAPI().poll(1)=={}
    with pytest.raises(ValueError):await meter.PanelMeterAPI().resume(1)
    assert remote.await_count==0
    async with finance() as s:
        m=await s.scalar(select(PasarGuardPanelMeter).where(PasarGuardPanelMeter.order_id==1))
        assert m.total_charged_irt==0 and not m.usage_offsets and not m.suspended
        assert (await s.get(User,1)).wallet_balance==before


async def test_explicit_volume_with_old_payg_prices_only_uses_volume_reconciler(finance,monkeypatch):
    await add_panel(finance)
    monkeypatch.setattr(meter,'SessionLocal',finance)
    monkeypatch.setattr(management,'SessionLocal',finance)
    async with finance() as s:
        (await s.get(Server,2)).meta={'scope':'all','reseller_billing_modes':['volume']}
        s.add(Setting(key='reseller_finance:panels:1',value=json.dumps({'billing_mode':'volume','available_bytes':2*1024**3})))
        await s.commit()
        assert await gate.panel_order_ids(s,'payg')==[]
        assert await gate.panel_order_ids(s,'volume')==[1]
    volume=AsyncMock(return_value={'mode':'volume'})
    monkeypatch.setattr(management,'poll_volume_panel',volume)
    remote=AsyncMock(side_effect=AssertionError('Wrong PAYG path'))
    monkeypatch.setattr(meter.PanelMeterAPI,'list_own_users',remote)
    await meter.sync_panel_payg()
    assert volume.await_count==0
    await meter.sync_volume_panels()
    volume.assert_awaited_once_with(1)
    assert remote.await_count==0


async def test_volume_reconciler_checks_mode_before_listing_users(finance,monkeypatch):
    await add_panel(finance)
    monkeypatch.setattr(management,'SessionLocal',finance)
    remote=AsyncMock(side_effect=AssertionError('No explicit volume ledger'))
    monkeypatch.setattr(meter.PanelMeterAPI,'list_own_users',remote)
    assert await management.poll_volume_panel(1)=={}
    assert remote.await_count==0


async def test_volume_connection_error_is_not_reported_as_payg(finance,monkeypatch,caplog):
    await add_panel(finance)
    monkeypatch.setattr(meter,'SessionLocal',finance)
    monkeypatch.setattr(meter.PanelMeterAPI,'poll',AsyncMock(side_effect=RuntimeError('Offline')))
    with caplog.at_level(logging.ERROR,logger=meter.__name__):
        await meter._sync_panel_ids([1],mode='volume')
    assert 'VOLUME metering failed order=1' in caplog.text
    assert 'PAYG metering failed' not in caplog.text


async def test_policy_change_during_remote_read_cannot_debit_wallet(finance,monkeypatch):
    await add_panel(finance)
    monkeypatch.setattr(meter,'SessionLocal',finance)
    async def changed(self,server,order):
        async with finance() as s:
            (await s.get(Server,2)).meta={'reseller_billing_modes':['volume']}
            await s.commit()
        return [{'id':9,'used_traffic':1024**3,'admin':{'id':77},'status':'active'}]
    monkeypatch.setattr(meter.PanelMeterAPI,'list_own_users',changed)
    async with finance() as s:before=(await s.get(User,1)).wallet_balance
    assert await meter.PanelMeterAPI().poll(1)=={}
    async with finance() as s:
        assert (await s.get(User,1)).wallet_balance==before
        m=await s.scalar(select(PasarGuardPanelMeter).where(PasarGuardPanelMeter.order_id==1))
        assert m.total_charged_irt==0 and not m.usage_offsets


async def test_recharge_does_not_retry_payg_resume_on_volume_only_server(finance,monkeypatch):
    from app.database.models import MiniAppOperation,Order
    from app.services import panel_wallet_recharge as recovery
    await add_panel(finance)
    monkeypatch.setattr(recovery,'SessionLocal',finance)
    resume=AsyncMock(side_effect=AssertionError('No PAYG resume for a volume server'))
    monkeypatch.setattr(meter.PanelMeterAPI,'resume',resume)
    async with finance() as s:
        (await s.get(Server,2)).meta={'reseller_billing_modes':['volume']}
        m=await s.scalar(select(PasarGuardPanelMeter).where(PasarGuardPanelMeter.order_id==1))
        m.suspended=True
        s.add(Order(id=1,user_id=1,amount_irt=100000,payment_method='card',status='paid'))
        s.add(MiniAppOperation(id=1,user_id=1,key='panel-recharge:1',kind='panel_recharge_notice',
            status='queued',payload={'order_id':1,'panel_id':1}))
        await s.commit()
    bot=AsyncMock()
    await recovery.process_panel_recharges(bot)
    await recovery.process_panel_recharges(bot)
    assert resume.await_count==0 and bot.send_message.await_count==1
    async with finance() as s:
        op=await s.get(MiniAppOperation,1)
        assert op.status=='queued' and op.result['recovery_errors']
        assert (await s.scalar(select(PasarGuardPanelMeter).where(PasarGuardPanelMeter.order_id==1))).suspended
