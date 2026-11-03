from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding='utf-8')


def test_multi_server_setting_and_backward_compatibility_are_wired():
    defaults = text('app/database/defaults.py')
    api = text('app/api/admin_web.py')
    assert "'test_account_targets_json': '[]'" in defaults
    assert "targets_json: str = Form('')" in api
    assert "'test_account_targets_json': json.dumps(normalized_targets" in api
    assert "'test_account_server_id': str(first['server_id'])" in api
    assert "'targets': targets" in api


def test_public_trial_handler_provisions_all_selected_targets_with_partial_success():
    source = text('app/bot/handlers/public/test_account.py')
    assert "async def _load_test_account_targets()" in source
    assert "async def _create_test_account_on_target" in source
    assert "for item in targets:" in source
    assert "successes.append(created)" in source
    assert "failures.append" in source
    assert "if not successes:" in source
    assert "for created in successes:" in source
    assert "len(successes)" in source


def test_all_multi_server_trial_services_keep_test_cleanup_policy():
    cleanup = text('app/jobs/service_cleanup.py')
    alerts = text('app/jobs/service_alerts.py')
    assert "ClientService.client_username.ilike('test_%')" in cleanup
    assert ".lower().startswith('test_')" in alerts


def test_web_admin_supports_server_and_per_server_inbound_multiselect():
    ui = text('frontend/components/admin-dashboard.tsx')
    assert 'type TestAccountTarget = { server_id: number; inbound_ids: number[] }' in ui
    assert 'Multi-Server Trial Accounts' in ui
    assert 'toggleServer(server' in ui
    assert 'toggleInbound(server.id, inbound.id)' in ui
    assert 'targets_json: JSON.stringify(form.targets)' in ui
    assert 'Save Multi-Server Test Account' in ui


def test_telegram_quick_picker_writes_new_multi_server_setting():
    source = text('app/bot/handlers/admin/settings.py')
    assert "test_account_targets_json" in source
    assert "s.server_type in {'xui', 'pasarguard', 'mikrotik'}" in source
    assert 'Web Admin → Test Account' in source
