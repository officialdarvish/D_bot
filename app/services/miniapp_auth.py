"""Telegram Mini App authentication. Never trust initDataUnsafe or URL user IDs."""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


def validate_init_data(raw: str, token: str, *, now: float | None = None, max_age: int = 3600) -> dict:
    if not raw or len(raw) > 16384:
        raise ValueError('Invalid Telegram session')
    pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
    data = dict(pairs)
    if len(pairs) != len(data):
        raise ValueError('Duplicate Telegram fields')
    received = data.pop('hash', '')
    secret = hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
    check = '\n'.join(f'{key}={value}' for key, value in sorted(data.items()))
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        raise ValueError('Invalid Telegram signature')
    age = (time.time() if now is None else now) - int(data.get('auth_date', '0'))
    if age < -30 or age > max_age:
        raise ValueError('Expired Telegram session')
    user = json.loads(data.get('user', '{}'))
    if not isinstance(user, dict) or type(user.get('id')) is not int or user['id'] <= 0:
        raise ValueError('Invalid Telegram user')
    return user
