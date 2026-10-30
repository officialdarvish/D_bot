import asyncio,json,uuid
from contextlib import asynccontextmanager
from datetime import datetime,timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select,func
from test_miniapp import client,signed,TOKEN
from app.api import miniapp_actions as actions
from app.database.models import Setting,Plan,ServerCategory,ClientService,MiniAppOperation,ServiceConversion
from app.services.pasarguard_service import PasarGuardService

@pytest.mark.asyncio
async def test_rotation_uses_verified_post_response_even_when_get_is_stale(monkeypatch):
 pg=PasarGuardService();server=SimpleNamespace(panel_url='https://panel.example',subscription_url='')
 old={'id':7,'subscription_url':'/sub/old','group_ids':[1,2],'proxy_settings':{'vless':{'id':'old'}}}
 new={**old,'subscription_url':'/sub/new','proxy_settings':{'vless':{'id':'new'}}}
 read=AsyncMock(return_value=old);write=AsyncMock(return_value=new)
 monkeypatch.setattr(pg,'get_user',read);monkeypatch.setattr(pg,'_request',write)
 result=await pg.revoke_subscription(server,'demo')
 assert result['sub_link']=='https://panel.example/sub/new' and result['uuid']=='new'
 assert read.await_count==1
 write.assert_awaited_once_with(server,'POST','/api/user/by-username/demo/revoke_sub')

@pytest.mark.asyncio
async def test_rotation_only_retries_reads_and_rejects_unchanged_credentials(monkeypatch):
 pg=PasarGuardService();server=SimpleNamespace(panel_url='https://panel.example',subscription_url='')
 old={'id':7,'subscription_url':'/sub/old','group_ids':[1]}
 new={**old,'subscription_url':'/sub/new'}
 monkeypatch.setattr(pg,'get_user',AsyncMock(side_effect=[old,old,new]))
 write=AsyncMock(return_value={});monkeypatch.setattr(pg,'_request',write)
 assert (await pg.revoke_subscription(server,'demo'))['sub_link'].endswith('/new')
 assert write.await_count==1
 monkeypatch.setattr(pg,'get_user',AsyncMock(return_value=old))
 with pytest.raises(RuntimeError,match='identity|rotation'):
  await pg.revoke_subscription(server,'demo')
 assert write.await_count==2
 with pytest.raises(RuntimeError,match='group'):
  pg.verify_subscription_rotation(server,old,{**new,'group_ids':[2]})

@pytest.mark.asyncio
async def test_hwid_returns_verified_rotation_without_an_extra_stale_read(monkeypatch):
 pg=PasarGuardService();clear=AsyncMock();revoke=AsyncMock(return_value={'sub_link':'new'})
 monkeypatch.setattr(pg,'clear_user_hwids',clear);monkeypatch.setattr(pg,'revoke_subscription',revoke)
 monkeypatch.setattr(pg,'get_user',AsyncMock(side_effect=AssertionError('Unexpected stale read')))
 assert await pg.reset_hwid_and_rotate(None,'demo')=={'sub_link':'new'}
 clear.assert_awaited_once();revoke.assert_awaited_once()

@pytest.fixture
def conversion(client,monkeypatch):
 _,sessions=client
 from app.bot.handlers.public import convert
 monkeypatch.setattr(actions,'SessionLocal',sessions);monkeypatch.setattr(convert,'SessionLocal',sessions)
 now=datetime.utcnow()+timedelta(days=12)
 monkeypatch.setattr(convert,'live_source',AsyncMock(return_value=(30*1024**3,12*1024**3,now)))
 monkeypatch.setattr(convert,'set_enabled',AsyncMock())
 monkeypatch.setattr(convert,'create_converted',AsyncMock(return_value={'uuid':'new','sub_link':'https://example.com/sub/new','inbound_ids':[1]}))
 presenter=AsyncMock();monkeypatch.setattr(convert,'send_service_info',presenter)
 bot=SimpleNamespace(token=TOKEN,send_message=AsyncMock())
 @asynccontextmanager
 async def fake_bot():yield bot
 monkeypatch.setattr(actions,'telegram_bot',fake_bot)
 async def seed():
  async with sessions() as s:
   s.add(ServerCategory(id=3,name='VIP',server_id=1))
   s.add(Plan(id=4,title='VIP 20 GB',volume_gb=20,duration_days=30,price_irt=120000,server_id=1,category_id=3))
   s.add(Setting(key='convert_category_rules',value=json.dumps({'1':{'price_per_gb_irt':6000,'server_ids':[1]},'3':{'price_per_gb_irt':12000,'server_ids':[1]}})))
   await s.commit()
 asyncio.run(seed())
 app=FastAPI();app.include_router(actions.router)
 with TestClient(app) as api:yield api,sessions,convert,presenter,bot


