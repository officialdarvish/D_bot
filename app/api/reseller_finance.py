import uuid
from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import Response
from sqlalchemy import select, func
from app.api.admin_web import _auth_user
from app.database.session import SessionLocal
from app.database.models import ResellerAccount, ResellerBillingEntry, ResellerUsageMeter, Server, ResellerWalletReceipt

router=APIRouter()

@router.get('/admin/api/v2/resellers/{rid}/billing')
async def billing_report(rid:int,_:str=Depends(_auth_user)):
    async with SessionLocal() as s:
        account=await s.get(ResellerAccount,rid)
        if not account:return {'ok':False,'message':'Reseller not found'}
        entries=(await s.execute(select(ResellerBillingEntry,Server.name).outerjoin(Server,ResellerBillingEntry.server_id==Server.id).where(ResellerBillingEntry.reseller_id==rid).order_by(ResellerBillingEntry.id.desc()).limit(100))).all()
        grouped=(await s.execute(select(ResellerBillingEntry.server_id,func.sum(ResellerBillingEntry.usage_bytes),func.sum(ResellerBillingEntry.amount_irt)).where(ResellerBillingEntry.reseller_id==rid,ResellerBillingEntry.kind=='usage').group_by(ResellerBillingEntry.server_id))).all()
        receipts=(await s.execute(select(ResellerWalletReceipt).where(ResellerWalletReceipt.reseller_id==rid).order_by(ResellerWalletReceipt.id.desc()).limit(30))).scalars().all()
        meters=(await s.execute(select(ResellerUsageMeter).where(ResellerUsageMeter.reseller_id==rid))).scalars().all()
    return {'ok':True,'mode':account.billing_mode,'wallet_balance_irt':account.wallet_balance_irt,
        'last_settlement':account.billing_last_run_at.isoformat() if account.billing_last_run_at else None,
        'by_server':[{'server_id':sid,'usage_bytes':int(traffic or 0),'cost_irt':-int(amount or 0)} for sid,traffic,amount in grouped],
        'suspended':sum(m.suspended for m in meters),'pending':sum(m.suspension_pending for m in meters),'errors':[{'service_id':m.service_id,'error':m.last_error} for m in meters if m.last_error],
        'receipts':[dict(id=r.id,amount_irt=r.amount_irt,status=r.status,created_at=r.created_at.isoformat()) for r in receipts],
        'entries':[{'id':e.id,'kind':e.kind,'amount_irt':e.amount_irt,'balance_after_irt':e.balance_after_irt,'usage_bytes':e.usage_bytes,'server_id':e.server_id,'server_name':name,'note':e.note,'created_at':e.created_at.isoformat()} for e,name in entries]}


@router.get('/admin/api/v2/reseller-wallet-receipts/{receipt_id}/file')
async def receipt_file(receipt_id:int,_:str=Depends(_auth_user)):
    import io
    from app.api.miniapp import telegram_bot
    async with SessionLocal() as s:
        receipt=await s.get(ResellerWalletReceipt,receipt_id)
        if not receipt:raise HTTPException(404,'Receipt not found')
    async with telegram_bot() as bot:
        remote=await bot.get_file(receipt.file_id)
        buf=io.BytesIO()
        await bot.download_file(remote.file_path,destination=buf)
    return Response(buf.getvalue(),media_type='image/jpeg' if receipt.is_photo else 'application/octet-stream',headers={
        'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
        'Content-Disposition':'inline; filename="receipt.jpg"' if receipt.is_photo else 'attachment; filename="receipt.bin"'})


@router.post('/admin/reseller-wallet-receipts/{receipt_id}/review')
async def receipt_review(receipt_id:int,decision:str=Form(...),owner:str=Depends(_auth_user)):
    from app.services.reseller_billing import review_receipt
    from app.api.miniapp import telegram_bot
    from app.core.config import settings
    if decision not in {'approve','reject'}:raise HTTPException(400,'Invalid decision')
    actor=int(owner.split(':')[-1]) if owner.startswith('telegram-owner:') else (settings.admin_ids[0] if settings.admin_ids else 0)
    async with SessionLocal() as s:
        result=await review_receipt(s,receipt_id,actor,decision=='approve')
        if not result:return {'ok':True,'message':'Receipt already reviewed'}
        receipt,account,user=result;await s.commit()
    if decision=='approve':
        from app.services.reseller_billing import reconcile_suspensions
        await reconcile_suspensions()
    if user:
        try:
            async with telegram_bot() as bot:
                await bot.send_message(user.telegram_id,('✅ رسید شارژ نمایندگی تایید شد.' if decision=='approve' else '❌ رسید شارژ نمایندگی رد شد.')+f'\nمبلغ: {receipt.amount_irt:,} تومان\nموجودی: {account.wallet_balance_irt:,} تومان')
        except Exception:pass
    return {'ok':True,'message':'Receipt reviewed'}

