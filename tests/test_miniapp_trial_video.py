"""Native trials share bot entitlement; per-app videos survive edits and deliver safely."""
import asyncio,json,uuid
from contextlib import asynccontextmanager
from datetime import datetime,timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select,func
from test_miniapp import client,signed
from app.api import miniapp,miniapp_actions as actions,admin_web as web
from app.bot.handlers.public import test_account as trial
from app.bot.handlers import user_content as menus
from app.services import user_content as content
from app.database.models import ClientService,TestAccountUsage,User,MiniAppOperation
REAL_CREATE=trial._create_test_account_on_target
H={'X-Telegram-Init-Data':signed()}
OTHER={'X-Telegram-Init-Data':signed(22)}

@pytest.fixture
def trials(client,monkeypatch):
    _,sessions=client
    for module in [actions,trial]:monkeypatch.setattr(module,'SessionLocal',sessions)
    monkeypatch.setattr(trial.settings,'ADMIN_IDS','99');monkeypatch.setattr(trial.settings,'OWNER_IDS','')
    values={'test_account_volume_gb':'0.2','test_account_duration_days':'1'}
    async def setting(k,d=''):return values.get(k,d)
    for module in [trial,miniapp]:monkeypatch.setattr(module,'get_setting_value',setting)
    monkeypatch.setattr(trial,'_load_test_account_targets',AsyncMock(return_value=[{'server_id':1},{'server_id':2}]))
    monkeypatch.setattr(trial,'_notify_admins_test_account',AsyncMock())
    import app.bot.error_reporting as reporting
    monkeypatch.setattr(reporting,'report_bot_error',AsyncMock())
    calls=[];failed=set()
    async def create(*,user_id,target,volume_gb,duration_days):
        calls.append((target['server_id'],volume_gb))
        if target['server_id'] in failed:raise RuntimeError('provider unavailable')
        async with sessions() as s:
            svc=ClientService(user_id=user_id,server_id=target['server_id'],client_username='test_'+uuid.uuid4().hex[:8],xui_email='test_email',sub_link='https://sub.example/test',total_bytes=int(volume_gb*1024**3),expires_at=datetime.utcnow()+timedelta(days=duration_days))
            s.add(svc);await s.commit()
            return dict(service_id=svc.id,client_name=svc.client_username,server_name='PG',server_type='pasarguard',sub_link=svc.sub_link,password=None)
    monkeypatch.setattr(trial,'_create_test_account_on_target',create)
    @asynccontextmanager
    async def bot():yield SimpleNamespace()
    monkeypatch.setattr(actions,'telegram_bot',bot)
    app=FastAPI();app.include_router(miniapp.router);app.include_router(actions.router)
    with TestClient(app) as c:yield c,sessions,values,calls,failed


def test_trial_queue_replay_multiserver_delivery_and_shared_bot_limit(trials):
    c,sessions,values,calls,failed=trials
    assert c.post('/api/miniapp/trial',json={'key':str(uuid.uuid4())}).status_code==401
    assert c.get('/api/miniapp/session',headers=H).json()['buttons']['test_account']
    b={'key':str(uuid.uuid4())}
    op=c.post('/api/miniapp/trial',headers=H,json=b).json();oid=op['id']
    assert op['status']=='queued'
    assert c.post('/api/miniapp/trial',headers=H,json=b).json()['id']==oid
    assert c.post('/api/miniapp/trial',headers=H,json={'key':str(uuid.uuid4())}).json()['id']==oid
    assert c.post('/api/miniapp/trial',headers=OTHER,json=b).status_code==409
    assert c.get('/api/miniapp/operations/'+str(oid),headers=OTHER).status_code==404
    asyncio.run(actions.process_operations())
    result=c.get('/api/miniapp/operations/'+str(oid),headers=H).json()
    assert result['status']=='done' and len(result['result']['services'])==2, (result,calls)
    assert calls==[(1,0.2),(2,0.2)]
    assert all(s['total_bytes']==int(.2*1024**3) and not s['unlimited'] for s in result['result']['services'])
    assert c.get('/api/miniapp/trial',headers=H).json()['used']
    assert c.post('/api/miniapp/trial',headers=H,json={'key':str(uuid.uuid4())}).status_code==409
    assert c.post('/api/miniapp/trial',headers=H,json=b).json()['id']==oid
    async def check():
        async with sessions() as s:
            assert await s.scalar(select(func.count(TestAccountUsage.id)))==1
            assert (await s.get(User,1)).wallet_balance==250000
        outcome=await trial.handle_test_account(SimpleNamespace(bot=SimpleNamespace()),11,None,native=True)
        assert not outcome['ok']
    asyncio.run(check());assert len(calls)==2


