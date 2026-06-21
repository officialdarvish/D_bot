from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from sqlalchemy import select, text
from app.core.config import settings
from app.services.reseller_service import get_user_reseller, is_reseller_access_active
from app.database.session import SessionLocal
from app.database.models import User
from app.bot.keyboards.common import (
    CB_ADMIN, CB_BACK_MAIN, CB_BACK_ADMIN, main_menu_inline, admin_panel_inline, rules_keyboard
)
from app.database.defaults import WELCOME_TEXT_DEFAULT, RULES_TEXT_DEFAULT, get_setting_value
from app.bot.utils import edit_or_answer, ui_message, ui_callback_message, ui_page, remember_ui_message, get_ui_message_id, forget_ui_message

router = Router()


def normalize_channel_url(url: str) -> str:
    return (url or '').strip().replace(' ', '')


def extract_channel_chat_id(url: str) -> str | None:
    """
    Accepts:
      https://t.me/channel_username
      t.me/channel_username
      @channel_username
      channel_username

    Telegram join links like https://t.me/+xxxx or https://t.me/joinchat/xxxx
    cannot be checked with get_chat_member unless you save the real channel @username
    or numeric chat_id and the bot is admin in that channel.
    """
    url = normalize_channel_url(url)
    if not url:
        return None

    if url.startswith('@'):
        return url

    # direct numeric channel id support: -1001234567890
    if url.startswith('-100') and url[4:].isdigit():
        return url

    cleaned = url
    for prefix in ('https://', 'http://'):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
    if cleaned.startswith('t.me/'):
        cleaned = cleaned[len('t.me/'):]
    if cleaned.startswith('telegram.me/'):
        cleaned = cleaned[len('telegram.me/'):]

    cleaned = cleaned.strip('/')

    # invite/private links are not checkable by username
    if cleaned.startswith('+') or cleaned.startswith('joinchat/'):
        return None

    # remove path/query if any
    cleaned = cleaned.split('?')[0].split('/')[0].strip()
    if not cleaned:
        return None
    return cleaned if cleaned.startswith('@') else '@' + cleaned


async def check_channel_join(bot, user_id: int) -> tuple[bool, str, str]:
    channel_url = normalize_channel_url(await get_setting_value('channel_url', ''))
    if not channel_url:
        return True, '', ''

    chat_id = extract_channel_chat_id(channel_url)
    if not chat_id:
        return False, channel_url, (
            '⚠️ لینک کانال قابل استعلام نیست.\n\n'
            'برای عضویت اجباری باید لینک عمومی کانال را ثبت کنید، مثل:\n'
            '@vpn_channel\n'
            'یا\n'
            'https://t.me/vpn_channel\n\n'
            'اگر کانال خصوصی است، باید عددی chat_id کانال را ذخیره کنید و ربات را ادمین کانال کنید.'
        )

    try:
        member = await bot.get_chat_member(chat_id, user_id)
        if member.status in ('member', 'administrator', 'creator'):
            return True, channel_url, ''
        return False, channel_url, '❌ هنوز عضو کانال نیستید. ابتدا عضو شوید و دوباره «عضو شدم ✅» را بزنید.'
    except (TelegramBadRequest, TelegramForbiddenError) as e:
        return False, channel_url, (
            '⚠️ ربات نتوانست عضویت شما را استعلام بگیرد.\n\n'
            'مدیر باید این موارد را انجام دهد:\n'
            '1) ربات را داخل کانال اجباری Admin کند.\n'
            '2) لینک کانال را به صورت عمومی ثبت کند، مثل @vpn_channel یا https://t.me/vpn_channel.\n'
            '3) اگر کانال خصوصی است، chat_id عددی کانال ثبت شود.\n\n'
            f'خطای تلگرام: {type(e).__name__}'
        )
    except Exception as e:
        return False, channel_url, f'⚠️ خطا در بررسی عضویت: {type(e).__name__}'


def channel_keyboard(url: str):
    url = normalize_channel_url(url)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='عضویت در کانال', url=url)],
        [InlineKeyboardButton(text='عضو شدم ✅', callback_data='channel:check')],
    ])


async def is_test_visible() -> bool:
    return (await get_setting_value('test_account_button_visible', '1')) == '1'


async def _repair_users_id_sequence(session) -> None:
    """Repair PostgreSQL users.id sequence after restores/imports.

    If old data was restored with explicit IDs, the sequence may still point to an
    already-used id. Then a brand-new Telegram user gets users_pkey duplicate errors.
    SQLite ignores this path because pg_get_serial_sequence does not exist.
    """
    try:
        await session.execute(text(
            "SELECT setval(pg_get_serial_sequence('users', 'id'), "
            "GREATEST(COALESCE((SELECT MAX(id) FROM users), 0) + 1, 1), false)"
        ))
        await session.commit()
    except Exception:
        await session.rollback()


