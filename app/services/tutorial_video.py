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


def byte_range(value: str | None, size: int) -> tuple[int, int] | None:
    """Resolve one inclusive HTTP byte range; ignore unsupported range units/multipart."""
    import re
    if not value or not value.startswith('bytes='):return None
    if len(value)>256:raise ValueError('Invalid media range')
    if ',' in value:return None
    match=re.fullmatch(r'bytes=([0-9]*)-([0-9]*)',value)
    if not match or not any(match.groups()) or size<=0:raise ValueError('Invalid media range')
    first,last=match.groups()
    if not first:
        count=int(last)
        if count<=0:raise ValueError('Invalid media range')
        return max(0,size-count),size-1
    start=int(first);end=min(int(last),size-1) if last else size-1
    if start>=size or end<start:raise ValueError('Unsatisfiable media range')
    return start,end
