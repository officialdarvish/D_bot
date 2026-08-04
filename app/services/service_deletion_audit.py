from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from app.core.config import settings
from app.database.models import ClientService, Plan, Server, User
from app.utils.jalali import fa_date

logger = logging.getLogger(__name__)


def _display_username(value: Any) -> str:
    text = str(value or '').strip()
    if not text:
        return '-'
    return text if text.startswith('@') else f'@{text}'


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def _gb(value: Any) -> float:
    try:
        return max(int(value or 0), 0) / (1024 ** 3)
    except Exception:
        return 0.0


def _reason_label(reason: str | None) -> str:
    labels = {
        'user_delete': 'حذف دستی توسط کاربر',
        'reseller_delete': 'حذف دستی توسط نماینده',
        'expired': 'انقضای سرویس و پایان مهلت ۷۲ ساعته',
        'volume': 'اتمام حجم و پایان مهلت ۷۲ ساعته',
        'missing_on_panel': 'عدم وجود سرویس در پنل و پایان مهلت',
        'panel': 'غیرفعال شدن در پنل و پایان مهلت',
    }
    return labels.get(str(reason or '').lower(), str(reason or '-') or '-')


def _source_label(source: str | None) -> str:
    labels = {
        'user_manual': 'کاربر از بخش «کانفیگ‌های من»',
        'reseller_manual': 'نماینده از بخش مدیریت کانفیگ‌ها',
        'automatic_72h': 'سیستم حذف خودکار پس از ۷۲ ساعت',
    }
    return labels.get(str(source or '').lower(), str(source or '-') or '-')


def _panel_status_label(status: str | None) -> str:
    labels = {
        'deleted': '✅ از ربات و پنل حذف شد',
        'already_missing': '✅ از ربات حذف شد؛ قبلاً در پنل وجود نداشت',
        'queued': '🕓 از ربات حذف شد؛ حذف از پنل در صف تلاش مجدد است',
        'local_deleted': '🗑 از بخش کانفیگ‌های کاربر حذف شد',
    }
    return labels.get(str(status or '').lower(), str(status or '-') or '-')


async def build_service_deletion_snapshot(
    session,
    svc: ClientService,
    *,
    server: Server | None = None,
    plan: Plan | None = None,
    owner: User | None = None,
    actor: Any = None,
    source: str = 'automatic_72h',
    reason: str | None = None,
    deleted_at: datetime | None = None,
) -> dict:
    """Capture all fields needed for an admin deletion report before local removal."""
    if server is None and getattr(svc, 'server_id', None):
        server = await session.get(Server, svc.server_id)
    if plan is None and getattr(svc, 'plan_id', None):
        plan = await session.get(Plan, svc.plan_id)
    if owner is None and getattr(svc, 'user_id', None):
        owner = await session.get(User, svc.user_id)

    total_bytes = int(getattr(svc, 'total_bytes', 0) or 0)
    used_bytes = int(getattr(svc, 'used_bytes', 0) or 0)
    remaining_bytes = max(total_bytes - used_bytes, 0)

    actor_id = getattr(actor, 'id', None) if actor is not None else None
    actor_username = getattr(actor, 'username', None) if actor is not None else None
    actor_full_name = getattr(actor, 'full_name', None) if actor is not None else None

    return {
        'service_id': int(svc.id),
        'owner_user_id': int(svc.user_id) if svc.user_id is not None else None,
        'owner_telegram_id': int(owner.telegram_id) if owner and owner.telegram_id is not None else None,
        'owner_username': owner.username if owner else None,
        'owner_full_name': owner.full_name if owner else None,
        'actor_telegram_id': int(actor_id) if actor_id is not None else None,
        'actor_username': actor_username,
        'actor_full_name': actor_full_name,
        'deletion_source': source,
        'deletion_reason': reason,
        'client_username': svc.client_username,
        'panel_username': svc.xui_email or svc.client_username,
        'xui_email': svc.xui_email,
        'server_id': int(svc.server_id) if svc.server_id is not None else None,
        'server_name': server.name if server else '-',
        'server_type': server.server_type if server else '-',
        'plan_id': int(svc.plan_id) if svc.plan_id is not None else None,
        'plan_title': plan.title if plan else '-',
        'total_bytes': total_bytes,
        'used_bytes': used_bytes,
        'remaining_bytes': remaining_bytes,
        'created_at': _iso(svc.created_at),
        'expires_at': _iso(svc.expires_at),
        'disabled_at': _iso(getattr(svc, 'disabled_at', None)),
        'deleted_at': _iso(deleted_at or datetime.utcnow()),
        'is_reseller_service': bool(getattr(svc, 'reseller_id', None)),
    }


