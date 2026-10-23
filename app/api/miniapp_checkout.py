"""Native Mini App purchases; existing receipt reviewers and provisioning remain authoritative."""
import asyncio
import io
import logging
import uuid
from datetime import datetime,timedelta
from PIL import Image,UnidentifiedImageError
from fastapi import APIRouter,Depends,HTTPException,UploadFile,File,Response
from pydantic import BaseModel,Field
from sqlalchemy import select,func
from app.api.miniapp import customer,require_button,telegram_bot,service_data
from app.database.session import SessionLocal
from app.database.models import User,Order,Plan,Server,PaymentCard,ClientService,WalletTransaction,DiscountCode
from app.services.miniapp_catalog import public_plans
from app.services.live_pricing import quote_plan,LivePricingError
from app.services.discount_service import apply_discount_amount,mark_discount_used,release_order_discount_usage,order_discount_usage_source
from app.core.security import encrypt_text
from app.core.config import settings

router=APIRouter(prefix='/api/miniapp',tags=['Mini App checkout'])
log=logging.getLogger(__name__)

class QuoteInput(BaseModel):
    plan_id:int=Field(gt=0)
    service_id:int|None=Field(default=None,gt=0)
    username:str=Field(min_length=1,max_length=32)
    password:str=Field(default='',max_length=128)
    discount_code:str=Field(default='',max_length=64)

class CheckoutInput(QuoteInput):
    key:uuid.UUID
    method:str
    expected_amount_irt:int=Field(ge=0)

async def validate_purchase(s,user,body,*,lock_discount=False):
    from app.bot.handlers.public.buy import normalize_service_username,get_service_username_error,valid_mikrotik_password
    rows=await public_plans(s)
    row=next((r for r in rows if r[0].id==body.plan_id),None)
    if not row:raise HTTPException(404,'این تعرفه دیگر قابل خرید نیست.')
    plan,server,_=row
    username=normalize_service_username(body.username)
    if body.service_id:
        from app.api.miniapp import owned_service
        svc=await owned_service(s,user,body.service_id)
        if svc.server_id!=server.id:raise HTTPException(409,'تعرفه تمدید باید متعلق به همان پنل اشتراک باشد.')
        username=svc.client_username or svc.xui_email
    else:
        try:error=await get_service_username_error(s,server,username)
        except RuntimeError:raise HTTPException(503,'بررسی نام در پنل ناموفق بود؛ کمی بعد دوباره تلاش کنید.')
        if error:raise HTTPException(409,error)
    if not body.service_id and server.server_type=='mikrotik' and not valid_mikrotik_password(body.password):
        raise HTTPException(422,'رمز کانفیگ را بدون فاصله وارد کنید.')
    try:quote=await quote_plan(plan)
    except LivePricingError:raise HTTPException(503,'دریافت قیمت لحظه‌ای ناموفق بود؛ دوباره تلاش کنید.')
    code=body.discount_code.strip().upper().replace(' ','')
    if lock_discount and code:
        await s.scalar(select(DiscountCode).where(func.upper(DiscountCode.code)==code).with_for_update())
    amount,error,discount=await apply_discount_amount(s,code,quote.amount_irt,user.id,'renew' if body.service_id else 'buy',server.id)
    if error:raise HTTPException(409,error)
    card=await s.scalar(select(PaymentCard).where(PaymentCard.server_id==server.id,PaymentCard.is_active.is_(True)).order_by(PaymentCard.id.desc()).limit(1))
    if not card:
        card=await s.scalar(select(PaymentCard).where(PaymentCard.server_type==server.server_type,PaymentCard.server_id.is_(None),PaymentCard.is_active.is_(True)).order_by(PaymentCard.id.desc()).limit(1))
    return plan,server,username,quote,amount,discount,card,code

@router.get('/services/{sid}/renewal-plans')
async def renewal_plans(sid:int,user=Depends(customer)):
    await require_button('my_services')
    from app.api.miniapp import owned_service
    from app.services.miniapp_catalog import public_catalog
    async with SessionLocal() as s:
        svc=await owned_service(s,user,sid)
        allowed={p.id for p,server,_ in await public_plans(s) if server.id==svc.server_id}
        catalog=await public_catalog(s)
        catalog['plans']=[p for p in catalog['plans'] if p['id'] in allowed]
        catalog['categories']=[{**c,'plan_ids':[pid for pid in c['plan_ids'] if pid in allowed]} for c in catalog['categories'] if any(pid in allowed for pid in c['plan_ids'])]
        return {**catalog,'username':svc.client_username or svc.xui_email,'service_id':sid}

