from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
from app.core.roles import is_owner
from app.database.session import SessionLocal
from app.database.models import User
from app.bot.states.admin_states import WalletChange
from app.services.wallet_service import WalletService
from app.bot.keyboards.common import CB_WALLET_ADJUST, back_button, back_admin_inline
from app.bot.utils import ui_message, ui_callback_message

router = Router()
def admin(uid): return is_owner(uid)


def wallet_admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text='➕ افزایش موجودی', callback_data='wallet_mode:add'),
            InlineKeyboardButton(text='➖ کاهش موجودی', callback_data='wallet_mode:sub'),
        ],
        [back_button('admin:user_interaction')],
    ])


@router.callback_query(F.data == CB_WALLET_ADJUST)
async def wallet_start(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    await state.clear()
    await state.set_state(WalletChange.mode)
    await ui_callback_message(
        callback,
        '💰 مدیریت کیف پول کاربر\n\nنوع عملیات را انتخاب کنید:',
        reply_markup=wallet_admin_menu(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith('wallet_mode:'))
async def wallet_mode(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    mode = callback.data.split(':')[-1]
    if mode not in {'add', 'sub'}:
        await callback.answer('عملیات نامعتبر است.', show_alert=True)
        return
    await state.update_data(mode=mode)
    await state.set_state(WalletChange.telegram_id)
    title = 'افزایش' if mode == 'add' else 'کاهش'
    await ui_callback_message(
        callback,
        f'🔢 آیدی عددی کاربر را برای {title} موجودی وارد کنید:',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:wallet_adjust')]]),
    )
    await callback.answer()


@router.message(WalletChange.telegram_id)
async def wallet_uid(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    raw = (message.text or '').strip()
    if not raw.isdigit():
        await ui_message(message, '❌ فقط آیدی عددی تلگرام کاربر را وارد کنید. مثال: 123456789')
        return
    telegram_id = int(raw)
    data = await state.get_data()
    mode = data.get('mode')
    async with SessionLocal() as session:
        user = (await session.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one_or_none()
    if not user:
        await ui_message(message, '❌ کاربری با این آیدی عددی پیدا نشد.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:wallet_adjust')]]))
        return
    await state.update_data(telegram_id=telegram_id)
    await state.set_state(WalletChange.amount)
    action = 'افزایش' if mode == 'add' else 'کاهش'
    await ui_message(
        message,
        f'💰 عملیات: {action} موجودی\n'
        f'👤 کاربر: {user.full_name or "-"}\n'
        f'🔢 آیدی عددی: {user.telegram_id}\n'
        f'💳 موجودی فعلی: {int(user.wallet_balance or 0):,} تومان\n\n'
        'مبلغ را به تومان وارد کنید:',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:wallet_adjust')]]),
    )


@router.message(WalletChange.amount)
async def wallet_amount(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    raw = (message.text or '').replace(',', '').replace('٬', '').strip()
    if not raw.isdigit() or int(raw) <= 0:
        await ui_message(message, '❌ مبلغ معتبر نیست. فقط عدد مثبت به تومان وارد کنید.')
        return
    amount = int(raw)
    data = await state.get_data()
    telegram_id = int(data.get('telegram_id') or 0)
    mode = data.get('mode')
    async with SessionLocal() as session:
        user = (await session.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one_or_none()
        if not user:
            await ui_message(message, '❌ کاربر پیدا نشد.', reply_markup=back_admin_inline())
            await state.clear()
            return
        before = int(user.wallet_balance or 0)
        if mode == 'add':
            await WalletService().add_balance(session, user, amount, 'admin wallet credit')
            action_text = 'افزایش'
        else:
            ok = await WalletService().charge(session, user, amount, 'admin wallet debit')
            if not ok:
                await ui_message(
                    message,
                    f'❌ موجودی کاربر کافی نیست.\n\nموجودی فعلی: {before:,} تومان\nمبلغ درخواستی: {amount:,} تومان',
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:wallet_adjust')]]),
                )
                return
            action_text = 'کاهش'
        after = int(user.wallet_balance or 0)
    await state.clear()
    await ui_message(
        message,
        f'✅ کیف پول کاربر با موفقیت {action_text} داده شد.\n\n'
        f'🔢 آیدی عددی: {telegram_id}\n'
        f'💳 موجودی قبلی: {before:,} تومان\n'
        f'🔁 مبلغ عملیات: {amount:,} تومان\n'
        f'💰 موجودی جدید: {after:,} تومان',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:user_interaction')]]),
    )
