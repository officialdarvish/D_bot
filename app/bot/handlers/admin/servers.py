from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy import select, update, delete
from app.core.roles import is_owner
from app.core.security import encrypt_text, decrypt_text
from app.database.session import SessionLocal
from app.database.models import Server, Plan, ServerCategory, ClientService, PaymentCard, Order, AntiSharingViolation, PaygUsageLog, TestAccountUsage
from app.bot.states.admin_states import AddServer
from app.services.xui_service import XuiService
from app.jobs.server_sync import refresh_server_inbounds
from app.bot.keyboards.common import CB_SERVERS, back_button, main_menu_inline
from app.bot.utils import edit_or_answer, ui_message, ui_callback_message
from app.bot.error_reporting import handle_user_facing_error

router = Router()
def admin(uid): return is_owner(uid)

def status_text(s): return '🟢 فعال' if s.is_active else '🔴 غیر فعال'
def type_text(t): return 'سنایی' if t == 'xui' else 'OpenVPN'
def is_public_server(s: Server | None) -> bool:
    return bool(s) and (s.meta or {}).get('scope') != 'reseller'

def _clean_inbound_ids(value) -> list[int]:
    ids: list[int] = []
    items = list(value) if isinstance(value, (list, tuple, set)) else ([] if value is None else [value])
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

def server_inbounds(server: Server | None) -> list[int]:
    return _clean_inbound_ids((server.meta or {}).get('inbound_ids') if server else [])

def _chunked_ids_text(ids: list[int], per_line: int = 4) -> str:
    ids = _clean_inbound_ids(ids or [])
    if not ids:
        return '└ -'
    return '\n'.join('└ ' + ' • '.join(map(str, ids[i:i + per_line])) for i in range(0, len(ids), per_line))

def _keep_or_new(value: str, old: str | None) -> str:
    value = (value or '').strip()
    return old if value == '-' and old is not None else value

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
        return base.rstrip('/'), parsed.path or '/'
    except Exception:
        return url, '/'

def _compose_panel_url(base_url: str, panel_path: str) -> str:
    base = (base_url or '').strip().rstrip('/')
    path = (panel_path or '').strip() or '/'
    if path == '-': path = '/'
    if not path.startswith('/'): path = '/' + path
    if path != '/' and not path.endswith('/'): path += '/'
    return f'{base}{path}'

def _server_summary(data: dict, action_text: str = 'اضافه کردن') -> str:
    inbound_ids = _clean_inbound_ids(data.get('inbound_ids') or [])
    panel_url = _compose_panel_url(data.get('panel_url', ''), data.get('panel_path', '/'))
    password_preview = '••••••••' if data.get('password') else '-'
    return (
        '🖥 پیش‌نمایش سرور فروش\n\n'
        f'🏷 نام سرور\n└ {data.get("name") or "-"}\n\n'
        f'🌐 آدرس پنل\n└ {data.get("panel_url") or "-"}\n\n'
        f'📂 Path پنل\n└ {data.get("panel_path") or "/"}\n\n'
        f'🔗 آدرس نهایی\n└ {panel_url or "-"}\n\n'
        f'👤 نام کاربری\n└ {data.get("username") or "-"}\n\n'
        f'🔐 رمز عبور\n└ {password_preview}\n\n'
        f'📡 لینک ساب\n└ {data.get("subscription_url") or "-"}\n\n'
        f'📥 Inbounds\n{_chunked_ids_text(inbound_ids)}\n\n'
        '━━━━━━━━━━━━━━━\n\n'
        'لطفاً اطلاعات را بررسی کنید.\n'
        f'اگر درست است روی «✅ {action_text}» بزنید.\n'
        'اگر نیاز به اصلاح دارد روی «❌ اصلاح اطلاعات» بزنید.'
    )

def _server_confirm_kb(mode: str) -> InlineKeyboardMarkup:
    label = 'تغییر' if mode == 'edit' else 'اضافه کردن'
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ تایید و ثبت', callback_data='server:confirm')],
        [InlineKeyboardButton(text='❌ عدم تایید و اصلاح', callback_data='server:restart')],
        [back_button('admin:servers')],
    ])

