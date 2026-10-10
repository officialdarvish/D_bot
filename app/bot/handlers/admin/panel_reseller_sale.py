"""Owner-only configuration, review, and fulfillment of PasarGuard panel sales."""
from __future__ import annotations

import logging
from datetime import datetime
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select

from app.bot.states.admin_states import PasarGuardPanelSalePrice
from app.bot.utils import edit_or_answer, ui_message
from app.core.roles import is_owner
from app.core.security import decrypt_text
from app.database.defaults import get_setting_value, set_setting_value
from app.database.models import Server, PasarGuardPanelOrder, PasarGuardPanelMeter, PaymentCard, User
from app.database.session import SessionLocal
from app.services.pasarguard_panel_sales import PanelResellerProvisioner, login_url

router = Router()
logger = logging.getLogger(__name__)


def _owner(callback):
    return is_owner(callback.from_user.id)


def _kb(*buttons):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=c)] for t, c in buttons])


@router.callback_query(F.data == 'pgadmin:settings')
async def panel_sale_settings(callback: CallbackQuery, state: FSMContext):
    if not _owner(callback):
        await callback.answer('دسترسی ندارید.', show_alert=True); return
    await state.clear()
    enabled = await get_setting_value('pasarguard_panel_sales_enabled', '0') == '1'
    price = int(await get_setting_value('pasarguard_panel_sales_price_irt', '0') or 0)
    gb = int(await get_setting_value('pasarguard_panel_sales_gb_price_irt', '0') or 0)
    hour = int(await get_setting_value('pasarguard_panel_sales_hourly_price_irt', '0') or 0)
    maximum = int(await get_setting_value('pasarguard_panel_sales_max_users', '0') or 0)
    sid = int(await get_setting_value('pasarguard_panel_sales_server_id', '0') or 0)
    async with SessionLocal() as session:
        server = await session.get(Server, sid) if sid else None
    await edit_or_answer(callback,
        f'💼 فروش پنل نمایندگی PasarGuard\n\n'
        f'وضعیت: {"🟢 فعال" if enabled else "🔴 غیرفعال"}\n'
        f'پنل: {server.name if server and server.server_type == "pasarguard" else "انتخاب نشده"}\n'
        f'قیمت خرید اولیه: {price:,} تومان {"(رایگان)" if price == 0 else ""}\n'
        f'PAYG هر گیگ: {gb:,} تومان\n'
        f'حق نمایندگی ساعتی: {hour:,} تومان\n'
        f'حداکثر تعداد کاربران: {maximum or "نامحدود"}\n\n'
        'فقط اتصال Owner پاسارگارد می‌تواند Role امن OWN و ادمین نماینده را ایجاد کند.\n'
        'برای دریافت رسید، کارت فعال از نوع نمایندگی یا متعلق به سرور انتخابی لازم است.',
        reply_markup=_kb(
            (('🔴 غیرفعال کردن' if enabled else '🟢 فعال کردن'), 'pgadmin:toggle'),
            ('🖥 انتخاب پنل PasarGuard', 'pgadmin:server'),
            ('💰 قیمت خرید اولیه / رایگان', 'pgadmin:edit:price'),
            ('📊 قیمت هر گیگ', 'pgadmin:edit:gb'),
            ('⏱ قیمت هر ساعت', 'pgadmin:edit:hour'),
            ('👥 محدودیت تعداد کاربر', 'pgadmin:edit:max'),
            ('🧾 سفارش‌های پنل', 'pgadmin:orders'),
            ('🔙 تنظیمات نمایندگان', 'admin:resellers')))
    await callback.answer()


@router.callback_query(F.data == 'pgadmin:server')
async def panel_sale_servers(callback: CallbackQuery):
    if not _owner(callback): return
    async with SessionLocal() as session:
        servers = (await session.execute(select(Server).where(Server.is_active.is_(True), Server.server_type == 'pasarguard').order_by(Server.id))).scalars().all()
    if not servers:
        await edit_or_answer(callback, 'پنل PasarGuard فعال در لیست سرورها وجود ندارد.', reply_markup=_kb(('🔙 برگشت', 'pgadmin:settings')))
    else:
        await edit_or_answer(callback, 'پنل مخصوص فروش نمایندگی را انتخاب کنید:', reply_markup=_kb(*[(f'🖥 {s.name}', f'pgadmin:setserver:{s.id}') for s in servers], ('🔙 برگشت','pgadmin:settings')))
    await callback.answer()