def test_native_conversion_quote_auth_idempotency_and_no_chat_delivery(conversion):
 c,sessions,flow,presenter,bot=conversion;h={'X-Telegram-Init-Data':signed()}
 assert c.get('/api/miniapp/services/1/conversion').status_code==401
 assert c.get('/api/miniapp/services/1/conversion',headers={'X-Telegram-Init-Data':signed(22)}).status_code==409
 catalog=c.get('/api/miniapp/services/1/conversion',headers=h)
 assert catalog.status_code==200,catalog.text
 assert [p['id'] for p in catalog.json()['plans']]==[4]
 key=str(uuid.uuid4());base='/api/miniapp/services/1/conversion'
 preview=c.post(base+'/preview',headers=h,json={'key':key,'target_plan_id':4})
 assert preview.status_code==200,preview.text
 assert preview.json()['quote']['destination_bytes']==9*1024**3
 assert c.post(base+'/confirm',headers={'X-Telegram-Init-Data':signed(22)},json={'key':key}).status_code==404
 queued=c.post(base+'/confirm',headers=h,json={'key':key})
 assert queued.status_code==200 and queued.json()['status']=='queued',queued.text
 assert c.post(base+'/confirm',headers=h,json={'key':key}).json()['id']==queued.json()['id']
 asyncio.run(actions.process_operations())
 result=c.get('/api/miniapp/operations/'+str(queued.json()['id']),headers=h)
 assert result.json()['status']=='done',result.text
 assert result.json()['result']['service']['username']=='cv1_4'
 flow.set_enabled.assert_awaited_once();flow.create_converted.assert_awaited_once()
 presenter.assert_not_awaited();bot.send_message.assert_not_awaited()
 asyncio.run(actions.process_operations())
 assert flow.create_converted.await_count==1
 async def verify():
  async with sessions() as s:
   record=await s.scalar(select(ServiceConversion))
   assert record.status=='completed' and record.target_total_bytes==9*1024**3
   assert await s.scalar(select(func.count()).select_from(MiniAppOperation))==1
 asyncio.run(verify())


def test_ambiguous_conversion_is_held_for_review_and_never_replayed(conversion):
 c,sessions,flow,presenter,bot=conversion;h={'X-Telegram-Init-Data':signed()};key=str(uuid.uuid4())
 flow.create_converted.side_effect=RuntimeError('Remote timed out after accepting creation')
 base='/api/miniapp/services/1/conversion'
 assert c.post(base+'/preview',headers=h,json={'key':key,'target_plan_id':4}).status_code==200
 op=c.post(base+'/confirm',headers=h,json={'key':key}).json()
 asyncio.run(actions.process_operations())
 result=c.get('/api/miniapp/operations/'+str(op['id']),headers=h).json()
 assert result['status']=='failed' and result['result']['retryable'] is False
 assert c.post(base+'/confirm',headers=h,json={'key':key}).json()['status']=='failed'
 asyncio.run(actions.process_operations())
 flow.create_converted.assert_awaited_once();presenter.assert_not_awaited()
 async def verify():
  async with sessions() as s:
   record=await s.scalar(select(ServiceConversion))
   assert record.status=='needs_review'
 asyncio.run(verify())


def test_expired_preview_cannot_queue_a_conversion(conversion):
 c,sessions,flow,presenter,bot=conversion;h={'X-Telegram-Init-Data':signed()};key=str(uuid.uuid4());base='/api/miniapp/services/1/conversion'
 preview=c.post(base+'/preview',headers=h,json={'key':key,'target_plan_id':4}).json()
 async def expire():
  async with sessions() as s:
   op=await s.get(MiniAppOperation,preview['id']);op.created_at=datetime.utcnow()-timedelta(minutes=6);await s.commit()
 asyncio.run(expire())
 assert c.post(base+'/confirm',headers=h,json={'key':key}).status_code==409
 flow.set_enabled.assert_not_awaited();flow.create_converted.assert_not_awaited()


def test_configuration_control_keeps_verified_pasarguard_link(conversion,monkeypatch):
 c,sessions,flow,presenter,bot=conversion
 from app.database.models import Server,User
 from app.services.xui_service import XuiService
 rotated={'sub_link':'https://example.com/sub/new','uuid':'rotated'}
 monkeypatch.setattr(PasarGuardService,'revoke_subscription',AsyncMock(return_value=rotated))
 monkeypatch.setattr(PasarGuardService,'reset_hwid_and_rotate',AsyncMock(return_value=rotated))
 resolver=AsyncMock(side_effect=AssertionError('Do not overwrite the verified POST response with a stale GET'))
 monkeypatch.setattr(XuiService,'resolve_service_subscription',resolver)
 async def run():
  async with sessions() as s:
   server=await s.get(Server,1);server.server_type='pasarguard';await s.commit()
   user=await s.get(User,1)
   for action in ('hwid','revoke'):
    assert await actions.configuration_control(s,user,1,action)==1
    svc=await s.get(ClientService,1)
    assert svc.sub_link==rotated['sub_link'] and svc.xui_uuid=='rotated'
 asyncio.run(run());resolver.assert_not_awaited()
