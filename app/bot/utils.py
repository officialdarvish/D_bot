"""UI helpers share the same lifecycle as direct Bot/Message send calls."""
from aiogram.types import CallbackQuery, ReplyKeyboardRemove, Message
from aiogram.exceptions import TelegramBadRequest
from app.bot.ui_navigation import current_ui, output_role, completion_text, restart_keyboard

_ACTIVE_UI_MESSAGES: dict[int,int] = {}
INPUT_ERROR_NOTE = '⚠️ مقدار واردشده معتبر نیست؛ راهنمای همین پیام را بخوانید و مقدار درست را دوباره بفرستید.'


def with_input_error_note(text):
    return str(text or '')


def _is_result_message(text):
    return completion_text(text)


async def _final_result(text,explicit=False):
    if explicit:return True
    if not _is_result_message(text):return False
    ctx=current_ui()
    if ctx and ctx.state is not None and await ctx.state.get_state() is not None:
        ctx.final_candidate=text
        return False
    return True


def _default_back_markup(reply_markup=None):
    return restart_keyboard()


def remember_ui_message(chat_id,message_id):
    if message_id is not None:
        try:_ACTIVE_UI_MESSAGES[int(chat_id)]=int(message_id)
        except (TypeError,ValueError):pass


def get_ui_message_id(chat_id):
    try:return _ACTIVE_UI_MESSAGES.get(int(chat_id))
    except (TypeError,ValueError):return None


def forget_ui_message(chat_id):
    try:_ACTIVE_UI_MESSAGES.pop(int(chat_id),None)
    except (TypeError,ValueError):pass


async def delete_active_ui_message(bot,chat_id,exclude_message_id=None):
    mid=get_ui_message_id(chat_id)
    if not mid or exclude_message_id is not None and int(mid)==int(exclude_message_id):return
    try:await bot.delete_message(chat_id=int(chat_id),message_id=int(mid))
    except Exception:
        try:await bot.edit_message_reply_markup(chat_id=int(chat_id),message_id=int(mid),reply_markup=None)
        except Exception:pass
    forget_ui_message(chat_id)


async def send_result_message(target,text,reply_markup=None,**kwargs):
    msg=getattr(target,'message',None) or target
    if current_ui():
        with output_role('final'):
            return await msg.bot.send_message(msg.chat.id,text,reply_markup=restart_keyboard(),**kwargs)
    # Fallback for callers outside the polling pipeline, e.g. jobs and tests.
    sent=await msg.answer(text,reply_markup=restart_keyboard(),**kwargs)
    mid=get_ui_message_id(msg.chat.id) or (msg.message_id if getattr(target,'message',None) else None)
    if mid:
        try:await msg.bot.delete_message(chat_id=msg.chat.id,message_id=mid)
        except Exception:
            try:await msg.bot.edit_message_reply_markup(chat_id=msg.chat.id,message_id=mid,reply_markup=None)
            except Exception:pass
    forget_ui_message(msg.chat.id)
    return sent


async def send_single_message(bot,chat_id,text,reply_markup=None,**kwargs):
    if current_ui():
        with output_role('page'):
            return await bot.send_message(chat_id,text,reply_markup=reply_markup,**kwargs)
    await delete_active_ui_message(bot,chat_id)
    sent=await bot.send_message(chat_id,text,reply_markup=reply_markup,**kwargs)
    remember_ui_message(chat_id,sent.message_id)
    return sent


async def _force_reply_markup(bot,chat_id,message_id,reply_markup=None):
    try:await bot.edit_message_reply_markup(chat_id=chat_id,message_id=message_id,reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        if 'message is not modified' not in str(exc).lower():raise


async def edit_or_answer(callback,text,reply_markup=None,*,ui_final=False,**kwargs):
    final=await _final_result(text,ui_final)
    if final:return await send_result_message(callback,text,reply_markup,**kwargs)
    if current_ui():
        with output_role('page'):
            return await callback.message.bot.send_message(callback.message.chat.id,text,reply_markup=reply_markup,**kwargs)
    try:
        sent=await callback.message.edit_text(text,reply_markup=reply_markup,**kwargs)
        remember_ui_message(callback.message.chat.id,getattr(sent,'message_id',callback.message.message_id))
        return sent
    except TelegramBadRequest as exc:
        if 'message is not modified' in str(exc).lower():
            await _force_reply_markup(callback.message.bot,callback.message.chat.id,callback.message.message_id,reply_markup)
            remember_ui_message(callback.message.chat.id,callback.message.message_id);return callback.message
        if getattr(callback.message,'photo',None) or getattr(callback.message,'document',None) or getattr(callback.message,'video',None):
            try:
                sent=await callback.message.edit_caption(caption=text,reply_markup=reply_markup,**kwargs)
                remember_ui_message(callback.message.chat.id,callback.message.message_id);return sent
            except TelegramBadRequest:pass
        sent=await callback.message.answer(text,reply_markup=reply_markup,**kwargs)
        try:await callback.message.delete()
        except Exception:pass
        remember_ui_message(sent.chat.id,sent.message_id);return sent


async def ui_message(message,text,reply_markup=None,*,ui_final=False,**kwargs):
    if await _final_result(text,ui_final):
        sent=await send_result_message(message,text,reply_markup,**kwargs)
    elif current_ui():
        with output_role('page'):
            sent=await message.bot.send_message(message.chat.id,text,reply_markup=reply_markup,**kwargs)
    else:
        mid=get_ui_message_id(message.chat.id)
        sent=None
        if mid:
            try:sent=await message.bot.edit_message_text(chat_id=message.chat.id,message_id=mid,text=text,reply_markup=reply_markup,**kwargs)
            except TelegramBadRequest as exc:
                if 'message is not modified' in str(exc).lower():sent=message
        if sent is None:
            sent=await message.answer(text,reply_markup=reply_markup,**kwargs)
            if mid:
                try:await message.bot.delete_message(chat_id=message.chat.id,message_id=mid)
                except Exception:pass
        remember_ui_message(message.chat.id,getattr(sent,'message_id',mid))
    if not current_ui():
        try:await message.delete()
        except Exception:pass
    return sent


async def ui_callback_message(callback,text,reply_markup=None,**kwargs):
    return await edit_or_answer(callback,text,reply_markup,**kwargs)


async def ui_page(message,text,reply_markup=None,**kwargs):
    if current_ui():
        with output_role('page'):return await message.bot.send_message(message.chat.id,text,reply_markup=reply_markup,**kwargs)
    mid=get_ui_message_id(message.chat.id)
    if mid:
        try:return await message.bot.edit_message_text(chat_id=message.chat.id,message_id=mid,text=text,reply_markup=reply_markup,**kwargs)
        except TelegramBadRequest as exc:
            if 'message is not modified' in str(exc).lower():return message
    sent=await message.answer(text,reply_markup=reply_markup,**kwargs)
    remember_ui_message(message.chat.id,sent.message_id);return sent


async def state_prompt(message,state,text,reply_markup=None,**kwargs):
    sent=await ui_message(message,text,reply_markup,**kwargs)
    if sent is not None and not _is_result_message(text):
        await state.update_data(last_bot_message_id=sent.message_id)
    return sent


async def delete_state_message(bot,chat_id,state):
    if current_ui():
        await state.update_data(last_bot_message_id=None);return
    data=await state.get_data();mid=data.get('last_bot_message_id') or get_ui_message_id(chat_id)
    if mid:
        try:await bot.delete_message(chat_id=chat_id,message_id=mid)
        except Exception:pass
    forget_ui_message(chat_id);await state.update_data(last_bot_message_id=None)
