import asyncio
import io
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from test_encrypted_backup import backup_client, key_store, new_key
from app.api import admin_web as web
from app.database.models import Setting, User, Server
from app.services import encrypted_backup as crypto
from app.services.backup_config import BACKUP_AES_PASSWORD_KEY
from app.core import security

PASSWORD = 'A strong backup password 2026!'
HEADERS = {'Accept':'application/json'}


def save_values(**values):
    asyncio.run(web._save_settings_map(values))


def test_all_three_modes_roundtrip_and_password_not_exported(backup_client, monkeypatch):
    client, _, _ = backup_client
    sender=AsyncMock(return_value={'ok':True})
    monkeypatch.setattr(web,'_telegram_send_recovery_keys',sender)
    save_values(backup_destination='bot',backup_chat_id='123')
    normal=client.post('/admin/backup/protection',data={'mode':'normal'},headers=HEADERS)
    assert normal.status_code==200,normal.text
    raw=client.get('/admin/backup/download')
    assert raw.json()['users'][0]['full_name']=='Private Customer'
    assert '.json' in raw.headers['content-disposition']
    sender.assert_not_awaited()
    result=client.post('/admin/backup/protection',data={'mode':'aes','aes_password':PASSWORD,'aes_password_confirm':PASSWORD},headers=HEADERS)
    assert result.status_code==200,result.text
    settings=client.get('/admin/api/v2/backup/settings').json()['settings']
    assert settings['backup_protection_mode']=='aes' and settings['backup_aes_password_configured']=='1'
    assert PASSWORD not in json.dumps(settings) and BACKUP_AES_PASSWORD_KEY not in settings
    raw=client.get('/admin/backup/download').content
    assert raw.startswith(crypto.MAGIC+bytes([crypto.PASSWORD_VERSION]))
    assert PASSWORD.encode() not in raw
    decoded=crypto.decode_backup(raw,password=PASSWORD)
    assert all(row['key'] not in (BACKUP_AES_PASSWORD_KEY,'backup_protection_mode') for row in decoded['settings'])
    sender.assert_not_awaited()
    # Backup key and bot-token changes cannot prevent AES password recovery.
    monkeypatch.setattr(crypto.settings,'BACKUP_ENCRYPTION_KEY',new_key())
    assert crypto.decode_backup(raw,password=PASSWORD)['users'][0]['telegram_id']==123
    result=client.post('/admin/backup/protection',data={'mode':'private'},headers=HEADERS)
    assert result.status_code==200,result.text
    sender.assert_awaited_once()
    raw=client.get('/admin/backup/download').content
    assert raw.startswith(crypto.MAGIC+bytes([crypto.VERSION]))
    assert sender.await_count==2
    document=sender.await_args.kwargs['document']
    bundle=json.loads(document)
    assert bundle['backup_name'].endswith('.dbot') and len(bundle['backup_sha256'])==64
    assert crypto.decode_backup(raw,key=document.decode())['servers'][0]['name']=='Private Panel'


@pytest.mark.parametrize('password,confirm',[('short','short'),(PASSWORD,'different')])
def test_bad_aes_settings_rejected_without_overwriting_mode(backup_client,password,confirm):
    client,_,_=backup_client
    save_values(backup_protection_mode='normal')
    response=client.post('/admin/backup/protection',data={'mode':'aes','aes_password':password,'aes_password_confirm':confirm},headers=HEADERS)
    assert response.status_code==400
    assert asyncio.run(web._settings_map())['backup_protection_mode']=='normal'


def test_no_aes_password_and_failed_key_delivery_fail_closed(backup_client,monkeypatch):
    client,_,_=backup_client
    save_values(backup_protection_mode='normal',backup_destination='bot',backup_chat_id='123')
    assert client.post('/admin/backup/protection',data={'mode':'aes'},headers=HEADERS).status_code==400
    monkeypatch.setattr(web,'_telegram_send_recovery_keys',AsyncMock(return_value={'ok':False}))
    assert client.post('/admin/backup/protection',data={'mode':'private'},headers=HEADERS).status_code==400
    assert asyncio.run(web._settings_map())['backup_protection_mode']=='normal'
    assert client.post('/admin/backup/protection',data={'mode':'bogus'},headers=HEADERS).status_code==400


