from __future__ import annotations

from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton

from app.bot.qr_card import make_qr_card


def _format_gb(value) -> str:
    try:
        n = float(value or 0)
    except Exception:
        n = 0.0
    return str(int(n)) if n.is_integer() else f'{n:g}'


def mikrotik_guide_text(l2tp_server: str | None = None, l2tp_ipsec_secret: str | None = None, username: str | None = None, password: str | None = None) -> str:
    server = (l2tp_server or 'de.rgiftshop.ir').strip()
    secret = (l2tp_ipsec_secret or '123456789').strip()
    account = (username or '').strip() or 'Username سرویس'
    pwd = (password or '').strip() or 'Password سرویس'
    return (
        '📲 <b>آموزش اضافه کردن کانفیگ OpenVPN</b>\n\n'
        '1️⃣ برنامه <b>OpenVPN Connect</b> رو باز کنید\n'
        '2️⃣ روی گزینه <b>Import Profile</b> یا <b>Upload File</b> بزنید\n'
        '3️⃣ وارد بخش <b>File</b> بشید\n'
        '4️⃣ فایل کانفیگ با فرمت <code>.ovpn</code> رو انتخاب کنید\n'
        '5️⃣ روی گزینه <b>Add</b> بزنید\n'
        '6️⃣ تیک گزینه <b>Save Password</b> رو فعال کنید\n'
        '7️⃣ اطلاعات <b>Username / Password / Private Key</b> رو وارد کنید\n'
        '8️⃣ دکمه اتصال رو فعال کنید ✅\n\n'
        '📱 <b>راهنمای اضافه کردن برای آیفون - L2TP</b>\n'
        '1) Settings را باز کنید.\n'
        '2) وارد VPN & Device Management شوید.\n'
        '3) Add VPN Configuration را بزنید.\n'
        '4) Type را روی L2TP بگذارید.\n'
        '5) اطلاعات زیر را وارد کنید:\n'
        f'   Account : <code>{account}</code>\n'
        f'   Password : <code>{pwd}</code>\n'
        f'6) server : <code>{server}</code>\n'
        f'7) secret : <code>{secret}</code>'
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


def build_service_caption(*, username: str, title: str, volume_gb, duration_days, sub_link: str | None, is_test: bool = False, server_type: str = 'xui', password: str | None = None, l2tp_server: str | None = None, l2tp_ipsec_secret: str | None = None) -> str:
    header = '🎁 اکانت تست شما با موفقیت ساخته شد' if is_test else 'سرویس شما با موفقیت ساخته شد'
    text = (
        f'━━━━━━━━━━━━━━\n'
        f'{header}\n'
        f'━━━━━━━━━━━━━━\n'
        f'👤 نام کاربری: <code>{username}</code>\n'
        f'📦 پلن: <b>{title}</b>\n'
        f'💾 حجم: <b>{_format_gb(volume_gb)} گیگ</b>\n'
        f'⏳ مدت: <b>{duration_days} روز</b>\n'
    )
    is_mikrotik = (server_type or '').lower() == 'mikrotik'
    if password and is_mikrotik:
        text += f'🔐 رمز عبور: <code>{password}</code>\n'
    if is_mikrotik:
        text += '\n'
        text += mikrotik_guide_text(l2tp_server, l2tp_ipsec_secret, username, password)
    elif sub_link:
        text += '\n'
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
    l2tp_server: str | None = None,
    l2tp_ipsec_secret: str | None = None,
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
        l2tp_server=l2tp_server,
        l2tp_ipsec_secret=l2tp_ipsec_secret,
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
        if (server_type or '').lower() == 'mikrotik' and service_id:
            try:
                from app.bot.profile_delivery import send_openvpn_profile_document
                await send_openvpn_profile_document(
                    bot,
                    chat_id,
                    int(service_id),
                    caption=None,
                )
            except Exception:
                pass
