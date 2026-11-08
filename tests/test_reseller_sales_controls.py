import asyncio,uuid
from unittest.mock import AsyncMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_reseller_onboarding import join,client,H,request
from app.api import admin_web
from app.services import reseller_onboarding as flow
from app.bot.keyboards.common import _button_value


def test_catalog_labels_include_plan_prices_and_disabled_panel_models_are_rejected(join):
 c,sessions,config=join
 catalog=c.get('/api/miniapp/reseller-join',headers=H).json()
 assert catalog['packages'][0]['price']=='2,000 تومان'
 config['pasarguard_panel_sales_payg_enabled']='0'
 catalog=c.get('/api/miniapp/reseller-join',headers=H).json()
 assert catalog['panel_modes']==['volume']
 data={'key':str(uuid.uuid4()),**request('panel',mode='payg',server_id=3)}
 r=c.post('/api/miniapp/reseller-join/quote',headers=H,json=data)
 assert r.status_code==409 and 'غیرفعال' in r.json()['detail']
 config['pasarguard_panel_sales_volume_enabled']='0'
 assert 'panel' not in c.get('/api/miniapp/reseller-join',headers=H).json()['options']


def test_panel_shop_visibility_follows_request_and_master_buttons():
 for key in ['button_reseller_menu_enabled','button_reseller_request_enabled']:
  assert _button_value({key:'0'},'panel_sales')[1] is False
 assert _button_value({'button_reseller_menu_enabled':'1','button_reseller_request_enabled':'1'},'panel_sales')[1] is True


def test_unified_save_validates_switches_and_synchronizes_existing_panel_settings(join,monkeypatch):
 _,sessions,config=join
 monkeypatch.setattr(admin_web,'SessionLocal',sessions)
 monkeypatch.setattr(admin_web,'_settings_map',AsyncMock(side_effect=lambda:dict(config)))
 async def persist(values):config.update(values)
 monkeypatch.setattr(admin_web,'_save_settings_map',persist)
 save_panel=AsyncMock(return_value={'ok':True});monkeypatch.setattr(admin_web,'save_panel_reseller_sales',save_panel)
 app=FastAPI();app.include_router(admin_web.router);app.dependency_overrides[admin_web._auth_user]=lambda:'admin'
 values={'button_reseller_menu_enabled':'1','button_reseller_request_enabled':'1','reseller_join_volume_enabled':'1','reseller_join_payg_enabled':'0','reseller_payg_min_topup_irt':'10000','pasarguard_panel_sales_enabled':'1','pasarguard_panel_sales_server_id':'3','pasarguard_panel_sales_price_irt':'0','pasarguard_panel_sales_gb_price_irt':'20','pasarguard_panel_sales_hourly_price_irt':'0','pasarguard_panel_sales_max_users':'0','pasarguard_panel_sales_min_initial_gb':'100','pasarguard_panel_sales_volume_enabled':'1','pasarguard_panel_sales_payg_enabled':'0'}
 with TestClient(app) as c:
  data=c.get('/admin/api/v2/reseller-onboarding').json()
  assert data['ok'] and data['servers'][0]['id']==3
  headers={'Accept':'application/json'}
  assert c.post('/admin/reseller-onboarding/settings',headers=headers,data={**values,'pasarguard_panel_sales_volume_enabled':'0'}).status_code==400
  save_panel.assert_not_awaited()
  r=c.post('/admin/reseller-onboarding/settings',headers=headers,data=values)
  assert r.status_code==200,r.text
  assert config['reseller_join_payg_enabled']=='0' and config['button_panel_sales_enabled']=='1'
  assert save_panel.call_args.kwargs['enabled']=='1' and save_panel.call_args.kwargs['min_initial_gb']==100
  values['button_reseller_menu_enabled']='0'
  assert c.post('/admin/reseller-onboarding/settings',headers=headers,data=values).status_code==200
  assert save_panel.call_args.kwargs['enabled']=='0' and config['pasarguard_panel_sales_enabled']=='1'
