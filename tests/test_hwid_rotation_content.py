import asyncio,base64,io,json,os
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from PIL import Image
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.database.models import Setting,Server,ClientService
from app.services import user_content as content
from app.services.pasarguard_service import PasarGuardService
from app.services.xui_service import XuiService
from app.bot.handlers import user_content as menus
from app.bot.keyboards import common
from test_miniapp import client


async def test_sanaei_reset_clears_then_rotates_both_credentials(monkeypatch):
 api=XuiService();calls=[]
 async def clear(*a):calls.append('clear')
 async def rotate(*a):calls.append('rotate');return {'uuid':'new','sub_id':'new-sub','sub_link':'https://sub.example/new'}
 monkeypatch.setattr(api,'clear_client_hwids',clear);monkeypatch.setattr(api,'revoke_and_new_link',rotate)
 assert (await api.reset_hwid_and_rotate(SimpleNamespace(),'name'))['sub_id']=='new-sub'
 assert calls==['clear','rotate']


@pytest.mark.parametrize('unchanged_uuid',[False,True])
async def test_pasarguard_native_reset_preserves_remote_account_and_quota(monkeypatch,unchanged_uuid):
 api=PasarGuardService();server=SimpleNamespace(panel_url='https://panel.example')
 before={'id':71,'subscription_url':'https://sub.example/old','proxy_settings':{'vless':{'id':'old'}},'data_limit':123,'used_traffic':12,'expire':'2030-01-01'}
 after={**before,'subscription_url':'https://sub.example/new','proxy_settings':{'vless':{'id':'old' if unchanged_uuid else 'new'}}}
 monkeypatch.setattr(api,'get_user',AsyncMock(side_effect=[deepcopy(before),deepcopy(after)]))
 clear=AsyncMock();rotate=AsyncMock(return_value=deepcopy(after))
 monkeypatch.setattr(api,'clear_user_hwids',clear);monkeypatch.setattr(api,'revoke_subscription',rotate)
 if unchanged_uuid:
  with pytest.raises(RuntimeError,match='UUID'):await api.reset_hwid_and_rotate(server,'name')
 else:
  result=await api.reset_hwid_and_rotate(server,'name')
  assert result['uuid']=='new' and result['id']==71 and result['sub_link']=='https://sub.example/new'
  assert all(result[k]==before[k] for k in ['data_limit','used_traffic','expire'])
 clear.assert_awaited_once();rotate.assert_awaited_once()


async def test_failed_hwid_clear_never_rotates(monkeypatch):
 api=XuiService();rotate=AsyncMock()
 monkeypatch.setattr(api,'clear_client_hwids',AsyncMock(side_effect=TimeoutError()))
 monkeypatch.setattr(api,'revoke_and_new_link',rotate)
 with pytest.raises(TimeoutError):await api.reset_hwid_and_rotate(SimpleNamespace(),'name')
 rotate.assert_not_awaited()


def test_tutorials_start_empty_and_round_trip_and_reject_unsafe_links(client,monkeypatch):
 _,sessions=client
 from app.api import admin_web as web
 monkeypatch.setattr(web,'SessionLocal',sessions)
 app=FastAPI();app.include_router(web.router);app.dependency_overrides[web._auth_user]=lambda:'owner'
 headers={'Accept':'application/json'}
 with TestClient(app) as c:
  assert c.get('/admin/api/v2/tutorials').json()['apps']==[]
  apps=[dict(id='',platform=p,name='Client '+p,download_url='https://download.example/app',text='نصب و افزودن کانفیگ') for p in ['android','ios','windows']]
  r=c.post('/admin/settings/tutorials',data={'enabled':'0','apps_json':json.dumps(apps)},headers=headers);assert r.status_code==200,r.text
  d=c.get('/admin/api/v2/tutorials').json();assert not d['enabled'] and len(d['apps'])==3
  assert len({a['id'] for a in d['apps']})==3
  invalid=[{**apps[0],'download_url':'javascript:alert(1)'}]
  assert c.post('/admin/settings/tutorials',data={'enabled':'1','apps_json':json.dumps(invalid)},headers=headers).status_code==400
  assert c.get('/admin/api/v2/tutorials').json()==d
  app.dependency_overrides.clear()
  assert c.get('/admin/api/v2/tutorials').status_code in (401,403)


@pytest.mark.parametrize('value',[{},[{'platform':'android','name':'x','download_url':'file:///etc/passwd'}],[{'platform':'linux','name':'x'}],[{'platform':'ios','name':'x','text':'x'*12001}]])
def test_tutorial_validation(value):
 with pytest.raises(ValueError):content.normalize_apps(value)


