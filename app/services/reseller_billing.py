"""Reseller PAYG ledger. Amounts are Toman; a billing GB is 1024**3 bytes.

Positive ledger amounts credit the independent reseller wallet. Every debit,
usage checkpoint and fractional carry commit together under the account lock.
"""
import logging
import asyncio
from datetime import datetime, timedelta
from sqlalchemy import select, func, or_
from app.database.models import ResellerAccount, ResellerUsageMeter, ResellerBillingEntry, ClientService, Server
from app.database.session import SessionLocal

GB=1024**3
MODES={'volume','payg'}
log=logging.getLogger(__name__)


def is_payg(account):
    return getattr(account,'billing_mode','volume')=='payg'


def policy(server):
    meta=getattr(server,'meta',None) or {}
    raw=meta.get('reseller_billing_modes',['volume'])
    if isinstance(raw,str):raw=raw.split(',')
    modes=[x for x in raw if x in MODES]
    return modes,int(meta.get('reseller_payg_rate_irt',0) or 0)


def validate_policy(modes,rate,provider):
    if isinstance(modes,str):modes=[x.strip() for x in modes.split(',') if x.strip()]
    if not modes or any(x not in MODES for x in modes):raise ValueError('Select Volume, PAYG or both.')
    if 'payg' in modes and provider not in {'xui','pasarguard'}:raise ValueError('PAYG requires X-UI or PasarGuard traffic counters.')
    if 'payg' in modes and not 1<=int(rate)<=10**9:raise ValueError('Enter a positive PAYG price per GB in Toman.')
    return {'reseller_billing_modes':list(dict.fromkeys(modes)),'reseller_payg_rate_irt':max(0,int(rate))}


def server_allows(account,server):
    modes,rate=policy(server)
    return getattr(account,'billing_mode','volume') in modes and (not is_payg(account) or rate>0)


async def rate_for(session,account,server):
    from app.services.reseller_management import profile
    settings=await profile(session,f'account:{account.id}')
    return int(settings.get('payg_rate') or policy(server)[1])


def capacity_bytes(account):
    # PAYG quotas on individual configs are safety limits, not prepaid inventory.
    if is_payg(account):return (10**6*GB) if int(account.wallet_balance_irt or 0)>0 else 0
    return max(0,int(account.total_bytes or 0))


def lifetime(service):
    return max(int(service.reseller_lifetime_used_bytes or 0),int(service.used_bytes or 0))


async def credit(session,account,amount,*,key,note='',kind='topup'):
    existing=await session.scalar(select(ResellerBillingEntry).where(ResellerBillingEntry.event_key==key))
    if existing:return False
    if abs(int(amount))>10**12:raise ValueError('Wallet adjustment is too large.')
    account.wallet_balance_irt=int(account.wallet_balance_irt or 0)+int(amount)
    session.add(ResellerBillingEntry(reseller_id=account.id,event_key=key,kind=kind,amount_irt=int(amount),
        balance_after_irt=account.wallet_balance_irt,note=note))
    await session.flush()
    return True


async def meter_for(session,account,svc,*,baseline=False):
    meter=await session.scalar(select(ResellerUsageMeter).where(ResellerUsageMeter.service_id==svc.id))
    if not meter:
        server=await session.get(Server,svc.server_id) if svc.server_id else None
        rate=await rate_for(session,account,server)
        meter=ResellerUsageMeter(reseller_id=account.id,service_id=svc.id,server_id=svc.server_id,
            checkpoint_bytes=lifetime(svc) if baseline else 0,remainder=0,rate_irt_per_gb=rate)
        session.add(meter);await session.flush()
    return meter


async def settle(session,account,*,now=None,active_servers_only=False):
    """Caller holds reseller FOR UPDATE. Never clamps debt or resets checkpoints."""
    if not is_payg(account):return {'cost':0,'bytes':0}
    now=now or datetime.utcnow();cost=traffic=0
    query=select(ClientService).where(ClientService.reseller_id==account.id)
    if active_servers_only:query=query.join(Server,Server.id==ClientService.server_id).where(Server.is_active.is_(True))
    services=(await session.execute(query)).scalars().all()
    for svc in services:
        meter=await meter_for(session,account,svc)
        current=lifetime(svc);delta=max(0,current-int(meter.checkpoint_bytes or 0))
        if not delta:continue
        server=await session.get(Server,svc.server_id) if svc.server_id else None
        current_rate=await rate_for(session,account,server)
        rate=int(meter.rate_irt_per_gb or current_rate)
        if rate<=0:
            meter.last_error='PAYG rate is not configured';continue
        amount,remainder=divmod(delta*rate+int(meter.remainder or 0),GB)
        key=f'usage:{meter.id}:{current}'
        existing=await session.scalar(select(ResellerBillingEntry.id).where(ResellerBillingEntry.event_key==key))
        if existing:continue
        account.wallet_balance_irt=int(account.wallet_balance_irt or 0)-amount
        session.add(ResellerBillingEntry(reseller_id=account.id,server_id=svc.server_id,service_id=svc.id,event_key=key,
            kind='usage',amount_irt=-amount,balance_after_irt=account.wallet_balance_irt,usage_bytes=delta,rate_irt_per_gb=rate,
            note='PAYG traffic settlement',created_at=now))
        meter.checkpoint_bytes=current;meter.remainder=remainder;meter.rate_irt_per_gb=current_rate or rate
        meter.last_billed_at=now;cost+=amount;traffic+=delta
    account.billing_last_run_at=now
    await session.flush()
    return {'cost':cost,'bytes':traffic}


