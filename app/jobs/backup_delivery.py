from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.config import settings

logger = logging.getLogger(__name__)


def _now_local() -> datetime:
    try:
        return datetime.now(ZoneInfo(settings.TZ))
    except Exception:
        return datetime.now()


async def deliver_scheduled_backup() -> None:
    """Create and send one new restorable backup document at the configured time.

    The job runs every minute but attempts delivery only once per local calendar
    day. Telegram delivery uses sendDocument and never edits an existing message.
    """
    # Local import keeps normal bot startup lightweight and avoids importing the
    # web backup stack before the database/application are initialized.
    from app.api.admin_web import (
        _effective_backup_chat_id,
        _save_settings_map,
        _settings_map,
        _telegram_send_backup,
        _telegram_token,
        _write_backup_file,
    )

    values = await _settings_map()
    configured_time = str(values.get('backup_time') or '03:00').strip()
    now = _now_local()
    try:
        due_hour, due_minute = [int(part) for part in configured_time.split(':', 1)]
        due_at = now.replace(hour=due_hour, minute=due_minute, second=0, microsecond=0)
    except Exception:
        logger.error('Invalid backup_time setting: %s', configured_time)
        return
    if now < due_at:
        return

    today = now.date().isoformat()
    if values.get('backup_last_scheduled_date') == today:
        return

    last_attempt_raw = str(values.get('backup_last_scheduled_attempt_at') or '').strip()
    if last_attempt_raw:
        try:
            last_attempt = datetime.fromisoformat(last_attempt_raw)
            if last_attempt.tzinfo is None:
                last_attempt = last_attempt.replace(tzinfo=now.tzinfo)
            if now - last_attempt < timedelta(minutes=15):
                return
        except Exception:
            pass

    # Claim this retry window before doing I/O. A failed delivery is retried
    # every 15 minutes until it succeeds, without creating duplicate backups.
    await _save_settings_map({'backup_last_scheduled_attempt_at': now.isoformat()})

    destination = str(values.get('backup_destination') or 'channel').strip()
    target = _effective_backup_chat_id(
        destination,
        str(values.get('backup_chat_id') or values.get('backup_channel') or '').strip(),
        values,
    )
    token = await _telegram_token(values)
    path = ''
    attempted_at = datetime.utcnow().isoformat()
    try:
        path = await _write_backup_file()
        stamp = now.strftime('%Y%m%d_%H%M%S')
        result = await _telegram_send_backup(
            token,
            target,
            path,
            destination,
            caption=(
                '🕒 D BOT scheduled portable backup v4\n\n'
                '✅ New backup document\n'
                '✅ Restorable from Backup & Restore'
            ),
            filename=f'dbot_scheduled_backup_{stamp}.json',
        )
        await _save_settings_map({
            'backup_last_backup_status': 'ok' if result.get('ok') else 'error',
            'backup_last_backup_message': result.get('message', ''),
            'backup_last_backup_at': attempted_at,
            'backup_last_scheduled_date': today if result.get('ok') else '',
        })
        if not result.get('ok'):
            logger.error('Scheduled backup delivery failed: %s', result.get('message'))
    except Exception as exc:
        logger.exception('Scheduled backup crashed')
        await _save_settings_map({
            'backup_last_backup_status': 'error',
            'backup_last_backup_message': f'Scheduled backup failed: {exc}',
            'backup_last_backup_at': attempted_at,
        })
    finally:
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass
