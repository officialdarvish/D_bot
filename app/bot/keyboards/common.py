from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select

from app.database.models import Setting
from app.database.session import SessionLocal

BTN_BUY = 'خرید کانفیگ 🛒'
BTN_MY_SERVICES = 'کانفیگ های من 📱'
BTN_ACCOUNT = 'حساب کاربری 👨‍💼'
BTN_TEST_ACCOUNT = 'اکانت تست 🧪'
BTN_TICKETS = 'تیکت های من 📨'
BTN_REFERRAL = 'زیرمجموعه گیری 🎁'
BTN_REFERRAL_SETTINGS = 'زیرمجموعه گیری 🎁'
BTN_QUERY = 'مشخصات کانفیگ 🧯'
BTN_RESELLER_REQUEST = 'درخواست نمایندگی 🤝'
BTN_RESELLER_MENU = 'منو نمایندگی 🤝'
BTN_ADMIN = 'مدیریت ربات ⚙️'
BTN_ACCEPT_RULES = '✅ قوانین را قبول دارم'
BTN_WALLET_TOPUP = 'شارژ کردن کیف پول 💳'

BTN_SERVERS = 'مدیریت سرور 🖥'
BTN_CATEGORIES = 'مدیریت دسته‌ها 🗂'
BTN_PLANS = 'مدیریت پلن‌های فروش 📋'
BTN_DISCOUNTS = 'کد تخفیف 🏷'
BTN_PAYMENT_CHANNEL = 'درگاه پرداخت 💳'
BTN_BROADCAST = 'ارسال پیام همگانی 📢'
BTN_WALLET_ADJUST = 'کیف پول 💰'
BTN_USERS = 'اطلاعات کاربران 👥'
BTN_RULES = 'متن خوشامدگویی و قوانین 📜'
BTN_BUTTONS = 'مدیریت دکمه‌ها 🔘'
BTN_WEBSITE_SETTINGS = 'وب سایت 🌐'
BTN_BACKUP = 'بک آپ 📦'
BTN_RESTORE = 'ری استور بک آپ ♻️'
BTN_RESELLERS = 'تنظیمات نماینده‌ها 🤝'
BTN_BACK = '🔙 بازگشت'

CB_BUY = 'menu:buy'
CB_MY_SERVICES = 'menu:my_services'
CB_ACCOUNT = 'menu:account'
CB_TEST_ACCOUNT = 'menu:test_account'
CB_TICKETS = 'menu:tickets'
CB_REFERRAL = 'menu:referral'
CB_REFERRAL_SETTINGS = 'admin:referral_settings'
CB_QUERY = 'menu:query'
CB_RESELLER = 'menu:reseller'
CB_ADMIN = 'menu:admin'
CB_BACK_MAIN = 'back:main'
CB_BACK_ADMIN = 'back:admin'

CB_SERVERS = 'admin:servers'
CB_CATEGORIES = 'admin:categories'
CB_PLANS = 'admin:plans'
CB_DISCOUNTS = 'admin:discounts'
CB_PAYMENT_CHANNEL = 'admin:payment_channel'
CB_BROADCAST = 'admin:broadcast'
CB_WALLET_ADJUST = 'admin:wallet_adjust'
CB_USERS = 'admin:users'
CB_RULES = 'admin:rules'
CB_BUTTONS = 'admin:buttons'
CB_BACKUP = 'admin:backup'
CB_RESTORE = 'admin:restore'
CB_RESELLERS = 'admin:resellers'
BTN_SALES_SECTION = 'بخش فروش 🛒'
BTN_USER_INTERACTION = 'تعامل با کاربر 👥'
BTN_BOT_SETTINGS = 'تنظیمات ربات ⚙️'
CB_SALES_SECTION = 'admin:sales_section'
CB_USER_INTERACTION = 'admin:user_interaction'
CB_BOT_SETTINGS = 'admin:bot_settings'

# User-facing buttons configurable from Admin Web > Settings > Bottom.
BUTTON_DEFAULTS: dict[str, tuple[str, bool]] = {
    'buy': (BTN_BUY, True),
    'my_services': (BTN_MY_SERVICES, True),
    'account': (BTN_ACCOUNT, True),
    'test_account': (BTN_TEST_ACCOUNT, True),
    'tickets': (BTN_TICKETS, True),
    'referral': (BTN_REFERRAL, True),
    'query': (BTN_QUERY, True),
    'reseller_request': (BTN_RESELLER_REQUEST, True),
    'reseller_menu': (BTN_RESELLER_MENU, True),
    'admin': (BTN_ADMIN, True),
    'wallet_topup': (BTN_WALLET_TOPUP, True),
}


def button_text_key(name: str) -> str:
    return f'button_{name}_text'


def button_enabled_key(name: str) -> str:
    return f'button_{name}_enabled'


async def _load_button_settings(names: list[str] | None = None) -> dict[str, str]:
    names = names or list(BUTTON_DEFAULTS)
    keys: list[str] = []
    for name in names:
        keys.extend([button_text_key(name), button_enabled_key(name)])
    async with SessionLocal() as session:
        rows = (await session.execute(select(Setting).where(Setting.key.in_(keys)))).scalars().all()
    return {row.key: str(row.value or '') for row in rows}


