from datetime import datetime, timedelta
import asyncio, contextlib
import tempfile, qrcode
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile
from sqlalchemy import select, update, delete
from app.database.session import SessionLocal
from app.database.models import User, ClientService, Plan, Server, Order, PaymentCard, PaygUsageLog, TestAccountUsage, AntiSharingViolation
from app.bot.keyboards.common import CB_MY_SERVICES, back_button, back_main_inline
from app.services.xui_service import XuiService
from app.bot.utils import edit_or_answer
from app.bot.error_reporting import handle_user_facing_error
from app.services.plan_order import saved_plan_order, sort_by_saved_order

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
def fa_date(dt): return dt.date().isoformat() if dt else 'نامحدود'

def install_text(sub_link: str) -> str:
    return (f"📲 نحوه اتصال:\n{sub_link}\n\n"
            "✅ آموزش Happ:\n"
            "1) برنامه Happ را باز کنید.\n"
            "2) روی دکمه + بزنید.\n"
            "3) گزینه Import / Subscription را انتخاب کنید.\n"
            "4) لینک بالا را وارد کنید و ذخیره بزنید.\n\n"
            "✅ آموزش V2rayNG:\n"
            "1) لینک بالا را کامل کپی کنید.\n"
            "2) داخل برنامه V2rayNG روی + بزنید.\n"
            "3) گزینه Subscription group setting را باز کنید.\n"
            "4) لینک را اضافه کنید و Update subscription را بزنید.")

def percent_bar(used: int, total: int, width: int = 10) -> str:
    if not total or total <= 0:
        return '▰' * width
    ratio = max(0, min(1, (used or 0) / total))
    filled = int(round(ratio * width))
    return '▰' * filled + '▱' * (width - filled)

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
    await session.execute(delete(AntiSharingViolation).where(AntiSharingViolation.service_id == svc.id))
    await session.execute(delete(PaygUsageLog).where(PaygUsageLog.service_id == svc.id))
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
    if not svc or not server or server.server_type != 'xui':
        return None
    try:
        found = await XuiService().find_client_any(server, svc.xui_email)
        if not found:
            if delete_missing:
                await delete_local_service_records(session, svc)
                await session.commit()
            else:
                svc.is_active = False
                await session.commit()
            return False
        c = found.get('client') or {}
        tr = found.get('traffic') or {}
        used = (tr.get('up', 0) or 0) + (tr.get('down', 0) or 0)
        total = tr.get('total') or c.get('totalGB') or svc.total_bytes
        svc.used_bytes = used
        svc.total_bytes = total or svc.total_bytes
        svc.is_active = bool(c.get('enable', svc.is_active))
        subid = c.get('subId') or svc.xui_email
        svc.sub_link = XuiService().build_subscription_link(server, subid, svc.xui_email)
        await session.commit()
        return True
    except Exception:
        # Do not delete anything when the panel is temporarily unavailable.
        return None

def detail_kb(svc, plan):
    remain=max((svc.total_bytes or 0)-(svc.used_bytes or 0),0)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f'{plan.title if plan else "نامشخص"}', callback_data='noop'), InlineKeyboardButton(text='🚀 نام پلن', callback_data='noop')],
        [InlineKeyboardButton(text=f'{fa_date(svc.created_at)}', callback_data='noop'), InlineKeyboardButton(text='⏰ تاریخ خرید', callback_data='noop')],
        [InlineKeyboardButton(text=f'{fa_date(svc.expires_at)}', callback_data='noop'), InlineKeyboardButton(text='⏰ تاریخ انقضا', callback_data='noop')],
        [InlineKeyboardButton(text=f'{gb(remain):.2f} گیگ', callback_data='noop'), InlineKeyboardButton(text='⏳ حجم باقیمانده', callback_data='noop')],
        [InlineKeyboardButton(text='♻️ بروزرسانی کانفیگ', callback_data=f'svc:refresh:{svc.id}'), InlineKeyboardButton(text='🔄 باطل کردن لینک و ارسال لینک جدید', callback_data=f'svc:revoke:{svc.id}')],
        [InlineKeyboardButton(text='💳 تمدید سرویس', callback_data=f'svc:renew_menu:{svc.id}'), InlineKeyboardButton(text='🗑 حذف کانفیگ', callback_data=f'svc:delete:{svc.id}')],
        [back_button('menu:my_services')]
    ])

