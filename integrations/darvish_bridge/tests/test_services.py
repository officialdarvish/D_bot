import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from fastapi import HTTPException
from sqlalchemy import select, func
from app import services as svc
from app import security
from app.models import Merchant, MerchantBot, ReceiveAccount, Order, LedgerRow, Receipt, Settlement
from app.schemas import OrderCreate
from app.config import settings


def setup_order(db, kind='physical'):
    m = Merchant(owner_tg_id=22334, name='فروشگاه تست', status='approved', fee_bps=500)
    db.add(m);db.flush()
    b, secret, hook_secret = svc.create_bot(db, m, 'D Bot connector', None)
    a = ReceiveAccount(currency='USDT', label='آدرس رسمی', instructions='انتقال به آدرس تأییدشده تست')
    db.add(a);db.flush()
    data = OrderCreate(external_order_id='seller-42',buyer_tg_id=99998,product_title='بسته تست',product_kind=kind,amount_minor=100_000_000,currency='USDT')
    return m,b,a,data


def test_receipt_approval_and_balanced_ledger(db):
    m,b,a,data=setup_order(db)
    order,created=svc.create_order(db,b,data)
    assert created
    assert order.receive_account_id==a.id
    old,created2=svc.create_order(db,b,data)
    assert old.id==order.id and not created2
    svc.submit_receipt(db,order.id,data.buyer_tg_id,'file_123','unique_123')
    assert order.status=='receipt_submitted'
    with pytest.raises(HTTPException) as exc:
        svc.review_order(db,order.id,1001,True,False)
    assert exc.value.status_code==422
    reviewed=svc.review_order(db,order.id,1001,True,True)
    assert reviewed.status=='fulfillment_pending'
    assert svc.balance(db,m.id,'USDT')==95_000_000
    assert db.scalar(select(func.sum(LedgerRow.amount_minor)))==0
    assert db.scalar(select(func.count(LedgerRow.id)))==3
    with pytest.raises(HTTPException) as exc:
        svc.review_order(db,order.id,1001,True,True)
    assert exc.value.status_code==409


def test_not_allow_manual_receipt_for_digital_product(db):
    m,b,a,data=setup_order(db,kind='digital')
    with pytest.raises(HTTPException) as exc:
        svc.create_order(db,b,data)
    assert exc.value.status_code==422


def test_receipt_buyer_binding_and_rejection(db):
    m,b,a,data=setup_order(db)
    order,_=svc.create_order(db,b,data)
    with pytest.raises(HTTPException) as exc:
        svc.submit_receipt(db,order.id,123,'photo','unique')
    assert exc.value.status_code==404
    svc.submit_receipt(db,order.id,data.buyer_tg_id,'photo','unique')
    svc.review_order(db,order.id,1001,False,False,'تأیید نشد')
    assert svc.balance(db,m.id,'USDT')==0
    assert order.status=='rejected'


def test_settlement_reserve_approve_pay_is_idempotent(db):
    m,b,a,data=setup_order(db)
    order,_=svc.create_order(db,b,data)
    svc.submit_receipt(db,order.id,data.buyer_tg_id,'photo','unique')
    svc.review_order(db,order.id,1001,True,True)
    settle=svc.create_settlement(db,m,60_000_000,'USDT','test wallet destination')
    assert svc.balance(db,m.id,'USDT')==35_000_000
    assert svc.balance(db,m.id,'USDT','seller_reserved')==60_000_000
    with pytest.raises(HTTPException):
        svc.create_settlement(db,m,40_000_000,'USDT','test wallet destination')
    svc.review_settlement(db,settle.id,1001,'approve')
    with pytest.raises(HTTPException):
        svc.review_settlement(db,settle.id,1001,'paid')
    svc.review_settlement(db,settle.id,1001,'paid','TXHASH-100')
    assert svc.balance(db,m.id,'USDT','seller_reserved')==0
    assert db.scalar(select(func.sum(LedgerRow.amount_minor)))==0
    with pytest.raises(HTTPException):
        svc.review_settlement(db,settle.id,1001,'paid','TXHASH-100')


def test_settlement_reject_releases_reserved_balance(db):
    m,b,a,data=setup_order(db)
    order,_=svc.create_order(db,b,data)
    svc.submit_receipt(db,order.id,data.buyer_tg_id,'photo','unique')
    svc.review_order(db,order.id,1001,True,True)
    settle=svc.create_settlement(db,m,30_000_000,'USDT','destination wallet')
    svc.review_settlement(db,settle.id,1001,'reject')
    assert svc.balance(db,m.id,'USDT')==95_000_000
    assert svc.balance(db,m.id,'USDT','seller_reserved')==0


def test_webapp_initdata_hmac_and_expiry():
    raw_fields={'auth_date':str(int(time.time())),'user':json.dumps({'id':22334,'first_name':'Ali'},separators=(',',':'))}
    check='\n'.join(f'{k}={raw_fields[k]}' for k in sorted(raw_fields))
    secret=hmac.new(b'WebAppData',settings.bot_token.encode(),hashlib.sha256).digest()
    signature=hmac.new(secret,check.encode(),hashlib.sha256).hexdigest()
    raw=urlencode({**raw_fields,'hash':signature})
    assert security.verify_telegram_init_data(raw)['id']==22334
    with pytest.raises(HTTPException):
        security.verify_telegram_init_data(raw.replace('22334','88888'))
    with pytest.raises(HTTPException):
        security.verify_telegram_init_data('user=malformed')


def test_auto_delivery_message_for_eligible_order(db):
    m,b,a,data=setup_order(db)
    data.delivery_message='جزئیات دریافت بسته حضوری: کد 1234'
    order,_=svc.create_order(db,b,data)
    svc.submit_receipt(db,order.id,data.buyer_tg_id,'photo','unique')
    svc.review_order(db,order.id,1001,True,True)
    assert order.status == 'fulfilled'
    from app.models import Outbox
    outbox=db.scalars(select(Outbox)).all()
    assert any('جزئیات دریافت بسته حضوری' in x.payload_json for x in outbox)


def test_refund_uses_historical_fee_and_prevents_duplicate(db):
    m,b,a,data=setup_order(db)
    order,_=svc.create_order(db,b,data)
    svc.submit_receipt(db,order.id,data.buyer_tg_id,'photo','unique')
    svc.review_order(db,order.id,1001,True,True)
    assert order.fee_minor==5_000_000
    svc.update_merchant_settings(db,m.id,1001,'approved',1000)  # fee rises to 10% later
    refund=svc.refund_order(db,order.id,1001,True,'TEST-REFUND-001','لغو سفارش')
    assert order.status=='refunded'
    assert svc.balance(db,m.id,'USDT')==0
    assert db.scalar(select(func.sum(LedgerRow.amount_minor)))==0
    with pytest.raises(HTTPException):
        svc.refund_order(db,order.id,1001,True,'TEST-REFUND-002','لغو دوباره')


def test_refund_not_allowed_when_seller_funds_reserved(db):
    m,b,a,data=setup_order(db)
    order,_=svc.create_order(db,b,data)
    svc.submit_receipt(db,order.id,data.buyer_tg_id,'photo','unique')
    svc.review_order(db,order.id,1001,True,True)
    svc.create_settlement(db,m,90_000_000,'USDT','test destination')
    with pytest.raises(HTTPException) as exc:
        svc.refund_order(db,order.id,1001,True,'TEST-REFUND-003','لغو سفارش')
    assert exc.value.status_code==409
