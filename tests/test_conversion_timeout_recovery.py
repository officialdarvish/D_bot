"""Lost panel replies must be verified, never blindly replayed."""
import asyncio,json,uuid
from datetime import datetime,timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
import httpx,pytest
from sqlalchemy import select,func
from test_miniapp import client,signed
from test_native_conversion_and_rotation import conversion
from app.services import conversion_provider as provider
from app.services import pasarguard_service as pg
from app.database.models import Server,Plan,Setting,ServiceConversion,ClientService

@pytest.fixture(autouse=True)
def fast_reads(monkeypatch):
 monkeypatch.setattr(provider.asyncio,'sleep',AsyncMock())

@pytest.mark.parametrize('kind',['pasarguard','xui'])
@pytest.mark.parametrize('failure',[httpx.ReadTimeout,httpx.WriteTimeout,httpx.RemoteProtocolError])
async def test_lost_disable_reply_recovers_only_from_readback(kind,failure,monkeypatch):
 error=failure('lost response')
 if kind=='pasarguard':error=pg.PasarGuardConnectionError(error)
 write=AsyncMock(side_effect=error)
 wrong={'status':'active'} if kind=='pasarguard' else {'client':{'enable':True}}
 right={'status':'disabled'} if kind=='pasarguard' else {'client':{'enable':False}}
 read=AsyncMock(side_effect=[httpx.ReadTimeout('transient read'),wrong,right])
 api=SimpleNamespace(set_enabled=write,set_client_enabled=write,get_user=read,find_client_any=read)
 monkeypatch.setattr(provider,'PasarGuardService' if kind=='pasarguard' else 'XuiService',lambda:api)
 await provider.set_enabled(SimpleNamespace(server_type=kind,id=1),'source',False)
 assert write.await_count==1 and read.await_count==3

@pytest.mark.parametrize('state',[{},None,{'status':'active'},{'status':'expired'},{'status':'limited'},{'status':'on_hold'}])
async def test_expired_or_missing_is_not_proof_of_disable(state,monkeypatch):
 write=AsyncMock(side_effect=pg.PasarGuardConnectionError(httpx.ReadTimeout('lost')))
 read=AsyncMock(return_value=state)
 monkeypatch.setattr(provider,'PasarGuardService',lambda:SimpleNamespace(set_enabled=write,get_user=read))
 with pytest.raises(provider.ConversionStateUnconfirmed):await provider.set_enabled(SimpleNamespace(server_type='pasarguard'),'source',False)
 assert write.await_count==1 and read.await_count==4

async def test_independent_disabled_switch_is_accepted(monkeypatch):
 api=SimpleNamespace(set_enabled=AsyncMock(),get_user=AsyncMock(return_value={'status':'active','is_disabled':True}))
 monkeypatch.setattr(provider,'PasarGuardService',lambda:api)
 await provider.set_enabled(SimpleNamespace(server_type='pasarguard'),'source',False)
 assert api.set_enabled.await_count==1

async def test_explicit_permission_error_is_not_hidden_by_readback(monkeypatch):
 api=SimpleNamespace(set_enabled=AsyncMock(side_effect=RuntimeError('denied (403)')),get_user=AsyncMock(return_value={'status':'disabled'}))
 monkeypatch.setattr(provider,'PasarGuardService',lambda:api)
 with pytest.raises(RuntimeError,match='403'):await provider.set_enabled(SimpleNamespace(server_type='pasarguard'),'source',False)
 api.get_user.assert_not_awaited()

@pytest.mark.parametrize('kind',['pasarguard','xui'])
async def test_exact_quota_update_timeout_is_verified_once(kind,monkeypatch):
 expiry=datetime.utcnow()+timedelta(days=5);quota=3*1024**3+123
 if kind=='pasarguard':
  write=AsyncMock(side_effect=pg.PasarGuardConnectionError(httpx.ReadTimeout('lost')))
  read=AsyncMock(side_effect=[{'data_limit':quota-1,'expire':expiry.isoformat()}, {'data_limit':quota,'expire':expiry.isoformat()}])
  monkeypatch.setattr(provider,'PasarGuardService',lambda:SimpleNamespace(update_user=write,get_user=read))
 else:
  write=AsyncMock(side_effect=httpx.ReadTimeout('lost'))
  record={'client':{'totalGB':quota,'expiryTime':int(expiry.replace(tzinfo=provider.timezone.utc).timestamp()*1000)}}
  read=AsyncMock(side_effect=[record,{'client':{'totalGB':quota+1,'expiryTime':record['client']['expiryTime']}},record])
  api=SimpleNamespace(login=AsyncMock(return_value=True),find_client=read,update_client=write,close=AsyncMock())
  monkeypatch.setattr(provider,'XUIClient',lambda *args:api);monkeypatch.setattr(provider,'decrypt_text',lambda x:x)
 await provider.set_exact_quota_and_expiry(SimpleNamespace(server_type=kind,panel_url='https://example',username='admin',password_encrypted='test'),'dest',quota,expiry)
 assert write.await_count==1

