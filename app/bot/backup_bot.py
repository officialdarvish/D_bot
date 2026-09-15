from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.core.config import settings
from app.database.defaults import get_setting_value, set_setting_value
from app.services.backup_config import BACKUP_INTERVALS, BACKUP_INTERVAL_LABELS, BACKUP_SECONDARY_BOT_TOKEN_KEY, decrypt_secondary_bot_token

logger = logging.getLogger(__name__)


def _owner(user_id: int) -> bool:
    return user_id in settings.owner_ids


async def _current_interval() -> int:
    raw = await get_setting_value('backup_interval_minutes', '1440')
    try:
        value = int(raw)
    except Exception:
        value = 1440
    return value if value in BACKUP_INTERVALS else 1440


async def _menu_markup() -> InlineKeyboardMarkup:
    interval = await _current_interval()
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='📦 دریافت بک آپ همین لحظه', callback_data='backupbot:now')],
        [InlineKeyboardButton(text=f'⏱ تنظیم ساعت و دوره دریافت بک آپ ({BACKUP_INTERVAL_LABELS.get(interval, interval)})', callback_data='backupbot:interval')],
    ])


async def _send_menu(target: Message | CallbackQuery, note: str = '') -> None:
    interval = await _current_interval()
    text = (
        '🛡 D BOT Backup Bot\n\n'
        f'چرخه فعلی: {BACKUP_INTERVAL_LABELS.get(interval, str(interval))}\n'
        'این تنظیمات مستقیماً با Backup Settings وب‌پنل سینک هستند.'
    )
    if note:
        text = note + '\n\n' + text
    markup = await _menu_markup()
    if isinstance(target, CallbackQuery):
        try:
            await target.message.edit_text(text, reply_markup=markup)
        except Exception:
            await target.message.answer(text, reply_markup=markup)
        await target.answer()
    else:
        await target.answer(text, reply_markup=markup)


def build_backup_router() -> Router:
    router = Router(name='dbot-secondary-backup-bot')

    @router.message(CommandStart())
    async def backup_start(message: Message):
        if not _owner(message.from_user.id):
            await message.answer('⛔️ دسترسی فقط برای مدیر اصلی D BOT فعال است.')
            return
        await set_setting_value('backup_secondary_owner_chat_id', str(message.from_user.id))
        await _send_menu(message)

    @router.callback_query(F.data == 'backupbot:now')
    async def backup_now(callback: CallbackQuery):
        if not _owner(callback.from_user.id):
            await callback.answer('دسترسی ندارید.', show_alert=True)
            return
        await callback.answer('در حال ساخت بکاپ...')
        path = ''
        try:
            from app.api.admin_web import _write_backup_file
            path = await _write_backup_file()
            stamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
            await callback.bot.send_document(
                callback.from_user.id,
                FSInputFile(path, filename=f'dbot_backup_{stamp}.json'),
                caption='📦 D BOT portable backup v4\n✅ بکاپ جدید همین لحظه ساخته شد.',
            )
            await set_setting_value('backup_last_backup_status', 'ok')
            await set_setting_value('backup_last_backup_message', 'Manual backup sent from secondary backup bot')
            await set_setting_value('backup_last_backup_at', datetime.utcnow().isoformat())
        except Exception as exc:
            logger.exception('Secondary backup bot manual backup failed')
            await callback.message.answer(f'❌ ساخت یا ارسال بکاپ ناموفق بود:\n{exc}')
        finally:
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass

    @router.callback_query(F.data == 'backupbot:interval')
    async def choose_interval(callback: CallbackQuery):
        if not _owner(callback.from_user.id):
            await callback.answer('دسترسی ندارید.', show_alert=True)
            return
        rows = []
        labels = {60: '1 ساعت', 180: '3 ساعت', 360: '6 ساعت', 720: '12 ساعت', 1440: '24 ساعت', 10080: '7 روز'}
        pair = []
        for value in BACKUP_INTERVALS:
            pair.append(InlineKeyboardButton(text=labels[value], callback_data=f'backupbot:set:{value}'))
            if len(pair) == 2:
                rows.append(pair); pair = []
        if pair:
            rows.append(pair)
        rows.append([InlineKeyboardButton(text='⬅️ برگشت', callback_data='backupbot:menu')])
        await callback.message.edit_text('چرخه دریافت بکاپ را انتخاب کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        await callback.answer()

    @router.callback_query(F.data.startswith('backupbot:set:'))
    async def set_interval(callback: CallbackQuery):
        if not _owner(callback.from_user.id):
            await callback.answer('دسترسی ندارید.', show_alert=True)
            return
        try:
            interval = int(callback.data.rsplit(':', 1)[-1])
        except Exception:
            interval = 0
        if interval not in BACKUP_INTERVALS:
            await callback.answer('چرخه نامعتبر است.', show_alert=True)
            return
        now = datetime.utcnow().isoformat()
        await set_setting_value('backup_interval_minutes', str(interval))
        await set_setting_value('backup_schedule_enabled', '1')
        await set_setting_value('backup_sender_mode', 'secondary')
        await set_setting_value('backup_destination', 'bot')
        await set_setting_value('backup_chat_id', str(callback.from_user.id))
        await set_setting_value('backup_target_input', str(callback.from_user.id))
        await set_setting_value('backup_secondary_owner_chat_id', str(callback.from_user.id))
        await set_setting_value('backup_schedule_anchor_at', now)
        await _send_menu(callback, '✅ چرخه بکاپ ذخیره و با وب‌پنل همگام شد.')

    @router.callback_query(F.data == 'backupbot:menu')
    async def back_menu(callback: CallbackQuery):
        if not _owner(callback.from_user.id):
            await callback.answer('دسترسی ندارید.', show_alert=True)
            return
        await _send_menu(callback)

    return router


async def _read_secondary_token() -> str:
    encrypted = await get_setting_value(BACKUP_SECONDARY_BOT_TOKEN_KEY, '')
    token = decrypt_secondary_bot_token(encrypted)
    if token:
        return token
    # Migration from older builds only.
    return (await get_setting_value('backup_bot_token', '')).strip()


async def backup_bot_supervisor(stop_event: asyncio.Event) -> None:
    """Keep the optional second Telegram bot alive and hot-reload its token."""
    active_token = ''
    bot: Bot | None = None
    polling_task: asyncio.Task | None = None

    async def stop_active() -> None:
        nonlocal bot, polling_task, active_token
        if polling_task:
            polling_task.cancel()
            try:
                await polling_task
            except BaseException:
                pass
            polling_task = None
        if bot:
            try:
                await bot.session.close()
            except Exception:
                pass
            bot = None
        active_token = ''

    try:
        while not stop_event.is_set():
            token = await _read_secondary_token()
            if token != active_token:
                await stop_active()
                if token:
                    try:
                        bot = Bot(token=token)
                        await bot.delete_webhook(drop_pending_updates=True)
                        dp = Dispatcher()
                        dp.include_router(build_backup_router())
                        polling_task = asyncio.create_task(dp.start_polling(bot, handle_signals=False))
                        active_token = token
                        logger.info('Secondary backup bot polling started')
                    except Exception:
                        logger.exception('Could not start secondary backup bot')
                        await stop_active()
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=15)
            except asyncio.TimeoutError:
                pass
    finally:
        await stop_active()
