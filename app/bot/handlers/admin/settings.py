import asyncio
import json
import tempfile
from datetime import datetime
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.fsm.context import FSMContext
from sqlalchemy import select, func, delete
from app.core.config import settings
from app.core.roles import is_owner
from app.database.session import SessionLocal
from app.database.models import User, Setting, PaymentCard, ClientService, Server, ServerCategory, Plan, Order, Ticket, TicketMessage, WalletTransaction, TestAccountUsage, DiscountCode
from app.bot.states.admin_states import TestAccountConfig, PaymentCardConfig, PaymentTextConfig, RulesTextConfig, PaygRate, BroadcastFlow, RestoreBackup, ServiceTypeConfig, AddDiscountCode, EditDiscountCode, WebsiteSettings, WebsiteCommandSetup, ReferralSettingsConfig
from app.bot.keyboards.common import BTN_USERS, BTN_PAYMENT_CHANNEL, BTN_RULES, BTN_PAYG, BTN_BUTTONS, BTN_BROADCAST, BTN_DISCOUNTS, CB_USERS, CB_PAYMENT_CHANNEL, CB_RULES, CB_PAYG, CB_BUTTONS, CB_BROADCAST, CB_DISCOUNTS, CB_BACKUP, CB_RESTORE, back_button, back_admin_inline, main_menu_inline
from app.database.defaults import get_setting_value, set_setting_value, WELCOME_TEXT_DEFAULT, RULES_TEXT_DEFAULT
from app.bot.utils import edit_or_answer, ui_message, ui_callback_message, ui_page
from app.bot.error_reporting import handle_user_facing_error, report_bot_error
from app.services.xui_service import XuiService

router = Router()
def admin(uid): return is_owner(uid)
async def set_value(key, value): await set_setting_value(key, value)

async def save_web_setting(key: str, value: str) -> None:
    # Website login is used by the API container, so store it directly in the shared settings table.
    async with SessionLocal() as session:
        row = await session.get(Setting, key)
        if row:
            row.value = value
        else:
            session.add(Setting(key=key, value=value))
        await session.commit()

async def save_web_settings_bulk(values: dict[str, str]) -> None:
    async with SessionLocal() as session:
        for key, value in values.items():
            row = await session.get(Setting, key)
            if row:
                row.value = value
            else:
                session.add(Setting(key=key, value=value))
        await session.commit()

@router.callback_query(F.data == CB_PAYMENT_CHANNEL)
@router.callback_query(F.data == 'admin:payment_channel')
async def payment_settings(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    async with SessionLocal() as session:
        cards=(await session.execute(select(PaymentCard).order_by(PaymentCard.id.asc()))).scalars().all()
    ch=await get_setting_value('channel_url', '')
    channel_required=await get_setting_value('force_join_enabled', '1')
    payment_text=await get_setting_value('payment_text', 'ثبت نشده')
    info='💳 تنظیمات درگاه و کانال\n━━━━━━━━━━━━━━━━\n\n'
    info += f'📢 کانال اجباری: {ch or "ثبت نشده"}\n'
    info += f'👁 وضعیت عضویت اجباری: {"روشن" if channel_required == "1" else "خاموش"}\n\n'
    info += f'📝 متن پرداخت: {payment_text[:120]}\n\n'
    if cards:
        info += '💳 کارت‌های ثبت‌شده:\n'
        for c in cards:
            status='🟢 فعال' if c.is_active else '🔴 غیرفعال'
            scope = 'نماینده‌ها' if c.server_type == 'reseller' else f'سرور: {c.server_id or c.server_type}'
            info += f'#{c.id} | {status} | {c.card_number} | {c.owner_name} | {scope}\n'
    else:
        info += 'هنوز شماره کارتی ثبت نشده است.'
    rows=[
        [InlineKeyboardButton(text='➕ افزودن شماره کارت سرویس‌ها', callback_data='paycard:add')],
        [InlineKeyboardButton(text='➕ افزودن کارت مخصوص نماینده‌ها', callback_data='paycard:add_reseller')],
        [InlineKeyboardButton(text='📢 تغییر کانال اجباری', callback_data='channel:set'), InlineKeyboardButton(text='👁 روشن/خاموش عضویت', callback_data='channel:toggle_required')],
        [InlineKeyboardButton(text='📝 تغییر متن پرداخت', callback_data='payment_text:set')],
    ]
    for c in cards:
        rows.append([InlineKeyboardButton(text=f'💳 کارت #{c.id}', callback_data=f'paycard:detail:{c.id}')])
    rows.append([back_button('admin:sales_section')])
    await edit_or_answer(callback, info, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)); await callback.answer()

@router.callback_query(F.data == 'paycard:add')
async def paycard_add(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    await state.clear(); await state.update_data(card_scope='server'); await state.set_state(PaymentCardConfig.card_number)
    await edit_or_answer(callback, '💳 شماره کارت را وارد کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:payment_channel')]])); await callback.answer()


@router.callback_query(F.data == 'paycard:add_reseller')
async def paycard_add_reseller(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    await state.clear(); await state.update_data(card_scope='reseller'); await state.set_state(PaymentCardConfig.card_number)
    await edit_or_answer(callback, '💳 شماره کارت مخصوص نماینده‌ها را وارد کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:payment_channel')]])); await callback.answer()

@router.message(PaymentCardConfig.card_number)
async def paycard_number(message: Message, state: FSMContext):
    await state.update_data(card_number=message.text.strip())
    await state.set_state(PaymentCardConfig.owner_name)
    await ui_message(message, '👤 نام صاحب کارت را وارد کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:payment_channel')]]))

@router.message(PaymentCardConfig.owner_name)
async def paycard_owner(message: Message, state: FSMContext):
    await state.update_data(owner_name=message.text.strip())
    data = await state.get_data()
    if data.get('card_scope') == 'reseller':
        async with SessionLocal() as session:
            session.add(PaymentCard(server_id=None, server_type='reseller', card_number=data['card_number'], owner_name=data['owner_name'], is_active=True))
            await session.commit()
        await state.clear()
        await ui_message(message, '✅ کارت مخصوص نماینده‌ها ذخیره شد. از این به بعد هنگام خرید/شارژ حجم نمایندگی همین کارت نمایش داده می‌شود.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:payment_channel')]]))
        return
    async with SessionLocal() as session:
        all_servers=(await session.execute(select(Server).where(Server.is_active == True))).scalars().all()
        servers=[s for s in all_servers if (s.meta or {}).get('scope') != 'reseller']
    if not servers:
        await ui_message(message, 'هیچ سروری ثبت نشده است.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:payment_channel')]])); await state.clear(); return
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=s.name, callback_data=f'paycard:server:{s.id}')] for s in servers] + [[back_button('admin:payment_channel')]])
    await state.set_state(PaymentCardConfig.server_id)
    await ui_message(message, 'این شماره کارت برای کدوم سرور استفاده بشه؟', reply_markup=kb)

@router.callback_query(F.data.startswith('paycard:server:'))
async def paycard_server(callback: CallbackQuery, state: FSMContext):
    data=await state.get_data(); sid=int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        server=await session.get(Server,sid)
        session.add(PaymentCard(server_id=sid, server_type=server.server_type, card_number=data['card_number'], owner_name=data['owner_name'], is_active=True))
        await session.commit()
    await state.clear(); await edit_or_answer(callback, '✅ شماره کارت برای سرور انتخاب‌شده ذخیره شد.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:payment_channel')]])); await callback.answer()


@router.message(F.text.startswith('https://t.me/'))
async def set_channel(message: Message):
    if not admin(message.from_user.id): return
    await set_value('channel_url', message.text.strip().replace(' ', ''))
    await ui_message(message, '✅ کانال ذخیره شد.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:user_interaction')]]))



@router.callback_query(F.data.startswith('paycard:detail:'))
async def paycard_detail(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    cid=int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        c=await session.get(PaymentCard, cid)
    if not c:
        await callback.answer('کارت پیدا نشد.', show_alert=True); return
    status='🟢 فعال' if c.is_active else '🔴 غیرفعال'
    card_usage = 'نماینده‌ها' if c.server_type == 'reseller' else f'سرور {c.server_id or c.server_type}'
    text=(
        '💳 مدیریت شماره کارت\n━━━━━━━━━━━━━━━━\n\n'
        f'🆔 شناسه: {c.id}\n'
        f'💳 شماره کارت: {c.card_number}\n'
        f'👤 نام صاحب کارت: {c.owner_name}\n'
        f'🖥 کاربرد: {card_usage}\n'
        f'👁 وضعیت: {status}'
    )
    kb=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✏️ تغییر شماره کارت', callback_data=f'paycard:edit:number:{cid}')],
        [InlineKeyboardButton(text='✏️ تغییر نام صاحب کارت', callback_data=f'paycard:edit:owner:{cid}')],
        [InlineKeyboardButton(text='👁 فعال/غیرفعال', callback_data=f'paycard:toggle:{cid}')],
        [InlineKeyboardButton(text='🗑 حذف کارت', callback_data=f'paycard:delete:{cid}')],
        [back_button('admin:payment_channel')],
    ])
    await edit_or_answer(callback, text, reply_markup=kb); await callback.answer()

