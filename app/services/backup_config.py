from __future__ import annotations

from app.core.security import decrypt_text, encrypt_text

ERROR_LOG_BOT_TOKEN_KEY = 'error_log_bot_token_encrypted'
BACKUP_SECONDARY_BOT_TOKEN_KEY = 'backup_secondary_bot_token_encrypted'
BACKUP_AES_PASSWORD_KEY = 'backup_aes_password_encrypted'
BACKUP_LOCAL_SETTINGS = {BACKUP_AES_PASSWORD_KEY, 'backup_protection_mode'}
BACKUP_MODES = {'normal', 'private', 'aes'}


def protection_mode(values: dict) -> str:
    mode = str(values.get('backup_protection_mode') or 'private')
    if mode not in BACKUP_MODES:
        raise ValueError('Invalid backup protection mode.')
    return mode


def backup_password(values: dict) -> str:
    raw = str(values.get(BACKUP_AES_PASSWORD_KEY) or '')
    if not raw:
        raise ValueError('Set an AES password before creating an AES backup.')
    try:
        return decrypt_text(raw)
    except RuntimeError as exc:
        raise ValueError('The saved AES password cannot be read. Set it again in Backup Protection.') from exc
BACKUP_INTERVALS: tuple[int, ...] = (60, 180, 360, 720, 1440, 10080)
BACKUP_INTERVAL_LABELS = {
    60: '1 hour',
    180: '3 hours',
    360: '6 hours',
    720: '12 hours',
    1440: '24 hours',
    10080: '7 days',
}


def normalize_backup_interval(value: object, default: int = 1440) -> int:
    try:
        minutes = int(str(value or '').strip())
    except (TypeError, ValueError):
        return default
    return minutes if minutes in BACKUP_INTERVALS else default


def encrypt_secondary_bot_token(token: str) -> str:
    clean = (token or '').strip()
    return encrypt_text(clean) if clean else ''


def decrypt_secondary_bot_token(value: str) -> str:
    raw = (value or '').strip()
    if not raw:
        return ''
    try:
        return decrypt_text(raw)
    except RuntimeError:
        return ''
