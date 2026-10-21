"""Native configuration creation using the purchased sub-admin's own credentials."""
import logging,re,uuid
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from sqlalchemy import select
from app.api.miniapp import customer,telegram_bot
from app.database.models import User,Server,PasarGuardPanelOrder,PasarGuardPanelMeter,MiniAppOperation
from app.database.session import SessionLocal
from app.services.pasarguard_service import PasarGuardService
from app.services.pasarguard_panel_meter import PanelMeterAPI
from app.services.reseller_management import profile,save_profile,GB
router=APIRouter(prefix='/api/miniapp/panels',tags=['Purchased panel configurations'])
log=logging.getLogger(__name__)

class PanelCreate(BaseModel):
    key:uuid.UUID
    username:str=Field(min_length=3,max_length=32)
    volume:int=Field(ge=1,le=1000000)
    days:int=Field(ge=1,le=3650)
    hwid_limit:int=Field(default=1,ge=0,le=10)
    group_ids:list[int]=Field(min_length=1,max_length=1000)
    confirmed:bool=False

async def context(s,user,pid,*,lock=False):
    panel=await s.get(PasarGuardPanelOrder,pid)
    if not panel or panel.user_id!=user.id or panel.status not in {'approved','delivery_pending'}:raise HTTPException(404,'پنل ساخته‌شده متعلق به شما پیدا نشد.')
    server=await s.get(Server,panel.server_id)
    if not server or not server.is_active or server.server_type!='pasarguard':raise HTTPException(409,'سرور پنل در دسترس نیست.')
    if not panel.password_encrypted or not panel.admin_id:raise HTTPException(409,'اطلاعات ورود پنل آماده نیست؛ با پشتیبانی تماس بگیرید.')
    current=await s.get(User,user.id,with_for_update=lock)
    finance=await profile(s,f'panels:{user.id}',lock)
    if finance.get('transition'):raise HTTPException(409,'تغییر تعرفه پنل در حال انجام است.')
    meter=await s.scalar(select(PasarGuardPanelMeter).where(PasarGuardPanelMeter.order_id==pid))
    if not meter:raise HTTPException(409,'همگام‌سازی حساب پنل هنوز کامل نشده است.')
    # Strip all owner authentication/access caches. Never fall back to the
    # configured owner token when purchased-dashboard authentication fails.
    child=SimpleNamespace(id=server.id,name=server.name,panel_url=server.panel_url,username=panel.username,
        password_encrypted=panel.password_encrypted,subscription_url=server.subscription_url,server_type='pasarguard',meta={key:value for key,value in (server.meta or {}).items() if key in {'pasarguard_api_base','panel_path'}})
    api=PasarGuardService();identity=await api.get_admin_profile(child)
    if int(identity.get('id') or 0)!=int(panel.admin_id) or str(identity.get('username','')).lower()!=panel.username.lower() or identity.get('is_sudo') or (identity.get('role') or {}).get('is_owner'):
        raise HTTPException(409,'مالکیت دسترسی پنل تأیید نشد.')
    groups=await api.list_groups(child)
    return panel,server,child,api,current,finance,meter,groups

@router.get('/{pid}/catalog')
async def catalog(pid:int,user=Depends(customer)):
    async with SessionLocal() as s:
        panel,server,child,api,current,finance,meter,groups=await context(s,user,pid)
        volume=finance.get('billing_mode')=='volume'
        return dict(groups=groups,username=panel.username,server=server.name,billing_mode='volume' if volume else 'payg',
            available_bytes=int(finance.get('available_bytes',0)),balance=int(current.wallet_balance or 0),
            can_create=bool(groups and (int(finance.get('available_bytes',0))>=GB if volume else not meter.suspended and int(current.wallet_balance or 0)>0)))

async def deliver(s,op,user):
    if (op.result or {}).get('delivered'):return
    from app.bot.service_presenter import send_service_info
    result=dict(op.result or {})
    try:
        async with telegram_bot() as bot:
            await send_service_info(bot,user.telegram_id,result['username'],'کانفیگ پنل نمایندگی',op.payload['volume'],op.payload['days'],result['link'],server_type='pasarguard')
        result['delivered']=True;op.result=result;await s.commit()
    except Exception:log.exception('Purchased panel configuration delivery pending operation=%s',op.id)

def view(op):
    data=op.result or {}
    return dict(id=op.id,status=op.status,username=data.get('username') or op.payload.get('username'),
        link=data.get('link') if op.status=='done' else None,retryable=data.get('retryable',op.status!='done'),
        message='کانفیگ ساخته شد.' if op.status=='done' else data.get('message','درخواست قبلی تکمیل نشده است؛ بررسی و ادامه ساخت را بزنید.'))

