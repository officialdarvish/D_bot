from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
from app.core.config import settings
from app.database.session import SessionLocal
from app.database.models import User, Ticket, TicketMessage
from app.bot.states.public_states import TicketFlow, AdminTicketReply
from app.bot.keyboards.common import CB_TICKETS, back_main_inline, main_menu_inline
from app.database.defaults import get_setting_value, WELCOME_TEXT_DEFAULT
from app.bot.utils import edit_or_answer, ui_message, ui_callback_message

router = Router()

def ticket_actions(tid:int, prefix='ticket_user'):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✍️ پاسخ به تیکت', callback_data=f'{prefix}:reply:{tid}'), InlineKeyboardButton(text='🔒 بستن تیکت', callback_data=f'{prefix}:close:{tid}')],
        [InlineKeyboardButton(text='🔙 بازگشت', callback_data='menu:tickets')]
    ])

def admin_actions(tid:int):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='✍️ پاسخ به تیکت', callback_data=f'ticket_admin:reply:{tid}'), InlineKeyboardButton(text='🔒 بستن تیکت', callback_data=f'ticket_admin:close:{tid}')]])

def ticket_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='ثبت تیکت جدید 📝', callback_data='ticket:new'), InlineKeyboardButton(text='لیست تیکت‌ها 📋', callback_data='ticket:list')],
        [InlineKeyboardButton(text='🔙 بازگشت', callback_data='back:main')],
    ])

async def send_home(bot, chat_id:int, is_admin=False):
    await bot.send_message(chat_id, await get_setting_value('welcome_text', WELCOME_TEXT_DEFAULT), reply_markup=main_menu_inline(is_admin))

@router.callback_query(F.data == CB_TICKETS)
async def ticket_menu(event):
    await edit_or_answer(event, '📨 بخش تیکت:', reply_markup=ticket_menu_kb())
    await event.answer()

@router.callback_query(F.data == 'ticket:new')
async def ticket_new(callback: CallbackQuery, state: FSMContext):
    await state.set_state(TicketFlow.subject)
    await edit_or_answer(callback, '📝 موضوع تیکت را ارسال کنید:', reply_markup=back_main_inline())
    await callback.answer()

@router.message(TicketFlow.subject)
async def ticket_subject(message: Message, state: FSMContext):
    await state.update_data(subject=message.text); await state.set_state(TicketFlow.message)
    await ui_message(message, 'متن تیکت را ارسال کنید:')

@router.message(TicketFlow.message)
async def ticket_save(message: Message, state: FSMContext):
    data=await state.get_data()
    async with SessionLocal() as session:
        user=(await session.execute(select(User).where(User.telegram_id == message.from_user.id))).scalar_one()
        ticket=Ticket(user_id=user.id, subject=data['subject'], status='open'); session.add(ticket); await session.flush()
        session.add(TicketMessage(ticket_id=ticket.id, sender_type='user', message=message.text)); await session.commit(); tid=ticket.id
    text=(f'📨 تیکت جدید #{tid}\nموضوع: {data["subject"]}\n\n👤 نام: {message.from_user.full_name}\n🔢 آیدی عددی: {message.from_user.id}\n🆔 یوزرنیم: {message.from_user.username or "ندارد"}\n\nمتن:\n{message.text}')
    for aid in settings.admin_ids:
        await message.bot.send_message(aid, text, reply_markup=admin_actions(tid))
    await state.clear(); await ui_message(message, f'✅ تیکت #{tid} ثبت شد و برای مدیر ارسال شد.')
    await send_home(message.bot, message.from_user.id, message.from_user.id in settings.admin_ids)

@router.callback_query(F.data == 'ticket:list')
async def ticket_list(callback: CallbackQuery):
    async with SessionLocal() as session:
        user=(await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one()
        tickets=(await session.execute(select(Ticket).where(Ticket.user_id == user.id).order_by(Ticket.id.desc()))).scalars().all()
    if not tickets:
        await edit_or_answer(callback, '📭 تیکتی ثبت نشده است.', reply_markup=ticket_menu_kb()); await callback.answer(); return
    rows=[[InlineKeyboardButton(text=f'#{t.id} - {t.subject} - {"باز ✅" if t.status=="open" else "بسته 🔒"}', callback_data=f'ticket:view:{t.id}')] for t in tickets]
    rows.append([InlineKeyboardButton(text='🔙 بازگشت', callback_data='menu:tickets')])
    await edit_or_answer(callback, '📋 لیست تیکت‌های شما:', reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)); await callback.answer()

