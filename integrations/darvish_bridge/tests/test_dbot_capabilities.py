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
