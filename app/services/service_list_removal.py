"""Local list visibility only. This module never calls a panel API."""
from datetime import datetime
from hashlib import sha256
from urllib.parse import urlsplit, urlunsplit, unquote
import json
import uuid
from sqlalchemy import select, update
from app.core.config import settings
from app.database.models import ClientService, User, Server, Order, ServiceConversion, ServiceDeletionTask, MiniAppOperation, Setting


class ListRemovalError(ValueError):
    pass


def normalized_link(raw):
    value = (raw or '').strip()
    if not value or len(value) > 8192 or any(c.isspace() for c in value):
        raise ListRemovalError('فقط لینک کامل ساب را در یک پیام بفرستید.')
    if value.startswith('happ://add/'):
        value = unquote(value[len('happ://add/'):])
    if any(c.isspace() for c in value):
        raise ListRemovalError('فقط لینک کامل ساب را بدون فاصله بفرستید.')
    if value.startswith('happ://crypt5/') and len(value) > len('happ://crypt5/'):
        return value  # Opaque encrypted links are case-sensitive; compare exactly.
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError()
        port = parsed.port
        host = parsed.hostname.lower()
        if ':' in host: host = f'[{host}]'
        if port is not None and not (parsed.scheme.lower() == 'http' and port == 80 or parsed.scheme.lower() == 'https' and port == 443):
            host += f':{port}'
        # Fragments are app labels, not subscription identity. Keep query params
        # (including auth tokens) and the full host/path; never match token-only.
        return urlunsplit((parsed.scheme.lower(), host, parsed.path.rstrip('/'), parsed.query, ''))
    except ValueError:
        raise ListRemovalError('لینک ساب معتبر نیست؛ لینک کامل HTTP، HTTPS یا Happ را بفرستید.')


def link_fingerprint(link):
    return sha256(normalized_link(link).encode()).hexdigest()


def require_admin(actor):
    if actor not in settings.admin_ids:
        raise ListRemovalError('این عملیات فقط برای مدیر ربات مجاز است.')


async def eligible(session, sid, actor, *, lock=False):
    require_admin(actor)
    query = select(ClientService).where(ClientService.id == sid)
    if lock: query = query.with_for_update()
    svc = await session.scalar(query)
    if not svc or str(svc.client_username or '').startswith('deleted_'):
        raise ListRemovalError('این کانفیگ دیگر در ربات ثبت نیست.')
    if svc.hidden_from_owner:
        raise ListRemovalError('این کانفیگ قبلاً از فهرست صاحب آن حذف شده است.')
    user = await session.get(User, svc.user_id)
    if not user: raise ListRemovalError('مالک کانفیگ در دیتابیس پیدا نشد.')
    deletion = await session.scalar(select(ServiceDeletionTask.id).where(
        ServiceDeletionTask.source_service_id == sid, ServiceDeletionTask.status != 'completed').limit(1))
    conversion = await session.scalar(select(ServiceConversion.id).where(
        ServiceConversion.source_service_id == sid, ServiceConversion.status != 'completed').limit(1))
    order = await session.scalar(select(Order.id).where(Order.service_id == sid,
        Order.status.in_(('pending','processing','waiting_receipt','waiting_payment','paid_pending_delivery'))).limit(1))
    operation = await session.scalar(select(MiniAppOperation.id).where(
        MiniAppOperation.status.in_(('queued','processing','review')),
        MiniAppOperation.payload['service_id'].as_integer() == sid).limit(1))
    if deletion or conversion or order or operation:
        raise ListRemovalError('برای این کانفیگ عملیات حذف، تبدیل یا پرداخت در انتظار است؛ ابتدا آن عملیات را تعیین تکلیف کنید.')
    return svc, user, await session.get(Server, svc.server_id) if svc.server_id else None


async def lookup(session, link, actor):
    require_admin(actor)
    target = normalized_link(link)
    matches = []
    # Read stored identities only. Never fetch an administrator-supplied URL.
    rows = await session.stream(select(ClientService.id, ClientService.sub_link).where(ClientService.sub_link.is_not(None)))
    async for sid, stored in rows:
        try: matches_link = normalized_link(stored) == target
        except ListRemovalError: continue
        if matches_link:
            matches.append(sid)
            if len(matches) > 1: break
    await rows.close()
    if not matches:
        raise ListRemovalError('کانفیگی با این لینک در ربات پیدا نشد؛ آخرین لینک ساب ثبت‌شده را بفرستید.')
    if len(matches) != 1:
        raise ListRemovalError('این لینک برای چند کانفیگ ثبت شده است؛ حذف انجام نشد. ابتدا لینک‌های تکراری را بررسی کنید.')
    return await eligible(session, matches[0], actor)


async def remove_from_owner_list(session, sid, actor, owner_id, fingerprint):
    """Caller commits flag + audit together. No deletes, quota/owner changes or network."""
    svc, user, server = await eligible(session, sid, actor, lock=True)
    if user.id != owner_id or not svc.sub_link or link_fingerprint(svc.sub_link) != fingerprint:
        raise ListRemovalError('مالک یا لینک کانفیگ تغییر کرده است؛ لینک ساب را دوباره بفرستید و اطلاعات تازه را تأیید کنید.')
    result = await session.execute(update(ClientService).where(
        ClientService.id == sid, ClientService.user_id == owner_id,
        ClientService.sub_link == svc.sub_link, ClientService.hidden_from_owner.is_(False)
    ).values(hidden_from_owner=True).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        raise ListRemovalError('اطلاعات کانفیگ تغییر کرده است؛ دوباره بررسی کنید.')
    session.add(Setting(key=f'service_list_removal:{uuid.uuid4().hex}', value=json.dumps({
        'service_id': sid, 'user_id': user.id, 'telegram_id': user.telegram_id,
        'actor_telegram_id': actor, 'at': datetime.utcnow().isoformat(),
    }, separators=(',', ':'))))
    await session.flush()
    return svc.client_username or svc.xui_email or str(sid), user.telegram_id
