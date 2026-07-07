from __future__ import annotations
from datetime import datetime, timedelta
from types import SimpleNamespace
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.fsm.context import FSMContext
from sqlalchemy import select, func, or_
import qrcode, tempfile, re, logging, random, string, asyncio
from app.database.session import SessionLocal
from app.database.models import User, Server, Plan, PaymentCard, ResellerAccount, ResellerPackage, ResellerTopupRequest, ResellerAccessRequest, ClientService, DiscountCode, DiscountUsage
from app.bot.keyboards.common import CB_RESELLER, back_button, back_main_inline, main_menu_inline
from app.bot.states.public_states import ResellerCreateUser, ResellerTopupFlow, ResellerDiscountInput, ResellerRenewUser, ResellerAddVolume, ResellerAddDays
from app.bot.utils import send_single_message, edit_or_answer, ui_message, forget_ui_message
from app.bot.error_reporting import handle_user_facing_error
from app.bot.service_presenter import build_service_caption, send_service_info as send_service_card
from app.bot.qr_card import make_qr_card
from app.services.reseller_service import gb_to_bytes, bytes_to_gb, get_user_reseller, is_reseller_access_active, reseller_stats, reserve_volume_for_service, refund_unused_volume, create_reseller_access_request, ensure_reseller_for_user, apply_package
from app.services.xui_service import XuiService
from app.services.mikrotik_service import MikroTikService
from app.xui.client import XuiClientPayload
from app.core.config import settings
from app.database.defaults import get_setting_value, WELCOME_TEXT_DEFAULT
from app.services.plan_order import saved_plan_order, sort_by_saved_order
from app.utils.jalali import fa_date

router = Router()

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

logger = logging.getLogger(__name__)


def _online_identity_tokens(*values: object) -> set[str]:
    """Normalize client identifiers for online checks without exposing IPs."""
    tokens: set[str] = set()
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if not text or text == '-':
            continue
        raw = text.lower()
        tokens.add(raw)
        if '@' in raw:
            local = raw.split('@', 1)[0].strip()
            if local:
                tokens.add(local)
        # Subscription links can contain useful identifiers in query/path parts.
        for piece in re.split(r'[^a-zA-Z0-9_@.:-]+', raw):
            piece = piece.strip()
            if len(piece) >= 4:
                tokens.add(piece)
    return tokens


def _online_status_from_identifiers(svc, online_clients: list[str]) -> bool:
    service_tokens = _online_identity_tokens(
        getattr(svc, 'xui_email', None),
        getattr(svc, 'client_username', None),
        getattr(svc, 'xui_uuid', None),
        getattr(svc, 'sub_link', None),
    )
    if not service_tokens:
        return False
    for item in online_clients or []:
        item_tokens = _online_identity_tokens(item)
        if service_tokens.intersection(item_tokens):
            return True
    return False


async def reseller_realtime_online_status(server: Server | None, svc) -> str:
    """Return a simple realtime online/offline label, never the connected IP list."""
    if not server or not svc:
        return 'نامشخص'
    try:
        if server.server_type == 'xui':
            online_clients = await XuiService().get_online_clients(server)
            return '🟢 آنلاین همین الان' if _online_status_from_identifiers(svc, online_clients) else '⚫ آفلاین'
        if server.server_type == 'mikrotik':
            found = await MikroTikService().get_user(server, svc.xui_email or svc.client_username)
            if not found:
                return '⚫ آفلاین'
            for key in ('online', 'is_online', 'connected', 'active_now'):
                if key in found:
                    return '🟢 آنلاین همین الان' if bool(found.get(key)) else '⚫ آفلاین'
            return 'نامشخص'
    except Exception as e:
        logger.warning('Failed to read realtime reseller online status for service %s: %s', getattr(svc, 'id', None), e)
        return 'نامشخص'
    return 'نامشخص'

async def apply_reseller_discount(session, code: str | None, amount: int, user_id: int | None = None) -> tuple[int, str | None, DiscountCode | None]:
    if not code:
        return amount, None, None
    clean = code.strip().upper().replace(' ', '')
    d = (await session.execute(select(DiscountCode).where(DiscountCode.code == clean, DiscountCode.is_active == True))).scalar_one_or_none()
    if not d:
        return amount, 'کد تخفیف معتبر نیست.', None
    if d.expires_at and d.expires_at < datetime.utcnow():
        return amount, 'کد تخفیف منقضی شده است.', None
    if d.max_uses and d.used_count >= d.max_uses:
        return amount, 'ظرفیت استفاده از این کد تکمیل شده است.', None
    if user_id and getattr(d, 'per_user_limit', 1):
        used_by_user = (await session.execute(select(func.count(DiscountUsage.id)).where(DiscountUsage.discount_id == d.id, DiscountUsage.user_id == user_id))).scalar() or 0
        if used_by_user >= d.per_user_limit:
            return amount, f'شما قبلاً از این کد {used_by_user} بار استفاده کرده‌اید و سقف استفاده شما تکمیل شده است.', None
    discount = int(amount * min(max(d.value, 0), 100) / 100) if d.discount_type == 'percent' else int(d.value)
    return max(amount - discount, 0), None, d

async def mark_reseller_discount_used(session, discount_obj: DiscountCode | None, user_id: int) -> None:
    if not discount_obj:
        return
    discount_obj.used_count += 1
    session.add(DiscountUsage(discount_id=discount_obj.id, user_id=user_id, source='reseller'))

async def send_home(bot, chat_id:int, is_admin: bool=False):
    text = await get_setting_value('welcome_text', WELCOME_TEXT_DEFAULT)
    await send_single_message(bot, chat_id, text, reply_markup=main_menu_inline(is_admin))


def success_home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🏠 خانه', callback_data='home:main')]
    ])


async def send_reseller_success_notice(bot, chat_id: int, username: str | None = None, *, action: str = 'create') -> None:
    title = '✅ یوزر نمایندگی با موفقیت تمدید شد.' if action == 'renew' else '✅ یوزر نمایندگی با موفقیت ساخته و ارسال شد.'
    extra = f'\n\n👤 اسم اختصاصی: {username}' if username else ''
    await bot.send_message(chat_id, title + extra + '\n\nبرای برگشت به صفحه اول، دکمه خانه را بزنید.', reply_markup=success_home_keyboard())


def is_admin_user(user_id: int) -> bool:
    return user_id in settings.admin_ids

def format_irt_dot(amount: int) -> str:
    return f'{int(amount):,}'.replace(',', '.')

def reseller_package_button_text(package: ResellerPackage, is_admin: bool = False) -> str:
    volume_text = f'{package.volume_gb:g} گیگ'
    price_text = 'رایگان برای مدیر' if is_admin else f'{format_irt_dot(package.price_irt)} تومان'
    if is_admin:
        return f'پلن حجم | {volume_text} | {price_text}'
    return f'پلن حجم | {volume_text} | {price_text}'

def reseller_payment_kb(pid: int, *, include_discount: bool = True) -> InlineKeyboardMarkup:
    rows = []
    if include_discount:
        rows.append([InlineKeyboardButton(text='🏷 اعمال کد تخفیف', callback_data='reseller:discount')])
    rows.append([InlineKeyboardButton(text='💳 پرداخت کارت به کارت', callback_data='reseller:pay_card')])
    rows.append([back_button('reseller:topup')])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def reseller_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='➕ شارژ حجم', callback_data='reseller:topup'), InlineKeyboardButton(text='🧩 ساخت یوزر', callback_data='reseller:create')],
        [InlineKeyboardButton(text='👥 یوزرها', callback_data='reseller:users')],
        [InlineKeyboardButton(text='🏠 خانه اول', callback_data='home:main')],
    ])


def reseller_back_kb(target: str = 'menu:reseller') -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='🔙 برگشت به منو نمایندگی', callback_data=target)]])

def install_text(link: str | None) -> str:
    return (
        f'🔗 لینک اتصال:\n{link or "لینک ساخته نشد"}\n\n'
        '⚠️ فقط و فقط برنامه Happ مورد تایید ما هستش.\n'
        'اگر از برنامه دیگری استفاده می‌کنید، هرچه زودتر Happ را از App Store یا Google Play دانلود و نصب کنید.\n\n'
        'در غیر این صورت، وصل نشدن سرورها مسئولیتش با خود شماست و در پشتیبانی خدماتی ارائه نمی‌شود.\n\n'
        '✅ مراحل اضافه کردن در Happ:\n'
        '1) Happ را باز کنید.\n'
        '2) روی + بزنید.\n'
        '3) Import / Subscription را انتخاب کنید.\n'
        '4) لینک را وارد و ذخیره کنید.\n\n'
        '♻️ هر ۱۲ ساعت از داخل Happ گزینه Update / Refresh Subscription را بزنید.'
    )

def reseller_home_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='🏠 برگشت به خانه اول', callback_data='home:main')], [InlineKeyboardButton(text='💼 منو نمایندگی', callback_data='menu:reseller')]])

def reseller_service_visible_filters(reseller_id: int):
    return (
        ClientService.reseller_id == reseller_id,
        or_(ClientService.client_username.is_(None), ~ClientService.client_username.like('deleted_%')),
    )

