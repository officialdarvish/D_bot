"""Mini App launcher and explicit Telegram checkout handoff."""
from urllib.parse import urlsplit
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from sqlalchemy import select
from app.database.session import SessionLocal
from app.database.models import ClientService, User
from app.bot.keyboards.common import get_user_button, back_button
from app.services.web_access import read_web_access
from app.services.miniapp_catalog import public_plans


async def miniapp_url():
    from app.services.miniapp_settings import read_config
    if not (await read_config())['enabled']:
        return None
    access = await read_web_access()
    base = access.login_url.removesuffix(access.login_path)
    parsed = urlsplit(base)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.hostname == 'SERVER_IP':
        return None
    return base + '/miniapp'


_menu_cache = {}


async def sync_menu_button(bot):
    from aiogram.types import MenuButtonWebApp, MenuButtonCommands
    url = await miniapp_url()
    # Use Telegram's current bot display name, including after a BotFather rename.
    # Stored legacy menu_text values must not override the bot's identity.
    name = ''
    if url:
        identity = await bot.get_me()
        name = str(identity.first_name or identity.username or 'مینی‌اپ').strip()
    menu = MenuButtonWebApp(text=name, web_app=WebAppInfo(url=url)) if url else MenuButtonCommands()
    signature = (url, name)
    key = getattr(bot, 'id', id(bot))
    if _menu_cache.get(key) == signature:
        return
    await bot.set_chat_menu_button(menu_button=menu)
    _menu_cache[key] = signature


async def sync_menu_safely(bot):
    try:
        await sync_menu_button(bot)
    except Exception:
        import logging
        logging.getLogger(__name__).warning('Telegram Mini App menu update failed; retrying later', exc_info=True)


async def handle_handoff(message, state, payload):
    if not payload.startswith('mini_'):
        return None
    parts = payload.split('_')
    action = parts[1] if len(parts) > 1 else ''
    sid = int(parts[2]) if len(parts) == 3 and parts[2].isdigit() else None
    if action in {'rhome','rcreate','rtopup','rmanage','rvol','rdays','rrenew','rdelete','rrevoke'}:
        return await reseller_handoff(message, state, action, sid)
    flags = {'buy': 'buy', 'renew': 'my_services', 'convert': 'convert', 'service': 'my_services', 'wallet': 'wallet_topup', 'support': 'tickets'}
    if action not in flags:
        return await message.answer('این درخواست معتبر نیست. لطفاً مینی‌اپ را دوباره باز کنید.')
    if not (await get_user_button(flags[action]))[1]:
        return await message.answer('این بخش توسط مدیریت غیرفعال شده است.')
    label, callback = '', ''
    async with SessionLocal() as session:
        if action == 'buy':
            row = next((row for row in await public_plans(session) if row[0].id == sid), None)
            if not row:
                return await message.answer('این پلن دیگر در دسترس نیست. لطفاً پلن دیگری انتخاب کنید.')
            plan, server, category = row
            from app.bot.handlers.public.buy import get_public_service_types
            types = await get_public_service_types(session)
            kind = next((kind for kind, _, provider in types if provider == server.server_type), 'v2ray')
            await state.update_data(kind=kind, server_type=server.server_type, server_ids=[server.id], server_id=server.id,
                                    category_id=category.id, category_ids=[category.id])
            label, callback = 'ادامه خرید «'+plan.title+'»', f'buy:plan:{plan.id}'
        elif action in ('service', 'renew', 'convert'):
            if not (await get_user_button('my_services'))[1]:
                return await message.answer('بخش کانفیگ‌ها غیرفعال است.')
            user_id = await session.scalar(select(User.id).where(User.telegram_id == message.from_user.id))
            svc = await session.scalar(select(ClientService).where(ClientService.id == sid, ClientService.user_id == user_id,
                                                                   ClientService.reseller_id.is_(None)))
            if not svc:
                return await message.answer('این اشتراک پیدا نشد.')
            callback = {'service': f'svc:{sid}', 'renew': f'svc:renew_menu:{sid}', 'convert': f'svcconvert:source:{sid}'}[action]
            label = {'service': 'نمایش و دریافت کانفیگ', 'renew': 'ادامه تمدید اشتراک', 'convert': 'ادامه تبدیل تعرفه'}[action]
        else:
            label, callback = ('افزایش موجودی کیف پول', 'wallet:topup') if action == 'wallet' else ('ورود به پشتیبانی', 'menu:tickets')
    if action == 'convert':
        # /start explicitly enters the established conversion workflow.
        from types import SimpleNamespace
        from app.bot.handlers.public.convert import convert_choose_category
        sent = await message.answer('در حال دریافت تعرفه‌های قابل تبدیل…')
        async def answered(text=None, **kwargs):
            if text:await sent.edit_text(text)
        callback_event = SimpleNamespace(from_user=message.from_user,message=sent,bot=message.bot,data=callback,answer=answered)
        await convert_choose_category(callback_event)
        return sent
    from app.bot.utils import remember_ui_message
    sent = await message.answer('درخواست شما از وب‌اپ دریافت شد. برای ادامه دکمه زیر را بزنید.', reply_markup=InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=label, callback_data=callback)], [back_button()]]))
    remember_ui_message(message.chat.id, sent.message_id)
    return sent


async def reseller_handoff(message, state, action, sid):
    from app.api.miniapp import RESELLER_ACTIONS
    from app.database.models import ResellerAccount
    from app.services.reseller_service import get_user_reseller, is_reseller_access_active
    from app.services.miniapp_settings import read_config
    if action not in RESELLER_ACTIONS or not (await read_config())['reseller_enabled']:
        return await message.answer('این درخواست در دسترس نیست.')
    async with SessionLocal() as session:
        user, account = await get_user_reseller(session,message.from_user.id)
        if not account or (not is_reseller_access_active(account) and action != 'rtopup'):
            return await message.answer('دسترسی نمایندگی شما غیرفعال یا منقضی شده است.')
        if action not in ('rhome','rcreate','rtopup'):
            svc=await session.scalar(select(ClientService).where(ClientService.id==sid,ClientService.reseller_id==account.id))
            from app.services.service_grace import visible_in_my_services
            if svc is None or not visible_in_my_services(svc):
                return await message.answer('کانفیگ نمایندگی پیدا نشد.')
        callbacks={'rhome':'menu:reseller','rcreate':'reseller:create','rtopup':'paygwallet:topup' if getattr(account,'billing_mode','volume')=='payg' else 'reseller:topup',
            'rmanage':f'reseller:user:{sid}','rvol':f'reseller:addvol:{sid}','rdays':f'reseller:adddays:{sid}',
            'rrenew':f'reseller:renew:{sid}','rdelete':f'reseller:delete:{sid}','rrevoke':f'reseller:revoke:{sid}'}
        labels={'rhome':'منوی نمایندگی','rcreate':'ساخت کانفیگ','rtopup':'شارژ حجم نمایندگی','rmanage':'مدیریت کانفیگ',
            'rvol':'افزایش حجم','rdays':'افزایش روز','rrenew':'تمدید کانفیگ','rdelete':'بررسی و تایید حذف','rrevoke':'بازسازی لینک'}
    from app.bot.utils import remember_ui_message
    sent=await message.answer('برای ادامه درخواست نمایندگی، دکمه زیر را بزنید.',reply_markup=InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=labels[action],callback_data=callbacks[action])],[back_button('menu:reseller')]]))
    remember_ui_message(message.chat.id,sent.message_id)
    return sent
