"""Native wallet/quota checkout and shared pending-order tracking."""
import io,uuid,logging
from datetime import datetime,timedelta
from fastapi import APIRouter,Depends,HTTPException,UploadFile,File
from pydantic import BaseModel,Field
from sqlalchemy import select,func
from PIL import Image,UnidentifiedImageError
from aiogram.types import BufferedInputFile,InlineKeyboardButton,InlineKeyboardMarkup
from app.api.miniapp import customer,reseller_context,require_button,telegram_bot
from app.api.miniapp_checkout import order_view,resend_order,submitted_order_clause
from app.database.session import SessionLocal
from app.database.models import User,Order,Plan,Server,PaymentCard,MiniAppOperation,ResellerPackage,ResellerAccount,ResellerTopupRequest,WalletTransaction,ResellerWalletReceipt,ResellerBillingEntry,DiscountCode,PasarGuardPanelOrder
from app.core.config import settings
from app.services.live_pricing import quote_plan,LivePricingError
from app.services.reseller_service import apply_package
from app.services.reseller_billing import credit,is_payg

router=APIRouter(prefix='/api/miniapp',tags=['Mini App payments'])
log=logging.getLogger(__name__)

class Funding(BaseModel):
    key:uuid.UUID
    kind:str
    package_id:int|None=Field(default=None,gt=0)
    panel_id:int|None=Field(default=None,gt=0)
    server_id:int|None=Field(default=None,gt=0)
    amount:int=Field(default=10000,ge=1,le=10**10)
    method:str='card'
    discount_code:str=Field(default='',max_length=64)
    expected_amount:int|None=Field(default=None,ge=0)

async def funding_quote(s,user,body):
    if body.kind not in {'reseller_package','reseller_wallet','wallet_topup','panel_wallet'}:raise HTTPException(422,'نوع خرید معتبر نیست.')
    account=await reseller_context(s,user) if body.kind in {'reseller_package','reseller_wallet'} else None
    if body.kind=='wallet_topup':await require_button('wallet_topup')
    from app.database.models import Setting
    minimum_row=await s.get(Setting,'reseller_payg_min_topup_irt') if body.kind=='reseller_wallet' else None
    minimum=int(minimum_row.value) if minimum_row else 10000
    if body.kind!='reseller_package' and body.amount<minimum:raise HTTPException(422,f'حداقل شارژ {minimum:,} تومان است.')
    amount=body.amount;package=None;discount=None
    if body.kind=='reseller_package':
        if is_payg(account):raise HTTPException(409,'برای مدل مصرفی از شارژ کیف پول نمایندگی استفاده کنید.')
        package=await s.get(ResellerPackage,body.package_id)
        if not package or not package.is_active:raise HTTPException(404,'بسته فعال نیست.')
        from app.services.reseller_service import reseller_package_server_ids
        from app.services.reseller_billing import server_allows
        target_id=body.server_id or account.server_id
        server=await s.get(Server,target_id) if target_id else None
        if not server or not server.is_active or target_id not in reseller_package_server_ids(account) or not server_allows(account,server) or (server.meta or {}).get('scope')!='reseller' or package.server_id!=target_id:
            raise HTTPException(403,'بسته حجمی متعلق به سرور انتخاب‌شده و مجاز نمایندگی نیست.')
        from app.services.reseller_management import quote_package
        try:quote=await quote_package(s,account,package)
        except LivePricingError:raise HTTPException(503,'دریافت قیمت لحظه‌ای ناموفق بود؛ دوباره تلاش کنید.')
        amount=quote.amount_irt
        if body.discount_code:
            await s.scalar(select(DiscountCode).where(func.upper(DiscountCode.code)==body.discount_code.strip().upper().replace(' ','')).with_for_update())
            from app.bot.handlers.public.reseller import apply_reseller_discount
            amount,error,discount=await apply_reseller_discount(s,body.discount_code,amount,user.id)
            if error:raise HTTPException(409,error)
    if body.kind=='reseller_wallet' and not is_payg(account):raise HTTPException(409,'کیف پول مصرفی برای شما فعال نیست.')
    if body.kind=='panel_wallet':
        panel=await s.get(PasarGuardPanelOrder,body.panel_id) if body.panel_id else None
        if not panel or panel.user_id!=user.id or panel.status not in {'approved','delivery_pending'}:raise HTTPException(404,'پنل متعلق به شما نیست یا هنوز ساخته نشده است.')
        server=await s.get(Server,panel.server_id)
        if not server or server.server_type!='pasarguard':raise HTTPException(409,'سرور پنل در دسترس نیست.')
        from app.services.payment_cards import reseller_payment_card
        card=await reseller_payment_card(s,panel.server_id)
    elif body.kind=='wallet_topup':
        card=await s.scalar(select(PaymentCard).where(PaymentCard.is_active.is_(True)).order_by(PaymentCard.id.desc()).limit(1))
    else:
        from app.services.payment_cards import reseller_payment_card
        target=package.server_id if package else account.server_id or next(iter(account.allowed_server_ids or []),None)
        card=await reseller_payment_card(s,target)
    return account,package,amount,discount,card