def service_detail_text(svc, plan) -> str:
    used = svc.used_bytes or 0
    total = svc.total_bytes or 0
    remain = max(total - used, 0)
    pct = int((used / total) * 100) if total else 0
    status_icon = '🟢' if svc.is_active else '🔴'
    status_text = 'فعال' if svc.is_active else 'غیرفعال'
    plan_title = plan.title if plan else 'نامشخص'
    link = svc.sub_link or 'ثبت نشده'
    return (
        '✅ کانفیگ با مشخصات زیر پیدا شد\n'
        '╭━━━━━━━━━━━━━━━━━━━━╮\n'
        f'│ 🚀 نام کانفیگ: {svc.client_username}\n'
        f'│ {status_icon} وضعیت: {status_text}\n'
        f'│ 📦 پلن انتخابی: {plan_title}\n'
        '╰━━━━━━━━━━━━━━━━━━━━╯\n\n'
        '📅 زمان‌بندی سرویس\n'
        f'├ 🛒 تاریخ خرید: {fa_date(svc.created_at)}\n'
        f'├ 🟢 شروع استفاده: {fa_date(svc.created_at)}\n'
        f'╰ ⏳ تاریخ انقضا: {fa_date(svc.expires_at)}\n\n'
        '📊 وضعیت مصرف\n'
        f'├ 💾 حجم کل: {gb(total):.2f} گیگ\n'
        f'├ 📈 مصرف‌شده: {gb(used):.2f} گیگ\n'
        f'├ ⏳ باقی‌مانده: {gb(remain):.2f} گیگ\n'
        f'╰ {percent_bar(used, total, 14)} {pct}%\n\n'
        '🔗 لینک اتصال\n'
        f'{link}\n\n'
        '📲 آموزش Happ\n'
        '1) برنامه Happ را باز کنید.\n'
        '2) روی دکمه + بزنید.\n'
        '3) Import / Subscription را انتخاب کنید.\n'
        '4) لینک بالا را وارد و ذخیره کنید.\n\n'
        '📲 آموزش V2rayNG\n'
        '1) لینک بالا را کامل کپی کنید.\n'
        '2) داخل V2rayNG روی + بزنید.\n'
        '3) Subscription group setting را باز کنید.\n'
        '4) لینک را اضافه و Update subscription را بزنید.\n\n'
        '♻️ اطلاعات هر ۳ ثانیه روی همین پیام بروزرسانی می‌شود.\n'
        '— ✦ Darvish D Bot ✦ —'
    )


def is_plain_service_callback(data: str | None) -> bool:
    if not data or not data.startswith('svc:'):
        return False
    parts = data.split(':')
    return len(parts) == 2 and parts[1].isdigit()