@router.get('/admin/api/v2/resellers/{kind}/{ident}/settings')
async def financial_settings(kind:str,ident:int,live:bool=False,rate:int=0,_:str=Depends(_auth_user)):
    from app.services.reseller_management import snapshot
    try:
        async with SessionLocal() as s:
            result=await snapshot(s,kind,ident,live=live,rate=rate)
            # Live preview persists only traffic checkpoints / PAYG settlement.
            await s.commit();return result
    except (ValueError,RuntimeError) as exc:raise HTTPException(409,str(exc))

@router.post('/admin/resellers/{kind}/{ident}/tariffs')
async def financial_tariffs(kind:str,ident:int,payg_rate:int=Form(...),volume_rate:int=Form(...),hourly_rate:int=Form(0),_:str=Depends(_auth_user)):
    from app.services.reseller_management import save_rates
    from app.services.pasarguard_panel_meter import PanelMeterAPI
    try:
        if kind=='panel':
            async with SessionLocal() as s:
                panel=await s.get(__import__('app.database.models',fromlist=['PasarGuardPanelOrder']).PasarGuardPanelOrder,ident)
                if not panel:raise ValueError('پنل پیدا نشد.')
                from app.database.models import PasarGuardPanelOrder
                ids=(await s.execute(select(PasarGuardPanelOrder.id).where(PasarGuardPanelOrder.user_id==panel.user_id,PasarGuardPanelOrder.status.in_(['approved','delivery_pending'])))).scalars().all()
            for oid in ids:await PanelMeterAPI().poll(oid)
        async with SessionLocal() as s:
            await save_rates(s,kind,ident,payg_rate,volume_rate,hourly_rate);await s.commit()
        return dict(ok=True,message='تعرفه نماینده ذخیره شد.')
    except (ValueError,RuntimeError) as exc:raise HTTPException(409,str(exc))

@router.post('/admin/resellers/{kind}/{ident}/switch')
async def financial_switch(kind:str,ident:int,mode:str=Form(...),rate:int=Form(...),key:str=Form(...),expected_balance:int=Form(...),expected_count:int=Form(...),_:str=Depends(_auth_user)):
    from app.services.reseller_management import start_switch
    try:return await start_switch(kind,ident,mode,rate,key,expected_balance,expected_count)
    except (ValueError,RuntimeError) as exc:raise HTTPException(409,str(exc))

@router.post('/admin/resellers/switch/{oid}/retry')
async def financial_retry(oid:int,_:str=Depends(_auth_user)):
    from app.services.reseller_management import run_switch
    try:return await run_switch(oid)
    except ValueError as exc:raise HTTPException(409,str(exc))

@router.post('/admin/resellers/requests/{ident}/configure')
async def configure_request(ident:int,server_id:int=Form(...),mode:str=Form(...),payg_rate:int=Form(...),volume_rate:int=Form(...),_:str=Depends(_auth_user)):
    from app.database.models import ResellerAccessRequest
    from app.services.reseller_management import save_rates
    from app.services.reseller_billing import policy
    async with SessionLocal() as s:
        req=await s.get(ResellerAccessRequest,ident,with_for_update=True)
        server=await s.get(Server,server_id)
        if not req or req.status not in {'pending','approved_payg','approved'}:raise HTTPException(409,'درخواست قابل تأیید نیست.')
        if not server or not server.is_active or (server.meta or {}).get('scope') not in {'reseller','all'}:raise HTTPException(409,'سرور نمایندگی فعال انتخاب کنید.')
        if mode not in policy(server)[0] or server.server_type not in {'xui','pasarguard'}:raise HTTPException(409,'این سیستم مالی در تنظیمات سرور فعال نیست.')
        account=await s.scalar(select(ResellerAccount).where(ResellerAccount.user_id==req.user_id).with_for_update())
        if account:raise HTTPException(409,'حساب نمایندگی موجود است؛ همان حساب را ویرایش کنید.')
        account=ResellerAccount(user_id=req.user_id,server_id=server_id,allowed_server_ids=[server_id],billing_mode=mode,is_active=True)
        s.add(account);await s.flush()
        try:await save_rates(s,'account',account.id,payg_rate,volume_rate)
        except ValueError as exc:raise HTTPException(422,str(exc))
        req.status='approved';req.reviewed_at=__import__('datetime').datetime.utcnow()
        await s.commit();return dict(ok=True,message='نمایندگی تنظیم و تأیید شد.',id=account.id)

