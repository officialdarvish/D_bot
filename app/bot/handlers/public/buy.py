from datetime import datetime, timedelta
import random, string, re
from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy import select, func
from app.core.config import settings
from app.database.session import SessionLocal
from app.database.models import User, Server, ServerCategory, Plan, PaymentCard, Order, ClientService, DiscountCode, DiscountUsage, Setting
from app.bot.states.public_states import BuyFlow, QueryClient, DiscountInput
from app.services.xui_service import XuiService
from app.services.mikrotik_service import MikroTikService
from app.services.nowpayments_service import NowPaymentsService
from app.bot.keyboards.common import CB_BUY, CB_QUERY, back_button, back_main_inline, main_menu_inline
from app.database.defaults import get_setting_value, WELCOME_TEXT_DEFAULT
from app.bot.utils import send_single_message, edit_or_answer, ui_message, ui_callback_message
from app.bot.error_reporting import handle_user_facing_error
from app.bot.service_presenter import send_service_info as send_service_card
from app.services.referral_service import apply_purchase_commission
from app.services.plan_order import saved_plan_order, sort_by_saved_order
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

async def replace_admin_receipt_buttons(callback: CallbackQuery, text: str = '✅ تایید شد') -> None:
    try:
        await callback.message.edit_reply_markup(reply_markup=approved_only_keyboard(text))
    except Exception:
        pass


def rnd_suffix(): return ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))
def extract_key(text: str) -> str:
    text=text.strip()
    m=re.search(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}', text)
    if m: return m.group(0)
    return text.rstrip('/').split('/')[-1].split('?')[0].split('#')[0]

def valid_mikrotik_password(text: str) -> bool:
    value = (text or '').strip()
    return bool(re.fullmatch(r'[A-Za-z0-9@._\-]{6,32}', value))

MIKROTIK_PASSWORD_PROMPT = (
    '🔐 حالا یک پسوورد برای سرویس خود انتخاب کنید.\n\n'
    '✅ فرمت قابل قبول:\n'
    '▫️ بین ۶ تا ۳۲ کاراکتر باشد.\n'
    '▫️ فقط حروف انگلیسی کوچک و بزرگ، عدد و کاراکترهای @ . _ - مجاز است.\n'
    '▫️ نمونه قابل قبول: Gift_1234\n\n'
    '⚠️ به حروف کوچک و بزرگ دقت کنید؛ مثلاً Gift_1234 با gift_1234 فرق دارد.\n'
    '❌ از فاصله، حروف فارسی و کاراکترهای غیرمجاز استفاده نکنید.'
)

MIKROTIK_USERNAME_PROMPT = (
    '👤 یک یوزرنیم اختصاصی برای سرویس خود انتخاب کنید.\n\n'
    '✅ فرمت قابل قبول:\n'
    '▫️ فقط حروف انگلیسی، عدد و آندرلاین (_) مجاز است.\n'
    '▫️ فاصله، خط تیره و کاراکتر فارسی وارد نکنید.\n'
    '▫️ نمونه قابل قبول: ali_123\n\n'
    'بعد از این مرحله، پسورد سرویس را هم خودتان انتخاب می‌کنید.\n'
    '⚠️ به حروف کوچک و بزرگ دقت کنید.'
)
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

def percent_bar(used: int, total: int, width: int = 14) -> str:
    if not total or total <= 0:
        return '▱' * width
    ratio = max(0, min(1, (used or 0) / total))
    filled = int(round(ratio * width))
    return '▰' * filled + '▱' * (width - filled)

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
        f'├ 💾 حجم کل: {gb(total):.2f} گیگ\n'
        f'├ 📈 مصرف‌شده: {gb(used):.2f} گیگ\n'
        f'├ ⏳ باقی‌مانده: {gb(remain):.2f} گیگ\n'
        f'╰ {percent_bar(used, total)} {pct}%\n\n'
        '— ✦ Darvish D Bot ✦ —'
    )