@router.callback_query(F.data.startswith('paycard:edit:'))
async def paycard_edit_start(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    _,_,field,cid=callback.data.split(':')
    await state.clear()
    await state.update_data(edit_card_id=int(cid), edit_card_field=field)
    await state.set_state(PaymentCardConfig.edit_value)
    label='شماره کارت جدید' if field == 'number' else 'نام صاحب کارت جدید'
    await edit_or_answer(callback, f'{label} را وارد کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(f'paycard:detail:{cid}')]]))
    await callback.answer()

@router.message(PaymentCardConfig.edit_value)
async def paycard_edit_save(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    data=await state.get_data(); cid=int(data.get('edit_card_id')); field=data.get('edit_card_field')
    async with SessionLocal() as session:
        c=await session.get(PaymentCard, cid)
        if c:
            if field == 'number': c.card_number=message.text.strip()
            else: c.owner_name=message.text.strip()
            await session.commit()
    await state.clear()
    await ui_message(message, '✅ تغییرات کارت ذخیره شد.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(f'paycard:detail:{cid}')]]))

@router.callback_query(F.data.startswith('paycard:toggle:'))
async def paycard_toggle(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    cid=int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        c=await session.get(PaymentCard, cid)
        if c:
            c.is_active=not c.is_active
            await session.commit()
    await paycard_detail(callback)

@router.callback_query(F.data.startswith('paycard:delete:'))
async def paycard_delete_ask(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    cid=int(callback.data.split(':')[-1])
    kb=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ بله، کارت حذف شود', callback_data=f'paycard:delete_confirm:{cid}')],
        [back_button(f'paycard:detail:{cid}')],
    ])
    await edit_or_answer(callback, '⚠️ مطمئنی می‌خواهی این کارت حذف شود؟', reply_markup=kb); await callback.answer()

@router.callback_query(F.data.startswith('paycard:delete_confirm:'))
async def paycard_delete(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    cid=int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        c=await session.get(PaymentCard, cid)
        if c:
            await session.delete(c)
            await session.commit()
    await edit_or_answer(callback, '✅ کارت حذف شد.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:payment_channel')]]))
    await callback.answer()

@router.callback_query(F.data == 'channel:toggle_required')
async def channel_toggle_required(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    cur=await get_setting_value('force_join_enabled', '1')
    await set_value('force_join_enabled', '0' if cur == '1' else '1')
    await payment_settings(callback)

@router.callback_query(F.data == 'payment_text:set')
async def payment_text_start(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    await state.clear(); await state.set_state(PaymentTextConfig.text)
    await edit_or_answer(callback, '📝 متن پرداخت جدید را وارد کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:payment_channel')]]))
    await callback.answer()

@router.message(PaymentTextConfig.text)
async def payment_text_save(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    await set_value('payment_text', message.text.strip())
    await state.clear()
    await ui_message(message, '✅ متن پرداخت ذخیره شد.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:payment_channel')]]))

@router.message(F.text == BTN_USERS)
@router.callback_query(F.data == CB_USERS)
async def user_info_hint(event):
    if not admin(event.from_user.id): return
    target = event.message if isinstance(event, CallbackQuery) else event
    await ui_page(target, 'برای جستجوی کاربر این دستور را ارسال کنید:\nuser numeric_id_or_username', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:user_interaction')]]))
    if isinstance(event, CallbackQuery): await event.answer()

@router.message(F.text.startswith('user '))
async def user_info(message: Message):
    if not admin(message.from_user.id): return
    key = message.text.replace('user ', '').strip().lstrip('@')
    async with SessionLocal() as session:
        q = select(User).where(User.username == key) if not key.isdigit() else select(User).where(User.telegram_id == int(key))
        user = (await session.execute(q)).scalar_one_or_none()
        if not user:
            await ui_message(message, 'کاربر پیدا نشد.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:user_interaction')]])); return
        active = (await session.execute(select(func.count(ClientService.id)).where(ClientService.user_id == user.id, ClientService.is_active == True))).scalar()
    joined = user.joined_at.date().isoformat() if user.joined_at else '-'
    await ui_message(message, f'👤 اطلاعات کاربر\nآیدی: {user.telegram_id}\nیوزرنیم: @{user.username}\nنام: {user.full_name}\nکیف پول: {user.wallet_balance:,} تومان\nسرویس فعال: {active}\nتاریخ عضویت: {joined}', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:user_interaction')]]))



def payg_kb(rate: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f'{rate:,} تومان', callback_data='noop'), InlineKeyboardButton(text='تعرفه فعلی هر 1 گیگ', callback_data='noop')],
        [InlineKeyboardButton(text='✏️ تغییر تعرفه', callback_data='payg:change')],
        [back_button('admin:sales_section')]
    ])

@router.message(F.text == BTN_PAYG)
@router.callback_query(F.data == CB_PAYG)
async def payg_hint(event, state: FSMContext = None):
    if not admin(event.from_user.id): return
    rate = int(await get_setting_value('payg_price_per_gb', '0'))
    text = '⚖️ سیستم Pay As You Go\n\nتعرفه فعلی هر 1 گیگ را از بخش زیر مدیریت کنید:'
    if isinstance(event, CallbackQuery):
        await edit_or_answer(event, text, reply_markup=payg_kb(rate)); await event.answer()
    else:
        await event.answer(text, reply_markup=payg_kb(rate))

@router.callback_query(F.data == 'payg:change')
async def payg_change(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    await state.set_state(PaygRate.amount)
    await edit_or_answer(callback, 'چه مقداری می‌خواهید بابت هر 1 گیگ بگذارید؟\n\nفقط رقم را به تومان وارد کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:sales_section')]]))
    await callback.answer()

@router.message(PaygRate.amount)
async def set_payg_rate_state(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    amount = int(message.text.replace(',', '').replace('تومان', '').strip())
    await set_value('payg_price_per_gb', str(amount))
    await state.clear()
    await ui_message(message, '✅ تعرفه Pay As You Go ذخیره شد.', reply_markup=payg_kb(amount))

@router.message(F.text.startswith('payg_rate '))
async def set_payg_rate(message: Message):
    if not admin(message.from_user.id): return
    amount = message.text.replace('payg_rate ', '').replace(',', '').strip()
    await set_value('payg_price_per_gb', str(int(amount)))
    await ui_message(message, '✅ تعرفه Pay As You Go ذخیره شد.', reply_markup=payg_kb(int(amount)))

def buttons_kb(bot_enabled='1', test_enabled='1', test_visible='1'):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f'🤖 ربات: {"روشن" if bot_enabled == "1" else "خاموش"}', callback_data='buttons:toggle_bot'),
            InlineKeyboardButton(text=f'🎁 اکانت تست: {"روشن" if test_enabled == "1" else "خاموش"}', callback_data='buttons:toggle_test'),
        ],
        [
            InlineKeyboardButton(text=f'👁 دکمه تست: {"نمایش" if test_visible == "1" else "حذف"}', callback_data='buttons:toggle_test_visible'),
            InlineKeyboardButton(text='⚙️ تنظیمات تست', callback_data='buttons:test_config'),
        ],
        [InlineKeyboardButton(text='🌐 وب سایت', callback_data='admin:website_settings')],
        [InlineKeyboardButton(text='🔙 بازگشت', callback_data='admin:bot_settings')],
    ])

@router.message(F.text == BTN_BUTTONS)
@router.callback_query(F.data == CB_BUTTONS)
async def buttons_menu(event):
    if not admin(event.from_user.id): return
    bot_enabled = await get_setting_value('bot_enabled', '1')
    test_enabled = await get_setting_value('test_account_enabled', '1')
    test_visible = await get_setting_value('test_account_button_visible', '1')
    text = '🔘 مدیریت دکمه‌ها و اکانت تست\n\nاز این بخش می‌توانید اکانت تست را روشن/خاموش کنید و مشخص کنید از کدام سرور و Inbound ساخته شود.'
    if isinstance(event, CallbackQuery):
        await edit_or_answer(event, text, reply_markup=buttons_kb(bot_enabled, test_enabled, test_visible)); await event.answer()
    else:
        await event.answer(text, reply_markup=buttons_kb(bot_enabled, test_enabled, test_visible))

