from datetime import datetime
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy import select, func
from app.core.config import settings
from app.database.session import SessionLocal
from app.database.models import User, ClientService, PaymentCard, Order, Server
from app.bot.keyboards.common import CB_ACCOUNT, back_button, main_menu_inline, get_user_button
from app.bot.states.public_states import WalletTopupFlow
from app.bot.states.admin_states import WalletReceiptReject
from app.bot.utils import send_single_message, edit_or_answer, ui_message, ui_callback_message
from app.database.defaults import get_setting_value, WELCOME_TEXT_DEFAULT
from app.utils.jalali import fa_date

router = Router()

def receipt_received_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🏠 خانه', callback_data='home:main')]
    ])

RECEIPT_RECEIVED_TEXT = (
    '✅ رسید با موفقیت دریافت شد.\n\n'
    'لطفاً منتظر بمانید تا مدیر رسید شما را بررسی و تایید کند.\n'
    'بعد از تایید، نتیجه از همین ربات برای شما ارسال می‌شود.'
)


def status_only_keyboard(text: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data='noop')]
    ])

async def mark_message_status(callback: CallbackQuery, text: str) -> None:
    try:
        await callback.message.edit_reply_markup(reply_markup=status_only_keyboard(text))
    except Exception:
        pass


def approved_only_keyboard(text: str = '✅ تایید شد') -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data='noop')]
    ])

async def replace_admin_receipt_buttons(callback: CallbackQuery, text: str = '✅ تایید شد') -> None:
    try:
        await callback.message.edit_reply_markup(reply_markup=approved_only_keyboard(text))
    except Exception:
        pass

def wallet_type_title(t): return 'کیف پول اصلی'
def wallet_field(t): return 'wallet_balance'

def _is_public_server(server: Server | None) -> bool:
    return bool(server) and bool(server.is_active) and ((server.meta or {}).get('scope') != 'reseller')

async def available_wallet_types(session) -> list[str]:
    rows = (await session.execute(select(Server).where(Server.is_active == True))).scalars().all()
    return ['all'] if any(_is_public_server(srv) for srv in rows) else []

async def send_home(bot, chat_id:int, is_admin=False):
    await send_single_message(bot, chat_id, await get_setting_value('welcome_text', WELCOME_TEXT_DEFAULT), reply_markup=await main_menu_inline(is_admin))