async def render_detail(callback: CallbackQuery, sid: int):
    async with SessionLocal() as session:
        svc = await session.get(ClientService, sid)
        if not svc:
            await callback.answer('پیدا نشد', show_alert=True)
            return
        if getattr(svc, 'reseller_id', None):
            # Reseller-created customer configs must not be opened from the normal
            # "My configs" page. They belong to the reseller users section.
            await edit_or_answer(
                callback,
                'این کانفیگ مربوط به بخش نمایندگی است.\nاز مسیر «منو نمایندگی → یوزرها» مدیریت کنید.',
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('menu:reseller')], [back_button('menu:my_services')]])
            )
            return
        sync_result = await sync_service_from_panel(session, svc, delete_missing=True)
        if sync_result is False:
            await edit_or_answer(callback, '⚠️ این کانفیگ قبلاً از داخل پنل حذف شده بود؛ رکورد باقی‌مانده از داخل ربات هم پاک شد.', reply_markup=back_main_inline())
            return
        plan = await session.get(Plan, svc.plan_id) if svc.plan_id else None
    await edit_or_answer(callback, service_detail_text(svc, plan), reply_markup=detail_kb(svc, plan))

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
                sync_result = await sync_service_from_panel(session, svc, delete_missing=True)
                if sync_result is False:
                    text = '⚠️ این کانفیگ دیگر داخل پنل وجود ندارد و از لیست ربات حذف شد.'
                    kb = back_main_inline()
                    with contextlib.suppress(Exception):
                        await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=kb)
                    return
                plan = await session.get(Plan, svc.plan_id) if svc.plan_id else None
                text = service_detail_text(svc, plan)
                kb = detail_kb(svc, plan)
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
        services = (await session.execute(
            select(ClientService)
            .where(ClientService.user_id == user.id)
            .where(ClientService.reseller_id.is_(None))
            .where(ClientService.is_active == True)
            .order_by(ClientService.id.desc())
        )).scalars().all()
        # RAM/CPU friendly: do not sync every service from panel on list open.
        # Individual service refresh still happens inside service detail actions.
    if not services:
        await edit_or_answer(event, '📭 شما هنوز هیچ کانفیگی خریداری نکرده‌اید.', reply_markup=back_main_inline()); await event.answer(); return
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f'{s.client_username}', callback_data=f'svc:{s.id}')] for s in services] + [[InlineKeyboardButton(text='🔙 بازگشت', callback_data='back:main')]])
    await edit_or_answer(event, '📱 کانفیگ‌های من\n\nیکی از سرویس‌ها را انتخاب کنید:', reply_markup=kb); await event.answer()

@router.callback_query(lambda c: is_plain_service_callback(c.data))
async def service_detail(callback: CallbackQuery):
    sid = int(callback.data.split(':')[1])
    if callback.message:
        cancel_auto_refresh(callback.message.chat.id, None)
    await render_detail(callback, sid)
    if callback.message:
        asyncio.create_task(auto_refresh_service_page(callback.message.bot, callback.message.chat.id, callback.message.message_id, sid))
    await callback.answer()

@router.callback_query(F.data.startswith('svc:revoke:'))
async def revoke_service(callback: CallbackQuery):
    if callback.message:
        cancel_auto_refresh(callback.message.chat.id, callback.message.message_id)
    sid=int(callback.data.split(':')[-1])
    detail_text = None
    detail_markup = None
    async with SessionLocal() as session:
        svc=await session.get(ClientService,sid); server=await session.get(Server,svc.server_id) if svc else None
        if not svc or not server:
            await callback.answer('پیدا نشد', show_alert=True); return
        try:
            new=await XuiService().revoke_and_new_link(server, svc.xui_email)
            svc.xui_uuid=(str(new.get('uuid')) if isinstance(new, dict) and new.get('uuid') is not None else None)
            svc.sub_link=new.get('sub_link')
            await session.commit()
            await session.refresh(svc)
            sub=svc.sub_link
            plan = await session.get(Plan, svc.plan_id) if svc.plan_id else None
            detail_text = service_detail_text(svc, plan)
            detail_markup = detail_kb(svc, plan)
        except Exception as e:
            await handle_user_facing_error(callback, e, context='User revoke/regenerate service link failed', reply_markup=back_main_inline()); await callback.answer(); return
    # First send the renewed config card. Then send a second message that opens
    # the same service detail page from "My configs" for the revoked service.
    if sub and callback.message:
        img = qrcode.make(sub)
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
        img.save(tmp.name)
        await callback.message.answer_photo(
            FSInputFile(tmp.name),
            caption='✅ لینک جدید با موفقیت ساخته شد.\n\n' + install_text(sub),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text='🏠 خانه', callback_data='back:main')]
            ]),
        )
        if detail_text and detail_markup:
            detail_msg = await callback.message.answer(detail_text, reply_markup=detail_markup)
            asyncio.create_task(auto_refresh_service_page(callback.message.bot, callback.message.chat.id, detail_msg.message_id, sid))

    await callback.answer('✅ لینک جدید ارسال شد')

@router.callback_query(F.data.startswith('svc:refresh:'))
async def refresh_service(callback: CallbackQuery):
    sid=int(callback.data.split(':')[-1])
    await render_detail(callback, sid)
    await callback.answer('✅ بروزرسانی شد')

