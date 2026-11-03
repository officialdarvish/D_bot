"""Customer-only Mini App API, independent of admin cookies and credentials."""
import asyncio
import io
import logging
from contextlib import asynccontextmanager
from datetime import datetime

import qrcode
from aiogram import Bot
from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.config import settings
from app.database.session import SessionLocal
from app.database.models import User, ClientService, Plan, Server, Order, ResellerAccount, PasarGuardPanelOrder
from app.database.defaults import get_setting_value
from app.bot.keyboards.common import get_user_button
from app.services.miniapp_auth import validate_init_data
from app.services.miniapp_settings import read_config
from app.services.miniapp_catalog import public_plans
from app.services.live_pricing import plan_price_label
from app.services.telegram_connection import get_connection_config, prepare_runtime_connection, build_telegram_session

router = APIRouter(prefix='/api/miniapp', tags=['Telegram Mini App'])


@asynccontextmanager
async def telegram_bot():
    runtime = await prepare_runtime_connection(await get_connection_config(include_secrets=True))
    bot = None
    try:
        bot = Bot(token=settings.BOT_TOKEN, session=await build_telegram_session(runtime))
        yield bot
    finally:
        if bot is not None:
            await bot.session.close()
        await runtime.close()


async def customer(response: Response, x_telegram_init_data: str = Header(default='')):
    response.headers['Cache-Control'] = 'no-store, private'
    try:
        identity = validate_init_data(x_telegram_init_data, settings.BOT_TOKEN)
    except (ValueError, TypeError, KeyError):
        raise HTTPException(401, 'نشست تلگرام معتبر نیست؛ مینی‌اپ را دوباره از ربات باز کنید.')
    async with SessionLocal() as session:
        user = (await session.execute(select(User).where(User.telegram_id == identity['id']))).scalar_one_or_none()
        config = await read_config(session)
    if not config['enabled']:
        raise HTTPException(403, 'مینی‌اپ در حال حاضر غیرفعال است.')
    if not user:
        raise HTTPException(403, 'ابتدا /start را در ربات بزنید.')
    if user.is_blocked:
        raise HTTPException(403, 'حساب شما مسدود شده است.')
    if await get_setting_value('bot_enabled', '1') != '1' and user.telegram_id not in settings.admin_ids:
        raise HTTPException(403, 'ربات در حال حاضر غیرفعال است.')
    if await get_setting_value('rules_enabled', '0') == '1' and not user.accepted_rules:
        raise HTTPException(403, 'ابتدا قوانین را در ربات تایید کنید.')
    # Membership is rechecked server-side, just as it is in /start.
    if await get_setting_value('force_join_enabled', '0') == '1':
        from app.bot.handlers.start import check_channel_join
        try:
            async with telegram_bot() as bot:
                ok, _, _ = await check_channel_join(bot, user.telegram_id)
        except Exception:
            raise HTTPException(503, 'بررسی عضویت انجام نشد؛ دوباره تلاش کنید.')
        if not ok:
            raise HTTPException(403, 'ابتدا عضویت کانال را در ربات تایید کنید.')
    return user


async def require_button(name):
    option = {'buy': 'show_buy', 'account': 'show_wallet', 'wallet_topup': 'show_wallet', 'my_services': 'show_services'}.get(name)
    if option:
        async with SessionLocal() as session:
            config = await read_config(session)
        if not config[option]:
            raise HTTPException(403, 'این بخش در مینی‌اپ غیرفعال است.')
    if not (await get_user_button(name))[1]:
        raise HTTPException(403, 'این بخش توسط مدیریت غیرفعال شده است.')


async def owned_service(session, user, sid):
    service = (await session.execute(select(ClientService).where(
        ClientService.id == sid, ClientService.user_id == user.id, ClientService.reseller_id.is_(None)
    ))).scalar_one_or_none()
    from app.services.service_grace import visible_in_my_services
    if service is None or not visible_in_my_services(service):
        raise HTTPException(404, 'اشتراک پیدا نشد.')
    return service


