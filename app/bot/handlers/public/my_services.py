from datetime import datetime, timedelta
import asyncio, contextlib
import tempfile, qrcode
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile
from sqlalchemy import select, update
from app.database.session import SessionLocal
from app.core.config import settings
from app.database.models import User, ClientService, Plan, Server, Order, PaymentCard, TestAccountUsage, OpenVPNProfile
from app.bot.keyboards.common import CB_MY_SERVICES, back_button, back_main_inline
from app.services.xui_service import XuiService
from app.services.mikrotik_service import MikroTikService
from app.services.reseller_service import apply_reseller_usage_delta, release_reserved_volume, drop_inactive_reservation
from app.bot.profile_delivery import send_openvpn_profile_document
from app.bot.renewal_delivery import renewal_confirmation_text, renewal_keyboard
from app.bot.states.public_states import BuyFlow, RenewDiscountInput
from app.services.discount_service import apply_discount_amount, mark_discount_used, order_discount_usage_source, release_order_discount_usage
from app.bot.utils import edit_or_answer, ui_message
from app.bot.error_reporting import handle_user_facing_error
from app.services.plan_order import saved_plan_order, sort_by_saved_order
from app.services.service_grace import (
    grace_deadline,
    local_terminal_reason,
    mark_service_active,
    mark_service_disabled,
    visible_in_my_services,
)
from app.utils.jalali import fa_date

router = Router()
_AUTO_REFRESH_TASKS = {}

def cancel_auto_refresh(chat_id: int = None, message_id: int = None):
    for key, task in list(_AUTO_REFRESH_TASKS.items()):
        k_chat, k_msg, _ = key
        if (chat_id is None or k_chat == chat_id) and (message_id is None or k_msg == message_id):
            if task and not task.done():
                task.cancel()
            _AUTO_REFRESH_TASKS.pop(key, None)

def gb(b): return b/1024**3 if b else 0

def format_gb(bytes_val: int | None, *, unlimited_when_zero: bool = False) -> str:
    value = int(bytes_val or 0)
    if unlimited_when_zero and value <= 0:
        return 'نامحدود'
    return f'{gb(value):.2f} گیگ'

def remote_value(remote: dict | None, *keys: str):
    if not isinstance(remote, dict):
        return None
    for key in keys:
        if key in remote and remote.get(key) not in (None, ''):
            return remote.get(key)
    return None

def int_or_zero(value) -> int:
    try:
        return max(int(float(value or 0)), 0)
    except Exception:
        return 0

def remote_used_bytes(remote: dict | None) -> int:
    direct = remote_value(
        remote,
        'used_bytes', 'bytes_used', 'used', 'usage_bytes', 'traffic_used_bytes',
        'used_traffic_bytes', 'total_used_bytes', 'consumed_bytes'
    )
    if direct is not None:
        return int_or_zero(direct)
    up = int_or_zero(remote_value(remote, 'up', 'upload', 'upload_bytes', 'tx', 'tx_bytes'))
    down = int_or_zero(remote_value(remote, 'down', 'download', 'download_bytes', 'rx', 'rx_bytes'))
    return up + down

def remote_total_bytes(remote: dict | None, fallback: int = 0) -> int:
    direct = remote_value(
        remote,
        'volume_bytes', 'total_bytes', 'total', 'limit_bytes', 'data_limit_bytes',
        'quota_bytes', 'transfer_enable', 'totalGB'
    )
    value = int_or_zero(direct)
    return value or int(fallback or 0)

def remote_remaining_bytes(remote: dict | None, total: int, used: int) -> int | None:
    direct = remote_value(
        remote,
        'remaining_bytes', 'remain_bytes', 'bytes_remaining', 'left_bytes',
        'unused_bytes', 'available_bytes', 'remaining'
    )
    if direct is not None:
        return int_or_zero(direct)
    if total and total > 0:
        return max(total - used, 0)
    return None

def expire_from_remote(remote: dict | None):
    return remote_value(remote, 'expire_at', 'expires_at', 'expiry', 'expiration', 'valid_until')

def active_from_remote(remote: dict | None, fallback: bool = True) -> bool:
    return MikroTikService().user_is_active(remote, fallback)


