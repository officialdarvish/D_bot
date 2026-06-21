from datetime import datetime, timedelta
import random, string, re
from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy import select, func
from app.core.config import settings
from app.database.session import SessionLocal
from app.database.models import User, Server, ServerCategory, Plan, PaymentCard, Order, ClientService, DiscountCode, DiscountUsage
from app.bot.states.public_states import BuyFlow, QueryClient, DiscountInput
from app.services.xui_service import XuiService
from app.services.nowpayments_service import NowPaymentsService
from app.bot.keyboards.common import CB_BUY, CB_QUERY, back_button, back_main_inline, main_menu_inline
from app.database.defaults import get_setting_value, WELCOME_TEXT_DEFAULT
from app.bot.utils import edit_or_answer, ui_message, ui_callback_message
from app.bot.service_presenter import send_service_info as send_service_card

router = Router()

def rnd_suffix(): return ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))
def extract_key(text: str) -> str:
    text=text.strip()
    m=re.search(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}', text)
    if m: return m.group(0)
    return text.rstrip('/').split('/')[-1].split('?')[0].split('#')[0]
def server_type_filter(kind: str): return 'xui' if kind == 'v2ray' else 'openvpn'
def wallet_field(server_type: str): return 'wallet_v2ray_balance' if server_type == 'xui' else 'wallet_openvpn_balance'

async def get_service_type_ui(kind: str) -> tuple[bool, str]:
    if kind == 'v2ray':
        enabled = await get_setting_value('service_type_v2ray_enabled', '1')
        label = await get_setting_value('service_type_v2ray_label', 'V2Ray')
    else:
        enabled = await get_setting_value('service_type_openvpn_enabled', '1')
        label = await get_setting_value('service_type_openvpn_label', 'OpenVPN - L2TP')
    return enabled == '1', label
def gb(bytes_val): return bytes_val/1024**3 if bytes_val else 0

def percent_bar(used: int, total: int, width: int = 14) -> str:
    if not total or total <= 0:
        return '▱' * width
    ratio = max(0, min(1, (used or 0) / total))
    filled = int(round(ratio * width))
    return '▰' * filled + '▱' * (width - filled)

def pretty_config_result(*, username: str, active: bool, plan_title: str = 'نامشخص', created_at: str = '-', expires_at: str = '-', total: int = 0, used: int = 0, uuid: str | None = None) -> str:
    remain = max((total or 0) - (used or 0), 0)
    pct = int(((used or 0) / total) * 100) if total else 0
    status_icon = '🟢' if active else '🔴'
    status_text = 'فعال' if active else 'غیرفعال'
    uuid_line = f'│ 🆔 UUID: {uuid}\n' if uuid else ''
    return (
        '✅ کانفیگ با مشخصات زیر پیدا شد\n'
        '╭━━━━━━━━━━━━━━━━━━━━╮\n'
        f'│ 🚀 نام کانفیگ: {username or "-"}\n'
        f'│ {status_icon} وضعیت: {status_text}\n'
        f'│ 📦 پلن انتخابی: {plan_title or "نامشخص"}\n'
        f'{uuid_line}'
        '╰━━━━━━━━━━━━━━━━━━━━╯\n\n'
        '📅 زمان‌بندی سرویس\n'
        f'├ 🛒 تاریخ خرید: {created_at or "-"}\n'
        f'╰ ⏳ تاریخ انقضا: {expires_at or "-"}\n\n'
        '📊 وضعیت مصرف\n'
        f'├ 💾 حجم کل: {gb(total):.2f} گیگ\n'
        f'├ 📈 مصرف‌شده: {gb(used):.2f} گیگ\n'
        f'├ ⏳ باقی‌مانده: {gb(remain):.2f} گیگ\n'
        f'╰ {percent_bar(used, total)} {pct}%\n\n'
        '— ✦ Darvish D Bot ✦ —'
    )


async def apply_discount_amount(session, code: str | None, amount: int, user_id: int | None = None, source: str = 'buy') -> tuple[int, str | None, DiscountCode | None]:
    if not code:
        return amount, None, None
    clean = code.strip().upper().replace(' ', '')
    d = (await session.execute(select(DiscountCode).where(DiscountCode.code == clean, DiscountCode.is_active == True))).scalar_one_or_none()
    if not d:
        return amount, 'کد تخفیف معتبر نیست.', None
    if d.expires_at and d.expires_at < datetime.utcnow():
        return amount, 'کد تخفیف منقضی شده است.', None
    if d.max_uses and d.used_count >= d.max_uses:
        return amount, 'ظرفیت استفاده از این کد تکمیل شده است.', None
    if user_id and getattr(d, 'per_user_limit', 1):
        used_by_user = (await session.execute(
            select(func.count(DiscountUsage.id)).where(DiscountUsage.discount_id == d.id, DiscountUsage.user_id == user_id)
        )).scalar() or 0
        if used_by_user >= d.per_user_limit:
            return amount, f'شما قبلاً از این کد {used_by_user} بار استفاده کرده‌اید و سقف استفاده شما تکمیل شده است.', None
    if d.discount_type == 'percent':
        discount = int(amount * min(max(d.value, 0), 100) / 100)
    else:
        discount = int(d.value)
    final = max(amount - discount, 0)
    return final, None, d

async def mark_discount_used(session, discount_obj: DiscountCode | None, user_id: int, source: str = 'buy') -> None:
    if not discount_obj:
        return
    discount_obj.used_count += 1
    session.add(DiscountUsage(discount_id=discount_obj.id, user_id=user_id, source=source))

async def pick_available_username(session, server, base_username: str) -> str:
    """Return a username that is free in both local DB and the real 3x-ui panel.

    This protects retries after a partial panel creation: the DB may have rolled
    back while 3x-ui already kept the client, so checking only ClientService is
    not enough.
    """
    clean = re.sub(r'[^A-Za-z0-9_]', '', (base_username or '').strip().replace(' ', ''))
    if not clean:
        clean = 'user' + rnd_suffix()

    for idx in range(20):
        candidate = clean if idx == 0 else f'{clean}{rnd_suffix()}'
        local = (await session.execute(
            select(ClientService).where(
                ClientService.server_id == server.id,
                (ClientService.client_username == candidate) | (ClientService.xui_email == candidate),
            )
        )).scalar_one_or_none()
        if local:
            continue

        if server.server_type == 'xui':
            try:
                remote = await XuiService().find_client_any(server, candidate)
            except Exception:
                remote = None
            if remote:
                continue

        return candidate

    return f'{clean}{rnd_suffix()}{rnd_suffix()}'

async def send_home(bot, chat_id:int, is_admin: bool=False):
    text=await get_setting_value('welcome_text', WELCOME_TEXT_DEFAULT)
    await bot.send_message(chat_id, text, reply_markup=main_menu_inline(is_admin))

def is_admin_user(user_id: int) -> bool:
    return user_id in settings.admin_ids

def plan_price_text(plan, is_admin: bool = False) -> str:
    if is_admin:
        return f'{plan.title} - رایگان برای مدیر'
    return f'{plan.title} - {plan.price_irt:,} تومان'

@router.callback_query(F.data == CB_BUY)
async def buy_start(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    rows = []
    v2_enabled, v2_label = await get_service_type_ui('v2ray')
    ov_enabled, ov_label = await get_service_type_ui('openvpn')
    if v2_enabled:
        rows.append([InlineKeyboardButton(text=f'🔵 {v2_label}', callback_data='buy:type:v2ray')])
    if ov_enabled:
        rows.append([InlineKeyboardButton(text=f'🟣 {ov_label}', callback_data='buy:type:openvpn')])
    if not rows:
        rows.append([InlineKeyboardButton(text='در حال حاضر هیچ نوع سرویسی فعال نیست', callback_data='noop')])
    rows.append([back_button('back:main')])
    kb=InlineKeyboardMarkup(inline_keyboard=rows)
    await edit_or_answer(callback, 'نوع سرویس را انتخاب کنید:', reply_markup=kb); await callback.answer()

@router.callback_query(F.data.startswith('buy:type:'))
async def buy_type(callback: CallbackQuery, state: FSMContext):
    kind=callback.data.split(':')[-1]; stype=server_type_filter(kind)
    await state.update_data(kind=kind, server_type=stype)
    async with SessionLocal() as session:
        all_servers=(await session.execute(select(Server).where(Server.is_active == True, Server.server_type == stype))).scalars().all()
        servers=[s for s in all_servers if (s.meta or {}).get('scope') != 'reseller']
    if not servers:
        await edit_or_answer(callback, 'در حال حاضر هیچ سروری برای این نوع سرویس فعال نیست.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('menu:buy')]])); await callback.answer(); return
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=s.name, callback_data=f'buy:server:{s.id}')] for s in servers] + [[back_button('menu:buy')]])
    await edit_or_answer(callback, 'سرور موردنظر را انتخاب کنید:', reply_markup=kb); await callback.answer()

@router.callback_query(F.data.startswith('buy:server:'))
async def buy_server(callback: CallbackQuery, state: FSMContext):
    sid=int(callback.data.split(':')[-1]); await state.update_data(server_id=sid)
    async with SessionLocal() as session:
        cats=(await session.execute(select(ServerCategory).where(ServerCategory.server_id == sid))).scalars().all()
    if not cats:
        await edit_or_answer(callback, 'برای این سرور هنوز دسته‌ای ثبت نشده است.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('menu:buy')]])); await callback.answer(); return
    data=await state.get_data()
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=c.name, callback_data=f'buy:cat:{c.id}')] for c in cats] + [[back_button(f'buy:type:{data.get("kind", "v2ray")}')]])
    await edit_or_answer(callback, 'دسته موردنظر را انتخاب کنید:', reply_markup=kb); await callback.answer()

@router.callback_query(F.data.startswith('buy:cat:'))
async def buy_category(callback: CallbackQuery, state: FSMContext):
    cid=int(callback.data.split(':')[-1]); data=await state.get_data(); await state.update_data(category_id=cid)
    async with SessionLocal() as session:
        plans=(await session.execute(select(Plan).where(Plan.server_id == data['server_id'], Plan.category_id == cid, Plan.is_active == True))).scalars().all()
    if not plans:
        await edit_or_answer(callback, 'برای این دسته هیچ پلنی ثبت نشده است.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(f'buy:server:{data["server_id"]}')]])); await callback.answer(); return
    is_admin = is_admin_user(callback.from_user.id)
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=plan_price_text(p, is_admin), callback_data=f'buy:plan:{p.id}')] for p in plans] + [[back_button(f'buy:server:{data["server_id"]}')]])
    await edit_or_answer(callback, 'پلن موردنظر را انتخاب کنید:', reply_markup=kb); await callback.answer()

@router.callback_query(F.data.startswith('buy:plan:'))
async def buy_plan(callback: CallbackQuery, state: FSMContext):
    pid=int(callback.data.split(':')[-1]); await state.update_data(plan_id=pid)
    async with SessionLocal() as session:
        plan=await session.get(Plan,pid); server=await session.get(Server, plan.server_id)
        user=(await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one()
    await state.set_state(BuyFlow.username)
    await edit_or_answer(callback, 'یک یوزرنیم اختصاصی با حروف و عدد وارد کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('back:main')]])); await callback.answer()

@router.message(BuyFlow.username)
async def buy_username(message: Message, state: FSMContext):
    username=message.text.strip().replace(' ','')
    data=await state.get_data()
    async with SessionLocal() as session:
        server=await session.get(Server, data['server_id'])
        plan=await session.get(Plan, data['plan_id'])
        user=(await session.execute(select(User).where(User.telegram_id == message.from_user.id))).scalar_one()
        final_username = await pick_available_username(session, server, username)
        if message.from_user.id in settings.admin_ids:
            try:
                service, sub_link = await build_service(session, user, server, plan, final_username)
                session.add(Order(user_id=user.id, plan_id=plan.id, service_id=service.id, amount_irt=0, payment_method='admin_free', status='paid'))
                await session.commit()
            except Exception as e:
                await session.rollback()
                await ui_message(message, f'❌ ساخت سرویس روی پنل با خطا مواجه شد:\n{e}', reply_markup=back_main_inline())
                await state.clear()
                return
            await state.clear()
            await send_service_info(message.bot, message.from_user.id, service.client_username, plan, sub_link)
            await send_home(message.bot, message.from_user.id, True)
            return
    if final_username != username:
        username = final_username
        await ui_message(message, f'این یوزرنیم قبلاً استفاده شده بود. یوزرنیم جدید شما: {username}')
    await state.update_data(username=username, discount_code=None, final_amount=None); await state.set_state(BuyFlow.payment_method)
    kb=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🏷 اعمال کد تخفیف', callback_data='pay:discount')],
        [InlineKeyboardButton(text='کیف پول', callback_data='pay:wallet'), InlineKeyboardButton(text='کارت به کارت', callback_data='pay:card')],
        [back_button(f'buy:plan:{data["plan_id"]}')]
    ])
    await ui_message(message, 'روش پرداخت را انتخاب کنید:\n\nاگر کد تخفیف دارید، ابتدا روی «اعمال کد تخفیف» بزنید.', reply_markup=kb)

