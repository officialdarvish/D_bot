"""Refresh only the authenticated customer's traffic; never mutate panel users."""
import asyncio
from sqlalchemy import select, or_, and_
from app.database.models import ClientService, ResellerAccount, Server, User
from app.database.session import SessionLocal
from app.services.xui_service import XuiService
from app.services.pasarguard_service import PasarGuardService
from app.services.mikrotik_service import MikroTikService


async def read_usage(server, service):
    name = service.xui_email or service.client_username
    if server.server_type == 'xui':
        remote = await XuiService().find_client_any(server, name)
        if not remote:return None
        client, traffic = remote.get('client') or {}, remote.get('traffic') or {}
        used = remote.get('used_traffic')
        if used is None:used = int(traffic.get('up') or 0) + int(traffic.get('down') or 0)
        total = traffic.get('total')
        if total is None:total = client.get('totalGB')
        if total is None:total = service.total_bytes
    elif server.server_type == 'pasarguard':
        remote = await PasarGuardService().get_user(server, name)
        if not remote:return None
        used = remote.get('used_traffic', remote.get('used_bytes'))
        total = remote.get('data_limit')
        if total is None:total = service.total_bytes
    elif server.server_type == 'mikrotik':
        remote = await MikroTikService().get_user(server, name)
        if not remote:return None
        used = MikroTikService.logical_used_bytes(remote, service.traffic_baseline_bytes or 0, service.used_bytes or 0)
        total = MikroTikService.logical_total_bytes(remote, service.traffic_baseline_bytes or 0, service.total_bytes or 0)
    else:return None
    if used is None:return None
    return max(0, int(used)), max(0, int(total or 0))


async def refresh_usage(user_id, *, include_reseller=True):
    """Bound network concurrency; apply deltas serially under the owner's lock."""
    async with SessionLocal() as session:
        own_resellers = select(ResellerAccount.id).where(ResellerAccount.user_id == user_id)
        scope = and_(ClientService.user_id == user_id, ClientService.reseller_id.is_(None))
        if include_reseller:scope = or_(scope, ClientService.reseller_id.in_(own_resellers))
        rows = (await session.execute(select(ClientService, Server).join(Server, Server.id == ClientService.server_id).where(scope))).all()
        from app.services.service_grace import visible_in_my_services
        rows = [(svc, server) for svc, server in rows if visible_in_my_services(svc)]
    # Never keep a DB transaction open while waiting for a remote panel.
    def revision(svc):return (svc.user_id, svc.reseller_id, svc.server_id, svc.xui_email, svc.client_username, svc.xui_uuid, svc.total_bytes, svc.expires_at, svc.used_bytes)
    revisions = {svc.id:revision(svc) for svc, _ in rows}
    gate = asyncio.Semaphore(4)
    failed_servers = set()
    async def read(service, server):
        async with gate:
            if server.id in failed_servers:return service.id, None
            try:
                result = await asyncio.wait_for(read_usage(server, service), timeout=8)
                return service.id, result
            except Exception:
                failed_servers.add(server.id)
                return service.id, None
    samples = await asyncio.gather(*(read(service, server) for service, server in rows))
    async with SessionLocal() as session:
        # Concurrent tabs cannot double-add the same reseller usage delta.
        await session.get(User, user_id, with_for_update=True, populate_existing=True)
        from app.services.reseller_service import apply_reseller_usage_delta
        stale = set()
        for sid, sample in samples:
            if sample is None:
                stale.add(sid);continue
            service = await session.get(ClientService, sid, with_for_update=True)
            if not service or revision(service) != revisions[sid]:
                stale.add(sid);continue # A renewal/rotation won the race; read again next minute.
            await apply_reseller_usage_delta(session, service, sample[0])
            service.total_bytes = sample[1]
        await session.commit()
        return stale
