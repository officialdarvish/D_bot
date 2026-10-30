import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from sqlalchemy import select
from test_miniapp_native_actions import native,client
from test_panel_wallet_miniapp_alerts import seed
from app.database.models import User,PasarGuardPanelMeter
from app.services import pasarguard_panel_meter as metering


def test_negative_panel_balance_debits_full_usage_and_restores_only_billing_pauses(native,monkeypatch):
 _,sessions,*_=native;seed(sessions)
 monkeypatch.setattr(metering,'SessionLocal',sessions)
 api=metering.PanelMeterAPI()
 users=[{'id':11,'username':'customer','used_traffic':1024**3,'status':'active'}, {'id':12,'username':'manual','used_traffic':0,'status':'disabled'}]
 monkeypatch.setattr(api,'list_own_users',AsyncMock(side_effect=lambda *a:list(users)))
 calls=[]
 async def request(server,method,path,**kwargs):
  calls.append((method,path,kwargs))
  for row in users:
   if row['id'] in kwargs['json']['ids']:row['status']='active' if path.endswith('/enable') else 'disabled'
  return {}
 monkeypatch.setattr(api.provider,'_request',request)
 async def run():
  async with sessions() as s:
   user=await s.get(User,1);user.wallet_balance=10
   meter=await s.scalar(select(PasarGuardPanelMeter).where(PasarGuardPanelMeter.order_id==1));meter.gb_price_irt=1000;meter.hourly_price_irt=0;await s.commit()
  result=await api.poll(1)
  assert result['remaining']==-990 and result['charged']==1000 and result['suspended']
  assert calls==[('POST','/api/users/bulk/disable',{'json':{'ids':[11]}})]
  async with sessions() as s:
   user=await s.get(User,1);user.wallet_balance+=990;await s.commit()
  # Exactly zero is settled; only the recorded auto-paused user is restored.
  assert await api.resume(1)==1
  assert users[0]['status']=='active' and users[1]['status']=='disabled'
  assert calls[-1]==('POST','/api/users/bulk/enable',{'json':{'ids':[11]}})
  async with sessions() as s:
   meter=await s.scalar(select(PasarGuardPanelMeter).where(PasarGuardPanelMeter.order_id==1))
   assert not meter.suspended and meter.auto_disabled_user_ids==[]
 asyncio.run(run())
