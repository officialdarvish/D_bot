from pathlib import Path

from app.bot.error_reporting import _context_fa, _error_reason_fa


def test_admin_error_reason_translates_expired_callback_to_persian():
    exc = RuntimeError('Telegram server says - Bad Request: query is too old and response timeout expired or query ID is invalid')
    reason = _error_reason_fa(exc)
    assert 'زمان پاسخ' in reason
    assert 'query' not in reason.lower()
    assert 'Bad Request' not in reason


def test_unhandled_context_is_persian():
    assert _context_fa('Unhandled bot handler exception') == 'پردازش پیام یا دکمه کاربر'


def test_admin_telegram_report_does_not_send_traceback_or_raw_exception():
    source = Path('app/bot/error_reporting.py').read_text(encoding='utf-8')
    report_block = source.split('async def report_bot_error', 1)[1].split('async def show_generic_error', 1)[0]
    assert 'محل خطا' not in report_block
    assert '_last_trace_frames' not in source
    assert "f'❌ خطا:" not in report_block
    assert 'جزئیات فنی و مسیر اجرای خطا فقط در لاگ سرور' in report_block


def test_reseller_duplicate_names_use_independent_four_digit_sequence():
    source = Path('app/bot/handlers/public/reseller.py').read_text(encoding='utf-8')
    assert 'ResellerUsernameCounter' in source
    assert "suffix = str(number).zfill(4)" in source
    assert "candidate = f'{base}_{suffix}'" in source
    assert 'یوزرنیم یا اسم اختصاصی‌ای که انتخاب کرده‌اید تکراری است.' in source


def test_reseller_panel_duplicate_is_retried_instead_of_failing_immediately():
    source = Path('app/bot/handlers/public/reseller.py').read_text(encoding='utf-8')
    block = source.split('# The panel can still report a duplicate', 1)[1].split('if not isinstance(result, dict):', 1)[0]
    assert 'for duplicate_attempt in range(8)' in block
    assert 'is_reseller_duplicate_username_error(panel_exc)' in block
    assert 'allocate_reseller_duplicate_username' in block
    assert 'await state.update_data(username=username, username_auto_adjusted=True)' in block


def test_portable_backup_includes_reseller_username_counter():
    source = Path('app/api/admin_web.py').read_text(encoding='utf-8')
    assert "('reseller_username_counters', ResellerUsernameCounter)" in source
