#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import string
import sys
from pathlib import Path

# This file is invoked directly by the VPS control script inside the API
# container (``python /app/scripts/web_credentials_cli.py``).  In that mode
# Python puts ``/app/scripts`` on sys.path, not the project root (``/app``),
# so absolute imports such as ``app.services...`` would fail.  Add the project
# root explicitly before importing the application package.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.web_credentials import read_web_credentials, save_web_credentials
from app.services.web_access import read_web_path, save_web_path


def generate_password(length: int = 24) -> str:
    alphabet = string.ascii_letters + string.digits + '_-@#%+'
    while True:
        value = ''.join(secrets.choice(alphabet) for _ in range(max(16, length)))
        if any(c.islower() for c in value) and any(c.isupper() for c in value) and any(c.isdigit() for c in value):
            return value


async def main() -> int:
    parser = argparse.ArgumentParser(description='Read or update the live D BOT website credentials.')
    sub = parser.add_subparsers(dest='command', required=True)

    show = sub.add_parser('show')
    show.add_argument('--json', action='store_true')

    set_username = sub.add_parser('set-username')
    set_username.add_argument('username')

    set_password = sub.add_parser('set-password')
    set_password.add_argument('--stdin', action='store_true')
    set_password.add_argument('password', nargs='?')

    generate = sub.add_parser('generate-password')
    generate.add_argument('--length', type=int, default=24)

    set_path = sub.add_parser('set-path')
    set_path.add_argument('web_path')

    args = parser.parse_args()
    if args.command == 'show':
        snap = await read_web_credentials()
        payload = {
            'username': snap.username,
            'password': snap.password,
            'password_available': snap.password_available,
            'updated_at': snap.updated_at,
            'updated_by': snap.updated_by,
            'source': snap.source,
            'web_path': await read_web_path(),
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            for key, value in payload.items():
                print(f'{key}={value}')
        return 0

    if args.command == 'set-username':
        snap = await save_web_credentials(username=args.username, updated_by='dbot-credentials-center')
        print(json.dumps({'ok': True, 'username': snap.username}, ensure_ascii=False))
        return 0

    if args.command == 'set-password':
        password = sys.stdin.read().rstrip('\r\n') if args.stdin else (args.password or '')
        snap = await save_web_credentials(password=password, updated_by='dbot-credentials-center')
        print(json.dumps({'ok': True, 'password_available': snap.password_available}, ensure_ascii=False))
        return 0

    if args.command == 'generate-password':
        password = generate_password(args.length)
        await save_web_credentials(password=password, updated_by='dbot-credentials-center-generated')
        print(password)
        return 0

    if args.command == 'set-path':
        value = await save_web_path(args.web_path)
        print(json.dumps({'ok': True, 'web_path': value}, ensure_ascii=False))
        return 0

    return 2


if __name__ == '__main__':
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        raise SystemExit(1)
