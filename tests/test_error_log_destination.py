import asyncio
from pathlib import Path
from unittest.mock import AsyncMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from cryptography.fernet import Fernet
from app.api import admin_web
from app.services import error_backup
from app.services.backup_config import ERROR_LOG_BOT_TOKEN_KEY,encrypt_secondary_bot_token,decrypt_secondary_bot_token
from app.core.config import settings

@pytest.fixture
def routing(monkeypatch):
 monkeypatch.setattr(settings,'FERNET_KEY',Fernet.generate_key().decode())
 monkeypatch.setattr(settings,'BOT_TOKEN','123456:MAIN_TOKEN_FOR_TESTING_123456789')
 current={};writes=[]
 monkeypatch.setattr(admin_web,'_settings_map',AsyncMock(side_effect=lambda:dict(current)))
 async def save(v):writes.append(v);current.update(v)
 monkeypatch.setattr(admin_web,'_save_settings_map',save)
 validate=AsyncMock(return_value={'ok':True,'chat_id':'-100456','admin_ok':True})
 monkeypatch.setattr(admin_web,'_telegram_validate_destination',validate)
 app=FastAPI();app.include_router(admin_web.router);app.dependency_overrides[admin_web._auth_user]=lambda:'admin'
 with TestClient(app) as c:yield c,current,writes,validate


def test_save_encrypts_token_test_does_not_change_routing_and_get_masks_secret(routing):
 c,current,writes,validate=routing
 token='987654:SECONDARY_TOKEN_FOR_TESTING_12345'
 data=dict(mode='separate',destination='channel',chat_id='@logs',sender_mode='secondary',bot_token=token)
 headers={'Accept':'application/json'}
 r=c.post('/admin/backup/error-logs/test',data=data,headers=headers)
 assert r.status_code==200,r.text
 assert not writes and validate.call_args.kwargs['send_test'] is True
 r=c.post('/admin/backup/error-logs/save',data=data,headers=headers)
 assert r.status_code==200,r.text
 assert validate.call_args.kwargs['send_test'] is False
 assert current['error_log_chat_id']=='-100456'
 assert current[ERROR_LOG_BOT_TOKEN_KEY]!=token
 assert decrypt_secondary_bot_token(current[ERROR_LOG_BOT_TOKEN_KEY])==token
 r=c.get('/admin/api/v2/error-logs/settings')
 assert r.json()['ok']
 assert r.json()['settings']['token_configured'] and token not in r.text and current[ERROR_LOG_BOT_TOKEN_KEY] not in r.text
 data['bot_token']=''
 assert c.post('/admin/backup/error-logs/save',data=data,headers=headers).status_code==200
 assert validate.call_args.args[0]==token
 assert c.post('/admin/backup/error-logs/save',data={**data,'chat_id':''},headers=headers).status_code==400
 assert c.post('/admin/backup/error-logs/save',data={'mode':'off'},headers=headers).status_code==200
 assert current['error_log_mode']=='off'


def test_dedicated_logs_use_separate_sender_and_never_fall_back_to_backup(routing,monkeypatch):
 c,current,_,_=routing
 secret='987654:SECONDARY_TOKEN_FOR_TESTING_12345'
 current.update(error_log_mode='separate',error_log_destination='group',error_log_chat_id='-100456',error_log_sender_mode='secondary',backup_chat_id='-100999')
 current[ERROR_LOG_BOT_TOKEN_KEY]=encrypt_secondary_bot_token(secret)
 seen=[]
 async def send(token,target,path,destination,**kwargs):
  assert error_backup._delivering.get()
  seen.append((token,target,destination,Path(path).read_text(),path));return {'ok':True}
 monkeypatch.setattr(admin_web,'_telegram_send_backup',send)
 asyncio.run(error_backup.send_error_log('Error sender '+secret+' https://panel.example/private password=hidden'))
 assert seen[0][:3]==(secret,'-100456','group')
 assert secret not in seen[0][3] and 'hidden' not in seen[0][3] and 'panel.example' not in seen[0][3]
 assert not Path(seen[0][4]).exists() and not error_backup._delivering.get()
 current['error_log_chat_id']=''
 asyncio.run(error_backup.send_error_log('No destination'))
 assert len(seen)==1
 current['error_log_chat_id']='-100456';current['error_log_mode']='off'
 asyncio.run(error_backup.send_error_log('Disabled'))
 assert len(seen)==1


def test_dedicated_token_is_part_of_portable_backup_credentials():
 source=Path('app/api/admin_web.py').read_text()
 assert source.count('{WEB_ADMIN_PASSWORD_SECRET_KEY, BACKUP_SECONDARY_BOT_TOKEN_KEY, ERROR_LOG_BOT_TOKEN_KEY}')==2