async def _owned_public_service(session, svc: ClientService | None, telegram_id: int):
    """Return (is_owner, user) for service actions from the normal My Configs menu.

    Callback data can be forged manually, so every action that receives a
    service_id must verify that the service belongs to the Telegram user and
    is not a reseller-created customer config.
    """
    if not svc:
        return False, None
    user = (await session.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one_or_none()
    if not user:
        return False, None
    return bool(svc.user_id == user.id and svc.reseller_id is None), user


async def _deny_not_owned(callback: CallbackQuery):
    await callback.answer('این سرویس برای شما نیست یا از قبل حذف شده است.', show_alert=True)


def install_text(sub_link: str) -> str:
    return (f"📲 نحوه اتصال:\n<code>{sub_link}</code>\n\n"
            "<b>⚠️ فقط و فقط برنامه Happ مورد تایید ما هستش.</b>\n"
            "<b>اگر از برنامه دیگری استفاده می‌کنید، هرچه زودتر Happ را از App Store یا Google Play دانلود و نصب کنید.</b>\n\n"
            "<b>در غیر این صورت، وصل نشدن سرورها مسئولیتش با خود شماست و در پشتیبانی خدماتی ارائه نمی‌شود.</b>\n\n"
            "✅ مراحل اضافه کردن در Happ:\n"
            "1) برنامه Happ را باز کنید.\n"
            "2) روی دکمه + بزنید.\n"
            "3) گزینه Import / Subscription را انتخاب کنید.\n"
            "4) لینک بالا را Paste و ذخیره کنید.\n\n"
            "♻️ بروزرسانی لینک هر ۱۲ ساعت در Happ:\n"
            "1) وارد Happ شوید.\n"
            "2) Subscription همین سرویس را باز کنید.\n"
            "3) Update / Refresh Subscription را بزنید.")

def percent_bar(used: int, total: int, width: int = 10) -> str:
    if not total or total <= 0:
        return '▰' * width
    ratio = max(0, min(1, (used or 0) / total))
    filled = int(round(ratio * width))
    return '▰' * filled + '▱' * (width - filled)


def service_building_text(username: str, plan_title: str, volume_gb, duration_days, *, action: str = 'تمدید') -> str:
    return (
        '⏳ سرویس شما در حال تمدید است. لطفاً منتظر بمانید.\n\n'
        f'👤 نام سرویس: {username or "-"}\n'
        f'📦 پلن: {plan_title or "-"}\n'
        f'💾 حجم: {volume_gb:g} گیگ\n'
        f'⏳ مدت: {duration_days} روز\n'
        f'🔄 وضعیت: در حال {action}...'
    )


async def send_building_notice(callback: CallbackQuery, text: str) -> None:
    try:
        await callback.message.bot.send_message(callback.from_user.id, text)
    except Exception:
        pass


def server_service_badge(server) -> tuple[str, str]:
    meta = getattr(server, 'meta', None) or {}
    server_type = (getattr(server, 'server_type', '') or '').lower()
    protocol = str(meta.get('default_protocol') or '').lower()
    if server_type == 'mikrotik' or protocol in ('openvpn', 'ovpn', 'l2tp', 'mikrotik'):
        default_emoji, default_label = '🟠', 'MikroTik / OpenVPN'
    else:
        default_emoji, default_label = '🔵', 'V2Ray'
    emoji = str(meta.get('badge_emoji') or default_emoji).strip() or default_emoji
    label = str(meta.get('badge_label') or default_label).strip() or default_label
    return emoji, label


async def delete_local_service_records(session, svc):
    """Soft-delete a local service and keep its panel identifiers as a tombstone.

    Keeping a small inactive tombstone lets the bot safely purge only this
    exact deleted client from 3x-ui inbound.settings before future creates.
    We never delete unknown/manual/offline panel users.
    """
    if not svc:
        return
    await session.execute(update(Order).where(Order.service_id == svc.id).values(service_id=None))
    await session.execute(update(TestAccountUsage).where(TestAccountUsage.service_id == svc.id).values(service_id=None))
    if getattr(svc, 'reseller_id', None):
        await release_reserved_volume(session, svc)
    svc.is_active = False
    old_name = (svc.client_username or svc.xui_email or 'client')
    tombstone_name = f'deleted_{svc.id}_{old_name}'
    svc.client_username = tombstone_name[:150]

async def sync_service_from_panel(session, svc, *, delete_missing: bool = False) -> bool | None:
    """Sync local service with 3x-ui.

    Returns:
        True  -> client exists on panel and local data was refreshed
        False -> panel answered successfully but the client does not exist there
        None  -> panel/server was unavailable, so no decision should be made
    """
    server = await session.get(Server, svc.server_id) if svc else None
    if not svc or not server:
        return None
    if server.server_type == 'mikrotik':
        try:
            found = await MikroTikService().get_user(server, svc.xui_email or svc.client_username)
            if not found:
                if delete_missing:
                    await delete_local_service_records(session, svc)
                    await session.commit()
                else:
                    mark_service_disabled(svc, reason='missing_on_panel')
                    if getattr(svc, 'reseller_id', None):
                        await drop_inactive_reservation(session, svc)
                    await session.commit()
                return False
            used = remote_used_bytes(found)
            total = remote_total_bytes(found, svc.total_bytes or 0)
            remaining = remote_remaining_bytes(found, total, used)
            # Some custom panels return only remaining volume. Keep local total when possible
            # and derive used volume so the user always sees both consumption and remaining.
            if total and remaining is not None and used <= 0:
                used = max(total - remaining, 0)
            await apply_reseller_usage_delta(session, svc, used)
            svc.total_bytes = total or (svc.total_bytes or 0)
            terminal_reason = local_terminal_reason(svc)
            panel_active = active_from_remote(found, svc.is_active) and terminal_reason is None
            if panel_active:
                mark_service_active(svc)
            else:
                mark_service_disabled(
                    svc,
                    reason=terminal_reason or 'disabled_on_mikrotik_panel',
                )
            if not svc.is_active and getattr(svc, 'reseller_id', None):
                await drop_inactive_reservation(session, svc)
            exp = expire_from_remote(found)
            if exp:
                try: svc.expires_at = datetime.fromisoformat(str(exp)[:10])
                except Exception: pass
            await session.commit()
            return True
        except Exception:
            return None
    if server.server_type != 'xui':
        return None
    try:
        found = await XuiService().find_client_any(server, svc.xui_email)
        if not found:
            if delete_missing:
                await delete_local_service_records(session, svc)
                await session.commit()
            else:
                mark_service_disabled(svc, reason='missing_on_panel')
                await session.commit()
            return False
        c = found.get('client') or {}
        tr = found.get('traffic') or {}
        used = (tr.get('up', 0) or 0) + (tr.get('down', 0) or 0)
        total = tr.get('total') or c.get('totalGB') or svc.total_bytes
        await apply_reseller_usage_delta(session, svc, used)
        svc.total_bytes = total or svc.total_bytes
        terminal_reason = local_terminal_reason(svc)
        panel_active = bool(c.get('enable', svc.is_active)) and terminal_reason is None
        if panel_active:
            mark_service_active(svc)
        else:
            mark_service_disabled(
                svc,
                reason=terminal_reason or 'disabled_on_panel',
            )
        if not panel_active and getattr(svc, 'reseller_id', None):
            await drop_inactive_reservation(session, svc)
        subid = c.get('subId') or svc.xui_email
        svc.sub_link = XuiService().build_subscription_link(server, subid, svc.xui_email)
        await session.commit()
        return True
    except Exception:
        # Do not delete anything when the panel is temporarily unavailable.
        return None

def detail_kb(svc, plan, server_type: str = 'xui'):
    used = int(svc.used_bytes or 0)
    total = int(svc.total_bytes or 0)
    remain = max(total - used, 0) if total else 0
    pct = int((used / total) * 100) if total else 0
    is_mikrotik = (server_type or '').lower() == 'mikrotik'
    rows = [
        [InlineKeyboardButton(text=f'{plan.title if plan else "نامشخص"}', callback_data='noop'), InlineKeyboardButton(text='🚀 نام پلن', callback_data='noop')],
        [InlineKeyboardButton(text=f'{fa_date(svc.created_at)}', callback_data='noop'), InlineKeyboardButton(text='⏰ تاریخ خرید', callback_data='noop')],
        [InlineKeyboardButton(text=f'{fa_date(svc.expires_at)}', callback_data='noop'), InlineKeyboardButton(text='⏰ تاریخ انقضا', callback_data='noop')],
        [InlineKeyboardButton(text=format_gb(total, unlimited_when_zero=True), callback_data='noop'), InlineKeyboardButton(text='💾 حجم کل', callback_data='noop')],
        [InlineKeyboardButton(text=format_gb(used), callback_data='noop'), InlineKeyboardButton(text='📈 مصرف‌شده', callback_data='noop')],
        [InlineKeyboardButton(text='نامحدود' if not total else format_gb(remain), callback_data='noop'), InlineKeyboardButton(text='⏳ حجم باقیمانده', callback_data='noop')],
        [InlineKeyboardButton(text=f'{pct}٪', callback_data='noop'), InlineKeyboardButton(text='📊 درصد مصرف', callback_data='noop')],
    ]
    if is_mikrotik:
        toggle_text = '⛔ غیرفعال کردن سرویس' if svc.is_active else '✅ فعال کردن سرویس'
        toggle_value = '0' if svc.is_active else '1'
        rows.append([InlineKeyboardButton(text=toggle_text, callback_data=f'svc:toggle:{svc.id}:{toggle_value}')])
        rows.append([InlineKeyboardButton(text='♻️ بروزرسانی کانفیگ', callback_data=f'svc:refresh:{svc.id}')])
    else:
        rows.append([
            InlineKeyboardButton(text='♻️ بروزرسانی کانفیگ', callback_data=f'svc:refresh:{svc.id}'),
            InlineKeyboardButton(text='🔄 باطل کردن و ارسال جدید', callback_data=f'svc:revoke:{svc.id}')
        ])
    if is_mikrotik:
        rows.append([InlineKeyboardButton(text='📥 دریافت پروفایل سرور', callback_data=f'svc:profile:{svc.id}')])
    rows += [
        [InlineKeyboardButton(text='🔁 انتخاب تعرفه جدید', callback_data=f'svc:renew_menu:{svc.id}'), InlineKeyboardButton(text='🗑 حذف کانفیگ', callback_data=f'svc:delete:{svc.id}')],
        [back_button('menu:my_services')]
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)

def service_detail_text(svc, plan, server_type: str = 'xui', server=None) -> str:
    used = svc.used_bytes or 0
    total = svc.total_bytes or 0
    remain = max(total - used, 0)
    pct = int((used / total) * 100) if total else 0
    status_icon = '🟢' if svc.is_active else '🔴'
    status_text = 'فعال' if svc.is_active else 'غیرفعال'
    plan_title = plan.title if plan else 'نامشخص'
    username = svc.client_username or svc.xui_email or 'ثبت نشده'
    created = fa_date(svc.created_at)
    expires = fa_date(svc.expires_at)
    badge_emoji, badge_label = server_service_badge(server)

    lines = [
        '📌 مشخصات کانفیگ',
        '━━━━━━━━━━━━━━',
        f'{badge_emoji} نوع سرویس: {badge_label}',
        f'🚀 نام کانفیگ: {username}',
        f'{status_icon} وضعیت: {status_text}',
        f'📦 پلن: {plan_title}',
        '',
        '⏰ زمان‌بندی',
        f'├ تاریخ خرید: {created}',
        f'╰ تاریخ انقضا: {expires}',
        '',
        '📊 مصرف سرویس',
        f'├ حجم کل: {format_gb(total, unlimited_when_zero=True)}',
        f'├ مصرف‌شده: {format_gb(used)}',
        f'├ باقی‌مانده: {"نامحدود" if not total else format_gb(remain)}',
        f'╰ {percent_bar(used, total, 12)} {pct}%',
        '',
    ]

    if not svc.is_active:
        deadline = grace_deadline(svc)
        if deadline is not None and datetime.utcnow() < deadline:
            seconds_left = max(int((deadline - datetime.utcnow()).total_seconds()), 0)
            hours_left = max((seconds_left + 3599) // 3600, 1)
            lines += [
                '⏳ مهلت تمدید',
                f'این کانفیگ تا حدود {hours_left} ساعت دیگر در «کانفیگ‌های من» باقی می‌ماند و قابل تمدید است.',
                '',
            ]

    if (server_type or '').lower() == 'mikrotik':
        password = svc.xui_uuid or 'ثبت نشده'
        meta = getattr(server, 'meta', None) or {}
        l2tp_server = str(meta.get('l2tp_server') or 'vpn.example.com').strip() or 'vpn.example.com'
        private_key = str(meta.get('l2tp_ipsec_secret') or 'CHANGE_ME_IPSEC_SECRET').strip() or 'CHANGE_ME_IPSEC_SECRET'
        lines += [
            '🔐 اطلاعات ورود',
            f'├ Username: {username}',
            f'├ Password: {password}',
            f'├ server : {l2tp_server}',
            f'╰ private key : {private_key}',
        ]
    else:
        link = svc.sub_link or 'ثبت نشده'
        lines += [
            '🔗 لینک اتصال',
            link,
        ]

    return '\n'.join(lines).strip()


def is_plain_service_callback(data: str | None) -> bool:
    if not data or not data.startswith('svc:'):
        return False
    parts = data.split(':')
    return len(parts) == 2 and parts[1].isdigit()

async def render_detail(callback: CallbackQuery, sid: int) -> bool:
    async with SessionLocal() as session:
        svc = await session.get(ClientService, sid)
        ok_owner, _user = await _owned_public_service(session, svc, callback.from_user.id)
        if not ok_owner:
            if svc and getattr(svc, 'reseller_id', None):
                # Reseller-created customer configs must not be opened from the normal
                # "My configs" page. They belong to the reseller users section.
                await edit_or_answer(
                    callback,
                    'این کانفیگ مربوط به بخش نمایندگی است.\nاز مسیر «منو نمایندگی → یوزرها» مدیریت کنید.',
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('menu:reseller')], [back_button('menu:my_services')]])
                )
                return False
            await _deny_not_owned(callback)
            return False
        sync_result = await sync_service_from_panel(session, svc, delete_missing=False)
        if sync_result is False and not visible_in_my_services(svc):
            await edit_or_answer(callback, '⚠️ مهلت ۷۲ ساعته تمدید این کانفیگ تمام شده است.', reply_markup=back_main_inline())
            return False
        plan = await session.get(Plan, svc.plan_id) if svc.plan_id else None
        server = await session.get(Server, svc.server_id)
        server_type = server.server_type if server else 'xui'
    await edit_or_answer(callback, service_detail_text(svc, plan, server_type, server), reply_markup=detail_kb(svc, plan, server_type))
    return True