def test_aes_restore_survives_complete_source_loss_and_preserves_target_protection(backup_client,monkeypatch,tmp_path):
    client,sessions,_=backup_client
    assert client.post('/admin/backup/protection',data={'mode':'aes','aes_password':PASSWORD,'aes_password_confirm':PASSWORD},headers=HEADERS).status_code==200
    raw=client.get('/admin/backup/download').content
    # Simulate a new installation with different infrastructure keys, existing
    # destination data, and its own unrelated AES password.
    monkeypatch.setattr(security,'fernet',Fernet(Fernet.generate_key()))
    monkeypatch.setattr(crypto.settings,'BACKUP_ENCRYPTION_KEY_FILE',str(tmp_path/'new-vps'/'backup.key'))
    target_password='Destination password stays private!'
    save_values(backup_protection_mode='aes',**{BACKUP_AES_PASSWORD_KEY:security.encrypt_text(target_password)})
    async def change():
        async with sessions() as session:
            (await session.get(User,1)).full_name='Destination Customer'
            await session.commit()
    async def name():
        async with sessions() as session:return (await session.get(User,1)).full_name
    asyncio.run(change())
    file={'file':('source.dbot',raw)}
    for values in [{},{'aes_password':'Wrong password 123!'}]:
        result=client.post('/admin/backup/restore',files=file,data=values,headers=HEADERS)
        assert result.status_code==409 and result.json()['code']=='backup_password_required'
        assert asyncio.run(name())=='Destination Customer'
    broken=raw[:-1]+bytes([raw[-1]^1])
    result=client.post('/admin/backup/restore',files={'file':('source.dbot',broken)},data={'aes_password':PASSWORD},headers=HEADERS)
    assert result.status_code==409 and asyncio.run(name())=='Destination Customer'
    result=client.post('/admin/backup/restore',files=file,data={'aes_password':PASSWORD},headers=HEADERS)
    assert result.status_code==200,result.text
    assert asyncio.run(name())=='Private Customer'
    values=asyncio.run(web._settings_map())
    assert security.decrypt_text(values[BACKUP_AES_PASSWORD_KEY])==target_password
    async def credential():
        async with sessions() as session:return (await session.get(Server,1)).password_encrypted
    assert security.decrypt_text(asyncio.run(credential()))=='panel-secret'


def test_key_list_keeps_previous_keys_and_imports_offline(key_store,monkeypatch,tmp_path):
    first=crypto.installation_key();crypto.recovery_keys()
    raw=crypto.encode_backup({'meta':{'app':'D BOT'},'value':'old-data'})
    second=new_key();monkeypatch.setattr(crypto.settings,'BACKUP_ENCRYPTION_KEY',second)
    bundle=crypto.recovery_bundle().decode()
    assert set(crypto.bundle_keys(bundle))=={first,second}
    assert crypto.decode_backup(raw)['value']=='old-data'  # local key history
    monkeypatch.setattr(crypto.settings,'BACKUP_ENCRYPTION_KEY_FILE',str(tmp_path/'clean'/'backup.key'))
    with pytest.raises(crypto.BackupKeyRequired):crypto.decode_backup(raw)
    assert crypto.decode_backup(raw,key=bundle)['value']=='old-data'
    malformed=json.loads(bundle);malformed['keys'][0]['id']='changed'
    with pytest.raises(ValueError):crypto.bundle_keys(malformed)


@pytest.mark.parametrize('offset',[7,8,12,35,51,-18,-1])
def test_aes_tampering_never_releases_plaintext(key_store,offset):
    raw=bytearray(crypto.encode_backup({'private':'data'},password=PASSWORD));raw[offset]^=1
    target=io.BytesIO()
    with pytest.raises(ValueError):crypto.decrypt_stream(io.BytesIO(raw),target,password=PASSWORD)
    assert target.getvalue()==b''


