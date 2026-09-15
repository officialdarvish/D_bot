from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.services.backup_config import BACKUP_INTERVAL_LABELS, normalize_backup_interval

logger = logging.getLogger(__name__)


def _now_local() -> datetime:
    try:
        return datetime.now(ZoneInfo(settings.TZ))
    except Exception:
        return datetime.now().astimezone()


def _parse_dt(value: str, tzinfo) -> datetime | None:
    raw = str(value or '').strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tzinfo)
        return dt.astimezone(tzinfo)
    except Exception:
        return None


async def deliver_scheduled_backup() -> None:
    """Send backups on a configurable interval: 1/3/6/12/24 hours or 7 days.

    The scheduler calls this every minute. A persisted anchor/last-success timestamp
    prevents duplicates across restarts. Failed attempts are retried after 15 minutes.
    """
    from app.api.admin_web import (
        _effective_backup_chat_id,
        _save_settings_map,
        _settings_map,
        _telegram_send_backup,
        _telegram_token,
        _write_backup_file,
    )

    values = await _settings_map()
    if str(values.get('backup_schedule_enabled') or '1') != '1':
        return

    interval_minutes = normalize_backup_interval(values.get('backup_interval_minutes') or '1440')
    now = _now_local()
    last_success = _parse_dt(values.get('backup_last_scheduled_at', ''), now.tzinfo)
    anchor = last_success or _parse_dt(values.get('backup_schedule_anchor_at', ''), now.tzinfo)
    if anchor is None:
        # First configuration/start: establish a deterministic anchor instead of
        # immediately spamming a backup on process start.
        await _save_settings_map({'backup_schedule_anchor_at': now.isoformat()})
        return

    due_at = anchor + timedelta(minutes=interval_minutes)
    if now < due_at:
        return

    last_attempt = _parse_dt(values.get('backup_last_scheduled_attempt_at', ''), now.tzinfo)
    if last_attempt and now - last_attempt < timedelta(minutes=15):
        return
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
        interval_label = BACKUP_INTERVAL_LABELS.get(interval_minutes, f'{interval_minutes} minutes')
        result = await _telegram_send_backup(
            token,
            target,
            path,
            destination,
            caption=(
                '🕒 D BOT scheduled portable backup v4\n\n'
                f'🔁 Cycle: {interval_label}\n'
                '✅ New backup document\n'
                '✅ Restorable from Backup & Restore'
            ),
            filename=f'dbot_scheduled_backup_{stamp}.json',
        )
        success = bool(result.get('ok'))
        save_values = {
            'backup_last_backup_status': 'ok' if success else 'error',
            'backup_last_backup_message': result.get('message', ''),
            'backup_last_backup_at': attempted_at,
        }
        if success:
            save_values.update({
                'backup_last_scheduled_at': now.isoformat(),
                'backup_schedule_anchor_at': now.isoformat(),
            })
        await _save_settings_map(save_values)
        if not success:
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
