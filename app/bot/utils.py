from aiogram.types import CallbackQuery, ReplyKeyboardRemove, Message
from aiogram.exceptions import TelegramBadRequest

# One active inline page per chat. Normal navigation should edit this message
# instead of sending a new one. Real outbound answers/notifications can still
# use bot.send_message/send_photo directly.
_ACTIVE_UI_MESSAGES: dict[int, int] = {}


def remember_ui_message(chat_id: int | str, message_id: int | str | None) -> None:
    if message_id is None:
        return
    try:
        _ACTIVE_UI_MESSAGES[int(chat_id)] = int(message_id)
    except Exception:
        pass


def get_ui_message_id(chat_id: int | str) -> int | None:
    try:
        return _ACTIVE_UI_MESSAGES.get(int(chat_id))
    except Exception:
        return None


def forget_ui_message(chat_id: int | str) -> None:
    try:
        _ACTIVE_UI_MESSAGES.pop(int(chat_id), None)
    except Exception:
        pass


async def _force_reply_markup(bot, chat_id: int | str, message_id: int | str, reply_markup=None) -> None:
    """Telegram sometimes keeps the previous inline keyboard when a helper falls
    back between edit/send paths. This explicitly replaces/removes the keyboard
    after changing a page, so each menu owns its own buttons.
    """
    try:
        await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if 'message is not modified' in str(e).lower():
            return
    except Exception:
        return


async def edit_or_answer(callback: CallbackQuery, text: str, reply_markup=None, **kwargs):
    """Edit the current inline page; create a new one only if Telegram cannot edit it.

    Important: always replace the inline keyboard too. This prevents reseller/admin
    pages from showing the previous page buttons while only the text changes.
    """
    try:
        msg = await callback.message.edit_text(text, reply_markup=reply_markup, **kwargs)
        remember_ui_message(callback.message.chat.id, msg.message_id)
        await _force_reply_markup(callback.message.bot, callback.message.chat.id, msg.message_id, reply_markup)
        return msg
    except TelegramBadRequest as e:
        low = str(e).lower()
        if 'message is not modified' in low:
            remember_ui_message(callback.message.chat.id, callback.message.message_id)
            await _force_reply_markup(callback.message.bot, callback.message.chat.id, callback.message.message_id, reply_markup)
            return callback.message
        # If this is a media message, update its caption instead of sending a new
        # page. This keeps navigation such as reseller menu on the same Telegram
        # message after a QR/photo delivery card.
        if getattr(callback.message, 'photo', None) or getattr(callback.message, 'document', None) or getattr(callback.message, 'video', None):
            try:
                msg = await callback.message.edit_caption(caption=text, reply_markup=reply_markup, **kwargs)
                remember_ui_message(callback.message.chat.id, callback.message.message_id)
                await _force_reply_markup(callback.message.bot, callback.message.chat.id, callback.message.message_id, reply_markup)
                return msg or callback.message
            except Exception:
                pass
        # If the current message is deleted/not editable, delete it and create a fresh page.
        try:
            await callback.message.delete()
        except Exception:
            pass
        sent = await callback.message.answer(text, reply_markup=reply_markup, **kwargs)
        remember_ui_message(sent.chat.id, sent.message_id)
        return sent
    except Exception:
        try:
            await callback.message.delete()
        except Exception:
            pass
        sent = await callback.message.answer(text, reply_markup=reply_markup, **kwargs)
        remember_ui_message(sent.chat.id, sent.message_id)
        return sent


async def ui_message(message: Message, text: str, reply_markup=None, **kwargs):
    """Use one bot message for FSM/input pages: delete user input and edit active page.

    The reply_markup is always applied explicitly, including None, so old buttons
    are removed when the next step only needs text input.
    """
    chat_id = message.chat.id
    mid = get_ui_message_id(chat_id)
    if mid:
        try:
            sent = await message.bot.edit_message_text(chat_id=chat_id, message_id=mid, text=text, reply_markup=reply_markup, **kwargs)
            try:
                await message.delete()
            except Exception:
                pass
            remember_ui_message(chat_id, mid)
            await _force_reply_markup(message.bot, chat_id, mid, reply_markup)
            return sent
        except TelegramBadRequest as e:
            if 'message is not modified' in str(e).lower():
                try:
                    await message.delete()
                except Exception:
                    pass
                await _force_reply_markup(message.bot, chat_id, mid, reply_markup)
                return None
            try:
                await message.bot.delete_message(chat_id, mid)
            except Exception:
                pass
        except Exception:
            pass
    sent = await message.answer(text, reply_markup=reply_markup, **kwargs)
    remember_ui_message(chat_id, sent.message_id)
    try:
        await message.delete()
    except Exception:
        pass
    return sent


