"""The frequent status poll stays authenticated and independent of DB reports."""
from datetime import datetime
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api import admin_web as web


def test_live_resources_are_fresh_uncached_and_do_not_query_reports(monkeypatch):
 calls=[]
 def sample():
  calls.append(True)
  return [dict(title='CPU',percent=len(calls)*11,value='sample',detail='',icon='',cls='blue')]
 monkeypatch.setattr(web,'_resource_stats',sample)
 def no_db():raise AssertionError('Resource polling queried sales DB')
 monkeypatch.setattr(web,'SessionLocal',no_db)
 app=FastAPI();app.include_router(web.router)
 app.dependency_overrides[web._auth_user]=lambda:'owner'
 with TestClient(app) as c:
  for expected in [11,22]:
   response=c.get('/admin/api/v2/resources')
   assert response.status_code==200
   assert response.headers['cache-control']=='no-store'
   payload=response.json();assert payload['ok'] and payload['resources'][0]['percent']==expected
   assert datetime.fromisoformat(payload['updated_at'].replace('Z','+00:00')).tzinfo
  app.dependency_overrides.clear()
  assert c.get('/admin/api/v2/resources').status_code in (401,403)
 assert len(calls)==2
