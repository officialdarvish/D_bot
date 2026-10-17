"""Purchase a restricted PasarGuard dashboard reseller login via card-to-card."""
from __future__ import annotations

import logging
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select, func

from app.bot.states.public_states import PasarGuardPanelPurchase, PasarGuardPanelPasswordChange
from app.bot.keyboards.common import back_button
from app.bot.utils import edit_or_answer, ui_message
from app.core.config import settings
from app.core.security import encrypt_text, decrypt_text
from app.database.defaults import get_setting_value
from app.database.models import User, Server, PaymentCard, PasarGuardPanelOrder, PasarGuardPanelMeter
from app.database.session import SessionLocal
from app.services.pasarguard_panel_sales import PanelResellerProvisioner, validate_panel_username, validate_panel_password, login_url
from app.services.pasarguard_panel_meter import PanelMeterAPI, GIB

router = Router()
log = logging.getLogger(__name__)


def _back():
    return InlineKeyboardMarkup(inline_keyboard=[[back_button('home:main')]])


async def _configuration(session):
    if await get_setting_value('pasarguard_panel_sales_enabled', '0') != '1':
        return None
    try:
        server_id = int(await get_setting_value('pasarguard_panel_sales_server_id', '0'))
        price = int(await get_setting_value('pasarguard_panel_sales_price_irt', '0'))
    except ValueError:
        return None
    server = await session.get(Server, server_id) if server_id else None
    if not server or server.server_type != 'pasarguard' or not server.is_active or price < 0:
        return None
    card = (await session.execute(select(PaymentCard).where(
        PaymentCard.is_active.is_(True),
        PaymentCard.server_type == 'reseller',
    ).order_by(PaymentCard.id.desc()))).scalars().first()
    if not card:
        card = (await session.execute(select(PaymentCard).where(
            PaymentCard.is_active.is_(True), PaymentCard.server_id == server.id,
        ).order_by(PaymentCard.id.desc()))).scalars().first()
    if not card and price > 0:
        return None
    return server, price, card


async def show_panel_sale(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    async with SessionLocal() as session:
        conf = await _configuration(session)
        user = (await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one_or_none()
        orders = (await session.execute(select(PasarGuardPanelOrder)
                 .where(PasarGuardPanelOrder.user_id == user.id, PasarGuardPanelOrder.status.in_(['pending','processing','delivery_pending','review_required']))
                 .order_by(PasarGuardPanelOrder.id.desc()))).scalars().all() if user else []
    if orders:
        order = orders[0]
        status = {'pending': 'در انتظار بررسی رسید', 'processing':'در حال ساخت پنل', 'approved':'تکمیل‌شده', 'delivery_pending':'در انتظار ارسال مشخصات', 'review_required':'نیازمند بررسی مدیر'}.get(order.status, order.status)
        await edit_or_answer(callback,
            f'💼 سفارش پنل نمایندگی پاسارگارد #{order.id}\n\n👤 نام کاربری: {order.username}\n📌 وضعیت: {status}\n\nدر صورت نیاز به پیگیری، با پشتیبانی ارتباط بگیرید.', reply_markup=_back())
        await callback.answer(); return
    if not conf:
        await edit_or_answer(callback, '❌ فروش پنل نمایندگی پاسارگارد هنوز به‌طور کامل توسط مدیر پیکربندی نشده است.', reply_markup=_back())
        await callback.answer(); return
    server, price, card = conf
    await edit_or_answer(callback,
        f'🛒 خرید پنل نمایندگی PasarGuard\n\n🖥 پنل: {server.name}\n💰 خرید اولیه: {price:,} تومان\n'
        f'📊 هر گیگ: {int(await get_setting_value("pasarguard_panel_sales_gb_price_irt", "0")):,} تومان\n'
        f'⏱ هر ساعت: {int(await get_setting_value("pasarguard_panel_sales_hourly_price_irt", "0")):,} تومان\n'
        f'👥 سقف کاربر: {int(await get_setting_value("pasarguard_panel_sales_max_users", "0")) or "نامحدود"}\n\n'
        '🔐 پنل دارای دسترسی محدود است: ایجاد، مشاهده، ویرایش، تمدید و حذف فقط کاربران ساخته‌شده توسط خودتان. '
        'دسترسی به کاربران دیگر، نودها یا تنظیمات اصلی پنل داده نمی‌شود.\n\n'
        'برای شروع، روی دکمه زیر بزنید.',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='✅ شروع خرید و انتخاب یوزرنیم', callback_data='pgsale:start')],
            [back_button('home:main')]]))
    await callback.answer()


