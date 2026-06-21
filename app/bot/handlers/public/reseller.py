from __future__ import annotations
from datetime import datetime, timedelta
from types import SimpleNamespace
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.fsm.context import FSMContext
from sqlalchemy import select, func
import qrcode, tempfile, re, logging, random, string, asyncio
from app.database.session import SessionLocal
from app.database.models import User, Server, Plan, PaymentCard, ResellerAccount, ResellerPackage, ResellerTopupRequest, ResellerAccessRequest, ClientService, DiscountCode, DiscountUsage
from app.bot.keyboards.common import CB_RESELLER, back_button, back_main_inline
from app.bot.states.public_states import ResellerCreateUser, ResellerTopupFlow, ResellerDiscountInput
from app.bot.utils import edit_or_answer, ui_message, forget_ui_message
from app.bot.service_presenter import build_service_caption, send_service_info as send_service_card
from app.bot.qr_card import make_qr_card
from app.services.reseller_service import gb_to_bytes, bytes_to_gb, get_user_reseller, is_reseller_access_active, reseller_stats, reserve_volume_for_service, refund_unused_volume, create_reseller_access_request
from app.services.xui_service import XuiService
from app.xui.client import XuiClientPayload
from app.core.config import settings

router = Router()
logger = logging.getLogger(__name__)

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

def reseller_payment_kb(pid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🏷 اعمال کد تخفیف', callback_data='reseller:discount')],
        [InlineKeyboardButton(text='💳 پرداخت کارت به کارت', callback_data='reseller:pay_card')],
        [back_button('reseller:topup')],
    ])

def reseller_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='➕ شارژ حجم', callback_data='reseller:topup'), InlineKeyboardButton(text='🧩 ساخت یوزر', callback_data='reseller:create')],
        [InlineKeyboardButton(text='👥 یوزرها', callback_data='reseller:users')],
        [InlineKeyboardButton(text='🏠 خانه اول', callback_data='back:main')],
    ])


def reseller_back_kb(target: str = 'menu:reseller') -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='🔙 برگشت به منو نمایندگی', callback_data=target)]])

def install_text(link: str | None) -> str:
    return f'🔗 لینک اتصال:\n{link or "لینک ساخته نشد"}\n\nبرنامه پیشنهادی: Happ / V2rayNG'

def reseller_home_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='🏠 برگشت به خانه اول', callback_data='back:main')], [InlineKeyboardButton(text='💼 منو نمایندگی', callback_data='menu:reseller')]])

def reseller_users_kb(services: list[ClientService]) -> InlineKeyboardMarkup:
    rows = []
    for s in services:
        remain = max((s.total_bytes or 0) - (s.used_bytes or 0), 0)
        rows.append([InlineKeyboardButton(text=f'{"🟢" if s.is_active else "🔴"} {s.client_username} | {bytes_to_gb(s.used_bytes)}GB مصرف | {bytes_to_gb(remain)}GB مانده', callback_data=f'reseller:user:{s.id}')])
    rows.append([InlineKeyboardButton(text='🔄 بروزرسانی مصرف', callback_data='reseller:users_refresh')])
    rows.append([InlineKeyboardButton(text='🔙 برگشت به منو نمایندگی', callback_data='menu:reseller')])
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

def reseller_created_text(username: str, volume: float, days: int, link: str | None, remaining_gb: float) -> str:
    return build_service_caption(
        username=username,
        title=f'نمایندگی | {volume:g} گیگ | {days} روز',
        volume_gb=volume,
        duration_days=days,
        sub_link=link,
        is_test=False,
    )

def clean_username(text: str) -> str:
    return re.sub(r'[^A-Za-z0-9_]', '', (text or '').strip().replace(' ', ''))


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
        return candidate
    return f'{clean}_{rnd_suffix()}{rnd_suffix()}'



