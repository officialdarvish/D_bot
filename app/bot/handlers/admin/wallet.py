from app.bot.utils import ui_message, ui_callback_message
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
from app.core.config import settings
from app.core.roles import is_owner
from app.database.session import SessionLocal
from app.database.models import User
from app.bot.states.admin_states import WalletChange
from app.services.wallet_service import WalletService
from app.bot.keyboards.common import CB_WALLET_ADJUST, back_button, back_admin_inline

router = Router()
def admin(uid): return is_owner(uid)

@router.callback_query(F.data == CB_WALLET_ADJUST)
async def wallet_start(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    await state.clear(); await state.set_state(WalletChange.telegram_id)
    await ui_callback_message(callback, 'آیدی عددی کاربر را وارد کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('back:admin')]])); await callback.answer()

@router.message(WalletChange.telegram_id)
async def wallet_uid(message: Message, state: FSMContext):
    await state.update_data(telegram_id=int(message.text.strip()))
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='افزایش موجودی', callback_data='wallet_mode:add'), InlineKeyboardButton(text='کاهش موجودی', callback_data='wallet_mode:sub')],[back_button('back:admin')]])
    await state.set_state(WalletChange.mode)
    await ui_message(message, 'نوع عملیات را انتخاب کنید:', reply_markup=kb)

@router.callback_query(F.data.startswith('wallet_mode:'))
async def wallet_mode(callback: CallbackQuery, state: FSMContext):
    await state.update_data(mode=callback.data.split(':')[-1])
    await state.set_state(WalletChange.amount)
    await ui_callback_message(callback, 'مبلغ را به تومان وارد کنید:'); await callback.answer()

@router.message(WalletChange.amount)
async def wallet_amount(message: Message, state: FSMContext):
    data=await state.get_data(); amount=int(message.text.replace(',','').strip())
    async with SessionLocal() as session:
        user=(await session.execute(select(User).where(User.telegram_id == int(data['telegram_id'])))).scalar_one_or_none()
        if not user:
            await ui_message(message, 'کاربر پیدا نشد.', reply_markup=back_admin_inline()); await state.clear(); return
        if data['mode'] == 'add':
            await WalletService().add_balance(session,user,amount,'admin add')
        else:
            user.wallet_balance -= amount
            await session.commit()
    await state.clear(); await ui_message(message, '✅ موجودی کاربر تغییر کرد.', reply_markup=back_admin_inline())
