"""Read purchased-panel configs without enrolling them in retail billing/sync."""
import asyncio
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from app.database.models import MiniAppOperation, PasarGuardPanelOrder, Server
from app.services.pasarguard_panel_meter import PanelMeterAPI


def configuration_data(op, panel, server, remote=None):
    saved = dict((op.result or {}).get('configuration') or {})
    request = op.payload
    total = int((remote or {}).get('data_limit', saved.get('total_bytes', request['volume'] * 1024**3)) or 0)
    used = int((remote or {}).get('used_traffic', saved.get('used_bytes', 0)) or 0)
    expiry = (remote or {}).get('expire', saved.get('expires_at'))
    if expiry is None:
        expiry = (op.created_at.replace(tzinfo=timezone.utc) + timedelta(days=request['days'])).isoformat()
    if isinstance(expiry, (int, float)):
        expiry = datetime.fromtimestamp(expiry, timezone.utc).isoformat()
    elif isinstance(expiry, datetime):
        expiry = expiry.isoformat()
    status = (remote or {}).get('status', saved.get('status', 'active'))
    try:
        parsed = datetime.fromisoformat(expiry.replace('Z', '+00:00'))
        if parsed.tzinfo is None:parsed = parsed.replace(tzinfo=timezone.utc)
        expired = parsed <= datetime.now(timezone.utc)
    except (ValueError, TypeError): expired = False
    return dict(id=-op.id, panel_id=panel.id, panel_operation_id=op.id, source='panel_reseller', source_label='نمایندگی',
        reseller=False, username=(op.result or {}).get('username') or request['username'], title='کانفیگ پنل نمایندگی',
        server=server.name, provider='pasarguard', total_bytes=total, used_bytes=used,
        remaining_bytes=max(total-used, 0) if total else None, unlimited=total == 0,
        active=status=='active' and not expired and (not total or used<total), expires_at=expiry,
        created_at=op.created_at.isoformat()+'Z')


async def panel_configurations(session, user):
    panels = (await session.execute(select(PasarGuardPanelOrder, Server).join(Server, Server.id==PasarGuardPanelOrder.server_id).where(
        PasarGuardPanelOrder.user_id==user.id, PasarGuardPanelOrder.status.in_(['approved','delivery_pending'])))).all()
    operations = (await session.execute(select(MiniAppOperation).where(MiniAppOperation.user_id==user.id,
        MiniAppOperation.kind=='panel_create', MiniAppOperation.status=='done').order_by(MiniAppOperation.id.desc()))).scalars().all()
    by_panel={p.id:(p,server) for p,server in panels}
    needed={op.payload.get('panel_id') for op in operations} & by_panel.keys()
    async def read(pid):
        panel,server=by_panel[pid]
        try:
            rows=await asyncio.wait_for(PanelMeterAPI().list_own_users(server,panel), timeout=4)
            return pid,{int(row['id']):row for row in rows}
        except Exception:return pid,None
    live=dict(await asyncio.gather(*(read(pid) for pid in needed)))
    result=[]
    for op in operations:
        if (op.result or {}).get('deleted'):continue
        pid=op.payload.get('panel_id')
        if pid not in by_panel:continue
        panel,server=by_panel[pid];rows=live.get(pid);remote_id=int((op.result or {}).get('remote_id') or 0)
        remote=rows.get(remote_id) if rows is not None else None
        # An authoritative empty/missing row indicates deletion or transfer.
        if rows is not None and remote is None:continue
        item=configuration_data(op,panel,server,remote)
        item['stale']=rows is None
        result.append(item)
    return result
