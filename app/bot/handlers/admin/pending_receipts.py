"""Pending receipt inbox shared by owners and delegated card reviewers."""
from __future__ import annotations

from html import escape
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from app.core.config import settings
from app.database.session import SessionLocal
from app.database.models import Order, PaymentCard, ResellerTopupRequest, PasarGuardPanelOrder, User, Plan, Server, ResellerPackage, ClientService
from app.bot.utils import edit_or_answer
from app.bot.keyboards.common import back_button
from app.bot.payment_audit import order_summary, date_label, _text

from app.services.receipt_status import ORDER_RECEIPT_OPEN_STATUSES, PANEL_RECEIPT_OPEN_STATUSES, receipt_status_label

router = Router()


def _main_admin(uid: int) -> bool:
    return int(uid) in set(settings.admin_ids or []) or int(uid) in set(settings.owner_ids or [])


async def is_receipt_reviewer(uid: int) -> bool:
    if _main_admin(uid):
        return True
    async with SessionLocal() as session:
        return bool((await session.execute(select(PaymentCard.id).where(
            PaymentCard.is_active.is_(True), PaymentCard.reviewer_telegram_id == uid).limit(1))).first())


async def _visible_receipts(uid: int):
    is_admin = _main_admin(uid)
    async with SessionLocal() as session:
        order_query = select(Order).where(
            Order.status.in_(ORDER_RECEIPT_OPEN_STATUSES), Order.receipt_file_id.is_not(None), Order.receipt_file_id != ''
        )
        panel_query = select(PasarGuardPanelOrder).where(PasarGuardPanelOrder.status.in_(PANEL_RECEIPT_OPEN_STATUSES))
        if not is_admin:
            # Apply reviewer scope BEFORE the limit; other vendors must not hide this inbox.
            order_query = order_query.where(Order.receipt_reviewer_telegram_id == uid)
            panel_query = panel_query.join(PaymentCard, PasarGuardPanelOrder.card_id == PaymentCard.id).where(PaymentCard.reviewer_telegram_id == uid)
        order_rows = (await session.execute(order_query.order_by(Order.id.desc()).limit(100))).scalars().all()
        panel_rows = (await session.execute(panel_query.order_by(PasarGuardPanelOrder.id.desc()).limit(100))).scalars().all()
        topups = (await session.execute(select(ResellerTopupRequest).where(
            ResellerTopupRequest.status == 'pending'
        ).order_by(ResellerTopupRequest.id.desc()).limit(100))).scalars().all() if is_admin else []
        cards = {x.id: x for x in (await session.execute(select(PaymentCard))).scalars().all()}
        # Snapshot reviewer in Order is authoritative; do not retroactively
        # reassign old receipts after a payment card is edited.
        orders = [o for o in order_rows if is_admin or int(o.receipt_reviewer_telegram_id or 0) == uid]
        panels = [o for o in panel_rows if is_admin or int(getattr(cards.get(o.card_id), 'reviewer_telegram_id', 0) or 0) == uid]
        return orders, panels, topups


@router.message(Command('pending_receipts'))
async def pending_receipts_command(message: Message):
    if not await is_receipt_reviewer(message.from_user.id):
        return
    await message.answer('🧾 رسیدهای تأییدنشده', reply_markup=await pending_receipts_keyboard(message.from_user.id))


