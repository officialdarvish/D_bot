from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

GENERIC_USER_ERROR_TEXT = '❌ خطایی رخ داده\nهرچه زودتر با پشتیبانی در ارتباط باشید.'


def _safe_get(obj: Any, attr: str, default: Any = None) -> Any:
    try:
        return getattr(obj, attr, default)
    except Exception:
        return default


def _event_user(event: Any) -> Any:
    return _safe_get(event, 'from_user')


def _event_chat(event: Any) -> Any:
    chat = _safe_get(event, 'chat')
    if chat is not None:
        return chat
    msg = _safe_get(event, 'message')
    return _safe_get(msg, 'chat')


def _event_bot(event: Any, explicit_bot: Any = None) -> Any:
    if explicit_bot is not None:
        return explicit_bot
    bot = _safe_get(event, 'bot')
    if bot is not None:
        return bot
    msg = _safe_get(event, 'message')
    return _safe_get(msg, 'bot')


def _clip(value: Any, limit: int = 800) -> str:
    text = str(value or '')
    if len(text) > limit:
        return text[:limit] + '...'
    return text


def _context_fa(context: str) -> str:
    """Return a user-friendly Persian area name without leaking internal code labels."""
    raw = str(context or '').strip()
    if any('\u0600' <= ch <= '\u06ff' for ch in raw):
        return raw
    low = raw.lower()
    rules = (
        (('unhandled bot handler exception',), 'پردازش پیام یا دکمه کاربر'),
        (('reseller renew user on panel failed',), 'تمدید سرویس نماینده روی پنل'),
        (('reseller create user failed',), 'ساخت سرویس توسط نماینده'),
        (('background admin approval service provisioning failed',), 'ساخت یا تمدید سرویس پس از تأیید مدیر'),
        (('background admin approval delivery failed',), 'ارسال نتیجه سفارش پس از تأیید مدیر'),
        (('renew', 'reseller'), 'تمدید سرویس نماینده'),
        (('create', 'reseller'), 'ساخت سرویس نماینده'),
        (('test account',), 'ساخت اکانت تست'),
        (('service cleanup',), 'پاک‌سازی سرویس‌های منقضی‌شده'),
        (('backup',), 'پشتیبان‌گیری ربات'),
        (('telegram',), 'ارتباط ربات با تلگرام'),
        (('x-ui',), 'ارتباط با پنل سنایی'),
        (('xui',), 'ارتباط با پنل سنایی'),
    )
    for tokens, label in rules:
        if all(token in low for token in tokens):
            return label
    return 'پردازش داخلی ربات'


def _error_reason_fa(exc: BaseException) -> str:
    """Translate common technical failures into concise Persian admin explanations.

    The raw exception and traceback are intentionally kept only in server logs.
    """
    text = str(exc or '').strip()
    low = f'{type(exc).__name__} {text}'.lower()

    if 'query is too old' in low or 'query id is invalid' in low or 'response timeout expired' in low:
        return 'زمان پاسخ‌گویی به دکمه گذشته است یا دکمه مربوط به یک پیام قدیمی بوده است.'
    if 'message is not modified' in low:
        return 'محتوای پیام تغییری نکرده بود و تلگرام اجازه ویرایش مجدد همان پیام را نداد.'
    if 'message to edit not found' in low or 'message can\'t be edited' in low or 'message cannot be edited' in low:
        return 'پیامی که ربات قصد ویرایش آن را داشت دیگر در دسترس یا قابل ویرایش نبود.'
    if 'bot was blocked' in low or 'forbidden: bot was blocked' in low:
        return 'کاربر ربات را مسدود کرده و امکان ارسال پیام به او وجود ندارد.'
    if 'chat not found' in low or 'user is deactivated' in low:
        return 'گفتگو یا حساب کاربر در تلگرام در دسترس نیست.'
    if 'readtimeout' in low or 'read timeout' in low or 'timed out' in low or 'timeout' in low:
        return 'پاسخ سرویس مقصد در زمان مجاز دریافت نشد. احتمال کندی موقت پنل، شبکه یا سرور وجود دارد.'
    if 'connecttimeout' in low or 'connect timeout' in low or 'connection refused' in low or 'connecterror' in low:
        return 'اتصال به سرویس مقصد برقرار نشد. وضعیت شبکه، پنل و سرور را بررسی کنید.'
    if 'networkerror' in low or 'serverdisconnected' in low or 'connection reset' in low:
        return 'ارتباط شبکه با سرویس مقصد قطع شد یا پاسخ کامل دریافت نشد.'
    if any(token in low for token in ('username already', 'email already', 'duplicate username', 'duplicate email', 'already in use')):
        return 'یوزرنیم یا نام اختصاصی انتخاب‌شده تکراری است و قبلاً استفاده شده است.'
    if 'required inbound memberships are missing' in low or ('inbound' in low and 'missing' in low):
        return 'برخی اینباندهای موردنیاز سرویس روی پنل موجود یا متصل نیستند. تنظیمات اینباند و سرور را بررسی کنید.'
    if 'manual reseller inbound mode has no selected inbound' in low or ('manual' in low and 'inbound' in low and 'selected' in low):
        return 'حالت اینباند نماینده روی دستی است اما هیچ اینباندی برای او انتخاب نشده است.'
    if 'x-ui login failed' in low or 'authentication failed' in low or 'unauthorized' in low:
        return 'ورود ربات به پنل سنایی ناموفق بود. نام کاربری، رمز عبور و آدرس پنل را بررسی کنید.'
    if 'no active 3x-ui inbound' in low:
        return 'هیچ اینباند فعال و معتبری برای ساخت سرویس روی پنل پیدا نشد.'
    if 'insufficient' in low and ('quota' in low or 'volume' in low or 'balance' in low):
        return 'حجم یا اعتبار کافی برای انجام این عملیات وجود ندارد.'
    if 'integrityerror' in low or 'unique constraint' in low or 'duplicate key' in low:
        return 'اطلاعات تکراری باعث شد ثبت داده در پایگاه‌داده انجام نشود.'
    if 'database is locked' in low or 'operationalerror' in low and 'database' in low:
        return 'پایگاه‌داده موقتاً در دسترس نبود یا هم‌زمان در حال استفاده بود.'
    if 'file is too big' in low or 'request entity too large' in low:
        return 'حجم فایل بیشتر از حد مجاز است.'
    if any('\u0600' <= ch <= '\u06ff' for ch in text):
        return _clip(text, 600)

    return 'یک خطای داخلی غیرمنتظره رخ داد. جزئیات فنی کامل در لاگ سرور ثبت شده است.'