async def _fetch_panel_inbounds(data: dict) -> tuple[bool, list[int], str]:
    if data.get('server_type') != 'xui':
        return True, [], ''
    server = Server(
        name=data.get('name') or 'preview', server_type='xui',
        panel_url=_compose_panel_url(data.get('panel_url', ''), data.get('panel_path', '/')),
        subscription_url=data.get('subscription_url'), username=data.get('username') or '',
        password_encrypted=encrypt_text(data.get('password') or ''), is_active=True,
        meta={'scope': 'public', 'panel_base_url': data.get('panel_url'), 'panel_path': data.get('panel_path')},
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

async def servers_keyboard():
    async with SessionLocal() as session:
        all_servers = (await session.execute(select(Server).order_by(Server.id.desc()))).scalars().all()
    servers = [srv for srv in all_servers if is_public_server(srv)]
    rows = [[InlineKeyboardButton(text='سرور', callback_data='noop'), InlineKeyboardButton(text='نوعیت', callback_data='noop'), InlineKeyboardButton(text='تنظیمات', callback_data='noop'), InlineKeyboardButton(text='وضعیت', callback_data='noop')]]
    for s in servers:
        rows.append([
            InlineKeyboardButton(text=s.name[:18], callback_data=f'server:detail:{s.id}'),
            InlineKeyboardButton(text=type_text(s.server_type), callback_data='noop'),
            InlineKeyboardButton(text='⚙️', callback_data=f'server:detail:{s.id}'),
            InlineKeyboardButton(text=status_text(s), callback_data=f'server:toggle:{s.id}'),
        ])
    rows.append([InlineKeyboardButton(text='ثبت سرور جدید ➕', callback_data='server:add:xui')])
    rows.append([back_button('admin:sales_section')])
    return InlineKeyboardMarkup(inline_keyboard=rows)

@router.callback_query(F.data == 'noop')
async def noop(callback: CallbackQuery): await callback.answer()

@router.callback_query(F.data == CB_SERVERS)
async def servers_menu(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    await state.clear()
    await edit_or_answer(callback, '🛒 بخش فروش > مدیریت سرور', reply_markup=await servers_keyboard()); await callback.answer()

async def _start_server_questions(callback: CallbackQuery, state: FSMContext, mode: str = 'add', server: Server | None = None, server_type: str = 'xui'):
    base, path = _split_panel_url(server)
    old_password = None
    if server:
        try: old_password = decrypt_text(server.password_encrypted)
        except Exception: old_password = None
    await state.clear()
    await state.update_data(
        mode=mode, server_type=server.server_type if server else server_type,
        edit_server_id=server.id if server else None,
        old_name=server.name if server else None,
        old_panel_url=base or None,
        old_panel_path=path or '/',
        old_subscription_url=server.subscription_url if server else None,
        old_username=server.username if server else None,
        old_password=old_password,
        old_inbound_ids=server_inbounds(server) if server else [],
    )
    await state.set_state(AddServer.name)
    await edit_or_answer(callback, 'نام سرور فروش را وارد کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:servers')]]))
    await callback.answer()

@router.callback_query(F.data.startswith('server:add:'))
async def add_server_type(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    await _start_server_questions(callback, state, 'add', None, callback.data.split(':')[-1])

@router.message(AddServer.name)
async def server_name(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    data = await state.get_data()
    name = _keep_or_new(message.text or '', data.get('old_name'))
    if not name:
        await ui_message(message, 'نام سرور نمی‌تواند خالی باشد.'); return
    await state.update_data(name=name); await state.set_state(AddServer.panel_url)
    await ui_message(message, 'آدرس اصلی پنل را بدون path وارد کنید:\nمثال: https://domain.com یا https://domain.com:2053', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:servers')]]))

@router.message(AddServer.panel_url)
async def server_url(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    data = await state.get_data()
    panel_url = _keep_or_new(message.text or '', data.get('old_panel_url'))
    if not panel_url.startswith(('http://', 'https://')):
        await ui_message(message, '❌ آدرس پنل باید با http:// یا https:// شروع شود. دوباره وارد کنید:'); return
    await state.update_data(panel_url=panel_url.rstrip('/')); await state.set_state(AddServer.panel_path)
    await ui_message(message, 'Path پنل را وارد کنید:\nمثال: /secretpath/ یا /\n\nاگر پنل path ندارد / بفرستید.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:servers')]]))

