from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_persistent_reports_have_home_button_and_stale_guard_exception():
    common = (ROOT / 'app/bot/keyboards/common.py').read_text()
    main = (ROOT / 'app/main.py').read_text()
    start = (ROOT / 'app/bot/handlers/start.py').read_text()

    assert "InlineKeyboardButton(text='🏠 خانه', callback_data='report:home')" in common
    assert "'report:home'," in main
    assert "F.data == 'report:home'" in start
    assert 'edit_reply_markup(reply_markup=None)' in start
    assert '_open_main_menu_from_callback(callback, state, force_new_message=True)' in start


def test_new_user_join_report_has_persistent_home_button():
    start = (ROOT / 'app/bot/handlers/start.py').read_text()
    assert 'await bot.send_message(admin_id, text_msg, reply_markup=report_home_inline())' in start


def test_test_account_shows_progress_and_notifies_admin_with_identity_and_name():
    text = (ROOT / 'app/bot/handlers/public/test_account.py').read_text()
    assert '⏳ در حال ساخت اکانت تست هستیم، لطفاً صبر کنید...' in text
    assert '🧪 گزارش دریافت اکانت تست' in text
    assert '🆔 آیدی عددی:' in text
    assert '🔗 یوزرنیم:' in text
    assert '🕒 تاریخ و ساعت:' in text
    assert '🧪 نام اکانت تست:' in text
    assert 'reply_markup=report_home_inline()' in text


def test_deletion_notification_has_persistent_home_button():
    text = (ROOT / 'app/services/service_deletion_audit.py').read_text()
    assert 'reply_markup=report_home_inline()' in text
