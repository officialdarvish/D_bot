import asyncio,json
import pytest
from fastapi import FastAPI,Depends
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_miniapp import client
from test_encrypted_backup import backup_client,key_store,new_key
from app.api import custom_texts as api,admin_web as web
from app.bot import custom_texts as runtime
from app.database import defaults
from app.database.models import Setting,User
from app.services import encrypted_backup as crypto

@pytest.fixture
def custom(client,monkeypatch):
    _,sessions=client
    for module in (api,runtime,defaults):monkeypatch.setattr(module,'SessionLocal',sessions)
    runtime.invalidate_custom_text_cache();defaults.invalidate_settings_cache()
    app=FastAPI();app.include_router(api.router,dependencies=[Depends(web._auth_user)])
    with TestClient(app) as c:
        assert c.get('/admin/api/v2/custom-profiles').status_code==401
        assert c.post('/admin/api/v2/custom-profiles',data={'name':'test'}).status_code==401
        app.dependency_overrides[web._auth_user]=lambda:'owner'
        yield c,sessions
    runtime.invalidate_custom_text_cache();defaults.invalidate_settings_cache()


def test_named_profile_saves_applies_and_resets_runtime_text_without_business_settings(custom):
    c,sessions=custom;items=c.get('/api/admin/custom-texts').json()['items']
    buy=next(i for i in items if i['legacy_key']=='button_buy_text')
    welcome=next(i for i in items if i['legacy_key']=='welcome_text')
    message=next(i for i in items if i['kind']=='message' and 'handlers/public/buy.py' in i['source'])
    async def seed():
        async with sessions() as s:
            s.add(Setting(key='payment_secret_encrypted',value='must-not-be-captured'))
            s.add(Setting(key='feature_resellers',value='0'));await s.commit()
    asyncio.run(seed())
    for item,value in [(buy,'خرید ویژه'),(welcome,'سلام {bot_name}'),(message,'متن خرید سفارشی')]:
        assert c.post('/api/admin/custom-texts',data={'key':item['key'],'value':value,**({'enabled':'0'} if item is buy else {})}).json()['ok']
    saved=c.post('/admin/api/v2/custom-profiles',data={'name':'My shop'}).json();pid=saved['id']
    assert c.get('/admin/api/v2/custom-profiles').json()['items']==[{'id':pid,'name':'My shop'}]
    assert c.post('/admin/api/v2/custom-profiles/apply',data={'profile_id':'default'}).json()['ok']
    current={i['key']:i for i in c.get('/api/admin/custom-texts').json()['items']}
    assert current[buy['key']]['current']==buy['default'] and current[buy['key']]['enabled']
    assert c.post('/admin/api/v2/custom-profiles/apply',data={'profile_id':pid}).json()['ok']
    current={i['key']:i for i in c.get('/api/admin/custom-texts').json()['items']}
    assert current[buy['key']]['current']=='خرید ویژه' and not current[buy['key']]['enabled']
    async def verify():
        assert await runtime.customize_text(message['default'])=='متن خرید سفارشی'
        assert 'سلام' in await defaults.get_setting_value('welcome_text')
        async with sessions() as s:
            assert (await s.get(Setting,'feature_resellers')).value=='0'
            assert (await s.get(Setting,'payment_secret_encrypted')).value=='must-not-be-captured'
            row=await s.get(Setting,'custom_profile:'+pid)
            assert 'must-not-be-captured' not in row.value and 'feature_resellers' not in row.value
    asyncio.run(verify())
    assert c.post('/admin/api/v2/custom-profiles/delete',data={'profile_id':pid}).json()['ok']
    assert c.get('/admin/api/v2/custom-profiles').json()['items']==[]
    # Deleting a stored template does not revert currently applied texts.
    assert next(i for i in c.get('/api/admin/custom-texts').json()['items'] if i['key']==buy['key'])['current']=='خرید ویژه'


def test_profile_limits_and_unknown_ids(custom):
    c,_=custom
    assert c.post('/admin/api/v2/custom-profiles',data={'name':' '}).status_code==422
    for i in range(8):assert c.post('/admin/api/v2/custom-profiles',data={'name':f'Style {i}'}).status_code==200
    assert c.post('/admin/api/v2/custom-profiles',data={'name':'Too many'}).status_code==409
    assert c.post('/admin/api/v2/custom-profiles/apply',data={'profile_id':'bad-setting-key'}).status_code==404


