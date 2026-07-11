from datetime import datetime, timedelta
import asyncio
import random, string, re
from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy import select, or_
from app.core.config import settings
from app.database.session import SessionLocal
from app.database.models import User, Server, ServerCategory, Plan, PaymentCard, Order, ClientService, Setting
from app.bot.states.public_states import BuyFlow, QueryClient, DiscountInput
from app.bot.states.admin_states import OrderReceiptReject
from app.services.xui_service import XuiService
from app.services.mikrotik_service import MikroTikService
from app.services.nowpayments_service import NowPaymentsService
from app.bot.keyboards.common import CB_BUY, CB_QUERY, back_button, back_main_inline, main_menu_inline
from app.database.defaults import get_setting_value, WELCOME_TEXT_DEFAULT
from app.bot.utils import send_single_message, edit_or_answer, ui_message, ui_callback_message
from app.bot.error_reporting import handle_user_facing_error, report_bot_error
from app.bot.service_presenter import send_service_info as send_service_card
from app.bot.renewal_delivery import send_renewal_confirmation
from app.services.referral_service import apply_purchase_commission
from app.services.discount_service import apply_discount_amount, mark_discount_used, release_order_discount_usage
from app.services.plan_order import saved_category_order, saved_plan_order, sort_by_saved_order, sort_categories_by_saved_order
from app.utils.jalali import fa_date

router = Router()

async def safe_callback_answer(callback: CallbackQuery, text: str | None = None, *, show_alert: bool = False) -> None:
    """Answer callback queries without crashing on old Telegram callback IDs."""
    try:
        if text is None:
            await callback.answer()
        else:
            await callback.answer(text, show_alert=show_alert)
    except TelegramBadRequest as exc:
        msg = str(exc).lower()
        if 'query is too old' in msg or 'query id is invalid' in msg or 'response timeout expired' in msg:
            return
        raise
    except Exception:
        return


def receipt_received_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🏠 خانه', callback_data='home:main')]
    ])

RECEIPT_RECEIVED_TEXT = (
    '✅ رسید با موفقیت دریافت شد.\n\n'
    'لطفاً منتظر بمانید تا مدیر رسید شما را بررسی و تایید کند.\n'
    'بعد از تایید، نتیجه از همین ربات برای شما ارسال می‌شود.'
)


def status_only_keyboard(text: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data='noop')]
    ])

async def mark_message_status(callback: CallbackQuery, text: str) -> None:
    try:
        await callback.message.edit_reply_markup(reply_markup=status_only_keyboard(text))
    except Exception:
        pass


def approved_only_keyboard(text: str = '✅ تایید شد') -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data='noop')]
    ])

def processing_only_keyboard(text: str = '⏳ در حال ساخت سرویس...') -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data='noop')]
    ])

def failed_retry_keyboard(order_id: int, *, is_renewal: bool = False) -> InlineKeyboardMarkup:
    retry_text = '🔁 تلاش مجدد تمدید' if is_renewal else '🔁 تلاش مجدد خرید جدید'
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=retry_text, callback_data=f'order:approve:{order_id}')],
        [InlineKeyboardButton(text='❌ رد رسید', callback_data=f'order:reject:{order_id}')],
    ])

async def replace_admin_receipt_buttons(callback: CallbackQuery, text: str = '✅ تایید شد') -> None:
    try:
        await callback.message.edit_reply_markup(reply_markup=approved_only_keyboard(text))
    except Exception:
        pass

async def edit_admin_receipt_keyboard(bot, chat_id: int | None, message_id: int | None, reply_markup: InlineKeyboardMarkup) -> None:
    if not bot or chat_id is None or message_id is None:
        return
    try:
        await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=reply_markup)
    except Exception:
        pass

async def send_admin_notice(bot, chat_id: int | None, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    if not bot or chat_id is None:
        return
    try:
        await bot.send_message(chat_id, text, reply_markup=reply_markup)
    except Exception:
        pass

async def send_buyer_notice(bot, chat_id: int | None, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    if not bot or chat_id is None:
        return
    try:
        await bot.send_message(chat_id, text, reply_markup=reply_markup)
    except Exception:
        pass


def success_home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🏠 خانه', callback_data='home:main')]
    ])


async def send_service_success_notice(bot, chat_id: int | None, *, username: str | None = None, action: str = 'ساخته و ارسال') -> None:
    title = '✅ سرویس شما با موفقیت تمدید شد.' if action == 'renew' else '✅ سرویس شما با موفقیت ساخته و ارسال شد.'
    extra = f'\n\n👤 نام اختصاصی: {username}' if username else ''
    await send_buyer_notice(bot, chat_id, title + extra + '\n\nبرای برگشت به صفحه اول، دکمه خانه را بزنید.', reply_markup=success_home_keyboard())


def service_building_text(username: str, plan_title: str, volume_gb, duration_days, *, action: str = 'ساخت و ارسال') -> str:
    return (
        '⏳ یوزر شما در حال ساخت و ارسال است. لطفاً منتظر بمانید.\n\n'
        f'👤 نام اختصاصی: {username or "-"}\n'
        f'📦 پلن: {plan_title or "-"}\n'
        f'💾 حجم: {volume_gb:g} گیگ\n'
        f'⏳ مدت: {duration_days} روز\n'
        f'🔄 وضعیت: در حال {action}...'
    )


def rnd_suffix(): return ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))
def extract_key(text: str) -> str:
    text=text.strip()
    m=re.search(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}', text)
    if m: return m.group(0)
    return text.rstrip('/').split('/')[-1].split('?')[0].split('#')[0]

def valid_mikrotik_password(text: str) -> bool:
    value = text or ''
    return bool(value) and not any(ch.isspace() for ch in value)

MIKROTIK_PASSWORD_PROMPT = (
    '🔐 لطفاً پسورد سرویس را ارسال کنید.\n'
    'پسورد می‌تواند حتی یک کاراکتر باشد؛ فقط نباید فاصله یا کاراکتر سفید داشته باشد.'
)

MIKROTIK_USERNAME_PROMPT = '👤 لطفاً یوزرنیم اختصاصی را ارسال کنید.'

SERVICE_USERNAME_RE = re.compile(r'[A-Za-z0-9_]{1,32}')

USERNAME_FORMAT_ERROR_TEXT = '❌ یوزرنیم معتبر نیست. لطفاً فقط حروف انگلیسی، عدد یا آندرلاین ارسال کنید.'

USERNAME_TAKEN_TEXT = '❌ این یوزرنیم قبلاً ثبت شده است. لطفاً یک یوزرنیم اختصاصی دیگر ارسال کنید.'


def normalize_service_username(text: str | None) -> str:
    return (text or '').strip()


def valid_service_username(username: str) -> bool:
    return bool(SERVICE_USERNAME_RE.fullmatch(username or ''))


async def service_username_exists(session, server, username: str) -> bool:
    local = (await session.execute(
        select(ClientService.id).where(
            (ClientService.client_username == username) | (ClientService.xui_email == username),
            or_(ClientService.client_username.is_(None), ~ClientService.client_username.like('deleted_%')),
        ).limit(1)
    )).scalar_one_or_none()
    if local:
        return True
    if not server:
        return False
    if server.server_type == 'xui':
        try:
            return bool(await XuiService().find_client_any(server, username))
        except Exception:
            return False
    if server.server_type == 'mikrotik':
        try:
            return bool(await MikroTikService().get_user(server, username))
        except Exception:
            return False
    return False




async def get_service_username_error(session, server, username: str) -> str | None:
    """Return the exact reason a requested public-service username is not usable.

The purchase state must stay on BuyFlow.username when this returns a message,
so the user can send a new name and continue the same flow.
    """
    if not valid_service_username(username):
        return USERNAME_FORMAT_ERROR_TEXT
    if await service_username_exists(session, server, username):
        return USERNAME_TAKEN_TEXT
    return None

async def ask_for_another_username(message: Message, reason_text: str) -> None:
    await ui_message(message, reason_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('menu:buy')]]))


def server_type_filter(kind: str):
    kind = (kind or '').lower()
    if ('mikrotik' in kind or 'microtik' in kind or 'میکروتیک' in kind
            or kind in ('openvpn','l2tp') or 'openvpn' in kind or 'l2tp' in kind
            or 'اوپن' in kind or 'وی پی ان' in kind):
        # OpenVPN/L2TP services are provisioned through MikroTik / Custom panel servers.
        return 'mikrotik'
    return 'xui'

def wallet_field(server_type: str): return 'wallet_balance'

async def get_public_service_types(session) -> list[tuple[str, str, str]]:
    # Show ONLY active service types created from Admin Web > Service Types.
    rows = (await session.execute(
        select(Setting).where(Setting.key.like('service_type:custom:%'))
    )).scalars().all()
    order_row = await session.get(Setting, 'service_type_order')
    settings_map = {r.key: r.value for r in rows}
    order = [x for x in ((order_row.value if order_row else '') or '').split('|') if x]
    rank = {k: i for i, k in enumerate(order)}
    service_rows = [r for r in rows if r.key.startswith('service_type:custom:') and not r.key.endswith(':active')]
    service_rows = sorted(service_rows, key=lambda r: (rank.get(r.key, 10_000), r.key))
    result = []
    seen = set()
    for row in service_rows:
        if settings_map.get(f'{row.key}:active', '1') == '0':
            continue
        label = (row.value or '').strip()
        if not label:
            continue
        slug = row.key.split(':')[-1].strip().lower()
        stype = server_type_filter(slug + ' ' + label.lower())
        kind = slug or stype
        if kind in seen:
            continue
        seen.add(kind)
        result.append((kind, label, stype))
    return result

