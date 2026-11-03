"""Reseller tariffs and durable, retryable mode changes without replacing users.

Configuration reseller wallets and purchased-dashboard wallets remain separate.
Purchased dashboards sharing a User wallet are switched as one billing family.
"""
import json
import uuid
from datetime import datetime
from sqlalchemy import select
from app.database.models import (Setting,User,Server,ResellerAccount,ClientService,
    PasarGuardPanelOrder,PasarGuardPanelMeter,MiniAppOperation,WalletTransaction,
    ResellerUsageMeter,ResellerServiceActivity)
from app.database.session import SessionLocal
GB=1024**3

async def profile(session,key,lock=False):
    row=await session.get(Setting,'reseller_finance:'+key,with_for_update=lock)
    return json.loads(row.value) if row else {}

async def save_profile(session,key,data):
    row=await session.get(Setting,'reseller_finance:'+key,with_for_update=True)
    if row:row.value=json.dumps(data)
    else:session.add(Setting(key='reseller_finance:'+key,value=json.dumps(data)))
    await session.flush()

async def target(session,kind,ident,lock=False):
    if kind=='account':
        obj=await session.get(ResellerAccount,ident,with_for_update=lock)
        if not obj:raise ValueError('نماینده پیدا نشد.')
        return obj,await session.get(User,obj.user_id),f'account:{obj.id}'
    if kind=='panel':
        obj=await session.get(PasarGuardPanelOrder,ident)
        if not obj or obj.status not in {'approved','delivery_pending'}:raise ValueError('پنل ساخته‌شده پیدا نشد.')
        user=await session.get(User,obj.user_id,with_for_update=lock)
        return obj,user,f'panels:{user.id}'
    raise ValueError('نوع نمایندگی معتبر نیست.')

async def own_rows(session,kind,obj):
    if kind=='account':
        from app.services.reseller_service import sync_reseller_service_panel_snapshot
        services=(await session.execute(select(ClientService).where(ClientService.reseller_id==obj.id))).scalars().all()
        rows=[]
        for svc in services:
            if str(svc.client_username).startswith('deleted_'):continue
            server=await session.get(Server,svc.server_id) if svc.server_id else None
            if not server or server.server_type not in {'xui','pasarguard'}:raise ValueError('تبدیل فقط برای کانفیگ‌های سنایی و PasarGuard پشتیبانی می‌شود.')
            from app.services.pasarguard_service import PasarGuardService
            if server.server_type=='xui':
                from app.services.xui_service import XuiService
                found=await XuiService().find_client_by_identifiers(server,svc.xui_email,svc.client_username,svc.xui_uuid)
                if not found:raise ValueError(f'کانفیگ {svc.client_username} روی پنل پیدا نشد؛ ابتدا همگام‌سازی کنید.')
                remote=found.get('client') or {};traffic=found.get('traffic') or {}
                used=int(traffic.get('up',0) or 0)+int(traffic.get('down',0) or 0)
                username=str(remote.get('email') or svc.xui_email or svc.client_username)
            else:
                remote=await PasarGuardService().get_user(server,svc.xui_email or svc.client_username)
                if not remote:raise ValueError('کانفیگ روی پنل پیدا نشد.')
                used=int(remote.get('used_traffic',0));username=svc.xui_email or svc.client_username
            from app.services.reseller_service import apply_reseller_usage_delta
            await apply_reseller_usage_delta(session,svc,used)
            rows.append(dict(key=f'service:{svc.id}',service_id=svc.id,server_id=server.id,username=username,used=used))
        return rows
    from app.services.pasarguard_panel_meter import PanelMeterAPI
    panels=(await session.execute(select(PasarGuardPanelOrder).where(PasarGuardPanelOrder.user_id==obj.user_id,PasarGuardPanelOrder.status.in_(['approved','delivery_pending'])))).scalars().all()
    rows=[]
    for panel in panels:
        server=await session.get(Server,panel.server_id)
        for remote in await PanelMeterAPI().list_own_users(server,panel):
            rows.append(dict(key=f'panel:{panel.id}:{remote["id"]}',order_id=panel.id,remote_id=remote['id'],server_id=server.id,username=remote['username'],used=int(remote['used_traffic'])))
    return rows