async def auto_refresh_service_page(bot, chat_id: int, message_id: int, sid: int):
    key=(chat_id, message_id, sid)
    old=_AUTO_REFRESH_TASKS.get(key)
    if old and not old.done():
        old.cancel()
    _AUTO_REFRESH_TASKS[key]=asyncio.current_task()
    try:
        for _ in range(20):
            await asyncio.sleep(3)
            async with SessionLocal() as session:
                svc = await session.get(ClientService, sid)
                if not svc:
                    return
                sync_result = await sync_service_from_panel(session, svc, delete_missing=False)
                if sync_result is False and not visible_in_my_services(svc):
                    text = '⚠️ مهلت ۷۲ ساعته تمدید این کانفیگ تمام شده است.'
                    kb = back_main_inline()
                    with contextlib.suppress(Exception):
                        await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=kb)
                    return
                plan = await session.get(Plan, svc.plan_id) if svc.plan_id else None
                server = await session.get(Server, svc.server_id)
                server_type = server.server_type if server else 'xui'
                text = service_detail_text(svc, plan, server_type, server)
                kb = detail_kb(svc, plan, server_type)
            with contextlib.suppress(Exception):
                await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=kb)
    finally:
        _AUTO_REFRESH_TASKS.pop(key, None)

@router.callback_query(F.data == CB_MY_SERVICES)
async def my_services(event):
    # Opening the services list must cancel any previously running detail refresh.
    if getattr(event, 'message', None):
        cancel_auto_refresh(event.message.chat.id, None)
    async with SessionLocal() as session:
        user = (await session.execute(select(User).where(User.telegram_id == event.from_user.id))).scalar_one()
        # Fetch every owned non-tombstone record first. Filtering by is_active in
        # SQL used to hide quota-finished services whose disabled_at had not yet
        # been backfilled. Normalize the lifecycle first, then apply the exact
        # 72-hour visibility rule.
        services = (await session.execute(
            select(ClientService)
            .where(ClientService.user_id == user.id)
            .where(ClientService.reseller_id.is_(None))
            .where((ClientService.client_username.is_(None)) | (~ClientService.client_username.like('deleted_%')))
            .order_by(ClientService.id.desc())
        )).scalars().all()
        now = datetime.utcnow()
        for service in list(services):
            if not service.is_active and service.disabled_at is None:
                mark_service_disabled(
                    service,
                    now,
                    reason=local_terminal_reason(service, now) or service.disabled_reason or 'disabled_on_panel',
                )
            # OpenVPN/MikroTik users must see manual panel changes immediately.
            # Sync only this user's MikroTik services; XUI stays detail-on-demand.
            server = await session.get(Server, service.server_id) if service.server_id else None
            if server and (server.server_type or '').lower() == 'mikrotik':
                await sync_service_from_panel(session, service, delete_missing=False)
        services = [service for service in services if visible_in_my_services(service, now)]
        await session.commit()
    if not services:
        await edit_or_answer(event, '📭 شما هنوز هیچ کانفیگی خریداری نکرده‌اید.', reply_markup=back_main_inline()); await event.answer(); return
    server_ids = [s.server_id for s in services if s.server_id]
    async with SessionLocal() as session:
        servers = {x.id: x for x in (await session.execute(select(Server).where(Server.id.in_(server_ids)))).scalars().all()} if server_ids else {}
    rows = []
    for s in services:
        server = servers.get(s.server_id)
        badge_emoji, badge_label = server_service_badge(server)
        title = s.client_username or s.xui_email or f'#{s.id}'
        status_icon = '🟢' if s.is_active else '🔴'
        rows.append([InlineKeyboardButton(text=f'{status_icon} {badge_emoji} {title} — {badge_label}', callback_data=f'svc:{s.id}')])
    kb = InlineKeyboardMarkup(inline_keyboard=rows + [[InlineKeyboardButton(text='🔙 بازگشت', callback_data='back:main')]])
    await edit_or_answer(event, '📱 کانفیگ‌های من\n\nیکی از سرویس‌ها را انتخاب کنید:', reply_markup=kb); await event.answer()

