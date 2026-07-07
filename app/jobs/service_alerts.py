from __future__ import annotations

import logging
from datetime import datetime, timedelta

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select, or_, and_, update

from app.database.session import SessionLocal
from app.database.models import (
    ClientService,
    User,
    Server,
    Order,
    TestAccountUsage,
    ResellerAccount,
)
from app.services.xui_service import XuiService
from app.services.mikrotik_service import MikroTikService

logger = logging.getLogger(__name__)

GB = 1024 ** 3
MB = 1024 ** 2
DISABLED_PURGE_AFTER = timedelta(hours=72)
DISABLED_NOTIFY_INTERVAL = timedelta(hours=24)
DISABLED_NOTIFY_WINDOW = DISABLED_PURGE_AFTER
TEST_EXPIRED_PURGE_AFTER = timedelta(hours=6)


def gb(b):
    return b / GB if b else 0


def _is_tombstone(svc: ClientService | None) -> bool:
    if not svc:
        return True
    name = (svc.client_username or '')
    return name.startswith('deleted_')


def _disable_reason(svc: ClientService, now: datetime) -> str | None:
    if not svc or _is_tombstone(svc):
        return None
    if svc.expires_at and svc.expires_at <= now:
        return 'expired'
    total = int(svc.total_bytes or 0)
    used = int(svc.used_bytes or 0)
    if total > 0 and used >= total:
        return 'volume'
    return None


def _reason_fa(reason: str | None) -> str:
    if reason == 'expired':
        return 'پایان تاریخ سرویس'
    if reason == 'volume':
        return 'اتمام حجم سرویس'
    return 'غیرفعال شدن سرویس'


async def _is_test_service(session, svc: ClientService | None) -> bool:
    if not svc or not getattr(svc, 'id', None):
        return False
    row = (await session.execute(
        select(TestAccountUsage.id)
        .where(TestAccountUsage.service_id == svc.id)
        .limit(1)
    )).scalar_one_or_none()
    return row is not None


def _renew_keyboard(svc: ClientService) -> InlineKeyboardMarkup:
    if getattr(svc, 'reseller_id', None):
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='🔁 تمدید سرویس نمایندگی', callback_data=f'reseller:renew:{svc.id}')],
            [InlineKeyboardButton(text='👥 یوزرهای نمایندگی', callback_data='reseller:users')],
            [InlineKeyboardButton(text='🏠 خانه', callback_data='home:main')],
        ])
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🔁 تمدید سرویس', callback_data=f'svc:renew_menu:{svc.id}')],
        [InlineKeyboardButton(text='📦 کانفیگ‌های من', callback_data='menu:my_services')],
        [InlineKeyboardButton(text='🏠 خانه', callback_data='home:main')],
    ])


