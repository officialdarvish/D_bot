import asyncio
from unittest.mock import AsyncMock
from starlette.requests import Request
from sqlalchemy import select
from test_miniapp_native_actions import native,client,H,funding
from app.database.models import Server,PaymentCard,ClientService,Order
from app.api import admin_web as web
from app.services.payment_cards import reseller_payment_card


def request():return Request({'type':'http','method':'POST','path':'/admin/payments/add','headers':[(b'accept',b'application/json'),(b'x-requested-with',b'fetch')],'query_string':b''})


def test_pasarguard_reseller_card_stays_bound_on_add_edit_and_checkout(native,monkeypatch):
 c,sessions,real,calls,flow,buy=native
 monkeypatch.setattr(web,'SessionLocal',sessions)
 async def run():
  async with sessions() as s:
   pg=await s.get(Server,2);pg.server_type='pasarguard';await s.commit()
  r=await web.pay_add(request(),card_number='PG-CARD',owner_name='PG Owner',reviewer_telegram_id=77,show_for='reseller',server_id=2,_='owner');assert r.status_code==200
  async with sessions() as s:
   card=await reseller_payment_card(s,2);assert card.server_id==2 and card.server_type=='reseller' and card.card_number=='PG-CARD';pid=card.id
   assert (await reseller_payment_card(s,1)).server_id is None
   # A newer fallback cannot override the selected panel's card.
   s.add(PaymentCard(server_type='reseller',card_number='FALLBACK',owner_name='Other',is_active=True));await s.commit()
  r=await web.pay_edit(request(),pid=pid,card_number='PG-UPDATED',owner_name='PG Owner',reviewer_telegram_id=77,show_for='reseller',server_id=2,_='owner');assert r.status_code==200
  async with sessions() as s:assert (await reseller_payment_card(s,2)).card_number=='PG-UPDATED'
 asyncio.run(run())
 b=funding(method='card');r=c.post('/api/miniapp/funding',headers=H,json=b);assert r.status_code==200,r.text
 assert r.json()['card']['number']=='PG-UPDATED'


def test_public_pasarguard_card_and_panel_sales_use_the_selected_server(native,monkeypatch):
 c,sessions,real,calls,flow,buy=native
 from app.bot.handlers.public import panel_reseller_sale as sale
 from app.bot.keyboards import common
 # This path reads button visibility too; use the same initialized test database.
 monkeypatch.setattr(common,'SessionLocal',sessions)
 monkeypatch.setattr(common,'_BUTTON_SETTINGS_CACHE',{})
 monkeypatch.setattr(common,'_BUTTON_SETTINGS_CACHE_UNTIL',0)
 monkeypatch.setattr(web,'SessionLocal',sessions)
 monkeypatch.setattr(sale,'get_setting_value',AsyncMock(side_effect=lambda key,default:{'pasarguard_panel_sales_enabled':'1','pasarguard_panel_sales_server_id':'1','pasarguard_panel_sales_price_irt':'10000'}.get(key,default)))
 async def run():
  async with sessions() as s:
   pg=await s.get(Server,1);pg.server_type='pasarguard';await s.commit()
  r=await web.pay_add(request(),card_number='PUBLIC-PG',owner_name='Public PG',reviewer_telegram_id=0,show_for='public',server_id=1,_='owner');assert r.status_code==200
  async with sessions() as s:
   card=await s.scalar(select(PaymentCard).where(PaymentCard.card_number=='PUBLIC-PG'))
   assert card.server_type=='pasarguard' and card.server_id==1
   cfg=await sale._configuration(s);assert cfg and cfg[2].id==card.id
  r=await web.pay_add(request(),card_number='BAD',owner_name='Bad',reviewer_telegram_id=0,show_for='public',server_id=2,_='owner');assert r.status_code==400
  r=await web.pay_add(request(),card_number='BAD',owner_name='Bad',reviewer_telegram_id=0,show_for='reseller',server_id=999,_='owner');assert r.status_code==404
 asyncio.run(run())


def test_non_miniapp_approved_purchase_sends_config_without_extra_success_message(native,monkeypatch):
 c,sessions,real,calls,flow,buy=native
 for n in ['send_buyer_notice','notify_paid_order','send_service_card','send_service_success_notice','send_home','send_admin_notice','edit_admin_receipt_keyboard','report_bot_error']:
  monkeypatch.setattr(buy,n,AsyncMock())
 monkeypatch.setattr(buy,'apply_purchase_commission',AsyncMock(return_value=0))
 async def build(s,user,server,plan,name,password=None):
  svc=ClientService(user_id=user.id,server_id=server.id,plan_id=plan.id,client_username=name,xui_email=name,total_bytes=30*1024**3,sub_link='https://example.com/sub/new');s.add(svc);await s.flush();return svc,svc.sub_link
 monkeypatch.setattr(buy,'build_service',AsyncMock(side_effect=build))
 async def run():
  async with sessions() as s:
   s.add(Order(id=999,user_id=1,plan_id=1,amount_irt=139000,payment_method='card:Completed',status='processing'));await s.commit()
  await buy.process_approved_order_background(999,real,admin_chat_id=99,admin_receipt_chat_id=99,admin_receipt_message_id=1)
  async with sessions() as s:assert (await s.get(Order,999)).status=='paid'
 asyncio.run(run())
 assert buy.send_service_card.await_count==1
 assert buy.send_service_success_notice.await_count==0


def test_reseller_payment_never_uses_another_server_scoped_card(native):
 c,sessions,*_=native
 async def run():
  async with sessions() as s:
   fallback=await s.get(PaymentCard,1);fallback.is_active=False
   s.add(PaymentCard(server_type='reseller',server_id=2,card_number='PRIVATE-2',owner_name='Only 2',is_active=True));await s.commit()
   assert await reseller_payment_card(s,1) is None
   assert (await reseller_payment_card(s,2)).card_number=='PRIVATE-2'
 asyncio.run(run())