@router.callback_query(F.data == 'buttons:toggle_bot')
async def toggle_bot(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    cur = await get_setting_value('bot_enabled', '1')
    await set_value('bot_enabled', '0' if cur == '1' else '1')
    await buttons_menu(callback)

@router.callback_query(F.data == 'buttons:toggle_test')
async def toggle_test(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    cur = await get_setting_value('test_account_enabled', '1')
    await set_value('test_account_enabled', '0' if cur == '1' else '1')
    await buttons_menu(callback)

@router.callback_query(F.data == 'buttons:toggle_test_visible')
async def toggle_test_visible(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    cur = await get_setting_value('test_account_button_visible', '1')
    await set_value('test_account_button_visible', '0' if cur == '1' else '1')
    await buttons_menu(callback)


SERVICE_TYPE_ITEMS = {
    'v2ray': {
        'title': 'V2Ray / 3x-ui',
        'enabled_key': 'service_type_v2ray_enabled',
        'label_key': 'service_type_v2ray_label',
        'default_label': 'V2Ray',
    },
    'openvpn': {
        'title': 'OpenVPN - L2TP',
        'enabled_key': 'service_type_openvpn_enabled',
        'label_key': 'service_type_openvpn_label',
        'default_label': 'OpenVPN - L2TP',
    },
}

async def service_types_text() -> str:
    lines = [
        '🧩 تنظیمات نوع سرویس‌ها',
        '━━━━━━━━━━━━━━━━',
        '',
        'از این بخش می‌توانید گزینه‌های نوع سرویس در خرید را روشن/خاموش کنید یا متن دکمه‌ها را تغییر دهید.',
        '',
    ]
    for key, item in SERVICE_TYPE_ITEMS.items():
        enabled = await get_setting_value(item['enabled_key'], '1')
        label = await get_setting_value(item['label_key'], item['default_label'])
        lines.append(f'• {"🟢 فعال" if enabled == "1" else "🔴 غیرفعال"} | {item["title"]}')
        lines.append(f'  متن دکمه: {label}')
    return '\n'.join(lines)

def service_types_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🔵 V2Ray / 3x-ui', callback_data='stype:detail:v2ray')],
        [InlineKeyboardButton(text='🟣 OpenVPN - L2TP', callback_data='stype:detail:openvpn')],
        [back_button(CB_BUTTONS)],
    ])

async def service_type_detail_text(kind: str) -> str:
    item = SERVICE_TYPE_ITEMS.get(kind)
    if not item:
        return '❌ نوع سرویس پیدا نشد.'
    enabled = await get_setting_value(item['enabled_key'], '1')
    label = await get_setting_value(item['label_key'], item['default_label'])
    return (
        f'🧩 مدیریت نوع سرویس\n'
        f'━━━━━━━━━━━━━━━━\n\n'
        f'📌 نوع اصلی: {item["title"]}\n'
        f'🏷 متن دکمه خرید: {label}\n'
        f'👁 وضعیت نمایش در خرید: {"🟢 فعال" if enabled == "1" else "🔴 غیرفعال"}\n\n'
        f'با غیرفعال کردن این گزینه، کاربر دیگر هنگام خرید این نوع سرویس را نمی‌بیند.'
    )

def service_type_detail_kb(kind: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='👁 فعال / غیرفعال', callback_data=f'stype:toggle:{kind}')],
        [InlineKeyboardButton(text='✏️ تغییر متن دکمه', callback_data=f'stype:rename:{kind}')],
        [back_button('admin:sales_section')],
    ])

@router.callback_query(F.data == 'buttons:service_types')
async def service_types_menu(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    await state.clear()
    await edit_or_answer(callback, await service_types_text(), reply_markup=service_types_kb())
    await callback.answer()

@router.callback_query(F.data.startswith('stype:detail:'))
async def service_type_detail(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    kind = callback.data.split(':')[-1]
    await edit_or_answer(callback, await service_type_detail_text(kind), reply_markup=service_type_detail_kb(kind))
    await callback.answer()

@router.callback_query(F.data.startswith('stype:toggle:'))
async def service_type_toggle(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    kind = callback.data.split(':')[-1]
    item = SERVICE_TYPE_ITEMS.get(kind)
    if not item:
        await callback.answer('نوع سرویس پیدا نشد.', show_alert=True); return
    cur = await get_setting_value(item['enabled_key'], '1')
    await set_value(item['enabled_key'], '0' if cur == '1' else '1')
    await edit_or_answer(callback, await service_type_detail_text(kind), reply_markup=service_type_detail_kb(kind))
    await callback.answer('وضعیت تغییر کرد.')

@router.callback_query(F.data.startswith('stype:rename:'))
async def service_type_rename_start(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    kind = callback.data.split(':')[-1]
    item = SERVICE_TYPE_ITEMS.get(kind)
    if not item:
        await callback.answer('نوع سرویس پیدا نشد.', show_alert=True); return
    await state.clear()
    await state.update_data(service_type_kind=kind)
    await state.set_state(ServiceTypeConfig.value)
    current = await get_setting_value(item['label_key'], item['default_label'])
    await edit_or_answer(
        callback,
        f'✏️ متن جدید دکمه خرید را وارد کنید:\n\nمتن فعلی: {current}\n\nمثال: مولتی لوکیشن V2Ray',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(f'stype:detail:{kind}')]])
    )
    await callback.answer()

@router.message(ServiceTypeConfig.value)
async def service_type_rename_save(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    data = await state.get_data()
    kind = data.get('service_type_kind')
    item = SERVICE_TYPE_ITEMS.get(kind)
    if not item:
        await state.clear()
        await ui_message(message, '❌ نوع سرویس پیدا نشد.', reply_markup=buttons_kb())
        return
    value = message.text.strip()
    if not value:
        await ui_message(message, '❌ متن نمی‌تواند خالی باشد.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(f'stype:detail:{kind}')]]))
        return
    await set_value(item['label_key'], value[:80])
    await state.clear()
    await ui_message(message, '✅ متن نوع سرویس ذخیره شد.\n\n' + await service_type_detail_text(kind), reply_markup=service_type_detail_kb(kind))


async def test_config_text() -> str:
    sid = await get_setting_value('test_account_server_id', '')
    inbounds = await get_setting_value('test_account_inbound_ids', '')
    volume = await get_setting_value('test_account_volume_gb', '1')
    duration = await get_setting_value('test_account_duration_days', '1')
    server_name = 'ثبت نشده'
    if sid:
        async with SessionLocal() as session:
            server = await session.get(Server, int(sid)) if str(sid).isdigit() else None
            if server:
                server_name = f'{server.name} (ID: {server.id})'
    return (
        '🎁 تنظیمات اکانت تست\n'
        '━━━━━━━━━━━━━━━━\n\n'
        f'🖥 سرور: {server_name}\n'
        f'🔢 Inbound ID ها: {inbounds or "ثبت نشده"}\n'
        f'💾 حجم: {volume} گیگ\n'
        f'📅 مدت: {duration} روز'
    )

def test_config_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🖥 تغییر سرور', callback_data='testcfg:server')],
        [InlineKeyboardButton(text='💾 تغییر حجم', callback_data='testcfg:volume')],
        [InlineKeyboardButton(text='📅 تغییر مدت', callback_data='testcfg:duration')],
        [InlineKeyboardButton(text='♻️ ریست دریافت‌کنندگان تست', callback_data='testcfg:reset_all')],
        [back_button(CB_BUTTONS)],
    ])


@router.callback_query(F.data == 'testcfg:reset_all')
async def test_config_reset_all_confirm(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    async with SessionLocal() as session:
        count = (await session.execute(select(func.count(TestAccountUsage.id)))).scalar_one()
    text = (
        '⚠️ <b>ریست اکانت‌های تست</b>\n'
        '━━━━━━━━━━━━━━━━\n\n'
        f'👥 تعداد کاربرانی که قبلاً اکانت تست گرفته‌اند: <b>{count}</b>\n\n'
        'با تایید این گزینه، همه این کاربران می‌توانند دوباره اکانت تست دریافت کنند.\n\n'
        'آیا مطمئن هستید؟'
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ بله، ریست کن', callback_data='testcfg:reset_all_confirm')],
        [InlineKeyboardButton(text='❌ انصراف', callback_data='buttons:test_config')],
    ])
    await edit_or_answer(callback, text, reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data == 'testcfg:reset_all_confirm')
async def test_config_reset_all_do(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    async with SessionLocal() as session:
        count = (await session.execute(select(func.count(TestAccountUsage.id)))).scalar_one()
        await session.execute(delete(TestAccountUsage))
        await session.commit()
    text = (
        '✅ <b>ریست انجام شد</b>\n'
        '━━━━━━━━━━━━━━━━\n\n'
        f'♻️ تعداد <b>{count}</b> رکورد دریافت اکانت تست ریست شد.\n'
        'از این به بعد همه کاربران می‌توانند دوباره اکانت تست بگیرند.'
    )
    await edit_or_answer(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('buttons:test_config')]]))
    await callback.answer('ریست شد.')

