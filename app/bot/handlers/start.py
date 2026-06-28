from aiogram import Router, F
from datetime import datetime
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from sqlalchemy import select, text, or_
from app.core.config import settings
from app.services.reseller_service import get_user_reseller, is_reseller_access_active
from app.database.session import SessionLocal
from app.database.models import User, ClientService
from app.bot.keyboards.common import (
    CB_ADMIN, CB_BACK_MAIN, CB_BACK_ADMIN, CB_REFERRAL, main_menu_inline, admin_panel_inline, rules_keyboard, back_button
)
from app.database.defaults import WELCOME_TEXT_DEFAULT, RULES_TEXT_DEFAULT, get_setting_value, set_setting_value
from app.bot.utils import edit_or_answer, ui_message, ui_callback_message, ui_page, remember_ui_message, get_ui_message_id, forget_ui_message, send_single_message
from app.bot.error_reporting import report_bot_error
from app.services.referral_service import maybe_grant_invite_reward, notify_referrer_about_new_subset
from app.bot.states.admin_states import InitialSetupWizard

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
        await report_bot_error(bot, e, context='Forced channel membership check failed')
        return False, channel_url, (
            '⚠️ ربات نتوانست عضویت شما را استعلام بگیرد.\n\n'
            'لطفاً هرچه زودتر با پشتیبانی در ارتباط باشید.'
        )
    except Exception as e:
        await report_bot_error(bot, e, context='Forced channel membership unexpected error')
        return False, channel_url, '⚠️ خطایی رخ داده. هرچه زودتر با پشتیبانی در ارتباط باشید.'


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



def _extract_start_payload(message: Message) -> str:
    parts = (message.text or '').strip().split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ''


def _clean_referral_payload(payload: str) -> str:
    payload = (payload or '').strip()
    for prefix in ('ref_', 'ref-', 'r_', 'r-'):
        if payload.startswith(prefix):
            return payload[len(prefix):].strip()
    return payload


async def _ensure_referral_code(session, user: User) -> None:
    if getattr(user, 'referral_code', None):
        return
    user.referral_code = f'D{user.telegram_id}'
    await session.flush()

