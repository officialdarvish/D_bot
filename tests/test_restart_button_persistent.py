from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_restart_button_bypasses_stale_callback_guard():
    main = (ROOT / 'app/main.py').read_text('utf-8')
    assert "'restart:start'," in main


def test_restart_button_opens_fresh_ui_instead_of_editing_old_broadcast_message():
    start = (ROOT / 'app/bot/handlers/start.py').read_text('utf-8')
    marker = "@router.callback_query(F.data == 'restart:start')"
    begin = start.index(marker)
    end = start.index('async def _open_main_menu_from_callback', begin)
    handler = start[begin:end]
    assert '_open_main_menu_from_callback(callback, state, force_new_message=True)' in handler
    assert 'send_single_message(' in handler
    assert 'await edit_or_answer(' not in handler
