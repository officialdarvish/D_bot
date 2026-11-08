"""Real authenticated containers and end-to-end web/bot restore boundaries."""
import asyncio
import base64
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.api import admin_web as web
from app.core.security import decrypt_text, encrypt_text
from app.database.base import Base
from app.database.models import User, Server
from app.services import encrypted_backup as crypto


def new_key():
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


@pytest.fixture
def key_store(tmp_path, monkeypatch):
    monkeypatch.setattr(crypto.settings, 'BACKUP_ENCRYPTION_KEY', '')
    monkeypatch.setattr(crypto.settings, 'BACKUP_ENCRYPTION_KEY_FILE', str(tmp_path/'private'/'backup.key'))
    return tmp_path/'private'/'backup.key'


def test_key_is_private_persistent_and_not_derived_from_bot_token(key_store, monkeypatch):
    first = crypto.installation_key()
    assert len(crypto.decode_key(first)) == 32
    assert key_store.stat().st_mode & 0o777 == 0o600
    monkeypatch.setattr(crypto.settings, 'BOT_TOKEN', 'another-token')
    assert crypto.installation_key() == first
    key_store.chmod(0o644)
    with pytest.raises(ValueError, match='chmod 600'):
        crypto.installation_key()


def test_parallel_processes_initialize_one_shared_key(key_store):
    from concurrent.futures import ProcessPoolExecutor
    with ProcessPoolExecutor(max_workers=4) as pool:
        values = list(pool.map(_read_key, range(12)))
    assert len(set(values)) == 1
    assert crypto.installation_key() == values[0]


def _read_key(_):
    return crypto.installation_key()


def test_configured_key_never_falls_back_if_invalid(key_store, monkeypatch):
    monkeypatch.setattr(crypto.settings, 'BACKUP_ENCRYPTION_KEY', 'bad-key')
    with pytest.raises(ValueError):
        crypto.encode_backup({'users': []})
    assert not key_store.exists()


def test_full_content_hidden_and_randomized_and_cross_install_recovery(key_store, monkeypatch):
    key = crypto.installation_key()
    data = {'meta': {'app': 'D BOT'}, 'users': [{'name': 'Private User'}], 'servers': [{'panel_url': 'https://private-server', 'password': 'secret_password'}]}
    a, b = crypto.encode_backup(data), crypto.encode_backup(data)
    assert a != b
    for secret in [b'Private User', b'private-server', b'secret_password', key.encode(), b'users', b'servers']:
        assert secret not in a
    assert crypto.decode_backup(a) == data
    monkeypatch.setattr(crypto.settings, 'BACKUP_ENCRYPTION_KEY', new_key())
    with pytest.raises(crypto.BackupKeyRequired):
        crypto.decode_backup(a)
    assert crypto.decode_backup(a, key=key) == data


@pytest.mark.parametrize('offset', [0, 7, 8, 9, 30, 50, -18, -1])
def test_modified_header_nonce_ciphertext_or_tag_rejected_without_plaintext(key_store, offset):
    raw = bytearray(crypto.encode_backup({'secret': 'never release me'}))
    raw[offset] ^= 1
    target = io.BytesIO()
    with pytest.raises(ValueError):
        crypto.decrypt_stream(io.BytesIO(raw), target)
    assert target.getvalue() == b''


@pytest.mark.parametrize('length', [0, 7, 20, 53, 60])
def test_truncated_files_rejected(key_store, length):
    raw = crypto.encode_backup({'hello': 'world'})
    with pytest.raises(ValueError):
        crypto.decode_backup(raw[:length])


def test_archive_streaming_and_wrong_content_rejected(key_store):
    data = os.urandom(3*crypto.CHUNK_SIZE+37)
    encrypted = io.BytesIO()
    crypto.encrypt_stream(io.BytesIO(data), encrypted, content=crypto.ARCHIVE_CONTENT)
    output = io.BytesIO()
    crypto.decrypt_stream(io.BytesIO(encrypted.getvalue()), output, content=crypto.ARCHIVE_CONTENT)
    assert output.getvalue() == data
    with pytest.raises(ValueError, match='archive'):
        crypto.decode_backup(encrypted.getvalue())