@router.message(AddServer.panel_path)
async def server_path(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    data = await state.get_data()
    panel_path = _keep_or_new(message.text or '', data.get('old_panel_path') or '/') or '/'
    if not panel_path.startswith('/'):
        panel_path = '/' + panel_path
    if panel_path != '/' and not panel_path.endswith('/'):
        panel_path += '/'
    await state.update_data(panel_path=panel_path); await state.set_state(AddServer.subscription_url)
    await ui_message(message, 'لینک ساب‌اسکریپشن را وارد کنید. مثال:\nhttps://sub.domain.com/subb/', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:servers')]]))

@router.message(AddServer.subscription_url)
async def server_subscription_url(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    data = await state.get_data()
    sub = _keep_or_new(message.text or '', data.get('old_subscription_url'))
    await state.update_data(subscription_url=sub); await state.set_state(AddServer.username)
    await ui_message(message, 'نام کاربری پنل را وارد کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:servers')]]))

@router.message(AddServer.username)
async def server_username(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    data = await state.get_data()
    username = _keep_or_new(message.text or '', data.get('old_username'))
    if not username:
        await ui_message(message, 'نام کاربری نمی‌تواند خالی باشد. دوباره وارد کنید:'); return
    await state.update_data(username=username); await state.set_state(AddServer.password)
    await ui_message(message, 'رمز عبور پنل را وارد کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:servers')]]))

