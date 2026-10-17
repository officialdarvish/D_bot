"""Check the actual Telegram home-keyboard layout without requiring aiogram."""
import ast
import asyncio
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / 'app/bot/keyboards/common.py'


def _load_menu_with_fakes(settings: dict[str, str], *, sales: bool = False):
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    needed_functions = {
        'button_text_key', 'button_enabled_key', '_button_value', '_pair_rows',
        'main_menu_inline',
    }
    wanted = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and all(isinstance(t, ast.Name) for t in node.targets):
            if any(t.id.startswith(('BTN_', 'CB_')) or t.id == 'BUTTON_DEFAULTS' for t in node.targets):
                wanted.append(node)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == 'BUTTON_DEFAULTS':
            wanted.append(node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in needed_functions:
            wanted.append(node)

    class FakeButton:
        def __init__(self, text: str, callback_data: str):
            self.text, self.callback_data = text, callback_data

    class FakeMarkup:
        def __init__(self, inline_keyboard):
            self.inline_keyboard = inline_keyboard

    async def load_settings(_names):
        return settings

    async def get_setting_value(_key, _default):
        return '1' if sales else '0'

    namespace = {
        'InlineKeyboardButton': FakeButton,
        'InlineKeyboardMarkup': FakeMarkup,
        '_load_button_settings': load_settings,
        'get_setting_value': get_setting_value,
    }
    exec(compile(ast.Module(body=wanted, type_ignores=[]), str(SOURCE), 'exec'), namespace)
    return namespace['main_menu_inline']


def _assert_convert_layout(keyboard):
    rows = keyboard.inline_keyboard
    convert_index = next(i for i, row in enumerate(rows) if any(b.callback_data == 'menu:convert' for b in row))
    reseller_index = next(i for i, row in enumerate(rows) if any(b.callback_data == 'menu:reseller' for b in row))
    assert convert_index + 1 == reseller_index
    assert len(rows[convert_index]) == 1  # Telegram renders this button at full row width.
    assert rows[convert_index][0].text == 'تبدیل تعرفه 🔄'  # RTL: icon visually at left.
    assert sum(b.callback_data == 'menu:convert' for row in rows for b in row) == 1


def test_convert_is_full_width_above_reseller_for_both_user_and_admin():
    menu = _load_menu_with_fakes({})
    for is_admin, is_reseller in ((False, False), (False, True), (True, False)):
        result = asyncio.run(menu(is_admin=is_admin, is_reseller=is_reseller))
        _assert_convert_layout(result)


def test_saved_old_default_text_keeps_new_icon_position():
    menu = _load_menu_with_fakes({'button_convert_text': '🔄 تبدیل تعرفه'})
    _assert_convert_layout(asyncio.run(menu()))


def test_convert_custom_label_and_disabled_setting_are_preserved():
    menu = _load_menu_with_fakes({'button_convert_text': 'تغییر پلن ✨'})
    result = asyncio.run(menu())
    convert = next(b for row in result.inline_keyboard for b in row if b.callback_data == 'menu:convert')
    assert convert.text == 'تغییر پلن ✨'

    menu = _load_menu_with_fakes({'button_convert_enabled': '0'})
    result = asyncio.run(menu())
    assert not any(b.callback_data == 'menu:convert' for row in result.inline_keyboard for b in row)
    assert any(b.callback_data == 'menu:reseller' for row in result.inline_keyboard for b in row)


def test_sale_menu_remains_independent_after_reseller_row():
    menu = _load_menu_with_fakes({}, sales=True)
    result = asyncio.run(menu())
    callbacks = [b.callback_data for row in result.inline_keyboard for b in row]
    assert callbacks.index('menu:convert') < callbacks.index('menu:reseller') < callbacks.index('pgsale:shop')