@router.post('/funding/quote')
async def quote(body:Funding,user=Depends(customer)):
    async with SessionLocal() as s:
        account,pkg,amount,_,card=await funding_quote(s,user,body)
        u=await s.get(User,user.id)
        return dict(amount=amount,title=pkg.title if pkg else 'شارژ کیف پول پنل نمایندگی' if body.kind=='panel_wallet' else 'شارژ کیف پول نمایندگی' if account else 'شارژ کیف پول',methods=(['wallet'] if account else [])+(['card'] if card else []),balance=u.wallet_balance)

async def funding_view(s,op):
    result=op.result or {};payload=op.payload or {};status=op.status;reason=None
    typ=result.get('target_type');target=await s.get({'reseller':ResellerTopupRequest,'payg':ResellerWalletReceipt,'order':Order}.get(typ,Order),result['target_id']) if result.get('target_id') else None
    if target:
        status='paid' if target.status in {'approved','paid'} else 'waiting_approval' if target.status in {'pending','waiting_receipt'} else target.status
        reason=getattr(target,'rejection_reason',None)
    return dict(id=op.id,key=op.key,kind=op.kind,status=status,title=payload.get('title','شارژ'),amount=payload.get('final_amount',0),
        created_at=op.created_at.isoformat()+'Z',card=payload.get('card') if status=='waiting_receipt' else None,receipt_uploaded=bool(target),rejection_reason=reason)

@router.post('/funding')
async def create(body:Funding,user=Depends(customer)):
    if body.method not in {'card','wallet'}:raise HTTPException(422,'روش پرداخت معتبر نیست.')
    async with SessionLocal() as s:
        u=await s.get(User,user.id,with_for_update=True)
        prior=await s.scalar(select(MiniAppOperation).where(MiniAppOperation.key==str(body.key)))
        request=body.model_dump(mode='json');request.pop('key')
        if prior:
            if prior.user_id!=user.id or (prior.payload or {}).get('request')!=request:raise HTTPException(409,'شناسهٔ خرید قبلاً استفاده شده است.')
            return await funding_view(s,prior)
        account,pkg,amount,discount,card=await funding_quote(s,user,body)
        if amount!=body.expected_amount:raise HTTPException(409,'قیمت تغییر کرده؛ مبلغ را دوباره بررسی کنید.')
        if body.method=='wallet' and not account:raise HTTPException(422,'روش پرداخت معتبر نیست.')
        if body.method=='card' and not card:raise HTTPException(409,'شماره کارت ثبت نشده است.')
        op=MiniAppOperation(user_id=user.id,key=str(body.key),kind=body.kind,status='waiting_receipt',payload=dict(request=request,title=pkg.title if pkg else 'شارژ کیف پول پنل نمایندگی' if body.kind=='panel_wallet' else 'شارژ کیف پول نمایندگی' if account else 'شارژ کیف پول',final_amount=amount,package_id=body.package_id,volume_bytes=int(pkg.volume_gb*1024**3) if pkg else 0,card=dict(number=card.card_number,owner=card.owner_name,id=card.id,reviewer=card.reviewer_telegram_id) if card else None))
        s.add(op);await s.flush()
        if body.method=='wallet':
            if int(u.wallet_balance or 0)<amount:raise HTTPException(409,'موجودی کیف پول شخصی کافی نیست.')
            account=await s.get(ResellerAccount,account.id,with_for_update=True)
            u.wallet_balance=int(u.wallet_balance or 0)-amount
            s.add(WalletTransaction(user_id=user.id,amount_irt=-amount,tx_type='reseller_purchase',description=f'Mini App funding #{op.id}'))
            if pkg:
                req=ResellerTopupRequest(user_id=user.id,package_id=pkg.id,amount_irt=amount,volume_bytes=int(pkg.volume_gb*1024**3),status='pending');s.add(req);await s.flush()
                await apply_package(s,req,source='miniapp_wallet',actor_telegram_id=user.telegram_id)
                op.result={'target_type':'reseller','target_id':req.id}
            else:await credit(s,account,amount,key=f'miniapp-transfer:{op.id}',kind='personal_transfer')
            op.status='paid'
        if discount and body.method=='wallet':
            from app.bot.handlers.public.reseller import mark_reseller_discount_used
            await mark_reseller_discount_used(s,discount,user.id)
        await s.commit()
        if body.method=='wallet' and body.kind=='reseller_wallet':
            from app.services.reseller_billing import reconcile_suspensions
            await reconcile_suspensions(account.id)
        # Admin accounting notice only; no chat prompt to the purchaser.
        if body.method=='wallet':
            try:
                async with telegram_bot() as bot:
                    for tid in set(settings.admin_ids+settings.owner_ids):
                        if tid==user.telegram_id:continue
                        try:await bot.send_message(tid,f'💳 خرید نمایندگی مینی‌اپ #{op.id}\nکاربر: {user.full_name} | {user.telegram_id}\nمبلغ: {amount:,} تومان',parse_mode=None)
                        except Exception:pass
            except Exception:log.exception('Mini App funding owner notification failed')
        return await funding_view(s,op)