@router.callback_query(F.data == CB_ACCOUNT)
async def account(callback: CallbackQuery):
    async with SessionLocal() as session:
        user=(await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one_or_none()
        active=(await session.execute(select(func.count(ClientService.id)).where(ClientService.user_id == user.id, ClientService.is_active == True))).scalar() if user else 0
        wallet_types = await available_wallet_types(session)
    if not user:
        await edit_or_answer(callback, 'کاربر پیدا نشد.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('back:main')]])); await callback.answer(); return
    joined=fa_date(user.joined_at, empty='-') if user.joined_at else '-'
    rows = [[InlineKeyboardButton(text=str(user.telegram_id), callback_data='noop'), InlineKeyboardButton(text='آیدی عددی 🆔:', callback_data='noop')]]
    rows.append([InlineKeyboardButton(text=f'{(user.wallet_balance or 0):,} تومان', callback_data='noop'), InlineKeyboardButton(text='کیف پول اصلی 💳:', callback_data='noop')])
    rows.extend([
        [InlineKeyboardButton(text=str(active), callback_data='noop'), InlineKeyboardButton(text='سرویس فعال 📦:', callback_data='noop')],
        [InlineKeyboardButton(text=joined, callback_data='noop'), InlineKeyboardButton(text='تاریخ عضویت 📅:', callback_data='noop')],
    ])
    wallet_button_text, wallet_button_enabled = await get_user_button('wallet_topup')
    if wallet_types and wallet_button_enabled:
        rows.append([InlineKeyboardButton(text=wallet_button_text, callback_data='wallet:topup')])
    elif not wallet_types:
        rows.append([InlineKeyboardButton(text='هنوز سروری برای شارژ کیف پول اضافه نشده است', callback_data='noop')])
    rows.append([back_button('back:main')])
    kb=InlineKeyboardMarkup(inline_keyboard=rows)
    await edit_or_answer(callback, '👤 حساب کاربری شما:', reply_markup=kb); await callback.answer()

@router.callback_query(F.data == 'wallet:topup')
async def wallet_topup(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    async with SessionLocal() as session:
        wallet_types = await available_wallet_types(session)
    if not wallet_types:
        await edit_or_answer(callback, 'هنوز هیچ سرور فعالی اضافه نشده است؛ بعد از اضافه شدن سرور، شارژ کیف پول فعال می‌شود.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('menu:account')]])); await callback.answer(); return
    await state.update_data(wallet_type='all')
    await state.set_state(WalletTopupFlow.amount)
    await edit_or_answer(callback, '💳 مبلغ شارژ کیف پول اصلی را به تومان وارد کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('menu:account')]])); await callback.answer()

@router.callback_query(F.data == 'wallet:back_amount')
async def wallet_back_amount(callback: CallbackQuery, state: FSMContext):
    await state.set_state(WalletTopupFlow.amount)
    await edit_or_answer(callback, '💳 مبلغ شارژ کیف پول اصلی را به تومان وارد کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('menu:account')]]))
    await callback.answer()

@router.callback_query(F.data.startswith('wallet:type:'))
async def wallet_type(callback: CallbackQuery, state: FSMContext):
    t=callback.data.split(':')[-1]
    async with SessionLocal() as session:
        wallet_types = await available_wallet_types(session)
    if t not in wallet_types:
        await edit_or_answer(callback, 'شارژ کیف پول در حال حاضر فعال نیست.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('menu:account')]])); await callback.answer(); return
    await state.update_data(wallet_type=t); await state.set_state(WalletTopupFlow.amount)
    await edit_or_answer(callback, 'مبلغ شارژ کیف پول اصلی را به تومان وارد کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('menu:account')]])); await callback.answer()

@router.message(WalletTopupFlow.amount)
async def wallet_amount(message: Message, state: FSMContext):
    amount=int(message.text.replace(',','').strip()); data=await state.get_data(); t=data['wallet_type']
    async with SessionLocal() as session:
        card=(await session.execute(select(PaymentCard).where(PaymentCard.is_active == True).order_by(PaymentCard.server_id.is_(None).desc(), PaymentCard.id.desc()))).scalars().first()
    if not card:
        await state.clear(); await ui_message(message, 'برای شارژ کیف پول هنوز شماره کارت ثبت نشده است.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('menu:account')]])); return
    await state.update_data(amount=amount); await state.set_state(WalletTopupFlow.receipt)
    await ui_message(message, f'💳 لطفاً مبلغ {amount:,} تومان را به کارت زیر واریز کنید و عکس رسید را ارسال کنید:\n\nشماره کارت: {card.card_number}\nنام صاحب حساب: {card.owner_name}', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('wallet:back_amount')]]))

@router.message(WalletTopupFlow.receipt, F.photo)
async def wallet_receipt(message: Message, state: FSMContext):
    data=await state.get_data(); file_id=message.photo[-1].file_id
    async with SessionLocal() as session:
        user=(await session.execute(select(User).where(User.telegram_id == message.from_user.id))).scalar_one()
        order=Order(user_id=user.id, amount_irt=int(data['amount']), payment_method=f'wallet_topup:{data["wallet_type"]}', status='waiting_receipt', receipt_file_id=file_id)
        session.add(order); await session.commit(); oid=order.id
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='✅ تایید شارژ کیف پول', callback_data=f'wallet_topup:approve:{oid}')],[InlineKeyboardButton(text='❌ رد شارژ کیف پول', callback_data=f'wallet_topup:reject:{oid}')]])
    caption = (
        f'💳 رسید شارژ کیف پول #{oid}\n'
        f'━━━━━━━━━━━━━━\n'
        f'💳 کیف پول: اصلی\n'
        f'💰 مبلغ: {int(data["amount"]):,} تومان\n\n'
        f'👤 نام کاربر: {message.from_user.full_name}\n'
        f'🔢 آیدی عددی: {message.from_user.id}\n'
        f'🆔 یوزرنیم تلگرام: {message.from_user.username or "ندارد"}\n'
        f'━━━━━━━━━━━━━━\n'
        f'لطفاً رسید را بررسی کنید و نتیجه را انتخاب کنید.'
    )
    for aid in settings.admin_ids:
        await message.bot.send_photo(aid, file_id, caption=caption, reply_markup=kb)
    await state.clear(); await ui_message(message, RECEIPT_RECEIVED_TEXT, reply_markup=receipt_received_keyboard())

@router.callback_query(F.data.startswith('wallet_topup:approve:'))
async def wallet_topup_approve(callback: CallbackQuery):
    if callback.from_user.id not in settings.admin_ids: return
    oid=int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        order=await session.get(Order, oid)
        if not order or order.status == 'paid':
            await mark_message_status(callback, '✅ رسید تایید شد.')
            await callback.answer('قبلاً تایید شده است.', show_alert=False)
            return
        user=await session.get(User, order.user_id)
        t=order.payment_method.split(':')[-1]; field=wallet_field(t)
        setattr(user, field, (getattr(user, field, 0) or 0) + order.amount_irt)
        order.status='paid'; await session.commit()
    await mark_message_status(callback, '✅ رسید تایید شد.')
    await callback.message.bot.send_message(user.telegram_id, f'✅ شارژ کیف پول اصلی به مبلغ {order.amount_irt:,} تومان تایید شد.')
    await send_home(callback.message.bot, user.telegram_id, user.telegram_id in settings.admin_ids)
    await ui_callback_message(callback, '✅ شارژ کیف پول تایید شد.'); await send_home(callback.message.bot, callback.from_user.id, True); await callback.answer()

@router.callback_query(F.data.startswith('wallet_topup:reject:'))
async def wallet_topup_reject(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in settings.admin_ids:
        return
    oid = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        order = await session.get(Order, oid)
        if not order:
            await mark_message_status(callback, '❌ سفارش پیدا نشد')
            await callback.answer('سفارش پیدا نشد.', show_alert=True)
            return
        if order.status == 'paid':
            await mark_message_status(callback, '✅ رسید تایید شد')
            await callback.answer('این رسید قبلاً تایید شده است.', show_alert=True)
            return
        if order.status == 'rejected':
            await mark_message_status(callback, '❌ رسید رد شد')
            await callback.answer('این رسید قبلاً رد شده است.', show_alert=True)
            return
    await state.clear()
    await state.update_data(
        wallet_reject_order_id=oid,
        wallet_receipt_chat_id=(callback.message.chat.id if callback.message else callback.from_user.id),
        wallet_receipt_message_id=(callback.message.message_id if callback.message else None),
    )
    await state.set_state(WalletReceiptReject.reason)
    await mark_message_status(callback, '✍️ دلیل رد را ارسال کنید')
    await callback.message.answer(
        f"""✍️ دلیل رد رسید شارژ کیف پول #{oid} را بنویسید.

همین متن برای کاربر ارسال و در سابقه سفارش ذخیره می‌شود."""
    )
    await callback.answer('دلیل رد را ارسال کنید.')


@router.message(WalletReceiptReject.reason)
async def wallet_topup_reject_reason(message: Message, state: FSMContext):
    if message.from_user.id not in settings.admin_ids:
        return
    reason = (message.text or '').strip()
    if not reason:
        await message.answer('❌ دلیل رد نمی‌تواند خالی باشد.')
        return
    if len(reason) > 1500:
        await message.answer('❌ متن دلیل خیلی طولانی است. حداکثر ۱۵۰۰ کاراکتر ارسال کنید.')
        return
    data = await state.get_data()
    oid = int(data.get('wallet_reject_order_id') or 0)
    chat_id = data.get('wallet_receipt_chat_id')
    message_id = data.get('wallet_receipt_message_id')
    async with SessionLocal() as session:
        order = await session.get(Order, oid)
        if not order:
            await state.clear(); await message.answer('❌ سفارش پیدا نشد.'); return
        user = await session.get(User, order.user_id)
        if order.status == 'paid':
            await state.clear()
            try: await message.bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=status_only_keyboard('✅ رسید تایید شد'))
            except Exception: pass
            await message.answer('این رسید قبلاً تایید شده است.')
            return
        if order.status == 'rejected':
            await state.clear()
            try: await message.bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=status_only_keyboard('❌ رسید رد شد'))
            except Exception: pass
            await message.answer('این رسید قبلاً رد شده است.')
            return
        order.status = 'rejected'
        order.rejection_reason = reason
        order.rejected_by = message.from_user.id
        order.rejected_at = datetime.utcnow()
        await session.commit()
    try:
        await message.bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=status_only_keyboard('❌ رسید رد شد'))
    except Exception:
        pass
    if user:
        rejection_text = (
            f"""❌ رسید شارژ کیف پول شما رد شد.

🧾 شماره درخواست: #{oid}
💰 مبلغ: {int(order.amount_irt or 0):,} تومان

📝 دلیل رد:
{reason}"""
        )
        await message.bot.send_message(
            user.telegram_id,
            rejection_text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='🏠 خانه', callback_data='home:main')]]),
        )
    await state.clear()
    try: await message.delete()
    except Exception: pass
    await send_home(message.bot, message.from_user.id, True)
