from dataclasses import replace
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.api import app
from app import api,services as svc
from app.config import settings
from app.schemas import OrderCreate
from test_services import setup_order


def test_digital_is_explicit_and_capability_matches_enabled_backend(db):
    merchant,_,account,_=setup_order(db)
    bot,key,_=svc.create_bot(db,merchant,'Capability connector',None)
    db.commit()
    configured=replace(settings,allow_digital_manual_receipts=True)
    with patch.object(svc,'settings',configured),patch.object(api,'settings',configured):
        with TestClient(app) as client:
            result=client.get('/api/v1/connect/capabilities',headers={'X-Darvish-Key':key})
            assert result.status_code==200 and 'digital' in result.json()['product_kinds']
            response=client.post('/api/v1/connect/orders',headers={'X-Darvish-Key':key},json={'external_order_id':'dbot:1','buyer_tg_id':2002,'product_title':'VPN','product_kind':'digital','amount_minor':1500,'currency':'USDT'})
            assert response.status_code==200,response.text
            assert response.json()['order']['product_kind']=='digital'


def test_toman_invoice_receipt_ledger_and_settlement_are_whole_toman(db):
    from app.models import ReceiveAccount
    merchant,bot,_,_=setup_order(db)
    db.add(ReceiveAccount(currency='IRT',label='Toman card',instructions='Pay exactly the Toman amount'));db.flush()
    data=OrderCreate(external_order_id='toman-1',buyer_tg_id=2002,product_title='Service',product_kind='physical',amount_minor=280000,currency='IRT')
    order,_=svc.create_order(db,bot,data)
    svc.submit_receipt(db,order.id,2002,'receipt','unique')
    svc.review_order(db,order.id,1001,True,True)
    assert order.amount_minor==280000 and order.currency=='IRT'
    assert svc.balance(db,merchant.id,'IRT')==266000
    settlement=svc.create_settlement(db,merchant,100000,'IRT','Toman bank account')
    assert settlement.amount_minor==100000 and svc.balance(db,merchant.id,'IRT')==166000
    assert svc.format_minor(280000,'IRT')=='280000'
    from app.config import CURRENCY_SCALE
    assert CURRENCY_SCALE['IRT']==0