@router.callback_query(F.data == 'pay:discount')
async def buy_discount_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(DiscountInput.code)
    await edit_or_answer(callback, '🏷 کد تخفیف را وارد کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('pay:back_methods')]]))
    await callback.answer()

@router.callback_query(F.data == 'pay:back_methods')
async def buy_discount_back(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.set_state(BuyFlow.payment_method)
    kb=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🏷 اعمال کد تخفیف', callback_data='pay:discount')],
        [InlineKeyboardButton(text='کیف پول', callback_data='pay:wallet'), InlineKeyboardButton(text='کارت به کارت', callback_data='pay:card')],
        [back_button(f'buy:plan:{data["plan_id"]}')]
    ])
    await edit_or_answer(callback, 'گزینه پرداخت را انتخاب کنید:', reply_markup=kb); await callback.answer()

@router.message(DiscountInput.code)
async def buy_discount_apply(message: Message, state: FSMContext):
    code = (message.text or '').strip().upper().replace(' ', '')
    data = await state.get_data()
    async with SessionLocal() as session:
        plan = await session.get(Plan, data['plan_id'])
        user=(await session.execute(select(User).where(User.telegram_id == message.from_user.id))).scalar_one()
        final, err, d = await apply_discount_amount(session, code, plan.price_irt, user.id, 'buy')
    if err:
        await ui_message(message, '❌ ' + err, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('pay:back_methods')]])); return
    await state.update_data(discount_code=code, final_amount=final)
    await state.set_state(BuyFlow.payment_method)
    kb=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='کیف پول', callback_data='pay:wallet'), InlineKeyboardButton(text='کارت به کارت', callback_data='pay:card')],
        [back_button(f'buy:plan:{data["plan_id"]}')]
    ])
    await ui_message(message, f'✅ کد تخفیف اعمال شد.\n\nمبلغ قبلی: {plan.price_irt:,} تومان\nمبلغ جدید: {final:,} تومان\n\nحالا روش پرداخت را انتخاب کنید:', reply_markup=kb)

async def build_service(session, user, server, plan, username):
    username = await pick_available_username(session, server, username)
    service=ClientService(user_id=user.id, server_id=server.id, plan_id=plan.id, client_username=username, xui_email=username, inbound_ids=plan.inbound_ids, total_bytes=plan.volume_gb*1024**3, expires_at=(datetime.utcnow()+timedelta(days=plan.duration_days) if plan.duration_days else None), is_payg=plan.is_payg)
    session.add(service); await session.flush()
    sub_link=None
    if server.server_type == 'xui':
        created=await XuiService().create_client_on_plan(server, plan, username)
        sub_link=created.get('sub_link') if isinstance(created, dict) else None
        service.sub_link=sub_link; service.xui_uuid=created.get('uuid') if isinstance(created, dict) else None
    return service, sub_link

async def send_service_info(bot, chat_id, username, plan, sub_link):
    await send_service_card(
        bot,
        chat_id,
        username,
        plan.title,
        plan.volume_gb,
        plan.duration_days,
        sub_link,
        is_test=False,
    )