async def sync_reseller_service_from_panel(session, svc) -> bool | None:
    """Refresh reseller client usage from X-UI before showing it.

    Returns True if refreshed, False if the panel says the client is missing,
    and None if panel/server is unavailable. This keeps reseller pages showing
    real used/remaining traffic instead of stale local values.
    """
    server = await session.get(Server, svc.server_id) if svc else None
    if not svc or not server or server.server_type != 'xui':
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
        svc.used_bytes = int(used or 0)
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
        select(ClientService).where(ClientService.reseller_id == reseller.id, ClientService.is_active == True)
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
    # Online count is calculated with the same lightweight source used in user list.
    services = (await session.execute(select(ClientService).where(ClientService.reseller_id == reseller.id, ClientService.is_active == True))).scalars().all()
    online_count = 0
    for svc in services:
        ips = svc.anti_share_last_ips or []
        if ips:
            online_count += 1
    return (
        '💼 <b>منو نمایندگی VPN Bot</b>\n'
        '━━━━━━━━━━━━━━━━━━━━━━\n\n'
        '📊 <b>وضعیت لحظه‌ای نمایندگی</b>\n\n'
        f'👥 <b>تعداد کل یوزرها:</b> {stats["total_users"]}\n'
        f'🟢 <b>یوزرهای آنلاین:</b> {online_count}\n\n'
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

def _reseller_package_button_text(package: ResellerPackage) -> str:
    # Public reseller top-up buttons should be fixed and compact:
    # 🟢 #1 --- 100 گیگ --- 800,000 تومان
    volume_text = f'{package.volume_gb:g} گیگ'
    return f'🟢 #{package.id} --- {volume_text} --- {package.price_irt:,} تومان'


@router.callback_query(F.data == 'reseller:topup')
async def reseller_topup(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    async with SessionLocal() as session:
        packages = (await session.execute(select(ResellerPackage).where(ResellerPackage.is_active == True).order_by(ResellerPackage.id.asc()))).scalars().all()
    if not packages:
        await edit_or_answer(callback, 'فعلاً هیچ بسته نمایندگی ثبت نشده است.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('menu:reseller')]])); await callback.answer(); return
    rows = []
    for p in packages:
        rows.append([InlineKeyboardButton(text=_reseller_package_button_text(p), callback_data=f'reseller:pkg:{p.id}')])
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
    await state.set_state(ResellerDiscountInput.code)
    await edit_or_answer(callback, '🏷 کد تخفیف نمایندگی را وارد کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('reseller:pay_card')]]))
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
        await ui_message(message, '❌ ' + err, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('reseller:topup')]])); return
    await state.update_data(reseller_discount_code=code, reseller_final_amount=final)
    await ui_message(message, f'✅ کد تخفیف اعمال شد.\n\nمبلغ قبلی: {pkg.price_irt:,} تومان\nمبلغ جدید: {final:,} تومان\n\nبرای ادامه پرداخت را بزنید.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='💳 پرداخت کارت به کارت', callback_data='reseller:pay_card')],[back_button('reseller:topup')]]))

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
        await edit_or_answer(callback, 'برای خرید حجم نمایندگی هنوز کارت پرداخت ثبت نشده است. لطفاً با پشتیبانی تماس بگیرید.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('reseller:topup')]])); await callback.answer(); return
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
    await edit_or_answer(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('reseller:topup')]])); await callback.answer()