async def _notify_disabled_service(bot, session, svc: ClientService, now: datetime) -> None:
    if await _is_test_service(session, svc):
        return
    user = await session.get(User, svc.user_id)
    if not user:
        return
    disabled_at = getattr(svc, 'disabled_at', None) or now
    delete_at = disabled_at + DISABLED_PURGE_AFTER
    hours_left = max(int((delete_at - now).total_seconds() // 3600), 0)
    reason = getattr(svc, 'disabled_reason', None) or _disable_reason(svc, now)
    username = svc.client_username or svc.xui_email or f'#{svc.id}'
    used_gb = gb(svc.used_bytes or 0)
    total_gb = gb(svc.total_bytes or 0)
    remain_gb = max(total_gb - used_gb, 0)
    owner_line = 'این یوزر مربوط به بخش نمایندگی شماست.' if getattr(svc, 'reseller_id', None) else 'این کانفیگ مربوط به خرید عمومی شماست.'
    text = (
        '⚠️ سرویس شما غیرفعال شده است\n\n'
        f'👤 کانفیگ: {username}\n'
        f'📌 علت: {_reason_fa(reason)}\n'
        f'📊 مصرف‌شده: {used_gb:.2f} گیگ از {total_gb:.2f} گیگ\n'
        f'⏳ باقی‌مانده: {remain_gb:.2f} گیگ\n'
        f'📅 تاریخ انقضا: {svc.expires_at.strftime("%Y-%m-%d") if svc.expires_at else "نامحدود"}\n\n'
        f'{owner_line}\n'
        'برای جلوگیری از حذف کامل، سرویس را تمدید کنید.\n'
        'در صورتی که تمایل به تمدید سرویس خود ندارید، لطفاً از قسمت «کانفیگ‌های من» آن را حذف کنید.\n'
        f'در صورت تمدید نشدن، حدود {hours_left} ساعت دیگر از ربات و پنل حذف می‌شود.'
    )
    try:
        await bot.send_message(user.telegram_id, text, reply_markup=_renew_keyboard(svc))
        svc.disabled_last_notified_at = now
        svc.disabled_notify_count = int(getattr(svc, 'disabled_notify_count', 0) or 0) + 1
    except Exception as exc:
        logger.warning('Disabled service notification failed service_id=%s user_id=%s: %s', svc.id, user.id, exc)


async def _delete_from_panel(server: Server | None, svc: ClientService) -> bool:
    if not server:
        return True
    try:
        if server.server_type == 'xui':
            await XuiService().delete_client(server, svc.xui_email, svc.client_username, svc.xui_uuid, svc.sub_link)
        elif server.server_type == 'mikrotik':
            await MikroTikService().delete_user(server, svc.xui_email or svc.client_username)
        return True
    except Exception as exc:
        msg = str(exc).lower()
        if any(token in msg for token in ('not found', 'not exist', 'not exists', 'record not found', '404')):
            return True
        logger.warning('Auto purge panel delete failed service_id=%s server_id=%s: %s', svc.id, getattr(server, 'id', None), exc)
        return False


async def _delete_service_from_db(session, svc: ClientService) -> None:
    # Keep accounting rows but detach them from the soon-deleted service.
    await session.execute(update(Order).where(Order.service_id == svc.id).values(service_id=None))
    await session.execute(update(TestAccountUsage).where(TestAccountUsage.service_id == svc.id).values(service_id=None))

    if getattr(svc, 'reseller_id', None):
        reseller = await session.get(ResellerAccount, svc.reseller_id)
        if reseller:
            reserved = int(svc.reseller_reserved_bytes or svc.total_bytes or 0)
            reseller.reserved_bytes = max(int(reseller.reserved_bytes or 0) - reserved, 0)
            # Keep used_bytes as actual consumed traffic; only free reserved capacity.

    await session.delete(svc)


async def _purge_disabled_service(bot, session, svc: ClientService, now: datetime) -> bool:
    user = await session.get(User, svc.user_id)
    username = svc.client_username or svc.xui_email or f'#{svc.id}'
    server = await session.get(Server, svc.server_id) if svc.server_id else None
    is_test_service = await _is_test_service(session, svc)
    if not await _delete_from_panel(server, svc):
        return False
    await _delete_service_from_db(session, svc)
    if user and not is_test_service:
        try:
            await bot.send_message(
                user.telegram_id,
                '🗑 سرویس غیرفعال شما به دلیل تمدید نشدن حذف شد.\n\n'
                f'👤 کانفیگ: {username}\n'
                'این سرویس هم از دیتابیس ربات و هم از پنل حذف شده است.',
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='🏠 خانه', callback_data='home:main')]])
            )
        except Exception as exc:
            logger.warning('Auto purge final user notice failed service_id=%s: %s', getattr(svc, 'id', None), exc)
    return True