@router.post('/checkout/quote')
async def quote_checkout(body:QuoteInput,user=Depends(customer)):
    await require_button('my_services' if body.service_id else 'buy')
    async with SessionLocal() as s:
        plan,server,name,quote,amount,discount,card,code=await validate_purchase(s,user,body)
        balance=int((await s.get(User,user.id)).wallet_balance or 0)
    return dict(amount_irt=amount,base_amount_irt=quote.amount_irt,username=name,plan_title=plan.title,
        balance=balance,methods=['wallet']+(['card'] if card else []),pricing=quote.as_meta())

async def order_view(s,order):
    plan=await s.get(Plan,order.plan_id) if order.plan_id else None
    meta=order.pricing_meta or {}
    service=await s.get(ClientService,order.service_id) if order.status=='paid' and order.service_id else None
    server=await s.get(Server,service.server_id) if service else None
    return dict(id=order.id,plan_id=order.plan_id,provider=(order.pricing_meta or {}).get('miniapp_provider','xui'),status=order.status,amount_irt=order.amount_irt,username=(service.client_username if service and service.user_id==order.user_id else meta.get('miniapp_username','')),
        title=plan.title if plan else '',method=meta.get('miniapp_method') or ('wallet' if (order.payment_method or '').startswith('wallet') else 'card'),renewal_service_id=meta.get('miniapp_renewal'),
        receipt_uploaded=bool(order.receipt_file_id),card=meta.get('miniapp_card') if order.status=='waiting_receipt' else None,
        created_at=order.created_at.isoformat()+'Z',rejection_reason=order.rejection_reason,
        service=service_data(service,plan,server) if service and service.user_id==order.user_id else None, key=order.checkout_key)

@router.post('/checkout')
async def checkout(body:CheckoutInput,user=Depends(customer)):
    await require_button('my_services' if body.service_id else 'buy')
    if body.method not in {'wallet','card'}:raise HTTPException(422,'روش پرداخت معتبر نیست.')
    async with SessionLocal() as s:
        locked=await s.get(User,user.id,with_for_update=True)
        if not locked or locked.is_blocked:raise HTTPException(403,'حساب در دسترس نیست.')
        previous=await s.scalar(select(Order).where(Order.checkout_key==str(body.key)))
        if previous:
            if previous.user_id!=user.id:raise HTTPException(409,'شناسهٔ عملیات معتبر نیست.')
            if previous.plan_id!=body.plan_id or (previous.pricing_meta or {}).get('miniapp_renewal')!=body.service_id or ((previous.pricing_meta or {}).get('miniapp_method') or ('wallet' if (previous.payment_method or '').startswith('wallet:') else 'card'))!=body.method or (previous.pricing_meta or {}).get('miniapp_username','').lower()!=body.username.strip().lower():
                raise HTTPException(409,'این عملیات قبلاً ثبت شده است؛ سفارش قبلی را پیگیری یا خرید جدید را انتخاب کنید.')
            return await order_view(s,previous)
        count=await s.scalar(select(func.count(Order.id)).where(Order.user_id==user.id,Order.checkout_key.is_not(None),Order.status.in_(['waiting_receipt','miniapp_queued','processing'])))
        if count>=10:raise HTTPException(409,'ابتدا سفارش‌های باز قبلی را تکمیل یا لغو کنید.')
        plan,server,name,quote,amount,discount,card,code=await validate_purchase(s,user,body,lock_discount=True)
        if amount!=body.expected_amount_irt:raise HTTPException(409,'قیمت تغییر کرده است؛ مبلغ جدید را دوباره بررسی کنید.')
        if body.method=='wallet' and int(locked.wallet_balance or 0)<amount:raise HTTPException(409,'موجودی کیف پول کافی نیست؛ کارت به کارت را انتخاب کنید.')
        if body.method=='card' and not card:raise HTTPException(409,'کارت پرداخت فعالی برای این تعرفه ثبت نشده است.')
        meta={**quote.as_meta(),'final_amount_irt':amount,'discount_code':code,'miniapp_username':name,'miniapp_source':True,'miniapp_provider':server.server_type,'miniapp_method':body.method,'miniapp_renewal':body.service_id}
        if not body.service_id and server.server_type=='mikrotik':meta['miniapp_password']=encrypt_text(body.password)
        if body.method=='card':meta['miniapp_card']={'number':card.card_number,'owner':card.owner_name}
        order=Order(user_id=user.id,plan_id=plan.id,amount_irt=amount,service_id=body.service_id,payment_method=(f'renew:{body.service_id}' if body.service_id else f'{body.method}:{name}')+(f':discount:{code}' if code else ''),
            status='miniapp_queued' if body.method=='wallet' else 'waiting_receipt',checkout_key=str(body.key),pricing_meta=meta,
            payment_card_id=card.id if body.method=='card' else None,
            receipt_reviewer_telegram_id=card.reviewer_telegram_id if body.method=='card' and card.reviewer_telegram_id else None)
        s.add(order);await s.flush()
        await mark_discount_used(s,discount,user.id,order_discount_usage_source(order.id,'renew' if body.service_id else 'buy'))
        if body.method=='wallet':
            locked.wallet_balance=int(locked.wallet_balance or 0)-amount
            s.add(WalletTransaction(user_id=user.id,amount_irt=-amount,tx_type='purchase',description=f'Mini App purchase #{order.id}'))
        await s.commit()
        return await order_view(s,order)