@router.callback_query(lambda c: is_plain_service_callback(c.data))
async def service_detail(callback: CallbackQuery):
    sid = int(callback.data.split(':')[1])
    if callback.message:
        cancel_auto_refresh(callback.message.chat.id, None)
    ok = await render_detail(callback, sid)
    # Manual refresh button is enough here; do not poll the panel every 3 seconds.
    if ok:
        await callback.answer()

@router.callback_query(F.data.startswith('svc:toggle:'))
async def toggle_openvpn_service(callback: CallbackQuery):
    parts = (callback.data or '').split(':')
    if len(parts) != 4 or not parts[2].isdigit() or parts[3] not in {'0', '1'}:
        await callback.answer('درخواست نامعتبر است.', show_alert=True)
        return
    sid = int(parts[2])
    desired_enabled = parts[3] == '1'
    async with SessionLocal() as session:
        svc = await session.get(ClientService, sid)
        ok_owner, _user = await _owned_public_service(session, svc, callback.from_user.id)
        server = await session.get(Server, svc.server_id) if svc else None
        if not ok_owner or not server:
            await _deny_not_owned(callback)
            return
        if (server.server_type or '').lower() != 'mikrotik':
            await callback.answer('این دکمه فقط برای سرویس OpenVPN فعال است.', show_alert=True)
            return
        username = svc.xui_email or svc.client_username
        try:
            await MikroTikService().set_enabled(server, username, desired_enabled)
            remote = await MikroTikService().get_user(server, username)
            actual_enabled = MikroTikService().user_is_active(remote, desired_enabled)
            svc.is_active = actual_enabled
            if actual_enabled:
                svc.disabled_at = None
                svc.disabled_reason = None
                svc.disabled_notify_count = 0
                svc.disabled_last_notified_at = None
            else:
                svc.disabled_at = svc.disabled_at or datetime.utcnow()
                svc.disabled_reason = 'disabled_by_user'
            await session.commit()
        except Exception as exc:
            await session.rollback()
            await handle_user_facing_error(
                callback,
                exc,
                context='User OpenVPN enable/disable failed',
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(f'svc:{sid}')]]),
            )
            return
    await render_detail(callback, sid)
    if actual_enabled == desired_enabled:
        await callback.answer('✅ سرویس فعال شد' if actual_enabled else '⛔ سرویس غیرفعال شد')
    else:
        await callback.answer('وضعیت پنل تغییر نکرد؛ احتمالاً سرویس منقضی یا محدود شده است.', show_alert=True)


@router.callback_query(F.data.startswith('svc:revoke:'))
async def revoke_service(callback: CallbackQuery):
    if callback.message:
        cancel_auto_refresh(callback.message.chat.id, callback.message.message_id)
    sid=int(callback.data.split(':')[-1])
    detail_text = None
    detail_markup = None
    async with SessionLocal() as session:
        svc=await session.get(ClientService,sid); server=await session.get(Server,svc.server_id) if svc else None
        ok_owner, _user = await _owned_public_service(session, svc, callback.from_user.id)
        if not ok_owner or not server:
            await _deny_not_owned(callback); return
        server_type = server.server_type
        new_password = None
        try:
            if server.server_type == 'mikrotik':
                new=await MikroTikService().rotate_password(server, svc.xui_email or svc.client_username)
                new_password=str(new.get('password') or '')
                svc.xui_uuid=new_password or svc.xui_uuid or ''
                svc.sub_link=None
            else:
                new=await XuiService().revoke_and_new_link(server, svc.xui_email)
                svc.xui_uuid=(str(new.get('uuid')) if isinstance(new, dict) and new.get('uuid') is not None else None)
                svc.sub_link=new.get('sub_link')
            await session.commit()
            await session.refresh(svc)
            sub=svc.sub_link
            plan = await session.get(Plan, svc.plan_id) if svc.plan_id else None
            detail_text = service_detail_text(svc, plan, server_type, server)
            detail_markup = detail_kb(svc, plan, server_type)
        except Exception as e:
            await handle_user_facing_error(callback, e, context='User revoke/regenerate service link failed', reply_markup=back_main_inline()); await callback.answer(); return
    # First send the renewed config card. Then send a second message that opens
    # the same service detail page from "My configs" for the revoked service.
    if server_type == 'mikrotik' and callback.message:
        # MikroTik has no subscription link; deliver the new PPP password directly.
        await callback.message.answer(
            '✅ رمز جدید با موفقیت ساخته شد.\n\n'
            f'👤 نام کاربری: <code>{svc.client_username}</code>\n'
            f'🔑 رمز عبور جدید: <code>{new_password}</code>\n\n'
            'با رمز قبلی دیگر نمی‌توانید متصل شوید؛ از رمز جدید استفاده کنید.',
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text='🏠 خانه', callback_data='home:main')]
            ]),
            parse_mode='HTML',
        )
        if detail_text and detail_markup:
            detail_msg = await callback.message.answer(detail_text, reply_markup=detail_markup)
            # Manual refresh button is enough here; avoid panel polling after revoke.
    elif sub and callback.message:
        img = qrcode.make(sub)
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
        img.save(tmp.name)
        await callback.message.answer_photo(
            FSInputFile(tmp.name),
            caption='✅ لینک جدید با موفقیت ساخته شد.\n\n' + install_text(sub),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text='🏠 خانه', callback_data='home:main')]
            ]),
            parse_mode='HTML',
        )
        if detail_text and detail_markup:
            detail_msg = await callback.message.answer(detail_text, reply_markup=detail_markup)
            # Manual refresh button is enough here; avoid panel polling after revoke.

    await callback.answer('✅ انجام شد')

@router.callback_query(F.data.startswith('svc:refresh:'))
async def refresh_service(callback: CallbackQuery):
    sid=int(callback.data.split(':')[-1])
    ok = await render_detail(callback, sid)
    if ok:
        await callback.answer('✅ بروزرسانی شد')