def reseller_users_kb(services: list[ClientService]) -> InlineKeyboardMarkup:
    rows = []
    current_row = []
    for s in services:
        remain = max((s.total_bytes or 0) - (s.used_bytes or 0), 0)
        status = '🟢' if s.is_active else '🔴'
        btn = InlineKeyboardButton(
            text=f'{status} {s.client_username} | {bytes_to_gb(s.used_bytes)}GB مصرف | {bytes_to_gb(remain)}GB مانده',
            callback_data=f'reseller:user:{s.id}'
        )
        current_row.append(btn)
        if len(current_row) == 2:
            rows.append(current_row)
            current_row = []
    if current_row:
        rows.append(current_row)
    rows.append([
        InlineKeyboardButton(text='🔄 بروزرسانی مصرف', callback_data='reseller:users_refresh'),
        InlineKeyboardButton(text='🔙 برگشت به منو نمایندگی', callback_data='menu:reseller'),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def reseller_create_prompt_text(remaining_gb: float) -> str:
    return (
        '🧩 <b>ساخت یوزر نماینده</b>\n'
        '━━━━━━━━━━━━━━━━━━━━━━\n\n'
        '📊 <b>ظرفیت قابل ساخت شما</b>\n'
        f'💾 <b>{remaining_gb:g} گیگابایت</b>\n\n'
        '━━━━━━━━━━━━━━━━━━━━━━\n'
        '👤 <b>یوزرنیم مشتری را وارد کنید</b>\n\n'
        '▫️ فقط حروف انگلیسی، عدد و آندرلاین مجاز است.\n'
        '▫️ نمونه: <code>ali_123</code>\n\n'
        'بعد از وارد کردن یوزرنیم، حجم و مدت سرویس ساخته می‌شود.'
    )

def reseller_created_text(username: str, volume: float, days: int, link: str | None, remaining_gb: float, *, server_type: str = 'xui', password: str | None = None) -> str:
    return build_service_caption(
        username=username,
        title=f'نمایندگی | {volume:g} گیگ | {days} روز',
        volume_gb=volume,
        duration_days=days,
        sub_link=link,
        is_test=False,
        server_type=server_type,
        password=password,
    )

async def send_reseller_created_admin_notice(bot, reseller_user, username: str, volume: float, days: int, expires_at) -> None:
    text = (
        '🧩 ساخت یوزر توسط نماینده\n'
        '━━━━━━━━━━━━━━━━\n'
        f'👤 اسم اختصاصی: {username}\n'
        f'💾 حجم: {volume:g} گیگ\n'
        f'📅 مدت: {days} روز\n'
        f'⏳ انقضا: {fa_date(expires_at)}\n'
        f'🤝 نماینده: {getattr(reseller_user, "full_name", None) or "-"} | {getattr(reseller_user, "id", "-")}'
    )
    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            pass

RESELLER_USERNAME_RE = re.compile(r'[A-Za-z0-9_]{1,32}')

RESELLER_USERNAME_FORMAT_ERROR_TEXT = (
    '❌ اسم اختصاصی واردشده فرمت درستی ندارد.\n\n'
    'مشکل از فرمت اسم است، نه تکراری بودن.\n\n'
    '✅ فرمت مجاز:\n'
    '▫️ فقط حروف انگلیسی، عدد و آندرلاین (_)\n'
    '▫️ حداکثر ۳۲ کاراکتر\n'
    '▫️ نمونه قابل قبول: ali_123\n\n'
    '❌ فاصله، خط تیره، حروف فارسی و کاراکترهای خاص مجاز نیستند.\n\n'
    'لطفاً همینجا یک اسم اختصاصی جدید بفرستید تا ادامه بدهم.'
)

RESELLER_USERNAME_TAKEN_TEXT = (
    '❌ این اسم اختصاصی قبلاً داخل دیتابیس یا پنل ثبت شده است.\n\n'
    'مشکل از تکراری بودن اسم است، نه فرمت آن.\n\n'
    'لطفاً همینجا یک اسم اختصاصی دیگر بفرستید تا ادامه ساخت یوزر را پیش ببریم.'
)


def normalize_reseller_username(text: str | None) -> str:
    return (text or '').strip()


def valid_reseller_username(username: str) -> bool:
    return bool(RESELLER_USERNAME_RE.fullmatch(username or ''))


def clean_username(text: str) -> str:
    return re.sub(r'[^A-Za-z0-9_]', '', (text or '').strip().replace(' ', ''))


async def reseller_username_exists(session, server: Server | None, username: str) -> bool:
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



async def get_reseller_username_error(session, server: Server | None, username: str) -> str | None:
    """Return the exact reason a requested reseller username is not usable.

The reseller creation state must stay on ResellerCreateUser.username when this
returns a message, so the reseller can send a new name and continue.
    """
    if not valid_reseller_username(username):
        return RESELLER_USERNAME_FORMAT_ERROR_TEXT
    if await reseller_username_exists(session, server, username):
        return RESELLER_USERNAME_TAKEN_TEXT
    return None

def rnd_suffix() -> str:
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))


def normalize_inbound_ids(value) -> list[int]:
    ids: list[int] = []
    if value is None:
        return ids
    if isinstance(value, str):
        items = re.split(r'[,\s]+', value.strip())
    elif isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        items = [value]
    for item in items:
        if isinstance(item, dict):
            item = item.get('id') or item.get('inbound_id') or item.get('inboundId')
        try:
            iid = int(item)
        except Exception:
            continue
        if iid > 0 and iid not in ids:
            ids.append(iid)
    return ids


async def resolve_reseller_build_target(session, reseller: ResellerAccount) -> tuple[Server | None, list[int]]:
    """Resolve reseller creation target without any separate build-settings flow.

    Source of truth is the reseller-specific server itself:
    1) the server attached to the reseller account/package;
    2) if missing/invalid, the newest active server whose meta.scope is reseller.

    Inbound IDs are read only from server.meta['inbound_ids']. Public servers and
    public plan inbound IDs are never used for reseller user creation.
    """
    def is_reseller_server(server: Server | None) -> bool:
        return bool(server and (server.meta or {}).get('scope') == 'reseller')

    server = await session.get(Server, reseller.server_id) if getattr(reseller, 'server_id', None) else None
    if not server or not server.is_active or not is_reseller_server(server):
        servers = (await session.execute(
            select(Server).where(Server.is_active == True).order_by(Server.id.desc())
        )).scalars().all()
        server = next((s for s in servers if is_reseller_server(s)), None)
        if server and getattr(reseller, 'server_id', None) != server.id:
            reseller.server_id = server.id
            await session.flush()

    if not server or not server.is_active or not is_reseller_server(server):
        return None, []

    inbound_ids = normalize_inbound_ids((server.meta or {}).get('inbound_ids') or [])
    return server, inbound_ids


async def pick_available_reseller_username(session, server: Server, base_username: str) -> str:
    clean = clean_username(base_username)
    if not clean:
        clean = 'user' + rnd_suffix()
    for idx in range(20):
        candidate = clean if idx == 0 else f'{clean}_{rnd_suffix()}'
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
    return f'{clean}_{rnd_suffix()}{rnd_suffix()}'



def _reseller_effective_used_bytes(svc, raw_used: int) -> int:
    """Return usage for the current reseller cycle only.

    3x-ui/MikroTik traffic counters may keep the old traffic value for a short
    time after a reseller renewal, or a resetTraffic call may fail silently on
    some panel versions.  When that happens, the first real traffic of the new
    cycle used to look like an "added volume / extra usage" record.

    For reseller services we reuse traffic_baseline_bytes as a traffic baseline:
    remote_panel_used - renewal_baseline = current_cycle_used.  If the panel
    counter is actually reset later and becomes smaller than the baseline, the
    baseline is cleared automatically.
    """
    try:
        raw = int(raw_used or 0)
    except Exception:
        raw = 0
    if not getattr(svc, 'reseller_id', None):
        return raw
    try:
        baseline = int(getattr(svc, 'traffic_baseline_bytes', 0) or 0)
    except Exception:
        baseline = 0
    if baseline <= 0:
        return raw
    if raw >= baseline:
        return max(raw - baseline, 0)

    # The panel counter was reset after the renewal baseline was stored.  From
    # now on the raw panel value is already the current-cycle usage.
    svc.traffic_baseline_bytes = 0
    return raw


async def sync_reseller_service_from_panel(session, svc) -> bool | None:
    """Refresh reseller client usage from X-UI before showing it.

    Returns True if refreshed, False if the panel says the client is missing,
    and None if panel/server is unavailable. This keeps reseller pages showing
    real used/remaining traffic instead of stale local values.
    """
    server = await session.get(Server, svc.server_id) if svc else None
    if not svc or not server:
        return None
    if server.server_type == 'mikrotik':
        try:
            found = await MikroTikService().get_user(server, svc.xui_email or svc.client_username)
            if not found:
                svc.is_active = False
                await session.flush()
                return False
            raw_used = int(found.get('used_bytes') or 0)
            svc.used_bytes = _reseller_effective_used_bytes(svc, raw_used)
            if found.get('volume_bytes') is not None:
                svc.total_bytes = int(found.get('volume_bytes') or 0)
            svc.is_active = not bool(found.get('disabled') or found.get('expired'))
            await session.flush()
            return True
        except Exception as e:
            logger.warning('Failed to sync reseller MikroTik service %s: %s', getattr(svc, 'id', None), e)
            return None
    if server.server_type != 'xui':
        return None
    try:
        found = await XuiService().find_client_any(server, svc.xui_email or svc.client_username)
        if not found:
            svc.is_active = False
            await session.flush()
            return False
        c = found.get('client') or {}
        tr = found.get('traffic') or {}
        used = (tr.get('up', 0) or 0) + (tr.get('down', 0) or 0)
        total = tr.get('total') or c.get('totalGB') or c.get('total') or svc.total_bytes
        svc.used_bytes = _reseller_effective_used_bytes(svc, int(used or 0))
        if total:
            svc.total_bytes = int(total)
        svc.is_active = bool(c.get('enable', svc.is_active))
        subid = c.get('subId') or c.get('sub_id') or tr.get('subId') or tr.get('sub_id')
        if subid:
            svc.sub_link = XuiService().build_subscription_link(server, subid, svc.xui_email or svc.client_username)
        await session.flush()
        return True
    except Exception as e:
        logger.warning('Failed to sync reseller service %s from panel: %s', getattr(svc, 'id', None), e)
        return None

async def sync_all_reseller_services(session, reseller: ResellerAccount) -> None:
    services = (await session.execute(
        select(ClientService).where(*reseller_service_visible_filters(reseller.id))
    )).scalars().all()
    changed = False
    for svc in services:
        result = await sync_reseller_service_from_panel(session, svc)
        if result is not None:
            changed = True
    if changed:
        await session.commit()

async def require_reseller(callback: CallbackQuery):
    async with SessionLocal() as session:
        user, reseller = await get_user_reseller(session, callback.from_user.id)
        if not reseller:
            return None, None, 'شما هنوز نماینده نیستید. از بخش شارژ حجم یک بسته نمایندگی خریداری کنید.'
        if not is_reseller_access_active(reseller):
            return user, reseller, '⛔️ اعتبار نمایندگی شما تمام شده است. سرویس‌های ساخته‌شده فعال می‌مانند، اما دسترسی نمایندگی قطع شده است.'
        return user, reseller, None