async def get_service_type_ui(kind: str) -> tuple[bool, str]:
    if kind == 'v2ray':
        enabled = await get_setting_value('service_type_v2ray_enabled', '1')
        label = await get_setting_value('service_type_v2ray_label', 'V2Ray')
    else:
        enabled = await get_setting_value('service_type_openvpn_enabled', '1')
        label = await get_setting_value('service_type_openvpn_label', 'OpenVPN - L2TP')
    return enabled == '1', label


def category_server_ids(cat) -> list[int]:
    ids = []
    try:
        for sid in (getattr(cat, 'server_ids', None) or []):
            if int(sid) > 0 and int(sid) not in ids:
                ids.append(int(sid))
    except Exception:
        pass
    try:
        sid = int(getattr(cat, 'server_id', 0) or 0)
        if sid > 0 and sid not in ids:
            ids.append(sid)
    except Exception:
        pass
    return ids

def category_matches_servers(cat, server_ids: list[int]) -> bool:
    if not server_ids:
        return True
    linked = category_server_ids(cat)
    return bool(set(int(x) for x in server_ids) & set(linked))

def category_key(name: str) -> str:
    return re.sub(r'\s+', ' ', (name or '').strip()).lower()

def category_group_callback(index: str | int) -> str:
    return f'buy:catgrp:{index}'

def gb(bytes_val): return bytes_val/1024**3 if bytes_val else 0

def format_gb(bytes_val: int | None, *, unlimited_when_zero: bool = False) -> str:
    value = int(bytes_val or 0)
    if unlimited_when_zero and value <= 0:
        return 'نامحدود'
    return f'{gb(value):.2f} گیگ'

def percent_bar(used: int, total: int, width: int = 14) -> str:
    if not total or total <= 0:
        return '▱' * width
    ratio = max(0, min(1, (used or 0) / total))
    filled = int(round(ratio * width))
    return '▰' * filled + '▱' * (width - filled)

def _remote_value(remote: dict | None, *keys: str):
    if not isinstance(remote, dict):
        return None
    for key in keys:
        if key in remote and remote.get(key) not in (None, ''):
            return remote.get(key)
    return None

def _int_or_zero(value) -> int:
    try:
        return max(int(float(value or 0)), 0)
    except Exception:
        return 0

def _remote_used_bytes(remote: dict | None) -> int:
    direct = _remote_value(
        remote,
        'used_bytes', 'bytes_used', 'used', 'usage_bytes', 'traffic_used_bytes',
        'used_traffic_bytes', 'total_used_bytes', 'consumed_bytes'
    )
    if direct is not None:
        return _int_or_zero(direct)
    up = _int_or_zero(_remote_value(remote, 'up', 'upload', 'upload_bytes', 'tx', 'tx_bytes'))
    down = _int_or_zero(_remote_value(remote, 'down', 'download', 'download_bytes', 'rx', 'rx_bytes'))
    return up + down

def _remote_total_bytes(remote: dict | None, fallback: int = 0) -> int:
    direct = _remote_value(
        remote,
        'volume_bytes', 'total_bytes', 'total', 'limit_bytes', 'data_limit_bytes',
        'quota_bytes', 'transfer_enable', 'totalGB'
    )
    value = _int_or_zero(direct)
    return value or int(fallback or 0)

def _remote_remaining_bytes(remote: dict | None, total: int, used: int) -> int | None:
    direct = _remote_value(
        remote,
        'remaining_bytes', 'remain_bytes', 'bytes_remaining', 'left_bytes',
        'unused_bytes', 'available_bytes', 'remaining'
    )
    if direct is not None:
        return _int_or_zero(direct)
    if total and total > 0:
        return max(total - used, 0)
    return None

def _usage_lines(total: int, used: int, remaining: int | None = None, *, prefix: str = '│ ') -> list[str]:
    remaining = max((total or 0) - (used or 0), 0) if remaining is None and total else remaining
    pct = int(((used or 0) / total) * 100) if total else 0
    remain_text = 'نامحدود' if not total else format_gb(remaining or 0)
    return [
        f'{prefix}💾 حجم کل: {format_gb(total, unlimited_when_zero=True)}',
        f'{prefix}📈 مصرف‌شده: {format_gb(used)}',
        f'{prefix}⏳ باقی‌مانده: {remain_text}',
        f'{prefix}📊 درصد مصرف: {percent_bar(used, total)} {pct}%',
    ]

def pretty_config_result(*, username: str, active: bool, plan_title: str = 'نامشخص', created_at: str = '-', expires_at: str = '-', total: int = 0, used: int = 0, uuid: str | None = None) -> str:
    remain = max((total or 0) - (used or 0), 0)
    pct = int(((used or 0) / total) * 100) if total else 0
    status_icon = '🟢' if active else '🔴'
    status_text = 'فعال' if active else 'غیرفعال'
    uuid_line = f'│ 🆔 UUID: {uuid}\n' if uuid else ''
    return (
        '✅ کانفیگ با مشخصات زیر پیدا شد\n'
        '╭━━━━━━━━━━━━━━━━━━━━╮\n'
        f'│ 🚀 نام کانفیگ: {username or "-"}\n'
        f'│ {status_icon} وضعیت: {status_text}\n'
        f'│ 📦 پلن انتخابی: {plan_title or "نامشخص"}\n'
        f'{uuid_line}'
        '╰━━━━━━━━━━━━━━━━━━━━╯\n\n'
        '📅 زمان‌بندی سرویس\n'
        f'├ 🛒 تاریخ خرید: {created_at or "-"}\n'
        f'╰ ⏳ تاریخ انقضا: {expires_at or "-"}\n\n'
        '📊 وضعیت مصرف\n'
        f'├ 💾 حجم کل: {format_gb(total, unlimited_when_zero=True)}\n'
        f'├ 📈 مصرف‌شده: {format_gb(used)}\n'
        f'├ ⏳ باقی‌مانده: {"نامحدود" if not total else format_gb(remain)}\n'
        f'╰ {percent_bar(used, total)} {pct}%\n\n'
        '— ✦ D Bot ✦ —'
    )


async def pick_available_username(session, server, base_username: str) -> str:
    """Return a username that is free in both local DB and the real 3x-ui panel.

    This protects retries after a partial panel creation: the DB may have rolled
    back while 3x-ui already kept the client, so checking only ClientService is
    not enough.
    """
    clean = re.sub(r'[^A-Za-z0-9_]', '', (base_username or '').strip().replace(' ', ''))
    if not clean:
        clean = 'user' + rnd_suffix()

    for idx in range(20):
        candidate = clean if idx == 0 else f'{clean}{rnd_suffix()}'
        local = (await session.execute(
            select(ClientService).where(
                ClientService.server_id == server.id,
                (ClientService.client_username == candidate) | (ClientService.xui_email == candidate),
            )
        )).scalar_one_or_none()
        if local:
            continue

        if server.server_type == 'xui':
            try:
                remote = await XuiService().find_client_any(server, candidate)
            except Exception:
                remote = None
            if remote:
                continue
        elif server.server_type == 'mikrotik':
            try:
                remote = await MikroTikService().get_user(server, candidate)
            except Exception:
                remote = None
            if remote:
                continue

        return candidate

    return f'{clean}{rnd_suffix()}{rnd_suffix()}'

async def send_home(bot, chat_id:int, is_admin: bool=False):
    text = await get_setting_value('welcome_text', WELCOME_TEXT_DEFAULT)
    await send_single_message(bot, chat_id, text, reply_markup=main_menu_inline(is_admin))

def is_admin_user(user_id: int) -> bool:
    return user_id in settings.admin_ids

def plan_price_text(plan, is_admin: bool = False) -> str:
    if is_admin:
        return f'{plan.title} - رایگان برای مدیر'
    return f'{plan.title} - {plan.price_irt:,} تومان'


