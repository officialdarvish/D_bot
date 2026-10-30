import asyncio
from datetime import datetime,timedelta
from pathlib import Path
from unittest.mock import AsyncMock
import httpx,pytest
from sqlalchemy import event,delete
from test_miniapp import client
from app.api import admin_web as web
from app.database.models import Order,Setting,User,WalletTransaction,ResellerAccount


def test_dashboard_aggregate_results_match_accounting_and_use_fewer_queries(client,monkeypatch):
 _,sessions=client
 now=datetime(2026,10,26,12);anchor=now.replace(hour=0)-timedelta(days=10)
 class Clock(datetime):
  @classmethod
  def utcnow(cls):return now
 monkeypatch.setattr(web,'datetime',Clock);monkeypatch.setattr(web,'SessionLocal',sessions)
 async def seed():
  async with sessions() as s:
   await s.execute(delete(Order))
   s.add(Setting(key=web.DASHBOARD_REVENUE_ANCHOR_KEY,value=anchor.isoformat()))
   u1=await s.get(User,1);u2=await s.get(User,2)
   u1.joined_at=now;u2.joined_at=now-timedelta(days=1)
   for i,(amount,status,created) in enumerate([(100,'paid',now-timedelta(days=1)),(200,'approved',now),(900,'pending',now),(300,'paid',anchor-timedelta(days=1)),(600,'failed',anchor-timedelta(days=2)),(50,'paid',anchor+timedelta(days=31))],10):
    s.add(Order(id=i,user_id=1,plan_id=1,amount_irt=amount,payment_method='wallet',status=status,created_at=created))
   for amount,created in [(100,now),(-20,now),(40,now-timedelta(days=1)),(999,now-timedelta(days=2))]:
    s.add(WalletTransaction(user_id=1,amount_irt=amount,tx_type='test',created_at=created))
   s.add(ResellerAccount(user_id=1,server_id=2,total_bytes=100))
   await s.commit()
 asyncio.run(seed())
 engine=sessions.kw['bind'];queries=[]
 def count(conn,cursor,statement,parameters,context,many):queries.append(statement)
 event.listen(engine.sync_engine,'before_cursor_execute',count)
 try:result=asyncio.run(web.api_v2_dashboard())
 finally:event.remove(engine.sync_engine,'before_cursor_execute',count)
 stats=result['stats']
 assert stats['monthly_sales']==300 and stats['monthly_sales_change']==0
 assert stats['today_orders']==3 and stats['orders_change']==50
 assert stats['users_total']==2 and stats['users_change']==0
 assert stats['wallet_balance']==250000 and stats['wallet_change']==100
 assert stats['resellers_total']==1 and stats['active_services']==2
 assert stats['conversion_rate']==66.67
 assert sum(row['sales'] for row in result['chart_ranges'][0]['data'])==300
 assert len(queries)<=9,queries


@pytest.mark.asyncio
async def test_static_assets_skip_database_and_are_compressed_and_cached(monkeypatch):
 from app.api import main
 lookup=AsyncMock(side_effect=AssertionError('static assets must not query WEB_PATH'))
 monkeypatch.setattr(main,'read_web_path',lookup)
 chunk=next((main.FRONTEND_OUT/'_next/static/chunks').glob('*.js'))
 relative='/'+chunk.relative_to(main.FRONTEND_OUT).as_posix()
 async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='http://test') as c:
  response=await c.get(relative,headers={'Accept-Encoding':'gzip'})
  assert response.status_code==200 and response.content==chunk.read_bytes()
  assert response.headers['content-encoding']=='gzip'
  assert 'immutable' in response.headers['cache-control']
  # Starlette may stream compressed static files without Content-Length.
  if 'content-length' in response.headers:
   assert int(response.headers['content-length']) < len(response.content)
  font=await c.get('/fonts/Vazirmatn-Regular.woff2')
  assert font.status_code==200 and 'max-age=86400' in font.headers['cache-control']
  health=await c.get('/health');assert health.status_code==200
  # Fixed /api/admin routes still execute the existing auth dependency.
  protected=await c.get('/api/admin/service-types')
  assert protected.status_code==401
 lookup.assert_not_awaited()


@pytest.mark.asyncio
async def test_managed_web_paths_still_use_database_routing(monkeypatch):
 from app.api import main
 lookup=AsyncMock(return_value='private-route')
 monkeypatch.setattr(main,'read_web_path',lookup)
 async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='http://test') as c:
  r=await c.get('/admin',follow_redirects=False)
  assert r.status_code==307 and r.headers['location']=='/private-route/admin'
 lookup.assert_awaited_once()