async def reseller_dashboard_text(session, reseller: ResellerAccount) -> str:
    stats = await reseller_stats(session, reseller)
    return (
        '💼 <b>منو نمایندگی D Bot</b>\n'
        '━━━━━━━━━━━━━━━━━━━━━━\n\n'
        '📊 <b>وضعیت لحظه‌ای نمایندگی</b>\n\n'
        f'👥 <b>تعداد کل یوزرها:</b> {stats["total_users"]}\n'
        f'💾 <b>حجم باقی‌مانده:</b> {bytes_to_gb(stats["remaining_bytes"])} گیگ\n'
        f'📉 <b>حجم مصرف‌شده:</b> {bytes_to_gb(stats["used_bytes"])} گیگ\n'
        f'📦 <b>حجم کل خریداری‌شده:</b> {bytes_to_gb(stats["total_bytes"])} گیگ\n\n'
        f'⏳ <b>اعتبار باقی‌مانده:</b> {stats["days_left"]} روز\n\n'
        '━━━━━━━━━━━━━━━━━━━━━━\n'
        'از دکمه‌های زیر می‌توانید حجم شارژ کنید، یوزر بسازید یا یوزرها را مدیریت کنید.'
    )

async def notify_owners_for_reseller_access(callback: CallbackQuery, request_id: int, user: User) -> None:
    full_name = user.full_name or callback.from_user.full_name or '-'
    username = user.username or callback.from_user.username or '-'
    text = (
        '🔐 درخواست دسترسی نمایندگی جدید\n\n'
        f'شماره درخواست: #{request_id}\n'
        f'کاربر: {full_name} | @{username}\n'
        f'Telegram ID: {user.telegram_id}\n\n'
        'برای باز شدن قفل صفحه نمایندگی این کاربر، تایید را بزنید.'
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ تایید دسترسی نمایندگی', callback_data=f'resadmin:access_approve:{request_id}')],
        [InlineKeyboardButton(text='❌ رد درخواست', callback_data=f'resadmin:access_reject:{request_id}')],
    ])
    for owner_id in settings.owner_ids:
        try:
            await callback.message.bot.send_message(owner_id, text, reply_markup=kb)
        except Exception:
            pass

