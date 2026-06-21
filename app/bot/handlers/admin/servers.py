from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy import select, update, delete
from app.core.config import settings
from app.core.roles import is_owner
from app.core.security import encrypt_text
from app.database.session import SessionLocal
from app.database.models import Server, Plan, ServerCategory, ClientService, PaymentCard, Order, AntiSharingViolation, PaygUsageLog, TestAccountUsage
from app.bot.states.admin_states import AddServer
from app.services.xui_service import XuiService
from app.bot.keyboards.common import CB_SERVERS, back_button
from app.bot.utils import edit_or_answer, ui_message, ui_callback_message, state_prompt, delete_state_message

router = Router()
def admin(uid): return is_owner(uid)

def status_text(s): return '🟢 فعال' if s.is_active else '🔴 غیر فعال'
def type_text(t): return 'سنایی' if t == 'xui' else 'OpenVPN'

async def servers_keyboard():
    async with SessionLocal() as session:
        all_servers = (await session.execute(select(Server).order_by(Server.id.desc()))).scalars().all()
    servers = [srv for srv in all_servers if (srv.meta or {}).get('scope') != 'reseller']
    rows = [[InlineKeyboardButton(text='سرور', callback_data='noop'), InlineKeyboardButton(text='نوعیت', callback_data='noop'), InlineKeyboardButton(text='تنظیمات', callback_data='noop'), InlineKeyboardButton(text='وضعیت', callback_data='noop')]]
    for s in servers:
        rows.append([
            InlineKeyboardButton(text=s.name[:18], callback_data=f'server:detail:{s.id}'),
            InlineKeyboardButton(text=type_text(s.server_type), callback_data='noop'),
            InlineKeyboardButton(text='⚙️', callback_data=f'server:detail:{s.id}'),
            InlineKeyboardButton(text=status_text(s), callback_data=f'server:toggle:{s.id}'),
        ])
    rows.append([InlineKeyboardButton(text='ثبت سرور XUI ➕', callback_data='server:add:xui'), InlineKeyboardButton(text='ثبت سرور OpenVPN ➕', callback_data='server:add:openvpn')])
    rows.append([back_button('back:admin')])
    return InlineKeyboardMarkup(inline_keyboard=rows)

@router.callback_query(F.data == 'noop')
async def noop(callback: CallbackQuery): await callback.answer()

@router.callback_query(F.data == CB_SERVERS)
async def servers_menu(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    await edit_or_answer(callback, '✅ مدیریت سرورها:', reply_markup=await servers_keyboard()); await callback.answer()

@router.callback_query(F.data.startswith('server:add:'))
async def add_server_type(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    await state.clear()
    await state.update_data(server_type=callback.data.split(':')[-1], mode='add')
    await state.set_state(AddServer.name)
    sent = await ui_callback_message(callback, 'نام سرور را وارد کنید. این نام هنگام خرید به کاربر نمایش داده می‌شود:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:servers')]])); await state.update_data(last_bot_message_id=sent.message_id); await callback.answer()

@router.message(AddServer.name)
async def server_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(AddServer.panel_url)
    await state_prompt(message, state, 'آدرس پنل همراه با path را وارد کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:servers')]]))

@router.message(AddServer.panel_url)
async def server_url(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get('mode') == 'edit_url':
        async with SessionLocal() as session:
            s = await session.get(Server, int(data['server_id']))
            if s: s.panel_url = message.text.strip(); await session.commit()
        await state.clear(); await ui_message(message, '✅ آدرس پنل تغییر کرد.', reply_markup=await servers_keyboard()); return
    await state.update_data(panel_url=message.text.strip())
    await state.set_state(AddServer.subscription_url)
    await state_prompt(message, state, 'لینک ساب‌اسکریپشن را وارد کنید. اگر داخل لینک توکن ثابت نیست، انتهای لینک را بدون توکن بفرستید. مثال: https://sub.domain.com/subb/', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:servers')]]))

@router.message(AddServer.username)
async def server_username(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get('mode') == 'edit_login':
        await state.update_data(username=message.text.strip())
        await state.set_state(AddServer.password)
        await ui_message(message, 'پسورد جدید را وارد کنید:')
        return
    await state.update_data(username=message.text.strip())
    await state.set_state(AddServer.password)
    await state_prompt(message, state, 'پسورد پنل را وارد کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:servers')]]))

