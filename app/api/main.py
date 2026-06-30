from datetime import datetime, timedelta
import logging
import uuid

from aiogram import Bot
from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse, FileResponse
from app.database.base import Base
from app.database.session import engine, SessionLocal
from app.database import models
from app.database.defaults import get_setting_value, WELCOME_TEXT_DEFAULT
from app.database.models import Order, User, Plan, Server, ClientService
from app.core.config import settings
from app.services.nowpayments_service import NowPaymentsService
from app.services.xui_service import XuiService
from app.services.mikrotik_service import MikroTikService
from app.bot.keyboards.common import main_menu_inline
from app.bot.service_presenter import send_service_info as send_service_card
from app.services.referral_service import apply_purchase_commission
from app.api.admin_web import router as admin_web_router
from fastapi.staticfiles import StaticFiles
from pathlib import Path

app = FastAPI(title='D Bot API')

@app.middleware('http')
async def admin_json_error_middleware(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as exc:
        wants_json = request.url.path.startswith('/admin') and (request.headers.get('x-requested-with') == 'fetch' or 'application/json' in request.headers.get('accept', '') or request.query_params.get('ajax') == '1')
        if wants_json:
            request_id = uuid.uuid4().hex[:12]
            logging.getLogger(__name__).exception('Admin JSON error request_id=%s path=%s', request_id, request.url.path)
            return JSONResponse({'ok': False, 'message': 'Internal server error', 'request_id': request_id}, status_code=500)
        raise

app.include_router(admin_web_router)

FRONTEND_OUT = Path(__file__).resolve().parents[2] / 'frontend_out'

def _frontend_file(path: str = '') -> Path:
    candidates = []
    clean = (path or '').strip('/')
    if clean:
        candidates.extend([
            FRONTEND_OUT / clean / 'index.html',
            FRONTEND_OUT / f'{clean}.html',
        ])
    candidates.append(FRONTEND_OUT / 'index.html')
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    raise HTTPException(status_code=404, detail='Frontend build was not found. Run npm install && npm run build inside frontend, or rebuild the Docker image.')

if (FRONTEND_OUT / '_next').exists():
    app.mount('/_next', StaticFiles(directory=str(FRONTEND_OUT / '_next')), name='next_static')
if (FRONTEND_OUT / 'd-bot-logo.png').exists():
    app.mount('/static', StaticFiles(directory=str(FRONTEND_OUT)), name='frontend_static')

@app.get('/', include_in_schema=False)
async def frontend_root():
    return FileResponse(_frontend_file(''))

@app.get('/admin', include_in_schema=False)
async def frontend_admin_root():
    return FileResponse(_frontend_file('admin'))

@app.get('/admin/{path:path}', include_in_schema=False)
async def frontend_admin_path(path: str):
    return FileResponse(_frontend_file('admin/' + path))

@app.on_event('startup')
async def startup():
    logger = logging.getLogger(__name__)

    async def safe_upgrade(conn, sql: str) -> None:
        try:
            await conn.exec_driver_sql(sql)
        except Exception as exc:
            logger.warning("Database upgrade skipped: %s | %s", sql, exc)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for sql in [
            'ALTER TABLE discount_codes ADD COLUMN IF NOT EXISTS per_user_limit INTEGER DEFAULT 1',
            'ALTER TABLE orders ADD COLUMN IF NOT EXISTS external_payment_id VARCHAR(120)',
            'ALTER TABLE orders ADD COLUMN IF NOT EXISTS external_invoice_url TEXT',
            "ALTER TABLE servers ADD COLUMN IF NOT EXISTS display_name VARCHAR(150)",
            "ALTER TABLE servers ADD COLUMN IF NOT EXISTS profile VARCHAR(32) DEFAULT '3x-ui'",
            "ALTER TABLE payment_cards ADD COLUMN IF NOT EXISTS scopes JSON DEFAULT '[]'",
            'ALTER TABLE client_services ALTER COLUMN server_id DROP NOT NULL',
            'ALTER TABLE plans ALTER COLUMN server_id DROP NOT NULL',
            'ALTER TABLE plans ALTER COLUMN category_id DROP NOT NULL',
            "ALTER TABLE server_categories ADD COLUMN IF NOT EXISTS server_ids JSON DEFAULT '[]'",
            "ALTER TABLE discount_codes ADD COLUMN IF NOT EXISTS allowed_server_ids JSON DEFAULT '[]'",
            'ALTER TABLE plans DROP CONSTRAINT IF EXISTS plans_category_id_fkey',
            'ALTER TABLE plans ADD CONSTRAINT plans_category_id_fkey FOREIGN KEY (category_id) REFERENCES server_categories(id) ON DELETE SET NULL',
            'ALTER TABLE plans DROP CONSTRAINT IF EXISTS plans_server_id_fkey',
            'ALTER TABLE plans ADD CONSTRAINT plans_server_id_fkey FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE SET NULL',
            "ALTER TABLE plans ADD COLUMN IF NOT EXISTS meta JSON DEFAULT '{}'",
            "ALTER TABLE reseller_packages ADD COLUMN IF NOT EXISTS meta JSON DEFAULT '{}'",
            'ALTER TABLE client_services DROP CONSTRAINT IF EXISTS client_services_server_id_fkey',
            'ALTER TABLE client_services ADD CONSTRAINT client_services_server_id_fkey FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE SET NULL',
            'ALTER TABLE server_categories DROP CONSTRAINT IF EXISTS server_categories_server_id_fkey',
            'ALTER TABLE server_categories ADD CONSTRAINT server_categories_server_id_fkey FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE SET NULL',
            'ALTER TABLE payment_cards DROP CONSTRAINT IF EXISTS payment_cards_server_id_fkey',
            'ALTER TABLE payment_cards ADD CONSTRAINT payment_cards_server_id_fkey FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE SET NULL',
            'ALTER TABLE reseller_accounts ALTER COLUMN server_id DROP NOT NULL',
            'ALTER TABLE reseller_build_configs ALTER COLUMN server_id DROP NOT NULL',
            'ALTER TABLE anti_sharing_violations ALTER COLUMN server_id DROP NOT NULL',
            'ALTER TABLE reseller_packages ALTER COLUMN server_id DROP NOT NULL',
            'ALTER TABLE reseller_topup_requests ALTER COLUMN package_id DROP NOT NULL',
            'ALTER TABLE reseller_topup_requests DROP CONSTRAINT IF EXISTS reseller_topup_requests_package_id_fkey',
            'ALTER TABLE reseller_topup_requests ADD CONSTRAINT reseller_topup_requests_package_id_fkey FOREIGN KEY (package_id) REFERENCES reseller_packages(id) ON DELETE SET NULL',
            'ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_code VARCHAR(64)',
            'CREATE UNIQUE INDEX IF NOT EXISTS ix_users_referral_code ON users(referral_code)',
            'ALTER TABLE users ADD COLUMN IF NOT EXISTS referred_by_user_id INTEGER',
            'ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_joined_at TIMESTAMP',
            'ALTER TABLE users DROP CONSTRAINT IF EXISTS users_referred_by_user_id_fkey',
            'ALTER TABLE users ADD CONSTRAINT users_referred_by_user_id_fkey FOREIGN KEY (referred_by_user_id) REFERENCES users(id) ON DELETE SET NULL',
            'ALTER TABLE reseller_packages DROP CONSTRAINT IF EXISTS reseller_packages_server_id_fkey',
            'ALTER TABLE reseller_packages ADD CONSTRAINT reseller_packages_server_id_fkey FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE SET NULL',
            'ALTER TABLE reseller_build_configs DROP CONSTRAINT IF EXISTS reseller_build_configs_server_id_fkey',
            'ALTER TABLE reseller_build_configs ADD CONSTRAINT reseller_build_configs_server_id_fkey FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE SET NULL',
            'ALTER TABLE reseller_accounts DROP CONSTRAINT IF EXISTS reseller_accounts_server_id_fkey',
            'ALTER TABLE reseller_accounts ADD CONSTRAINT reseller_accounts_server_id_fkey FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE SET NULL',
            'ALTER TABLE anti_sharing_violations DROP CONSTRAINT IF EXISTS anti_sharing_violations_server_id_fkey',
            'ALTER TABLE anti_sharing_violations ADD CONSTRAINT anti_sharing_violations_server_id_fkey FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE SET NULL',
        ]:
            await safe_upgrade(conn, sql)
    # Database must stay fully raw. No default settings, servers, plans, cards, or users are seeded.

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
        service.xui_uuid = (str(created.get('uuid')) if isinstance(created, dict) and created.get('uuid') is not None else None)
    elif server.server_type == 'mikrotik':
        created = await MikroTikService().create_user_on_plan(server, plan, username)
        service.sub_link = None
        service.xui_uuid = str(created.get('password') or '')
    return service, sub_link

@app.post('/webhooks/nowpayments')
async def nowpayments_ipn(request: Request, x_nowpayments_sig: str | None = Header(default=None)):
    raw = await request.body()
    if not settings.NOWPAYMENTS_IPN_SECRET:
        raise HTTPException(status_code=503, detail='NOWPayments IPN secret is not configured')
    if not x_nowpayments_sig or not NowPaymentsService.verify_ipn(raw, x_nowpayments_sig):
        raise HTTPException(status_code=401, detail='invalid signature')
    data = await request.json()
    order_id = str(data.get('order_id') or '')
    payment_id = str(data.get('payment_id') or '')
    status = str(data.get('payment_status') or '').lower()
    if not order_id.isdigit():
        return {'ok': True, 'ignored': 'missing order_id'}
    if status not in {'finished', 'confirmed', 'sending'}:
        return {'ok': True, 'status': status}
    if not payment_id:
        raise HTTPException(status_code=400, detail='missing payment_id')

    bot = Bot(token=settings.BOT_TOKEN)
    try:
        async with SessionLocal() as session:
            order = await session.get(Order, int(order_id))
            if not order or order.status == 'paid':
                return {'ok': True, 'status': 'already_processed'}
            if payment_id and order.external_payment_id and str(order.external_payment_id) != payment_id:
                raise HTTPException(status_code=400, detail='payment_id mismatch')
            verifier = NowPaymentsService()
            details = await verifier.get_payment(payment_id)
            NowPaymentsService.validate_payment_details(details, order_id=order.id, payment_id=payment_id, amount_irt=order.amount_irt)
            user = await session.get(User, order.user_id)
            plan = await session.get(Plan, order.plan_id)
            if not user or not plan:
                raise HTTPException(status_code=400, detail='order data is incomplete')
            server = await session.get(Server, plan.server_id)
            if not server:
                raise HTTPException(status_code=400, detail='order server is missing')
            username = order.payment_method.split(':', 1)[1].split(':discount:', 1)[0] if order.payment_method and order.payment_method.startswith('crypto:') else f'user{user.telegram_id}_{order.id}'
            service, sub_link = await _build_service(session, user, server, plan, username)
            order.status = 'paid'
            order.external_payment_id = payment_id
            order.service_id = service.id
            await apply_purchase_commission(session, user, int(order.amount_irt or 0), bot, server.server_type)
            await session.commit()
        await send_service_card(bot, int(user.telegram_id), service.client_username, plan.title, plan.volume_gb, plan.duration_days, sub_link, is_test=False, service_id=service.id, server_type=server.server_type, password=(service.xui_uuid if server.server_type == 'mikrotik' else None))
        await _send_home(bot, int(user.telegram_id))
    finally:
        await bot.session.close()
    return {'ok': True, 'status': 'processed'}

