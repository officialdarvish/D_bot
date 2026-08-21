from __future__ import annotations

import os

os.environ.setdefault('BOT_TOKEN', 'test-token')
os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://user:pass@localhost/test')

from app.services.service_deletion_audit import admin_deletion_message


def test_admin_deletion_report_contains_owner_service_and_queue_status():
    text = admin_deletion_message(
        {
            'service_id': 264,
            'owner_telegram_id': 708872939,
            'owner_username': 'sample_owner',
            'owner_full_name': 'Sample Owner',
            'actor_telegram_id': 708872939,
            'actor_username': 'sample_owner',
            'actor_full_name': 'Sample Owner',
            'deletion_source': 'user_manual',
            'deletion_reason': 'user_delete',
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
        },
        panel_status='queued',
        task_id=12,
    )

    assert 'کاربر از بخش «کانفیگ‌های من»' in text
    assert 'Telegram ID: 708872939' in text
    assert '@sample_owner' in text
    assert 'openvpn-user-264' in text
    assert 'OpenVPN 50GB' in text
    assert 'Finland 1' in text
    assert '50.00 گیگ' in text
    assert 'در صف تلاش مجدد است' in text
    assert 'شناسه صف حذف: #12' in text
