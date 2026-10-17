"""Regression tests for the persistent restart button under delivered configs."""
from __future__ import annotations

import ast
from pathlib import Path
from dataclasses import dataclass

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class _Button:
    text: str
    callback_data: str | None = None


@dataclass
class _Markup:
    inline_keyboard: list[list[_Button]]


def _load_keyboard_helper():
    """Exercise the production helper without requiring the Telegram SDK."""
    path = ROOT / 'app/bot/service_presenter.py'
    tree = ast.parse(path.read_text('utf-8'))
    helper = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'config_restart_keyboard')
    code = compile(ast.Module(body=[helper], type_ignores=[]), str(path), 'exec')
    namespace = {
        'InlineKeyboardMarkup': _Markup,
        'InlineKeyboardButton': _Button,
        'RESTART_BOT_LABEL': '🔄 شروع مجدد ربات',
        'RESTART_BOT_CALLBACK': 'restart:start',
    }
    exec(code, namespace)
    return namespace['config_restart_keyboard']


def _callbacks(markup):
    return [[button.callback_data for button in row] for row in markup.inline_keyboard]


def test_restart_keyboard_is_full_width_and_persistent():
    markup = _load_keyboard_helper()()
    assert len(markup.inline_keyboard) == 1
    button = markup.inline_keyboard[0][0]
    assert button.text == '🔄 شروع مجدد ربات'
    assert button.callback_data == 'restart:start'


def test_restart_keyboard_preserves_existing_controls_and_does_not_mutate_input():
    helper = _load_keyboard_helper()
    original = _Markup(inline_keyboard=[[_Button('📥 پروفایل', 'svc:profile:24')], [_Button('🏠 خانه', 'report:home')]])
    result = helper(original)
    assert _callbacks(original) == [['svc:profile:24'], ['report:home']]
    assert _callbacks(result) == [['svc:profile:24'], ['report:home'], ['restart:start']]
    assert result.inline_keyboard[0] is not original.inline_keyboard[0]


def test_restart_keyboard_is_not_duplicated_if_provided_by_caller():
    helper = _load_keyboard_helper()
    original = _Markup(inline_keyboard=[[_Button('🔄 شروع مجدد ربات', 'restart:start')]])
    result = helper(original)
    assert _callbacks(result) == [['restart:start']]


def test_all_standard_config_cards_attach_restart_action():
    src = (ROOT / 'app/bot/service_presenter.py').read_text('utf-8')
    assert 'markup = config_restart_keyboard(markup)' in src
    assert src.index('markup = config_restart_keyboard(markup)') < src.index('if sub_link and')
    assert "reply_markup=markup" in src


def test_special_delivery_paths_attach_restart_action():
    reseller = (ROOT / 'app/bot/handlers/public/reseller.py').read_text('utf-8')
    public = (ROOT / 'app/bot/handlers/public/my_services.py').read_text('utf-8')
    convert = (ROOT / 'app/bot/handlers/public/convert.py').read_text('utf-8')
    renewal = (ROOT / 'app/bot/renewal_delivery.py').read_text('utf-8')
    profile = (ROOT / 'app/bot/profile_delivery.py').read_text('utf-8')
    assert "await message.answer_photo(FSInputFile(qr_path), caption=caption, parse_mode='HTML', reply_markup=config_restart_keyboard())" in reseller
    assert "reply_markup=config_restart_keyboard(reseller_home_kb())" in reseller
    revoke = public.split("@router.callback_query(F.data.startswith('svc:revoke:'))", 1)[1].split("@router.callback_query(F.data.startswith('svc:refresh:'))", 1)[0]
    assert revoke.count('reply_markup=config_restart_keyboard()') == 2
    assert 'await send_service_info(' in convert
    assert 'return config_restart_keyboard(' in renewal
    assert 'reply_markup=config_restart_keyboard(reply_markup or profile_home_keyboard())' in profile


def test_restart_action_bypasses_stale_guard_and_reopens_fresh_start_page():
    main = (ROOT / 'app/main.py').read_text('utf-8')
    start = (ROOT / 'app/bot/handlers/start.py').read_text('utf-8')
    assert "'restart:start'," in main
    handler = start.split("@router.callback_query(F.data == 'restart:start')", 1)[1].split('async def _open_main_menu_from_callback', 1)[0]
    assert 'await state.clear()' in handler
    assert "get_setting_value('rules_enabled', '0')" in handler
    assert 'await check_channel_join(' in handler
    assert '_open_main_menu_from_callback(callback, state, force_new_message=True)' in handler
