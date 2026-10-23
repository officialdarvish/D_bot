"""Native Mini App reseller operations and configuration controls."""
import asyncio,logging,uuid
from datetime import datetime,timedelta
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from sqlalchemy import select
from app.api.miniapp import customer,reseller_context,reseller_service,owned_service,service_data,telegram_bot,require_button
from app.database.session import SessionLocal
from app.database.models import User,Server,Plan,ClientService,ResellerAccount,ResellerPackage,MiniAppOperation,ResellerServiceActivity
from app.services.reseller_billing import server_allows,is_payg
from app.services.miniapp_runtime import native_event,NativeState
from app.services.live_pricing import plan_price_label

router=APIRouter(prefix='/api/miniapp',tags=['Mini App native actions'])
log=logging.getLogger(__name__)

class Action(BaseModel):
    key:uuid.UUID
    action:str
    service_id:int|None=Field(default=None,gt=0)
    server_id:int|None=Field(default=None,gt=0)
    username:str=Field(default='',max_length=32)
    volume:float=Field(default=1,gt=0,le=1000000,allow_inf_nan=False)
    days:int=Field(default=30,gt=0,le=3650)
    hwid_limit:int=Field(default=0,ge=0,le=10)
    confirmed:bool=False

async def operation_view(s,op):
    result=dict(op.result or {})
    if result.get('service_id') and op.status=='done':
        svc=await s.get(ClientService,result['service_id'])
        if svc and svc.user_id==op.user_id:
            plan=await s.get(Plan,svc.plan_id) if svc.plan_id else None
            server=await s.get(Server,svc.server_id)
            result['service']={**service_data(svc,plan,server),'reseller':bool(svc.reseller_id)}
    if op.kind=='trial' and op.status=='done':
        services=[]
        for sid in result.get('service_ids',[]):
            svc=await s.get(ClientService,sid)
            if svc and svc.user_id==op.user_id and not svc.reseller_id:
                server=await s.get(Server,svc.server_id)
                services.append({**service_data(svc,None,server),'title':'اکانت تست','source_label':'اکانت تست'})
        result['services']=services
    return dict(id=op.id,kind=op.kind,status=op.status,result=result,created_at=op.created_at.isoformat()+'Z')

@router.get('/operations/{oid}')
async def operation(oid:int,user=Depends(customer)):
    async with SessionLocal() as s:
        op=await s.get(MiniAppOperation,oid)
        if not op or op.user_id!=user.id:raise HTTPException(404,'عملیات پیدا نشد.')
        return await operation_view(s,op)

async def trial_access():
    from app.api.miniapp import get_setting_value
    await require_button('test_account')
    if await get_setting_value('test_account_button_visible','1')!='1' or await get_setting_value('test_account_enabled','1')!='1':
        raise HTTPException(403,'دریافت اکانت تست غیرفعال است.')


@router.get('/trial')
async def trial_info(user=Depends(customer)):
    from app.api.miniapp import get_setting_value,settings
    from app.database.models import TestAccountUsage
    from app.bot.handlers.public.test_account import parse_volume_gb,_load_test_account_targets
    await trial_access()
    async with SessionLocal() as s:
        used=bool(await s.scalar(select(TestAccountUsage.id).where(TestAccountUsage.telegram_id==user.telegram_id)))
        op=await s.scalar(select(MiniAppOperation).where(MiniAppOperation.user_id==user.id,MiniAppOperation.kind=='trial').order_by(MiniAppOperation.id.desc()).limit(1))
        operation=await operation_view(s,op) if op else None
    return dict(used=used and user.telegram_id not in settings.admin_ids,volume_gb=parse_volume_gb(await get_setting_value('test_account_volume_gb','1')),
                duration_days=await get_setting_value('test_account_duration_days','1'),server_count=len(await _load_test_account_targets()),operation=operation)


class TrialRequest(BaseModel):
    key:uuid.UUID


