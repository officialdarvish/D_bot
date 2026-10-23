from __future__ import annotations

from html import escape

import os
from qrcode.exceptions import DataOverflowError

from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton

from app.bot.qr_card import make_qr_card
from app.bot.config_delivery import send_config_photo, send_config_text


# Keep this navigation button on every delivered config (QR, text, OpenVPN).
# Unlike normal UI callbacks, restart:start is explicitly allowed for old
# messages by FreshCallbackOnlyMiddleware, so customers can restart anytime.
RESTART_BOT_LABEL = '🔄 شروع مجدد ربات'
RESTART_BOT_CALLBACK = 'restart:start'


def config_restart_keyboard(reply_markup: InlineKeyboardMarkup | None = None) -> InlineKeyboardMarkup:
    """Preserve existing service controls and append one full-width restart row.

    Never mutate a caller-supplied keyboard: some flows reuse the same markup.
    """
    rows = [list(row) for row in (getattr(reply_markup, 'inline_keyboard', None) or [])]
    if not any(getattr(button, 'callback_data', None) == RESTART_BOT_CALLBACK
               for row in rows for button in row):
        rows.append([InlineKeyboardButton(text=RESTART_BOT_LABEL, callback_data=RESTART_BOT_CALLBACK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


SERVICE_CARD_XUI_TEXT = (
    '━━━━━━━━━━━━━━\n'
    'سرویس شما با موفقیت ساخته شد\n'
    '━━━━━━━━━━━━━━\n'
    '👤 نام کاربری: <code>{username}</code>\n'
    '📦 پلن: <b>{title}</b>\n'
    '💾 حجم: <b>{volume_gb} گیگ</b>\n'
    '⏳ مدت: <b>{duration_days} روز</b>\n\n'
    '🔗 لینک ساب‌اسکریپشن:\n<code>{sub_link}</code>\n\n'
    '<b>⚠️ فقط و فقط برنامه Happ مورد تایید ما هستش.</b>\n'
    '<b>اگر از برنامه دیگری استفاده می‌کنید، هرچه زودتر Happ را از App Store یا Google Play دانلود و نصب کنید.</b>\n\n'
    '<b>در غیر این صورت، وصل نشدن سرورها مسئولیتش با خود شماست و در پشتیبانی خدماتی ارائه نمی‌شود.</b>\n\n'
    '✅ مراحل اضافه کردن در Happ:\n'
    '1) برنامه Happ را باز کنید.\n'
    '2) روی دکمه + بزنید.\n'
    '3) گزینه Import / Subscription را انتخاب کنید.\n'
    '4) لینک بالا را Paste کنید.\n'
    '5) ذخیره کنید و سرورها را از داخل Happ انتخاب کنید.\n\n'
    '♻️ بروزرسانی لینک در Happ هر ۱۲ ساعت:\n'
    '1) وارد Happ شوید.\n'
    '2) روی Subscription همین سرویس بزنید.\n'
    '3) گزینه Update / Refresh Subscription را بزنید.\n'
    '4) بعد از بروزرسانی، دوباره یکی از سرورها را انتخاب و وصل شوید.'
)

TEST_SERVICE_CARD_XUI_TEXT = SERVICE_CARD_XUI_TEXT.replace(
    'سرویس شما با موفقیت ساخته شد',
    '🎁 اکانت تست شما با موفقیت ساخته شد',
)

SERVICE_CARD_BASIC_TEXT = (
    '━━━━━━━━━━━━━━\n'
    'سرویس شما با موفقیت ساخته شد\n'
    '━━━━━━━━━━━━━━\n'
    '👤 نام کاربری: <code>{username}</code>\n'
    '📦 پلن: <b>{title}</b>\n'
    '💾 حجم: <b>{volume_gb} گیگ</b>\n'
    '⏳ مدت: <b>{duration_days} روز</b>\n'
)

TEST_SERVICE_CARD_BASIC_TEXT = (
    '━━━━━━━━━━━━━━\n'
    '🎁 اکانت تست شما با موفقیت ساخته شد\n'
    '━━━━━━━━━━━━━━\n'
    '👤 نام کاربری: <code>{username}</code>\n'
    '📦 پلن: <b>{title}</b>\n'
    '💾 حجم: <b>{volume_gb} گیگ</b>\n'
    '⏳ مدت: <b>{duration_days} روز</b>\n'
)

SERVICE_CARD_MIKROTIK_TEXT = (
    '━━━━━━━━━━━━━━\n'
    'سرویس شما با موفقیت ساخته شد\n'
    '━━━━━━━━━━━━━━\n'
    '👤 نام کاربری: <code>{username}</code>\n'
    '📦 پلن: <b>{title}</b>\n'
    '💾 حجم: <b>{volume_gb} گیگ</b>\n'
    '⏳ مدت: <b>{duration_days} روز</b>\n'
    '{password_line}\n'
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
    '   Account : <code>{username}</code>\n'
    '   Password : <code>{password}</code>\n'
    '6) server : <code>{l2tp_server}</code>\n'
    '7) secret : <code>{l2tp_ipsec_secret}</code>'
)

TEST_SERVICE_CARD_MIKROTIK_TEXT = SERVICE_CARD_MIKROTIK_TEXT.replace(
    'سرویس شما با موفقیت ساخته شد',
    '🎁 اکانت تست شما با موفقیت ساخته شد',
)


def _format_gb(value) -> str:
    try:
        n = float(value or 0)
    except Exception:
        n = 0.0
    return str(int(n)) if n.is_integer() else f'{n:g}'


def mikrotik_guide_text(l2tp_server: str | None = None, l2tp_ipsec_secret: str | None = None, username: str | None = None, password: str | None = None) -> str:
    server = (l2tp_server or 'vpn.example.com').strip()
    secret = (l2tp_ipsec_secret or 'CHANGE_ME_IPSEC_SECRET').strip()
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
    volume_label = _format_gb(volume_gb)
    duration_label = duration_days
    is_mikrotik = (server_type or '').lower() == 'mikrotik'

    if is_mikrotik:
        template = TEST_SERVICE_CARD_MIKROTIK_TEXT if is_test else SERVICE_CARD_MIKROTIK_TEXT
        pwd = (password or '').strip() or 'Password سرویس'
        password_line = f'🔐 رمز عبور: <code>{password}</code>\n' if password else ''
        return template.format(
            username=username,
            title=title,
            volume_gb=volume_label,
            duration_days=duration_label,
            password_line=password_line,
            password=pwd,
            l2tp_server=(l2tp_server or 'vpn.example.com').strip(),
            l2tp_ipsec_secret=(l2tp_ipsec_secret or 'CHANGE_ME_IPSEC_SECRET').strip(),
        )

    if sub_link:
        template = TEST_SERVICE_CARD_XUI_TEXT if is_test else SERVICE_CARD_XUI_TEXT
        return template.format(
            username=username,
            title=title,
            volume_gb=volume_label,
            duration_days=duration_label,
            sub_link=escape(sub_link),
        )

    template = TEST_SERVICE_CARD_BASIC_TEXT if is_test else SERVICE_CARD_BASIC_TEXT
    return template.format(
        username=username,
        title=title,
        volume_gb=volume_label,
        duration_days=duration_label,
    )


async def build_delivery_caption(**values) -> str:
    from app.services.delivery_templates import selected_caption
    selected = await selected_caption(**values)
    return selected if selected is not None else build_service_caption(**values)


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
    allow_happ: bool = False,
    reply_markup=None,
    service_id: int | None = None,
    server_type: str = 'xui',
    password: str | None = None,
    l2tp_server: str | None = None,
    l2tp_ipsec_secret: str | None = None,
):
    # The caller must explicitly identify an ordinary retail delivery. Other
    # entry points (trial, reseller, Convert) always receive the normal link.
    happ_delivery_failed = False
    if (server_type or '').lower() == 'xui' and service_id and allow_happ and not is_test:
        from app.database.session import SessionLocal
        from app.database.models import ClientService, Server, Plan
        from app.services.xui_service import XuiService
        async with SessionLocal() as db:
            svc = await db.get(ClientService, int(service_id))
            srv = await db.get(Server, svc.server_id) if svc and svc.server_id else None
            plan = await db.get(Plan, svc.plan_id) if svc and svc.plan_id else None
            if await XuiService.service_happ_enabled(db, srv, svc, plan):
                sub_link = await XuiService().resolve_service_subscription(db, srv, svc, plan, refresh_happ=True)
                await db.commit()
                happ_delivery_failed = not bool(sub_link)
            elif isinstance(sub_link, str) and sub_link.startswith('happ://crypt5/'):
                # E.g. older server-wide settings: never carry encrypted links
                # into non-retail delivery after migrating to per-plan policy.
                sub_link = None
    elif isinstance(sub_link, str) and sub_link.startswith('happ://crypt5/'):
        # Do not forward legacy Happ links from an unqualified path.
        sub_link = None
    if (server_type or '').lower() == 'xui' and service_id and not happ_delivery_failed and not sub_link:
        # The old global server preference may have persisted only a Happ URI.
        # Recover the regular link for a plan that no longer requests Happ.
        from app.database.session import SessionLocal
        from app.database.models import ClientService, Server
        from app.services.xui_service import XuiService
        async with SessionLocal() as db:
            svc = await db.get(ClientService, int(service_id))
            srv = await db.get(Server, svc.server_id) if svc and svc.server_id else None
            if srv and svc:
                sub_link = await XuiService().normal_subscription_link(srv, svc.xui_email or svc.client_username)
                if sub_link is not None and sub_link != svc.sub_link:
                    svc.sub_link = sub_link
                    await db.commit()
    caption = await build_delivery_caption(
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

    if happ_delivery_failed:
        caption = type(caption)(caption + ('\n\n⚠️ لینک اختصاصی Happ هنوز از پنل سنایی دریافت نشده است. '
                    'لطفاً کمی بعد از «کانفیگ‌های من» تلاش کنید یا با پشتیبانی تماس بگیرید.'))

    # Respect caller-provided controls (for example the persistent Home
    # button used by admin-created services). MikroTik also needs its profile
    # action, so merge both keyboards instead of silently replacing one.
    markup = reply_markup
    if (server_type or '').lower() == 'mikrotik' and service_id:
        rows = [[InlineKeyboardButton(text='📥 دریافت پروفایل سرور', callback_data=f'svc:profile:{service_id}')]]
        if reply_markup is not None:
            rows.extend(list(getattr(reply_markup, 'inline_keyboard', []) or []))
        markup = InlineKeyboardMarkup(inline_keyboard=rows)

    # Covers customer purchase, reseller deliveries, regenerated links,
    # converted plans and test cards through the same delivery entry point.
    markup = config_restart_keyboard(markup)

    if sub_link and (server_type or '').lower() != 'mikrotik':
        try:
            from app.services.user_content import background_bytes
            artwork = await background_bytes()
            qr_path = make_qr_card(
                sub_link,
                background_bytes=artwork,
                title='VPN BOT',
                subtitle='VPN',
                username=username,
                plan_title=title,
                volume_gb=volume_gb,
                duration_days=duration_days,
                server_name='Multi Location',
            )
        except DataOverflowError:
            await send_config_text(bot, chat_id, caption, reply_markup=markup)
            return

        try:
            await send_config_photo(bot, chat_id, FSInputFile(qr_path), caption, reply_markup=markup)
        finally:
            try:
                os.unlink(qr_path)
            except OSError:
                pass
    else:
        await send_config_text(bot, chat_id, caption, reply_markup=markup)
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
