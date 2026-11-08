import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from test_miniapp import client
from app.database.models import ClientService, Server, Plan
from app.services import panel_snapshot as snap
from app.jobs import service_alerts as alerts
from app.jobs import service_cleanup as cleanup

@pytest.mark.parametrize('raw,kind,expected',[
 ('2026-11-03T12:30:00+03:30','pasarguard',datetime(2026,11,3,9)),
 ('1793700000','pasarguard',datetime.utcfromtimestamp(1793700000)),
 (1793700000000,'xui',datetime.utcfromtimestamp(1793700000)),
 (0,'xui',None),(None,'pasarguard',None),(-86400000,'xui',None)])
def test_exact_expiry_including_numeric_strings_unlimited_and_pending(raw,kind,expected):
 svc=SimpleNamespace(expires_at=datetime(2020,1,1))
 assert snap.apply_panel_expiry(svc,{'expiryTime' if kind=='xui' else 'expire':raw},kind)
 assert svc.expires_at==expected


def test_panel_edits_override_local_values_and_detail_has_no_duplicate_metrics(client,monkeypatch):
 from app.bot.handlers.public.my_services import sync_service_from_panel,detail_kb,service_detail_text
 _,sessions=client
 remote={'status':'active','expire':'2027-01-02T13:04:05+03:30','data_limit':0,'used_traffic':100}
 monkeypatch.setattr(snap.PasarGuardService,'get_user',AsyncMock(side_effect=lambda *a:dict(remote)))
 async def run():
  async with sessions() as s:
   server=await s.get(Server,1);server.server_type='pasarguard'
   svc=await s.get(ClientService,1);svc.expires_at=datetime(2020,1,1);await s.commit()
   assert await sync_service_from_panel(s,svc) is True
   assert svc.is_active and svc.expires_at==datetime(2027,1,2,9,34,5) and svc.total_bytes==0
   plan=await s.get(Plan,1)
   assert all(b.callback_data!='noop' for row in detail_kb(svc,plan,'pasarguard').inline_keyboard for b in row)
   text=service_detail_text(svc,plan,'pasarguard',server)
   from app.core.config import settings
   from zoneinfo import ZoneInfo
   from datetime import timezone
   expected_time=svc.expires_at.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(settings.TZ)).strftime('%H:%M')
   assert text.count('تاریخ انقضا:')==1 and expected_time in text and settings.TZ in text
   remote['expire']=None
   assert await sync_service_from_panel(s,svc) is True and svc.expires_at is None
 asyncio.run(run())


def test_volume_thresholds_persist_once_rearm_after_topup_and_skip_unlimited(client,monkeypatch):
 _,sessions=client;remaining=[snap.GB]
 remote={'status':'active','expire':None,'data_limit':10*snap.GB,'used_traffic':9*snap.GB}
 monkeypatch.setattr(snap.PasarGuardService,'get_user',AsyncMock(side_effect=lambda *a:dict(remote)))
 bot=SimpleNamespace(send_message=AsyncMock())
 async def scan():
  async with sessions() as s:
   await alerts._send_regular_pre_expiry_alerts(bot,s,datetime.utcnow());await s.commit()
 async def run():
  async with sessions() as s:
   (await s.get(Server,1)).server_type='pasarguard'
   (await s.get(ClientService,2)).hidden_from_owner=True
   await s.commit()
  for amount,count in [(snap.GB,1),(500*snap.MB,2),(100*snap.MB,3)]:
   remote['used_traffic']=10*snap.GB-amount
   await scan();await scan();assert bot.send_message.await_count==count
  remote['used_traffic']=0;await scan()
  remote['used_traffic']=10*snap.GB-500*snap.MB;await scan()
  assert bot.send_message.await_count==5
  remote['data_limit']=0;await scan();assert bot.send_message.await_count==5
 asyncio.run(run())


@pytest.mark.parametrize('unavailable',[True,False])
def test_stale_expiry_is_verified_before_alert_and_cleanup_queue(client,monkeypatch,unavailable):
 _,sessions=client
 mock=AsyncMock(side_effect=TimeoutError() if unavailable else None,return_value={'status':'active','expire':'2030-01-01T00:00:00Z','data_limit':0,'used_traffic':0})
 monkeypatch.setattr(snap.PasarGuardService,'get_user',mock)
 bot=SimpleNamespace(send_message=AsyncMock())
 async def run():
  async with sessions() as s:
   (await s.get(Server,1)).server_type='pasarguard'
   (await s.get(ClientService,2)).hidden_from_owner=True
   svc=await s.get(ClientService,1);svc.expires_at=datetime.utcnow()-timedelta(days=10)
   await s.commit()
  async with sessions() as s:
   await alerts._send_regular_pre_expiry_alerts(bot,s,datetime.utcnow())
   await cleanup._mark_terminal_services(s,datetime.utcnow())
   assert await cleanup._enqueue_due_services(s,datetime.utcnow())==0
   assert not bot.send_message.called
   svc=await s.get(ClientService,1)
   assert svc.is_active
 asyncio.run(run())


