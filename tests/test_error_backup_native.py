import asyncio,logging
from pathlib import Path
from unittest.mock import AsyncMock
from app.services import error_backup


def test_error_backup_uses_backup_destination_and_redacts_secrets(monkeypatch):
 from app.api import admin_web
 from app.core.config import settings
 monkeypatch.setattr(settings,'BOT_TOKEN','123:PRIVATE_TOKEN')
 monkeypatch.setattr(admin_web,'_settings_map',AsyncMock(return_value={'backup_destination':'channel','backup_chat_id':'-100123'}))
 monkeypatch.setattr(admin_web,'_telegram_token',AsyncMock(return_value='backup-token'))
 monkeypatch.setattr(admin_web,'_effective_backup_chat_id',lambda *a:'-100123')
 seen=[]
 async def send(token,target,path,destination,**kwargs):
  seen.append((token,target,destination,Path(path).read_text(),kwargs));return {'ok':True}
 monkeypatch.setattr(admin_web,'_telegram_send_backup',send)
 asyncio.run(error_backup.send_error_log('RuntimeError: fail\nhttps://private.example/secret\nbot=123:PRIVATE_TOKEN password=secret'))
 assert len(seen)==1
 assert seen[0][:3]==('backup-token','-100123','channel')
 assert 'RuntimeError' in seen[0][3]
 assert 'PRIVATE_TOKEN' not in seen[0][3] and 'secret' not in seen[0][3] and 'private.example' not in seen[0][3]
 assert seen[0][4]['filename']=='dbot-error-log.txt'


def test_runtime_error_handler_captures_traceback_without_recursive_reports(monkeypatch):
 seen=[]
 async def send(text):
  seen.append(text)
  token=error_backup._delivering.set(True)
  try:logging.getLogger('native-test').error('reporting itself failed')
  finally:error_backup._delivering.reset(token)
 monkeypatch.setattr(error_backup,'send_error_log',send)
 root=logging.getLogger();handler=error_backup.ErrorBackupHandler();root.addHandler(handler)
 async def run():
  try:raise ValueError('native-unique-failure')
  except ValueError:logging.getLogger('native-test').exception('native workflow failed')
  await asyncio.gather(*list(error_backup._tasks))
 try:asyncio.run(run())
 finally:root.removeHandler(handler)
 assert len(seen)==1 and 'ValueError: native-unique-failure' in seen[0] and 'Traceback' in seen[0]
