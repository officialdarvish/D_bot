from __future__ import annotations

from datetime import datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import desc, select

from app.bot.keyboards.common import CB_ANTI_SHARING, back_button
from app.bot.states.admin_states import AntiSharingConfig
from app.bot.utils import edit_or_answer, ui_message
from app.bot.error_reporting import handle_user_facing_error
from app.core.roles import is_owner
from app.database.defaults import get_setting_value, set_setting_value
from app.database.models import AntiSharingViolation, ClientService, Server
from app.database.session import SessionLocal
from app.services.xui_service import XuiService

router = Router()


def admin(uid: int) -> bool:
    return is_owner(uid)


def _fa_status(enabled: str) -> str:
    return "روشن ✅" if enabled == "1" else "خاموش ❌"


def _action_fa(action: str) -> str:
    return {
        "warning": "هشدار",
        "temp_ban_24h": "بن ۲۴ ساعته",
        "permanent_ban": "بن دائمی",
        "manual_unban": "آن‌بن دستی",
    }.get(action, action)


async def anti_text() -> str:
    enabled = await get_setting_value("anti_sharing_enabled", "1")
    limit = await get_setting_value("anti_sharing_default_ip_limit", "2")
    scan = await get_setting_value("anti_sharing_scan_minutes", "5")
    ban24 = await get_setting_value("anti_sharing_auto_ban_24h_after", "2")
    perm = await get_setting_value("anti_sharing_auto_ban_permanent_after", "3")
    async with SessionLocal() as session:
        total = len((await session.execute(select(AntiSharingViolation))).scalars().all())
        banned = len((await session.execute(
            select(ClientService).where(
                (ClientService.anti_share_banned_permanent == True) |
                (ClientService.anti_share_banned_until != None)
            )
        )).scalars().all())
    return (
        "🛡 سیستم ضد اشتراک‌گذاری\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"وضعیت: {_fa_status(enabled)}\n"
        f"حد پیش‌فرض IP: {limit}\n"
        f"اسکن خودکار: هر {scan} دقیقه\n"
        f"بن ۲۴ ساعته بعد از تخلف: {ban24}\n"
        f"بن دائمی بعد از تخلف: {perm}\n\n"
        f"تخلف‌های ثبت‌شده: {total}\n"
        f"کانفیگ‌های بن‌شده: {banned}\n\n"
        "این سیستم فقط روی پلن‌های نامحدود اجرا می‌شود. پلن‌های حجمی و PAYG بررسی IP نمی‌شوند.\n"
        "API رسمی 3x-ui استفاده می‌شود و access.log خوانده نمی‌شود."
    )


def anti_kb(enabled: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"وضعیت: {_fa_status(enabled)}", callback_data="anti:toggle")],
        [InlineKeyboardButton(text="⚙️ تغییر حد IP", callback_data="anti:set:limit"), InlineKeyboardButton(text="⏱ تغییر زمان اسکن", callback_data="anti:set:scan")],
        [InlineKeyboardButton(text="🚫 تنظیم بن ۲۴ ساعته", callback_data="anti:set:ban24"), InlineKeyboardButton(text="⛔️ تنظیم بن دائمی", callback_data="anti:set:perm")],
        [InlineKeyboardButton(text="📊 آخرین تخلف‌ها", callback_data="anti:violations"), InlineKeyboardButton(text="🚷 کاربران بن‌شده", callback_data="anti:banned")],
        [back_button("admin:bot_settings")],
    ])


@router.callback_query(F.data == CB_ANTI_SHARING)
async def anti_menu(callback: CallbackQuery):
    if not admin(callback.from_user.id):
        return
    enabled = await get_setting_value("anti_sharing_enabled", "1")
    await edit_or_answer(callback, await anti_text(), reply_markup=anti_kb(enabled))
    await callback.answer()


@router.callback_query(F.data == "anti:toggle")
async def anti_toggle(callback: CallbackQuery):
    if not admin(callback.from_user.id):
        return
    cur = await get_setting_value("anti_sharing_enabled", "1")
    await set_setting_value("anti_sharing_enabled", "0" if cur == "1" else "1")
    await anti_menu(callback)


@router.callback_query(F.data.startswith("anti:set:"))
async def anti_set_start(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id):
        return
    field = callback.data.split(":")[-1]
    key_map = {
        "limit": "anti_sharing_default_ip_limit",
        "scan": "anti_sharing_scan_minutes",
        "ban24": "anti_sharing_auto_ban_24h_after",
        "perm": "anti_sharing_auto_ban_permanent_after",
    }
    title_map = {
        "limit": "حد مجاز IP پیش‌فرض را برای پلن‌های نامحدود وارد کنید. مثال: 2",
        "scan": "زمان اسکن را به دقیقه وارد کنید. مثال: 5",
        "ban24": "بعد از چند تخلف بن ۲۴ ساعته اعمال شود؟ مثال: 2",
        "perm": "بعد از چند تخلف بن دائمی اعمال شود؟ مثال: 3",
    }
    await state.clear()
    await state.update_data(anti_key=key_map[field])
    await state.set_state(AntiSharingConfig.value)
    await edit_or_answer(callback, title_map[field], reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(CB_ANTI_SHARING)]]))
    await callback.answer()


