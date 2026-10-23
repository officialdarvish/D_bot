import asyncio,json,uuid
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.services.pasarguard_service import PasarGuardService
from app.services.xui_service import XuiService
from app.bot.handlers.public.reseller import reseller_server_group,reseller_server_policy
from app.api import admin_web as web
from app.database.models import ResellerAccount,Server
from test_miniapp import client

@pytest.mark.parametrize('template',[False,True])
@pytest.mark.parametrize('unlimited',[False,True])
@pytest.mark.parametrize('reset_denied',[False,True])
async def test_pg_renew_explicitly_enables_disabled_account(template,unlimited,reset_denied,monkeypatch):
    api=PasarGuardService();calls=[]
    state={'id':8,'username':'user_demo','status':'disabled','is_disabled':True,'used_traffic':987,'data_limit':1234,'hwid_limit':1,'group_ids':[5],'subscription_url':'https://sub.example/token'}
    server=SimpleNamespace(meta={'inbound_ids':[5]},panel_url='https://pg.example')
    plan=SimpleNamespace(volume_gb=0 if unlimited else 20,is_unlimited=unlimited,duration_days=30,inbound_ids=[5],hwid_limit=1)
    monkeypatch.setattr(api,'_effective_template_id',lambda s,p:10 if template else None)
    async def request(s,method,path,**kwargs):
        calls.append((method,path,deepcopy(kwargs.get('json'))))
        if path.endswith('/reset'):
            if reset_denied:raise RuntimeError('reset denied (403)')
            state['used_traffic']=0
        elif path.endswith('/disabled'):
            assert kwargs['json']=={'disabled':False}
            state['is_disabled']=False;state['status']='active'
        elif '/from_template/' in path:
            state['data_limit']=0 if unlimited else 20*1024**3
            # Reproduces a template renewal retaining the independent disable flag.
            state['status']='disabled';state['used_traffic']=0
        elif method=='PUT':state.update(kwargs['json'])
        return deepcopy(state)
    monkeypatch.setattr(api,'_request',request)
    result=await api.renew_user_on_plan(server,plan,'user_demo')
    assert result['enabled'] and result['status']=='active' and not result['is_disabled']
    expected=0 if unlimited else 20*1024**3+(987 if reset_denied and not template else 0)
    assert result['data_limit']==expected
    assert result['subscription_url']=='https://sub.example/token'
    assert sum(path.endswith('/reset') for _,path,_ in calls)<=1
    assert any(path.endswith('/disabled') for _,path,_ in calls)
    assert calls[-1][0]=='GET'


async def test_pg_template_unlimited_repairs_stale_finite_quota(monkeypatch):
    api=PasarGuardService()
    state={'id':2,'status':'active','disabled':False,'data_limit':99,'hwid_limit':0,'group_ids':[5],'subscription_url':'https://sub.example/stable'}
    monkeypatch.setattr(api,'_effective_template_id',lambda *a:10)
    writes=[]
    async def request(server,method,path,**kwargs):
        if method=='PUT' and not '/from_template/' in path and not path.endswith('/disabled'):
            state.update(kwargs['json']);writes.append(kwargs['json'])
        return deepcopy(state)
    monkeypatch.setattr(api,'_request',request)
    plan=SimpleNamespace(volume_gb=0,is_unlimited=True,duration_days=30,inbound_ids=[5],hwid_limit=0)
    result=await api.renew_user_on_plan(SimpleNamespace(meta={}),plan,'demo')
    assert result['data_limit']==0 and any(w.get('data_limit')==0 for w in writes)