async def ui_callback_message(callback: CallbackQuery, text: str, reply_markup=None, **kwargs):
    return await edit_or_answer(callback, text, reply_markup=reply_markup, **kwargs)


async def ui_page(message: Message, text: str, reply_markup=None, **kwargs):
    """Edit/send the active bot UI page without deleting the supplied message."""
    chat_id = message.chat.id
    mid = get_ui_message_id(chat_id) or getattr(message, 'message_id', None)
    if mid:
        try:
            sent = await message.bot.edit_message_text(chat_id=chat_id, message_id=mid, text=text, reply_markup=reply_markup, **kwargs)
            remember_ui_message(chat_id, mid)
            await _force_reply_markup(message.bot, chat_id, mid, reply_markup)
            return sent
        except TelegramBadRequest as e:
            if 'message is not modified' in str(e).lower():
                remember_ui_message(chat_id, mid)
                await _force_reply_markup(message.bot, chat_id, mid, reply_markup)
                return None
            try:
                await message.bot.delete_message(chat_id, mid)
            except Exception:
                pass
        except Exception:
            pass
    sent = await message.answer(text, reply_markup=reply_markup, **kwargs)
    remember_ui_message(chat_id, sent.message_id)
    return sent


async def state_prompt(message: Message, state, text: str, reply_markup=None, **kwargs):
    """Show the next FSM prompt on the same active UI message.

    Keeps admin/user step-by-step forms clean: the user's previous answer is
    removed, the previous bot prompt is edited/deleted, and the new prompt gets
    its own inline keyboard.
    """
    data = {}
    try:
        data = await state.get_data()
    except Exception:
        data = {}

    last_mid = data.get("last_bot_message_id") or get_ui_message_id(message.chat.id)
    sent = None
    if last_mid:
        try:
            sent = await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=int(last_mid),
                text=text,
                reply_markup=reply_markup,
                **kwargs,
            )
            remember_ui_message(message.chat.id, int(last_mid))
            await _force_reply_markup(message.bot, message.chat.id, int(last_mid), reply_markup)
        except TelegramBadRequest as e:
            if 'message is not modified' in str(e).lower():
                remember_ui_message(message.chat.id, int(last_mid))
                await _force_reply_markup(message.bot, message.chat.id, int(last_mid), reply_markup)
            else:
                try:
                    await message.bot.delete_message(message.chat.id, int(last_mid))
                except Exception:
                    pass
                sent = await message.answer(text, reply_markup=reply_markup, **kwargs)
                remember_ui_message(message.chat.id, sent.message_id)
        except Exception:
            sent = await message.answer(text, reply_markup=reply_markup, **kwargs)
            remember_ui_message(message.chat.id, sent.message_id)
    else:
        sent = await message.answer(text, reply_markup=reply_markup, **kwargs)
        remember_ui_message(message.chat.id, sent.message_id)

    try:
        await message.delete()
    except Exception:
        pass

    try:
        if sent is not None:
            await state.update_data(last_bot_message_id=sent.message_id)
        elif last_mid:
            await state.update_data(last_bot_message_id=int(last_mid))
    except Exception:
        pass
    return sent


async def delete_state_message(bot, chat_id: int | str, state) -> None:
    """Delete the last FSM prompt message if it exists."""
    try:
        data = await state.get_data()
    except Exception:
        data = {}
    mid = data.get("last_bot_message_id") or get_ui_message_id(chat_id)
    if not mid:
        return
    try:
        await bot.delete_message(chat_id=int(chat_id), message_id=int(mid))
    except Exception:
        pass
    forget_ui_message(chat_id)
    try:
        await state.update_data(last_bot_message_id=None)
    except Exception:
        pass
