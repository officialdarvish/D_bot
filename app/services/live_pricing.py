from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

import httpx

WALLEX_MARKETS_URL = 'https://api.wallex.ir/v1/markets'
WALLEX_SYMBOL = 'USDTTMN'
WALLEX_RATE_FIELD = 'askPrice'
_CACHE_TTL_SECONDS = 30.0
_HTTP_TIMEOUT_SECONDS = 8.0

_cache_lock = asyncio.Lock()
_cached_rate_tmn: int | None = None
_cached_at_monotonic: float = 0.0
_cached_fetched_at: datetime | None = None


class LivePricingError(RuntimeError):
    pass


@dataclass(frozen=True)
class PriceQuote:
    currency: str
    amount_irt: int
    price_usd: Decimal | None = None
    usd_rate_tmn: int | None = None
    source: str = 'fixed'
    quoted_at: datetime | None = None

    def as_meta(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            'currency': self.currency,
            'base_amount_irt': int(self.amount_irt),
            'source': self.source,
        }
        if self.price_usd is not None:
            data['price_usd'] = format(self.price_usd, 'f')
        if self.usd_rate_tmn is not None:
            data['usd_rate_tmn'] = int(self.usd_rate_tmn)
        if self.quoted_at is not None:
            data['quoted_at'] = self.quoted_at.astimezone(timezone.utc).isoformat()
        return data


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or '0').strip())
    except (InvalidOperation, ValueError, TypeError):
        return Decimal('0')


def plan_currency(plan: Any) -> str:
    meta = dict(getattr(plan, 'meta', None) or {})
    value = str(meta.get('pricing_currency') or 'IRT').strip().upper()
    return 'USD' if value == 'USD' else 'IRT'


def plan_price_usd(plan: Any) -> Decimal:
    meta = dict(getattr(plan, 'meta', None) or {})
    value = _decimal(meta.get('price_usd'))
    return value if value > 0 else Decimal('0')


def format_usd(value: Any) -> str:
    amount = _decimal(value)
    text = f'{amount:.4f}'.rstrip('0').rstrip('.')
    return text or '0'


def plan_price_label(plan: Any, *, toman_suffix: bool = True) -> str:
    if plan_currency(plan) == 'USD':
        return f'${format_usd(plan_price_usd(plan))}'
    amount = int(getattr(plan, 'price_irt', 0) or 0)
    return f'{amount:,} تومان' if toman_suffix else f'{amount:,}'


def update_plan_pricing_meta(meta: dict[str, Any] | None, *, pricing_currency: str, price_usd: Any) -> dict[str, Any]:
    result = dict(meta or {})
    currency = str(pricing_currency or 'IRT').strip().upper()
    if currency == 'USD':
        usd = _decimal(price_usd)
        if usd <= 0:
            raise ValueError('USD price must be greater than zero.')
        result['pricing_currency'] = 'USD'
        result['price_usd'] = format(usd, 'f')
    else:
        result.pop('pricing_currency', None)
        result.pop('price_usd', None)
    return result


def parse_wallex_rate(payload: Any) -> int:
    try:
        symbols = payload['result']['symbols']
        market = symbols[WALLEX_SYMBOL]
        stats = market['stats']
        raw = stats.get(WALLEX_RATE_FIELD) or stats.get('lastPrice')
        rate = _decimal(raw)
    except Exception as exc:
        raise LivePricingError('Wallex response does not contain USDTTMN price data.') from exc
    if rate <= 0:
        raise LivePricingError('Wallex returned an invalid USDTTMN price.')
    # USDTTMN is quoted in Toman, so no Rial/Toman conversion is required.
    return int(rate.to_integral_value(rounding=ROUND_HALF_UP))


async def wallex_usdt_tmn_rate(*, force_refresh: bool = False) -> tuple[int, datetime]:
    global _cached_rate_tmn, _cached_at_monotonic, _cached_fetched_at
    now = time.monotonic()
    if not force_refresh and _cached_rate_tmn and (now - _cached_at_monotonic) < _CACHE_TTL_SECONDS:
        return _cached_rate_tmn, _cached_fetched_at or datetime.now(timezone.utc)

    async with _cache_lock:
        now = time.monotonic()
        if not force_refresh and _cached_rate_tmn and (now - _cached_at_monotonic) < _CACHE_TTL_SECONDS:
            return _cached_rate_tmn, _cached_fetched_at or datetime.now(timezone.utc)
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS, follow_redirects=True) as client:
                response = await client.get(WALLEX_MARKETS_URL, headers={'Accept': 'application/json'})
                response.raise_for_status()
                payload = response.json()
            rate = parse_wallex_rate(payload)
        except LivePricingError:
            raise
        except Exception as exc:
            raise LivePricingError('Unable to fetch the live Wallex USD/USDT rate.') from exc

        fetched_at = datetime.now(timezone.utc)
        _cached_rate_tmn = rate
        _cached_at_monotonic = time.monotonic()
        _cached_fetched_at = fetched_at
        return rate, fetched_at


async def quote_plan(plan: Any, *, force_refresh: bool = False) -> PriceQuote:
    if plan_currency(plan) != 'USD':
        return PriceQuote(currency='IRT', amount_irt=max(int(getattr(plan, 'price_irt', 0) or 0), 0))

    usd = plan_price_usd(plan)
    if usd <= 0:
        raise LivePricingError('The selected plan does not have a valid USD price.')
    rate, fetched_at = await wallex_usdt_tmn_rate(force_refresh=force_refresh)
    total = (usd * Decimal(rate)).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
    return PriceQuote(
        currency='USD',
        amount_irt=max(int(total), 0),
        price_usd=usd,
        usd_rate_tmn=rate,
        source='Wallex USDTTMN askPrice',
        quoted_at=fetched_at,
    )


def quote_lines(quote: PriceQuote) -> str:
    if quote.currency != 'USD':
        return f'💰 مبلغ: {quote.amount_irt:,} تومان'
    return (
        f'💵 قیمت پایه: ${format_usd(quote.price_usd)}\n'
        f'💱 نرخ لحظه‌ای والکس: {int(quote.usd_rate_tmn or 0):,} تومان\n'
        f'💰 مبلغ قابل پرداخت: {quote.amount_irt:,} تومان'
    )


def quote_from_meta(meta: dict[str, Any] | None, *, fallback_irt: int = 0) -> PriceQuote:
    data = dict(meta or {})
    currency = str(data.get('currency') or 'IRT').upper()
    if currency != 'USD':
        return PriceQuote(currency='IRT', amount_irt=max(int(data.get('base_amount_irt') or fallback_irt or 0), 0))
    quoted_at = None
    raw_time = data.get('quoted_at')
    if raw_time:
        try:
            quoted_at = datetime.fromisoformat(str(raw_time).replace('Z', '+00:00'))
            if quoted_at.tzinfo is None:
                quoted_at = quoted_at.replace(tzinfo=timezone.utc)
        except Exception:
            quoted_at = None
    return PriceQuote(
        currency='USD',
        amount_irt=max(int(data.get('base_amount_irt') or fallback_irt or 0), 0),
        price_usd=_decimal(data.get('price_usd')),
        usd_rate_tmn=max(int(data.get('usd_rate_tmn') or 0), 0),
        source=str(data.get('source') or 'Wallex USDTTMN askPrice'),
        quoted_at=quoted_at,
    )