async def owned_funding(s,user,oid,lock=False):
    op=await s.get(MiniAppOperation,oid,with_for_update=lock)
    if not op or op.user_id!=user.id or op.kind not in {'reseller_package','reseller_wallet','wallet_topup','panel_wallet'}:raise HTTPException(404,'سفارش پیدا نشد.')
    return op

@router.get('/funding/{oid}')
async def get(oid:int,user=Depends(customer)):
    async with SessionLocal() as s:return await funding_view(s,await owned_funding(s,user,oid))

async def notify_receipt(bot,typ,target,user,title,amount,file_id,reviewer=None,*,uploaded_to=None,uploaded_message_id=None,resend=True):
    rid=target.id
    if typ=='reseller':approve=f'resadmin:req_approve:{rid}';reject=f'resadmin:req_reject:{rid}'
    elif typ=='payg':approve=f'paygwallet:review:approve:{rid}';reject=f'paygwallet:review:reject:{rid}'
    else:approve=f'wallet_topup:approve:{rid}';reject=f'wallet_topup:reject:{rid}'
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='✅ تایید رسید',callback_data=approve),InlineKeyboardButton(text='❌ رد رسید',callback_data=reject)]])
    label='درخواست بررسی مجدد رسید' if resend else 'رسید شارژ / خرید مینی‌اپ'
    text=f'🧾 {label} #{rid}\nنام: {user.full_name or "-"}\nID: {user.telegram_id}\nUsername: @{user.username or "-"}\nمورد خرید: {title}\nمبلغ: {amount:,} تومان\nتاریخ: {target.created_at}'
    delivered=False
    targets=list(dict.fromkeys(int(tid) for tid in (([reviewer] if reviewer and typ=='order' else [])+settings.admin_ids+settings.owner_ids)))
    for tid in targets:
        try:
            if tid==uploaded_to and uploaded_message_id:
                try:await bot.edit_message_caption(chat_id=tid,message_id=uploaded_message_id,caption=text,reply_markup=kb,parse_mode=None)
                except Exception:
                    # Keep the already-delivered image; never resend that photo.
                    await bot.send_message(tid,text,reply_markup=kb,parse_mode=None)
            else:
                try:await bot.send_photo(tid,file_id,caption=text,reply_markup=kb,parse_mode=None)
                except Exception:await bot.send_document(tid,file_id,caption=text,reply_markup=kb,parse_mode=None)
            delivered=True
        except Exception:log.warning('Mini App receipt delivery failed target=%s kind=%s id=%s',tid,typ,rid)
    return delivered