@router.callback_query(F.data.startswith('svc:renew_menu:'))
async def renew_menu(callback: CallbackQuery):
    if callback.message:
        cancel_auto_refresh(callback.message.chat.id, callback.message.message_id)
    sid=int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        svc=await session.get(ClientService,sid)
        plans=(await session.execute(select(Plan).where(Plan.server_id == svc.server_id, Plan.is_active == True))).scalars().all()
        plans=sort_by_saved_order(plans, await saved_plan_order(session, 'public'))
    rows=[
        [InlineKeyboardButton(text='💳 تمدید همین سرویس با کارت', callback_data=f'svc:renew_card:{sid}')],
        [InlineKeyboardButton(text='💎 تمدید همین سرویس با کیف پول', callback_data=f'svc:renew_wallet:{sid}')],
    ]
    for p in plans:
        rows.append([InlineKeyboardButton(text=f'🔁 {p.title} | {p.price_irt:,} تومان', callback_data=f'svc:change_plan:{sid}:{p.id}')])
    rows.append([back_button(f'svc:{sid}')])
    await edit_or_answer(callback, '🔄 تمدید سرویس\n\nروش پرداخت یا پلن جدید را انتخاب کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)); await callback.answer()

@router.callback_query(F.data.startswith('svc:change_plan:'))
async def change_plan(callback: CallbackQuery):
    _,_,sid,pid=callback.data.split(':'); sid=int(sid); pid=int(pid)
    async with SessionLocal() as session:
        svc=await session.get(ClientService,sid); plan=await session.get(Plan,pid); server=await session.get(Server, svc.server_id)
        if svc.plan_id == pid:
            await callback.answer('شما در همین لحظه از همین تعرفه استفاده می‌کنید. برای تمدید، گزینه تمدید همین سرویس را بزنید.', show_alert=True); return
        if server.server_type == 'xui':
            try: await XuiService().reset_client_plan(server, svc.xui_email, plan.volume_gb, plan.duration_days)
            except Exception as e:
                await handle_user_facing_error(callback, e, context='User service panel refresh failed', reply_markup=back_main_inline()); return
        svc.plan_id=pid; svc.total_bytes=plan.volume_gb*1024**3; svc.used_bytes=0; svc.expires_at=datetime.utcnow()+timedelta(days=plan.duration_days) if plan.duration_days else None; svc.is_active=True
        await session.commit()
    await render_detail(callback, sid); await callback.answer('✅ پلن سرویس تغییر کرد')

@router.callback_query(F.data.startswith('svc:renew_card:') | F.data.startswith('svc:renew_same:'))
async def renew_card(callback: CallbackQuery, state: FSMContext):
    sid=int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        svc=await session.get(ClientService,sid); plan=await session.get(Plan,svc.plan_id); server=await session.get(Server,svc.server_id); user=await session.get(User,svc.user_id)
        card=(await session.execute(select(PaymentCard).where(PaymentCard.server_id == server.id, PaymentCard.is_active == True))).scalar_one_or_none()
        if not card:
            await edit_or_answer(callback, 'برای این سرور شماره کارت ثبت نشده است.', reply_markup=back_main_inline()); await callback.answer(); return
        order=Order(user_id=user.id, plan_id=plan.id, service_id=svc.id, amount_irt=plan.price_irt, payment_method=f'renew:{svc.client_username}', status='waiting_receipt')
        session.add(order); await session.commit(); oid=order.id
    await state.update_data(order_id=oid, username=svc.client_username, plan_id=plan.id, server_id=server.id)
    from app.bot.states.public_states import BuyFlow
    await state.set_state(BuyFlow.receipt)
    await edit_or_answer(callback, f'💳 برای تمدید مبلغ {plan.price_irt:,} تومان را واریز کنید و عکس رسید را ارسال کنید.\n\nشماره کارت: {card.card_number}\nنام صاحب حساب: {card.owner_name}', reply_markup=back_main_inline()); await callback.answer()


@router.callback_query(F.data.startswith('svc:renew_wallet:'))
async def renew_wallet(callback: CallbackQuery):
    if callback.message:
        cancel_auto_refresh(callback.message.chat.id, callback.message.message_id)
    sid=int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        svc=await session.get(ClientService,sid)
        if not svc:
            await callback.answer('سرویس پیدا نشد.', show_alert=True); return
        plan=await session.get(Plan,svc.plan_id)
        server=await session.get(Server,svc.server_id)
        user=await session.get(User,svc.user_id)
        if not plan or not user or not server:
            await callback.answer('اطلاعات تمدید کامل نیست.', show_alert=True); return
        wallet_type = 'wallet_v2ray_balance' if server.server_type == 'xui' else 'wallet_openvpn_balance'
        balance = getattr(user, wallet_type, 0) or 0
        if balance < (plan.price_irt or 0):
            await callback.answer('موجودی کیف پول کافی نیست.', show_alert=True)
            await edit_or_answer(callback, f'❌ موجودی کیف پول کافی نیست.\n\n💰 مبلغ تمدید: {plan.price_irt:,} تومان\n💎 موجودی شما: {balance:,} تومان', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='💳 پرداخت با کارت', callback_data=f'svc:renew_card:{sid}')],[back_button(f'svc:renew_menu:{sid}')]]))
            return
        try:
            if server.server_type == 'xui':
                await XuiService().reset_client_plan(server, svc.xui_email, plan.volume_gb, plan.duration_days)
            setattr(user, wallet_type, balance - (plan.price_irt or 0))
            svc.total_bytes=plan.volume_gb*1024**3
            svc.used_bytes=0
            svc.expires_at=datetime.utcnow()+timedelta(days=plan.duration_days) if plan.duration_days else None
            svc.is_active=True
            order=Order(user_id=user.id, plan_id=plan.id, service_id=svc.id, amount_irt=plan.price_irt, payment_method='wallet_renew', status='paid')
            session.add(order)
            await session.commit()
        except Exception as e:
            await session.rollback()
            await handle_user_facing_error(callback, e, context='User service renewal with wallet failed', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(f'svc:renew_menu:{sid}')]]))
            return
    await render_detail(callback, sid)
    await callback.answer('✅ سرویس با کیف پول تمدید شد')