def service_data(svc, plan, server):
    total, used = int(svc.total_bytes or 0), int(svc.used_bytes or 0)
    unlimited = bool(plan and plan.is_unlimited) or total == 0
    active = bool(svc.is_active and (not svc.expires_at or svc.expires_at > datetime.utcnow()) and (not total or used < total))
    result = dict(source='reseller' if getattr(svc,'reseller_id',None) else 'public', source_label='نمایندگی' if getattr(svc,'reseller_id',None) else 'خرید عمومی', id=svc.id, username=svc.client_username, title=plan.title if plan else svc.client_username,
                server=server.display_name if hasattr(server, 'display_name') and server.display_name else (server.name if server else ''),
                provider=server.server_type if server else '', total_bytes=total, used_bytes=used,
                remaining_bytes=None if unlimited else max(total-used, 0), unlimited=unlimited, active=active,
                expires_at=svc.expires_at.isoformat()+'Z' if svc.expires_at else None,
                created_at=svc.created_at.isoformat()+'Z' if svc.created_at else None)
    if server and server.server_type=='mikrotik':
        result['password']=svc.xui_uuid or ''
        result['connection_server']=(server.meta or {}).get('l2tp_server') or ''
        result['ipsec_secret']=(server.meta or {}).get('l2tp_ipsec_secret') or ''
    return result


async def panel_wallet_theme(session,user):
    from app.database.models import Setting
    import secrets
    key=f'panel_wallet_theme:{user.id}'
    row=await session.get(Setting,key)
    if row and row.value in {'red','black','green','purple','blue'}:return row.value
    await session.get(User,user.id,with_for_update=True)
    row=await session.get(Setting,key,populate_existing=True)
    if row and row.value in {'red','black','green','purple','blue'}:return row.value
    theme=secrets.choice(['red','black','green','purple','blue'])
    if row:row.value=theme
    else:session.add(Setting(key=key,value=theme))
    await session.commit()
    return theme