def _button_value(values: dict[str, str], name: str) -> tuple[str, bool]:
    default_text, default_enabled = BUTTON_DEFAULTS[name]
    text = values.get(button_text_key(name), '').strip() or default_text
    enabled_raw = values.get(button_enabled_key(name), '1' if default_enabled else '0').strip().lower()
    enabled = enabled_raw not in {'0', 'false', 'off', 'no', 'disabled'}
    return text[:64], enabled


async def get_user_button(name: str) -> tuple[str, bool]:
    if name not in BUTTON_DEFAULTS:
        raise KeyError(name)
    values = await _load_button_settings([name])
    return _button_value(values, name)


def back_button(callback_data: str = CB_BACK_MAIN):
    return InlineKeyboardButton(text=BTN_BACK, callback_data=callback_data)


def _pair_rows(buttons: list[InlineKeyboardButton]) -> list[list[InlineKeyboardButton]]:
    return [buttons[i:i + 2] for i in range(0, len(buttons), 2)]


async def main_menu_inline(is_admin: bool = False, show_test: bool = True, is_reseller: bool = False) -> InlineKeyboardMarkup:
    values = await _load_button_settings([
        'buy', 'my_services', 'account', 'test_account', 'tickets', 'referral',
        'query', 'reseller_request', 'reseller_menu', 'admin',
    ])

    buttons: list[InlineKeyboardButton] = []
    for name, callback_data in (
        ('buy', CB_BUY),
        ('my_services', CB_MY_SERVICES),
        ('account', CB_ACCOUNT),
    ):
        text, enabled = _button_value(values, name)
        if enabled:
            buttons.append(InlineKeyboardButton(text=text, callback_data=callback_data))

    test_text, test_enabled = _button_value(values, 'test_account')
    if show_test and test_enabled:
        buttons.append(InlineKeyboardButton(text=test_text, callback_data=CB_TEST_ACCOUNT))

    for name, callback_data in (
        ('tickets', CB_TICKETS),
        ('referral', CB_REFERRAL),
        ('query', CB_QUERY),
    ):
        text, enabled = _button_value(values, name)
        if enabled:
            buttons.append(InlineKeyboardButton(text=text, callback_data=callback_data))

    rows = _pair_rows(buttons)
    if not is_admin:
        reseller_name = 'reseller_menu' if is_reseller else 'reseller_request'
        reseller_text, reseller_enabled = _button_value(values, reseller_name)
        if reseller_enabled:
            rows.append([InlineKeyboardButton(text=reseller_text, callback_data=CB_RESELLER)])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    reseller_text, reseller_enabled = _button_value(values, 'reseller_menu')
    if reseller_enabled:
        rows.append([InlineKeyboardButton(text=reseller_text, callback_data=CB_RESELLER)])
    admin_text, admin_enabled = _button_value(values, 'admin')
    if admin_enabled:
        rows.append([InlineKeyboardButton(text=admin_text, callback_data=CB_ADMIN)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_panel_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=BTN_SALES_SECTION, callback_data=CB_SALES_SECTION), InlineKeyboardButton(text=BTN_USER_INTERACTION, callback_data=CB_USER_INTERACTION)],
        [InlineKeyboardButton(text=BTN_BOT_SETTINGS, callback_data=CB_BOT_SETTINGS), InlineKeyboardButton(text=BTN_RESELLERS, callback_data=CB_RESELLERS)],
        [back_button(CB_BACK_MAIN)],
    ])


def sales_section_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=BTN_SERVERS, callback_data=CB_SERVERS), InlineKeyboardButton(text=BTN_CATEGORIES, callback_data=CB_CATEGORIES)],
        [InlineKeyboardButton(text='🧩 نوع سرویس‌ها', callback_data='buttons:service_types'), InlineKeyboardButton(text=BTN_PLANS, callback_data=CB_PLANS)],
        [InlineKeyboardButton(text=BTN_PAYMENT_CHANNEL, callback_data=CB_PAYMENT_CHANNEL), InlineKeyboardButton(text=BTN_DISCOUNTS, callback_data=CB_DISCOUNTS)],
        [back_button(CB_BACK_ADMIN)],
    ])


def user_interaction_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=BTN_BROADCAST, callback_data=CB_BROADCAST), InlineKeyboardButton(text=BTN_TICKETS, callback_data=CB_TICKETS)],
        [InlineKeyboardButton(text=BTN_USERS, callback_data=CB_USERS), InlineKeyboardButton(text=BTN_WALLET_ADJUST, callback_data=CB_WALLET_ADJUST)],
        [InlineKeyboardButton(text=BTN_RULES, callback_data=CB_RULES), InlineKeyboardButton(text=BTN_REFERRAL_SETTINGS, callback_data=CB_REFERRAL_SETTINGS)],
        [back_button(CB_BACK_ADMIN)],
    ])


def bot_settings_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=BTN_WEBSITE_SETTINGS, callback_data='admin:website_settings')],
        [back_button(CB_BACK_ADMIN)],
    ])


def back_main_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[back_button(CB_BACK_MAIN)]])


def back_admin_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[back_button(CB_BACK_ADMIN)]])


def rules_keyboard() -> InlineKeyboardMarkup:
    # Acceptance is intentionally always available; disabling it would lock every
    # new user out of the bot. Its text remains managed from the rules message page.
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=BTN_ACCEPT_RULES, callback_data='rules:accept')]])


# Compatibility aliases.
async def public_menu():
    return await main_menu_inline(False)


async def admin_menu():
    return await main_menu_inline(True)


def admin_panel_menu():
    return admin_panel_inline()