@router.callback_query(F.data.startswith('ticket:view:'))
async def ticket_view(callback: CallbackQuery):
    tid=int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        ticket=await session.get(Ticket, tid)
        msgs=(await session.execute(select(TicketMessage).where(TicketMessage.ticket_id==tid).order_by(TicketMessage.id.asc()))).scalars().all()
    if not ticket:
        await callback.answer('تیکت پیدا نشد.', show_alert=True); return
    lines=[f'📨 تیکت #{ticket.id}', f'موضوع: {ticket.subject}', f'وضعیت: {"باز ✅" if ticket.status=="open" else "بسته 🔒"}', '']
    for m in msgs[-10:]:
        who='شما' if m.sender_type=='user' else 'مدیر'
        lines.append(f'{who}: {m.message}')
    kb=ticket_actions(tid) if ticket.status=='open' else InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='🔙 بازگشت', callback_data='ticket:list')]])
    await edit_or_answer(callback, '\n'.join(lines), reply_markup=kb); await callback.answer()

@router.callback_query(F.data.startswith('ticket_user:reply:'))
async def user_reply_start(callback: CallbackQuery, state: FSMContext):
    tid=int(callback.data.split(':')[-1]); await state.update_data(ticket_id=tid); await state.set_state(AdminTicketReply.message)
    await edit_or_answer(callback, f'پاسخ خود را برای تیکت #{tid} ارسال کنید:', reply_markup=ticket_actions(tid)); await callback.answer()

@router.callback_query(F.data.startswith('ticket_admin:reply:'))
async def admin_reply_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in settings.admin_ids:
        await callback.answer('دسترسی ندارید.', show_alert=True); return
    tid=int(callback.data.split(':')[-1])
    await state.update_data(ticket_id=tid)
    await state.set_state(AdminTicketReply.message)
    await edit_or_answer(callback, f'✍️ پاسخ خود را برای تیکت #{tid} ارسال کنید.\n\nبعد از ارسال پاسخ، دکمه‌های پاسخ/بستن دوباره نمایش داده می‌شود.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='🔙 بازگشت', callback_data='back:admin')]]))
    await callback.answer()

@router.message(AdminTicketReply.message)
async def ticket_reply_save(message: Message, state: FSMContext):
    data=await state.get_data(); tid=int(data['ticket_id'])
    sender_is_admin=message.from_user.id in settings.admin_ids
    sender_type='admin' if sender_is_admin else 'user'
    async with SessionLocal() as session:
        ticket=await session.get(Ticket, tid)
        if not ticket or ticket.status!='open':
            await ui_message(message, 'تیکت پیدا نشد یا بسته شده است.'); await state.clear(); return
        user=await session.get(User, ticket.user_id)
        session.add(TicketMessage(ticket_id=tid, sender_type=sender_type, message=message.text)); await session.commit()
    if sender_is_admin:
        await message.bot.send_message(user.telegram_id, f'📨 پاسخ مدیر به تیکت #{tid}:\n\n{message.text}', reply_markup=ticket_actions(tid))
        await ui_message(message, '✅ پاسخ برای کاربر ارسال شد.', reply_markup=admin_actions(tid))
        await send_home(message.bot, message.from_user.id, True)
    else:
        for aid in settings.admin_ids:
            await message.bot.send_message(aid, f'📨 پاسخ کاربر به تیکت #{tid}:\n\n{message.text}', reply_markup=admin_actions(tid))
        await ui_message(message, '✅ پاسخ شما ارسال شد.')
        await send_home(message.bot, message.from_user.id, message.from_user.id in settings.admin_ids)
    await state.clear()

@router.callback_query(F.data.startswith('ticket_user:close:') | F.data.startswith('ticket_admin:close:'))
async def close_ticket(callback: CallbackQuery):
    tid=int(callback.data.split(':')[-1])
    is_admin=callback.data.startswith('ticket_admin')
    if is_admin and callback.from_user.id not in settings.admin_ids:
        await callback.answer('دسترسی ندارید.', show_alert=True); return
    async with SessionLocal() as session:
        ticket=await session.get(Ticket, tid)
        if not ticket: await callback.answer('تیکت پیدا نشد.', show_alert=True); return
        ticket.status='closed'; user=await session.get(User, ticket.user_id); await session.commit()
    await callback.message.bot.send_message(user.telegram_id, f'🔒 تیکت #{tid} بسته شد.')
    await edit_or_answer(callback, f'✅ تیکت #{tid} بسته شد.')
    await send_home(callback.message.bot, callback.from_user.id, callback.from_user.id in settings.admin_ids)
    await callback.answer()
