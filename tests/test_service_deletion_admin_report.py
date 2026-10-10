from __future__ import annotations

import os

os.environ.setdefault('BOT_TOKEN', 'test-token')
os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://user:pass@localhost/test')

from app.services.service_deletion_audit import admin_deletion_message


def _snapshot(source: str = 'user_manual', reason: str = 'user_delete') -> dict:
    return {
        'service_id': 264,
        'owner_telegram_id': 708872939,
        'owner_username': 'sample_owner',
        'owner_full_name': 'Sample Owner',
        'actor_telegram_id': 708872939,
        'actor_username': 'sample_owner',
        'actor_full_name': 'Sample Owner',
        'deletion_source': source,
        'deletion_reason': reason,
        'client_username': 'openvpn-user-264',
        'panel_username': 'openvpn-user-264',
        'plan_title': 'OpenVPN 50GB',
        'server_name': 'Finland 1',
        'server_type': 'mikrotik',
        'total_bytes': 50 * 1024 ** 3,
        'used_bytes': 12 * 1024 ** 3,
        'remaining_bytes': 38 * 1024 ** 3,
        'created_at': '2026-07-01T10:00:00',
        'expires_at': '2026-08-01T10:00:00',
        'deleted_at': '2026-08-02T10:00:00',
    }


def test_admin_deletion_report_is_short_and_manual():
    text = admin_deletion_message(_snapshot(), panel_status='queued', task_id=12)

    assert 'گزارش حذف کانفیگ' in text
    assert 'دلیل: دستی' in text
    assert '@sample_owner' in text
    assert 'آیدی عددی: 708872939' in text
    assert 'یوزرنیم پنل: openvpn-user-264' in text
    assert 'حجم کل: 50 گیگ' in text
    assert 'حجم مانده: 38 گیگ' in text
    assert 'تاریخ انقضا:' in text

    # Explicitly removed from the compact manager report.
    assert 'شناسه صف' not in text
    assert 'Finland 1' not in text
    assert 'OpenVPN 50GB' not in text
    assert 'مصرف‌شده' not in text
    assert 'وضعیت:' not in text
    assert 'شناسه سرویس' not in text


def test_admin_deletion_report_marks_automatic_cleanup_as_bot():
    text = admin_deletion_message(
        _snapshot(source='automatic_72h', reason='expired'),
        panel_status='deleted',
        task_id=22,
    )
    assert 'دلیل: ربات' in text
    assert 'شناسه صف' not in text
