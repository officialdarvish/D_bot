from __future__ import annotations

from app.core.security import decrypt_text, encrypt_text

BACKUP_SECONDARY_BOT_TOKEN_KEY = 'backup_secondary_bot_token_encrypted'
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
