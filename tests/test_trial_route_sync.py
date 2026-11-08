import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from test_miniapp_trial_video import trials, H, OTHER
from test_miniapp import client
from app.api import miniapp, miniapp_actions as actions
from app.bot.handlers.public import test_account as trial
from app.bot.keyboards import common
from app.database.models import ClientService


def test_bot_delivery_is_recovered_in_native_trial_route(trials, monkeypatch):
    c,sessions,values,calls,failed=trials
    monkeypatch.setattr(trial,'send_service_info',AsyncMock())
    monkeypatch.setattr(trial,'send_result_message',AsyncMock())
    bot=SimpleNamespace(send_message=AsyncMock())
    result=asyncio.run(trial.handle_test_account(SimpleNamespace(bot=bot),11,None))
    assert result is None  # Telegram path delivers a final message.
    data=c.get('/api/miniapp/trial',headers=H).json()
    assert data['used'] and not data['can_request'] and not data['can_repeat']
    assert data['operation'] is None and len(data['services'])==2
    assert all(s['source']=='trial' and s['source_label']=='اکانت تست' for s in data['services'])
    assert c.post('/api/miniapp/trial',headers=H,json={'key':str(uuid.uuid4())}).status_code==409
    trial.send_result_message.assert_awaited_once()
    assert 'به صفحه اصلی برگشتید' not in trial.send_result_message.call_args.args[1]
    # Delivery remains accessible when My Configs is hidden, including bot trials.
    monkeypatch.setattr(miniapp,'get_user_button',AsyncMock(side_effect=lambda k:('button',k!='my_services')))
    from app.services.xui_service import XuiService
    monkeypatch.setattr(XuiService,'resolve_service_subscription',AsyncMock(return_value='https://sub.example/test'))
    sid=data['services'][0]['id']
    assert c.get(f'/api/miniapp/services/{sid}/link',headers=H).status_code==200
    assert c.get(f'/api/miniapp/services/{sid}/link',headers=OTHER).status_code==403


def test_admin_can_repeat_completed_trials_without_replaying_previous_batch(trials,monkeypatch):
    c,sessions,values,calls,failed=trials
    monkeypatch.setattr(trial.settings,'ADMIN_IDS','11')
    first=c.post('/api/miniapp/trial',headers=H,json={'key':str(uuid.uuid4())}).json()
    asyncio.run(actions.process_operations())
    data=c.get('/api/miniapp/trial',headers=H).json()
    assert data['operation']['status']=='done'
    assert not data['used'] and data['can_request'] and data['can_repeat']
    second=c.post('/api/miniapp/trial',headers=H,json={'key':str(uuid.uuid4())}).json()
    assert second['id']!=first['id']
    assert not c.get('/api/miniapp/trial',headers=H).json()['can_request']
    asyncio.run(actions.process_operations())
    data=c.get('/api/miniapp/trial',headers=H).json()
    assert len(data['services'])==4 and len(calls)==4


@pytest.mark.parametrize('key',['test_account_button_visible','test_account_enabled','button_test_account_enabled'])
def test_disabled_controls_block_both_routes_and_menu(trials,monkeypatch,key):
    c,sessions,values,calls,failed=trials
    values[key]='0'
    async def button(name):return ('🧪 Custom trial',not(name=='test_account' and key=='button_test_account_enabled'))
    monkeypatch.setattr(miniapp,'get_user_button',button)
    monkeypatch.setattr(common,'get_user_button',button)
    assert not c.get('/api/miniapp/session',headers=H).json()['buttons']['test_account']
    assert c.post('/api/miniapp/trial',headers=H,json={'key':str(uuid.uuid4())}).status_code==403
    outcome=asyncio.run(trial.handle_test_account(SimpleNamespace(),11,None,native=True))
    assert not outcome['ok'] and not calls
    async def setting(k,d=''):return values.get(k,d)
    monkeypatch.setattr(common,'get_setting_value',setting)
    monkeypatch.setattr(common,'_load_button_settings',AsyncMock(return_value={common.button_enabled_key('test_account'):'0'} if key=='button_test_account_enabled' else {}))
    menu=asyncio.run(common.main_menu_inline())
    assert all(b.callback_data!=common.CB_TEST_ACCOUNT for row in menu.inline_keyboard for b in row)


@pytest.mark.parametrize('raw,expected',[('0',1),('-3',1),('bad',1),('2',2)])
def test_duration_and_custom_button_label_match(trials,monkeypatch,raw,expected):
    c,sessions,values,calls,failed=trials
    values['test_account_duration_days']=raw
    monkeypatch.setattr(miniapp,'get_user_button',AsyncMock(return_value=('تست ویژه',True)))
    assert c.get('/api/miniapp/session',headers=H).json()['button_labels']['test_account']=='تست ویژه'
    assert c.get('/api/miniapp/trial',headers=H).json()['duration_days']==expected
    c.post('/api/miniapp/trial',headers=H,json={'key':str(uuid.uuid4())})
    asyncio.run(actions.process_operations())
    data=c.get('/api/miniapp/trial',headers=H).json()
    assert data['operation']['status']=='done' and not data['can_request']


def test_trial_list_is_owned_visible_and_not_unrelated_services(trials):
    c,sessions,values,calls,failed=trials
    c.post('/api/miniapp/trial',headers=H,json={'key':str(uuid.uuid4())})
    asyncio.run(actions.process_operations())
    data=c.get('/api/miniapp/trial',headers=H).json()
    assert len(data['services'])==2
    assert c.get('/api/miniapp/trial',headers=OTHER).json()['services']==[]
    ids=[s['id'] for s in data['services']]
    async def hide():
        async with sessions() as s:
            svc=await s.get(ClientService,ids[0]);svc.hidden_from_owner=True
            await s.commit()
    asyncio.run(hide())
    refreshed=c.get('/api/miniapp/trial',headers=H).json()
    assert [s['id'] for s in refreshed['services']]==[ids[1]]
    assert [s['id'] for s in refreshed['operation']['result']['services']]==[ids[1]]