@pytest.fixture
def backup_client(tmp_path, monkeypatch, key_store):
    engine = create_async_engine('sqlite+aiosqlite:///'+str(tmp_path/'backup.db'))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async def seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with sessions() as session:
            session.add_all([User(id=1, telegram_id=123, full_name='Private Customer', wallet_balance=500), Server(id=1, name='Private Panel', server_type='xui', panel_url='https://private.example', username='owner', password_encrypted=encrypt_text('panel-secret'))])
            await session.commit()
    asyncio.run(seed())
    monkeypatch.setattr(web, 'SessionLocal', sessions)
    app = FastAPI()
    app.include_router(web.router)
    app.dependency_overrides[web._auth_user] = lambda: 'owner'
    with TestClient(app) as client:
        yield client, sessions, app
    asyncio.run(engine.dispose())


def test_web_download_restore_wrong_key_untouched_and_reencrypt_credentials(backup_client, monkeypatch, tmp_path):
    client, sessions, _ = backup_client
    response = client.get('/admin/backup/download')
    assert response.status_code == 200, response.text
    raw = response.content
    assert raw.startswith(crypto.MAGIC)
    assert 'dbot' in response.headers['content-disposition']
    assert response.headers['cache-control'] == 'no-store'
    key_response = client.get('/admin/backup/recovery-key')
    assert key_response.status_code == 200
    assert key_response.headers['cache-control'] == 'no-store'
    source_key = key_response.text.strip()
    assert source_key.encode() not in raw
    destination_box = Fernet(Fernet.generate_key())
    monkeypatch.setattr(crypto.settings, 'BACKUP_ENCRYPTION_KEY', new_key())
    monkeypatch.setattr(crypto.settings, 'BACKUP_ENCRYPTION_KEY_FILE', str(tmp_path/'destination'/'backup.key'))
    monkeypatch.setattr(web, 'encrypt_text', lambda value: destination_box.encrypt(value.encode()).decode())
    async def change():
        async with sessions() as s:
            (await s.get(User, 1)).full_name = 'Current Destination Data'
            await s.commit()
    async def current():
        async with sessions() as s:
            return (await s.get(User, 1)).full_name
    asyncio.run(change())
    headers = {'Accept': 'application/json'}
    files = {'file': ('backup.dbot', raw, 'application/octet-stream')}
    result = client.post('/admin/backup/restore', files=files, headers=headers)
    assert result.status_code == 409 and result.json()['code'] == 'backup_key_required'
    assert asyncio.run(current()) == 'Current Destination Data'
    result = client.post('/admin/backup/restore', files=files, data={'recovery_key': new_key()}, headers=headers)
    assert result.status_code == 409
    assert asyncio.run(current()) == 'Current Destination Data'
    broken = raw[:-1] + bytes([raw[-1] ^ 1])
    result = client.post('/admin/backup/restore', files={'file': ('backup.dbot', broken)}, data={'recovery_key': source_key}, headers=headers)
    assert result.status_code == 409
    assert asyncio.run(current()) == 'Current Destination Data'
    result = client.post('/admin/backup/restore', files=files, data={'recovery_key': source_key}, headers=headers)
    assert result.status_code == 200, result.text
    assert asyncio.run(current()) == 'Private Customer'
    async def credential():
        async with sessions() as s:
            return (await s.get(Server, 1)).password_encrypted
    assert destination_box.decrypt(asyncio.run(credential()).encode()) == b'panel-secret'


def test_legacy_json_still_restores_but_next_export_is_encrypted(backup_client):
    client, _, _ = backup_client
    legacy = asyncio.run(web._export_backup_payload())
    result = client.post('/admin/backup/restore', files={'file': ('legacy.json', json.dumps(legacy))}, headers={'Accept': 'application/json'})
    assert result.status_code == 200, result.text
    assert client.get('/admin/backup/download').content.startswith(crypto.MAGIC)


def test_export_requires_authentication(backup_client):
    client, _, app = backup_client
    app.dependency_overrides.clear()
    assert client.get('/admin/backup/download', follow_redirects=False).status_code in (401, 403, 303, 307)
    assert client.get('/admin/backup/recovery-key', follow_redirects=False).status_code in (401, 403, 303, 307)