async def test_pg_activation_failure_does_not_delete_or_claim_success(monkeypatch):
    api=PasarGuardService();calls=[]
    async def request(server,method,path,**kwargs):
        calls.append((method,path))
        return {'id':3,'status':'disabled','is_disabled':True,'data_limit':0,'used_traffic':0,'group_ids':[5]}
    monkeypatch.setattr(api,'_request',request)
    monkeypatch.setattr(api,'_effective_template_id',lambda *a:None)
    plan=SimpleNamespace(volume_gb=0,duration_days=30,inbound_ids=[5],hwid_limit=0)
    with pytest.raises(RuntimeError,match='activation was not confirmed'):
        await api.renew_user_on_plan(SimpleNamespace(meta={'inbound_ids':[5]}),plan,'demo')
    assert not any(method=='DELETE' for method,path in calls)
    assert sum(path.endswith('/reset') for method,path in calls)==1


async def test_pg_enable_permission_failure_never_triggers_recreate(monkeypatch):
    api=PasarGuardService();calls=[]
    async def request(server,method,path,**kwargs):
        calls.append((method,path))
        if path.endswith('/disabled'):raise RuntimeError('enable denied (403)')
        return {'id':3,'status':'disabled','is_disabled':True,'data_limit':0}
    monkeypatch.setattr(api,'_request',request)
    monkeypatch.setattr(api,'_effective_template_id',lambda *a:None)
    plan=SimpleNamespace(volume_gb=0,duration_days=30,inbound_ids=[5],hwid_limit=0)
    with pytest.raises(RuntimeError):await api.renew_user_on_plan(SimpleNamespace(meta={'inbound_ids':[5]}),plan,'demo')
    assert not any(method=='DELETE' for method,path in calls)


def test_groups_are_per_server_and_explicit_empty_overrides_legacy():
    r=SimpleNamespace(server_id=2,group_name='Legacy',inbound_policies={'2':{'mode':'manual','inbound_ids':[4],'group_name':'VIP'},'4':{'mode':'automatic','inbound_ids':[],'group_name':'Regular'}})
    assert reseller_server_group(r,SimpleNamespace(id=2,server_type='xui'))=='VIP'
    assert reseller_server_group(r,SimpleNamespace(id=4,server_type='xui'))=='Regular'
    assert reseller_server_group(r,SimpleNamespace(id=3,server_type='pasarguard'))==''
    r.inbound_policies['2']['group_name']=''
    assert reseller_server_group(r,SimpleNamespace(id=2,server_type='xui'))==''
    assert reseller_server_policy(r,SimpleNamespace(id=2,server_type='xui'))==('manual',[4])


def test_web_groups_roundtrip_validation_and_old_edit_preservation(client,monkeypatch):
    _,sessions=client;monkeypatch.setattr(web,'SessionLocal',sessions)
    from app.services import reseller_service
    monkeypatch.setattr(web,'reconcile_reseller_accounting',AsyncMock())
    async def seed():
        async with sessions() as s:
            s.add_all([Server(id=4,name='Second',server_type='xui',panel_url='https://second.example',username='x',password_encrypted='x',meta={'scope':'reseller','inbound_ids':[4]}),Server(id=3,name='PG',server_type='pasarguard',panel_url='https://pg.example',username='x',password_encrypted='x',meta={'scope':'reseller','inbound_ids':[5]})]);await s.commit()
    asyncio.run(seed())
    async def groups(self,server):return [{'name':'VIP'}] if server.id==2 else [{'name':'Regular'}]
    monkeypatch.setattr(XuiService,'live_client_groups',groups)
    app=FastAPI();app.include_router(web.router);app.dependency_overrides[web._auth_user]=lambda:'owner'
    headers={'Accept':'application/json'}
    policies={'2':{'mode':'automatic','inbound_ids':[],'group_name':'VIP'},'4':{'mode':'manual','inbound_ids':[4],'group_name':'Regular'}}
    with TestClient(app) as c:
        data={'telegram_id':11,'total_gb':100,'days':30,'allowed_server_ids':'2,4','inbound_policies_json':json.dumps(policies)}
        response=c.post('/admin/resellers/add',data=data,headers=headers);assert response.status_code==200,response.text
        async def read():
            async with sessions() as s:return await s.scalar(select(ResellerAccount).where(ResellerAccount.user_id==1))
        r=asyncio.run(read());assert r.inbound_policies==policies and r.group_name=='VIP'
        action=f'/admin/resellers/{r.id}/edit'
        # A pre-existing editor sends inbound restrictions but omits group fields.
        older={sid:{k:v for k,v in p.items() if k!='group_name'} for sid,p in policies.items()}
        response=c.post(action,data={'allowed_server_ids':'2,4','inbound_policies_json':json.dumps(older)},headers=headers)
        assert response.status_code==200,response.text
        assert asyncio.run(read()).inbound_policies==policies
        wrong=deepcopy(policies);wrong['4']['group_name']='VIP'
        assert c.post(action,data={'allowed_server_ids':'2,4','inbound_policies_json':json.dumps(wrong)},headers=headers).status_code==400
        assert asyncio.run(read()).inbound_policies==policies
        cleared=deepcopy(policies);cleared['2']['group_name']=''
        assert c.post(action,data={'allowed_server_ids':'2,4','inbound_policies_json':json.dumps(cleared)},headers=headers).status_code==200
        assert asyncio.run(read()).inbound_policies==cleared
        # Removing a server drops its policy; its group must not transfer to the new primary.
        assert c.post(action,data={'allowed_server_ids':'4','inbound_policies_json':json.dumps({'4':policies['4']})},headers=headers).status_code==200
        r=asyncio.run(read());assert r.server_id==4 and r.group_name=='Regular' and '2' not in r.inbound_policies
        app.dependency_overrides.clear()
        assert c.post(action,data={},headers=headers).status_code in (401,403)