def payment_methods_keyboard(data: dict, *, include_discount: bool = True) -> InlineKeyboardMarkup:
    rows = []
    if include_discount:
        rows.append([InlineKeyboardButton(text='🏷 اعمال کد تخفیف', callback_data='pay:discount')])
    rows.append([InlineKeyboardButton(text='کیف پول', callback_data='pay:wallet'), InlineKeyboardButton(text='کارت به کارت', callback_data='pay:card')])
    plan_id = data.get('plan_id') or 0
    rows.append([back_button(f'buy:plan:{plan_id}')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def show_buy_payment_methods_callback(callback: CallbackQuery, state: FSMContext, text: str | None = None, *, include_discount: bool = True) -> None:
    data = await state.get_data()
    await state.set_state(BuyFlow.payment_method)
    await edit_or_answer(
        callback,
        text or 'روش پرداخت را انتخاب کنید:\n\nاگر کد تخفیف دارید، ابتدا روی «اعمال کد تخفیف» بزنید.',
        reply_markup=payment_methods_keyboard(data, include_discount=include_discount),
    )
    await safe_callback_answer(callback)

@router.callback_query(F.data == CB_BUY)
async def buy_start(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    async with SessionLocal() as session:
        service_types = await get_public_service_types(session)
    rows = []
    for kind, label, stype in service_types:
        icon = '🔵' if stype == 'xui' else ('🟠' if stype == 'mikrotik' else '🟣')
        rows.append([InlineKeyboardButton(text=f'{icon} {label}', callback_data=f'buy:type:{kind}')])
    if not rows:
        rows.append([InlineKeyboardButton(text='در حال حاضر هیچ نوع سرویسی فعال نیست', callback_data='noop')])
    rows.append([back_button('back:main')])
    kb=InlineKeyboardMarkup(inline_keyboard=rows)
    await edit_or_answer(callback, 'نوع سرویس را انتخاب کنید:', reply_markup=kb); await safe_callback_answer(callback)

@router.callback_query(F.data.startswith('buy:type:'))
async def buy_type(callback: CallbackQuery, state: FSMContext):
    kind=callback.data.split(':')[-1]
    async with SessionLocal() as session:
        service_types = await get_public_service_types(session)
        matched = next((row for row in service_types if row[0] == kind), None)
        stype = matched[2] if matched else server_type_filter(kind)
        all_servers=(await session.execute(select(Server).where(Server.is_active == True, Server.server_type == stype))).scalars().all()
        servers=[srv for srv in all_servers if ((srv.meta or {}).get('scope') or 'public') in ('public','all')]
        server_ids=[srv.id for srv in servers]
        cats=[]
        if server_ids:
            all_cats=(await session.execute(
                select(ServerCategory).where(ServerCategory.is_active == True).order_by(ServerCategory.id.desc())
            )).scalars().all()
            cats=[cat for cat in all_cats if category_matches_servers(cat, server_ids)]
            cats=sort_categories_by_saved_order(cats, await saved_category_order(session))

    await state.update_data(kind=kind, server_type=stype, server_ids=server_ids)
    if not servers:
        await edit_or_answer(callback, 'در حال حاضر هیچ سروری برای این نوع سرویس فعال نیست.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('menu:buy')]])); await safe_callback_answer(callback); return
    if not cats:
        await edit_or_answer(callback, 'برای این نوع سرویس هنوز دسته‌ای ثبت نشده است.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('menu:buy')]])); await safe_callback_answer(callback); return

    groups = []
    seen = {}
    for cat in cats:
        key = category_key(cat.name)
        if not key:
            continue
        if key not in seen:
            seen[key] = {'name': cat.name, 'ids': []}
            groups.append(seen[key])
        seen[key]['ids'].append(cat.id)

    category_groups = {str(i): group['ids'] for i, group in enumerate(groups)}
    await state.update_data(category_groups=category_groups)
    rows = [[InlineKeyboardButton(text=group['name'], callback_data=category_group_callback(i))] for i, group in enumerate(groups)]
    rows.append([back_button('menu:buy')])
    kb=InlineKeyboardMarkup(inline_keyboard=rows)
    await edit_or_answer(callback, 'دسته موردنظر را انتخاب کنید:', reply_markup=kb); await safe_callback_answer(callback)

@router.callback_query(F.data.startswith('buy:server:'))
async def buy_server(callback: CallbackQuery, state: FSMContext):
    sid=int(callback.data.split(':')[-1]); await state.update_data(server_id=sid)
    async with SessionLocal() as session:
        all_cats=(await session.execute(select(ServerCategory).where(ServerCategory.is_active == True).order_by(ServerCategory.id.desc()))).scalars().all()
        cats=[cat for cat in all_cats if category_matches_servers(cat, [sid])]
        cats=sort_categories_by_saved_order(cats, await saved_category_order(session))
    data=await state.get_data()
    if not cats:
        await edit_or_answer(callback, 'برای این سرور هنوز دسته‌ای ثبت نشده است.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(f'buy:type:{data.get("kind", "v2ray")}')]])); await safe_callback_answer(callback); return
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=c.name, callback_data=f'buy:cat:{c.id}')] for c in cats] + [[back_button(f'buy:type:{data.get("kind", "v2ray")}')]])
    await edit_or_answer(callback, 'دسته موردنظر را انتخاب کنید:', reply_markup=kb); await safe_callback_answer(callback)

@router.callback_query(lambda c: (c.data or '').startswith('buy:cat:') or (c.data or '').startswith('buy:catgrp:'))
async def buy_category(callback: CallbackQuery, state: FSMContext):
    data=await state.get_data()
    cat_ids = []
    selected_group = None
    if callback.data.startswith('buy:catgrp:'):
        selected_group = callback.data.split(':')[-1]
        group_map = data.get('category_groups') or {}
        cat_ids = [int(x) for x in group_map.get(str(selected_group), []) if str(x).isdigit()]
    else:
        cid=int(callback.data.split(':')[-1])
        cat_ids=[cid]
    if not cat_ids:
        await edit_or_answer(callback, 'این دسته پیدا نشد. لطفاً دوباره انتخاب کنید.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(f'buy:type:{data.get("kind", "v2ray")}')]])); await safe_callback_answer(callback); return
    await state.update_data(category_id=cat_ids[0], category_ids=cat_ids, selected_category_group=selected_group)
    server_ids = [int(x) for x in (data.get('server_ids') or []) if str(x).isdigit()]
    async with SessionLocal() as session:
        query = select(Plan).where(Plan.category_id.in_(cat_ids), Plan.is_active == True)
        if server_ids:
            query = query.where(Plan.server_id.in_(server_ids))
        plans=(await session.execute(query)).scalars().all()
        plans=sort_by_saved_order(plans, await saved_plan_order(session, 'public'))
    if not plans:
        await edit_or_answer(callback, 'برای این دسته هیچ پلنی ثبت نشده است.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(f'buy:type:{data.get("kind", "v2ray")}')]])); await safe_callback_answer(callback); return
    is_admin = is_admin_user(callback.from_user.id)
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=plan_price_text(p, is_admin), callback_data=f'buy:plan:{p.id}')] for p in plans] + [[back_button(f'buy:type:{data.get("kind", "v2ray")}')]])
    await edit_or_answer(callback, 'پلن موردنظر را انتخاب کنید:', reply_markup=kb); await safe_callback_answer(callback)

@router.callback_query(F.data.startswith('buy:plan:'))
async def buy_plan(callback: CallbackQuery, state: FSMContext):
    pid=int(callback.data.split(':')[-1])
    data = await state.get_data()
    async with SessionLocal() as session:
        plan=await session.get(Plan,pid); server=await session.get(Server, plan.server_id)
        user=(await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one()
    await state.update_data(plan_id=pid, server_id=getattr(server, 'id', None), category_id=getattr(plan, 'category_id', data.get('category_id')))
    selected_group = data.get('selected_category_group')
    back_cb = category_group_callback(selected_group) if selected_group is not None else (f'buy:cat:{getattr(plan, "category_id", data.get("category_id", 0))}' if (getattr(plan, 'category_id', None) or data.get('category_id')) else f'buy:type:{data.get("kind", "v2ray")}')
    await state.set_state(BuyFlow.username)
    if getattr(server, 'server_type', '') == 'mikrotik':
        prompt = MIKROTIK_USERNAME_PROMPT
    else:
        prompt = '👤 لطفاً یوزرنیم اختصاصی را ارسال کنید.'
    await edit_or_answer(callback, prompt, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(back_cb)]])); await safe_callback_answer(callback)

@router.message(BuyFlow.username)
async def buy_username(message: Message, state: FSMContext):
    username = normalize_service_username(message.text)
    data = await state.get_data()
    async with SessionLocal() as session:
        server = await session.get(Server, data['server_id'])
        plan = await session.get(Plan, data['plan_id'])
        user = (await session.execute(select(User).where(User.telegram_id == message.from_user.id))).scalar_one()
        username_error = await get_service_username_error(session, server, username)
        if username_error:
            await state.set_state(BuyFlow.username)
            await ask_for_another_username(message, username_error)
            return
        if is_admin_user(message.from_user.id) and getattr(server, 'server_type', '') != 'mikrotik':
            await create_admin_free_service(message, state, user, server, plan, username)
            return
    await state.update_data(username=username, discount_code=None, final_amount=None)
    if server and getattr(server, 'server_type', '') == 'mikrotik':
        await state.set_state(BuyFlow.password)
        await ui_message(message, MIKROTIK_PASSWORD_PROMPT, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(f'buy:plan:{data.get("plan_id")}')]]))
        return
    await state.set_state(BuyFlow.payment_method)
    data = await state.get_data()
    await ui_message(message, 'روش پرداخت را انتخاب کنید:\n\nاگر کد تخفیف دارید، ابتدا روی «اعمال کد تخفیف» بزنید.', reply_markup=payment_methods_keyboard(data))

@router.message(BuyFlow.password)
async def buy_mikrotik_password(message: Message, state: FSMContext):
    password = message.text or ''
    if not valid_mikrotik_password(password):
        await ui_message(message, '❌ پسورد نباید خالی باشد و نباید فاصله یا کاراکتر سفید داشته باشد؛ حتی یک کاراکتر هم قابل قبول است.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('pay:back_username')]]))
        return
    await state.update_data(password=password)
    data = await state.get_data()
    if is_admin_user(message.from_user.id):
        async with SessionLocal() as session:
            server = await session.get(Server, data['server_id'])
            plan = await session.get(Plan, data['plan_id'])
            user = (await session.execute(select(User).where(User.telegram_id == message.from_user.id))).scalar_one()
            await create_admin_free_service(message, state, user, server, plan, data.get('username') or '', password=password)
        return
    await state.set_state(BuyFlow.payment_method)
    data = await state.get_data()
    await ui_message(message, 'روش پرداخت را انتخاب کنید:\n\nاگر کد تخفیف دارید، ابتدا روی «اعمال کد تخفیف» بزنید.', reply_markup=payment_methods_keyboard(data))

@router.callback_query(F.data == 'pay:discount')
async def buy_discount_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(DiscountInput.code)
    await edit_or_answer(callback, '🏷 کد تخفیف را وارد کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('pay:back_methods')]]))
    await safe_callback_answer(callback)

@router.callback_query(F.data == 'pay:back_methods')
async def buy_discount_back(callback: CallbackQuery, state: FSMContext):
    await show_buy_payment_methods_callback(callback, state, 'گزینه پرداخت را انتخاب کنید:')


@router.callback_query(F.data == 'pay:back_username')
async def buy_password_back_to_username(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.set_state(BuyFlow.username)
    await edit_or_answer(callback, MIKROTIK_USERNAME_PROMPT, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(f'buy:plan:{data.get("plan_id", 0)}')]]))
    await safe_callback_answer(callback)