async def panel_snapshot(session,user):
    from app.database.models import PasarGuardPanelOrder,PasarGuardPanelMeter
    from app.services.pasarguard_panel_sales import login_url
    rows=(await session.execute(select(PasarGuardPanelOrder,Server,PasarGuardPanelMeter)
        .join(Server,Server.id==PasarGuardPanelOrder.server_id)
        .outerjoin(PasarGuardPanelMeter,PasarGuardPanelMeter.order_id==PasarGuardPanelOrder.id)
        .where(PasarGuardPanelOrder.user_id==user.id,PasarGuardPanelOrder.status.in_(['approved','delivery_pending']))
        .order_by(PasarGuardPanelOrder.id.desc()))).all()
    result=[]
    from app.services.reseller_management import profile
    finance=await profile(session,f'panels:{user.id}')
    current=await session.get(User,user.id)
    theme=await panel_wallet_theme(session,user) if rows else 'blue'
    for panel,server,meter in rows:
        try:url=login_url(server)
        except (ValueError,RuntimeError):url=''
        result.append(dict(theme=theme,holder=user.full_name or user.username or str(user.telegram_id),id=panel.id,username=panel.username,server=server.name,login_url=url,
            billing_mode=finance.get('billing_mode','payg'),available_bytes=int(finance.get('available_bytes',0)),transition=finance.get('transition'),balance=int(current.wallet_balance or 0),suspended=bool(finance.get('billing_mode','payg')=='payg' and meter and meter.suspended),
            traffic_bytes=int(meter.traffic_bytes or 0) if meter else 0,billable_seconds=int(meter.billable_seconds or 0) if meter else 0,
            charged=int(meter.total_charged_irt or 0) if meter else 0,
            gb_price=int(meter.gb_price_irt or 0) if meter else panel.payg_gb_price_irt,
            hourly_price=int(meter.hourly_price_irt or 0) if meter else panel.payg_hourly_price_irt,
            max_users=(sum(1 for key in finance.get('allocations',{}) if key.startswith(f'panel:{panel.id}:'))+max(0,int(finance.get('available_bytes',0)))//1024**3) if finance.get('billing_mode')=='volume' else int(meter.max_users or 0) if meter else panel.payg_max_users,
            active=bool(server.is_active and not finance.get('transition') and (finance.get('billing_mode')=='volume' or not (meter and meter.suspended))),meter_ready=bool(meter)))
    return result


@router.get('/session')
async def snapshot(user=Depends(customer)):
    names = ('buy', 'my_services', 'wallet_topup', 'account', 'tickets', 'convert', 'test_account', 'reseller_request', 'panel_sales')
    buttons = {name: (await get_user_button(name))[1] for name in names}
    buttons['test_account']=buttons['test_account'] and await get_setting_value('test_account_enabled','1')=='1' and await get_setting_value('test_account_button_visible','1')=='1'
    services, orders = [], []
    async with SessionLocal() as session:
        config = await read_config(session)
        existing_reseller=await session.scalar(select(ResellerAccount.id).where(ResellerAccount.user_id==user.id))
        existing_panel=await session.scalar(select(PasarGuardPanelOrder.id).where(PasarGuardPanelOrder.user_id==user.id,PasarGuardPanelOrder.status.in_(['approved','delivery_pending'])).limit(1))
        buttons['reseller_request']=buttons['reseller_request'] and config['reseller_requests'] and not existing_reseller and not existing_panel
        for flag, option in [('buy','show_buy'),('my_services','show_services'),('account','show_wallet'),('wallet_topup','show_wallet')]:
            buttons[flag] = buttons[flag] and config[option]
        reseller = await reseller_snapshot(session, user) if config['reseller_enabled'] else None
        panels = await panel_snapshot(session,user) if config['reseller_enabled'] else []
        if buttons['my_services']:
            rows = (await session.execute(select(ClientService, Plan, Server)
                .outerjoin(Plan, ClientService.plan_id == Plan.id).outerjoin(Server, ClientService.server_id == Server.id)
                .where(ClientService.user_id == user.id, ClientService.reseller_id.is_(None)).order_by(ClientService.id.desc()))).all()
            from app.services.service_grace import visible_in_my_services
            services = [service_data(s, p, srv) for s, p, srv in rows if visible_in_my_services(s)]
            if config['reseller_enabled']:
                from app.services.miniapp_panel_configs import panel_configurations
                services.extend(await panel_configurations(session, user))
        if buttons['account']:
            from app.api.miniapp_checkout import submitted_order_clause
            rows = (await session.execute(select(Order).where(Order.user_id == user.id,submitted_order_clause()).order_by(Order.id.desc()).limit(20))).scalars().all()
            orders = [dict(id=o.id, amount=int(o.amount_irt or 0), status=o.status, created_at=o.created_at.isoformat()+'Z') for o in rows]
    return dict(config=config, reseller=reseller, panels=panels, user=dict(can_transfer_ownership=user.telegram_id in settings.admin_ids,name=user.full_name or 'دوست عزیز', telegram_id=user.telegram_id, username=user.username,
                         balance=int(user.wallet_balance or 0) if buttons['account'] else None), services=services, orders=orders, buttons=buttons,
                synced_at=datetime.utcnow().isoformat()+'Z')


@router.get('/usage')
async def live_usage(user=Depends(customer)):
    await require_button('my_services')
    from app.services.miniapp_usage import refresh_usage
    async with SessionLocal() as session:
        config = await read_config(session)
    if not config['show_services']:raise HTTPException(403, 'نمایش کانفیگ‌ها غیرفعال است.')
    stale = await refresh_usage(user.id, include_reseller=config['reseller_enabled'])
    result = await snapshot(user)
    for service in [*result['services'], *((result.get('reseller') or {}).get('services') or [])]:
        if service['id'] in stale:service['stale'] = True
    return result


@router.get('/plans')
async def plans(user=Depends(customer)):
    await require_button('buy')
    async with SessionLocal() as session:
        from app.services.miniapp_catalog import public_catalog
        return await public_catalog(session)


async def subscription(user, sid, *, reseller=False):
    if not reseller:
        try:
            await require_button('my_services')
        except HTTPException as exc:
            if exc.status_code != 403:raise
            # A hidden My Configs tab must not block delivery of a completed native purchase.
            async with SessionLocal() as access_session:
                purchase=await access_session.scalar(select(Order.id).where(Order.user_id==user.id,Order.service_id==sid,Order.status=='paid',Order.checkout_key.is_not(None)).limit(1))
            if not purchase:
                from app.database.models import MiniAppOperation
                async with SessionLocal() as trial_session:
                    trials=(await trial_session.execute(select(MiniAppOperation).where(MiniAppOperation.user_id==user.id,MiniAppOperation.kind=='trial',MiniAppOperation.status=='done'))).scalars().all()
                    if not any(sid in (op.result or {}).get('service_ids',[]) for op in trials):raise exc
    async with SessionLocal() as session:
        svc = await reseller_service(session, user, sid) if reseller else await owned_service(session, user, sid)
        plan = await session.get(Plan, svc.plan_id) if svc.plan_id else None
        server = await session.get(Server, svc.server_id) if svc.server_id else None
        from app.services.xui_service import XuiService
        link = await XuiService().resolve_service_subscription(session, server, svc, plan, refresh_happ=True)
        await session.commit()
        link = str(link or '')
        if not link.startswith(('https://', 'http://', 'happ://crypt5/')):
            raise HTTPException(409, 'لینک اشتراک آماده نیست؛ دریافت کانفیگ را در ربات ادامه دهید.')
        return link


@router.get('/services/{sid}/link')
async def service_link(sid: int, user=Depends(customer)):
    link = await subscription(user, sid)
    return dict(link=link, happ_url=link if link.startswith('happ://') else 'happ://add/'+link)


@router.get('/services/{sid}/qr')
async def service_qr(sid: int, user=Depends(customer)):
    link = await subscription(user, sid)
    def render():
        buf = io.BytesIO()
        qrcode.make(link).save(buf, format='PNG')
        return buf.getvalue()
    try:
        data = await asyncio.to_thread(render)
    except Exception:
        raise HTTPException(409, 'این لینک برای QR طولانی است؛ از کپی لینک استفاده کنید.')
    return Response(data, media_type='image/png', headers={'Cache-Control': 'no-store, private'})


class Handoff(BaseModel):
    action: str = Field(max_length=20)
    item_id: int | None = Field(default=None, gt=0)


@router.post('/handoff')
async def handoff(body: Handoff, user=Depends(customer)):
    if body.action.startswith('r') and body.action in RESELLER_ACTIONS:
        async with SessionLocal() as session:
            await reseller_context(session, user, active=body.action != 'rtopup')
            if body.action not in ('rhome','rcreate','rtopup'):
                await reseller_service(session, user, body.item_id)
        return await handoff_url(body.action, body.item_id)
    if body.action == 'support':
        async with SessionLocal() as session:
            config = await read_config(session)
        if not config['show_support'] or not config['support_url']:
            raise HTTPException(404, 'پشتیبانی هنوز تنظیم نشده است.')
        return {'url':config['support_url']}
    flags = {'buy': 'buy', 'renew': 'my_services', 'convert': 'convert', 'service': 'my_services', 'wallet': 'wallet_topup', 'support': 'tickets'}
    if body.action not in flags:
        raise HTTPException(400, 'عملیات نامعتبر است.')
    await require_button(flags[body.action])
    async with SessionLocal() as session:
        if body.action == 'buy':
            if body.item_id not in {p.id for p, _, _ in await public_plans(session)}:
                raise HTTPException(404, 'این پلن در دسترس نیست.')
        elif body.action in ('renew', 'convert', 'service'):
            await require_button('my_services')
            await owned_service(session, user, body.item_id)
    return await handoff_url(body.action, body.item_id)


async def handoff_url(action, item_id):
    payload = 'mini_'+action+(f'_{item_id}' if item_id else '')
    try:
        async with telegram_bot() as bot:
            me = await bot.get_me()
    except Exception:
        logging.getLogger(__name__).exception('Mini App Telegram handoff unavailable')
        raise HTTPException(503, 'ارتباط با تلگرام برقرار نشد؛ دوباره تلاش کنید.')
    return dict(url=f'https://t.me/{me.username}?start={payload}')


RESELLER_ACTIONS = {'rhome','rcreate','rtopup','rmanage','rvol','rdays','rrenew','rdelete','rrevoke'}


async def reseller_context(session, user, *, active=False):
    config = await read_config(session)
    if not config['reseller_enabled']:
        raise HTTPException(403, 'بخش نمایندگی غیرفعال است.')
    account = await session.scalar(select(ResellerAccount).where(ResellerAccount.user_id == user.id))
    if account is None:
        raise HTTPException(403, 'شما دسترسی نمایندگی ندارید.')
    from app.services.reseller_service import is_reseller_access_active
    if active and not is_reseller_access_active(account):
        raise HTTPException(403, 'اعتبار نمایندگی غیرفعال یا منقضی شده است.')
    return account


async def reseller_service(session, user, sid):
    account = await reseller_context(session, user)
    svc = await session.scalar(select(ClientService).where(ClientService.id == sid, ClientService.reseller_id == account.id))
    from app.services.service_grace import visible_in_my_services
    if svc is None or not visible_in_my_services(svc):
        raise HTTPException(404, 'کانفیگ نمایندگی پیدا نشد.')
    return svc


async def reseller_snapshot(session, user):
    from app.services.reseller_service import is_reseller_access_active
    from app.services.service_grace import visible_in_my_services
    account = await session.scalar(select(ResellerAccount).where(ResellerAccount.user_id == user.id))
    if not account: return None
    rows = (await session.execute(select(ClientService, Plan, Server)
        .outerjoin(Plan, ClientService.plan_id == Plan.id).outerjoin(Server, ClientService.server_id == Server.id)
        .where(ClientService.reseller_id == account.id).order_by(ClientService.id.desc()))).all()
    services = [service_data(s,p,srv) for s,p,srv in rows if visible_in_my_services(s)]
    for item in services: item['reseller'] = True
    from app.services.reseller_billing import policy
    assigned=list(account.allowed_server_ids or ([account.server_id] if account.server_id else []))
    servers=(await session.execute(select(Server).where(Server.id.in_(assigned)))).scalars().all() if assigned else []
    from app.services.reseller_management import profile
    finance=await profile(session,f'account:{account.id}')
    tariffs=[dict(server_id=s.id,server_name=s.name,rate_irt_per_gb=int(finance.get('payg_rate') or policy(s)[1])) for s in servers]
    return dict(billing_mode=account.billing_mode or 'volume',wallet_balance_irt=int(account.wallet_balance_irt or 0),
        last_settlement=account.billing_last_run_at.isoformat()+'Z' if account.billing_last_run_at else None,tariffs=tariffs,
        active=is_reseller_access_active(account), available_bytes=int(account.total_bytes or 0),
        reserved_bytes=int(account.reserved_bytes or 0), used_bytes=int(account.used_bytes or 0),
        expires_at=account.expires_at.isoformat()+'Z' if account.expires_at else None, services=services)


@router.get('/reseller')
async def reseller_dashboard(user=Depends(customer)):
    async with SessionLocal() as session:
        await reseller_context(session,user)
        return await reseller_snapshot(session,user)


@router.get('/reseller/services/{sid}/link')
async def reseller_link(sid:int,user=Depends(customer)):
    link=await subscription(user,sid,reseller=True)
    return dict(link=link,happ_url=link if link.startswith('happ://') else 'happ://add/'+link)


@router.get('/reseller/services/{sid}/qr')
async def reseller_qr(sid:int,user=Depends(customer)):
    link=await subscription(user,sid,reseller=True)
    def render():
        buf=io.BytesIO();qrcode.make(link).save(buf,format='PNG');return buf.getvalue()
    try: data=await asyncio.to_thread(render)
    except Exception: raise HTTPException(409,'لینک برای QR طولانی است؛ لینک را کپی کنید.')
    return Response(data,media_type='image/png',headers={'Cache-Control':'no-store, private'})


@router.get('/services/{sid}/profile')
async def service_profile(sid:int,user=Depends(customer)):
    from app.bot.profile_delivery import find_openvpn_profile
    async with SessionLocal() as session:
        svc=await owned_service(session,user,sid)
        server=await session.get(Server,svc.server_id)
        plan=await session.get(Plan,svc.plan_id) if svc.plan_id else None
        profile=await find_openvpn_profile(session,svc,server,plan)
        if not profile or not profile.is_active:raise HTTPException(404,'پروفایل فعالی برای این سرویس ثبت نشده است.')
        content=profile.content or ''
    return Response(content,media_type='application/x-openvpn-profile',headers={'Cache-Control':'no-store, private','Content-Disposition':'attachment; filename="profile.ovpn"'})


@router.get('/panels')
async def purchased_panel_snapshot(user=Depends(customer)):
    async with SessionLocal() as session:
        config=await read_config(session)
        if not config['reseller_enabled']:return {'panels':[]}
        return {'panels':await panel_snapshot(session,user)}
