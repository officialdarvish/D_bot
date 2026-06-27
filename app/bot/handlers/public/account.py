from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy import select, func
from app.core.config import settings
from app.database.session import SessionLocal
from app.database.models import User, ClientService, PaymentCard, Order, Server
from app.bot.keyboards.common import CB_ACCOUNT, BTN_WALLET_TOPUP, back_button, main_menu_inline
from app.bot.states.public_states import WalletTopupFlow
from app.bot.utils import send_single_message, edit_or_answer, ui_message, ui_callback_message
from app.database.defaults import get_setting_value, WELCOME_TEXT_DEFAULT

router = Router()

def receipt_received_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🏠 خانه', callback_data='noop')]
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

def wallet_type_title(t): return 'V2Ray' if t == 'xui' else 'OpenVPN - L2TP'
def wallet_field(t): return 'wallet_v2ray_balance' if t == 'xui' else 'wallet_openvpn_balance'

def _is_public_server(server: Server | None) -> bool:
    return bool(server) and bool(server.is_active) and ((server.meta or {}).get('scope') != 'reseller')

async def available_wallet_types(session) -> list[str]:
    rows = (await session.execute(select(Server).where(Server.is_active == True))).scalars().all()
    types: list[str] = []
    for srv in rows:
        if not _is_public_server(srv):
            continue
        t = 'openvpn' if (srv.server_type or '').lower() in ('openvpn', 'l2tp') else 'xui'
        if t not in types:
            types.append(t)
    return types

async def send_home(bot, chat_id:int, is_admin=False):
    await send_single_message(bot, chat_id, await get_setting_value('welcome_text', WELCOME_TEXT_DEFAULT), reply_markup=main_menu_inline(is_admin))

