from __future__ import annotations

import logging
from datetime import datetime
from sqlalchemy import select
from app.database.session import SessionLocal
from app.database.models import Server, Plan, ResellerBuildConfig, ClientService
from app.services.xui_service import XuiService
from app.services.mikrotik_service import MikroTikService

logger = logging.getLogger(__name__)


async def sync_mikrotik_usage() -> None:
    """Refresh used/volume/expiry/active state for MikroTik client services.

    The MikroTik panel itself enforces expiry and volume limits; this job only
    mirrors that state back into the bot DB so the "My services" page, the
    low-volume / near-expiry alerts (scan_service_alerts) and PAYG logic all
    operate on fresh data instead of the values captured at purchase time.
    """
    async with SessionLocal() as session:
        servers = {
            s.id: s for s in (await session.execute(
                select(Server).where(Server.is_active == True, Server.server_type == "mikrotik")
            )).scalars().all()
        }
        if not servers:
            return
        services = (await session.execute(
            select(ClientService).where(
                ClientService.is_active == True,
                ClientService.server_id.in_(list(servers.keys())),
            )
        )).scalars().all()
        changed = 0
        for svc in services:
            server = servers.get(svc.server_id)
            if not server:
                continue
            try:
                found = await MikroTikService().get_user(server, svc.xui_email or svc.client_username)
            except Exception as exc:
                logger.warning("MikroTik usage sync failed service_id=%s: %s", svc.id, exc)
                continue
            if not found:
                # None => panel returned not-found; leave the record for the
                # interactive detail page to clean up so we don't delete here.
                continue
            try:
                svc.used_bytes = int(found.get("used_bytes") or 0)
                svc.total_bytes = int(found.get("volume_bytes") or svc.total_bytes or 0)
                svc.is_active = not bool(found.get("disabled") or found.get("expired"))
                exp = found.get("expire_at")
                if exp:
                    svc.expires_at = datetime.fromisoformat(str(exp)[:10])
                changed += 1
            except Exception as exc:
                logger.warning("MikroTik usage parse failed service_id=%s: %s", svc.id, exc)
                continue
        if changed:
            await session.commit()
            logger.info("MikroTik usage sync updated %s service(s)", changed)



async def refresh_mikrotik_server(session, server: Server) -> tuple[bool, str]:
    """Refresh MikroTik / Custom router status metadata from /api/routers."""
    if not server or server.server_type != "mikrotik":
        return True, ""
    try:
        routers = await MikroTikService().routers(server)
    except Exception as exc:
        return False, str(exc)
    meta = dict(server.meta or {})
    router_name = str(meta.get("router_name") or server.username or "").strip()
    matched = None
    for row in routers:
        if str(row.get("name") or "").strip().lower() == router_name.lower():
            matched = row
            break
    matched = matched or (routers[0] if routers else {})
    if matched:
        meta.update({
            "custom_panel": True,
            "custom_panel_name": "MikroTik / Custom",
            "router_name": str(matched.get("name") or router_name).strip(),
            "router_host": matched.get("host") or "",
            "router_port": matched.get("port") or "",
            "router_online": bool(matched.get("online", True)),
            "router_identity": matched.get("identity") or "",
            "router_version": matched.get("version") or "",
            "router_uptime": matched.get("uptime") or "",
            "router_secrets": int(matched.get("secrets") or 0),
            "router_active": int(matched.get("active") or 0),
            "router_error": matched.get("error") or "",
            "routers_snapshot": routers,
            "last_router_sync_at": datetime.utcnow().isoformat(timespec="seconds"),
        })
        server.username = str(matched.get("name") or router_name).strip()
        server.is_active = bool(matched.get("online", True))
        server.meta = meta
    return True, ""


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
    """Auto-refresh all active servers every scheduler run.

    X-UI/Sanaei: refresh inbound IDs and push changes into plans.
    MikroTik / Custom: refresh router status/counts/version and mirror client usage.
    """
    async with SessionLocal() as session:
        servers = (await session.execute(select(Server).where(Server.is_active == True))).scalars().all()
        changed = 0
        for server in servers:
            if server.server_type == "xui":
                ok, old_ids, new_ids, err = await refresh_server_inbounds(session, server)
                if not ok:
                    logger.warning("Server inbound sync failed server_id=%s name=%s: %s", server.id, server.name, err)
                    continue
                if old_ids != new_ids:
                    changed += 1
                    logger.info("Server inbound IDs refreshed server_id=%s old=%s new=%s", server.id, old_ids, new_ids)
            elif server.server_type == "mikrotik":
                ok, err = await refresh_mikrotik_server(session, server)
                if not ok:
                    logger.warning("MikroTik router sync failed server_id=%s name=%s: %s", server.id, server.name, err)
                    continue
                changed += 1
        if changed:
            await session.commit()
    await sync_mikrotik_usage()
