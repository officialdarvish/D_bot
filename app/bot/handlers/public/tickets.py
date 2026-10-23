from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from app.bot.keyboards.common import CB_TICKETS, back_button, main_menu_inline
from app.bot.states.public_states import TicketFlow, TicketReply
from app.bot.utils import edit_or_answer, remember_ui_message, send_single_message, ui_message
from app.core.config import settings
from app.database.defaults import WELCOME_TEXT_DEFAULT, get_setting_value
from app.database.models import Ticket, TicketMessage, User
from app.database.session import SessionLocal

router = Router()
logger = logging.getLogger(__name__)


def ticket_actions(tid: int, prefix: str = 'ticket_user') -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text='✍️ پاسخ به تیکت', callback_data=f'{prefix}:reply:{tid}'),
            InlineKeyboardButton(text='🔒 بستن تیکت', callback_data=f'{prefix}:close:{tid}'),
        ],
        [InlineKeyboardButton(text='🔙 بازگشت', callback_data='menu:tickets')],
    ])


def admin_actions(tid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text='✍️ پاسخ به تیکت', callback_data=f'ticket_admin:reply:{tid}'),
        InlineKeyboardButton(text='🔒 بستن تیکت', callback_data=f'ticket_admin:close:{tid}'),
    ]])


def ticket_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text='ثبت تیکت جدید 📝', callback_data='ticket:new'),
            InlineKeyboardButton(text='لیست تیکت‌ها 📋', callback_data='ticket:list'),
        ],
        [InlineKeyboardButton(text='🔙 بازگشت', callback_data='back:main')],
    ])


def user_reply_prompt_kb(tid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🔙 بازگشت به تیکت', callback_data=f'ticket:view:{tid}')],
        [InlineKeyboardButton(text='🏠 صفحه اصلی', callback_data='back:main')],
    ])


def admin_reply_prompt_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🔙 بازگشت به پنل مدیریت', callback_data='back:admin')],
    ])


def _ticket_id(callback: CallbackQuery) -> int | None:
    try:
        return int((callback.data or '').rsplit(':', 1)[-1])
    except (TypeError, ValueError):
        return None


async def _user_for_telegram(session, telegram_id: int) -> User | None:
    return (await session.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one_or_none()


async def _owned_ticket(session, telegram_id: int, tid: int) -> tuple[User | None, Ticket | None]:
    """Return a ticket only when it belongs to the Telegram user.

    Ticket IDs appear in callback data, so every user action must perform this
    ownership check instead of trusting the callback payload.
    """
    user = await _user_for_telegram(session, telegram_id)
    if not user:
        return None, None
    ticket = await session.get(Ticket, tid)
    if not ticket or ticket.user_id != user.id:
        return user, None
    return user, ticket


async def send_home(bot, chat_id: int, is_admin: bool = False):
    """Send Home and mark it as the active UI page.

    Ticket flows intentionally send a result/confirmation first and then Home.
    Remembering the Home message prevents FreshCallbackOnlyMiddleware from
    treating its buttons as stale immediately after a ticket action.
    """
    sent = await bot.send_message(
        chat_id,
        await get_setting_value('welcome_text', WELCOME_TEXT_DEFAULT),
        reply_markup=await main_menu_inline(is_admin),
    )
    remember_ui_message(sent.chat.id, sent.message_id)
    return sent


@router.callback_query(F.data == CB_TICKETS)
async def ticket_menu(event: CallbackQuery, state: FSMContext):
    await state.clear()
    await edit_or_answer(event, '📨 بخش تیکت:', reply_markup=ticket_menu_kb())
    await event.answer()


@router.callback_query(F.data == 'ticket:new')
async def ticket_new(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(TicketFlow.subject)
    await edit_or_answer(
        callback,
        '📝 موضوع تیکت را ارسال کنید:',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('menu:tickets')]]),
    )
    await callback.answer()


@router.message(TicketFlow.subject)
async def ticket_subject(message: Message, state: FSMContext):
    subject = (message.text or '').strip()
    if not subject:
        await ui_message(
            message,
            'موضوع تیکت باید به صورت متن ارسال شود:',
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('menu:tickets')]]),
        )
        return
    if len(subject) > 180:
        await ui_message(
            message,
            'موضوع تیکت حداکثر می‌تواند ۱۸۰ کاراکتر باشد. موضوع کوتاه‌تری ارسال کنید:',
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('menu:tickets')]]),
        )
        return
    await state.update_data(subject=subject)
    await state.set_state(TicketFlow.message)
    await ui_message(
        message,
        'متن تیکت را ارسال کنید:',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('ticket:back_subject')]]),
    )


