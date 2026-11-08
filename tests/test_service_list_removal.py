"""Link-based local removal must not touch upstream configuration or money."""
import asyncio,json
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import select,func
from sqlalchemy.ext.asyncio import create_async_engine
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.base import StorageKey
from aiogram.types import CallbackQuery,Message,Chat,User as TelegramUser
from test_miniapp import client,signed
from app.database.models import ClientService,User,Setting,Order,Server,ServiceConversion,ServiceDeletionTask,MiniAppOperation,ResellerAccount
from app.database.service_visibility import ensure_service_visibility_column
from app.services import service_list_removal as removal
from app.bot.handlers.admin import service_list_removal as flow
from app.services.service_grace import visible_in_my_services,is_auto_purge_service


@pytest.fixture
def local(client,monkeypatch):
 c,sessions=client
 monkeypatch.setattr(removal,'settings',SimpleNamespace(admin_ids=[11]))
 monkeypatch.setattr(flow,'settings',SimpleNamespace(admin_ids=[11]))
 monkeypatch.setattr(flow,'SessionLocal',sessions)
 monkeypatch.setattr(flow,'ui_message',AsyncMock())
 monkeypatch.setattr(flow,'edit_or_answer',AsyncMock())
 monkeypatch.setattr(CallbackQuery,'answer',AsyncMock())
 return c,sessions


def state():return FSMContext(storage=MemoryStorage(),key=StorageKey(bot_id=123,chat_id=11,user_id=11))
def message(text='',uid=11,chat_type='private'):
 return Message(message_id=1,date=datetime.now(timezone.utc),chat=Chat(id=uid,type=chat_type),from_user=TelegramUser(id=uid,is_bot=False,first_name='Admin'),text=text)
def callback(data='admin:unlink_service',uid=11,chat_type='private'):
 return CallbackQuery(id='test',from_user=TelegramUser(id=uid,is_bot=False,first_name='Admin'),chat_instance='test',message=message(uid=uid,chat_type=chat_type),data=data)


@pytest.mark.parametrize('url',[
 'https://example.com/sub/mine','https://EXAMPLE.com:443/sub/mine/#Friendly',
 'happ://add/https%3A%2F%2Fexample.com%2Fsub%2Fmine',
])
def test_exact_subscription_lookup_and_normalization(local,url):
 _,sessions=local
 async def run():
  async with sessions() as s:
   svc,owner,server=await removal.lookup(s,url,11)
   assert svc.id==1 and owner.telegram_id==11 and server.id==1
 asyncio.run(run())


@pytest.mark.parametrize('url',['https://other.example/sub/mine','https://example.com/sub/mine?token=wrong','https://example.com:0/sub/mine','https://example.com/sub/other-token','','not-a-link','vless://x','https://example.com/sub/mine words','file:///tmp/test'])
def test_lookup_rejects_invalid_or_nonmatching_identity(local,url):
 _,sessions=local
 async def run():
  async with sessions() as s:
   with pytest.raises(removal.ListRemovalError):await removal.lookup(s,url,11)
 asyncio.run(run())


def test_happ_crypt5_is_compared_exactly(local):
 _,sessions=local
 async def run():
  async with sessions() as s:
   svc=await s.get(ClientService,1);svc.sub_link='happ://crypt5/AbCdEf';await s.commit()
   assert (await removal.lookup(s,'happ://crypt5/AbCdEf',11))[0].id==1
   with pytest.raises(removal.ListRemovalError):await removal.lookup(s,'happ://crypt5/abcdef',11)
 asyncio.run(run())


def test_duplicate_links_are_never_resolved_by_first_match(local):
 _,sessions=local
 async def run():
  async with sessions() as s:
   other=await s.get(ClientService,2);other.sub_link='https://EXAMPLE.com/sub/mine#label';await s.commit()
   with pytest.raises(removal.ListRemovalError,match='چند کانفیگ'):await removal.lookup(s,'https://example.com/sub/mine',11)
 asyncio.run(run())