@pytest.mark.parametrize('kind',['pasarguard','xui'])
async def test_wrong_quota_remains_unconfirmed(kind,monkeypatch):
 expiry=datetime.utcnow()+timedelta(days=1);quota=1024**3
 if kind=='pasarguard':
  write=AsyncMock();read=AsyncMock(return_value={'data_limit':0,'expire':expiry.isoformat()})
  monkeypatch.setattr(provider,'PasarGuardService',lambda:SimpleNamespace(update_user=write,get_user=read))
 else:
  write=AsyncMock();read=AsyncMock(return_value={'client':{'totalGB':0,'expiryTime':int(expiry.replace(tzinfo=provider.timezone.utc).timestamp()*1000)}})
  monkeypatch.setattr(provider,'XUIClient',lambda *a:SimpleNamespace(login=AsyncMock(return_value=True),update_client=write,find_client=read,close=AsyncMock()))
  monkeypatch.setattr(provider,'decrypt_text',lambda x:x)
 with pytest.raises(RuntimeError,match='quota'):await provider.set_exact_quota_and_expiry(SimpleNamespace(server_type=kind,panel_url='',username='',password_encrypted=''),'dest',quota,expiry)
 assert write.await_count==1

@pytest.mark.parametrize('source_kind,target_kind',[('pasarguard','xui'),('xui','pasarguard'),('pasarguard','pasarguard'),('xui','xui')])
@pytest.mark.parametrize('surface',['miniapp','bot'])
def test_native_conversion_after_lost_disable_reply(conversion,source_kind,target_kind,surface,monkeypatch):
 c,sessions,flow,presenter,bot=conversion
 async def seed():
  async with sessions() as s:
   src=await s.get(Server,1);src.server_type=source_kind
   s.add(Server(id=3,name='Destination',server_type=target_kind,panel_url='https://destination.example',username='admin',password_encrypted='private',meta={'scope':'public'}))
   plan=await s.get(Plan,4);plan.server_id=3
   row=await s.get(Setting,'convert_category_rules');row.value=json.dumps({'1':{'price_per_gb_irt':6000,'server_ids':[1]},'3':{'price_per_gb_irt':12000,'server_ids':[3]}})
   await s.commit()
 asyncio.run(seed())
 write=AsyncMock(side_effect=pg.PasarGuardConnectionError(httpx.ReadTimeout('lost')) if source_kind=='pasarguard' else httpx.ReadTimeout('lost'))
 right={'status':'disabled'} if source_kind=='pasarguard' else {'client':{'enable':False}}
 read=AsyncMock(side_effect=[httpx.ReadTimeout('delayed'),right])
 fake=SimpleNamespace(set_enabled=write,set_client_enabled=write,get_user=read,find_client_any=read)
 monkeypatch.setattr(provider,'PasarGuardService' if source_kind=='pasarguard' else 'XuiService',lambda:fake)
 monkeypatch.setattr(flow,'set_enabled',provider.set_enabled)
 h={'X-Telegram-Init-Data':signed()};base='/api/miniapp/services/1/conversion';key=str(uuid.uuid4())
 preview=c.post(base+'/preview',headers=h,json={'key':key,'target_plan_id':4})
 assert preview.status_code==200
 if surface=='miniapp':
  op=c.post(base+'/confirm',headers=h,json={'key':key}).json()
  from app.api import miniapp_actions as actions
  asyncio.run(actions.process_operations())
  result=c.get('/api/miniapp/operations/'+str(op['id']),headers=h).json()
  assert result['status']=='done',result
  assert result['result']['service']['provider']==target_kind
  asyncio.run(actions.process_operations())
  presenter.assert_not_awaited()
 else:
  from app.services.miniapp_runtime import NativeState,native_event
  from app.database.models import User
  async def run_bot():
   async with sessions() as s:user=await s.get(User,1)
   _,callback,_=native_event(bot,user,'','svcconvert:confirm:1:4')
   state=NativeState({'convert_quote':preview.json()['quote']})
   await flow.convert_confirm(callback,state)
   # Repeated confirmation with the old quote must not provision again.
   await state.update_data(convert_quote=preview.json()['quote'])
   await flow.convert_confirm(callback,state)
  asyncio.run(run_bot());presenter.assert_awaited_once()
 assert write.await_count==1 and flow.create_converted.await_count==1
 async def verify():
  async with sessions() as s:
   item=await s.scalar(select(ServiceConversion));assert item.status=='completed' and item.target_total_bytes==9*1024**3
   old=await s.get(ClientService,1)
   assert old is None or not old.is_active
 asyncio.run(verify())