@router.callback_query(F.data == 'pay:back_methods_from_receipt')
async def buy_receipt_back(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    order_id = data.get('order_id')
    if order_id:
        async with SessionLocal() as session:
            order = await session.get(Order, int(order_id))
            if order and order.status == 'waiting_receipt':
                order.status = 'cancelled'
                await session.commit()
    await state.update_data(order_id=None)
    await show_buy_payment_methods_callback(callback, state, 'یک مرحله برگشتید. روش پرداخت را انتخاب کنید:')

@router.message(DiscountInput.code)
async def buy_discount_apply(message: Message, state: FSMContext):
    code = (message.text or '').strip().upper().replace(' ', '')
    data = await state.get_data()
    async with SessionLocal() as session:
        plan = await session.get(Plan, data['plan_id'])
        user=(await session.execute(select(User).where(User.telegram_id == message.from_user.id))).scalar_one()
        final, err, d = await apply_discount_amount(session, code, plan.price_irt, user.id, 'buy', int(data.get('server_id') or (plan.server_id or 0)))
    if err:
        await ui_message(message, '❌ ' + err, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('pay:back_methods')]])); return
    await state.update_data(discount_code=code, final_amount=final)
    await state.set_state(BuyFlow.payment_method)
    data = await state.get_data()
    await ui_message(message, f'✅ کد تخفیف اعمال شد.\n\nمبلغ قبلی: {plan.price_irt:,} تومان\nمبلغ جدید: {final:,} تومان\n\nحالا روش پرداخت را انتخاب کنید:', reply_markup=payment_methods_keyboard(data, include_discount=False))

async def build_service(session, user, server, plan, username, password: str | None = None):
    service=ClientService(user_id=user.id, server_id=server.id, plan_id=plan.id, client_username=username, xui_email=username, inbound_ids=plan.inbound_ids, total_bytes=plan.volume_gb*1024**3, expires_at=(datetime.utcnow()+timedelta(days=plan.duration_days) if plan.duration_days else None))
    session.add(service); await session.flush()
    sub_link=None
    if server.server_type == 'xui':
        created=await XuiService().create_client_on_plan(server, plan, username)
        sub_link=created.get('sub_link') if isinstance(created, dict) else None
        service.sub_link=sub_link; service.xui_uuid=(str(created.get('uuid')) if isinstance(created, dict) and created.get('uuid') is not None else None)
    elif server.server_type == 'mikrotik':
        created=await MikroTikService().create_user_on_plan(server, plan, username, password=password)
        service.sub_link=None
        service.xui_uuid=str(created.get('password') or password or '')
    return service, sub_link

async def send_service_info(bot, chat_id, username, plan, sub_link, service_id=None, server_type='xui', password=None, server=None):
    await send_service_card(
        bot,
        chat_id,
        username,
        plan.title,
        plan.volume_gb,
        plan.duration_days,
        sub_link,
        is_test=False,
        service_id=service_id,
        server_type=server_type,
        password=password,
        l2tp_server=((server.meta or {}).get('l2tp_server') if server is not None else None),
        l2tp_ipsec_secret=((server.meta or {}).get('l2tp_ipsec_secret') if server is not None else None),
    )

async def create_admin_free_service(message: Message, state: FSMContext, user: User, server: Server, plan: Plan, username: str, password: str | None = None) -> None:
    if not is_admin_user(message.from_user.id):
        await ui_message(message, 'این امکان فقط برای مدیر فعال است.', reply_markup=back_main_inline())
        return
    await ui_message(message, service_building_text(username, plan.title, plan.volume_gb, plan.duration_days))
    async with SessionLocal() as session:
        try:
            db_user = await session.get(User, user.id)
            db_server = await session.get(Server, server.id)
            db_plan = await session.get(Plan, plan.id)
            service, sub_link = await build_service(session, db_user, db_server, db_plan, username, password=(password if db_server.server_type == 'mikrotik' else None))
            session.add(Order(user_id=db_user.id, plan_id=db_plan.id, service_id=service.id, amount_irt=0, payment_method='admin_free', status='paid'))
            await session.commit()
        except Exception as e:
            await session.rollback()
            await handle_user_facing_error(message, e, context='Public buy admin-free service creation failed', reply_markup=back_main_inline())
            await state.clear()
            return
    await state.clear()
    await send_service_info(
        message.bot,
        message.from_user.id,
        service.client_username,
        db_plan,
        sub_link,
        service.id,
        db_server.server_type,
        (service.xui_uuid if db_server.server_type == 'mikrotik' else None),
        db_server,
    )
    await send_service_success_notice(message.bot, message.from_user.id, username=service.client_username, action='create')

@router.callback_query(F.data.in_({'pay:wallet','pay:card','pay:crypto'}))
async def buy_payment(callback: CallbackQuery, state: FSMContext):
    data=await state.get_data()
    async with SessionLocal() as session:
        user=(await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one()
        plan=await session.get(Plan,data['plan_id']); server=await session.get(Server,data['server_id'])
        username = data.get('username') or ''
        username_error = await get_service_username_error(session, server, username)
        if username_error:
            await state.set_state(BuyFlow.username)
            await ui_callback_message(callback, username_error, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(f'buy:plan:{data.get("plan_id", 0)}')]]))
            await safe_callback_answer(callback)
            return
        final_amount = int(data.get('final_amount') or plan.price_irt)
        discount_code = data.get('discount_code')
        discount_obj = None
        if discount_code:
            final_amount, err, discount_obj = await apply_discount_amount(session, discount_code, plan.price_irt, user.id, 'buy', server.id if server else None)
            if err:
                await ui_callback_message(callback, '❌ ' + err, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('pay:discount')]])); await safe_callback_answer(callback); return
        if callback.data == 'pay:crypto':
            order = Order(user_id=user.id, plan_id=plan.id, amount_irt=final_amount, payment_method=f'crypto:{data["username"]}' + (f':discount:{discount_code}' if discount_code else ''), status='waiting_crypto')
            session.add(order)
            await session.flush()
            try:
                pay = await NowPaymentsService().create_payment(order_id=order.id, amount_irt=final_amount, description=f'D Bot - {plan.title}')
            except Exception as e:
                await session.rollback()
                await handle_user_facing_error(callback, e, context='Public buy crypto payment creation failed', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('pay:back_methods')]]))
                await safe_callback_answer(callback); return
            order.external_payment_id = str(pay.get('payment_id') or '')
            order.external_invoice_url = pay.get('invoice_url') or pay.get('payment_url') or None
            await mark_discount_used(session, discount_obj, user.id, 'buy')
            await session.commit(); await state.clear()
            pay_amount = pay.get('pay_amount') or '-'
            pay_currency = (pay.get('pay_currency') or settings.NOWPAYMENTS_PAY_CURRENCY).upper()
            address = pay.get('pay_address') or '-'
            text = (
                f'🪙 پرداخت کریپتو ساخته شد\n\n'
                f'💰 مبلغ پرداخت: {pay_amount} {pay_currency}\n'
                f'📥 آدرس کیف پول:\n`{address}`\n\n'
                f'بعد از تایید شبکه، سفارش خودکار قابل پیگیری است. شناسه سفارش: #{order.id}'
            )
            if order.external_invoice_url:
                text += f'\n\n🔗 لینک پرداخت:\n{order.external_invoice_url}'
            await ui_callback_message(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('pay:back_methods')]]))
            await safe_callback_answer(callback); return

        if callback.data == 'pay:wallet':
            field=wallet_field(server.server_type); balance=getattr(user, field, 0) or 0
            if balance < final_amount:
                await ui_callback_message(callback, 'موجودی کیف پول اصلی کافی نیست. لطفاً کیف پول را شارژ کنید و دوباره تلاش کنید.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('pay:back_methods')]])); await safe_callback_answer(callback); return
            setattr(user, field, balance - final_amount)
            await send_buyer_notice(callback.message.bot, callback.from_user.id, service_building_text(data['username'], plan.title, plan.volume_gb, plan.duration_days))
            try:
                service, sub_link = await build_service(session, user, server, plan, data['username'], password=(data.get('password') if server.server_type == 'mikrotik' else None))
            except Exception as e:
                await session.rollback(); await handle_user_facing_error(callback, e, context='Public buy wallet service creation failed', reply_markup=back_main_inline()); await state.clear(); await safe_callback_answer(callback); return
            
            await mark_discount_used(session, discount_obj, user.id, 'buy')
            session.add(Order(user_id=user.id, plan_id=plan.id, service_id=service.id, amount_irt=final_amount, payment_method=('wallet' + (f':discount:{discount_code}' if discount_code else '')), status='paid'))
            commission_amount = await apply_purchase_commission(session, user, int(final_amount or 0), callback.message.bot, server.server_type)
            await session.commit(); await state.clear(); await safe_callback_answer(callback)
            await send_service_info(callback.message.bot, callback.from_user.id, service.client_username, plan, sub_link, service.id, server.server_type, (service.xui_uuid if server.server_type == 'mikrotik' else None), server)
            await send_service_success_notice(callback.message.bot, callback.from_user.id, username=service.client_username, action='create')
            return
        card=(await session.execute(select(PaymentCard).where(PaymentCard.server_id == server.id, PaymentCard.is_active == True))).scalar_one_or_none()
        if not card:
            card=(await session.execute(select(PaymentCard).where(PaymentCard.server_type == server.server_type, PaymentCard.server_id.is_(None), PaymentCard.is_active == True))).scalar_one_or_none()
        if not card:
            await ui_callback_message(callback, 'برای این سرور هنوز شماره کارت ثبت نشده است.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('pay:back_methods')]])); await safe_callback_answer(callback); return
        
        await mark_discount_used(session, discount_obj, user.id, 'buy')
        order=Order(user_id=user.id, plan_id=plan.id, amount_irt=final_amount, payment_method=f'card:{data["username"]}' + (f':discount:{discount_code}' if discount_code else ''), status='waiting_receipt', external_invoice_url=(('mtpass:' + data.get('password', '')) if server.server_type == 'mikrotik' and data.get('password') else None))
        session.add(order); await session.commit(); await state.update_data(order_id=order.id)
    await state.set_state(BuyFlow.receipt)
    await ui_callback_message(callback, f'لطفاً مبلغ {final_amount:,} تومان را به کارت زیر واریز کنید و عکس رسید را ارسال کنید:\n\nشماره کارت: {card.card_number}\nنام صاحب حساب: {card.owner_name}', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('pay:back_methods_from_receipt')]])); await safe_callback_answer(callback)

