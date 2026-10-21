"""Administrator-owned client tutorials and QR artwork, stored in the database."""
import base64
import io
import json
import logging
from sqlalchemy.exc import SQLAlchemyError
import uuid
from urllib.parse import urlsplit
from PIL import Image, ImageOps
from app.database.models import Setting
def SessionLocal():
    from app.database.session import SessionLocal as factory
    return factory()

APPS_KEY='client_tutorial_apps'
BACKGROUND_KEY='qr_card_background_png'
PLATFORMS={'android':'اندروید','ios':'iOS','windows':'ویندوز'}


def normalize_apps(value):
    if not isinstance(value,list) or len(value)>60:raise ValueError('حداکثر ۶۰ برنامه مجاز است.')
    result=[];seen=set()
    for item in value:
        if not isinstance(item,dict):raise ValueError('اطلاعات برنامه معتبر نیست.')
        row={k:str(item.get(k) or '').strip() for k in ('id','platform','name','download_url','text')}
        enabled=item.get('enabled',True)
        if enabled not in (True,False,0,1,'0','1'):raise ValueError('وضعیت نمایش برنامه معتبر نیست.')
        row['enabled']=enabled in (True,1,'1')
        if not any(row[k] for k in ('name','download_url','text')):continue
        if not row['name'] or len(row['name'])>60 or row['platform'] not in PLATFORMS:raise ValueError('نام و سیستم‌عامل برنامه را مشخص کنید.')
        if len(row['text'])>12000 or len(row['download_url'])>2048:raise ValueError('متن یا لینک بیش از حد طولانی است.')
        if row['download_url']:
            url=urlsplit(row['download_url'])
            if url.scheme not in {'http','https'} or not url.hostname or url.username or url.password or any(c.isspace() for c in row['download_url']):raise ValueError('لینک دانلود باید HTTP یا HTTPS معتبر باشد.')
        row['id']=row['id'] or uuid.uuid4().hex[:12]
        if not row['id'].isalnum() or len(row['id'])>24 or row['id'] in seen:raise ValueError('شناسه برنامه نامعتبر یا تکراری است.')
        seen.add(row['id']);result.append(row)
    return result


async def load_apps(session=None):
    if session is None:
        async with SessionLocal() as s:return await load_apps(s)
    row=await session.get(Setting,APPS_KEY)
    return json.loads(row.value) if row else []


async def save_apps(apps,session=None):
    value=json.dumps(normalize_apps(apps),ensure_ascii=False)
    if session is None:
        async with SessionLocal() as s:
            await s.merge(Setting(key=APPS_KEY,value=value));await s.commit()
    else:await session.merge(Setting(key=APPS_KEY,value=value))


def normalize_background(raw):
    if len(raw)>5*1024**2:raise ValueError('حجم تصویر باید حداکثر ۵ مگابایت باشد.')
    with Image.open(io.BytesIO(raw)) as im:
        if im.width*im.height>20_000_000:raise ValueError('ابعاد تصویر بیش از حد بزرگ است.')
        image=ImageOps.fit(ImageOps.exif_transpose(im).convert('RGB'),(1080,1350))
        out=io.BytesIO();image.save(out,format='PNG',optimize=True)
    return base64.b64encode(out.getvalue()).decode('ascii')


async def background_bytes():
    try:
        async with SessionLocal() as s:
            row=await s.get(Setting,BACKGROUND_KEY)
            return base64.b64decode(row.value,validate=True) if row and row.value else None
    except (SQLAlchemyError,ValueError):
        logging.getLogger(__name__).warning('QR artwork unavailable; using default background')
        return None
