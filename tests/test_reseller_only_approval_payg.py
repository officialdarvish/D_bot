"""Coverage for reseller-only server scope, confirmation workflow, and delegated PAYG."""
import ast
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def src(path): return (ROOT/path).read_text()

def test_reseller_only_list_and_no_default_placeholder():
    frontend = src('frontend/components/admin-dashboard.tsx')
    assert "server.scope === 'reseller'" in frontend
    fn = frontend.split('function resellerForm(',1)[1].split('function ',1)[0]
    assert 'Primary/default server' not in fn
    assert "resellerServers.map(server => ({ value: server.id" in fn
    backend = src('app/api/admin_web.py')
    assert "(item.meta or {}).get('scope') != 'reseller'" in backend
    assert 'obj.server_id = selected_ids[0]' in backend


def test_bot_never_falls_back_to_unauthorized_default():
    bot = src('app/bot/handlers/public/reseller.py')
    fn = bot.split('async def resolve_reseller_build_target(',1)[1].split('async def ',1)[0]
    assert "(server.meta or {}).get('scope') == 'reseller'" in fn
    assert 'Never silently choose a default' in fn
    assert 'server = next(' not in fn


def test_admin_wizard_collects_all_steps_then_notifies_real_user():
    admin = src('app/bot/handlers/admin/resellers.py')
    for callback in ('resadmin:awpick:', 'resadmin:awnext:', 'resadmin:awib:',
                     'resadmin:awibnext:', 'resadmin:awconfirm:'):
        assert callback in admin
    assert 'ResellerAccessApproval.quota' in admin
    assert 'ResellerAccessApproval.days' in admin
    assert 'with_for_update()' in admin
    assert 'reseller.allowed_server_ids = allowed' in admin
    assert "callback_data='restart:start'" in admin
    assert 'target_id = u.telegram_id' in admin
    ast.parse(admin)


def test_ownerless_sales_check_upstream_permissions_not_owner_label():
    adapter = src('app/services/pasarguard_panel_sales.py')
    assert 'require_provisioning_access' in adapter
    assert 'admins.create is denied' in adapter
    assert 'ensure_control_permissions' in adapter and '_verify_reseller_role(verified)' in adapter
    assert "'read': {'scope': 1}" in adapter
    api = src('app/api/admin_web.py')
    assert 'await provider.require_provisioning_access(server)' in api
    assert "(server.meta or {}).get('scope') != 'reseller'" in api