async def test_status_mutation_has_own_timeout_without_slowing_reads(monkeypatch):
 class Client:
  async def __aenter__(self):return self
  async def __aexit__(self,*args):pass
 monkeypatch.setattr(pg.httpx,'AsyncClient',lambda **kw:Client())
 monkeypatch.setattr(pg.settings,'PASARGUARD_READ_TIMEOUT_SECONDS',20)
 monkeypatch.setattr(pg.settings,'PASARGUARD_STATUS_TIMEOUT_SECONDS',55)
 api=pg.PasarGuardService()
 monkeypatch.setattr(api,'_auth_headers',AsyncMock(return_value=({},'https://panel.example')))
 request=AsyncMock(return_value=httpx.Response(200,json={}))
 monkeypatch.setattr(api,'_network_request',request)
 for method,path,expected in [('PUT','/api/user/by-username/demo/disabled',55),('GET','/api/user/by-username/demo',20),('PUT','/api/user/by-username/demo',20)]:
  await api._request(None,method,path)
  assert request.await_args.kwargs['timeout'].read==expected
 api=pg.PasarGuardService(timeout=7)
 monkeypatch.setattr(api,'_auth_headers',AsyncMock(return_value=({},'https://panel.example')))
 monkeypatch.setattr(api,'_network_request',request)
 await api._request(None,'PUT','/api/user/by-username/demo/disabled')
 assert request.await_args.kwargs['timeout'].read==7


def test_unconfirmed_disable_never_builds_destination_or_releases_claim(conversion,monkeypatch):
 c,sessions,flow,presenter,bot=conversion
 async def seed():
  async with sessions() as s:
   src=await s.get(Server,1);src.server_type='pasarguard';await s.commit()
 asyncio.run(seed())
 write=AsyncMock(side_effect=pg.PasarGuardConnectionError(httpx.ReadTimeout('lost')))
 read=AsyncMock(return_value={'status':'limited'})
 monkeypatch.setattr(provider,'PasarGuardService',lambda:SimpleNamespace(set_enabled=write,get_user=read))
 monkeypatch.setattr(flow,'set_enabled',provider.set_enabled)
 from app.api import miniapp_actions as actions
 h={'X-Telegram-Init-Data':signed()};base='/api/miniapp/services/1/conversion';key=str(uuid.uuid4())
 assert c.post(base+'/preview',headers=h,json={'key':key,'target_plan_id':4}).status_code==200
 op=c.post(base+'/confirm',headers=h,json={'key':key}).json()
 asyncio.run(actions.process_operations())
 result=c.get('/api/miniapp/operations/'+str(op['id']),headers=h).json()
 assert result['status']=='failed' and result['result']['retryable'] is False
 assert 'مقصد ساخته نشده' in result['result']['message']
 flow.create_converted.assert_not_awaited();presenter.assert_not_awaited()
 asyncio.run(actions.process_operations());assert write.await_count==1
 async def verify():
  async with sessions() as s:
   row=await s.scalar(select(ServiceConversion));assert row.status=='needs_review' and 'stage=disable_source' in row.error
   assert await s.scalar(select(func.count()).select_from(ClientService))==2
 asyncio.run(verify())
