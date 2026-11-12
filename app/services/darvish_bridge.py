"""Darvish Bridge invoice connector. Approval is verified against the remote ledger.

Amounts are integer currency minor units. Pending orders retain encrypted
connection credentials so changing admin settings never misroutes old webhooks.
"""
import hashlib,hmac,json,re,time
from datetime import datetime
from urllib.parse import urlsplit
import httpx
from sqlalchemy import select
from app.core.security import encrypt_text,decrypt_text
from app.database.models import Setting,Order,User,Plan

KEY='darvish_bridge_config'
SCALES={'IRT':0}


async def config(session):
    row=await session.get(Setting,KEY)
    if not row:return {'enabled':False,'currency':'IRT'}
    value=json.loads(decrypt_text(row.value))
    if value.get('currency')!='IRT':
        return {**value,'enabled':False,'currency':'IRT','requires_toman_setup':True}
    return value


def normalize(value,previous=None):
    result={**(previous or {}),**{k:value[k] for k in ('url','bot_username','currency','enabled') if k in value}}
    for key in ('key','secret'):
        if value.get(key):result[key]=str(value[key]).strip()
    result.pop('requires_toman_setup',None)
    result.setdefault('currency','IRT')
    result['enabled']=result.get('enabled') in (True,'1',1)
    result['url']=str(result.get('url','')).strip().rstrip('/')
    result['bot_username']=str(result.get('bot_username','')).strip().lstrip('@')
    if result.get('currency') not in SCALES:raise ValueError('Bridge payments must use Toman (IRT)')
    if not result['url'] and not result['enabled']:return result
    parsed=urlsplit(result['url'])
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:raise ValueError('Bridge URL must be HTTPS')
    if not re.fullmatch(r'[A-Za-z0-9_]{5,32}',result['bot_username']):raise ValueError('Invalid Bridge bot username')
    if result['enabled'] and (not result.get('key') or len(result.get('secret',''))<24):raise ValueError('Bridge API key and webhook secret are required')
    return result


async def request(connection,method,path,**kwargs):
    async with httpx.AsyncClient(timeout=httpx.Timeout(15,connect=8),follow_redirects=False) as client:
        response=await client.request(method,connection['url']+'/api/v1/connect'+path,headers={'X-Darvish-Key':connection['key']},**kwargs)
        if response.status_code>=300:raise ValueError(f'Bridge request failed ({response.status_code})')
        return response.json()


async def quote(session,amount):
    connection=await config(session)
    if not connection.get('enabled'):return None
    if connection.get('currency')!='IRT':raise ValueError('Bridge payments must use Toman (IRT)')
    if type(amount) is not int or amount<=0 or amount>10**16:raise ValueError('Bridge amount is outside supported limits')
    return {'amount_minor':amount,'currency':'IRT','scale':0,'display':f'{amount:,} Toman','connection':connection}


def public_quote(value):return {k:v for k,v in value.items() if k!='connection'} if value else None


def pending_meta(quotation,title):
    return {'bridge_connection':encrypt_text(json.dumps(quotation['connection'])),'bridge_amount_minor':quotation['amount_minor'],'bridge_currency':quotation['currency'],'bridge_display':quotation['display'],'bridge_title':title}


def order_connection(order):return json.loads(decrypt_text(order.pricing_meta['bridge_connection']))


def validate_invoice(order,user,invoice):
    meta=order.pricing_meta or {}
    if (str(invoice.get('external_order_id'))!=f'dbot:{order.id}' or int(invoice.get('amount_minor',-1))!=meta['bridge_amount_minor'] or invoice.get('currency')!=meta['bridge_currency'] or int(invoice.get('buyer_tg_id',0))!=user.telegram_id or invoice.get('product_kind')!='digital'):
        raise ValueError('Bridge invoice does not match this purchase')