async def get_or_create_user(message: Message) -> User:
    telegram_id = int(message.from_user.id)
    username = message.from_user.username
    full_name = message.from_user.full_name
    payload = _clean_referral_payload(_extract_start_payload(message))

    async with SessionLocal() as session:
        q = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = q.scalar_one_or_none()
        if user:
            changed = False
            linked_to_referrer = False
            if user.username != username:
                user.username = username
                changed = True
            if user.full_name != full_name:
                user.full_name = full_name
                changed = True
            await _ensure_referral_code(session, user)
            # If an existing user opens a referral link for the first time, attach
            # them to the referrer once. Never overwrite an existing referrer and
            # never allow self-referral.
            if payload and not getattr(user, 'referred_by_user_id', None):
                if payload.isdigit():
                    ref_q = await session.execute(select(User).where((User.referral_code == payload) | (User.telegram_id == int(payload))))
                else:
                    ref_q = await session.execute(select(User).where(User.referral_code == payload))
                ref_user = ref_q.scalar_one_or_none()
                if ref_user and ref_user.id != user.id:
                    user.referred_by_user_id = ref_user.id
                    from datetime import datetime as _dt
                    user.referral_joined_at = _dt.utcnow()
                    changed = True
                    linked_to_referrer = True
            if changed or not getattr(user, 'referral_code', None):
                try:
                    await session.commit()
                    if linked_to_referrer:
                        await notify_referrer_about_new_subset(session, message.bot, user)
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
            await session.flush()
            await _ensure_referral_code(session, user)
            if payload:
                if payload.isdigit():
                    ref_q = await session.execute(select(User).where((User.referral_code == payload) | (User.telegram_id == int(payload))))
                else:
                    ref_q = await session.execute(select(User).where(User.referral_code == payload))
                ref_user = ref_q.scalar_one_or_none()
                if ref_user and ref_user.id != user.id:
                    user.referred_by_user_id = ref_user.id
                    from datetime import datetime as _dt
                    user.referral_joined_at = _dt.utcnow()
            await session.commit()
            await session.refresh(user)
            try:
                if user.referred_by_user_id:
                    await notify_referrer_about_new_subset(session, message.bot, user)
                await maybe_grant_invite_reward(session, message.bot, user)
            except Exception:
                pass
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
                    accepted_rules, is_blocked, referral_code, joined_at
                ) VALUES (
                    :telegram_id, :username, :full_name,
                    0, 0, 0,
                    FALSE, FALSE, :referral_code, CURRENT_TIMESTAMP
                )
                ON CONFLICT (telegram_id) DO UPDATE SET
                    username = EXCLUDED.username,
                    full_name = EXCLUDED.full_name
                """
            ), {
                "telegram_id": telegram_id,
                "username": username,
                "full_name": full_name,
                "referral_code": f"D{telegram_id}",
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
        await ui_page(target, welcome_text, reply_markup=main_menu_inline(is_admin, await is_test_visible(), (is_admin or await is_reseller_menu_unlocked(user_id))))


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


async def _is_initial_setup_done() -> bool:
    return (await get_setting_value('initial_setup_done', '0')) == '1'

async def _ask_initial_setup_channel(message: Message, state: FSMContext):
    await state.set_state(InitialSetupWizard.channel_url)
    sent = await message.answer('''⚙️ راه‌اندازی اولیه ربات لازم است.

مرحله ۱ از ۳: کانال عضویت اجباری را ارسال کنید.

لطفاً آدرس کانالی که کاربران باید عضو آن باشند را بفرستید.

مثال معتبر:
@your_channel
https://t.me/your_channel

⚠️ نکته مهم:
برای اینکه ربات بتواند عضویت کاربران را بررسی کند، کانال باید Username عمومی داشته باشد یا chat_id عددی کانال ثبت شود.
بعد از ارسال کانال، ربات به شما آموزش می‌دهد چطور آن را داخل کانال Admin کنید.''')
    remember_ui_message(message.chat.id, sent.message_id)


def setup_channel_admin_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ تایید می‌کنم، بررسی کن', callback_data='setup:channel_admin_check')],
    ])

async def _check_bot_admin_in_channel(bot, channel_url: str) -> tuple[bool, str]:
    chat_id = extract_channel_chat_id(channel_url)
    if not chat_id:
        return False, (
            '❌ این نوع لینک قابل بررسی نیست.\n\n'
            'لطفاً یکی از این موارد را ثبت کنید:\n'
            '• @your_channel\n'
            '• https://t.me/your_channel\n'
            '• chat_id عددی کانال مثل -100xxxxxxxxxx'
        )
    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(chat_id, me.id)
        if member.status in ('administrator', 'creator'):
            return True, 'ok'
        return False, '❌ ربات هنوز Admin کانال نیست. ابتدا ربات را داخل کانال Admin کنید، سپس دوباره دکمه تایید را بزنید.'
    except (TelegramBadRequest, TelegramForbiddenError) as e:
        await report_bot_error(bot, e, context='Channel admin status check failed')
        return False, (
            '❌ ربات نتوانست کانال را بررسی کند.\n\n'
            'لطفاً این موارد را چک کنید:\n'
            '1) ربات را داخل همان کانال Add کنید.\n'
            '2) ربات را Admin کنید.\n'
            '3) اگر کانال خصوصی است، به جای لینک دعوت، chat_id عددی کانال را ثبت کنید.\n\n'
            'در صورت ادامه مشکل، با پشتیبانی در ارتباط باشید.'
        )
    except Exception as e:
        await report_bot_error(bot, e, context='Channel admin status unexpected error')
        return False, '❌ خطایی رخ داده. هرچه زودتر با پشتیبانی در ارتباط باشید.'

async def _show_channel_admin_help(target, channel_url: str):
    text = (
        '✅ کانال ذخیره شد.\n\n'
        'مرحله ۲ از ۴: ربات را داخل کانال Admin کنید.\n\n'
        'آموزش:\n'
        '1) وارد کانال شوید.\n'
        '2) روی Manage Channel / مدیریت کانال بزنید.\n'
        '3) وارد Administrators شوید.\n'
        '4) Add Admin را بزنید.\n'
        '5) ربات را انتخاب کنید و Add کنید.\n\n'
        '✅ مهم:\n'
        'لازم نیست دسترسی خاصی به ربات بدهید.\n'
        'می‌توانید همه تیک‌های ادمین را خاموش کنید؛ فقط Admin بودن ربات برای بررسی عضویت کافی است.\n\n'
        f'کانال ثبت‌شده:\n{channel_url}\n\n'
        'بعد از Admin کردن ربات، دکمه زیر را بزنید.'
    )
    if isinstance(target, CallbackQuery):
        await edit_or_answer(target, text, reply_markup=setup_channel_admin_kb())
    else:
        sent = await target.answer(text, reply_markup=setup_channel_admin_kb())
        remember_ui_message(target.chat.id, sent.message_id)


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

    if message.from_user.id in settings.admin_ids and not await _is_initial_setup_done():
        await _ask_initial_setup_channel(message, state)
        return

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
                reply_markup=main_menu_inline(message.from_user.id in settings.admin_ids, await is_test_visible(), (message.from_user.id in settings.admin_ids or await is_reseller_menu_unlocked(message.from_user.id))),
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
        reply_markup=main_menu_inline(callback.from_user.id in settings.admin_ids, await is_test_visible(), (callback.from_user.id in settings.admin_ids or await is_reseller_menu_unlocked(callback.from_user.id))),
    )


@router.callback_query(F.data == 'channel:check')
async def channel_check(callback: CallbackQuery):
    ok, channel_url, error_text = await check_channel_join(callback.message.bot, callback.from_user.id)
    if ok:
        await callback.answer('✅ عضویت شما تایید شد.')
        await edit_or_answer(
            callback,
            await get_setting_value('welcome_text', WELCOME_TEXT_DEFAULT),
            reply_markup=main_menu_inline(callback.from_user.id in settings.admin_ids, await is_test_visible(), (callback.from_user.id in settings.admin_ids or await is_reseller_menu_unlocked(callback.from_user.id))),
        )
        return

    await callback.answer('عضویت تایید نشد.', show_alert=True)
    await edit_or_answer(
        callback,
        error_text or '❌ هنوز عضو کانال نیستید. ابتدا عضو شوید و دوباره امتحان کنید.',
        reply_markup=channel_keyboard(channel_url),
    )





@router.message(InitialSetupWizard.channel_url)
async def initial_setup_channel(message: Message, state: FSMContext):
    if message.from_user.id not in settings.admin_ids:
        return
    value = normalize_channel_url(message.text or '')
    if not value or value.startswith('/'):
        await ui_message(message, '⚠️ آدرس کانال نمی‌تواند خالی یا دستور ربات باشد.\n\nلطفاً آدرس کانال را ارسال کنید:\n@your_channel\nیا\nhttps://t.me/your_channel')
        return
    if not (value.startswith('@') or value.startswith('https://t.me/') or value.startswith('http://t.me/') or value.startswith('t.me/') or value.startswith('-100')):
        await ui_message(message, '⚠️ فرمت آدرس کانال درست نیست.\n\nمثال معتبر:\n@your_channel\nhttps://t.me/your_channel\n\nاگر کانال خصوصی است، chat_id عددی کانال را ارسال کنید.')
        return
    if not extract_channel_chat_id(value):
        await ui_message(message, '⚠️ این لینک قابل بررسی نیست.\n\nلینک‌های Invite مثل t.me/+xxxx قابل بررسی نیستند.\nلطفاً Username عمومی کانال مثل @your_channel یا chat_id عددی کانال را ارسال کنید.')
        return

    await set_setting_value('channel_url', value)
    await set_setting_value('force_join_enabled', '1')
    await state.set_state(InitialSetupWizard.channel_admin_confirm)
    await _show_channel_admin_help(message, value)

@router.callback_query(F.data == 'setup:channel_admin_check')
async def initial_setup_channel_admin_check(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in settings.admin_ids:
        return
    current = await state.get_state()
    if current != InitialSetupWizard.channel_admin_confirm.state:
        await callback.answer('این مرحله فعال نیست.', show_alert=True)
        return

    channel_url = normalize_channel_url(await get_setting_value('channel_url', ''))
    ok, err = await _check_bot_admin_in_channel(callback.message.bot, channel_url)
    if not ok:
        await callback.answer('ربات هنوز Admin نیست.', show_alert=True)
        await edit_or_answer(callback, err + '\n\nبعد از اصلاح، دوباره دکمه زیر را بزنید.', reply_markup=setup_channel_admin_kb())
        return

    await callback.answer('✅ Admin بودن ربات تایید شد.')
    await state.set_state(InitialSetupWizard.rules_text)
    await edit_or_answer(callback, '''✅ کانال تایید شد و عضویت اجباری فعال شد.

مرحله ۳ از ۴: متن قوانین ربات را ارسال کنید.

⚠️ این متن به کاربران نمایش داده می‌شود و باید آن را قبول کنند؛ پس حتماً متن کامل بفرستید و خالی نگذارید.''')

@router.message(InitialSetupWizard.rules_text)
async def initial_setup_rules(message: Message, state: FSMContext):
    if message.from_user.id not in settings.admin_ids:
        return
    value = (message.text or '').strip()
    if not value or value.startswith('/'):
        await message.answer('⚠️ متن قوانین نمی‌تواند خالی یا دستور ربات باشد.\n\nلطفاً متن قوانین را کامل ارسال کنید تا کاربران قبل از استفاده آن را ببینند و تایید کنند.')
        return
    await set_setting_value('rules_text', value)
    await state.set_state(InitialSetupWizard.welcome_text)
    await message.answer('''✅ مرحله ۳ ذخیره شد.

مرحله ۴ از ۴: متن خانه اصلی ربات را ارسال کنید.

⚠️ این متن بالای منوی اصلی نمایش داده می‌شود؛ حتماً متن کامل بفرستید و خالی نگذارید.''')

@router.message(InitialSetupWizard.welcome_text)
async def initial_setup_welcome(message: Message, state: FSMContext):
    if message.from_user.id not in settings.admin_ids:
        return
    value = (message.text or '').strip()
    if not value or value.startswith('/'):
        await message.answer('⚠️ متن خانه اصلی نمی‌تواند خالی یا دستور ربات باشد.\n\nلطفاً متن صفحه اصلی ربات را کامل ارسال کنید.')
        return
    await set_setting_value('welcome_text', value)
    await set_setting_value('initial_setup_done', '1')
    try:
        await state.clear()
    except Exception:
        pass
    # After first setup, force the owner through the same rules acceptance flow.
    # This opens the main menu immediately after they press the accept button.
    try:
        async with SessionLocal() as session:
            q = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
            admin_user = q.scalar_one_or_none()
            if admin_user:
                admin_user.accepted_rules = False
                await session.commit()
    except Exception:
        pass
    await message.answer(
        '✅ راه‌اندازی اولیه با موفقیت تکمیل شد.\n\nلطفاً قوانین ربات را تایید کنید تا صفحه اصلی برای شما باز شود.'
    )
    await message.answer(
        await get_setting_value('rules_text', RULES_TEXT_DEFAULT),
        reply_markup=rules_keyboard(),
    )

@router.callback_query(F.data == CB_REFERRAL)
async def referral_page(callback: CallbackQuery):
    async with SessionLocal() as session:
        q = await session.execute(select(User).where(User.telegram_id == callback.from_user.id))
        user = q.scalar_one_or_none()
        if not user:
            await callback.answer('کاربر پیدا نشد.', show_alert=True); return
        await _ensure_referral_code(session, user)
        from sqlalchemy import func as _func
        count = await session.scalar(select(_func.count(User.id)).where(User.referred_by_user_id == user.id)) or 0
        active_service_id = await session.scalar(
            select(ClientService.id)
            .where(ClientService.user_id == user.id)
            .where(ClientService.is_active == True)
            .where(or_(ClientService.expires_at.is_(None), ClientService.expires_at > datetime.utcnow()))
            .limit(1)
        )
        await session.commit()
    me = await callback.message.bot.get_me()
    link = f'https://t.me/{me.username}?start=ref_{user.referral_code}'
    if active_service_id:
        commission_note = '✅ چون سرویس فعال دارید، در صورت خرید زیرمجموعه‌ها پورسانت به شما تعلق می‌گیرد.'
    else:
        commission_note = '⚠️ چون سرویس فعالی در حال حاضر ندارید، در صورت اضافه شدن زیرمجموعه و خرید از سمت مجموعه شما پورسانت به شما تعلق نمی‌گیرد.'
    text = ('🎁 سیستم زیرمجموعه گیری\n━━━━━━━━━━━━━━━━\n\n'
            f'{commission_note}\n\n'
            f'🔗 لینک اختصاصی شما:\n{link}\n\n'
            f'👥 تعداد زیرمجموعه‌های شما: {count}\n\n'
            'هر کاربری با این لینک وارد ربات شود، زیرمجموعه شما ثبت می‌شود.')
    await edit_or_answer(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(CB_BACK_MAIN)]]))
    await callback.answer()

@router.callback_query(F.data == CB_ADMIN)
async def open_admin_panel(callback: CallbackQuery):
    if callback.from_user.id not in settings.admin_ids:
        await callback.answer('شما دسترسی مدیریت ندارید.', show_alert=True)
        return
    await edit_or_answer(callback, '⚙️ پنل مدیریت ربات', reply_markup=admin_panel_inline())
    await callback.answer()



@router.callback_query(F.data == 'restart:start')
async def restart_from_button(callback: CallbackQuery, state: FSMContext):
    try:
        await state.clear()
    except Exception:
        pass
    user = await get_or_create_user(callback)
    if callback.from_user.id in settings.admin_ids and not await _is_initial_setup_done():
        await callback.message.answer('⚙️ راه‌اندازی اولیه هنوز کامل نشده است. برای ادامه /start را ارسال کنید.')
        await callback.answer('برای ادامه /start را ارسال کنید.')
        return
    bot_enabled = await get_setting_value('bot_enabled', '1')
    if bot_enabled != '1' and callback.from_user.id not in settings.admin_ids:
        await edit_or_answer(callback, '⛔️ ربات در حال حاضر توسط مدیریت خاموش شده است.', reply_markup=ReplyKeyboardRemove())
        await callback.answer()
        return
    if not user.accepted_rules:
        await edit_or_answer(callback, await get_setting_value('rules_text', RULES_TEXT_DEFAULT), reply_markup=rules_keyboard())
        await callback.answer('شروع مجدد انجام شد.')
        return
    ok, channel_url, error_text = await check_channel_join(callback.message.bot, callback.from_user.id)
    if not ok:
        await edit_or_answer(callback, error_text or 'برای استفاده از ربات ابتدا باید عضو کانال شوید.', reply_markup=channel_keyboard(channel_url))
        await callback.answer('عضویت کانال را بررسی کنید.')
        return
    await edit_or_answer(
        callback,
        await get_setting_value('welcome_text', WELCOME_TEXT_DEFAULT),
        reply_markup=main_menu_inline(callback.from_user.id in settings.admin_ids, await is_test_visible(), (callback.from_user.id in settings.admin_ids or await is_reseller_menu_unlocked(callback.from_user.id))),
    )
    await callback.answer('شروع مجدد انجام شد.')

async def _open_main_menu_from_callback(callback: CallbackQuery, state: FSMContext, *, force_new_message: bool = False):
    # Always answer immediately. Profile/file messages can make Telegram show
    # "query is too old / expired" if we wait until after DB/menu rendering.
    try:
        await callback.answer()
    except Exception:
        pass
    try:
        await state.clear()
    except Exception:
        pass
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
    text = await get_setting_value('welcome_text', WELCOME_TEXT_DEFAULT)
    markup = main_menu_inline(
        callback.from_user.id in settings.admin_ids,
        await is_test_visible(),
        (callback.from_user.id in settings.admin_ids or await is_reseller_menu_unlocked(callback.from_user.id)),
    )
    # The Home button under an .ovpn document must not try to edit the document
    # caption. Send/open a fresh main-menu page instead.
    is_media_message = bool(
        callback.message and (
            getattr(callback.message, 'document', None)
            or getattr(callback.message, 'photo', None)
            or getattr(callback.message, 'video', None)
        )
    )
    if force_new_message or is_media_message:
        if callback.message:
            await send_single_message(callback.message.bot, callback.from_user.id, text, reply_markup=markup)
        return
    await edit_or_answer(callback, text, reply_markup=markup)


@router.callback_query(F.data == 'profile:home')
async def profile_home_menu(callback: CallbackQuery, state: FSMContext):
    await _open_main_menu_from_callback(callback, state, force_new_message=True)


@router.callback_query(F.data == 'home:main')
async def global_home_menu(callback: CallbackQuery, state: FSMContext):
    await _open_main_menu_from_callback(callback, state, force_new_message=True)


@router.callback_query(F.data == CB_BACK_MAIN)
async def back_to_main_menu(callback: CallbackQuery, state: FSMContext):
    # Home/back-to-main must always open a fresh main-menu message.
    # Editing old document/photo/service messages can make Telegram show
    # "this message is expired" or keep the user on the previous page.
    await _open_main_menu_from_callback(callback, state, force_new_message=True)


@router.callback_query(F.data == CB_BACK_ADMIN)
async def back_to_admin(callback: CallbackQuery, state: FSMContext):
    try:
        await state.clear()
    except Exception:
        pass
    if callback.from_user.id not in settings.admin_ids:
        await callback.answer('شما دسترسی مدیریت ندارید.', show_alert=True)
        return
    await edit_or_answer(callback, '⚙️ پنل مدیریت ربات', reply_markup=admin_panel_inline())
    await callback.answer()