@router.callback_query(F.data.startswith('svc:renew_menu:'))
async def renew_menu(callback: CallbackQuery):
    if callback.message:
        cancel_auto_refresh(callback.message.chat.id, callback.message.message_id)
    sid = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        svc = await session.get(ClientService, sid)
        ok_owner, _user = await _owned_public_service(session, svc, callback.from_user.id)
        if not ok_owner:
            await _deny_not_owned(callback)
            return
        current_plan = await session.get(Plan, svc.plan_id) if svc.plan_id else None
        plans = (await session.execute(
            select(Plan).where(Plan.server_id == svc.server_id, Plan.is_active == True)
        )).scalars().all()
        plans = sort_by_saved_order(plans, await saved_plan_order(session, 'public'))
    is_admin = callback.from_user.id in settings.admin_ids
    rows = []
    for p in plans:
        marker = '✅ ' if current_plan and p.id == current_plan.id else '🔁 '
        price_label = 'رایگان برای مدیر' if is_admin else f'{p.price_irt:,} تومان'
        rows.append([InlineKeyboardButton(text=f'{marker}{p.title} | {price_label}', callback_data=f'svc:renew_plan:{sid}:{p.id}')])
    rows.append([back_button(f'svc:{sid}')])
    renew_note = 'برای مدیر، تمدید بلافاصله و رایگان انجام می‌شود.' if is_admin else 'بعد از انتخاب تعرفه، روش پرداخت نمایش داده می‌شود و تمدید فقط بعد از پرداخت موفق یا تایید رسید انجام خواهد شد.'
    await edit_or_answer(
        callback,
        '🔁 تمدید / تغییر تعرفه سرویس\n\n'
        'اول تعرفه موردنظر را انتخاب کنید.\n'
        f'{renew_note}',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()




@router.callback_query(F.data.startswith('svc:renew_card:') | F.data.startswith('svc:renew_wallet:') | F.data.startswith('svc:renew_same:'))
async def legacy_renew_buttons(callback: CallbackQuery):
    # Old inline keyboards used to renew immediately or jump directly to a payment method.
    # Keep them safe by redirecting to the new tariff-first renewal flow.
    await renew_menu(callback)


def renew_payment_methods_keyboard(sid: int, pid: int, discount_code: str | None = None) -> InlineKeyboardMarkup:
    discount_text = '🏷 تغییر کد تخفیف' if discount_code else '🏷 اعمال کد تخفیف'
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=discount_text, callback_data=f'svc:renew_discount:{sid}:{pid}')],
        [InlineKeyboardButton(text='💎 پرداخت با کیف پول', callback_data=f'svc:renew_pay:{sid}:{pid}:wallet')],
        [InlineKeyboardButton(text='💳 کارت به کارت و ارسال رسید', callback_data=f'svc:renew_pay:{sid}:{pid}:card')],
        [back_button(f'svc:renew_menu:{sid}')],
    ])


def _renew_checkout_matches(data: dict, sid: int, pid: int) -> bool:
    try:
        return int(data.get('renewal_service_id') or 0) == sid and int(data.get('renewal_plan_id') or 0) == pid
    except (TypeError, ValueError):
        return False


def renewal_checkout_text(
    svc: ClientService,
    plan: Plan,
    current_plan: Plan | None,
    *,
    is_admin: bool,
    discount_code: str | None = None,
    final_amount: int | None = None,
    prefix: str = '',
) -> str:
    base_amount = int(plan.price_irt or 0)
    text = (
        f'{prefix}'
        '🔁 تمدید سرویس\n\n'
        f'👤 کانفیگ: {svc.client_username or svc.xui_email}\n'
        f'📦 تعرفه انتخابی: {plan.title}\n'
        f'💾 حجم: {plan.volume_gb} گیگ\n'
        f'⏳ مدت: {plan.duration_days} روز\n'
    )
    if is_admin:
        text += '💰 مبلغ: رایگان برای مدیر\n'
    elif discount_code:
        payable = max(int(final_amount if final_amount is not None else base_amount), 0)
        text += (
            f'💰 مبلغ اصلی: {base_amount:,} تومان\n'
            f'🏷 کد تخفیف: {discount_code}\n'
            f'💵 مبلغ نهایی: {payable:,} تومان\n'
        )
    else:
        text += f'💰 مبلغ: {base_amount:,} تومان\n'
    if current_plan:
        text += f'\nتعرفه فعلی شما: {current_plan.title}\n'
    if not is_admin:
        text += '\nاگر کد تخفیف دارید، قبل از پرداخت آن را اعمال کنید.'
    text += '\nتمدید فقط بعد از پرداخت موفق یا تأیید رسید انجام می‌شود.'
    return text


async def show_renew_payment_methods(
    callback: CallbackQuery,
    sid: int,
    pid: int,
    state: FSMContext | None = None,
    *,
    prefix: str = '',
    reset_discount: bool = False,
) -> bool:
    async with SessionLocal() as session:
        svc = await session.get(ClientService, sid)
        ok_owner, _user = await _owned_public_service(session, svc, callback.from_user.id)
        plan = await session.get(Plan, pid)
        server = await session.get(Server, svc.server_id) if svc else None
        if not ok_owner or not svc or not plan or not server or plan.server_id != svc.server_id:
            await _deny_not_owned(callback)
            return False
        current_plan = await session.get(Plan, svc.plan_id) if svc.plan_id else None

    discount_code = None
    final_amount = int(plan.price_irt or 0)
    if state is not None:
        data = await state.get_data()
        if reset_discount or not _renew_checkout_matches(data, sid, pid):
            await state.update_data(
                renewal_service_id=sid,
                renewal_plan_id=pid,
                renew_discount_code=None,
                renew_final_amount=final_amount,
                order_id=None,
            )
        else:
            discount_code = data.get('renew_discount_code')
            try:
                final_amount = int(data.get('renew_final_amount')) if data.get('renew_final_amount') is not None else final_amount
            except (TypeError, ValueError):
                final_amount = int(plan.price_irt or 0)
        await state.set_state(None)

    is_admin = callback.from_user.id in settings.admin_ids
    text = renewal_checkout_text(
        svc,
        plan,
        current_plan,
        is_admin=is_admin,
        discount_code=discount_code,
        final_amount=final_amount,
        prefix=prefix,
    )
    await edit_or_answer(
        callback,
        text,
        reply_markup=renew_payment_methods_keyboard(sid, pid, discount_code if not is_admin else None),
    )
    return True


@router.callback_query(F.data.startswith('svc:renew_discount:'))
async def renew_discount_start(callback: CallbackQuery, state: FSMContext):
    _, _, sid_raw, pid_raw = callback.data.split(':')
    sid = int(sid_raw)
    pid = int(pid_raw)
    async with SessionLocal() as session:
        svc = await session.get(ClientService, sid)
        ok_owner, _user = await _owned_public_service(session, svc, callback.from_user.id)
        plan = await session.get(Plan, pid)
        if not ok_owner or not svc or not plan or plan.server_id != svc.server_id:
            await _deny_not_owned(callback)
            return
    await state.update_data(renewal_service_id=sid, renewal_plan_id=pid)
    await state.set_state(RenewDiscountInput.code)
    await edit_or_answer(
        callback,
        '🏷 کد تخفیف تمدید را وارد کنید:',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(f'svc:renew_discount_back:{sid}:{pid}')]]),
    )
    await callback.answer()