async def get_or_create_user(message: Message) -> User:
    telegram_id = int(message.from_user.id)
    username = message.from_user.username
    full_name = message.from_user.full_name

    async with SessionLocal() as session:
        q = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = q.scalar_one_or_none()
        if user:
            changed = False
            if user.username != username:
                user.username = username
                changed = True
            if user.full_name != full_name:
                user.full_name = full_name
                changed = True
            if changed:
                try:
                    await session.commit()
                except Exception:
                    await session.rollback()
            return user

        # First repair the sequence, then insert. This prevents duplicate users_pkey
        # for new users after backup/restore.
        await _repair_users_id_sequence(session)

        try:
            user = User(
                telegram_id=telegram_id,
                username=username,
                full_name=full_name,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user
        except Exception:
            await session.rollback()

        # Last-resort path: repair again and use raw SQL with telegram_id upsert.
        # This keeps /start from getting stuck when ORM insert fails because of an
        # older/restored schema or a stale sequence.
        await _repair_users_id_sequence(session)
        try:
            await session.execute(text(
                """
                INSERT INTO users (
                    telegram_id, username, full_name,
                    wallet_balance, wallet_v2ray_balance, wallet_openvpn_balance,
                    accepted_rules, is_blocked, joined_at
                ) VALUES (
                    :telegram_id, :username, :full_name,
                    0, 0, 0,
                    FALSE, FALSE, CURRENT_TIMESTAMP
                )
                ON CONFLICT (telegram_id) DO UPDATE SET
                    username = EXCLUDED.username,
                    full_name = EXCLUDED.full_name
                """
            ), {
                "telegram_id": telegram_id,
                "username": username,
                "full_name": full_name,
            })
            await session.commit()
        except Exception:
            await session.rollback()
            raise

        q = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = q.scalar_one()
        return user


async def is_reseller_menu_unlocked(user_id: int) -> bool:
    try:
        async with SessionLocal() as session:
            _user, reseller = await get_user_reseller(session, user_id)
            return is_reseller_access_active(reseller)
    except Exception:
        return False


async def send_main_menu(target, user_id: int):
    is_admin = user_id in settings.admin_ids
    welcome_text = await get_setting_value('welcome_text', WELCOME_TEXT_DEFAULT)
    if hasattr(target, 'answer'):
        await ui_page(target, welcome_text, reply_markup=main_menu_inline(is_admin, await is_test_visible(), await is_reseller_menu_unlocked(user_id)))


async def _safe_send_start_page(message: Message, text: str, reply_markup=None):
    """Always create a fresh visible page for /start.

    This deliberately does not edit old messages. Old pages may be photos/QR cards,
    deleted messages, or messages still controlled by an auto-refresh task. Editing
    them is the main reason /start looked like it did nothing.
    """
    sent = None
    try:
        sent = await message.answer(text, reply_markup=reply_markup, reply_markup_remove=None)
    except TypeError:
        # aiogram does not accept unknown kwargs in some versions.
        sent = await message.answer(text, reply_markup=reply_markup)
    except Exception:
        sent = await message.bot.send_message(message.chat.id, text, reply_markup=reply_markup)
    remember_ui_message(message.chat.id, sent.message_id)
    return sent


@router.message(CommandStart())
@router.message(Command('start'))
async def start(message: Message, state: FSMContext):
    """Hard reset the user session and always open a fresh main page.

    /start must never stay silent because of an old FSM state, a deleted active UI
    message, a photo/QR message, or a running service auto-refresh task.
    """
    try:
        await state.clear()
    except Exception:
        pass

    # Stop any running auto-refresh that might overwrite/delete the next UI page.
    try:
        from app.bot.handlers.public.my_services import cancel_auto_refresh
        cancel_auto_refresh(message.chat.id, None)
    except Exception:
        pass

    old_mid = get_ui_message_id(message.chat.id)
    forget_ui_message(message.chat.id)

    user = await get_or_create_user(message)

    bot_enabled = await get_setting_value('bot_enabled', '1')
    if bot_enabled != '1' and message.from_user.id not in settings.admin_ids:
        sent = await _safe_send_start_page(
            message,
            '⛔️ ربات در حال حاضر توسط مدیریت خاموش شده است.',
            reply_markup=ReplyKeyboardRemove(),
        )
    elif not user.accepted_rules:
        sent = await _safe_send_start_page(
            message,
            await get_setting_value('rules_text', RULES_TEXT_DEFAULT),
            reply_markup=rules_keyboard(),
        )
    else:
        ok, channel_url, error_text = await check_channel_join(message.bot, message.from_user.id)
        if not ok:
            sent = await _safe_send_start_page(
                message,
                error_text or 'برای استفاده از ربات ابتدا باید عضو کانال شوید.',
                reply_markup=channel_keyboard(channel_url),
            )
        else:
            sent = await _safe_send_start_page(
                message,
                await get_setting_value('welcome_text', WELCOME_TEXT_DEFAULT),
                reply_markup=main_menu_inline(message.from_user.id in settings.admin_ids, await is_test_visible(), await is_reseller_menu_unlocked(message.from_user.id)),
            )

    # Cleanup happens only AFTER the fresh page was sent, so /start never looks silent.
    if old_mid and old_mid not in (message.message_id, getattr(sent, 'message_id', None)):
        try:
            await message.bot.delete_message(message.chat.id, int(old_mid))
        except Exception:
            pass
    try:
        await message.delete()
    except Exception:
        pass


@router.callback_query(F.data == 'rules:accept')
async def accept_rules(callback: CallbackQuery):
    async with SessionLocal() as session:
        q = await session.execute(select(User).where(User.telegram_id == callback.from_user.id))
        user = q.scalar_one_or_none()
        if user:
            user.accepted_rules = True
            await session.commit()

    ok, channel_url, error_text = await check_channel_join(callback.message.bot, callback.from_user.id)
    if not ok:
        await edit_or_answer(callback, error_text or 'برای استفاده از ربات ابتدا باید عضو کانال شوید.', reply_markup=channel_keyboard(channel_url))
        await callback.answer('عضویت کانال بررسی شد.')
        return

    await callback.answer('قوانین تایید شد.')
    await edit_or_answer(
        callback,
        await get_setting_value('welcome_text', WELCOME_TEXT_DEFAULT),
        reply_markup=main_menu_inline(callback.from_user.id in settings.admin_ids, await is_test_visible(), await is_reseller_menu_unlocked(callback.from_user.id)),
    )


@router.callback_query(F.data == 'channel:check')
async def channel_check(callback: CallbackQuery):
    ok, channel_url, error_text = await check_channel_join(callback.message.bot, callback.from_user.id)
    if ok:
        await callback.answer('✅ عضویت شما تایید شد.')
        await edit_or_answer(
            callback,
            await get_setting_value('welcome_text', WELCOME_TEXT_DEFAULT),
            reply_markup=main_menu_inline(callback.from_user.id in settings.admin_ids, await is_test_visible(), await is_reseller_menu_unlocked(callback.from_user.id)),
        )
        return

    await callback.answer('عضویت تایید نشد.', show_alert=True)
    await edit_or_answer(
        callback,
        error_text or '❌ هنوز عضو کانال نیستید. ابتدا عضو شوید و دوباره امتحان کنید.',
        reply_markup=channel_keyboard(channel_url),
    )


@router.callback_query(F.data == CB_ADMIN)
async def open_admin_panel(callback: CallbackQuery):
    if callback.from_user.id not in settings.admin_ids:
        await callback.answer('شما دسترسی مدیریت ندارید.', show_alert=True)
        return
    await edit_or_answer(callback, '⚙️ پنل مدیریت ربات', reply_markup=admin_panel_inline())
    await callback.answer()


@router.callback_query(F.data == CB_BACK_MAIN)
async def back_to_main_menu(callback: CallbackQuery):
    # Stop service-detail auto refresh before opening home.
    # Without this, the old "My Configs" detail task edits the same message
    # every 3 seconds and pulls the user back to the service page.
    try:
        from app.bot.handlers.public.my_services import cancel_auto_refresh
        if callback.message:
            cancel_auto_refresh(callback.message.chat.id, callback.message.message_id)
            cancel_auto_refresh(callback.message.chat.id, None)
    except Exception:
        pass
    await edit_or_answer(
        callback,
        await get_setting_value('welcome_text', WELCOME_TEXT_DEFAULT),
        reply_markup=main_menu_inline(callback.from_user.id in settings.admin_ids, await is_test_visible(), await is_reseller_menu_unlocked(callback.from_user.id)),
    )
    await callback.answer()


@router.callback_query(F.data == CB_BACK_ADMIN)
async def back_to_admin(callback: CallbackQuery):
    if callback.from_user.id not in settings.admin_ids:
        await callback.answer('شما دسترسی مدیریت ندارید.', show_alert=True)
        return
    await edit_or_answer(callback, '⚙️ پنل مدیریت ربات', reply_markup=admin_panel_inline())
    await callback.answer()