@router.post('/funding/{oid}/receipt')
async def upload(oid:int,file:UploadFile=File(...),user=Depends(customer)):
    async with SessionLocal() as s:
        op=await owned_funding(s,user,oid,True)
        if (op.result or {}).get('target_id'):return await funding_view(s,op)
        if op.status!='waiting_receipt':raise HTTPException(409,'سفارش در انتظار رسید نیست.')
        raw=await file.read(8*1024**2+1)
        if len(raw)>8*1024**2:raise HTTPException(413,'حداکثر حجم رسید ۸ مگابایت است.')
        try:
            image=Image.open(io.BytesIO(raw))
            if image.width*image.height>25000000 or max(image.size)>min(image.size)*20:raise ValueError()
            image.load();image=image.convert('RGB');image.thumbnail((4000,4000));out=io.BytesIO();image.save(out,'JPEG',quality=92)
        except (OSError,ValueError,UnidentifiedImageError,Image.DecompressionBombError):raise HTTPException(422,'عکس رسید معتبر نیست.')
        data=op.payload
        if (data.get('request') or {}).get('discount_code'):
            from app.bot.handlers.public.reseller import apply_reseller_discount,mark_reseller_discount_used
            await s.scalar(select(DiscountCode).where(func.upper(DiscountCode.code)==data['request']['discount_code'].strip().upper().replace(' ','')).with_for_update())
            pkg=await s.get(ResellerPackage,data['package_id'])
            if not pkg:raise HTTPException(409,'بسته حذف شده است.')
            from app.services.reseller_management import quote_package
            account=await reseller_context(s,user)
            price=await quote_package(s,account,pkg)
            amount,error,discount=await apply_reseller_discount(s,data['request']['discount_code'],price.amount_irt,user.id)
            if error:raise HTTPException(409,error)
            if amount!=data['final_amount']:raise HTTPException(409,'قیمت یا تخفیف تغییر کرده؛ قبل از واریز با پشتیبانی بررسی کنید.')
            await mark_reseller_discount_used(s,discount,user.id)
        card=data.get('card') or {};targets=list(dict.fromkeys(([card.get('reviewer')] if card.get('reviewer') and op.kind in {'wallet_topup','panel_wallet'} else [])+settings.admin_ids+settings.owner_ids))
        async with telegram_bot() as bot:
            message=None;uploaded_to=None
            for tid in targets:
                try:
                    message=await bot.send_photo(tid,BufferedInputFile(out.getvalue(),filename='receipt.jpg'),caption=f'رسید مینی‌اپ #{op.id}',parse_mode=None)
                    uploaded_to=int(tid);break
                except Exception:pass
            if not message:raise HTTPException(503,'ارسال رسید انجام نشد؛ دوباره تلاش کنید.')
            fid=message.photo[-1].file_id;amount=data['final_amount']
            if op.kind=='reseller_package':
                pkg=await s.get(ResellerPackage,data['package_id'])
                if not pkg:raise HTTPException(409,'بسته حذف شده؛ با پشتیبانی تماس بگیرید.')
                target=ResellerTopupRequest(user_id=user.id,package_id=pkg.id,amount_irt=amount,volume_bytes=data['volume_bytes'],receipt_file_id=fid,status='pending');typ='reseller'
            elif op.kind=='reseller_wallet':
                account=await reseller_context(s,user);target=ResellerWalletReceipt(reseller_id=account.id,amount_irt=amount,file_id=fid,is_photo=True);typ='payg'
            else:
                target=Order(user_id=user.id,amount_irt=amount,payment_method='wallet_topup:all',status='waiting_receipt',receipt_file_id=fid,payment_card_id=card.get('id'),receipt_reviewer_telegram_id=card.get('reviewer'),pricing_meta={'miniapp_source':True,'panel_order_id':(data.get('request') or {}).get('panel_id')});typ='order'
            s.add(target);await s.flush();op.result={'target_type':typ,'target_id':target.id};op.status='waiting_approval';await s.commit()
            await notify_receipt(bot,typ,target,user,data['title'],amount,fid,card.get('reviewer'),uploaded_to=uploaded_to,uploaded_message_id=message.message_id,resend=False)
        return await funding_view(s,op)

