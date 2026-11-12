from test_miniapp import client
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from app.services.web_update import manifest
from app.services.network_errors import telegram_timeout
from app.services.custom_tariff import normalize,selected_plan,snapshot


def test_small_update_build_does_not_require_version_bump():
    a=manifest({'schema':1,'channel':'main','version':'1.3.0','build':1})
    b=manifest({'schema':1,'channel':'main','version':'1.3.0','build':2})
    assert a['version']==b['version'] and a['build']<b['build']
    for invalid in (0,-1,True,'2'):
        with pytest.raises(ValueError):manifest({**a,'build':invalid})
    with pytest.raises(ValueError):manifest({**a,'channel':'attacker'})


def test_telegram_timeout_is_logged_but_not_reported_as_provider_failure():
    assert telegram_timeout(TimeoutError('request timed out'),'telegram connection')
    assert not telegram_timeout(TimeoutError('read timed out'),'PasarGuard provisioning')
    assert not telegram_timeout(ValueError('invalid input'),'telegram handler')


def template():
    policy=normalize(dict(enabled='yes',min_gb=1,max_gb=100,min_days=1,max_days=90,price_gb=10000,price_day=1000))
    return SimpleNamespace(id=42,title='Custom',volume_gb=1,duration_days=1,price_irt=0,server_id=3,category_id=5,inbound_ids=[1],hwid_limit=1,meta={'custom_tariff':policy,'pricing_currency':'USD','price_usd':'5'})


def test_custom_tariff_is_server_priced_and_does_not_modify_template():
    original=template();selected=selected_plan(original,20,30)
    assert selected.price_irt==230000 and selected.volume_gb==20 and selected.duration_days==30
    assert original.price_irt==0 and original.volume_gb==1
    assert selected.meta['pricing_currency']=='IRT' and 'price_usd' not in selected.meta
    for gb,days in [(0,30),(101,30),(20,91),('nan',1),('1.5',30)]:
        with pytest.raises(ValueError):selected_plan(original,gb,days)


def test_snapshot_preserves_terms_after_admin_edits_template():
    selected=selected_plan(template(),20,30);rows=[]
    session=SimpleNamespace(add=rows.append,flush=AsyncMock())
    row=asyncio.run(snapshot(session,selected,7))
    selected.price_irt=1;selected.volume_gb=2
    assert row.price_irt==230000 and row.volume_gb==20 and row.duration_days==30
    assert not row.is_active and row.meta['custom_owner_id']==7


def test_disabled_reseller_blocks_direct_api_and_hides_miniapp(client):
    from test_miniapp import signed
    from app.database.models import Setting
    c,sessions=client
    async def disable():
        async with sessions() as session:
            await session.merge(Setting(key='feature_resellers',value='0'));await session.commit()
    asyncio.run(disable())
    headers={'X-Telegram-Init-Data':signed()}
    data=c.get('/api/miniapp/session',headers=headers).json()
    assert data['reseller'] is None and data['panels']==[]
    assert not data['buttons']['reseller_request'] and not data['buttons']['panel_sales']
    assert c.get('/api/miniapp/reseller',headers=headers).status_code==403

from test_miniapp_checkout import native,H,body

def test_custom_checkout_price_replay_and_immutable_plan(native):
    from app.database.models import Plan,Order
    c,sessions,bot,buy=native
    async def configure():
        async with sessions() as session:
            plan=await session.get(Plan,1)
            plan.meta={**(plan.meta or {}),'custom_tariff':template().meta['custom_tariff']}
            await session.commit()
    asyncio.run(configure())
    payload=body(volume_gb=20,duration_days=30);payload['expected_amount_irt']=230000
    assert c.post('/api/miniapp/checkout/quote',headers=H,json={k:v for k,v in payload.items() if k not in ('method','key','expected_amount_irt')}).json()['amount_irt']==230000
    result=c.post('/api/miniapp/checkout',headers=H,json=payload)
    assert result.status_code==200,result.text
    oid=result.json()['id']
    assert c.post('/api/miniapp/checkout',headers=H,json=payload).json()['id']==oid
    assert c.post('/api/miniapp/checkout',headers=H,json={**payload,'duration_days':31}).status_code==409
    async def verify():
        async with sessions() as session:
            order=await session.get(Order,oid);concrete=await session.get(Plan,order.plan_id)
            assert order.plan_id!=1 and concrete.volume_gb==20 and concrete.duration_days==30 and concrete.price_irt==230000
            assert not concrete.is_active
    asyncio.run(verify())


def test_update_queue_exclusive_and_no_arbitrary_command(tmp_path,monkeypatch):
    from app.services import web_update
    sha='a'*40
    monkeypatch.setattr(web_update,'QUEUE',tmp_path)
    monkeypatch.setattr(web_update,'check',AsyncMock(return_value={'host_ready':True,'available':True,'commit':sha,'latest':{'version':'1.3.0','build':2}}))
    first=asyncio.run(web_update.enqueue(sha))
    assert set(first)=={'id','commit','build','version'} and first['commit']==sha
    with pytest.raises(ValueError):asyncio.run(web_update.enqueue(sha))
    with pytest.raises(ValueError):asyncio.run(web_update.enqueue('$(whoami)'))
