from __future__ import annotations

import logging
import traceback
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


def _chunks(text: str, limit: int = 3900) -> list[str]:
    if len(text) <= limit:
        return [text]
    return [text[i:i + limit] for i in range(0, len(text), limit)]


async def report_bot_error(bot: Any, exc: BaseException, context: str = '', event: Any = None) -> None:
    """Send full technical error details only to owner/admin Telegram IDs."""
    try:
        from app.core.config import settings
        admin_ids = list(dict.fromkeys(settings.owner_ids or settings.admin_ids or []))
    except Exception:
        admin_ids = []

    try:
        user = _event_user(event)
        chat = _event_chat(event)
        message = _safe_get(event, 'message') if _safe_get(event, 'message') is not None else event
        callback_data = _safe_get(event, 'data')
        message_text = _safe_get(message, 'text') or _safe_get(message, 'caption')

        user_line = '-'
        if user is not None:
            user_line = (
                f'id={_safe_get(user, "id", "-")} '
                f'username=@{_safe_get(user, "username", "-")} '
                f'full_name={_safe_get(user, "full_name", "-")}'
            )
        chat_line = '-'
        if chat is not None:
            chat_line = f'id={_safe_get(chat, "id", "-")} type={_safe_get(chat, "type", "-")}'

        tb = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        text = (
            '🚨 BOT ERROR REPORT\n'
            '━━━━━━━━━━━━━━━━\n'
            f'⏰ Time UTC: {datetime.utcnow().isoformat()}Z\n'
            f'📍 Context: {context or "-"}\n'
            f'👤 User: {user_line}\n'
            f'💬 Chat: {chat_line}\n'
            f'🔘 Callback: {_clip(callback_data, 500)}\n'
            f'✉️ Message: {_clip(message_text, 700)}\n'
            '━━━━━━━━━━━━━━━━\n'
            f'{tb}'
        )

        if not admin_ids:
            logger.exception('Bot error without configured admin recipients | context=%s', context, exc_info=exc)
            return
        if bot is None:
            logger.exception('Bot error without bot instance | context=%s', context, exc_info=exc)
            return
        for admin_id in admin_ids:
            for part_no, chunk in enumerate(_chunks(text), start=1):
                prefix = f'Part {part_no}\n' if len(text) > 3900 else ''
                try:
                    await bot.send_message(admin_id, prefix + chunk)
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
