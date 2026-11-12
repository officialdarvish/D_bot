"""Short-lived media URLs for native video elements without exposing Telegram tokens."""
import hashlib
import hmac
import time
from app.core.config import settings


def signature(app_id: str, user_id: int, expires: int) -> str:
    message=f'tutorial:{app_id}:{user_id}:{expires}'.encode()
    return hmac.new(settings.BOT_TOKEN.encode(),message,hashlib.sha256).hexdigest()


def url(app_id: str, user_id: int) -> str:
    expires=int(time.time())+300
    return f'/api/miniapp/tutorial-video/{app_id}?uid={user_id}&expires={expires}&token={signature(app_id,user_id,expires)}'


def validate(app_id: str, user_id: int, expires: int, token: str) -> bool:
    now=int(time.time())
    return now<=expires<=now+300 and hmac.compare_digest(signature(app_id,user_id,expires),token)
