"""Convert belongs inside selected My Configs service, not on bot home."""
import ast
import asyncio
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / 'app/bot/keyboards/common.py'
DETAILS = Path(__file__).resolve().parents[1] / 'app/bot/handlers/public/my_services.py'
CONVERT = Path(__file__).resolve().parents[1] / 'app/bot/handlers/public/convert.py'


def _load_menu_with_fakes(settings: dict[str, str], *, sales: bool = False):
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    names = {'button_text_key', 'button_enabled_key', '_button_value', '_pair_rows', 'main_menu_inline'}
    wanted = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and all(isinstance(t, ast.Name) for t in node.targets):
            if any(t.id.startswith(('BTN_', 'CB_')) or t.id == 'BUTTON_DEFAULTS' for t in node.targets):
                wanted.append(node)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == 'BUTTON_DEFAULTS':
            wanted.append(node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            wanted.append(node)

    class FakeButton:
        def __init__(self, text, callback_data):
            self.text, self.callback_data = text, callback_data

    class FakeMarkup:
        def __init__(self, inline_keyboard):
            self.inline_keyboard = inline_keyboard

    async def load(_names):
        return settings

    async def get_setting(_key, _default):
        return '1' if sales else '0'

    ns = {'InlineKeyboardButton': FakeButton, 'InlineKeyboardMarkup': FakeMarkup,
          '_load_button_settings': load, 'get_setting_value': get_setting}
    exec(compile(ast.Module(body=wanted, type_ignores=[]), str(SOURCE), 'exec'), ns)
    return ns['main_menu_inline']


def test_convert_only_appears_within_selected_service_details():
    menu = _load_menu_with_fakes({})
    for is_admin, is_reseller in ((False, False), (False, True), (True, False)):
        home = asyncio.run(menu(is_admin=is_admin, is_reseller=is_reseller))
        callbacks = [b.callback_data for row in home.inline_keyboard for b in row]
        assert 'menu:convert' not in callbacks
        assert 'menu:my_services' in callbacks
    detail = DETAILS.read_text()
    assert "callback_data=f'svcconvert:source:{svc.id}'" in detail
    assert "rows.append([InlineKeyboardButton(text='تبدیل تعرفه 🔄'" in detail


def test_conversion_back_navigation_returns_to_selected_service():
    code = CONVERT.read_text()
    assert "rows.append([back_button(f'svc:{sid}')])" in code
    assert "rows.append([back_button('menu:my_services')])" in code


def test_panel_sales_remains_separate_and_menu_does_not_include_convert():
    menu = _load_menu_with_fakes({}, sales=True)
    rows = asyncio.run(menu()).inline_keyboard
    callbacks = [b.callback_data for row in rows for b in row]
    assert 'menu:convert' not in callbacks
    assert callbacks.index('menu:reseller') < callbacks.index('pgsale:shop')
