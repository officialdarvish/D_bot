from datetime import datetime, timedelta

from aiogram import Bot
from fastapi import FastAPI, Request, Header, HTTPException
from app.database.base import Base
from app.database.session import engine, SessionLocal
from app.database import models
from app.database.defaults import seed_default_settings, get_setting_value, WELCOME_TEXT_DEFAULT
from app.database.models import Order, User, Plan, Server, ClientService
from app.core.config import settings
from app.services.nowpayments_service import NowPaymentsService
from app.services.xui_service import XuiService
from app.bot.keyboards.common import main_menu_inline
from app.bot.service_presenter import send_service_info as send_service_card

app = FastAPI(title='Darvish D Bot API')

@app.on_event('startup')
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for sql in [
            'ALTER TABLE discount_codes ADD COLUMN IF NOT EXISTS per_user_limit INTEGER DEFAULT 1',
            'ALTER TABLE orders ADD COLUMN IF NOT EXISTS external_payment_id VARCHAR(120)',
            'ALTER TABLE orders ADD COLUMN IF NOT EXISTS external_invoice_url TEXT',
        ]:
            try:
                await conn.exec_driver_sql(sql)
            except Exception:
                pass
    await seed_default_settings()

@app.get('/health')
async def health():
    return {'status': 'ok'}

async def _send_home(bot: Bot, chat_id: int) -> None:
    text = await get_setting_value('welcome_text', WELCOME_TEXT_DEFAULT)
    await bot.send_message(chat_id, text, reply_markup=main_menu_inline(chat_id in settings.admin_ids))

async def _build_service(session, user: User, server: Server, plan: Plan, username: str):
    service = ClientService(
        user_id=user.id,
        server_id=server.id,
        plan_id=plan.id,
        client_username=username,
        xui_email=username,
        inbound_ids=plan.inbound_ids,
        total_bytes=plan.volume_gb * 1024 ** 3,
        expires_at=(datetime.utcnow() + timedelta(days=plan.duration_days) if plan.duration_days else None),
        is_payg=plan.is_payg,
    )
    session.add(service)
    await session.flush()
    sub_link = None
    if server.server_type == 'xui':
        created = await XuiService().create_client_on_plan(server, plan, username)
        sub_link = created.get('sub_link') if isinstance(created, dict) else None
        service.sub_link = sub_link
        service.xui_uuid = created.get('uuid') if isinstance(created, dict) else None
    return service, sub_link

@app.post('/webhooks/nowpayments')
async def nowpayments_ipn(request: Request, x_nowpayments_sig: str | None = Header(default=None)):
    raw = await request.body()
    if settings.NOWPAYMENTS_IPN_SECRET and not NowPaymentsService.verify_ipn(raw, x_nowpayments_sig):
        raise HTTPException(status_code=401, detail='invalid signature')
    data = await request.json()
    order_id = str(data.get('order_id') or '')
    payment_id = str(data.get('payment_id') or '')
    status = str(data.get('payment_status') or '').lower()
    if not order_id.isdigit():
        return {'ok': True, 'ignored': 'missing order_id'}
    if status not in {'finished', 'confirmed', 'sending'}:
        return {'ok': True, 'status': status}

    bot = Bot(token=settings.BOT_TOKEN)
    try:
        async with SessionLocal() as session:
            order = await session.get(Order, int(order_id))
            if not order or order.status == 'paid':
                return {'ok': True, 'status': 'already_processed'}
            if payment_id and order.external_payment_id and str(order.external_payment_id) != payment_id:
                raise HTTPException(status_code=400, detail='payment_id mismatch')
            user = await session.get(User, order.user_id)
            plan = await session.get(Plan, order.plan_id)
            server = await session.get(Server, plan.server_id)
            username = order.payment_method.split(':', 1)[1].split(':discount:', 1)[0] if order.payment_method and order.payment_method.startswith('crypto:') else f'user{user.telegram_id}_{order.id}'
            service, sub_link = await _build_service(session, user, server, plan, username)
            order.status = 'paid'
            order.service_id = service.id
            await session.commit()
        await send_service_card(bot, int(user.telegram_id), service.client_username, plan.title, plan.volume_gb, plan.duration_days, sub_link, is_test=False)
        await _send_home(bot, int(user.telegram_id))
    finally:
        await bot.session.close()
    return {'ok': True, 'status': 'processed'}