async def _refresh_active_xui_usage(session, now: datetime) -> None:
    # Refresh a bounded batch of X-UI services so volume-finished clients can be
    # detected even when the user has not opened the service detail page.
    rows = (await session.execute(
        select(ClientService)
        .where(ClientService.is_active == True)
        .where(ClientService.server_id != None)
        .where(or_(ClientService.client_username.is_(None), ~ClientService.client_username.like('deleted_%')))
        .order_by(ClientService.id.asc())
        .limit(80)
    )).scalars().all()
    server_cache: dict[int, Server] = {}
    for svc in rows:
        if not svc.server_id:
            continue
        server = server_cache.get(svc.server_id)
        if server is None:
            server = await session.get(Server, svc.server_id)
            if server:
                server_cache[svc.server_id] = server
        if not server or server.server_type != 'xui':
            continue
        try:
            found = await XuiService().find_client_any(server, svc.xui_email or svc.client_username)
        except Exception as exc:
            logger.warning('X-UI alert refresh failed service_id=%s: %s', svc.id, exc)
            continue
        if not found:
            svc.is_active = False
            svc.disabled_at = svc.disabled_at or now
            svc.disabled_reason = svc.disabled_reason or 'panel'
            continue
        c = found.get('client') or {}
        tr = found.get('traffic') or {}
        used = int((tr.get('up', 0) or 0) + (tr.get('down', 0) or 0))
        total = int(tr.get('total') or c.get('totalGB') or c.get('total') or svc.total_bytes or 0)
        svc.used_bytes = used
        if total:
            svc.total_bytes = total
        enabled = bool(c.get('enable', svc.is_active))
        svc.is_active = enabled
        if not enabled:
            svc.disabled_at = svc.disabled_at or now
            svc.disabled_reason = svc.disabled_reason or _disable_reason(svc, now) or 'panel'


async def _backfill_disabled_tracking(session, now: datetime) -> list[ClientService]:
    # Older versions and panel-sync paths may have already set is_active=False
    # without storing the start time for the 72-hour cleanup window. Start the
    # countdown from the first scan after this version is installed.
    rows = (await session.execute(
        select(ClientService)
        .where(ClientService.is_active == False)
        .where(ClientService.disabled_at == None)
        .where(or_(ClientService.client_username.is_(None), ~ClientService.client_username.like('deleted_%')))
        .order_by(ClientService.id.asc())
        .limit(200)
    )).scalars().all()
    for svc in rows:
        svc.disabled_at = now
        svc.disabled_reason = _disable_reason(svc, now) or 'panel'
        svc.disabled_notify_count = 0
        svc.disabled_last_notified_at = None
    if rows:
        await session.flush()
    return rows


async def _mark_newly_disabled_services(session, now: datetime) -> list[ClientService]:
    # Mark services disabled when local DB confirms expiry or volume exhaustion.
    # MikroTik usage is refreshed by sync_mikrotik_usage every 5 minutes; X-UI rows
    # are updated whenever users/admins open service details or renew.
    candidates = (await session.execute(
        select(ClientService)
        .where(ClientService.is_active == True)
        .where(or_(ClientService.disabled_at.is_(None), ClientService.disabled_at == None))
        .where(or_(
            and_(ClientService.expires_at != None, ClientService.expires_at <= now),
            and_(ClientService.total_bytes > 0, ClientService.used_bytes >= ClientService.total_bytes),
        ))
        .order_by(ClientService.id.asc())
        .limit(200)
    )).scalars().all()
    marked: list[ClientService] = []
    for svc in candidates:
        reason = _disable_reason(svc, now)
        if not reason:
            continue
        svc.is_active = False
        svc.disabled_at = now
        svc.disabled_reason = reason
        svc.disabled_notify_count = 0
        svc.disabled_last_notified_at = None
        marked.append(svc)
    if marked:
        await session.flush()
    return marked