@router.callback_query(F.data.startswith('svc:renew_discount_back:'))
async def renew_discount_back(callback: CallbackQuery, state: FSMContext):
    _, _, sid_raw, pid_raw = callback.data.split(':')
    await state.set_state(None)
    ok = await show_renew_payment_methods(callback, int(sid_raw), int(pid_raw), state)
    if ok:
        await callback.answer()


@router.message(RenewDiscountInput.code)
async def renew_discount_apply(message: Message, state: FSMContext):
    code = (message.text or '').strip().upper().replace(' ', '')
    data = await state.get_data()
    try:
        sid = int(data.get('renewal_service_id') or 0)
        pid = int(data.get('renewal_plan_id') or 0)
    except (TypeError, ValueError):
        sid = pid = 0

    async with SessionLocal() as session:
        svc = await session.get(ClientService, sid) if sid else None
        ok_owner, user = await _owned_public_service(session, svc, message.from_user.id)
        plan = await session.get(Plan, pid) if pid else None
        server = await session.get(Server, svc.server_id) if svc else None
        if not ok_owner or not user or not svc or not plan or not server or plan.server_id != svc.server_id:
            await state.clear()
            await ui_message(message, 'این سرویس یا تعرفه برای تمدید پیدا نشد.', reply_markup=back_main_inline())
            return
        final_amount, err, _discount = await apply_discount_amount(
            session,
            code,
            int(plan.price_irt or 0),
            user.id,
            'renew',
            server.id,
        )
        current_plan = await session.get(Plan, svc.plan_id) if svc.plan_id else None

    if err:
        await ui_message(
            message,
            '❌ ' + err,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(f'svc:renew_discount_back:{sid}:{pid}')]]),
        )
        return

    await state.update_data(renew_discount_code=code, renew_final_amount=final_amount)
    await state.set_state(None)
    text = (
        '✅ کد تخفیف برای تمدید اعمال شد.\n\n'
        + renewal_checkout_text(
            svc,
            plan,
            current_plan,
            is_admin=False,
            discount_code=code,
            final_amount=final_amount,
        )
    )
    await ui_message(message, text, reply_markup=renew_payment_methods_keyboard(sid, pid, code))


async def _apply_service_renewal(session, svc: ClientService, user: User, plan: Plan, server: Server, *, amount_irt: int, payment_method: str) -> Order:
    order = Order(
        user_id=user.id,
        plan_id=plan.id,
        service_id=svc.id,
        amount_irt=amount_irt,
        payment_method=payment_method,
        status='processing',
    )
    session.add(order)
    await session.flush()
    if server.server_type == 'xui':
        await XuiService().reset_client_plan(server, svc.xui_email, plan.volume_gb, plan.duration_days)
    elif server.server_type == 'mikrotik':
        await MikroTikService().renew_user(server, svc.xui_email or svc.client_username, volume_gb=plan.volume_gb, expire_days=plan.duration_days)
    svc.plan_id = plan.id
    svc.total_bytes = plan.volume_gb * 1024**3
    svc.used_bytes = 0
    svc.traffic_baseline_bytes = 0
    svc.expires_at = datetime.utcnow() + timedelta(days=plan.duration_days) if plan.duration_days else None
    svc.is_active = True
    svc.disabled_at = None
    svc.disabled_reason = None
    svc.disabled_notify_count = 0
    svc.disabled_last_notified_at = None
    order.status = 'paid'
    return order


async def admin_free_renew(callback: CallbackQuery, sid: int, pid: int) -> bool:
    renewed_username = None
    if callback.from_user.id not in settings.admin_ids:
        return False
    if callback.message:
        cancel_auto_refresh(callback.message.chat.id, callback.message.message_id)
    async with SessionLocal() as session:
        svc = await session.get(ClientService, sid)
        ok_owner, user = await _owned_public_service(session, svc, callback.from_user.id)
        plan = await session.get(Plan, pid)
        server = await session.get(Server, svc.server_id) if svc else None
        if not ok_owner or not user or not svc or not plan or not server or plan.server_id != svc.server_id:
            await _deny_not_owned(callback)
            return False
        try:
            renewed_username = svc.client_username or svc.xui_email
            await send_building_notice(callback, service_building_text(renewed_username, plan.title, plan.volume_gb, plan.duration_days))
            await _apply_service_renewal(session, svc, user, plan, server, amount_irt=0, payment_method='admin_free_renew')
            await session.commit()
        except Exception as e:
            await session.rollback()
            await handle_user_facing_error(
                callback,
                e,
                context='Admin free public service renewal failed',
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(f'svc:renew_menu:{sid}')]])
            )
            return False
    await edit_or_answer(
        callback,
        renewal_confirmation_text(
            username=renewed_username,
            plan_title=plan.title,
            volume_gb=plan.volume_gb,
            duration_days=plan.duration_days,
            expires_at=svc.expires_at,
            server_type=server.server_type,
            amount_irt=0,
        ),
        reply_markup=renewal_keyboard(),
    )
    await callback.answer('✅ سرویس برای مدیر رایگان تمدید شد')
    return True


@router.callback_query(F.data.startswith('svc:renew_plan:'))
async def renew_plan_selected(callback: CallbackQuery, state: FSMContext):
    _, _, sid, pid = callback.data.split(':')
    if callback.from_user.id in settings.admin_ids:
        await admin_free_renew(callback, int(sid), int(pid))
        return
    ok = await show_renew_payment_methods(callback, int(sid), int(pid), state, reset_discount=True)
    if ok:
        await callback.answer()


@router.callback_query(F.data.startswith('svc:change_plan:'))
async def change_plan(callback: CallbackQuery, state: FSMContext):
    # Backward compatibility for old inline keyboards: choosing a plan must never
    # renew the service directly. It now opens the payment step instead.
    _, _, sid, pid = callback.data.split(':')
    if callback.from_user.id in settings.admin_ids:
        await admin_free_renew(callback, int(sid), int(pid))
        return
    ok = await show_renew_payment_methods(callback, int(sid), int(pid), state, reset_discount=True)
    if ok:
        await callback.answer('روش پرداخت را انتخاب کنید')


@router.callback_query(F.data.startswith('svc:renew_back_methods:'))
async def renew_receipt_back(callback: CallbackQuery, state: FSMContext):
    _, _, sid, pid = callback.data.split(':')
    data = await state.get_data()
    order_id = data.get('order_id')
    if order_id:
        async with SessionLocal() as session:
            order = await session.get(Order, int(order_id))
            if order and order.status == 'waiting_receipt':
                discount_code = None
                if ':discount:' in (order.payment_method or ''):
                    discount_code = order.payment_method.split(':discount:', 1)[1]
                await release_order_discount_usage(
                    session,
                    order_id=order.id,
                    user_id=order.user_id,
                    code=discount_code,
                    source='renew',
                )
                order.status = 'cancelled'
                await session.commit()
    await state.update_data(order_id=None)
    ok = await show_renew_payment_methods(callback, int(sid), int(pid), state, prefix='یک مرحله برگشتید.\n\n')
    if ok:
        await callback.answer()


