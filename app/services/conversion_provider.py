"""Provider-specific exact-byte and absolute-expiry operations for service conversion."""
from __future__ import annotations

import math
import asyncio
import logging
import time

import httpx
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


logger = logging.getLogger(__name__)


class ConversionStateUnconfirmed(RuntimeError):
    """The source claim must stay held; no destination may be created."""


def _ambiguous_transport_error(error):
    return isinstance(error, (httpx.TimeoutException, httpx.ReadError, httpx.WriteError,
                              httpx.RemoteProtocolError, TimeoutError)) or getattr(error, 'error_code', '') in {
        'ReadTimeout', 'WriteTimeout', 'ReadError', 'WriteError', 'RemoteProtocolError'}


def _status_matches(kind, found, enabled):
    if not isinstance(found, dict): return False
    if kind == 'xui':
        value = (found.get('client') or {}).get('enable')
        if value is None: return False
        if isinstance(value, bool): return value == enabled
        normalized = str(value).strip().lower()
        if normalized not in {'1','true','yes','0','false','no'}: return False
        return (normalized in {'1','true','yes'}) == enabled
    status = str(found.get('status') or '').strip().lower()
    disabled = any(value is True or str(value).strip().lower() in {'1','true','yes','on'}
                   for value in (found.get('disabled'), found.get('is_disabled')))
    # Missing, expired, limited or on-hold is not evidence that our disable
    # operation committed. The independent PasarGuard disable flag is explicit.
    return status == 'active' and not disabled if enabled else status == 'disabled' or disabled


async def _confirm_readback(read, predicate, message, write_error=None, error_type=RuntimeError):
    """Bound confirmation reads to 15 seconds; this helper never mutates panels."""
    deadline = time.monotonic() + 15.0
    last_error = None
    for delay in (0, 0.25, 0.75, 1.5):
        remaining = deadline - time.monotonic()
        if remaining <= delay: break
        if delay: await asyncio.sleep(delay)
        try:
            async with asyncio.timeout(min(4.0, deadline-time.monotonic())):
                fresh = await read()
            if predicate(fresh):
                if write_error:
                    logger.warning('Conversion write confirmed by read-back after lost response (%s)', type(write_error).__name__)
                return
        except Exception as exc:
            last_error = exc
    error = error_type(message)
    raise error from (write_error or last_error)


async def set_enabled(server, username: str, enabled: bool):
    """Write once, then verify with bounded reads, including after lost replies.

    Never replay a timed-out mutation. A GET must explicitly confirm the desired
    state before the caller can provision the converted destination.
    """
    if server.server_type == 'xui':
        provider = XuiService()
        write = provider.set_client_enabled
        read = provider.find_client_any
        label = 'Sanaei'
    elif server.server_type == 'pasarguard':
        provider = PasarGuardService()
        write = provider.set_enabled
        read = provider.get_user
        label = 'PasarGuard'
    else:
        raise ValueError('Unsupported provider for conversion')
    write_error = None
    try:
        await write(server, username, enabled)
    except Exception as exc:
        if not _ambiguous_transport_error(exc): raise
        write_error = exc
    await _confirm_readback(lambda: read(server,username),
        lambda fresh: _status_matches(server.server_type,fresh,enabled),
        f'{label} did not confirm the client status change; destination creation was not started.',
        write_error,ConversionStateUnconfirmed)


async def set_exact_quota_and_expiry(server, username: str, quota_bytes: int, expires_at: datetime):
    if server.server_type == 'pasarguard':
        provider=PasarGuardService()
        write_error=None
        try:
            await provider.update_user(server, username, data_limit_bytes=quota_bytes, expire_at=expires_at)
        except Exception as exc:
            if not _ambiguous_transport_error(exc): raise
            write_error=exc
        def matches(found):
            if not isinstance(found,dict) or 'data_limit' not in found:return False
            remote_expiry=parse_panel_expiry(found.get('expire'))
            return int(found['data_limit'])==quota_bytes and bool(remote_expiry and abs((remote_expiry-expires_at).total_seconds())<=1)
        await _confirm_readback(lambda:provider.get_user(server,username),matches,
            'PasarGuard did not confirm exact converted quota and inherited expiry.',write_error)
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
        write_error=None
        try:
            await xui.update_client(username, client)
        except Exception as exc:
            if not _ambiguous_transport_error(exc): raise
            write_error=exc
        def matches(found):
            record=(found or {}).get('client') or {}
            return ('totalGB' in record and int(record['totalGB'])==quota_bytes
                    and 'expiryTime' in record and abs(int(record['expiryTime'])-client['expiryTime'])<=1000)
        await _confirm_readback(lambda:xui.find_client(username),matches,
            'Sanaei did not confirm exact converted quota and inherited expiry.',write_error)
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
