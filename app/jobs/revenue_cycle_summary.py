from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.core.config import settings
from app.database.models import Order, Setting
from app.database.session import SessionLocal
from app.utils.jalali import fa_datetime

logger = logging.getLogger(__name__)

PAID_STATUSES = {'paid', 'approved', 'completed'}
CYCLE_DAYS = 30
REVENUE_ANCHOR_KEY = 'dashboard_revenue_anchor_utc'
REVENUE_ORIGINAL_KEY = 'dashboard_revenue_original_anchor_utc'
SUMMARY_NEXT_END_KEY = 'dashboard_revenue_summary_next_end_utc'
SUMMARY_LAST_END_KEY = 'dashboard_revenue_summary_last_end_utc'
SUMMARY_LAST_STATUS_KEY = 'dashboard_revenue_summary_last_status'
SUMMARY_LAST_MESSAGE_KEY = 'dashboard_revenue_summary_last_message'


def _parse_utc(value: str | None) -> datetime | None:
    raw = str(value or '').strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _localize_utc(value: datetime) -> datetime:
    try:
        tz = ZoneInfo(settings.TZ)
    except Exception:
        tz = timezone.utc
    return value.replace(tzinfo=timezone.utc).astimezone(tz)


def _cycle_containing(anchor: datetime, now: datetime) -> tuple[datetime, datetime]:
    if anchor > now:
        anchor = now
    elapsed = max(0, int((now - anchor).total_seconds() // timedelta(days=CYCLE_DAYS).total_seconds()))
    start = anchor + timedelta(days=elapsed * CYCLE_DAYS)
    return start, start + timedelta(days=CYCLE_DAYS)


def _is_aligned_cycle_end(anchor: datetime, end: datetime) -> bool:
    delta = end - anchor
    seconds = int(delta.total_seconds())
    cycle_seconds = CYCLE_DAYS * 24 * 60 * 60
    return seconds > 0 and seconds % cycle_seconds == 0


def _summary_text(start: datetime, end: datetime, sales_count: int, total_revenue: int) -> str:
    start_local = _localize_utc(start)
    end_local = _localize_utc(end)
    return (
        '📊 گزارش پایان دوره ۳۰ روزه فروش\n\n'
        f'🗓 شروع دوره: {fa_datetime(start_local)}\n'
        f'🏁 پایان دوره: {fa_datetime(end_local)}\n'
        f'🧾 تعداد رسید / فروش تاییدشده: {int(sales_count):,}\n'
        f'💰 مبلغ کل فروش: {int(total_revenue):,} تومان\n\n'
        '✅ دوره ۳۰ روزه بسته شد و دوره جدید به‌صورت خودکار آغاز شده است.'
    )


async def _setting_value(session, key: str) -> str | None:
    row = await session.get(Setting, key)
    return str(row.value) if row and row.value is not None else None


async def _save_setting(session, key: str, value: str) -> None:
    row = await session.get(Setting, key)
    if row:
        row.value = value
    else:
        session.add(Setting(key=key, value=value))


async def deliver_revenue_cycle_summary(bot) -> dict[str, object]:
    """Notify the primary owner once when each persisted 30-day revenue cycle ends.

    The first run only records the end of the currently active cycle, so enabling
    this feature does not backfill/spam old periods. The persisted next-end value
    survives restarts; if the bot was offline at period end, the report is sent
    on the next scheduler run. A manual Reset Display changes the anchor and also
    resets this next-end marker from the web endpoint.
    """
    owner_ids = [int(x) for x in (settings.owner_ids or settings.admin_ids or []) if int(x) > 0]
    if not owner_ids:
        return {'ok': False, 'skipped': True, 'message': 'No primary owner Telegram ID configured'}
    primary_owner_id = owner_ids[0]
    now = datetime.utcnow()

    async with SessionLocal() as session:
        anchor = _parse_utc(await _setting_value(session, REVENUE_ANCHOR_KEY))
        if anchor is None:
            anchor = _parse_utc(await _setting_value(session, REVENUE_ORIGINAL_KEY))
        if anchor is None:
            first_sale = await session.scalar(
                select(func.min(Order.created_at)).where(
                    Order.status.in_(PAID_STATUSES),
                    Order.amount_irt > 0,
                )
            )
            anchor = first_sale or now.replace(hour=0, minute=0, second=0, microsecond=0)
            await _save_setting(session, REVENUE_ORIGINAL_KEY, anchor.isoformat())
            await session.commit()

        _, current_end = _cycle_containing(anchor, now)
        next_end = _parse_utc(await _setting_value(session, SUMMARY_NEXT_END_KEY))

        # First deployment, or a manual anchor reset from an older build: start
        # tracking the active period instead of backfilling historic cycles.
        if next_end is None or not _is_aligned_cycle_end(anchor, next_end):
            await _save_setting(session, SUMMARY_NEXT_END_KEY, current_end.isoformat())
            await _save_setting(session, SUMMARY_LAST_STATUS_KEY, 'tracking')
            await _save_setting(session, SUMMARY_LAST_MESSAGE_KEY, f'Next revenue cycle summary: {current_end.isoformat()}')
            await session.commit()
            return {'ok': True, 'skipped': True, 'message': 'Revenue cycle summary tracking initialized'}

        if now < next_end:
            return {'ok': True, 'skipped': True, 'message': 'Revenue cycle is not due yet'}

        start = next_end - timedelta(days=CYCLE_DAYS)
        sales_count, total_revenue = (
            await session.execute(
                select(
                    func.count(Order.id),
                    func.coalesce(func.sum(Order.amount_irt), 0),
                ).where(
                    Order.status.in_(PAID_STATUSES),
                    Order.amount_irt > 0,
                    Order.created_at >= start,
                    Order.created_at < next_end,
                )
            )
        ).one()
        sales_count = int(sales_count or 0)
        total_revenue = int(total_revenue or 0)
        message = _summary_text(start, next_end, sales_count, total_revenue)

        try:
            await bot.send_message(primary_owner_id, message)
        except Exception as exc:
            logger.exception('Failed to send revenue cycle summary to primary owner')
            await _save_setting(session, SUMMARY_LAST_STATUS_KEY, 'error')
            await _save_setting(session, SUMMARY_LAST_MESSAGE_KEY, str(exc))
            await session.commit()
            return {'ok': False, 'message': str(exc)}

        await _save_setting(session, SUMMARY_LAST_END_KEY, next_end.isoformat())
        await _save_setting(session, SUMMARY_NEXT_END_KEY, (next_end + timedelta(days=CYCLE_DAYS)).isoformat())
        await _save_setting(session, SUMMARY_LAST_STATUS_KEY, 'ok')
        await _save_setting(session, SUMMARY_LAST_MESSAGE_KEY, message)
        await session.commit()
        return {
            'ok': True,
            'sent_to': primary_owner_id,
            'period_start': start.isoformat(),
            'period_end': next_end.isoformat(),
            'sales_count': sales_count,
            'total_revenue': total_revenue,
        }