@router.message(BuyFlow.receipt, F.photo)
async def buy_receipt(message: Message, state: FSMContext):
    data=await state.get_data(); file_id=message.photo[-1].file_id
    async with SessionLocal() as session:
        order=await session.get(Order,data['order_id']); order.receipt_file_id=file_id
        plan=await session.get(Plan, order.plan_id); server=await session.get(Server, plan.server_id)
        renew_service = await session.get(ClientService, order.service_id) if (order.service_id and (order.payment_method or '').startswith('renew:')) else None
        await session.commit()
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='✅ تایید رسید', callback_data=f'order:approve:{data["order_id"]}')],[InlineKeyboardButton(text='❌ رد رسید', callback_data=f'order:reject:{data["order_id"]}')]])
    discount_code = None
    if order.payment_method and ':discount:' in order.payment_method:
        discount_code = order.payment_method.split(':discount:', 1)[1]
    original_amount = int(plan.price_irt or 0)
    discount_info = f'🏷 کد تخفیف: {discount_code}\n💵 مبلغ نهایی: {order.amount_irt:,} تومان\n' if discount_code else ''
    order_kind = '🔁 نوع سفارش: تمدید\n' if renew_service else '🆕 نوع سفارش: خرید جدید\n'
    caption = (
        f'🧾 رسید سفارش #{data["order_id"]}\n'
        f'━━━━━━━━━━━━━━\n'
        f'{order_kind}'
        f'👤 نام مشتری: {message.from_user.full_name}\n'
        f'🔢 آیدی عددی: {message.from_user.id}\n'
        f'🆔 یوزرنیم تلگرام: {message.from_user.username or "ندارد"}\n\n'
        f'👥 یوزرنیم سرویس: {data.get("username")}\n'
        + (f'🔐 پسورد انتخابی: {data.get("password")}\n' if data.get('password') else '')
        + (f'🔗 سرویس فعلی: #{renew_service.id}\n' if renew_service else '')
        + f'📦 پلن: {plan.title}\n'
        f'💰 مبلغ: {original_amount:,} تومان\n'
        f'{discount_info}'
        f'🖥 سرور: {server.name}\n'
        f'━━━━━━━━━━━━━━\n'
        f'لطفاً رسید را بررسی کنید.'
    )
    for aid in settings.admin_ids:
        await message.bot.send_photo(aid, file_id, caption=caption, reply_markup=kb)
    await state.clear(); await ui_message(message, RECEIPT_RECEIVED_TEXT, reply_markup=receipt_received_keyboard())

async def process_approved_order_background(
    order_id: int,
    bot,
    admin_chat_id: int | None = None,
    admin_receipt_chat_id: int | None = None,
    admin_receipt_message_id: int | None = None,
) -> None:
    """Provision the approved order outside the admin callback response path."""
    buyer_chat_id = None
    buyer_is_admin = False
    plan_title = 'نامشخص'
    plan_volume_gb = 0
    plan_duration_days = 0
    service_username = None
    service_sub_link = None
    service_id = None
    service_password = None
    service_expires_at = None
    server_type_value = 'xui'
    server_meta_value = {}
    is_renewal_order = False
    commission_amount = 0
    order_amount_irt = 0

    try:
        async with SessionLocal() as session:
            try:
                order = await session.get(Order, order_id)
                if not order:
                    await send_admin_notice(bot, admin_chat_id, f'❌ سفارش #{order_id} پیدا نشد.')
                    await edit_admin_receipt_keyboard(bot, admin_receipt_chat_id, admin_receipt_message_id, failed_retry_keyboard(order_id, is_renewal=is_renewal_order))
                    return
                if order.status == 'paid':
                    await edit_admin_receipt_keyboard(bot, admin_receipt_chat_id, admin_receipt_message_id, approved_only_keyboard('✅ رسید تایید شد.'))
                    await send_admin_notice(bot, admin_chat_id, f'✅ سفارش #{order_id} قبلاً پرداخت‌شده ثبت شده است.')
                    return
                if order.status != 'processing':
                    # The callback handler normally sets this before scheduling the task.
                    # Keeping this fallback makes direct/retry calls safe too.
                    order.status = 'processing'
                    await session.flush()

                user = await session.get(User, order.user_id)
                plan = await session.get(Plan, order.plan_id) if order.plan_id else None
                if not user or not plan:
                    raise RuntimeError(f'Order #{order_id} is missing user or plan')

                service = None
                if order.payment_method and order.payment_method.startswith('renew:') and order.service_id:
                    service = await session.get(ClientService, order.service_id)
                    server = await session.get(Server, service.server_id) if service else None
                else:
                    server = await session.get(Server, plan.server_id) if plan else None

                if not server:
                    raise RuntimeError(f'Order #{order_id} is missing server')
                if order.payment_method and order.payment_method.startswith('renew:') and order.service_id and not service:
                    raise RuntimeError(f'Order #{order_id} renewal service not found')

                buyer_chat_id = int(user.telegram_id)
                buyer_is_admin = buyer_chat_id in settings.admin_ids
                order_amount_irt = int(order.amount_irt or 0)
                plan_title = plan.title
                plan_volume_gb = plan.volume_gb
                plan_duration_days = plan.duration_days
                server_type_value = server.server_type if server else 'xui'
                server_meta_value = dict(server.meta or {}) if server else {}

                username = (
                    order.payment_method.split(':', 1)[1].split(':discount:', 1)[0]
                    if order.payment_method and (order.payment_method.startswith('card:') or order.payment_method.startswith('crypto:'))
                    else f'user{user.telegram_id}_{order.id}'
                )
                pending_password = ''
                if server and server.server_type == 'mikrotik' and (order.external_invoice_url or '').startswith('mtpass:'):
                    pending_password = (order.external_invoice_url or '')[7:]

                is_renewal_order = bool(order.payment_method and order.payment_method.startswith('renew:') and order.service_id)

                if is_renewal_order:
                    building_username = service.client_username or service.xui_email or username
                    await send_buyer_notice(bot, buyer_chat_id, service_building_text(building_username, plan.title, plan.volume_gb, plan.duration_days, action='تمدید'))
                    if server.server_type == 'xui':
                        await XuiService().reset_client_plan(server, service.xui_email, plan.volume_gb, plan.duration_days)
                    elif server.server_type == 'mikrotik':
                        await MikroTikService().renew_user(server, service.xui_email or service.client_username, volume_gb=plan.volume_gb, expire_days=plan.duration_days)
                    service.plan_id = plan.id
                    service.total_bytes = plan.volume_gb * 1024**3
                    service.used_bytes = 0
                    service.expires_at = datetime.utcnow() + timedelta(days=plan.duration_days) if plan.duration_days else None
                    service.is_active = True
                    service.disabled_at = None
                    service.disabled_reason = None
                    service.disabled_notify_count = 0
                    service.disabled_last_notified_at = None
                    sub_link = service.sub_link
                else:
                    await send_buyer_notice(bot, buyer_chat_id, service_building_text(username, plan.title, plan.volume_gb, plan.duration_days))
                    service, sub_link = await build_service(session, user, server, plan, username, password=(pending_password or None))

                service_username = service.client_username or service.xui_email
                service_sub_link = sub_link
                service_id = service.id
                service_password = service.xui_uuid if (server.server_type == 'mikrotik') else None
                service_expires_at = service.expires_at
                order.status = 'paid'
                order.service_id = service.id
                commission_amount = await apply_purchase_commission(session, user, int(order.amount_irt or 0), bot, server.server_type)
                await session.commit()
            except Exception:
                await session.rollback()
                raise

        await edit_admin_receipt_keyboard(bot, admin_receipt_chat_id, admin_receipt_message_id, approved_only_keyboard('✅ رسید تایید شد.'))

        if is_renewal_order:
            await send_renewal_confirmation(
                bot,
                buyer_chat_id,
                username=service_username,
                plan_title=plan_title,
                volume_gb=plan_volume_gb,
                duration_days=plan_duration_days,
                expires_at=service_expires_at,
                server_type=server_type_value,
                amount_irt=order_amount_irt,
            )
        else:
            await send_service_card(
                bot,
                buyer_chat_id,
                service_username,
                plan_title,
                plan_volume_gb,
                plan_duration_days,
                service_sub_link,
                is_test=False,
                service_id=service_id,
                server_type=server_type_value,
                password=service_password,
                l2tp_server=server_meta_value.get('l2tp_server'),
                l2tp_ipsec_secret=server_meta_value.get('l2tp_ipsec_secret'),
            )
            await send_service_success_notice(
                bot,
                buyer_chat_id,
                username=service_username,
                action='create',
            )

        admin_text = (
            ('✅ رسید تایید شد و پیام تایید تمدید برای خریدار ارسال شد.\n\n' if is_renewal_order else '✅ رسید تایید شد و سرویس فقط برای خریدار ارسال شد.\n\n')
            + f'👤 خریدار: {buyer_chat_id}\n'
            f'📦 پلن: {plan_title}\n'
            f'🔐 کانفیگ: {service_username}'
        )
        if commission_amount:
            admin_text += f'\n🎁 پورسانت معرف: {commission_amount:,} تومان'
        await send_admin_notice(bot, admin_chat_id, admin_text)
        if admin_chat_id and admin_chat_id != buyer_chat_id:
            await send_home(bot, admin_chat_id, True)

    except Exception as exc:
        order_is_paid = False
        try:
            async with SessionLocal() as session:
                order = await session.get(Order, order_id)
                if order and order.status == 'paid':
                    order_is_paid = True
                elif order:
                    order.status = 'failed'
                    await session.commit()
        except Exception:
            pass

        if order_is_paid:
            await edit_admin_receipt_keyboard(bot, admin_receipt_chat_id, admin_receipt_message_id, approved_only_keyboard('✅ رسید تایید شد.'))
            await report_bot_error(bot, exc, context=f'Background admin approval delivery failed after paid order_id={order_id}')
            await send_admin_notice(
                bot,
                admin_chat_id,
                '⚠️ سرویس ساخته و سفارش paid شد، اما ارسال پیام نهایی/کارت سرویس با خطا مواجه شد.\n\n'
                f'شماره سفارش: #{order_id}\n'
                'جزئیات فنی خطا برای ادمین‌ها ارسال شد.'
            )
            return

        await edit_admin_receipt_keyboard(bot, admin_receipt_chat_id, admin_receipt_message_id, failed_retry_keyboard(order_id, is_renewal=is_renewal_order))
        await report_bot_error(bot, exc, context=f'Background admin approval service provisioning failed order_id={order_id}')
        await send_admin_notice(
            bot,
            admin_chat_id,
            (('❌ رسید تایید شد، اما تمدید سرویس روی پنل با خطا مواجه شد.\n\n' if is_renewal_order else '❌ رسید تایید شد، اما خرید جدید روی پنل با خطا مواجه شد.\n\n')
            + f'شماره سفارش: #{order_id}\n'
            + ('دکمه «تلاش مجدد تمدید» روی همان رسید فعال شد. ' if is_renewal_order else 'دکمه «تلاش مجدد خرید جدید» روی همان رسید فعال شد. ')
            + 'جزئیات فنی خطا برای ادمین‌ها ارسال شد.')
        )
        if buyer_chat_id:
            await send_buyer_notice(
                bot,
                buyer_chat_id,
                (('✅ رسید شما تایید شد، اما تمدید سرویس با مشکل موقت مواجه شده است.\n' if is_renewal_order else '✅ رسید شما تایید شد، اما خرید جدید با مشکل موقت مواجه شده است.\n')
                + 'پشتیبانی در حال بررسی است و نتیجه از همین ربات اطلاع‌رسانی می‌شود.')
            )