@router.callback_query(F.data.startswith('pgadmin:setserver:'))
async def panel_sale_set_server(callback: CallbackQuery):
    if not _owner(callback): return
    sid = int(callback.data.rsplit(':',1)[-1])
    async with SessionLocal() as session:
        server = await session.get(Server, sid)
        if not server or not server.is_active or server.server_type != 'pasarguard':
            await callback.answer('پنل معتبر نیست.', show_alert=True); return
    try:
        await PanelResellerProvisioner().require_owner(server)
        login_url(server)
    except Exception as exc:
        logger.warning('PasarGuard panel owner configuration failed server_id=%s: %s', sid, exc)
        await callback.answer('اتصال پنل باید HTTPS و با دسترسی Owner باشد.', show_alert=True); return
    await set_setting_value('pasarguard_panel_sales_server_id', str(sid))
    await set_setting_value('pasarguard_panel_sales_enabled', '0')
    await edit_or_answer(callback, '✅ پنل ثبت شد. فروش تا زمان فعال‌سازی مجدد خاموش است.', reply_markup=_kb(('⚙️ تنظیمات فروش','pgadmin:settings')))
    await callback.answer()


@router.callback_query(F.data.startswith('pgadmin:edit:'))
async def panel_sale_price(callback: CallbackQuery, state: FSMContext):
    if not _owner(callback): return
    field = callback.data.rsplit(':', 1)[-1]
    if field not in {'price', 'gb', 'hour', 'max'}:
        await callback.answer('گزینه نامعتبر است.', show_alert=True); return
    await state.clear(); await state.update_data(pg_sale_field=field); await state.set_state(PasarGuardPanelSalePrice.amount)
    await edit_or_answer(callback, 'یک عدد صحیح غیرمنفی وارد کنید. عدد ۰ برای خرید اولیه = رایگان؛ سقف کاربر ۰ = نامحدود.', reply_markup=_kb(('🔙 برگشت','pgadmin:settings')))
    await callback.answer()


@router.message(PasarGuardPanelSalePrice.amount)
async def panel_sale_price_save(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id): return
    raw = (message.text or '').strip().replace(',', '').replace(' ', '')
    data = await state.get_data()
    field = data.get('pg_sale_field')
    key = {'price': 'pasarguard_panel_sales_price_irt', 'gb': 'pasarguard_panel_sales_gb_price_irt', 'hour': 'pasarguard_panel_sales_hourly_price_irt', 'max': 'pasarguard_panel_sales_max_users'}.get(field)
    if not key or not raw.isdigit() or int(raw) > (100000 if field == 'max' else 10_000_000_000):
        await ui_message(message, 'عدد معتبر و غیرمنفی وارد کنید.'); return
    await set_setting_value(key, raw)
    await set_setting_value('pasarguard_panel_sales_enabled', '0')
    await state.clear(); await ui_message(message, f'✅ تعرفه: {int(raw):,} تومان. فروش برای ایمنی تا فعال‌سازی مجدد خاموش می‌ماند.', reply_markup=_kb(('⚙️ تنظیمات','pgadmin:settings')))


@router.callback_query(F.data == 'pgadmin:toggle')
async def panel_sale_toggle(callback: CallbackQuery):
    if not _owner(callback): return
    if await get_setting_value('pasarguard_panel_sales_enabled', '0') == '1':
        await set_setting_value('pasarguard_panel_sales_enabled', '0')
        await panel_sale_settings(callback, _NoState()); return
    try:
        sid = int(await get_setting_value('pasarguard_panel_sales_server_id', '0') or 0)
        price = int(await get_setting_value('pasarguard_panel_sales_price_irt', '0') or 0)
        async with SessionLocal() as session:
            server = await session.get(Server, sid) if sid else None
            card = (await session.execute(select(PaymentCard).where(PaymentCard.is_active.is_(True), PaymentCard.server_type == 'reseller').order_by(PaymentCard.id.desc()))).scalars().first()
            if not card and server:
                card = (await session.execute(select(PaymentCard).where(PaymentCard.is_active.is_(True), PaymentCard.server_id == server.id).order_by(PaymentCard.id.desc()))).scalars().first()
        if not server or not server.is_active or server.server_type != 'pasarguard' or price < 0 or (price > 0 and not card):
            raise RuntimeError('Panel, price and active payment card are required')
        provider = PanelResellerProvisioner()
        await provider.require_owner(server)
        login_url(server)
        # Role is validated before enabling public sales: no fallback to wide privileges.
        await provider.ensure_safe_role(server)
    except Exception as exc:
        logger.warning('PasarGuard panel sales enable rejected: %s', exc)
        await callback.answer('ابتدا پنل Owner، تعرفه، کارت پرداخت و Role امن را بررسی کنید.', show_alert=True)
        return
    await set_setting_value('pasarguard_panel_sales_enabled', '1')
    await panel_sale_settings(callback, _NoState())