@pytest.mark.parametrize('failed_ids,expected',[(set([1]),1),(set([1,2]),0)])
def test_trial_partial_success_and_all_failed_retry(trials,failed_ids,expected):
    c,sessions,values,calls,failed=trials;failed.update(failed_ids)
    r=c.post('/api/miniapp/trial',headers=H,json={'key':str(uuid.uuid4())});assert r.status_code==200,r.text
    asyncio.run(actions.process_operations())
    data=c.get('/api/miniapp/trial',headers=H).json();op=data['operation']
    assert data['used']==bool(expected)
    if expected:
        assert op['status']=='done' and len(op['result']['services'])==expected
        assert op['result']['failed_count']==1
    else:
        assert op['status']=='failed'
        failed.clear()
        assert c.post('/api/miniapp/trial',headers=H,json={'key':str(uuid.uuid4())}).status_code==200
        asyncio.run(actions.process_operations())
        assert c.get('/api/miniapp/trial',headers=H).json()['operation']['status']=='done'


@pytest.mark.parametrize('key',['test_account_enabled','test_account_button_visible'])
def test_trial_flags_rechecked_before_queue_and_worker(trials,key):
    c,sessions,values,calls,failed=trials
    op=c.post('/api/miniapp/trial',headers=H,json={'key':str(uuid.uuid4())}).json()
    values[key]='0'
    assert not c.get('/api/miniapp/session',headers=H).json()['buttons']['test_account']
    assert c.post('/api/miniapp/trial',headers=H,json={'key':str(uuid.uuid4())}).status_code==403
    asyncio.run(actions.process_operations());assert not calls
    assert c.get('/api/miniapp/operations/'+str(op['id']),headers=H).json()['status']=='failed'


def test_trial_links_available_with_hidden_services_but_isolated(trials,monkeypatch):
    c,sessions,values,calls,failed=trials
    oid=c.post('/api/miniapp/trial',headers=H,json={'key':str(uuid.uuid4())}).json()['id']
    asyncio.run(actions.process_operations())
    sid=c.get('/api/miniapp/operations/'+str(oid),headers=H).json()['result']['service_ids'][0]
    monkeypatch.setattr(miniapp,'get_user_button',AsyncMock(side_effect=lambda k:('button',k!='my_services')))
    from app.services.xui_service import XuiService
    monkeypatch.setattr(XuiService,'resolve_service_subscription',AsyncMock(return_value='https://sub.example/test'))
    assert c.get(f'/api/miniapp/services/{sid}/link',headers=H).status_code==200
    assert c.get(f'/api/miniapp/services/{sid}/qr',headers=H).status_code==200
    assert c.get(f'/api/miniapp/services/{sid}/link',headers=OTHER).status_code==403
    assert c.get('/api/miniapp/services/1/link',headers=H).status_code==403


def test_video_web_upload_save_preserve_replace_remove_and_auth(client,monkeypatch):
    _,sessions=client
    monkeypatch.setattr(web,'SessionLocal',sessions)
    monkeypatch.setattr(web.settings,'ADMIN_IDS','99');monkeypatch.setattr(web.settings,'OWNER_IDS','')
    send=AsyncMock(return_value=SimpleNamespace(video=SimpleNamespace(file_id='BAAC_video123')))
    @asynccontextmanager
    async def bot():yield SimpleNamespace(send_video=send)
    monkeypatch.setattr(miniapp,'telegram_bot',bot)
    app=FastAPI();app.include_router(web.router);app.dependency_overrides[web._auth_user]=lambda:'owner'
    headers={'Accept':'application/json'}
    with TestClient(app) as c:
        raw=b'\x00\x00\x00\x18ftypmp42'+b'video-data'
        r=c.post('/admin/settings/tutorials/video',files={'file':('guide.mp4',raw,'video/mp4')},headers=headers)
        assert r.status_code==200,r.text
        fid=r.json()['video_file_id'];assert send.await_args.args[0]==99
        apps=[dict(id='client',platform='ios',name='Client',text='guide',download_url='https://example.com',video_file_id=fid)]
        def save():return c.post('/admin/settings/tutorials',data={'apps_json':json.dumps(apps)},headers=headers)
        assert save().status_code==200
        assert c.get('/admin/api/v2/tutorials').json()['apps'][0]['video_file_id']==fid
        apps[0].pop('video_file_id');assert save().status_code==200
        assert c.get('/admin/api/v2/tutorials').json()['apps'][0]['video_file_id']==fid
        apps[0]['video_file_id']='BAAC_replaced';assert save().status_code==200
        assert c.get('/admin/api/v2/tutorials').json()['apps'][0]['video_file_id']=='BAAC_replaced'
        apps[0]['video_file_id']='';assert save().status_code==200
        assert not c.get('/admin/api/v2/tutorials').json()['apps'][0].get('video_file_id')
        for filename,raw in [('x.txt',b'bad'),('x.mp4',b'not an mp4 video')]:
            assert c.post('/admin/settings/tutorials/video',files={'file':(filename,raw)},headers=headers).status_code==400
        monkeypatch.setattr(content,'MAX_TUTORIAL_VIDEO_BYTES',10)
        assert c.post('/admin/settings/tutorials/video',files={'file':('x.mp4',b'x'*11)},headers=headers).status_code==400
        assert send.await_count==1
        app.dependency_overrides.clear()
        assert c.post('/admin/settings/tutorials/video',files={'file':('x.mp4',raw)},headers=headers).status_code in (401,403)


