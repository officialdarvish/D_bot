"""Regression coverage for scoped multi-provider reseller assignments and approval delivery."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
def source(path): return (ROOT / path).read_text(encoding="utf8")


def test_reseller_server_allowlist_is_persisted_and_migrated_in_both_runtimes():
    model = source('app/database/models/core.py')
    assert 'allowed_server_ids: Mapped[list]' in model
    for runtime in ['app/main.py', 'app/api/main.py']:
        assert 'ALTER TABLE reseller_accounts ADD COLUMN IF NOT EXISTS allowed_server_ids JSON' in source(runtime)


def test_server_ids_validation_is_strict_and_de_duplicates():
    tree = ast.parse(source('app/api/admin_web.py'))
    fn = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == '_parse_reseller_server_selection')
    code = compile(ast.Module(body=[fn], type_ignores=[]), '<reseller-ids>', 'exec')
    ns = {}
    exec(code, ns)
    parse = ns[fn.name]
    assert parse('2,3,3,7') == [2,3,7]
    assert parse('[2, 5, 8]') == [2,5,8]
    for bad in ('abc', '1,-2', '[true]', '[2, false]', '{"x":2}', '1,0'):
        try: parse(bad)
        except ValueError: pass
        else: raise AssertionError(f'Unsafe reseller ID accepted: {bad}')


def test_reseller_bot_checks_explicit_allowlist_before_provisioning():
    text = source('app/bot/handlers/public/reseller.py')
    assert "if chosen not in allowed:" in text
    assert "if server_id_value not in allowed_now" in text or "server_id_value not in allowed_now" in text
    assert "reseller_target_server_id" in text
    assert "callback_data=f'reseller:buildserver:{sv.id}'" in text
    assert "server.server_type == 'pasarguard'" in text
    assert "server.server_type == 'mikrotik'" in text


def test_request_toggle_is_independent_of_panel_sales_and_approved_resellers():
    admin = source('app/api/admin_web.py')
    bot = source('app/bot/keyboards/common.py')
    assert "@router.post('/admin/resellers/request-settings')" in admin
    assert "invalidate_button_settings_cache()" in admin
    assert "'reseller_menu' if is_reseller else 'reseller_request'" in bot
    assert "pasarguard_panel_sales_enabled" in bot


def test_admin_approval_refreshes_only_the_buyer_menu():
    admin = source('app/bot/handlers/admin/resellers.py')
    fn = admin.split('async def reseller_approval_confirm(', 1)[1].split('@router.callback_query', 1)[0]
    assert 'target_id = u.telegram_id' in fn and 'bot.send_message(' in fn
    assert "callback_data='restart:start'" in fn
    assert "callback.message.answer('🏠 صفحه اصلی'" not in fn
    panel = source('app/bot/handlers/admin/panel_reseller_sale.py')
    assert "InlineKeyboardButton(text='🔄 شروع مجدد ربات', callback_data='restart:start')" in panel
    assert "await bot.send_message(destination, '🏠 صفحه اصلی ربات'" not in panel