async def notify_admins_for_reseller_topup(message: Message, request_id: int, user: User, pkg: ResellerPackage, receipt_file_id: str | None = None, is_photo: bool = False) -> None:
    full_name = user.full_name or message.from_user.full_name or '-'
    username = user.username or message.from_user.username or '-'
    caption = (
        '🧾 رسید جدید شارژ حجم نمایندگی\n\n'
        f'شماره درخواست: #{request_id}\n'
        f'کاربر: {full_name} | @{username}\n'
        f'Telegram ID: {user.telegram_id}\n\n'
        f'📦 پلن: {pkg.title if pkg else "-"}\n'
        f'💾 حجم: {pkg.volume_gb if pkg else "-"} گیگ\n'
        f'💰 مبلغ: {pkg.price_irt if pkg else 0:,} تومان\n\n'
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
        await ui_message(message, 'لطفاً رسید را به صورت عکس، اسکرین‌شات یا فایل ارسال کنید.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('reseller:topup')]])); return
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
    await notify_admins_for_reseller_topup(message, request_id, user_info, pkg_info, receipt, is_photo)
    await state.clear()
    await ui_message(message, f'✅ رسید شارژ حجم نمایندگی ارسال شد.\nشماره درخواست: #{request_id}\nبعد از تایید مدیر، حجم به سقف نمایندگی شما اضافه می‌شود.', reply_markup=reseller_menu())

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
    username = clean_username(message.text)
    if not username:
        await ui_message(message, 'یوزرنیم فقط با حروف انگلیسی، عدد و _ قابل قبول است.'); return
    await state.update_data(username=username)
    await state.set_state(ResellerCreateUser.volume)
    await ui_message(message, 'حجم کانفیگ چند گیگ باشد؟ فقط عدد وارد کنید.')

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
    await ui_message(message, 'مدت زمان اعتبار کانفیگ چند روز باشد؟ فقط عدد وارد کنید.')

@router.message(ResellerCreateUser.duration)
async def reseller_create_duration(message: Message, state: FSMContext):
    try: days = int(message.text.strip())
    except Exception:
        await ui_message(message, 'فقط عدد روز را وارد کنید. مثلا 30'); return
    if days <= 0:
        await ui_message(message, 'مدت باید بیشتر از صفر باشد.'); return
    data = await state.get_data(); username = data['username']; volume = float(data['volume']); volume_bytes = gb_to_bytes(volume)
    await ui_message(message, '⏳ درخواست ساخت یوزر دریافت شد.\nدر حال اتصال به پنل و ساخت کانفیگ هستم، لطفاً چند لحظه صبر کنید...')
    logger.info('Reseller create user started telegram_id=%s username=%s volume=%s days=%s', message.from_user.id, username, volume, days)
    async with SessionLocal() as session:
        user, reseller = await get_user_reseller(session, message.from_user.id)
        if not reseller or not is_reseller_access_active(reseller):
            await ui_message(message, 'دسترسی نمایندگی فعال نیست.', reply_markup=back_main_inline()); await state.clear(); return
        server, inbounds = await resolve_reseller_build_target(session, reseller)
        if not server or not inbounds:
            await ui_message(message, 'سرور نمایندگی یا Inbound ID برای ساخت یوزر آماده نیست. مدیر باید از بخش مدیریت سرورهای نماینده، یک سرور فعال با Inbound ID معتبر ثبت کند.', reply_markup=reseller_menu()); await state.clear(); return
        if server.server_type != 'xui':
            await ui_message(message, 'ساخت یوزر نمایندگی فقط برای سرورهای X-UI/V2Ray پشتیبانی می‌شود.', reply_markup=reseller_menu()); await state.clear(); return
        # Keep scalar IDs/values before rollback/commit. Do not access ORM objects inside
        # the exception logger, because async SQLAlchemy may try a lazy DB load there and
        # raise MissingGreenlet.
        server_id_value = server.id
        user_id_value = user.id
        reseller_id_value = reseller.id
        created_sub_link = None
        try:
            username = await pick_available_reseller_username(session, server, username)
            await reserve_volume_for_service(session, reseller, volume_bytes)
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
            svc = ClientService(
                user_id=user_id_value,
                server_id=server_id_value,
                reseller_id=reseller_id_value,
                reseller_reserved_bytes=volume_bytes,
                client_username=username,
                xui_email=username,
                xui_uuid=result.get('uuid'),
                inbound_ids=inbounds,
                sub_link=created_sub_link,
                total_bytes=volume_bytes,
                used_bytes=0,
                expires_at=datetime.utcnow()+timedelta(days=days),
                is_active=True,
                is_payg=False,
            )
            session.add(svc)
            await session.commit()
        except asyncio.TimeoutError:
            await session.rollback()
            try:
                if server and getattr(server, 'server_type', None) == 'xui':
                    await XuiService().delete_client(server, username)
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
            except Exception:
                pass
            logger.exception(
                'Reseller create user failed for telegram_id=%s username=%s server_id=%s volume=%s days=%s',
                message.from_user.id, username, server_id_value, volume, days,
            )
            err = str(e).strip() or e.__class__.__name__
            await ui_message(message, f'❌ ساخت یوزر ناموفق بود:\n{err}', reply_markup=reseller_menu()); await state.clear(); return
    await state.clear()
    remaining_after = 0
    async with SessionLocal() as session:
        _, r_after = await get_user_reseller(session, message.from_user.id)
        if r_after:
            remaining_after = bytes_to_gb(max((r_after.total_bytes or 0) - (r_after.reserved_bytes or 0), 0))
    caption = reseller_created_text(username, volume, days, created_sub_link, remaining_after)
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
        await message.answer_photo(FSInputFile(qr_path), caption=caption, parse_mode='HTML', reply_markup=reseller_home_kb())
    else:
        await ui_message(message, caption, parse_mode='HTML', reply_markup=reseller_home_kb())

@router.callback_query(F.data == 'reseller:users')
async def reseller_users(callback: CallbackQuery):
    user, reseller, err = await require_reseller(callback)
    if err:
        await edit_or_answer(callback, err, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('menu:reseller')]])); await callback.answer(); return
    async with SessionLocal() as session:
        reseller = await session.get(ResellerAccount, reseller.id)
        services = (await session.execute(select(ClientService).where(ClientService.reseller_id == reseller.id).order_by(ClientService.id.desc()))).scalars().all()
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
        services = (await session.execute(select(ClientService).where(ClientService.reseller_id == reseller.id).order_by(ClientService.id.desc()))).scalars().all()
    if not services:
        await edit_or_answer(callback, '📭 هنوز هیچ یوزری نساخته‌اید.', reply_markup=reseller_back_kb()); return
    await edit_or_answer(callback, '✅ مصرف یوزرها بروزرسانی شد.\n\n👥 یوزرهای نمایندگی شما:', reply_markup=reseller_users_kb(services))

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
    online, ips = False, []
    if server and server.server_type == 'xui':
        try:
            online_list = await XuiService().get_online_clients(server)
            ips = await XuiService().get_client_ips(server, svc.xui_email)
            online = svc.xui_email in online_list or svc.client_username in online_list or bool(ips)
        except Exception:
            pass
    remain = max((svc.total_bytes or 0)-(svc.used_bytes or 0),0)
    text = f'👤 اطلاعات یوزر\n\nنام: {svc.client_username}\nوضعیت: {"فعال" if svc.is_active else "غیرفعال"}\nآنلاین الان: {"✅ بله" if online else "❌ خیر"}\nIPهای آنلاین:\n{chr(10).join(ips) if ips else "-"}\n\nحجم کل: {bytes_to_gb(svc.total_bytes)} گیگ\nمصرف‌شده: {bytes_to_gb(svc.used_bytes)} گیگ\nباقی‌مانده: {bytes_to_gb(remain)} گیگ\nانقضا: {svc.expires_at.date().isoformat() if svc.expires_at else "-"}\n\nلینک:\n{svc.sub_link or "-"}'
    kb=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='باطل کردن لینک و ارسال لینک جدید 🔁', callback_data=f'reseller:revoke:{sid}')],
        [InlineKeyboardButton(text='حذف کانفیگ 🗑', callback_data=f'reseller:delete:{sid}')],
        [InlineKeyboardButton(text='نمایش راهنمای اتصال 📖', callback_data=f'reseller:help:{sid}')],
        [back_button('reseller:users')],
    ])
    await edit_or_answer(callback, text, reply_markup=kb); await callback.answer()