@router.post('/trial')
async def request_trial(body:TrialRequest,user=Depends(customer)):
    from app.api.miniapp import settings
    from app.database.models import TestAccountUsage
    from app.bot.handlers.public.test_account import _load_test_account_targets
    await trial_access()
    async with SessionLocal() as s:
        await s.get(User,user.id,with_for_update=True)
        prior=await s.scalar(select(MiniAppOperation).where(MiniAppOperation.key==str(body.key)))
        if prior:
            if prior.user_id!=user.id or prior.kind!='trial':raise HTTPException(409,'شناسه درخواست معتبر نیست.')
            return await operation_view(s,prior)
        pending=await s.scalar(select(MiniAppOperation).where(MiniAppOperation.user_id==user.id,MiniAppOperation.kind=='trial',MiniAppOperation.status.in_(['queued','processing'])).order_by(MiniAppOperation.id.desc()).limit(1))
        if pending:return await operation_view(s,pending)
        if user.telegram_id not in settings.admin_ids and await s.scalar(select(TestAccountUsage.id).where(TestAccountUsage.telegram_id==user.telegram_id)):
            raise HTTPException(409,'شما قبلاً یک بار اکانت تست دریافت کرده‌اید.')
        if not await _load_test_account_targets():raise HTTPException(409,'تنظیمات اکانت تست هنوز توسط مدیر کامل نشده است.')
        op=MiniAppOperation(user_id=user.id,key=str(body.key),kind='trial',payload={'action':'trial'})
        s.add(op);await s.commit();return await operation_view(s,op)


@router.get('/reseller/catalog')
async def catalog(user=Depends(customer)):
    async with SessionLocal() as s:
        account=await reseller_context(s,user)
        ids=account.allowed_server_ids or ([account.server_id] if account.server_id else [])
        rows=(await s.execute(select(Server).where(Server.id.in_(ids),Server.is_active.is_(True)))).scalars().all()
        packages=(await s.execute(select(ResellerPackage).where(ResellerPackage.is_active.is_(True)))).scalars().all()
        from app.services.reseller_management import profile
        personal_rate=int((await profile(s,f'account:{account.id}')).get('volume_rate',0))
        return dict(servers=[dict(id=x.id,name=x.name,provider=x.server_type) for x in rows if server_allows(account,x) and (x.meta or {}).get('scope')=='reseller'],
            packages=[dict(id=p.id,title=p.title,volume_gb=p.volume_gb,days=p.reseller_validity_days,price=f'{personal_rate*int(p.volume_gb):,} تومان' if personal_rate else plan_price_label(p)) for p in packages])

@router.post('/reseller/actions')
async def reseller_action(body:Action,user=Depends(customer)):
    if body.action not in {'create','add_volume','add_days','renew','delete','revoke','hwid'}:raise HTTPException(422,'عملیات معتبر نیست.')
    if not body.confirmed:raise HTTPException(409,'عملیات را تأیید کنید.')
    async with SessionLocal() as s:
        await s.get(User,user.id,with_for_update=True)
        payload=body.model_dump(mode='json');payload.pop('key')
        from app.bot.handlers.public.reseller import normalize_reseller_username
        payload['username']=normalize_reseller_username(body.username)
        prior=await s.scalar(select(MiniAppOperation).where(MiniAppOperation.key==str(body.key)))
        if prior:
            if prior.user_id!=user.id or prior.payload!=payload:raise HTTPException(409,'این شناسه قبلاً برای درخواست دیگری ثبت شده است.')
            return await operation_view(s,prior)
        account=await reseller_context(s,user,active=body.action!='delete')
        if body.action=='create':
            from app.bot.handlers.public.reseller import resolve_reseller_build_target,normalize_reseller_username,get_reseller_username_error
            name=normalize_reseller_username(body.username)
            server,_=await resolve_reseller_build_target(s,account,body.server_id)
            if not server or not server.is_active or not server_allows(account,server):raise HTTPException(403,'سرور در دسترس نمایندگی نیست.')
            try:error = await get_reseller_username_error(s, server, name)
            except RuntimeError:raise HTTPException(503,'بررسی نام در پنل انجام نشد؛ کمی بعد دوباره تلاش کنید.')
            if error:raise HTTPException(422, error)
            payload['username']=name
        else:
            svc=await reseller_service(s,user,body.service_id)
            if svc.disabled_reason=='mode_switch_manual':raise HTTPException(409,'این کانفیگ باید توسط مدیر تمدید شود.')
            server=await s.get(Server,svc.server_id)
            if not server or not server_allows(account,server):raise HTTPException(403,'این سرور برای نماینده مجاز نیست.')
        # One unresolved mutation per account avoids racing panel writes. A failed
        # remote operation requires review; a new key never retries it silently.
        pending=await s.scalar(select(MiniAppOperation.id).where(MiniAppOperation.user_id==user.id,MiniAppOperation.status.in_(['queued','processing']),MiniAppOperation.kind.like('reseller_%')).limit(1))
        if pending:raise HTTPException(409,'عملیات قبلی هنوز در حال انجام است؛ وضعیت آن را بررسی کنید.')
        op=MiniAppOperation(user_id=user.id,key=str(body.key),kind='reseller_'+body.action,payload=payload)
        s.add(op);await s.commit();return await operation_view(s,op)