def _chat_type_fa(chat_type: Any) -> str:
    return {
        'private': 'خصوصی',
        'group': 'گروه',
        'supergroup': 'سوپرگروه',
        'channel': 'کانال',
    }.get(str(chat_type or '').lower(), 'نامشخص')


def _event_type_fa(event: Any) -> str:
    if _safe_get(event, 'data') is not None:
        return 'فشردن دکمه'
    if _safe_get(event, 'text') is not None or _safe_get(event, 'caption') is not None:
        return 'ارسال پیام'
    if _safe_get(event, 'message') is not None:
        return 'رویداد مربوط به پیام'
    return 'رویداد داخلی ربات'


async def report_bot_error(bot: Any, exc: BaseException, context: str = '', event: Any = None) -> None:
    """Send admins a Persian, non-technical error report; keep raw details in server logs."""
    # Always retain the original technical exception and traceback in server logs.
    try:
        logger.error(
            'Bot error | context=%s',
            context,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
    except Exception:
        logger.error('Bot error | context=%s | %r', context, exc)

    try:
        from app.core.config import settings
        admin_ids = list(dict.fromkeys(settings.owner_ids or settings.admin_ids or []))
    except Exception:
        admin_ids = []

    try:
        user = _event_user(event)
        chat = _event_chat(event)
        message = _safe_get(event, 'message') if _safe_get(event, 'message') is not None else event
        message_text = _safe_get(message, 'text') or _safe_get(message, 'caption')

        user_line = '-'
        if user is not None:
            username = _safe_get(user, 'username', None)
            user_line = (
                f'{_safe_get(user, "id", "-")}'
                + (f' | @{username}' if username else '')
                + (f' | {_safe_get(user, "full_name", "-")}' if _safe_get(user, 'full_name', None) else '')
            )

        chat_line = '-'
        if chat is not None:
            chat_line = f'{_safe_get(chat, "id", "-")} | {_chat_type_fa(_safe_get(chat, "type", None))}'

        text = (
            '🚨 گزارش خطای ربات\n'
            '━━━━━━━━━━━━━━━━\n'
            f'📍 بخش: {_context_fa(context)}\n'
            f'❌ دلیل: {_error_reason_fa(exc)}\n'
            f'👤 کاربر: {user_line}\n'
            f'💬 گفتگو: {chat_line}\n'
            f'🧭 نوع عملیات: {_event_type_fa(event)}\n'
            f'✉️ متن پیام: {_clip(message_text, 450) or "-"}\n'
            f'🕒 زمان ثبت: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n'
            '━━━━━━━━━━━━━━━━\n'
            'ℹ️ جزئیات فنی و مسیر اجرای خطا فقط در لاگ سرور ذخیره شده است.'
        )

        if not admin_ids:
            return
        if bot is None:
            return
        for admin_id in admin_ids:
            try:
                await bot.send_message(admin_id, _clip(text, 3600))
            except Exception:
                logger.exception('Failed to send bot error report to admin_id=%s', admin_id)
    except Exception:
        logger.exception('Failed to report bot error')


async def show_generic_error(event: Any, reply_markup: Any = None) -> None:
    """Show a safe generic error to the end user without technical details."""
    try:
        from app.bot.utils import ui_message, ui_callback_message
        if _safe_get(event, 'message') is not None and _safe_get(event, 'data') is not None:
            try:
                await event.answer('خطایی رخ داده؛ لطفاً با پشتیبانی در ارتباط باشید.', show_alert=True)
            except Exception:
                pass
            await ui_callback_message(event, GENERIC_USER_ERROR_TEXT, reply_markup=reply_markup)
            return
        if _safe_get(event, 'chat') is not None:
            await ui_message(event, GENERIC_USER_ERROR_TEXT, reply_markup=reply_markup)
            return
        bot = _event_bot(event)
        chat = _event_chat(event)
        if bot is not None and chat is not None:
            await bot.send_message(chat.id, GENERIC_USER_ERROR_TEXT, reply_markup=reply_markup)
    except Exception:
        logger.exception('Failed to show generic error to user')


async def handle_user_facing_error(event: Any, exc: BaseException, context: str = '', reply_markup: Any = None, bot: Any = None) -> None:
    await report_bot_error(_event_bot(event, bot), exc, context=context, event=event)
    await show_generic_error(event, reply_markup=reply_markup)
