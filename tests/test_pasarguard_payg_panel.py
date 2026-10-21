"""Isolated PAYG tests (do not require live panel, DB or bot credentials)."""
import ast
import asyncio
import importlib.util
from pathlib import Path
import sys
import types

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_meter():
    """Load the metering policy with network/database boundaries replaced."""
    src = (ROOT / 'app/services/pasarguard_panel_meter.py').read_text()
    tree = ast.parse(src)
    functions = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name in ('price_for_usage', 'PanelMeterAPI')]
    mod = ast.fix_missing_locations(ast.Module(body=functions, type_ignores=[]))
    namespace = {'__name__':'test_meter', 'GIB': 1024**3, 'PasarGuardService':type('PasarGuardService',(),{}), 'log':None,
                 'datetime':__import__('datetime').datetime, 'select':None}
    exec(compile(mod, 'panel_meter.py', 'exec'), namespace)
    return namespace


def test_cost_rounding_and_no_per_minute_duplicate_fees():
    price = load_meter()['price_for_usage']
    assert price(0,0,12000,3600) == (0,0)
    assert price(1024**3,3600,12000,3600) == (12000,3600)
    total = price(1024**3 // 60, 60, 12000,3600)
    assert total == (200,60)
    assert price(1024**3 // 60,60,12000,3600) == total
    assert price(1024**3,3600,0,0) == (0,0)


def test_ownership_enforced_before_bulk_user_mutation():
    class MockClient:
        def __init__(self, user_admin):
            self.user_admin = user_admin
            self.calls = []
        async def _request(self, server, method, path, **kwargs):
            self.calls.append((method,path,kwargs))
            if method == 'GET':
                return {'total':1, 'users':[{'id':56,'admin':{'id':self.user_admin},
                                              'used_traffic':55, 'status':'active'}]}
            return {}
    klass = load_meter()['PanelMeterAPI']
    server=object();order=types.SimpleNamespace(admin_id=42)
    fake=MockClient(41)
    with pytest.raises(RuntimeError,match='outside'):
        asyncio.run(klass(fake).set_users(server,order,False))
    assert all(m != 'POST' for m, _, _ in fake.calls)
    fake=MockClient(42)
    rows=asyncio.run(klass(fake).set_users(server,order,False))
    assert rows == [56]
    assert any(method == 'POST' and path == '/api/users/bulk/disable' and payload['json']=={'ids':[56]}
               for method,path,payload in fake.calls)
    assert fake.calls[0][2]['params']['admin_ids'] == 42


def test_sold_panel_controls_do_not_replace_normal_reseller_request():
    menu=(ROOT/'app/bot/keyboards/common.py').read_text()
    reseller=(ROOT/'app/bot/handlers/public/reseller.py').read_text()
    main=(ROOT/'app/main.py').read_text()
    assert "callback_data=CB_RESELLER" in menu
    assert "callback_data='pgsale:shop'" in menu
    assert "callback_data='pgsale:panels'" in menu
    assert "'pgsale:panel:'" in main
    assert 'show_panel_sale' not in reseller


def test_web_pricing_and_scrollbar_and_scheduler_wired():
    tsx=(ROOT/'frontend/components/admin-dashboard.tsx').read_text()
    css=(ROOT/'frontend/app/globals.css').read_text()
    api=(ROOT/'app/api/admin_web.py').read_text()
    main=(ROOT/'app/main.py').read_text()
    for item in ('PasarGuard Panel Sales', 'Initial purchase', 'Maximum users',
                 'PAYG price per GB', 'Reseller rental per hour'):
        assert item in tsx
    for item in ('gb_price_irt','hourly_price_irt','max_users','price_irt','enabled','server_id'):
        assert item in api
    assert 'scrollbar-width: none' in css and '.shell > .sidebar:hover .sidebar-nav' in css
    assert 'PasarGuardPanelMeter, WalletTransaction' in api  # API cannot raise NameError
    assert "id='pasarguard_panel_payg'" in main


def test_wallet_checkpoints_and_auto_suspend_reenable_are_present():
    src=(ROOT/'app/services/pasarguard_panel_meter.py').read_text()
    assert 'with_for_update' in src
    assert 'locked.total_charged_irt' in src
    assert 'account.wallet_balance = balance - paid' in src
    assert 'm.auto_disabled_user_ids' in src
    assert 'await self.set_users(server, order, False, only_ids=active_ids)' in src
    assert 'only_ids=restore_ids' in src