def test_additive_alert_migration_is_idempotent_on_existing_sqlite():
 from sqlalchemy.ext.asyncio import create_async_engine
 from sqlalchemy import text,inspect
 from app.database.service_visibility import ensure_service_visibility_column
 async def run():
  engine=create_async_engine('sqlite+aiosqlite:///:memory:')
  async with engine.begin() as c:
   await c.execute(text('CREATE TABLE client_services (id INTEGER PRIMARY KEY)'))
   await c.execute(text('INSERT INTO client_services (id) VALUES (1)'))
   await ensure_service_visibility_column(c);await ensure_service_visibility_column(c)
   assert (await c.execute(text('SELECT notify_500mb_sent FROM client_services'))).scalar()==0
  await engine.dispose()
 asyncio.run(run())

@pytest.mark.parametrize('offline',[True,False])
def test_already_disabled_due_service_rechecks_panel_before_queue(client,monkeypatch,offline):
 _,sessions=client
 remote=AsyncMock(side_effect=TimeoutError() if offline else None,return_value={'status':'active','expire':None,'data_limit':0,'used_traffic':0})
 monkeypatch.setattr(snap.PasarGuardService,'get_user',remote)
 async def run():
  async with sessions() as s:
   (await s.get(Server,1)).server_type='pasarguard'
   svc=await s.get(ClientService,1);svc.is_active=False;svc.disabled_reason='expired'
   svc.disabled_at=svc.expires_at=datetime.utcnow()-timedelta(days=10);await s.commit()
  async with sessions() as s:
   assert await cleanup._enqueue_due_services(s,datetime.utcnow())==0
   svc=await s.get(ClientService,1)
   assert bool(svc.is_active) is (not offline)
 asyncio.run(run())


def test_xui_batch_covers_all_services_without_first_80_starvation(client,monkeypatch):
 _,sessions=client
 def row(name):return {'client':{'email':name,'expiryTime':0,'enable':True,'totalGB':10*snap.GB},'traffic':{'up':0,'down':9*snap.GB},'usage_known':True}
 bulk=AsyncMock(return_value=[row('mine'),row('other')]);target=AsyncMock(side_effect=AssertionError('Unnecessary per-client read'))
 monkeypatch.setattr(snap.XuiService,'list_client_snapshots',bulk)
 monkeypatch.setattr(snap.XuiService,'find_client_any',target)
 async def run():
  async with sessions() as s:
   s.info['alert_scan']=True
   for ident in (1,2):assert await snap.verified_panel_snapshot(s,await s.get(ClientService,ident)) is True
   assert bulk.await_count==1 and target.await_count==0
 asyncio.run(run())


def test_xui_missing_expiry_does_not_authorize_cached_expiration(client,monkeypatch):
 _,sessions=client
 monkeypatch.setattr(snap.XuiService,'find_client_any',AsyncMock(return_value={'client':{'enable':True},'traffic':{}}))
 async def run():
  async with sessions() as s:
   svc=await s.get(ClientService,1);svc.expires_at=datetime(2020,1,1)
   assert await snap.refresh_panel_snapshot(s,svc) is None
   assert svc.is_active
 asyncio.run(run())


def test_shortened_panel_expiry_triggers_alert_despite_old_far_future_date(client,monkeypatch):
 _,sessions=client
 expiry=datetime.utcnow()+timedelta(hours=10)
 monkeypatch.setattr(snap.PasarGuardService,'get_user',AsyncMock(return_value={'status':'active','expire':expiry.isoformat()+'Z','data_limit':0,'used_traffic':0}))
 bot=SimpleNamespace(send_message=AsyncMock())
 async def run():
  async with sessions() as s:
   (await s.get(Server,1)).server_type='pasarguard';(await s.get(ClientService,2)).hidden_from_owner=True;await s.commit()
  for _ in range(2):
   async with sessions() as s:
    await alerts._send_regular_pre_expiry_alerts(bot,s,datetime.utcnow());await s.commit()
  assert bot.send_message.await_count==1
  assert '24 ساعت' in bot.send_message.call_args.args[1]
 asyncio.run(run())


def test_volume_exhaustion_sends_renewal_notification(client,monkeypatch):
 _,sessions=client
 monkeypatch.setattr(alerts,'SessionLocal',sessions)
 monkeypatch.setattr(snap.PasarGuardService,'get_user',AsyncMock(return_value={'status':'limited','expire':None,'data_limit':snap.GB,'used_traffic':snap.GB}))
 bot=SimpleNamespace(send_message=AsyncMock())
 async def run():
  async with sessions() as s:
   (await s.get(Server,1)).server_type='pasarguard';(await s.get(ClientService,2)).hidden_from_owner=True;await s.commit()
  await alerts.scan_service_alerts(bot);await alerts.scan_service_alerts(bot)
  assert bot.send_message.await_count==1
  assert 'اتمام حجم' in bot.send_message.call_args.args[1]
 asyncio.run(run())