@router.callback_query(F.data == 'pgsale:shop')
async def show_panel_shop(callback: CallbackQuery, state: FSMContext):
    await show_panel_sale(callback, state)


@router.callback_query(F.data == 'pgsale:start')
async def purchase_start(callback: CallbackQuery, state: FSMContext):
    async with SessionLocal() as session:
        conf = await _configuration(session)
    if not conf:
        await callback.answer('فروش غیرفعال یا ناقص است.', show_alert=True); return
    await state.clear()
    await state.set_state(PasarGuardPanelPurchase.username)
    await edit_or_answer(callback,
        '👤 نام کاربری پنل را بنویسید.\n\nقالب مجاز: ۴ تا ۳۲ کاراکتر انگلیسی، شروع با حرف، سپس حروف، اعداد یا زیرخط (_).\n'
        'نام کاربری با خود پنل PasarGuard بررسی می‌شود و نباید تکراری باشد.', reply_markup=_back())
    await callback.answer()


@router.message(PasarGuardPanelPurchase.username)
async def purchase_username(message: Message, state: FSMContext):
    username = (message.text or '').strip()
    if not validate_panel_username(username):
        await ui_message(message, '❌ نام کاربری نامعتبر است. ۴ تا ۳۲ کاراکتر انگلیسی و عدد/زیرخط، با شروع حرف وارد کنید.')
        return
    async with SessionLocal() as session:
        conf = await _configuration(session)
        if not conf:
            await ui_message(message, 'فروش پنل در حال حاضر فعال نیست.'); await state.clear(); return
        server, _, _ = conf
        reserved = (await session.execute(select(PasarGuardPanelOrder.id).where(
            PasarGuardPanelOrder.server_id == server.id,
            func.lower(PasarGuardPanelOrder.username) == username.lower(),
            PasarGuardPanelOrder.status.in_(['pending','processing','delivery_pending','approved','review_required'])
        ))).first()
    if reserved:
        await ui_message(message, '❌ این نام کاربری قبلاً انتخاب شده است. نام دیگری وارد کنید.'); return
    try:
        available = await PanelResellerProvisioner().username_available(server, username)
    except Exception:
        log.exception('PasarGuard username check failed for server_id=%s', server.id)
        await ui_message(message, '⚠️ بررسی یوزرنیم از پنل پاسارگارد ممکن نشد. لطفاً بعداً دوباره تلاش کنید.'); return
    if not available:
        await ui_message(message, '❌ این نام کاربری در PasarGuard وجود دارد. یک نام دیگر وارد کنید.'); return
    await state.update_data(pg_username=username, pg_server_id=server.id)
    await state.set_state(PasarGuardPanelPurchase.password)
    await ui_message(message,
        '🔑 رمز عبور پنل خود را بنویسید.\n\nرمز باید حداقل **۱۲ کاراکتر** داشته باشد و شامل تمام موارد زیر باشد:\n'
        '• حداقل دو حرف کوچک انگلیسی (a-z)\n• حداقل دو حرف بزرگ انگلیسی (A-Z)\n• حداقل دو عدد (0-9)\n• نماد مجاز (مثل ! @ # $)\n\n'
        'فاصله مجاز نیست. پیام حاوی رمز پس از دریافت حذف می‌شود.')