@router.callback_query(F.data == CB_RESELLER)
async def reseller_home(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    async with SessionLocal() as session:
        user = (await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one_or_none()
        if not user:
            user = User(telegram_id=callback.from_user.id, username=callback.from_user.username, full_name=callback.from_user.full_name)
            session.add(user)
            await session.flush()
        reseller = (await session.execute(select(ResellerAccount).where(ResellerAccount.user_id == user.id))).scalar_one_or_none()
        if callback.from_user.id in settings.admin_ids:
            reseller = await ensure_reseller_for_user(session, user.id, None, 0)
            reseller.is_active = True
            reseller.expires_at = None
            await session.commit()
            await edit_or_answer(callback, await reseller_dashboard_text(session, reseller), reply_markup=reseller_menu(), parse_mode='HTML')
            await callback.answer()
            return
        access_req = (await session.execute(select(ResellerAccessRequest).where(ResellerAccessRequest.user_id == user.id))).scalar_one_or_none()
        if reseller and is_reseller_access_active(reseller):
            await edit_or_answer(callback, await reseller_dashboard_text(session, reseller), reply_markup=reseller_menu(), parse_mode='HTML')
            await callback.answer()
            return
        if access_req and access_req.status == 'pending':
            await edit_or_answer(callback, '⏳ درخواست نمایندگی شما قبلاً ثبت شده و منتظر تایید مدیر است.\nبعد از تایید، همین بخش برای شما باز می‌شود.', reply_markup=back_main_inline())
            await callback.answer('درخواست شما در انتظار تایید است.', show_alert=True)
            return
        if access_req and access_req.status == 'rejected':
            access_req = await create_reseller_access_request(session, user.id)
        else:
            access_req = await create_reseller_access_request(session, user.id)
        await session.commit()
        await session.refresh(access_req)
    await notify_owners_for_reseller_access(callback, access_req.id, user)
    await edit_or_answer(callback, '✅ درخواست نمایندگی شما برای مدیر ارسال شد.\nتا زمانی که مدیر تایید نکند، این صفحه قفل می‌ماند.', reply_markup=back_main_inline())
    await callback.answer('درخواست برای مدیر ارسال شد.', show_alert=True)

@router.callback_query(F.data == 'reseller:topup')
async def reseller_topup(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    async with SessionLocal() as session:
        packages = (await session.execute(select(ResellerPackage).where(ResellerPackage.is_active == True))).scalars().all()
        packages = sort_by_saved_order(packages, await saved_plan_order(session, 'reseller'))
    if not packages:
        await edit_or_answer(callback, 'فعلاً هیچ بسته نمایندگی ثبت نشده است.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('menu:reseller')]])); await callback.answer(); return
    rows = []
    for p in packages:
        rows.append([InlineKeyboardButton(text=reseller_package_button_text(p, is_admin_user(callback.from_user.id)), callback_data=f'reseller:pkg:{p.id}')])
    rows.append([back_button('menu:reseller')])
    await edit_or_answer(callback, '📦 بسته نمایندگی موردنظر را انتخاب کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)); await callback.answer()

@router.callback_query(F.data.startswith('reseller:pkg:'))
async def reseller_pkg(callback: CallbackQuery, state: FSMContext):
    pid = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        pkg = await session.get(ResellerPackage, pid)
        server = await session.get(Server, pkg.server_id) if pkg else None
    if not pkg:
        await callback.answer('بسته پیدا نشد.', show_alert=True); return
    if callback.from_user.id in settings.admin_ids:
        async with SessionLocal() as session:
            user = (await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one_or_none()
            if not user:
                user = User(telegram_id=callback.from_user.id, username=callback.from_user.username, full_name=callback.from_user.full_name)
                session.add(user); await session.flush()
            req = ResellerTopupRequest(user_id=user.id, package_id=pkg.id, amount_irt=0, volume_bytes=gb_to_bytes(pkg.volume_gb), status='pending')
            session.add(req); await session.flush()
            await apply_package(session, req)
            await session.commit()
        await edit_or_answer(callback, f'✅ بسته نمایندگی رایگان برای مدیر فعال شد.\nحجم اضافه‌شده: {pkg.volume_gb:g} گیگ\nاعتبار: {pkg.reseller_validity_days} روز')
        await send_home(callback.message.bot, callback.from_user.id, True)
        await callback.answer()
        return
    await state.update_data(package_id=pid, reseller_discount_code=None, reseller_final_amount=pkg.price_irt)
    text = (
        '💼 خرید بسته نمایندگی\n\n'
        '━━━━━━━━━━━━━━━━━━\n'
        f'📦 پلن انتخابی\n{pkg.title}\n\n'
        f'🖥 سرور:\n{server.name if server else "-"}\n\n'
        f'💾 حجم قابل استفاده:\n{pkg.volume_gb} گیگابایت\n\n'
        f'⏳ مدت اعتبار نمایندگی:\n{pkg.reseller_validity_days} روز\n\n'
        f'💰 مبلغ:\n{pkg.price_irt:,} تومان\n'
        '━━━━━━━━━━━━━━━━━━\n\n'
        'اگر کد تخفیف دارید، ابتدا روی اعمال کد تخفیف بزنید.'
    )
    await edit_or_answer(callback, text, reply_markup=reseller_payment_kb(pid)); await callback.answer()

@router.callback_query(F.data == 'reseller:discount')
async def reseller_discount_start(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    pid = int(data.get('package_id') or 0)
    await state.set_state(ResellerDiscountInput.code)
    await edit_or_answer(callback, '🏷 کد تخفیف نمایندگی را وارد کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(f'reseller:pkg:{pid}')]]))
    await callback.answer()

@router.message(ResellerDiscountInput.code)
async def reseller_discount_apply(message: Message, state: FSMContext):
    code = (message.text or '').strip().upper().replace(' ', '')
    data = await state.get_data(); pid = int(data.get('package_id') or 0)
    async with SessionLocal() as session:
        pkg = await session.get(ResellerPackage, pid)
        if not pkg:
            await ui_message(message, 'بسته پیدا نشد.', reply_markup=reseller_menu()); await state.clear(); return
        user=(await session.execute(select(User).where(User.telegram_id == message.from_user.id))).scalar_one()
        final, err, d = await apply_reseller_discount(session, code, pkg.price_irt, user.id)
    if err:
        await ui_message(message, '❌ ' + err, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(f'reseller:pkg:{pid}')]])); return
    await state.update_data(reseller_discount_code=code, reseller_final_amount=final)
    await ui_message(message, f'✅ کد تخفیف اعمال شد.\n\nمبلغ قبلی: {pkg.price_irt:,} تومان\nمبلغ جدید: {final:,} تومان\n\nبرای ادامه پرداخت را بزنید.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='💳 پرداخت کارت به کارت', callback_data='reseller:pay_card')],[back_button(f'reseller:pkg:{pid}')]]))

@router.callback_query(F.data == 'reseller:pay_card')
async def reseller_pay_card(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data(); pid = int(data.get('package_id') or 0)
    async with SessionLocal() as session:
        pkg = await session.get(ResellerPackage, pid)
        server = await session.get(Server, pkg.server_id) if pkg else None
        reseller_card = (await session.execute(select(PaymentCard).where(PaymentCard.server_type == 'reseller', PaymentCard.is_active == True).order_by(PaymentCard.id.desc()))).scalars().first()
        server_card = None
        if pkg:
            server_card = (await session.execute(select(PaymentCard).where(PaymentCard.server_id == pkg.server_id, PaymentCard.is_active == True).order_by(PaymentCard.id.desc()))).scalars().first()
        card = reseller_card or server_card
    if not pkg:
        await callback.answer('بسته پیدا نشد.', show_alert=True); return
    if not card:
        await edit_or_answer(callback, 'برای خرید حجم نمایندگی هنوز کارت پرداخت ثبت نشده است. لطفاً با پشتیبانی تماس بگیرید.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(f'reseller:pkg:{pid}')]])); await callback.answer(); return
    final_amount = int(data.get('reseller_final_amount') or pkg.price_irt)
    await state.set_state(ResellerTopupFlow.receipt)
    card_number = str(card.card_number or '').replace(' ', '')
    pretty_card = card_number if card_number else '-'
    text = (
        '💼 خرید بسته نمایندگی\n\n'
        '━━━━━━━━━━━━━━━━━━\n'
        f'📦 پلن انتخابی\n{pkg.title}\n\n'
        f'🖥 سرور:\n{server.name if server else "-"}\n\n'
        f'💾 حجم قابل استفاده:\n{pkg.volume_gb} گیگابایت\n\n'
        f'⏳ مدت اعتبار نمایندگی:\n{pkg.reseller_validity_days} روز\n\n'
        f'💰 مبلغ قابل پرداخت:\n{final_amount:,} تومان\n'
        '━━━━━━━━━━━━━━━━━━\n\n'
        '💳 اطلاعات پرداخت\n\n'
        f'🔹 شماره کارت\n{pretty_card}\n\n'
        f'👤 صاحب حساب\n{card.owner_name or "-"}\n\n'
        '━━━━━━━━━━━━━━━━━━\n\n'
        '📸 بعد از واریز، تصویر رسید پرداخت را همینجا ارسال کنید.\n'
        '⚠️ درخواست شما پس از بررسی و تأیید مدیریت فعال خواهد شد.'
    )
    await edit_or_answer(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(f'reseller:pkg:{pid}')]])); await callback.answer()

async def notify_admins_for_reseller_topup(message: Message, request_id: int, user: User, pkg: ResellerPackage, receipt_file_id: str | None = None, is_photo: bool = False, final_amount: int | None = None, discount_code: str | None = None) -> None:
    full_name = user.full_name or message.from_user.full_name or '-'
    username = user.username or message.from_user.username or '-'
    original_amount = int(pkg.price_irt if pkg else 0)
    final_display_amount = int(final_amount if final_amount is not None else original_amount)
    discount_line = f'🏷 کد تخفیف: {discount_code}\n💵 مبلغ نهایی: {format_irt_dot(final_display_amount)} تومان\n' if discount_code else ''
    caption = (
        '🧾 رسید جدید شارژ حجم نمایندگی  \n  \n'
        f'شماره درخواست: #{request_id}  \n'
        f'کاربر: {full_name} | @{username}  \n'
        f'Telegram ID: {user.telegram_id}  \n\n'
        f'📦 پلن: {pkg.title if pkg else "-"}  \n'
        f'💾 حجم: {pkg.volume_gb if pkg else "-"} گیگ  \n'
        f'💰 مبلغ: {format_irt_dot(original_amount)} تومان  \n'
        f'{discount_line}\n'
        'برای تایید یا رد رسید، یکی از دکمه‌های زیر را بزنید.'
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ تایید و افزودن حجم', callback_data=f'resadmin:req_approve:{request_id}')],
        [InlineKeyboardButton(text='❌ رد درخواست', callback_data=f'resadmin:req_reject:{request_id}')],
        [InlineKeyboardButton(text='📋 مشاهده درخواست', callback_data=f'resadmin:req:{request_id}')],
    ])

    admin_ids = sorted(set(settings.owner_ids or settings.admin_ids))
    if not admin_ids:
        logger.warning('No owner/admin id configured for reseller topup request #%s', request_id)
        return

    for admin_id in admin_ids:
        copied = False
        try:
            # This is the most reliable path: it copies the exact receipt message,
            # regardless of whether the user sent a photo, document, screenshot file, etc.
            await message.bot.copy_message(
                chat_id=admin_id,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
            )
            copied = True
        except Exception as e:
            logger.warning('Failed to copy reseller receipt #%s to admin %s: %s', request_id, admin_id, e)

        try:
            await message.bot.send_message(admin_id, caption, reply_markup=kb)
        except Exception as e:
            logger.warning('Failed to notify admin %s for reseller topup #%s: %s', admin_id, request_id, e)

        if not copied and receipt_file_id:
            # Legacy fallback for Telegram clients where copy_message fails.
            try:
                if is_photo:
                    await message.bot.send_photo(admin_id, receipt_file_id, caption=f'رسید درخواست #{request_id}')
                else:
                    await message.bot.send_document(admin_id, receipt_file_id, caption=f'رسید درخواست #{request_id}')
            except Exception as e:
                logger.warning('Failed legacy receipt send for reseller topup #%s to admin %s: %s', request_id, admin_id, e)

@router.message(ResellerTopupFlow.receipt)
async def reseller_receipt(message: Message, state: FSMContext):
    data = await state.get_data()
    pid = int(data.get('package_id') or 0)
    is_photo = bool(message.photo)
    receipt = None
    if message.photo:
        receipt = message.photo[-1].file_id
    elif message.document:
        receipt = message.document.file_id
    elif message.video:
        receipt = message.video.file_id
    elif message.animation:
        receipt = message.animation.file_id
    if not receipt:
        await ui_message(message, 'لطفاً رسید را به صورت عکس، اسکرین‌شات یا فایل ارسال کنید.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(f'reseller:pkg:{pid}')]])); return
    async with SessionLocal() as session:
        user = (await session.execute(select(User).where(User.telegram_id == message.from_user.id))).scalar_one_or_none()
        if not user:
            user = User(telegram_id=message.from_user.id, username=message.from_user.username, full_name=message.from_user.full_name)
            session.add(user)
            await session.flush()
        pkg = await session.get(ResellerPackage, pid)
        if not pkg:
            await ui_message(message, 'بسته نمایندگی پیدا نشد. لطفاً دوباره از بخش شارژ حجم اقدام کنید.', reply_markup=reseller_menu())
            await state.clear()
            return
        final_amount = int(data.get('reseller_final_amount') or pkg.price_irt)
        discount_code = data.get('reseller_discount_code')
        if discount_code:
            user=(await session.execute(select(User).where(User.telegram_id == message.from_user.id))).scalar_one()
            final_amount, err, discount_obj = await apply_reseller_discount(session, discount_code, pkg.price_irt, user.id)
            if err:
                await ui_message(message, '❌ ' + err, reply_markup=reseller_menu()); await state.clear(); return
            await mark_reseller_discount_used(session, discount_obj, user.id)
        req = ResellerTopupRequest(user_id=user.id, package_id=pid, amount_irt=final_amount, volume_bytes=gb_to_bytes(pkg.volume_gb), receipt_file_id=receipt, status='pending')
        session.add(req); await session.commit(); await session.refresh(req)
        # keep plain objects usable after the session closes
        user_info = SimpleNamespace(id=user.id, telegram_id=user.telegram_id, username=user.username, full_name=user.full_name)
        pkg_info = SimpleNamespace(id=pkg.id, title=pkg.title, volume_gb=pkg.volume_gb, price_irt=pkg.price_irt)
        request_id = req.id
    await notify_admins_for_reseller_topup(message, request_id, user_info, pkg_info, receipt, is_photo, final_amount, discount_code)
    await state.clear()
    await ui_message(message, RECEIPT_RECEIVED_TEXT, reply_markup=receipt_received_keyboard())

@router.callback_query(F.data == 'reseller:create')
async def reseller_create_start(callback: CallbackQuery, state: FSMContext):
    user, reseller, err = await require_reseller(callback)
    if err:
        await edit_or_answer(callback, err, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('menu:reseller')]])); await callback.answer(); return
    await state.clear(); await state.set_state(ResellerCreateUser.username)
    remaining = bytes_to_gb(max((reseller.total_bytes or 0)-(reseller.reserved_bytes or 0),0))
    await edit_or_answer(callback, reseller_create_prompt_text(remaining), reply_markup=reseller_back_kb(), parse_mode='HTML'); await callback.answer()

@router.message(ResellerCreateUser.username)
async def reseller_create_username(message: Message, state: FSMContext):
    username = normalize_reseller_username(message.text)
    async with SessionLocal() as session:
        _, reseller = await get_user_reseller(session, message.from_user.id)
        if not reseller or not is_reseller_access_active(reseller):
            await ui_message(message, 'دسترسی نمایندگی فعال نیست.', reply_markup=back_main_inline())
            await state.clear()
            return
        server, inbounds = await resolve_reseller_build_target(session, reseller)
        if not server or (server.server_type == 'xui' and not inbounds):
            await ui_message(message, 'سرور نمایندگی یا تنظیمات ساخت یوزر آماده نیست. برای X-UI باید Inbound ID معتبر ثبت شود و برای MikroTik باید Router/API آماده باشد.', reply_markup=reseller_menu())
            await state.clear()
            return
        username_error = await get_reseller_username_error(session, server, username)
        if username_error:
            await state.set_state(ResellerCreateUser.username)
            await ui_message(message, username_error, reply_markup=reseller_back_kb())
            return
    await state.update_data(username=username)
    await state.set_state(ResellerCreateUser.volume)
    await ui_message(message, 'حجم کانفیگ چند گیگ باشد؟ فقط عدد وارد کنید.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('reseller:create')]]))

@router.message(ResellerCreateUser.volume)
async def reseller_create_volume(message: Message, state: FSMContext):
    try: volume = float(message.text.replace(',', '.').strip())
    except Exception:
        await ui_message(message, 'فقط عدد حجم را وارد کنید. مثلا 10'); return
    if volume <= 0:
        await ui_message(message, 'حجم باید بیشتر از صفر باشد.'); return
    async with SessionLocal() as session:
        _, reseller = await get_user_reseller(session, message.from_user.id)
        if not reseller or not is_reseller_access_active(reseller):
            await ui_message(message, 'دسترسی نمایندگی فعال نیست.', reply_markup=back_main_inline()); await state.clear(); return
        if max((reseller.total_bytes or 0)-(reseller.reserved_bytes or 0),0) < gb_to_bytes(volume):
            await ui_message(message, f'حجم کافی نیست. باقی‌مانده: {bytes_to_gb(max((reseller.total_bytes or 0)-(reseller.reserved_bytes or 0),0))} گیگ', reply_markup=reseller_menu()); await state.clear(); return
    await state.update_data(volume=volume)
    await state.set_state(ResellerCreateUser.duration)
    await ui_message(message, 'مدت زمان اعتبار کانفیگ چند روز باشد؟ فقط عدد وارد کنید.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('reseller:create_back_volume')]]))

@router.callback_query(F.data == 'reseller:create_back_volume')
async def reseller_create_back_volume(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ResellerCreateUser.volume)
    await edit_or_answer(callback, 'حجم کانفیگ چند گیگ باشد؟ فقط عدد وارد کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('reseller:create')]]))
    await callback.answer()


@router.message(ResellerCreateUser.duration)
async def reseller_create_duration(message: Message, state: FSMContext):
    try: days = int(message.text.strip())
    except Exception:
        await ui_message(message, 'فقط عدد روز را وارد کنید. مثلا 30'); return
    if days <= 0:
        await ui_message(message, 'مدت باید بیشتر از صفر باشد.'); return
    data = await state.get_data(); username = data['username']; volume = float(data['volume']); volume_bytes = gb_to_bytes(volume)
    logger.info('Reseller create user started telegram_id=%s username=%s volume=%s days=%s', message.from_user.id, username, volume, days)
    async with SessionLocal() as session:
        user, reseller = await get_user_reseller(session, message.from_user.id)
        if not reseller or not is_reseller_access_active(reseller):
            await ui_message(message, 'دسترسی نمایندگی فعال نیست.', reply_markup=back_main_inline()); await state.clear(); return
        server, inbounds = await resolve_reseller_build_target(session, reseller)
        if not server or (server.server_type == 'xui' and not inbounds):
            await ui_message(message, 'سرور نمایندگی یا تنظیمات ساخت یوزر آماده نیست. برای X-UI باید Inbound ID معتبر ثبت شود و برای MikroTik باید Router/API آماده باشد.', reply_markup=reseller_menu()); await state.clear(); return
        # Keep scalar IDs/values before rollback/commit. Do not access ORM objects inside
        # the exception logger, because async SQLAlchemy may try a lazy DB load there and
        # raise MissingGreenlet.
        server_id_value = server.id
        user_id_value = user.id
        reseller_id_value = reseller.id
        created_sub_link = None
        created_service_id = None
        created_password = None
        try:
            username_error = await get_reseller_username_error(session, server, username)
            if username_error:
                await state.set_state(ResellerCreateUser.username)
                await ui_message(message, username_error, reply_markup=reseller_back_kb())
                return
            await ui_message(
                message,
                '⏳ یوزر با مشخصات زیر درحال ساخت و ارسال است. لطفاً منتظر بمانید.\n\n'
                f'👤 اسم اختصاصی: {username}\n'
                f'💾 حجم: {volume:g} گیگ\n'
                f'📅 مدت: {days} روز\n'
                f'⏳ انقضا: {fa_date(datetime.utcnow() + timedelta(days=days))}'
            )
            await reserve_volume_for_service(session, reseller, volume_bytes)
            if server.server_type == 'mikrotik':
                _Plan = type('MikroTikResellerPlan', (), {'volume_gb': volume, 'duration_days': days, 'inbound_ids': []})
                result = await asyncio.wait_for(MikroTikService().create_user_on_plan(server, _Plan, username), timeout=60)
            else:
                result = await asyncio.wait_for(
                    XuiService().create_client_on_inbounds(
                        server,
                        inbounds,
                        XuiClientPayload(email=username, total_gb=volume, expire_days=days),
                    ),
                    timeout=60,
                )
            if not isinstance(result, dict):
                raise RuntimeError('پاسخ پنل X-UI نامعتبر بود.')
            created_sub_link = result.get('sub_link')
            created_password = result.get('password')
            svc = ClientService(
                user_id=user_id_value,
                server_id=server_id_value,
                reseller_id=reseller_id_value,
                reseller_reserved_bytes=volume_bytes,
                client_username=username,
                xui_email=username,
                xui_uuid=(str(result.get('password') or result.get('uuid')) if (result.get('password') or result.get('uuid')) is not None else None),
                inbound_ids=inbounds,
                sub_link=created_sub_link if server.server_type != 'mikrotik' else None,
                total_bytes=volume_bytes,
                used_bytes=0,
                expires_at=datetime.utcnow()+timedelta(days=days),
                is_active=True,
            )
            session.add(svc)
            await session.flush()
            created_service_id = svc.id
            await session.commit()
        except asyncio.TimeoutError:
            await session.rollback()
            try:
                if server and getattr(server, 'server_type', None) == 'xui':
                    await XuiService().delete_client(server, username)
                elif server and getattr(server, 'server_type', None) == 'mikrotik':
                    await MikroTikService().delete_user(server, username)
            except Exception:
                pass
            logger.exception(
                'Reseller create user timed out telegram_id=%s username=%s server_id=%s volume=%s days=%s',
                message.from_user.id, username, server_id_value, volume, days,
            )
            await ui_message(
                message,
                '❌ ساخت یوزر ناموفق بود:\nاتصال به پنل یا ساخت کانفیگ بیشتر از حد معمول طول کشید. لطفاً سرورهای نماینده و Inbound IDهای ثبت‌شده را بررسی کنید و دوباره تست کنید.',
                reply_markup=reseller_menu(),
            )
            await state.clear(); return
        except Exception as e:
            await session.rollback()
            try:
                if server and getattr(server, 'server_type', None) == 'xui':
                    await XuiService().delete_client(server, username)
                elif server and getattr(server, 'server_type', None) == 'mikrotik':
                    await MikroTikService().delete_user(server, username)
            except Exception:
                pass
            logger.exception(
                'Reseller create user failed for telegram_id=%s username=%s server_id=%s volume=%s days=%s',
                message.from_user.id, username, server_id_value, volume, days,
            )
            await handle_user_facing_error(message, e, context='Reseller create user failed', reply_markup=reseller_menu()); await state.clear(); return
    await state.clear()
    remaining_after = 0
    async with SessionLocal() as session:
        _, r_after = await get_user_reseller(session, message.from_user.id)
        if r_after:
            remaining_after = bytes_to_gb(max((r_after.total_bytes or 0) - (r_after.reserved_bytes or 0), 0))
    caption = reseller_created_text(username, volume, days, created_sub_link, remaining_after, server_type=server.server_type if 'server' in locals() and server else 'xui', password=created_password)
    if created_sub_link:
        qr_path = make_qr_card(
            created_sub_link,
            title='VPN BOT',
            subtitle='RESELLER',
            username=username,
            plan_title=f'نمایندگی | {volume:g} گیگ | {days} روز',
            volume_gb=volume,
            duration_days=days,
            server_name='Multi Location',
        )
        try:
            await message.delete()
        except Exception:
            pass
        await message.answer_photo(FSInputFile(qr_path), caption=caption, parse_mode='HTML')
    else:
        await send_service_card(message.bot, message.from_user.id, username, f'نمایندگی | {volume:g} گیگ | {days} روز', volume, days, None, is_test=False, service_id=created_service_id, server_type=server.server_type if 'server' in locals() and server else 'xui', password=created_password)
    await send_reseller_created_admin_notice(
        message.bot,
        message.from_user,
        username,
        volume,
        days,
        datetime.utcnow() + timedelta(days=days),
    )
    await send_reseller_success_notice(message.bot, message.from_user.id, username, action='create')

@router.callback_query(F.data == 'reseller:users')
async def reseller_users(callback: CallbackQuery):
    user, reseller, err = await require_reseller(callback)
    if err:
        await edit_or_answer(callback, err, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('menu:reseller')]])); await callback.answer(); return
    async with SessionLocal() as session:
        reseller = await session.get(ResellerAccount, reseller.id)
        services = (await session.execute(select(ClientService).where(*reseller_service_visible_filters(reseller.id)).order_by(ClientService.id.desc()))).scalars().all()
    if not services:
        await edit_or_answer(callback, '📭 هنوز هیچ یوزری نساخته‌اید.', reply_markup=reseller_back_kb()); await callback.answer(); return
    await edit_or_answer(callback, '👥 یوزرهای نمایندگی شما\n\nبرای جلوگیری از کندی، مصرف به‌صورت دستی با دکمه بروزرسانی آپدیت می‌شود.', reply_markup=reseller_users_kb(services)); await callback.answer()

@router.callback_query(F.data == 'reseller:users_refresh')
async def reseller_users_refresh(callback: CallbackQuery):
    user, reseller, err = await require_reseller(callback)
    if err:
        await edit_or_answer(callback, err, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('menu:reseller')]])); await callback.answer(); return
    await callback.answer('در حال بروزرسانی مصرف...', show_alert=False)
    async with SessionLocal() as session:
        reseller = await session.get(ResellerAccount, reseller.id)
        if reseller:
            await sync_all_reseller_services(session, reseller)
        services = (await session.execute(select(ClientService).where(*reseller_service_visible_filters(reseller.id)).order_by(ClientService.id.desc()))).scalars().all()
    if not services:
        await edit_or_answer(callback, '📭 هنوز هیچ یوزری نساخته‌اید.', reply_markup=reseller_back_kb()); return
    await edit_or_answer(callback, '👥 یوزرهای نمایندگی شما\n\n✅ مصرف یوزرها بروزرسانی شد.', reply_markup=reseller_users_kb(services))

