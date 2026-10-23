"""Dedicated PAYG reseller wallet: internal transfer and owner-reviewed receipts."""
import html
import uuid
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select
from app.core.config import settings
from app.database.session import SessionLocal
from app.database.models import User, ResellerAccount, PaymentCard, ResellerWalletReceipt, ResellerBillingEntry, WalletTransaction
from app.services.reseller_billing import is_payg, credit
from app.bot.utils import edit_or_answer, ui_message

router=Router()
class WalletFlow(StatesGroup):
    amount=State()
    method=State()
    receipt=State()


def back():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='بازگشت به نمایندگی',callback_data='menu:reseller')]])


async def account_for(session,tid,lock=False):
    user=await session.scalar(select(User).where(User.telegram_id==tid))
    q=select(ResellerAccount).where(ResellerAccount.user_id==user.id) if user else None
    account=await session.scalar(q.with_for_update() if lock else q) if q is not None else None
    if not account or not is_payg(account):raise ValueError('کیف پول PAYG برای شما فعال نیست.')
    # Expired accounts may recharge and repay debt without gaining provisioning access.
    return user,account


@router.callback_query(F.data=='paygwallet:topup')
async def wallet_start(callback:CallbackQuery,state:FSMContext):
    async with SessionLocal() as session:
        try:user,account=await account_for(session,callback.from_user.id)
        except ValueError as e:await callback.answer(str(e),show_alert=True);return
    await state.clear();await state.set_state(WalletFlow.amount)
    await edit_or_answer(callback,f'💳 کیف پول نمایندگی PAYG\nموجودی: {account.wallet_balance_irt:,} تومان\n\nمبلغ شارژ را به تومان وارد کنید (حداقل ۱۰٬۰۰۰ تومان).',reply_markup=back())
    await callback.answer()


@router.message(WalletFlow.amount)
async def wallet_amount(message:Message,state:FSMContext):
    try:amount=int((message.text or '').replace(',','').replace('٬','').strip())
    except ValueError:amount=0
    if not 10000<=amount<=10**10:
        await ui_message(message,'مبلغ معتبر بین ۱۰٬۰۰۰ و ۱۰ میلیارد تومان وارد کنید.');return
    await state.update_data(payg_amount=amount,payg_operation=uuid.uuid4().hex)
    await state.set_state(WalletFlow.method)
    await ui_message(message,f'مبلغ شارژ: {amount:,} تومان\nروش شارژ را انتخاب کنید:',reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='انتقال از کیف پول شخصی',callback_data='paygwallet:personal')],
        [InlineKeyboardButton(text='کارت به کارت و ارسال رسید',callback_data='paygwallet:card')],
        [InlineKeyboardButton(text='بازگشت',callback_data='menu:reseller')]]))


@router.callback_query(WalletFlow.method,F.data=='paygwallet:personal')
async def from_personal(callback:CallbackQuery,state:FSMContext):
    data=await state.get_data();amount=int(data.get('payg_amount') or 0);op=str(data.get('payg_operation') or '')
    if amount<=0 or not op:await callback.answer('دوباره مبلغ را وارد کنید.',show_alert=True);return
    async with SessionLocal() as session:
        try:
            user,account=await account_for(session,callback.from_user.id,lock=True)
            key=f'wallet-transfer:{account.id}:{op}'
            already=await session.scalar(select(ResellerBillingEntry.id).where(ResellerBillingEntry.event_key==key))
            if not already:
                user=await session.get(User,user.id,with_for_update=True,populate_existing=True)
                if int(user.wallet_balance or 0)<amount:raise ValueError('موجودی کیف پول شخصی کافی نیست.')
                user.wallet_balance=int(user.wallet_balance or 0)-amount
                await credit(session,account,amount,key=key,kind='personal_transfer',note=f'Transfer by Telegram {user.telegram_id}')
                session.add(WalletTransaction(user_id=user.id,amount_irt=-amount,tx_type='reseller_transfer',description='Transfer to independent reseller PAYG wallet'))
                await session.commit()
        except ValueError as e:await callback.answer(str(e),show_alert=True);return
    await state.clear();await edit_or_answer(callback,f'✅ شارژ کیف پول نمایندگی انجام شد.\nموجودی: {account.wallet_balance_irt:,} تومان',reply_markup=back());await callback.answer()
    for admin in settings.admin_ids:
        try:await callback.bot.send_message(admin,f'💳 انتقال به کیف پول نمایندگی\nکاربر: {user.full_name}\nID: {user.telegram_id}\nمبلغ: {amount:,} تومان\nموجودی نمایندگی: {account.wallet_balance_irt:,} تومان')
        except Exception:pass