@router.message(PasarGuardPanelPurchase.password)
async def purchase_password(message: Message, state: FSMContext):
    password = message.text or ''
    try:
        await message.delete()
    except Exception:
        pass
    if not validate_panel_password(password):
        await ui_message(message, '❌ رمز معتبر نیست. حداقل ۱۲ کاراکتر با دست‌کم دو حرف کوچک، دو حرف بزرگ، دو رقم و یک نماد مجاز بدون فاصله الزامی است. دوباره وارد کنید.'); return
    data = await state.get_data()
    async with SessionLocal() as session:
        conf = await _configuration(session)
    if not conf or conf[0].id != data.get('pg_server_id'):
        await ui_message(message, 'تنظیمات فروش تغییر کرده است؛ لطفاً خرید را دوباره آغاز کنید.'); await state.clear(); return
    server, price, card = conf
    await state.update_data(pg_password_encrypted=encrypt_text(password), pg_price=price, pg_card_id=card.id if card else None)
    if price == 0:
        order_id = await _store_panel_order(message, state, receipt_file_id='FREE', free=True)
        if order_id:
            await ui_message(message, f'✅ سفارش رایگان #{order_id} ثبت شد و در انتظار تأیید مدیر است.', reply_markup=_back())
        return
    await state.set_state(PasarGuardPanelPurchase.receipt)
    await ui_message(message,
        f'💳 پرداخت کارت‌به‌کارت پنل نمایندگی\n\n🖥 پنل: {server.name}\n👤 نام کاربری: {data["pg_username"]}\n'
        f'💰 مبلغ: {price:,} تومان\n💳 شماره کارت: {card.card_number}\n👤 صاحب حساب: {card.owner_name}\n\n'
        'پس از پرداخت، عکس یا فایل رسید را همینجا ارسال کنید. دسترسی صرفاً پس از تأیید مدیر و ساخت موفق اکانت فعال خواهد شد.',
        reply_markup=_back())


async def _store_panel_order(message: Message, state: FSMContext, receipt_file_id: str, free: bool = False) -> int | None:
    data = await state.get_data()
    async with SessionLocal() as session:
        conf = await _configuration(session)
        if not conf or conf[0].id != data.get('pg_server_id') or conf[1] != data.get('pg_price') or (conf[2].id if conf[2] else None) != data.get('pg_card_id'):
            await ui_message(message, 'اطلاعات فروش تغییر کرده است؛ خرید را مجدداً آغاز کنید.'); await state.clear(); return None
        user = (await session.execute(select(User).where(User.telegram_id == message.from_user.id))).scalar_one_or_none()
        if not user:
            user = User(telegram_id=message.from_user.id, username=message.from_user.username, full_name=message.from_user.full_name)
            session.add(user); await session.flush()
        await session.execute(select(Server).where(Server.id == conf[0].id).with_for_update())
        reserved = (await session.execute(select(PasarGuardPanelOrder.id).where(
            PasarGuardPanelOrder.server_id == conf[0].id,
            func.lower(PasarGuardPanelOrder.username) == data.get('pg_username', '').lower(),
            PasarGuardPanelOrder.status.in_(['pending','processing','delivery_pending','approved','review_required'])
        ))).first()
        existing = (await session.execute(select(PasarGuardPanelOrder.id).where(
            PasarGuardPanelOrder.user_id == user.id,
            PasarGuardPanelOrder.status.in_(['pending','processing','delivery_pending','review_required'])
        ))).first()
        if reserved or existing:
            await ui_message(message, '⚠️ یک سفارش با این نام یا برای همین کاربر در جریان است.'); await state.clear(); return None
        gb_price = max(0, int(await get_setting_value('pasarguard_panel_sales_gb_price_irt', '0') or 0))
        hourly_price = max(0, int(await get_setting_value('pasarguard_panel_sales_hourly_price_irt', '0') or 0))
        max_users = max(0, int(await get_setting_value('pasarguard_panel_sales_max_users', '0') or 0))
        order = PasarGuardPanelOrder(user_id=user.id, server_id=conf[0].id,
            username=data['pg_username'], password_encrypted=data['pg_password_encrypted'],
            amount_irt=conf[1], payg_gb_price_irt=gb_price, payg_hourly_price_irt=hourly_price,
            payg_max_users=max_users, card_id=conf[2].id if conf[2] else None,
            receipt_file_id=receipt_file_id, status='pending')
        session.add(order); await session.commit(); await session.refresh(order)
        oid, username, price = order.id, order.username, order.amount_irt
    await state.clear()
    buttons = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ تأیید و ساخت اکانت محدود', callback_data=f'pgadmin:approve:{oid}')],
        [InlineKeyboardButton(text='❌ رد درخواست', callback_data=f'pgadmin:reject:{oid}')],
    ])
    for admin_id in sorted(set(settings.owner_ids)):
        try:
            if not free:
                await message.bot.copy_message(admin_id, message.chat.id, message.message_id)
            await message.bot.send_message(admin_id,
                f'🧾 درخواست خرید پنل نمایندگی PasarGuard #{oid}\n'
                f'کاربر: {message.from_user.full_name}\nTelegram ID: {message.from_user.id}\n'
                f'یوزرنیم: {username}\nقیمت اولیه: {price:,} تومان\n'
                f'هر GB: {gb_price:,} تومان | هر ساعت: {hourly_price:,} تومان\n'
                f'حداکثر کاربر: {max_users or "نامحدود"}\n'
                + ('ثبت نام رایگان؛ بدون رسید پرداخت.' if free else 'لطفاً رسید را بررسی کنید.'), reply_markup=buttons)
        except Exception:
            log.exception('Failed to notify owner %s of PasarGuard panel order %s', admin_id, oid)
    return oid