@pytest.mark.parametrize('provider',['pasarguard','xui','mikrotik'])
def test_only_visibility_flag_changes_preserves_service_owner_money_and_orders(local,provider):
 c,sessions=local
 async def run():
  async with sessions() as s:
   server=await s.get(Server,1);server.server_type=provider
   svc=await s.get(ClientService,1);svc.xui_uuid='uuid-kept';svc.inbound_ids=[1,2]
   order=await s.get(Order,1);order.service_id=svc.id;await s.commit()
   before={col.name:getattr(svc,col.name) for col in ClientService.__table__.columns}
   before_order={col.name:getattr(order,col.name) for col in Order.__table__.columns}
   users={u.id:u.wallet_balance for u in (await s.scalars(select(User))).all()}
   await removal.remove_from_owner_list(s,svc.id,11,svc.user_id,removal.link_fingerprint(svc.sub_link));await s.commit()
  async with sessions() as s:
   svc=await s.get(ClientService,1);after={col.name:getattr(svc,col.name) for col in ClientService.__table__.columns}
   assert after.pop('hidden_from_owner') is True
   before.pop('hidden_from_owner');assert before==after
   order=await s.get(Order,1);assert before_order=={col.name:getattr(order,col.name) for col in Order.__table__.columns}
   assert users=={u.id:u.wallet_balance for u in (await s.scalars(select(User))).all()}
   assert not visible_in_my_services(svc) and not is_auto_purge_service(svc)
   assert await s.scalar(select(func.count()).select_from(ServiceDeletionTask))==0
   audit=await s.scalar(select(Setting).where(Setting.key.startswith('service_list_removal:')))
   assert json.loads(audit.value)['telegram_id']==11 and 'sub_link' not in audit.value
   with pytest.raises(removal.ListRemovalError,match='قبلاً'):await removal.remove_from_owner_list(s,1,11,1,removal.link_fingerprint(svc.sub_link))
 asyncio.run(run())
 # Public bot and MiniApp use the same visibility and access predicate.
 r=c.get('/api/miniapp/session',headers={'X-Telegram-Init-Data':signed()});assert r.status_code==200
 assert not r.json()['services']
 assert c.get('/api/miniapp/services/1/link',headers={'X-Telegram-Init-Data':signed()}).status_code==404


@pytest.mark.parametrize('change',['owner','link'])
def test_owner_or_link_change_invalidates_confirmation(local,change):
 _,sessions=local
 async def run():
  async with sessions() as s:
   svc=await s.get(ClientService,1);fingerprint=removal.link_fingerprint(svc.sub_link)
   if change=='owner':svc.user_id=2
   else:svc.sub_link='https://example.com/sub/rotated'
   await s.commit()
   with pytest.raises(removal.ListRemovalError,match='تغییر کرده'):await removal.remove_from_owner_list(s,1,11,1,fingerprint)
   await s.refresh(svc);assert not svc.hidden_from_owner
 asyncio.run(run())


@pytest.mark.parametrize('pending',['deletion','conversion','payment','native'])
def test_pending_mutations_block_local_removal(local,pending):
 _,sessions=local
 async def run():
  async with sessions() as s:
   if pending=='deletion':s.add(ServiceDeletionTask(source_service_id=1,user_id=1,server_id=1,status='pending'))
   if pending=='conversion':s.add(ServiceConversion(source_service_id=1,user_id=1,target_plan_id=1,status='reserved'))
   if pending=='payment':
    order=await s.get(Order,1);order.service_id=1;order.status='pending'
   if pending=='native':s.add(MiniAppOperation(user_id=1,key='pending',kind='public_delete',status='queued',payload={'service_id':1}))
   await s.commit()
   with pytest.raises(removal.ListRemovalError,match='انتظار'):await removal.lookup(s,'https://example.com/sub/mine',11)
 asyncio.run(run())


def test_hidden_expired_service_is_not_queued_or_alerted(local):
 _,sessions=local
 from app.jobs import service_cleanup as cleanup,service_alerts as alerts
 async def run():
  async with sessions() as s:
   svc=await s.get(ClientService,1);svc.hidden_from_owner=True;svc.is_active=False
   svc.expires_at=datetime.utcnow()-timedelta(days=10);svc.disabled_at=svc.expires_at;svc.disabled_reason='expired'
   await s.commit()
   assert await cleanup._enqueue_due_services(s,datetime.utcnow())==0
   bot=SimpleNamespace(send_message=AsyncMock())
   await alerts._process_disabled_services(bot,s,datetime.utcnow());await alerts._send_regular_pre_expiry_alerts(bot,s,datetime.utcnow())
   bot.send_message.assert_not_awaited()
   assert await s.scalar(select(func.count()).select_from(ServiceDeletionTask))==0
 asyncio.run(run())


def test_workflow_preview_confirm_and_old_button_replay(local):
 _,sessions=local;st=state()
 async def run():
  await flow.begin(callback(),st)
  await flow.receive_link(message('https://example.com/sub/other'),st)
  text=flow.ui_message.await_args.args[1]
  assert 'Other' in text and '<code>22</code>' in text
  data=(await st.get_data())['list_removal'];assert 'https://' not in json.dumps(data)
  async with sessions() as s:assert not (await s.get(ClientService,2)).hidden_from_owner
  cb=callback('admin:unlink_confirm:'+data['nonce']);await flow.confirm(cb,st)
  assert await st.get_state() is None
  async with sessions() as s:assert (await s.get(ClientService,2)).hidden_from_owner
  count=flow.edit_or_answer.await_count;await flow.confirm(cb,st);assert flow.edit_or_answer.await_count==count
 asyncio.run(run())


