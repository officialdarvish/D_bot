"""Shared sellability checks for Mini App browsing and Telegram handoff."""
from app.services.catalog_settings import category_service_bindings, categories_for_service, service_badges
from sqlalchemy import select
from app.database.models import Plan, Server, ServerCategory
from app.services.category_visibility import category_group_rows, category_is_enabled, public_provider_servers
from app.services.plan_order import saved_plan_order, sort_by_saved_order


async def public_plans(session):
    rows = (await session.execute(select(Plan, Server).join(Server, Plan.server_id == Server.id).where(
        Plan.is_active.is_(True), Server.is_active.is_(True), Plan.category_id.is_not(None)
    ))).all()
    categories = (await session.execute(select(ServerCategory))).scalars().all()
    by_id = {c.id: c for c in categories}
    from app.bot.handlers.public.buy import get_public_service_types
    service_types = await get_public_service_types(session)
    bindings = await category_service_bindings(session)
    visible_ids = {kind: {c.id for c in categories_for_service(categories, kind, bindings)} for kind, _, _ in service_types}
    eligible = {}
    for plan, server in rows:
        cat = by_id.get(plan.category_id)
        if not any(plan.category_id in visible_ids[kind] and public_provider_servers([server], provider, active_only=True) for kind, _, provider in service_types):
            continue
        if str((server.meta or {}).get('scope') or 'public').lower() not in ('public', 'all'):
            continue
        if cat is None or not category_is_enabled(category_group_rows(categories, cat)):
            continue
        eligible[plan.id] = (plan, server, cat)
    ordered = sort_by_saved_order([row[0] for row in eligible.values()], await saved_plan_order(session, 'public'))
    return [eligible[p.id] for p in ordered]


async def public_catalog(session):
    from app.bot.handlers.public.buy import get_public_service_types
    from app.services.category_visibility import eligible_category_ids_for_servers, sellable_category_groups
    from app.services.plan_order import saved_category_order, sort_categories_by_saved_order
    from app.services.live_pricing import plan_price_label
    types=await get_public_service_types(session)
    servers=(await session.execute(select(Server))).scalars().all()
    categories=(await session.execute(select(ServerCategory))).scalars().all()
    categories=sort_categories_by_saved_order(categories,await saved_category_order(session))
    rows=await public_plans(session)
    plans=[dict(id=p.id,title=p.title,volume_gb=p.volume_gb,duration_days=p.duration_days,
        unlimited=bool(p.is_unlimited or not p.volume_gb),price=plan_price_label(p),category=c.name,category_id=c.id,
        server=s.name,provider=s.server_type) for p,s,c in rows]
    bindings = await category_service_bindings(session)
    badges = await service_badges(session, types)
    groups=[]
    for kind,label,provider in types:
        allowed=public_provider_servers(servers,provider,active_only=False)
        type_categories = categories_for_service(categories, kind, bindings)
        category_ids = {c.id for c in type_categories}
        matching=[p for p,s,c in rows if p.category_id in category_ids and public_provider_servers([s],provider,active_only=True)]
        eligible=eligible_category_ids_for_servers(type_categories,[s.id for s in allowed],[p.category_id for p in matching])
        for group in sellable_category_groups(type_categories,eligible):
            ids=[p.id for p in matching if p.category_id in group['ids']]
            groups.append(dict(key=kind+':'+str(group['ids'][0]),title=group['name'],type_key=kind,type_label=label,plan_ids=ids,**badges[kind]))
    return dict(plans=plans,categories=groups,service_types=[dict(key=k,label=l,**badges[k]) for k,l,_ in types if any(g['type_key']==k for g in groups)])
