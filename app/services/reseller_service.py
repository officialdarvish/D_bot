from __future__ import annotations
from datetime import datetime, timedelta
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.models import ResellerAccount, ResellerPackage, ResellerTopupRequest, ResellerAccessRequest, ClientService, User, Server

GB = 1024 ** 3

def gb_to_bytes(value: float | int) -> int:
    return int(float(value) * GB)

def bytes_to_gb(value: int | None) -> float:
    return round((value or 0) / GB, 2)

def days_left(expires_at) -> int:
    if not expires_at:
        return 0
    return max((expires_at.date() - datetime.utcnow().date()).days, 0)

def is_reseller_access_active(reseller: ResellerAccount | None) -> bool:
    if not reseller or not reseller.is_active:
        return False
    if reseller.expires_at and reseller.expires_at < datetime.utcnow():
        return False
    return True

def _is_deleted_service(service: ClientService | None) -> bool:
    if not service:
        return True
    name = str(service.client_username or '')
    return name.startswith('deleted_')

def _service_reserved_bytes(service: ClientService | None) -> int:
    if not service or _is_deleted_service(service) or not bool(service.is_active):
        return 0
    return int(service.reseller_reserved_bytes or service.total_bytes or 0)

def remaining_bytes(reseller: ResellerAccount) -> int:
    """Current sellable reseller volume.

    In the reseller inventory model, ``total_bytes`` is the live sellable pool.
    Creating a 10GB client subtracts 10GB from this pool immediately.  Deleting
    that client returns only the unused part back to this pool.  ``used_bytes``
    is display-only historical traffic and ``reserved_bytes`` is the active
    allocation total; neither should be subtracted again here.
    """
    return max(int(reseller.total_bytes or 0), 0)

async def reconcile_reseller_accounting(session: AsyncSession, reseller: ResellerAccount | None, *, force_used_rebuild: bool = False) -> dict | None:
    """Keep reseller counters consistent with the inventory accounting model.

    Total     = current sellable volume still available to create users.
    Reserved  = volume allocated to active reseller-created users.
    Used      = cumulative traffic consumed by reseller users; display-only.
    Remaining = same as Total, because Total is the live sellable pool.
    """
    if not reseller:
        return None
    services = (await session.execute(
        select(ClientService).where(ClientService.reseller_id == reseller.id)
    )).scalars().all()
    active_services = [svc for svc in services if bool(svc.is_active) and not _is_deleted_service(svc)]
    reserved = sum(_service_reserved_bytes(svc) for svc in active_services)
    used_floor = sum(
        max(int(getattr(svc, 'reseller_lifetime_used_bytes', 0) or 0), int(svc.used_bytes or 0))
        for svc in services
    )
    reseller.total_bytes = max(int(reseller.total_bytes or 0), 0)
    reseller.reserved_bytes = int(reserved)
    if force_used_rebuild:
        # Admin repair action: overwrite an accidentally edited aggregate with
        # the exact sum retained on every reseller-created service.
        reseller.used_bytes = int(used_floor)
    else:
        reseller.used_bytes = max(int(reseller.used_bytes or 0), int(used_floor))
    return {
        'total_users': len(active_services),
        'used_bytes': int(reseller.used_bytes or 0),
        'total_bytes': int(reseller.total_bytes or 0),
        'reserved_bytes': int(reseller.reserved_bytes or 0),
        'remaining_bytes': remaining_bytes(reseller),
        'days_left': days_left(reseller.expires_at),
    }

async def apply_reseller_usage_delta(session: AsyncSession, service: ClientService, new_used_bytes: int) -> int:
    """Set service usage and add only positive traffic delta to reseller.used_bytes."""
    try:
        new_used = max(int(new_used_bytes or 0), 0)
    except Exception:
        new_used = 0
    old_used = max(int(service.used_bytes or 0), 0)
    lifetime_used = max(int(getattr(service, 'reseller_lifetime_used_bytes', 0) or 0), old_used)
    delta = max(new_used - old_used, 0)
    service.used_bytes = new_used
    if getattr(service, 'reseller_id', None):
        service.reseller_lifetime_used_bytes = lifetime_used + delta
        if delta:
            reseller = await session.get(ResellerAccount, service.reseller_id)
            if reseller:
                reseller.used_bytes = int(reseller.used_bytes or 0) + delta
    return delta