async def _process_disabled_services(bot, session, now: datetime) -> None:
    disabled = (await session.execute(
        select(ClientService)
        .where(ClientService.is_active == False)
        .where(ClientService.disabled_at != None)
        .where(or_(ClientService.client_username.is_(None), ~ClientService.client_username.like('deleted_%')))
        .order_by(ClientService.disabled_at.asc(), ClientService.id.asc())
        .limit(300)
    )).scalars().all()

    for svc in disabled:
        disabled_at = svc.disabled_at or now
        age = now - disabled_at
        is_test_service = await _is_test_service(session, svc)

        if is_test_service:
            # Test accounts must never receive disabled/expiry reminders.
            # Once their expiry time is 6+ hours in the past, remove them from
            # both the bot database and the upstream panel. Use expires_at as the
            # countdown base so old expired test accounts are cleaned on the
            # first scan after this version is installed.
            expired_at = svc.expires_at if svc.expires_at and svc.expires_at <= now else None
            if expired_at and (now - expired_at) >= TEST_EXPIRED_PURGE_AFTER:
                await _purge_disabled_service(bot, session, svc, now)
                await session.flush()
            continue

        if age >= DISABLED_PURGE_AFTER:
            await _purge_disabled_service(bot, session, svc, now)
            await session.flush()
            continue

        last = getattr(svc, 'disabled_last_notified_at', None)
        should_notify = age <= DISABLED_NOTIFY_WINDOW and (last is None or (now - last) >= DISABLED_NOTIFY_INTERVAL)
        if should_notify:
            await _notify_disabled_service(bot, session, svc, now)
            await session.flush()


async def _send_regular_pre_expiry_alerts(bot, session, now: datetime) -> None:
    soon_24h = now + timedelta(hours=24)
    q = (
        select(ClientService)
        .where(ClientService.is_active == True)
        .where(or_(ClientService.disabled_at.is_(None), ClientService.disabled_at == None))
        .where(or_(
            and_(ClientService.total_bytes > 0, (ClientService.total_bytes - ClientService.used_bytes) <= GB, ClientService.notify_1gb_sent == False),
            and_(ClientService.total_bytes > 0, (ClientService.total_bytes - ClientService.used_bytes) <= 100 * MB, ClientService.notify_100mb_sent == False),
            and_(ClientService.expires_at != None, ClientService.expires_at <= soon_24h, ClientService.expires_at > now),
        ))
        .order_by(ClientService.id.asc())
        .limit(100)
    )
    services = (await session.execute(q)).scalars().all()
    for svc in services:
        if await _is_test_service(session, svc):
            continue
        user = await session.get(User, svc.user_id)
        if not user:
            continue
        remain = max((svc.total_bytes or 0) - (svc.used_bytes or 0), 0)
        kb = _renew_keyboard(svc)
        try:
            if svc.total_bytes and remain <= GB and not getattr(svc, 'notify_1gb_sent', False):
                await bot.send_message(user.telegram_id, f'⚠️ اشتراک شما با یوزرنیم {svc.client_username} کمتر از 1 گیگ حجم دارد.', reply_markup=kb)
                setattr(svc, 'notify_1gb_sent', True)
            if svc.total_bytes and remain <= 100 * MB and not getattr(svc, 'notify_100mb_sent', False):
                await bot.send_message(user.telegram_id, f'⚠️ حجم اشتراک شما با یوزرنیم {svc.client_username} کمتر از 100 مگابایت مانده است.', reply_markup=kb)
                setattr(svc, 'notify_100mb_sent', True)
            if svc.expires_at:
                delta = svc.expires_at - now
                checks = [
                    ('notify_24h_sent', timedelta(hours=24), 'کمتر از 24 ساعت'),
                    ('notify_2h_sent', timedelta(hours=2), 'کمتر از 2 ساعت'),
                    ('notify_20m_sent', timedelta(minutes=20), 'کمتر از 20 دقیقه'),
                ]
                for attr, limit, label in checks:
                    if delta <= limit and delta.total_seconds() > 0 and not getattr(svc, attr, False):
                        await bot.send_message(user.telegram_id, f'⏰ از زمان سرویس {svc.client_username} {label} باقی مانده است.', reply_markup=kb)
                        setattr(svc, attr, True)
        except Exception as exc:
            logger.warning('Regular service alert failed service_id=%s: %s', svc.id, exc)


async def scan_service_alerts(bot):
    now = datetime.utcnow()
    async with SessionLocal() as session:
        await _refresh_active_xui_usage(session, now)
        await _send_regular_pre_expiry_alerts(bot, session, now)
        await _mark_newly_disabled_services(session, now)
        await _backfill_disabled_tracking(session, now)
        await _process_disabled_services(bot, session, now)
        await session.commit()
