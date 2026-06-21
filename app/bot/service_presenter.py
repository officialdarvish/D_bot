from __future__ import annotations

from aiogram.types import FSInputFile

from app.bot.qr_card import make_qr_card


def _format_gb(value) -> str:
    try:
        n = float(value or 0)
    except Exception:
        n = 0.0
    return str(int(n)) if n.is_integer() else f'{n:g}'


def build_service_caption(*, username: str, title: str, volume_gb, duration_days, sub_link: str | None, is_test: bool = False) -> str:
    header = '🎁 اکانت تست شما با موفقیت ساخته شد' if is_test else '🎉 سرویس شما با موفقیت ساخته شد'
    text = (
        f'{header}\n'
        f'━━━━━━━━━━━━━━\n'
        f'👤 نام کانفیگ: <code>{username}</code>\n'
        f'📦 پلن: <b>{title}</b>\n'
        f'💾 حجم: <b>{_format_gb(volume_gb)} گیگ</b>\n'
        f'⏳ مدت: <b>{duration_days} روز</b>\n'
        f'━━━━━━━━━━━━━━\n'
    )
    if sub_link:
        text += (
            f'🔗 لینک ساب‌اسکریپشن:\n<code>{sub_link}</code>\n\n'
            f'✅ آموزش Happ:\n'
            f'1) برنامه Happ را باز کنید.\n'
            f'2) روی + بزنید.\n'
            f'3) Import / Subscription را انتخاب کنید.\n'
            f'4) لینک بالا را وارد و ذخیره کنید.\n\n'
            f'✅ آموزش V2rayNG:\n'
            f'1) لینک بالا را کپی کنید.\n'
            f'2) داخل V2rayNG روی + بزنید.\n'
            f'3) Subscription group setting را باز کنید.\n'
            f'4) لینک را اضافه کنید و Update subscription را بزنید.'
        )
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
):
    caption = build_service_caption(
        username=username,
        title=title,
        volume_gb=volume_gb,
        duration_days=duration_days,
        sub_link=sub_link,
        is_test=is_test,
    )

    # The delivery message should not show inline navigation buttons.
    # User requested removing: home, connection guide, refresh link.
    # Delivery card must be clean: no inline buttons below QR.
    markup = None

    if sub_link:
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
