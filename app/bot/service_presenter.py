from __future__ import annotations

from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton

from app.bot.qr_card import make_qr_card


def _format_gb(value) -> str:
    try:
        n = float(value or 0)
    except Exception:
        n = 0.0
    return str(int(n)) if n.is_integer() else f'{n:g}'


def mikrotik_guide_text() -> str:
    return (
        '<b>⚠️ فقط و فقط برنامه OpenVPN برای پروفایل OVPN و اتصال L2TP از Settings آیفون مورد تایید ما هستش.</b>\n'
        '<b>اگر از برنامه دیگری استفاده می‌کنید، مسئولیت وصل نشدن با خود شماست و پشتیبانی خدماتی ارائه نمی‌دهد.</b>\n\n'
        '📥 برای OpenVPN روی دکمه «دریافت پروفایل سرور» بزنید و فایل OVPN را داخل OpenVPN Import کنید.\n\n'
        '📱 راهنمای L2TP آیفون:\n'
        '1) Settings را باز کنید.\n'
        '2) وارد VPN & Device Management شوید.\n'
        '3) Add VPN Configuration را بزنید.\n'
        '4) Type را روی L2TP بگذارید.\n'
        '5) Server، Account و Password را وارد کنید.\n'
        '6) اگر Secret از طرف پشتیبانی داده شده، در Secret وارد کنید و Save بزنید.\n\n'
        '♻️ اگر پروفایل OpenVPN تغییر کرد، از همین دکمه دوباره فایل پروفایل سرور را دریافت کنید.'
    )


def happ_guide_text(sub_link: str) -> str:
    return (
        f'🔗 لینک ساب‌اسکریپشن:\n<code>{sub_link}</code>\n\n'
        f'<b>⚠️ فقط و فقط برنامه Happ مورد تایید ما هستش.</b>\n'
        f'<b>اگر از برنامه دیگری استفاده می‌کنید، هرچه زودتر Happ را از App Store یا Google Play دانلود و نصب کنید.</b>\n\n'
        f'<b>در غیر این صورت، وصل نشدن سرورها مسئولیتش با خود شماست و در پشتیبانی خدماتی ارائه نمی‌شود.</b>\n\n'
        f'✅ مراحل اضافه کردن در Happ:\n'
        f'1) برنامه Happ را باز کنید.\n'
        f'2) روی دکمه + بزنید.\n'
        f'3) گزینه Import / Subscription را انتخاب کنید.\n'
        f'4) لینک بالا را Paste کنید.\n'
        f'5) ذخیره کنید و سرورها را از داخل Happ انتخاب کنید.\n\n'
        f'♻️ بروزرسانی لینک در Happ هر ۱۲ ساعت:\n'
        f'1) وارد Happ شوید.\n'
        f'2) روی Subscription همین سرویس بزنید.\n'
        f'3) گزینه Update / Refresh Subscription را بزنید.\n'
        f'4) بعد از بروزرسانی، دوباره یکی از سرورها را انتخاب و وصل شوید.'
    )


def build_service_caption(*, username: str, title: str, volume_gb, duration_days, sub_link: str | None, is_test: bool = False, server_type: str = 'xui', password: str | None = None) -> str:
    header = '🎁 اکانت تست شما با موفقیت ساخته شد' if is_test else '🎉 سرویس شما با موفقیت ساخته شد'
    text = (
        f'{header}\n'
        f'━━━━━━━━━━━━━━\n'
        f'👤 نام کاربری: <code>{username}</code>\n'
        f'📦 پلن: <b>{title}</b>\n'
        f'💾 حجم: <b>{_format_gb(volume_gb)} گیگ</b>\n'
        f'⏳ مدت: <b>{duration_days} روز</b>\n'
    )
    if password:
        text += f'🔐 رمز عبور: <code>{password}</code>\n'
    text += '━━━━━━━━━━━━━━\n'
    if (server_type or '').lower() == 'mikrotik':
        text += mikrotik_guide_text()
    elif sub_link:
        text += happ_guide_text(sub_link)
    return text


async def send_service_info(
    bot,
    chat_id,
    username: str,
    title: str,
    volume_gb,
    duration_days,
    sub_link: str | None,
    *,
    is_test: bool = False,
    reply_markup=None,
    service_id: int | None = None,
    server_type: str = 'xui',
    password: str | None = None,
):
    caption = build_service_caption(
        username=username,
        title=title,
        volume_gb=volume_gb,
        duration_days=duration_days,
        sub_link=sub_link,
        is_test=is_test,
        server_type=server_type,
        password=password,
    )

    markup = None
    if (server_type or '').lower() == 'mikrotik' and service_id:
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='📥 دریافت پروفایل سرور', callback_data=f'svc:profile:{service_id}')]
        ])

    if sub_link and (server_type or '').lower() != 'mikrotik':
        qr_path = make_qr_card(
            sub_link,
            title='VPN BOT',
            subtitle='VPN',
            username=username,
            plan_title=title,
            volume_gb=volume_gb,
            duration_days=duration_days,
            server_name='Multi Location',
        )
        await bot.send_photo(chat_id, FSInputFile(qr_path), caption=caption, parse_mode='HTML', reply_markup=markup)
    else:
        await bot.send_message(chat_id, caption, parse_mode='HTML', reply_markup=markup)
