import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from fastapi.testclient import TestClient
from app.api import app
from app.config import settings
from app.models import ReceiveAccount, Merchant, MerchantBot
from app.security import digest_key
from app.database import SessionLocal


def init_data(user_id):
    d={'auth_date':str(int(time.time())),'user':json.dumps({'id':user_id,'first_name':'Tester'},separators=(',',':'))}
    payload='\n'.join(f'{k}={d[k]}' for k in sorted(d))
    key=hmac.new(b'WebAppData',settings.bot_token.encode(),hashlib.sha256).digest()
    d['hash']=hmac.new(key,payload.encode(),hashlib.sha256).hexdigest()
    return urlencode(d)


def test_admin_and_merchant_access_controls():
    with TestClient(app) as client:
        assert client.get('/health').status_code==200
        assert client.get('/api/v1/admin/overview').status_code==401
        headers={'X-Telegram-Init-Data':init_data(5566)}
        assert client.get('/api/v1/admin/overview',headers=headers).status_code==403
        resp=client.post('/api/v1/merchants',headers=headers,json={'name':'فروشنده آزمایشی'})
        assert resp.status_code==200
        merchant_id=resp.json()['id']
        admin_headers={'X-Telegram-Init-Data':init_data(1001)}
        assert client.get('/api/v1/admin/overview',headers=admin_headers).status_code==200
        assert client.post(f'/api/v1/admin/merchants/{merchant_id}/review',headers=admin_headers,json={'approved':True,'fee_bps':250}).status_code==200
        # Admin is not necessarily the merchant owner; owner-based read authorization remains enforced.
        assert client.get(f'/api/v1/merchants/{merchant_id}/dashboard',headers=admin_headers).status_code==404
        assert client.get(f'/api/v1/merchants/{merchant_id}/dashboard',headers=headers).status_code==200
        connector=client.post(f'/api/v1/merchants/{merchant_id}/bots',headers=headers,json={'label':'Test Merchant Bot'})
        assert connector.status_code==200
        key=connector.json()['api_key_once']
        assert key.startswith('db_')
        account=client.post('/api/v1/admin/accounts',headers=admin_headers,json={'currency':'UNIT','label':'حساب تست','instructions':'آدرس تست معتبر'})
        assert account.status_code==200
        order=client.post('/api/v1/connect/orders',headers={'X-Darvish-Key':key},json={
            'external_order_id':'test-ord-01','buyer_tg_id':2002,'product_title':'کالای حضوری',
            'product_kind':'physical','amount_minor':1500,'currency':'UNIT',
            'delivery_message':'اطلاعات تحویل حضوری'
        })
        assert order.status_code==200
        order_id=order.json()['order']['id']
        assert order.json()['order']['receiver']['label']=='حساب تست'
        duplicate=client.post('/api/v1/connect/orders',headers={'X-Darvish-Key':key},json={
            'external_order_id':'test-ord-01','buyer_tg_id':2002,'product_title':'کالای حضوری',
            'product_kind':'physical','amount_minor':1500,'currency':'UNIT',
            'delivery_message':'اطلاعات تحویل حضوری'
        })
        assert duplicate.status_code==200 and duplicate.json()['created'] is False
        assert client.get(f'/api/v1/connect/orders/{order_id}',headers={'X-Darvish-Key':'BAD'}).status_code==401
        assert client.get(f'/api/v1/buyer/orders/{order_id}',headers=headers).status_code==404
        assert client.get(f'/api/v1/buyer/orders/{order_id}',headers={'X-Telegram-Init-Data':init_data(2002)}).status_code==200
        digital=client.post('/api/v1/connect/orders',headers={'X-Darvish-Key':key},json={
            'external_order_id':'test-ord-dig','buyer_tg_id':2002,'product_title':'اشتراک دیجیتال',
            'product_kind':'digital','amount_minor':1500,'currency':'UNIT'
        })
        assert digital.status_code==422
