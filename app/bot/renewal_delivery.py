from __future__ import annotations

from datetime import datetime

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.utils.jalali import fa_date


RENEWAL_CONFIRMATION_XUI_TEXT = (
    '✅ تمدید سرویس با موفقیت انجام شد.\n\n'
    '🧾 مشخصات تمدید\n'
    '━━━━━━━━━━━━━━\n'
    '👤 نام سرویس: {username}\n'
    '📦 تعرفه: {plan_title}\n'
    '💾 حجم جدید: {volume_label}\n'
    '⏳ مدت اعتبار: {duration_label}\n'
    '📅 تاریخ انقضای جدید: {expires_at}\n\n'
    'ℹ️ اطلاعات اتصال، رمز و لینک قبلی شما تغییری نکرده و دوباره ارسال نمی‌شود.\n\n'
    '♻️ آموزش بروزرسانی در Happ\n'
    '1) برنامه Happ را باز کنید.\n'
    '2) Subscription همین سرویس را پیدا کنید.\n'
    '3) روی Update / Refresh Subscription بزنید.\n'
    '4) بعد از پایان بروزرسانی، اتصال را یک‌بار قطع و وصل کنید.'
)

RENEWAL_CONFIRMATION_XUI_WITH_AMOUNT_TEXT = (
    '✅ تمدید سرویس با موفقیت انجام شد.\n\n'
    '🧾 مشخصات تمدید\n'
    '━━━━━━━━━━━━━━\n'
    '👤 نام سرویس: {username}\n'
    '📦 تعرفه: {plan_title}\n'
    '💾 حجم جدید: {volume_label}\n'
    '⏳ مدت اعتبار: {duration_label}\n'
    '📅 تاریخ انقضای جدید: {expires_at}\n'
    '💰 مبلغ پرداختی: {amount_irt} تومان\n\n'
    'ℹ️ اطلاعات اتصال، رمز و لینک قبلی شما تغییری نکرده و دوباره ارسال نمی‌شود.\n\n'
    '♻️ آموزش بروزرسانی در Happ\n'
    '1) برنامه Happ را باز کنید.\n'
    '2) Subscription همین سرویس را پیدا کنید.\n'
    '3) روی Update / Refresh Subscription بزنید.\n'
    '4) بعد از پایان بروزرسانی، اتصال را یک‌بار قطع و وصل کنید.'
)

RENEWAL_CONFIRMATION_OPENVPN_TEXT = (
    '✅ تمدید سرویس با موفقیت انجام شد.\n\n'
    '🧾 مشخصات تمدید\n'
    '━━━━━━━━━━━━━━\n'
    '👤 نام سرویس: {username}\n'
    '📦 تعرفه: {plan_title}\n'
    '💾 حجم جدید: {volume_label}\n'
    '⏳ مدت اعتبار: {duration_label}\n'
    '📅 تاریخ انقضای جدید: {expires_at}\n\n'
    'ℹ️ اطلاعات اتصال، رمز و لینک قبلی شما تغییری نکرده و دوباره ارسال نمی‌شود.\n\n'
    '♻️ برای اعمال تمدید OpenVPN، اتصال را یک‌بار قطع و دوباره وصل کنید؛ نیازی به دریافت مجدد پروفایل نیست.'
)

RENEWAL_CONFIRMATION_OPENVPN_WITH_AMOUNT_TEXT = (
    '✅ تمدید سرویس با موفقیت انجام شد.\n\n'
    '🧾 مشخصات تمدید\n'
    '━━━━━━━━━━━━━━\n'
    '👤 نام سرویس: {username}\n'
    '📦 تعرفه: {plan_title}\n'
    '💾 حجم جدید: {volume_label}\n'
    '⏳ مدت اعتبار: {duration_label}\n'
    '📅 تاریخ انقضای جدید: {expires_at}\n'
    '💰 مبلغ پرداختی: {amount_irt} تومان\n\n'
    'ℹ️ اطلاعات اتصال، رمز و لینک قبلی شما تغییری نکرده و دوباره ارسال نمی‌شود.\n\n'
    '♻️ برای اعمال تمدید OpenVPN، اتصال را یک‌بار قطع و دوباره وصل کنید؛ نیازی به دریافت مجدد پروفایل نیست.'
)


def renewal_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='📱 کانفیگ‌های من', callback_data='menu:my_services')],
        [InlineKeyboardButton(text='🏠 خانه', callback_data='home:main')],
    ])


def _volume_label(volume_gb: int | float | None) -> str:
    value = float(volume_gb or 0)
    if value <= 0:
        return 'نامحدود'
    return f'{value:g} گیگ'


def _duration_label(duration_days: int | None) -> str:
    value = int(duration_days or 0)
    if value <= 0:
        return 'نامحدود'
    return f'{value} روز'


def renewal_confirmation_text(
    *,
    username: str | None,
    plan_title: str | None,
    volume_gb: int | float | None,
    duration_days: int | None,
    expires_at: datetime | None,
    server_type: str = 'xui',
    amount_irt: int | None = None,
) -> str:
    values = {
        'username': username or '-',
        'plan_title': plan_title or '-',
        'volume_label': _volume_label(volume_gb),
        'duration_label': _duration_label(duration_days),
        'expires_at': fa_date(expires_at),
        'amount_irt': f'{int(amount_irt or 0):,}',
    }
    is_xui = (server_type or '').lower() == 'xui'
    if is_xui:
        template = RENEWAL_CONFIRMATION_XUI_WITH_AMOUNT_TEXT if amount_irt is not None else RENEWAL_CONFIRMATION_XUI_TEXT
    else:
        template = RENEWAL_CONFIRMATION_OPENVPN_WITH_AMOUNT_TEXT if amount_irt is not None else RENEWAL_CONFIRMATION_OPENVPN_TEXT
    return template.format(**values)


async def send_renewal_confirmation(
    bot,
    chat_id: int | None,
    *,
    username: str | None,
    plan_title: str | None,
    volume_gb: int | float | None,
    duration_days: int | None,
    expires_at: datetime | None,
    server_type: str = 'xui',
    amount_irt: int | None = None,
) -> None:
    if not bot or chat_id is None:
        return
    await bot.send_message(
        chat_id,
        renewal_confirmation_text(
            username=username,
            plan_title=plan_title,
            volume_gb=volume_gb,
            duration_days=duration_days,
            expires_at=expires_at,
            server_type=server_type,
            amount_irt=amount_irt,
        ),
        reply_markup=renewal_keyboard(),
    )
