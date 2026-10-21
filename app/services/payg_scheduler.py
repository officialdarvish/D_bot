"""Cheap database gates for optional PAYG workers; never probes a panel."""
import json
import logging
from datetime import datetime
from sqlalchemy import select,or_,and_
from app.database.models import Server,ResellerAccount,ClientService,ResellerUsageMeter,PasarGuardPanelOrder,PasarGuardPanelMeter,Setting
from app.database.session import SessionLocal

log=logging.getLogger(__name__)

async def _profiles(s,keys):
    if not keys:return {}
    rows=(await s.execute(select(Setting.key,Setting.value).where(Setting.key.in_(keys)))).all()
    return {key:json.loads(value or '{}') for key,value in rows}

async def panel_order_ids(s,mode='payg'):
    rows=(await s.execute(select(PasarGuardPanelOrder.id,PasarGuardPanelOrder.user_id,Server.meta,
        PasarGuardPanelMeter.gb_price_irt,PasarGuardPanelMeter.hourly_price_irt)
        .join(Server,Server.id==PasarGuardPanelOrder.server_id)
        .join(PasarGuardPanelMeter,PasarGuardPanelMeter.order_id==PasarGuardPanelOrder.id)
        .where(PasarGuardPanelOrder.status.in_(['approved','delivery_pending']),Server.is_active.is_(True),Server.server_type=='pasarguard'))).all()
    profiles=await _profiles(s,{f'reseller_finance:panels:{row[1]}' for row in rows})
    from app.services.panel_billing_policy import panel_billing_mode
    return [oid for oid,uid,meta,gb,hour in rows
        if panel_billing_mode(meta,gb,hour,profiles.get(f'reseller_finance:panels:{uid}',{}))==mode]

async def reseller_ids(s):
    rows=(await s.execute(select(ResellerAccount.id,ResellerAccount.server_id,ResellerAccount.allowed_server_ids)
        .where(ResellerAccount.billing_mode=='payg',ResellerAccount.is_active.is_(True),
            or_(ResellerAccount.expires_at.is_(None),ResellerAccount.expires_at>datetime.utcnow())))).all()
    if not rows:return []
    services=(await s.execute(select(ClientService.reseller_id,ClientService.server_id).where(
        ClientService.reseller_id.in_([r[0] for r in rows]),~ClientService.client_username.like('deleted\\_%',escape='\\')).distinct())).all()
    assigned={rid:set(allowed or ([sid] if sid else [])) for rid,sid,allowed in rows}
    for rid,sid in services:
        if sid:assigned[rid].add(sid)
    ids=set().union(*assigned.values())
    if not ids:return []
    servers=(await s.execute(select(Server.id,Server.meta).where(Server.id.in_(ids),Server.is_active.is_(True),Server.server_type.in_(['xui','pasarguard'])))).all()
    from app.services.reseller_billing import policy
    from types import SimpleNamespace
    eligible={sid for sid,meta in servers if 'payg' in policy(SimpleNamespace(meta=meta))[0] and policy(SimpleNamespace(meta=meta))[1]>0}
    profiles=await _profiles(s,{f'reseller_finance:account:{rid}' for rid in assigned})
    return [rid for rid in assigned if assigned[rid]&eligible and not profiles.get(f'reseller_finance:account:{rid}',{}).get('transition')]

async def maintenance_needed(s):
    return bool(await s.scalar(select(ClientService.id).join(Server,Server.id==ClientService.server_id)
        .join(ResellerAccount,ResellerAccount.id==ClientService.reseller_id)
        .outerjoin(ResellerUsageMeter,ResellerUsageMeter.service_id==ClientService.id)
        .where(Server.is_active.is_(True),or_(ClientService.disabled_reason=='mode_switch_manual',ResellerUsageMeter.suspended.is_(True),ResellerUsageMeter.suspension_pending.is_(True),
            and_(ClientService.is_active.is_(True),ResellerAccount.billing_mode=='payg',or_(ResellerAccount.wallet_balance_irt<=0,ResellerAccount.is_active.is_(False),ResellerAccount.expires_at<=datetime.utcnow())))).limit(1)))

async def reconcile_payg_jobs(scheduler):
    async with SessionLocal() as s:
        panel=bool(await panel_order_ids(s,'payg'))
        reseller=bool(await reseller_ids(s))
        volume=bool(await panel_order_ids(s,'volume'))
        maintenance=await maintenance_needed(s)
    desired={'pasarguard_panel_payg':panel,'reseller_payg_billing':reseller,'panel_volume_sync':volume,'reseller_payg_suspension':maintenance}
    for ident,enabled in desired.items():
        job=scheduler.get_job(ident)
        if job is not None and (job.next_run_time is not None)!=enabled:
            scheduler.modify_job(ident,next_run_time=datetime.now(scheduler.timezone) if enabled else None)
            log.info('Optional worker %s %s',ident,'enabled' if enabled else 'paused')
    return desired
