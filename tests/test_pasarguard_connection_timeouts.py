import asyncio,importlib.util,subprocess,sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import httpx,pytest
from sqlalchemy import select
from app.services import pasarguard_service as pg,pasarguard_panel_meter as metering
from app.database.models import PasarGuardPanelMeter,User,WalletTransaction
from test_miniapp_native_actions import native,client
from test_panel_wallet_miniapp_alerts import seed

@pytest.fixture
def server(monkeypatch):
 monkeypatch.setattr(pg,'decrypt_text',lambda _: 'pg_key_TEST_SECRET')
 return SimpleNamespace(id=2,panel_url='https://panel.example/hub/',username='admin',password_encrypted='encrypted',meta={'auth_mode':'api_key'})

@pytest.mark.asyncio
async def test_connect_timeout_is_not_a_route_error_or_probe_every_path(server):
 calls=[]
 def handler(request):calls.append(request);raise httpx.ConnectTimeout('secret URL must not be logged',request=request)
 api=pg.PasarGuardService()
 async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
  with pytest.raises(pg.PasarGuardConnectionError) as error:await api._auth_headers(c,server)
 assert len(calls)==2 and calls[0].url==calls[1].url
 assert error.value.error_code=='ConnectTimeout' and isinstance(error.value.__cause__,httpx.ConnectTimeout)
 assert 'path could not be detected' not in str(error.value)
 assert 'TEST_SECRET' not in str(error.value) and 'secret URL' not in str(error.value)

@pytest.mark.asyncio
async def test_transient_connect_timeout_recovers_and_404_still_discovers_root(server):
 calls=[]
 def handler(request):
  calls.append(request.url.path)
  if len(calls)==1:raise httpx.ConnectTimeout('',request=request)
  return httpx.Response(404 if request.url.path.startswith('/hub/') else 200,json={'username':'admin'})
 api=pg.PasarGuardService()
 async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
  headers,base=await api._auth_headers(c,server)
 assert calls==['/hub/api/admin','/hub/api/admin','/api/admin']
 assert base=='https://panel.example' and headers['X-Api-Key']=='pg_key_TEST_SECRET'

@pytest.mark.asyncio
@pytest.mark.parametrize('failure',[httpx.ReadTimeout,httpx.WriteTimeout])
async def test_ambiguous_mutation_is_never_replayed(failure):
 calls=[]
 def handler(request):calls.append(request);raise failure('',request=request)
 async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
  with pytest.raises(pg.PasarGuardConnectionError):await pg.PasarGuardService()._network_request(c,'POST','https://panel.example/api/user',json={'username':'customer'})
 assert len(calls)==1

@pytest.mark.asyncio
async def test_auth_denied_is_not_retried_or_changed_to_network_error(server):
 calls=[]
 def handler(request):calls.append(request);return httpx.Response(403,json={'detail':'Permission denied'})
 async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
  with pytest.raises(RuntimeError,match='failed \\(403\\)'):await pg.PasarGuardService()._auth_headers(c,server)
 assert len(calls)==1


def test_outage_keeps_billing_checkpoints_and_suspension_intact(native,monkeypatch):
 _,sessions,bot,*_=native;seed(sessions)
 monkeypatch.setattr(metering,'SessionLocal',sessions)
 from app.services import panel_wallet_recharge
 monkeypatch.setattr(panel_wallet_recharge,'process_panel_recharges',AsyncMock())
 async def state():
  async with sessions() as s:
   m=await s.scalar(select(PasarGuardPanelMeter).where(PasarGuardPanelMeter.order_id==1));u=await s.get(User,1)
   return (u.wallet_balance,m.traffic_bytes,m.billable_seconds,m.total_charged_irt,m.last_meter_at,deepcopy(m.usage_offsets),m.suspended)
 before=asyncio.run(state())
 failure=pg.PasarGuardConnectionError(httpx.ConnectTimeout(''))
 monkeypatch.setattr(metering.PanelMeterAPI,'list_own_users',AsyncMock(side_effect=failure))
 import app.bot.error_reporting as reporting
 report=AsyncMock();monkeypatch.setattr(reporting,'report_bot_error',report)
 asyncio.run(metering.sync_panel_payg(bot));asyncio.run(metering.sync_panel_payg(bot))
 assert asyncio.run(state())==before
 assert report.await_count==1
 async def reason():
  async with sessions() as s:return (await s.scalar(select(PasarGuardPanelMeter).where(PasarGuardPanelMeter.order_id==1))).last_error
 assert 'ConnectTimeout' in asyncio.run(reason())
 # First successful poll uses the old usage checkpoint, not an empty outage snapshot.
 monkeypatch.setattr(metering.PanelMeterAPI,'list_own_users',AsyncMock(return_value=[{'id':9,'used_traffic':2*1024**3,'admin':{'id':77},'status':'active'}]))
 result=asyncio.run(metering.PanelMeterAPI().poll(1))
 assert result['remaining']<before[0]
 after=asyncio.run(state());assert after[1]==before[1]+2*1024**3
 again=asyncio.run(metering.PanelMeterAPI().poll(1));assert again['remaining']==result['remaining']
 assert asyncio.run(reason()) is None


def load_diagnostic():
 path=Path(__file__).resolve().parents[1]/'scripts/diagnose_pasarguard_connection.py'
 spec=importlib.util.spec_from_file_location('pg_diagnostic',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module,path


def test_diagnostic_help_does_not_require_app_credentials(monkeypatch):
 module,path=load_diagnostic()
 assert module.origin('https://username:TOP_SECRET@panel.example:8443/private?token=TOP_SECRET')=='https://panel.example:8443'
 result=subprocess.run([sys.executable,str(path),'--help'],capture_output=True,text=True)
 assert result.returncode==0 and '--order-id' in result.stdout


@pytest.mark.asyncio
async def test_diagnostic_never_sends_embedded_credentials_or_tokens(monkeypatch):
 module,_=load_diagnostic();seen=[];original=httpx.AsyncClient
 def handler(request):
  seen.append(request)
  assert 'authorization' not in request.headers and 'x-api-key' not in request.headers
  assert request.url.username=='' and request.url.password=='' and request.url.query==b''
  return httpx.Response(401,headers={'content-type':'application/json'})
 monkeypatch.setattr(module.httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))
 monkeypatch.setattr(module.socket,'getaddrinfo',lambda *args,**kwargs:[(2,1,6,'',('192.0.2.1',443))])
 data=await module.diagnose(SimpleNamespace(panel_url='https://user:TOP_SECRET@panel.example/hub?token=TOP_SECRET',meta={}))
 assert seen and all(c['connected'] for c in data['checks'])
 assert 'TOP_SECRET' not in str(data)


@pytest.mark.asyncio
async def test_slow_wrong_ui_path_can_still_fall_back_to_reachable_api_root(server):
 seen=[]
 def handler(request):
  seen.append(request.url.path)
  if request.url.path.startswith('/hub/'):raise httpx.ReadTimeout('',request=request)
  return httpx.Response(200,json={'username':'admin'})
 async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
  _,base=await pg.PasarGuardService()._auth_headers(c,server)
 assert seen==['/hub/api/admin','/api/admin'] and base=='https://panel.example'