@router.callback_query(F.data == 'ticket:back_subject')
async def ticket_back_subject(callback: CallbackQuery, state: FSMContext):
    await state.set_state(TicketFlow.subject)
    await edit_or_answer(
        callback,
        '📝 موضوع تیکت را ارسال کنید:',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('menu:tickets')]]),
    )
    await callback.answer()


@router.message(TicketFlow.message)
async def ticket_save(message: Message, state: FSMContext):
    body = (message.text or '').strip()
    if not body:
        await ui_message(
            message,
            'متن تیکت باید به صورت پیام متنی ارسال شود:',
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('ticket:back_subject')]]),
        )
        return

    data = await state.get_data()
    subject = str(data.get('subject') or '').strip()
    if not subject:
        await state.set_state(TicketFlow.subject)
        await ui_message(message, 'موضوع تیکت مشخص نیست. لطفاً موضوع تیکت را دوباره ارسال کنید:')
        return

    async with SessionLocal() as session:
        user = await _user_for_telegram(session, message.from_user.id)
        if not user:
            await state.clear()
            await ui_message(message, 'کاربر پیدا نشد. لطفاً /start را ارسال کنید و دوباره تلاش کنید.')
            return
        ticket = Ticket(user_id=user.id, subject=subject, status='open')
        session.add(ticket)
        await session.flush()
        session.add(TicketMessage(ticket_id=ticket.id, sender_type='user', message=body))
        await session.commit()
        tid = ticket.id

    text = (
        f'📨 تیکت جدید #{tid}\n'
        f'موضوع: {subject}\n\n'
        f'👤 نام: {message.from_user.full_name}\n'
        f'🔢 آیدی عددی: {message.from_user.id}\n'
        f'🆔 یوزرنیم: {message.from_user.username or "ندارد"}\n\n'
        f'متن:\n{body}'
    )
    for aid in settings.admin_ids:
        try:
            await message.bot.send_message(aid, text, reply_markup=admin_actions(tid))
        except Exception:
            logger.exception('Failed to deliver new ticket #%s notification to admin %s', tid, aid)

    await state.clear()
    await ui_message(message, f'✅ تیکت #{tid} ثبت شد و برای مدیر ارسال شد.')
    await send_home(message.bot, message.from_user.id, message.from_user.id in settings.admin_ids)


@router.callback_query(F.data == 'ticket:list')
async def ticket_list(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    async with SessionLocal() as session:
        user = await _user_for_telegram(session, callback.from_user.id)
        if not user:
            await callback.answer('کاربر پیدا نشد. لطفاً /start را ارسال کنید.', show_alert=True)
            return
        tickets = (
            await session.execute(
                select(Ticket).where(Ticket.user_id == user.id).order_by(Ticket.id.desc())
            )
        ).scalars().all()

    if not tickets:
        await edit_or_answer(callback, '📭 تیکتی ثبت نشده است.', reply_markup=ticket_menu_kb())
        await callback.answer()
        return

    rows = [[InlineKeyboardButton(
        text=f'#{t.id} - {t.subject} - {"باز ✅" if t.status == "open" else "بسته 🔒"}',
        callback_data=f'ticket:view:{t.id}',
    )] for t in tickets]
    rows.append([InlineKeyboardButton(text='🔙 بازگشت', callback_data='menu:tickets')])
    await edit_or_answer(
        callback,
        '📋 لیست تیکت‌های شما:',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith('ticket:view:'))
async def ticket_view(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    tid = _ticket_id(callback)
    if tid is None:
        await callback.answer('تیکت نامعتبر است.', show_alert=True)
        return

    async with SessionLocal() as session:
        _, ticket = await _owned_ticket(session, callback.from_user.id, tid)
        if not ticket:
            await callback.answer('تیکت پیدا نشد یا متعلق به حساب شما نیست.', show_alert=True)
            return
        msgs = (
            await session.execute(
                select(TicketMessage)
                .where(TicketMessage.ticket_id == tid)
                .order_by(TicketMessage.id.asc())
            )
        ).scalars().all()

    lines = [
        f'📨 تیکت #{ticket.id}',
        f'موضوع: {ticket.subject}',
        f'وضعیت: {"باز ✅" if ticket.status == "open" else "بسته 🔒"}',
        '',
    ]
    for item in msgs[-10:]:
        who = 'شما' if item.sender_type == 'user' else 'مدیر'
        lines.append(f'{who}: {item.message}')

    kb = ticket_actions(tid) if ticket.status == 'open' else InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🔙 بازگشت', callback_data='ticket:list')]
    ])
    await edit_or_answer(callback, '\n'.join(lines), reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith('ticket_user:reply:'))
