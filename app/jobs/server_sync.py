from __future__ import annotations

import logging
from datetime import datetime
from sqlalchemy import select
from app.database.session import SessionLocal
from app.database.models import Server, Plan, ResellerBuildConfig
from app.services.xui_service import XuiService

logger = logging.getLogger(__name__)



def _inbound_summary(row: dict) -> dict:
    """Return a stable, UI-friendly inbound summary from a panel row."""
    try:
        iid = int(row.get("id"))
    except Exception:
        return {}
    if iid <= 0:
        return {}
    return {
        "id": iid,
        "remark": row.get("remark") or row.get("tag") or row.get("name") or f"Inbound {iid}",
        "protocol": row.get("protocol") or row.get("proto") or "",
        "enable": bool(row.get("enable", row.get("enabled", True))),
    }

def _clean_inbound_ids(value) -> list[int]:
    ids: list[int] = []
    items = list(value) if isinstance(value, (list, tuple, set)) else ([] if value is None else [value])
    for item in items:
        if isinstance(item, dict):
            item = item.get("id") or item.get("inbound_id") or item.get("inboundId")
        try:
            iid = int(item)
        except Exception:
            continue
        if iid > 0 and iid not in ids:
            ids.append(iid)
    return ids

async def refresh_server_inbounds(session, server: Server, *, force_plan_update: bool = True) -> tuple[bool, list[int], list[int], str]:
    if not server or server.server_type != "xui":
        return True, [], [], ""
    old_ids = _clean_inbound_ids((server.meta or {}).get("inbound_ids") or [])
    try:
        ok, rows = await XuiService().test_server(server)
    except Exception as exc:
        return False, old_ids, old_ids, str(exc)
    if not ok:
        return False, old_ids, old_ids, "Login/List inbounds failed"
    inbound_rows = [_inbound_summary(r) for r in (rows or []) if isinstance(r, dict)]
    inbound_rows = [r for r in inbound_rows if r.get("id")]
    new_ids = _clean_inbound_ids([r.get("id") for r in inbound_rows])
    if not new_ids:
        return False, old_ids, old_ids, "No active inbound was returned by panel"
    meta = dict(server.meta or {})
    old_rows = meta.get("inbounds") or []
    changed = old_ids != new_ids or old_rows != inbound_rows
    if changed:
        meta["inbound_ids"] = new_ids
        meta["inbounds"] = inbound_rows
        meta["last_inbound_sync_at"] = datetime.utcnow().isoformat(timespec="seconds")
        server.meta = meta
    scope = meta.get("scope")
    # Always refresh public customer plans tied to this server when the current
    # panel inbounds are known. This fixes plan edits where the server changes
    # but stale inbound IDs remain attached to the plan.
    if force_plan_update:
        plans = (await session.execute(select(Plan).where(Plan.server_id == server.id))).scalars().all()
        for plan in plans:
            if server.server_type == "xui":
                plan.inbound_ids = new_ids
    if scope in {"reseller", "all"}:
        configs = (await session.execute(select(ResellerBuildConfig).where(ResellerBuildConfig.server_id == server.id))).scalars().all()
        for cfg in configs:
            cfg.inbound_ids = new_ids
    return True, old_ids, new_ids, ""

async def sync_all_servers() -> None:
    async with SessionLocal() as session:
        servers = (await session.execute(select(Server).where(Server.is_active == True, Server.server_type == "xui"))).scalars().all()
        changed = 0
        for server in servers:
            ok, old_ids, new_ids, err = await refresh_server_inbounds(session, server)
            if not ok:
                logger.warning("Server inbound sync failed server_id=%s name=%s: %s", server.id, server.name, err)
                continue
            if old_ids != new_ids:
                changed += 1
                logger.info("Server inbound IDs refreshed server_id=%s old=%s new=%s", server.id, old_ids, new_ids)
        if changed:
            await session.commit()