@router.callback_query(F.data.startswith('reseller:delete:'))
async def reseller_delete_user(callback: CallbackQuery):
    sid = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        svc = await session.get(ClientService, sid)
        user, reseller = await get_user_reseller(session, callback.from_user.id)
        if not svc or not reseller or svc.reseller_id != reseller.id:
            await callback.answer('یوزر پیدا نشد.', show_alert=True); return
        server = await session.get(Server, svc.server_id)
        if server and server.server_type == 'xui':
            try: await XuiService().delete_client(server, svc.xui_email, svc.client_username, svc.xui_uuid, svc.sub_link)
            except Exception: pass
        refund = await refund_unused_volume(session, svc, reseller)
        await session.delete(svc); await session.commit()
    await edit_or_answer(callback, f'✅ یوزر حذف شد.\nحجم برگشتی به سقف نمایندگی: {bytes_to_gb(refund)} گیگ', reply_markup=reseller_menu()); await callback.answer()

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
            new = await XuiService().revoke_and_new_link(server, svc.xui_email)
            svc.xui_uuid = new.get('uuid')
            svc.sub_link = new.get('sub_link')
            await session.commit()
            await session.refresh(svc)
        except Exception as e:
            await session.rollback()
            await edit_or_answer(callback, f'❌ تغییر لینک ناموفق بود:\n{e}', reply_markup=reseller_back_kb(f'reseller:user:{sid}'))
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
    await edit_or_answer(callback, '📖 راهنمای اتصال\n\n1) برنامه Happ را نصب کنید.\n2) لینک ساب‌اسکریپشن را کپی کنید.\n3) داخل برنامه Import from Clipboard را بزنید.\n\nبرای V2rayNG هم گزینه + و Import from Clipboard را بزنید.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('reseller:users')]])); await callback.answer()
