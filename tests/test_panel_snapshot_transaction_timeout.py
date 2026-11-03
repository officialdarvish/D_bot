"""Regressions for cancellation during asyncpg/SQLAlchemy autoflush."""
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from test_miniapp import client
from app.database.models import ClientService, Server, Setting
from app.services import panel_snapshot as snap

REMOTE={'status':'active','expire':None,'data_limit':0,'used_traffic':10}


def test_database_updates_outlive_network_deadline_without_cancellation(client,monkeypatch):
 _,sessions=client
 monkeypatch.setattr(snap,'PANEL_READ_TIMEOUT_SECONDS',.01)
 monkeypatch.setattr(snap.PasarGuardService,'get_user',AsyncMock(return_value=REMOTE))
 original=snap.apply_reseller_usage_delta
 cancelled=[]
 async def slow_database(session,svc,used):
  try:await asyncio.sleep(.04)
  except asyncio.CancelledError:cancelled.append(True);raise
  return await original(session,svc,used)
 monkeypatch.setattr(snap,'apply_reseller_usage_delta',slow_database)
 async def run():
  async with sessions() as s:
   (await s.get(Server,1)).server_type='pasarguard';await s.commit()
   svc=await s.get(ClientService,1)
   assert await snap.verified_panel_snapshot(s,svc) is True
   await s.commit()
   assert not cancelled and svc.used_bytes==10
   assert s.is_active and (await s.get(ClientService,2)).id==2
 asyncio.run(run())


def test_network_timeout_leaves_transaction_and_service_usable(client,monkeypatch):
 _,sessions=client
 monkeypatch.setattr(snap,'PANEL_READ_TIMEOUT_SECONDS',.01)
 async def slow_panel(*a):await asyncio.sleep(.05);return REMOTE
 read=AsyncMock(side_effect=slow_panel)
 monkeypatch.setattr(snap.PasarGuardService,'get_user',read)
 async def run():
  async with sessions() as s:
   (await s.get(Server,1)).server_type='pasarguard';await s.commit()
   svc=await s.get(ClientService,1)
   before=(svc.expires_at,svc.used_bytes,svc.total_bytes,svc.is_active)
   assert await snap.verified_panel_snapshot(s,svc) is None
   assert before==(svc.expires_at,svc.used_bytes,svc.total_bytes,svc.is_active)
   assert await snap.verified_panel_snapshot(s,await s.get(ClientService,2)) is None
   assert read.await_count==1
   s.add(Setting(key='timeout_still_usable',value='yes'));await s.commit()
   assert (await s.get(Setting,'timeout_still_usable')).value=='yes'
 asyncio.run(run())


def test_real_flush_failure_propagates_original_error_for_rollback(client,monkeypatch):
 _,sessions=client
 monkeypatch.setattr(snap.PasarGuardService,'get_user',AsyncMock(return_value=REMOTE))
 async def broken_database(session,svc,used):
  session.add(Setting(key='duplicate_for_timeout_test',value='second'))
  await session.flush()
 monkeypatch.setattr(snap,'apply_reseller_usage_delta',broken_database)
 async def run():
  async with sessions() as s:
   (await s.get(Server,1)).server_type='pasarguard'
   s.add(Setting(key='duplicate_for_timeout_test',value='first'));await s.commit()
   svc=await s.get(ClientService,1)
   with pytest.raises(IntegrityError):await snap.verified_panel_snapshot(s,svc)
   assert 1 not in s.info['verified_panel_snapshots']
   assert not s.info['snapshot_failed_servers']
   await s.rollback()
   assert (await s.get(ClientService,1)).used_bytes==12*1024**3
   assert (await s.get(Setting,'duplicate_for_timeout_test')).value=='first'
 asyncio.run(run())


def test_slow_reseller_reservation_reconciliation_is_not_cancelled(client,monkeypatch):
 from app.database.models import ResellerAccount
 _,sessions=client
 monkeypatch.setattr(snap,'PANEL_READ_TIMEOUT_SECONDS',.01)
 monkeypatch.setattr(snap.PasarGuardService,'get_user',AsyncMock(return_value={**REMOTE,'status':'limited','data_limit':10}))
 original=snap.drop_inactive_reservation
 async def slow_reconcile(session,svc):
  await asyncio.sleep(.04)
  return await original(session,svc)
 monkeypatch.setattr(snap,'drop_inactive_reservation',slow_reconcile)
 async def run():
  async with sessions() as s:
   (await s.get(Server,1)).server_type='pasarguard'
   s.add(ResellerAccount(id=1,user_id=1,server_id=1,total_bytes=100,reserved_bytes=10))
   svc=await s.get(ClientService,1);svc.reseller_id=1;svc.reseller_reserved_bytes=10
   await s.commit()
   assert await snap.verified_panel_snapshot(s,svc) is True
   await s.commit()
   assert svc.is_active is False and svc.reseller_reserved_bytes==0
   assert s.is_active
 asyncio.run(run())
