import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from test_category_service_assignment import catalogue
from app.api import custom_texts as api
from app.api.admin_web import _auth_user
from app.bot import service_presenter as presenter, custom_texts
from app.bot.config_delivery import send_config_text, send_config_photo, plain_html
from app.services import delivery_templates as templates

LINK='https://sub.example/s/opaque?key=a&copy=1'
VALUES=dict(username='test_user', title='20GB service', volume_gb=20, duration_days=30, sub_link=LINK, server_type='pasarguard')


@pytest.fixture
def editor(catalogue,monkeypatch):
    _,sessions=catalogue
    monkeypatch.setattr(api,'SessionLocal',sessions)
    import app.database.session as db
    monkeypatch.setattr(db,'SessionLocal',sessions)
    app=FastAPI();app.include_router(api.router,dependencies=[Depends(_auth_user)])
    with TestClient(app) as c:
        c.cookies.set('dbot_admin_token','valid')
        c.headers.update({'Accept':'application/json','X-CSRF-Token':'csrf'})
        yield c,sessions


def test_default_simple_and_save_custom_switch_restore(editor):
    c,_=editor
    response=c.get('/admin/api/v2/delivery-templates');assert response.status_code==200
    config=response.json();assert config['active']=='simple' and config['templates']==[]
    assert [p['id'] for p in config['presets']]==['simple','legacy']
    custom=[{'id':'brand','name':'برند من','text':'<b>{title}</b>\nکاربر: {username}\n{traffic}\n{duration}\n{subscription_line}'}]
    r=c.post('/admin/api/v2/delivery-templates',data={'active':'brand','templates_json':__import__('json').dumps(custom)})
    assert r.status_code==200,r.text
    caption=asyncio.run(presenter.build_delivery_caption(**VALUES))
    assert '20GB service' in caption and LINK in plain_html(caption) and 'Happ' not in caption
    assert c.get('/admin/api/v2/delivery-templates').json()['templates']==custom
    assert c.post('/admin/api/v2/delivery-templates',data={'active':'legacy','templates_json':'[]'}).status_code==200
    assert asyncio.run(presenter.build_delivery_caption(**VALUES))==presenter.build_service_caption(**VALUES)
    assert c.post('/admin/api/v2/delivery-templates',data={'active':'simple','templates_json':'[]'}).status_code==200
    assert isinstance(asyncio.run(presenter.build_delivery_caption(**VALUES)), templates.DeliveryTemplateText)


@pytest.mark.parametrize('bad',[
 {'active':'missing','templates':[]},
 {'active':'simple','templates':[{'id':'simple','name':'a','text':'test'}]},
 {'active':'simple','templates':[{'id':'x','name':'a','text':'{username.__class__}'}]},
 {'active':'simple','templates':[{'id':'x','name':'a','text':'<b>unclosed'}]},
 {'active':'simple','templates':[{'id':'x','name':'a','text':'<script>x</script>'}]},
 {'active':'simple','templates':[{'id':'x','name':'a','text':'{sub_link!r}'}]},
 {'active':'simple','templates':[{'id':'x','name':'a','text':'< 1 &copy;'}]},
 {'active':'simple','templates':[{'id':'x','name':'a','text':'<?xml version=1?>'}]},
 {'active':'simple','templates':[{'id':'x','name':'a','text':'x'*3501}]},
])
def test_invalid_templates_are_rejected_without_overwriting(editor,bad):
    import json
    c,_=editor
    r=c.post('/admin/api/v2/delivery-templates',data={'active':bad['active'],'templates_json':json.dumps(bad['templates'])})
    assert r.status_code==400
    assert c.get('/admin/api/v2/delivery-templates').json()['active']=='simple'


def test_preview_escapes_user_fields_and_keeps_full_real_link(editor):
    c,_=editor
    r=c.post('/admin/api/v2/delivery-templates/preview',data={'text':'سلام {username}؛ {traffic}؛ {duration}'})
    assert r.status_code==200 and 'https://example.com/sub/demo' in r.json()['preview']
    caption=templates.render_template(templates.SIMPLE_TEXT,**{**VALUES,'username':'<b>A&B</b>','title':'<i>VIP</i>','volume_gb':0,'duration_days':0})
    assert '&lt;b&gt;A&amp;B&lt;/b&gt;' in caption and '&lt;i&gt;VIP&lt;/i&gt;' in caption
    assert 'نامحدود' in caption and 'بدون انقضا' in caption and '0 گیگ' not in caption
    assert LINK in plain_html(caption)
    assert c.post('/admin/api/v2/delivery-templates/preview',data={'text':'{unknown}'}).status_code==400