async def test_bot_video_upload_remove_owner_only_and_tutorial_delivery(monkeypatch):
    apps=[dict(id='client',platform='ios',name='Client',download_url='https://example.com',text='Full instructions')]
    monkeypatch.setattr(menus,'load_apps',AsyncMock(side_effect=lambda:apps))
    save=AsyncMock();monkeypatch.setattr(menus,'save_apps',save)
    monkeypatch.setattr(menus,'is_owner',lambda uid:uid==99)
    monkeypatch.setattr(menus,'ui_message',AsyncMock())
    state=SimpleNamespace(get_data=AsyncMock(return_value={'ident':'client'}),clear=AsyncMock())
    message=SimpleNamespace(from_user=SimpleNamespace(id=99),text=None,video=SimpleNamespace(file_size=1024,file_id='BAAC_botvideo'))
    await menus.save_video(message,state);assert apps[0]['video_file_id']=='BAAC_botvideo';save.assert_awaited_once()
    monkeypatch.setattr(menus,'get_user_button',AsyncMock(return_value=('Tutorial',True)))
    cb=SimpleNamespace(data='tutorial:app:client',answer=AsyncMock(),message=SimpleNamespace(answer=AsyncMock(),answer_video=AsyncMock()))
    await menus.tutorials(cb)
    assert cb.message.answer.await_args.args[0]=='Full instructions'
    assert cb.message.answer.await_args.kwargs['reply_markup'].inline_keyboard[0][0].url=='https://example.com'
    assert cb.message.answer_video.await_args.args[0]=='BAAC_botvideo'
    message.from_user.id=11;message.text='-';await menus.save_video(message,state)
    assert apps[0]['video_file_id']=='BAAC_botvideo'
    message.from_user.id=99;await menus.save_video(message,state);assert not apps[0]['video_file_id']


async def test_bot_video_rejects_oversize_and_wrong_media_without_clearing(monkeypatch):
    monkeypatch.setattr(menus,'is_owner',lambda _:True)
    monkeypatch.setattr(menus,'load_apps',AsyncMock(return_value=[dict(id='client')]))
    store=AsyncMock();monkeypatch.setattr(menus,'save_apps',store)
    monkeypatch.setattr(menus,'ui_message',AsyncMock())
    state=SimpleNamespace(get_data=AsyncMock(return_value={'ident':'client'}),clear=AsyncMock())
    for video in [None,SimpleNamespace(file_size=51*1024**2)]:
        await menus.save_video(SimpleNamespace(from_user=SimpleNamespace(id=99),text=None,video=video),state)
    store.assert_not_awaited();state.clear.assert_not_awaited()


def test_queue_runs_actual_pasarguard_trial_persistence(trials,monkeypatch):
    c,sessions,values,calls,failed=trials
    from app.database.models import Server
    from app.services.pasarguard_service import PasarGuardService
    # Restore the real target provisioner; only the external panel is simulated.
    monkeypatch.setattr(trial,'_create_test_account_on_target',REAL_CREATE)
    monkeypatch.setattr(trial,'_load_test_account_targets',AsyncMock(return_value=[{'server_id':1,'inbound_ids':[5]}]))
    async def create(self,server,plan,name):
        assert server.server_type=='pasarguard' and plan.is_test_account and plan.volume_gb==.2
        return {'username':'test_from_template','sub_link':'https://sub.example/actual','uuid':'actual-uuid'}
    monkeypatch.setattr(PasarGuardService,'create_user_on_plan',create)
    async def seed():
        async with sessions() as s:
            server=await s.get(Server,1);server.server_type='pasarguard';await s.commit()
    asyncio.run(seed())
    r=c.post('/api/miniapp/trial',headers=H,json={'key':str(uuid.uuid4())});assert r.status_code==200,r.text
    asyncio.run(actions.process_operations())
    op=c.get('/api/miniapp/trial',headers=H).json()['operation'];assert op['status']=='done',op
    service=op['result']['services'][0]
    assert service['username']=='test_from_template' and service['total_bytes']==int(.2*1024**3)
    async def check():
        async with sessions() as s:
            svc=await s.get(ClientService,service['id'])
            assert svc.sub_link=='https://sub.example/actual' and svc.xui_uuid=='actual-uuid'
    asyncio.run(check())


def test_bot_usage_blocks_first_native_request(trials):
    c,sessions,values,calls,failed=trials
    async def used():
        async with sessions() as s:
            s.add(TestAccountUsage(user_id=1,telegram_id=11,service_id=1));await s.commit()
    asyncio.run(used())
    assert c.get('/api/miniapp/trial',headers=H).json()['used']
    assert c.post('/api/miniapp/trial',headers=H,json={'key':str(uuid.uuid4())}).status_code==409
    assert not calls
