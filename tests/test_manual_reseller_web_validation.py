import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select,func
from test_miniapp import client
from app.api import admin_web as web
from app.database.models import ResellerAccount,User

@pytest.fixture
def admin(client,monkeypatch):
 _,sessions=client
 monkeypatch.setattr(web,'SessionLocal',sessions)
 app=FastAPI();app.include_router(web.router)
 app.dependency_overrides[web._auth_user]=lambda:'owner'
 with TestClient(app) as c:yield c,sessions

@pytest.mark.parametrize('volume',['0','100','12.5','0.1'])
def test_create_reseller_accepts_integer_and_fractional_prepaid_volume(admin,volume):
 c,sessions=admin
 r=c.post('/admin/resellers/add',data={'telegram_id':'11','total_gb':volume,'days':'0','allowed_server_ids':'2','inbound_policies_json':'{}','billing_mode':'volume'},headers={'Accept':'application/json'})
 assert r.status_code==200,r.text
 assert r.json()['ok'] is True
 async def check():
  async with sessions() as s:
   account=await s.scalar(select(ResellerAccount).where(ResellerAccount.user_id==1))
   assert account.total_bytes==int(Decimal(volume)*1024**3)
   assert account.expires_at is None and account.allowed_server_ids==[2]
 asyncio.run(check())

@pytest.mark.parametrize('overrides',[
 {'telegram_id':'0'},{'telegram_id':'-11'},{'telegram_id':str(2**63)},
 {'total_gb':'-1'},{'total_gb':'NaN'},{'total_gb':'Infinity'},{'total_gb':'1e100'},
 {'days':'-1'},{'days':'1000000000'},{'days':'1.5'},{'telegram_id':'not-a-number'},
])
def test_invalid_add_does_not_create_user_or_reseller(admin,overrides):
 c,sessions=admin
 data={'telegram_id':'333','total_gb':'1.5','days':'30','allowed_server_ids':'2',**overrides}
 r=c.post('/admin/resellers/add',data=data,headers={'Accept':'application/json'})
 assert r.status_code in (400,422),r.text
 async def check():
  async with sessions() as s:
   assert await s.scalar(select(func.count()).select_from(ResellerAccount))==0
   assert await s.scalar(select(func.count()).select_from(User))==2
 asyncio.run(check())


def test_duplicate_add_is_readable_and_edit_keeps_fractional_balance(admin,monkeypatch):
 c,sessions=admin
 monkeypatch.setattr(web,'reconcile_reseller_accounting',AsyncMock())
 data={'telegram_id':'11','total_gb':'12.5','days':'30','allowed_server_ids':'2'}
 first=c.post('/admin/resellers/add',data=data,headers={'Accept':'application/json'})
 assert first.status_code==200,first.text
 again=c.post('/admin/resellers/add',data=data,headers={'Accept':'application/json'})
 assert again.status_code==400 and isinstance(again.json()['message'],str)
 async def ident():
  async with sessions() as s:return await s.scalar(select(ResellerAccount.id))
 rid=asyncio.run(ident())
 edited=c.post(f'/admin/resellers/{rid}/edit',data={'total_gb':'7.25','expires_at':'2027-01-01','allowed_server_ids':'2'},headers={'Accept':'application/json'})
 assert edited.status_code==200,edited.text
 async def check():
  async with sessions() as s:assert (await s.get(ResellerAccount,rid)).total_bytes==int(Decimal('7.25')*1024**3)
 asyncio.run(check())