async def configure_mode(session,account,mode):
    if mode not in MODES:raise ValueError('Invalid reseller billing mode.')
    services=(await session.execute(select(ClientService).where(ClientService.reseller_id==account.id))).scalars().all()
    ids=list(set(account.allowed_server_ids or ([account.server_id] if account.server_id else [])) | {s.server_id for s in services if s.server_id and not str(s.client_username).startswith('deleted_')})
    servers=(await session.execute(select(Server).where(Server.id.in_(ids)))).scalars().all() if ids else []
    for server in servers:
        modes,rate=policy(server)
        if mode not in modes or (mode=='payg' and rate<=0):raise ValueError(f'{server.name}: enable {mode} and its tariff in server financial settings first.')
    old=getattr(account,'billing_mode','volume') or 'volume'
    if old==mode:return
    if old=='payg':
        await settle(session,account)
        if int(account.wallet_balance_irt or 0)<0:raise ValueError('Clear the PAYG wallet debt before switching to Volume.')
        usable=[s for s in services if not str(s.client_username).startswith('deleted_') and (not s.expires_at or s.expires_at>datetime.utcnow())]
        required=sum(max(0,int(s.total_bytes or 0)-int(s.used_bytes or 0)) for s in usable)
        if required>int(account.total_bytes or 0):raise ValueError('Prepaid GB balance is insufficient to fund the remaining quota of existing users.')
        account.total_bytes=int(account.total_bytes or 0)-required
        for svc in usable:
            svc.reseller_reserved_bytes=max(0,int(svc.total_bytes or 0)-int(svc.used_bytes or 0))
            svc.reseller_reserved_used_baseline=int(svc.used_bytes or 0)
    else:
        # Preserve unused prepaid entitlements in the dormant GB pool.
        for svc in services:
            if str(svc.client_username).startswith('deleted_'):
                meter=await meter_for(session,account,svc,baseline=True)
                meter.checkpoint_bytes=lifetime(svc)
                continue
            allocated=int(svc.reseller_reserved_bytes or svc.total_bytes or 0)
            used=max(0,int(svc.used_bytes or 0)-int(svc.reseller_reserved_used_baseline or 0))
            account.total_bytes=int(account.total_bytes or 0)+max(0,allocated-used)
            svc.reseller_reserved_bytes=0
            meter=await meter_for(session,account,svc,baseline=True)
            meter.checkpoint_bytes=lifetime(svc)
    account.billing_mode=mode
    account.billing_last_run_at=datetime.utcnow()
    await session.flush()


async def set_remote(server,svc,enabled):
    if server.server_type=='xui':
        from app.services.xui_service import XuiService
        await XuiService().set_client_enabled(server,svc.xui_email or svc.client_username,enabled)
    elif server.server_type=='pasarguard':
        from app.services.pasarguard_service import PasarGuardService
        await PasarGuardService().set_enabled(server,svc.xui_email or svc.client_username,enabled)
    else:raise ValueError('Unsupported PAYG provider')


async def _reconcile_suspensions():
    """Retry only billing-owned pauses; never re-enable an unrelated manual pause."""
    async with SessionLocal() as session:
        ids=(await session.execute(select(ResellerAccount.id).where(or_(ResellerAccount.billing_mode=='payg',ResellerAccount.id.in_(select(ClientService.reseller_id).where(ClientService.disabled_reason=='mode_switch_manual')), ResellerAccount.id.in_(select(ResellerUsageMeter.reseller_id).where(or_(ResellerUsageMeter.suspended.is_(True),ResellerUsageMeter.suspension_pending.is_(True)))))))).scalars().all()
    for rid in ids:
        try:
            async with SessionLocal() as session:
                account=await session.get(ResellerAccount,rid,with_for_update=True)
                if not account:continue
                from app.services.reseller_management import profile
                if (await profile(session,f'account:{rid}')).get('transition'):continue
                rows=(await session.execute(select(ClientService).join(Server,Server.id==ClientService.server_id).where(ClientService.reseller_id==rid,Server.is_active.is_(True)))).scalars().all()
                for svc in rows:
                    if str(svc.client_username).startswith('deleted_'):continue
                    if svc.disabled_reason=='mode_switch_manual':
                        server=await session.get(Server,svc.server_id)
                        try:
                            if server:await set_remote(server,svc,False)
                            svc.is_active=False
                        except Exception:log.exception('Mode switch manual pause failed service=%s',svc.id)
                        continue
                    meter=await meter_for(session,account,svc)
                    server=await session.get(Server,svc.server_id) if svc.server_id else None
                    invalid=not server or not server_allows(account,server)
                    must_pause=(is_payg(account) and int(account.wallet_balance_irt or 0)<=0) or not account.is_active or (account.expires_at and account.expires_at<=datetime.utcnow()) or invalid
                    if must_pause and (svc.is_active or meter.suspension_pending):
                        meter.suspension_pending=True;await session.commit()
                        try:
                            if not server:raise ValueError('Service server is missing')
                            await set_remote(server,svc,False)
                            svc.is_active=False;svc.disabled_reason='billing_credit';meter.suspended=True;meter.suspension_pending=False;meter.last_error=None
                        except Exception as exc:meter.last_error=str(exc)[:500]
                    elif not must_pause and meter.suspended:
                        if (svc.expires_at and svc.expires_at<=datetime.utcnow()) or (svc.total_bytes and svc.used_bytes>=svc.total_bytes):
                            continue
                        try:
                            await set_remote(server,svc,True);svc.is_active=True;svc.disabled_reason=None
                            meter.suspended=False;meter.suspension_pending=False;meter.last_error=None
                        except Exception as exc:meter.last_error=str(exc)[:500]
                await session.commit()
        except Exception:log.exception('Reseller suspension retry failed id=%s',rid)