async def pending_receipts_keyboard(uid: int):
    orders, panels, topups = await _visible_receipts(uid)
    rows = []
    # Show the buyer and purchased item in the inbox, not only a numeric order ID.
    user_ids = {o.user_id for o in [*orders[:40], *panels[:40], *topups[:40]]}
    plan_ids = {o.plan_id for o in orders[:40] if o.plan_id}
    package_ids = {o.package_id for o in topups[:40] if o.package_id}
    async with SessionLocal() as session:
        users = {u.id: u for u in (await session.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()} if user_ids else {}
        plans = {p.id: p for p in (await session.execute(select(Plan).where(Plan.id.in_(plan_ids)))).scalars().all()} if plan_ids else {}
        packages = {p.id: p for p in (await session.execute(select(ResellerPackage).where(ResellerPackage.id.in_(package_ids)))).scalars().all()} if package_ids else {}
    def owner_label(row):
        u = users.get(row.user_id)
        return str((u.full_name or u.username or u.telegram_id) if u else row.user_id)[:18]
    for o in orders[:40]:
        plan = plans.get(o.plan_id)
        what = 'شارژ کیف پول' if (o.payment_method or '').startswith('wallet_topup:') else (plan.title if plan else 'خرید / تمدید')
        rows.append([InlineKeyboardButton(text=f'{receipt_status_label(o.status)} | #{o.id} {owner_label(o)} | {str(what)[:20]}', callback_data=f'pending_receipts:order:{o.id}')])
    for o in panels[:40]:
        rows.append([InlineKeyboardButton(text=f'{receipt_status_label(o.status)} | 💼 #{o.id} {owner_label(o)} | {o.username}', callback_data=f'pending_receipts:panel:{o.id}')])
    for o in topups[:40]:
        title = packages[o.package_id].title if o.package_id in packages else 'شارژ نمایندگی'
        rows.append([InlineKeyboardButton(text=f'🤝 #{o.id} {owner_label(o)} | {str(title)[:20]}', callback_data=f'pending_receipts:reseller:{o.id}')])
    if not rows:
        rows.append([InlineKeyboardButton(text='✅ رسید تأییدنشده‌ای وجود ندارد', callback_data='noop')])
    rows.append([InlineKeyboardButton(text='🔄 بروزرسانی', callback_data='pending_receipts:list')])
    rows.append([back_button('back:main')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == 'pending_receipts:list')
async def pending_receipts_list(callback: CallbackQuery):
    if not await is_receipt_reviewer(callback.from_user.id):
        await callback.answer('دسترسی ندارید', show_alert=True); return
    await edit_or_answer(callback, '🧾 رسیدهای تأییدنشده\nفهرست بر اساس وضعیت فعلی پرداخت‌ها بروزرسانی می‌شود.',
                         reply_markup=await pending_receipts_keyboard(callback.from_user.id))
    await callback.answer()


@router.callback_query(F.data.startswith('pending_receipts:order:'))
@router.callback_query(F.data.startswith('pending_receipts:panel:'))
@router.callback_query(F.data.startswith('pending_receipts:reseller:'))
async def pending_receipts_detail(callback: CallbackQuery):
    uid = int(callback.from_user.id)
    if not await is_receipt_reviewer(uid):
        await callback.answer('دسترسی ندارید', show_alert=True); return
    kind, oid = callback.data.split(':')[-2:]
    try: oid = int(oid)
    except ValueError:
        await callback.answer('شناسه نامعتبر', show_alert=True); return
    async with SessionLocal() as session:
        if kind == 'order':
            order = await session.get(Order, oid)
            if not order or order.status not in ORDER_RECEIPT_OPEN_STATUSES or not order.receipt_file_id or not (_main_admin(uid) or order.receipt_reviewer_telegram_id == uid):
                await callback.answer('رسید موجود یا قابل مشاهده نیست', show_alert=True); return
            user = await session.get(User, order.user_id)
            plan = await session.get(Plan, order.plan_id) if order.plan_id else None
            service = await session.get(ClientService, order.service_id) if order.service_id else None
            server_id = (service.server_id if service else plan.server_id if plan else None)
            server = await session.get(Server, server_id) if server_id else None
            file_id = order.receipt_file_id
            desc = order_summary(order, user, plan, server, service, event='🧾 رسید تأییدنشده')
            desc += '\n\nوضعیت: ' + receipt_status_label(order.status)
            if order.status == 'processing':
                desc += '\nاین سفارش در حال پردازش است؛ تأیید مجدد و رد رسید تا پایان عملیات غیرفعال است.'
                actions = []
            else:
                label = '🔁 تلاش مجدد پس از اصلاح خطا' if order.status == 'failed' else '✅ تایید'
                if order.status == 'failed':
                    failure = (order.pricing_meta or {}).get('receipt_last_failure') or {}
                    reason = failure.get('reason') if isinstance(failure, dict) else None
                    desc += '\n' + escape(str(reason or 'ساخت یا تمدید قبلی انجام نشد؛ تنظیمات پلن و اینباندها را بررسی و اصلاح کنید.')[:600])
                actions = [(label, f'wallet_topup:approve:{oid}' if (order.payment_method or '').startswith('wallet_topup:') else f'order:approve:{oid}'),
                           ('❌ رد', f'wallet_topup:reject:{oid}' if (order.payment_method or '').startswith('wallet_topup:') else f'order:reject:{oid}')]
        elif kind == 'panel':
            order = await session.get(PasarGuardPanelOrder, oid)
            card = await session.get(PaymentCard, order.card_id) if order and order.card_id else None
            if not order or order.status not in PANEL_RECEIPT_OPEN_STATUSES or not (_main_admin(uid) or card and card.reviewer_telegram_id == uid):
                await callback.answer('سفارش قابل مشاهده نیست', show_alert=True); return
            user = await session.get(User, order.user_id)
            server = await session.get(Server, order.server_id)
            file_id = order.receipt_file_id if order.receipt_file_id != 'FREE' else None
            desc = '\n'.join([
                f'💼 رسید خرید پنل PasarGuard #{oid}',
                f'👤 نام خریدار: {_text(user.full_name if user else None)}',
                f'🔢 آیدی عددی: {_text(user.telegram_id if user else None)}',
                f'🆔 یوزرنیم تلگرام: @{_text(user.username)}' if user and user.username else '🆔 یوزرنیم تلگرام: ندارد',
                f'📦 مورد خریداری‌شده: پنل نمایندگی PasarGuard',
                f'🔐 یوزرنیم پنل: {_text(order.username)}',
                f'🖥 سرور: {_text(server.name if server else None)}',
                f'💰 مبلغ: {int(order.amount_irt or 0):,} تومان',
                f'📅 تاریخ خرید: {date_label(order.created_at)}',
            ])
            desc += '\nوضعیت: ' + receipt_status_label(order.status)
            actions = []
            if _main_admin(uid) and order.status == 'pending':
                actions = [('✅ تایید و ساخت', f'pgadmin:approve:{oid}'), ('❌ رد', f'pgadmin:reject:{oid}')]
            elif _main_admin(uid) and order.status == 'delivery_pending':
                actions = [('📨 ارسال دوباره مشخصات', f'pgadmin:deliver:{oid}')]
            elif order.status == 'review_required':
                desc += '\nقبل از هر اقدام جدید، وجود اکانت را در پاسارگارد بررسی کنید؛ ساخت مجدد خودکار فعال نیست.'
        else:
            if not _main_admin(uid):
                await callback.answer('دسترسی ندارید', show_alert=True); return
            order = await session.get(ResellerTopupRequest, oid)
            if not order or order.status != 'pending':
                await callback.answer('سفارش موجود نیست', show_alert=True); return
            user = await session.get(User, order.user_id)
            package = await session.get(ResellerPackage, order.package_id) if order.package_id else None
            file_id = order.receipt_file_id
            desc = '\n'.join([
                f'🤝 رسید شارژ نمایندگی #{oid}',
                f'👤 نام خریدار: {_text(user.full_name if user else None)}',
                f'🔢 آیدی عددی: {_text(user.telegram_id if user else None)}',
                f'🆔 یوزرنیم تلگرام: @{_text(user.username)}' if user and user.username else '🆔 یوزرنیم تلگرام: ندارد',
                f'📦 مورد خریداری‌شده: {_text(package.title if package else "شارژ حجم نمایندگی")}',
                f'💾 حجم: {order.volume_bytes / 1024**3:.2f} گیگابایت',
                f'💰 مبلغ: {int(order.amount_irt or 0):,} تومان',
                f'📅 تاریخ خرید: {date_label(order.created_at)}',
            ])
            actions = [('✅ تایید', f'resadmin:req_approve:{oid}'), ('❌ رد', f'resadmin:req_reject:{oid}')]
    keyboard = InlineKeyboardMarkup(inline_keyboard=[*[ [InlineKeyboardButton(text=label, callback_data=code)] for label,code in actions],
        [InlineKeyboardButton(text='🔙 رسیدهای تایید نشده', callback_data='pending_receipts:list')],
        [back_button('back:main')]])
    if file_id:
        short_caption = desc if len(desc) <= 1000 else f'🧾 رسید سفارش #{oid}؛ جزئیات کامل در پیام بعدی.'
        delivered = False
        for send in (callback.message.bot.send_photo, callback.message.bot.send_document):
            try:
                await send(uid, file_id, caption=short_caption, parse_mode='HTML', reply_markup=keyboard if len(desc) <= 1000 else None)
                delivered = True
                break
            except Exception:
                pass
        if not delivered:
            await callback.message.bot.send_message(uid, desc + '\n⚠️ فایل رسید در دسترس نیست.', parse_mode='HTML', reply_markup=keyboard)
        elif len(desc) > 1000:
            await callback.message.bot.send_message(uid, desc, parse_mode='HTML', reply_markup=keyboard)
    else:
        await callback.message.bot.send_message(uid, desc, parse_mode='HTML', reply_markup=keyboard)
    await callback.answer()