@router.callback_query(F.data.startswith('order:approve:'))
async def approve_order_cb(callback: CallbackQuery):
    if callback.from_user.id not in settings.admin_ids:
        return

    oid = int(callback.data.split(':')[-1])
    bot = callback.message.bot if callback.message else getattr(callback, 'bot', None)
    admin_chat_id = callback.message.chat.id if callback.message else callback.from_user.id
    admin_receipt_chat_id = callback.message.chat.id if callback.message else None
    admin_receipt_message_id = callback.message.message_id if callback.message else None

    async with SessionLocal() as session:
        order = await session.get(Order, oid)
        if not order:
            await mark_message_status(callback, '❌ سفارش پیدا نشد.')
            await safe_callback_answer(callback, 'سفارش پیدا نشد.', show_alert=True)
            return

        is_renewal = bool((order.payment_method or '').startswith('renew:') and order.service_id)
        operation_name = 'تمدید' if is_renewal else 'خرید جدید'

        if order.status == 'paid':
            await mark_message_status(callback, '✅ رسید تایید شد.')
            await safe_callback_answer(callback, 'این سفارش قبلاً انجام شده است.', show_alert=True)
            return
        if order.status == 'processing':
            await mark_message_status(callback, f'⏳ {operation_name} در حال انجام است...')
            await safe_callback_answer(callback, f'{operation_name} در حال انجام است.', show_alert=False)
            return
        if order.status in {'rejected', 'cancelled'}:
            await mark_message_status(callback, '❌ این رسید قبلاً رد/لغو شده است.')
            await safe_callback_answer(callback, 'این رسید قبلاً رد یا لغو شده است.', show_alert=True)
            return
        if order.status not in {'waiting_receipt', 'failed'}:
            await mark_message_status(callback, f'⚠️ وضعیت سفارش: {order.status}')
            await safe_callback_answer(callback, f'وضعیت سفارش: {order.status}', show_alert=True)
            return

        order.status = 'processing'
        await session.commit()

    await safe_callback_answer(callback, f'رسید تایید شد؛ {operation_name} در پس‌زمینه شروع شد.', show_alert=False)
    await edit_admin_receipt_keyboard(
        bot,
        admin_receipt_chat_id,
        admin_receipt_message_id,
        processing_only_keyboard(f'⏳ {operation_name} در حال انجام...'),
    )
    await send_admin_notice(bot, admin_chat_id, f'✅ رسید سفارش #{oid} تایید شد. {operation_name} در پس‌زمینه شروع شد.')

    asyncio.create_task(process_approved_order_background(
        oid,
        bot,
        admin_chat_id=admin_chat_id,
        admin_receipt_chat_id=admin_receipt_chat_id,
        admin_receipt_message_id=admin_receipt_message_id,
    ))