def test_first_run_restore_preserves_destination_login_and_finishes_wizard(backup_client,monkeypatch,tmp_path):
    c,sessions,_=backup_client
    async def settings(values):
        async with sessions() as s:
            for k,v in values.items():await s.merge(Setting(key=k,value=v))
            await s.commit()
    asyncio.run(settings({'web_path':'old-source','web_admin_username':'old-admin','web_credentials_updated_at':'old-version','initial_setup_done':'1','bot_name':'Restored shop','setup_progress_v1':'{"step":12}'}))
    raw=c.get('/admin/backup/download').content
    key=c.get('/admin/backup/recovery-key').text.strip()
    asyncio.run(settings({'web_path':'new-panel','web_admin_username':'new-admin','web_credentials_updated_at':'destination-version','initial_setup_done':'0','bot_name':'Fresh shop'}))
    monkeypatch.setattr(crypto.settings,'BACKUP_ENCRYPTION_KEY',new_key())
    headers={'Accept':'application/json'}
    files={'file':('backup.dbot',raw,'application/octet-stream')}
    failed=c.post('/admin/backup/restore',data={'setup_restore':'1','recovery_key':new_key()},files=files,headers=headers)
    assert failed.status_code==409
    result=c.post('/admin/backup/restore',data={'setup_restore':'1','recovery_key':key},files=files,headers=headers)
    assert result.status_code==200,result.text
    async def verify():
        async with sessions() as s:
            values={r.key:r.value for r in (await s.execute(select(Setting))).scalars()}
            assert values['web_path']=='new-panel' and values['web_admin_username']=='new-admin'
            assert values['web_credentials_updated_at']=='destination-version'
            assert values['bot_name']=='Restored shop' and values['initial_setup_done']=='1'
            assert 'setup_progress_v1' not in values
    asyncio.run(verify())
    assert c.post('/admin/backup/restore',data={'setup_restore':'1'},files=files,headers=headers).status_code==409


def test_profile_tutorial_texts_preserve_live_video_and_download_settings(custom):
    from app.services.user_content import save_apps,load_apps
    c,sessions=custom
    async def configure(name,text,video):
        async with sessions() as s:
            await save_apps([{'id':'happ','platform':'android','name':name,'text':text,'download_url':'https://example.com/current','video_file_id':video,'enabled':True}],s);await s.commit()
    asyncio.run(configure('Happ custom','Original tutorial','video_old'))
    pid=c.post('/admin/api/v2/custom-profiles',data={'name':'Tutorial style'}).json()['id']
    asyncio.run(configure('Changed','Changed text','video_new'))
    assert c.post('/admin/api/v2/custom-profiles/apply',data={'profile_id':pid}).status_code==200
    async def verify():
        async with sessions() as s:
            row=(await load_apps(s))[0]
            assert row['name']=='Happ custom' and row['text']=='Original tutorial'
            assert row['video_file_id']=='video_new' and row['download_url']=='https://example.com/current'
    asyncio.run(verify())


def test_profile_preserves_unrelated_delivery_template_definitions(custom):
    c,sessions=custom
    from app.services.delivery_templates import SETTING_KEY,load_config
    def config(active,ids):
        return {'active':active,'templates':[{'id':i,'name':i,'text':'Ready {username}'} for i in ids]}
    async def store(value):
        async with sessions() as s:
            await s.merge(Setting(key=SETTING_KEY,value=json.dumps(value)));await s.commit()
    asyncio.run(store(config('style_a',['style_a'])))
    pid=c.post('/admin/api/v2/custom-profiles',data={'name':'Delivery style'}).json()['id']
    asyncio.run(store(config('style_b',['style_a','style_b'])))
    assert c.post('/admin/api/v2/custom-profiles/apply',data={'profile_id':pid}).status_code==200
    async def verify(active):
        async with sessions() as s:
            result=await load_config(s)
            assert result['active']==active
            assert {r['id'] for r in result['templates']}=={'style_a','style_b'}
    asyncio.run(verify('style_a'))
    assert c.post('/admin/api/v2/custom-profiles/apply',data={'profile_id':'default'}).status_code==200
    asyncio.run(verify('simple'))
