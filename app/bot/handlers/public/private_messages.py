from __future__ import annotations

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton

from app.bot.keyboards.common import private_message_user_actions, private_message_admin_actions
from app.bot.states.public_states import PrivateMessageReply
from app.bot.utils import send_single_message, ui_message
from app.core.roles import is_owner
from app.bot.error_reporting import report_bot_error

router = Router()


def _reply_prompt_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ خاتمه گفتگو', callback_data='private_chat:end')],
    ])


@router.callback_query(F.data == 'private_chat:end')
async def private_chat_end(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    # Reuse the canonical home renderer so reseller/admin/test-button visibility
    # stays identical to /start and the normal Home button.
    from app.bot.handlers.start import _open_main_menu_from_callback
    await _open_main_menu_from_callback(callback, state, force_new_message=True)


@router.callback_query(F.data.startswith('private_chat:reply:'))
async def private_chat_reply_start(callback: CallbackQuery, state: FSMContext):
    try:
        admin_id = int((callback.data or '').rsplit(':', 1)[-1])
    except (TypeError, ValueError):
        await callback.answer('این گفتگو معتبر نیست.', show_alert=True)
        return

    # Never let a forged callback forward messages to an arbitrary Telegram ID.
    if admin_id <= 0 or not is_owner(admin_id):
        await callback.answer('مدیر این گفتگو در دسترس نیست.', show_alert=True)
        return

    await state.clear()
    await state.update_data(private_message_admin_id=admin_id)
    await state.set_state(PrivateMessageReply.message)
    await send_single_message(
        callback.bot,
        callback.from_user.id,
        '✍️ پاسخ خود را ارسال کنید.\n\nمتن، عکس، ویدیو و فایل قابل ارسال است. برای خروج از گفتگو دکمه زیر را بزنید.',
        reply_markup=_reply_prompt_keyboard(),
    )
    await callback.answer()


@router.message(PrivateMessageReply.message)
async def private_chat_reply_send(message: Message, state: FSMContext):
    data = await state.get_data()
    try:
        admin_id = int(data.get('private_message_admin_id') or 0)
    except (TypeError, ValueError):
        admin_id = 0

    if admin_id <= 0 or not is_owner(admin_id):
        await state.clear()
        await ui_message(
            message,
            '❌ این گفتگو دیگر معتبر نیست.',
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text='🏠 صفحه اصلی', callback_data='home:main')],
            ]),
        )
        return

    username = f'@{message.from_user.username}' if message.from_user.username else 'بدون یوزرنیم'
    full_name = message.from_user.full_name or 'بدون نام'
    header = (
        '📩 پاسخ کاربر به پیام خصوصی\n\n'
        f'👤 {full_name}\n'
        f'🆔 {username}\n'
        f'🔢 User ID: {message.from_user.id}'
    )

    try:
        await message.bot.send_message(admin_id, header)
        await message.bot.copy_message(
            chat_id=admin_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
            reply_markup=private_message_admin_actions(message.from_user.id),
        )
    except Exception as exc:
        await report_bot_error(
            message.bot,
            exc,
            context=f'Private message user reply delivery failed admin_id={admin_id} user_id={message.from_user.id}',
            event=message,
        )
        await ui_message(
            message,
            '❌ ارسال پاسخ ناموفق بود. دوباره تلاش کنید یا گفتگو را خاتمه دهید.',
            reply_markup=private_message_user_actions(admin_id),
        )
        return

    await state.clear()
    await ui_message(
        message,
        '✅ پاسخ شما برای مدیریت ارسال شد.\n\nمی‌توانید دوباره پاسخ بدهید یا گفتگو را خاتمه دهید.',
        reply_markup=private_message_user_actions(admin_id),
    )
