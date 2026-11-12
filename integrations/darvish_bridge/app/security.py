import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import parse_qsl, urlparse
from fastapi import HTTPException
from .config import settings


def issue_api_key():
    return "db_" + secrets.token_urlsafe(32)


def digest_key(key):
    return hmac.new(settings.app_secret.encode(), key.encode(), hashlib.sha256).hexdigest()


def verify_telegram_init_data(raw: str, max_age_seconds: int = 3600) -> dict:
    """Verify raw Telegram WebApp.initData; never trust initDataUnsafe."""
    if not settings.bot_token or not raw:
        raise HTTPException(401, "ورود فقط از داخل مینی‌اپ تلگرام امکان‌پذیر است")
    try:
        fields = dict(parse_qsl(raw, keep_blank_values=True, strict_parsing=True))
        signature = fields.pop("hash")
        fields.pop("signature", None)
        check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
        secret = hmac.new(b"WebAppData", settings.bot_token.encode(), hashlib.sha256).digest()
        expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        auth_date = int(fields["auth_date"])
        if not hmac.compare_digest(expected, signature) or not (0 <= time.time() - auth_date <= max_age_seconds):
            raise ValueError("signature or date invalid")
        user = json.loads(fields["user"])
        user_id = int(user["id"])
        if user_id <= 0:
            raise ValueError("invalid id")
        return {"id": user_id, "first_name": user.get("first_name", "")}
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise HTTPException(401, "اطلاعات ورود تلگرام نامعتبر یا منقضی شده است")


def permitted_callback_url(url: str | None):
    if not url:
        return None
    u = urlparse(url)
    if u.scheme != "https" or not u.hostname or u.username or u.password or u.fragment:
        raise HTTPException(422, "نشانی وب‌هوک باید HTTPS و معتبر باشد")
    if u.port not in (None, 443):
        raise HTTPException(422, "فقط درگاه استاندارد HTTPS مجاز است")
    if u.hostname.lower() not in settings.webhook_allowed_hosts:
        raise HTTPException(422, "دامنه وب‌هوک در فهرست مجاز سرور ثبت نشده است")
    return url