async def snapshot(session,kind,ident,*,live=False,rate=0):
    obj,user,key=await target(session,kind,ident)
    p=await profile(session,key)
    rows=await own_rows(session,kind,obj) if live else []
    mode=obj.billing_mode if kind=='account' else p.get('billing_mode','payg')
    balance=int(obj.wallet_balance_irt or 0) if kind=='account' else int(user.wallet_balance or 0)
    if live and mode=='payg' and kind=='panel':
        await settle_panel_snapshot(session,user,rows,p);balance=int(user.wallet_balance or 0)
    if live and mode=='payg' and kind=='account':
        from app.services.reseller_billing import settle
        await settle(session,obj);balance=int(obj.wallet_balance_irt or 0)
    volume_rate=int(rate or p.get('volume_rate',0))
    purchased=max(0,balance)*GB//volume_rate if volume_rate else 0
    return dict(ok=True,kind=kind,id=ident,billing_mode=mode,balance=balance,
        volume_rate=volume_rate,payg_rate=p.get('payg_rate',0),hourly_rate=p.get('hourly_rate',0),
        available_bytes=int(obj.total_bytes or 0) if kind=='account' else int(p.get('available_bytes',0)),
        transition=p.get('transition'),services=rows,count=len(rows),converted_bytes=purchased,
        reserved_bytes=len(rows)*GB,remaining_bytes=purchased-len(rows)*GB,
        scope='همه پنل‌های خریداری‌شده با کیف پول مشترک' if kind=='panel' else 'حساب نمایندگی ساخت کانفیگ')

async def freeze_remote(session,row,quota=GB,*,enabled=False,expire_at=None):
    server=await session.get(Server,row['server_id'])
    if not server:raise ValueError('سرور پیدا نشد.')
    if server.server_type=='xui':
        from app.services.xui_service import XuiService
        await XuiService().set_client_quota(server,row['username'],quota,enabled,expire_at=expire_at)
    elif server.server_type=='pasarguard':
        from app.services.pasarguard_service import PasarGuardService
        # Every panel row was resolved from an ownership-verified list. Recheck
        # ownership before replaying a durable remote operation.
        if row.get('order_id'):
            panel=await session.get(PasarGuardPanelOrder,row['order_id'])
            remote=await PasarGuardService().get_user(server,row['username'])
            if int((remote.get('admin') or {}).get('id') or 0)!=int(panel.admin_id or 0):raise ValueError('مالکیت کانفیگ پنل تغییر کرده است.')
        await PasarGuardService().update_user(server,row['username'],data_limit_bytes=quota,status='active' if enabled else 'disabled',expire_at=expire_at)
    else:raise ValueError('پنل پشتیبانی نمی‌شود.')

async def save_rates(session,kind,ident,payg_rate,volume_rate,hourly_rate=0):
    if not 1<=payg_rate<=10**9 or not 1<=volume_rate<=10**9 or not 0<=hourly_rate<=10**9:raise ValueError('نرخ هر گیگ باید مثبت و حداکثر یک میلیارد تومان باشد.')
    obj,user,key=await target(session,kind,ident,True);p=await profile(session,key,True)
    if p.get('transition'):raise ValueError('ابتدا تبدیل در حال انجام را تکمیل کنید.')
    if kind=='account':
        from app.services.reseller_billing import settle
        await own_rows(session,kind,obj)
        await settle(session,obj)
        meters=(await session.execute(select(ResellerUsageMeter).where(ResellerUsageMeter.reseller_id==obj.id))).scalars().all()
        for m in meters:m.rate_irt_per_gb=payg_rate
    else:
        panels=(await session.execute(select(PasarGuardPanelOrder).where(PasarGuardPanelOrder.user_id==user.id,PasarGuardPanelOrder.status.in_(['approved','delivery_pending'])))).scalars().all()
        for panel in panels:
            m=await session.scalar(select(PasarGuardPanelMeter).where(PasarGuardPanelMeter.order_id==panel.id).with_for_update())
            if m:
                # Old cumulative charges remain intact; rebase before applying
                # new rates so historical traffic/time is never repriced.
                p.setdefault('tariff_offsets',{})[str(panel.id)]={'traffic':int(m.traffic_bytes),'seconds':int(m.billable_seconds),'due':int(m.billed_traffic_irt)+int(m.billed_hours_irt)}
                m.gb_price_irt=payg_rate;m.hourly_price_irt=hourly_rate
            panel.payg_gb_price_irt=payg_rate;panel.payg_hourly_price_irt=hourly_rate
    p.update(payg_rate=payg_rate,volume_rate=volume_rate,hourly_rate=hourly_rate)
    await save_profile(session,key,p)