@pytest.mark.parametrize('server_type,recipient',[('xui',11),('pasarguard',22)])
def test_simple_purchase_delivers_qr_specs_link_and_restart_for_both_providers(editor,monkeypatch,tmp_path,server_type,recipient):
    qr=tmp_path/'card.png';qr.write_bytes(b'mocked')
    make=Mock(return_value=str(qr));monkeypatch.setattr(presenter,'make_qr_card',make)
    from app.services import user_content
    monkeypatch.setattr(user_content,'background_bytes',AsyncMock(return_value=b'background'))
    bot=SimpleNamespace(send_photo=AsyncMock(),send_message=AsyncMock())
    asyncio.run(presenter.send_service_info(bot,recipient,'test_user','20GB service',20,30,LINK,server_type=server_type))
    assert make.call_args.args[0]==LINK and make.call_args.kwargs['background_bytes']==b'background'
    caption=bot.send_photo.await_args.kwargs['caption']
    assert LINK in plain_html(caption) and '20 گیگابایت' in caption and '30 روز' in caption and 'Happ' not in caption
    assert bot.send_photo.await_args.args[0]==recipient and bot.send_message.await_count==0
    keyboard=bot.send_photo.await_args.kwargs['reply_markup']
    assert keyboard.inline_keyboard[-1][0].callback_data=='restart:start'
    assert not qr.exists()


def test_templates_do_not_replace_trials_or_drop_openvpn_credentials(editor):
    assert asyncio.run(templates.selected_caption(is_test=True,**VALUES)) is None
    caption=templates.render_template('سلام {username}',**{**VALUES,'sub_link':None,'server_type':'mikrotik'},password='PW&1',l2tp_server='vpn.example',l2tp_ipsec_secret='secret')
    assert 'PW&1' in plain_html(caption) and 'vpn.example' in caption


@pytest.mark.asyncio
async def test_legacy_text_customization_cannot_rewrite_a_chosen_template(monkeypatch):
    from aiogram.methods import SendMessage
    rewrite=AsyncMock(return_value='old override');monkeypatch.setattr(custom_texts,'customize_text',rewrite)
    output=[]
    async def deliver(chat_id,text,**kwargs):
        method=await custom_texts.customize_method(SendMessage(chat_id=chat_id,text=text))
        output.append(method.text)
    bot=SimpleNamespace(send_message=deliver)
    chosen=templates.render_template('سلام {username}',**VALUES)
    await send_config_text(bot,11,chosen)
    assert output[-1]==chosen and rewrite.await_count==0 and not templates.FIXED_DELIVERY_TEXT.get()
    await send_config_text(bot,11,'legacy card')
    assert output[-1]=='old override' and rewrite.await_count==1
    # A failed send must not leak the template context into subsequent messages.
    bot.send_message=AsyncMock(side_effect=RuntimeError('offline'))
    with pytest.raises(RuntimeError):await send_config_text(bot,11,chosen)
    assert not templates.FIXED_DELIVERY_TEXT.get()


@pytest.mark.asyncio
async def test_long_custom_caption_keeps_qr_and_entire_link(monkeypatch):
    caption=templates.render_template('متن '*300+'\n{subscription_line}',**VALUES)
    bot=SimpleNamespace(send_photo=AsyncMock(),send_message=AsyncMock())
    await send_config_photo(bot,11,'mock-photo',caption,reply_markup=presenter.config_restart_keyboard())
    assert bot.send_photo.await_count==1 and bot.send_photo.await_args.kwargs['reply_markup'] is None
    assert LINK in plain_html(bot.send_message.await_args.args[1])
    assert bot.send_message.await_args.kwargs['reply_markup'].inline_keyboard[-1][0].callback_data=='restart:start'


def test_template_writes_require_admin_session_and_csrf(editor):
    c,_=editor
    assert c.post('/admin/api/v2/delivery-templates',data={'active':'simple','templates_json':'[]'},headers={'X-CSRF-Token':'wrong'}).status_code==403
    c.cookies.clear()
    assert c.get('/admin/api/v2/delivery-templates').status_code==401
    assert c.post('/admin/api/v2/delivery-templates',data={'active':'simple','templates_json':'[]'}).status_code==401