async def owned_order(s,user,oid,*,lock=False):
    order=await s.get(Order,oid,with_for_update=lock)
    if not order or order.user_id!=user.id or not order.checkout_key:raise HTTPException(404,'سفارش پیدا نشد.')
    return order

@router.get('/checkout/orders')
async def orders(user=Depends(customer)):
    async with SessionLocal() as s:
        rows=(await s.execute(select(Order).where(Order.user_id==user.id,Order.checkout_key.is_not(None)).order_by(Order.id.desc()).limit(20))).scalars().all()
        return {'orders':[await order_view(s,o) for o in rows]}

@router.get('/orders/latest')
async def latest_order(user=Depends(customer)):
    # Include chat purchases as well as native Mini App orders.
    async with SessionLocal() as s:
        order=await s.scalar(select(Order).where(Order.user_id==user.id).order_by(Order.id.desc()).limit(1))
        return {'order':await order_view(s,order) if order else None}

@router.post('/orders/{oid}/resend')
async def resend_order(oid:int,user=Depends(customer)):
    from aiogram.types import InlineKeyboardMarkup,InlineKeyboardButton
    from app.bot.handlers.public.buy import order_receipt_targets
    from app.bot.payment_audit import order_summary
    async with SessionLocal() as s:
        order=await s.get(Order,oid,with_for_update=True)
        if not order or order.user_id!=user.id:raise HTTPException(404,'سفارش پیدا نشد.')
        if order.status!='waiting_receipt' or not order.receipt_file_id:
            raise HTTPException(409,'فقط سفارش دارای رسید و منتظر تأیید قابل ارسال مجدد است.')
        meta=dict(order.pricing_meta or {})
        now=datetime.utcnow()
        try:last=datetime.fromisoformat(meta.get('miniapp_resent_at',''))
        except (ValueError,TypeError):last=None
        if last and (now-last).total_seconds()<300:
            raise HTTPException(429,'درخواست قبلی ارسال شده است؛ ۵ دقیقه بعد دوباره تلاش کنید.')
        plan=await s.get(Plan,order.plan_id) if order.plan_id else None
        service=await s.get(ClientService,order.service_id) if order.service_id else None
        sid=service.server_id if service else plan.server_id if plan else None
        server=await s.get(Server,sid) if sid else None
        text=order_summary(order,user,plan,server,service,event='🔄 درخواست مجدد بررسی سفارش')
        prefix='wallet_topup' if (order.payment_method or '').startswith('wallet_topup:') else 'order'
        kb=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text='✅ تایید رسید',callback_data=f'{prefix}:approve:{order.id}'),
            InlineKeyboardButton(text='❌ رد رسید',callback_data=f'{prefix}:reject:{order.id}')]])
        targets=list(dict.fromkeys(order_receipt_targets(order)+list(settings.admin_ids)+list(settings.owner_ids)))
        delivered=False
        async with telegram_bot() as bot:
            for tid in targets:
                try:
                    await bot.send_photo(tid,order.receipt_file_id,caption=f'🧾 ارسال مجدد سفارش #{order.id}',parse_mode=None)
                    await bot.send_message(tid,text,parse_mode='HTML',reply_markup=kb)
                    delivered=True
                except Exception:log.warning('Order reminder failed order=%s target=%s',order.id,tid)
        if not delivered:raise HTTPException(503,'ارسال مجدد انجام نشد؛ کمی بعد دوباره تلاش کنید.')
        meta['miniapp_resent_at']=now.isoformat();order.pricing_meta=meta
        await s.commit()
        return {'order':await order_view(s,order),'message':'سفارش برای بررسی مجدد ارسال شد.'}

