from datetime import datetime,timedelta
from unittest.mock import AsyncMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api import admin_web as web


@pytest.mark.parametrize('state',['missing','expired','credentials_changed'])
@pytest.mark.parametrize('headers',[{'Accept':'application/json'},{'X-Requested-With':'fetch'}])
def test_expired_fetch_test_returns_json_without_login_redirect(monkeypatch,state,headers):
 session={'username':'owner','expires_at':datetime.utcnow()+timedelta(hours=1),'credential_version':'old','csrf':'csrf'}
 if state=='expired':session['expires_at']=datetime.utcnow()-timedelta(seconds=1)
 monkeypatch.setattr(web,'_sessions',{} if state=='missing' else {'test-session':session})
 monkeypatch.setattr(web,'db_setting',AsyncMock(return_value='new' if state=='credentials_changed' else 'old'))
 probe=AsyncMock();monkeypatch.setattr(web.PasarGuardService,'probe_server',probe)
 app=FastAPI();app.include_router(web.router)
 with TestClient(app) as c:
  c.cookies.set('dbot_admin_token','test-session')
  r=c.post('/admin/servers/test',data={'server_type':'pasarguard','panel_url':'https://panel.example','username':'panel-admin','password':'panel-password'},headers=headers,follow_redirects=False)
  assert r.status_code==401 and r.headers['content-type'].startswith('application/json')
  assert 'location' not in r.headers and r.json()['detail']
 probe.assert_not_awaited()


def test_legacy_unauthenticated_form_uses_get_redirect(monkeypatch):
 monkeypatch.setattr(web,'_sessions',{})
 app=FastAPI();app.include_router(web.router)
 with TestClient(app) as c:
  r=c.post('/admin/servers/test',data={'panel_url':'https://panel.example'},follow_redirects=False)
  assert r.status_code==303 and '/login' in r.headers['location']


def test_authenticated_password_connection_test_still_reaches_pasarguard(monkeypatch):
 monkeypatch.setattr(web,'_sessions',{'test-session':{'username':'owner','expires_at':datetime.utcnow()+timedelta(hours=1),'credential_version':'v1','csrf':'csrf'}})
 monkeypatch.setattr(web,'db_setting',AsyncMock(return_value='v1'))
 async def probe(server):
  assert server.meta['auth_mode']=='oauth-password' and server.username=='panel-admin'
  raise RuntimeError('panel-specific connection failure')
 monkeypatch.setattr(web.PasarGuardService,'probe_server',AsyncMock(side_effect=probe))
 app=FastAPI();app.include_router(web.router)
 with TestClient(app) as c:
  c.cookies.set('dbot_admin_token','test-session')
  r=c.post('/admin/servers/test',data={'server_type':'pasarguard','panel_url':'https://panel.example','username':'panel-admin','password':'panel-password'},headers={'Accept':'application/json','X-CSRF-Token':'csrf'})
  assert r.status_code==400 and r.json()['message']=='PasarGuard connection failed: panel-specific connection failure'
