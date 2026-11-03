import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import select,func
from test_miniapp import client
from app.bot.handlers.admin import conversion_requests as inbox
from app.services import conversion_recovery as recovery
from app.bot.keyboards.common import admin_panel_inline
from app.database.models import ServiceConversion,ClientService

@pytest.fixture
def review(client,monkeypatch):
 _,sessions=client
 monkeypatch.setattr(inbox,'SessionLocal',sessions)
 monkeypatch.setattr(recovery,'destination_absent',AsyncMock(return_value=True))
 monkeypatch.setattr(recovery,'source_state',AsyncMock(return_value={'client':{'enable':True}}))
 monkeypatch.setattr(inbox,'settings',SimpleNamespace(admin_ids=[11]))
 output=AsyncMock();monkeypatch.setattr(inbox,'edit_or_answer',output)
 async def seed():
  async with sessions() as s:
   s.add(ServiceConversion(id=3,source_service_id=1,target_plan_id=1,user_id=1,status='needs_review',error='stage=disable_source: <bad> https://private.example token=secret'))
   await s.commit()
 asyncio.run(seed())
 def callback(data,uid=11):return SimpleNamespace(data='admin:conversions'+data,from_user=SimpleNamespace(id=uid),answer=AsyncMock())
 return sessions,output,callback

def test_admin_menu_link():
 assert any(b.callback_data=='admin:conversions' for row in admin_panel_inline().inline_keyboard for b in row)

def test_auth_and_bad_callbacks(review):
 sessions,output,callback=review
 for data in ('',':check:3:0:0',':archive:3:0:0',':restore:3:1:0'):
  cb=callback(data,22);asyncio.run(inbox.conversion_requests(cb));assert cb.answer.await_args.kwargs['show_alert']
 output.assert_not_awaited()
 asyncio.run(inbox.conversion_requests(callback(':check:bad')));output.assert_not_awaited()

def test_details_escape_and_redact_no_panel_reads(review,monkeypatch):
 sessions,output,callback=review
 read=AsyncMock(side_effect=AssertionError('Unexpected read'));monkeypatch.setattr(inbox,'panel_state',read)
 asyncio.run(inbox.conversion_requests(callback(':detail:3:0:0')))
 text=output.await_args.args[1]
 assert '&lt;bad&gt;' in text and 'private.example' not in text and 'secret' not in text
 assert '<code>11</code>' in text and 'cv1_1' in text
 read.assert_not_awaited()

def test_archive_confirm_idempotency_preserve_claim_and_restore(review):
 sessions,output,callback=review
 async def snapshot():
  async with sessions() as s:
   record=await s.get(ServiceConversion,3);svc=await s.get(ClientService,1)
   return record.status,record.error,svc.is_active,await s.scalar(select(func.count()).select_from(ClientService))
 before=asyncio.run(snapshot())
 asyncio.run(inbox.conversion_requests(callback(':ask:3:0:0')))
 assert 'تأیید حذف' in output.await_args.kwargs['reply_markup'].inline_keyboard[0][0].text
 assert asyncio.run(snapshot())==before
 for _ in range(2):asyncio.run(inbox.conversion_requests(callback(':archive:3:0:0')))
 after=asyncio.run(snapshot());assert after[0]==inbox.READY and after[1:]==before[1:]
 asyncio.run(inbox.conversion_requests(callback(':list:1:0')))
 assert any('#3' in b.text for row in output.await_args.kwargs['reply_markup'].inline_keyboard for b in row)
 asyncio.run(inbox.conversion_requests(callback(':restore:3:1:0')))
 assert asyncio.run(snapshot())==before

@pytest.mark.parametrize('status',['completed','reserved'])
def test_stale_buttons_cannot_touch_running_or_completed(review,status):
 sessions,output,callback=review
 async def setup():
  async with sessions() as s:
   record=await s.get(ServiceConversion,3);record.status=status;await s.commit()
 asyncio.run(setup())
 for action in ('archive','restore','ask','detail'):asyncio.run(inbox.conversion_requests(callback(f':{action}:3:0:0')))
 async def verify():
  async with sessions() as s:assert (await s.get(ServiceConversion,3)).status==status
 asyncio.run(verify())

def test_pagination_and_clamp(review):
 sessions,output,callback=review
 async def seed():
  async with sessions() as s:
   for ident in range(4,23):s.add(ServiceConversion(id=ident,source_service_id=ident,target_plan_id=1,user_id=1,status='needs_review'))
   await s.commit()
 asyncio.run(seed());asyncio.run(inbox.conversion_requests(callback('')))
 rows=output.await_args.kwargs['reply_markup'].inline_keyboard
 assert sum(':detail:' in (b.callback_data or '') for row in rows for b in row)==8
 assert any(':list:0:1' in (b.callback_data or '') for row in rows for b in row)
 asyncio.run(inbox.conversion_requests(callback(':list:0:999')));assert 'صفحه 3' in output.await_args.args[1]

def test_check_reads_both_without_releasing_claim(review,monkeypatch):
 sessions,output,callback=review
 read=AsyncMock(side_effect=['غیرفعال','فعال']);monkeypatch.setattr(inbox,'panel_state',read)
 asyncio.run(inbox.conversion_requests(callback(':check:3:0:0')))
 assert read.await_count==2 and 'بررسی تازه پنل' in output.await_args.args[1]
 async def verify():
  async with sessions() as s:assert (await s.get(ServiceConversion,3)).status=='needs_review'
 asyncio.run(verify())

@pytest.mark.parametrize('kind,found,expected',[
 ('pasarguard',{'status':'active'},'فعال'),('pasarguard',{'status':'disabled'},'غیرفعال'),
 ('xui',{'client':{'enable':False}},'غیرفعال'),('xui',{'client':{'enable':True}},'فعال'),
 ('pasarguard',{'status':'expired'},'موجود است'),('xui',None,'یافت نشد')])
async def test_read_only_panel_states(kind,found,expected,monkeypatch):
 read=AsyncMock(return_value=found);api=SimpleNamespace(get_user=read,find_client_any=read)
 monkeypatch.setattr(inbox,'PasarGuardService',lambda:api);monkeypatch.setattr(inbox,'XuiService',lambda:api)
 assert expected in await inbox.panel_state(SimpleNamespace(server_type=kind),'demo')
 assert read.await_count==1
 if kind=='xui':assert read.await_args.kwargs['exhaustive'] is True

async def test_timeout_is_unknown(monkeypatch):
 monkeypatch.setattr(inbox,'PasarGuardService',lambda:SimpleNamespace(get_user=AsyncMock(side_effect=TimeoutError())))
 assert 'نامشخص' in await inbox.panel_state(SimpleNamespace(server_type='pasarguard'),'demo')
