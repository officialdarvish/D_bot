import asyncio
import pytest
from test_miniapp import client
from app.core.security import encrypt_text
from app.database.models import Server,ClientService,ResellerAccount
from app.services.server_connections import add_shared_connection


def test_registering_second_sales_role_reuses_id_without_repricing_or_rebinding(client):
    _,sessions=client
    async def scenario():
        async with sessions() as session:
            old=await session.get(Server,1)
            old.password_encrypted=encrypt_text('secret');old.meta={'scope':'public','inbound_ids':[1],'reseller_payg_rate_irt':55}
            session.add(ResellerAccount(id=1,user_id=2,server_id=1,allowed_server_ids=[1],wallet_balance_irt=12345))
            await session.commit()
        async with sessions() as session:
            candidate=Server(name='Same panel',server_type='xui',panel_url='https://EXAMPLE.com/',username='private',password_encrypted=encrypt_text('secret'),meta={'scope':'reseller','reseller_billing_modes':['volume','payg'],'reseller_payg_rate_irt':9000})
            row=await add_shared_connection(session,candidate);await session.commit()
            assert row.id==1 and row.meta['scope']=='all' and row.name=='Public'
            svc=await session.get(ClientService,1);account=await session.get(ResellerAccount,1)
            assert svc.server_id==1 and account.server_id==1 and account.wallet_balance_irt==12345
            assert row.meta['inbound_ids']==[1]
            bad=Server(server_type='xui',panel_url='https://example.com',username='private',password_encrypted=encrypt_text('wrong'),meta={'scope':'public'})
            with pytest.raises(ValueError):await add_shared_connection(session,bad)
    asyncio.run(scenario())


def test_legacy_merge_preserves_finance_history_and_remaps_nested_references(client):
    from app.services.server_migration import consolidate,sync_alias_connections,REPORT_KEY
    from app.database.models import Plan,Setting,ResellerBillingEntry,ResellerUsageMeter,ServerCategory,MiniAppOperation
    from sqlalchemy import select,func
    import json
    _,sessions=client
    async def scenario():
        async with sessions() as session:
            first=await session.get(Server,1);second=await session.get(Server,2)
            first.password_encrypted=encrypt_text('same');first.meta={'scope':'public','inbound_ids':[7]}
            second.panel_url=first.panel_url;second.username=first.username;second.password_encrypted=encrypt_text('same');second.meta={'scope':'reseller','inbound_ids':[7],'reseller_billing_modes':['payg'],'reseller_payg_rate_irt':123}
            account=ResellerAccount(id=1,user_id=2,server_id=2,allowed_server_ids=[2],inbound_mode='manual',inbound_ids=[7],wallet_balance_irt=17000,total_bytes=1000,used_bytes=100,reserved_bytes=200)
            session.add(account);await session.flush()
            session.add(ResellerBillingEntry(id=1,reseller_id=1,server_id=2,event_key='old-event',kind='usage',amount_irt=-13,balance_after_irt=17000,usage_bytes=100,rate_irt_per_gb=123))
            plan=await session.get(Plan,3);plan.server_id=2
            session.add(MiniAppOperation(id=1,user_id=1,key='legacy-op',kind='trial',status='pending',payload={'server_id':2},result={}))
            await session.merge(Setting(key='test_account_targets_json',value=json.dumps([{'server_id':2,'inbound_ids':[7]}])))
            await session.merge(Setting(key='test_account_server_id',value='2'))
            await session.commit()
        async with sessions() as session:
            report=await consolidate(session);await session.commit()
            assert report['merged']==[{'canonical_id':1,'alias_ids':[2]}] and not report['conflicts']
            assert (await session.get(Plan,3)).server_id==1
            account=await session.get(ResellerAccount,1)
            assert account.server_id==1 and account.allowed_server_ids==[1] and account.inbound_policies=={'1':{'mode':'manual','inbound_ids':[7]}}
            assert (account.wallet_balance_irt,account.total_bytes,account.used_bytes,account.reserved_bytes)==(17000,1000,100,200)
            ledger=await session.get(ResellerBillingEntry,1)
            assert (ledger.server_id,ledger.amount_irt,ledger.balance_after_irt,ledger.rate_irt_per_gb,ledger.event_key)==(2,-13,17000,123,'old-event')
            assert json.loads((await session.get(Setting,'test_account_targets_json')).value)[0]['server_id']==1
            assert (await session.get(MiniAppOperation,1)).payload['server_id']==1
            assert (await session.get(Server,2)).meta['connection_alias_of']==1
            canonical=await session.get(Server,1)
            assert canonical.meta['scope']=='all' and canonical.meta['reseller_payg_rate_irt']==123
            canonical.password_encrypted=encrypt_text('changed');await sync_alias_connections(session,canonical);await session.commit()
            from app.core.security import decrypt_text
            assert decrypt_text((await session.get(Server,2)).password_encrypted)=='changed'
            assert await consolidate(session)==report
    asyncio.run(scenario())


def test_legacy_conflicting_username_group_is_untouched(client):
    from app.services.server_migration import consolidate
    _,sessions=client
    async def scenario():
        async with sessions() as session:
            first=await session.get(Server,1);second=await session.get(Server,2)
            second.panel_url=first.panel_url;second.username=first.username;second.password_encrypted=first.password_encrypted;second.meta={'scope':'reseller'}
            a=await session.get(ClientService,1);b=await session.get(ClientService,2);b.server_id=2;b.client_username=a.client_username
            await session.commit()
        async with sessions() as session:
            result=await consolidate(session);await session.commit()
            assert not result['merged'] and result['conflicts'][0]['server_ids']==[1,2]
            assert 'username' in result['conflicts'][0]['reason']
            assert (await session.get(ClientService,2)).server_id==2
            assert not (await session.get(Server,2)).meta.get('connection_alias_of')
    asyncio.run(scenario())