@router.callback_query(F.data.startswith('reseller:user:'))
async def reseller_user_detail(callback: CallbackQuery):
    sid = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        svc = await session.get(ClientService, sid)
        user, reseller = await get_user_reseller(session, callback.from_user.id)
        if not svc or not reseller or svc.reseller_id != reseller.id:
            await callback.answer('یوزر پیدا نشد.', show_alert=True); return
        await sync_reseller_service_from_panel(session, svc)
        await session.commit()
        await session.refresh(svc)
        server = await session.get(Server, svc.server_id)
    online_text = await reseller_realtime_online_status(server, svc)
    remain = max((svc.total_bytes or 0)-(svc.used_bytes or 0),0)
    status_text = 'فعال' if svc.is_active else 'غیرفعال'
    expire_text = fa_date(svc.expires_at, empty='-') if svc.expires_at else '-'
    sub_link_text = svc.sub_link or '-'
    text = (
        '👤 اطلاعات یوزر\n\n'
        f'نام: {svc.client_username}\n'
        f'وضعیت سرویس: {status_text}\n'
        f'وضعیت اتصال: {online_text}\n'
        f'حجم کل: {bytes_to_gb(svc.total_bytes)} گیگ\n'
        f'مصرف‌شده: {bytes_to_gb(svc.used_bytes)} گیگ\n'
        f'باقی‌مانده: {bytes_to_gb(remain)} گیگ\n'
        f'انقضا: {expire_text}\n\n'
        f'لینک:\n{sub_link_text}'
    )
    kb=InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text='➕ حجم اضافه', callback_data=f'reseller:addvol:{sid}'),
            InlineKeyboardButton(text='📅 تاریخ اضافه', callback_data=f'reseller:adddays:{sid}'),
        ],
        [
            InlineKeyboardButton(text='🔄 تمدید سرویس', callback_data=f'reseller:renew:{sid}'),
            InlineKeyboardButton(text='🔁 باطل کردن لینک و ارسال لینک جدید', callback_data=f'reseller:revoke:{sid}'),
        ],
        [
            InlineKeyboardButton(text='🗑 حذف کانفیگ', callback_data=f'reseller:delete:{sid}'),
            InlineKeyboardButton(text='📖 نمایش راهنمای اتصال', callback_data=f'reseller:help:{sid}'),
        ],
        [back_button('reseller:users')],
    ])
    await edit_or_answer(callback, text, reply_markup=kb); await callback.answer()


