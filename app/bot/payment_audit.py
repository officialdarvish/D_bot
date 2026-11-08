"""Consistent post-commit purchase/receipt summaries for bot owners.

Notifications are best-effort and never change payment state. No client
passwords, raw subscription URLs, or other secret credentials are included.
"""
from __future__ import annotations

import logging
from datetime import datetime
from html import escape

from app.core.config import settings
from app.database.models import ClientService, Order, Plan, Server, User
from app.database.session import SessionLocal

log = logging.getLogger(__name__)


def _text(value, fallback: str = 'ثبت نشده') -> str:
    return escape(str(value).strip(), quote=False) if value is not None and str(value).strip() else fallback


def date_label(value: datetime | None) -> str:
    # Stored timestamps are naive UTC across D Bot. Explicitly label the zone.
    return value.strftime('%Y-%m-%d %H:%M UTC') if value else 'نامشخص'


def payment_label(method: str | None) -> str:
    key = str(method or '').lower()
    if key.startswith('wallet_topup:'):
        return 'شارژ کیف پول (کارت به کارت)'
    if key.startswith('wallet_renew'):
        return 'تمدید با کیف پول'
    if key.startswith('wallet'):
        return 'خرید با کیف پول'
    if key.startswith('renew:'):
        return 'تمدید (کارت به کارت)'
    if key.startswith('card:'):
        return 'خرید (کارت به کارت)'
    if key.startswith('crypto:'):
        return 'خرید با رمزارز'
    if key.startswith('discount_renew'):
        return 'تمدید با تخفیف کامل'
    if key.startswith('admin_free'):
        return 'سرویس رایگان مدیر'
    return 'پرداخت'


def order_service_name(order: Order, service: ClientService | None = None) -> str:
    if service:
        return _text(service.client_username or service.xui_email)
    # Card and crypto purchases snapshot the requested client username in the method.
    method = str(order.payment_method or '')
    if method.startswith(('card:', 'crypto:')):
        return _text(method.split(':', 1)[1].split(':discount:', 1)[0])
    return 'هنوز ساخته نشده'


def order_summary(order: Order, user: User | None, plan: Plan | None = None,
                  server: Server | None = None, service: ClientService | None = None,
                  *, event: str = '🧾 جزئیات پرداخت') -> str:
    return '\n'.join([
        _text(event),
        f'🧾 شماره سفارش: #{order.id}',
        f'👤 نام خریدار: {_text(user.full_name if user else None)}',
        f'🔢 آیدی عددی: {_text(user.telegram_id if user else None)}',
        f'🆔 یوزرنیم تلگرام: @{_text((user.username or "").lstrip("@") if user else None)}' if user and user.username else '🆔 یوزرنیم تلگرام: ندارد',
        f'📦 مورد خریداری‌شده: {_text(plan.title if plan else "شارژ کیف پول" if str(order.payment_method or "").startswith("wallet_topup:") else "نامشخص")}',
        f'🖥 سرور: {_text(server.name if server else None)}',
        f'🔐 نام کانفیگ: {order_service_name(order, service)}',
        f'💳 روش پرداخت: {payment_label(order.payment_method)}',
        f'💰 مبلغ: {int(order.amount_irt or 0):,} تومان',
        f'📅 تاریخ خرید: {date_label(order.created_at)}',
        f'📋 وضعیت: {_text(order.status)}',
    ])


async def notify_paid_order(bot, order_id: int, *, event: str = '✅ پرداخت تأیید شد', reviewer_id: int | None = None) -> None:
    """After a successful commit, report the completed transaction to owners.

    The payment reviewer, if one exists, also gets a copy. Recipient failures
    cannot roll back a successful purchase or cause the buyer to be charged again.
    """
    if bot is None:
        return
    try:
        async with SessionLocal() as session:
            order = await session.get(Order, int(order_id))
            if not order or order.status != 'paid':
                return
            user = await session.get(User, order.user_id)
            plan = await session.get(Plan, order.plan_id) if order.plan_id else None
            service = await session.get(ClientService, order.service_id) if order.service_id else None
            server = await session.get(Server, service.server_id if service else plan.server_id) if (service and service.server_id) or (plan and plan.server_id) else None
            text = order_summary(order, user, plan, server, service, event=event)
            reviewer = reviewer_id or order.receipt_reviewer_telegram_id
    except Exception:
        log.exception("Failed to load audit details for successful order %s", order_id)
        return
    recipients = set()
    for candidate in [*(settings.admin_ids or []), *(settings.owner_ids or []), reviewer]:
        try:
            if int(candidate or 0) > 0:
                recipients.add(int(candidate))
        except (ValueError, TypeError):
            pass
    for telegram_id in recipients:
        try:
            await bot.send_message(telegram_id, text, parse_mode='HTML')
        except Exception:
            log.warning('Could not deliver payment audit order=%s to telegram_id=%s', order_id, telegram_id, exc_info=True)


async def notify_receipt_review(bot, text: str, *, reviewer_id: int | None = None) -> None:
    """Send a fresh approval event (not only a modified inline keyboard)."""
    recipients = set()
    for candidate in [*(settings.admin_ids or []), *(settings.owner_ids or []), reviewer_id]:
        try:
            if int(candidate or 0) > 0:
                recipients.add(int(candidate))
        except (TypeError, ValueError):
            pass
    for telegram_id in recipients:
        try:
            await bot.send_message(telegram_id, text, parse_mode=None)
        except Exception:
            log.warning('Could not deliver receipt approval notification to %s', telegram_id, exc_info=True)