async def start_switch(kind,ident,mode,rate,key,expected_balance,expected_count):
    if mode not in {'volume','payg'}:raise ValueError('سیستم مالی معتبر نیست.')
    uuid.UUID(key)
    async with SessionLocal() as s:
        obj,user,pk=await target(s,kind,ident,True)
        old=await s.scalar(select(MiniAppOperation).where(MiniAppOperation.key==key))
        if old:
            if old.kind!='reseller_switch' or old.payload.get('target')!=pk or old.payload.get('mode')!=mode:raise ValueError('شناسه عملیات تکراری است.')
            oid=old.id
        else:
            p=await profile(s,pk,True)
            # Billing families may only switch when the other family already
            # uses the destination mode. Never create simultaneous mixed models.
            from app.database.models import PasarGuardPanelOrder,ResellerAccount
            if kind=='account':
                other=await s.scalar(select(PasarGuardPanelOrder.id).where(PasarGuardPanelOrder.user_id==user.id,PasarGuardPanelOrder.status.in_(['pending','processing','approved','delivery_pending','review_required'])).limit(1))
                if other and (await profile(s,f'panels:{user.id}')).get('billing_mode','payg')!=mode:raise ValueError('همه نمایندگی‌های یک کاربر باید یک مدل تعرفه داشته باشند.')
            else:
                other=await s.scalar(select(ResellerAccount).where(ResellerAccount.user_id==user.id))
                if other and other.billing_mode!=mode:raise ValueError('همه نمایندگی‌های یک کاربر باید یک مدل تعرفه داشته باشند.')
            if p.get('transition'):raise ValueError('تبدیل دیگری در حال انجام است؛ همان عملیات را ادامه دهید.')
            from app.database.models import Order,ResellerWalletReceipt,ResellerTopupRequest
            if kind=='account':
                pending=await s.scalar(select(ResellerWalletReceipt.id).where(ResellerWalletReceipt.reseller_id==obj.id,ResellerWalletReceipt.status=='pending').limit(1))
                pending=pending or await s.scalar(select(ResellerTopupRequest.id).where(ResellerTopupRequest.user_id==user.id,ResellerTopupRequest.status=='pending').limit(1))
            else:
                receipts=(await s.execute(select(Order).where(Order.user_id==user.id,Order.status=='waiting_receipt'))).scalars().all()
                pending=any((order.pricing_meta or {}).get('panel_order_id') for order in receipts)
            creating=await s.scalar(select(MiniAppOperation.id).where(MiniAppOperation.user_id==user.id,MiniAppOperation.kind.in_(['panel_create','panel_action']),MiniAppOperation.status.in_(['processing','review'])).limit(1)) if kind=='panel' else None
            if creating:raise ValueError('ابتدا عملیات ساخت کانفیگ پنل را تعیین تکلیف کنید.')
            if pending:raise ValueError('ابتدا رسیدهای شارژ و حجم در انتظار تأیید این نماینده را تعیین تکلیف کنید.')
            current=obj.billing_mode if kind=='account' else p.get('billing_mode','payg')
            if current==mode:raise ValueError('سیستم مالی از قبل همین است.')
            rows=await own_rows(s,kind,obj)
            if kind=='account':
                from app.services.reseller_billing import settle
                await settle(s,obj)
            elif current=='payg':await settle_panel_snapshot(s,user,rows,p)
            balance=int(obj.wallet_balance_irt or 0) if kind=='account' else int(user.wallet_balance or 0)
            if balance!=expected_balance or len(rows)!=expected_count:raise ValueError('موجودی یا تعداد کانفیگ‌ها تغییر کرده؛ پیش‌نمایش را دوباره دریافت کنید.')
            if mode=='volume':
                if not 1<=rate<=10**9:raise ValueError('نرخ حجمی معتبر نیست.')
                if balance<0:raise ValueError('ابتدا بدهی کیف پول را تسویه کنید.')
                if balance*GB//rate<len(rows)*GB:raise ValueError('اعتبار تبدیل‌شده برای سهمیه یک گیگ همه کانفیگ‌ها کافی نیست؛ ابتدا شارژ کنید.')
            if kind=='account':
                servers=(await s.execute(select(Server).where(Server.id.in_(obj.allowed_server_ids or [obj.server_id])))).scalars().all()
                from app.services.reseller_billing import policy
                for server in servers:
                    modes,server_rate=policy(server)
                    if mode not in modes:raise ValueError(f'{server.name}: ابتدا سیستم مقصد را در تنظیمات سرور فعال کنید.')
                    if mode=='payg' and not (p.get('payg_rate') or server_rate):raise ValueError('نرخ PAYG را مشخص کنید.')
            op=MiniAppOperation(user_id=user.id,key=key,kind='reseller_switch',status='processing',payload=dict(target=pk,kind=kind,ident=ident,mode=mode,rate=rate,rows=rows,done=[],was_active=bool(obj.is_active) if kind=='account' else True))
            s.add(op);await s.flush();oid=op.id
            p['transition']=oid
            if kind=='account':obj.is_active=False
            await save_profile(s,pk,p);await s.commit()
    return await run_switch(oid)

