"""Regression: approved minimal, readable conversion preview must not affect quote math."""
from datetime import datetime

from app.services.plan_conversion import GIB, quote_conversion, format_conversion_preview


def make_message(**replacements):
    quote = {
        'source_remaining_bytes': 10 * GIB,
        'destination_bytes': (10 * GIB * 14000) // 6000,
        'value_irt': '139998.54',
        'remaining_seconds': 29 * 86400 + 2 * 3600,
        'expires_at': datetime(2026, 11, 12, 16, 20),
    }
    return format_conversion_preview(
        username=replacements.get('username', 'hdhdj111'),
        source_category=replacements.get('source_category', '⚡️  VIP حجمی پرسرعت'),
        target_category=replacements.get('target_category', '💰 حجمی اقتصادی'),
        target_server=replacements.get('target_server', 'اقتصادی'),
        quote=replacements.get('quote', quote),
    )


def test_preview_is_minimal_and_preserves_approved_section_order():
    text = make_message()
    assert '<b>پیش‌نمایش تبدیل تعرفه</b>' in text
    assert text.count('──────────────') == 3
    assert text.index('کانفیگ:') < text.index('تعرفه فعلی:') < text.index('تعرفه جدید:')
    assert text.index('سرور مقصد:') < text.index('حجم باقی‌مانده:') < text.index('حجم جدید:') < text.index('اعتبار باقی‌مانده:')
    assert 'VIP حجمی پرسرعت ⚡️' in text
    assert 'حجمی اقتصادی 💰' in text
    assert '<code>hdhdj111</code>' in text
    assert '۱۰ گیگابایت' in text
    assert '۲۳٫۳۳۳ گیگابایت' in text
    assert '۱۳۹٬۹۹۹ تومان' in text
    assert '۱۳۹۹۹۸٫۵۴' not in text
    assert '۲۹ روز و ۲ ساعت' in text
    assert '۱۲ نوامبر ۲۰۲۶، ساعت ۱۶:۲۰ UTC' in text
    assert 'نرخ فعلی' not in text
    assert 'نرخ مقصد' not in text
    assert 'غیرفعال' in text


def test_preview_does_not_mutate_quote_and_uses_safe_html():
    expiry = datetime(2026, 10, 20, 12, 30)
    q = quote_conversion(8 * GIB, 6000, 14000, expiry, datetime(2026, 10, 14, 12, 30))
    original = dict(q)
    text = make_message(username='user<one>&two', source_category='⚡ VIP <fast>', target_server='A&B', quote=q)
    assert q == original
    assert q['destination_bytes'] == (8 * GIB * 6000) // 14000
    assert '<code>user&lt;one&gt;&amp;two</code>' in text
    assert 'VIP &lt;fast&gt; ⚡' in text
    assert 'A&amp;B' in text
    assert '۳٫۴۲۹ گیگابایت' in text
    assert '۴۸٬۰۰۰ تومان' in text
    assert '۱۴ اکتبر' not in text
    assert '۲۰ اکتبر ۲۰۲۶' in text


def test_preview_short_remaining_time_never_has_blank_fields():
    q = {
        'source_remaining_bytes': 2 * GIB,
        'destination_bytes': GIB,
        'value_irt': '12000.00',
        'remaining_seconds': 31 * 60,
        'expires_at': datetime(2026, 10, 15, 9, 31),
    }
    text = make_message(quote=q)
    assert '۳۱ دقیقه' in text
    assert '۱ گیگابایت' in text
    assert '۲ گیگابایت' in text
    assert '۱۲٬۰۰۰ تومان' in text


def test_handler_passes_html_parse_mode_and_uses_minimal_renderer():
    from pathlib import Path
    code = (Path(__file__).resolve().parents[1] / 'app/bot/handlers/public/convert.py').read_text()
    assert 'text = format_conversion_preview(' in code
    assert "]), parse_mode='HTML')" in code
    assert 'نرخ فعلی:' not in code
