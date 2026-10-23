"""Provider-specific exact-byte and absolute-expiry operations for service conversion."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.plan_conversion import GIB, parse_panel_expiry
from app.services.xui_service import XuiService
from app.services.pasarguard_service import PasarGuardService
from app.xui.client import XUIClient
from app.core.security import decrypt_text


async def live_source(server, service):
    """Fetch authoritative remote quota/usage/expiry; never rely on stale local usage."""
    username = service.xui_email or service.client_username
    if server.server_type == 'xui':
        found = await XuiService().find_client_any(server, username)
        if not found or not found.get('client'):
            raise ValueError('Source client not found on Sanaei panel.')
        client = found['client']
        # /clients/get can omit usage in some versions. Never treat missing usage
        # as zero: that would convert already-consumed traffic a second time.
        traffic = await XuiService().query_client(server, username)
        if not isinstance(traffic, dict):
            raise ValueError('Sanaei usage endpoint is unavailable; conversion paused safely.')
        total = int(client.get('totalGB') or traffic.get('total') or traffic.get('totalGB') or 0)
        if 'usedTraffic' in traffic or 'used_traffic' in traffic:
            used = max(0, int(traffic.get('usedTraffic') or traffic.get('used_traffic') or 0))
        elif 'up' in traffic or 'down' in traffic:
            used = max(0, int(traffic.get('up') or 0) + int(traffic.get('down') or 0))
        else:
            raise ValueError('Sanaei did not report live used traffic; conversion paused safely.')
        if total <= 0:
            raise ValueError('Unlimited or unknown source traffic cannot be converted.')
        expiry = parse_panel_expiry(client.get('expiryTime'))
        enabled_flag = client.get('enable')
        if enabled_flag is not None and str(enabled_flag).strip().lower() in ('false', '0', 'no'):
            raise ValueError('Source client is disabled on panel.')
        return total, used, expiry
    if server.server_type == 'pasarguard':
        found = await PasarGuardService().get_user(server, username)
        if not found:
            raise ValueError('Source client not found on PasarGuard panel.')
        total = int(found.get('data_limit') or 0)
        if 'used_traffic' not in found and 'used_bytes' not in found:
            raise ValueError('PasarGuard did not report live usage; conversion paused safely.')
        used = int(found.get('used_traffic') or found.get('used_bytes') or 0)
        if total <= 0:
            raise ValueError('Unlimited or unknown source traffic cannot be converted.')
        expiry = parse_panel_expiry(found.get('expire'))
        if str(found.get('status') or '').lower() != 'active':
            raise ValueError('Source client is not active on panel.')
        return total, used, expiry
    raise ValueError('Conversion currently supports Sanaei / 3x-ui and PasarGuard only.')


async def set_enabled(server, username: str, enabled: bool):
    if server.server_type == 'xui':
        await XuiService().set_client_enabled(server, username, enabled)
        fresh = await XuiService().find_client_any(server, username)
        if not fresh or not fresh.get('client'):
            raise RuntimeError('Could not verify the source client status after disabling.')
        actual = fresh['client'].get('enable')
        active = actual if isinstance(actual, bool) else str(actual).lower() in ('1', 'true', 'yes')
        if active != enabled:
            raise RuntimeError('Sanaei did not confirm the client status change.')
    elif server.server_type == 'pasarguard':
        await PasarGuardService().set_enabled(server, username, enabled)
        fresh = await PasarGuardService().get_user(server, username)
        if not fresh or (str(fresh.get('status') or '').lower() == 'active') != enabled:
            raise RuntimeError('PasarGuard did not confirm the client status change.')
    else:
        raise ValueError('Unsupported provider for conversion')


async def set_exact_quota_and_expiry(server, username: str, quota_bytes: int, expires_at: datetime):
    if server.server_type == 'pasarguard':
        await PasarGuardService().update_user(server, username, data_limit_bytes=quota_bytes, expire_at=expires_at)
        found = await PasarGuardService().get_user(server, username)
        if not found or abs(int(found.get('data_limit') or 0) - quota_bytes) > 1024:
            raise RuntimeError('PasarGuard did not confirm the converted byte quota.')
        remote_expiry = parse_panel_expiry(found.get('expire'))
        if not remote_expiry or abs((remote_expiry - expires_at).total_seconds()) > 1:
            raise RuntimeError('PasarGuard did not confirm the inherited expiry.')
        return
    if server.server_type != 'xui':
        raise ValueError('Unsupported provider for conversion')
    xui = XUIClient(server.panel_url, server.username, decrypt_text(server.password_encrypted))
    try:
        if not await xui.login():
            raise RuntimeError('Could not log in to Sanaei to set exact expiry.')
        found = await xui.find_client(username)
        if not found or not found.get('client'):
            raise RuntimeError('New Sanaei client missing immediately after creation.')
        client = dict(found['client'])
        client['totalGB'] = int(quota_bytes)
        client['expiryTime'] = int(expires_at.replace(tzinfo=timezone.utc).timestamp() * 1000)
        await xui.update_client(username, client)
        confirmed = await xui.find_client(username)
        record = (confirmed or {}).get('client') or {}
        if abs(int(record.get('totalGB') or 0) - quota_bytes) > 1024:
            raise RuntimeError('Sanaei did not confirm exact converted quota.')
        if abs(int(record.get('expiryTime') or 0) - client['expiryTime']) > 1000:
            raise RuntimeError('Sanaei did not confirm inherited expiry.')
    finally:
        await xui.close()


async def create_converted(server, target_plan, username: str, target_bytes: int, expires_at: datetime):
    """Provision a new client using target-plan routing; finalize exact quota and expiry."""
    # Provider create calls take full days/GB. Provision an initial safe quota,
    # then set exact bytes and the old absolute expiry and verify read-back.
    days = max(1, math.ceil((expires_at - datetime.utcnow()).total_seconds() / 86400))
    initial_gb = max(1, math.ceil(target_bytes / GIB))
    surrogate = SimpleNamespace(
        volume_gb=initial_gb, duration_days=days,
        hwid_limit=target_plan.hwid_limit,
        inbound_ids=list(target_plan.inbound_ids or []),
        meta=dict(target_plan.meta or {}),
        server_id=server.id,
    )
    if server.server_type == 'xui':
        created = await XuiService().create_client_on_plan(server, surrogate, username)
    elif server.server_type == 'pasarguard':
        created = await PasarGuardService().create_user_on_plan(server, target_plan, username)
    else:
        raise ValueError('Unsupported target provider')
    await set_exact_quota_and_expiry(server, username, target_bytes, expires_at)
    return created


async def delete_converted_source(server, service):
    username = service.xui_email or service.client_username
    if server.server_type == 'xui':
        await XuiService().delete_client(server, service.xui_email, service.client_username, service.xui_uuid, service.sub_link)
    elif server.server_type == 'pasarguard':
        await PasarGuardService().delete_user(server, username)
