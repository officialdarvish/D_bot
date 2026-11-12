"""Exercise panel confirmation through the shared queue and host command runner."""
import asyncio
import importlib.util
import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.services import web_update
from app.api import admin_web as web

SHA='a'*40
PREVIOUS='b'*40


def worker_at(app):
    spec=importlib.util.spec_from_file_location('dbot_test_update_worker',Path('scripts/web-update-worker.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.configure(app)
    return module


def test_confirm_endpoint_queue_and_host_build_restart_complete(tmp_path,monkeypatch):
    worker=worker_at(tmp_path)
    monkeypatch.setattr(web_update,'QUEUE',worker.QUEUE)
    (worker.QUEUE/'ready').touch()
    monkeypatch.setattr(web_update,'check',AsyncMock(return_value={'ok':True,'host_ready':True,'available':True,'commit':SHA,'latest':{'version':'1.4.0','build':3}}))
    app=FastAPI();app.include_router(web.router)
    with TestClient(app) as c:
        assert c.post('/admin/update/start',data={'commit':SHA},headers={'X-Requested-With':'fetch'}).status_code==401
        app.dependency_overrides[web._auth_user]=lambda:'owner'
        response=c.post('/admin/update/start',data={'commit':SHA})
        assert response.status_code==200,response.text
        job=response.json()['job'];assert job['state']=='queued'
        assert c.get('/admin/api/v2/update').json()['job']=={'id':job['id'],'state':'queued'}
        assert c.post('/admin/update/start',data={'commit':SHA}).status_code==409
        assert stat.S_IMODE((worker.QUEUE/'request.json').stat().st_mode)==0o600
        calls=[]
        def run(args,**kwargs):
            calls.append(args)
            if args[:3]==['git','rev-parse','FETCH_HEAD']:return SimpleNamespace(stdout=SHA)
            if args[:2]==['git','show']:return SimpleNamespace(stdout=json.dumps({'schema':1,'channel':'main','build':3,'version':'1.4.0'}))
            if args[:3]==['git','rev-parse','HEAD']:return SimpleNamespace(stdout=PREVIOUS)
            if args[:2]==['git','status']:return SimpleNamespace(stdout='')
            if args[:4]==['docker','compose','exec','-T']:kwargs['stdout'].write(b'-- database backup\n')
            return SimpleNamespace(stdout='')
        monkeypatch.setattr(worker,'run',run);monkeypatch.setattr(worker,'healthy',lambda:True)
        worker.process_update()
        state=c.get('/admin/api/v2/update').json()['job']
        assert state['id']==job['id'] and state['state']=='completed'
        assert not (worker.QUEUE/'request.json').exists()
        assert (worker.QUEUE/state['backup']).read_bytes()==b'-- database backup\n'
        backup=next(i for i,x in enumerate(calls) if x[:4]==['docker','compose','exec','-T'])
        switch=calls.index(['git','checkout','--detach',SHA])
        build=calls.index(['docker','compose','build']);restart=calls.index(['docker','compose','up','-d'])
        assert backup<switch<build<restart
        assert not any('shell' in str(x) for x in calls)


@pytest.mark.parametrize('failure',['manifest','build','health'])
def test_host_failure_never_reports_success_and_retains_backup(tmp_path,monkeypatch,failure):
    worker=worker_at(tmp_path);queue=worker.QUEUE
    job={'id':'12345678-1234-1234-1234-123456789abc','commit':SHA,'version':'1.4.0','build':3}
    (queue/'request.json').write_text(json.dumps(job))
    calls=[]
    def run(args,**kwargs):
        calls.append(args)
        if args[:3]==['git','rev-parse','FETCH_HEAD']:return SimpleNamespace(stdout=SHA)
        if args[:2]==['git','show']:return SimpleNamespace(stdout=json.dumps({'schema':1,'channel':'main','build':999 if failure=='manifest' else 3,'version':'1.4.0'}))
        if args[:3]==['git','rev-parse','HEAD']:return SimpleNamespace(stdout=PREVIOUS)
        if args[:2]==['git','status']:return SimpleNamespace(stdout='')
        if args[:4]==['docker','compose','exec','-T']:kwargs['stdout'].write(b'backup')
        if args==['docker','compose','build'] and failure=='build':raise RuntimeError('mock build failed')
        return SimpleNamespace(stdout='')
    monkeypatch.setattr(worker,'run',run)
    checks=iter([False,True]) if failure=='health' else iter([True])
    monkeypatch.setattr(worker,'healthy',lambda:next(checks))
    worker.process_update();state=json.loads((queue/'status.json').read_text())
    assert state['state']=='failed' and not (queue/'request.json').exists()
    if failure=='manifest':
        assert not any(c[:2]==['git','checkout'] for c in calls)
        assert not list(queue.glob('database-*.sql'))
    else:
        assert ['git','checkout','--detach',PREVIOUS] in calls
        assert ['docker','compose','up','-d','--build'] in calls
        assert list(queue.glob('database-*.sql'))[0].read_bytes()==b'backup'


def test_connection_missing_stale_and_ready_are_distinct(tmp_path,monkeypatch):
    monkeypatch.setattr(web_update,'QUEUE',tmp_path)
    assert web_update.host_connection()['reason']=='worker_missing'
    ready=tmp_path/'ready';ready.touch();assert web_update.host_connection()['ready']
    os.utime(ready,(1,1));assert web_update.host_connection()['reason']=='worker_offline'
    ready.touch();monkeypatch.setattr(web_update.os,'access',lambda *args:False)
    assert web_update.host_connection()['reason']=='queue_not_writable'


def test_atomic_publish_ignores_partially_written_temporary_file(tmp_path,monkeypatch):
    monkeypatch.setattr(web_update,'QUEUE',tmp_path)
    monkeypatch.setattr(web_update,'check',AsyncMock(return_value={'host_ready':True,'available':True,'commit':SHA,'latest':{'version':'1.4.0','build':3}}))
    original=os.link
    def link(source,target,**kwargs):
        assert web_update.status()['state']=='idle'
        pending=json.loads(Path(source).read_text());assert pending['commit']==SHA
        original(source,target,**kwargs)
    monkeypatch.setattr(web_update.os,'link',link)
    job=asyncio.run(web_update.enqueue(SHA));assert web_update.status()=={'id':job['id'],'state':'queued'}
    assert not list(tmp_path.glob('.request-*'))


def test_offline_or_changed_commit_never_creates_host_request(tmp_path,monkeypatch):
    monkeypatch.setattr(web_update,'QUEUE',tmp_path)
    for ready,commit in [(False,SHA),(True,PREVIOUS)]:
        monkeypatch.setattr(web_update,'check',AsyncMock(return_value={'host_ready':ready,'available':True,'commit':commit,'latest':{'version':'1.4.0','build':3}}))
        with pytest.raises(ValueError):asyncio.run(web_update.enqueue(SHA))
        assert not (tmp_path/'request.json').exists()


def test_web_update_refreshes_host_agent_after_health_and_before_completion(tmp_path,monkeypatch):
    worker=worker_at(tmp_path);installer=tmp_path/'scripts/install-web-updater.sh'
    installer.parent.mkdir();installer.write_text('#!/bin/sh\n')
    (worker.QUEUE/'request.json').write_text(json.dumps({'id':'12345678-1234-1234-1234-123456789abc','commit':SHA,'version':'1.4.0','build':3}))
    calls=[]
    def run(args,**kwargs):
        calls.append(args)
        if args[:3]==['git','rev-parse','FETCH_HEAD']:return SimpleNamespace(stdout=SHA)
        if args[:2]==['git','show']:return SimpleNamespace(stdout=json.dumps({'schema':1,'channel':'main','build':3,'version':'1.4.0'}))
        if args[:3]==['git','rev-parse','HEAD']:return SimpleNamespace(stdout=PREVIOUS)
        return SimpleNamespace(stdout='')
    monkeypatch.setattr(worker,'run',run);monkeypatch.setattr(worker,'healthy',lambda:calls.append(['health']) or True)
    assert worker.process_update() is True
    assert calls.index(['health'])<calls.index(['bash',str(installer),'--defer-restart'])
    assert web_update.queue_json(worker.QUEUE/'status.json')['state']=='completed'