@router.get('/tracking')
async def tracking(user=Depends(customer)):
    async with SessionLocal() as s:
        items=[]
        rows=(await s.execute(select(Order).where(Order.user_id==user.id,submitted_order_clause()).order_by(Order.id.desc()).limit(100))).scalars().all()
        for o in rows:
            if (o.pricing_meta or {}).get('miniapp_source') and not o.checkout_key:continue # funding copy below
            item=await order_view(s,o);item.update(track_kind='order',track_id=o.id,can_resend=o.status=='waiting_receipt' and bool(o.receipt_file_id));items.append(item)
        ops=(await s.execute(select(MiniAppOperation).where(MiniAppOperation.user_id==user.id,MiniAppOperation.kind.in_(['reseller_package','reseller_wallet','wallet_topup','panel_wallet'])).order_by(MiniAppOperation.id.desc()).limit(100))).scalars().all()
        linked={'reseller':set(),'payg':set()}
        for op in ops:
            view=await funding_view(s,op)
            if view['status'] in {'waiting_receipt','cancelled','canceled'}:continue
            view.update(track_kind='funding',track_id=op.id,can_resend=view['status']=='waiting_approval',amount_irt=view['amount']);items.append(view)
            result=op.result or {}
            if result.get('target_type') in linked:linked[result['target_type']].add(result.get('target_id'))
        rs=(await s.execute(select(ResellerTopupRequest).where(ResellerTopupRequest.user_id==user.id).order_by(ResellerTopupRequest.id.desc()).limit(100))).scalars().all()
        for req in rs:
            if req.id in linked['reseller'] or req.status in {'cancelled','canceled'} or not req.receipt_file_id:continue
            pkg=await s.get(ResellerPackage,req.package_id) if req.package_id else None
            items.append(dict(id=req.id,track_id=req.id,track_kind='reseller',status='paid' if req.status=='approved' else 'waiting_approval' if req.status=='pending' else req.status,title=pkg.title if pkg else 'خرید حجم نمایندگی',amount_irt=req.amount_irt,can_resend=req.status=='pending' and bool(req.receipt_file_id),rejection_reason=req.rejection_reason,created_at=req.created_at.isoformat()+'Z'))
        acc=await s.scalar(select(ResellerAccount).where(ResellerAccount.user_id==user.id))
        if acc:
            rows=(await s.execute(select(ResellerWalletReceipt).where(ResellerWalletReceipt.reseller_id==acc.id).order_by(ResellerWalletReceipt.id.desc()).limit(100))).scalars().all()
            for req in rows:
                if req.id in linked['payg']:continue
                items.append(dict(id=req.id,track_id=req.id,track_kind='payg',status='paid' if req.status=='approved' else 'waiting_approval' if req.status=='pending' else req.status,title='شارژ کیف پول نمایندگی',amount_irt=req.amount_irt,can_resend=req.status=='pending',rejection_reason=getattr(req,'rejection_reason',None),created_at=req.created_at.isoformat()+'Z'))
        return {'orders':sorted(items,key=lambda x:x['created_at'],reverse=True)}

@router.post('/tracking/{kind}/{oid}/resend')
async def resend(kind:str,oid:int,user=Depends(customer)):
    if kind=='order':return await resend_order(oid,user)
    async with SessionLocal() as s:
        await s.get(User,user.id,with_for_update=True)
        op=None
        if kind=='funding':
            op=await owned_funding(s,user,oid,True);view=await funding_view(s,op)
            if view['status']!='waiting_approval':raise HTTPException(409,'سفارش منتظر تأیید نیست.')
            ref=op.result;typ=ref['target_type'];rid=ref['target_id']
        elif kind in {'reseller','payg'}:typ=kind;rid=oid
        else:raise HTTPException(404,'سفارش پیدا نشد.')
        model={'reseller':ResellerTopupRequest,'payg':ResellerWalletReceipt,'order':Order}[typ]
        target=await s.get(model,rid,with_for_update=True)
        account=await s.scalar(select(ResellerAccount).where(ResellerAccount.user_id==user.id))
        if not target or (typ=='payg' and (not account or target.reseller_id!=account.id)) or (typ!='payg' and target.user_id!=user.id):raise HTTPException(404,'سفارش پیدا نشد.')
        if target.status not in {'pending','waiting_receipt'}:raise HTTPException(409,'رسید قبلاً بررسی شده است.')
        fid=target.file_id if typ=='payg' else target.receipt_file_id
        if not fid:raise HTTPException(409,'ابتدا رسید را ارسال کنید.')
        # Stable idempotency record also covers receipts originally sent in chat.
        cooldown=await s.scalar(select(MiniAppOperation).where(MiniAppOperation.key==f'reminder:{typ}:{rid}').with_for_update())
        if cooldown and datetime.utcnow()-cooldown.updated_at<timedelta(minutes=5):raise HTTPException(429,'درخواست ارسال شده؛ ۵ دقیقه بعد دوباره تلاش کنید.')
        async with telegram_bot() as bot:
            ok=await notify_receipt(bot,typ,target,user,(op.payload or {}).get('title','بررسی سفارش') if op else 'بررسی سفارش',target.amount_irt,fid,getattr(target,'receipt_reviewer_telegram_id',None))
        if not ok:raise HTTPException(503,'ارسال مجدد انجام نشد؛ دوباره تلاش کنید.')
        if not cooldown:s.add(MiniAppOperation(user_id=user.id,key=f'reminder:{typ}:{rid}',kind='reminder',status='done'))
        else:cooldown.updated_at=datetime.utcnow()
        await s.commit()
    return {'message':'رسید و درخواست بررسی مجدد برای مدیر ارسال شد.'}