async def run_switch(oid):
    async with SessionLocal() as s:
        op=await s.get(MiniAppOperation,oid,with_for_update=True)
        if not op or op.kind!='reseller_switch':raise ValueError('عملیات پیدا نشد.')
        if op.status=='paid':return dict(ok=True,status='paid',id=oid,message='تبدیل قبلاً تکمیل شده است.')
        data=dict(op.payload);kind=data['kind'];mode=data['mode']
        obj,user,pk=await target(s,kind,data['ident'],True);p=await profile(s,pk,True)
        try:
            if kind=='panel' and mode=='volume':await panel_account_limits(s,user.id,data['rows'],hold=True)
            # Persist each success; a crash can replay a quota/disable PUT safely.
            for row in data['rows']:
                if row['key'] in data['done']:continue
                if mode=='volume':await freeze_remote(s,row)
                data['done']=data['done']+[row['key']];op.payload=dict(data);await s.commit()
                # Reacquire the operation lock after each durable checkpoint.
                op=await s.get(MiniAppOperation,oid,with_for_update=True,populate_existing=True)
                if op.status=='paid':return dict(ok=True,status='paid',id=oid)
            obj,user,pk=await target(s,kind,data['ident'],True)
            await s.refresh(obj)
            await s.refresh(user)
            p=await profile(s,pk,True)
            if mode=='volume':
                if kind=='account':
                    await own_rows(s,kind,obj)
                    from app.services.reseller_billing import settle
                    await settle(s,obj)
                else:
                    latest=await own_rows(s,kind,obj)
                    if {r['key'] for r in latest}!={r['key'] for r in data['rows']}:raise ValueError('تعداد کانفیگ‌های پنل تغییر کرده؛ پیش از ادامه، تغییرات مستقیم پنل را متوقف کنید.')
                    await settle_panel_snapshot(s,user,latest,p)
                balance=int(obj.wallet_balance_irt or 0) if kind=='account' else int(user.wallet_balance or 0)
                converted=max(0,balance)*GB//data['rate'];reserved=len(data['rows'])*GB
                if converted<reserved:raise ValueError('اعتبار کافی نیست؛ شارژ کنید و عملیات را ادامه دهید.')
                if kind=='account':
                    from app.services.reseller_billing import credit
                    await credit(s,obj,-balance,key=f'swap:{oid}',kind='volume_swap',note=f'{data["rate"]} Toman / GB')
                    obj.total_bytes=int(obj.total_bytes or 0)+converted-reserved;obj.billing_mode='volume'
                    for row in data['rows']:
                        svc=await s.get(ClientService,row['service_id'])
                        svc.total_bytes=GB;svc.is_active=False;svc.disabled_reason='mode_switch_manual';svc.reseller_reserved_bytes=GB;svc.reseller_reserved_used_baseline=int(svc.used_bytes or 0)
                        m=await s.scalar(select(ResellerUsageMeter).where(ResellerUsageMeter.service_id==svc.id))
                        if m:m.suspended=False;m.suspension_pending=False
                else:
                    user.wallet_balance=int(user.wallet_balance or 0)-balance
                    s.add(WalletTransaction(user_id=user.id,amount_irt=-balance,tx_type='volume_swap',description=f'Panel PAYG to Volume #{oid}, {data["rate"]} Toman/GB'))
                    p['available_bytes']=int(p.get('available_bytes',0))+converted-reserved
                    await panel_account_limits(s,user.id,data['rows'],p['available_bytes'])
                    p['allocations']={r['key']:GB for r in data['rows']};p['quota_limits']={r['key']:GB for r in data['rows']};p['manual_pauses']=[r['key'] for r in data['rows']]
                p['volume_rate']=data['rate'];p['billing_mode']='volume'
            else:
                if kind=='account':
                    from app.services.reseller_billing import configure_mode
                    await configure_mode(s,obj,'payg')
                p['billing_mode']='payg'
                # Prepaid GB stays dormant; money is never minted on reversal.
                if kind=='panel':
                    panels=(await s.execute(select(PasarGuardPanelOrder).where(PasarGuardPanelOrder.user_id==user.id,PasarGuardPanelOrder.status.in_(['approved','delivery_pending'])))).scalars().all()
                    p['payg_baselines']=[str(panel.id) for panel in panels]
                    allocations=p.get('allocations',{});limits=p.get('quota_limits',{})
                    returned=sum(max(0,min(int(allocations.get(row['key'],0)),int(limits.get(row['key'],0))-row['used'])) for row in data['rows'])
                    p['available_bytes']=int(p.get('available_bytes',0))+returned
                    p['allocations']={};p['quota_limits']={}
                    await panel_account_limits(s,user.id,data['rows'],payg=True)
            if kind=='account':obj.is_active=data['was_active']
            p.pop('transition',None);await save_profile(s,pk,p)
            op.status='paid';op.result={'converted_bytes':converted if mode=='volume' else 0,'count':len(data['rows'])};await s.commit()
            return dict(ok=True,status='paid',id=oid,message='تبدیل کامل شد؛ کانفیگ‌ها تا تمدید دستی مدیر غیرفعال هستند.' if mode=='volume' else 'سیستم PAYG فعال شد.')
        except Exception as exc:
            await s.rollback()
            op=await s.get(MiniAppOperation,oid,with_for_update=True);op.result={'error':str(exc)[:500]};await s.commit()
            return dict(ok=True,status='processing',id=oid,message='تبدیل متوقف است؛ پس از رفع خطا، ادامه عملیات را بزنید.',error=str(exc)[:500])