class _NoState:
    async def clear(self): pass


@router.callback_query(F.data == 'pgadmin:orders')
async def panel_sale_orders(callback: CallbackQuery):
    if not _owner(callback): return
    async with SessionLocal() as session:
        orders = (await session.execute(select(PasarGuardPanelOrder).order_by(PasarGuardPanelOrder.id.desc()).limit(30))).scalars().all()
    kb = _kb(*[(f'#{o.id} | {o.username} | {o.status}',f'pgadmin:order:{o.id}') for o in orders], ('🔙 فروش پنل','pgadmin:settings'))
    await edit_or_answer(callback, '🧾 آخرین سفارش‌های پنل نمایندگی:', reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith('pgadmin:order:'))
async def panel_sale_order_detail(callback: CallbackQuery):
    if not _owner(callback): return
    oid = int(callback.data.rsplit(':',1)[-1])
    async with SessionLocal() as session:
        order = await session.get(PasarGuardPanelOrder, oid)
        user = await session.get(User, order.user_id) if order else None
    if not order:
        await callback.answer('سفارش پیدا نشد.', show_alert=True); return
    options=[]
    if order.status == 'pending':
        options = [('✅ تأیید و ساخت پنل', f'pgadmin:approve:{oid}'),('❌ رد رسید',f'pgadmin:reject:{oid}')]
    if order.status == 'delivery_pending':
        options = [('📨 ارسال دوباره مشخصات', f'pgadmin:deliver:{oid}')]
    if order.status == 'review_required':
        options = [('⚠️ ابطال پس از بررسی دستی پنل', f'pgadmin:cancelreview:{oid}')]
    await edit_or_answer(callback,
        f'سفارش پنل #{oid}\nکاربر: {user.full_name if user else "-"}\n'
        f'Telegram ID: {user.telegram_id if user else "-"}\nنام کاربری: {order.username}\n'
        f'مبلغ: {order.amount_irt:,} تومان\nوضعیت: {order.status}',
        reply_markup=_kb(*options, ('🔙 سفارش‌ها','pgadmin:orders')))
    await callback.answer()


async def _deliver(bot, oid: int) -> bool:
    async with SessionLocal() as session:
        order = await session.get(PasarGuardPanelOrder, oid)
        if not order or order.status != 'delivery_pending' or not order.password_encrypted or not order.admin_id:
            return False
        user = await session.get(User, order.user_id)
        server = await session.get(Server, order.server_id)
        password = decrypt_text(order.password_encrypted)
        destination = user.telegram_id
        text = (f'✅ پنل نمایندگی PasarGuard شما فعال شد!\n\n'
                f'🌐 لینک ورود: {login_url(server)}\n'
                f'👤 نام کاربری: {order.username}\n🔑 رمز عبور: {password}\n\n'
                '🔒 دسترسی شما محدود به ساخت، مشاهده، ویرایش، تمدید و حذف یوزرهای متعلق به خودتان است.\n'
                'پس از اولین ورود، در صورت نیاز رمز را تغییر دهید و این پیام را نزد خود محفوظ نگه دارید.')
    try:
        await bot.send_message(destination, text, parse_mode=None)
    except Exception:
        logger.exception('Could not deliver PasarGuard credentials for order %s', oid)
        return False
    async with SessionLocal() as session:
        order = await session.get(PasarGuardPanelOrder, oid, with_for_update=True)
        if order and order.status == 'delivery_pending':
            # Password remains encrypted at rest so its owner can explicitly reveal it in My Panels.
            order.status = 'approved'
            await session.commit()
    return True