@router.post('/services/{sid}/actions')
async def public_action(sid:int,body:Action,user=Depends(customer)):
    await require_button('my_services')
    if body.action not in {'revoke','hwid','delete'} or not body.confirmed:raise HTTPException(422,'عملیات تأییدشده معتبر نیست.')
    async with SessionLocal() as s:
        await s.get(User,user.id,with_for_update=True)
        payload={'action':body.action,'service_id':sid}
        prior=await s.scalar(select(MiniAppOperation).where(MiniAppOperation.key==str(body.key)))
        if prior:
            if prior.user_id!=user.id or prior.payload!=payload:raise HTTPException(409,'شناسهٔ عملیات معتبر نیست.')
            return await operation_view(s,prior)
        await owned_service(s,user,sid)
        pending=await s.scalar(select(MiniAppOperation.id).where(MiniAppOperation.user_id==user.id,MiniAppOperation.status.in_(['queued','processing'])).limit(1))
        if pending:raise HTTPException(409,'عملیات قبلی هنوز تمام نشده است.')
        op=MiniAppOperation(user_id=user.id,key=str(body.key),kind='public_'+body.action,payload=payload)
        s.add(op);await s.commit();return await operation_view(s,op)

async def configuration_control(s,user,sid,action,*,reseller=False):
    svc=await reseller_service(s,user,sid) if reseller else await owned_service(s,user,sid)
    server=await s.get(Server,svc.server_id)
    if not server:raise ValueError('سرور پیدا نشد.')
    from app.services.xui_service import XuiService
    from app.services.pasarguard_service import PasarGuardService
    from app.services.mikrotik_service import MikroTikService
    email=svc.xui_email or svc.client_username
    if action=='hwid':
        if server.server_type=='pasarguard':result=await PasarGuardService().reset_hwid_and_rotate(server,email)
        elif server.server_type=='xui':result=await XuiService().reset_hwid_and_rotate(server,email)
        else:raise ValueError('این پنل قابلیت ریست HWID ندارد.')
        svc.sub_link=result.get('sub_link') or result.get('subscription_url')
        if result.get('uuid'):svc.xui_uuid=str(result['uuid'])
        plan=await s.get(Plan,svc.plan_id) if svc.plan_id else None
        svc.sub_link=await XuiService().resolve_service_subscription(s,server,svc,plan,refresh_happ=True)
    elif server.server_type=='mikrotik':
        result=await MikroTikService().rotate_password(server,email);svc.xui_uuid=str(result.get('password') or svc.xui_uuid or '')
    elif server.server_type in {'xui','pasarguard'}:
        if server.server_type=='pasarguard':
            # Sanaei subscription rotation must never be used for other providers.
            result=await PasarGuardService().revoke_subscription(server,email)
        else:result=await XuiService().revoke_and_new_link(server,email)
        svc.sub_link=result.get('sub_link') or result.get('subscription_url')
        if result.get('uuid'):svc.xui_uuid=str(result['uuid'])
        plan=await s.get(Plan,svc.plan_id) if svc.plan_id else None
        svc.sub_link=await XuiService().resolve_service_subscription(s,server,svc,plan,refresh_happ=True)
    else:raise ValueError('این پنل پشتیبانی نمی‌شود.')
    await s.commit()
    return svc.id