@pytest.mark.parametrize('deny_groups',[False,True])
async def test_manual_pg_group_selection_survives_template_or_fails_cleanly(monkeypatch,deny_groups):
    api=PasarGuardService();calls=[]
    state={'id':6,'username':'template_demo','status':'active','data_limit':20*1024**3,'group_ids':[1,2],'hwid_limit':0,'subscription_url':'https://sub.example/template'}
    async def request(server,method,path,**kwargs):
        calls.append((method,path,kwargs.get('json')))
        if method=='PUT' and kwargs['json'].get('group_ids'):
            if deny_groups:raise RuntimeError('groups update denied (403)')
            state.update(kwargs['json'])
        return deepcopy(state)
    monkeypatch.setattr(api,'_request',request);monkeypatch.setattr(api,'_effective_template_id',lambda *a:10)
    plan=SimpleNamespace(volume_gb=20,duration_days=30,inbound_ids=[5],hwid_limit=0,enforce_group_ids=True)
    if deny_groups:
        with pytest.raises(RuntimeError,match='groups update denied'):await api.create_user_on_plan(SimpleNamespace(meta={}),plan,'demo')
        assert any(method=='DELETE' and path.endswith('/template_demo') for method,path,body in calls)
    else:
        result=await api.create_user_on_plan(SimpleNamespace(meta={}),plan,'demo')
        assert result['inbound_ids']==[5] and state['group_ids']==[5]
        assert all('status' not in body for method,path,body in calls if method=='PUT')


