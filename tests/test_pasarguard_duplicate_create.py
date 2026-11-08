"""Retry only an explicit, rejected PasarGuard create; never adopt an old user."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import httpx
import pytest
from sqlalchemy import select,func
from app.services import pasarguard_service as pg
from app.bot.handlers.public import buy
from app.database.models import Order,Server,ClientService,User
from test_miniapp import client


@pytest.mark.parametrize('method,path,status,detail,conflict',[
 ('POST','/api/user',409,'User already exists',True),
 ('POST','/api/user/from_template',409,'Username already exists',True),
 ('POST','/api/user',409,'USER ALREADY EXISTS.',True),
 ('POST','/api/user',409,'User limit exceeded',False),
 ('POST','/api/user',403,'User already exists',False),
 ('POST','/api/user',500,'User already exists',False),
 ('PUT','/api/user/9',409,'User already exists',False),
 ('GET','/api/user/by-username/demo',409,'User already exists',False),
 ('POST','/api/users/bulk/enable',409,'User already exists',False),
])
async def test_only_create_conflict_is_typed(monkeypatch,method,path,status,detail,conflict):
 factory=httpx.AsyncClient
 transport=httpx.MockTransport(lambda request:httpx.Response(status,json={'detail':detail}))
 monkeypatch.setattr(pg.httpx,'AsyncClient',lambda **kwargs:factory(transport=transport,**kwargs))
 api=pg.PasarGuardService()
 monkeypatch.setattr(api,'_auth_headers',AsyncMock(return_value=({},'https://panel.example')))
 with pytest.raises(RuntimeError) as error:await api._request(SimpleNamespace(),method,path)
 assert isinstance(error.value,pg.PasarGuardUsernameConflict) is conflict


def inputs():
 return (SimpleNamespace(add=Mock(),flush=AsyncMock()),SimpleNamespace(id=1),
   SimpleNamespace(id=2,server_type='pasarguard'),
   SimpleNamespace(id=3,category_id=4,inbound_ids=[7],volume_gb=10,duration_days=30))


async def test_create_race_saves_and_returns_only_fresh_credentials(monkeypatch):
 session,user,server,plan=inputs()
 api=SimpleNamespace(create_user_on_plan=AsyncMock(side_effect=[
  pg.PasarGuardUsernameConflict('User already exists'),
  {'sub_link':'https://sub.example/opaque-new','uuid':'101','inbound_ids':[8,9]}]))
 resolve=AsyncMock(side_effect=[('requested_000001',True),('requested_000002',True)])
 monkeypatch.setattr(buy,'PasarGuardService',lambda:api)
 monkeypatch.setattr(buy,'resolve_service_username',resolve)
 service,link=await buy.build_service(session,user,server,plan,'requested')
 assert [call.args[-1] for call in api.create_user_on_plan.await_args_list]==['requested_000001','requested_000002']
 assert resolve.await_args_list[1].args[-1]=='requested'  # Keep original base, not nested suffixes.
 assert resolve.await_args_list[1].kwargs=={'force_duplicate':True}
 assert service.client_username==service.xui_email=='requested_000002'
 assert link==service.sub_link=='https://sub.example/opaque-new'
 assert service.xui_uuid=='101' and service.inbound_ids==[8,9]
 session.add.assert_called_once_with(service)
 session.flush.assert_awaited_once()


@pytest.mark.parametrize('error',[
 RuntimeError('ReadTimeout'), RuntimeError('Permission denied'),
 RuntimeError('PasarGuard API PUT /api/user/9 failed (409): User already exists'),
 RuntimeError('Subscription link missing after successful create'),
 pg.PasarGuardConnectionError(httpx.ReadTimeout('')),
])
async def test_ambiguous_or_post_create_errors_never_create_another_user(monkeypatch,error):
 session,user,server,plan=inputs()
 api=SimpleNamespace(create_user_on_plan=AsyncMock(side_effect=error))
 resolve=AsyncMock(return_value=('requested',False))
 monkeypatch.setattr(buy,'PasarGuardService',lambda:api)
 monkeypatch.setattr(buy,'resolve_service_username',resolve)
 with pytest.raises(type(error)):await buy.build_service(session,user,server,plan,'requested')
 assert api.create_user_on_plan.await_count==1 and resolve.await_count==1
 session.add.assert_not_called()


async def test_duplicate_retries_are_bounded(monkeypatch):
 session,user,server,plan=inputs()
 api=SimpleNamespace(create_user_on_plan=AsyncMock(side_effect=pg.PasarGuardUsernameConflict('User already exists')))
 resolve=AsyncMock(side_effect=[('requested',False)]+[(f'requested_{i:06d}',True) for i in range(1,8)])
 monkeypatch.setattr(buy,'PasarGuardService',lambda:api)
 monkeypatch.setattr(buy,'resolve_service_username',resolve)
 with pytest.raises(pg.PasarGuardUsernameConflict):await buy.build_service(session,user,server,plan,'requested')
 assert api.create_user_on_plan.await_count==8 and resolve.await_count==8
 session.add.assert_not_called()


def test_approved_receipt_with_collision_delivers_once_and_does_not_adopt_other_service(client,monkeypatch):
 _,sessions=client
 monkeypatch.setattr(buy,'SessionLocal',sessions)
 for name in ['send_buyer_notice','notify_paid_order','send_service_card','send_home','send_admin_notice','edit_admin_receipt_keyboard','report_bot_error']:
  monkeypatch.setattr(buy,name,AsyncMock())
 monkeypatch.setattr(buy,'apply_purchase_commission',AsyncMock(return_value=0))
 async def seed():
  async with sessions() as s:
   (await s.get(Server,1)).server_type='pasarguard'
   s.add(ClientService(id=99,user_id=2,server_id=1,plan_id=1,client_username='requested',xui_email='requested',sub_link='https://sub.example/private-old',xui_uuid='old'))
   s.add(Order(id=654,user_id=1,plan_id=1,amount_irt=139000,payment_method='card:requested',status='processing'))
   await s.commit()
 asyncio.run(seed())
 monkeypatch.setattr(buy,'resolve_service_username',AsyncMock(side_effect=[('requested',False),('requested_000001',True)]))
 api=SimpleNamespace(create_user_on_plan=AsyncMock(side_effect=[pg.PasarGuardUsernameConflict('User already exists'),{'uuid':'new','sub_link':'https://sub.example/new'}]))
 monkeypatch.setattr(buy,'PasarGuardService',lambda:api)
 bot=SimpleNamespace()
 asyncio.run(buy.process_approved_order_background(654,bot))
 asyncio.run(buy.process_approved_order_background(654,bot))
 async def verify():
  async with sessions() as s:
   order=await s.get(Order,654);assert order.status=='paid'
   service=await s.get(ClientService,order.service_id)
   assert service.user_id==1 and service.client_username=='requested_000001' and service.sub_link=='https://sub.example/new'
   other=await s.get(ClientService,99)
   assert other.user_id==2 and other.sub_link=='https://sub.example/private-old' and other.xui_uuid=='old'
   assert await s.scalar(select(func.count(ClientService.id)).where(ClientService.client_username=='requested_000001'))==1
 asyncio.run(verify())
 assert api.create_user_on_plan.await_count==2
 buy.send_service_card.assert_awaited_once()
 assert buy.send_service_card.await_args.args[2]=='requested_000001'
 assert buy.send_service_card.await_args.args[6]=='https://sub.example/new'
 buy.report_bot_error.assert_not_awaited()
 buy.apply_purchase_commission.assert_awaited_once()


@pytest.mark.parametrize('template',[False,True])
async def test_real_direct_and_template_create_paths_propagate_collision_safely(monkeypatch,template):
 session,user,server,plan=inputs()
 api=pg.PasarGuardService()
 monkeypatch.setattr(api,'_effective_template_id',lambda server,plan:12 if template else None)
 monkeypatch.setattr(api,'_effective_group_ids',lambda server,plan:[7])
 request=AsyncMock(side_effect=[pg.PasarGuardUsernameConflict('User already exists'),
   {'id':101,'username':'requested_000001','hwid_limit':0,'group_ids':[7]}])
 monkeypatch.setattr(api,'_request',request)
 monkeypatch.setattr(api,'current_subscription_link',AsyncMock(return_value='https://sub.example/new'))
 monkeypatch.setattr(buy,'PasarGuardService',lambda:api)
 monkeypatch.setattr(buy,'resolve_service_username',AsyncMock(side_effect=[('requested',False),('requested_000001',True)]))
 service,link=await buy.build_service(session,user,server,plan,'requested')
 expected='/api/user/from_template' if template else '/api/user'
 assert [c.args[1:3] for c in request.await_args_list]==[('POST',expected),('POST',expected)]
 assert request.await_args_list[1].kwargs['json']['username']=='requested_000001'
 assert service.client_username=='requested_000001' and link=='https://sub.example/new'


async def test_template_hwid_failure_after_creation_does_not_repeat_create(monkeypatch):
 session,user,server,plan=inputs();plan.hwid_limit=2
 api=pg.PasarGuardService()
 monkeypatch.setattr(api,'_effective_template_id',lambda server,plan:12)
 request=AsyncMock(return_value={'id':101,'username':'requested','hwid_limit':0})
 monkeypatch.setattr(api,'_request',request)
 monkeypatch.setattr(api,'update_user',AsyncMock(side_effect=RuntimeError('PasarGuard API PUT /api/user/101 failed (409): User already exists')))
 monkeypatch.setattr(api,'delete_user',AsyncMock())
 monkeypatch.setattr(buy,'PasarGuardService',lambda:api)
 monkeypatch.setattr(buy,'resolve_service_username',AsyncMock(return_value=('requested',False)))
 with pytest.raises(RuntimeError):await buy.build_service(session,user,server,plan,'requested')
 assert request.await_count==1
 api.delete_user.assert_awaited_once_with(server,'requested')
 session.add.assert_not_called()