async def user_reply_start(callback: CallbackQuery, state: FSMContext):
    tid = _ticket_id(callback)
    if tid is None:
        await callback.answer('تیکت نامعتبر است.', show_alert=True)
        return

    async with SessionLocal() as session:
        _, ticket = await _owned_ticket(session, callback.from_user.id, tid)
        if not ticket:
            await callback.answer('تیکت پیدا نشد یا متعلق به حساب شما نیست.', show_alert=True)
            return
        if ticket.status != 'open':
            await callback.answer('این تیکت بسته شده و امکان پاسخ ندارد.', show_alert=True)
            return

    # The reply button may live on a proactive notification instead of the
    # current UI page. Create a fresh active prompt rather than trying to edit
    # whichever notification message was clicked.
    await state.clear()
    await state.update_data(ticket_id=tid, ticket_reply_role='user')
    await state.set_state(TicketReply.message)
    await send_single_message(
        callback.bot,
        callback.from_user.id,
        f'✍️ پاسخ خود را برای تیکت #{tid} ارسال کنید:',
        reply_markup=user_reply_prompt_kb(tid),
    )
    await callback.answer('پاسخ خود را ارسال کنید')


@router.callback_query(F.data.startswith('ticket_admin:reply:'))
async def admin_reply_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in settings.admin_ids:
        await callback.answer('دسترسی ندارید.', show_alert=True)
        return

    tid = _ticket_id(callback)
    if tid is None:
        await callback.answer('تیکت نامعتبر است.', show_alert=True)
        return

    async with SessionLocal() as session:
        ticket = await session.get(Ticket, tid)
        if not ticket:
            await callback.answer('تیکت پیدا نشد.', show_alert=True)
            return
        if ticket.status != 'open':
            await callback.answer('این تیکت بسته شده و امکان پاسخ ندارد.', show_alert=True)
            return

    await state.clear()
    await state.update_data(ticket_id=tid, ticket_reply_role='admin')
    await state.set_state(TicketReply.message)
    await send_single_message(
        callback.bot,
        callback.from_user.id,
        f'✍️ پاسخ خود را برای تیکت #{tid} ارسال کنید.\n\nبعد از ارسال، پاسخ برای کاربر فرستاده می‌شود.',
        reply_markup=admin_reply_prompt_kb(),
    )
    await callback.answer('پاسخ خود را ارسال کنید')


