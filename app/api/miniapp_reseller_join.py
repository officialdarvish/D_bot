"""Native reseller onboarding with the same durable checkout used by Telegram."""
import io,uuid
from fastapi import APIRouter,Depends,HTTPException,File,UploadFile
from pydantic import BaseModel,Field
from sqlalchemy import select
from PIL import Image,UnidentifiedImageError
from aiogram.types import BufferedInputFile
from app.api.miniapp import customer,telegram_bot
from app.database.session import SessionLocal
from app.database.models import MiniAppOperation,User
from app.services import reseller_onboarding as flow
from app.core.config import settings
router=APIRouter(prefix='/api/miniapp/reseller-join',tags=['Reseller onboarding'])

class Purchase(BaseModel):
    key:uuid.UUID
    kind:str
    mode:str='volume'
    server_id:int=0
    package_id:int=0
    username:str=Field(default='',max_length=32)
    password:str=Field(default='',max_length=72)
    expected_amount:int=Field(default=0,ge=0)

async def owned(s,user,oid):
    op=await s.get(MiniAppOperation,oid,with_for_update=True)
    if not op or op.user_id!=user.id or op.kind!=flow.KIND:raise HTTPException(404,'درخواست پیدا نشد.')
    return op

@router.get('')
async def catalog(user=Depends(customer)):
    async with SessionLocal() as s:
        try:
            data=await flow.catalog(s,user)
            op=await s.scalar(select(MiniAppOperation).where(MiniAppOperation.user_id==user.id,MiniAppOperation.kind==flow.KIND,MiniAppOperation.status.in_(list(flow.OPEN))).order_by(MiniAppOperation.id.desc()).limit(1))
            return {**data,'order':flow.view(op) if op else None}
        except ValueError as exc:raise HTTPException(409,str(exc))

@router.post('/credentials')
async def credentials(body:Purchase,user=Depends(customer)):
    from app.services.pasarguard_panel_sales import validate_panel_password
    async with SessionLocal() as s:
        try:
            cat=await flow.catalog(s,user)
            if 'panel' not in cat['options']:raise ValueError('فروش پنل فعال نیست.')
            if not validate_panel_password(body.password):raise ValueError('رمز باید ۱۲ نویسه یا بیشتر، دو حرف کوچک، دو حرف بزرگ، دو عدد و نماد بدون فاصله داشته باشد.')
            await flow.check_panel_username(s,body.username.strip(),cat['panel_server_id'])
            return {'ok':True}
        except ValueError as exc:raise HTTPException(422,str(exc))

@router.post('/quote')
async def quote(body:Purchase,user=Depends(customer)):
    async with SessionLocal() as s:
        try:return await flow.quote(s,user,body.model_dump(exclude={'password','key','expected_amount'}))
        except ValueError as exc:raise HTTPException(409,str(exc))

@router.post('')
async def purchase(body:Purchase,user=Depends(customer)):
    async with SessionLocal() as s:
        try:
            op=await flow.checkout(s,user,str(body.key),body.model_dump(exclude={'key','expected_amount'}),body.expected_amount)
            if op.payload['amount']==0:await flow.submit(s,op,'FREE')
            await s.commit()
            if op.payload['amount']==0:
                async with telegram_bot() as bot:await flow.notify(bot,s,op)
            return flow.view(op)
        except ValueError as exc:raise HTTPException(409,str(exc))

@router.get('/{oid}')
async def status(oid:int,user=Depends(customer)):
    async with SessionLocal() as s:return flow.view(await owned(s,user,oid))

@router.post('/{oid}/cancel')
async def cancel(oid:int,user=Depends(customer)):
    async with SessionLocal() as s:
        op=await owned(s,user,oid)
        if op.status!='waiting_receipt':raise HTTPException(409,'رسید ثبت‌شده قابل لغو نیست.')
        op.status='cancelled';await s.commit();return flow.view(op)

@router.post('/{oid}/receipt')
async def receipt(oid:int,file:UploadFile=File(...),user=Depends(customer)):
    raw=await file.read(8*1024**2+1)
    if len(raw)>8*1024**2:raise HTTPException(413,'حداکثر حجم رسید ۸ مگابایت است.')
    try:
        picture=Image.open(io.BytesIO(raw))
        if picture.width*picture.height>25000000:raise ValueError()
        picture.load();picture=picture.convert('RGB');picture.thumbnail((4000,4000));out=io.BytesIO();picture.save(out,'JPEG',quality=92)
    except (OSError,ValueError,UnidentifiedImageError,Image.DecompressionBombError):raise HTTPException(422,'تصویر رسید معتبر نیست.')
    async with SessionLocal() as s:
        op=await owned(s,user,oid)
        if op.status!='waiting_receipt':return flow.view(op)
        if not settings.owner_ids:raise HTTPException(409,'شناسه مدیر ربات تنظیم نشده است.')
        async with telegram_bot() as bot:
            uploaded=await bot.send_photo(settings.owner_ids[0],BufferedInputFile(out.getvalue(),filename='receipt.jpg'))
            try:await flow.submit(s,op,uploaded.photo[-1].file_id)
            except ValueError as exc:raise HTTPException(409,str(exc))
            await s.commit()
            await flow.notify(bot,s,op,uploaded=(settings.owner_ids[0],uploaded.message_id))
        return flow.view(op)