@router.callback_query(F.data.startswith('order:reject:'))
async def reject_order_cb(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in settings.admin_ids:
        return
    oid = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        order = await session.get(Order, oid)
        if not order:
            await mark_message_status(callback, '❌ سفارش پیدا نشد.')
            await safe_callback_answer(callback, 'سفارش پیدا نشد.', show_alert=True)
            return
        if order.status == 'paid':
            await mark_message_status(callback, '✅ این رسید قبلاً تایید شده است.')
            await safe_callback_answer(callback, 'این رسید قبلاً تایید شده است.', show_alert=True)
            return
        if order.status == 'processing':
            await mark_message_status(callback, '⏳ سرویس در حال ساخت است.')
            await safe_callback_answer(callback, 'در زمان ساخت امکان رد رسید نیست.', show_alert=True)
            return
        if order.status == 'rejected':
            await mark_message_status(callback, '❌ رسید رد شد')
            await safe_callback_answer(callback, 'این رسید قبلاً رد شده است.', show_alert=True)
            return

    await state.clear()
    await state.update_data(
        reject_order_id=oid,
        reject_receipt_chat_id=(callback.message.chat.id if callback.message else callback.from_user.id),
        reject_receipt_message_id=(callback.message.message_id if callback.message else None),
    )
    await state.set_state(OrderReceiptReject.reason)
    await mark_message_status(callback, '✍️ دلیل رد را ارسال کنید')
    await callback.message.answer(
        f"""✍️ دلیل رد رسید سفارش #{oid} را بنویسید.

همین متن برای کاربر ارسال و در سابقه سفارش ذخیره می‌شود."""
    )
    await safe_callback_answer(callback, 'دلیل رد را به‌صورت پیام ارسال کنید.', show_alert=False)


@router.message(OrderReceiptReject.reason)
async def reject_order_reason(message: Message, state: FSMContext):
    if message.from_user.id not in settings.admin_ids:
        return
    reason = (message.text or '').strip()
    if not reason:
        await message.answer('❌ دلیل رد نمی‌تواند خالی باشد. لطفاً متن دلیل را ارسال کنید.')
        return
    if len(reason) > 1500:
        await message.answer('❌ متن دلیل خیلی طولانی است. حداکثر ۱۵۰۰ کاراکتر ارسال کنید.')
        return

    data = await state.get_data()
    oid = int(data.get('reject_order_id') or 0)
    receipt_chat_id = data.get('reject_receipt_chat_id')
    receipt_message_id = data.get('reject_receipt_message_id')
    async with SessionLocal() as session:
        order = await session.get(Order, oid)
        if not order:
            await state.clear()
            await message.answer('❌ سفارش پیدا نشد.')
            return
        if order.status == 'paid':
            await state.clear()
            await edit_admin_receipt_keyboard(message.bot, receipt_chat_id, receipt_message_id, status_only_keyboard('✅ رسید تایید شد'))
            await message.answer('این رسید قبلاً تایید شده است.')
            return
        if order.status == 'processing':
            await state.clear()
            await edit_admin_receipt_keyboard(message.bot, receipt_chat_id, receipt_message_id, status_only_keyboard('⏳ سرویس در حال ساخت است'))
            await message.answer('سرویس در حال ساخت است و رسید قابل رد نیست.')
            return
        if order.status == 'rejected':
            await state.clear()
            await edit_admin_receipt_keyboard(message.bot, receipt_chat_id, receipt_message_id, status_only_keyboard('❌ رسید رد شد'))
            await message.answer('این رسید قبلاً رد شده است.')
            return
        user = await session.get(User, order.user_id)
        plan = await session.get(Plan, order.plan_id) if order.plan_id else None
        if (order.payment_method or '').startswith('renew:') and ':discount:' in (order.payment_method or ''):
            await release_order_discount_usage(
                session,
                order_id=order.id,
                user_id=order.user_id,
                code=order.payment_method.split(':discount:', 1)[1],
                source='renew',
            )
        order.status = 'rejected'
        order.rejection_reason = reason
        order.rejected_by = message.from_user.id
        order.rejected_at = datetime.utcnow()
        await session.commit()

    await edit_admin_receipt_keyboard(
        message.bot, receipt_chat_id, receipt_message_id, status_only_keyboard('❌ رسید رد شد')
    )
    if user:
        kind = 'تمدید سرویس' if (order.payment_method or '').startswith('renew:') else 'خرید سرویس'
        rejection_text = (
            f"""❌ رسید شما رد شد.

🧾 شماره سفارش: #{oid}
📌 نوع درخواست: {kind}
📦 تعرفه: {plan.title if plan else '-'}
💰 مبلغ: {int(order.amount_irt or 0):,} تومان

📝 دلیل رد:
{reason}"""
        )
        await message.bot.send_message(
            user.telegram_id,
            rejection_text,
            reply_markup=success_home_keyboard(),
        )
    await state.clear()
    try:
        await message.delete()
    except Exception:
        pass
    await send_home(message.bot, message.from_user.id, True)


def query_home_keyboard(back_cb: str = 'back:main') -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[back_button(back_cb)]])


def query_result_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [back_button('menu:query')],
        [InlineKeyboardButton(text='🏠 خانه', callback_data='home:main')],
    ])


def _query_server_label(server: Server) -> str:
    meta = server.meta or {}
    name = str(meta.get('display_name') or server.name or '').strip()
    if server.server_type == 'mikrotik':
        router = str(meta.get('router_name') or server.username or '').strip()
        return f'{name} ({router})' if router and router not in name else name
    return name


def _query_needs_password(server: Server) -> bool:
    meta = server.meta or {}
    protocol = str(meta.get('default_protocol') or '').lower()
    return server.server_type in ('mikrotik', 'openvpn', 'l2tp') or protocol in ('openvpn', 'l2tp')


async def _query_public_servers(session) -> list[Server]:
    rows = (await session.execute(select(Server).where(Server.is_active == True).order_by(Server.id.asc()))).scalars().all()
    return [s for s in rows if ((s.meta or {}).get('scope') or 'public') in ('public', 'all')]


async def _query_public_servers_by_type(session, stype: str) -> list[Server]:
    rows = (await session.execute(
        select(Server).where(Server.is_active == True, Server.server_type == stype).order_by(Server.id.asc())
    )).scalars().all()
    return [s for s in rows if ((s.meta or {}).get('scope') or 'public') in ('public', 'all')]


def query_category_group_callback(index: str | int) -> str:
    return f'query:catgrp:{index}'


async def _query_prompt_username(callback: CallbackQuery, state: FSMContext, server_ids: list[int], *, back_cb: str = 'menu:query') -> None:
    async with SessionLocal() as session:
        servers = (await session.execute(select(Server).where(Server.id.in_(server_ids), Server.is_active == True))).scalars().all() if server_ids else []
    if not servers:
        await ui_callback_message(callback, 'برای این نوع سرویس، سرور فعالی جهت استعلام پیدا نشد.', reply_markup=query_home_keyboard(back_cb))
        await safe_callback_answer(callback)
        return
    server_type = (await state.get_data()).get('server_type') or (servers[0].server_type if servers else '')
    await state.update_data(
        query_server_ids=[s.id for s in servers],
        server_id=None,
        needs_password=False,
        server_type=server_type,
    )
    await state.set_state(QueryClient.username)
    if server_type == 'mikrotik':
        text = (
            '👤 یوزرنیم سرویس OpenVPN / MikroTik را ارسال کنید.\n\n'
            'ربات فقط داخل سرورهای متصل به همین نوع سرویس جست‌وجو می‌کند و بعد از پیدا شدن، مشخصات کامل کانفیگ را نمایش می‌دهد.'
        )
    else:
        text = (
            '👤 یوزرنیم اختصاصی V2Ray را ارسال کنید.\n\n'
            'ربات فقط داخل سرورهای متصل به همین نوع سرویس جست‌وجو می‌کند و بعد از پیدا شدن، مشخصات کامل کانفیگ را نمایش می‌دهد.'
        )
    await ui_callback_message(callback, text, reply_markup=query_home_keyboard(back_cb))
    await safe_callback_answer(callback)


def _openvpn_expire_value(local: ClientService | None, remote: dict | None):
    remote_exp = _remote_value(remote, 'expire_at', 'expires_at', 'expiry', 'expiration', 'valid_until')
    return remote_exp or (local.expires_at if local else None)

def _openvpn_active(local: ClientService | None, remote: dict | None) -> bool:
    if isinstance(remote, dict):
        if bool(remote.get('disabled') or remote.get('expired')):
            return False
        if 'enabled' in remote:
            return bool(remote.get('enabled'))
        if 'active' in remote:
            return bool(remote.get('active'))
    return bool(local.is_active) if local else True

def _openvpn_result_text(server: Server, username: str, password: str, local: ClientService | None, plan: Plan | None, remote: dict | None = None) -> str:
    local_total = int(local.total_bytes or 0) if local else 0
    local_used = int(local.used_bytes or 0) if local else 0
    used = _remote_used_bytes(remote) if remote else local_used
    if remote and used <= 0 and local_used > 0:
        used = local_used
    total = _remote_total_bytes(remote, local_total) if remote else local_total
    remaining = _remote_remaining_bytes(remote, total, used) if remote else max(total - used, 0) if total else None
    active = _openvpn_active(local, remote)
    status_icon = '🟢' if active else '🔴'
    status_text = 'فعال' if active else 'غیرفعال'
    expires_at = _openvpn_expire_value(local, remote)
    password_text = password or (local.xui_uuid if local and local.xui_uuid else '-')
    lines = [
        '✅ مشخصات سرویس OpenVPN / MikroTik پیدا شد',
        '╭━━━━━━━━━━━━━━━━━━━━╮',
        f'│ 🖥 سرور: {_query_server_label(server)}',
        f'│ 👤 Username: {username}',
        f'│ 🔐 Password: {password_text}',
        f'│ {status_icon} وضعیت: {status_text}',
        f'│ 📦 پلن: {plan.title if plan else "نامشخص"}',
        f'│ ⏳ انقضا: {fa_date(expires_at) if expires_at else "نامحدود"}',
        '│',
        '│ 📊 وضعیت حجم و مصرف',
    ]
    lines += _usage_lines(total, used, remaining)
    if remote:
        lines += [
            '│',
            f'│ 🌐 IP ریموت: {remote.get("remote_address") or remote.get("ip") or "-"}',
            f'│ 🔌 آنلاین: {"بله" if remote.get("online") else "خیر"}',
            f'│ 🚦 وضعیت پنل: {"غیرفعال" if remote.get("disabled") else "فعال"}',
            f'│ ⚡ سرعت صف: {remote.get("queue_max_limit") or remote.get("rate_limit") or "-"}',
        ]
    if local and local.sub_link:
        lines.append(f'│ 🔗 لینک/فایل: {local.sub_link}')
    lines += ['╰━━━━━━━━━━━━━━━━━━━━╯', '', '— ✦ D Bot ✦ —']
    return '\n'.join(lines)


def _client_username_match(username: str):
    return (
        (ClientService.client_username == username)
        | (ClientService.xui_email == username)
        | (ClientService.xui_uuid == username)
    )


async def _find_local_query_service(session, server_ids: list[int], username: str) -> ClientService | None:
    if not server_ids or not username:
        return None
    return (await session.execute(
        select(ClientService)
        .where(ClientService.server_id.in_(server_ids), _client_username_match(username))
        .order_by(ClientService.is_active.desc(), ClientService.id.desc())
    )).scalars().first()