async def ensure_invoice(session,order):
    meta=dict(order.pricing_meta or {})
    if meta.get('bridge_invoice_id'):return order
    if order.status!='waiting_bridge':raise ValueError('Order is not waiting for Bridge payment')
    user=await session.get(User,order.user_id)
    result=await request(order_connection(order),'POST','/orders',json={'external_order_id':f'dbot:{order.id}','buyer_tg_id':user.telegram_id,'product_title':meta['bridge_title'],'product_kind':'digital','amount_minor':meta['bridge_amount_minor'],'currency':meta['bridge_currency']})
    invoice=result['order'];validate_invoice(order,user,invoice)
    invoice_id=str(invoice.get('id',''))
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',invoice_id):raise ValueError('Invalid Bridge invoice ID')
    order.pricing_meta={**meta,'bridge_invoice_id':invoice_id,'bridge_url':f'https://t.me/{order_connection(order)["bot_username"]}?start=order_{invoice_id}'}
    await session.commit()
    return order


def verify_signature(connection,raw,timestamp,signature):
    try:
        if abs(time.time()-int(timestamp))>300:raise ValueError
        expected=hmac.new(connection['secret'].encode(),timestamp.encode()+b'.'+raw,hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected,signature):raise ValueError
    except (ValueError,TypeError,KeyError):raise ValueError('Invalid Bridge signature') from None


async def receive_event(session,raw,timestamp,signature,event_id):
    if len(raw)>16384:raise ValueError('Webhook too large')
    data=json.loads(raw)
    external=str(data.get('external_order_id',''))
    if not re.fullmatch(r'dbot:[1-9][0-9]{0,17}',external):raise ValueError('Invalid external order ID')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,72}',event_id or '') or data.get('event_id')!=event_id:raise ValueError('Invalid Bridge event ID')
    order=await session.get(Order,int(external[5:]),with_for_update=True)
    if not order or not (order.pricing_meta or {}).get('bridge_connection'):raise ValueError('Bridge order not found')
    connection=order_connection(order);verify_signature(connection,raw,timestamp,signature)
    seen='bridge_event:'+event_id
    if await session.get(Setting,seen):return {'ok':True,'duplicate':True}
    meta=order.pricing_meta or {}
    if str(data.get('order_id',''))!=str(meta.get('bridge_invoice_id','')):raise ValueError('Bridge invoice ID mismatch')
    user=await session.get(User,order.user_id)
    remote=await request(connection,'GET','/orders/'+meta['bridge_invoice_id'])
    validate_invoice(order,user,remote)
    if str(remote.get('id',''))!=meta['bridge_invoice_id'] or data.get('amount_minor')!=remote['amount_minor'] or data.get('currency')!=remote['currency']:raise ValueError('Bridge amount mismatch')
    event=data.get('event')
    if event=='order.approved':
        if remote['status'] not in {'fulfillment_pending','fulfilled','delivery_failed'}:raise ValueError('Bridge has not verified this payment')
        if order.status=='waiting_bridge':
            order.status='miniapp_queued'
            order.pricing_meta={**meta,'miniapp_submitted_at':datetime.utcnow().isoformat()}
    elif event=='order.rejected':
        if remote['status']!='rejected':raise ValueError('Rejection not verified')
        if order.status=='waiting_bridge':
            order.status='rejected';order.rejection_reason=str(data.get('reason') or 'Bridge receipt rejected')[:500]
            from app.services.discount_service import release_order_discount_usage
            await release_order_discount_usage(session,order_id=order.id,user_id=user.id,code=meta.get('discount_code'),source='renew' if meta.get('miniapp_renewal') else 'buy')
    else:raise ValueError('Unsupported Bridge event')
    session.add(Setting(key=seen,value=str(order.id)))
    await session.commit()
    return {'ok':True}


async def report_deliveries(session):
    rows=(await session.execute(select(Order).where(Order.status=='paid',Order.pricing_meta['miniapp_method'].as_string()=='bridge',Order.pricing_meta['buyer_delivery_done'].as_boolean().is_(True),Order.pricing_meta['bridge_delivery_reported'].as_boolean().is_not(True)).order_by(Order.id).limit(100))).scalars().all()
    for order in rows:
        meta=order.pricing_meta or {}
        if meta.get('bridge_delivery_reported') or not meta.get('buyer_delivery_done') or not meta.get('bridge_invoice_id'):continue
        try:
            await request(order_connection(order),'POST',f'/orders/{meta["bridge_invoice_id"]}/delivery',json={'status':'fulfilled','message':'D BOT delivered the service to the buyer'})
            order.pricing_meta={**meta,'bridge_delivery_reported':True};await session.commit()
        except Exception:
            import logging;logging.getLogger(__name__).warning('Bridge delivery report pending for order %s',order.id)