def test_legacy_conflicting_tariffs_are_not_averaged_or_merged(client):
    from app.services.server_migration import consolidate
    _,sessions=client
    async def scenario():
        async with sessions() as session:
            first=await session.get(Server,1);second=await session.get(Server,2)
            second.panel_url=first.panel_url;second.username=first.username;second.password_encrypted=first.password_encrypted
            first.meta={'scope':'all','reseller_billing_modes':['payg'],'reseller_payg_rate_irt':100}
            second.meta={'scope':'reseller','reseller_billing_modes':['payg'],'reseller_payg_rate_irt':200}
            await session.commit()
        async with sessions() as session:
            report=await consolidate(session);await session.commit()
            assert not report['merged'] and 'tariff' in report['conflicts'][0]['reason']
            assert (await session.get(Server,1)).meta['reseller_payg_rate_irt']==100
            assert (await session.get(Server,2)).meta['reseller_payg_rate_irt']==200
    asyncio.run(scenario())


def test_removing_connection_preserves_receipts_services_and_plan_references(client,monkeypatch):
    from app.api import admin_web as web
    from app.database.models import Order,Plan
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from unittest.mock import AsyncMock
    _,sessions=client
    monkeypatch.setattr(web,'SessionLocal',sessions)
    monkeypatch.setattr(web,'db_setting',AsyncMock(side_effect=lambda key,default:default))
    app=FastAPI();app.include_router(web.router);app.dependency_overrides[web._auth_user]=lambda:'owner'
    async def add_receipt():
        async with sessions() as session:
            order=await session.get(Order,1);order.receipt_file_id='original-receipt';await session.commit()
    asyncio.run(add_receipt())
    with TestClient(app) as api:
        result=api.post('/admin/servers/1/delete',headers={'X-Requested-With':'fetch'})
        assert result.status_code==200,result.text
        assert 1 not in [r['id'] for r in api.get('/admin/api/v2/servers').json()['items']]
    async def verify():
        async with sessions() as session:
            assert not (await session.get(Server,1)).is_active
            assert (await session.get(Plan,1)).server_id==1
            assert (await session.get(ClientService,1)).server_id==1
            order=await session.get(Order,1)
            assert order.status=='paid' and order.receipt_file_id=='original-receipt'
    asyncio.run(verify())


def test_role_cards_merge_after_v1_conflict_without_changing_receipt_routes(client):
    from app.services.server_migration import consolidate, REPORT_KEY
    from app.services.payment_cards import public_payment_card, reseller_payment_card
    from app.database.models import PaymentCard, Setting, Order
    import json
    _, sessions = client
    async def scenario():
        async with sessions() as session:
            first = await session.get(Server, 1); second = await session.get(Server, 2)
            first.password_encrypted = encrypt_text('same'); first.meta = {'scope': 'public'}
            second.panel_url = first.panel_url; second.username = first.username
            second.password_encrypted = encrypt_text('same'); second.meta = {'scope': 'reseller'}
            session.add_all([
                PaymentCard(id=1,server_id=1,server_type='xui',card_number='public-card',owner_name='Public',reviewer_telegram_id=111,is_active=True),
                PaymentCard(id=2,server_id=2,server_type='reseller',card_number='reseller-card',owner_name='Reseller',reviewer_telegram_id=222,is_active=True),
                PaymentCard(id=3,server_id=2,server_type='panel_reseller',card_number='panel-card',owner_name='Panel',reviewer_telegram_id=333,is_active=True),
            ])
            await session.flush()
            order = await session.get(Order,1); order.payment_card_id=1; order.receipt_reviewer_telegram_id=111
            session.add(Setting(key='server_connection_migration_v1',value=json.dumps({'schema':1,'merged':[],'conflicts':[{'server_ids':[1,2],'reason':'role-specific payment routing requires review'}]})))
            await session.commit()
        async with sessions() as session:
            result=await consolidate(session); await session.commit()
            assert result['merged']==[{'canonical_id':1,'alias_ids':[2]}] and not result['conflicts']
            assert (await public_payment_card(session,await session.get(Server,1))).id==1
            assert (await reseller_payment_card(session,1)).id==2
            assert (await reseller_payment_card(session,1,panel=True)).id==3
            assert (await public_payment_card(session,await session.get(Server,2))).id==1
            assert (await reseller_payment_card(session,2)).id==2
            order=await session.get(Order,1)
            assert (order.payment_card_id,order.receipt_reviewer_telegram_id)==(1,111)
            assert await session.get(Setting,REPORT_KEY)
            assert 'conflicts' in (await session.get(Setting,'server_connection_migration_v1')).value
            assert await consolidate(session)==result
    asyncio.run(scenario())


def test_merge_retains_conflict_when_same_role_would_change_recipient(client):
    from app.services.server_migration import consolidate
    from app.database.models import PaymentCard
    _,sessions=client
    async def scenario():
        async with sessions() as session:
            first=await session.get(Server,1); second=await session.get(Server,2)
            second.panel_url=first.panel_url;second.username=first.username
            first.password_encrypted=second.password_encrypted=encrypt_text('same')
            first.meta=second.meta={'scope':'public'}
            session.add_all([PaymentCard(id=i,server_id=i,server_type='xui',card_number=f'card-{i}',owner_name=f'Owner-{i}',is_active=True) for i in [1,2]])
            await session.commit()
        async with sessions() as session:
            result=await consolidate(session)
            assert not result['merged'] and result['conflicts'][0]['reason']=='public payment recipient would change'
            assert not (await session.get(Server,2)).meta.get('connection_alias_of')
    asyncio.run(scenario())
