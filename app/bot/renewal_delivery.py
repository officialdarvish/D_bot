from __future__ import annotations

from datetime import datetime

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.utils.jalali import fa_date


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
    lines = [
        '✅ تمدید سرویس با موفقیت انجام شد.',
        '',
        '🧾 مشخصات تمدید',
        '━━━━━━━━━━━━━━',
        f'👤 نام سرویس: {username or "-"}',
        f'📦 تعرفه: {plan_title or "-"}',
        f'💾 حجم جدید: {_volume_label(volume_gb)}',
        f'⏳ مدت اعتبار: {_duration_label(duration_days)}',
        f'📅 تاریخ انقضای جدید: {fa_date(expires_at)}',
    ]
    if amount_irt is not None:
        lines.append(f'💰 مبلغ پرداختی: {int(amount_irt or 0):,} تومان')

    lines += [
        '',
        'ℹ️ اطلاعات اتصال، رمز و لینک قبلی شما تغییری نکرده و دوباره ارسال نمی‌شود.',
    ]

    if (server_type or '').lower() == 'xui':
        lines += [
            '',
            '♻️ آموزش بروزرسانی در Happ',
            '1) برنامه Happ را باز کنید.',
            '2) Subscription همین سرویس را پیدا کنید.',
            '3) روی Update / Refresh Subscription بزنید.',
            '4) بعد از پایان بروزرسانی، اتصال را یک‌بار قطع و وصل کنید.',
        ]
    else:
        lines += [
            '',
            '♻️ برای اعمال تمدید OpenVPN، اتصال را یک‌بار قطع و دوباره وصل کنید؛ نیازی به دریافت مجدد پروفایل نیست.',
        ]
    return '\n'.join(lines)


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