def test_cancel_and_invalid_lookup_clear_old_confirmation(local):
 _,sessions=local;st=state()
 async def run():
  await flow.begin(callback(),st);await flow.receive_link(message('https://example.com/sub/mine'),st)
  old=(await st.get_data())['list_removal']['nonce']
  await flow.receive_link(message('not-a-link'),st)
  await flow.confirm(callback('admin:unlink_confirm:'+old),st)
  async with sessions() as s:assert not (await s.get(ClientService,1)).hidden_from_owner
  await flow.receive_link(message('https://example.com/sub/mine'),st)
  new=(await st.get_data())['list_removal']['nonce'];await flow.cancel(callback('admin:unlink_cancel:'+new),st)
  assert await st.get_state() is None
 asyncio.run(run())


def test_expired_confirmation_does_nothing(local):
 _,sessions=local;st=state()
 async def run():
  await flow.begin(callback(),st);await flow.receive_link(message('https://example.com/sub/mine'),st)
  data=(await st.get_data())['list_removal'];data['at']=(datetime.utcnow()-timedelta(minutes=11)).isoformat()
  await st.update_data(list_removal=data);await flow.confirm(callback('admin:unlink_confirm:'+data['nonce']),st)
  async with sessions() as s:assert not (await s.get(ClientService,1)).hidden_from_owner
 asyncio.run(run())


def test_admin_only_and_private_chat(local):
 _,sessions=local;st=state()
 async def run():
  await flow.begin(callback(uid=22),st);await flow.begin(callback(chat_type='group'),st)
  assert await st.get_state() is None
  flow.edit_or_answer.assert_not_awaited()
  async with sessions() as s:
   with pytest.raises(removal.ListRemovalError):await removal.lookup(s,'https://example.com/sub/mine',22)
 asyncio.run(run())


def test_migration_upgrades_existing_sqlite_without_data_loss(tmp_path):
 async def run():
  engine=create_async_engine('sqlite+aiosqlite:///'+str(tmp_path/'legacy.db'))
  async with engine.begin() as conn:
   await conn.exec_driver_sql('CREATE TABLE client_services(id INTEGER PRIMARY KEY, client_username TEXT)')
   await conn.exec_driver_sql("INSERT INTO client_services VALUES (1, 'keep')")
   await ensure_service_visibility_column(conn);await ensure_service_visibility_column(conn)
   row=(await conn.exec_driver_sql('SELECT client_username,hidden_from_owner FROM client_services')).one()
   assert tuple(row)==('keep',0)
  await engine.dispose()
 asyncio.run(run())


def test_menu_and_reseller_accounting_preserved(local):
 _,sessions=local
 from app.bot.keyboards.common import user_interaction_inline
 assert any(b.callback_data=='admin:unlink_service' for row in user_interaction_inline().inline_keyboard for b in row)
 async def run():
  async with sessions() as s:
   account=ResellerAccount(id=1,user_id=1,server_id=1,billing_mode='volume',total_bytes=100*1024**3,reserved_bytes=30*1024**3,used_bytes=12*1024**3)
   s.add(account);await s.flush()
   svc=await s.get(ClientService,1);svc.reseller_id=1;svc.reseller_reserved_bytes=30*1024**3
   await s.commit()
   before={col.name:getattr(account,col.name) for col in ResellerAccount.__table__.columns}
   await removal.remove_from_owner_list(s,1,11,1,removal.link_fingerprint(svc.sub_link));await s.commit()
  async with sessions() as s:
   account=await s.get(ResellerAccount,1)
   assert before=={col.name:getattr(account,col.name) for col in ResellerAccount.__table__.columns}
   svc=await s.get(ClientService,1);assert svc.reseller_reserved_bytes==30*1024**3 and not visible_in_my_services(svc)
 asyncio.run(run())


def test_rollback_keeps_visibility_and_audit_atomic(local):
 _,sessions=local
 async def run():
  async with sessions() as s:
   await removal.remove_from_owner_list(s,1,11,1,removal.link_fingerprint('https://example.com/sub/mine'))
   await s.rollback()
  async with sessions() as s:
   assert not (await s.get(ClientService,1)).hidden_from_owner
   assert await s.scalar(select(func.count()).select_from(Setting).where(Setting.key.startswith('service_list_removal:')))==0
 asyncio.run(run())


def test_concurrent_confirmations_only_record_one_removal(local):
 _,sessions=local
 async def once():
  async with sessions() as s:
   await removal.remove_from_owner_list(s,1,11,1,removal.link_fingerprint('https://example.com/sub/mine'))
   await s.commit()
 async def run():
  outcomes=await asyncio.gather(once(),once(),return_exceptions=True)
  assert sum(outcome is None for outcome in outcomes)==1
  async with sessions() as s:
   assert (await s.get(ClientService,1)).hidden_from_owner
   assert await s.scalar(select(func.count()).select_from(Setting).where(Setting.key.startswith('service_list_removal:')))==1
 asyncio.run(run())