def parse_positive_float(text: str) -> float | None:
    raw = (text or '').replace('گیگ', '').replace('GB', '').replace('gb', '').strip()
    try:
        value = float(raw)
    except Exception:
        return None
    return value if value > 0 else None

def parse_positive_int(text: str) -> int | None:
    raw = (text or '').replace('روز', '').replace('day', '').replace('days', '').strip()
    try:
        value = int(raw)
    except Exception:
        return None
    return value if value > 0 else None

def reseller_service_expiry_with_added_days(current_expires_at, add_days: int) -> datetime:
    now = datetime.utcnow()
    base = current_expires_at if current_expires_at and current_expires_at > now else now
    return base + timedelta(days=add_days)


@router.callback_query(F.data.startswith('reseller:addvol:'))
async def reseller_add_volume_start(callback: CallbackQuery, state: FSMContext):
    sid = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        svc = await session.get(ClientService, sid)
        user, reseller = await get_user_reseller(session, callback.from_user.id)
        if not svc or not reseller or svc.reseller_id != reseller.id:
            await callback.answer('یوزر پیدا نشد.', show_alert=True)
            return
        reseller_remaining = max((reseller.total_bytes or 0) - (reseller.reserved_bytes or 0), 0)
        max_gb = bytes_to_gb(reseller_remaining)
        current_total_gb = bytes_to_gb(svc.total_bytes or 0)
        current_used_gb = bytes_to_gb(svc.used_bytes or 0)
    await state.clear()
    await state.update_data(service_id=sid, max_volume_gb=max_gb)
    await state.set_state(ResellerAddVolume.volume)
    await edit_or_answer(
        callback,
        '➕ حجم اضافه برای یوزر نمایندگی\n\n'
        'این گزینه فقط حجم کل کانفیگ را زیاد می‌کند و مصرف فعلی را صفر نمی‌کند.\n'
        'اگر کانفیگ غیرفعال باشد، بعد از افزایش حجم فعال می‌شود.\n\n'
        f'حجم فعلی کانفیگ: {current_total_gb:g} گیگ\n'
        f'مصرف فعلی: {current_used_gb:g} گیگ\n'
        f'حجم قابل اضافه از سهمیه شما: {max_gb:g} گیگ\n\n'
        'چند گیگ اضافه شود؟\nمثال: 20',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(f'reseller:user:{sid}')]])
    )
    await callback.answer()


@router.message(ResellerAddVolume.volume)
async def reseller_add_volume_apply(message: Message, state: FSMContext):
    volume = parse_positive_float(message.text or '')
    if volume is None:
        await ui_message(message, '❌ حجم معتبر نیست. فقط عدد گیگ را وارد کنید. مثال: 20')
        return
    data = await state.get_data()
    sid = int(data.get('service_id') or 0)
    add_bytes = gb_to_bytes(volume)
    try:
        async with SessionLocal() as session:
            user, reseller = await get_user_reseller(session, message.from_user.id)
            if reseller:
                reseller = (await session.execute(
                    select(ResellerAccount).where(ResellerAccount.id == reseller.id).with_for_update()
                )).scalar_one_or_none()
            svc = (await session.execute(
                select(ClientService).where(ClientService.id == sid).with_for_update()
            )).scalar_one_or_none()
            if not svc or not reseller or svc.reseller_id != reseller.id:
                await state.clear()
                await ui_message(message, '❌ یوزر پیدا نشد.', reply_markup=reseller_back_kb('reseller:users'))
                return
            reseller_remaining = max((reseller.total_bytes or 0) - (reseller.reserved_bytes or 0), 0)
            if reseller_remaining < add_bytes:
                await ui_message(
                    message,
                    '❌ حجم باقی‌مانده نمایندگی برای این افزایش حجم کافی نیست.\n\n'
                    f'حجم قابل اضافه: {bytes_to_gb(reseller_remaining):g} گیگ',
                    reply_markup=reseller_back_kb(f'reseller:user:{sid}')
                )
                return
            server = await session.get(Server, svc.server_id)
            if not server:
                await state.clear()
                await ui_message(message, '❌ سرور این یوزر پیدا نشد.', reply_markup=reseller_back_kb('reseller:users'))
                return
            current_total = int(svc.total_bytes or 0)
            new_total = current_total + add_bytes
            try:
                if server.server_type == 'xui':
                    await XuiService().add_client_volume(server, svc.xui_email, volume)
                elif server.server_type == 'mikrotik':
                    await MikroTikService().update_user(server, svc.xui_email or svc.client_username, volume_gb=bytes_to_gb(new_total))
                    try:
                        await MikroTikService().enable_user(server, svc.xui_email or svc.client_username)
                    except Exception:
                        pass
            except Exception as e:
                await session.rollback()
                await handle_user_facing_error(message, e, context='Reseller add volume failed', reply_markup=reseller_back_kb(f'reseller:user:{sid}'))
                return
            reseller.reserved_bytes = (reseller.reserved_bytes or 0) + add_bytes
            svc.total_bytes = new_total
            svc.reseller_reserved_bytes = int(svc.reseller_reserved_bytes or current_total or 0) + add_bytes
            svc.is_active = True
            svc.disabled_at = None
            svc.disabled_reason = None
            svc.disabled_notify_count = 0
            svc.disabled_last_notified_at = None
            svc.notify_1gb_sent = False
            svc.notify_100mb_sent = False
            username = svc.client_username or svc.xui_email or '-'
            remaining_quota = max((reseller.total_bytes or 0) - (reseller.reserved_bytes or 0), 0)
            await session.commit()
    finally:
        pass
    await state.clear()
    await ui_message(
        message,
        '✅ حجم کانفیگ اضافه شد.\n\n'
        f'👤 یوزر: {username}\n'
        f'➕ حجم اضافه‌شده: {volume:g} گیگ\n'
        f'💾 حجم کل جدید: {bytes_to_gb(new_total):g} گیگ\n'
        f'📦 باقی‌مانده سهمیه نماینده: {bytes_to_gb(remaining_quota):g} گیگ\n'
        '🟢 وضعیت: فعال',
        reply_markup=reseller_back_kb(f'reseller:user:{sid}')
    )


@router.callback_query(F.data.startswith('reseller:adddays:'))
async def reseller_add_days_start(callback: CallbackQuery, state: FSMContext):
    sid = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        svc = await session.get(ClientService, sid)
        user, reseller = await get_user_reseller(session, callback.from_user.id)
        if not svc or not reseller or svc.reseller_id != reseller.id:
            await callback.answer('یوزر پیدا نشد.', show_alert=True)
            return
        expire_text = fa_date(svc.expires_at, empty='-') if svc.expires_at else '-'
    await state.clear()
    await state.update_data(service_id=sid)
    await state.set_state(ResellerAddDays.days)
    await edit_or_answer(
        callback,
        '📅 تاریخ اضافه برای یوزر نمایندگی\n\n'
        'این گزینه فقط روز به تاریخ انقضا اضافه می‌کند و حجم/مصرف را تغییر نمی‌دهد.\n'
        'اگر کانفیگ غیرفعال باشد، بعد از افزایش تاریخ فعال می‌شود.\n\n'
        f'تاریخ فعلی انقضا: {expire_text}\n\n'
        'چند روز اضافه شود؟\nمثال: 30',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(f'reseller:user:{sid}')]])
    )
    await callback.answer()


@router.message(ResellerAddDays.days)
async def reseller_add_days_apply(message: Message, state: FSMContext):
    days = parse_positive_int(message.text or '')
    if days is None:
        await ui_message(message, '❌ تعداد روز معتبر نیست. فقط عدد مثبت وارد کنید. مثال: 30')
        return
    data = await state.get_data()
    sid = int(data.get('service_id') or 0)
    try:
        async with SessionLocal() as session:
            user, reseller = await get_user_reseller(session, message.from_user.id)
            svc = (await session.execute(
                select(ClientService).where(ClientService.id == sid).with_for_update()
            )).scalar_one_or_none()
            if not svc or not reseller or svc.reseller_id != reseller.id:
                await state.clear()
                await ui_message(message, '❌ یوزر پیدا نشد.', reply_markup=reseller_back_kb('reseller:users'))
                return
            server = await session.get(Server, svc.server_id)
            if not server:
                await state.clear()
                await ui_message(message, '❌ سرور این یوزر پیدا نشد.', reply_markup=reseller_back_kb('reseller:users'))
                return
            old_expire = svc.expires_at
            new_expires_at = reseller_service_expiry_with_added_days(old_expire, days)
            expire_days_for_panel = max((new_expires_at.date() - datetime.utcnow().date()).days, 1)
            try:
                if server.server_type == 'xui':
                    await XuiService().add_client_days(server, svc.xui_email, days)
                elif server.server_type == 'mikrotik':
                    await MikroTikService().update_user(server, svc.xui_email or svc.client_username, expire_days=expire_days_for_panel)
                    try:
                        await MikroTikService().enable_user(server, svc.xui_email or svc.client_username)
                    except Exception:
                        pass
            except Exception as e:
                await session.rollback()
                await handle_user_facing_error(message, e, context='Reseller add days failed', reply_markup=reseller_back_kb(f'reseller:user:{sid}'))
                return
            svc.expires_at = new_expires_at
            svc.is_active = True
            svc.disabled_at = None
            svc.disabled_reason = None
            svc.disabled_notify_count = 0
            svc.disabled_last_notified_at = None
            svc.notify_24h_sent = False
            svc.notify_2h_sent = False
            svc.notify_20m_sent = False
            username = svc.client_username or svc.xui_email or '-'
            await session.commit()
    finally:
        pass
    await state.clear()
    await ui_message(
        message,
        '✅ تاریخ کانفیگ اضافه شد.\n\n'
        f'👤 یوزر: {username}\n'
        f'📅 روز اضافه‌شده: {days} روز\n'
        f'⏳ تاریخ انقضای جدید: {fa_date(new_expires_at)}\n'
        '🟢 وضعیت: فعال',
        reply_markup=reseller_back_kb(f'reseller:user:{sid}')
    )