@pytest.mark.parametrize('ignores_zero_forever',[False,True])
async def test_xui_unlimited_renew_requires_zero_quota_and_enabled(monkeypatch,ignores_zero_forever):
    from app.xui.client import XUIClient
    api=object.__new__(XUIClient)
    state={'id':'uuid1','email':'demo','totalGB':10*1024**3,'expiryTime':1,'enable':False};updates=[]
    async def find(email):return {'client':dict(state),'traffic':{'up':0,'down':0},'used_traffic':0,'inbound_ids':[5]}
    async def update(payload):
        updates.append(dict(payload));state['expiryTime']=payload['expiryTime']
        # Simulate a stale quota on the first write and a separately disabled user.
        if len(updates)>1 and not ignores_zero_forever:state['totalGB']=payload['totalGB']
        return {'success':True}
    async def enable(*args):state['enable']=True;return {'success':True}
    api.find_client=AsyncMock(side_effect=find);api.reset_client_traffic=AsyncMock(return_value={'success':True})
    api._update_client=AsyncMock(side_effect=update);api.bulk_set_enabled=AsyncMock(side_effect=enable);api.set_client_enabled=AsyncMock(side_effect=enable)
    api._list_clients_api=AsyncMock(return_value=[])
    api.attach_client=AsyncMock();api.bulk_attach_clients=AsyncMock();api.detach_client=AsyncMock()
    monkeypatch.setattr('app.xui.client.asyncio.sleep',AsyncMock())
    if ignores_zero_forever:
        with pytest.raises(RuntimeError,match='renew verification failed'):await api.reset_client_plan('demo',0,30)
    else:
        result=await api.reset_client_plan('demo',0,30)
        assert result['client']['totalGB']==0 and result['client']['enable']
        assert len(updates)==2
    api.reset_client_traffic.assert_awaited_once()


async def test_public_xui_explicit_unlimited_flag_overrides_legacy_volume(monkeypatch):
    panel=SimpleNamespace(login=AsyncMock(return_value=True),reset_client_plan=AsyncMock(return_value={}),close=AsyncMock())
    monkeypatch.setattr('app.services.xui_service.XUIClient',lambda *a:panel)
    monkeypatch.setattr('app.services.xui_service.decrypt_text',lambda x:'secret')
    api=XuiService();monkeypatch.setattr(api,'_apply_plan_group',AsyncMock())
    server=SimpleNamespace(panel_url='https://example.com',username='x',password_encrypted='x',meta={'inbound_ids':[5]})
    plan=SimpleNamespace(volume_gb=77,is_unlimited=True,duration_days=30,inbound_ids=[5],hwid_limit=0,meta={'inbound_mode':'manual'})
    await api.renew_client_on_plan(server,plan,'demo')
    assert panel.reset_client_plan.await_args.args[1]==0


async def test_pg_renew_rechecks_expiry_to_avoid_immediate_disable(monkeypatch):
    from datetime import datetime,timedelta,timezone
    api=PasarGuardService();state={'id':7,'status':'active','data_limit':0,'expire':'2020-01-01T00:00:00Z','group_ids':[5]}
    monkeypatch.setattr(api,'_effective_template_id',lambda *a:10)
    async def request(server,method,path,**kwargs):
        if method=='PUT' and not '/from_template/' in path and not path.endswith('/disabled'):state.update(kwargs['json'])
        return deepcopy(state)
    monkeypatch.setattr(api,'_request',request)
    plan=SimpleNamespace(volume_gb=0,is_unlimited=True,duration_days=30,inbound_ids=[5],hwid_limit=0)
    result=await api.renew_user_on_plan(SimpleNamespace(meta={}),plan,'demo')
    assert datetime.fromisoformat(result['expire'])>datetime.now(timezone.utc)+timedelta(days=29)


def test_web_tariff_switch_updates_unlimited_flag(client,monkeypatch):
    from app.database.models import Plan
    _,sessions=client;monkeypatch.setattr(web,'SessionLocal',sessions)
    app=FastAPI();app.include_router(web.router);app.dependency_overrides[web._auth_user]=lambda:'owner'
    async def prepare():
        async with sessions() as s:
            srv=await s.get(Server,1);srv.meta={'scope':'public','inbound_ids':[5]};await s.commit()
    asyncio.run(prepare())
    async def flag():
        async with sessions() as s:return (await s.get(Plan,1)).is_unlimited
    with TestClient(app) as c:
        for volume,expected in [(0,True),(20,False)]:
            result=c.post('/admin/plans/1/edit',data={'title':'Plan','volume_gb':volume,'duration_days':30,'category_id':1,'server_id':1},headers={'Accept':'application/json'})
            assert result.status_code==200,result.text
            assert asyncio.run(flag()) is expected
