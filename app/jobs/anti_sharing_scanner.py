from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Iterable

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.security import decrypt_text
from app.database.defaults import get_setting_value
from app.database.models import AntiSharingViolation, ClientService, Plan, Server, User
from app.database.session import SessionLocal
from app.xui.client import XUIClient

logger = logging.getLogger(__name__)
_LAST_SCAN_AT: datetime | None = None


def _int(value: str | int | None, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except Exception:
        return default


def _short_ips(ips: Iterable[str], limit: int = 12) -> str:
    items = list(ips)
    shown = items[:limit]
    text = "\n".join(f"• {ip}" for ip in shown)
    if len(items) > limit:
        text += f"\n… و {len(items) - limit} آی‌پی دیگر"
    return text or "-"


def _same_ips(old: list | None, new: list[str]) -> bool:
    return sorted(str(x) for x in (old or [])) == sorted(str(x) for x in new)


def _plan_is_unlimited(plan: Plan | None) -> bool:
    if not plan or getattr(plan, 'is_payg', False):
        return False
    # Backward compatible: old VPN Bot plans used volume_gb=0 as unlimited.
    return bool(getattr(plan, 'is_unlimited', False) or int(getattr(plan, 'volume_gb', 0) or 0) <= 0)


def _plan_anti_sharing_enabled(plan: Plan | None) -> bool:
    return _plan_is_unlimited(plan) and bool(getattr(plan, 'anti_sharing_enabled', True))


async def _notify_owner(bot: Bot, text: str) -> None:
    for owner_id in settings.owner_ids:
        try:
            await bot.send_message(owner_id, text)
        except Exception as exc:
            logger.warning("Anti-sharing owner notify failed for %s: %s", owner_id, exc)


async def _notify_buyer(bot: Bot, user: User | None, text: str) -> None:
    if not user or not getattr(user, "telegram_id", None):
        return
    try:
        await bot.send_message(user.telegram_id, text)
    except Exception as exc:
        logger.warning("Anti-sharing buyer notify failed for %s: %s", getattr(user, "telegram_id", None), exc)


def _buyer_warning_text(*, service: ClientService, allowed: int, ip_count: int, action: str) -> str:
    if action == "temp_ban_24h":
        return (
            "🚫 سرویس شما به دلیل تکرار نقض قانون محدودیت تعداد کاربران به مدت ۲۴ ساعت مسدود شد.\n\n"
            f"📧 سرویس: {service.xui_email}\n"
            f"👤 تعداد مجاز: {allowed}\n"
            f"🌐 تعداد شناسایی‌شده: {ip_count}\n\n"
            "پس از پایان مدت مسدودیت، سرویس به صورت خودکار فعال خواهد شد."
        )
    if action == "permanent_ban":
        return (
            "🚫 سرویس شما به دلیل تکرار مکرر نقض قانون محدودیت تعداد کاربران به صورت دائمی مسدود شد.\n\n"
            f"📧 سرویس: {service.xui_email}\n"
            f"👤 تعداد مجاز: {allowed}\n"
            f"🌐 تعداد شناسایی‌شده: {ip_count}\n\n"
            "در صورت نیاز با پشتیبانی تماس بگیرید."
        )
    return (
        "⚠️ اخطار نقض قانون محدودیت کاربر\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "کاربر گرامی، در سرویس نامحدود شما تعداد کاربران متصل بیشتر از حد مجاز شناسایی شده است.\n\n"
        f"📧 سرویس: {service.xui_email}\n"
        f"👤 تعداد مجاز: {allowed}\n"
        f"🌐 تعداد شناسایی‌شده: {ip_count}\n\n"
        "لطفاً از اشتراک‌گذاری سرویس خودداری نمایید. در صورت تکرار، سرویس به صورت موقت یا دائمی مسدود خواهد شد."
    )


async def scan_anti_sharing(bot: Bot) -> None:
    """Scan 3x-ui recorded client IPs and apply anti-sharing rules.

    Uses 3x-ui 3.3.x official APIs:
      POST /panel/api/clients/onlines
      POST /panel/api/clients/ips/{email}
    It does not read access.log.
    """
    enabled = await get_setting_value("anti_sharing_enabled", "1")
    if enabled != "1":
        return

    global _LAST_SCAN_AT
    now = datetime.utcnow()
    scan_minutes = max(1, _int(await get_setting_value("anti_sharing_scan_minutes", "5"), 5))
    if _LAST_SCAN_AT and (now - _LAST_SCAN_AT) < timedelta(minutes=scan_minutes):
        return
    _LAST_SCAN_AT = now

    default_limit = _int(await get_setting_value("anti_sharing_default_ip_limit", "2"), 2)
    ban24_after = _int(await get_setting_value("anti_sharing_auto_ban_24h_after", "2"), 2)
    permanent_after = _int(await get_setting_value("anti_sharing_auto_ban_permanent_after", "3"), 3)
    batch_limit = max(25, _int(await get_setting_value("anti_sharing_batch_limit", "250"), 250))

    async with SessionLocal() as session:
        services = (await session.execute(
            select(ClientService).where(ClientService.is_active == True, ClientService.anti_share_banned_permanent == False).order_by(ClientService.server_id, ClientService.id).limit(batch_limit)
        )).scalars().all()
        plan_ids = sorted({s.plan_id for s in services if s.plan_id})
        plans = {pid: await session.get(Plan, pid) for pid in plan_ids}
        services = [s for s in services if _plan_anti_sharing_enabled(plans.get(s.plan_id))]

        server_ids = sorted({s.server_id for s in services})
        servers = {sid: await session.get(Server, sid) for sid in server_ids}

        # Auto-unban expired temporary bans first.
        for service in services:
            if getattr(service, "anti_share_banned_until", None) and not getattr(service, "anti_share_banned_permanent", False):
                if service.anti_share_banned_until <= now:
                    server = servers.get(service.server_id)
                    if server and server.server_type == "xui":
                        try:
                            xui = XUIClient(server.panel_url, server.username, decrypt_text(server.password_encrypted))
                            try:
                                if await xui.login():
                                    await xui.set_client_enabled(service.xui_email, True)
                            finally:
                                await xui.close()
                            service.anti_share_banned_until = None
                            service.anti_share_last_alert_at = now
                            await _notify_owner(bot, f"✅ بن موقت تمام شد و کانفیگ فعال شد.\n\n👤 {service.xui_email}")
                        except Exception as exc:
                            logger.warning("Anti-sharing auto-unban failed for %s: %s", service.xui_email, exc)
        await session.commit()

    # Scan grouped by server with one XUI login per server.
    async with SessionLocal() as session:
        services = (await session.execute(
            select(ClientService).where(ClientService.is_active == True, ClientService.anti_share_banned_permanent == False).order_by(ClientService.server_id, ClientService.id).limit(batch_limit)
        )).scalars().all()
        plan_ids = sorted({s.plan_id for s in services if s.plan_id})
        plans = {pid: await session.get(Plan, pid) for pid in plan_ids}
        services = [s for s in services if _plan_anti_sharing_enabled(plans.get(s.plan_id))]
        by_server: dict[int, list[ClientService]] = {}
        for service in services:
            by_server.setdefault(service.server_id, []).append(service)

        for server_id, server_services in by_server.items():
            server = await session.get(Server, server_id)
            if not server or server.server_type != "xui" or not server.is_active:
                continue
            xui = XUIClient(server.panel_url, server.username, decrypt_text(server.password_encrypted))
            try:
                if not await xui.login():
                    logger.warning("Anti-sharing login failed for server %s", server.name)
                    continue
                try:
                    online = set(await xui.get_online_clients())
                except Exception:
                    online = set()

                for service in server_services:
                    # Anti Sharing is intentionally enforced only on Unlimited plans.
                    # Volume/PAYG plans are skipped before grouping, because traffic limits already protect them.
                    if getattr(service, "anti_share_banned_permanent", False):
                        continue
                    if getattr(service, "anti_share_banned_until", None) and service.anti_share_banned_until > now:
                        continue
                    if online and service.xui_email not in online:
                        continue

                    allowed = int(getattr(service, "ip_limit", 0) or default_limit or 0)
                    if allowed <= 0:
                        continue

                    try:
                        ips = await xui.get_client_ips(service.xui_email)
                    except Exception as exc:
                        logger.warning("Anti-sharing get ips failed for %s: %s", service.xui_email, exc)
                        continue
                    ip_count = len(ips)
                    service.anti_share_last_ips = ips

                    if ip_count <= allowed:
                        # Reset only the visible current IP set; keep violation history in table.
                        continue

                    # Avoid spamming the owner with exactly the same IP set too often.
                    recently_alerted = bool(service.anti_share_last_alert_at and (now - service.anti_share_last_alert_at) < timedelta(minutes=20))
                    same_ips = _same_ips(getattr(service, "anti_share_last_ips", []), ips)

                    service.anti_share_violation_count = int(getattr(service, "anti_share_violation_count", 0) or 0) + 1
                    count = service.anti_share_violation_count
                    action = "warning"
                    if permanent_after > 0 and count >= permanent_after:
                        action = "permanent_ban"
                        service.anti_share_banned_permanent = True
                        await xui.set_client_enabled(service.xui_email, False)
                    elif ban24_after > 0 and count >= ban24_after:
                        action = "temp_ban_24h"
                        service.anti_share_banned_until = now + timedelta(hours=24)
                        await xui.set_client_enabled(service.xui_email, False)

                    violation = AntiSharingViolation(
                        service_id=service.id,
                        user_id=service.user_id,
                        server_id=service.server_id,
                        email=service.xui_email,
                        ip_count=ip_count,
                        allowed_ip=allowed,
                        ips=ips,
                        action=action,
                        status="open",
                    )
                    session.add(violation)
                    service.anti_share_last_alert_at = now
                    await session.commit()

                    if not (recently_alerted and same_ips and action == "warning"):
                        user = await session.get(User, service.user_id)
                        action_fa = {
                            "warning": "هشدار ثبت شد",
                            "temp_ban_24h": "بن ۲۴ ساعته اعمال شد",
                            "permanent_ban": "بن دائمی اعمال شد",
                        }.get(action, action)
                        owner_text = (
                            "🚨 اخطار نقض قانون محدودیت کاربر\n"
                            "━━━━━━━━━━━━━━━━\n\n"
                            f"👤 کاربر: {user.full_name if user else '-'}\n"
                            f"🆔 Telegram ID: {user.telegram_id if user else '-'}\n"
                            f"📧 Email: {service.xui_email}\n"
                            f"🖥 سرور: {server.name}\n"
                            f"🔢 حد مجاز IP: {allowed}\n"
                            f"🌐 تعداد IP شناسایی‌شده: {ip_count}\n"
                            f"⚠️ تعداد تخلف: {count}\n"
                            f"🚦 اقدام: {action_fa}\n\n"
                            f"IP List:\n{_short_ips(ips)}"
                        )
                        buyer_text = _buyer_warning_text(service=service, allowed=allowed, ip_count=ip_count, action=action)
                        await _notify_buyer(bot, user, buyer_text)
                        await _notify_owner(bot, owner_text)
            except Exception as exc:
                logger.exception("Anti-sharing scan failed on server %s: %s", server_id, exc)
            finally:
                await xui.close()