@router.callback_query(WalletFlow.method,F.data=='paygwallet:card')
async def wallet_card(callback:CallbackQuery,state:FSMContext):
    async with SessionLocal() as session:
        user,account=await account_for(session,callback.from_user.id)
        cards=(await session.execute(select(PaymentCard).where(PaymentCard.is_active.is_(True),PaymentCard.server_type=='reseller',(PaymentCard.server_id.is_(None) | PaymentCard.server_id.in_(account.allowed_server_ids or ([account.server_id] if account.server_id else [])))))).scalars().all()
    if not cards:await callback.answer('کارت پرداخت نمایندگی ثبت نشده است؛ انتقال از کیف پول شخصی را انتخاب کنید.',show_alert=True);return
    text='به یکی از حساب‌های زیر واریز کنید و عکس یا فایل رسید را بفرستید:\n\n'+'\n'.join(f'{c.owner_name}\n{c.card_number}\n' for c in cards)
    await state.set_state(WalletFlow.receipt);await edit_or_answer(callback,text,reply_markup=back());await callback.answer()


@router.message(WalletFlow.receipt)
async def wallet_receipt(message:Message,state:FSMContext):
    photo=bool(message.photo);file=message.photo[-1] if photo else message.document
    if not file:await ui_message(message,'لطفاً عکس یا فایل رسید پرداخت را ارسال کنید.');return
    data=await state.get_data();amount=int(data.get('payg_amount') or 0)
    if amount<=0:await state.clear();await ui_message(message,'مبلغ شارژ منقضی شده؛ دوباره شروع کنید.',reply_markup=back());return
    async with SessionLocal() as session:
        user,account=await account_for(session,message.from_user.id,lock=True)
        prior=await session.scalar(select(ResellerWalletReceipt.id).where(ResellerWalletReceipt.reseller_id==account.id,ResellerWalletReceipt.file_id==file.file_id,ResellerWalletReceipt.status.in_(['pending','approved'])))
        if prior:await ui_message(message,'این رسید قبلاً ثبت شده است.',reply_markup=back());return
        receipt=ResellerWalletReceipt(reseller_id=account.id,amount_irt=amount,file_id=file.file_id,is_photo=photo)
        session.add(receipt);await session.commit();rid=receipt.id
    await state.clear();await ui_message(message,'رسید شارژ نمایندگی برای مدیر ارسال شد و در انتظار تایید است.',reply_markup=back())
    caption=f'🧾 شارژ کیف پول نمایندگی PAYG #{rid}\nنام: {html.escape(user.full_name or "-")}\nID: {user.telegram_id}\nUsername: @{html.escape(user.username or "-")}\nمبلغ: {amount:,} تومان\nتاریخ: {receipt.created_at}'
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='تایید',callback_data=f'paygwallet:review:approve:{rid}'),InlineKeyboardButton(text='رد',callback_data=f'paygwallet:review:reject:{rid}')]])
    for admin in settings.admin_ids:
        try:
            if photo:await message.bot.send_photo(admin,receipt.file_id,caption=caption,reply_markup=kb)
            else:await message.bot.send_document(admin,receipt.file_id,caption=caption,reply_markup=kb)
        except Exception:pass


@router.callback_query(F.data.startswith('paygwallet:review:'))
async def wallet_review(callback:CallbackQuery):
    if callback.from_user.id not in settings.admin_ids:await callback.answer('دسترسی ندارید.',show_alert=True);return
    parts=callback.data.split(':');approve=parts[2]=='approve'
    if parts[2] not in {'approve','reject'} or not parts[-1].isdigit():return
    async with SessionLocal() as session:
        from app.services.reseller_billing import review_receipt
        result=await review_receipt(session,int(parts[-1]),callback.from_user.id,approve)
        if not result:
            await callback.answer('این رسید قبلاً بررسی شده است.',show_alert=True);return
        receipt,account,user=result
        from app.services.miniapp_runtime import is_native_receipt
        native=await is_native_receipt(session,user.id,'payg',receipt.id)
        await session.commit()
    if approve:
        from app.services.reseller_billing import reconcile_suspensions
        await reconcile_suspensions()
    try: await callback.message.edit_reply_markup(reply_markup=None)
    except Exception: pass
    await callback.answer('تایید شد' if approve else 'رد شد')
    try:
        if approve or not native:await callback.bot.send_message(user.telegram_id,('✅ رسید شارژ کیف پول نمایندگی تایید شد.' if approve else '❌ رسید شارژ کیف پول نمایندگی رد شد.')+f'\nمبلغ: {receipt.amount_irt:,} تومان\nموجودی: {account.wallet_balance_irt:,} تومان',reply_markup=back())
    except Exception:pass
