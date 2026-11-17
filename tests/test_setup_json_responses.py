from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request
import pytest
from test_miniapp import client
from test_nx_url_paths import admin
from app.api import admin_web as web


@pytest.mark.parametrize('header', ['fetch', 'XMLHttpRequest', 'xmlhttprequest'])
def test_ajax_headers_return_json_instead_of_navigation(header):
    request=Request({'type':'http','method':'POST','path':'/admin/servers/add','query_string':b'','headers':[(b'x-requested-with',header.encode())]})
    assert web.is_ajax(request)
    result=web.ok(request,'/admin/servers','NX saved')
    assert result.status_code==200 and result.media_type=='application/json'
    result=web.fail(request,'Connection failed',400)
    assert result.status_code==400 and result.media_type=='application/json'


def test_old_setup_xhr_add_succeeds_without_following_html_redirect(admin):
    api,sessions,calls=admin
    payload={'server_type':'nx','name':'NX setup','panel_url':'https://nx.test','panel_path':'/private/','api_key':'dummy-local-token','scope':'public'}
    result=api.post('/admin/servers/add',data=payload,headers={'X-Requested-With':'XMLHttpRequest'},follow_redirects=False)
    assert result.status_code==200,result.text
    assert result.headers['content-type'].startswith('application/json')
    assert result.json()['ok'] is True
    assert len(calls)==1


def test_expired_old_setup_xhr_gets_401_without_login_redirect():
    app=FastAPI();app.include_router(web.router)
    with TestClient(app) as api:
        result=api.post('/admin/servers/test',data={'panel_url':'https://nx.test'},headers={'X-Requested-With':'XMLHttpRequest'},follow_redirects=False)
    assert result.status_code==401
    assert result.headers['content-type'].startswith('application/json')
    assert 'location' not in result.headers