async def owned_remote(api,child,server,panel,username,remote):
    if not isinstance(remote,dict) or int(remote.get('id') or 0)<=0:raise ValueError('invalid_remote')
    owner=remote.get('admin')
    if isinstance(owner,dict) and owner.get('id') is not None:
        if int(owner['id'])!=int(panel.admin_id):raise ValueError('owner_mismatch')
    else:
        # Some versions omit admin in the create response. Verify via the
        # existing strict owner-filtered meter listing instead of assuming it.
        rows=await PanelMeterAPI().list_own_users(server,panel)
        if not any(int(r['id'])==int(remote['id']) and r.get('username')==username for r in rows):raise ValueError('owner_mismatch')
    return remote

async def retire_absent(s,api,child,user,pid,*,exclude=None):
    rows=(await s.execute(select(MiniAppOperation).where(MiniAppOperation.user_id==user.id,MiniAppOperation.kind=='panel_create',MiniAppOperation.status=='review').order_by(MiniAppOperation.id.desc()).limit(50))).scalars().all()
    for old in rows:
        if old.id==exclude or old.payload.get('panel_id')!=pid:continue
        if await api.get_user(child,old.payload['username']) is None:
            old.status='failed';old.result={'username':old.payload['username'],'retryable':True,'error_code':'not_created','message':'درخواست قبلی به ساخت کانفیگ منجر نشده است؛ می‌توانید دوباره تلاش کنید.'}

@router.get('/{pid}/configurations/pending')
async def pending(pid:int,user=Depends(customer)):
    async with SessionLocal() as s:
        panel,server,child,api,current,finance,meter,groups=await context(s,user,pid,lock=True)
        await retire_absent(s,api,child,user,pid)
        rows=(await s.execute(select(MiniAppOperation).where(MiniAppOperation.user_id==user.id,MiniAppOperation.kind=='panel_create').order_by(MiniAppOperation.id.desc()).limit(50))).scalars().all()
        op=next((row for row in rows if row.payload.get('panel_id')==pid),None)
        await s.commit()
        if not op or op.status=='done':return {'operation':None}
        return {'operation':dict(**view(op),key=op.key,request=op.payload)}

async def report_failure(exc,oid,stage):
    try:
        from app.bot.error_reporting import report_bot_error
        async with telegram_bot() as bot:
            await report_bot_error(bot,exc,context=f'Mini App panel configuration #{oid}, stage={stage}')
    except Exception:log.warning('Could not forward panel creation diagnostic operation=%s',oid)

def failure(exc,stage):
    text=str(exc)
    if 'owner_mismatch' in text:return 'owner_mismatch','مالکیت کانفیگ تأیید نشد. با پشتیبانی تماس بگیرید.',False
    if '(409)' in text:return 'conflict','این نام در پنل ثبت شده است؛ نام دیگری انتخاب کنید.',False
    if '(403)' in text:return 'permission','پنل اجازه ساخت یا ویرایش این کانفیگ را نمی‌دهد؛ دسترسی نماینده را مدیر بررسی کند.',True
    if '(401)' in text:return 'authentication','اطلاعات ورود پنل معتبر نیست؛ رمز پنل نمایندگی را بررسی کنید.',True
    if '(422)' in text or '(400)' in text:return 'validation','پنل مشخصات را نپذیرفت؛ گروه‌ها و محدودیت‌های حجم، زمان یا دستگاه را بررسی کنید.',True
    if 'credit_changed' in text:return 'credit','اعتبار پنل تغییر کرده است؛ موجودی را به‌روز کنید و دوباره تلاش کنید.',True
    if 'existing_mismatch' in text:return 'name_exists','این نام روی پنل وجود دارد و با درخواست شما مطابقت ندارد؛ نام دیگری انتخاب کنید.',False
    return 'connection','ارتباط با پنل کامل نشد؛ بررسی و ادامه ساخت را بزنید تا بدون ساخت تکراری، وضعیت بررسی شود.',True

