"""Released claims are single-use and customers choose categories, not plans."""
import asyncio,json,uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import select,func
from test_miniapp import client,signed
from test_native_conversion_and_rotation import conversion
from app.database.models import ClientService,ServiceConversion,MiniAppOperation,Plan,Server,Setting
from app.services import conversion_recovery as recovery


def seed_failure(sessions,status='needs_review',error='stage=disable_source: timeout'):
 async def seed():
  async with sessions() as s:
   s.add(ServiceConversion(id=3,source_service_id=1,target_plan_id=4,user_id=1,status=status,error=error))
   await s.commit()
 asyncio.run(seed())


def release_mocks(monkeypatch,enabled=True):
 absent=AsyncMock(return_value=True);read=AsyncMock(return_value={'client':{'enable':enabled}});write=AsyncMock()
 monkeypatch.setattr(recovery,'destination_absent',absent);monkeypatch.setattr(recovery,'source_state',read);monkeypatch.setattr(recovery,'set_enabled',write)
 return absent,read,write


@pytest.mark.parametrize('status',['needs_review','review_archived','failed','error'])
@pytest.mark.parametrize('enabled',[True,False])
def test_release_preserves_quota_and_only_restores_disabled_source(conversion,monkeypatch,status,enabled):
 _,sessions,_,_,_=conversion;seed_failure(sessions,status)
 absent,read,write=release_mocks(monkeypatch,enabled)
 async def snapshot():
  async with sessions() as s:
   svc=await s.get(ClientService,1);return svc.total_bytes,svc.expires_at,svc.used_bytes
 before=asyncio.run(snapshot())
 asyncio.run(recovery.release_failed(3,sessions))
 async def verify():
  async with sessions() as s:
   row=await s.get(ServiceConversion,3);assert row.status==recovery.READY and row.error=='stage=disable_source: timeout'
 asyncio.run(verify());assert asyncio.run(snapshot())==before
 assert absent.await_count==2 and write.await_count==int(not enabled)
 if not enabled:assert write.await_args.args[2] is True


@pytest.mark.parametrize('problem',['target_exists','unknown_source','read_timeout','enable_timeout','target_appears'])
def test_ambiguous_or_existing_target_does_not_release(conversion,monkeypatch,problem):
 _,sessions,_,_,_=conversion;seed_failure(sessions)
 absent,read,write=release_mocks(monkeypatch,enabled=problem!='enable_timeout')
 if problem=='target_exists':absent.return_value=False
 if problem=='unknown_source':read.return_value=None
 if problem=='read_timeout':absent.side_effect=TimeoutError()
 if problem=='enable_timeout':write.side_effect=TimeoutError()
 if problem=='target_appears':absent.side_effect=[True,False]
 with pytest.raises(ValueError):asyncio.run(recovery.release_failed(3,sessions))
 async def verify():
  async with sessions() as s:assert (await s.get(ServiceConversion,3)).status=='needs_review'
 asyncio.run(verify())
 if problem!='enable_timeout':write.assert_not_awaited()


@pytest.mark.parametrize('status',['reserved','completed'])
def test_release_never_touches_processing_or_success(conversion,monkeypatch,status):
 _,sessions,_,_,_=conversion;seed_failure(sessions,status);absent,read,write=release_mocks(monkeypatch)
 with pytest.raises(ValueError):asyncio.run(recovery.release_failed(3,sessions))
 absent.assert_not_awaited();write.assert_not_awaited()


def test_release_invalidates_old_drafts_and_queued_only_for_this_service(conversion,monkeypatch):
 _,sessions,_,_,_=conversion;seed_failure(sessions);release_mocks(monkeypatch)
 async def seed():
  async with sessions() as s:
   for status,sid in [('draft',1),('queued',1),('draft',2)]:
    s.add(MiniAppOperation(user_id=1,key=str(uuid.uuid4()),kind='public_convert',status=status,payload={'service_id':sid}))
   await s.commit()
 asyncio.run(seed());asyncio.run(recovery.release_failed(3,sessions))
 async def verify():
  async with sessions() as s:
   ops=(await s.scalars(select(MiniAppOperation).order_by(MiniAppOperation.id))).all()
   assert [o.status for o in ops]==['failed','failed','draft']
 asyncio.run(verify())


def test_legacy_archive_released_on_open_then_one_successful_conversion(conversion,monkeypatch):
 c,sessions,flow,_,_=conversion;seed_failure(sessions,'review_archived');release_mocks(monkeypatch)
 h={'X-Telegram-Init-Data':signed()};base='/api/miniapp/services/1/conversion'
 catalog=c.get(base,headers=h);assert catalog.status_code==200,catalog.text
 assert catalog.json()['categories']==[{'id':3,'name':'VIP'}]
 key=str(uuid.uuid4());preview=c.post(base+'/preview',headers=h,json={'key':key,'target_category_id':3})
 assert preview.status_code==200,preview.text
 quote=preview.json()['quote'];assert quote['target_plan_id']==4 and quote['target_title']=='VIP'
 assert quote['destination_bytes']==9*1024**3
 assert c.post(base+'/confirm',headers=h,json={'key':key}).status_code==200
 from app.api import miniapp_actions as actions
 asyncio.run(actions.process_operations())
 assert flow.create_converted.await_count==1
 async def verify():
  async with sessions() as s:
   row=await s.get(ServiceConversion,3);assert row.status=='completed'
   assert await s.scalar(select(func.count()).select_from(ServiceConversion))==1
 asyncio.run(verify())


