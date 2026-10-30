"""Owner configuration transfer, completed entirely inside Mini App."""
import uuid
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from sqlalchemy import select
from app.api.miniapp import customer,require_button,telegram_bot
from app.database.models import User,MiniAppOperation
from app.database.session import SessionLocal
from app.services.service_ownership import eligible_service,recipient_telegram_id,transfer_service_ownership,OwnershipTransferError
from app.core.config import settings

router=APIRouter(prefix='/api/miniapp/services',tags=['Mini App ownership transfer'])
KIND='ownership_transfer'

class Recipient(BaseModel):
    target_telegram_id:str=Field(min_length=1,max_length=20)

class TransferRequest(Recipient):
    key:uuid.UUID
    confirmed:bool=False

async def access(user):
    if user.telegram_id not in settings.admin_ids:raise HTTPException(403,'انتقال مالکیت فقط برای مدیر ربات مجاز است.')
    await require_button('my_services')

async def recipient(s,raw,actor):
    tid=recipient_telegram_id(raw)
    target=await s.scalar(select(User).where(User.telegram_id==tid))
    if not target:raise OwnershipTransferError('کاربر مقصد پیدا نشد؛ ابتدا باید ربات را استارت کند.')
    if target.id==actor.id:raise OwnershipTransferError('این سرویس هم‌اکنون متعلق به شماست؛ کاربر دیگری را انتخاب کنید.')
    if target.is_blocked:raise OwnershipTransferError('کاربر مقصد مسدود است.')
    return target

@router.post('/{sid}/ownership/preview')
async def preview(sid:int,body:Recipient,user=Depends(customer)):
    await access(user)
    async with SessionLocal() as s:
        try:
            svc,actor=await eligible_service(s,sid,user.telegram_id)
            target=await recipient(s,body.target_telegram_id,actor)
            return {'service_id':sid,'service_name':svc.client_username or svc.xui_email or str(sid),
                'recipient':{'telegram_id':target.telegram_id,'name':target.full_name or str(target.telegram_id),'username':target.username}}
        except OwnershipTransferError as exc:raise HTTPException(409,str(exc))

@router.post('/{sid}/ownership')
async def transfer(sid:int,body:TransferRequest,user=Depends(customer)):
    await access(user)
    if not body.confirmed:raise HTTPException(409,'انتقال مالکیت را تأیید کنید.')
    async with SessionLocal() as s:
        await s.get(User,user.id,with_for_update=True)
        try:tid=recipient_telegram_id(body.target_telegram_id)
        except OwnershipTransferError as exc:raise HTTPException(422,str(exc))
        payload={'service_id':sid,'target_telegram_id':tid}
        op=await s.scalar(select(MiniAppOperation).where(MiniAppOperation.key==str(body.key)))
        if op:
            if op.user_id!=user.id or op.kind!=KIND or op.payload!=payload:raise HTTPException(409,'این شناسه برای درخواست دیگری استفاده شده است.')
            return op.result
        try:result=await transfer_service_ownership(s,sid,user.telegram_id,tid)
        except OwnershipTransferError as exc:raise HTTPException(409,str(exc))
        op=MiniAppOperation(user_id=user.id,key=str(body.key),kind=KIND,status='done',payload=payload,
            result={'service_id':sid,'service_name':result.service_name,'target_telegram_id':tid,'transferred':True,'recipient_notified':False})
        s.add(op)
        # The transfer, audit and idempotency record commit together. A Telegram
        # delivery failure must never roll back or repeat ownership changes.
        await s.commit();oid=op.id;response=dict(op.result)
    notified=False
    try:
        from app.bot.handlers.public.my_services import _notify_ownership_recipient
        async with telegram_bot() as bot:notified=await _notify_ownership_recipient(bot,result)
    except Exception:
        import logging
        logging.getLogger(__name__).warning('Ownership recipient notification unavailable service=%s',sid)
    response['recipient_notified']=notified
    async with SessionLocal() as s:
        op=await s.get(MiniAppOperation,oid);op.result=response;await s.commit()
    return response