@router.message(PasarGuardPanelPurchase.receipt)
async def purchase_receipt(message: Message, state: FSMContext):
    fid = (message.photo[-1].file_id if message.photo else
           message.document.file_id if message.document else None)
    if not fid:
        await ui_message(message, 'لطفاً تصویر یا فایل رسید کارت‌به‌کارت را ارسال کنید.'); return
    oid = await _store_panel_order(message, state, receipt_file_id=fid)
    if oid:
        await ui_message(message, f'✅ رسید ثبت شد (سفارش #{oid}). پس از تأیید مدیر، لینک ورود و مشخصات ارسال می‌شود.', reply_markup=_back())




async def _owned_panel(telegram_id: int, order_id: int):
    async with SessionLocal() as session:
        user = (await session.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one_or_none()
        order = (await session.execute(select(PasarGuardPanelOrder).where(
            PasarGuardPanelOrder.id == order_id, PasarGuardPanelOrder.user_id == user.id,
            PasarGuardPanelOrder.status.in_(['approved', 'delivery_pending'])))).scalar_one_or_none() if user else None
        if not order:
            raise ValueError('پنل معتبر یا متعلق به شما نیست.')
        server = await session.get(Server, order.server_id)
        meter = (await session.execute(select(PasarGuardPanelMeter).where(PasarGuardPanelMeter.order_id == order.id))).scalar_one_or_none()
        return user, order, server, meter


@router.callback_query(F.data == 'pgsale:panels')
async def purchased_panels(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    async with SessionLocal() as session:
        user = (await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one_or_none()
        rows = (await session.execute(select(PasarGuardPanelOrder).where(
            PasarGuardPanelOrder.user_id == user.id,
            PasarGuardPanelOrder.status.in_(['approved', 'delivery_pending']))
            .order_by(PasarGuardPanelOrder.id.desc()))).scalars().all() if user else []
    if not rows:
        await edit_or_answer(callback, 'هنوز پنل نمایندگی PasarGuard خریداری‌شده‌ای ندارید.', reply_markup=_back())
    else:
        await edit_or_answer(callback, '🌐 ورود به پنل نمایندگی (وب سایت)\n\nنام کاربری پنل موردنظر را انتخاب کنید:',
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                *[[InlineKeyboardButton(text=f'👤 {row.username}', callback_data=f'pgsale:panel:{row.id}')] for row in rows],
                [back_button('home:main')]]))
    await callback.answer()


@router.callback_query(F.data.startswith('pgsale:panel:'))
async def purchased_panel_detail(callback: CallbackQuery, state: FSMContext, panel_id: int | None = None):
    try:
        oid = panel_id if panel_id is not None else int(callback.data.rsplit(':',1)[-1])
        user, order, server, meter = await _owned_panel(callback.from_user.id, oid)
    except (ValueError, TypeError):
        await callback.answer('پنل معتبر نیست یا دسترسی ندارید.', show_alert=True); return
    # Presentation reads the most recent durable meter checkpoint. Refresh is
    # available below; it first polls the panel and may debit usage.
    traffic_gb = (int(meter.traffic_bytes or 0) / GIB) if meter else 0
    cap_gb = ('نامحدود (پرداخت به میزان مصرف)' if meter else 'نامشخص')
    wallet = int(user.wallet_balance or 0)
    remaining_gb = (f'{wallet / int(meter.gb_price_irt):.2f} GB اعتبار تقریبی' if meter and meter.gb_price_irt else 'وابسته به هزینه ساعتی')
    traffic_cost = int(meter.billed_traffic_irt or 0) if meter else 0
    hours = (int(meter.billable_seconds or 0) / 3600) if meter else 0
    hourly_cost = int(meter.billed_hours_irt or 0) if meter else 0
    status = '🔴 غیرفعال (اتمام اعتبار)' if meter and meter.suspended else '🟢 فعال'
    if meter and meter.last_error:
        status += '\n⚠️ آخرین خطای همگام‌سازی: ' + meter.last_error[:100]
    text = (
        '👤 اطلاعات نمایندگی:\n\n'
        f'• نام کاربری: {order.username}\n'
        f'• رمز عبور: 🔒 محفوظ (برای نمایش دکمه مشخصات رمز را بزنید)\n'
        f'• وضعیت: {status}\n'
        f'• محدودیت کاربر: {meter.max_users or "نامحدود" if meter else "نامشخص"}\n\n'
        '📊 ترافیک (GB):\n'
        f'• مصرف: {traffic_gb:.3f} | سقف: {cap_gb}\n'
        f'• مانده: {remaining_gb}\n'
        f'• هزینه: {traffic_cost:,} تومان (هر گیگ: {int(meter.gb_price_irt or 0) if meter else 0:,})\n\n'
        '💼 حق نمایندگی:\n'
        '• انقضاء: بدون تاریخ ثابت (تا موجودی کیف پول)\n'
        f'• کارکرد: {hours:.2f} ساعت\n'
        f'• هزینه: {hourly_cost:,} تومان (ساعتی: {int(meter.hourly_price_irt or 0) if meter else 0:,})\n\n'
        f'💰 موجودی کیف پول: {wallet:,} تومان\n'
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🌐 ورود به پنل', url=login_url(server))],
        [InlineKeyboardButton(text='🔑 نمایش رمز عبور', callback_data=f'pgsale:password:{oid}')],
        [InlineKeyboardButton(text='🔐 تغییر رمز عبور', callback_data=f'pgsale:changepass:{oid}')],
        [InlineKeyboardButton(text='⛔ غیرفعال‌سازی کاربران', callback_data=f'pgsale:disable:{oid}')],
        [InlineKeyboardButton(text='✅ فعال‌سازی کاربران', callback_data=f'pgsale:enable:{oid}')],
        [InlineKeyboardButton(text='🔄 بروزرسانی مصرف و هزینه', callback_data=f'pgsale:refresh:{oid}')],
        [InlineKeyboardButton(text='🔙 پنل‌های خریداری‌شده', callback_data='pgsale:panels')],
    ])
    await edit_or_answer(callback, text, reply_markup=kb, parse_mode=None)
    await callback.answer()