@pytest.mark.asyncio
async def test_shared_sender_delivers_complete_key_list_then_backup_and_reports_key_failure(backup_client,monkeypatch):
    path=await web._write_backup_file()
    requests=[];ok=True
    def transport(request):
        requests.append(request.content)
        return httpx.Response(200,json={'ok':ok,'description':'delivery rejected' if not ok else 'sent'})
    original=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(transport),**kw))
    try:
        result=await web._telegram_send_backup('fake-token','123',path,'bot',filename='backup.dbot')
        assert result['ok'] and len(requests)==2
        assert b'dbot-recovery-keys.json' in requests[0]
        assert crypto.installation_key().encode() in requests[0]
        assert b'backup.dbot' in requests[1] and crypto.MAGIC in requests[1]
        requests.clear();ok=False
        result=await web._telegram_send_backup('fake-token','123',path,'bot',filename='backup.dbot')
        assert not result['ok'] and len(requests)==1
        assert 'Recovery key delivery failed' in result['message']
    finally:Path(path).unlink()


@pytest.mark.asyncio
async def test_aes_archive_uses_password_with_no_installation_key(key_store,monkeypatch):
    payload=os.urandom(100000)
    encrypted=io.BytesIO();crypto.encrypt_stream(io.BytesIO(payload),encrypted,content=crypto.ARCHIVE_CONTENT,password=PASSWORD)
    monkeypatch.setattr(crypto,'installation_key',lambda:(_ for _ in ()).throw(AssertionError('must not access old key')))
    output=io.BytesIO();crypto.decrypt_stream(io.BytesIO(encrypted.getvalue()),output,content=crypto.ARCHIVE_CONTENT,password=PASSWORD)
    assert output.getvalue()==payload


@pytest.mark.asyncio
@pytest.mark.parametrize('mode',['normal','aes'])
async def test_scheduled_backup_uses_saved_mode_and_matching_filename(backup_client,monkeypatch,mode):
    from app.jobs.backup_delivery import deliver_scheduled_backup
    await web._save_settings_map({'backup_protection_mode':mode,'backup_destination':'bot','backup_chat_id':'123',
        'backup_schedule_enabled':'1','backup_schedule_anchor_at':'2020-01-01T00:00:00+00:00',
        BACKUP_AES_PASSWORD_KEY:security.encrypt_text(PASSWORD)})
    monkeypatch.setattr(web,'_telegram_token',AsyncMock(return_value='fake'))
    sent=[]
    async def sender(token,target,path,destination,**kwargs):
        raw=Path(path).read_bytes();sent.append((raw,kwargs['filename'],Path(path)))
        return {'ok':True,'message':'sent'}
    monkeypatch.setattr(web,'_telegram_send_backup',sender)
    await deliver_scheduled_backup()
    assert len(sent)==1
    raw,name,path=sent[0]
    assert name.endswith('.json' if mode=='normal' else '.dbot')
    assert crypto.decode_backup(raw,password=PASSWORD if mode=='aes' else '')['users'][0]['full_name']=='Private Customer'
    assert not path.exists()


@pytest.mark.asyncio
async def test_bot_aes_restore_prompts_password_and_never_persists_it(backup_client,monkeypatch):
    from app.bot.handlers.admin import settings as handler
    from app.bot.states.admin_states import RestoreBackup
    from aiogram.fsm.context import FSMContext
    from aiogram.fsm.storage.memory import MemoryStorage
    from aiogram.fsm.storage.base import StorageKey
    from types import SimpleNamespace
    raw=crypto.encode_backup(await web._export_backup_payload(),password=PASSWORD)
    monkeypatch.setattr(handler,'admin',lambda _:True)
    monkeypatch.setattr(handler,'ui_message',AsyncMock())
    monkeypatch.setattr(handler,'main_menu_inline',AsyncMock(return_value=None))
    monkeypatch.setattr(handler,'handle_user_facing_error',AsyncMock())
    importer=AsyncMock(return_value={'users':1});monkeypatch.setattr(web,'_restore_backup_payload',importer)
    async def download(_,path):Path(path).write_bytes(raw)
    message=SimpleNamespace(from_user=SimpleNamespace(id=123),document=SimpleNamespace(file_name='backup.dbot',file_size=len(raw),file_id='backup'),
        bot=SimpleNamespace(get_file=AsyncMock(return_value=SimpleNamespace(file_path='remote')),download_file=download))
    storage=MemoryStorage();state=FSMContext(storage,StorageKey(bot_id=1,chat_id=123,user_id=123))
    await handler.restore_backup_file(message,state)
    assert await state.get_state()==RestoreBackup.recovery_key.state
    assert (await state.get_data())['aes_backup'] is True
    path=Path((await state.get_data())['legacy_backup_path'])
    key_message=SimpleNamespace(from_user=message.from_user,text='Incorrect password!',delete=AsyncMock())
    await handler.restore_backup_legacy_secret(key_message,state)
    importer.assert_not_awaited();assert path.exists()
    assert 'Incorrect password!' not in json.dumps(await state.get_data())
    key_message.text=PASSWORD
    await handler.restore_backup_legacy_secret(key_message,state)
    importer.assert_awaited_once();assert not path.exists() and await state.get_state() is None
    assert PASSWORD not in json.dumps(await state.get_data())
    await storage.close()