@router.get('/checkout/orders/{oid}')
async def get_order(oid:int,user=Depends(customer)):
    async with SessionLocal() as s:return await order_view(s,await owned_order(s,user,oid))

@router.post('/checkout/orders/{oid}/cancel')
async def cancel_order(oid:int,user=Depends(customer)):
    async with SessionLocal() as s:
        order=await owned_order(s,user,oid,lock=True)
        if order.status=='cancelled':return await order_view(s,order)
        if order.status!='waiting_receipt' or order.receipt_file_id:raise HTTPException(409,'این سفارش دیگر قابل لغو نیست.')
        await release_order_discount_usage(s,order_id=order.id,user_id=user.id,code=(order.pricing_meta or {}).get('discount_code'),source='buy')
        order.status='cancelled';await s.commit()
        return await order_view(s,order)

@router.post('/checkout/orders/{oid}/receipt')
async def receipt(oid:int,file:UploadFile=File(...),user=Depends(customer)):
    from aiogram.types import BufferedInputFile,InlineKeyboardMarkup,InlineKeyboardButton
    from app.bot.handlers.public.buy import order_receipt_targets
    async with SessionLocal() as s:
        order=await owned_order(s,user,oid,lock=True)
        await require_button('my_services' if (order.pricing_meta or {}).get('miniapp_renewal') else 'buy')
        if order.receipt_file_id:return await order_view(s,order)
        if order.status!='waiting_receipt':raise HTTPException(409,'این سفارش در مرحلهٔ دریافت رسید نیست.')
        raw=await file.read(8*1024*1024+1)
        if len(raw)>8*1024*1024:raise HTTPException(413,'حجم عکس رسید باید کمتر از ۸ مگابایت باشد.')
        try:
            image=Image.open(io.BytesIO(raw))
            if image.width*image.height>25000000:raise ValueError()
            image.load();image=image.convert('RGB');image.thumbnail((4000,4000))
            if max(image.size)>min(image.size)*20:raise ValueError()
            output=io.BytesIO();image.save(output,'JPEG',quality=92);payload=output.getvalue()
        except (UnidentifiedImageError,OSError,ValueError,Image.DecompressionBombError):raise HTTPException(422,'عکس رسید معتبر نیست؛ عکس JPG یا PNG ارسال کنید.')
        plan=await s.get(Plan,order.plan_id);server=await s.get(Server,plan.server_id) if plan else None
        text=(f'🧾 رسید خرید مینی‌اپ #{order.id}\n📅 تاریخ خرید: {order.created_at}\n'
            f'👤 نام: {user.full_name or "-"}\n🔢 آیدی عددی: {user.telegram_id}\n🆔 یوزرنیم تلگرام: @{user.username or "-"}\n'
            f'👥 نام کانفیگ: {(order.pricing_meta or {}).get("miniapp_username")}\n📦 تعرفه: {plan.title if plan else "-"}\n'
            f'🖥 سرور: {server.name if server else "-"}\n💰 مبلغ: {order.amount_irt:,} تومان\n'
            f'🏷 کد تخفیف: {(order.pricing_meta or {}).get("discount_code") or "ندارد"}')
        caption=text[:1000]
        targets=list(dict.fromkeys(order_receipt_targets(order)+list(settings.admin_ids)))
        message=None;primary=None
        async with telegram_bot() as bot:
            for tid in targets:
                try:
                    message=await bot.send_photo(tid,BufferedInputFile(payload,filename='receipt.jpg'),caption=caption,parse_mode=None);primary=tid;break
                except Exception:log.warning('Receipt upload delivery failed order=%s target=%s',order.id,tid)
            if not message:raise HTTPException(503,'ارسال رسید به مسئول فروش ناموفق بود؛ دوباره تلاش کنید.')
            order.receipt_file_id=message.photo[-1].file_id
            await s.commit()
            kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='✅ تایید رسید',callback_data=f'order:approve:{order.id}'),InlineKeyboardButton(text='❌ رد رسید',callback_data=f'order:reject:{order.id}')]])
            try:await bot.edit_message_reply_markup(chat_id=primary,message_id=message.message_id,reply_markup=kb)
            except Exception:log.warning('Receipt keyboard pending; inbox remains available order=%s',order.id)
            # Selected sellers are the primary reviewers; owners retain fallback access.
            for tid in targets:
                if tid==primary:continue
                try:await bot.send_photo(tid,order.receipt_file_id,caption=caption,reply_markup=kb,parse_mode=None)
                except Exception:pass
        return await order_view(s,order)