@router.callback_query(F.data.startswith('reseller:renew:'))
async def reseller_renew_start(callback: CallbackQuery, state: FSMContext):
    sid = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        svc = await session.get(ClientService, sid)
        user, reseller = await get_user_reseller(session, callback.from_user.id)
        if not svc or not reseller or svc.reseller_id != reseller.id:
            await callback.answer('یوزر پیدا نشد.', show_alert=True)
            return
        # Refresh usage first so the unused-volume credit is calculated from the
        # latest panel traffic, not from stale local data.
        await sync_reseller_service_from_panel(session, svc)
        await session.flush()
        current_reserved = int(svc.reseller_reserved_bytes or svc.total_bytes or 0)
        current_used = int(svc.used_bytes or 0)
        refundable = max(current_reserved - current_used, 0)
        reseller_remaining = max((reseller.total_bytes or 0) - (reseller.reserved_bytes or 0), 0)
        max_gb = bytes_to_gb(reseller_remaining + refundable)
        current_gb = bytes_to_gb(current_reserved)
        used_gb = bytes_to_gb(current_used)
        refundable_gb = bytes_to_gb(refundable)
        total_gb = bytes_to_gb(reseller.total_bytes or 0)
        reserved_gb = bytes_to_gb(reseller.reserved_bytes or 0)
    await state.clear()
    await state.update_data(service_id=sid, max_volume_gb=max_gb)
    await state.set_state(ResellerRenewUser.volume)
    await edit_or_answer(
        callback,
        '🔄 تمدید سرویس نمایندگی\n\n'
        'در تمدید، اول مانده مصرف‌نشده‌ی دوره قبلی به سهمیه نماینده برمی‌گردد، سپس حجم دوره جدید کم می‌شود.\n\n'
        f'حجم دوره فعلی این یوزر: {current_gb:g} گیگ\n'
        f'مصرف‌شده تا الان: {used_gb:g} گیگ\n'
        f'قابل برگشت به سهمیه: {refundable_gb:g} گیگ\n\n'
        f'سهمیه کل نماینده: {total_gb:g} گیگ\n'
        f'رزروشده از سهمیه: {reserved_gb:g} گیگ\n'
        f'حجم قابل تمدید بعد از برگشت مانده: {max_gb:g} گیگ\n\n'
        'چند گیگ برای دوره جدید این یوزر تمدید شود؟\nمثال: 100',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(f'reseller:user:{sid}')]])
    )
    await callback.answer()

@router.message(ResellerRenewUser.volume)
async def reseller_renew_volume(message: Message, state: FSMContext):
    raw = (message.text or '').replace('گیگ', '').replace('GB', '').replace('gb', '').strip()
    try:
        volume = float(raw)
    except ValueError:
        await ui_message(message, '❌ حجم معتبر نیست. فقط عدد گیگ را وارد کنید. مثال: 100')
        return
    if volume <= 0:
        await ui_message(message, '❌ حجم باید بیشتر از صفر باشد.')
        return
    max_volume = (await state.get_data()).get('max_volume_gb')
    if max_volume is not None and volume > float(max_volume):
        await ui_message(message, f'❌ حداکثر حجمی که می‌توانید برای این یوزر تمدید کنید {float(max_volume):g} گیگ است.')
        return
    await state.update_data(volume=volume)
    await state.set_state(ResellerRenewUser.duration)
    await ui_message(
        message,
        '📅 تاریخ انقضا را وارد کنید.\n\nمی‌توانید تعداد روز بنویسید مثل 30\nیا تاریخ دقیق مثل 2026-12-30',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('reseller:renew_back_volume')]])
    )

@router.callback_query(F.data == 'reseller:renew_back_volume')
async def reseller_renew_back_volume(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    sid = int(data.get('service_id') or 0)
    max_gb = data.get('max_volume_gb')
    await state.set_state(ResellerRenewUser.volume)
    text = '🔄 تمدید سرویس نمایندگی\n\n'
    if max_gb is not None:
        text += f'حجم قابل تمدید از سهمیه نماینده: {float(max_gb):g} گیگ\n\n'
    text += 'چند گیگ برای دوره جدید این یوزر تمدید شود؟\nمثال: 100'
    await edit_or_answer(
        callback,
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(f'reseller:user:{sid}' if sid else 'reseller:users')]])
    )
    await callback.answer()


@router.message(ResellerRenewUser.duration)
async def reseller_renew_duration(message: Message, state: FSMContext):
    data = await state.get_data()
    sid = int(data.get('service_id'))
    volume = float(data.get('volume'))
    raw = (message.text or '').strip()
    now = datetime.utcnow()
    expire_days = 0
    expires_at = None
    try:
        if re.match(r'^\d{4}-\d{2}-\d{2}$', raw):
            expires_at = datetime.strptime(raw, '%Y-%m-%d')
            expire_days = max((expires_at.date() - now.date()).days, 1)
        else:
            expire_days = int(raw)
            if expire_days <= 0:
                raise ValueError()
            expires_at = now + timedelta(days=expire_days)
    except Exception:
        await ui_message(message, '❌ تاریخ انقضا معتبر نیست. تعداد روز مثل 30 یا تاریخ مثل 2026-12-30 وارد کنید.')
        return

    new_bytes = gb_to_bytes(volume)
    try:
        async with SessionLocal() as session:
            # Lock the reseller and service rows so two fast renew requests cannot
            # spend the same remaining reseller quota at the same time.
            user, reseller = await get_user_reseller(session, message.from_user.id)
            if reseller:
                reseller = (await session.execute(
                    select(ResellerAccount)
                    .where(ResellerAccount.id == reseller.id)
                    .with_for_update()
                )).scalar_one_or_none()
            svc = (await session.execute(
                select(ClientService)
                .where(ClientService.id == sid)
                .with_for_update()
            )).scalar_one_or_none()
            if not svc or not reseller or svc.reseller_id != reseller.id:
                await state.clear()
                await ui_message(message, '❌ یوزر پیدا نشد.', reply_markup=reseller_back_kb('reseller:users'))
                return

            # Refresh the real traffic from the panel before settlement. This prevents
            # returning more unused traffic than the client really has left.
            await sync_reseller_service_from_panel(session, svc)
            await session.flush()

            old_reserved_bytes = int(svc.reseller_reserved_bytes or svc.total_bytes or 0)
            old_used_bytes = int(svc.used_bytes or 0)
            refundable_bytes = max(old_reserved_bytes - old_used_bytes, 0)
            reseller_remaining = max((reseller.total_bytes or 0) - (reseller.reserved_bytes or 0), 0)
            effective_remaining = reseller_remaining + refundable_bytes
            # Renew is a NEW reseller cycle with settlement of the previous cycle.
            # Example: 100GB quota, 20GB user created => 80GB left.
            # User used 15GB, 5GB is unused. Renew 20GB => 80 + 5 - 20 = 65GB left.
            if effective_remaining < new_bytes:
                await ui_message(
                    message,
                    '❌ حجم باقی‌مانده نمایندگی برای این تمدید کافی نیست.\n\n'
                    f'مانده فعلی نماینده: {bytes_to_gb(reseller_remaining):g} گیگ\n'
                    f'قابل برگشت از دوره قبلی: {bytes_to_gb(refundable_bytes):g} گیگ\n'
                    f'حجم قابل تمدید بعد از برگشت مانده: {bytes_to_gb(effective_remaining):g} گیگ',
                    reply_markup=reseller_back_kb(f'reseller:user:{sid}')
                )
                return
            server = await session.get(Server, svc.server_id)
            if not server:
                await state.clear()
                await ui_message(message, '❌ سرور این یوزر پیدا نشد.', reply_markup=reseller_back_kb('reseller:users'))
                return
            await ui_message(
                message,
                '⏳ یوزر با مشخصات زیر درحال تمدید و ارسال است. لطفاً منتظر بمانید.\n\n'
                f'👤 اسم اختصاصی: {svc.client_username or svc.xui_email or "-"}\n'
                f'💾 حجم جدید: {volume:g} گیگ\n'
                f'📅 مدت: {expire_days} روز\n'
                f'⏳ انقضا: {fa_date(expires_at)}'
            )
            renew_baseline_bytes = 0
            try:
                if server.server_type == 'xui':
                    identifiers = [svc.xui_email, svc.client_username, svc.xui_uuid, svc.sub_link]
                    reset_info = await XuiService().reset_client_plan_any(server, identifiers, volume, expire_days)
                    # If the client was found by UUID/subId/link, keep the local
                    # database aligned with the real email stored in the panel.
                    panel_email = (reset_info or {}).get('panel_email')
                    found_after = (reset_info or {}).get('found') or {}
                    if panel_email:
                        svc.xui_email = panel_email
                        if not svc.client_username:
                            svc.client_username = panel_email
                    client_after = (found_after or {}).get('client') or {}
                    sub_after = client_after.get('subId') or client_after.get('sub_id')
                    if sub_after:
                        svc.sub_link = XuiService().build_subscription_link(server, str(sub_after), svc.xui_email or svc.client_username)
                    # Read the panel counter after renewal.  If resetTraffic did
                    # not really zero the remote counter, this value becomes the
                    # baseline and will not be counted as new-cycle usage.
                    try:
                        after = found_after or await XuiService().find_client_by_identifiers(server, svc.xui_email, svc.client_username, svc.xui_uuid, svc.sub_link)
                        tr = (after or {}).get('traffic') or {}
                        renew_baseline_bytes = int((tr.get('up', 0) or 0) + (tr.get('down', 0) or 0))
                    except Exception:
                        renew_baseline_bytes = old_used_bytes
                elif server.server_type == 'mikrotik':
                    await MikroTikService().renew_user(server, svc.xui_email or svc.client_username, volume_gb=volume, expire_days=expire_days)
                    try:
                        after = await MikroTikService().get_user(server, svc.xui_email or svc.client_username)
                        renew_baseline_bytes = int((after or {}).get('used_bytes') or 0)
                    except Exception:
                        renew_baseline_bytes = old_used_bytes
            except Exception as e:
                await session.rollback()
                await handle_user_facing_error(message, e, context='Reseller renew user on panel failed', reply_markup=reseller_back_kb(f'reseller:user:{sid}'))
                return
            refunded_bytes = await refund_unused_volume(session, svc, reseller)
            reseller.reserved_bytes = (reseller.reserved_bytes or 0) + new_bytes
            svc.total_bytes = new_bytes
            svc.reseller_reserved_bytes = new_bytes
            svc.used_bytes = 0
            svc.traffic_baseline_bytes = int(max(renew_baseline_bytes, 0))
            svc.expires_at = expires_at
            svc.is_active = True
            svc.disabled_at = None
            svc.disabled_reason = None
            svc.disabled_notify_count = 0
            svc.disabled_last_notified_at = None
            svc.notify_1gb_sent = False
            svc.notify_100mb_sent = False
            svc.notify_24h_sent = False
            svc.notify_2h_sent = False
            svc.notify_20m_sent = False
            remaining_quota = max((reseller.total_bytes or 0) - (reseller.reserved_bytes or 0), 0)
            await session.commit()
            username = svc.client_username or svc.xui_email or '-'
    finally:
        pass
    await state.clear()
    try:
        await message.delete()
    except Exception:
        pass
    await ui_message(
        message,
        '✅ یوزر نمایندگی با موفقیت تمدید شد.\n\n'
        f'👤 یوزر: {username}\n'
        f'💾 حجم دوره جدید: {volume:g} گیگ\n'
        f'📅 تاریخ انقضا: {fa_date(expires_at)}\n'
        f'↩️ حجم برگشتی از دوره قبلی: {bytes_to_gb(refunded_bytes):g} گیگ\n'
        f'📦 باقی‌مانده سهمیه نماینده: {bytes_to_gb(remaining_quota):g} گیگ\n'
        '♻️ ترافیک مصرفی ریست شد.\n'
        '📉 حجم تمدید جدید از سهمیه نماینده کم شد.\n'
        '🟢 وضعیت: فعال\n\n'
        'برای برگشت به صفحه اول، دکمه خانه را بزنید.',
        reply_markup=success_home_keyboard(),
    )

