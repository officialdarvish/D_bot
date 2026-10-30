"""D BOT authenticated backup containers, independent of the portable schema.

Version 1 derives a per-file key from an installation key using HKDF-SHA256.
Version 2 derives it from an administrator password using fixed-cost scrypt.
AES-256-GCM authenticates the complete header and content in both versions;
each file has a fresh salt and nonce. Recovery bundles are separate documents.
"""
from __future__ import annotations

import base64
import binascii
import fcntl
import hashlib
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import BinaryIO

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from app.core.config import settings

MAGIC = b'DBOTBK\x00'
VERSION = 1
PASSWORD_VERSION = 2
JSON_CONTENT = 1
ARCHIVE_CONTENT = 2
HEADER_SIZE = len(MAGIC) + 2 + 32 + 12
CHUNK_SIZE = 1024 * 1024


class BackupKeyRequired(ValueError):
    """Wrong key and damaged ciphertext intentionally share one error."""


class BackupPasswordRequired(ValueError):
    """An AES password is missing, incorrect, or the file failed authentication."""


def validate_password(password: str) -> None:
    if not 12 <= len(password) <= 256:
        raise ValueError('AES password must contain 12 to 256 characters.')


def decode_key(value: str) -> bytes:
    try:
        raw = base64.b64decode(value.strip().encode('ascii'), altchars=b'-_', validate=True)
        if len(raw) != 32:
            raise ValueError
        return raw
    except (ValueError, UnicodeError, binascii.Error) as exc:
        raise ValueError('Recovery key must be a URL-safe Base64 encoded 32-byte key.') from exc


def installation_key() -> str:
    """Persist once, under a cross-process lock shared by API and bot containers."""
    configured = str(settings.BACKUP_ENCRYPTION_KEY or '').strip()
    if configured:
        decode_key(configured)
        return configured
    path = Path(settings.BACKUP_ENCRYPTION_KEY_FILE)
    try:
        path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        lock_fd = os.open(str(path) + '.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(lock_fd, 'r+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if not path.exists():
                key = base64.urlsafe_b64encode(os.urandom(32)).decode('ascii')
                fd, name = tempfile.mkstemp(dir=path.parent, prefix='.backup-key-')
                try:
                    with os.fdopen(fd, 'w', encoding='ascii') as stream:
                        stream.write(key + '\n')
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(name, path)
                finally:
                    Path(name).unlink(missing_ok=True)
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, 'r', encoding='ascii') as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
                    raise ValueError('Backup key file must be a private regular file (chmod 600).')
                key = stream.read(256).strip()
            decode_key(key)
            return key
    except OSError as exc:
        raise ValueError('Backup key storage is unavailable. Mount the persistent backup_keys volume or configure BACKUP_ENCRYPTION_KEY.') from exc


def key_id(key: str) -> str:
    return hashlib.sha256(decode_key(key)).hexdigest()[:24]


def recovery_keys() -> dict:
    """Keep every locally registered backup key, including a changed env override.

    A bundle is recovery material, never embedded in a database/project backup.
    """
    active = installation_key()
    path = Path(settings.BACKUP_ENCRYPTION_KEY_FILE).parent / 'recovery-keys.json'
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    lock_fd = os.open(str(path)+'.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, 'r+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = {'app': 'D BOT', 'kind': 'backup-recovery-keys', 'version': 1, 'keys': []}
        if path.exists():
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, 'r', encoding='utf-8') as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
                    raise ValueError('Recovery key list must be a private regular file (chmod 600).')
                data = json.loads(stream.read(131073))
            bundle_keys(data)  # Reject corruption; never discard previous keys.
        ident = key_id(active)
        if not any(row['id'] == ident for row in data['keys']):
            if len(data['keys']) >= 128:
                raise ValueError('Recovery key list is full. Archive old recovery keys before changing the key.')
            data['keys'].append({'id': ident, 'key': active, 'created_at': datetime.now(timezone.utc).isoformat()})
        data['active_key_id'] = ident
        fd, name = tempfile.mkstemp(dir=path.parent, prefix='.recovery-keys-')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, path)
        finally:
            Path(name).unlink(missing_ok=True)
        return data


def bundle_keys(value: dict | str) -> list[str]:
    if isinstance(value, str):
        if len(value) > 131072:
            raise ValueError('Recovery key list is too large.')
        if not value.lstrip().startswith('{'):
            decode_key(value)
            return [value.strip()]
        try:
            value = json.loads(value)
        except ValueError as exc:
            raise ValueError('Invalid recovery key list.') from exc
    if not isinstance(value, dict) or value.get('app') != 'D BOT' or value.get('kind') != 'backup-recovery-keys' or value.get('version') != 1:
        raise ValueError('Invalid D BOT recovery key list.')
    rows = value.get('keys')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 128:
        raise ValueError('Invalid recovery key list size.')
    result = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('key'), str) or row.get('id') != key_id(row['key']):
            raise ValueError('Invalid recovery key entry.')
        result.append(row['key'])
    return list(dict.fromkeys(result))


