"""Restricted dashboard reseller role/API contract and purchase-flow wiring."""
import asyncio
import importlib.util
from pathlib import Path
import sys
import types

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def sale():
    # Isolate the pure API adapter from production secrets/DB during unit tests.
    module_name = 'app.services.pasarguard_service'
    previous = sys.modules.get(module_name)
    fake = types.ModuleType(module_name)
    fake.PasarGuardService = type('PasarGuardService', (), {})
    sys.modules[module_name] = fake
    try:
        spec = importlib.util.spec_from_file_location('test_private_panel_sales', ROOT / 'app/services/pasarguard_panel_sales.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield module
    finally:
        if previous is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous


def test_panel_username_and_password_policy(sale):
    assert sale.validate_panel_username('Reseller_2026')
    assert not sale.validate_panel_username('12startswithdigit')
    assert not sale.validate_panel_username('invalid-name')
    assert not sale.validate_panel_username('ab')
    assert sale.validate_panel_password('PaSSword123!')
    for bad in ['Password123', 'password123!', 'PASSWORD123!', 'Password!!!', 'Pass word123!', 'Aa123!', 'PaSSword123"']:
        assert not sale.validate_panel_password(bad)


def test_dashboard_login_url_preserves_custom_reverse_proxy_and_requires_https(sale):
    server = types.SimpleNamespace(panel_url='https://pg.example.org/dashboard/')
    assert sale.login_url(server) == 'https://pg.example.org/dashboard/'
    server.panel_url = 'https://pg.example.org/hub/'
    assert sale.login_url(server) == 'https://pg.example.org/hub/'
    server.panel_url = 'https://pg.example.org'
    assert sale.login_url(server) == 'https://pg.example.org/dashboard/'
    server.panel_url = 'http://localhost:8000'
    with pytest.raises(RuntimeError):
        sale.login_url(server)


def safe_role(sale, role_id=7):
    return {'name': sale.ROLE_NAME, 'id': role_id, 'is_owner': False,
            'permissions': {'users': {**sale.USER_RULES, 'reset_usage': None},
                            'groups': {**sale.GROUP_RULES, 'delete': None},
                            'admins': {'create': None}}}


def test_role_is_strictly_own_user_with_readonly_group_names(sale):
    role = safe_role(sale)
    sale._verify_reseller_role(role)
    role['permissions']['users']['delete'] = {'scope': 2}
    with pytest.raises(RuntimeError, match='users.delete'):
        sale._verify_reseller_role(role)
    role = safe_role(sale)
    role['permissions']['admins']['create'] = True
    with pytest.raises(RuntimeError, match='admins'):
        sale._verify_reseller_role(role)
    role = safe_role(sale)
    role['permissions']['groups']['update'] = True
    with pytest.raises(RuntimeError, match='groups'):
        sale._verify_reseller_role(role)
    role = safe_role(sale)
    role['is_owner'] = True
    with pytest.raises(RuntimeError):
        sale._verify_reseller_role(role)


def test_provisioning_creates_scoped_role_then_restricted_admin(sale):
    calls = []
    class FakeClient:
        async def get_admin_profile(self, server):
            return {'role': {'is_owner': True}}
        async def _request(self, server, method, path, **kwargs):
            calls.append((method, path, kwargs))
            if (method, path) == ('GET', '/api/admin-roles'):
                return {'roles': []}
            if (method, path) == ('POST', '/api/admin-role'):
                role = kwargs['json']
                return {'id': 7, 'name': role['name'], 'is_owner': False, 'permissions': role['permissions']}
            if (method, path) == ('GET', '/api/admins'):
                return {'admins': []}
            if (method, path) == ('POST', '/api/admin'):
                return {'id': 22, 'username': kwargs['json']['username'], 'role': {'id': 7}}
            raise AssertionError((method, path))
    server = types.SimpleNamespace(panel_url='https://pg.example.org')
    result = asyncio.run(sale.PanelResellerProvisioner(FakeClient()).create_account(server, 'Good_Name', 'PaSSword123!'))
    assert result == {'username': 'Good_Name', 'role_id': 7, 'admin_id': 22, 'login_url': 'https://pg.example.org/dashboard/'}
    role_payload = next(kw['json'] for method,path,kw in calls if path == '/api/admin-role')
    assert role_payload['permissions']['users'] == sale.USER_RULES
    assert role_payload['permissions']['groups'] == {'read_simple': True}
    admin_payload = next(kw['json'] for method,path,kw in calls if path == '/api/admin' and method == 'POST')
    assert admin_payload['role_id'] == 7 and not admin_payload.get('is_sudo', False)


def test_provisioning_rejects_non_owner_and_preexisting_admin(sale):
    class FakeClient:
        async def get_admin_profile(self, server):
            return {'role': {'is_owner': False}}
    with pytest.raises(RuntimeError, match='OWNER'):
        asyncio.run(sale.PanelResellerProvisioner(FakeClient()).ensure_safe_role(object()))

    class OwnerClient:
        async def get_admin_profile(self, server):
            return {'role': {'is_owner': True}}
        async def _request(self, server, method, path, **kwargs):
            if path == '/api/admin-roles': return {'roles': [{'name': sale.ROLE_NAME, 'id': 7}]}
            if path == '/api/admin-role/7': return safe_role(sale)
            if path == '/api/admins': return {'admins': [{'username': 'Good_Name'}]}
            raise AssertionError('create attempted with existing username')
    with pytest.raises(RuntimeError, match='already registered'):
        asyncio.run(sale.PanelResellerProvisioner(OwnerClient()).create_account(
            types.SimpleNamespace(panel_url='https://pg.example.org'), 'Good_Name', 'PaSSword123!'))


def test_purchase_and_approval_flow_wiring():
    public = (ROOT / 'app/bot/handlers/public/panel_reseller_sale.py').read_text()
    admin = (ROOT / 'app/bot/handlers/admin/panel_reseller_sale.py').read_text()
    main = (ROOT / 'app/main.py').read_text()
    assert 'pg_username' in public and 'pg_password_encrypted' in public
    assert 'PasarGuardPanelOrder' in public and 'encrypt_text(password)' in public
    assert 'with_for_update()' in public
    assert "order.status = 'processing'" in admin
    assert "order.status = 'review_required'" in admin
    assert "order.status = 'delivery_pending'" in admin
    assert 'order.password_encrypted' in admin  # encrypted at rest for explicit owner reveal
    assert 'pgadmin:approve:' in main and 'pgadmin:reject:' in main
    assert 'admin_panel_sale.router' in main and 'public_panel_sale.router' in main
    assert 'show_panel_sale' not in (ROOT / 'app/bot/handlers/public/reseller.py').read_text()  # independent legacy reseller request
    assert 'pgsale:shop' in (ROOT / 'app/bot/keyboards/common.py').read_text()
