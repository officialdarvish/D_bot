"""Subscription-link lookup and confirmed owner-list removal for administrators."""
from datetime import datetime, timedelta
from html import escape
import secrets
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from app.core.config import settings
from app.database.session import SessionLocal
from app.bot.states.admin_states import RemoveServiceFromList
from app.bot.keyboards.common import user_interaction_inline
from app.bot.utils import edit_or_answer, ui_message
from app.services.service_list_removal import lookup, link_fingerprint, remove_from_owner_list, ListRemovalError

router = Router()
TTL = timedelta(minutes=10)


def back_markup():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text='🔙 بازگشت به تعامل با کاربر', callback_data='admin:user_interaction')]])


async def authorized(event):
    if event.from_user.id not in settings.admin_ids:
        if isinstance(event, CallbackQuery): await event.answer('این بخش فقط برای مدیر ربات است.', show_alert=True)
        return False
    message = event.message if isinstance(event, CallbackQuery) else event
    if not message or message.chat.type != 'private':
        if isinstance(event, CallbackQuery): await event.answer('این عملیات را در گفت‌وگوی خصوصی ربات انجام دهید.', show_alert=True)
        return False
    return True


@router.callback_query(F.data == 'admin:unlink_service')
async def begin(callback: CallbackQuery, state: FSMContext):
    if not await authorized(callback): return
    await state.clear()
    await state.set_state(RemoveServiceFromList.link)
    await edit_or_answer(callback,
        'حذف کانفیگ از لیست ربات\n\nلینک کامل ساب کانفیگ را بفرستید تا صاحب آن نمایش داده شود. حذف فقط پس از تأیید شما انجام می‌شود و کانفیگ داخل پنل باقی می‌ماند.',
        reply_markup=back_markup())
    await callback.answer()


@router.message(RemoveServiceFromList.link)
@router.message(RemoveServiceFromList.confirm)
async def receive_link(message: Message, state: FSMContext):
    if not await authorized(message): return
    try:
        async with SessionLocal() as session:
            svc, owner, server = await lookup(session, message.text or '', message.from_user.id)
        nonce = secrets.token_hex(12)
        await state.set_state(RemoveServiceFromList.confirm)
        await state.update_data(list_removal={
            'nonce': nonce, 'service_id': svc.id, 'owner_id': owner.id,
            'fingerprint': link_fingerprint(svc.sub_link), 'at': datetime.utcnow().isoformat(),
        })
        safe = lambda value: escape(str(value or '—'))
        text = ('🔎 <b>تأیید حذف از لیست ربات</b>\n\n'
            f'کانفیگ: <code>{safe(svc.client_username or svc.xui_email)}</code>\n'
            f'شناسه سرویس: #{svc.id}\n'
            f'سرور: {safe(server.name if server else None)}\n'
            f'نام صاحب کانفیگ: {safe(owner.full_name)}\n'
            f'یوزرنیم تلگرام: {safe("@" + owner.username if owner.username else None)}\n'
            f'آیدی عددی صاحب کانفیگ: <code>{owner.telegram_id}</code>\n'
            f'نوع سرویس: {"نمایندگی" if svc.reseller_id else "خرید عمومی"}\n\n'
            'با تأیید، کانفیگ فقط از فهرست این کاربر در ربات و مینی‌اپ حذف می‌شود. کانفیگ داخل پنل می‌ماند و وضعیت، حجم و انقضای آن تغییر نمی‌کند.')
        await ui_message(message, text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='✅ تأیید حذف فقط از لیست ربات', callback_data=f'admin:unlink_confirm:{nonce}')],
            [InlineKeyboardButton(text='❌ انصراف', callback_data=f'admin:unlink_cancel:{nonce}')],
            *back_markup().inline_keyboard,
        ]))
    except ListRemovalError as exc:
        # A failed/new lookup must invalidate every older confirmation.
        await state.clear()
        await state.set_state(RemoveServiceFromList.link)
        await ui_message(message, '❌ ' + str(exc), reply_markup=back_markup(), parse_mode=None)


@router.callback_query(F.data.startswith('admin:unlink_cancel:'))
async def cancel(callback: CallbackQuery, state: FSMContext):
    if not await authorized(callback): return
    data = (await state.get_data()).get('list_removal') or {}
    if data.get('nonce') != callback.data.split(':')[-1]:
        await callback.answer('این دکمه قدیمی است؛ از درخواست فعلی استفاده کنید.', show_alert=True)
        return
    await state.clear()
    await edit_or_answer(callback, 'حذف از فهرست لغو شد.', reply_markup=user_interaction_inline())
    await callback.answer()


@router.callback_query(F.data.startswith('admin:unlink_confirm:'))
async def confirm(callback: CallbackQuery, state: FSMContext):
    if not await authorized(callback): return
    data = (await state.get_data()).get('list_removal') or {}
    if (await state.get_state() != RemoveServiceFromList.confirm.state
            or data.get('nonce') != callback.data.split(':')[-1]):
        await callback.answer('این دکمه قدیمی است؛ لینک ساب را دوباره بفرستید.', show_alert=True)
        return
    try:
        at = datetime.fromisoformat(data.get('at') or '')
        if datetime.utcnow() - at > TTL:
            raise ValueError()
    except (TypeError, ValueError):
        await state.clear()
        await callback.answer('تأیید منقضی شده است؛ دوباره از بخش تعامل با کاربر شروع کنید.', show_alert=True)
        return
    await callback.answer('در حال حذف فقط از فهرست ربات…')
    try:
        async with SessionLocal() as session:
            name, telegram_id = await remove_from_owner_list(session,
                int(data['service_id']), callback.from_user.id, int(data['owner_id']), str(data['fingerprint']))
            await session.commit()
    except ListRemovalError as exc:
        await state.clear()
        await edit_or_answer(callback, '❌ ' + str(exc), reply_markup=back_markup(), parse_mode=None)
        return
    await state.clear()
    await edit_or_answer(callback,
        f'✅ کانفیگ {name} از لیست کاربر {telegram_id} در ربات و مینی‌اپ حذف شد.\nکانفیگ داخل پنل باقی مانده و هیچ تغییری در آن انجام نشد.',
        reply_markup=user_interaction_inline(), parse_mode=None)
