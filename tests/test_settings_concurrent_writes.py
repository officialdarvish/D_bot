import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import defaults
from app.database.models import Setting
from app.database.settings_write import settings_upsert_statement, upsert_settings
from app.bot.handlers.admin import settings as bot_settings


def test_postgres_uses_one_atomic_conflict_update():
    statement = settings_upsert_statement('postgresql', {'backup_chat_id': 'one', 'backup_admin_ok': '1'})
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert 'ON CONFLICT (key) DO UPDATE SET value = excluded.value' in sql
    assert sql.startswith('INSERT INTO settings')
    assert len(statement.compile(dialect=postgresql.dialect()).params) == 4


def test_concurrent_backup_detection_and_atomic_bulk_writes(tmp_path, monkeypatch):
    async def run():
        engine = create_async_engine('sqlite+aiosqlite:///' + str(tmp_path / 'settings.db'))
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Setting.__table__.create)
        monkeypatch.setattr(defaults, 'SessionLocal', sessions)
        defaults.invalidate_settings_cache()
        try:
            # Deliver duplicate channel posts concurrently, all observing the
            # same invite-link state before any of their writes have completed.
            ready = asyncio.Event()
            arrived = 0
            async def stale_setting(key, default=''):
                nonlocal arrived
                if key == 'backup_chat_id':
                    arrived += 1
                    if arrived == 12:
                        ready.set()
                    await ready.wait()
                    return 'https://t.me/+private-invite'
                return 'channel'
            monkeypatch.setattr(bot_settings, 'get_setting_value', stale_setting)
            message = SimpleNamespace(chat=SimpleNamespace(type='channel', id=-1001234567890, title='Backup'))
            await asyncio.gather(*(bot_settings.detect_existing_private_backup_channel(message) for _ in range(12)))
            async with sessions() as session:
                rows = dict((await session.execute(select(Setting.key, Setting.value))).all())
            assert len(rows) == 7
            assert rows['backup_chat_id'] == '-1001234567890'
            assert rows['backup_admin_ok'] == '1'
            # Prime the cache, then verify a subsequent committed write refreshes it.
            assert await defaults.get_setting_value('backup_chat_id') == '-1001234567890'
            await asyncio.gather(*(defaults.set_setting_value('backup_chat_id', 'updated') for _ in range(12)))
            assert await defaults.get_setting_value('backup_chat_id') == 'updated'
            # A failed batch must not leave half its settings saved.
            with pytest.raises(IntegrityError):
                async with sessions() as session:
                    await upsert_settings(session, {'backup_chat_id': 'must-rollback', 'invalid': None})
                    await session.commit()
            async with sessions() as session:
                assert (await session.get(Setting, 'backup_chat_id')).value == 'updated'
                assert await session.get(Setting, 'invalid') is None
            # Unrelated configuration survives a partial settings update.
            await bot_settings.save_web_settings_bulk({'backup_admin_ok': '0'})
            assert await defaults.get_setting_value('backup_chat_id') == 'updated'
            assert await defaults.get_setting_value('backup_admin_ok') == '0'
        finally:
            defaults.invalidate_settings_cache()
            await engine.dispose()
    asyncio.run(run())