async def drop_inactive_reservation(session: AsyncSession, service: ClientService, reseller: ResellerAccount | None = None) -> int:
    """Remove an inactive service from Reserved without refunding Total.

    Inactivity/volume exhaustion only changes the active allocation counter.
    Sellable Total is credited only by explicit deletion or renewal settlement.
    """
    if not service or not getattr(service, 'reseller_id', None):
        return 0
    if reseller is None:
        reseller = await session.get(ResellerAccount, service.reseller_id)
    if not reseller:
        return 0
    allocated = int(service.reseller_reserved_bytes or service.total_bytes or 0)
    reseller.reserved_bytes = max(int(reseller.reserved_bytes or 0) - allocated, 0)
    service.reseller_reserved_bytes = 0
    await reconcile_reseller_accounting(session, reseller)
    return allocated


async def release_reserved_volume(session: AsyncSession, service: ClientService, reseller: ResellerAccount | None = None) -> int:
    """Settle a reseller-created service and return only its unused volume.

    Example: a reseller creates a 10GB user, so 10GB is removed from the
    sellable pool.  If the user consumed 4GB before deletion/expiry, only 6GB
    returns to the reseller.  If the full 10GB was consumed, nothing returns.
    Historical traffic remains in reseller.used_bytes for display/reporting.
    """
    if not service.reseller_id:
        return 0
    if reseller is None:
        reseller = await session.get(ResellerAccount, service.reseller_id)
    if not reseller:
        return 0

    # Best effort: refresh the panel counter before settling, so a manual delete
    # returns the correct unused amount. Failures must not block local cleanup.
    try:
        await sync_reseller_service_panel_snapshot(session, service)
    except Exception:
        pass

    allocated = int(service.reseller_reserved_bytes or service.total_bytes or 0)
    if allocated <= 0:
        await reconcile_reseller_accounting(session, reseller)
        return 0
    used = max(int(service.used_bytes or 0), 0)
    unused = max(allocated - used, 0)

    reseller.total_bytes = max(int(reseller.total_bytes or 0), 0) + unused
    reseller.reserved_bytes = max(int(reseller.reserved_bytes or 0) - allocated, 0)
    service.reseller_reserved_bytes = 0
    await reconcile_reseller_accounting(session, reseller)
    return unused


def _service_identifier_candidates(service: ClientService | None) -> list[str]:
    values: list[str] = []
    if not service:
        return values
    for raw in (
        getattr(service, 'xui_email', None),
        getattr(service, 'client_username', None),
        getattr(service, 'xui_uuid', None),
        getattr(service, 'sub_link', None),
    ):
        text = str(raw or '').strip()
        if not text:
            continue
        if text not in values:
            values.append(text)
        if text.startswith(('http://', 'https://')):
            token = text.rstrip('/').split('/')[-1].strip()
            if token and token not in values:
                values.append(token)
    return values


def _server_is_reseller_like(server: Server | None) -> bool:
    if not server:
        return False
    meta = getattr(server, 'meta', None) or {}
    scope = meta.get('scope')
    return scope in {'reseller', 'all', 'reseller_deleted'}


async def _candidate_servers_for_reseller_service(session: AsyncSession, service: ClientService) -> list[Server]:
    """Return server records that may still contain a reseller-created client.

    Existing reseller users must not disappear from the DB/UI simply because a
    server was edited, refreshed, detached, or archived.  The service row itself
    is the source of truth for ownership; panel lookups are used only to repair
    the server link and update live usage.
    """
    candidates: list[Server] = []
    seen: set[int] = set()
    if getattr(service, 'server_id', None):
        current = await session.get(Server, service.server_id)
        if current:
            candidates.append(current)
            seen.add(current.id)
    rows = (await session.execute(select(Server).order_by(Server.id.desc()))).scalars().all()
    for server in rows:
        if server.id in seen:
            continue
        if not _server_is_reseller_like(server):
            continue
        candidates.append(server)
        seen.add(server.id)
    return candidates


