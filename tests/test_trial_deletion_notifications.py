import asyncio
from unittest.mock import AsyncMock
from types import SimpleNamespace
import pytest
from sqlalchemy import select
from test_miniapp_native_actions import native, client, H, action
from app.api import miniapp_actions as actions
from app.bot.handlers.public import my_services
from app.jobs import service_cleanup as cleanup
from app.database.models import ClientService, Server, TestAccountUsage, ServiceDeletionTask, User
from app.services.xui_service import XuiService
from app.services.pasarguard_service import PasarGuardService
from app.services.miniapp_runtime import native_event


def prepare(native,monkeypatch,provider='pasarguard',outage=False,renamed=False):
 c,sessions,real,calls,flow,buy=native
 for module in [my_services,cleanup]:monkeypatch.setattr(module,'SessionLocal',sessions)
 remote=AsyncMock(side_effect=TimeoutError('panel offline') if outage else None)
 monkeypatch.setattr(XuiService,'delete_client',remote)
 monkeypatch.setattr(PasarGuardService,'delete_user',remote)
 async def seed():
  async with sessions() as s:
   svc=await s.get(ClientService,1);svc.plan_id=None;svc.client_username='renamed_trial' if renamed else 'test_000001';svc.xui_email=svc.client_username;svc.total_bytes=int(.2*1024**3);svc.used_bytes=0
   (await s.get(Server,1)).server_type=provider
   (await s.get(User,1)).username='trial_owner'
   s.add(TestAccountUsage(user_id=1,telegram_id=11,service_id=1));await s.commit()
 asyncio.run(seed())
 return c,sessions,real,calls,remote


@pytest.mark.parametrize('route',['bot','miniapp'])
@pytest.mark.parametrize('provider',['xui','pasarguard'])
@pytest.mark.parametrize('outage',[False,True])
def test_trial_deletion_notifies_admin_once_across_routes(native,monkeypatch,route,provider,outage):
 c,sessions,real,calls,remote=prepare(native,monkeypatch,provider,outage)
 if route=='miniapp':
  b=action('delete');r=c.post('/api/miniapp/services/1/actions',headers=H,json=b);assert r.status_code==200,r.text
  asyncio.run(actions.process_operations());asyncio.run(actions.process_operations())
  result=c.get('/api/miniapp/operations/'+str(r.json()['id']),headers=H).json();assert result['status']=='done',result
  assert c.post('/api/miniapp/services/1/actions',headers=H,json=b).json()['status']=='done'
 else:
  async def run():
   async with sessions() as s:user=await s.get(User,1)
   _,callback,_=native_event(real,user,data='svc:delete_confirm:1')
   await my_services.delete_service(callback)
  asyncio.run(run())
 asyncio.run(cleanup.notify_service_deletion_task_admin(real))
 reports=[m for m in calls if getattr(m,'chat_id',None)==99 and 'گزارش حذف اکانت تست' in (getattr(m,'text','') or '')]
 assert len(reports)==1 and remote.await_count==1
 text=reports[0].text
 assert '@trial_owner' in text and 'آیدی عددی: 11' in text and 'test_000001' in text and '0.2 گیگ' in text
 assert ('در صف تلاش مجدد' in text)==outage
 async def check():
  async with sessions() as s:
   task=await s.scalar(select(ServiceDeletionTask));assert task.admin_notified_at is not None
   assert task.identifiers['is_test_service']
   assert await s.scalar(select(TestAccountUsage.id)) is not None
 asyncio.run(check())


def test_renamed_trial_is_identified_by_usage_record(native,monkeypatch):
 c,sessions,real,calls,remote=prepare(native,monkeypatch,renamed=True)
 c.post('/api/miniapp/services/1/actions',headers=H,json=action('delete'))
 asyncio.run(actions.process_operations())
 assert any('گزارش حذف اکانت تست' in (getattr(m,'text','') or '') and 'renamed_trial' in m.text for m in calls)


def test_admin_deleting_own_trial_still_gets_admin_report(native,monkeypatch):
 c,sessions,real,calls,remote=prepare(native,monkeypatch)
 monkeypatch.setattr(my_services.settings,'ADMIN_IDS','11')
 c.post('/api/miniapp/services/1/actions',headers=H,json=action('delete'))
 asyncio.run(actions.process_operations())
 assert sum(getattr(m,'chat_id',None)==11 and 'گزارش حذف اکانت تست' in (getattr(m,'text','') or '') for m in calls)==1


def test_telegram_failure_keeps_report_pending_for_retry(native,monkeypatch):
 c,sessions,real,calls,remote=prepare(native,monkeypatch)
 original=real.session.make_request
 async def failing(bot,method,timeout=None):
  if getattr(method,'chat_id',None)==99:raise TimeoutError('Telegram offline')
  return await original(bot,method,timeout)
 monkeypatch.setattr(real.session,'make_request',failing)
 r=c.post('/api/miniapp/services/1/actions',headers=H,json=action('delete'))
 asyncio.run(actions.process_operations())
 assert c.get('/api/miniapp/operations/'+str(r.json()['id']),headers=H).json()['status']=='done'
 async def pending():
  async with sessions() as s:assert (await s.scalar(select(ServiceDeletionTask))).admin_notified_at is None
 asyncio.run(pending())
 monkeypatch.setattr(real.session,'make_request',original)
 assert asyncio.run(cleanup.notify_service_deletion_task_admin(real))==1
 assert asyncio.run(cleanup.notify_service_deletion_task_admin(real))==0
 assert remote.await_count==1
