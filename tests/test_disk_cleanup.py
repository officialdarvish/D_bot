import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from test_miniapp import client
from app.services import disk_cleanup as clean
from app.api import admin_web as web

@pytest.fixture
def artifacts(tmp_path,monkeypatch):
    monkeypatch.setattr(clean,'ARTIFACT_DIR',tmp_path/'disposable')
    return Path(clean.artifact_directory())


def test_cleanup_only_old_regular_allowlisted_files(artifacts,tmp_path,monkeypatch):
    with clean.temporary_artifact(suffix='.png',delete=False) as stream:
        stream.write(b'old thumbnail'); old=Path(stream.name)
    backup=tmp_path/'permanent.dbot';backup.write_bytes(b'permanent backup')
    key=tmp_path/'backup.key';key.write_bytes(b'private key')
    (artifacts/'dbot-artifact-key.key').write_bytes(b'key')
    (artifacts/'database.sqlite').write_bytes(b'database')
    (artifacts/'dbot-artifact-database.sqlite').write_bytes(b'database')
    (artifacts/'untracked.json').write_bytes(b'unknown')
    nested=artifacts/'dbot-artifact-folder.json';nested.mkdir();(nested/'file').write_bytes(b'nested')
    (artifacts/'dbot-artifact-link.json').symlink_to(backup)
    hard=artifacts/'dbot-artifact-hard.json';os.link(key,hard)
    clock=clean.time.time()+clean.RETENTION_SECONDS+60
    monkeypatch.setattr(clean.time,'time',lambda:clock)
    # A fresh artifact remains protected even while old files are eligible.
    recent=artifacts/'dbot-artifact-recent.json';recent.write_bytes(b'current')
    os.utime(recent,(clock,clock))
    preview=clean.cleanup_artifacts();assert preview['files']==1 and preview['bytes']==len(b'old thumbnail')
    assert old.exists()
    result=clean.cleanup_artifacts(delete=True)
    assert result['files']==1 and not old.exists()
    assert backup.read_bytes()==b'permanent backup' and key.read_bytes()==b'private key'
    assert recent.exists() and hard.exists() and nested.is_dir()
    assert clean.cleanup_artifacts(delete=True)['files']==0


def test_symlink_root_rejected(tmp_path,monkeypatch):
    target=tmp_path/'keys';target.mkdir();key=target/'dbot-artifact-secret.json';key.write_text('safe')
    link=tmp_path/'disposable';link.symlink_to(target,target_is_directory=True)
    monkeypatch.setattr(clean,'ARTIFACT_DIR',link)
    with pytest.raises(OSError):clean.cleanup_artifacts(delete=True)
    assert key.read_text()=='safe'


def test_shared_directory_helpers(artifacts):
    fd,path=clean.artifact_mkstemp(prefix='ignored',suffix='.pdf')
    os.close(fd)
    assert Path(path).parent==artifacts and Path(path).name.startswith('dbot-artifact-')
    assert Path(path).stat().st_mode&0o777==0o600


def test_cleanup_endpoint_database_snapshot_unchanged(client,artifacts,monkeypatch):
    _,sessions=client
    monkeypatch.setattr(web,'SessionLocal',sessions)
    async def snapshot():
        async with sessions() as session:
            return {table.name:[tuple(row) for row in (await session.execute(text('SELECT * FROM "'+table.name+'"'))).all()] for table in web.Base.metadata.sorted_tables}
    before=asyncio.run(snapshot())
    old=artifacts/'dbot-artifact-old.txt';old.write_bytes(b'temporary')
    clock=old.stat().st_ctime+clean.RETENTION_SECONDS+60
    monkeypatch.setattr(clean.time,'time',lambda:clock)
    statements=[]
    def record(conn,cursor,statement,params,context,many):statements.append(statement)
    event.listen(sessions.kw['bind'].sync_engine,'before_cursor_execute',record)
    app=FastAPI();app.include_router(web.router);app.dependency_overrides[web._auth_user]=lambda:'owner'
    with TestClient(app) as c:
        preview=c.get('/admin/api/v2/disk-cleanup');assert preview.json()['files']==1
        deleted=c.post('/admin/api/v2/disk-cleanup');assert deleted.json()['files']==1
        assert deleted.headers['cache-control']=='no-store'
    event.remove(sessions.kw['bind'].sync_engine,'before_cursor_execute',record)
    assert statements==[]
    assert asyncio.run(snapshot())==before


def test_cleanup_requires_authentication_and_csrf(artifacts,monkeypatch):
    app=FastAPI();app.include_router(web.router)
    with TestClient(app) as c:
        for method in [c.get,c.post]:
            response=method('/admin/api/v2/disk-cleanup',headers={'Accept':'application/json'})
            assert response.status_code==401
    # Exercise the actual auth dependency with a valid session but no CSRF.
    monkeypatch.setattr(web,'db_setting',AsyncMock(return_value=''))
    token='test-disk-cleanup-session'
    from datetime import timedelta
    monkeypatch.setitem(web._sessions,token,{'username':'owner','expires_at':web._now()+timedelta(hours=1),'credential_version':'','csrf':'valid-token'})
    with TestClient(app) as c:
        c.cookies.set('dbot_admin_token',token)
        response=c.post('/admin/api/v2/disk-cleanup',headers={'Accept':'application/json'})
        assert response.status_code==403
        response=c.post('/admin/api/v2/disk-cleanup',headers={'Accept':'application/json','X-CSRF-Token':'valid-token'})
        assert response.status_code==200