@router.callback_query(F.data == 'buttons:test_config')
async def test_config_start(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    await state.clear()
    await edit_or_answer(callback, await test_config_text(), reply_markup=test_config_kb())
    await callback.answer()

@router.callback_query(F.data == 'testcfg:server')
async def test_config_server_start(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    async with SessionLocal() as session:
        all_servers = (await session.execute(select(Server).where(Server.server_type == 'xui', Server.is_active == True))).scalars().all()
        servers = [s for s in all_servers if (s.meta or {}).get('scope') != 'reseller']
    if not servers:
        await callback.answer('هیچ سرور X-UI فعالی ثبت نشده است.', show_alert=True); return
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f'{s.name} | ID {s.id}', callback_data=f'testcfg:server_pick:{s.id}')] for s in servers] + [[back_button('buttons:test_config')]])
    await edit_or_answer(callback, '🖥 سرور اکانت تست را انتخاب کنید:', reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data.startswith('testcfg:server_pick:'))
async def test_config_server_pick(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    sid = callback.data.split(':')[-1]
    inbound_ids = []
    async with SessionLocal() as session:
        server = await session.get(Server, int(sid)) if str(sid).isdigit() else None
        if server and server.server_type == 'xui':
            try:
                ok, rows = await XuiService().test_server(server)
                if ok:
                    for row in rows or []:
                        try:
                            iid = int(row.get('id')) if isinstance(row, dict) else int(row)
                        except Exception:
                            continue
                        if iid > 0 and iid not in inbound_ids:
                            inbound_ids.append(iid)
            except Exception:
                inbound_ids = []
            if not inbound_ids:
                for item in ((server.meta or {}).get('inbound_ids') or []):
                    try:
                        iid = int(item.get('id') if isinstance(item, dict) else item)
                    except Exception:
                        continue
                    if iid > 0 and iid not in inbound_ids:
                        inbound_ids.append(iid)
    await set_value('test_account_server_id', sid)
    await set_value('test_account_inbound_ids', ','.join(str(i) for i in inbound_ids))
    await edit_or_answer(callback, await test_config_text(), reply_markup=test_config_kb())
    await callback.answer('سرور اکانت تست ذخیره شد و همه Inboundها خودکار اضافه شدند.')

@router.callback_query(F.data.in_({'testcfg:inbounds','testcfg:volume','testcfg:duration'}))
async def test_config_field_start(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    field = callback.data.split(':')[-1]
    await state.clear()
    await state.update_data(testcfg_field=field)
    if field == 'inbounds':
        await state.set_state(TestAccountConfig.inbound_ids)
        prompt = '🔢 Inbound ID های اکانت تست را با کاما وارد کنید. مثال:\n1,2,3'
    elif field == 'volume':
        await state.set_state(TestAccountConfig.volume)
        prompt = '💾 حجم اکانت تست را به گیگ وارد کنید:'
    else:
        await state.set_state(TestAccountConfig.duration)
        prompt = '📅 مدت اکانت تست را به روز وارد کنید:'
    await edit_or_answer(callback, prompt, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('buttons:test_config')]]))
    await callback.answer()

@router.message(TestAccountConfig.inbound_ids)
async def test_config_inbounds(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    await set_value('test_account_inbound_ids', message.text.strip())
    await state.clear()
    await ui_message(message, '✅ Inbound اکانت تست ذخیره شد.', reply_markup=test_config_kb())

@router.message(TestAccountConfig.volume)
async def test_config_volume(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    await set_value('test_account_volume_gb', message.text.strip())
    await state.clear()
    await ui_message(message, '✅ حجم اکانت تست ذخیره شد.', reply_markup=test_config_kb())

@router.message(TestAccountConfig.duration)
async def test_config_duration(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    await set_value('test_account_duration_days', message.text.strip())
    await state.clear()
    await ui_message(message, '✅ مدت اکانت تست ذخیره شد.', reply_markup=test_config_kb())

# Broadcast flow: stores all /start users from the users table and sends a preview before delivery.
@router.message(F.text == BTN_BROADCAST)
@router.callback_query(F.data == CB_BROADCAST)
async def broadcast_start(event, state: FSMContext):
    if not admin(event.from_user.id): return
    await state.set_state(BroadcastFlow.message)
    text='📢 متن پیام همگانی را وارد کنید:'
    if isinstance(event, CallbackQuery):
        await edit_or_answer(event, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:user_interaction')]])); await event.answer()
    else:
        await event.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:user_interaction')]]))

@router.message(BroadcastFlow.message)
async def broadcast_preview(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    await state.update_data(text=message.text)
    kb=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ ارسال کن', callback_data='broadcast:send'), InlineKeyboardButton(text='✏️ اصلاح کن', callback_data='broadcast:edit')],
        [back_button('admin:user_interaction')]
    ])
    await ui_message(message, '📢 پیش‌نمایش پیام همگانی:\n\n' + message.text + '\n\nارسال کنم یا اصلاح می‌کنید؟', reply_markup=kb)

@router.callback_query(F.data == 'broadcast:edit')
async def broadcast_edit(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    await state.set_state(BroadcastFlow.message)
    await edit_or_answer(callback, '✏️ متن اصلاح‌شده را ارسال کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:user_interaction')]]))
    await callback.answer()

async def finish_home_later(bot, chat_id: int, delay: int = 3):
    await asyncio.sleep(delay)
    await bot.send_message(chat_id, await get_setting_value('welcome_text', WELCOME_TEXT_DEFAULT), reply_markup=main_menu_inline(True))

async def run_broadcast(bot, admin_chat_id: int, text: str):
    sent = failed = last_no = 0
    restart_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='🔄 شروع مجدد', callback_data='restart:start')]])
    async with SessionLocal() as session:
        users=(await session.execute(select(User).where(User.is_blocked == False).order_by(User.id.asc()))).scalars().all()
    for idx, user in enumerate(users, start=1):
        last_no = idx
        try:
            await bot.send_message(user.telegram_id, text, reply_markup=restart_kb)
            sent += 1
            await asyncio.sleep(0.04)
        except Exception:
            failed += 1
    await bot.send_message(admin_chat_id, f'✅ ارسال پیام همگانی تمام شد.\n\n👥 کل کاربران: {len(users)}\n✅ ارسال موفق: {sent}\n❌ ناموفق: {failed}\n🔢 آخرین شماره بررسی‌شده: {last_no}')
    await asyncio.sleep(5)
    await bot.send_message(admin_chat_id, await get_setting_value('welcome_text', WELCOME_TEXT_DEFAULT), reply_markup=main_menu_inline(True))

@router.callback_query(F.data == 'broadcast:send')
async def broadcast_send(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    data=await state.get_data(); text=data.get('text')
    await state.clear()
    if not text:
        await callback.answer('متنی ثبت نشده است.', show_alert=True); return
    await edit_or_answer(callback, '⏳ در حال ارسال هستم؛ این کار ممکن است زمان‌بر باشد...')
    asyncio.create_task(finish_home_later(callback.message.bot, callback.from_user.id, 3))
    asyncio.create_task(run_broadcast(callback.message.bot, callback.from_user.id, text))
    await callback.answer('ارسال شروع شد')

import json, tempfile
from aiogram.types import FSInputFile
from app.database.models import ServerCategory, Server, Plan, PaymentCard, Order, WalletTransaction, ClientService, Ticket, TicketMessage
from app.bot.states.admin_states import WelcomeTextConfig, ChannelConfig
from app.bot.keyboards.common import CB_BACKUP

@router.callback_query(F.data == 'rules:edit_welcome')
async def edit_welcome_start(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    await state.set_state(WelcomeTextConfig.text)
    await ui_callback_message(callback, 'متن جدید پیام صفحه اول را ارسال کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:user_interaction')]]))
    await callback.answer()

@router.message(WelcomeTextConfig.text)
async def save_welcome_text(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    await set_value('welcome_text', message.text)
    await state.clear()
    await ui_message(message, '✅ متن صفحه اول ذخیره شد.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:user_interaction')]]))

@router.callback_query(F.data == 'channel:set')
async def channel_set_start(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    await state.set_state(ChannelConfig.url)
    await ui_callback_message(callback, 'لینک کانال اجباری را ارسال کنید. مثال:\nhttps://t.me/yourchannel', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:user_interaction')]]))
    await callback.answer()

@router.message(ChannelConfig.url)
async def channel_save_state(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    await set_value('channel_url', message.text.strip().replace(' ', ''))
    await state.clear()
    await ui_message(message, '✅ کانال اجباری ذخیره شد.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:user_interaction')]]))