@router.callback_query(F.data.in_({'pay:wallet','pay:card','pay:crypto'}))
async def buy_payment(callback: CallbackQuery, state: FSMContext):
    data=await state.get_data()
    async with SessionLocal() as session:
        user=(await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one()
        plan=await session.get(Plan,data['plan_id']); server=await session.get(Server,data['server_id'])
        final_amount = int(data.get('final_amount') or plan.price_irt)
        discount_code = data.get('discount_code')
        discount_obj = None
        if discount_code:
            final_amount, err, discount_obj = await apply_discount_amount(session, discount_code, plan.price_irt, user.id, 'buy')
            if err:
                await ui_callback_message(callback, '❌ ' + err, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('pay:discount')]])); await callback.answer(); return
        if callback.data == 'pay:crypto':
            order = Order(user_id=user.id, plan_id=plan.id, amount_irt=final_amount, payment_method=f'crypto:{data["username"]}' + (f':discount:{discount_code}' if discount_code else ''), status='waiting_crypto')
            session.add(order)
            await session.flush()
            try:
                pay = await NowPaymentsService().create_payment(order_id=order.id, amount_irt=final_amount, description=f'Darvish D Bot - {plan.title}')
            except Exception as e:
                await session.rollback()
                await ui_callback_message(callback, f'❌ ساخت پرداخت کریپتو ناموفق بود:\n{e}', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('pay:back_methods')]]))
                await callback.answer(); return
            order.external_payment_id = str(pay.get('payment_id') or '')
            order.external_invoice_url = pay.get('invoice_url') or pay.get('payment_url') or None
            await mark_discount_used(session, discount_obj, user.id, 'buy')
            await session.commit(); await state.clear()
            pay_amount = pay.get('pay_amount') or '-'
            pay_currency = (pay.get('pay_currency') or settings.NOWPAYMENTS_PAY_CURRENCY).upper()
            address = pay.get('pay_address') or '-'
            text = (
                f'🪙 پرداخت کریپتو ساخته شد\n\n'
                f'💰 مبلغ پرداخت: {pay_amount} {pay_currency}\n'
                f'📥 آدرس کیف پول:\n`{address}`\n\n'
                f'بعد از تایید شبکه، سفارش خودکار قابل پیگیری است. شناسه سفارش: #{order.id}'
            )
            if order.external_invoice_url:
                text += f'\n\n🔗 لینک پرداخت:\n{order.external_invoice_url}'
            await ui_callback_message(callback, text, reply_markup=back_main_inline())
            await callback.answer(); return

        if callback.data == 'pay:wallet':
            field=wallet_field(server.server_type); balance=getattr(user, field, 0) or 0
            if balance < final_amount:
                await ui_callback_message(callback, 'موجودی کیف پول این نوع سرویس کافی نیست. لطفاً کیف پول همان بخش را شارژ کنید و دوباره تلاش کنید.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('menu:account')]])); await state.clear(); await callback.answer(); return
            setattr(user, field, balance - final_amount)
            try:
                service, sub_link = await build_service(session, user, server, plan, data['username'])
            except Exception as e:
                await session.rollback(); await ui_callback_message(callback, f'❌ ساخت سرویس روی پنل با خطا مواجه شد:\n{e}', reply_markup=back_main_inline()); await state.clear(); await callback.answer(); return
            
            await mark_discount_used(session, discount_obj, user.id, 'buy')
            session.add(Order(user_id=user.id, plan_id=plan.id, service_id=service.id, amount_irt=final_amount, payment_method=('wallet' + (f':discount:{discount_code}' if discount_code else '')), status='paid'))
            await session.commit(); await state.clear(); await callback.answer()
            await send_service_info(callback.message.bot, callback.from_user.id, service.client_username, plan, sub_link)
            await send_home(callback.message.bot, callback.from_user.id, callback.from_user.id in settings.admin_ids)
            return
        card=(await session.execute(select(PaymentCard).where(PaymentCard.server_id == server.id, PaymentCard.is_active == True))).scalar_one_or_none()
        if not card:
            card=(await session.execute(select(PaymentCard).where(PaymentCard.server_type == server.server_type, PaymentCard.is_active == True))).scalar_one_or_none()
        if not card:
            await ui_callback_message(callback, 'برای این سرور هنوز شماره کارت ثبت نشده است.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('back:main')]])); await state.clear(); await callback.answer(); return
        
        await mark_discount_used(session, discount_obj, user.id, 'buy')
        order=Order(user_id=user.id, plan_id=plan.id, amount_irt=final_amount, payment_method=f'card:{data["username"]}' + (f':discount:{discount_code}' if discount_code else ''), status='waiting_receipt')
        session.add(order); await session.commit(); await state.update_data(order_id=order.id)
    await state.set_state(BuyFlow.receipt)
    await ui_callback_message(callback, f'لطفاً مبلغ {final_amount:,} تومان را به کارت زیر واریز کنید و عکس رسید را ارسال کنید:\n\nشماره کارت: {card.card_number}\nنام صاحب حساب: {card.owner_name}', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('back:main')]])); await callback.answer()

