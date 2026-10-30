"""Durable, owner-scoped controls for native purchased-panel configurations."""
import uuid
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from app.database.models import User, MiniAppOperation
from app.services.reseller_management import GB, save_profile, profile
from app.services.miniapp_panel_configs import configuration_data

ACTIONS={'delete','hwid','revoke','renew','add_volume','add_days'}

class PanelAction(BaseModel):
    key: uuid.UUID
    action: str
    volume: int=Field(default=1,ge=1,le=1000000)
    days: int=Field(default=30,ge=1,le=3650)
    confirmed: bool=False


def view(op):
    return dict(id=op.id,status=op.status,result=op.result or {},request=op.payload)


def expiry(value):
    if isinstance(value,(int,float)):return datetime.fromtimestamp(value,timezone.utc)
    if isinstance(value,datetime):parsed=value
    elif value:parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
    else:return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


async def execute(pid,oid,body,user):
    from app.api import miniapp_panels as panels
    from app.api.miniapp import require_button
    await require_button('my_services')
    if body.action not in ACTIONS or not body.confirmed:raise HTTPException(422,'عملیات تأییدشده معتبر نیست.')
    request=dict(panel_id=pid,configuration_id=oid,action=body.action)
    if body.action in {'renew','add_volume'}:request['volume']=body.volume
    if body.action in {'renew','add_days'}:request['days']=body.days
    async with panels.SessionLocal() as s:
        await s.get(User,user.id,with_for_update=True)
        prior=await s.scalar(select(MiniAppOperation).where(MiniAppOperation.key==str(body.key)).with_for_update())
        if prior:
            if prior.user_id!=user.id or prior.kind!='panel_action' or prior.payload!=request:raise HTTPException(409,'شناسه عملیات قبلاً استفاده شده است.')
            if prior.status=='done':return view(prior)
            if prior.status=='processing' and (datetime.utcnow()-prior.updated_at).total_seconds()<120:return view(prior)
        creation=await s.get(MiniAppOperation,oid,with_for_update=True)
        if not creation or creation.user_id!=user.id or creation.kind!='panel_create' or creation.status!='done' or creation.payload.get('panel_id')!=pid:
            raise HTTPException(404,'کانفیگ پیدا نشد.')
        if (creation.result or {}).get('deleted'):raise HTTPException(410,'این کانفیگ حذف شده است.')
        panel,server,child,api,current,finance,meter,groups=await panels.context(s,user,pid,lock=True)
        pending=await s.scalar(select(MiniAppOperation.id).where(MiniAppOperation.user_id==user.id,
            MiniAppOperation.kind.in_(['panel_create','panel_action']), MiniAppOperation.status.in_(['processing','review']),
            MiniAppOperation.id!=(prior.id if prior else -1)).limit(1))
        if pending:raise HTTPException(409,'ابتدا عملیات قبلی پنل را بررسی و کامل کنید.')
        name=creation.payload['username'];rid=int(creation.result.get('remote_id') or 0)
        remote=await api.get_user(child,name)
        if remote is None and not(prior and body.action=='delete'):raise HTTPException(404,'کانفیگ روی پنل پیدا نشد.')
        if remote is None and prior and body.action=='delete':
            from app.services.pasarguard_panel_meter import PanelMeterAPI
            rows=await PanelMeterAPI().list_own_users(server,panel)
            if any(int(row.get('id') or 0)==rid for row in rows):raise HTTPException(409,'نام کانفیگ در پنل تغییر کرده است؛ مدیر عملیات را بررسی کند.')
        if remote is not None:
            if int(remote.get('id') or 0)!=rid:raise HTTPException(409,'این نام اکنون متعلق به کانفیگ دیگری است.')
            try:await panels.owned_remote(api,child,server,panel,name,remote)
            except ValueError:raise HTTPException(403,'کانفیگ متعلق به این پنل نیست.')
        allocation=f'panel:{pid}:{rid}';volume_mode=finance.get('billing_mode')=='volume'
        if not prior:
            if body.action in {'revoke','hwid'} and not api.subscription_link(remote):raise HTTPException(409,'لینک فعلی از پنل دریافت نشد؛ دوباره تلاش کنید.')
            if body.action in {'renew','add_volume','add_days'}:
                if allocation in finance.get('manual_pauses',[]):raise HTTPException(409,'این کانفیگ باید ابتدا توسط مدیر تمدید شود.')
                if not volume_mode and (meter.suspended or int(current.wallet_balance or 0)<=0):raise HTTPException(409,'ابتدا کیف پول پنل را شارژ کنید.')
            used=int(remote.get('used_traffic') or remote.get('used_bytes') or 0)
            total=int(remote.get('data_limit') or 0)
            target=dict(remote_id=rid,used=used,total=total,status=remote.get('status'),expires_at=remote.get('expire'),
                before_link=api.subscription_link(remote),before_proxy=remote.get('proxy_settings') or {},
                before_groups=remote.get('group_ids'),before_uuid=remote.get('uuid'),volume_mode=volume_mode,allocation=allocation)
            if body.action in {'renew','add_volume'}:
                if total<=0:raise HTTPException(409,'کانفیگ نامحدود نیازی به افزایش حجم ندارد.')
                added=body.volume*GB;target['total']=total+added
                if volume_mode:
                    available=int(finance.get('available_bytes',0))
                    if added>available:raise HTTPException(409,'حجم پنل برای این عملیات کافی نیست.')
                    finance['available_bytes']=available-added
                    finance.setdefault('allocations',{})[allocation]=int(finance.get('allocations',{}).get(allocation,0))+added
                    finance.setdefault('quota_limits',{})[allocation]=target['total']
                    await save_profile(s,f'panels:{user.id}',finance)
            if body.action in {'renew','add_days'}:
                old=expiry(remote.get('expire'));now=datetime.now(timezone.utc)
                start=now if body.action=='renew' else max(old or now,now)
                target['expires_at']=(start+timedelta(days=body.days)).isoformat()
                if body.action=='renew':target['status']='active'
            op=MiniAppOperation(user_id=user.id,key=str(body.key),kind='panel_action',status='processing',payload=request,
                result=dict(target=target,retryable=True))
            s.add(op)
        else:
            op=prior;target=dict(op.result['target']);op.status='processing'
            if volume_mode!=bool(target['volume_mode']):raise HTTPException(409,'سیستم مالی پنل تغییر کرده است؛ مدیر عملیات را بررسی کند.')
        # Keep the final observed traffic across deletes and same-key retries.
        # Do not reset the usage counter during renewal or quota extension.
        if body.action=='delete' and not volume_mode and remote is not None:
            used=int(remote.get('used_traffic') or remote.get('used_bytes') or 0)
            offsets=dict(meter.usage_offsets or {});before=int(offsets.get(str(rid),0))
            meter.traffic_bytes=int(meter.traffic_bytes or 0)+(used-before if used>=before else used)
            offsets[str(rid)]=used;meter.usage_offsets=offsets
        op.updated_at=datetime.utcnow();await s.commit();action_id=op.id
        try:
            if body.action=='delete':
                if remote is not None:await api.delete_user(child,name)
                if volume_mode:
                    await s.get(User,user.id,with_for_update=True,populate_existing=True)
                    finance=await profile(s,f'panels:{user.id}',True)
                    # Credit only after a confirmed deletion; uncertainty retains
                    # the allocation until this exact operation is resumed.
                    saved=int(finance.get('allocations',{}).get(allocation,0))
                    used=max(target['used'],int((remote or {}).get('used_traffic') or 0))
                    refund=max(0,min(saved,int(finance.get('quota_limits',{}).get(allocation,target['total']))-used))
                    finance['available_bytes']=int(finance.get('available_bytes',0))+refund
                    finance.setdefault('allocations',{}).pop(allocation,None);finance.setdefault('quota_limits',{}).pop(allocation,None)
                    finance['deleted_allocations']=list(set(finance.get('deleted_allocations',[]))|{allocation})
                    finance['manual_pauses']=[k for k in finance.get('manual_pauses',[]) if k!=allocation]
                    await save_profile(s,f'panels:{user.id}',finance)
                creation.result={**creation.result,'deleted':True}
                result=dict(message='کانفیگ حذف شد.',retryable=False)
            else:
                updated={}
                if body.action in {'hwid','revoke'} and panel.role_id:
                    from app.services.pasarguard_panel_sales import PanelResellerProvisioner
                    await PanelResellerProvisioner().ensure_control_permissions(server, int(panel.role_id))
                if body.action=='hwid':
                    # Preserve completed HWID reset across a durable same-key retry.
                    if not op.result.get('hwid_cleared'):
                        await api.clear_user_hwids(child,name)
                        op.result={**op.result,'hwid_cleared':True};await s.commit()
                    if api.subscription_link(remote)==target['before_link']:
                        updated=await api.revoke_subscription(child,name)
                elif body.action=='revoke':
                    # A completed-but-unacknowledged rotation is adopted on retry.
                    if not api.subscription_link(remote) or api.subscription_link(remote)==target['before_link']:
                        updated=await api.revoke_subscription(child,name)
                else:
                    updated=await api.update_user(child,name,
                        data_limit_bytes=target['total'] if body.action in {'renew','add_volume'} else None,
                        expire_at=expiry(target['expires_at']) if body.action in {'renew','add_days'} else None,
                        status=target['status'] if body.action=='renew' else None)
                latest=await api.get_user(child,name)
                if not latest or int(latest.get('id') or 0)!=rid:raise RuntimeError('remote identity changed')
                await panels.owned_remote(api,child,server,panel,name,latest)
                link=api.resolve_subscription_link(child,remote,updated,latest)
                if body.action in {'revoke','hwid'} and (not link or link==target['before_link']):raise RuntimeError('rotation not confirmed')
                if body.action in {'revoke','hwid'}:
                    before=dict(id=rid,subscription_url=target['before_link'],proxy_settings=target.get('before_proxy') or {},uuid=target.get('before_uuid'))
                    if target.get('before_groups') is not None:before['group_ids']=target['before_groups']
                    api.verify_subscription_rotation(child,before,latest)
                if body.action in {'renew','add_volume'} and int(latest.get('data_limit') or 0)!=target['total']:raise RuntimeError('quota not confirmed')
                if body.action in {'renew','add_days'} and expiry(latest.get('expire'))!=expiry(target['expires_at']):raise RuntimeError('expiry not confirmed')
                record=dict(creation.result);record.update(link=link,configuration=dict(total_bytes=int(latest.get('data_limit') or 0),
                    used_bytes=int(latest.get('used_traffic') or 0),expires_at=latest.get('expire'),status=latest.get('status')))
                creation.result=record
                result=dict(message='عملیات با موفقیت انجام شد.',service=configuration_data(creation,panel,server,latest),retryable=False)
            op.status='done';op.result=result;op.updated_at=datetime.utcnow();await s.commit()
            if body.action=='hwid':
                # Delivery failure must not turn a completed rotation into a retry.
                try:
                    from app.bot.service_presenter import send_service_info
                    async with panels.telegram_bot() as bot:
                        await send_service_info(bot,user.telegram_id,name,'کانفیگ پنل نمایندگی',
                            int(latest.get('data_limit') or 0)/GB,creation.payload['days'],link,server_type='pasarguard')
                except Exception:
                    import logging
                    logging.getLogger(__name__).exception('Rotated panel configuration delivery failed action=%s',action_id)
            return view(op)
        except Exception as exc:
            await s.rollback()
            op=await s.get(MiniAppOperation,action_id)
            op.status='review';op.result={**op.result,'retryable':True,'message':'ارتباط کامل نشد؛ بررسی و ادامه عملیات را بزنید. اعتبار رزروشده دوباره کسر نمی‌شود.'}
            await s.commit();await panels.report_failure(exc,action_id,'panel_'+body.action)
            return view(op)