@router.message(AddServer.password)
async def server_password(message: Message, state: FSMContext):
    if not admin(message.from_user.id): return
    data = await state.get_data()
    password = _keep_or_new(message.text or '', data.get('old_password'))
    if not password:
        await ui_message(message, 'رمز عبور نمی‌تواند خالی باشد. دوباره وارد کنید:'); return
    await state.update_data(password=password)
    data = await state.get_data()
    ok, inbound_ids, err = await _fetch_panel_inbounds(data)
    if not ok:
        await handle_user_facing_error(message, Exception(err or 'Login/List inbounds failed'), context='Admin public server inbound fetch failed', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:servers')]]))
        await state.clear(); return
    await state.update_data(inbound_ids=inbound_ids)
    data = await state.get_data()
    await state.set_state(AddServer.confirm)
    action_text = 'تغییر' if data.get('mode') == 'edit' else 'اضافه کردن'
    await ui_message(message, _server_summary(data, action_text), reply_markup=_server_confirm_kb(data.get('mode') or 'add'))

@router.callback_query(F.data == 'server:restart')
async def server_restart(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    data = await state.get_data()
    sid = data.get('edit_server_id')
    if data.get('mode') == 'edit' and sid:
        async with SessionLocal() as session: server = await session.get(Server, int(sid))
        await _start_server_questions(callback, state, 'edit', server)
        return
    await _start_server_questions(callback, state, 'add', None, data.get('server_type') or 'xui')

@router.callback_query(F.data == 'server:confirm')
async def server_confirm(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    data = await state.get_data()
    panel_url_full = _compose_panel_url(data.get('panel_url', ''), data.get('panel_path', '/'))
    inbound_ids = _clean_inbound_ids(data.get('inbound_ids') or [])
    server_type = data.get('server_type') or 'xui'
    server = Server(
        name=data['name'], server_type=server_type, panel_url=panel_url_full,
        subscription_url=data.get('subscription_url'), username=data['username'],
        password_encrypted=encrypt_text(data['password']), is_active=True,
        meta={'scope': 'public', 'inbound_ids': inbound_ids, 'panel_base_url': data.get('panel_url'), 'panel_path': data.get('panel_path')},
    )
    if server_type == 'xui':
        ok=False; err=''; rows=[]
        try: ok, rows = await XuiService().test_server(server)
        except Exception as exc: err=str(exc)
        if not ok:
            await handle_user_facing_error(callback, Exception(err or 'Login/List inbounds failed'), context='Admin public server confirm test failed', reply_markup=_server_confirm_kb(data.get('mode') or 'add'))
            await callback.answer(); return
        live_ids = _clean_inbound_ids([r.get('id') for r in (rows or []) if isinstance(r, dict)])
        if not live_ids:
            await edit_or_answer(callback, '❌ اتصال به پنل موفق بود، اما هیچ Inboundی از پنل دریافت نشد.', reply_markup=_server_confirm_kb(data.get('mode') or 'add'))
            await callback.answer(); return
        inbound_ids = live_ids
        server.meta = {'scope': 'public', 'inbound_ids': inbound_ids, 'panel_base_url': data.get('panel_url'), 'panel_path': data.get('panel_path')}
    mode = data.get('mode') or 'add'
    async with SessionLocal() as session:
        if mode == 'edit' and data.get('edit_server_id'):
            target = await session.get(Server, int(data['edit_server_id']))
            if not is_public_server(target):
                await callback.answer('سرور پیدا نشد.', show_alert=True); return
            target.name = data['name']; target.server_type = server_type; target.panel_url = panel_url_full
            target.subscription_url = data.get('subscription_url'); target.username = data['username']
            target.password_encrypted = encrypt_text(data['password'])
            target.meta = {'scope': 'public', 'inbound_ids': inbound_ids, 'panel_base_url': data.get('panel_url'), 'panel_path': data.get('panel_path')}
            server_id = target.id; success_text = '✅ اطلاعات سرور فروش با موفقیت تغییر کرد.'
        else:
            session.add(server); await session.flush(); server_id = server.id; success_text = '✅ سرور فروش با موفقیت اضافه شد.'
        await session.commit()
    await state.clear()
    await edit_or_answer(callback, f'{success_text}\n\n🖥 سرور: {data["name"]}\n🆔 ID: {server_id}\n🔢 اینباندها: {", ".join(map(str, inbound_ids)) if inbound_ids else "-"}\n\n📋 لیست سرورها بروزرسانی شد:', reply_markup=await servers_keyboard())
    await callback.answer()

@router.callback_query(F.data.startswith('server:toggle:'))
async def toggle_server(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    sid=int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        s=await session.get(Server,sid)
        if is_public_server(s): s.is_active=not s.is_active; await session.commit()
    await edit_or_answer(callback, '✅ وضعیت سرور بروزرسانی شد.', reply_markup=await servers_keyboard()); await callback.answer()

@router.callback_query(F.data.startswith('server:detail:'))
async def server_detail(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    sid=int(callback.data.split(':')[-1])
    async with SessionLocal() as session: s=await session.get(Server,sid)
    if not is_public_server(s): await callback.answer('سرور پیدا نشد.', show_alert=True); return
    ids=server_inbounds(s); base, path = _split_panel_url(s)
    kb=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🔄 بروزرسانی سرور', callback_data=f'server:refresh:{s.id}')],
        [InlineKeyboardButton(text='✏️ تغییر اطلاعات لاگین', callback_data=f'server:edit:{s.id}')],
        [InlineKeyboardButton(text='🔄 تغییر وضعیت', callback_data=f'server:toggle:{s.id}')],
        [InlineKeyboardButton(text='🗑 حذف سرور', callback_data=f'server:delete:{s.id}')],
        [back_button('admin:servers')],
    ])
    st = '✅ فعال' if s.is_active else '❌ غیرفعال'
    text=(
        '🖥 اطلاعات سرور فروش\n\n'
        f'🏷 نام سرور\n└ {s.name}\n\n'
        f'🌐 آدرس پنل\n└ {base or s.panel_url}\n\n'
        f'📂 Path پنل\n└ {path}\n\n'
        f'🔗 آدرس نهایی\n└ {s.panel_url}\n\n'
        f'👤 نام کاربری\n└ {s.username}\n\n'
        f'📡 لینک ساب\n└ {s.subscription_url or "-"}\n\n'
        f'⚙️ وضعیت\n└ {st}\n\n'
        f'📥 Inbounds\n{_chunked_ids_text(ids)}'
    )
    await edit_or_answer(callback, text, reply_markup=kb); await callback.answer()


@router.callback_query(F.data.startswith('server:refresh:'))
async def refresh_server(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    sid = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        s = await session.get(Server, sid)
        if not is_public_server(s):
            await callback.answer('سرور پیدا نشد.', show_alert=True); return
        ok, old_ids, new_ids, err = await refresh_server_inbounds(session, s, force_plan_update=True)
        if ok:
            await session.commit()
    if not ok:
        await handle_user_facing_error(callback, Exception(err or 'Refresh server inbounds failed'), context='Admin public server refresh failed', reply_markup=await servers_keyboard())
        return
    changed = 'تغییر کرد' if old_ids != new_ids else 'تغییری نداشت'
    await edit_or_answer(callback, f'✅ سرور بروزرسانی شد.\n\nقبلی: {", ".join(map(str, old_ids)) or "-"}\nجدید: {", ".join(map(str, new_ids)) or "-"}\nوضعیت: {changed}', reply_markup=await servers_keyboard())
    await callback.answer('بروزرسانی شد.')

@router.callback_query(F.data.startswith('server:edit:'))
async def server_edit(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    sid=int(callback.data.split(':')[-1])
    async with SessionLocal() as session: s=await session.get(Server,sid)
    if not is_public_server(s): await callback.answer('سرور پیدا نشد.', show_alert=True); return
    await _start_server_questions(callback, state, 'edit', s)

@router.callback_query(F.data.startswith('server:delete:'))
async def delete_server_ask(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    if callback.data.startswith('server:delete_confirm:'): return
    sid=int(callback.data.split(':')[-1])
    kb=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ بله، سرور حذف شود', callback_data=f'server:delete_confirm:{sid}')],
        [back_button(f'server:detail:{sid}')],
    ])
    await edit_or_answer(callback, '⚠️ مطمئنی می‌خواهی این سرور حذف شود؟\nتمام پلن‌ها، کارت‌ها و رکورد سرویس‌های مربوط به این سرور از دیتابیس حذف می‌شوند.', reply_markup=kb); await callback.answer()

@router.callback_query(F.data.startswith('server:delete_confirm:'))
async def delete_server(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    sid=int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        s=await session.get(Server,sid)
        if is_public_server(s):
            plan_ids=[p.id for p in (await session.execute(select(Plan).where(Plan.server_id == sid))).scalars().all()]
            service_ids=[cs.id for cs in (await session.execute(select(ClientService).where(ClientService.server_id == sid))).scalars().all()]
            if plan_ids:
                await session.execute(delete(Order).where(Order.plan_id.in_(plan_ids)))
            if service_ids:
                await session.execute(update(Order).where(Order.service_id.in_(service_ids)).values(service_id=None))
                await session.execute(update(TestAccountUsage).where(TestAccountUsage.service_id.in_(service_ids)).values(service_id=None))
                await session.execute(delete(AntiSharingViolation).where(AntiSharingViolation.service_id.in_(service_ids)))
                await session.execute(delete(PaygUsageLog).where(PaygUsageLog.service_id.in_(service_ids)))
            await session.execute(delete(PaymentCard).where(PaymentCard.server_id == sid))
            await session.execute(delete(ClientService).where(ClientService.server_id == sid))
            await session.execute(delete(Plan).where(Plan.server_id == sid))
            await session.execute(delete(ServerCategory).where(ServerCategory.server_id == sid))
            await session.delete(s); await session.commit()
    await edit_or_answer(callback, '✅ سرور به‌صورت کامل حذف شد.\n\n📋 لیست سرورها:', reply_markup=await servers_keyboard()); await callback.answer()
