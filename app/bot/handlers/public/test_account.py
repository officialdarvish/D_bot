from datetime import datetime, timedelta
import time
import re
from decimal import Decimal, InvalidOperation
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select
from app.database.session import SessionLocal
from app.database.models import User, Server, ClientService, TestAccountUsage
from app.database.defaults import get_setting_value, WELCOME_TEXT_DEFAULT
from app.bot.keyboards.common import BTN_TEST_ACCOUNT, CB_TEST_ACCOUNT, back_main_inline, main_menu_inline
from app.bot.service_presenter import send_service_info
from app.xui.client import XuiClientPayload
from app.services.xui_service import XuiService
from app.bot.utils import ui_page

def _xui_text(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


router = Router()

def parse_inbounds(text: str) -> list[int]:
    return [int(x) for x in re.split(r'[,\s]+', text.strip()) if x.isdigit()]

def parse_volume_gb(value: str | None, default: str = '1') -> float:
    raw = (value or default).strip().replace(',', '.')
    try:
        parsed = Decimal(raw)
    except (InvalidOperation, ValueError):
        parsed = Decimal(default)
    if parsed <= 0:
        parsed = Decimal(default)
    return float(parsed)

def format_gb(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f'{value:g}'

async def handle_test_account(target, telegram_id: int, username: str | None):
    if await get_setting_value('test_account_enabled', '1') != '1':
        await ui_page(target, '⛔️ دریافت اکانت تست فعلاً غیرفعال است.', reply_markup=back_main_inline())
        return
    server_id = await get_setting_value('test_account_server_id', '')
    saved_inbound_ids = parse_inbounds(await get_setting_value('test_account_inbound_ids', ''))
    volume_gb = parse_volume_gb(await get_setting_value('test_account_volume_gb', '1'), '1')
    duration_days = int(await get_setting_value('test_account_duration_days', '1') or '1')
    if not server_id:
        await ui_page(target, '⚠️ تنظیمات اکانت تست هنوز توسط مدیر کامل نشده است.', reply_markup=back_main_inline())
        return
    async with SessionLocal() as session:
        user = (await session.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one()
        used = (await session.execute(select(TestAccountUsage).where(TestAccountUsage.telegram_id == telegram_id))).scalar_one_or_none()
        if used:
            await ui_page(target, '⛔️ شما قبلاً یک بار اکانت تست دریافت کرده‌اید.', reply_markup=back_main_inline())
            return
        server = await session.get(Server, int(server_id))
        if not server or not server.is_active:
            await ui_page(target, '⚠️ سرور اکانت تست در دسترس نیست.', reply_markup=back_main_inline())
            return
        inbound_ids = saved_inbound_ids or [int(x.get('id') if isinstance(x, dict) else x) for x in ((server.meta or {}).get('inbound_ids') or []) if str(x.get('id') if isinstance(x, dict) else x).isdigit()]
        if not inbound_ids:
            await ui_page(target, '⚠️ برای سرور اکانت تست هیچ Inbound فعالی ثبت نشده است.', reply_markup=back_main_inline())
            return
        # Use a unique email for every test account creation. When the admin resets
        # test-account receivers, the old test client may still exist on 3x-ui;
        # reusing test_<telegram_id> causes: email already in use.
        client_name = f'test_{telegram_id}_{int(time.time())}'
        service = ClientService(
            user_id=user.id,
            server_id=server.id,
            plan_id=None,
            client_username=client_name,
            xui_email=client_name,
            inbound_ids=inbound_ids,
            total_bytes=int(volume_gb * 1024**3),
            expires_at=datetime.utcnow() + timedelta(days=duration_days),
            is_active=True,
            is_payg=False,
        )
        session.add(service)
        await session.flush()
        session.add(TestAccountUsage(user_id=user.id, telegram_id=telegram_id, service_id=service.id))
        sub_link = None
        if server.server_type == 'xui':
            payload = XuiClientPayload(email=client_name, total_gb=volume_gb, expire_days=duration_days)
            created = await XuiService().create_client_on_inbounds(server, inbound_ids, payload)
            if isinstance(created, dict):
                sub_link = created.get('sub_link')
                service.sub_link = sub_link
                service.xui_uuid = _xui_text(created.get('uuid'))
        await session.commit()
    await send_service_info(
        target.bot,
        telegram_id,
        client_name,
        'اکانت تست',
        volume_gb,
        duration_days,
        sub_link,
        is_test=True,
        reply_markup=back_main_inline(),
    )
    async with SessionLocal() as session:
        user = (await session.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one_or_none()
        is_reseller = False
        if user:
            from app.database.models import ResellerAccount
            reseller = (await session.execute(select(ResellerAccount).where(ResellerAccount.user_id == user.id))).scalar_one_or_none()
            is_reseller = bool(reseller and reseller.is_active)
    await target.bot.send_message(
        telegram_id,
        '✅ اکانت تست برای شما ارسال شد.\n\nبه صفحه اصلی برگشتید.',
        reply_markup=main_menu_inline(False, is_reseller=is_reseller),
    )

@router.message(F.text == BTN_TEST_ACCOUNT)
async def test_account_text(message: Message):
    await handle_test_account(message, message.from_user.id, message.from_user.username)

@router.callback_query(F.data == CB_TEST_ACCOUNT)
async def test_account_cb(callback: CallbackQuery):
    await handle_test_account(callback.message, callback.from_user.id, callback.from_user.username)
    await callback.answer()
