"""Category-priced remaining-quota transfers (no time/value double counting)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from html import escape

from app.database.models import Setting

GIB = 1024 ** 3
RULES_KEY = 'convert_category_rules'


def normalize_rules(raw: object) -> dict[str, dict]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return {}
    if not isinstance(raw, dict):
        return {}
    result = {}
    for category, rule in raw.items():
        if not isinstance(rule, dict):
            continue
        try:
            cid = int(category)
            price = int(rule.get('price_per_gb_irt') or 0)
        except (ValueError, TypeError):
            continue
        if cid <= 0 or price <= 0:
            continue
        ids = []
        for candidate in rule.get('server_ids') or []:
            try:
                sid = int(candidate)
            except (ValueError, TypeError):
                continue
            if sid > 0 and sid not in ids:
                ids.append(sid)
        result[str(cid)] = {'price_per_gb_irt': price, 'server_ids': ids}
    return result


async def load_rules(session) -> dict[str, dict]:
    setting = await session.get(Setting, RULES_KEY)
    return normalize_rules(setting.value if setting else None)


def quote_conversion(source_remaining_bytes: int, source_price: int, dest_price: int, expiry: datetime, now: datetime | None = None) -> dict:
    """Floor destination bytes to avoid granting monetary value we did not own."""
    now = now or datetime.utcnow()
    if expiry is None or expiry <= now:
        raise ValueError('The source service has expired.')
    if source_remaining_bytes <= 0:
        raise ValueError('The source service has no traffic remaining.')
    if source_price <= 0 or dest_price <= 0:
        raise ValueError('Both categories must have a positive per-GB conversion price.')
    remaining = int(source_remaining_bytes)
    dest_bytes = (remaining * int(source_price)) // int(dest_price)
    # Less than 1MB is not practically provisionable and could round to zero on a provider.
    if dest_bytes < 1024 ** 2:
        raise ValueError('The converted traffic would be less than 1 MB.')
    value_irt = (Decimal(remaining) * Decimal(source_price) / Decimal(GIB)).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
    return {
        'source_remaining_bytes': remaining,
        'destination_bytes': dest_bytes,
        'source_rate_irt': int(source_price),
        'destination_rate_irt': int(dest_price),
        'value_irt': str(value_irt),
        'expires_at': expiry,
        'remaining_seconds': int((expiry - now).total_seconds()),
    }


def format_volume(size: int) -> str:
    return f'{Decimal(int(size)) / Decimal(GIB):.3f}'


def parse_panel_expiry(value) -> datetime | None:
    if value in (None, '', 0, '0'):
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 1e11:
            timestamp /= 1000
        return datetime.utcfromtimestamp(timestamp) if timestamp > 0 else None
    try:
        return parse_panel_expiry(float(value)) if str(value).isdigit() else parse_panel_expiry(datetime.fromisoformat(str(value).replace('Z', '+00:00')))
    except (TypeError, ValueError, OverflowError):
        return None


# Readable Telegram HTML message for the customer-approved minimal conversion preview.
# Keep all prices in this renderer presentation-only; quote_conversion owns the math.
_PERSIAN_DIGITS = str.maketrans('0123456789,.', '۰۱۲۳۴۵۶۷۸۹٬٫')
_MONTHS_FA = (
    'ژانویه', 'فوریه', 'مارس', 'آوریل', 'مه', 'ژوئن',
    'ژوئیه', 'اوت', 'سپتامبر', 'اکتبر', 'نوامبر', 'دسامبر',
)


def _fa_number(value: object) -> str:
    return str(value).translate(_PERSIAN_DIGITS)


def _preview_category_name(name: str) -> str:
    """Keep the configured label, moving an initial VIP/price icon to the right side."""
    label = str(name or '').strip()
    for marker in ('⚡️', '⚡', '💰'):
        if label.startswith(marker):
            title = label[len(marker):].strip()
            if title:
                return f'{title} {marker}'
    return label


def format_conversion_preview(
    *, username: str, source_category: str, target_category: str,
    target_server: str, quote: dict,
) -> str:
    """Prepare the minimal 3-section HTML preview; never mutate the quoted values."""
    remaining_gb = format_volume(quote['source_remaining_bytes']).rstrip('0').rstrip('.')
    target_gb = format_volume(quote['destination_bytes']).rstrip('0').rstrip('.')
    # Amounts are displayed as whole tomans while internal math retains precision.
    amount_irt = Decimal(str(quote['value_irt'])).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
    amount_label = _fa_number(f'{int(amount_irt):,}')
    total_seconds = max(0, int(quote['remaining_seconds']))
    days, hours = total_seconds // 86400, (total_seconds % 86400) // 3600
    if days and hours:
        duration = f'{_fa_number(days)} روز و {_fa_number(hours)} ساعت'
    elif days:
        duration = f'{_fa_number(days)} روز'
    elif hours:
        duration = f'{_fa_number(hours)} ساعت'
    else:
        minutes = max(1, (total_seconds + 59) // 60)
        duration = f'{_fa_number(minutes)} دقیقه'
    expiry = quote['expires_at']
    expiry_label = (
        f'{_fa_number(expiry.day)} {_MONTHS_FA[expiry.month - 1]} '
        f'{_fa_number(expiry.year)}، ساعت {_fa_number(expiry.strftime("%H:%M"))} UTC'
    )
    return (
        '🔄 <b>پیش‌نمایش تبدیل تعرفه</b>\n'
        '──────────────\n'
        f'📱 <b>کانفیگ:</b> <code>{escape(str(username or ""))}</code>\n\n'
        f'<b>تعرفه فعلی:</b> {escape(_preview_category_name(source_category))}\n'
        f'<b>تعرفه جدید:</b> {escape(_preview_category_name(target_category))}\n'
        f'<b>سرور مقصد:</b> {escape(str(target_server))}\n\n'
        '──────────────\n'
        f'💾 <b>حجم باقی‌مانده:</b> {_fa_number(remaining_gb)} گیگابایت\n'
        f'💵 <b>ارزش باقی‌مانده:</b> {amount_label} تومان\n'
        f'✅ <b>حجم جدید:</b> {_fa_number(target_gb)} گیگابایت\n\n'
        '──────────────\n'
        f'⏳ <b>اعتبار باقی‌مانده:</b> {duration}\n'
        f'📅 <b>انقضا:</b> {expiry_label}\n\n'
        '⚠️ با تأیید نهایی، کانفیگ قبلی غیرفعال شده و پس از ساخت موفق کانفیگ جدید حذف می‌شود.'
    )