@pytest.mark.asyncio
async def test_bot_restore_uses_same_container_and_requests_source_key(backup_client, monkeypatch, tmp_path):
    from app.bot.handlers.admin import settings as handler
    from app.bot.states.admin_states import RestoreBackup
    from aiogram.fsm.context import FSMContext
    from aiogram.fsm.storage.memory import MemoryStorage
    from aiogram.fsm.storage.base import StorageKey
    raw = crypto.encode_backup(await web._export_backup_payload())
    source_key = crypto.installation_key()
    monkeypatch.setattr(crypto.settings, 'BACKUP_ENCRYPTION_KEY', new_key())
    monkeypatch.setattr(crypto.settings, 'BACKUP_ENCRYPTION_KEY_FILE', str(tmp_path/'destination'/'backup.key'))
    monkeypatch.setattr(handler, 'admin', lambda _: True)
    monkeypatch.setattr(handler, 'ui_message', AsyncMock())
    monkeypatch.setattr(handler, 'main_menu_inline', AsyncMock(return_value=None))
    importer = AsyncMock(return_value={'users': 1})
    monkeypatch.setattr(web, '_restore_backup_payload', importer)
    async def download(_, path):
        Path(path).write_bytes(raw)
    message = SimpleNamespace(from_user=SimpleNamespace(id=123), document=SimpleNamespace(file_name='backup.dbot', file_size=len(raw), file_id='file'), bot=SimpleNamespace(get_file=AsyncMock(return_value=SimpleNamespace(file_path='remote')), download_file=download))
    storage = MemoryStorage()
    state = FSMContext(storage, StorageKey(bot_id=1, chat_id=123, user_id=123))
    await handler.restore_backup_file(message, state)
    assert await state.get_state() == RestoreBackup.recovery_key.state
    importer.assert_not_awaited()
    assert source_key not in json.dumps(await state.get_data())
    path = (await state.get_data())['legacy_backup_path']
    assert Path(path).read_bytes().startswith(crypto.MAGIC)
    key_message = SimpleNamespace(from_user=message.from_user, text=new_key(), delete=AsyncMock())
    await handler.restore_backup_legacy_secret(key_message, state)
    importer.assert_not_awaited()
    assert Path(path).exists()
    key_message.text = source_key
    await handler.restore_backup_legacy_secret(key_message, state)
    importer.assert_awaited_once()
    assert await state.get_state() is None and not Path(path).exists()
    await storage.close()


@pytest.mark.asyncio
async def test_main_bot_exports_real_encrypted_file_and_removes_temporary_file(backup_client, monkeypatch):
    from app.bot.handlers.admin import settings as handler
    monkeypatch.setattr(handler, 'admin', lambda _: True)
    monkeypatch.setattr(handler, 'handle_user_facing_error', AsyncMock())
    monkeypatch.setattr(handler, 'ui_callback_message', AsyncMock())
    monkeypatch.setattr(handler, 'main_menu_inline', AsyncMock(return_value=None))
    monkeypatch.setattr(handler, 'get_setting_value', AsyncMock(return_value='Welcome'))
    captured = []
    async def document(upload, **kwargs):
        if upload.filename == 'dbot-recovery-keys.json':
            assert crypto.bundle_keys(upload.data.decode())
            return
        captured.append((Path(upload.path), Path(upload.path).read_bytes(), upload.filename))
    callback = SimpleNamespace(from_user=SimpleNamespace(id=123), message=SimpleNamespace(answer_document=document), answer=AsyncMock())
    await handler.backup_send(callback)
    assert len(captured) == 1
    path, raw, name = captured[0]
    assert name.endswith('.dbot') and raw.startswith(crypto.MAGIC)
    assert crypto.decode_backup(raw)['users'][0]['full_name'] == 'Private Customer'
    assert not path.exists()