async def test_public_rules_only_sends_text_and_restart(monkeypatch):
 monkeypatch.setattr(menus,'get_user_button',AsyncMock(return_value=('قوانین',True)))
 send=AsyncMock();cb=SimpleNamespace(answer=AsyncMock())
 monkeypatch.setattr(menus,'ui_callback_message',send)
 monkeypatch.setattr(menus,'get_setting_value',AsyncMock(return_value='قوانین دستی'))
 await menus.public_rules(cb)
 assert send.await_args.args[1]=='قوانین دستی'
 buttons=[b for row in send.await_args.kwargs['reply_markup'].inline_keyboard for b in row]
 assert [b.callback_data for b in buttons]==['restart:start']


async def test_disabled_tutorial_rejects_old_app_button(monkeypatch):
 monkeypatch.setattr(menus,'get_user_button',AsyncMock(return_value=('آموزش',False)))
 reader=AsyncMock();monkeypatch.setattr(menus,'load_apps',reader)
 cb=SimpleNamespace(data='tutorial:app:old',answer=AsyncMock())
 await menus.tutorials(cb);reader.assert_not_awaited()
 assert cb.answer.await_args.kwargs['show_alert']


async def test_owner_only_content_editing(monkeypatch):
 monkeypatch.setattr(menus,'is_owner',lambda _:False)
 store=AsyncMock();monkeypatch.setattr(menus,'save_apps',store)
 cb=SimpleNamespace(from_user=SimpleNamespace(id=7),data='content:delete:123')
 await menus.delete_app(cb,SimpleNamespace())
 await menus.app_visibility_toggle(cb,SimpleNamespace())
 await menus.content_visibility_toggle(cb,SimpleNamespace())
 store.assert_not_awaited()


def test_reseller_menu_visibility_and_new_navigation(client,monkeypatch):
 _,sessions=client
 monkeypatch.setattr(common,'SessionLocal',sessions)
 monkeypatch.setattr(common,'get_setting_value',AsyncMock(side_effect=lambda k,d:d))
 common.invalidate_button_settings_cache()
 async def run():
  initial=await common.main_menu_inline(False,is_reseller=True)
  assert any(b.callback_data=='menu:reseller' for row in initial.inline_keyboard for b in row)
  async with sessions() as s:
   s.add(Setting(key='button_reseller_menu_enabled',value='0'));await s.commit()
  common.invalidate_button_settings_cache()
  current=await common.main_menu_inline(False,is_reseller=True)
  names={b.callback_data for row in current.inline_keyboard for b in row}
  assert 'menu:reseller' not in names and {'menu:rules','menu:tutorials'}<=names
 asyncio.run(run());common.invalidate_button_settings_cache()


def test_custom_qr_artwork_survives_database_roundtrip_and_has_quiet_zone(client,monkeypatch):
 _,sessions=client;monkeypatch.setattr(content,'SessionLocal',sessions)
 raw=io.BytesIO();Image.new('RGB',(400,500),(180,30,90)).save(raw,'PNG')
 encoded=content.normalize_background(raw.getvalue())
 async def save():
  async with sessions() as s:s.add(Setting(key=content.BACKGROUND_KEY,value=encoded));await s.commit()
  return await content.background_bytes()
 restored=asyncio.run(save());assert restored==base64.b64decode(encoded)
 from app.bot.qr_card import make_qr_card
 path=make_qr_card('https://sub.example/new',background_bytes=restored)
 try:
  image=Image.open(path).convert('RGB')
  assert image.size==(1080,1350) and image.getpixel((5,5))==(180,30,90)
  # White card + unmodified four-module QR quiet zone stay independent of artwork.
  assert image.getpixel((270,405))==(255,255,255)
 finally:os.unlink(path)


async def test_telegram_tutorial_sends_manual_text_and_download(monkeypatch):
 monkeypatch.setattr(menus,'get_user_button',AsyncMock(return_value=('آموزش',True)))
 monkeypatch.setattr(menus,'load_apps',AsyncMock(return_value=[dict(id='app1',platform='ios',name='My App',download_url='https://example.com/client',text='متن دلخواه')]))
 cb=SimpleNamespace(data='tutorial:app:app1',answer=AsyncMock(),message=SimpleNamespace(answer=AsyncMock()))
 await menus.tutorials(cb)
 assert cb.message.answer.await_args.args[0]=='متن دلخواه'
 buttons=[b for row in cb.message.answer.await_args.kwargs['reply_markup'].inline_keyboard for b in row]
 assert buttons[0].url=='https://example.com/client' and buttons[-1].callback_data=='restart:start'