async def poll_volume_panel(order_id):
    """Reconcile direct panel edits against prepaid allocations, scoped to owner."""
    from app.services.pasarguard_panel_meter import PanelMeterAPI
    async with SessionLocal() as s:
        order=await s.get(PasarGuardPanelOrder,order_id)
        if not order or order.status not in {'approved','delivery_pending'}:return {}
        server=await s.get(Server,order.server_id)
        if not server or not server.is_active or server.server_type!='pasarguard':return {}
        p=await profile(s,f'panels:{order.user_id}')
        from app.services.panel_billing_policy import panel_billing_mode
        if panel_billing_mode(server.meta,0,0,p)!='volume':return {}
        rows=await PanelMeterAPI().list_own_users(server,order)
        user=await s.get(User,order.user_id,with_for_update=True)
        pk=f'panels:{user.id}';p=await profile(s,pk,True)
        if p.get('transition') or p.get('billing_mode')!='volume':return {}
        allocations=dict(p.get('allocations',{}));limits=dict(p.get('quota_limits',{}));pauses=set(p.get('manual_pauses',[]));available=int(p.get('available_bytes',0))
        for remote in rows:
            key=f'panel:{order.id}:{remote["id"]}'
            if key in p.get('deleted_allocations',[]):continue
            old=int(allocations.get(key,0))
            wanted=max(GB,int(remote.get('data_limit') or 0))
            row=dict(key=key,order_id=order.id,remote_id=remote['id'],server_id=server.id,username=remote['username'])
            if key in pauses:
                await freeze_remote(s,row,old or GB);continue
            delta=max(0,wanted-int(limits.get(key,old)))
            if delta>available or not remote.get('data_limit'):
                await freeze_remote(s,row,old or GB);continue
            if delta>0:available-=delta;allocations[key]=old+delta;limits[key]=wanted
        await panel_account_limits(s,user.id,[dict(order_id=order.id) for r in rows],available,only_order=order.id)
        p['available_bytes']=available;p['allocations']=allocations;p['quota_limits']=limits;await save_profile(s,pk,p);await s.commit()
        return dict(mode='volume',available_bytes=available)

