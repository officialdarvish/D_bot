from __future__ import annotations
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy import select, update, delete
from app.core.roles import is_owner
from app.core.security import encrypt_text, decrypt_text
from app.database.session import SessionLocal
from app.database.models import User, Server, ResellerAccount, ResellerPackage, ResellerTopupRequest, ResellerAccessRequest, ClientService, ResellerBuildConfig, PaymentCard
from app.bot.keyboards.common import CB_RESELLERS, back_button, back_admin_inline, main_menu_inline
from app.bot.states.admin_states import AddResellerPackage, EditResellerPackage, ExtendReseller, ResellerServerForm, AdjustResellerVolume
from app.bot.utils import edit_or_answer, ui_message, send_single_message
from app.bot.error_reporting import handle_user_facing_error
from app.database.defaults import get_setting_value, WELCOME_TEXT_DEFAULT
from app.services.reseller_service import gb_to_bytes, bytes_to_gb, reseller_stats, apply_package, approve_reseller_access, reject_reseller_access
from app.services.xui_service import XuiService
from app.services.plan_order import saved_plan_order, sort_by_saved_order
from app.jobs.server_sync import refresh_server_inbounds

router = Router()

def status_only_keyboard(text: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data='noop')]
    ])

async def mark_message_status(callback: CallbackQuery, text: str) -> None:
    try:
        await callback.message.edit_reply_markup(reply_markup=status_only_keyboard(text))
    except Exception:
        pass

def admin(uid: int) -> bool: return is_owner(uid)

def is_reseller_server(server: Server | None) -> bool:
    return bool(server and (server.meta or {}).get('scope') == 'reseller')

def reseller_server_inbounds(server: Server | None) -> list[int]:
    return _clean_inbound_ids((server.meta or {}).get('inbound_ids') if server else [])

def reseller_server_type_text(server: Server) -> str:
    return 'سنایی نمایندگی' if server.server_type == 'xui' else server.server_type

async def active_reseller_servers(session):
    servers = (await session.execute(select(Server).where(Server.is_active == True).order_by(Server.id.desc()))).scalars().all()
    return [s for s in servers if is_reseller_server(s)]

async def all_reseller_servers(session):
    servers = (await session.execute(select(Server).order_by(Server.id.desc()))).scalars().all()
    return [s for s in servers if is_reseller_server(s)]

async def send_reseller_home(bot, chat_id: int, is_admin_user: bool = False) -> None:
    async with SessionLocal() as session:
        user = (await session.execute(select(User).where(User.telegram_id == chat_id))).scalar_one_or_none()
        reseller = None
        if user:
            reseller = (await session.execute(select(ResellerAccount).where(ResellerAccount.user_id == user.id))).scalar_one_or_none()
    await send_single_message(
        bot,
        chat_id,
        await get_setting_value('welcome_text', WELCOME_TEXT_DEFAULT),
        reply_markup=main_menu_inline(is_admin_user, is_reseller=bool(reseller and reseller.is_active)),
    )

def admin_reseller_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='لیست نماینده‌ها 👥', callback_data='resadmin:list'), InlineKeyboardButton(text='درخواست‌های دسترسی نمایندگی 🔐', callback_data='resadmin:access_requests')],
        [InlineKeyboardButton(text='درخواست‌های شارژ حجم 🧾', callback_data='resadmin:requests')],
        [InlineKeyboardButton(text='مدیریت سرورهای نماینده 🖥', callback_data='resadmin:servers'), InlineKeyboardButton(text='مدیریت بسته‌های نمایندگی 📦', callback_data='resadmin:packages')],
        [InlineKeyboardButton(text='اضافه کردن بسته نمایندگی ➕', callback_data='resadmin:add_package')],
        [back_button('back:admin')],
    ])


def reseller_back_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:resellers')]])


def reseller_cancel_menu(target: str = 'admin:resellers') -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[back_button(target)]])

@router.callback_query(F.data == CB_RESELLERS)
@router.callback_query(F.data == 'admin:resellers')
async def resellers_home(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    await state.clear()
    await edit_or_answer(callback, '🤝 تنظیمات نماینده‌ها', reply_markup=admin_reseller_menu()); await callback.answer()

@router.callback_query(F.data == 'resadmin:list')
async def reseller_list(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    async with SessionLocal() as session:
        items = (await session.execute(select(ResellerAccount).order_by(ResellerAccount.id.desc()))).scalars().all()
    if not items:
        await edit_or_answer(callback, 'هنوز نماینده‌ای ثبت نشده است.', reply_markup=admin_reseller_menu()); await callback.answer(); return
    rows=[]
    async with SessionLocal() as session:
        for r in items:
            u = await session.get(User, r.user_id)
            rows.append([InlineKeyboardButton(text=f'#{r.id} | {u.full_name if u else "-"} | {bytes_to_gb(r.total_bytes)}GB', callback_data=f'resadmin:detail:{r.id}')])
    rows.append([back_button('admin:resellers')])
    await edit_or_answer(callback, '👥 لیست نماینده‌ها:', reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)); await callback.answer()

@router.callback_query(F.data.startswith('resadmin:detail:'))
async def reseller_detail(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    rid=int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        r=await session.get(ResellerAccount,rid)
        if not r:
            await callback.answer('نماینده پیدا نشد.', show_alert=True); return
        u=await session.get(User,r.user_id)
        srv=await session.get(Server,r.server_id) if r.server_id else None
        stats=await reseller_stats(session,r)
        await session.commit()
    text=(
        '🤝 اطلاعات نماینده\n\n'
        f'🆔 شناسه: {r.id}\n'
        f'👤 کاربر: {u.full_name if u else "-"} | @{u.username if u and u.username else "-"}\n'
        f'تلگرام ID: {u.telegram_id if u else "-"}\n'
        f'🖥 سرور: {srv.name if srv else "-"}\n'
        f'وضعیت: {"فعال" if r.is_active else "غیرفعال"}\n'
        f'تعداد یوزرها: {stats["total_users"]}\n'
        f'حجم کل: {bytes_to_gb(stats["total_bytes"])} گیگ\n'
        f'حجم رزروشده/ساخته‌شده: {bytes_to_gb(stats["reserved_bytes"])} گیگ\n'
        f'حجم مصرف‌شده واقعی: {bytes_to_gb(stats["used_bytes"])} گیگ\n'
        f'حجم باقی‌مانده: {bytes_to_gb(stats["remaining_bytes"])} گیگ\n'
        f'روز باقی‌مانده: {stats["days_left"]} روز'
    )
    kb=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='تمدید روز نمایندگی ⏳', callback_data=f'resadmin:extend:{r.id}')],
        [InlineKeyboardButton(text='افزایش /کاهش حجم', callback_data=f'resadmin:adjust_volume_id:{u.telegram_id if u else 0}')],
        [InlineKeyboardButton(text='حذف نماینده 🗑', callback_data=f'resadmin:delete:{r.id}')],
        [back_button('resadmin:list')],
    ])
    await edit_or_answer(callback,text,reply_markup=kb); await callback.answer()