@router.callback_query(F.data == 'rules:edit_rules')
async def edit_rules_start(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    await state.set_state(RulesTextConfig.text)
    await ui_callback_message(callback, 'متن جدید قوانین و تاییدیه اولیه را ارسال کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:user_interaction')]]))
    await callback.answer()

@router.message(RulesTextConfig.text)
async def save_rules_text(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    await set_value('rules_text', message.text)
    await state.clear()
    await ui_message(message, '✅ متن قوانین و تاییدیه اولیه ذخیره شد.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:user_interaction')]]))

@router.callback_query(F.data == CB_RULES)
async def rules_menu_new(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    current_rules = await get_setting_value('rules_text', RULES_TEXT_DEFAULT)
    kb=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✏️ تغییر متن صفحه اول', callback_data='rules:edit_welcome')],
        [InlineKeyboardButton(text='⚠️ تغییر متن قوانین اولیه', callback_data='rules:edit_rules')],
        [back_button('admin:user_interaction')]
    ])
    await edit_or_answer(callback, '📜 مدیریت متن خوشامدگویی و قوانین:\n\nمتن قوانین فعلی:\n' + current_rules[:800], reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data == CB_BACKUP)
async def backup_send(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    async with SessionLocal() as session:
        async def rows(model):
            result=(await session.execute(select(model))).scalars().all()
            out=[]
            for obj in result:
                item={c.name: getattr(obj, c.name) for c in obj.__table__.columns}
                for k,v in list(item.items()):
                    if hasattr(v, 'isoformat'): item[k]=v.isoformat()
                out.append(item)
            return out
        data={
            'users': await rows(User), 'servers': await rows(Server), 'categories': await rows(ServerCategory), 'plans': await rows(Plan),
            'payment_cards': await rows(PaymentCard), 'orders': await rows(Order), 'services': await rows(ClientService),
            'tickets': await rows(Ticket), 'ticket_messages': await rows(TicketMessage), 'wallet_transactions': await rows(WalletTransaction), 'settings': await rows(Setting)
        }
    tmp=tempfile.NamedTemporaryFile(delete=False, suffix='.json', mode='w', encoding='utf-8')
    json.dump(data, tmp, ensure_ascii=False, indent=2); tmp.close()
    await callback.message.answer_document(FSInputFile(tmp.name, filename='dbot_backup.json'), caption='📦 بک‌آپ کامل دیتابیس ربات')
    await ui_callback_message(callback, await get_setting_value('welcome_text', WELCOME_TEXT_DEFAULT), reply_markup=main_menu_inline(True))
    await callback.answer()


@router.callback_query(F.data == CB_RESTORE)
async def restore_backup_start(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id):
        return
    await state.clear()
    await state.set_state(RestoreBackup.file)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:user_interaction')]])
    await edit_or_answer(callback, '♻️ فایل بک‌آپ JSON را ارسال کنید.\n\n⚠️ با ری‌استور، اطلاعات فعلی دیتابیس با اطلاعات فایل جایگزین می‌شود.', reply_markup=kb)
    await callback.answer()

def _parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None

async def _restore_rows(session, model, rows):
    await session.execute(delete(model))
    for item in rows or []:
        data = dict(item)
        for col in model.__table__.columns:
            if col.name in data and str(col.type).upper().startswith('DATETIME'):
                data[col.name] = _parse_dt(data[col.name])
        session.add(model(**{k: v for k, v in data.items() if k in model.__table__.columns.keys()}))

@router.message(RestoreBackup.file, F.document)
async def restore_backup_file(message: Message, state: FSMContext):
    if not admin(message.from_user.id):
        return
    doc = message.document
    if not doc.file_name.lower().endswith('.json'):
        await ui_message(message, '❌ لطفاً فایل بک‌آپ با فرمت JSON ارسال کنید.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:user_interaction')]]))
        return
    file = await message.bot.get_file(doc.file_id)
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    tmp.close()
    await message.bot.download_file(file.file_path, tmp.name)
    try:
        with open(tmp.name, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        async with SessionLocal() as session:
            # Restore dependent tables in a safe order.
            for model, key in [
                (TicketMessage, 'ticket_messages'), (Ticket, 'tickets'), (WalletTransaction, 'wallet_transactions'), (Order, 'orders'),
                (ClientService, 'services'), (Plan, 'plans'), (PaymentCard, 'payment_cards'),
                (ServerCategory, 'categories'), (Server, 'servers'), (Setting, 'settings'), (User, 'users')
            ]:
                await session.execute(delete(model))
            await session.commit()
            # Insert parent tables first and flush/commit after each table.
            # This prevents PostgreSQL foreign-key errors when restoring dependent rows
            # such as client_services.user_id -> users.id.
            for model, key in [
                (User, 'users'),
                (Setting, 'settings'),
                (Server, 'servers'),
                (ServerCategory, 'categories'),
                (PaymentCard, 'payment_cards'),
                (Plan, 'plans'),
                (ClientService, 'services'),
                (Order, 'orders'),
                (WalletTransaction, 'wallet_transactions'),
                (Ticket, 'tickets'),
                (TicketMessage, 'ticket_messages')
            ]:
                for item in data.get(key, []):
                    clean = {}
                    colnames = set(model.__table__.columns.keys())
                    for k, v in dict(item).items():
                        if k not in colnames:
                            continue
                        col = model.__table__.columns[k]
                        if 'DateTime' in type(col.type).__name__:
                            v = _parse_dt(v)
                        clean[k] = v
                    session.add(model(**clean))
                await session.flush()
                await session.commit()
        await state.clear()
        await ui_message(message, '✅ بک‌آپ با موفقیت ری‌استور شد.', reply_markup=main_menu_inline(True))
    except Exception as e:
        await state.clear()
        await handle_user_facing_error(message, e, context='Admin restore backup failed', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:bot_settings')]]))

# ---- Discount code management ----
from datetime import datetime
from sqlalchemy.exc import IntegrityError

def discounts_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='➕ افزودن کد درصدی', callback_data='discount:add:percent')],
        [InlineKeyboardButton(text='➕ افزودن کد مبلغی', callback_data='discount:add:fixed')],
        [InlineKeyboardButton(text='📋 لیست کدهای تخفیف', callback_data='discount:list')],
        [back_button('admin:sales_section')],
    ])

@router.message(F.text == BTN_DISCOUNTS)
@router.callback_query(F.data == CB_DISCOUNTS)
async def discounts_menu(event, state: FSMContext = None):
    if not admin(event.from_user.id): return
    text = '🏷 مدیریت کد تخفیف\n\nکد تخفیف می‌تواند به دو حالت ساخته شود:\n\n1️⃣ درصدی: درصدی از مبلغ کم می‌شود.\n2️⃣ مبلغی: مقدار مشخصی از مبلغ کم می‌شود.\n\nاین کدها برای خرید عمومی و خرید بسته نمایندگی قابل استفاده هستند.'
    if isinstance(event, CallbackQuery):
        await edit_or_answer(event, text, reply_markup=discounts_kb()); await event.answer()
    else:
        await event.answer(text, reply_markup=discounts_kb())

