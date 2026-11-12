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