async def sync_reseller_service_panel_snapshot(session: AsyncSession, service: ClientService) -> bool | None:
    """Find a reseller-created user on the panel by its saved username and repair DB fields.

    This is intentionally conservative: it never deletes or hides a DB record.
    It only attaches the service to the server where the username is found and
    refreshes usage/expiry/link fields.  This keeps reseller services visible
    after server edits or archived/deleted server records.
    """
    if not service or not getattr(service, 'reseller_id', None):
        return None
    identifiers = _service_identifier_candidates(service)
    if not identifiers:
        return None

    # Local imports avoid making the reseller accounting module part of the
    # bot/API import graph at startup.
    from app.services.xui_service import XuiService
    from app.services.mikrotik_service import MikroTikService

    for server in await _candidate_servers_for_reseller_service(session, service):
        try:
            if server.server_type == 'xui':
                found = await XuiService().find_client_by_identifiers(server, *identifiers)
                if not found:
                    continue
                client = found.get('client') or {}
                traffic = found.get('traffic') or {}
                panel_email = str(client.get('email') or service.xui_email or service.client_username or '').strip()
                if panel_email:
                    service.xui_email = panel_email
                if not service.client_username and panel_email:
                    service.client_username = panel_email
                service.server_id = server.id
                inbound_ids = found.get('inbound_ids') or []
                if inbound_ids:
                    service.inbound_ids = inbound_ids
                sub_id = client.get('subId') or client.get('sub_id') or traffic.get('subId') or traffic.get('sub_id')
                if sub_id:
                    service.sub_link = XuiService().build_subscription_link(server, str(sub_id), panel_email or service.client_username)
                uuid_val = client.get('uuid') or client.get('id') or client.get('password') or client.get('auth')
                if uuid_val and not str(uuid_val).isdigit():
                    service.xui_uuid = str(uuid_val)
                raw_used = int((traffic.get('up', 0) or 0) + (traffic.get('down', 0) or 0))
                await apply_reseller_usage_delta(session, service, raw_used)
                total = traffic.get('total') or client.get('totalGB') or client.get('total')
                if total:
                    try:
                        service.total_bytes = int(total)
                    except Exception:
                        pass
                if 'enable' in client:
                    service.is_active = bool(client.get('enable'))
                await session.flush()
                return True
            if server.server_type == 'mikrotik':
                for ident in identifiers:
                    found = await MikroTikService().get_user(server, ident)
                    if not found:
                        continue
                    service.server_id = server.id
                    service.xui_email = str(found.get('username') or ident).strip() or service.xui_email
                    if not service.client_username:
                        service.client_username = service.xui_email
                    await apply_reseller_usage_delta(session, service, int(found.get('used_bytes') or 0))
                    if found.get('volume_bytes') is not None:
                        service.total_bytes = int(found.get('volume_bytes') or service.total_bytes or 0)
                    service.is_active = not bool(found.get('disabled') or found.get('expired'))
                    await session.flush()
                    return True
        except Exception:
            continue
    return False


async def repair_reseller_services_from_panels(session: AsyncSession, reseller: ResellerAccount | None) -> int:
    """Repair missing/stale server links for a reseller before rendering lists."""
    if not reseller:
        return 0
    services = (await session.execute(
        select(ClientService).where(ClientService.reseller_id == reseller.id)
    )).scalars().all()
    repaired = 0
    for service in services:
        if _is_deleted_service(service):
            continue
        needs_repair = not getattr(service, 'server_id', None)
        if not needs_repair and getattr(service, 'server_id', None):
            srv = await session.get(Server, service.server_id)
            needs_repair = srv is None
        if needs_repair:
            ok = await sync_reseller_service_panel_snapshot(session, service)
            if ok:
                repaired += 1
    return repaired

