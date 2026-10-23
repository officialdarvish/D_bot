from __future__ import annotations

import logging
import os
import tempfile
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.services.sales_report import build_accounting_sales_pdf, collect_sales_report

logger = logging.getLogger(__name__)


def _now_local() -> datetime:
    try:
        return datetime.now(ZoneInfo(settings.TZ))
    except Exception:
        return datetime.now().astimezone()


def _parse_dt(value: str, tzinfo) -> datetime | None:
    raw = str(value or '').strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tzinfo)
        return dt.astimezone(tzinfo)
    except Exception:
        return None


async def deliver_monthly_sales_report(*, force: bool = False) -> dict[str, object]:
    """Send a detailed 30-day accounting PDF to the same Telegram target as backups.

    The scheduler may call this hourly; persistent timestamps make the actual
    delivery occur only once every 30 days. force=True is used by the web panel.
    """
    from app.api.admin_web import _effective_backup_chat_id, _save_settings_map, _settings_map, _telegram_send_backup, _telegram_token

    values = await _settings_map()
    if not force and str(values.get('monthly_sales_report_enabled') or '1') != '1':
        return {'ok': True, 'skipped': True, 'message': 'Monthly sales reporting is disabled'}

    now = _now_local(); interval = timedelta(days=30)
    last_success = _parse_dt(values.get('monthly_sales_report_last_sent_at', ''), now.tzinfo)
    anchor = last_success or _parse_dt(values.get('monthly_sales_report_anchor_at', ''), now.tzinfo)
    if not force:
        if anchor is None:
            await _save_settings_map({'monthly_sales_report_anchor_at': now.isoformat()})
            return {'ok': True, 'skipped': True, 'message': 'Monthly sales report schedule initialized'}
        if now < anchor + interval:
            return {'ok': True, 'skipped': True, 'message': 'Monthly sales report is not due yet'}
        last_attempt = _parse_dt(values.get('monthly_sales_report_last_attempt_at', ''), now.tzinfo)
        if last_attempt and now - last_attempt < timedelta(hours=1):
            return {'ok': True, 'skipped': True, 'message': 'Monthly sales report retry cooldown is active'}

    await _save_settings_map({'monthly_sales_report_last_attempt_at': now.isoformat()})
    destination = str(values.get('backup_destination') or 'channel').strip()
    target = _effective_backup_chat_id(destination, str(values.get('backup_chat_id') or values.get('backup_channel') or '').strip(), values)
    token = await _telegram_token(values)
    if not token or not target:
        message = 'Backup/Telegram destination is not configured.'
        await _save_settings_map({'monthly_sales_report_last_status': 'waiting', 'monthly_sales_report_last_message': message})
        return {'ok': False, 'message': message}

    end_dt = datetime.utcnow(); start_dt = end_dt - timedelta(days=30); path = ''
    try:
        payload = await collect_sales_report(start_dt, end_dt)
        pdf = build_accounting_sales_pdf(payload)
        fd, path = tempfile.mkstemp(prefix='dbot_sales_report_', suffix='.pdf')
        with os.fdopen(fd, 'wb') as fh: fh.write(pdf)
        top_plan = payload['plan_summary'][0]['plan'] if payload.get('plan_summary') else 'No completed sales'
        caption = (
            'D BOT - 30 Day Sales Accounting Report\n\n'
            f"Period: {payload.get('range_label')}\n"
            f"Completed sales: {payload.get('order_count', 0)}\n"
            f"Total revenue: {int(payload.get('total_revenue', 0)):,} Toman\n"
            f"Top plan: {top_plan}\n\n"
            'PDF includes a 3-day revenue chart, plan totals, payment summary and complete sales details.'
        )
        result = await _telegram_send_backup(token, target, path, destination, caption=caption, filename=f"dbot_sales_report_{end_dt.strftime('%Y%m%d')}.pdf", content_type='application/pdf')
        success = bool(result.get('ok'))
        values_to_save = {
            'monthly_sales_report_last_status': 'ok' if success else 'error',
            'monthly_sales_report_last_message': str(result.get('message') or ''),
            'monthly_sales_report_last_period_start': start_dt.isoformat(),
            'monthly_sales_report_last_period_end': end_dt.isoformat(),
        }
        if success:
            values_to_save.update({'monthly_sales_report_last_sent_at': now.isoformat(), 'monthly_sales_report_anchor_at': now.isoformat()})
        await _save_settings_map(values_to_save)
        return {**result, 'report': payload}
    except Exception as exc:
        logger.exception('Monthly sales report failed')
        await _save_settings_map({'monthly_sales_report_last_status': 'error', 'monthly_sales_report_last_message': f'Monthly report failed: {exc}'})
        return {'ok': False, 'message': f'Monthly report failed: {exc}'}
    finally:
        if path:
            try: os.unlink(path)
            except OSError: pass