def recovery_bundle(*, backup_name: str = '', backup_sha256: str = '') -> bytes:
    data = recovery_keys()
    data['exported_at'] = datetime.now(timezone.utc).isoformat()
    data['backup_name'] = backup_name
    data['backup_sha256'] = backup_sha256
    data['warning'] = 'Sensitive recovery keys. Anyone with these keys and a matching backup can decrypt it. Keep an offline copy.'
    return json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8')


def _password_key(password: str, salt: bytes) -> bytes:
    # Fixed cost, never controlled by untrusted file headers: ~128 MiB memory.
    if not password or len(password) > 256:
        raise BackupPasswordRequired('Enter the AES password used when this backup was created.')
    return Scrypt(salt=salt, length=32, n=2**17, r=8, p=1).derive(password.encode('utf-8'))


def _file_key(key: str, salt: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt,
                info=b'D BOT backup encryption v1').derive(decode_key(key))


def encrypt_stream(source: BinaryIO, target: BinaryIO, *, content: int = JSON_CONTENT, key: str = '', password: str = '') -> None:
    if content not in (JSON_CONTENT, ARCHIVE_CONTENT):
        raise ValueError('Unsupported backup content type.')
    if password:
        validate_password(password)
    else:
        key = key or installation_key()
    salt, nonce = os.urandom(32), os.urandom(12)
    version = PASSWORD_VERSION if password else VERSION
    header = MAGIC + bytes([version, content]) + salt + nonce
    material = _password_key(password, salt) if password else _file_key(key, salt)
    encryptor = Cipher(algorithms.AES(material), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(header)
    target.write(header)
    while chunk := source.read(CHUNK_SIZE):
        target.write(encryptor.update(chunk))
    target.write(encryptor.finalize())
    target.write(encryptor.tag)


def decrypt_stream(source: BinaryIO, target: BinaryIO, *, content: int = JSON_CONTENT, key: str = '', password: str = '') -> None:
    """Never release plaintext to target until the entire file authenticates."""
    header = source.read(HEADER_SIZE)
    if len(header) != HEADER_SIZE or not header.startswith(MAGIC):
        raise ValueError('Invalid D BOT encrypted backup header.')
    version = header[len(MAGIC)]
    if version not in (VERSION, PASSWORD_VERSION):
        raise ValueError('Unsupported D BOT encrypted backup version. Update D BOT.')
    if header[len(MAGIC) + 1] != content:
        raise ValueError('This is a full project archive. Use the D BOT archive recovery tool; web/bot restore requires a database backup.')
    salt, nonce = header[-44:-12], header[-12:]
    try:
        material = _password_key(password, salt) if version == PASSWORD_VERSION else _file_key(key or installation_key(), salt)
        decryptor = Cipher(algorithms.AES(material), modes.GCM(nonce)).decryptor()
        decryptor.authenticate_additional_data(header)
        # Private, automatically removed scratch file also bounds RAM for full archives.
        with tempfile.TemporaryFile() as verified:
            tail = b''
            while chunk := source.read(CHUNK_SIZE):
                combined = tail + chunk
                if len(combined) > 16:
                    verified.write(decryptor.update(combined[:-16]))
                tail = combined[-16:]
            if len(tail) != 16:
                raise InvalidTag
            verified.write(decryptor.finalize_with_tag(tail))
            verified.seek(0)
            while chunk := verified.read(CHUNK_SIZE):
                target.write(chunk)
    except InvalidTag as exc:
        if version == PASSWORD_VERSION:
            raise BackupPasswordRequired('AES password is incorrect or the backup is damaged/modified.') from exc
        raise BackupKeyRequired('Cannot open backup: provide its original recovery key. A wrong key or a damaged/modified file will be rejected.') from exc


def encode_backup(data: dict, *, key: str = '', password: str = '') -> bytes:
    source = io.BytesIO(json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
    target = io.BytesIO()
    encrypt_stream(source, target, key=key, password=password)
    return target.getvalue()


def decode_backup(raw: bytes, *, key: str = '', password: str = '') -> dict:
    if raw.startswith(MAGIC):
        if len(raw) <= len(MAGIC):
            raise ValueError('Invalid D BOT encrypted backup header.')
        target = io.BytesIO()
        if raw[len(MAGIC)] == VERSION:
            candidates = bundle_keys(key) if key else [installation_key()]
            if not key:
                # Old keys are used only from the protected local keyring.
                path = Path(settings.BACKUP_ENCRYPTION_KEY_FILE).parent / 'recovery-keys.json'
                if path.exists():
                    candidates = list(dict.fromkeys(candidates + bundle_keys(recovery_keys())))
            for candidate in candidates:
                try:
                    decrypt_stream(io.BytesIO(raw), target, key=candidate)
                    break
                except BackupKeyRequired:
                    if candidate == candidates[-1]:
                        raise
        else:
            decrypt_stream(io.BytesIO(raw), target, password=password)
        raw = target.getvalue()
    elif not raw.lstrip().startswith(b'{'):
        raise ValueError('Invalid D BOT backup file.')
    # Legacy JSON import is preserved. All newly exported files are encrypted.
    try:
        data = json.loads(raw.decode('utf-8'))
    except (UnicodeError, ValueError) as exc:
        raise ValueError('Invalid backup JSON content.') from exc
    if not isinstance(data, dict):
        raise ValueError('Invalid backup structure.')
    return data