@router.post('/{pid}/configurations')
async def create(pid:int,body:PanelCreate,user=Depends(customer)):
    if not body.confirmed:raise HTTPException(409,'ساخت کانفیگ را تأیید کنید.')
    username=body.username.strip().lower()
    if not re.fullmatch(r'[a-z][a-z0-9_]{2,31}',username):raise HTTPException(422,'نام باید با حرف انگلیسی شروع شود و شامل حروف انگلیسی، عدد یا زیرخط باشد.')
    request=body.model_dump(mode='json');request.pop('key');request.update(panel_id=pid,username=username,group_ids=sorted(set(body.group_ids)))
    async with SessionLocal() as s:
        current=await s.get(User,user.id,with_for_update=True)
        prior=await s.scalar(select(MiniAppOperation).where(MiniAppOperation.key==str(body.key)).with_for_update())
        if prior:
            if prior.user_id!=user.id or prior.kind!='panel_create' or prior.payload!=request:raise HTTPException(409,'شناسه عملیات قبلاً استفاده شده است.')
            if prior.status=='done':await deliver(s,prior,current);return view(prior)
            if not (prior.result or {}).get('retryable',True):return view(prior)
        panel,server,child,api,current,finance,meter,groups=await context(s,user,pid,lock=True)
        if not set(body.group_ids).issubset({int(g['id']) for g in groups}):raise HTTPException(403,'گروه انتخاب‌شده در دسترس این پنل نیست.')
        volume=finance.get('billing_mode')=='volume';quota=body.volume*GB
        if volume and quota>int(finance.get('available_bytes',0)) and not prior:raise HTTPException(409,'حجم پنل برای ساخت کافی نیست.')
        if not volume and (meter.suspended or int(current.wallet_balance or 0)<=0):raise HTTPException(409,'ابتدا کیف پول پنل را شارژ کنید.')
        await retire_absent(s,api,child,user,pid,exclude=prior.id if prior else None)
        pending_id=await s.scalar(select(MiniAppOperation.id).where(MiniAppOperation.user_id==user.id,MiniAppOperation.kind.in_(['panel_create','panel_action']),MiniAppOperation.status.in_(['processing','review']),MiniAppOperation.id!=(prior.id if prior else -1)).limit(1))
        if pending_id:raise HTTPException(409,'ساخت قبلی هنوز کامل نشده است؛ ابتدا بررسی و ادامه ساخت همان درخواست را بزنید.')
        existing=await api.get_user(child,username)
        if existing and not prior:raise HTTPException(409,'این نام قبلاً در پنل ثبت شده است.')
        own=await PanelMeterAPI().list_own_users(server,panel)
        if not existing and not volume and meter.max_users and len(own)>=meter.max_users:raise HTTPException(409,'سقف تعداد کاربر این پنل پر شده است.')
        op=prior or MiniAppOperation(user_id=user.id,key=str(body.key),kind='panel_create',status='processing',payload=request)
        if not prior:s.add(op)
        op.status='processing';await s.commit();oid=op.id
        stage='prepare';marker=f'D Bot Mini App operation {body.key}'
        try:
            current=await s.get(User,user.id,with_for_update=True,populate_existing=True)
            op=await s.get(MiniAppOperation,oid,with_for_update=True,populate_existing=True)
            if op.status=='done':return view(op)
            finance=await profile(s,f'panels:{user.id}',True)
            # Resolve the fixed username before every retry. The upstream unique
            # username constraint is an additional duplicate-creation boundary.
            created=await api.get_user(child,username) if prior else None
            if created:
                await owned_remote(api,child,server,panel,username,created)
                old_marker=str(created.get('note') or '')
                legacy_match=(created.get('status') in {'disabled','on_hold'} and not int(created.get('used_traffic') or 0) and int(created.get('data_limit') or 0)==quota and set(created.get('group_ids') or [])==set(request['group_ids']))
                if old_marker!=marker and not legacy_match:raise ValueError('existing_mismatch')
            else:
                if finance.get('transition') or (volume and quota>int(finance.get('available_bytes',0))) or (not volume and int(current.wallet_balance or 0)<=0):raise ValueError('credit_changed')
                stage='create'
                # PasarGuard UserCreate permits active/on_hold, NOT disabled.
                # on_hold requires a duration and cannot have an absolute expiry.
                created=await api._request(child,'POST','/api/user',json={'username':username,'status':'on_hold','on_hold_expire_duration':body.days*86400,'on_hold_timeout':(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat(),'data_limit':quota,'data_limit_reset_strategy':'no_reset','group_ids':request['group_ids'],'hwid_limit':body.hwid_limit,'note':marker})
                await owned_remote(api,child,server,panel,username,created)
            remote_id=int(created['id']);stage='pause'
            expiry=datetime.now(timezone.utc)+timedelta(days=body.days)
            await api.update_user(child,username,status='disabled',expire_at=expiry)
            finance=await profile(s,f'panels:{user.id}',True)
            if finance.get('transition'):raise ValueError('credit_changed')
            if volume:
                allocation=f'panel:{panel.id}:{remote_id}'
                reserved=int(finance.get('allocations',{}).get(allocation,0));delta=max(0,quota-reserved)
                if delta>int(finance.get('available_bytes',0)):raise ValueError('credit_changed')
                finance['available_bytes']=int(finance.get('available_bytes',0))-delta
                finance.setdefault('allocations',{})[allocation]=quota;finance.setdefault('quota_limits',{})[allocation]=quota
                await save_profile(s,f'panels:{user.id}',finance)
            stage='activate'
            updated=await api.update_user(child,username,status='active',expire_at=expiry)
            link=await api.current_subscription_link(child,username,created,updated)
            if not link:raise RuntimeError('subscription link missing')
            stage='commit';op.status='done';op.result=dict(username=username,link=link,remote_id=remote_id,delivered=False,configuration=dict(total_bytes=quota,used_bytes=0,expires_at=expiry.isoformat(),status='active'))
            await s.commit();await deliver(s,op,current);return view(op)
        except Exception as exc:
            await s.rollback();log.exception('Purchased panel creation pending operation=%s stage=%s',oid,stage)
            code,message,retryable=failure(exc,stage)
            if code=='conflict' and stage=='create':
                try:
                    found=await api.get_user(child,username)
                    if found and (found.get('note') or '')==marker and int((found.get('admin') or {}).get('id') or 0)==int(panel.admin_id):
                        code,message,retryable='connection','کانفیگ ثبت شده است؛ بررسی و ادامه ساخت را بزنید.',True
                except Exception:
                    code,message,retryable='connection','ارتباط با پنل کامل نشد؛ بررسی و ادامه ساخت را بزنید.',True
            op=await s.get(MiniAppOperation,oid,with_for_update=True)
            op.status='failed' if (code in {'validation','permission','authentication','conflict'} and stage=='create') or code=='name_exists' else 'review'
            op.result={'username':username,'stage':stage,'error_code':code,'message':message,'retryable':retryable};await s.commit()
            await report_failure(exc,oid,stage)
            return view(op)


async def configuration_link(pid, oid, user):
    from app.api.miniapp import require_button
    await require_button('my_services')
    async with SessionLocal() as s:
        op=await s.get(MiniAppOperation,oid)
        if not op or op.user_id!=user.id or op.kind!='panel_create' or op.status!='done' or op.payload.get('panel_id')!=pid:
            raise HTTPException(404,'کانفیگ پیدا نشد.')
        if (op.result or {}).get('deleted'):raise HTTPException(410,'این کانفیگ حذف شده است.')
        panel,server,child,api,current,finance,meter,groups=await context(s,user,pid)
        remote=await api.get_user(child,op.payload['username'])
        if not remote or int(remote.get('id') or 0)!=int((op.result or {}).get('remote_id') or 0):
            raise HTTPException(404,'کانفیگ در پنل پیدا نشد.')
        try:await owned_remote(api,child,server,panel,op.payload['username'],remote)
        except ValueError:raise HTTPException(403,'کانفیگ متعلق به این پنل نیست.')
        link=api.resolve_subscription_link(child,remote)
        if not link.startswith(('https://','http://')):raise HTTPException(409,'لینک کانفیگ آماده نیست.')
        result=dict(op.result or {});result['link']=link;op.result=result;await s.commit()
        return link

@router.get('/{pid}/configurations/{oid}/link')
async def config_link(pid:int,oid:int,user=Depends(customer)):
    link=await configuration_link(pid,oid,user)
    return dict(link=link,happ_url='happ://add/'+link)

@router.get('/{pid}/configurations/{oid}/qr')
async def config_qr(pid:int,oid:int,user=Depends(customer)):
    import io,qrcode
    from fastapi import Response
    link=await configuration_link(pid,oid,user)
    image=qrcode.make(link);output=io.BytesIO();image.save(output,format='PNG')
    return Response(output.getvalue(),media_type='image/png',headers={'Cache-Control':'no-store'})

from app.api.miniapp_panel_actions import PanelAction

@router.post('/{pid}/configurations/{oid}/actions')
async def configuration_action(pid:int,oid:int,body:PanelAction,user=Depends(customer)):
    from app.api.miniapp_panel_actions import execute
    return await execute(pid,oid,body,user)


@router.get('/{pid}/configurations/{oid}/actions/{key}')
async def panel_action_status(pid:int,oid:int,key:str,user=Depends(customer)):
    from app.api.miniapp_panel_actions import view as action_view
    async with SessionLocal() as s:
        op=await s.scalar(select(MiniAppOperation).where(MiniAppOperation.key==key,MiniAppOperation.user_id==user.id,MiniAppOperation.kind=='panel_action'))
        if not op or op.payload.get('panel_id')!=pid or op.payload.get('configuration_id')!=oid:raise HTTPException(404,'عملیات پیدا نشد.')
        return action_view(op)