@router.message(BuyFlow.receipt, F.photo)
async def buy_receipt(message: Message, state: FSMContext):
    data=await state.get_data(); file_id=message.photo[-1].file_id
    async with SessionLocal() as session:
        order=await session.get(Order,data['order_id']); order.receipt_file_id=file_id
        plan=await session.get(Plan, order.plan_id); server=await session.get(Server, plan.server_id)
        await session.commit()
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='✅ تایید رسید', callback_data=f'order:approve:{data["order_id"]}')],[InlineKeyboardButton(text='❌ رد رسید', callback_data=f'order:reject:{data["order_id"]}')]])
    discount_code = None
    if order.payment_method and ':discount:' in order.payment_method:
        discount_code = order.payment_method.split(':discount:', 1)[1]
    original_amount = int(plan.price_irt or 0)
    discount_info = f'🏷 کد تخفیف: {discount_code}\n💵 مبلغ نهایی: {order.amount_irt:,} تومان\n' if discount_code else ''
    caption = (
        f'🧾 رسید سفارش #{data["order_id"]}\n'
        f'━━━━━━━━━━━━━━\n'
        f'👤 نام مشتری: {message.from_user.full_name}\n'
        f'🔢 آیدی عددی: {message.from_user.id}\n'
        f'🆔 یوزرنیم تلگرام: {message.from_user.username or "ندارد"}\n\n'
        f'👥 یوزرنیم سرویس: {data.get("username")}\n'
        f'📦 پلن: {plan.title}\n'
        f'💰 مبلغ: {original_amount:,} تومان\n'
        f'{discount_info}'
        f'🖥 سرور: {server.name}\n'
        f'━━━━━━━━━━━━━━\n'
        f'لطفاً رسید را بررسی کنید.'
    )
    for aid in settings.admin_ids:
        await message.bot.send_photo(aid, file_id, caption=caption, reply_markup=kb)
    await state.clear(); await ui_message(message, '✅ رسید ارسال شد. بعد از تایید مدیر، سرویس برای شما ساخته می‌شود.'); await send_home(message.bot, message.from_user.id, message.from_user.id in settings.admin_ids)

@router.callback_query(F.data.startswith('order:approve:'))
async def approve_order_cb(callback: CallbackQuery):
    if callback.from_user.id not in settings.admin_ids: return
    oid=int(callback.data.split(':')[-1])

    # Config/service delivery must go ONLY to the buyer.  The admin who presses
    # approve should only receive a short confirmation in the admin chat.
    buyer_chat_id = None
    buyer_is_admin = False
    service_username = None
    service_sub_link = None
    plan_title = None
    plan_volume_gb = None
    plan_duration_days = None

    async with SessionLocal() as session:
        order=await session.get(Order,oid); user=await session.get(User,order.user_id); plan=await session.get(Plan,order.plan_id); server=await session.get(Server,plan.server_id)
        buyer_chat_id = int(user.telegram_id)
        buyer_is_admin = buyer_chat_id in settings.admin_ids
        plan_title = plan.title
        plan_volume_gb = plan.volume_gb
        plan_duration_days = plan.duration_days
        username=order.payment_method.split(':',1)[1].split(':discount:',1)[0] if order.payment_method and (order.payment_method.startswith('card:') or order.payment_method.startswith('crypto:')) else f'user{user.telegram_id}_{order.id}'
        if order.payment_method and order.payment_method.startswith('renew:') and order.service_id:
            service=await session.get(ClientService, order.service_id)
            if server.server_type == 'xui':
                try:
                    await XuiService().reset_client_plan(server, service.xui_email, plan.volume_gb, plan.duration_days)
                except Exception as e:
                    await session.rollback()
                    await ui_callback_message(callback, f'❌ تمدید سرویس روی پنل با خطا مواجه شد:\n{e}')
                    await callback.answer()
                    return
            service.total_bytes=plan.volume_gb*1024**3
            service.used_bytes=0
            service.expires_at=datetime.utcnow()+timedelta(days=plan.duration_days) if plan.duration_days else None
            service.is_active=True
            sub_link=service.sub_link
        else:
            try: service, sub_link=await build_service(session,user,server,plan,username)
            except Exception as e:
                await session.rollback(); await ui_callback_message(callback, f'❌ ساخت سرویس روی پنل با خطا مواجه شد:\n{e}'); await callback.answer(); return
        service_username = service.client_username
        service_sub_link = sub_link
        order.status='paid'; order.service_id=service.id; await session.commit()

    await send_service_card(
        callback.message.bot,
        buyer_chat_id,
        service_username,
        plan_title,
        plan_volume_gb,
        plan_duration_days,
        service_sub_link,
        is_test=False,
    )
    await send_home(callback.message.bot, buyer_chat_id, buyer_is_admin)

    admin_text = (
        '✅ رسید تایید شد و سرویس فقط برای خریدار ارسال شد.\n\n'
        f'👤 خریدار: {buyer_chat_id}\n'
        f'📦 پلن: {plan_title}\n'
        f'🔐 کانفیگ: {service_username}'
    )
    await ui_callback_message(callback, admin_text)
    await send_home(callback.message.bot, callback.from_user.id, True)
    await callback.answer('تایید شد.', show_alert=False)