@router.callback_query(F.data.startswith('pgadmin:approve:'))
async def panel_sale_approve(callback: CallbackQuery):
    if not _owner(callback):
        await callback.answer('دسترسی ندارید.', show_alert=True); return
    oid = int(callback.data.rsplit(':',1)[-1])
    async with SessionLocal() as session:
        order = await session.get(PasarGuardPanelOrder, oid, with_for_update=True)
        if not order or order.status != 'pending':
            await callback.answer('این سفارش قابل تأیید مجدد نیست.', show_alert=True); return
        server = await session.get(Server, order.server_id)
        if not server or not server.is_active or server.server_type != 'pasarguard':
            await callback.answer('پنل در دسترس نیست.', show_alert=True); return
        order.status = 'processing'
        await session.commit()
        username, password = order.username, decrypt_text(order.password_encrypted)
    await callback.answer('در حال ساخت اکانت محدود در PasarGuard...')
    try:
        result = await PanelResellerProvisioner().create_account(server, username, password, max_users=int(order.payg_max_users or 0))
    except Exception:
        logger.exception('PasarGuard panel account provisioning failed for order %s', oid)
        async with SessionLocal() as session:
            order = await session.get(PasarGuardPanelOrder, oid, with_for_update=True)
            if order and order.status == 'processing':
                # A network timeout could occur AFTER upstream creation; no blind retry.
                order.status = 'review_required'
                await session.commit()
        await callback.message.answer(f'⚠️ سفارش #{oid}: ساخت/تأیید پنل کامل نشد. قبل از هر تلاش جدید، یوزرنیم را در PasarGuard بررسی کنید. هیچ اکانت گسترده‌ای ایجاد نمی‌شود.')
        return
    async with SessionLocal() as session:
        order = await session.get(PasarGuardPanelOrder, oid, with_for_update=True)
        if not order or order.status != 'processing':
            logger.error('Panel order %s changed during provisioning; operator review required', oid)
            return
        order.admin_id = int(result['admin_id']) if result.get('admin_id') is not None else None
        if not order.admin_id:
            order.status = 'review_required'
        else:
            order.role_id = int(result['role_id'])
            order.status = 'delivery_pending'
            session.add(PasarGuardPanelMeter(order_id=order.id, gb_price_irt=int(order.payg_gb_price_irt or 0),
                hourly_price_irt=int(order.payg_hourly_price_irt or 0), max_users=int(order.payg_max_users or 0)))
            order.reviewed_by = callback.from_user.id
            order.reviewed_at = datetime.utcnow()
        await session.commit()
    if not order.admin_id:
        await callback.message.answer('⚠️ حساب ساخته شد اما Admin ID برنگشت؛ ارسال مشخصات تا بررسی متوقف است.')
        return
    sent = await _deliver(callback.message.bot, oid)
    await callback.message.answer('✅ پنل ساخته شد و مشخصات ورود ارسال شد.' if sent else
        f'⚠️ پنل ساخته شد اما ارسال تلگرام ناموفق بود؛ در سفارش #{oid} دکمه ارسال دوباره مشخصات موجود است.')
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception: pass


@router.callback_query(F.data.startswith('pgadmin:deliver:'))
async def panel_sale_deliver(callback: CallbackQuery):
    if not _owner(callback): return
    oid = int(callback.data.rsplit(':',1)[-1])
    sent = await _deliver(callback.message.bot, oid)
    await callback.answer('✅ ارسال شد.' if sent else 'ارسال ممکن نبود یا قبلاً ارسال شده است.', show_alert=True)


@router.callback_query(F.data.startswith('pgadmin:reject:'))
async def panel_sale_reject(callback: CallbackQuery):
    if not _owner(callback): return
    oid = int(callback.data.rsplit(':',1)[-1])
    async with SessionLocal() as session:
        order = await session.get(PasarGuardPanelOrder, oid, with_for_update=True)
        if not order or order.status != 'pending':
            await callback.answer('این سفارش قابل رد نیست.', show_alert=True); return
        user = await session.get(User, order.user_id)
        destination = user.telegram_id
        order.status = 'rejected'; order.password_encrypted = None
        order.reviewed_at = datetime.utcnow(); order.reviewed_by = callback.from_user.id
        await session.commit()
    try:
        await callback.message.bot.send_message(destination, f'❌ رسید خرید پنل نمایندگی (سفارش #{oid}) تأیید نشد. برای پیگیری به پشتیبانی پیام دهید.')
    except Exception: logger.exception('Failed to notify rejected panel order %s', oid)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception: pass
    await callback.answer('سفارش رد شد.', show_alert=True)


@router.callback_query(F.data.startswith('pgadmin:cancelreview:'))
async def panel_sale_cancel_failed(callback: CallbackQuery):
    """Manual terminal state only, never a blind second provisioning attempt."""
    if not _owner(callback): return
    oid = int(callback.data.rsplit(':', 1)[-1])
    async with SessionLocal() as session:
        order = await session.get(PasarGuardPanelOrder, oid, with_for_update=True)
        if not order or order.status != 'review_required':
            await callback.answer('این سفارش در وضعیت بررسی نیست.', show_alert=True); return
        order.status = 'rejected'
        order.password_encrypted = None
        order.reviewed_by = callback.from_user.id
        order.reviewed_at = datetime.utcnow()
        await session.commit()
    await callback.answer('سفارش برای بررسی دستی بسته شد. حساب احتمالی در PasarGuard را بررسی/حذف کنید.', show_alert=True)