@router.post('/admin/resellers/{kind}/{ident}/renew-service')
async def renew_managed_service(kind:str,ident:int,service_key:str=Form(...),volume_gb:int=Form(...),days:int=Form(30),key:str=Form(...),_:str=Depends(_auth_user)):
    from datetime import datetime,timedelta
    from app.database.models import MiniAppOperation,ClientService
    from app.services.reseller_management import target,profile,save_profile,own_rows,freeze_remote,GB
    if not 1<=volume_gb<=10**6 or not 1<=days<=3650:raise HTTPException(422,'حجم یا مدت معتبر نیست.')
    try:uuid.UUID(key)
    except ValueError:raise HTTPException(422,'شناسه عملیات معتبر نیست.')
    async with SessionLocal() as s:
        obj,user,pk=await target(s,kind,ident,True);p=await profile(s,pk,True)
        if p.get('transition'):raise HTTPException(409,'ابتدا تبدیل در حال انجام را کامل کنید.')
        prior=await s.scalar(select(MiniAppOperation).where(MiniAppOperation.key==key).with_for_update())
        payload=dict(target=pk,service_key=service_key,volume_gb=volume_gb,days=days)
        if prior:
            if prior.kind!='admin_reseller_renew' or prior.payload!=payload:raise HTTPException(409,'شناسه عملیات تکراری است.')
            if prior.status=='paid':return dict(ok=True,message='تمدید قبلاً اعمال شده است.')
        if kind=='panel':
            pending=await s.scalar(select(MiniAppOperation.id).where(MiniAppOperation.user_id==user.id,MiniAppOperation.kind=='panel_action',MiniAppOperation.status.in_(['processing','review'])).limit(1))
            if pending:raise HTTPException(409,'ابتدا عملیات در حال انجام کانفیگ پنل را کامل کنید.')
        rows=await own_rows(s,kind,obj);row=next((r for r in rows if r['key']==service_key),None)
        if not row:raise HTTPException(404,'کانفیگ متعلق به این نماینده نیست.')
        mode=obj.billing_mode if kind=='account' else p.get('billing_mode','payg')
        quota=volume_gb*GB
        if kind=='account':
            svc=await s.get(ClientService,row['service_id']);old=int(svc.reseller_reserved_bytes or 0)
            available=int(obj.total_bytes or 0)
        else:old=int(p.get('allocations',{}).get(service_key,0));available=int(p.get('available_bytes',0))
        delta=quota-old if mode=='volume' else 0
        if delta>available:raise HTTPException(409,'حجم نماینده برای تمدید کافی نیست.')
        if not prior:
            prior=MiniAppOperation(user_id=user.id,key=key,kind='admin_reseller_renew',status='processing',payload=payload);s.add(prior);await s.flush()
        try:await freeze_remote(s,row,row['used']+quota,enabled=True,expire_at=datetime.utcnow()+timedelta(days=days))
        except Exception as exc:raise HTTPException(503,f'تمدید روی پنل انجام نشد؛ با همان عملیات دوباره تلاش کنید: {exc}')
        if kind=='account':
            obj.total_bytes=available-delta;svc.total_bytes=row['used']+quota;svc.reseller_reserved_bytes=quota if mode=='volume' else 0
            svc.reseller_reserved_used_baseline=row['used'];svc.is_active=True;svc.disabled_reason=None;svc.expires_at=datetime.utcnow()+timedelta(days=days)
            m=await s.scalar(select(ResellerUsageMeter).where(ResellerUsageMeter.service_id==svc.id))
            if m:m.suspended=False;m.suspension_pending=False
        else:
            p['available_bytes']=available-delta
            p.setdefault('allocations',{})[service_key]=quota if mode=='volume' else 0
            p.setdefault('quota_limits',{})[service_key]=row['used']+quota
            p['manual_pauses']=[k for k in p.get('manual_pauses',[]) if k!=service_key]
            await save_profile(s,pk,p)
        prior.status='paid';await s.commit()
        return dict(ok=True,message='کانفیگ با حجم و مدت جدید تمدید و فعال شد.')