@router.callback_query(F.data.startswith('pgsale:password:'))
async def panel_show_password(callback: CallbackQuery):
    try:
        oid = int(callback.data.rsplit(':', 1)[-1])
        _, order, _, _ = await _owned_panel(callback.from_user.id, oid)
    except (ValueError, TypeError):
        await callback.answer('پنل متعلق به شما نیست.', show_alert=True); return
    # Never expose a reseller password in a shared Telegram group/channel.
    if callback.message.chat.type != 'private':
        await callback.answer('نمایش رمز فقط در گفتگوی خصوصی ربات مجاز است.', show_alert=True); return
    if not order.password_encrypted:
        await callback.answer('رمز قبلی در نسخه قدیمی ذخیره نشده؛ از تغییر رمز استفاده کنید.', show_alert=True); return
    try:
        await callback.message.answer('🔐 رمز ورود پنل «' + order.username + '»:\n' + decrypt_text(order.password_encrypted),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='🔙 پنل', callback_data=f'pgsale:panel:{oid}')]]), parse_mode=None)
    except Exception:
        await callback.answer('ارسال پیام خصوصی رمز ممکن نشد.', show_alert=True); return
    await callback.answer()


@router.callback_query(F.data.startswith('pgsale:changepass:'))
async def panel_password_start(callback: CallbackQuery, state: FSMContext):
    try:
        oid = int(callback.data.rsplit(':',1)[-1])
        await _owned_panel(callback.from_user.id, oid)
    except (ValueError, TypeError):
        await callback.answer('پنل معتبر نیست.', show_alert=True); return
    await state.clear()
    await state.update_data(panel_order_id=oid)
    await state.set_state(PasarGuardPanelPasswordChange.new_password)
    await edit_or_answer(callback, '🔑 رمز جدید را ارسال کنید: حداقل ۱۲ کاراکتر، ۲ حرف بزرگ، ۲ حرف کوچک، ۲ عدد و یک نماد. پیام رمز حذف خواهد شد.', reply_markup=_back())
    await callback.answer()