@router.callback_query(F.data.startswith('order:reject:'))
async def reject_order_cb(callback: CallbackQuery):
    if callback.from_user.id not in settings.admin_ids: return
    oid=int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        order=await session.get(Order,oid); order.status='rejected'; user=await session.get(User,order.user_id); await session.commit()
    await callback.message.bot.send_message(user.telegram_id,'❌ خرید ناموفق بود؛ رسید شما رد شد. لطفاً با پشتیبانی در ارتباط باشید.')
    await ui_callback_message(callback, 'رسید رد شد.'); await send_home(callback.message.bot, callback.from_user.id, True); await callback.answer()

@router.callback_query(F.data == CB_QUERY)
async def query_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(QueryClient.keyword)
    await ui_callback_message(callback, 'لینک، UUID یا Username کانفیگ را ارسال کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('back:main')]])); await callback.answer()

@router.message(QueryClient.keyword)
async def query_client(message: Message, state: FSMContext):
    key=extract_key(message.text); result_text=''
    async with SessionLocal() as session:
        q=select(ClientService).where((ClientService.client_username == key) | (ClientService.xui_email == key) | (ClientService.xui_uuid == key))
        if key: q=q.union_all(select(ClientService).where(ClientService.sub_link.contains(key))) if False else q
        local=(await session.execute(select(ClientService).where((ClientService.client_username == key) | (ClientService.xui_email == key) | (ClientService.xui_uuid == key)))).scalar_one_or_none()
        if not local and key:
            local=(await session.execute(select(ClientService).where(ClientService.sub_link.contains(key)))).scalar_one_or_none()
        if local:
            plan=await session.get(Plan, local.plan_id) if local.plan_id else None
            result_text = pretty_config_result(
                username=local.client_username,
                active=bool(local.is_active),
                plan_title=plan.title if plan else 'نامشخص',
                created_at=local.created_at.date().isoformat() if local.created_at else '-',
                expires_at=local.expires_at.date().isoformat() if local.expires_at else 'نامحدود',
                total=local.total_bytes or 0,
                used=local.used_bytes or 0,
                uuid=local.xui_uuid or None,
            )
        all_servers=(await session.execute(select(Server).where(Server.server_type == 'xui', Server.is_active == True))).scalars().all()
        servers=[s for s in all_servers if (s.meta or {}).get('scope') != 'reseller']
    if not result_text:
        for server in servers:
            try:
                found=await XuiService().find_client_any(server,key)
                if found:
                    c=found.get('client',{}); tr=found.get('traffic') or {}; up=tr.get('up',0) or 0; down=tr.get('down',0) or 0; total=tr.get('total', c.get('totalGB',0)) or 0
                    result_text = pretty_config_result(
                        username=c.get('email') or '-',
                        active=bool(c.get('enable', True)),
                        plan_title='نامشخص',
                        created_at='-',
                        expires_at='-',
                        total=total or 0,
                        used=(up or 0) + (down or 0),
                        uuid=c.get('id') or None,
                    )
                    break
            except Exception: continue
    await state.clear(); await ui_message(message, result_text or 'کانفیگ پیدا نشد. لطفاً لینک، UUID یا Username را دقیق‌تر ارسال کنید.', reply_markup=back_main_inline())
