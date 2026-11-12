import asyncio,json
from datetime import datetime,timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import httpx,pytest
from app.services.nx_service import NxService,NxCreateUnconfirmed
from app.services.pasarguard_service import PasarGuardService
from app.core.security import encrypt_text
from app.database.models import Server,Plan
from app.services.traffic_units import gb_to_bytes


def server():return Server(id=10,name='NX',server_type='nx',panel_url='https://panel.test/private',subscription_url='https://sub.test/sub/',username='api-token',password_encrypted=encrypt_text('token'),meta={'scope':'all','inbound_ids':[7]})
def user(**extra):return {'id':4,'name':'buyer','volume':10000,'up':100,'down':200,'expiry':0,'enable':True,'templateIds':[7],'updatedAt':55,'subId':'old','subUrl':'https://wildcard.test/sub/old','config':{'uuid':'old','flow':'vision'},**extra}


def test_paging_exact_name_and_authoritative_subscription(monkeypatch):
    svc=NxService();calls=[]
    async def request(s,method,path,**kwargs):
        calls.append((method,path,kwargs))
        return {'items':[user(name='buyer-extra'),user()],'total':2}
    monkeypatch.setattr(svc,'_request',request)
    found=asyncio.run(svc.get_user(server(),'buyer'))
    assert found['used_traffic']==300 and found['data_limit']==10000
    assert found['sub_link']=='https://wildcard.test/sub/old'
    assert calls[0][2]['params']['q']=='buyer'


def test_patch_concurrency_and_rotation_retains_other_config(monkeypatch):
    svc=NxService();calls=[]
    async def request(s,method,path,**kwargs):
        calls.append((method,path,kwargs))
        if method=='GET':return {'items':[user()],'total':1}
        return user(**kwargs['json'],subUrl='https://wildcard.test/sub/new')
    monkeypatch.setattr(svc,'_request',request)
    result=asyncio.run(svc.revoke_subscription(server(),'buyer'))
    sent=calls[-1][2]['json']
    assert sent['version']==55 and sent['config']['flow']=='vision'
    assert sent['config']['uuid']!='old' and sent['subId']!='old'
    assert 'volume' not in sent and 'templateIds' not in sent and 'subToken' not in sent
    assert result['sub_link'].endswith('/new')


def test_ambiguous_create_is_never_repeated_or_adopts_other_user(monkeypatch):
    svc=NxService();calls=[]
    async def request(s,method,path,**kwargs):
        calls.append((method,path,kwargs))
        if method=='GET':return {'items':[],'total':0} if len(calls)==1 else {'items':[user(desc='someone else')],'total':1}
        raise httpx.ReadTimeout('lost reply')
    monkeypatch.setattr(svc,'_request',request)
    with pytest.raises(NxCreateUnconfirmed):asyncio.run(svc.create_user_on_plan(server(),Plan(volume_gb=1,duration_days=1,inbound_ids=[7]),'buyer'))
    assert len([x for x in calls if x[0]=='POST'])==1
    assert calls[1][2]['headers']['Idempotency-Key'].startswith('dbot:')


def test_create_uses_decimal_trial_bytes_and_explicit_templates(monkeypatch):
    svc=NxService();calls=[]
    async def request(s,method,path,**kwargs):
        calls.append((method,path,kwargs))
        if method=='GET':return {'items':[],'total':0}
        return user(**kwargs['json'])
    monkeypatch.setattr(svc,'_request',request)
    plan=SimpleNamespace(volume_gb=0.0001,duration_days=1,inbound_ids=[7],hwid_limit=2,is_unlimited=False)
    found=asyncio.run(svc.create_user_on_plan(server(),plan,'buyer'))
    sent=calls[-1][2]['json']
    assert sent['volume']==gb_to_bytes(0.0001)>0 and sent['templateIds']==[7] and sent['allTemplates'] is False and sent['deviceLimit']==2
    assert found['sub_link']


def test_nx_dispatches_through_shared_provider_without_pg_api(monkeypatch):
    expected=user();mock=AsyncMock(return_value=expected)
    monkeypatch.setattr(NxService,'get_user',mock)
    assert asyncio.run(PasarGuardService().get_user(server(),'buyer'))==expected
    mock.assert_awaited_once()


def test_native_profiles_match_documented_schema_and_sanitize_names(monkeypatch):
    svc=NxService();monkeypatch.setattr(svc,'get_user',AsyncMock(return_value=user()))
    monkeypatch.setattr(svc,'_request',AsyncMock(return_value={'configs':[{'name':'WG','type':'wireguard','fileName':'../../user.conf','content':'[Interface]\nPrivateKey=test'},{'type':'unknown','content':'x'}]}))
    result=asyncio.run(svc.app_configs(server(),'buyer'))
    assert len(result)==1 and '/' not in result[0]['file_name']
    assert result[0]['content'].startswith('[Interface]')

from app.bot.handlers.public.buy import get_public_service_types as real_public_types
from test_miniapp_checkout import native,H,body
from test_miniapp import client


def test_real_checkout_queue_provisions_nx_once(native,monkeypatch):
    from app.api import miniapp_checkout as checkout
    from app.database.models import User,Setting,ClientService,Order
    from sqlalchemy import select,func
    c,sessions,bot,buy=native
    monkeypatch.setattr(buy,'get_public_service_types',real_public_types)
    async def seed():
        async with sessions() as session:
            row=await session.get(Server,1);row.server_type='nx';row.meta={'scope':'all','inbound_ids':[7]};row.panel_url='https://nx.test';row.password_encrypted=encrypt_text('token')
            plan=await session.get(Plan,1);plan.inbound_ids=[7]
            await session.merge(Setting(key='service_type:custom:nx',value='NX'))
            await session.merge(Setting(key='service_type_provider:nx',value='nx'))
            await session.commit()
    asyncio.run(seed())
    calls=[];remote=[]
    async def request(self,s,method,path,**kwargs):
        calls.append((method,path,kwargs))
        if method=='GET':return {'items':remote,'total':len(remote)}
        result=user(**kwargs['json']);remote.append(result);return result
    monkeypatch.setattr(NxService,'_request',request)
    for name in ['send_buyer_notice','notify_paid_order','send_service_card','send_service_success_notice','send_home','send_admin_notice','edit_admin_receipt_keyboard','report_bot_error']:
        monkeypatch.setattr(buy,name,AsyncMock())
    monkeypatch.setattr(buy,'apply_purchase_commission',AsyncMock(return_value=0))
    payload=body();result=c.post('/api/miniapp/checkout',headers=H,json=payload)
    assert result.status_code==200,result.text
    oid=result.json()['id'];asyncio.run(checkout.process_wallet_queue());asyncio.run(checkout.process_wallet_queue())
    result=c.get(f'/api/miniapp/checkout/orders/{oid}',headers=H).json()
    assert result['status']=='paid',result
    assert len([x for x in calls if x[0]=='POST'])==1
    async def verify():
        async with sessions() as session:
            assert (await session.get(User,1)).wallet_balance==111000
            svc=await session.get(ClientService,(await session.get(Order,oid)).service_id)
            assert svc.server_id==1 and svc.inbound_ids==[7] and svc.sub_link
    asyncio.run(verify())