@router.callback_query(F.data.startswith('resadmin:extend:'))
async def reseller_extend_start(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    rid=int(callback.data.split(':')[-1])
    await state.update_data(reseller_id=rid)
    await state.set_state(ExtendReseller.days)
    await edit_or_answer(callback,'چند روز به اعتبار نماینده اضافه شود؟ فقط عدد وارد کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(f'resadmin:detail:{rid}')]])); await callback.answer()

@router.message(ExtendReseller.days)
async def reseller_extend_save(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    try: days=int(message.text.strip())
    except Exception:
        await ui_message(message,'فقط عدد روز را وارد کنید.'); return
    data=await state.get_data(); rid=int(data['reseller_id'])
    async with SessionLocal() as session:
        r=await session.get(ResellerAccount,rid)
        if r:
            now=datetime.utcnow(); base=r.expires_at if r.expires_at and r.expires_at>now else now
            r.expires_at=base+timedelta(days=days); r.is_active=True; await session.commit()
    await state.clear(); await ui_message(message,'✅ اعتبار نماینده تمدید شد.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(f'resadmin:detail:{rid}')]]))

@router.callback_query(F.data.startswith('resadmin:delete:'))
async def reseller_delete_ask(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    rid=int(callback.data.split(':')[-1])
    kb=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ بله، دسترسی حذف/غیرفعال شود', callback_data=f'resadmin:delete_confirm:{rid}')],
        [back_button(f'resadmin:detail:{rid}')],
    ])
    await edit_or_answer(callback, '⚠️ مطمئنی می‌خواهی دسترسی این نماینده حذف/غیرفعال شود؟\nسرویس‌های ساخته‌شده دست‌نخورده می‌مانند.', reply_markup=kb); await callback.answer()

@router.callback_query(F.data.startswith('resadmin:delete_confirm:'))
async def reseller_delete(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    rid=int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        r=await session.get(ResellerAccount,rid)
        if r:
            r.is_active=False
            await session.commit()
    await mark_message_status(callback, '✅ رسید تایید شد.')

    await callback.message.answer('✅ درخواست تایید شد و حجم به نماینده اضافه شد.', reply_markup=admin_reseller_menu()); await callback.answer()





def _clean_inbound_ids(value) -> list[int]:
    ids: list[int] = []
    if isinstance(value, str):
        items = [x.strip() for x in value.replace('،', ',').replace(' ', ',').split(',') if x.strip()]
    elif isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        items = [] if value is None else [value]
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



def _inbound_title(row: dict) -> str:
    remark = row.get('remark') or row.get('tag') or row.get('name') or '-'
    proto = row.get('protocol') or row.get('proto') or ''
    iid = row.get('id')
    return f'#{iid} | {remark} {f"({proto})" if proto else ""}'.strip()



def reseller_servers_keyboard(items: list[Server]) -> InlineKeyboardMarkup:
    rows = []
    for s in items:
        rows.append([InlineKeyboardButton(text=s.name, callback_data=f'resadmin:server_detail:{s.id}')])
    rows.append([InlineKeyboardButton(text='➕ افزودن سرور نماینده', callback_data='resadmin:server_add')])
    rows.append([back_button('admin:resellers')])
    return InlineKeyboardMarkup(inline_keyboard=rows)

@router.callback_query(F.data == 'resadmin:servers')
async def reseller_servers_home(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    await state.clear()
    async with SessionLocal() as session:
        items = await all_reseller_servers(session)
    text = '🖥 مدیریت سرورهای نماینده\n\nاین سرورها کاملاً جدا از سرورهای عمومی هستند و فقط برای ساخت یوزر نماینده استفاده می‌شوند.'
    await edit_or_answer(callback, text, reply_markup=reseller_servers_keyboard(items)); await callback.answer()

def _split_panel_url(server: Server | None) -> tuple[str, str]:
    if not server:
        return '', '/'
    meta = server.meta or {}
    base = (meta.get('panel_base_url') or '').strip()
    path = (meta.get('panel_path') or '').strip()
    if base:
        return base.rstrip('/'), path or '/'
    url = (server.panel_url or '').strip().rstrip('/')
    if not url:
        return '', '/'
    try:
        from urllib.parse import urlsplit
        parsed = urlsplit(url)
        base = f'{parsed.scheme}://{parsed.netloc}' if parsed.scheme and parsed.netloc else url
        path = parsed.path or '/'
        return base.rstrip('/'), path
    except Exception:
        return url, '/'


def _compose_panel_url(base_url: str, panel_path: str) -> str:
    base = (base_url or '').strip().rstrip('/')
    path = (panel_path or '').strip()
    if not path or path == '-':
        path = '/'
    if not path.startswith('/'):
        path = '/' + path
    if path != '/' and not path.endswith('/'):
        path += '/'
    return f'{base}{path}'




def _chunked_ids_text(ids: list[int], per_line: int = 4) -> str:
    ids = _clean_inbound_ids(ids or [])
    if not ids:
        return '└ -'
    rows = []
    for i in range(0, len(ids), per_line):
        rows.append('└ ' + ' • '.join(map(str, ids[i:i + per_line])))
    return '\n'.join(rows)

def _keep_or_new(value: str, old: str | None) -> str:
    value = (value or '').strip()
    if value == '-' and old is not None:
        return old
    return value


def _reseller_server_summary(data: dict, action_text: str = 'اضافه کردن') -> str:
    inbound_ids = _clean_inbound_ids(data.get('inbound_ids') or [])
    panel_url = _compose_panel_url(data.get('panel_url', ''), data.get('panel_path', '/'))
    password_preview = '••••••••' if data.get('password') else '-'
    return (
        '🖥 پیش‌نمایش سرور نماینده\n\n'
        '🏷 نام سرور\n'
        f'└ {data.get("name") or "-"}\n\n'
        '🌐 آدرس پنل\n'
        f'└ {data.get("panel_url") or "-"}\n\n'
        '📂 Path پنل\n'
        f'└ {data.get("panel_path") or "/"}\n\n'
        '🔗 آدرس نهایی\n'
        f'└ {panel_url or "-"}\n\n'
        '👤 نام کاربری\n'
        f'└ {data.get("username") or "-"}\n\n'
        '🔐 رمز عبور\n'
        f'└ {password_preview}\n\n'
        '📡 لینک ساب\n'
        f'└ {data.get("subscription_url") or "-"}\n\n'
        '📥 Inbounds\n'
        f'{_chunked_ids_text(inbound_ids)}\n\n'
        '━━━━━━━━━━━━━━━\n\n'
        'لطفاً اطلاعات را بررسی کنید.\n'
        f'اگر درست است روی «✅ {action_text}» بزنید.\n'
        'اگر نیاز به اصلاح دارد روی «❌ اصلاح اطلاعات» بزنید.'
    )


def _reseller_server_confirm_kb(mode: str) -> InlineKeyboardMarkup:
    label = 'تغییر' if mode == 'edit' else 'اضافه کردن'
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ تایید و ثبت', callback_data='resadmin:server_confirm')],
        [InlineKeyboardButton(text='❌ عدم تایید و اصلاح', callback_data='resadmin:server_restart')],
        [back_button('resadmin:servers')],
    ])


async def _fetch_reseller_panel_inbounds(data: dict) -> tuple[bool, list[int], str]:
    panel_url_full = _compose_panel_url(data.get('panel_url', ''), data.get('panel_path', '/'))
    server = Server(
        name=data.get('name') or 'reseller-preview',
        server_type='xui',
        panel_url=panel_url_full,
        subscription_url=data.get('subscription_url'),
        username=data.get('username') or '',
        password_encrypted=encrypt_text(data.get('password') or ''),
        is_active=True,
        meta={'scope': 'reseller', 'panel_base_url': data.get('panel_url'), 'panel_path': data.get('panel_path')},
    )
    try:
        ok, rows = await XuiService().test_server(server)
    except Exception as exc:
        return False, [], str(exc)
    if not ok:
        return False, [], 'Login/List inbounds failed'
    ids = _clean_inbound_ids([r.get('id') for r in (rows or []) if isinstance(r, dict)])
    if not ids:
        return False, [], 'هیچ Inbound فعالی از پنل دریافت نشد.'
    return True, ids, ''


async def _start_reseller_server_questions(callback: CallbackQuery, state: FSMContext, mode: str = 'add', server: Server | None = None):
    base, path = _split_panel_url(server)
    old_password = decrypt_text(server.password_encrypted) if server else None
    await state.clear()
    await state.update_data(
        mode=mode,
        edit_server_id=server.id if server else None,
        old_name=server.name if server else None,
        old_panel_url=base or None,
        old_panel_path=path or '/',
        old_subscription_url=server.subscription_url if server else None,
        old_username=server.username if server else None,
        old_password=old_password,
        old_inbound_ids=reseller_server_inbounds(server) if server else [],
    )
    await state.set_state(ResellerServerForm.name)
    await edit_or_answer(callback, 'نام سرور نماینده را وارد کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('resadmin:servers')]]))
    await callback.answer()


@router.callback_query(F.data == 'resadmin:server_add')
async def reseller_server_add(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    await _start_reseller_server_questions(callback, state, 'add')

@router.message(ResellerServerForm.name)
async def reseller_server_name(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    data = await state.get_data()
    name = _keep_or_new(message.text or '', data.get('old_name'))
    if not name:
        await ui_message(message, 'نام سرور نمی‌تواند خالی باشد.'); return
    await state.update_data(name=name); await state.set_state(ResellerServerForm.panel_url)
    await ui_message(message, 'آدرس اصلی پنل را بدون path وارد کنید:\nمثال: https://domain.com یا https://domain.com:2053', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('resadmin:servers')]]))

@router.message(ResellerServerForm.panel_url)
async def reseller_server_url(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    data = await state.get_data()
    panel_url = _keep_or_new(message.text or '', data.get('old_panel_url'))
    if not panel_url.startswith(('http://', 'https://')):
        await ui_message(message, '❌ آدرس پنل باید با http:// یا https:// شروع شود. دوباره وارد کنید:'); return
    await state.update_data(panel_url=panel_url.rstrip('/')); await state.set_state(ResellerServerForm.panel_path)
    await ui_message(message, 'Path پنل را وارد کنید:\nمثال: /secretpath/ یا /\n\nاگر پنل path ندارد / بفرستید.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('resadmin:servers')]]))

@router.message(ResellerServerForm.panel_path)
async def reseller_server_path(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    data = await state.get_data()
    panel_path = _keep_or_new(message.text or '', data.get('old_panel_path') or '/')
    if not panel_path:
        panel_path = '/'
    if not panel_path.startswith('/'):
        panel_path = '/' + panel_path
    if panel_path != '/' and not panel_path.endswith('/'):
        panel_path += '/'
    await state.update_data(panel_path=panel_path); await state.set_state(ResellerServerForm.subscription_url)
    await ui_message(message, 'لینک ساب‌اسکریپشن را وارد کنید. مثال:\nhttps://sub.domain.com/subb/', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('resadmin:servers')]]))

@router.message(ResellerServerForm.subscription_url)
async def reseller_server_sub(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    data = await state.get_data()
    sub = _keep_or_new(message.text or '', data.get('old_subscription_url'))
    await state.update_data(subscription_url=sub); await state.set_state(ResellerServerForm.username)
    await ui_message(message, 'نام کاربری پنل را وارد کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('resadmin:servers')]]))

@router.message(ResellerServerForm.username)
async def reseller_server_username(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    data = await state.get_data()
    username = _keep_or_new(message.text or '', data.get('old_username'))
    if not username:
        await ui_message(message, 'نام کاربری نمی‌تواند خالی باشد. دوباره وارد کنید:'); return
    await state.update_data(username=username); await state.set_state(ResellerServerForm.password)
    await ui_message(message, 'رمز عبور پنل را وارد کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('resadmin:servers')]]))

@router.message(ResellerServerForm.password)
async def reseller_server_password(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    data = await state.get_data()
    password = _keep_or_new(message.text or '', data.get('old_password'))
    if not password:
        await ui_message(message, 'رمز عبور نمی‌تواند خالی باشد. دوباره وارد کنید:'); return
    await state.update_data(password=password)
    data = await state.get_data()

    ok, inbound_ids, err = await _fetch_reseller_panel_inbounds(data)
    if not ok:
        await state.update_data(auto_fetch_error=err or 'Login/List inbounds failed')
        await state.set_state(ResellerServerForm.inbound_ids)
        await handle_user_facing_error(
            message,
            Exception(err or 'Login/List inbounds failed'),
            context='Admin reseller server inbound fetch failed',
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='❌ اصلاح اطلاعات', callback_data='resadmin:server_restart')], [back_button('resadmin:servers')]])
        )
        return

    await state.update_data(inbound_ids=inbound_ids, manual_inbounds='0')
    data = await state.get_data()
    await state.set_state(ResellerServerForm.confirm)
    action_text = 'تغییر' if data.get('mode') == 'edit' else 'اضافه کردن'
    await ui_message(message, _reseller_server_summary(data, action_text), reply_markup=_reseller_server_confirm_kb(data.get('mode') or 'add'))

@router.message(ResellerServerForm.inbound_ids)
async def reseller_server_preview(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    inbound_ids = _clean_inbound_ids(message.text or '')
    if not inbound_ids:
        await ui_message(message, '❌ حداقل یک Inbound ID معتبر وارد کن. مثال: 1,2,3', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('resadmin:servers')]]))
        return
    await state.update_data(inbound_ids=inbound_ids, manual_inbounds='1')
    data = await state.get_data()
    await state.set_state(ResellerServerForm.confirm)
    action_text = 'تغییر' if data.get('mode') == 'edit' else 'اضافه کردن'
    await ui_message(message, _reseller_server_summary(data, action_text) + '\n\n⚠️ این Inboundها دستی ثبت شده‌اند؛ در مرحله تایید، تست زنده پنل رد نمی‌شود.', reply_markup=_reseller_server_confirm_kb(data.get('mode') or 'add'))

@router.callback_query(F.data == 'resadmin:server_restart')
async def reseller_server_restart(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    data = await state.get_data()
    sid = data.get('edit_server_id')
    if data.get('mode') == 'edit' and sid:
        async with SessionLocal() as session:
            server = await session.get(Server, int(sid))
        await _start_reseller_server_questions(callback, state, 'edit', server)
        return
    await _start_reseller_server_questions(callback, state, 'add')

@router.callback_query(F.data == 'resadmin:server_confirm')
async def reseller_server_confirm(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    data = await state.get_data()
    inbound_ids = _clean_inbound_ids(data.get('inbound_ids') or [])
    panel_url_full = _compose_panel_url(data.get('panel_url', ''), data.get('panel_path', '/'))
    server = Server(
        name=data['name'], server_type='xui', panel_url=panel_url_full, subscription_url=data.get('subscription_url'),
        username=data['username'], password_encrypted=encrypt_text(data['password']), is_active=True,
        meta={'scope': 'reseller', 'inbound_ids': inbound_ids, 'panel_base_url': data.get('panel_url'), 'panel_path': data.get('panel_path')},
    )
    if str(data.get('manual_inbounds') or '0') != '1':
        ok=False; err=''; rows=[]
        try:
            ok, rows = await XuiService().test_server(server)
        except Exception as exc:
            err=str(exc)
        if not ok:
            await handle_user_facing_error(callback, Exception(err or 'Login/List inbounds failed'), context='Admin reseller server confirm test failed', reply_markup=_reseller_server_confirm_kb(data.get('mode') or 'add'))
            await callback.answer(); return
        live_ids = _clean_inbound_ids([r.get('id') for r in (rows or []) if isinstance(r, dict)])
        if not live_ids:
            await edit_or_answer(callback, '❌ اتصال به پنل موفق بود، اما هیچ Inboundی از پنل دریافت نشد.', reply_markup=_reseller_server_confirm_kb(data.get('mode') or 'add'))
            await callback.answer(); return
        inbound_ids = live_ids
    elif not inbound_ids:
        await edit_or_answer(callback, '❌ هیچ Inbound ID معتبری برای ثبت وجود ندارد.', reply_markup=_reseller_server_confirm_kb(data.get('mode') or 'add'))
        await callback.answer(); return
    server.meta = {'scope': 'reseller', 'inbound_ids': inbound_ids, 'panel_base_url': data.get('panel_url'), 'panel_path': data.get('panel_path')}
    mode = data.get('mode') or 'add'
    async with SessionLocal() as session:
        if mode == 'edit' and data.get('edit_server_id'):
            target = await session.get(Server, int(data['edit_server_id']))
            if not target or not is_reseller_server(target):
                await callback.answer('سرور نماینده پیدا نشد.', show_alert=True); return
            target.name = data['name']
            target.panel_url = panel_url_full
            target.subscription_url = data.get('subscription_url')
            target.username = data['username']
            target.password_encrypted = encrypt_text(data['password'])
            target.meta = {'scope': 'reseller', 'inbound_ids': inbound_ids, 'panel_base_url': data.get('panel_url'), 'panel_path': data.get('panel_path')}
            server_id = target.id
            success_text = '✅ اطلاعات پنل نماینده با موفقیت تغییر کرد.'
        else:
            session.add(server)
            await session.flush()
            server_id = server.id
            success_text = '✅ پنل نماینده با موفقیت اضافه شد.'
        await session.commit()
        items = await all_reseller_servers(session)
    await state.clear()
    await edit_or_answer(callback, f'{success_text}\n\n🖥 سرور: {data["name"]}\n🆔 ID: {server_id}\n🔢 اینباندها: {", ".join(map(str, inbound_ids))}\n\n📋 لیست سرورهای نماینده بروزرسانی شد:', reply_markup=reseller_servers_keyboard(items))
    await callback.answer()

@router.callback_query(F.data.startswith('resadmin:server_detail:'))
async def reseller_server_detail(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    sid=int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        s=await session.get(Server,sid)
    if not is_reseller_server(s):
        await callback.answer('سرور نماینده پیدا نشد.', show_alert=True); return
    ids=reseller_server_inbounds(s)
    base, path = _split_panel_url(s)
    kb=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🔄 بروزرسانی سرور', callback_data=f'resadmin:server_refresh:{s.id}')],
        [InlineKeyboardButton(text='✏️ تغییر اطلاعات لاگین', callback_data=f'resadmin:server_edit:{s.id}')],
        [InlineKeyboardButton(text='🔄 تغییر وضعیت', callback_data=f'resadmin:server_toggle:{s.id}')],
        [InlineKeyboardButton(text='🗑 حذف سرور', callback_data=f'resadmin:server_delete:{s.id}')],
        [back_button('resadmin:servers')],
    ])
    status_text = '✅ فعال' if s.is_active else '❌ غیرفعال'
    detail_text = (
        '🖥 اطلاعات سرور نماینده\n\n'
        '🏷 نام سرور\n'
        f'└ {s.name}\n\n'
        '🌐 آدرس پنل\n'
        f'└ {base or s.panel_url}\n\n'
        '📂 Path پنل\n'
        f'└ {path}\n\n'
        '🔗 آدرس نهایی\n'
        f'└ {s.panel_url}\n\n'
        '👤 نام کاربری\n'
        f'└ {s.username}\n\n'
        '📡 لینک ساب\n'
        f'└ {s.subscription_url or "-"}\n\n'
        '⚙️ وضعیت\n'
        f'└ {status_text}\n\n'
        '📥 Inbounds\n'
        f'{_chunked_ids_text(ids)}'
    )
    await edit_or_answer(callback, detail_text, reply_markup=kb); await callback.answer()


@router.callback_query(F.data.startswith('resadmin:server_refresh:'))
async def reseller_server_refresh(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    sid = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        s = await session.get(Server, sid)
        if not is_reseller_server(s):
            await callback.answer('سرور نماینده پیدا نشد.', show_alert=True); return
        ok, old_ids, new_ids, err = await refresh_server_inbounds(session, s, force_plan_update=True)
        if ok:
            await session.commit()
        items = await all_reseller_servers(session)
    if not ok:
        await handle_user_facing_error(callback, Exception(err or 'Refresh reseller server inbounds failed'), context='Admin reseller server refresh failed', reply_markup=reseller_servers_keyboard(items))
        return
    changed = 'تغییر کرد' if old_ids != new_ids else 'تغییری نداشت'
    await edit_or_answer(callback, f'✅ سرور نماینده بروزرسانی شد.\n\nقبلی: {", ".join(map(str, old_ids)) or "-"}\nجدید: {", ".join(map(str, new_ids)) or "-"}\nوضعیت: {changed}', reply_markup=reseller_servers_keyboard(items))
    await callback.answer('بروزرسانی شد.')

@router.callback_query(F.data.startswith('resadmin:server_edit:'))
async def reseller_server_edit(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    sid=int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        s=await session.get(Server,sid)
    if not is_reseller_server(s):
        await callback.answer('سرور نماینده پیدا نشد.', show_alert=True); return
    await _start_reseller_server_questions(callback, state, 'edit', s)

@router.callback_query(F.data.startswith('resadmin:server_toggle:'))
async def reseller_server_toggle(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    sid=int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        s=await session.get(Server,sid)
        if s and is_reseller_server(s):
            s.is_active = not s.is_active
            await session.commit()
    async with SessionLocal() as session:
        items=await all_reseller_servers(session)
    await edit_or_answer(callback, '✅ وضعیت سرور بروزرسانی شد.', reply_markup=reseller_servers_keyboard(items)); await callback.answer()

@router.callback_query(F.data.startswith('resadmin:server_delete:'))
async def reseller_server_delete_ask(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    sid=int(callback.data.split(':')[-1])
    kb=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ بله، سرور نماینده حذف شود', callback_data=f'resadmin:server_delete_confirm:{sid}')],
        [back_button(f'resadmin:server_detail:{sid}')],
    ])
    await edit_or_answer(callback, '⚠️ مطمئنی می‌خواهی این سرور نماینده حذف/غیرفعال شود؟', reply_markup=kb); await callback.answer()

@router.callback_query(F.data.startswith('resadmin:server_delete_confirm:'))
async def reseller_server_delete(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    sid=int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        s=await session.get(Server,sid)
        if not s or not is_reseller_server(s):
            await callback.answer('سرور پیدا نشد.', show_alert=True); return
        used=(await session.execute(select(ClientService.id).where(ClientService.server_id==sid).limit(1))).scalar_one_or_none()
        await session.execute(update(ResellerAccount).where(ResellerAccount.server_id == sid).values(server_id=None))
        await session.execute(update(ResellerPackage).where(ResellerPackage.server_id == sid).values(server_id=None))
        await session.execute(update(ResellerBuildConfig).where(ResellerBuildConfig.server_id == sid).values(server_id=None))
        await session.execute(update(PaymentCard).where(PaymentCard.server_id == sid).values(server_id=None))
        if used:
            meta = dict(s.meta or {})
            meta['scope'] = 'reseller_deleted'
            meta['deleted_from_bot'] = True
            s.meta = meta
            s.is_active=False
            message_text = '✅ سرور از لیست نماینده‌ها حذف شد. چون سرویس فعال روی آن وجود داشت، به‌صورت آرشیو نگهداری شد.'
        else:
            await session.delete(s)
            message_text = '✅ سرور نماینده به‌صورت کامل حذف شد.'
        await session.commit()
        items=await all_reseller_servers(session)
    await edit_or_answer(callback, message_text, reply_markup=reseller_servers_keyboard(items)); await callback.answer()

@router.callback_query(F.data == 'resadmin:adjust_volume')
async def reseller_adjust_volume_start(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    await state.clear(); await state.set_state(AdjustResellerVolume.telegram_id)
    await edit_or_answer(callback, 'آیدی عددی تلگرام نماینده را وارد کنید:', reply_markup=reseller_cancel_menu()); await callback.answer()

@router.callback_query(F.data.startswith('resadmin:adjust_volume_id:'))
async def reseller_adjust_volume_from_detail(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    telegram_id=int(callback.data.split(':')[-1])
    await state.clear(); await state.update_data(telegram_id=telegram_id); await state.set_state(AdjustResellerVolume.amount)
    await edit_or_answer(callback, 'مقدار حجم را به گیگ وارد کنید.\nبرای کاهش، عدد منفی بزنید. مثال: 50 یا -20', reply_markup=reseller_cancel_menu()); await callback.answer()

@router.message(AdjustResellerVolume.telegram_id)
async def reseller_adjust_volume_telegram(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    try:
        telegram_id=int((message.text or '').strip())
    except Exception:
        await ui_message(message, 'فقط آیدی عددی تلگرام را وارد کنید.'); return
    await state.update_data(telegram_id=telegram_id); await state.set_state(AdjustResellerVolume.amount)
    await ui_message(message, 'مقدار حجم را به گیگ وارد کنید.\nبرای کاهش، عدد منفی بزنید. مثال: 50 یا -20', reply_markup=reseller_cancel_menu())

@router.message(AdjustResellerVolume.amount)
async def reseller_adjust_volume_save(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    try:
        amount=float((message.text or '').replace(',', '.').strip())
    except Exception:
        await ui_message(message, 'فقط عدد وارد کنید. مثال: 50 یا -20'); return
    data=await state.get_data(); telegram_id=int(data.get('telegram_id') or 0)
    delta=gb_to_bytes(amount)
    async with SessionLocal() as session:
        u=(await session.execute(select(User).where(User.telegram_id==telegram_id))).scalar_one_or_none()
        if not u:
            await ui_message(message, '❌ کاربر با این آیدی عددی پیدا نشد.', reply_markup=admin_reseller_menu()); await state.clear(); return
        r=(await session.execute(select(ResellerAccount).where(ResellerAccount.user_id==u.id))).scalar_one_or_none()
        if not r:
            r=ResellerAccount(user_id=u.id, server_id=None, total_bytes=0, used_bytes=0, reserved_bytes=0, is_active=True)
            session.add(r); await session.flush()
        new_total=(r.total_bytes or 0)+delta
        min_total=r.reserved_bytes or 0
        if new_total < min_total:
            await ui_message(message, f'❌ حجم کل نمی‌تواند کمتر از حجم رزروشده باشد.\nحجم رزروشده فعلی: {bytes_to_gb(min_total)} گیگ', reply_markup=admin_reseller_menu()); await state.clear(); return
        r.total_bytes=new_total; r.is_active=True
        await session.commit()
        total=bytes_to_gb(r.total_bytes); remaining=bytes_to_gb(max((r.total_bytes or 0)-(r.reserved_bytes or 0),0))
    await state.clear()
    await ui_message(message, f'✅ حجم نماینده بروزرسانی شد.\n\nآیدی عددی: {telegram_id}\nتغییر: {amount:g} گیگ\nحجم کل: {total} گیگ\nحجم باقی‌مانده: {remaining} گیگ', reply_markup=admin_reseller_menu())

@router.callback_query(F.data == 'resadmin:access_requests')
async def reseller_access_requests(callback: CallbackQuery):
    if not admin(callback.from_user.id):
        await callback.answer('دسترسی ندارید.', show_alert=True)
        return
    async with SessionLocal() as session:
        reqs = (await session.execute(
            select(ResellerAccessRequest)
            .where(ResellerAccessRequest.status == 'pending')
            .order_by(ResellerAccessRequest.id.desc())
        )).scalars().all()
        rows = []
        for req in reqs:
            u = await session.get(User, req.user_id)
            rows.append([
                InlineKeyboardButton(
                    text=f'#{req.id} | {u.full_name if u else "-"} | {u.telegram_id if u else "-"}',
                    callback_data=f'resadmin:access_detail:{req.id}'
                )
            ])
    if not rows:
        await edit_or_answer(callback, 'درخواست دسترسی نمایندگی در انتظار تایید وجود ندارد.', reply_markup=reseller_back_menu())
        await callback.answer()
        return
    rows.append([back_button('admin:resellers')])
    await edit_or_answer(callback, '🔐 درخواست‌های دسترسی نمایندگی:', reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()

@router.callback_query(F.data.startswith('resadmin:access_detail:'))
async def reseller_access_detail(callback: CallbackQuery):
    if not admin(callback.from_user.id):
        await callback.answer('دسترسی ندارید.', show_alert=True)
        return
    req_id = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        req = await session.get(ResellerAccessRequest, req_id)
        u = await session.get(User, req.user_id) if req else None
    if not req:
        await callback.answer('درخواست پیدا نشد.', show_alert=True)
        return
    text = (
        f'🔐 درخواست دسترسی نمایندگی #{req.id}\n\n'
        f'👤 کاربر: {u.full_name if u else "-"}\n'
        f'Username: @{u.username if u and u.username else "-"}\n'
        f'Telegram ID: {u.telegram_id if u else "-"}\n'
        f'وضعیت: {req.status}\n\n'
        'با تایید، قفل صفحه نمایندگی برای این کاربر باز می‌شود.'
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ تایید و باز کردن قفل', callback_data=f'resadmin:access_approve:{req.id}')],
        [InlineKeyboardButton(text='❌ رد درخواست', callback_data=f'resadmin:access_reject:{req.id}')],
        [back_button('resadmin:access_requests')],
    ])
    await edit_or_answer(callback, text, reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data.startswith('resadmin:access_approve:'))
async def reseller_access_approve(callback: CallbackQuery):
    if not admin(callback.from_user.id):
        await callback.answer('دسترسی ندارید.', show_alert=True)
        return
    req_id = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        req = await session.get(ResellerAccessRequest, req_id)
        if not req:
            await callback.answer('درخواست پیدا نشد.', show_alert=True)
            return
        if req.status != 'pending':
            await callback.answer('این درخواست قبلاً بررسی شده است.', show_alert=True)
            return
        reseller = await approve_reseller_access(session, req, callback.from_user.id)
        u = await session.get(User, req.user_id)
        await session.commit()
    try:
        await callback.message.bot.send_message(
            u.telegram_id,
            '✅ درخواست نمایندگی شما تایید شد.\n\nمنوی شما بروزرسانی شد؛ از این به بعد به‌جای «درخواست نمایندگی»، دکمه «منو نمایندگی» را می‌بینید.'
        )
        await callback.message.bot.send_message(
            u.telegram_id,
            await get_setting_value('welcome_text', WELCOME_TEXT_DEFAULT),
            reply_markup=main_menu_inline(False, True, True),
        )
    except Exception:
        pass
    await mark_message_status(callback, '✅ تایید شد')
    await callback.message.answer('✅ دسترسی نمایندگی تایید شد و قفل صفحه برای کاربر باز شد.', reply_markup=admin_reseller_menu())
    await callback.message.answer('🏠 صفحه اصلی', reply_markup=main_menu_inline(True))
    await callback.answer('تایید شد.', show_alert=True)

@router.callback_query(F.data.startswith('resadmin:access_reject:'))
async def reseller_access_reject(callback: CallbackQuery):
    if not admin(callback.from_user.id):
        await callback.answer('دسترسی ندارید.', show_alert=True)
        return
    req_id = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        req = await session.get(ResellerAccessRequest, req_id)
        if not req:
            await callback.answer('درخواست پیدا نشد.', show_alert=True)
            return
        await reject_reseller_access(session, req, callback.from_user.id)
        u = await session.get(User, req.user_id)
        await session.commit()
    try:
        await callback.message.bot.send_message(u.telegram_id, '❌ درخواست نمایندگی شما رد شد. برای پیگیری به پشتیبانی پیام بدهید.')
        await callback.message.bot.send_message(
            u.telegram_id,
            await get_setting_value('welcome_text', WELCOME_TEXT_DEFAULT),
            reply_markup=main_menu_inline(False, True, False),
        )
    except Exception:
        pass
    await mark_message_status(callback, '❌ رد شد')
    await callback.message.answer('❌ درخواست نمایندگی رد شد.', reply_markup=admin_reseller_menu())
    await callback.message.answer('🏠 صفحه اصلی', reply_markup=main_menu_inline(True))
    await callback.answer('رد شد.', show_alert=True)

@router.callback_query(F.data == 'resadmin:requests')
async def reseller_requests(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    async with SessionLocal() as session:
        reqs=(await session.execute(select(ResellerTopupRequest).where(ResellerTopupRequest.status=='pending').order_by(ResellerTopupRequest.id.desc()))).scalars().all()
    if not reqs:
        await edit_or_answer(callback,'درخواست شارژ حجم در انتظار تایید وجود ندارد.', reply_markup=reseller_back_menu()); await callback.answer(); return
    rows=[]
    async with SessionLocal() as session:
        for r in reqs:
            u=await session.get(User,r.user_id); p=await session.get(ResellerPackage,r.package_id)
            rows.append([InlineKeyboardButton(text=f'#{r.id} | {u.full_name if u else "-"} | {p.title if p else "-"}', callback_data=f'resadmin:req:{r.id}')])
    rows.append([back_button('admin:resellers')])
    await edit_or_answer(callback,'🧾 درخواست‌های نمایندگی:', reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)); await callback.answer()

@router.callback_query(F.data.startswith('resadmin:req:'))
async def reseller_request_detail(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    req_id=int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        r=await session.get(ResellerTopupRequest, req_id); u=await session.get(User,r.user_id) if r else None; p=await session.get(ResellerPackage,r.package_id) if r else None
    if not r:
        await callback.answer('درخواست پیدا نشد.', show_alert=True); return
    text=f'🧾 درخواست شارژ نمایندگی #{r.id}\n\nکاربر: {u.full_name if u else "-"} | {u.telegram_id if u else "-"}\nپلن: {p.title if p else "-"}\nحجم: {bytes_to_gb(r.volume_bytes)} گیگ\nمبلغ: {r.amount_irt:,} تومان\nوضعیت: {r.status}'
    kb=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ تایید و افزودن حجم', callback_data=f'resadmin:req_approve:{r.id}')],
        [InlineKeyboardButton(text='❌ رد درخواست', callback_data=f'resadmin:req_reject:{r.id}')],
        [back_button('resadmin:requests')],
    ])
    await edit_or_answer(callback,text,reply_markup=kb); await callback.answer()

@router.callback_query(F.data.startswith('resadmin:req_approve:'))
async def reseller_request_approve(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    req_id=int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        r=await session.get(ResellerTopupRequest, req_id)
        if not r or r.status!='pending': await callback.answer('درخواست قابل تایید نیست.', show_alert=True); return
        reseller=await apply_package(session,r); u=await session.get(User,r.user_id); await session.commit()
    await mark_message_status(callback, '✅ تایید شد')
    try:
        await callback.message.bot.send_message(u.telegram_id, f'✅ رسید تایید شد.\nحجم اضافه‌شده به حساب نمایندگی شما: {bytes_to_gb(r.volume_bytes)} گیگ')
        await send_reseller_home(callback.message.bot, u.telegram_id, False)
    except Exception:
        pass
    await edit_or_answer(callback, '✅ رسید تایید شد.\nحجم به سقف نماینده اضافه شد.')
    await send_reseller_home(callback.message.bot, callback.from_user.id, True)
    await callback.answer('رسید تایید شد.', show_alert=False)

@router.callback_query(F.data.startswith('resadmin:req_reject:'))
async def reseller_request_reject(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    req_id=int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        r=await session.get(ResellerTopupRequest, req_id)
        if r: r.status='rejected'; u=await session.get(User,r.user_id); await session.commit()
    await mark_message_status(callback, '❌ رد شد')
    try: await callback.message.bot.send_message(u.telegram_id, '❌ درخواست شارژ نمایندگی شما رد شد. لطفاً با پشتیبانی تماس بگیرید.')
    except Exception: pass
    await edit_or_answer(callback,'درخواست رد شد.', reply_markup=admin_reseller_menu()); await callback.answer()

@router.callback_query(F.data == 'resadmin:add_package')
async def add_package_start(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    await state.clear()
    async with SessionLocal() as session:
        servers=await active_reseller_servers(session)
    if not servers:
        await edit_or_answer(callback,'هیچ سرور نمایندگی ثبت نشده است. اول از مدیریت سرورهای نماینده یک سرور اضافه کن.', reply_markup=reseller_back_menu()); await state.clear(); await callback.answer(); return
    await state.set_state(AddResellerPackage.server_id)
    await edit_or_answer(
        callback,
        'سرور نمایندگی مخصوص این بسته را انتخاب کنید:',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=s.name, callback_data=f'resadmin:pkg_server:{s.id}')] for s in servers]+[[back_button('admin:resellers')]])
    )
    await callback.answer()

@router.callback_query(F.data.startswith('resadmin:pkg_server:'))
async def add_package_server(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    await state.update_data(server_id=int(callback.data.split(':')[-1]))
    await state.set_state(AddResellerPackage.volume)
    await edit_or_answer(callback,'حجم بسته چند گیگ باشد؟ فقط عدد وارد کنید:', reply_markup=reseller_cancel_menu()); await callback.answer()

@router.message(AddResellerPackage.volume)
async def add_package_volume(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    try: vol=int(float(message.text.replace(',','.').strip()))
    except Exception:
        await ui_message(message,'فقط عدد حجم را وارد کنید.'); return
    await state.update_data(volume=vol); await state.set_state(AddResellerPackage.price)
    await ui_message(message,'قیمت بسته را به تومان وارد کنید:', reply_markup=reseller_cancel_menu())

@router.message(AddResellerPackage.price)
async def add_package_price(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    try: price=int(message.text.replace(',','').strip())
    except Exception:
        await ui_message(message,'فقط عدد قیمت را وارد کنید.'); return
    await state.update_data(price=price); await state.set_state(AddResellerPackage.validity_days)
    await ui_message(message,'مدت زمان اعتبار نماینده چند روز باشد؟ مثلا 365', reply_markup=reseller_cancel_menu())

@router.message(AddResellerPackage.validity_days)
async def add_package_validity(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    try: days=int(message.text.strip())
    except Exception:
        await ui_message(message,'فقط عدد روز را وارد کنید.'); return
    data=await state.get_data()
    async with SessionLocal() as session:
        title = f'بسته نمایندگی {int(data["volume"])} گیگ'
        session.add(ResellerPackage(title=title, server_id=int(data['server_id']), volume_gb=int(data['volume']), price_irt=int(data['price']), reseller_validity_days=days, is_active=True))
        await session.commit()
    await state.clear(); await ui_message(message,'✅ بسته نمایندگی اضافه شد و در بخش شارژ حجم قابل خرید است.', reply_markup=admin_reseller_menu())


def _money(v: int | None) -> str:
    try:
        return f'{int(v or 0):,} تومان'
    except Exception:
        return f'{v} تومان'


def _pkg_visibility_text(pkg: ResellerPackage) -> str:
    return '🟢 فعال / قابل خرید' if pkg.is_active else '🔴 غیرفعال / مخفی'


async def reseller_package_detail_text(package_id: int) -> str:
    async with SessionLocal() as session:
        pkg = await session.get(ResellerPackage, package_id)
        server = await session.get(Server, pkg.server_id) if pkg else None
    if not pkg:
        return '❌ بسته نمایندگی پیدا نشد.'
    return (
        '📦 مدیریت بسته نمایندگی\n'
        '━━━━━━━━━━━━━━━━━━\n\n'
        f'🆔 شناسه: {pkg.id}\n'
        f'📦 نام بسته: {pkg.title}\n'
        f'👁 وضعیت: {_pkg_visibility_text(pkg)}\n'
        f'🖥 سرور: {server.name if server else "نامشخص"}\n\n'
        '━━━━━━━━━━━━━━━━━━\n'
        f'💾 حجم شارژ: {pkg.volume_gb} گیگ\n'
        f'⏳ اعتبار نمایندگی: {pkg.reseller_validity_days} روز\n'
        f'💰 قیمت: {_money(pkg.price_irt)}\n'
    )


def reseller_package_detail_keyboard(package_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✏️ تغییر نام بسته', callback_data=f'resadmin:pkg_edit:title:{package_id}'), InlineKeyboardButton(text='💰 تغییر قیمت', callback_data=f'resadmin:pkg_edit:price:{package_id}')],
        [InlineKeyboardButton(text='💾 تغییر حجم', callback_data=f'resadmin:pkg_edit:volume:{package_id}'), InlineKeyboardButton(text='⏳ تغییر اعتبار', callback_data=f'resadmin:pkg_edit:validity:{package_id}')],
        [InlineKeyboardButton(text='🖥 تغییر سرور', callback_data=f'resadmin:pkg_edit:server:{package_id}')],
        [InlineKeyboardButton(text='👁 فعال / غیرفعال', callback_data=f'resadmin:pkg_toggle:{package_id}')],
        [InlineKeyboardButton(text='🗑 حذف بسته', callback_data=f'resadmin:pkg_delete:{package_id}')],
        [back_button('resadmin:packages')],
    ])


@router.callback_query(F.data == 'resadmin:packages')
async def packages_list(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    async with SessionLocal() as session:
        packs=(await session.execute(select(ResellerPackage))).scalars().all()
        packs=sort_by_saved_order(packs, await saved_plan_order(session, 'reseller'))
    if not packs:
        await edit_or_answer(callback,'📦 مدیریت بسته‌های نمایندگی\n\nهنوز بسته‌ای ثبت نشده است.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='➕ اضافه کردن بسته نمایندگی', callback_data='resadmin:add_package')],
            [back_button('admin:resellers')],
        ])); await callback.answer(); return
    rows=[]
    for p in packs:
        status='🟢' if p.is_active else '🔴'
        vol_text = f'{int(p.volume_gb) if float(p.volume_gb).is_integer() else p.volume_gb} گیگ'
        rows.append([InlineKeyboardButton(text=f'{status} #{p.id} | {vol_text} | {_money(p.price_irt)}', callback_data=f'resadmin:pkg_detail:{p.id}')])
    rows.append([InlineKeyboardButton(text='➕ اضافه کردن بسته نمایندگی', callback_data='resadmin:add_package')])
    rows.append([back_button('admin:resellers')])
    await edit_or_answer(callback,'📦 مدیریت بسته‌های نمایندگی\n\nبرای مشاهده، ویرایش، حذف یا تغییر وضعیت روی بسته بزنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)); await callback.answer()


@router.callback_query(F.data.startswith('resadmin:pkg_detail:'))
async def package_detail(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    pid=int(callback.data.split(':')[-1])
    await edit_or_answer(callback, await reseller_package_detail_text(pid), reply_markup=reseller_package_detail_keyboard(pid)); await callback.answer()


@router.callback_query(F.data.startswith('resadmin:pkg_toggle:'))
async def package_toggle(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    pid=int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        p=await session.get(ResellerPackage,pid)
        if p: p.is_active=not p.is_active; await session.commit()
    await edit_or_answer(callback, await reseller_package_detail_text(pid), reply_markup=reseller_package_detail_keyboard(pid)); await callback.answer('وضعیت بسته تغییر کرد.')


@router.callback_query(F.data.startswith('resadmin:pkg_delete:'))
async def package_delete(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    pid=int(callback.data.split(':')[-1])
    kb=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ بله، حذف شود', callback_data=f'resadmin:pkg_delete_confirm:{pid}')],
        [back_button(f'resadmin:pkg_detail:{pid}')],
    ])
    await edit_or_answer(callback, '⚠️ مطمئنی می‌خواهی این بسته نمایندگی حذف شود؟\n\nاگر درخواست شارژ قبلی به این بسته وصل باشد، بسته به‌صورت امن غیرفعال می‌شود تا تاریخچه خراب نشود.', reply_markup=kb); await callback.answer()


@router.callback_query(F.data.startswith('resadmin:pkg_delete_confirm:'))
async def package_delete_confirm(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    pid=int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        pkg=await session.get(ResellerPackage,pid)
        has_requests=False
        if pkg:
            req=(await session.execute(select(ResellerTopupRequest.id).where(ResellerTopupRequest.package_id==pid).limit(1))).scalar_one_or_none()
            has_requests=req is not None
            if has_requests:
                pkg.is_active=False
            else:
                await session.delete(pkg)
            await session.commit()
    msg='✅ بسته حذف شد.' if not has_requests else '✅ این بسته چون سابقه درخواست داشت، به‌صورت امن غیرفعال شد.'
    await edit_or_answer(callback, msg, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('resadmin:packages')]])); await callback.answer()


@router.callback_query(F.data.startswith('resadmin:pkg_edit:'))
async def package_edit_start(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    parts=callback.data.split(':')
    field=parts[2]; pid=int(parts[3])
    if field == 'server':
        async with SessionLocal() as session:
            servers=await active_reseller_servers(session)
        if not servers:
            await edit_or_answer(callback, '❌ هیچ سرور فعالی ثبت نشده است.', reply_markup=reseller_package_detail_keyboard(pid)); await callback.answer(); return
        rows=[[InlineKeyboardButton(text=s.name, callback_data=f'resadmin:pkg_edit_server:{pid}:{s.id}')] for s in servers]
        rows.append([back_button(f'resadmin:pkg_detail:{pid}')])
        await edit_or_answer(callback, '🖥 سرور جدید بسته نمایندگی را انتخاب کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)); await callback.answer(); return
    labels={
        'title':'نام جدید بسته نمایندگی را وارد کنید:',
        'price':'قیمت جدید را به تومان وارد کنید:',
        'volume':'حجم جدید را به گیگ وارد کنید:',
        'validity':'اعتبار جدید نمایندگی را به روز وارد کنید:',
    }
    if field not in labels:
        await callback.answer('گزینه نامعتبر است.', show_alert=True); return
    await state.clear(); await state.update_data(package_id=pid, field=field)
    await state.set_state(EditResellerPackage.value)
    await edit_or_answer(callback, labels[field], reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(f'resadmin:pkg_detail:{pid}')]])); await callback.answer()


@router.callback_query(F.data.startswith('resadmin:pkg_edit_server:'))
async def package_edit_server_save(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    parts=callback.data.split(':')
    pid=int(parts[2]); sid=int(parts[3])
    async with SessionLocal() as session:
        pkg=await session.get(ResellerPackage,pid)
        server=await session.get(Server,sid)
        if not pkg or not server:
            await callback.answer('بسته یا سرور پیدا نشد.', show_alert=True); return
        pkg.server_id=sid
        await session.commit()
    await edit_or_answer(callback, await reseller_package_detail_text(pid), reply_markup=reseller_package_detail_keyboard(pid)); await callback.answer('سرور ذخیره شد.')


@router.message(EditResellerPackage.value)
async def package_edit_save(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    data=await state.get_data(); pid=int(data.get('package_id')); field=data.get('field')
    value=(message.text or '').strip()
    try:
        async with SessionLocal() as session:
            pkg=await session.get(ResellerPackage,pid)
            if not pkg:
                await ui_message(message,'❌ بسته نمایندگی پیدا نشد.'); await state.clear(); return
            if field == 'title':
                if not value:
                    raise ValueError('empty title')
                pkg.title=value
            elif field == 'price':
                pkg.price_irt=int(value.replace(',',''))
            elif field == 'volume':
                pkg.volume_gb=int(float(value.replace(',','.')))
            elif field == 'validity':
                pkg.reseller_validity_days=int(value)
            else:
                await ui_message(message,'گزینه ویرایش نامعتبر است.'); await state.clear(); return
            await session.commit()
    except Exception:
        await ui_message(message,'❌ مقدار وارد شده معتبر نیست. دوباره تلاش کنید.'); return
    await state.clear()
    await ui_message(message, await reseller_package_detail_text(pid), reply_markup=reseller_package_detail_keyboard(pid))