async def _render_local_query_service(session, server: Server, local: ClientService, username: str, password: str = '') -> str:
    plan = await session.get(Plan, local.plan_id) if local and local.plan_id else None
    if server.server_type == 'mikrotik':
        remote = None
        try:
            remote = await MikroTikService().get_user(server, local.client_username or username)
        except Exception:
            remote = None
        return _openvpn_result_text(server, local.client_username or username, password, local, plan, remote)

    used = int(local.used_bytes or 0)
    total = int(local.total_bytes or 0)
    active = bool(local.is_active)
    uuid = local.xui_uuid or None
    try:
        found = await XuiService().find_client_any(server, local.xui_email or local.client_username or username) if server.server_type == 'xui' else None
    except Exception:
        found = None
    if found:
        c = found.get('client', {}) or {}
        tr = found.get('traffic') or {}
        up = int(tr.get('up', 0) or 0)
        down = int(tr.get('down', 0) or 0)
        remote_total = int(tr.get('total', c.get('totalGB', 0)) or 0)
        used = (up + down) or used
        total = remote_total or total
        active = bool(c.get('enable', active))
        uuid = c.get('id') or uuid
    return pretty_config_result(
        username=local.client_username or local.xui_email or username,
        active=active,
        plan_title=plan.title if plan else 'نامشخص',
        created_at=fa_date(local.created_at, empty='-') if local.created_at else '-',
        expires_at=fa_date(local.expires_at) if local.expires_at else 'نامحدود',
        total=total,
        used=used,
        uuid=uuid,
    )


async def _process_query_lookup(message: Message, state: FSMContext, password: str = '') -> None:
    data = await state.get_data()
    selected_server_id = int(data.get('server_id') or 0)
    if selected_server_id:
        server_ids = [selected_server_id]
    else:
        server_ids = [int(x) for x in (data.get('query_server_ids') or []) if str(x).isdigit()]
    username = extract_key(str(data.get('username') or message.text or ''))
    result_text = ''
    if not server_ids:
        await state.clear()
        await ui_message(message, 'برای استعلام، اول نوع سرویس کانفیگ را انتخاب کنید.', reply_markup=query_home_keyboard())
        return

    async with SessionLocal() as session:
        servers = (await session.execute(
            select(Server).where(Server.id.in_(server_ids), Server.is_active == True).order_by(Server.id.asc())
        )).scalars().all()
        server_map = {s.id: s for s in servers}
        if not servers:
            await state.clear()
            await ui_message(message, 'برای این نوع سرویس، سرور فعالی پیدا نشد. لطفاً دوباره تلاش کنید.', reply_markup=query_home_keyboard())
            return

        # First, use the bot database to find the exact server already connected to this username.
        # This prevents searching unrelated servers and makes the lookup follow the user's chosen service type.
        local = await _find_local_query_service(session, list(server_map.keys()), username)
        if local and local.server_id in server_map:
            result_text = await _render_local_query_service(session, server_map[local.server_id], local, username, password)
        else:
            # Fallback for configs that exist on the panel but are not stored locally yet.
            for server in servers:
                if server.server_type == 'mikrotik':
                    remote = None
                    try:
                        remote = await MikroTikService().get_user(server, username)
                    except Exception:
                        remote = None
                    if remote:
                        result_text = _openvpn_result_text(server, username, password, None, None, remote)
                        break
                    continue

                found = None
                try:
                    found = await XuiService().find_client_any(server, username, exhaustive=True) if server.server_type == 'xui' else None
                except Exception:
                    found = None
                if found:
                    c = found.get('client', {}) or {}
                    tr = found.get('traffic') or {}
                    up = int(tr.get('up', 0) or 0)
                    down = int(tr.get('down', 0) or 0)
                    total = int(tr.get('total', c.get('totalGB', 0)) or 0)
                    result_text = pretty_config_result(
                        username=c.get('email') or username or '-',
                        active=bool(c.get('enable', True)),
                        plan_title='نامشخص',
                        created_at='-',
                        expires_at='-',
                        total=total or 0,
                        used=(up or 0) + (down or 0),
                        uuid=c.get('id') or None,
                    )
                    break
    await state.clear()
    await ui_message(message, result_text or 'کانفیگ با این یوزرنیم داخل سرورهای متصل به نوع سرویس انتخاب‌شده پیدا نشد.', reply_markup=query_result_keyboard())

@router.callback_query(F.data == CB_QUERY)
async def query_start(callback: CallbackQuery, state: FSMContext):
    async with SessionLocal() as session:
        service_types = await get_public_service_types(session)
    await state.clear()
    rows = []
    for kind, label, stype in service_types:
        icon = '🔵' if stype == 'xui' else ('🟠' if stype == 'mikrotik' else '🟣')
        rows.append([InlineKeyboardButton(text=f'{icon} {label}', callback_data=f'query:type:{kind}')])
    if not rows:
        rows.append([InlineKeyboardButton(text='فعلاً نوع سرویس فعالی برای استعلام ثبت نشده', callback_data='noop')])
    rows.append([back_button('back:main')])
    await ui_callback_message(callback, 'نوع سرویس کانفیگ را انتخاب کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await safe_callback_answer(callback)


@router.callback_query(F.data.startswith('query:type:'))
async def query_pick_type(callback: CallbackQuery, state: FSMContext):
    kind = callback.data.split(':')[-1]
    async with SessionLocal() as session:
        service_types = await get_public_service_types(session)
        matched = next((row for row in service_types if row[0] == kind), None)
        stype = matched[2] if matched else server_type_filter(kind)
        label = matched[1] if matched else ('OpenVPN / MikroTik' if stype == 'mikrotik' else 'V2Ray')
        servers = await _query_public_servers_by_type(session, stype)
        server_ids = [s.id for s in servers]
    await state.update_data(
        query_kind=kind,
        query_service_label=label,
        server_type=stype,
        query_server_ids=server_ids,
        server_id=None,
        needs_password=False,
    )
    if not servers:
        await ui_callback_message(callback, 'برای این نوع سرویس، سرور فعالی جهت استعلام ثبت نشده است.', reply_markup=query_home_keyboard('menu:query'))
        await safe_callback_answer(callback)
        return
    await _query_prompt_username(callback, state, server_ids, back_cb='menu:query')


@router.callback_query(lambda c: (c.data or '').startswith('query:catgrp:') or (c.data or '').startswith('query:cat:'))
async def query_pick_category(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if callback.data.startswith('query:catgrp:'):
        group_key = callback.data.split(':')[-1]
        group_map = data.get('query_category_groups') or {}
        cat_ids = [int(x) for x in group_map.get(str(group_key), []) if str(x).isdigit()]
        back_cb = f'query:type:{data.get("query_kind", "v2ray")}'
    else:
        cat_ids = [int(callback.data.split(':')[-1])]
        back_cb = f'query:type:{data.get("query_kind", "v2ray")}'
    if not cat_ids:
        await ui_callback_message(callback, 'این دسته پیدا نشد. دوباره انتخاب کنید.', reply_markup=query_home_keyboard(back_cb))
        await safe_callback_answer(callback)
        return
    all_server_ids = [int(x) for x in (data.get('query_server_ids') or []) if str(x).isdigit()]
    async with SessionLocal() as session:
        cats = (await session.execute(select(ServerCategory).where(ServerCategory.id.in_(cat_ids)))).scalars().all()
        linked_ids = []
        for cat in cats:
            for sid in category_server_ids(cat):
                if sid in all_server_ids and sid not in linked_ids:
                    linked_ids.append(sid)
        servers = (await session.execute(select(Server).where(Server.id.in_(linked_ids), Server.is_active == True).order_by(Server.id.asc()))).scalars().all() if linked_ids else []
    server_ids = [s.id for s in servers]
    if not server_ids:
        await ui_callback_message(callback, 'برای این دسته سرور فعالی پیدا نشد.', reply_markup=query_home_keyboard(back_cb))
        await safe_callback_answer(callback)
        return
    await state.update_data(query_selected_category_ids=cat_ids, query_server_ids=server_ids, server_id=None)
    await _query_prompt_username(callback, state, server_ids, back_cb=back_cb)


@router.callback_query(F.data.startswith('query:server:'))
async def query_pick_server(callback: CallbackQuery, state: FSMContext):
    sid = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        server = await session.get(Server, sid)
    if not server:
        await ui_callback_message(callback, 'سرور انتخاب‌شده پیدا نشد.', reply_markup=query_home_keyboard())
        await safe_callback_answer(callback)
        return
    await state.update_data(server_id=sid, query_server_ids=[sid], needs_password=False, server_type=server.server_type)
    await state.set_state(QueryClient.username)
    text = 'یوزرنیم کانفیگ را ارسال کنید:'
    await ui_callback_message(callback, text, reply_markup=query_home_keyboard('menu:query'))
    await safe_callback_answer(callback)


@router.message(QueryClient.username)
async def query_username(message: Message, state: FSMContext):
    username = extract_key(message.text or '')
    if not username:
        await ui_message(message, 'یوزرنیم معتبر نیست. دوباره ارسال کنید.', reply_markup=query_home_keyboard())
        return
    await state.update_data(username=username)
    await _process_query_lookup(message, state)


@router.callback_query(F.data == 'query:back_username')
async def query_back_to_username(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    server_ids = [int(x) for x in (data.get('query_server_ids') or []) if str(x).isdigit()]
    sid = int(data.get('server_id') or 0)
    if sid and sid not in server_ids:
        server_ids = [sid]
    if not server_ids:
        await query_start(callback, state)
        return
    await _query_prompt_username(callback, state, server_ids, back_cb=f'query:type:{data.get("query_kind", "v2ray")}')


@router.message(QueryClient.password)
async def query_password(message: Message, state: FSMContext):
    await _process_query_lookup(message, state, password=(message.text or '').strip())