async def apply_discount_amount(session, code: str | None, amount: int, user_id: int | None = None, source: str = 'buy', server_id: int | None = None) -> tuple[int, str | None, DiscountCode | None]:
    if not code:
        return amount, None, None
    clean = code.strip().upper().replace(' ', '')
    d = (await session.execute(select(DiscountCode).where(func.upper(DiscountCode.code) == clean, DiscountCode.is_active == True))).scalar_one_or_none()
    if not d:
        return amount, 'کد تخفیف معتبر نیست.', None
    if d.expires_at and d.expires_at < datetime.utcnow():
        return amount, 'کد تخفیف منقضی شده است.', None
    if d.max_uses and d.used_count >= d.max_uses:
        return amount, 'ظرفیت استفاده از این کد تکمیل شده است.', None
    allowed_servers = []
    try:
        allowed_servers = [int(x) for x in (getattr(d, 'allowed_server_ids', None) or []) if int(x) > 0]
    except Exception:
        allowed_servers = []
    if allowed_servers and (not server_id or int(server_id) not in allowed_servers):
        return amount, 'این کد تخفیف برای سرور انتخابی شما فعال نیست.', None
    if user_id and getattr(d, 'per_user_limit', 1):
        used_by_user = (await session.execute(
            select(func.count(DiscountUsage.id)).where(DiscountUsage.discount_id == d.id, DiscountUsage.user_id == user_id)
        )).scalar() or 0
        if used_by_user >= d.per_user_limit:
            return amount, f'شما قبلاً از این کد {used_by_user} بار استفاده کرده‌اید و سقف استفاده شما تکمیل شده است.', None
    if d.discount_type == 'percent':
        discount = int(amount * min(max(d.value, 0), 100) / 100)
    else:
        discount = int(d.value)
    final = max(amount - discount, 0)
    return final, None, d

async def mark_discount_used(session, discount_obj: DiscountCode | None, user_id: int, source: str = 'buy') -> None:
    if not discount_obj:
        return
    discount_obj.used_count += 1
    session.add(DiscountUsage(discount_id=discount_obj.id, user_id=user_id, source=source))

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
                select(ServerCategory).where(ServerCategory.is_active == True)
            )).scalars().all()
            cats=[cat for cat in all_cats if category_matches_servers(cat, server_ids)]

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
        all_cats=(await session.execute(select(ServerCategory).where(ServerCategory.is_active == True))).scalars().all(); cats=[cat for cat in all_cats if category_matches_servers(cat, [sid])]
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
        prompt = 'یک یوزرنیم اختصاصی با حروف انگلیسی و عدد وارد کنید:'
    await edit_or_answer(callback, prompt, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(back_cb)]])); await safe_callback_answer(callback)

@router.message(BuyFlow.username)
async def buy_username(message: Message, state: FSMContext):
    username=message.text.strip().replace(' ','')
    data=await state.get_data()
    async with SessionLocal() as session:
        server=await session.get(Server, data['server_id'])
        plan=await session.get(Plan, data['plan_id'])
        user=(await session.execute(select(User).where(User.telegram_id == message.from_user.id))).scalar_one()
        final_username = await pick_available_username(session, server, username)
        if message.from_user.id in settings.admin_ids and getattr(server, 'server_type', '') != 'mikrotik':
            try:
                service, sub_link = await build_service(session, user, server, plan, final_username, password=(data.get('password') if server.server_type == 'mikrotik' else None))
                session.add(Order(user_id=user.id, plan_id=plan.id, service_id=service.id, amount_irt=0, payment_method='admin_free', status='paid'))
                await session.commit()
            except Exception as e:
                await session.rollback()
                await handle_user_facing_error(message, e, context='Public buy admin-free service creation failed', reply_markup=back_main_inline())
                await state.clear()
                return
            await state.clear()
            await send_service_info(message.bot, message.from_user.id, service.client_username, plan, sub_link, service.id, server.server_type, (service.xui_uuid if server.server_type == 'mikrotik' else None), server)
            await send_home(message.bot, message.from_user.id, True)
            return
    if final_username != username:
        username = final_username
        await ui_message(message, f'این یوزرنیم قبلاً استفاده شده بود. یوزرنیم جدید شما: {username}')
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
    password = (message.text or '').strip()
    if not valid_mikrotik_password(password):
        await ui_message(message, '❌ پسورد معتبر نیست. لطفاً دقیقاً طبق نمونه ارسال کنید.\n\n' + MIKROTIK_PASSWORD_PROMPT, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('pay:back_username')]]))
        return
    await state.update_data(password=password)
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
    username = await pick_available_username(session, server, username)
    service=ClientService(user_id=user.id, server_id=server.id, plan_id=plan.id, client_username=username, xui_email=username, inbound_ids=plan.inbound_ids, total_bytes=plan.volume_gb*1024**3, expires_at=(datetime.utcnow()+timedelta(days=plan.duration_days) if plan.duration_days else None), is_payg=plan.is_payg)
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

