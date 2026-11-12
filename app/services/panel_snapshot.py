"""Read-only panel snapshots, normalized to naive UTC database timestamps."""
import asyncio
import logging
from datetime import datetime, timezone

from app.services.xui_service import XuiService
from app.services.pasarguard_service import PasarGuardService
from app.services.mikrotik_service import MikroTikService
from app.services.reseller_service import apply_reseller_usage_delta, drop_inactive_reservation, lock_reseller_accounting
from app.services.service_grace import local_terminal_reason, mark_service_active, mark_service_disabled

logger = logging.getLogger(__name__)

GB = 1024**3
MB = 1024**2


def parse_panel_expiry(value, *, milliseconds=False):
    if value is None or str(value).strip().lower() in ('', '0', 'none', 'null'):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        date = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return date.astimezone(timezone.utc).replace(tzinfo=None) if date.tzinfo else date
    if number <= 0:  # X-UI negative expiry is an unstarted relative duration.
        return None
    if milliseconds or number > 100_000_000_000:
        number /= 1000
    return datetime.fromtimestamp(number, timezone.utc).replace(tzinfo=None)


def apply_panel_expiry(svc, remote, server_type):
    keys = ('expiryTime', 'expiry_time') if server_type == 'xui' else ('expire', 'expires_at', 'expire_at', 'expiry', 'expiration', 'valid_until')
    for key in keys:
        if key in remote:
            expiry = parse_panel_expiry(remote[key], milliseconds=server_type == 'xui')
            old = svc.expires_at
            svc.panel_expiry_pending = server_type == "xui" and str(remote[key]).startswith("-")
            svc.expires_at = expiry
            if old != expiry:
                for attr in ('notify_24h_sent', 'notify_2h_sent', 'notify_20m_sent'):
                    setattr(svc, attr, False)
            return True
    return False


def reset_volume_alerts(svc):
    remaining = max(int(svc.total_bytes or 0) - int(svc.used_bytes or 0), 0)
    for attr, threshold in (('notify_1gb_sent', GB), ('notify_500mb_sent', 500*MB), ('notify_100mb_sent', 100*MB)):
        if not svc.total_bytes or remaining > threshold:
            setattr(svc, attr, False)


PANEL_READ_TIMEOUT_SECONDS = 12


async def _read_panel_user(session, server, name):
    """Network reads only: never flush, refresh or update ORM records here."""
    if server.server_type == 'xui':
        cache = session.info.setdefault('alert_xui_panels', {}) if session.info.get('alert_scan') else None
        if cache is not None:
            if server.id not in cache:
                rows = await XuiService().list_client_snapshots(server)
                cache[server.id] = {str((r.get('client') or {}).get('email')): r for r in rows}
            found = cache[server.id].get(name)
            if found and found.get('usage_known', True):
                return found
        return await XuiService().find_client_any(server, name)
    if server.server_type in {'pasarguard','nx'}:
        return await PasarGuardService().get_user(server, name)
    if server.server_type == 'mikrotik':
        return await MikroTikService().get_user(server, name)
    raise ValueError('Unsupported panel type')


async def refresh_panel_snapshot(session, svc, *, server=None):
    """True=verified; False=confirmed missing; None=unavailable/invalid.

    Only the remote read has a deadline. Database work stays in the caller's
    task/transaction and failures propagate so that caller can roll it back.
    """
    from app.database.models import Server
    service_id, server_id = svc.id, svc.server_id
    server = server or (await session.get(Server, server_id) if server_id else None)
    if not server or server.server_type not in ('xui', 'pasarguard', 'nx', 'mikrotik'):
        return None
    kind = server.server_type
    name = svc.xui_email or svc.client_username
    try:
        found = await asyncio.wait_for(
            _read_panel_user(session, server, name), timeout=PANEL_READ_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        # Capture scalar identifiers before any awaited work. Never dereference
        # an expired ORM object while handling a failed transaction.
        logger.warning('Panel snapshot unavailable service_id=%s: %s', service_id, type(exc).__name__)
        return None

    # Do not dirty/lock a child service before its reseller account.
    await lock_reseller_accounting(session, getattr(svc, 'reseller_id', None))
    if not found:
        mark_service_disabled(svc, reason='missing_on_panel')
        if getattr(svc, 'reseller_id', None):
            await drop_inactive_reservation(session, svc)
        return False

    try:
        if kind == 'xui':
            remote = found.get('client') or {}
            traffic = found.get('traffic') or {}
            used = int(traffic.get('up') or 0) + int(traffic.get('down') or 0)
            total = traffic.get('total')
            if total is None:
                total = remote.get('totalGB', remote.get('total', svc.total_bytes))
            enabled = str(remote.get('enable', svc.is_active)).lower() not in ('false', '0', 'disabled')
        elif kind in {'pasarguard','nx'}:
            remote = found
            used = int(remote.get('used_traffic', remote.get('used_bytes', 0)) or 0)
            total = remote.get('data_limit', remote.get('total_bytes', svc.total_bytes))
            enabled = str(remote.get('status') or '').lower() == 'active'
        else:
            remote = found
            baseline = int(getattr(svc, 'traffic_baseline_bytes', 0) or 0)
            used = MikroTikService.logical_used_bytes(remote, baseline, svc.used_bytes or 0)
            total = MikroTikService.logical_total_bytes(remote, baseline, svc.total_bytes or 0)
            enabled = MikroTikService().user_is_active(remote, svc.is_active)
        total = max(int(total or 0), 0)
        if not apply_panel_expiry(svc, remote, kind):
            return None
    except (ValueError, TypeError, OverflowError, OSError) as exc:
        logger.warning('Invalid panel snapshot service_id=%s: %s', service_id, type(exc).__name__)
        return None

    # From here on exceptions belong to the database transaction, not the
    # panel connection. In particular, never swallow a flush/rollback error.
    if used < int(svc.used_bytes or 0) or total > int(svc.total_bytes or 0):
        for attr in ('notify_1gb_sent', 'notify_500mb_sent', 'notify_100mb_sent'):
            setattr(svc, attr, False)
    if kind != 'xui' or found.get('usage_known', True):
        await apply_reseller_usage_delta(session, svc, used)
    if kind != 'xui' or found.get('total_known', True):
        svc.total_bytes = total
    reset_volume_alerts(svc)
    if kind in {'pasarguard','nx'}:
        svc.sub_link = remote.get('subscription_url') or svc.sub_link
    reason = local_terminal_reason(svc)
    if enabled and reason is None:
        mark_service_active(svc)
    else:
        mark_service_disabled(svc, reason=reason or str(remote.get('status') or 'disabled_on_panel'))
        if getattr(svc, 'reseller_id', None):
            await drop_inactive_reservation(session, svc)
    return True


async def verified_panel_snapshot(session, svc):
    """Reuse only reads from this scan; database failures must reach rollback."""
    service_id, server_id = svc.id, svc.server_id
    cache = session.info.setdefault('verified_panel_snapshots', {})
    if service_id not in cache:
        failed = session.info.setdefault('snapshot_failed_servers', set())
        if server_id in failed:
            return None
        cache[service_id] = await refresh_panel_snapshot(session, svc)
        if cache[service_id] is None:
            failed.add(server_id)
    return cache[service_id]