def test_category_auto_select_prefers_configured_server_order_and_hides_invalid(conversion):
 c,sessions,flow,_,_=conversion
 async def seed():
  async with sessions() as s:
   s.add(Server(id=3,name='Preferred',server_type='pasarguard',panel_url='https://example',username='admin',password_encrypted='private',meta={'scope':'public'}))
   s.add(Plan(id=8,title='Hidden template',volume_gb=1,duration_days=10,price_irt=1,server_id=3,category_id=3))
   r=await s.get(Setting,'convert_category_rules');r.value=json.dumps({'1':{'price_per_gb_irt':6000,'server_ids':[1]},'3':{'price_per_gb_irt':12000,'server_ids':[3,1]}})
   await s.commit()
 asyncio.run(seed());h={'X-Telegram-Init-Data':signed()};base='/api/miniapp/services/1/conversion'
 r=c.post(base+'/preview',headers=h,json={'key':str(uuid.uuid4()),'target_category_id':3})
 assert r.status_code==200,r.text
 assert r.json()['quote']['target_plan_id']==8 and r.json()['quote']['target_title']=='VIP'
 for bad in (1,999):
  r=c.post(base+'/preview',headers=h,json={'key':str(uuid.uuid4()),'target_category_id':bad})
  assert r.status_code==409,r.text
 flow.create_converted.assert_not_awaited()


def test_bot_category_button_goes_straight_to_preview(conversion,monkeypatch):
 _,sessions,flow,_,bot=conversion
 from app.services.miniapp_runtime import native_event,NativeState
 from app.database.models import User
 output=AsyncMock();monkeypatch.setattr(flow,'edit_or_answer',output)
 async def run():
  async with sessions() as s:user=await s.get(User,1)
  _,cb,_=native_event(bot,user,'','svcconvert:cat:1:3')
  state=NativeState();await flow.convert_choose_server(cb,state)
  assert (await state.get_data())['convert_quote']['target_plan_id']==4
 asyncio.run(run())
 text=output.await_args.args[1];assert 'پیش‌نمایش' in text
 rows=output.await_args.kwargs['reply_markup'].inline_keyboard
 assert rows[0][0].callback_data=='svcconvert:confirm:1:4'
 assert rows[-1][0].callback_data=='svcconvert:source:1'


async def test_strict_pasarguard_absence_requires_404(monkeypatch):
 api=SimpleNamespace(_request=AsyncMock(side_effect=RuntimeError('HTTP (404)')))
 monkeypatch.setattr(recovery,'PasarGuardService',lambda:api)
 server=SimpleNamespace(server_type='pasarguard')
 assert await recovery.destination_absent(server,'cv1_4')
 api._request.side_effect=RuntimeError('HTTP (403)')
 with pytest.raises(RuntimeError):await recovery.destination_absent(server,'cv1_4')
 api._request.side_effect=None;api._request.return_value={}
 assert not await recovery.destination_absent(server,'cv1_4')


async def test_sanaei_absence_uses_strict_name_scan(monkeypatch):
 read=AsyncMock(return_value=False);monkeypatch.setattr(recovery,'XuiService',lambda:SimpleNamespace(client_username_exists=read))
 assert await recovery.destination_absent(SimpleNamespace(server_type='xui'),'cv1_4')
 read.side_effect=RuntimeError('incomplete page')
 with pytest.raises(RuntimeError):await recovery.destination_absent(SimpleNamespace(server_type='xui'),'cv1_4')


def test_two_admins_release_one_claim_without_duplicate_enable(conversion,monkeypatch):
 _,sessions,_,_,_=conversion;seed_failure(sessions);absent,read,write=release_mocks(monkeypatch,False)
 async def run():
  outcomes=await asyncio.gather(recovery.release_failed(3,sessions),recovery.release_failed(3,sessions),return_exceptions=True)
  assert any(outcome is None for outcome in outcomes)
 asyncio.run(run());assert write.await_count==1


def test_failed_claim_message_is_actionable_and_has_id(conversion):
 c,sessions,_,_,_=conversion;seed_failure(sessions)
 r=c.get('/api/miniapp/services/1/conversion',headers={'X-Telegram-Init-Data':signed()})
 assert r.status_code==409 and '#3' in r.json()['detail'] and 'حذف و آزادسازی' in r.json()['detail']


def test_admin_delete_then_retry_reuses_claim(conversion,monkeypatch):
 c,sessions,flow,_,_=conversion;seed_failure(sessions);release_mocks(monkeypatch)
 from app.bot.handlers.admin import conversion_requests as inbox
 monkeypatch.setattr(inbox,'SessionLocal',sessions);monkeypatch.setattr(inbox,'settings',SimpleNamespace(admin_ids=[11]))
 output=AsyncMock();monkeypatch.setattr(inbox,'edit_or_answer',output)
 cb=SimpleNamespace(data='admin:conversions:archive:3:0:0',from_user=SimpleNamespace(id=11),answer=AsyncMock())
 asyncio.run(inbox.conversion_requests(cb));assert 'آزاد شد' in output.await_args.args[1]
 h={'X-Telegram-Init-Data':signed()};base='/api/miniapp/services/1/conversion';key=str(uuid.uuid4())
 r=c.post(base+'/preview',headers=h,json={'key':key,'target_category_id':3});assert r.status_code==200,r.text
 c.post(base+'/confirm',headers=h,json={'key':key})
 from app.api import miniapp_actions as actions
 asyncio.run(actions.process_operations());assert flow.create_converted.await_count==1
 # Repeated old admin button cannot unlock the completed conversion.
 asyncio.run(inbox.conversion_requests(cb));assert 'وضعیت درخواست تغییر' in output.await_args.args[1]
 async def verify():
  async with sessions() as s:assert (await s.get(ServiceConversion,3)).status=='completed'
 asyncio.run(verify())
