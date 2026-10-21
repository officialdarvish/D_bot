from app.services.delivery_templates import preserve_template_text
"""Deliver complete configurations without Telegram caption/text overflow."""
from html.parser import HTMLParser
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile


class _PlainHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def plain_html(text: str) -> str:
    parser = _PlainHTML()
    parser.feed(text)
    return ''.join(parser.parts)


def telegram_length(text: str) -> int:
    # Conservatively count UTF-16 units after entity parsing, including emoji.
    return len(plain_html(text).encode('utf-16-le')) // 2


@preserve_template_text
async def send_config_text(bot, chat_id, text: str, *, reply_markup=None):
    if telegram_length(text) <= 4096:
        try:
            return await bot.send_message(chat_id, text, parse_mode='HTML', reply_markup=reply_markup)
        except TelegramBadRequest as exc:
            if 'message is too long' not in str(exc).casefold():
                raise
    # Splitting an encrypted URI destroys copy/import. Keep the whole value in
    # a UTF-8 file when it exceeds even the message limit.
    return await bot.send_document(
        chat_id, BufferedInputFile(plain_html(text).encode('utf-8'), filename='configuration.txt'),
        caption='🔗 لینک کامل کانفیگ در فایل پیوست است؛ آن را کامل کپی کنید.',
        reply_markup=reply_markup,
    )


@preserve_template_text
async def send_config_photo(bot, chat_id, photo, caption: str, *, reply_markup=None):
    long_caption = telegram_length(caption) > 1024
    try:
        result = await bot.send_photo(
            chat_id, photo,
            caption='✅ کانفیگ آماده است. لینک کامل در پیام بعدی است.' if long_caption else caption,
            parse_mode='HTML', reply_markup=None if long_caption else reply_markup,
        )
    except TelegramBadRequest as exc:
        error = str(exc).casefold()
        if 'caption is too long' in error:
            # Custom bot text may expand after the length check. Keep the QR and
            # move the full original caption into its own message.
            result = await bot.send_photo(chat_id, photo, caption='✅ کانفیگ آماده است.')
            long_caption = True
        elif 'image_process_failed' in error:
            return await send_config_text(bot, chat_id, caption, reply_markup=reply_markup)
        else:
            raise
    if long_caption:
        return await send_config_text(bot, chat_id, caption, reply_markup=reply_markup)
    return result