def test_bot_editor_creates_empty_fields_then_edits_and_deletes(client,monkeypatch):
 monkeypatch.setattr(menus,'get_user_button',AsyncMock(return_value=('آموزش',True)))
 _,sessions=client;monkeypatch.setattr(content,'SessionLocal',sessions)
 monkeypatch.setattr(menus,'is_owner',lambda uid:uid==99)
 monkeypatch.setattr(menus,'ui_message',AsyncMock());monkeypatch.setattr(menus,'ui_callback_message',AsyncMock())
 from aiogram.fsm.context import FSMContext
 from aiogram.fsm.storage.memory import MemoryStorage
 from aiogram.fsm.storage.base import StorageKey
 async def run():
  state=FSMContext(storage=MemoryStorage(),key=StorageKey(bot_id=1,chat_id=99,user_id=99))
  cb=SimpleNamespace(data='content:new:android',from_user=SimpleNamespace(id=99),answer=AsyncMock())
  message=SimpleNamespace(from_user=SimpleNamespace(id=99),text='My app')
  await menus.edit_field(cb,state);await menus.save_field(message,state)
  apps=await content.load_apps();item=apps[0]
  assert item['platform']=='android' and item['text']==item['download_url']==''
  for field,value in [('download_url','https://example.com/app.apk'),('text','راهنمای دلخواه')]:
   cb.data=f"content:field:{item['id']}:{field}";message.text=value
   await menus.edit_field(cb,state);await menus.save_field(message,state)
  item=(await content.load_apps())[0];assert item['text']=='راهنمای دلخواه'
  cb.data='content:delete:'+item['id'];await menus.delete_app(cb,state)
  assert await content.load_apps()==[]
 asyncio.run(run())