@router.callback_query(F.data.startswith('reseller:delete:'))
async def reseller_delete_user_ask(callback: CallbackQuery):
    sid = int(callback.data.split(':')[-1])
    kb=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ تایید حذف کانفیگ', callback_data=f'reseller:delete_confirm:{sid}')],
        [back_button(f'reseller:user:{sid}')],
    ])
    await edit_or_answer(callback, '⚠️ این کانفیگ از پنل و ربات حذف می‌شود. مطمئن هستید؟', reply_markup=kb); await callback.answer()

@router.callback_query(F.data.startswith('reseller:delete_confirm:'))
async def reseller_delete_user(callback: CallbackQuery):
    sid = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        svc = await session.get(ClientService, sid)
        user, reseller = await get_user_reseller(session, callback.from_user.id)
        if not svc or not reseller or svc.reseller_id != reseller.id:
            await callback.answer('یوزر پیدا نشد.', show_alert=True); return
        server = await session.get(Server, svc.server_id)
        name = svc.client_username or svc.xui_email or '-'
        email = svc.xui_email or svc.client_username or '-'
        total_gb = bytes_to_gb(svc.total_bytes)
        used_gb = bytes_to_gb(svc.used_bytes)
        expire_text = fa_date(svc.expires_at, empty='-') if svc.expires_at else '-'
        panel_already_missing = False
        if server and server.server_type == 'xui':
            try:
                await XuiService().delete_client(server, svc.xui_email, svc.client_username, svc.xui_uuid, svc.sub_link)
            except Exception as e:
                msg_l = str(e).lower()
                if 'not found' in msg_l or 'not exist' in msg_l or 'not exists' in msg_l or 'record not found' in msg_l:
                    panel_already_missing = True
                else:
                    await session.rollback()
                    await handle_user_facing_error(callback, e, context='Reseller delete service from panel failed', reply_markup=reseller_back_kb(f'reseller:user:{sid}'))
                    await callback.answer()
                    return
        elif server and server.server_type == 'mikrotik':
            try:
                await MikroTikService().delete_user(server, svc.xui_email or svc.client_username)
            except Exception as e:
                msg_l = str(e).lower()
                # If the client was already manually removed from 3x-ui, allow
                # local cleanup. Other panel errors must stop the local delete
                # so the bot and panel never get out of sync.
                if 'not found' in msg_l or 'not exist' in msg_l or 'not exists' in msg_l or 'record not found' in msg_l:
                    panel_already_missing = True
                else:
                    await session.rollback()
                    await handle_user_facing_error(callback, e, context='Reseller delete service from panel failed', reply_markup=reseller_back_kb(f'reseller:user:{sid}'))
                    await callback.answer()
                    return
        refund = await refund_unused_volume(session, svc, reseller)
        # Soft-delete and keep identifiers as tombstone for safe future cleanup.
        svc.is_active = False
        old_name = (svc.client_username or svc.xui_email or 'client')
        svc.client_username = f'deleted_{svc.id}_{old_name}'[:150]
        await session.commit()
    msg = (
        '✅ سرویس شما با موفقیت حذف شد\n\n'
        '🗑 سرویس شما با مشخصات زیر حذف شد:\n'
        '━━━━━━━━━━━━━━━━\n'
        f'👤 نام کانفیگ: {name}\n'
        f'🆔 ایمیل/یوزرنیم پنل: {email}\n'
        f'💾 حجم کل: {total_gb:.2f} گیگ\n'
        f'📊 مصرف‌شده: {used_gb:.2f} گیگ\n'
        f'⏳ تاریخ انقضا: {expire_text}\n\n'
        f'↩️ حجم برگشتی به سقف نمایندگی: {bytes_to_gb(refund):g} گیگ'
    )
    await edit_or_answer(
        callback,
        msg,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('reseller:users')]])
    )
    await callback.answer('✅ سرویس حذف شد')

@router.callback_query(F.data.startswith('reseller:revoke:'))
async def reseller_revoke(callback: CallbackQuery):
    sid = int(callback.data.split(':')[-1])

    # Rotate subscription/UUID, then send the renewed config with the same
    # beautiful delivery card used by normal purchases.  Do not send the old
    # plain QR/text block here.
    async with SessionLocal() as session:
        svc = await session.get(ClientService, sid)
        user, reseller = await get_user_reseller(session, callback.from_user.id)
        if not svc or not reseller or svc.reseller_id != reseller.id:
            await callback.answer('یوزر پیدا نشد.', show_alert=True)
            return

        server = await session.get(Server, svc.server_id)
        if not server:
            await edit_or_answer(callback, '❌ سرور این کانفیگ پیدا نشد.', reply_markup=reseller_back_kb('reseller:users'))
            await callback.answer()
            return

        try:
            if server.server_type == 'mikrotik':
                new = await MikroTikService().rotate_password(server, svc.xui_email or svc.client_username)
                svc.xui_uuid = str(new.get('password') or svc.xui_uuid or '')
                svc.sub_link = None
            else:
                new = await XuiService().revoke_and_new_link(server, svc.xui_email)
                svc.xui_uuid = (str(new.get('uuid')) if isinstance(new, dict) and new.get('uuid') is not None else None)
                svc.sub_link = new.get('sub_link')
            await session.commit()
            await session.refresh(svc)
        except Exception as e:
            await session.rollback()
            await handle_user_facing_error(callback, e, context='Reseller revoke/regenerate service link failed', reply_markup=reseller_back_kb(f'reseller:user:{sid}'))
            await callback.answer()
            return

        # Snapshot values before leaving the async SQLAlchemy session to avoid
        # lazy-load/MissingGreenlet issues and to keep the outgoing card stable.
        username = svc.client_username or svc.xui_email or '-'
        link = svc.sub_link
        volume_gb = bytes_to_gb(svc.total_bytes or svc.reseller_reserved_bytes or 0)
        if svc.created_at and svc.expires_at:
            try:
                duration_days = max((svc.expires_at.date() - svc.created_at.date()).days, 0)
            except Exception:
                duration_days = 0
        elif svc.expires_at:
            try:
                duration_days = max((svc.expires_at.date() - datetime.utcnow().date()).days, 0)
            except Exception:
                duration_days = 0
        else:
            duration_days = 0
        plan_title = f'نمایندگی | {volume_gb:g} گیگ | {duration_days} روز'

    caption = build_service_caption(
        username=username,
        title=plan_title,
        volume_gb=volume_gb,
        duration_days=duration_days,
        sub_link=link,
        is_test=False,
        server_type=server.server_type if 'server' in locals() and server else 'xui',
        password=svc.xui_uuid if 'svc' in locals() and svc else None,
    )

    # Send the renewed config EXACTLY like the normal public purchase flow:
    # same QR card, same caption builder, and no extra inline buttons under the
    # service card.  Navigation stays in the original message.
    try:
        await send_service_card(
            callback.message.bot,
            callback.from_user.id,
            username,
            plan_title,
            volume_gb,
            duration_days,
            link,
            is_test=False,
            service_id=sid,
            server_type=server.server_type if 'server' in locals() and server else 'xui',
            password=svc.xui_uuid if 'svc' in locals() and svc else None,
        )
        await edit_or_answer(
            callback,
            '✅ لینک قبلی باطل شد و لینک جدید دقیقاً مثل خرید عمومی برای شما ارسال شد.',
            reply_markup=reseller_home_kb(),
        )
        await callback.answer('✅ لینک جدید ارسال شد')
    except Exception:
        # Fallback keeps the same purchase-style text if QR generation/sending fails.
        await edit_or_answer(callback, caption, parse_mode='HTML', reply_markup=reseller_home_kb())
        await callback.answer('✅ لینک جدید ساخته شد')

@router.callback_query(F.data.startswith('reseller:help:'))
async def reseller_help(callback: CallbackQuery):
    await edit_or_answer(callback, '📖 راهنمای اتصال\n\n⚠️ فقط و فقط برنامه Happ مورد تایید ما هستش. اگر از برنامه دیگری استفاده می‌کنید، هرچه زودتر از App Store یا Google Play نصبش کنید.\n\nدر غیر این صورت، وصل نشدن سرورها مسئولیتش با خود شماست و در پشتیبانی خدماتی ارائه نمی‌شود.\n\n✅ مراحل اضافه کردن در Happ:\n1) برنامه Happ را باز کنید.\n2) روی + بزنید.\n3) Import / Subscription را انتخاب کنید.\n4) لینک ساب را وارد و ذخیره کنید.\n\n♻️ هر ۱۲ ساعت برای بروزرسانی، داخل Happ روی Subscription همان سرویس بزنید و Update / Refresh Subscription را انتخاب کنید.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('reseller:users')]])); await callback.answer()
