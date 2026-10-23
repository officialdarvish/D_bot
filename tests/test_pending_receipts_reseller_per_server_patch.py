"""Regression checks for per-server reseller scope, inbox reviewers and PAYG selection."""
from __future__ import annotations
import ast
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]

def code(path):
    return (ROOT / path).read_text(encoding='utf8')

def functions(path, *names, ns=None):
    tree = ast.parse(code(path))
    found = [node for node in tree.body if isinstance(node,(ast.AsyncFunctionDef, ast.FunctionDef)) and node.name in names]
    assert len(found) == len(names)
    module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), *found], type_ignores=[])
    namespace = {} if ns is None else ns
    exec(compile(ast.fix_missing_locations(module),path,'exec'), namespace)
    return namespace


def test_policies_reject_cross_server_manual_empty_and_unknown_provider():
    server = SimpleNamespace(id=4,name='Sanaei',server_type='xui',meta={'inbound_ids':[2,4,7]})
    pg = SimpleNamespace(id=5,name='PasarGuard',server_type='pasarguard',meta={'inbound_ids':[10,11]})
    router = SimpleNamespace(id=6,name='VPN',server_type='mikrotik',meta={})
    ns = functions('app/api/admin_web.py', '_parse_reseller_inbound_policies', ns={
        'json':json,
        '_clean_plan_inbound_ids': lambda values: [int(v) for v in values],
        '_server_available_inbound_ids': lambda sv: sv.meta.get('inbound_ids',[]),
    })
    parse = ns['_parse_reseller_inbound_policies']
    valid = {'4':{'mode':'manual','inbound_ids':[4,7]}, '5':{'mode':'manual','inbound_ids':[11]}}
    assert parse(json.dumps(valid),{4:server,5:pg,6:router},[4,5,6]) == valid
    assert parse('{}',{4:server},[4]) == {}
    for bad in [
        {'99':{'mode':'manual','inbound_ids':[4]}},
        {'4':{'mode':'manual','inbound_ids':[]}},
        {'4':{'mode':'manual','inbound_ids':[123]}},
        {'6':{'mode':'manual','inbound_ids':[1]}},
    ]:
        with pytest.raises(ValueError):
            parse(json.dumps(bad), {4:server,5:pg,6:router}, [4,5,6])


def test_reseller_can_choose_secondary_pasarguard_and_own_group_only():
    from app.services.reseller_billing import server_allows
    servers = {
        1:SimpleNamespace(id=1,name='primary', server_type='xui', is_active=True, meta={'scope':'reseller','inbound_ids':[3,6]}),
        2:SimpleNamespace(id=2,name='secondary',server_type='pasarguard',is_active=True,meta={'scope':'reseller','inbound_ids':[11,12]}),
        3:SimpleNamespace(id=3,name='router',server_type='mikrotik',is_active=True,meta={'scope':'reseller'}),
    }
    class Session:
        async def get(self,kind,key): return servers.get(key)
    ns = functions('app/bot/handlers/public/reseller.py', 'reseller_inbound_mode', 'reseller_manual_inbound_ids', 'reseller_server_policy', 'resolve_reseller_build_target', ns={
        'normalize_inbound_ids':lambda ids:[int(x) for x in ids], 'Server':object, 'server_allows':server_allows,
    })
    reseller=SimpleNamespace(server_id=1,allowed_server_ids=[1,2,3],inbound_mode='manual',inbound_ids=[3],
        inbound_policies={'1':{'mode':'manual','inbound_ids':[3]},'2':{'mode':'manual','inbound_ids':[12]}})
    resolver=ns['resolve_reseller_build_target']
    selected, groups=asyncio.run(resolver(Session(),reseller,2))
    assert selected.id == 2 and groups == [12], 'secondary PasarGuard must not fall back to primary Sanaei'
    selected, ids=asyncio.run(resolver(Session(),reseller,1))
    assert selected.id == 1 and ids == [3]
    selected, ids=asyncio.run(resolver(Session(),reseller,3))
    assert selected.id == 3 and ids == []
    selected, ids=asyncio.run(resolver(Session(),reseller,99))
    assert selected is None and not ids
    reseller.billing_mode='payg'
    selected, ids=asyncio.run(resolver(Session(),reseller,2))
    assert selected is None and not ids, 'PAYG must reject a server that only allows prepaid volume'


def test_db_migrations_and_multi_server_UI_and_purchase_guards():
    model=code('app/database/models/core.py')
    assert 'inbound_policies: Mapped[dict]' in model
    for runtime in ['app/api/main.py','app/main.py']:
        assert 'ALTER TABLE reseller_accounts ADD COLUMN IF NOT EXISTS inbound_policies' in code(runtime)
    frontend=code('frontend/components/admin-dashboard.tsx')
    assert "field.type === 'reseller-inbounds'" in frontend
    assert 'Per-server inbound/group restrictions' in frontend
    assert 'get_service_username_error(session, server, username)' in code('app/bot/handlers/public/buy.py')
    assert 'این نام کلاینت قبلاً روی پنل ثبت شده است' in code('app/bot/handlers/public/buy.py')


def test_receipt_access_and_payg_approval_split():
    receipt=code('app/bot/handlers/admin/pending_receipts.py')
    assert 'order.receipt_reviewer_telegram_id == uid' in receipt
    assert "order.status != 'waiting_receipt'" in receipt
    assert 'card.reviewer_telegram_id == uid' in receipt
    assert 'pending_receipts:order:' in receipt
    admin=code('app/bot/handlers/admin/resellers.py')
    assert 'resadmin:access_payg:' in admin and 'resadmin:access_approve:' in admin
    assert "req.status = 'approved_payg'" in admin
    assert "pasarguard_panel_sales_enabled" in admin
    assert "'pending_receipts:'" in code('app/main.py')
    assert 'receipt_reviewer_telegram_id=int(data.get' in code('app/bot/handlers/public/account.py')


def test_reviewer_main_menu_does_not_shadow_sqlalchemy_imports():
    tree = ast.parse(code('app/bot/keyboards/common.py'))
    function = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == 'main_menu_inline')
    for node in ast.walk(function):
        if isinstance(node, ast.ImportFrom) and node.module in {'sqlalchemy', 'app.database.session'}:
            pytest.fail('Do not shadow global select / SessionLocal imports in main_menu_inline')
    account = code('app/bot/handlers/public/account.py')
    assert 'main_menu_inline(is_admin, telegram_id=chat_id)' in account
    assert "callback.from_user.id in settings.admin_ids); await callback.answer()" in account