@router.message(AddServer.password)
async def server_password(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get('mode') == 'edit_login':
        async with SessionLocal() as session:
            s = await session.get(Server, int(data['server_id']))
            if s:
                s.username = data['username']; s.password_encrypted = encrypt_text(message.text.strip())
                await session.commit()
        await state.clear(); await ui_message(message, '✅ اطلاعات ورود تغییر کرد.', reply_markup=await servers_keyboard()); return
    server = Server(name=data['name'], server_type=data['server_type'], panel_url=data['panel_url'], subscription_url=data.get('subscription_url'), username=data['username'], password_encrypted=encrypt_text(message.text.strip()), is_active=True)
    ok=True; err=''
    if server.server_type == 'xui':
        try:
            ok, _ = await XuiService().test_server(server)
        except Exception as e:
            ok=False; err=str(e)
    await delete_state_message(message.bot, message.chat.id, state)
    try:
        await message.delete()
    except Exception:
        pass
    if not ok:
        await state.clear()
        kb=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:servers')]])
        await ui_message(message, f'❌ ارتباط با پنل موفقیت‌آمیز نبود.\n\nلطفاً آدرس پنل، مسیر مخفی، یوزرنیم و پسورد را بررسی کنید.\n\nجزئیات خطا:\n{err or "Login/List inbounds failed"}', reply_markup=kb)
        return
    async with SessionLocal() as session:
        session.add(server); await session.commit()
    await state.clear()
    await ui_message(message, '✅ سرور با موفقیت ثبت شد و اتصال با پنل هم تایید شد.', reply_markup=await servers_keyboard())

@router.callback_query(F.data.startswith('server:toggle:'))
async def toggle_server(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    sid=int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        s=await session.get(Server,sid)
        if s: s.is_active=not s.is_active; await session.commit()
    await edit_or_answer(callback, '✅ مدیریت سرورها:', reply_markup=await servers_keyboard()); await callback.answer()

@router.callback_query(F.data.startswith('server:detail:'))
async def server_detail(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    sid=int(callback.data.split(':')[-1])
    async with SessionLocal() as session: s=await session.get(Server,sid)
    if not s: await callback.answer('سرور پیدا نشد.', show_alert=True); return
    kb=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='♻️ تغییر آدرس پنل', callback_data=f'server:edit_url:{s.id}')],
        [InlineKeyboardButton(text='🔗 تغییر لینک ساب', callback_data=f'server:edit_sub:{s.id}')],
        [InlineKeyboardButton(text='☀️ تغییر اطلاعات ورود', callback_data=f'server:edit_login:{s.id}')],
        [InlineKeyboardButton(text='✂️ حذف سرور', callback_data=f'server:delete:{s.id}')],
        [back_button('admin:servers')],
    ])
    text=f'✅ مدیریت سرورها:\n\n❕ نام سرور: {s.name}\n⚡️ آدرس پنل: {s.panel_url}\n🔗 لینک ساب: {s.subscription_url or "ثبت نشده"}\nوضعیت: {status_text(s)}'
    await edit_or_answer(callback, text, reply_markup=kb); await callback.answer()

@router.callback_query(F.data.startswith('server:delete:'))
async def delete_server(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    sid=int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        s=await session.get(Server,sid)
        if s:
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
            await session.delete(s)
            await session.commit()
    await edit_or_answer(callback, '✅ سرور به‌صورت کامل حذف شد.', reply_markup=await servers_keyboard()); await callback.answer()

@router.callback_query(F.data.startswith('server:edit_url:'))
async def edit_url(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    await state.clear(); await state.update_data(mode='edit_url', server_id=int(callback.data.split(':')[-1]))
    await state.set_state(AddServer.panel_url)
    await ui_callback_message(callback, 'آدرس جدید پنل را وارد کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:servers')]])); await callback.answer()

@router.callback_query(F.data.startswith('server:edit_login:'))
async def edit_login(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    await state.clear(); await state.update_data(mode='edit_login', server_id=int(callback.data.split(':')[-1]))
    await state.set_state(AddServer.username)
    await ui_callback_message(callback, 'یوزرنیم جدید را وارد کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:servers')]])); await callback.answer()


@router.callback_query(F.data.startswith('server:edit_sub:'))
async def edit_sub_url(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    await state.clear(); await state.update_data(mode='edit_sub', server_id=int(callback.data.split(':')[-1]))
    await state.set_state(AddServer.subscription_url)
    await ui_callback_message(callback, 'لینک جدید ساب‌اسکریپشن را وارد کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:servers')]])); await callback.answer()

# override subscription handler for edit mode is handled here by highest matching state
@router.message(AddServer.subscription_url)
async def server_subscription_url_editable(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get('mode') == 'edit_sub':
        async with SessionLocal() as session:
            s = await session.get(Server, int(data['server_id']))
            if s: s.subscription_url = message.text.strip(); await session.commit()
        await state.clear(); await ui_message(message, '✅ لینک ساب تغییر کرد.', reply_markup=await servers_keyboard()); return
    await state.update_data(subscription_url=message.text.strip())
    await state.set_state(AddServer.username)
    await state_prompt(message, state, 'یوزرنیم پنل را وارد کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:servers')]]))