@router.message(PasarGuardPanelPasswordChange.new_password)
async def panel_password_finish(message: Message, state: FSMContext):
    raw = message.text or ''
    try: await message.delete()
    except Exception: pass
    if not validate_panel_password(raw):
        await ui_message(message, 'رمز معتبر نیست؛ فرمت ۱۲ کاراکتری با حروف بزرگ/کوچک، عدد و نماد را رعایت کنید.'); return
    oid = int((await state.get_data()).get('panel_order_id') or 0)
    try:
        _, order, server, _ = await _owned_panel(message.from_user.id, oid)
        await PanelMeterAPI().change_password(server, order, raw)
    except Exception:
        log.exception('PasarGuard password change failed order=%s', oid)
        await ui_message(message, '⚠️ تغییر رمز در پنل ناموفق بود. لطفاً دوباره تلاش کنید.'); return
    async with SessionLocal() as session:
        order = await session.get(PasarGuardPanelOrder, oid, with_for_update=True)
        if order:
            order.password_encrypted = encrypt_text(raw)
            await session.commit()
    await state.clear()
    await ui_message(message, '✅ رمز ورود PasarGuard با موفقیت تغییر کرد.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🌐 پنل خریداری‌شده', callback_data=f'pgsale:panel:{oid}')]]))


@router.callback_query(F.data.startswith('pgsale:refresh:'))
async def panel_refresh(callback: CallbackQuery, state: FSMContext):
    try:
        oid = int(callback.data.rsplit(':', 1)[-1])
        await _owned_panel(callback.from_user.id, oid)
        await PanelMeterAPI().poll(oid, bot=callback.bot)
    except Exception:
        log.exception('PasarGuard PAYG refresh failed')
        await callback.answer('⚠️ خواندن مصرف از پنل ناموفق بود؛ هزینه‌ای بابت این بروزرسانی ثبت نشد.', show_alert=True); return
    await purchased_panel_detail(callback, state, panel_id=oid)


@router.callback_query(F.data.startswith('pgsale:disable:'))
async def panel_disable(callback: CallbackQuery):
    try:
        oid = int(callback.data.rsplit(':', 1)[-1])
        _, order, server, meter = await _owned_panel(callback.from_user.id, oid)
        # Never disable users outside the purchased admin ownership scope.
        api = PanelMeterAPI()
        owned_ids = {int(u['id']) for u in await api.list_own_users(server, order)}
        ids = await api.set_users(server, order, False)
        if meter and owned_ids:
            # Explicit owner disable takes precedence over automatic restoration.
            async with SessionLocal() as session:
                m = (await session.execute(select(PasarGuardPanelMeter).where(PasarGuardPanelMeter.order_id == oid).with_for_update())).scalar_one()
                m.auto_disabled_user_ids = [i for i in (m.auto_disabled_user_ids or []) if i not in owned_ids]
                await session.commit()
        await callback.answer(f'✅ {len(ids)} کاربر غیرفعال شد.', show_alert=True)
    except Exception:
        log.exception('Reseller panel disable failed')
        await callback.answer('⚠️ غیرفعال‌سازی از پنل PasarGuard ناموفق بود.', show_alert=True)


@router.callback_query(F.data.startswith('pgsale:enable:'))
async def panel_enable(callback: CallbackQuery):
    try:
        oid = int(callback.data.rsplit(':', 1)[-1])
        user, order, server, meter = await _owned_panel(callback.from_user.id, oid)
        if meter and meter.suspended:
            count = await PanelMeterAPI().resume(oid)
        else:
            if meter and int(user.wallet_balance or 0) <= 0 and (meter.gb_price_irt or meter.hourly_price_irt):
                raise ValueError('کیف پول خالی است.')
            count = len(await PanelMeterAPI().set_users(server, order, True))
        await callback.answer(f'✅ {count} کاربر فعال شد.', show_alert=True)
    except ValueError as exc:
        await callback.answer(str(exc), show_alert=True)
    except Exception:
        log.exception('Reseller panel activation failed')
        await callback.answer('⚠️ فعال‌سازی از پنل PasarGuard ناموفق بود.', show_alert=True)