@router.callback_query(F.data.startswith('svc:delete:'))
async def delete_service_ask(callback: CallbackQuery):
    if callback.message:
        cancel_auto_refresh(callback.message.chat.id, callback.message.message_id)
    sid=int(callback.data.split(':')[-1])
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='✅ تایید حذف کانفیگ 🗑', callback_data=f'svc:delete_confirm:{sid}')],[back_button(f'svc:{sid}')]])
    await edit_or_answer(callback, '⚠️ این کانفیگ هم از ربات و هم از پنل حذف می‌شود. مطمئن هستید؟', reply_markup=kb); await callback.answer()

@router.callback_query(F.data.startswith('svc:delete_confirm:'))
async def delete_service(callback: CallbackQuery):
    if callback.message:
        cancel_auto_refresh(callback.message.chat.id, callback.message.message_id)
    sid=int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        svc=await session.get(ClientService,sid)
        if not svc:
            await callback.answer('پیدا نشد', show_alert=True); return
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
        deleted_username = svc.client_username
        deleted_email = svc.xui_email
        deleted_volume = svc.total_bytes or 0
        deleted_used = svc.used_bytes or 0
        deleted_expires = svc.expires_at
        # Remove or detach all local references before deleting the service.
        # Orders must stay as accounting history, so their service_id is cleared.
        await delete_local_service_records(session, svc)
        await session.commit()
    deleted_text = (
        '✅ سرویس شما با موفقیت حذف شد\n\n'
        '🗑 سرویس شما با مشخصات زیر حذف شد:\n'
        '━━━━━━━━━━━━━━━━\n'
        f'👤 نام کانفیگ: {deleted_username or "-"}\n'
        f'🆔 ایمیل/یوزرنیم پنل: {deleted_email or "-"}\n'
        f'💾 حجم کل: {gb(deleted_volume):.2f} گیگ\n'
        f'📊 مصرف‌شده: {gb(deleted_used):.2f} گیگ\n'
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
