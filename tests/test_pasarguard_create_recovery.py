import asyncio,json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import httpx,pytest
from sqlalchemy import select,func
from app.services import pasarguard_service as pg
from app.bot.handlers.public import buy
from app.database.models import Server,User,Plan,ClientService,Order
from test_miniapp import client

@pytest.fixture
def inputs(monkeypatch):
 monkeypatch.setattr(pg,'decrypt_text',lambda _: 'pg_key_private')
 server=SimpleNamespace(id=1,panel_url='https://pg.example',username='owner',password_encrypted='secret',meta={'auth_mode':'api_key'})
 plan=SimpleNamespace(volume_gb=10,duration_days=30,inbound_ids=[7],hwid_limit=1,is_test_account=False)
 return server,plan

@pytest.fixture
def transport(monkeypatch):
 original=httpx.AsyncClient
 def install(handler):monkeypatch.setattr(pg.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
 return install

@pytest.mark.parametrize('template',[False,True])
@pytest.mark.parametrize('error',[httpx.ReadTimeout,httpx.WriteTimeout,httpx.ReadError,httpx.RemoteProtocolError])
async def test_create_committed_then_response_lost_is_recovered_without_second_post(inputs,transport,template,error):
 server,plan=inputs;remote={};calls=[];timeouts=[]
 if template:server.meta.update(pasarguard_require_template=True,pasarguard_allowed_template_ids=[9],pasarguard_templates=[{'id':9,'username_prefix':'pre_','username_suffix':'_vip','group_ids':[7]}])
 def handler(req):
  calls.append((req.method,req.url.path))
  if req.url.path=='/api/admin':return httpx.Response(200,json={'username':'owner'})
  if req.method=='POST':
   payload=json.loads(req.content);timeouts.append(req.extensions['timeout']['read'])
   name='pre_customer_vip' if template else 'customer'
   remote.update(id=88,username=name,note=payload['note'],data_limit=10*1024**3,group_ids=[7],hwid_limit=1,status='active',subscription_url='https://sub.example/opaque')
   raise error('lost reply',request=req)
  if req.url.path.endswith('/'+remote['username']):return httpx.Response(200,json=remote)
  return httpx.Response(404,json={'detail':'not found'})
 transport(handler)
 result=await pg.PasarGuardService().create_user_on_plan(server,plan,'customer')
 assert result['sub_link']=='https://sub.example/opaque' and result['username']==remote['username']
 assert sum(m=='POST' for m,_ in calls)==1
 assert sum(path=='/api/admin' for _,path in calls)==1
 assert timeouts==[45.0] and remote['note'].startswith('dbot:create:')

@pytest.mark.parametrize('exists',[False,True])
async def test_uncertain_result_never_replays_or_adopts_another_user(inputs,transport,exists):
 server,plan=inputs;calls=[]
 def handler(req):
  calls.append((req.method,req.url.path))
  if req.url.path=='/api/admin':return httpx.Response(200,json={})
  if req.method=='POST':raise httpx.ReadTimeout('',request=req)
  return httpx.Response(200,json={'id':99,'username':'customer','note':'someone else','subscription_url':'https://private'}) if exists else httpx.Response(404,json={})
 transport(handler)
 with pytest.raises(pg.PasarGuardCreateUnconfirmed) as err:await pg.PasarGuardService().create_user_on_plan(server,plan,'customer')
 assert sum(m=='POST' for m,_ in calls)==1
 assert all(m not in ('PUT','DELETE') for m,_ in calls)
 assert 'تکراری' in err.value.user_message

async def test_transient_read_retries_but_mutations_do_not(inputs,transport):
 server,_=inputs;calls=[]
 def handler(req):
  calls.append(req.url.path)
  if req.url.path=='/api/admin':return httpx.Response(200,json={})
  if calls.count(req.url.path)==1:raise httpx.ReadTimeout('',request=req)
  return httpx.Response(200,json={'id':1,'username':'customer'})
 transport(handler)
 result=await pg.PasarGuardService().get_user(server,'customer')
 assert result['id']==1 and calls.count('/api/user/by-username/customer')==2

async def test_cached_auth_refreshes_once_on_401_and_changes_with_credentials(inputs,transport,monkeypatch):
 server,_=inputs;calls=[];unauthorized=True
 def handler(req):
  nonlocal unauthorized
  calls.append((req.url.path,req.headers.get('x-api-key')))
  if req.url.path=='/api/admin':return httpx.Response(200,json={})
  if unauthorized:unauthorized=False;return httpx.Response(401,json={})
  return httpx.Response(200,json={'id':1,'username':'customer'})
 transport(handler);api=pg.PasarGuardService()
 await api.get_user(server,'customer');await api.get_user(server,'customer')
 assert sum(path=='/api/admin' for path,_ in calls)==2
 monkeypatch.setattr(pg,'decrypt_text',lambda _: 'pg_key_changed')
 await api.get_user(server,'customer')
 assert sum(path=='/api/admin' for path,_ in calls)==3
 assert calls[-1][1]=='pg_key_changed'


def test_admin_free_purchase_persists_and_delivers_once_after_recovered_post(client,inputs,transport,monkeypatch):
 _,sessions=client;_,plan=inputs;remote={};posts=[]
 async def setup():
  async with sessions() as s:
   server=await s.get(Server,1);server.server_type='pasarguard';server.meta={'auth_mode':'api_key'};server.panel_url='https://pg.example'
   (await s.get(Plan,1)).inbound_ids=[7]
   await s.commit()
   return await s.get(User,1),server,await s.get(Plan,1)
 user,server,dbplan=asyncio.run(setup())
 def handler(req):
  if req.url.path=='/api/admin':return httpx.Response(200,json={})
  if req.method=='POST':
   posts.append(req);payload=json.loads(req.content);remote.update(id=123,username=payload['username'],note=payload['note'],data_limit=payload['data_limit'],group_ids=[7],hwid_limit=0,status='active',subscription_url='https://sub.example/fresh')
   raise httpx.ReadTimeout('',request=req)
  return httpx.Response(200,json=remote)
 transport(handler)
 monkeypatch.setattr(buy,'SessionLocal',sessions)
 monkeypatch.setattr(buy,'is_admin_user',lambda _:True)
 monkeypatch.setattr(buy,'resolve_service_username',AsyncMock(return_value=('customer',False)))
 monkeypatch.setattr(buy,'ui_message',AsyncMock());delivery=AsyncMock();monkeypatch.setattr(buy,'send_service_info',delivery)
 failed=AsyncMock();monkeypatch.setattr(buy,'handle_user_facing_error',failed)
 state=SimpleNamespace(clear=AsyncMock());message=SimpleNamespace(from_user=SimpleNamespace(id=11),bot=object())
 asyncio.run(buy.create_admin_free_service(message,state,user,server,dbplan,'customer'))
 failed.assert_not_awaited();delivery.assert_awaited_once();assert len(posts)==1
 async def check():
  async with sessions() as s:
   services=(await s.execute(select(ClientService).where(ClientService.client_username=='customer'))).scalars().all()
   assert len(services)==1 and services[0].xui_uuid=='123'
   assert await s.scalar(select(func.count(Order.id)).where(Order.service_id==services[0].id,Order.status=='paid',Order.payment_method=='admin_free'))==1
 asyncio.run(check())

@pytest.mark.parametrize('bad_field,bad_value',[('data_limit',0),('group_ids',[99]),('hwid_limit',0)])
async def test_recovery_never_delivers_wrong_quota_or_groups(inputs,transport,bad_field,bad_value):
 server,plan=inputs;row={};posts=[]
 def handler(req):
  if req.url.path=='/api/admin':return httpx.Response(200,json={})
  if req.method=='POST':
   posts.append(req);payload=json.loads(req.content)
   row.update(id=88,username='customer',note=payload['note'],data_limit=payload['data_limit'],group_ids=[7],hwid_limit=1,subscription_url='https://sub.example/link')
   row[bad_field]=bad_value
   raise httpx.ReadTimeout('',request=req)
  return httpx.Response(200,json=row)
 transport(handler)
 with pytest.raises(pg.PasarGuardCreateUnconfirmed):await pg.PasarGuardService().create_user_on_plan(server,plan,'customer')
 assert len(posts)==1
