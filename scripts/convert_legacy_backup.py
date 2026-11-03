#!/usr/bin/env python3
"""Convert a D BOT backup format 1-3 into portable format 4.

The old source installation's FERNET_KEY is required because legacy server
and website credentials were encrypted for that installation only. Supply it through the
LEGACY_FERNET_KEY environment variable or enter it securely when prompted.
"""
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.portable_backup import (
    PORTABLE_BACKUP_FORMAT,
    attach_checksum,
    create_portable_secret_box,
    portable_secret_metadata,
    seal_portable_secret,
)


def _source_fernet() -> Fernet:
    raw_key = (os.getenv('LEGACY_FERNET_KEY') or '').strip()
    if raw_key:
        try:
            return Fernet(raw_key.encode('ascii'))
        except Exception as exc:
            raise SystemExit('LEGACY_FERNET_KEY is not a valid Fernet key.') from exc

    bot_token = (os.getenv('LEGACY_BOT_TOKEN') or '').strip()
    if bot_token:
        derived = base64.urlsafe_b64encode(hashlib.sha256(bot_token.encode('utf-8')).digest())
        return Fernet(derived)

    entered = getpass.getpass('Old source FERNET_KEY (input is hidden): ').strip()
    if not entered:
        raise SystemExit('The old source FERNET_KEY is required.')
    try:
        return Fernet(entered.encode('ascii'))
    except Exception as exc:
        raise SystemExit('The entered FERNET_KEY is invalid.') from exc


def _decrypt_legacy(value: Any, source_box: Fernet) -> str:
    raw = str(value or '').strip()
    if not raw:
        return ''
    try:
        return source_box.decrypt(raw.encode('ascii')).decode('utf-8')
    except InvalidToken as exc:
        if raw.startswith('gAAAAA'):
            raise SystemExit(
                'A credential could not be decrypted. The supplied FERNET_KEY/BOT_TOKEN does not match the source installation.'
            ) from exc
        # Very old installations occasionally stored panel passwords as plaintext.
        return raw


def convert(data: dict[str, Any], source_box: Fernet) -> dict[str, Any]:
    meta = data.get('meta') or {}
    if not isinstance(meta, dict) or meta.get('app') != 'D BOT':
        raise SystemExit('The input file is not a D BOT backup.')
    try:
        source_format = int(meta.get('format') or 1)
    except (TypeError, ValueError) as exc:
        raise SystemExit('The input backup format is invalid.') from exc
    if source_format >= PORTABLE_BACKUP_FORMAT:
        raise SystemExit('The input backup is already portable format 4 or newer.')

    portable_key, portable_box = create_portable_secret_box()
    converted = json.loads(json.dumps(data, ensure_ascii=False))
    converted_meta = dict(converted.get('meta') or {})
    converted_meta.pop('signature', None)
    converted_meta.pop('checksum', None)
    converted_meta.update({
        'format': PORTABLE_BACKUP_FORMAT,
        'portability': 'cross-installation',
        'converted_from_format': source_format,
        'portable_secrets': portable_secret_metadata(portable_key),
    })
    converted['meta'] = converted_meta

    for row in converted.get('servers', []) or []:
        if not isinstance(row, dict):
            raise SystemExit('The servers section contains an invalid row.')
        plaintext = _decrypt_legacy(row.get('password_encrypted'), source_box)
        row['password_encrypted'] = seal_portable_secret(plaintext, portable_box)

    for row in converted.get('settings', []) or []:
        if not isinstance(row, dict):
            raise SystemExit('The settings section contains an invalid row.')
        if str(row.get('key') or '') != 'web_admin_password_encrypted':
            continue
        raw = str(row.get('value') or '')
        if raw:
            row['value'] = seal_portable_secret(_decrypt_legacy(raw, source_box), portable_box)

    attach_checksum(converted)
    return converted


def main() -> None:
    parser = argparse.ArgumentParser(description='Convert D BOT legacy JSON backup to portable format 4.')
    parser.add_argument('input', type=Path, help='Legacy backup JSON path')
    parser.add_argument('output', type=Path, nargs='?', help='Output path (default: dbot_portable_backup_v4.json)')
    args = parser.parse_args()

    source = args.input.expanduser().resolve()
    output = (args.output or Path('dbot_portable_backup_v4.json')).expanduser().resolve()
    data = json.loads(source.read_text(encoding='utf-8'))
    converted = convert(data, _source_fernet())
    output.write_text(json.dumps(converted, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    try:
        os.chmod(output, 0o600)
    except OSError:
        pass
    print(f'Portable backup created: {output}')


if __name__ == '__main__':
    main()