async def settle_panel_snapshot(session,user,rows,p):
    """Close verified traffic/time at old tariffs before converting their wallet."""
    from app.services.pasarguard_panel_meter import price_for_usage
    panels=(await session.execute(select(PasarGuardPanelOrder).where(PasarGuardPanelOrder.user_id==user.id,PasarGuardPanelOrder.status.in_(['approved','delivery_pending'])))).scalars().all()
    now=datetime.utcnow()
    for panel in panels:
        m=await session.scalar(select(PasarGuardPanelMeter).where(PasarGuardPanelMeter.order_id==panel.id).with_for_update())
        if not m:raise ValueError('حساب مصرف پنل آماده نیست؛ ابتدا همگام‌سازی کنید.')
        offsets=dict(m.usage_offsets or {});delta=0
        for row in rows:
            if row.get('order_id')!=panel.id:continue
            current=row['used'];previous=int(offsets.get(str(row['remote_id']),0))
            delta+=current-previous if current>=previous else current;offsets[str(row['remote_id'])]=current
        m.usage_offsets=offsets;m.traffic_bytes+=delta
        if not m.suspended:m.billable_seconds+=max(0,int((now-m.last_meter_at).total_seconds()))
        m.last_meter_at=max(now,m.last_meter_at)
        base=(p.get('tariff_offsets') or {}).get(str(panel.id),{})
        traffic,hours=price_for_usage(max(0,m.traffic_bytes-int(base.get('traffic',0))),max(0,m.billable_seconds-int(base.get('seconds',0))),m.gb_price_irt,m.hourly_price_irt)
        m.billed_traffic_irt=traffic+int(base.get('due',0));m.billed_hours_irt=hours
        debt=max(0,m.billed_traffic_irt+m.billed_hours_irt-m.total_charged_irt)
        paid=min(debt,max(0,int(user.wallet_balance or 0)))
        user.wallet_balance=int(user.wallet_balance or 0)-paid;m.total_charged_irt+=paid
        if paid:session.add(WalletTransaction(user_id=user.id,amount_irt=-paid,tx_type='debit',description=f'Panel settlement before mode change #{panel.id}'))
        if paid<debt:raise ValueError('ابتدا بدهی مصرف پنل را شارژ و تسویه کنید.')
    await session.flush()

async def panel_account_limits(session,user_id,rows,available_bytes=0,*,hold=False,only_order=None,payg=False):
    """Preserve unrelated permission overrides; constrain verified sub-admins only."""
    from app.services.pasarguard_service import PasarGuardService
    provider=PasarGuardService()
    panels=(await session.execute(select(PasarGuardPanelOrder).where(PasarGuardPanelOrder.user_id==user_id,PasarGuardPanelOrder.status.in_(['approved','delivery_pending'])))).scalars().all()
    for panel in panels:
        if only_order is not None and panel.id!=only_order:continue
        server=await session.get(Server,panel.server_id)
        data=await provider._request(server,'GET','/api/admins',params={'username':panel.username,'limit':100})
        matches=[r for r in data.get('admins',[]) if r.get('username')==panel.username and int(r.get('id') or 0)==int(panel.admin_id or 0)]
        if len(matches)!=1:raise ValueError('شناسه نماینده روی پنل تأیید نشد.')
        count=sum(1 for r in rows if r.get('order_id')==panel.id)
        maximum=int(panel.payg_max_users or 0) if payg else count+(0 if hold else max(0,available_bytes)//GB)
        overrides={**(matches[0].get('permission_overrides') or {}),'max_users':maximum if payg else max(1,maximum)}
        await provider._request(server,'PUT',f'/api/admin/by-id/{panel.admin_id}',json={'permission_overrides':overrides,'status':'active' if payg or maximum>0 else 'disabled'})

async def quote_package(session,account,package,*,force_refresh=False):
    from app.services.live_pricing import PriceQuote,quote_plan
    p=await profile(session,f'account:{account.id}') if account else {}
    rate=int(p.get('volume_rate',0))
    if rate>0:return PriceQuote(currency='IRT',amount_irt=rate*int(package.volume_gb),source='reseller_volume_tariff')
    return await quote_plan(package,force_refresh=force_refresh)
