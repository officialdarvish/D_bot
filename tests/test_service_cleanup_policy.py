from __future__ import annotations

import sys
import types
import os
from datetime import datetime, timedelta
from types import SimpleNamespace


def _import_cleanup_helpers():
    os.environ.setdefault('BOT_TOKEN', 'test-token')
    os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://user:pass@localhost/test')
    aiogram = types.ModuleType('aiogram')
    aiogram_types = types.ModuleType('aiogram.types')

    class DummyTelegramType:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    aiogram_types.InlineKeyboardButton = DummyTelegramType
    aiogram_types.InlineKeyboardMarkup = DummyTelegramType
    sys.modules.setdefault('aiogram', aiogram)
    sys.modules.setdefault('aiogram.types', aiogram_types)

    # The retry helpers do not need a real engine. Avoid creating one merely to
    # import the cleanup module in this policy-level unit test.
    session_module = types.ModuleType('app.database.session')
    session_module.SessionLocal = None
    sys.modules.setdefault('app.database.session', session_module)

    from app.jobs.service_cleanup import _panel_missing, retry_delay

    return _panel_missing, retry_delay


def _service(**overrides):
    defaults = {
        'client_username': 'sample-user',
        'is_active': False,
        'disabled_at': datetime(2026, 1, 1, 12, 0, 0),
        'disabled_reason': 'expired',
        'expires_at': datetime(2026, 1, 1, 12, 0, 0),
        'total_bytes': 10,
        'used_bytes': 1,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_retry_backoff_is_bounded_and_increasing():
    _panel_missing, retry_delay = _import_cleanup_helpers()
    minutes = [int(retry_delay(attempt).total_seconds() // 60) for attempt in range(1, 10)]
    assert minutes == [5, 15, 30, 60, 180, 360, 720, 720, 720]


def test_panel_not_found_counts_as_success_state():
    panel_missing, _retry_delay = _import_cleanup_helpers()
    assert panel_missing(RuntimeError('404 record not found')) is True
    assert panel_missing(RuntimeError('connect failed: timed out')) is False


def test_expired_service_disappears_at_72_hour_deadline():
    from app.services.service_grace import visible_in_my_services

    service = _service()
    before = service.disabled_at + timedelta(hours=72) - timedelta(seconds=1)
    at_deadline = service.disabled_at + timedelta(hours=72)
    assert visible_in_my_services(service, before) is True
    assert visible_in_my_services(service, at_deadline) is False


def test_manual_disable_is_not_auto_purged():
    from app.services.service_grace import visible_in_my_services

    service = _service(
        disabled_reason='disabled_on_mikrotik_panel',
        expires_at=datetime(2027, 1, 1),
        total_bytes=0,
        used_bytes=0,
    )
    much_later = service.disabled_at + timedelta(days=90)
    assert visible_in_my_services(service, much_later) is True


def test_cleanup_queue_table_keeps_required_retry_fields():
    from app.database import models  # noqa: F401
    from app.database.base import Base

    table = Base.metadata.tables['service_deletion_tasks']
    columns = set(table.columns.keys())
    assert {
        'source_service_id',
        'server_id',
        'identifiers',
        'status',
        'attempt_count',
        'next_attempt_at',
        'last_error',
        'completed_at',
        'admin_notified_at',
    } <= columns
