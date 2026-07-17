from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

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

def back_button(callback_data: str = CB_BACK_MAIN):
    return InlineKeyboardButton(text=BTN_BACK, callback_data=callback_data)

def _pair_rows(buttons: list[InlineKeyboardButton]) -> list[list[InlineKeyboardButton]]:
    return [buttons[i:i + 2] for i in range(0, len(buttons), 2)]

def main_menu_inline(is_admin: bool = False, show_test: bool = True, is_reseller: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=BTN_BUY, callback_data=CB_BUY),
        InlineKeyboardButton(text=BTN_MY_SERVICES, callback_data=CB_MY_SERVICES),
        InlineKeyboardButton(text=BTN_ACCOUNT, callback_data=CB_ACCOUNT),
    ]
    if show_test:
        buttons.append(InlineKeyboardButton(text=BTN_TEST_ACCOUNT, callback_data=CB_TEST_ACCOUNT))
    buttons.extend([
        InlineKeyboardButton(text=BTN_TICKETS, callback_data=CB_TICKETS),
        InlineKeyboardButton(text=BTN_REFERRAL, callback_data=CB_REFERRAL),
        InlineKeyboardButton(text=BTN_QUERY, callback_data=CB_QUERY),
    ])
    # برای کاربر عادی، درخواست/منوی نمایندگی آخرین دکمه و تنها پایین صفحه است.
    # برای مدیر، دکمه «مدیریت ربات» باید آخرین دکمه باشد.
    if not is_admin:
        rows = _pair_rows(buttons)
        rows.append([InlineKeyboardButton(text=(BTN_RESELLER_MENU if is_reseller else BTN_RESELLER_REQUEST), callback_data=CB_RESELLER)])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    buttons.append(InlineKeyboardButton(text=BTN_RESELLER_MENU, callback_data=CB_RESELLER))
    rows = _pair_rows(buttons)
    rows.append([InlineKeyboardButton(text=BTN_ADMIN, callback_data=CB_ADMIN)])
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
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=BTN_ACCEPT_RULES, callback_data='rules:accept')]])

# Compatibility aliases.
def public_menu():
    return main_menu_inline(False)
def admin_menu():
    return main_menu_inline(True)
def admin_panel_menu():
    return admin_panel_inline()
