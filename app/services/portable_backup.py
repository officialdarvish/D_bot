from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

PORTABLE_BACKUP_FORMAT = 4
PORTABLE_SECRET_SCHEME = 'fernet-self-contained-v1'
PORTABLE_SECRET_PREFIX = 'dbot-portable-v1:'


def canonical_backup(data: dict[str, Any]) -> bytes:
    """Return a stable representation used by the portable integrity checksum.

    The checksum and old host-bound signature are excluded so the backup remains
    verifiable after moving it to another D BOT installation.
    """
    clone = dict(data)
    meta = dict(clone.get('meta') or {})
    meta.pop('checksum', None)
    meta.pop('signature', None)
    clone['meta'] = meta
    return json.dumps(
        clone,
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')


def backup_checksum(data: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_backup(data)).hexdigest()


def attach_checksum(data: dict[str, Any]) -> None:
    meta = data.setdefault('meta', {})
    meta['checksum'] = backup_checksum(data)


def verify_checksum(data: dict[str, Any]) -> None:
    meta = data.get('meta') or {}
    supplied = str(meta.get('checksum') or '').strip().lower()
    if not supplied:
        raise ValueError('Portable backup checksum is missing')
    expected = backup_checksum(data)
    if not hmac.compare_digest(supplied, expected):
        raise ValueError('Portable backup checksum is invalid; the file may be incomplete or modified')


def create_portable_secret_box() -> tuple[str, Fernet]:
    key = Fernet.generate_key()
    return key.decode('ascii'), Fernet(key)


def portable_secret_metadata(key: str) -> dict[str, Any]:
    return {
        'scheme': PORTABLE_SECRET_SCHEME,
        'key': key,
        'fields': ['servers.password_encrypted', 'settings.web_admin_password_encrypted'],
        'warning': 'This backup contains recoverable credentials. Store it privately.',
    }


def portable_secret_box_from_meta(meta: dict[str, Any]) -> Fernet:
    envelope = meta.get('portable_secrets') or {}
    if not isinstance(envelope, dict):
        raise ValueError('Portable backup secret metadata is invalid')
    if envelope.get('scheme') != PORTABLE_SECRET_SCHEME:
        raise ValueError('Portable backup secret scheme is unsupported')
    key = str(envelope.get('key') or '').strip()
    if not key:
        raise ValueError('Portable backup secret key is missing')
    try:
        return Fernet(key.encode('ascii'))
    except Exception as exc:
        raise ValueError('Portable backup secret key is invalid') from exc


def seal_portable_secret(plaintext: str, box: Fernet) -> str:
    token = box.encrypt((plaintext or '').encode('utf-8')).decode('ascii')
    return PORTABLE_SECRET_PREFIX + token


def open_portable_secret(value: str, box: Fernet) -> str:
    raw = str(value or '')
    if not raw.startswith(PORTABLE_SECRET_PREFIX):
        raise ValueError('Portable backup contains an unwrapped credential')
    token = raw[len(PORTABLE_SECRET_PREFIX):]
    try:
        return box.decrypt(token.encode('ascii')).decode('utf-8')
    except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
        raise ValueError('Portable backup credential could not be decrypted') from exc
