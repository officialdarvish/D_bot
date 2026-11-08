import asyncio,uuid,json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select,func
from test_miniapp import client,signed
from app.api import miniapp,miniapp_ownership as ownership
from app.database.models import ClientService,User,Setting,MiniAppOperation,Order

@pytest.fixture
def native(client,monkeypatch):
 _,sessions=client
 monkeypatch.setattr(ownership,'SessionLocal',sessions)
 monkeypatch.setattr(ownership.settings,'OWNER_IDS','11')
 monkeypatch.setattr(ownership.settings,'ADMIN_IDS','11')
 bot=SimpleNamespace(send_message=AsyncMock())
 @asynccontextmanager
 async def fake_bot():yield bot
 monkeypatch.setattr(ownership,'telegram_bot',fake_bot)
 app=FastAPI();app.include_router(miniapp.router);app.include_router(ownership.router)
 with TestClient(app) as c:yield c,sessions,bot

H={'X-Telegram-Init-Data':signed()}
OTHER={'X-Telegram-Init-Data':signed(22)}
def body(target='22',**extra):return {'key':str(uuid.uuid4()),'target_telegram_id':target,'confirmed':True,**extra}
BASE='/api/miniapp/services/1/ownership'


def test_admin_capability_preview_validation_and_no_mutation(native):
 c,sessions,bot=native
 assert c.get('/api/miniapp/session',headers=H).json()['user']['can_transfer_ownership'] is True
 assert c.get('/api/miniapp/session',headers=OTHER).json()['user']['can_transfer_ownership'] is False
 assert c.post(BASE+'/preview',json={'target_telegram_id':'22'}).status_code==401
 assert c.post(BASE+'/preview',headers=OTHER,json={'target_telegram_id':'11'}).status_code==403
 for target in ['11','123456789','@user','-1','0']:
  assert c.post(BASE+'/preview',headers=H,json={'target_telegram_id':target}).status_code==409
 r=c.post(BASE+'/preview',headers=H,json={'target_telegram_id':'22'})
 assert r.status_code==200 and r.json()['recipient']['telegram_id']==22,r.text
 async def verify():
  async with sessions() as s:assert (await s.get(ClientService,1)).user_id==1
 asyncio.run(verify());bot.send_message.assert_not_awaited()


def test_transfer_is_atomic_idempotent_and_notifies_only_the_recipient(native):
 c,sessions,bot=native;b=body()
 async def snapshot():
  async with sessions() as s:
   svc=await s.get(ClientService,1)
   return {column.name:getattr(svc,column.name) for column in svc.__table__.columns if column.name!='user_id'}
 before=asyncio.run(snapshot())
 assert c.post(BASE,headers=H,json={**b,'confirmed':False}).status_code==409
 r=c.post(BASE,headers=H,json=b)
 assert r.status_code==200 and r.json()['transferred'] and r.json()['recipient_notified'],r.text
 bot.send_message.assert_awaited_once()
 assert bot.send_message.call_args.args[0]==22 and 'mine' in bot.send_message.call_args.args[1]
 assert 'کانفیگ‌های من' in bot.send_message.call_args.args[1]
 assert asyncio.run(snapshot())==before
 assert c.post(BASE,headers=H,json=b).json()==r.json()
 assert bot.send_message.await_count==1
 assert c.post(BASE,headers=H,json=body()).status_code==409
 assert c.post(BASE,headers=H,json={**b,'target_telegram_id':'123'}).status_code==409
 assert 1 not in [v['id'] for v in c.get('/api/miniapp/session',headers=H).json()['services']]
 assert 1 in [v['id'] for v in c.get('/api/miniapp/session',headers=OTHER).json()['services']]
 async def verify():
  async with sessions() as s:
   assert (await s.get(ClientService,1)).user_id==2
   assert (await s.get(Order,1)).user_id==1
   assert (await s.get(User,1)).wallet_balance==250000
   assert await s.scalar(select(func.count()).select_from(MiniAppOperation).where(MiniAppOperation.kind=='ownership_transfer'))==1
   rows=(await s.scalars(select(Setting).where(Setting.key.like('service_ownership_transfer:%')))).all()
   assert len(rows)==1 and json.loads(rows[0].value)['to_telegram_id']==22
 asyncio.run(verify())


def test_notification_failure_never_rolls_back_or_replays_transfer(native):
 c,sessions,bot=native;bot.send_message.side_effect=RuntimeError('Telegram unavailable');b=body()
 r=c.post(BASE,headers=H,json=b)
 assert r.status_code==200 and r.json()['transferred'] and not r.json()['recipient_notified'],r.text
 assert c.post(BASE,headers=H,json=b).json()==r.json()
 assert bot.send_message.await_count==1
 async def verify():
  async with sessions() as s:assert (await s.get(ClientService,1)).user_id==2
 asyncio.run(verify())


def test_pending_native_operation_and_blocked_recipient_are_rejected(native):
 c,sessions,bot=native
 async def seed():
  async with sessions() as s:
   user=await s.get(User,2);user.is_blocked=True;await s.commit()
 asyncio.run(seed())
 assert c.post(BASE,headers=H,json=body()).status_code==409
 async def seed_pending():
  async with sessions() as s:
   user=await s.get(User,2);user.is_blocked=False
   s.add(MiniAppOperation(user_id=1,key=str(uuid.uuid4()),kind='public_hwid',status='queued',payload={'action':'hwid','service_id':1}));await s.commit()
 asyncio.run(seed_pending())
 assert c.post(BASE+'/preview',headers=H,json={'target_telegram_id':'22'}).status_code==409
 assert c.post(BASE,headers=H,json=body()).status_code==409
 bot.send_message.assert_not_awaited()