async def deliver_subscription(real,user,sid):
    from app.bot.service_presenter import send_service_info
    from app.services.xui_service import XuiService
    async with SessionLocal() as s:
        svc=await s.get(ClientService,sid);plan=await s.get(Plan,svc.plan_id) if svc.plan_id else None;server=await s.get(Server,svc.server_id)
        link=await XuiService().resolve_service_subscription(s,server,svc,plan,refresh_happ=True) if server.server_type!='mikrotik' else None
        await s.commit()
        await send_service_info(real,user.telegram_id,svc.client_username,plan.title if plan else f'نمایندگی | {svc.total_bytes/1024**3:g} گیگ',svc.total_bytes/1024**3,max(0,((svc.expires_at or datetime.utcnow())-datetime.utcnow()).days),link,
            is_test=False,allow_happ=not bool(svc.reseller_id),service_id=svc.id,server_type=server.server_type,password=svc.xui_uuid if server.server_type=='mikrotik' else None,
            l2tp_server=(server.meta or {}).get('l2tp_server'),l2tp_ipsec_secret=(server.meta or {}).get('l2tp_ipsec_secret'))

async def process_operations():
    async with SessionLocal() as s:
        ids=(await s.execute(select(MiniAppOperation.id).where(MiniAppOperation.status=='queued',MiniAppOperation.kind.in_(['reseller_'+x for x in ['create','add_volume','add_days','renew','delete','revoke','hwid']]+['public_revoke','public_hwid','public_delete','trial'])).order_by(MiniAppOperation.id).limit(10))).scalars().all()
    for oid in ids:
        async with SessionLocal() as s:
            op=await s.scalar(select(MiniAppOperation).where(MiniAppOperation.id==oid).with_for_update(skip_locked=True))
            if not op or op.status!='queued':continue
            op.status='processing';op.updated_at=datetime.utcnow();await s.commit()
            user=await s.get(User,op.user_id);data=dict(op.payload);kind=op.kind
        sid=data.get('service_id');action=data['action'];result={};status='failed'
        try:
            async with telegram_bot() as real:
                if kind=='trial':
                    await trial_access()
                    if not user or user.is_blocked:raise ValueError('User is blocked')
                    from types import SimpleNamespace
                    from app.bot.handlers.public.test_account import handle_test_account
                    outcome=await handle_test_account(SimpleNamespace(bot=real),user.telegram_id,user.username,native=True)
                    result={k:v for k,v in outcome.items() if k!='ok'}
                    status='done' if outcome['ok'] else 'failed'
                elif action in {'revoke','hwid'}:
                    async with SessionLocal() as s:
                        if kind.startswith('reseller_'):await reseller_context(s,user,active=True)
                        sid=await configuration_control(s,user,sid,action,reseller=kind.startswith('reseller_'))
                    result={'service_id':sid,'message':'عملیات با موفقیت انجام شد.'};status='done'
                elif kind=='public_delete':
                    from app.bot.handlers.public import my_services as public_flow
                    _,callback,quiet=native_event(real,user,'',f'svc:delete_confirm:{sid}')
                    try:await public_flow.delete_service(callback)
                    except Exception:log.exception('Native public delete ended with error operation=%s',oid)
                    async with SessionLocal() as s:
                        from app.services.service_grace import visible_in_my_services
                        svc=await s.get(ClientService,sid)
                        success=not svc or not visible_in_my_services(svc)
                        from app.database.models import ServiceDeletionTask
                        cleanup=await s.scalar(select(ServiceDeletionTask).where(ServiceDeletionTask.source_service_id==sid))
                        queued=bool(cleanup and cleanup.status!='completed')
                    if success:
                        status='done';result={'message':'کانفیگ از فهرست شما حذف شد؛ حذف از پنل پس از اتصال دوباره ادامه می‌یابد.' if queued else 'کانفیگ حذف شد.'}
                    else:result={'message':'حذف کانفیگ تکمیل نشد؛ با پشتیبانی بررسی کنید.'}
                else:
                    from app.bot.handlers.public import reseller as flow
                    async with SessionLocal() as s:await reseller_context(s,user,active=action!='delete')
                    text=str(data['hwid_limit'] if action=='create' else data['volume'] if action=='add_volume' else data['days'])
                    message,callback,quiet=native_event(real,user,text,f'reseller:delete_confirm:{sid}')
                    state=NativeState(dict(username=data['username'],volume=data['volume'],duration=data['days'],reseller_target_server_id=data.get('server_id'),service_id=sid,operation_id=str(oid)))
                    handlers={'create':flow.reseller_create_hwid_limit,'add_volume':flow.reseller_add_volume_apply,'add_days':flow.reseller_add_days_apply,'renew':flow.reseller_renew_duration}
                    try:
                        if action=='delete':await flow.reseller_delete_user(callback)
                        else:await handlers[action](message,state)
                    except Exception:
                        log.exception('Native reseller flow ended with error operation=%s',oid)
                    async with SessionLocal() as s:
                        if action=='delete':
                            from app.services.service_grace import visible_in_my_services
                            svc=await s.get(ClientService,sid);success=not svc or not visible_in_my_services(svc)
                        else:
                            rows=(await s.execute(select(ResellerServiceActivity).where(ResellerServiceActivity.reseller_id.in_(select(ResellerAccount.id).where(ResellerAccount.user_id==user.id)),ResellerServiceActivity.action==action).order_by(ResellerServiceActivity.id.desc()).limit(50))).scalars().all()
                            activity=next((x for x in rows if str((x.meta or {}).get('operation_id'))==str(oid)),None)
                            success=bool(activity)
                            if activity:sid=activity.service_id
                    if success:
                        status='done';result={'service_id':sid if action!='delete' else None,'message':'عملیات با موفقیت انجام شد.'}
                    else:result={'message':next((t for t in reversed(quiet.texts) if '❌' in t or 'کافی نیست' in t or 'فعال نیست' in t),'عملیات تکمیل نشد؛ برای بررسی با پشتیبانی تماس بگیرید.')}
                # Commit success BEFORE delivery: network delivery cannot trigger
                # another allocation, renewal or financial debit.
                async with SessionLocal() as s:
                    op=await s.get(MiniAppOperation,oid);op.status=status;op.result=result;op.updated_at=datetime.utcnow();await s.commit()
                if status=='done' and action in {'create','renew','hwid'}:
                    try:await deliver_subscription(real,user,sid)
                    except Exception as exc:
                        from app.bot.error_reporting import report_bot_error
                        await report_bot_error(real,exc,context=f'Mini App subscription delivery operation={oid}')
        except Exception as exc:
            log.exception('Mini App action failed operation=%s',oid)
            async with SessionLocal() as s:
                op=await s.get(MiniAppOperation,oid)
                if op.status!='done':op.status='failed';op.result={'message':'انجام عملیات ناموفق بود؛ قبل از تلاش مجدد با پشتیبانی بررسی کنید.'};await s.commit()

async def recover_operations():
    async with SessionLocal() as s:
        rows=(await s.execute(select(MiniAppOperation).where(MiniAppOperation.status=='processing',MiniAppOperation.kind.notin_(['reseller_switch','admin_reseller_renew','panel_create','panel_action']),MiniAppOperation.updated_at<datetime.utcnow()-timedelta(minutes=15)))).scalars().all()
        for op in rows:op.status='failed';op.result={'message':'عملیات قطع شده و نیازمند بررسی پشتیبانی است؛ دوباره پرداخت نکنید.'}
        await s.commit()