@router.message(AntiSharingConfig.value)
async def anti_set_save(message: Message, state: FSMContext):
    if not admin(message.from_user.id):
        return
    value = message.text.strip()
    if not value.isdigit() or int(value) < 0:
        await ui_message(message, "فقط عدد مثبت وارد کنید.")
        return
    data = await state.get_data()
    await set_setting_value(data["anti_key"], str(int(value)))
    await state.clear()
    enabled = await get_setting_value("anti_sharing_enabled", "1")
    await ui_message(message, "✅ تنظیمات ذخیره شد.", reply_markup=anti_kb(enabled))


@router.callback_query(F.data == "anti:violations")
async def anti_violations(callback: CallbackQuery):
    if not admin(callback.from_user.id):
        return
    async with SessionLocal() as session:
        rows = (await session.execute(select(AntiSharingViolation).order_by(desc(AntiSharingViolation.id)).limit(10))).scalars().all()
    if not rows:
        text = "هنوز تخلفی ثبت نشده است."
    else:
        parts = ["📊 آخرین تخلف‌های ضد اشتراک‌گذاری", "━━━━━━━━━━━━━━━━"]
        for v in rows:
            date = v.created_at.strftime("%Y-%m-%d %H:%M") if v.created_at else "-"
            parts.append(f"#{v.id} | {v.email}\nIP: {v.ip_count}/{v.allowed_ip} | اقدام: {_action_fa(v.action)} | {date}")
        text = "\n\n".join(parts)
    await edit_or_answer(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(CB_ANTI_SHARING)]]))
    await callback.answer()


@router.callback_query(F.data == "anti:banned")
async def anti_banned(callback: CallbackQuery):
    if not admin(callback.from_user.id):
        return
    async with SessionLocal() as session:
        rows = (await session.execute(select(ClientService).where(
            (ClientService.anti_share_banned_permanent == True) |
            (ClientService.anti_share_banned_until != None)
        ).order_by(desc(ClientService.id)).limit(20))).scalars().all()
    if not rows:
        await edit_or_answer(callback, "کاربر بن‌شده‌ای وجود ندارد.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(CB_ANTI_SHARING)]]))
        await callback.answer()
        return
    kb=[]
    for s in rows:
        status = "دائمی" if s.anti_share_banned_permanent else f"تا {s.anti_share_banned_until}"
        kb.append([InlineKeyboardButton(text=f"{s.xui_email} | {status}", callback_data=f"anti:service:{s.id}")])
    kb.append([back_button(CB_ANTI_SHARING)])
    await edit_or_answer(callback, "🚷 کاربران بن‌شده:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()


@router.callback_query(F.data.startswith("anti:service:"))
async def anti_service_detail(callback: CallbackQuery):
    if not admin(callback.from_user.id):
        return
    sid = int(callback.data.split(":")[-1])
    async with SessionLocal() as session:
        s = await session.get(ClientService, sid)
        server = await session.get(Server, s.server_id) if s else None
    if not s:
        await callback.answer("سرویس پیدا نشد.", show_alert=True)
        return
    text = (
        "🚷 مدیریت بن ضد اشتراک‌گذاری\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"📧 Email: {s.xui_email}\n"
        f"🖥 سرور: {server.name if server else '-'}\n"
        f"⚠️ تعداد تخلف: {s.anti_share_violation_count}\n"
        f"⛔️ بن دائمی: {'بله' if s.anti_share_banned_permanent else 'خیر'}\n"
        f"⏳ بن موقت تا: {s.anti_share_banned_until or '-'}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ آن‌بن و فعال‌سازی", callback_data=f"anti:unban:{s.id}")],
        [back_button("anti:banned")],
    ])
    await edit_or_answer(callback, text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("anti:unban:"))
async def anti_unban(callback: CallbackQuery):
    if not admin(callback.from_user.id):
        return
    sid = int(callback.data.split(":")[-1])
    async with SessionLocal() as session:
        s = await session.get(ClientService, sid)
        server = await session.get(Server, s.server_id) if s else None
        if not s or not server:
            await callback.answer("سرویس پیدا نشد.", show_alert=True)
            return
        try:
            await XuiService().set_client_enabled(server, s.xui_email, True)
        except Exception as exc:
            await handle_user_facing_error(callback, exc, context='Admin anti-sharing unban panel enable failed')
            return
        s.anti_share_banned_until = None
        s.anti_share_banned_permanent = False
        s.anti_share_violation_count = 0
        session.add(AntiSharingViolation(
            service_id=s.id,
            user_id=s.user_id,
            server_id=s.server_id,
            email=s.xui_email,
            ip_count=len(s.anti_share_last_ips or []),
            allowed_ip=int(s.ip_limit or 0),
            ips=s.anti_share_last_ips or [],
            action="manual_unban",
            status="closed",
        ))
        await session.commit()
    await edit_or_answer(callback, "✅ سرویس آن‌بن و روی پنل فعال شد.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(CB_ANTI_SHARING)]]))
    await callback.answer()