@router.callback_query(F.data.startswith('svc:renew_pay:'))
async def renew_pay(callback: CallbackQuery, state: FSMContext):
    _, _, sid_raw, pid_raw, method = callback.data.split(':')
    sid = int(sid_raw)
    pid = int(pid_raw)
    if callback.message:
        cancel_auto_refresh(callback.message.chat.id, callback.message.message_id)

    renewed_username = None
    final_amount = 0
    discount_code = None

    async with SessionLocal() as session:
        svc = await session.get(ClientService, sid)
        ok_owner, user = await _owned_public_service(session, svc, callback.from_user.id)
        plan = await session.get(Plan, pid)
        server = await session.get(Server, svc.server_id) if svc else None
        if not ok_owner or not user or not svc or not plan or not server or plan.server_id != svc.server_id:
            await _deny_not_owned(callback)
            return

        if callback.from_user.id in settings.admin_ids:
            try:
                renewed_username = svc.client_username or svc.xui_email
                await send_building_notice(callback, service_building_text(renewed_username, plan.title, plan.volume_gb, plan.duration_days))
                await _apply_service_renewal(session, svc, user, plan, server, amount_irt=0, payment_method='admin_free_renew')
                await session.commit()
            except Exception as exc:
                await session.rollback()
                await handle_user_facing_error(
                    callback,
                    exc,
                    context='Admin free public service renewal failed',
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(f'svc:renew_plan:{sid}:{pid}')]]),
                )
                return
            await state.clear()
            await edit_or_answer(
                callback,
                renewal_confirmation_text(
                    username=renewed_username,
                    plan_title=plan.title,
                    volume_gb=plan.volume_gb,
                    duration_days=plan.duration_days,
                    expires_at=svc.expires_at,
                    server_type=server.server_type,
                    amount_irt=0,
                ),
                reply_markup=renewal_keyboard(),
            )
            await callback.answer('✅ سرویس برای مدیر رایگان تمدید شد')
            return

        checkout_data = await state.get_data()
        if _renew_checkout_matches(checkout_data, sid, pid):
            discount_code = checkout_data.get('renew_discount_code')

        discount_obj = None
        final_amount = int(plan.price_irt or 0)
        if discount_code:
            final_amount, discount_error, discount_obj = await apply_discount_amount(
                session,
                discount_code,
                int(plan.price_irt or 0),
                user.id,
                'renew',
                server.id,
            )
            if discount_error:
                await state.update_data(renew_discount_code=None, renew_final_amount=int(plan.price_irt or 0))
                await state.set_state(None)
                await edit_or_answer(
                    callback,
                    '❌ ' + discount_error + '\n\nکد تخفیف از این تمدید حذف شد؛ می‌توانید کد دیگری وارد کنید.',
                    reply_markup=renew_payment_methods_keyboard(sid, pid),
                )
                await callback.answer('کد تخفیف قابل استفاده نیست.', show_alert=True)
                return

        payment_suffix = f':discount:{discount_code}' if discount_code else ''

        # A 100% or fixed full discount renews immediately; asking for a zero-value
        # card receipt would be confusing and unnecessary.
        if final_amount <= 0:
            try:
                renewed_username = svc.client_username or svc.xui_email
                await send_building_notice(callback, service_building_text(renewed_username, plan.title, plan.volume_gb, plan.duration_days))
                await _apply_service_renewal(
                    session,
                    svc,
                    user,
                    plan,
                    server,
                    amount_irt=0,
                    payment_method='discount_renew' + payment_suffix,
                )
                await mark_discount_used(session, discount_obj, user.id, 'renew')
                await session.commit()
            except Exception as exc:
                await session.rollback()
                await handle_user_facing_error(
                    callback,
                    exc,
                    context='User service renewal with full discount failed',
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(f'svc:renew_plan:{sid}:{pid}')]]),
                )
                return
            await state.clear()
            await edit_or_answer(
                callback,
                renewal_confirmation_text(
                    username=renewed_username,
                    plan_title=plan.title,
                    volume_gb=plan.volume_gb,
                    duration_days=plan.duration_days,
                    expires_at=svc.expires_at,
                    server_type=server.server_type,
                    amount_irt=0,
                ),
                reply_markup=renewal_keyboard(),
            )
            await callback.answer('✅ کد تخفیف اعمال شد و سرویس تمدید شد')
            return

        if method == 'card':
            card = (
                await session.execute(
                    select(PaymentCard).where(
                        PaymentCard.server_id == server.id,
                        PaymentCard.is_active == True,  # noqa: E712
                    )
                )
            ).scalar_one_or_none()
            if not card:
                card = (
                    await session.execute(
                        select(PaymentCard).where(
                            PaymentCard.server_type == server.server_type,
                            PaymentCard.server_id.is_(None),
                            PaymentCard.is_active == True,  # noqa: E712
                        )
                    )
                ).scalar_one_or_none()
            if not card:
                await edit_or_answer(
                    callback,
                    'برای این سرور شماره کارت ثبت نشده است.',
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(f'svc:renew_plan:{sid}:{pid}')]]),
                )
                await callback.answer()
                return

            order = Order(
                user_id=user.id,
                plan_id=plan.id,
                service_id=svc.id,
                amount_irt=final_amount,
                payment_method=f'renew:{svc.id}' + payment_suffix,
                status='waiting_receipt',
            )
            session.add(order)
            await session.flush()
            if discount_code:
                await mark_discount_used(
                    session,
                    discount_obj,
                    user.id,
                    order_discount_usage_source(order.id, 'renew'),
                )
            await session.commit()
            oid = order.id
            username = svc.client_username or svc.xui_email
            await state.update_data(
                order_id=oid,
                username=username,
                plan_id=plan.id,
                server_id=server.id,
                renewal_service_id=svc.id,
                renewal_plan_id=plan.id,
                renew_discount_code=discount_code,
                renew_final_amount=final_amount,
            )
            await state.set_state(BuyFlow.receipt)
            discount_line = ''
            if discount_code:
                discount_line = (
                    f'💰 مبلغ اصلی: {int(plan.price_irt or 0):,} تومان\n'
                    f'🏷 کد تخفیف: {discount_code}\n'
                )
            await edit_or_answer(
                callback,
                f'💳 تمدید سرویس با کارت به کارت\n\n'
                f'👤 کانفیگ: {username}\n'
                f'📦 تعرفه انتخابی: {plan.title}\n'
                f'{discount_line}'
                f'💵 مبلغ قابل پرداخت: {final_amount:,} تومان\n\n'
                f'شماره کارت: {card.card_number}\n'
                f'نام صاحب حساب: {card.owner_name}\n\n'
                'بعد از واریز، عکس رسید را همینجا ارسال کنید.\n'
                'تمدید سرویس فقط بعد از تایید رسید توسط مدیر انجام می‌شود.',
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(f'svc:renew_back_methods:{sid}:{pid}')]]),
            )
            await callback.answer()
            return

        if method != 'wallet':
            await callback.answer('روش پرداخت نامعتبر است.', show_alert=True)
            return

        wallet_type = 'wallet_balance'
        balance = getattr(user, wallet_type, 0) or 0
        if balance < final_amount:
            await callback.answer('موجودی کیف پول کافی نیست.', show_alert=True)
            discount_line = f'🏷 کد تخفیف: {discount_code}\n' if discount_code else ''
            await edit_or_answer(
                callback,
                f'❌ موجودی کیف پول کافی نیست.\n\n'
                f'💰 مبلغ اصلی تمدید: {int(plan.price_irt or 0):,} تومان\n'
                f'{discount_line}'
                f'💵 مبلغ قابل پرداخت: {final_amount:,} تومان\n'
                f'💎 موجودی شما: {balance:,} تومان\n\n'
                'می‌توانید پرداخت کارت به کارت را انتخاب کنید و رسید بفرستید.',
                reply_markup=renew_payment_methods_keyboard(sid, pid, discount_code),
            )
            return

        try:
            renewed_username = svc.client_username or svc.xui_email
            await send_building_notice(callback, service_building_text(renewed_username, plan.title, plan.volume_gb, plan.duration_days))
            await _apply_service_renewal(
                session,
                svc,
                user,
                plan,
                server,
                amount_irt=final_amount,
                payment_method='wallet_renew' + payment_suffix,
            )
            setattr(user, wallet_type, balance - final_amount)
            await mark_discount_used(session, discount_obj, user.id, 'renew')
            await session.commit()
        except Exception as exc:
            await session.rollback()
            await handle_user_facing_error(
                callback,
                exc,
                context='User service renewal with wallet failed',
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(f'svc:renew_plan:{sid}:{pid}')]]),
            )
            return

    await state.clear()
    await edit_or_answer(
        callback,
        renewal_confirmation_text(
            username=renewed_username,
            plan_title=plan.title,
            volume_gb=plan.volume_gb,
            duration_days=plan.duration_days,
            expires_at=svc.expires_at,
            server_type=server.server_type,
            amount_irt=final_amount,
        ),
        reply_markup=renewal_keyboard(),
    )
    await callback.answer('✅ سرویس با کیف پول تمدید شد')


