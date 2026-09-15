from __future__ import annotations

from datetime import datetime, timedelta
import re
import random
import string
from sqlalchemy import select, func
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from app.database.models import User, Server, ClientService, WalletTransaction, Order
from app.database.defaults import get_setting_value
from app.services.xui_service import XuiService
from app.utils.jalali import fa_datetime


def _enabled(value: str | None) -> bool:
    return str(value or '0') == '1'


def _username(base: str) -> str:
    clean = re.sub(r'[^A-Za-z0-9_]', '', str(base or 'ref').strip()) or 'ref'
    suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=5))
    return f'{clean}_{suffix}'[:80]


async def referral_status_text() -> str:
    reward_enabled = await get_setting_value('referral_reward_service_enabled', '0')
    commission_enabled = await get_setting_value('referral_commission_enabled', '0')
    server_id = await get_setting_value('referral_reward_server_id', '')
    volume = await get_setting_value('referral_reward_volume_gb', '0')
    days = await get_setting_value('referral_reward_days', '0')
    invites = await get_setting_value('referral_reward_invites', '0')
    percent = await get_setting_value('referral_commission_percent', '0')
    return (
        '🎁 تنظیمات زیرمجموعه گیری\n'
        '━━━━━━━━━━━━━━━━\n\n'
        f'1️⃣ ارسال یوزر به ازای دعوت: {"🟢 روشن" if _enabled(reward_enabled) else "🔴 خاموش"}\n'
        f'├ سرور: {server_id or "ثبت نشده"}\n'
        f'├ حجم: {volume} گیگ\n'
        f'├ مدت: {days} روز\n'
        f'╰ شرط: هر {invites} دعوت\n\n'
        f'2️⃣ پورسانت خرید: {"🟢 روشن" if _enabled(commission_enabled) else "🔴 خاموش"}\n'
        f'╰ درصد پورسانت: {percent}%'
    )


async def maybe_grant_invite_reward(session, bot, invited_user: User) -> None:
    if not invited_user or not invited_user.referred_by_user_id:
        return
    if not _enabled(await get_setting_value('referral_reward_service_enabled', '0')):
        return
    try:
        required = int(await get_setting_value('referral_reward_invites', '0') or 0)
        server_id = int(await get_setting_value('referral_reward_server_id', '0') or 0)
        volume_gb = int(await get_setting_value('referral_reward_volume_gb', '0') or 0)
        days = int(await get_setting_value('referral_reward_days', '0') or 0)
    except Exception:
        return
    if required <= 0 or server_id <= 0 or volume_gb <= 0 or days <= 0:
        return

    referrer = await session.get(User, invited_user.referred_by_user_id)
    server = await session.get(Server, server_id)
    if not referrer or not server or not getattr(server, 'is_active', True):
        return
    count = (await session.execute(select(func.count(User.id)).where(User.referred_by_user_id == referrer.id))).scalar() or 0
    if count <= 0 or count % required != 0:
        return
    marker = f'referral_reward:{referrer.id}:{count}'
    existing = (await session.execute(select(ClientService).where(ClientService.client_username == marker))).scalar_one_or_none()
    if existing:
        return

    username = _username(f'ref{referrer.telegram_id}')
    inbound_ids = []
    try:
        meta = server.meta or {}
        inbound_ids = [int(x.get('id') if isinstance(x, dict) else x) for x in (meta.get('inbound_ids') or [])]
    except Exception:
        inbound_ids = []
    service = ClientService(
        user_id=referrer.id,
        server_id=server.id,
        plan_id=None,
        client_username=username,
        xui_email=username,
        inbound_ids=inbound_ids,
        total_bytes=volume_gb * 1024**3,
        expires_at=datetime.utcnow() + timedelta(days=days),
        is_active=True,
    )
    session.add(service)
    await session.flush()
    sub_link = None
    if server.server_type == 'xui':
        _Plan = type('ReferralPlan', (), {'volume_gb': volume_gb, 'duration_days': days, 'inbound_ids': inbound_ids})
        created = await XuiService().create_client_on_plan(server, _Plan, username)
        if isinstance(created, dict):
            sub_link = created.get('sub_link')
            service.sub_link = sub_link
            service.xui_uuid = (str(created.get('uuid')) if isinstance(created, dict) and created.get('uuid') is not None else None)
    await session.commit()
    try:
        await bot.send_message(
            int(referrer.telegram_id),
            '🎁 جایزه زیرمجموعه گیری فعال شد!\n\n'
            f'👥 تعداد دعوت شما به {count} رسید.\n'
            f'📦 سرویس هدیه: {volume_gb} گیگ | {days} روز\n'
            f'🔐 نام سرویس: {username}' + (f'\n🔗 ساب لینک:\n{sub_link}' if sub_link else '')
        )
    except Exception:
        pass


