import asyncio,uuid
from unittest.mock import AsyncMock
import pytest
from test_miniapp_native_actions import native,client,H,OTHER,action
from app.api import miniapp_actions as actions
from app.bot.handlers.public import my_services
from app.database.models import Server,ClientService,ResellerAccount
from app.services.xui_service import XuiService
from app.services.pasarguard_service import PasarGuardService


@pytest.mark.parametrize('provider',['xui','pasarguard'])
def test_public_delete_is_owned_confirmed_idempotent_and_quiet(native,monkeypatch,provider):
 c,sessions,real,calls,flow,buy=native
 monkeypatch.setattr(my_services,'SessionLocal',sessions)
 monkeypatch.setattr(my_services,'notify_service_deletion_task_admin',AsyncMock())
 remote=AsyncMock()
 monkeypatch.setattr(XuiService,'delete_client',remote)
 monkeypatch.setattr(PasarGuardService,'delete_user',remote)
 async def seed():
  async with sessions() as s:(await s.get(Server,1)).server_type=provider;await s.commit()
 asyncio.run(seed())
 b=action('delete');path='/api/miniapp/services/1/actions'
 assert c.post(path,json=b).status_code==401
 assert c.post('/api/miniapp/services/2/actions',headers=H,json=b).status_code==404
 assert c.post(path,headers=H,json={**b,'confirmed':False}).status_code==422
 r=c.post(path,headers=H,json=b);assert r.status_code==200,r.text
 oid=r.json()['id'];assert c.get(f'/api/miniapp/operations/{oid}',headers=OTHER).status_code==404
 asyncio.run(actions.process_operations());asyncio.run(actions.process_operations())
 result=c.get(f'/api/miniapp/operations/{oid}',headers=H).json();assert result['status']=='done',result
 assert remote.await_count==1 and not result['result'].get('service_id')
 assert c.post(path,headers=H,json=b).json()['status']=='done'
 async def check():
  async with sessions() as s:
   from app.services.service_grace import visible_in_my_services
   assert not visible_in_my_services(await s.get(ClientService,1))
   assert await s.get(ClientService,2) is not None
 asyncio.run(check())
 assert all(getattr(m,'chat_id',None)!=11 for m in calls)


@pytest.mark.parametrize('notification_failure',[False,True])
def test_public_panel_outage_queues_cleanup_instead_of_repeating_delete(native,monkeypatch,notification_failure):
 c,sessions,real,calls,flow,buy=native
 monkeypatch.setattr(my_services,'SessionLocal',sessions)
 monkeypatch.setattr(my_services,'notify_service_deletion_task_admin',AsyncMock())
 if notification_failure:monkeypatch.setattr(my_services,'notify_service_deletion_task_admin',AsyncMock(side_effect=TimeoutError('Telegram offline')))
 remote=AsyncMock(side_effect=TimeoutError('panel offline'));monkeypatch.setattr(XuiService,'delete_client',remote)
 b=action('delete');r=c.post('/api/miniapp/services/1/actions',headers=H,json=b)
 asyncio.run(actions.process_operations())
 result=c.get(f"/api/miniapp/operations/{r.json()['id']}",headers=H).json()
 assert result['status']=='done',result
 assert 'اتصال دوباره' in result['result']['message']
 assert c.post('/api/miniapp/services/1/actions',headers=H,json=b).json()['status']=='done'
 asyncio.run(actions.process_operations());assert remote.await_count==1
