"""Archive an unapproved receipt from the inbox without deleting financial data."""
import json
from datetime import datetime
from sqlalchemy import select, exists, literal, cast, String
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from app.core.config import settings
from app.database.models import Setting, Order, ResellerTopupRequest, PasarGuardPanelOrder
from app.services.receipt_status import ORDER_RECEIPT_OPEN_STATUSES, PANEL_RECEIPT_OPEN_STATUSES

PREFIX='receipt_inbox_archived:'
MODELS={'order':(Order,ORDER_RECEIPT_OPEN_STATUSES),'panel':(PasarGuardPanelOrder,PANEL_RECEIPT_OPEN_STATUSES),'reseller':(ResellerTopupRequest,('pending',))}


def visible_receipt(kind, model):
    key=literal(PREFIX+kind+':')+cast(model.id,String)
    return ~exists(select(Setting.key).where(Setting.key==key))


async def is_archived(session,kind,ident):
    return await session.get(Setting,f'{PREFIX}{kind}:{ident}') is not None


async def archive_receipt(session,kind,ident,actor):
    if actor not in settings.admin_ids:
        raise ValueError('حذف رسید از فهرست فقط برای مدیر اصلی مجاز است.')
    if kind not in MODELS or ident<=0:raise ValueError('شناسه رسید معتبر نیست.')
    model,statuses=MODELS[kind]
    item=await session.scalar(select(model).where(model.id==ident).with_for_update())
    if not item or item.status not in statuses:
        raise ValueError('رسید دیگر در انتظار بررسی نیست؛ فهرست را بروزرسانی کنید.')
    if item.status in ('processing','delivery_pending'):
        raise ValueError('این درخواست در حال پردازش یا ارسال سرویس است؛ پس از پایان عملیات دوباره بررسی کنید.')
    values={'key':f'{PREFIX}{kind}:{ident}','value':json.dumps({
        'kind':kind,'request_id':ident,'user_id':item.user_id,'status':item.status,
        'actor_telegram_id':actor,'at':datetime.utcnow().isoformat(),
    },separators=(',',':'))}
    insert=sqlite_insert if session.get_bind().dialect.name=='sqlite' else pg_insert
    result=await session.execute(insert(Setting).values(**values).on_conflict_do_nothing(index_elements=['key']))
    return result.rowcount==1