@pytest.mark.parametrize('mode', ['private', 'normal', 'aes'])
def test_cli_archive_encrypts_database_env_and_project_without_bundled_key(tmp_path, monkeypatch, mode):
    import subprocess
    import tarfile
    root = Path(__file__).resolve().parents[1]
    application, bins = tmp_path/'application', tmp_path/'bin'
    application.mkdir(); bins.mkdir()
    key = new_key()
    database_url='sqlite+aiosqlite:///'+str(tmp_path/'cli.db')
    async def seed_cli():
        engine=create_async_engine(database_url)
        async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
        if mode != 'private':
            from app.database.models import Setting
            async with async_sessionmaker(engine)() as session:
                session.add(Setting(key='backup_protection_mode',value=mode))
                if mode=='aes':session.add(Setting(key='backup_aes_password_encrypted',value=encrypt_text('Password for archive AES!')))
                await session.commit()
        await engine.dispose()
    asyncio.run(seed_cli())
    (application/'.env').write_text(f'BOT_TOKEN=123456:TEST_ONLY\nDATABASE_URL={database_url}\nBACKUP_ENCRYPTION_KEY={key}\nBACKUP_ENCRYPTION_KEY_FILE={tmp_path/'private'/'backup.key'}\nPOSTGRES_USER=dbot\n')
    (application/'code.py').write_text('print("demo")\n')
    docker = bins/'docker'
    # The actual control script, actual Python CLI and actual crypto run. Only
    # Docker transport/Postgres are replaced because tests need no daemon.
    docker.write_text('''#!/usr/bin/env python3
import os, sys
from pathlib import Path
args = sys.argv[1:]
if args == ['compose', 'version']: sys.exit(0)
if args[:4] == ['compose', 'exec', '-T', 'db']:
    print('-- private SQL dump'); sys.exit(0)
if args[:4] == ['compose', 'exec', '-T', 'api']:
    os.execv(sys.executable, [sys.executable, os.environ['TEST_BACKUP_CLI'], *args[6:]])
sys.exit(1)
''')
    docker.chmod(0o755)
    env = {**os.environ, 'PATH': str(bins)+os.pathsep+os.environ['PATH'], 'DBOT_APP_DIR': str(application), 'TEST_BACKUP_CLI': str(root/'scripts/backup_crypto_cli.py'), 'DATABASE_URL': database_url}
    result = subprocess.run(['bash', str(root/'scripts/dbot-control.sh'), 'backup'], env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    files = list((application/'backups').iterdir())
    if mode=='private':
        assert len(files)==2
        assert crypto.bundle_keys(next(p for p in files if p.suffix=='.json').read_text())
        files=[p for p in files if p.suffix=='.dbot']
    assert len(files)==1
    assert files[0].name.endswith('.tar.gz' if mode=='normal' else '.dbot')
    assert files[0].stat().st_mode & 0o777 == 0o600
    raw = files[0].read_bytes()
    assert key.encode() not in raw
    restored = io.BytesIO(raw if mode=='normal' else b'')
    if mode!='normal':
        assert b'private SQL dump' not in raw
        crypto.decrypt_stream(io.BytesIO(raw), restored, content=crypto.ARCHIVE_CONTENT,
            key=key if mode=='private' else '',password='Password for archive AES!' if mode=='aes' else '')
    with tarfile.open(fileobj=io.BytesIO(restored.getvalue())) as archive:
        assert b'private SQL dump' in archive.extractfile('./database.sql').read()
        assert key.encode() not in archive.extractfile('./.env.backup').read()
        project = archive.extractfile('./project-files.tar.gz').read()
    with tarfile.open(fileobj=io.BytesIO(project)) as archive:
        assert './code.py' in archive.getnames()
        assert './.env' not in archive.getnames()
    # The shipped CLI can recover the same encrypted archive. Normal archives
    # are opened directly with tar and need no cryptography CLI.
    if mode=='normal':return
    saved_key = tmp_path/'key.txt'
    saved_key.write_text(key if mode=='private' else 'Password for archive AES!')
    flag='--key-file' if mode=='private' else '--password-file'
    result = subprocess.run(['python3', str(root/'scripts/backup_crypto_cli.py'), 'decrypt', flag, str(saved_key)], input=raw, capture_output=True, env=env)
    assert result.returncode == 0 and result.stdout == restored.getvalue()
    saved_key.write_text(new_key())
    result = subprocess.run(['python3', str(root/'scripts/backup_crypto_cli.py'), 'decrypt', flag, str(saved_key)], input=raw, capture_output=True, env=env)
    assert result.returncode != 0 and result.stdout == b''