@pytest.mark.asyncio
async def test_secondary_bot_sends_key_list_and_database_backup(backup_client,monkeypatch):
    from app.bot import backup_bot as secondary
    from types import SimpleNamespace
    monkeypatch.setattr(secondary,'_owner',lambda _:True)
    monkeypatch.setattr(secondary,'set_setting_value',AsyncMock())
    sent=[]
    async def send(chat,upload,**kwargs):
        raw=upload.data if hasattr(upload,'data') else Path(upload.path).read_bytes()
        sent.append((upload.filename,raw))
    callback=SimpleNamespace(from_user=SimpleNamespace(id=123),answer=AsyncMock(),bot=SimpleNamespace(send_document=send),message=SimpleNamespace(answer=AsyncMock()))
    router=secondary.build_backup_router()
    action=next(h.callback for h in router.callback_query.handlers if h.callback.__name__=='backup_now')
    await action(callback)
    assert len(sent)==2
    assert sent[0][0]=='dbot-recovery-keys.json'
    assert sent[1][0].endswith('.dbot')
    assert crypto.decode_backup(sent[1][1],key=sent[0][1].decode())['users'][0]['full_name']=='Private Customer'


@pytest.mark.asyncio
async def test_bot_accepts_key_list_document_for_restore(backup_client,monkeypatch,tmp_path):
    from app.bot.handlers.admin import settings as handler
    from app.bot.states.admin_states import RestoreBackup
    from aiogram.fsm.context import FSMContext
    from aiogram.fsm.storage.memory import MemoryStorage
    from aiogram.fsm.storage.base import StorageKey
    from types import SimpleNamespace
    raw=crypto.encode_backup(await web._export_backup_payload())
    bundle=crypto.recovery_bundle()
    path=tmp_path/'pending.dbot';path.write_bytes(raw)
    monkeypatch.setattr(handler,'admin',lambda _:True)
    monkeypatch.setattr(handler,'ui_message',AsyncMock())
    monkeypatch.setattr(handler,'main_menu_inline',AsyncMock(return_value=None))
    importer=AsyncMock(return_value={'users':1});monkeypatch.setattr(web,'_restore_backup_payload',importer)
    async def download(_,target):target.write(bundle)
    message=SimpleNamespace(from_user=SimpleNamespace(id=123),document=SimpleNamespace(file_size=len(bundle),file_id='key-file'),
        delete=AsyncMock(),bot=SimpleNamespace(get_file=AsyncMock(return_value=SimpleNamespace(file_path='remote')),download_file=download))
    storage=MemoryStorage();state=FSMContext(storage,StorageKey(bot_id=1,chat_id=123,user_id=123))
    await state.set_state(RestoreBackup.recovery_key)
    await state.update_data(legacy_backup_path=str(path),encrypted_backup=True,aes_backup=False)
    monkeypatch.setattr(crypto,'installation_key',lambda:(_ for _ in ()).throw(AssertionError('must use uploaded bundle')))
    await handler.restore_backup_key_file(message,state)
    importer.assert_awaited_once();message.delete.assert_awaited_once()
    assert await state.get_state() is None and not path.exists()
    await storage.close()