@router.message(TicketReply.message)
async def ticket_reply_save(message: Message, state: FSMContext):
    data = await state.get_data()
    try:
        tid = int(data.get('ticket_id'))
    except (TypeError, ValueError):
        await state.clear()
        await ui_message(message, 'اطلاعات تیکت معتبر نیست. لطفاً دوباره از لیست تیکت‌ها وارد شوید.')
        return

    role = str(data.get('ticket_reply_role') or '')
    reply_text = (message.text or message.caption or '').strip()
    if not reply_text:
        await ui_message(
            message,
            'لطفاً پاسخ تیکت را به صورت متن ارسال کنید:',
            reply_markup=admin_reply_prompt_kb() if role == 'admin' else user_reply_prompt_kb(tid),
        )
        return

    async with SessionLocal() as session:
        ticket = await session.get(Ticket, tid)
        if not ticket or ticket.status != 'open':
            await state.clear()
            await ui_message(message, 'تیکت پیدا نشد یا بسته شده است.')
            return

        owner = await session.get(User, ticket.user_id)
        if not owner:
            await state.clear()
            await ui_message(message, 'صاحب تیکت پیدا نشد.')
            return

        if role == 'admin':
            if message.from_user.id not in settings.admin_ids:
                await state.clear()
                await ui_message(message, 'دسترسی پاسخ مدیریت برای این حساب وجود ندارد.')
                return
            sender_type = 'admin'
        elif role == 'user':
            current_user = await _user_for_telegram(session, message.from_user.id)
            if not current_user or current_user.id != ticket.user_id:
                await state.clear()
                await ui_message(message, 'این تیکت متعلق به حساب شما نیست.')
                return
            sender_type = 'user'
        else:
            await state.clear()
            await ui_message(message, 'حالت پاسخ تیکت معتبر نیست. لطفاً دوباره تلاش کنید.')
            return

        session.add(TicketMessage(ticket_id=tid, sender_type=sender_type, message=reply_text))
        await session.commit()
        owner_telegram_id = owner.telegram_id

    # The reply is committed at this point. Clear the input state before remote
    # delivery so a Telegram delivery failure cannot accidentally duplicate it.
    await state.clear()

    if role == 'admin':
        delivered = True
        try:
            await message.bot.send_message(
                owner_telegram_id,
                f'📨 پاسخ مدیر به تیکت #{tid}:\n\n{reply_text}',
                reply_markup=ticket_actions(tid),
            )
        except Exception:
            delivered = False
            logger.exception('Failed to deliver admin reply for ticket #%s to user %s', tid, owner_telegram_id)

        if delivered:
            await ui_message(message, '✅ پاسخ برای کاربر ارسال شد.', reply_markup=admin_actions(tid))
        else:
            await ui_message(
                message,
                '⚠️ پاسخ داخل تیکت ذخیره شد، اما ارسال اعلان تلگرام به کاربر ناموفق بود.',
                reply_markup=admin_actions(tid),
            )
        await send_home(message.bot, message.from_user.id, True)
        return

    delivered_count = 0
    for aid in settings.admin_ids:
        try:
            await message.bot.send_message(
                aid,
                f'📨 پاسخ کاربر به تیکت #{tid}:\n\n{reply_text}',
                reply_markup=admin_actions(tid),
            )
            delivered_count += 1
        except Exception:
            logger.exception('Failed to deliver user reply for ticket #%s to admin %s', tid, aid)

    if delivered_count:
        await ui_message(message, '✅ پاسخ شما ارسال شد.')
    else:
        await ui_message(
            message,
            '⚠️ پاسخ شما داخل تیکت ذخیره شد، اما اعلان تلگرام برای مدیریت ارسال نشد.',
        )
    await send_home(message.bot, message.from_user.id, message.from_user.id in settings.admin_ids)


@router.callback_query(F.data.startswith('ticket_user:close:') | F.data.startswith('ticket_admin:close:'))
async def close_ticket(callback: CallbackQuery, state: FSMContext):
    tid = _ticket_id(callback)
    if tid is None:
        await callback.answer('تیکت نامعتبر است.', show_alert=True)
        return

    is_admin_action = (callback.data or '').startswith('ticket_admin:')
    if is_admin_action and callback.from_user.id not in settings.admin_ids:
        await callback.answer('دسترسی ندارید.', show_alert=True)
        return

    async with SessionLocal() as session:
        if is_admin_action:
            ticket = await session.get(Ticket, tid)
            if not ticket:
                await callback.answer('تیکت پیدا نشد.', show_alert=True)
                return
        else:
            _, ticket = await _owned_ticket(session, callback.from_user.id, tid)
            if not ticket:
                await callback.answer('تیکت پیدا نشد یا متعلق به حساب شما نیست.', show_alert=True)
                return

        owner = await session.get(User, ticket.user_id)
        if ticket.status == 'closed':
            await state.clear()
            await callback.answer('این تیکت قبلاً بسته شده است.', show_alert=True)
            return
        ticket.status = 'closed'
        await session.commit()
        owner_telegram_id = owner.telegram_id if owner else None

    await state.clear()

    if is_admin_action and owner_telegram_id:
        try:
            await callback.bot.send_message(owner_telegram_id, f'🔒 تیکت #{tid} توسط مدیریت بسته شد.')
        except Exception:
            logger.exception('Failed to notify user about ticket #%s close', tid)
    elif not is_admin_action:
        for aid in settings.admin_ids:
            try:
                await callback.bot.send_message(aid, f'🔒 کاربر تیکت #{tid} را بست.')
            except Exception:
                logger.exception('Failed to notify admin %s about ticket #%s close', aid, tid)

    await edit_or_answer(callback, f'✅ تیکت #{tid} بسته شد.')
    await send_home(callback.bot, callback.from_user.id, callback.from_user.id in settings.admin_ids)
    await callback.answer()
