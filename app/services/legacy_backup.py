from __future__ import annotations

import base64
import hashlib
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.core.security import decrypt_text


class LegacyBackupSecretRequired(ValueError):
    """Raised when a format 1-3 backup needs the source installation secret."""


class LegacyBackupSecretInvalid(ValueError):
    """Raised when the supplied source secret cannot decrypt legacy credentials."""


def legacy_source_box(secret: str = '', kind: str = 'auto') -> Fernet | None:
    """Build the old installation's Fernet box without storing the supplied secret.

    Older D BOT installations encrypted credentials with either FERNET_KEY or,
    when that value was empty, a SHA-256 key derived from BOT_TOKEN. The restore
    screen accepts either value and uses it only for the current request.
    """
    raw = (secret or '').strip()
    if not raw:
        return None
    kind = (kind or 'auto').strip().lower()
    if kind not in {'auto', 'fernet', 'bot_token'}:
        raise ValueError('Legacy secret type is invalid')

    if kind in {'auto', 'fernet'}:
        try:
            return Fernet(raw.encode('ascii'))
        except Exception:
            if kind == 'fernet':
                raise LegacyBackupSecretInvalid('The old FERNET_KEY format is invalid.')

    if kind in {'auto', 'bot_token'}:
        if kind == 'bot_token' and ':' not in raw:
            raise LegacyBackupSecretInvalid('The old Telegram bot token format is invalid.')
        derived = base64.urlsafe_b64encode(hashlib.sha256(raw.encode('utf-8')).digest())
        return Fernet(derived)
    return None


def open_legacy_secret(value: Any, source_box: Fernet | None, label: str) -> str:
    """Decrypt a legacy value with the local key or an explicitly supplied source key."""
    raw = str(value or '').strip()
    if not raw:
        return ''

    # Same-install restores still work without asking for the old key. Plaintext
    # credentials from very old releases are also handled by decrypt_text().
    try:
        return decrypt_text(raw)
    except RuntimeError:
        pass

    if source_box is None:
        raise LegacyBackupSecretRequired(
            f'This is a legacy backup and {label} was encrypted by the source installation. '
            'Enter the old FERNET_KEY from dbot credentials/show secrets. If that installation had no FERNET_KEY, enter its old Telegram bot token instead.'
        )
    try:
        return source_box.decrypt(raw.encode('ascii')).decode('utf-8')
    except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
        raise LegacyBackupSecretInvalid(
            f'The supplied old FERNET_KEY or bot token does not match the source backup ({label}).'
        ) from exc