@router.callback_query(F.data == CB_ACCOUNT)
async def account(callback: CallbackQuery):
    async with SessionLocal() as session:
        user=(await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one_or_none()
        active=(await session.execute(select(func.count(ClientService.id)).where(ClientService.user_id == user.id, ClientService.is_active == True))).scalar() if user else 0
        wallet_types = await available_wallet_types(session)
    if not user:
        await edit_or_answer(callback, 'کاربر پیدا نشد.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('back:main')]])); await callback.answer(); return
    joined=user.joined_at.date().isoformat() if user.joined_at else '-'
    rows = [[InlineKeyboardButton(text=str(user.telegram_id), callback_data='noop'), InlineKeyboardButton(text='آیدی عددی 🆔:', callback_data='noop')]]
    if 'xui' in wallet_types:
        rows.append([InlineKeyboardButton(text=f'{(user.wallet_v2ray_balance or 0):,} تومان', callback_data='noop'), InlineKeyboardButton(text='کیف پول V2Ray 💎:', callback_data='noop')])
    if 'openvpn' in wallet_types:
        rows.append([InlineKeyboardButton(text=f'{(user.wallet_openvpn_balance or 0):,} تومان', callback_data='noop'), InlineKeyboardButton(text='کیف پول OpenVPN 🌐:', callback_data='noop')])
    rows.extend([
        [InlineKeyboardButton(text=str(active), callback_data='noop'), InlineKeyboardButton(text='سرویس فعال 📦:', callback_data='noop')],
        [InlineKeyboardButton(text=joined, callback_data='noop'), InlineKeyboardButton(text='تاریخ عضویت 📅:', callback_data='noop')],
    ])
    if wallet_types:
        rows.append([InlineKeyboardButton(text=BTN_WALLET_TOPUP, callback_data='wallet:topup')])
    else:
        rows.append([InlineKeyboardButton(text='هنوز سروری برای شارژ کیف پول اضافه نشده است', callback_data='noop')])
    rows.append([back_button('back:main')])
    kb=InlineKeyboardMarkup(inline_keyboard=rows)
    await edit_or_answer(callback, '👤 حساب کاربری شما:', reply_markup=kb); await callback.answer()

@router.callback_query(F.data == 'wallet:topup')
async def wallet_topup(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    async with SessionLocal() as session:
        wallet_types = await available_wallet_types(session)
    rows = []
    if 'xui' in wallet_types:
        rows.append([InlineKeyboardButton(text='شارژ کیف پول V2Ray', callback_data='wallet:type:xui')])
    if 'openvpn' in wallet_types:
        rows.append([InlineKeyboardButton(text='شارژ کیف پول OpenVPN - L2TP', callback_data='wallet:type:openvpn')])
    rows.append([back_button('menu:account')])
    if not wallet_types:
        await edit_or_answer(callback, 'هنوز هیچ سرور فعالی اضافه نشده است؛ بعد از اضافه شدن سرور، کیف پول همان نوع سرویس قابل شارژ می‌شود.', reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)); await callback.answer(); return
    kb=InlineKeyboardMarkup(inline_keyboard=rows)
    await edit_or_answer(callback, '💳 کدام کیف پول را می‌خواهید شارژ کنید؟', reply_markup=kb); await callback.answer()

@router.callback_query(F.data.startswith('wallet:type:'))
async def wallet_type(callback: CallbackQuery, state: FSMContext):
    t=callback.data.split(':')[-1]
    async with SessionLocal() as session:
        wallet_types = await available_wallet_types(session)
    if t not in wallet_types:
        await edit_or_answer(callback, 'برای این نوع سرویس هنوز سرور فعالی اضافه نشده است و کیف پول آن قابل شارژ نیست.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('menu:account')]])); await callback.answer(); return
    await state.update_data(wallet_type=t); await state.set_state(WalletTopupFlow.amount)
    await edit_or_answer(callback, f'مبلغ شارژ کیف پول {wallet_type_title(t)} را به تومان وارد کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('menu:account')]])); await callback.answer()

@router.message(WalletTopupFlow.amount)
async def wallet_amount(message: Message, state: FSMContext):
    amount=int(message.text.replace(',','').strip()); data=await state.get_data(); t=data['wallet_type']
    async with SessionLocal() as session:
        card=(await session.execute(select(PaymentCard).where(PaymentCard.server_type == t, PaymentCard.is_active == True))).scalar_one_or_none()
    if not card:
        await state.clear(); await ui_message(message, 'برای این نوع کیف پول هنوز شماره کارت ثبت نشده است.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('menu:account')]])); return
    await state.update_data(amount=amount); await state.set_state(WalletTopupFlow.receipt)
    await ui_message(message, f'💳 لطفاً مبلغ {amount:,} تومان را به کارت زیر واریز کنید و عکس رسید را ارسال کنید:\n\nشماره کارت: {card.card_number}\nنام صاحب حساب: {card.owner_name}', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('menu:account')]]))

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
        f'🏦 نوع کیف پول: {wallet_type_title(data["wallet_type"])}\n'
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
    await callback.message.bot.send_message(user.telegram_id, f'✅ شارژ کیف پول {wallet_type_title(t)} به مبلغ {order.amount_irt:,} تومان تایید شد.')
    await send_home(callback.message.bot, user.telegram_id, user.telegram_id in settings.admin_ids)
    await ui_callback_message(callback, '✅ شارژ کیف پول تایید شد.'); await send_home(callback.message.bot, callback.from_user.id, True); await callback.answer()

@router.callback_query(F.data.startswith('wallet_topup:reject:'))
async def wallet_topup_reject(callback: CallbackQuery):
    if callback.from_user.id not in settings.admin_ids: return
    oid=int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        order=await session.get(Order, oid); user=await session.get(User, order.user_id); order.status='rejected'; await session.commit()
    await mark_message_status(callback, '❌ رسید رد شد.')
    await callback.message.bot.send_message(user.telegram_id, '❌ رسید شارژ کیف پول شما رد شد.')
    await send_home(callback.message.bot, user.telegram_id, user.telegram_id in settings.admin_ids)
    await ui_callback_message(callback, 'رسید رد شد.'); await send_home(callback.message.bot, callback.from_user.id, True); await callback.answer()