async def billing_cycle(bot=None):
    """Catch up on restart, then at most once per reseller per 30 minutes."""
    async with SessionLocal() as s:
        from app.services.payg_scheduler import reseller_ids
        ids=await reseller_ids(s)
    for rid in ids:
        try:
            # Refresh independently; failures leave the last known monotonic usage.
            async with SessionLocal() as s:
                account=await s.get(ResellerAccount,rid)
                from app.services.reseller_management import profile
                if account and (await profile(s,f'account:{rid}')).get('transition'):continue
                if not account or (account.billing_last_run_at and datetime.utcnow()-account.billing_last_run_at<timedelta(minutes=30)):
                    continue
                from app.bot.handlers.public.reseller import sync_all_reseller_services
                await sync_all_reseller_services(s,account,commit=True,active_servers_only=True)
            async with SessionLocal() as s:
                account=await s.get(ResellerAccount,rid,with_for_update=True)
                if not account or not is_payg(account):continue
                from app.services.reseller_management import profile
                if (await profile(s,f'account:{rid}')).get('transition'):continue
                now=datetime.utcnow()
                if account.billing_last_run_at and now-account.billing_last_run_at<timedelta(minutes=30):continue
                result=await settle(s,account,now=now,active_servers_only=True);await s.commit()
                if bot and result['cost']:
                    from app.database.models import User
                    user=await s.get(User,account.user_id)
                    if user:
                        try:await bot.send_message(user.telegram_id,f"💼 تسویه PAYG نمایندگی\nمصرف: {result['bytes']/GB:.3f} گیگ\nهزینه: {result['cost']:,} تومان\nموجودی: {account.wallet_balance_irt:,} تومان")
                        except Exception:log.warning('PAYG notification failed id=%s',rid)
        except Exception:log.exception('Reseller PAYG settlement failed id=%s',rid)
    await reconcile_suspensions()


async def update_server_policy(session,server,modes,rate):
    values=validate_policy(modes,rate,server.server_type)
    # A tariff edit closes known usage at the old rate before new rates apply.
    accounts=(await session.execute(select(ResellerAccount).order_by(ResellerAccount.id).with_for_update())).scalars().all()
    for account in accounts:
        assigned=set(account.allowed_server_ids or ([account.server_id] if account.server_id else []))
        present=await session.scalar(select(ClientService.id).where(ClientService.reseller_id==account.id,ClientService.server_id==server.id,ClientService.is_active.is_(True)).limit(1))
        if server.id not in assigned and not present:continue
        if (account.billing_mode or 'volume') not in values['reseller_billing_modes']:
            raise ValueError('This mode is still used by an assigned reseller. Change that reseller first.')
        if is_payg(account):await settle(session,account)
    server.meta={**(server.meta or {}),**values}
    meters=(await session.execute(select(ResellerUsageMeter).where(ResellerUsageMeter.server_id==server.id))).scalars().all()
    for meter in meters:
        account=await session.get(ResellerAccount,meter.reseller_id)
        meter.rate_irt_per_gb=await rate_for(session,account,server) if account else values['reseller_payg_rate_irt']


_suspension_lock=asyncio.Lock()

async def reconcile_suspensions():
    async with _suspension_lock:
        await _reconcile_suspensions()


async def review_receipt(session,receipt_id,actor,approve):
    from app.database.models import ResellerWalletReceipt, User
    receipt=await session.get(ResellerWalletReceipt,receipt_id,with_for_update=True)
    if not receipt or receipt.status!='pending':return None
    account=await session.get(ResellerAccount,receipt.reseller_id,with_for_update=True)
    if not account:raise ValueError('Reseller account is missing')
    if approve:
        await credit(session,account,receipt.amount_irt,key=f'receipt:{receipt.id}',note=f'Owner {actor} approved receipt',kind='card_topup')
    receipt.status='approved' if approve else 'rejected';receipt.reviewed_by=actor
    user=await session.get(User,account.user_id)
    return receipt,account,user