async def _paid_purchase_count(session, user_id: int) -> int:
    return (await session.execute(
        select(func.count(Order.id)).where(Order.user_id == user_id, Order.status == 'paid')
    )).scalar() or 0


def _wallet_field_for(server_type: str | None) -> str:
    st = (server_type or 'xui').lower()
    return 'wallet_openvpn_balance' if st in ('openvpn', 'l2tp') or 'openvpn' in st or 'l2tp' in st else 'wallet_v2ray_balance'


async def notify_referrer_about_new_subset(session, bot, invited_user: User) -> None:
    if not bot or not invited_user or not invited_user.referred_by_user_id:
        return
    referrer = await session.get(User, invited_user.referred_by_user_id)
    if not referrer:
        return
    try:
        joined = fa_datetime(invited_user.referral_joined_at, empty='-') if invited_user.referral_joined_at else '-'
    except Exception:
        joined = '-'
    text = (
        '🎉 زیرمجموعه جدید ثبت شد!\n'
        '━━━━━━━━━━━━━━━━\n\n'
        f'👤 نام: {invited_user.full_name or "-"}\n'
        f'🆔 یوزرنیم: @{invited_user.username or "ندارد"}\n'
        f'🔢 آیدی عددی: {invited_user.telegram_id}\n'
        f'📅 زمان ثبت: {joined}\n\n'
        'از این به بعد اگر این کاربر خرید انجام دهد و شرایط پورسانت فعال باشد، درصد خرید به کیف پول شما اضافه می‌شود.'
    )
    try:
        await bot.send_message(int(referrer.telegram_id), text)
    except Exception:
        pass


async def apply_purchase_commission(session, buyer: User, amount_irt: int, bot=None, server_type: str | None = 'xui') -> int:
    if not buyer or not buyer.referred_by_user_id:
        return 0
    if not _enabled(await get_setting_value('referral_commission_enabled', '0')):
        return 0
    try:
        percent = float(await get_setting_value('referral_commission_percent', '0') or 0)
    except Exception:
        percent = 0
    if percent <= 0 or amount_irt <= 0:
        return 0
    referrer = await session.get(User, buyer.referred_by_user_id)
    if not referrer or referrer.id == buyer.id:
        return 0

    # شرط امنیتی/تجاری: معرف باید حداقل یک خرید موفق از ربات داشته باشد.
    if await _paid_purchase_count(session, referrer.id) < 1:
        return 0

    commission = int(amount_irt * percent / 100)
    if commission <= 0:
        return 0
    field = _wallet_field_for(server_type)
    referrer.wallet_balance = int(referrer.wallet_balance or 0) + commission
    setattr(referrer, field, int(getattr(referrer, field, 0) or 0) + commission)
    session.add(WalletTransaction(user_id=referrer.id, amount_irt=commission, tx_type='referral_commission', description=f'پورسانت خرید کاربر {buyer.telegram_id}'))

    if bot:
        try:
            wallet_title = 'اصلی'
            balance = int(getattr(referrer, field, 0) or 0)
            buyer_name = buyer.full_name or buyer.username or str(buyer.telegram_id)
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='💎 مشاهده کیف پول', callback_data='menu:account')]])
            await bot.send_message(
                int(referrer.telegram_id),
                '🎉 تبریک! یکی از زیرمجموعه‌های شما خرید انجام داد.\n'
                '━━━━━━━━━━━━━━━━\n\n'
                f'👤 زیرمجموعه: {buyer_name}\n'
                f'💰 مبلغ خرید: {int(amount_irt):,} تومان\n'
                f'🎁 درصد پورسانت: {percent:g}%\n'
                f'✅ مبلغ {commission:,} تومان به کیف پول شما اضافه شد.',
                reply_markup=kb,
            )
            await bot.send_message(
                int(referrer.telegram_id),
                f'💎 موجودی کیف پول {wallet_title}: {balance:,} تومان',
                reply_markup=kb,
            )
        except Exception:
            pass
    return commission
