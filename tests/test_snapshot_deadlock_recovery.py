"""Lock order and whole-transaction retry regressions; no real panel writes."""
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.dialects import postgresql
from test_miniapp import client
from app.database.models import Setting, ClientService, Server, ResellerAccount
from app.database import transaction_retry as retry
from app.services import panel_snapshot as snap
from app.jobs import service_cleanup as cleanup

class DriverDeadlock(Exception):
 sqlstate='40P01'


def deadlock():return DBAPIError('UPDATE reseller_accounts',{},DriverDeadlock('deadlock detected'),False)


def test_deadlock_detection_uses_sqlstate_not_text():
 assert retry.is_deadlock(deadlock())
 assert not retry.is_deadlock(DBAPIError('x',{},ValueError('deadlock detected'),False))
 assert not retry.is_deadlock(ValueError('40P01'))


def test_retry_replays_only_after_rollback_with_fresh_session(client,monkeypatch):
 _,sessions=client
 monkeypatch.setattr(retry.asyncio,'sleep',AsyncMock())
 seen=[]
 async def operation(s):
  seen.append(s)
  item=await s.get(Setting,'deadlock_counter')
  item.value=str(int(item.value)+1);await s.flush()
  if len(seen)<3:raise deadlock()
  return 'done'
 async def run():
  async with sessions() as s:s.add(Setting(key='deadlock_counter',value='0'));await s.commit()
  assert await retry.run_snapshot_transaction(sessions,operation,label='test')=='done'
  assert len(seen)==3 and len({id(s) for s in seen})==3
  async with sessions() as s:assert (await s.get(Setting,'deadlock_counter')).value=='1'
 asyncio.run(run())


@pytest.mark.parametrize('transient',[True,False])
def test_retry_is_bounded_and_other_database_errors_are_not_replayed(client,monkeypatch,transient):
 _,sessions=client;calls=[]
 monkeypatch.setattr(retry.asyncio,'sleep',AsyncMock())
 async def operation(s):
  calls.append(s);s.add(Setting(key='must_rollback',value='no'));await s.flush()
  raise deadlock() if transient else DBAPIError('x',{},ValueError('not transient'),False)
 async def run():
  with pytest.raises(DBAPIError):await retry.run_snapshot_transaction(sessions,operation,label='test')
  assert len(calls)==(3 if transient else 1)
  async with sessions() as s:assert await s.get(Setting,'must_rollback') is None
 asyncio.run(run())


def test_snapshot_locks_reseller_before_service_autoflush(client,monkeypatch):
 _,sessions=client
 monkeypatch.setattr(snap.PasarGuardService,'get_user',AsyncMock(return_value={'status':'limited','expire':None,'data_limit':10,'used_traffic':10}))
 statements=[]
 def record(conn,clause,multiparams,params,options):
  statements.append(str(clause.compile(dialect=postgresql.dialect())).lower())
 async def run():
  async with sessions() as s:
   (await s.get(Server,1)).server_type='pasarguard'
   s.add(ResellerAccount(id=1,user_id=1,server_id=1,total_bytes=100,reserved_bytes=10))
   svc=await s.get(ClientService,1);svc.reseller_id=1;svc.reseller_reserved_bytes=10;await s.commit()
  engine=sessions.kw['bind']
  event.listen(engine.sync_engine,'before_execute',record)
  try:
   async with sessions() as s:
    svc=await s.get(ClientService,1)
    assert await snap.verified_panel_snapshot(s,svc) is True
    await s.commit()
  finally:event.remove(engine.sync_engine,'before_execute',record)
  parent=next(i for i,q in enumerate(statements) if q.startswith('select reseller_accounts.id') and 'for update' in q)
  child=next(i for i,q in enumerate(statements) if q.startswith('update client_services') or 'from client_services' in q and 'for update' in q)
  assert parent<child
 asyncio.run(run())


def test_cleanup_commits_each_service_and_external_actions_run_after_retry(client,monkeypatch):
 _,sessions=client
 monkeypatch.setattr(cleanup,'SessionLocal',sessions)
 monkeypatch.setattr(retry.asyncio,'sleep',AsyncMock())
 calls=[]
 async def snapshot(s,sid,now):
  calls.append((sid,s))
  s.add(Setting(key=f'cleanup_committed:{sid}',value='yes'));await s.flush()
  if len(calls)==1:raise deadlock()
  return 1
 async def external(*a,**kw):
  async with sessions() as s:
   assert await s.get(Setting,'cleanup_committed:1')
   assert await s.get(Setting,'cleanup_committed:2')
  return 0
 process=AsyncMock(side_effect=external);notify=AsyncMock(side_effect=external)
 monkeypatch.setattr(cleanup,'_cleanup_service_snapshot',snapshot)
 monkeypatch.setattr(cleanup,'process_service_deletion_queue',process)
 monkeypatch.setattr(cleanup,'notify_service_deletion_task_admin',notify)
 async def run():
  async with sessions() as s:
   for sid in (1,2):(await s.get(ClientService,sid)).expires_at=datetime.utcnow()-timedelta(days=1)
   await s.commit()
  await cleanup.cleanup_expired_services()
  assert [sid for sid,_ in calls]==[1,1,2]
  assert len({id(s) for _,s in calls})==3
  assert process.await_count==notify.await_count==1
 asyncio.run(run())

@pytest.mark.parametrize('state',['expired','renewed','offline'])
def test_per_service_cleanup_preserves_live_panel_verification_and_grace(client,monkeypatch,state):
 from app.database.models import ServiceDeletionTask
 _,sessions=client;past=datetime.utcnow()-timedelta(days=5)
 remote={'status':'expired','expire':past.isoformat()+'Z','data_limit':0,'used_traffic':0}
 if state=='renewed':remote.update(status='active',expire=None)
 monkeypatch.setattr(snap.PasarGuardService,'get_user',AsyncMock(side_effect=TimeoutError() if state=='offline' else None,return_value=remote))
 async def run():
  async with sessions() as s:
   (await s.get(Server,1)).server_type='pasarguard'
   svc=await s.get(ClientService,1);svc.is_active=False;svc.expires_at=past;svc.disabled_at=past;svc.disabled_reason='expired';await s.commit()
  async with sessions() as s:
   count=await cleanup._cleanup_service_snapshot(s,1,datetime.utcnow());await s.commit()
   assert count==(1 if state=='expired' else 0)
  async with sessions() as s:
   svc=await s.get(ClientService,1)
   task=await s.scalar(select(ServiceDeletionTask).where(ServiceDeletionTask.source_service_id==1))
   assert bool(task) is (state=='expired')
   if state=='renewed':assert svc.is_active and svc.expires_at is None
   if state=='offline':assert svc and not svc.is_active
 asyncio.run(run())