@router.callback_query(F.data.startswith('discount:add:'))
async def discount_add_start(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    dtype = callback.data.split(':')[-1]
    await state.clear(); await state.update_data(discount_type=dtype); await state.set_state(AddDiscountCode.code)
    await edit_or_answer(callback, 'کد تخفیف را وارد کنید. مثال: OFF20', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:discounts')]]))
    await callback.answer()

@router.message(AddDiscountCode.code)
async def discount_code_save_code(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    code = (message.text or '').strip().upper().replace(' ', '')
    if not code:
        await ui_message(message, 'کد معتبر وارد کنید.'); return
    await state.update_data(code=code); await state.set_state(AddDiscountCode.value)
    data = await state.get_data()
    if data.get('discount_type') == 'percent':
        await ui_message(message, 'درصد تخفیف را وارد کنید. مثال: 20')
    else:
        await ui_message(message, 'مبلغ تخفیف را به تومان وارد کنید. مثال: 50000')

@router.message(AddDiscountCode.value)
async def discount_code_save_value(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    data = await state.get_data()
    try:
        value = int((message.text or '').replace(',', '').strip())
    except ValueError:
        await ui_message(message, 'فقط عدد وارد کنید.'); return
    if data.get('discount_type') == 'percent' and not (1 <= value <= 100):
        await ui_message(message, 'درصد باید بین 1 تا 100 باشد.'); return
    if value <= 0:
        await ui_message(message, 'مقدار باید بزرگتر از صفر باشد.'); return
    await state.update_data(value=value); await state.set_state(AddDiscountCode.max_uses)
    await ui_message(message, 'حداکثر تعداد استفاده کلی را وارد کنید. برای نامحدود عدد 0 را بزنید.')

@router.message(AddDiscountCode.max_uses)
async def discount_code_save_max_uses(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    data = await state.get_data()
    try:
        max_uses = int((message.text or '').replace(',', '').strip())
    except ValueError:
        await ui_message(message, 'فقط عدد وارد کنید.'); return
    await state.update_data(max_uses=max_uses)
    await state.set_state(AddDiscountCode.per_user_limit)
    await ui_message(message, 'هر کاربر چند بار بتواند از این کد استفاده کند؟\nبرای پیش‌فرض عدد 1، برای نامحدود عدد 0 را بزنید.')

@router.message(AddDiscountCode.per_user_limit)
async def discount_code_finish(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    data = await state.get_data()
    try:
        per_user_limit = int((message.text or '').replace(',', '').strip())
    except ValueError:
        await ui_message(message, 'فقط عدد وارد کنید.'); return
    async with SessionLocal() as session:
        dc = DiscountCode(code=data['code'], discount_type=data['discount_type'], value=int(data['value']), max_uses=int(data.get('max_uses', 0)), per_user_limit=per_user_limit, used_count=0, is_active=True)
        session.add(dc)
        try:
            await session.commit()
            msg = '✅ کد تخفیف ذخیره شد.'
        except IntegrityError:
            await session.rollback()
            msg = '❌ این کد قبلاً ثبت شده است.'
    await state.clear()
    await ui_message(message, msg, reply_markup=discounts_kb())

@router.callback_query(F.data == 'discount:list')
async def discount_list(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    async with SessionLocal() as session:
        items = (await session.execute(select(DiscountCode).order_by(DiscountCode.id.desc()).limit(30))).scalars().all()
    if not items:
        await edit_or_answer(callback, 'هنوز کد تخفیفی ثبت نشده است.', reply_markup=discounts_kb()); await callback.answer(); return
    lines = ['📋 لیست کدهای تخفیف\n']
    rows = []
    for d in items:
        kind = 'درصدی' if d.discount_type == 'percent' else 'مبلغی'
        val = f'{d.value}٪' if d.discount_type == 'percent' else f'{d.value:,} تومان'
        limit = 'نامحدود' if d.max_uses == 0 else str(d.max_uses)
        per_user = 'نامحدود' if getattr(d, 'per_user_limit', 1) == 0 else str(getattr(d, 'per_user_limit', 1))
        status = '🟢 فعال' if d.is_active else '🔴 غیرفعال'
        lines.append(f'🎟 {d.code}  #{d.id}\n├ نوع: {kind} | مقدار: {val}\n├ مصرف کلی: {d.used_count}/{limit}\n├ محدودیت هر کاربر: {per_user} بار\n╰ وضعیت: {status}\n')
        rows.append([InlineKeyboardButton(text=f'⚙️ مدیریت {d.code}', callback_data=f'discount:detail:{d.id}')])
    rows.append([back_button('admin:discounts')])
    await edit_or_answer(callback, '\n'.join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)); await callback.answer()

@router.callback_query(F.data.startswith('discount:toggle:'))
async def discount_toggle(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    did = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        d = await session.get(DiscountCode, did)
        if d:
            d.is_active = not d.is_active
            await session.commit()
    await discount_list(callback)


@router.callback_query(F.data.startswith('discount:detail:'))
async def discount_detail(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    did = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        d = await session.get(DiscountCode, did)
    if not d:
        await callback.answer('کد پیدا نشد.', show_alert=True); return
    kind = 'درصدی' if d.discount_type == 'percent' else 'مبلغی'
    val = f'{d.value}٪' if d.discount_type == 'percent' else f'{d.value:,} تومان'
    limit = 'نامحدود' if d.max_uses == 0 else f'{d.max_uses} بار'
    per_user = 'نامحدود' if getattr(d, 'per_user_limit', 1) == 0 else f'{getattr(d, "per_user_limit", 1)} بار'
    text = (
        f'🏷 مدیریت کد تخفیف\n━━━━━━━━━━━━━━━━\n\n'
        f'🎟 کد: {d.code}\n'
        f'📌 نوع: {kind}\n'
        f'💰 مقدار: {val}\n'
        f'🔢 مصرف کلی: {d.used_count} / {limit}\n'
        f'👤 محدودیت هر کاربر: {per_user}\n'
        f'⚙️ وضعیت: {"فعال" if d.is_active else "غیرفعال"}'
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✏️ تغییر مقدار/درصد', callback_data=f'discount:edit_value:{did}')],
        [InlineKeyboardButton(text='🔢 تغییر سقف کلی', callback_data=f'discount:edit_max:{did}')],
        [InlineKeyboardButton(text='👤 تغییر سقف هر کاربر', callback_data=f'discount:edit_user:{did}')],
        [InlineKeyboardButton(text='🟢/🔴 فعال یا غیرفعال', callback_data=f'discount:toggle:{did}')],
        [InlineKeyboardButton(text='🗑 حذف کد', callback_data=f'discount:delete:{did}')],
        [back_button('discount:list')],
    ])
    await state.clear()
    await edit_or_answer(callback, text, reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data.startswith('discount:edit_value:'))
async def discount_edit_value_start(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    did = int(callback.data.split(':')[-1])
    await state.clear(); await state.update_data(edit_discount_id=did); await state.set_state(EditDiscountCode.value)
    await edit_or_answer(callback, 'مقدار جدید را وارد کنید. برای درصد فقط عدد 1 تا 100 و برای مبلغ عدد تومان:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(f'discount:detail:{did}')]]))
    await callback.answer()

@router.message(EditDiscountCode.value)
async def discount_edit_value_save(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    data = await state.get_data(); did = int(data['edit_discount_id'])
    try: value = int((message.text or '').replace(',', '').strip())
    except ValueError:
        await ui_message(message, 'فقط عدد وارد کنید.'); return
    async with SessionLocal() as session:
        d = await session.get(DiscountCode, did)
        if d.discount_type == 'percent' and not (1 <= value <= 100):
            await ui_message(message, 'درصد باید بین 1 تا 100 باشد.'); return
        d.value = value; await session.commit()
    await state.clear(); await ui_message(message, '✅ مقدار کد تخفیف تغییر کرد.', reply_markup=discounts_kb())

@router.callback_query(F.data.startswith('discount:edit_max:'))
async def discount_edit_max_start(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    did = int(callback.data.split(':')[-1]); await state.clear(); await state.update_data(edit_discount_id=did); await state.set_state(EditDiscountCode.max_uses)
    await edit_or_answer(callback, 'سقف استفاده کلی را وارد کنید. برای نامحدود عدد 0:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(f'discount:detail:{did}')]])); await callback.answer()

@router.message(EditDiscountCode.max_uses)
async def discount_edit_max_save(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    data = await state.get_data(); did = int(data['edit_discount_id'])
    try: value = int((message.text or '').replace(',', '').strip())
    except ValueError:
        await ui_message(message, 'فقط عدد وارد کنید.'); return
    async with SessionLocal() as session:
        d = await session.get(DiscountCode, did); d.max_uses = value; await session.commit()
    await state.clear(); await ui_message(message, '✅ سقف کلی تغییر کرد.', reply_markup=discounts_kb())

@router.callback_query(F.data.startswith('discount:edit_user:'))
async def discount_edit_user_start(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    did = int(callback.data.split(':')[-1]); await state.clear(); await state.update_data(edit_discount_id=did); await state.set_state(EditDiscountCode.per_user_limit)
    await edit_or_answer(callback, 'هر کاربر چند بار بتواند استفاده کند؟ برای نامحدود عدد 0:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(f'discount:detail:{did}')]])); await callback.answer()

@router.message(EditDiscountCode.per_user_limit)
async def discount_edit_user_save(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    data = await state.get_data(); did = int(data['edit_discount_id'])
    try: value = int((message.text or '').replace(',', '').strip())
    except ValueError:
        await ui_message(message, 'فقط عدد وارد کنید.'); return
    async with SessionLocal() as session:
        d = await session.get(DiscountCode, did); d.per_user_limit = value; await session.commit()
    await state.clear(); await ui_message(message, '✅ محدودیت هر کاربر تغییر کرد.', reply_markup=discounts_kb())

@router.callback_query(F.data.startswith('discount:delete:'))
async def discount_delete_ask(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    did = int(callback.data.split(':')[-1])
    kb=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ بله، کد حذف شود', callback_data=f'discount:delete_confirm:{did}')],
        [back_button(f'discount:detail:{did}')],
    ])
    await edit_or_answer(callback, '⚠️ مطمئنی می‌خواهی این کد تخفیف حذف شود؟', reply_markup=kb); await callback.answer()

@router.callback_query(F.data.startswith('discount:delete_confirm:'))
async def discount_delete(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    did = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        d = await session.get(DiscountCode, did)
        if d:
            await session.delete(d); await session.commit()
    await discount_list(callback)


# ---------------- Website admin panel settings ----------------
async def _notify_admins(bot, text: str, reply_markup=None) -> None:
    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(admin_id, text, reply_markup=reply_markup)
        except Exception:
            pass


def _website_back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='⬅️ برگشت', callback_data='admin:website_settings')]])

async def _get_web_settings_text() -> str:
    domain = await get_setting_value('web_domain', '')
    username = await get_setting_value('web_admin_username', '')
    timeout = await get_setting_value('web_token_timeout_minutes', '30')
    cert_status = await get_setting_value('web_ssl_status', 'not_configured')
    password_status = 'ثبت شده' if await get_setting_value('web_admin_password', '') else 'ثبت نشده'
    return (
        '🌐 تنظیمات وب سایت\n━━━━━━━━━━━━━━━━\n\n'
        f'🌍 دامنه: {domain or "ثبت نشده"}\n'
        f'👤 Username: {username or "ثبت نشده"}\n'
        f'🔐 Password: {password_status}\n'
        f'⏱ زمان توکن: {timeout} دقیقه\n'
        f'🛡 وضعیت SSL: {cert_status}\n\n'
        'بعد از ثبت دامنه، سیستم همان لحظه روی VPS برای همان دامنه SSL می‌گیرد. اگر خطا رخ دهد، پیام خطا برای مدیر ارسال می‌شود.\n\nدستور سریع ربات: /websetup your-domain.com'
    )


def _website_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='👤 تغییر Username', callback_data='website:set_username'), InlineKeyboardButton(text='🔐 تغییر Password', callback_data='website:set_password')],
        [InlineKeyboardButton(text='🌍 تغییر دامنه و دریافت SSL', callback_data='website:set_domain')],
        [InlineKeyboardButton(text='⏱ تغییر زمان توکن', callback_data='website:set_timeout')],
        [back_button('admin:bot_settings')],
    ])



def _normalize_domain(raw: str) -> str:
    return (raw or '').strip().replace('https://', '').replace('http://', '').strip('/').split('/')[0]


def _valid_domain(domain: str) -> bool:
    import re
    return bool(re.match(r'^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$', domain or ''))


async def _run_web_ssl(domain: str) -> tuple[bool, str]:
    cmd = f"bash scripts/setup_web_ssl.sh {domain}"
    try:
        proc = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await proc.communicate()
        output = ((out or b'') + b'\n' + (err or b'')).decode(errors='ignore').strip()
        if proc.returncode == 0:
            return True, output[-1800:] or 'SSL applied successfully'
        return False, output[-3500:] or 'Unknown SSL error'
    except Exception as exc:
        return False, str(exc)


async def _start_domain_ssl_flow(message: Message, state: FSMContext, domain: str) -> None:
    domain = _normalize_domain(domain)
    if not _valid_domain(domain):
        await state.set_state(WebsiteCommandSetup.domain)
        await ui_message(
            message,
            '🌍 دامنه معتبر نیست. دامنه را بدون https وارد کنید.\n\nمثال:\nexample.com',
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:website_settings')]])
        )
        return
    await state.clear()
    await save_web_setting('web_domain', domain)
    await set_value('web_ssl_status', 'running')
    await ui_message(message, f'⏳ دامنه ذخیره شد. در حال دریافت SSL برای:\n{domain}\n\nبعد از موفقیت، Username و Password پنل سایت را از شما می‌پرسم.')
    ok_ssl, msg = await _run_web_ssl(domain)
    if not ok_ssl:
        await set_value('web_ssl_status', 'error')
        await set_value('web_ssl_message', msg)
        await ui_message(
            message,
            f'❌ SSL برای دامنه فعال نشد.\n🌍 Domain: {domain}\n\n{msg[-3000:]}',
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:website_settings')]])
        )
        return
    await set_value('web_ssl_status', 'active')
    await set_value('web_ssl_message', msg)
    await state.update_data(web_setup_domain=domain)
    await state.set_state(WebsiteCommandSetup.username)
    await ui_message(
        message,
        f'✅ SSL با موفقیت فعال شد.\n🌍 Domain: {domain}\n\nحالا Username جدید پنل سایت را ارسال کنید:',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:website_settings')]])
    )


@router.message(Command('websetup'))
@router.message(Command('site_setup'))
@router.message(Command('sslsetup'))
async def website_command_setup_start(message: Message, state: FSMContext):
    if not admin(message.from_user.id):
        return
    parts = (message.text or '').split(maxsplit=1)
    if len(parts) > 1 and parts[1].strip():
        await _start_domain_ssl_flow(message, state, parts[1].strip())
        return
    await state.clear()
    await state.set_state(WebsiteCommandSetup.domain)
    await ui_message(
        message,
        '🌐 راه‌اندازی دامنه، SSL و اطلاعات ورود سایت\n\nدامنه را بدون https ارسال کنید.\nمثال:\nexample.com\n\nیا مستقیم بزنید:\n/websetup example.com',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:website_settings')]])
    )


@router.message(WebsiteCommandSetup.domain)
async def website_command_domain_save(message: Message, state: FSMContext):
    if not admin(message.from_user.id):
        return
    await _start_domain_ssl_flow(message, state, message.text or '')


@router.message(WebsiteCommandSetup.username)
async def website_command_username_save(message: Message, state: FSMContext):
    if not admin(message.from_user.id):
        return
    username = (message.text or '').strip()
    if len(username) < 3:
        await ui_message(message, '❌ Username باید حداقل ۳ کاراکتر باشد.')
        return
    await state.update_data(web_setup_username=username)
    await state.set_state(WebsiteCommandSetup.password)
    await ui_message(message, '🔐 حالا Password جدید پنل سایت را ارسال کنید.\nحداقل ۴ کاراکتر باشد.')


@router.message(WebsiteCommandSetup.password)
async def website_command_password_save(message: Message, state: FSMContext):
    if not admin(message.from_user.id):
        return
    password = (message.text or '').strip()
    if len(password) < 4:
        await ui_message(message, '❌ Password باید حداقل ۴ کاراکتر باشد.')
        return
    data = await state.get_data()
    domain = data.get('web_setup_domain') or await get_setting_value('web_domain', '')
    username = data.get('web_setup_username') or 'admin'
    await save_web_settings_bulk({
        'web_admin_username': username,
        'web_admin_password': password,
        'web_credentials_updated_at': datetime.utcnow().isoformat(),
    })
    await state.clear()
    url = f'https://{domain}/admin' if domain else '/admin'
    await ui_message(
        message,
        '✅ تنظیمات ورود سایت ذخیره شد.\n\n'
        f'🌍 Login URL: {url}\n'
        f'👤 Username: {username}\n'
        f'🔐 Password: {password}\n\n'
        'از این به بعد با همین اطلاعات وارد پنل Owner شوید.',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:website_settings')]])
    )

@router.callback_query(F.data == 'admin:website_settings')
async def website_settings_menu(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    await edit_or_answer(callback, await _get_web_settings_text(), reply_markup=_website_kb())
    await callback.answer()


@router.callback_query(F.data == 'website:set_username')
async def website_username_start(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    await state.set_state(WebsiteSettings.username)
    await edit_or_answer(callback, '👤 Username جدید پنل سایت را وارد کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:website_settings')]]))
    await callback.answer()


@router.message(WebsiteSettings.username)
async def website_username_save(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    username = message.text.strip()
    await save_web_setting('web_admin_username', username)
    await state.clear()
    await ui_message(message, f'✅ Username سایت داخل دیتابیس ذخیره شد.\n👤 Username فعلی: {username}\n\nبرای اعمال کامل، از سایت Logout کنید و دوباره Login بزنید.', reply_markup=_website_kb())


@router.callback_query(F.data == 'website:set_password')
async def website_password_start(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    await state.set_state(WebsiteSettings.password)
    await edit_or_answer(callback, '🔐 Password جدید پنل سایت را وارد کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:website_settings')]]))
    await callback.answer()


@router.message(WebsiteSettings.password)
async def website_password_save(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    password = message.text.strip()
    if len(password) < 4:
        await ui_message(message, '❌ Password باید حداقل ۴ کاراکتر باشد.', reply_markup=_website_kb())
        return
    await save_web_setting('web_admin_password', password)
    await state.clear()
    await ui_message(message, '✅ Password سایت داخل دیتابیس ذخیره شد.\n🔐 برای تست، از سایت Logout کنید و با پسورد جدید وارد شوید.', reply_markup=_website_kb())


@router.callback_query(F.data == 'website:set_timeout')
async def website_timeout_start(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    await state.set_state(WebsiteSettings.token_timeout)
    await edit_or_answer(callback, '⏱ زمان اعتبار توکن را به دقیقه وارد کنید. مثال: 30', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:website_settings')]]))
    await callback.answer()


@router.message(WebsiteSettings.token_timeout)
async def website_timeout_save(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    value = max(5, int(message.text.strip()))
    await save_web_setting('web_token_timeout_minutes', str(value))
    await state.clear()
    await ui_message(message, f'✅ زمان توکن سایت روی {value} دقیقه تنظیم شد.', reply_markup=_website_kb())


@router.callback_query(F.data == 'website:set_domain')
async def website_domain_start(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    await state.set_state(WebsiteSettings.domain)
    await edit_or_answer(callback, '🌍 دامنه سایت را بدون https وارد کنید. مثال:\nexample.com', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:website_settings')]]))
    await callback.answer()


@router.message(WebsiteSettings.domain)
async def website_domain_save(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    import asyncio, re
    domain = message.text.strip().replace('https://','').replace('http://','').strip('/')
    if not re.match(r'^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$', domain):
        await ui_message(message, '❌ دامنه معتبر نیست.', reply_markup=_website_kb()); return
    await save_web_setting('web_domain', domain)
    await set_value('web_ssl_status', 'running')
    await state.clear()

    # Send SSL progress as a brand-new message, not by editing the previous website menu.
    await message.answer('⏳ دامنه ذخیره شد. در حال دریافت SSL روی VPS هستم...')

    cmd = f"bash scripts/setup_web_ssl.sh {domain}"
    try:
        proc = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await proc.communicate()
        output = ((out or b'') + b'\n' + (err or b'')).decode(errors='ignore')
        if proc.returncode == 0:
            await set_value('web_ssl_status', 'active')
            await _notify_admins(message.bot, f'✅ SSL سایت با موفقیت فعال شد.\n🌍 Domain: {domain}', reply_markup=_website_back_kb())
        else:
            error = output[-3500:] or 'Unknown SSL error'
            await set_value('web_ssl_status', 'error')
            await _notify_admins(
                message.bot,
                f'❌ خطا در دریافت SSL سایت\n🌍 Domain: {domain}\n\n{error}',
                reply_markup=_website_back_kb(),
            )
    except Exception as e:
        await set_value('web_ssl_status', 'error')
        await report_bot_error(message.bot, e, context=f'Website SSL command failed for domain={domain}', event=message)
        await _notify_admins(
            message.bot,
            f'❌ خطایی رخ داده. هرچه زودتر با پشتیبانی در ارتباط باشید.\n🌍 Domain: {domain}',
            reply_markup=_website_back_kb(),
        )


# =========================
# Referral settings
# =========================
from app.services.referral_service import referral_status_text


def referral_settings_kb(reward_enabled: str = '0', commission_enabled: str = '0') -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f'1️⃣ ارسال یوزر به ازای دعوت | {"🟢 روشن" if reward_enabled == "1" else "🔴 خاموش"}', callback_data='refset:reward')],
        [InlineKeyboardButton(text=f'2️⃣ پورسانت به ازای خرید | {"🟢 روشن" if commission_enabled == "1" else "🔴 خاموش"}', callback_data='refset:commission')],
        [back_button('admin:user_interaction')],
    ])


@router.callback_query(F.data == 'admin:referral_settings')
async def referral_settings_menu(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    reward_enabled = await get_setting_value('referral_reward_service_enabled', '0')
    commission_enabled = await get_setting_value('referral_commission_enabled', '0')
    await edit_or_answer(callback, await referral_status_text(), reply_markup=referral_settings_kb(reward_enabled, commission_enabled))
    await callback.answer()


@router.callback_query(F.data == 'refset:reward')
async def referral_reward_start(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    await state.clear()
    async with SessionLocal() as session:
        servers=(await session.execute(select(Server).where(Server.is_active == True).order_by(Server.id.asc()))).scalars().all()
    rows=[]
    for s in servers:
        rows.append([InlineKeyboardButton(text=f'🖥 {s.name}', callback_data=f'refset:reward_server:{s.id}')])
    rows.append([back_button('admin:referral_settings')])
    await state.set_state(ReferralSettingsConfig.reward_server_id)
    await edit_or_answer(callback, '🎁 ارسال یوزر به ازای دعوت\n\nاول سرور هدیه را انتخاب کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(F.data.startswith('refset:reward_server:'))
async def referral_reward_server(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    sid=int(callback.data.split(':')[-1])
    await state.update_data(reward_server_id=sid)
    await state.set_state(ReferralSettingsConfig.reward_volume)
    await edit_or_answer(callback, '📦 چند گیگ هدیه داده شود؟\nفقط عدد وارد کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:referral_settings')]]))
    await callback.answer()


@router.message(ReferralSettingsConfig.reward_volume)
async def referral_reward_volume(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    try:
        value=int(message.text.strip().replace(',', ''))
        if value <= 0: raise ValueError()
    except Exception:
        await ui_message(message, '❌ حجم باید عدد مثبت باشد. دوباره وارد کنید:')
        return
    await state.update_data(reward_volume=value)
    await state.set_state(ReferralSettingsConfig.reward_days)
    await ui_message(message, '⏳ چند روز اعتبار داشته باشد؟\nفقط عدد وارد کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:referral_settings')]]))


@router.message(ReferralSettingsConfig.reward_days)
async def referral_reward_days(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    try:
        value=int(message.text.strip().replace(',', ''))
        if value <= 0: raise ValueError()
    except Exception:
        await ui_message(message, '❌ تعداد روز باید عدد مثبت باشد. دوباره وارد کنید:')
        return
    await state.update_data(reward_days=value)
    await state.set_state(ReferralSettingsConfig.reward_invites)
    await ui_message(message, '👥 به ازای چند دعوت این سرویس داده شود؟\nفقط عدد وارد کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:referral_settings')]]))


@router.message(ReferralSettingsConfig.reward_invites)
async def referral_reward_invites(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    try:
        value=int(message.text.strip().replace(',', ''))
        if value <= 0: raise ValueError()
    except Exception:
        await ui_message(message, '❌ تعداد دعوت باید عدد مثبت باشد. دوباره وارد کنید:')
        return
    data=await state.get_data()
    await set_value('referral_reward_service_enabled', '1')
    await set_value('referral_reward_server_id', str(data.get('reward_server_id')))
    await set_value('referral_reward_volume_gb', str(data.get('reward_volume')))
    await set_value('referral_reward_days', str(data.get('reward_days')))
    await set_value('referral_reward_invites', str(value))
    await state.clear()
    text=(
        '✅ شرط ارسال یوزر به ازای دعوت ثبت شد.\n\n'
        f'🖥 سرور: {data.get("reward_server_id")}\n'
        f'📦 حجم: {data.get("reward_volume")} گیگ\n'
        f'⏳ مدت: {data.get("reward_days")} روز\n'
        f'👥 شرط: هر {value} دعوت'
    )
    await ui_message(message, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:referral_settings')]]))
    # Show previous page again in a new message, as requested.
    reward_enabled = await get_setting_value('referral_reward_service_enabled', '0')
    commission_enabled = await get_setting_value('referral_commission_enabled', '0')
    await ui_message(message, await referral_status_text(), reply_markup=referral_settings_kb(reward_enabled, commission_enabled))


@router.callback_query(F.data == 'refset:commission')
async def referral_commission_start(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    await state.clear()
    await state.set_state(ReferralSettingsConfig.commission_percent)
    await edit_or_answer(callback, '💰 پورسانت به ازای خرید\n\nدرصد پورسانت را وارد کنید. مثال: 10', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:referral_settings')]]))
    await callback.answer()


@router.message(ReferralSettingsConfig.commission_percent)
async def referral_commission_save(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    raw=message.text.strip().replace('%','').replace(',', '.')
    try:
        percent=float(raw)
        if percent < 0 or percent > 100: raise ValueError()
    except Exception:
        await ui_message(message, '❌ درصد باید عددی بین 0 تا 100 باشد. دوباره وارد کنید:')
        return
    await set_value('referral_commission_enabled', '1' if percent > 0 else '0')
    await set_value('referral_commission_percent', str(percent).rstrip('0').rstrip('.') if isinstance(percent, float) else str(percent))
    await state.clear()
    await ui_message(message, f'✅ پورسانت خرید ثبت شد: {percent:g}٪\nاز این به بعد درصد خرید کاربران زیرمجموعه به کیف پول معرف اضافه می‌شود.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:referral_settings')]]))
    reward_enabled = await get_setting_value('referral_reward_service_enabled', '0')
    commission_enabled = await get_setting_value('referral_commission_enabled', '0')
    await ui_message(message, await referral_status_text(), reply_markup=referral_settings_kb(reward_enabled, commission_enabled))