async def test_long_emoji_tutorial_respects_telegram_utf16_limit(monkeypatch):
 monkeypatch.setattr(menus,'get_user_button',AsyncMock(return_value=('آموزش',True)))
 text='😀'*4000
 monkeypatch.setattr(menus,'load_apps',AsyncMock(return_value=[dict(id='x',name='App',platform='android',text=text,download_url='')]))
 cb=SimpleNamespace(data='tutorial:app:x',answer=AsyncMock(),message=SimpleNamespace(answer=AsyncMock()))
 await menus.tutorials(cb)
 chunks=[c.args[0] for c in cb.message.answer.await_args_list]
 assert ''.join(chunks)==text and all(len(c.encode('utf-16-le'))//2<=3500 for c in chunks)
 assert cb.message.answer.await_args_list[-1].kwargs['reply_markup']


async def test_artwork_upload_stores_manual_picture_and_clears_editor(monkeypatch):
 raw=io.BytesIO();Image.new('RGB',(300,400),'green').save(raw,'PNG')
 async def download(media,destination):destination.write(raw.getvalue())
 message=SimpleNamespace(from_user=SimpleNamespace(id=99),text=None,photo=[],document=SimpleNamespace(file_size=len(raw.getvalue())),bot=SimpleNamespace(download=download))
 state=SimpleNamespace(clear=AsyncMock());store=AsyncMock()
 monkeypatch.setattr(menus,'is_owner',lambda uid:uid==99)
 monkeypatch.setattr(menus,'set_setting_value',store);monkeypatch.setattr(menus,'ui_message',AsyncMock())
 await menus.artwork_save(message,state)
 assert store.await_args.args[0]==content.BACKGROUND_KEY
 with Image.open(io.BytesIO(base64.b64decode(store.await_args.args[1]))) as im:assert im.size==(1080,1350)
 state.clear.assert_awaited_once()


def test_artwork_filter_accepts_photos_and_leaves_start_to_main_router():
 handler=next(h for h in menus.router.message.handlers if h.callback is menus.artwork_save)
 guard=handler.filters[-1].callback
 assert guard(SimpleNamespace(text=None)) and not guard(SimpleNamespace(text='/start'))


@pytest.mark.parametrize('uuid_field',[False,True])
async def test_sanaei_rotation_changes_real_uuid_alias_and_subid_without_changing_plan(uuid_field):
 from app.xui.client import XUIClient
 api=object.__new__(XUIClient)
 state={'email':'client','id':'old-id','subId':'old-sub','totalGB':12345,'expiryTime':9999,'enable':False}
 if uuid_field:state['uuid']='old-id'
 async def read(email):return {'client':dict(state),'inbound_ids':[1,2]}
 async def update(client,inbound_ids=None):
  assert inbound_ids is None;state.update(client);return {'success':True}
 api.find_client=read;api._update_client=update;api._new_sub_id=lambda:'new-sub'
 result=await api.rotate_client_uuid('client')
 assert result['client']['id']!='old-id' and state['subId']=='new-sub'
 if uuid_field:assert state['uuid']==state['id']
 assert state['totalGB']==12345 and state['expiryTime']==9999 and state['enable'] is False


async def test_sanaei_missing_readback_never_claims_success():
 from app.xui.client import XUIClient
 api=object.__new__(XUIClient)
 api.find_client=AsyncMock(side_effect=[{'client':{'id':'old','subId':'old-sub'}},None])
 api._update_client=AsyncMock();api._new_sub_id=lambda:'new-sub'
 with pytest.raises(RuntimeError,match='read back'):await api.rotate_client_uuid('client')


async def test_legacy_purchased_role_upgrade_is_only_for_own_users():
 from app.services import pasarguard_panel_sales as sale
 state={'id':7,'name':sale.ROLE_NAME,'is_owner':False,'permissions':{'users':deepcopy(sale.LEGACY_USER_RULES),'groups':dict(sale.GROUP_RULES),'hwids':None},'access':{'require_template':True},'limits':{'max_users':10}}
 calls=[]
 async def request(server,method,path,**kwargs):
  calls.append((method,path,kwargs))
  if method=='PUT':state['permissions']=deepcopy(kwargs['json']['permissions'])
  return deepcopy(state)
 await sale.PanelResellerProvisioner(SimpleNamespace(_request=request)).ensure_control_permissions(SimpleNamespace(),7)
 payload=next(k['json'] for m,p,k in calls if m=='PUT')
 assert set(payload)=={'permissions'} and payload['permissions']['users']['revoke_sub']=={'scope':1}
 assert payload['permissions']['hwids']=={'read':{'scope':1},'delete':{'scope':1}}
 assert state['limits']['max_users']==10 and state['access']['require_template']
 sale._verify_reseller_role(state)


async def test_unsafe_role_is_not_automatically_upgraded():
 from app.services import pasarguard_panel_sales as sale
 role={'id':7,'name':sale.ROLE_NAME,'is_owner':False,'permissions':{'users':{**sale.LEGACY_USER_RULES,'read':{'scope':2}},'groups':dict(sale.GROUP_RULES)}}
 api=SimpleNamespace(_request=AsyncMock(return_value=role))
 with pytest.raises(RuntimeError):await sale.PanelResellerProvisioner(api).ensure_control_permissions(SimpleNamespace(),7)
 assert api._request.await_count==1


async def test_native_role_denial_is_not_bypassed():
 from app.services import pasarguard_panel_sales as sale
 role={'id':7,'name':sale.ROLE_NAME,'is_owner':False,'permissions':{'users':dict(sale.LEGACY_USER_RULES),'groups':dict(sale.GROUP_RULES)}}
 api=SimpleNamespace(_request=AsyncMock(side_effect=[role,RuntimeError('403 denied')]))
 with pytest.raises(RuntimeError,match='403'):await sale.PanelResellerProvisioner(api).ensure_control_permissions(SimpleNamespace(),7)
 assert api._request.await_count==2


async def test_tutorial_guide_registers_current_message_for_back_button(monkeypatch):
 from unittest.mock import Mock
 monkeypatch.setattr(menus,'get_user_button',AsyncMock(return_value=('آموزش',True)))
 monkeypatch.setattr(menus,'load_apps',AsyncMock(return_value=[dict(id='x',name='App',platform='android',text='راهنما',download_url='')]))
 remember=Mock();monkeypatch.setattr(menus,'remember_ui_message',remember)
 sent=SimpleNamespace(message_id=123,chat=SimpleNamespace(id=11))
 cb=SimpleNamespace(data='tutorial:app:x',answer=AsyncMock(),message=SimpleNamespace(answer=AsyncMock(return_value=sent)))
 await menus.tutorials(cb);remember.assert_called_once_with(11,123)


def test_web_visibility_preserves_content_and_initial_rules(client,monkeypatch):
 _,sessions=client
 from app.api import admin_web as web
 monkeypatch.setattr(web,'SessionLocal',sessions)
 app=FastAPI();app.include_router(web.router);app.dependency_overrides[web._auth_user]=lambda:'owner'
 async def seed():
  async with sessions() as s:
   await s.merge(Setting(key='rules_enabled',value='1'));await s.commit()
 asyncio.run(seed())
 apps=[dict(id='manual',platform='ios',name='Client',download_url='',text='راهنمای دستی',enabled=False)]
 with TestClient(app) as c:
  data={'enabled':'0','rules_button_enabled':'0','apps_json':json.dumps(apps)}
  assert c.post('/admin/settings/tutorials',data=data,headers={'Accept':'application/json'}).status_code==200
  saved=c.get('/admin/api/v2/tutorials').json()
  assert saved['apps']==apps and not saved['enabled'] and not saved['rules_button_enabled']
  # Older clients omit the new Rules toggle; their saves must preserve it.
  data.pop('rules_button_enabled');data['enabled']='1'
  assert c.post('/admin/settings/tutorials',data=data,headers={'Accept':'application/json'}).status_code==200
  assert not c.get('/admin/api/v2/tutorials').json()['rules_button_enabled']
 async def verify():
  async with sessions() as s:assert (await s.get(Setting,'rules_enabled')).value=='1'
 asyncio.run(verify())


async def test_disabled_program_hidden_and_stale_button_blocked(monkeypatch):
 monkeypatch.setattr(menus,'get_user_button',AsyncMock(return_value=('آموزش',True)))
 apps=[dict(id='hidden',platform='android',name='Hidden',download_url='',text='secret',enabled=False),dict(id='legacy',platform='android',name='Visible',download_url='',text='guide')]
 monkeypatch.setattr(menus,'load_apps',AsyncMock(return_value=apps))
 send=AsyncMock();monkeypatch.setattr(menus,'ui_callback_message',send)
 cb=SimpleNamespace(data='tutorial:os:android',answer=AsyncMock(),message=SimpleNamespace(answer=AsyncMock()))
 await menus.tutorials(cb)
 names={b.callback_data for row in send.await_args.kwargs['reply_markup'].inline_keyboard for b in row}
 assert 'tutorial:app:legacy' in names and 'tutorial:app:hidden' not in names
 cb.data='tutorial:app:hidden';await menus.tutorials(cb)
 cb.message.answer.assert_not_awaited()
 assert send.await_args.args[1]=='این آموزش دیگر موجود نیست.'


async def test_rules_disabled_blocks_old_button(monkeypatch):
 monkeypatch.setattr(menus,'get_user_button',AsyncMock(return_value=('قوانین',False)))
 send=AsyncMock();monkeypatch.setattr(menus,'ui_callback_message',send)
 cb=SimpleNamespace(answer=AsyncMock());await menus.public_rules(cb)
 send.assert_not_awaited();assert cb.answer.await_args.kwargs['show_alert']


def test_bot_toggles_preserve_program_and_update_home_menu(client,monkeypatch):
 _,sessions=client
 monkeypatch.setattr(content,'SessionLocal',sessions)
 monkeypatch.setattr(common,'SessionLocal',sessions)
 monkeypatch.setattr(common,'get_setting_value',AsyncMock(side_effect=lambda k,d:d))
 monkeypatch.setattr(menus,'is_owner',lambda uid:uid==99)
 monkeypatch.setattr(menus,'ui_callback_message',AsyncMock())
 async def set_value(k,v):
  async with sessions() as s:await s.merge(Setting(key=k,value=v));await s.commit()
 monkeypatch.setattr(menus,'set_setting_value',set_value)
 async def run():
  common.invalidate_button_settings_cache()
  await content.save_apps([dict(id='a1',platform='android',name='Manual',download_url='',text='kept')])
  cb=SimpleNamespace(from_user=SimpleNamespace(id=99),data='content:app_toggle:a1',answer=AsyncMock())
  state=SimpleNamespace(clear=AsyncMock())
  await menus.app_visibility_toggle(cb,state)
  assert (await content.load_apps())[0]['enabled'] is False
  await menus.app_visibility_toggle(cb,state)
  row=(await content.load_apps())[0];assert row['enabled'] and row['text']=='kept'
  for name in ['rules','tutorials']:
   cb.data='content:toggle:'+name;await menus.content_visibility_toggle(cb,state)
  keys={b.callback_data for row in (await common.main_menu_inline(False)).inline_keyboard for b in row}
  assert 'menu:rules' not in keys and 'menu:tutorials' not in keys
  for name in ['rules','tutorials']:
   cb.data='content:toggle:'+name;await menus.content_visibility_toggle(cb,state)
  keys={b.callback_data for row in (await common.main_menu_inline(False)).inline_keyboard for b in row}
  assert {'menu:rules','menu:tutorials'}<=keys
 asyncio.run(run());common.invalidate_button_settings_cache()
