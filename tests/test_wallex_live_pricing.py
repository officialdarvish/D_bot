from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.services import live_pricing


def test_parse_wallex_uses_usdttmn_ask_price():
    payload = {
        'result': {
            'symbols': {
                'USDTTMN': {
                    'stats': {
                        'bidPrice': '109000.0',
                        'askPrice': '110250.0',
                        'lastPrice': '109800.0',
                    }
                }
            }
        }
    }
    assert live_pricing.parse_wallex_rate(payload) == 110250


def test_plan_price_metadata_and_label():
    plan = SimpleNamespace(price_irt=0, meta={'pricing_currency': 'USD', 'price_usd': '4.99'})
    assert live_pricing.plan_currency(plan) == 'USD'
    assert str(live_pricing.plan_price_usd(plan)) == '4.99'
    assert live_pricing.plan_price_label(plan) == '$4.99'


@pytest.mark.asyncio
async def test_usd_plan_quote_converts_live_toman_rate(monkeypatch):
    plan = SimpleNamespace(price_irt=0, meta={'pricing_currency': 'USD', 'price_usd': '4.99'})

    async def fake_rate(*, force_refresh=False):
        return 110250, datetime(2026, 9, 30, 6, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(live_pricing, 'wallex_usdt_tmn_rate', fake_rate)
    quote = await live_pricing.quote_plan(plan, force_refresh=True)
    assert quote.currency == 'USD'
    assert quote.usd_rate_tmn == 110250
    assert quote.amount_irt == 550148
    assert quote.as_meta()['source'] == 'Wallex USDTTMN askPrice'


@pytest.mark.asyncio
async def test_fixed_toman_plan_never_calls_wallex(monkeypatch):
    plan = SimpleNamespace(price_irt=275000, meta={})

    async def should_not_run(*, force_refresh=False):
        raise AssertionError('Wallex must not be called for fixed Toman plans')

    monkeypatch.setattr(live_pricing, 'wallex_usdt_tmn_rate', should_not_run)
    quote = await live_pricing.quote_plan(plan)
    assert quote.currency == 'IRT'
    assert quote.amount_irt == 275000


def test_reseller_package_can_use_usd_pricing_meta():
    package = SimpleNamespace(price_irt=0, meta={'pricing_currency': 'USD', 'price_usd': '12.50'})
    assert live_pricing.plan_currency(package) == 'USD'
    assert str(live_pricing.plan_price_usd(package)) == '12.50'
    assert live_pricing.plan_price_label(package) == '$12.5'


@pytest.mark.asyncio
async def test_reseller_package_quote_converts_usd_with_wallex(monkeypatch):
    package = SimpleNamespace(price_irt=0, meta={'pricing_currency': 'USD', 'price_usd': '12.50'})

    async def fake_rate(*, force_refresh=False):
        return 100_000, datetime.now(timezone.utc)

    monkeypatch.setattr(live_pricing, 'wallex_usdt_tmn_rate', fake_rate)
    quote = await live_pricing.quote_plan(package, force_refresh=True)
    assert quote.currency == 'USD'
    assert quote.amount_irt == 1_250_000
    assert quote.usd_rate_tmn == 100_000