async def get_user_reseller(session: AsyncSession, telegram_id: int) -> tuple[User | None, ResellerAccount | None]:
    user = (await session.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one_or_none()
    if not user:
        return None, None
    reseller = (await session.execute(select(ResellerAccount).where(ResellerAccount.user_id == user.id))).scalar_one_or_none()
    return user, reseller

async def get_reseller_access_request(session: AsyncSession, user_id: int) -> ResellerAccessRequest | None:
    return (await session.execute(select(ResellerAccessRequest).where(ResellerAccessRequest.user_id == user_id))).scalar_one_or_none()

async def create_reseller_access_request(session: AsyncSession, user_id: int) -> ResellerAccessRequest:
    req = await get_reseller_access_request(session, user_id)
    if req:
        if req.status == 'rejected':
            req.status = 'pending'
            req.reviewed_by = None
            req.reviewed_at = None
            req.created_at = datetime.utcnow()
        await session.flush()
        return req
    req = ResellerAccessRequest(user_id=user_id, status='pending')
    session.add(req)
    await session.flush()
    return req

async def approve_reseller_access(session: AsyncSession, request: ResellerAccessRequest, reviewer_telegram_id: int | None = None) -> ResellerAccount:
    request.status = 'approved'
    request.reviewed_by = reviewer_telegram_id
    request.reviewed_at = datetime.utcnow()
    reseller = await ensure_reseller_for_user(session, request.user_id, None, 0)
    reseller.is_active = True
    if reseller.expires_at and reseller.expires_at < datetime.utcnow():
        reseller.expires_at = None
    await session.flush()
    return reseller

async def reject_reseller_access(session: AsyncSession, request: ResellerAccessRequest, reviewer_telegram_id: int | None = None) -> None:
    request.status = 'rejected'
    request.reviewed_by = reviewer_telegram_id
    request.reviewed_at = datetime.utcnow()
    await session.flush()

async def ensure_reseller_for_user(session: AsyncSession, user_id: int, server_id: int | None, validity_days: int = 365) -> ResellerAccount:
    reseller = (await session.execute(select(ResellerAccount).where(ResellerAccount.user_id == user_id))).scalar_one_or_none()
    if reseller:
        if server_id and not reseller.server_id:
            reseller.server_id = server_id
        await reconcile_reseller_accounting(session, reseller)
        return reseller
    reseller = ResellerAccount(user_id=user_id, server_id=server_id, total_bytes=0, used_bytes=0, reserved_bytes=0, expires_at=(datetime.utcnow() + timedelta(days=validity_days) if validity_days else None), is_active=True)
    session.add(reseller)
    await session.flush()
    return reseller

async def apply_package(session: AsyncSession, request: ResellerTopupRequest) -> ResellerAccount:
    pkg = await session.get(ResellerPackage, request.package_id)
    reseller = await ensure_reseller_for_user(session, request.user_id, pkg.server_id if pkg else None, pkg.reseller_validity_days if pkg else 365)
    reseller.total_bytes = (reseller.total_bytes or 0) + (request.volume_bytes or 0)
    if pkg and pkg.server_id:
        reseller.server_id = pkg.server_id
    now = datetime.utcnow()
    add_days = pkg.reseller_validity_days if pkg else 365
    base = reseller.expires_at if reseller.expires_at and reseller.expires_at > now else now
    reseller.expires_at = base + timedelta(days=add_days)
    reseller.is_active = True
    request.reseller_id = reseller.id
    request.status = 'approved'
    await reconcile_reseller_accounting(session, reseller)
    await session.flush()
    return reseller

async def reserve_volume_for_service(session: AsyncSession, reseller: ResellerAccount, bytes_amount: int) -> None:
    """Spend reseller sellable volume and reserve it for a new/updated service."""
    if bytes_amount <= 0:
        raise ValueError('حجم باید بیشتر از صفر باشد.')
    await reconcile_reseller_accounting(session, reseller)
    available = remaining_bytes(reseller)
    if available < bytes_amount:
        raise ValueError('حجم باقی‌مانده نمایندگی کافی نیست.')
    reseller.total_bytes = max(int(reseller.total_bytes or 0) - int(bytes_amount or 0), 0)
    reseller.reserved_bytes = int(reseller.reserved_bytes or 0) + int(bytes_amount or 0)
    await session.flush()

async def refund_unused_volume(session: AsyncSession, service: ClientService, reseller: ResellerAccount | None = None) -> int:
    # Backward-compatible name used by existing handlers.
    return await release_reserved_volume(session, service, reseller)

async def reseller_stats(session: AsyncSession, reseller: ResellerAccount) -> dict:
    stats = await reconcile_reseller_accounting(session, reseller)
    if stats is None:
        return {
            'total_users': 0,
            'used_bytes': 0,
            'total_bytes': 0,
            'reserved_bytes': 0,
            'remaining_bytes': 0,
            'days_left': 0,
        }
    return stats