@router.callback_query(F.data.in_({'pay:wallet','pay:card','pay:crypto'}))
async def buy_payment(callback: CallbackQuery, state: FSMContext):
    data=await state.get_data()
    async with SessionLocal() as session:
        user=(await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one()
        plan=await session.get(Plan,data['plan_id']); server=await session.get(Server,data['server_id'])
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
                pay = await NowPaymentsService().create_payment(order_id=order.id, amount_irt=final_amount, description=f'Darvish D Bot - {plan.title}')
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
            try:
                service, sub_link = await build_service(session, user, server, plan, data['username'], password=(data.get('password') if server.server_type == 'mikrotik' else None))
            except Exception as e:
                await session.rollback(); await handle_user_facing_error(callback, e, context='Public buy wallet service creation failed', reply_markup=back_main_inline()); await state.clear(); await safe_callback_answer(callback); return
            
            await mark_discount_used(session, discount_obj, user.id, 'buy')
            session.add(Order(user_id=user.id, plan_id=plan.id, service_id=service.id, amount_irt=final_amount, payment_method=('wallet' + (f':discount:{discount_code}' if discount_code else '')), status='paid'))
            commission_amount = await apply_purchase_commission(session, user, int(final_amount or 0), callback.message.bot, server.server_type)
            await session.commit(); await state.clear(); await safe_callback_answer(callback)
            await send_service_info(callback.message.bot, callback.from_user.id, service.client_username, plan, sub_link, service.id, server.server_type, (service.xui_uuid if server.server_type == 'mikrotik' else None), server)
            await send_home(callback.message.bot, callback.from_user.id, callback.from_user.id in settings.admin_ids)
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
        await session.commit()
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='✅ تایید رسید', callback_data=f'order:approve:{data["order_id"]}')],[InlineKeyboardButton(text='❌ رد رسید', callback_data=f'order:reject:{data["order_id"]}')]])
    discount_code = None
    if order.payment_method and ':discount:' in order.payment_method:
        discount_code = order.payment_method.split(':discount:', 1)[1]
    original_amount = int(plan.price_irt or 0)
    discount_info = f'🏷 کد تخفیف: {discount_code}\n💵 مبلغ نهایی: {order.amount_irt:,} تومان\n' if discount_code else ''
    caption = (
        f'🧾 رسید سفارش #{data["order_id"]}\n'
        f'━━━━━━━━━━━━━━\n'
        f'👤 نام مشتری: {message.from_user.full_name}\n'
        f'🔢 آیدی عددی: {message.from_user.id}\n'
        f'🆔 یوزرنیم تلگرام: {message.from_user.username or "ندارد"}\n\n'
        f'👥 یوزرنیم سرویس: {data.get("username")}\n'
        + (f'🔐 پسورد انتخابی: {data.get("password")}\n' if data.get('password') else '')
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

@router.callback_query(F.data.startswith('order:approve:'))
async def approve_order_cb(callback: CallbackQuery):
    if callback.from_user.id not in settings.admin_ids: return
    await safe_callback_answer(callback, 'در حال تایید رسید...', show_alert=False)
    oid=int(callback.data.split(':')[-1])
    await mark_message_status(callback, '⏳ در حال تایید رسید...')

    # Config/service delivery must go ONLY to the buyer.  The admin who presses
    # approve should only receive a short confirmation in the admin chat.
    buyer_chat_id = None
    buyer_is_admin = False
    service_username = None
    service_sub_link = None
    plan_title = None
    plan_volume_gb = None
    plan_duration_days = None

    async with SessionLocal() as session:
        order=await session.get(Order,oid)
        if not order or order.status == 'paid':
            await mark_message_status(callback, '✅ رسید تایید شد.')
            await safe_callback_answer(callback, 'قبلاً تایید شده است.', show_alert=False)
            return
        user=await session.get(User,order.user_id); plan=await session.get(Plan,order.plan_id); server=await session.get(Server,plan.server_id)
        buyer_chat_id = int(user.telegram_id)
        buyer_is_admin = buyer_chat_id in settings.admin_ids
        plan_title = plan.title
        plan_volume_gb = plan.volume_gb
        plan_duration_days = plan.duration_days
        server_type_value = server.server_type if server else 'xui'
        server_meta_value = dict(server.meta or {}) if server else {}
        username=order.payment_method.split(':',1)[1].split(':discount:',1)[0] if order.payment_method and (order.payment_method.startswith('card:') or order.payment_method.startswith('crypto:')) else f'user{user.telegram_id}_{order.id}'
        pending_password = ''
        if server and server.server_type == 'mikrotik' and (order.external_invoice_url or '').startswith('mtpass:'):
            pending_password = (order.external_invoice_url or '')[7:]
        if order.payment_method and order.payment_method.startswith('renew:') and order.service_id:
            service=await session.get(ClientService, order.service_id)
            if server.server_type == 'xui':
                try:
                    await XuiService().reset_client_plan(server, service.xui_email, plan.volume_gb, plan.duration_days)
                except Exception as e:
                    await session.rollback()
                    await handle_user_facing_error(callback, e, context='Admin approval renewal on panel failed')
                    await safe_callback_answer(callback)
                    return
            elif server.server_type == 'mikrotik':
                try:
                    await MikroTikService().renew_user(server, service.xui_email, volume_gb=plan.volume_gb, expire_days=plan.duration_days)
                except Exception as e:
                    await session.rollback()
                    await handle_user_facing_error(callback, e, context='Admin approval MikroTik renewal failed')
                    await safe_callback_answer(callback)
                    return
            service.total_bytes=plan.volume_gb*1024**3
            service.used_bytes=0
            service.expires_at=datetime.utcnow()+timedelta(days=plan.duration_days) if plan.duration_days else None
            service.is_active=True
            sub_link=service.sub_link
        else:
            try: service, sub_link=await build_service(session,user,server,plan,username, password=(pending_password or None))
            except Exception as e:
                await session.rollback(); await handle_user_facing_error(callback, e, context='Admin approval service creation on panel failed'); await safe_callback_answer(callback); return
        service_username = service.client_username
        service_sub_link = sub_link
        service_password = service.xui_uuid if (server.server_type == 'mikrotik') else None
        order.status='paid'; order.service_id=service.id
        commission_amount = await apply_purchase_commission(session, user, int(order.amount_irt or 0), callback.message.bot, server.server_type)
        await session.commit()

    await mark_message_status(callback, '✅ رسید تایید شد.')

    await send_service_card(
        callback.message.bot,
        buyer_chat_id,
        service_username,
        plan_title,
        plan_volume_gb,
        plan_duration_days,
        service_sub_link,
        is_test=False,
        service_id=order.service_id,
        server_type=server_type_value if 'server_type_value' in locals() else (server.server_type if 'server' in locals() and server else 'xui'),
        password=service_password if 'service_password' in locals() else None,
        l2tp_server=(server_meta_value.get('l2tp_server') if 'server_meta_value' in locals() else None),
        l2tp_ipsec_secret=(server_meta_value.get('l2tp_ipsec_secret') if 'server_meta_value' in locals() else None),
    )
    await send_home(callback.message.bot, buyer_chat_id, buyer_is_admin)

    admin_text = (
        '✅ رسید تایید شد و سرویس فقط برای خریدار ارسال شد.\n\n'
        f'👤 خریدار: {buyer_chat_id}\n'
        f'📦 پلن: {plan_title}\n'
        f'🔐 کانفیگ: {service_username}'
    )
    if 'commission_amount' in locals() and commission_amount:
        admin_text += f'\n🎁 پورسانت معرف: {commission_amount:,} تومان'
    await ui_callback_message(callback, admin_text)
    await send_home(callback.message.bot, callback.from_user.id, True)

@router.callback_query(F.data.startswith('order:reject:'))
async def reject_order_cb(callback: CallbackQuery):
    if callback.from_user.id not in settings.admin_ids:
        return
    await safe_callback_answer(callback, 'در حال رد رسید...', show_alert=False)
    oid = int(callback.data.split(':')[-1])
    await mark_message_status(callback, '⏳ در حال رد رسید...')
    async with SessionLocal() as session:
        order = await session.get(Order, oid)
        if not order:
            await mark_message_status(callback, '❌ سفارش پیدا نشد.')
            return
        if order.status == 'rejected':
            await mark_message_status(callback, '❌ رسید قبلاً رد شده است.')
            return
        user = await session.get(User, order.user_id)
        order.status = 'rejected'
        await session.commit()
    if user:
        await callback.message.bot.send_message(user.telegram_id, '❌ خرید ناموفق بود؛ رسید شما رد شد. لطفاً با پشتیبانی در ارتباط باشید.')
    await mark_message_status(callback, '❌ رسید رد شد.')
    await ui_callback_message(callback, 'رسید رد شد.')
    await send_home(callback.message.bot, callback.from_user.id, True)


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


def _openvpn_result_text(server: Server, username: str, password: str, local: ClientService | None, plan: Plan | None, remote: dict | None = None) -> str:
    meta = server.meta or {}
    lines = [
        '✅ مشخصات سرویس OpenVPN / MikroTik پیدا شد',
        '╭━━━━━━━━━━━━━━━━━━━━╮',
        f'│ 🖥 سرور: {_query_server_label(server)}',
        f'│ 👤 Username: {username}',
        f'│ 🔐 Password: {password or (local.xui_uuid if local and local.xui_uuid else "-")}',
    ]
    if local:
        lines += [
            f'│ 📦 پلن: {plan.title if plan else "نامشخص"}',
            f'│ 🟢 وضعیت: {"فعال" if local.is_active else "غیرفعال"}',
            f'│ ⏳ انقضا: {fa_date(local.expires_at) if local.expires_at else "نامحدود"}',
            f'│ 💾 حجم کل: {gb(local.total_bytes or 0):.2f} گیگ',
            f'│ 📈 مصرف: {gb(local.used_bytes or 0):.2f} گیگ',
        ]
        if local.sub_link:
            lines.append(f'│ 🔗 لینک/فایل: {local.sub_link}')
    if remote:
        lines += [
            f'│ 🌐 IP ریموت: {remote.get("remote_address") or "-"}',
            f'│ 🔌 آنلاین: {"بله" if remote.get("online") else "خیر"}',
            f'│ 🚦 وضعیت پنل: {"غیرفعال" if remote.get("disabled") else "فعال"}',
            f'│ 📅 انقضا: {fa_date(remote.get("expire_at")) if remote.get("expire_at") else "نامحدود"}',
            f'│ 📊 مصرف: {gb(int(remote.get("used_bytes") or 0)):.2f} گیگ',
            f'│ ⚡ سرعت صف: {remote.get("queue_max_limit") or "-"}',
        ]
    lines += ['╰━━━━━━━━━━━━━━━━━━━━╯', '', '— ✦ Darvish D Bot ✦ —']
    return '\n'.join(lines)


async def _process_query_lookup(message: Message, state: FSMContext, password: str = '') -> None:
    data = await state.get_data()
    server_id = int(data.get('server_id') or 0)
    username = extract_key(str(data.get('username') or message.text or ''))
    result_text = ''
    async with SessionLocal() as session:
        server = await session.get(Server, server_id)
        if not server:
            await state.clear()
            await ui_message(message, 'سرور انتخاب‌شده پیدا نشد. لطفاً دوباره تلاش کنید.', reply_markup=query_home_keyboard())
            return
        local = (await session.execute(select(ClientService).where(
            ClientService.server_id == server.id,
            (ClientService.client_username == username) | (ClientService.xui_email == username) | (ClientService.xui_uuid == username)
        ))).scalar_one_or_none()
        plan = await session.get(Plan, local.plan_id) if local and local.plan_id else None

        if _query_needs_password(server):
            remote = None
            if server.server_type == 'mikrotik':
                try:
                    remote = await MikroTikService().get_user(server, username)
                except Exception:
                    remote = None
            if local or remote:
                result_text = _openvpn_result_text(server, username, password, local, plan, remote)
        else:
            if local:
                result_text = pretty_config_result(
                    username=local.client_username,
                    active=bool(local.is_active),
                    plan_title=plan.title if plan else 'نامشخص',
                    created_at=fa_date(local.created_at, empty='-') if local.created_at else '-',
                    expires_at=fa_date(local.expires_at) if local.expires_at else 'نامحدود',
                    total=local.total_bytes or 0,
                    used=local.used_bytes or 0,
                    uuid=local.xui_uuid or None,
                )
            else:
                try:
                    found = await XuiService().find_client_any(server, username) if server.server_type == 'xui' else None
                except Exception:
                    found = None
                if found:
                    c = found.get('client', {})
                    tr = found.get('traffic') or {}
                    up = tr.get('up', 0) or 0
                    down = tr.get('down', 0) or 0
                    total = tr.get('total', c.get('totalGB', 0)) or 0
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
    await state.clear()
    await ui_message(message, result_text or 'کانفیگ پیدا نشد. لطفاً سرور و اطلاعات ورود را دقیق‌تر انتخاب/ارسال کنید.', reply_markup=query_result_keyboard())


@router.callback_query(F.data == CB_QUERY)
async def query_start(callback: CallbackQuery, state: FSMContext):
    async with SessionLocal() as session:
        servers = await _query_public_servers(session)
    if not servers:
        await ui_callback_message(callback, 'فعلاً سرور فعالی برای بررسی مشخصات کانفیگ ثبت نشده است.', reply_markup=query_home_keyboard())
        await safe_callback_answer(callback)
        return
    rows = [[InlineKeyboardButton(text=_query_server_label(s), callback_data=f'query:server:{s.id}')] for s in servers]
    rows.append([back_button('back:main')])
    await state.clear()
    await state.set_state(QueryClient.server_id)
    await ui_callback_message(callback, 'اول سروری که کانفیگ روی آن ساخته شده را انتخاب کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await safe_callback_answer(callback)


@router.callback_query(F.data.startswith('query:server:'))
async def query_pick_server(callback: CallbackQuery, state: FSMContext):
    sid = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        server = await session.get(Server, sid)
    if not server:
        await ui_callback_message(callback, 'سرور انتخاب‌شده پیدا نشد.', reply_markup=query_home_keyboard())
        await safe_callback_answer(callback)
        return
    await state.update_data(server_id=sid, needs_password=_query_needs_password(server))
    await state.set_state(QueryClient.username)
    if _query_needs_password(server):
        text = 'یوزرنیم سرویس OpenVPN را ارسال کنید:'
    else:
        text = 'یوزرنیم اختصاصی V2Ray را ارسال کنید:'
    await ui_callback_message(callback, text, reply_markup=query_home_keyboard('menu:query'))
    await safe_callback_answer(callback)


@router.message(QueryClient.username)
async def query_username(message: Message, state: FSMContext):
    username = extract_key(message.text or '')
    if not username:
        await ui_message(message, 'یوزرنیم معتبر نیست. دوباره ارسال کنید.', reply_markup=query_home_keyboard())
        return
    data = await state.get_data()
    await state.update_data(username=username)
    if data.get('needs_password'):
        await state.set_state(QueryClient.password)
        await ui_message(message, 'حالا پسورد سرویس OpenVPN را ارسال کنید:', reply_markup=query_home_keyboard('query:back_username'))
        return
    await _process_query_lookup(message, state)


@router.callback_query(F.data == 'query:back_username')
async def query_back_to_username(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    sid = int(data.get('server_id') or 0)
    async with SessionLocal() as session:
        server = await session.get(Server, sid) if sid else None
    if not server:
        await query_start(callback, state)
        return
    await state.set_state(QueryClient.username)
    await state.update_data(server_id=sid, needs_password=_query_needs_password(server), username=None)
    if _query_needs_password(server):
        text = 'یوزرنیم سرویس OpenVPN را ارسال کنید:'
    else:
        text = 'یوزرنیم اختصاصی V2Ray را ارسال کنید:'
    await ui_callback_message(callback, text, reply_markup=query_home_keyboard('menu:query'))
    await safe_callback_answer(callback)


@router.message(QueryClient.password)
async def query_password(message: Message, state: FSMContext):
    await _process_query_lookup(message, state, password=(message.text or '').strip())