def admin_deletion_message(
    snapshot: dict,
    *,
    panel_status: str,
    task_id: int | None = None,
) -> str:
    total = int(snapshot.get('total_bytes') or 0)
    used = int(snapshot.get('used_bytes') or 0)
    remaining = int(snapshot.get('remaining_bytes') or max(total - used, 0))

    owner_username = _display_username(snapshot.get('owner_username'))
    actor_id = snapshot.get('actor_telegram_id')
    if actor_id:
        actor_line = (
            f'{snapshot.get("actor_full_name") or "-"} | '
            f'{_display_username(snapshot.get("actor_username"))} | '
            f'ID: {actor_id}'
        )
    else:
        actor_line = 'سیستم خودکار ربات'

    created_at = _as_datetime(snapshot.get('created_at'))
    expires_at = _as_datetime(snapshot.get('expires_at'))
    deleted_at = _as_datetime(snapshot.get('deleted_at'))
    task_line = f'\n🧾 شناسه صف حذف: #{task_id}' if task_id else ''

    return (
        '🗑 گزارش حذف کانفیگ\n'
        '━━━━━━━━━━━━━━━━\n'
        f'🔔 نوع عملیات: {_source_label(snapshot.get("deletion_source"))}\n'
        f'📌 دلیل: {_reason_label(snapshot.get("deletion_reason"))}\n'
        f'⚙️ وضعیت: {_panel_status_label(panel_status)}'
        f'{task_line}\n\n'
        '👤 مالک سرویس\n'
        f'• نام: {snapshot.get("owner_full_name") or "-"}\n'
        f'• یوزرنیم: {owner_username}\n'
        f'• Telegram ID: {snapshot.get("owner_telegram_id") or "-"}\n'
        f'• حذف‌کننده: {actor_line}\n\n'
        '🔐 مشخصات کانفیگ\n'
        f'• شناسه سرویس: #{snapshot.get("service_id") or "-"}\n'
        f'• نام کانفیگ: {snapshot.get("client_username") or "-"}\n'
        f'• یوزرنیم پنل: {snapshot.get("panel_username") or "-"}\n'
        f'• تعرفه: {snapshot.get("plan_title") or "-"}\n'
        f'• سرور: {snapshot.get("server_name") or "-"}\n'
        f'• نوع سرور: {snapshot.get("server_type") or "-"}\n'
        f'• حجم کل: {_gb(total):.2f} گیگ\n'
        f'• مصرف‌شده: {_gb(used):.2f} گیگ\n'
        f'• باقی‌مانده: {_gb(remaining):.2f} گیگ\n'
        f'• تاریخ ساخت: {fa_date(created_at) if created_at else "-"}\n'
        f'• تاریخ انقضا: {fa_date(expires_at) if expires_at else "-"}\n'
        f'• زمان حذف: {fa_date(deleted_at) if deleted_at else "-"}'
    )


async def notify_admins_service_deletion(
    bot,
    snapshot: dict,
    *,
    panel_status: str,
    task_id: int | None = None,
) -> bool:
    """Best-effort deletion report to all configured full-access owners."""
    if bot is None:
        return False
    admin_ids = list(dict.fromkeys(settings.owner_ids or settings.admin_ids or []))
    if not admin_ids:
        return False

    text = admin_deletion_message(snapshot, panel_status=panel_status, task_id=task_id)
    delivered = False
    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, text)
            delivered = True
        except Exception as exc:
            logger.warning(
                'Failed to notify admin %s about service deletion service_id=%s: %s',
                admin_id,
                snapshot.get('service_id'),
                exc,
            )
    return delivered
