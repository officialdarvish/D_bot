"""Optional PAYG workers follow actual assignments and active servers."""
import asyncio
import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock
import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.database.models import (Server, ResellerAccount, ClientService,
    PasarGuardPanelOrder, PasarGuardPanelMeter, Setting, ResellerUsageMeter)
from app.services import payg_scheduler as gate, pasarguard_panel_meter as panel_meter
from test_reseller_payg import finance


async def add_panel(sessions):
    async with sessions() as s:
        s.add_all([PasarGuardPanelOrder(id=1, user_id=1, server_id=2,
            username='Panel', amount_irt=10000, receipt_file_id='receipt',
            status='approved', admin_id=77), PasarGuardPanelMeter(order_id=1,
            gb_price_irt=1000, hourly_price_irt=0)])
        await s.commit()


def scheduler():
    result = AsyncIOScheduler(timezone='UTC')
    for name, minutes in [('pasarguard_panel_payg', 30),
            ('reseller_payg_billing', 30), ('panel_volume_sync', 1),
            ('reseller_payg_suspension', 1)]:
        result.add_job(AsyncMock(), 'interval', minutes=minutes, id=name,
            next_run_time=None)
    return result


async def test_unused_payg_capability_leaves_workers_paused(finance, monkeypatch):
    monkeypatch.setattr(gate, 'SessionLocal', finance)
    async with finance() as s:
        for rid in (1, 2):
            (await s.get(ResellerAccount, rid)).billing_mode = 'volume'
        await s.commit()
    jobs = scheduler()
    assert not any((await gate.reconcile_payg_jobs(jobs)).values())
    assert all(j.next_run_time is None for j in jobs.get_jobs())


async def test_real_scheduler_enables_once_and_pauses_inactive_servers(finance, monkeypatch):
    monkeypatch.setattr(gate, 'SessionLocal', finance)
    await add_panel(finance)
    jobs = scheduler()
    desired = await gate.reconcile_payg_jobs(jobs)
    assert desired == dict(pasarguard_panel_payg=True,
        reseller_payg_billing=True, panel_volume_sync=False,
        reseller_payg_suspension=False)
    first = jobs.get_job('pasarguard_panel_payg').next_run_time
    await gate.reconcile_payg_jobs(jobs)
    assert jobs.get_job('pasarguard_panel_payg').next_run_time == first
    async with finance() as s:
        for sid in (1, 2):
            (await s.get(Server, sid)).is_active = False
        await s.commit()
    assert not any((await gate.reconcile_payg_jobs(jobs)).values())
    async with finance() as s:
        (await s.get(Server, 2)).is_active = True
        await s.commit()
    desired = await gate.reconcile_payg_jobs(jobs)
    assert desired['pasarguard_panel_payg'] and desired['reseller_payg_billing']


async def test_panel_volume_and_pending_orders_do_not_enable_payg(finance, monkeypatch):
    await add_panel(finance)
    async with finance() as s:
        s.add(Setting(key='reseller_finance:panels:1',
            value=json.dumps({'billing_mode': 'volume'})))
        await s.commit()
        assert await gate.panel_order_ids(s, 'payg') == []
        assert await gate.panel_order_ids(s, 'volume') == [1]
        (await s.get(PasarGuardPanelOrder, 1)).status = 'pending'
        await s.commit()
        assert await gate.panel_order_ids(s, 'volume') == []


async def test_transition_and_expired_accounts_are_excluded(finance):
    async with finance() as s:
        s.add(Setting(key='reseller_finance:account:1',
            value=json.dumps({'transition': 'pending'})))
        (await s.get(ResellerAccount, 2)).expires_at = datetime.utcnow()-timedelta(days=1)
        await s.commit()
        assert await gate.reseller_ids(s) == []
        assert await gate.maintenance_needed(s)  # Expired account still needs cutoff.


async def test_credit_cutoff_retries_independent_of_usage_scan(finance, monkeypatch):
    monkeypatch.setattr(gate, 'SessionLocal', finance)
    jobs = scheduler()
    async with finance() as s:
        (await s.get(ResellerAccount, 1)).wallet_balance_irt = 0
        await s.commit()
    assert (await gate.reconcile_payg_jobs(jobs))['reseller_payg_suspension']
    async with finance() as s:
        (await s.get(ResellerAccount, 1)).wallet_balance_irt = 100
        s.add(ResellerUsageMeter(reseller_id=1,service_id=1,server_id=1,
            suspended=True, suspension_pending=False))
        await s.commit()
    assert (await gate.reconcile_payg_jobs(jobs))['reseller_payg_suspension']


async def test_inactive_panel_never_constructs_provider(finance, monkeypatch):
    await add_panel(finance)
    async with finance() as s:
        (await s.get(Server, 2)).is_active = False
        await s.commit()
    monkeypatch.setattr(panel_meter, 'SessionLocal', finance)
    def forbidden():
        raise AssertionError('No provider for an inactive server')
    monkeypatch.setattr(panel_meter, 'PanelMeterAPI', forbidden)
    await panel_meter.sync_panel_payg()


async def test_panel_scans_have_at_most_two_live_requests(monkeypatch):
    active = maximum = 0
    seen = []
    class API:
        async def poll(self, oid, bot=None):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0)
            seen.append(oid)
            active -= 1
    monkeypatch.setattr(panel_meter, 'PanelMeterAPI', API)
    await panel_meter._sync_panel_ids(list(range(101)))
    assert maximum == 2 and sorted(seen) == list(range(101))


async def test_periodic_settlement_skips_inactive_servers(finance):
    from app.services import reseller_billing as billing
    async with finance() as s:
        (await s.get(Server, 2)).is_active = False
        account = await s.get(ResellerAccount, 1)
        result = await billing.settle(s, account, active_servers_only=True)
        await s.commit()
        assert result['cost'] == 10 and account.wallet_balance_irt == 90
        (await s.get(Server, 2)).is_active = True
        result = await billing.settle(s, account, active_servers_only=True)
        assert result['cost'] == 15  # Retains the inactive server's checkpoint.


def test_application_schedule_keeps_recharge_recovery_independent():
    import ast
    from pathlib import Path
    calls = {}
    for node in ast.walk(ast.parse(Path('app/main.py').read_text())):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'add_job':
            values = {kw.arg: kw.value for kw in node.keywords}
            if 'id' in values and isinstance(values['id'], ast.Constant):
                calls[values['id'].value] = values
    for ident in ('pasarguard_panel_payg', 'reseller_payg_billing'):
        assert ast.literal_eval(calls[ident]['minutes']) == 30
        assert ast.literal_eval(calls[ident]['next_run_time']) is None
    assert ast.literal_eval(calls['panel_recharge_recovery']['minutes']) == 1
    assert ast.literal_eval(calls['panel_volume_sync']['minutes']) == 1
    assert ast.literal_eval(calls['payg_job_gate']['minutes']) == 1


async def test_capable_server_without_assigned_payg_account_does_not_scan(finance):
    async with finance() as s:
        for rid in (1, 2):
            account = await s.get(ResellerAccount, rid)
            account.allowed_server_ids = []
            account.server_id = None
        for sid in (1, 2, 3):
            (await s.get(ClientService, sid)).client_username = f'deleted_{sid}'
        await s.commit()
        assert await gate.reseller_ids(s) == []