@router.callback_query(F.data.startswith('svc:profile:'))
async def send_openvpn_profile(callback: CallbackQuery):
    # Answer the callback immediately. If the user presses an old profile button,
    # Telegram may otherwise show "query/message is too old" while we are reading
    # the profile from DB and sending the document.
    try:
        await callback.answer('در حال ارسال پروفایل...')
    except Exception:
        pass
    sid = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        svc = await session.get(ClientService, sid)
        ok_owner, _user = await _owned_public_service(session, svc, callback.from_user.id)
        server = await session.get(Server, svc.server_id) if svc else None
        if not ok_owner or not server:
            await callback.message.answer('این سرویس برای شما نیست یا پیدا نشد.', reply_markup=back_main_inline())
            return
        if (server.server_type or '').lower() != 'mikrotik':
            await callback.message.answer('دریافت پروفایل سرور فقط برای سرویس‌های MikroTik / OpenVPN فعال است.', reply_markup=back_main_inline())
            return
    sent = await send_openvpn_profile_document(
        callback.message.bot,
        callback.from_user.id,
        sid,
        caption=None,
    )
    if not sent:
        await callback.message.answer('برای این سرور هنوز پروفایل OpenVPN ثبت نشده است.', reply_markup=back_main_inline())

@router.callback_query(F.data.startswith('svc:delete:'))
async def delete_service_ask(callback: CallbackQuery):
    if callback.message:
        cancel_auto_refresh(callback.message.chat.id, callback.message.message_id)
    sid=int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        svc = await session.get(ClientService, sid)
        ok_owner, _user = await _owned_public_service(session, svc, callback.from_user.id)
        if not ok_owner:
            await _deny_not_owned(callback); return
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='✅ تایید حذف کانفیگ 🗑', callback_data=f'svc:delete_confirm:{sid}')],[back_button(f'svc:{sid}')]])
    await edit_or_answer(callback, '⚠️ این کانفیگ هم از ربات و هم از پنل حذف می‌شود. مطمئن هستید؟', reply_markup=kb); await callback.answer()

@router.callback_query(F.data.startswith('svc:delete_confirm:'))
async def delete_service(callback: CallbackQuery):
    if callback.message:
        cancel_auto_refresh(callback.message.chat.id, callback.message.message_id)
    sid=int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        svc=await session.get(ClientService,sid)
        ok_owner, _user = await _owned_public_service(session, svc, callback.from_user.id)
        if not ok_owner:
            await _deny_not_owned(callback); return
        server=await session.get(Server,svc.server_id)
        panel_already_missing = False
        if server and server.server_type == 'xui':
            try:
                await XuiService().delete_client(
                    server,
                    svc.xui_email,
                    svc.client_username,
                    svc.xui_uuid,
                    svc.sub_link,
                )
            except Exception as e:
                msg = str(e).lower()
                # If the admin already removed the client directly from 3x-ui,
                # local cleanup must still continue instead of blocking the user.
                if 'not found' in msg or 'not exist' in msg or 'not exists' in msg:
                    panel_already_missing = True
                else:
                    await handle_user_facing_error(callback, e, context='User service delete from panel failed', reply_markup=back_main_inline()); return
        elif server and server.server_type == 'mikrotik':
            try:
                await MikroTikService().delete_user(server, svc.xui_email or svc.client_username)
            except Exception as e:
                msg = str(e).lower()
                if 'not found' in msg or 'not exist' in msg or 'not exists' in msg:
                    panel_already_missing = True
                else:
                    await handle_user_facing_error(callback, e, context='User MikroTik service delete failed', reply_markup=back_main_inline()); return
        deleted_username = svc.client_username
        deleted_email = svc.xui_email
        deleted_volume = svc.total_bytes or 0
        deleted_used = svc.used_bytes or 0
        deleted_expires = svc.expires_at
        deleted_created = svc.created_at
        deleted_server_name = server.name if server else '-'
        deleted_server_type = server.server_type if server else '-'
        deleted_plan = await session.get(Plan, svc.plan_id) if svc.plan_id else None
        deleted_plan_title = deleted_plan.title if deleted_plan else '-'
        # Remove or detach all local references before deleting the service.
        # Orders must stay as accounting history, so their service_id is cleared.
        await delete_local_service_records(session, svc)
        await session.commit()
    deleted_remaining = max(int(deleted_volume or 0) - int(deleted_used or 0), 0)
    deleted_text = (
        f'✅ یوزرنیم {deleted_username or deleted_email or "-"} با مشخصات کامل زیر با موفقیت حذف شد.\n\n'
        '━━━━━━━━━━━━━━━━\n'
        f'👤 نام کانفیگ: {deleted_username or "-"}\n'
        f'🆔 یوزرنیم پنل: {deleted_email or "-"}\n'
        f'📦 تعرفه: {deleted_plan_title}\n'
        f'🖥 سرور: {deleted_server_name}\n'
        f'🔌 نوع سرویس: {deleted_server_type}\n'
        f'💾 حجم کل: {gb(deleted_volume):.2f} گیگ\n'
        f'📊 مصرف‌شده: {gb(deleted_used):.2f} گیگ\n'
        f'📉 حجم باقی‌مانده: {gb(deleted_remaining):.2f} گیگ\n'
        f'📅 تاریخ ساخت: {fa_date(deleted_created)}\n'
        f'⏳ تاریخ انقضا: {fa_date(deleted_expires)}'
    )
    await edit_or_answer(
        callback,
        deleted_text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(CB_MY_SERVICES)]])
    )
    if locals().get('panel_already_missing'):
        await callback.answer('✅ کانفیگ داخل پنل نبود؛ از ربات پاک شد')
    else:
        await callback.answer('✅ کانفیگ از ربات و پنل حذف شد')
