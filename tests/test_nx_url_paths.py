import asyncio
from unittest.mock import AsyncMock
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_miniapp import client
from app.api import admin_web as web
from app.services.nx_service import NxService, normalize_nx_panel_parts
from app.database.models import Server
from app.core.security import encrypt_text, decrypt_text


@pytest.mark.parametrize('url,path,expected',[
 ('https://nx.test:28431','/secret/','https://nx.test:28431/secret'),
 ('https://nx.test/secret/','/','https://nx.test/secret'),
 ('https://nx.test/secret','/secret/','https://nx.test/secret'),
 ('https://nx.test/secret/api/v1/','/','https://nx.test/secret'),
 ('https://nx.test/secret/api','/','https://nx.test/secret'),
 ('https://nx.test/secret/login/','/','https://nx.test/secret'),
 ('https://nx.test','/secret/api/v1/','https://nx.test/secret'),
 ('https://nx.test','/','https://nx.test'),
])
def test_normalize_private_path_and_api_suffix(url,path,expected):
    origin,private,final=normalize_nx_panel_parts(url,path)
    assert final==expected
    assert final==origin+(private.rstrip('/') if private!='/' else '')


@pytest.mark.parametrize('url,path',[
 ('https://user:secret@nx.test/','/'),('https://nx.test/?token=secret','/'),
 ('https://nx.test/#login','/'),('https://nx.test','https://other.test'),
 ('https://nx.test','/../secret/'),('https://nx.test:bad','/'),
])
def test_invalid_bases_rejected_without_request(url,path):
    with pytest.raises(ValueError):normalize_nx_panel_parts(url,path)


def test_actual_template_request_keeps_private_prefix_and_only_one_api_prefix(monkeypatch):
    original=httpx.AsyncClient;calls=[]
    def transport(request):
        calls.append(request)
        return httpx.Response(200,json={'items':[{'id':7,'name':'NX template'}],'total':1})
    def client_factory(**kwargs):
        assert kwargs.get('follow_redirects') is False
        return original(transport=httpx.MockTransport(transport),**kwargs)
    monkeypatch.setattr(httpx,'AsyncClient',client_factory)
    server=Server(panel_url='https://nx.test:28431/secret/api/v1/',password_encrypted=encrypt_text('test-token'),meta={'panel_path':'/'})
    result=asyncio.run(NxService().list_templates(server))
    assert result[0]['id']==7
    assert str(calls[0].url).split('?')[0]=='https://nx.test:28431/secret/api/v1/templates'
    assert calls[0].headers['Authorization']=='Bearer test-token'
    assert len(calls)==1


def test_404_reports_path_hint_without_probing_other_routes_or_leaking_token(monkeypatch):
    original=httpx.AsyncClient;calls=[]
    def transport(request):
        calls.append(request);return httpx.Response(404,text='private upstream page')
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(transport),**kwargs))
    server=Server(panel_url='https://nx.test/secret',password_encrypted=encrypt_text('secret-token'),meta={})
    with pytest.raises(RuntimeError) as error:asyncio.run(NxService().list_templates(server))
    assert '404' in str(error.value) and 'private web path' in str(error.value)
    assert 'secret-token' not in str(error.value) and 'upstream page' not in str(error.value)
    assert len(calls)==1


@pytest.fixture
def admin(client,monkeypatch):
    _,sessions=client;monkeypatch.setattr(web,'SessionLocal',sessions)
    app=FastAPI();app.include_router(web.router);app.dependency_overrides[web._auth_user]=lambda:'owner'
    calls=[]
    async def probe(self,server):
        calls.append((server.panel_url,dict(server.meta or {})))
        return {'ok':True,'groups':[{'id':7,'name':'NX template'}],'templates':[],'access':{},'api_base':'/api/v1'}
    monkeypatch.setattr(NxService,'probe_server',probe)
    with TestClient(app) as api:yield api,sessions,calls


def test_web_test_add_edit_preserve_split_path_and_existing_token(admin):
    api,sessions,calls=admin
    payload={'server_type':'nx','name':'NX','panel_url':'https://nx.test:28431','panel_path':'/secret/','api_key':'test-token','scope':'public'}
    response=api.post('/admin/servers/test',data=payload,headers={'Accept':'application/json'})
    assert response.status_code==200,response.text
    assert response.json()['auto_fill']['panel_path']=='/secret/'
    assert response.json()['auto_fill']['panel_url']=='https://nx.test:28431'
    response=api.post('/admin/servers/add',data=payload,headers={'Accept':'application/json'})
    assert response.status_code==200,response.text
    async def get():
        async with sessions() as s:
            return (await s.execute(select(Server).where(Server.server_type=='nx'))).scalar_one()
    row=asyncio.run(get())
    assert row.panel_url=='https://nx.test:28431/secret' and row.meta['panel_path']=='/secret/'
    payload.update(panel_path='/new-private/',api_key='')
    response=api.post(f'/admin/servers/{row.id}/edit',data=payload,headers={'Accept':'application/json'})
    assert response.status_code==200,response.text
    row=asyncio.run(get())
    assert row.panel_url=='https://nx.test:28431/new-private'
    assert row.meta['panel_path']=='/new-private/'
    assert decrypt_text(row.password_encrypted)=='test-token'
    assert [c[0] for c in calls]==['https://nx.test:28431/secret','https://nx.test:28431/secret','https://nx.test:28431/new-private']