async def process_wallet_queue():
    from app.bot.handlers.public.buy import process_approved_order_background
    async with SessionLocal() as s:
        ids=(await s.execute(select(Order.id).where(Order.checkout_key.is_not(None),Order.status=='miniapp_queued').order_by(Order.id).limit(10))).scalars().all()
    for oid in ids:
        async with SessionLocal() as s:
            order=await s.get(Order,oid,with_for_update=True)
            if not order or order.status!='miniapp_queued':continue
            order.status='processing'
            order.pricing_meta={**(order.pricing_meta or {}),'miniapp_processing_at':datetime.utcnow().isoformat()}
            await s.commit()
        try:
            async with telegram_bot() as bot:
                aid=settings.admin_ids[0] if settings.admin_ids else None
                mid=None
                if aid:
                    try:
                        notice=await bot.send_message(aid,f'💳 خرید از کیف پول در مینی‌اپ · سفارش #{oid}\nساخت کانفیگ در حال انجام است.')
                        mid=notice.message_id
                    except Exception:pass
                await process_approved_order_background(oid,bot,admin_chat_id=aid,admin_receipt_chat_id=aid,admin_receipt_message_id=mid)
        except Exception:log.exception('Native wallet order requires owner review id=%s',oid)

async def recover_stalled_wallet_orders():
    """An interrupted remote mutation needs owner review, never blind re-provisioning."""
    from aiogram.types import InlineKeyboardMarkup,InlineKeyboardButton
    async with SessionLocal() as s:
        ids=(await s.execute(select(Order.id).where(Order.checkout_key.is_not(None),Order.status=='processing',(Order.payment_method.like('wallet:%') | ((Order.pricing_meta['miniapp_method'].as_string()=='wallet') & Order.payment_method.like('renew:%')))))).scalars().all()
    for oid in ids:
        async with SessionLocal() as s:
            order=await s.get(Order,oid,with_for_update=True)
            if not order or order.status!='processing':continue
            meta=dict(order.pricing_meta or {})
            try:started=datetime.fromisoformat(meta.get('miniapp_processing_at',''))
            except ValueError:started=order.created_at
            if not started or datetime.utcnow()-started<timedelta(minutes=15):continue
            order.status='failed';order.pricing_meta={**meta,'miniapp_needs_review':True}
            await s.commit()
        try:
            async with telegram_bot() as bot:
                kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='پس از بررسی پنل: تلاش مجدد ساخت',callback_data=f'order:approve:{oid}')]])
                for aid in settings.admin_ids:
                    try:await bot.send_message(aid,f'⚠️ خرید کیف پول مینی‌اپ #{oid} به بررسی نیاز دارد.\nپیش از تلاش مجدد، وجود کانفیگ را در پنل بررسی کنید. برای جلوگیری از ساخت تکراری، این سفارش خودکار تکرار نمی‌شود.',reply_markup=kb)
                    except Exception:pass
        except Exception:log.exception('Interrupted checkout notification failed id=%s',oid)

async def worker_loop():
    while True:
        try:
            from app.api.miniapp_actions import process_operations,recover_operations
            await recover_operations()
            await process_operations()
            await recover_stalled_wallet_orders()
            await process_wallet_queue()
        except Exception:log.exception('Native checkout queue failed')
        await asyncio.sleep(5)
