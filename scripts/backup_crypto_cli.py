#!/usr/bin/env python3
"""D BOT archive encryption/recovery, using the same policy as web and bot."""
from pathlib import Path
import argparse
import asyncio
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.encrypted_backup import (
    ARCHIVE_CONTENT, decrypt_stream, encrypt_stream,
    installation_key, recovery_bundle, recovery_keys, bundle_keys,
)
from app.services.backup_config import protection_mode, backup_password


async def configured_policy():
    from app.api.admin_web import _settings_map
    return await _settings_map()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['encrypt', 'decrypt', 'recovery-key', 'recovery-keys', 'mode'])
    parser.add_argument('--key-file', type=Path, help='One recovery key or the JSON recovery-key list')
    parser.add_argument('--password-file', type=Path, help='Private file containing the original AES password (one trailing newline removed)')
    parser.add_argument('--mode', choices=['normal', 'private', 'aes'], help='Snapshot selected by the D BOT control script')
    args = parser.parse_args()
    try:
        if args.command == 'recovery-key':
            print(installation_key())
            return 0
        if args.command == 'recovery-keys':
            sys.stdout.buffer.write(recovery_bundle())
            return 0
        if args.command in ('mode', 'encrypt'):
            values = asyncio.run(configured_policy())
            mode = args.mode or protection_mode(values)
            password = backup_password(values) if mode == 'aes' else ''
            if args.command == 'mode':
                print(mode)
                return 0
            if mode == 'normal':
                shutil.copyfileobj(sys.stdin.buffer, sys.stdout.buffer)
            else:
                if mode == 'private':
                    recovery_keys()
                    async def deliver_keys():
                        from app.api.admin_web import _telegram_send_recovery_keys, _telegram_token, _effective_backup_chat_id
                        destination = str(values.get('backup_destination') or 'channel')
                        target = _effective_backup_chat_id(destination, str(values.get('backup_chat_id') or values.get('backup_channel') or ''), values)
                        if target:
                            result = await _telegram_send_recovery_keys(await _telegram_token(values), target, destination)
                            if not result.get('ok'):
                                raise ValueError('Recovery key delivery failed; archive was not encrypted.')
                        elif values.get('backup_protection_mode') == 'private':
                            raise ValueError('Configure a backup destination before creating a private-key archive.')
                    asyncio.run(deliver_keys())
                encrypt_stream(sys.stdin.buffer, sys.stdout.buffer, content=ARCHIVE_CONTENT, password=password)
            return 0
        key = args.key_file.read_text(encoding='utf-8').strip() if args.key_file else ''
        password = args.password_file.read_text(encoding='utf-8').removesuffix('\n') if args.password_file else ''
        if args.key_file:
            # Verify each candidate against a seekable private spool, releasing no
            # unauthenticated plaintext. Handles full archives larger than RAM.
            import tempfile
            from app.services.encrypted_backup import BackupKeyRequired
            with tempfile.TemporaryFile() as source:
                shutil.copyfileobj(sys.stdin.buffer, source)
                keys = bundle_keys(key)
                for candidate in keys:
                    source.seek(0)
                    try:
                        decrypt_stream(source, sys.stdout.buffer, content=ARCHIVE_CONTENT, key=candidate, password=password)
                        break
                    except BackupKeyRequired:
                        if candidate == keys[-1]:
                            raise
        else:
            decrypt_stream(sys.stdin.buffer, sys.stdout.buffer, content=ARCHIVE_CONTENT, password=password)
        return 0
    except (OSError, ValueError) as exc:
        print(f'D BOT backup failed: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
