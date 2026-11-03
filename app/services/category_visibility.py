"""Logical category grouping shared by Telegram sales and Web Admin.

Older installations may contain several ServerCategory rows with the same name,
while plans still reference any one of those row IDs. They represent one visible
category: toggling or selling by only a representative ID is incorrect.
"""
from __future__ import annotations

from collections.abc import Iterable



def category_linked_server_ids(category) -> list[int]:
    """Return linked server IDs from both the modern list and legacy column."""
    raw = getattr(category, 'server_ids', None) or []
    if isinstance(raw, str):
        raw = raw.split(',')
    result = []
    for value in [*(raw if isinstance(raw, (list, tuple, set)) else []), getattr(category, 'server_id', None)]:
        try:
            sid = int(str(value).strip())
        except (TypeError, ValueError):
            continue
        if sid > 0 and sid not in result:
            result.append(sid)
    return result


def category_name_key(value: str | None) -> str:
    return ' '.join(str(value or '').strip().casefold().split())


def category_group_rows(rows: Iterable, selected) -> list:
    key = category_name_key(getattr(selected, 'name', ''))
    if not key:
        return [selected]
    return [row for row in rows if category_name_key(getattr(row, 'name', '')) == key]


def category_is_enabled(rows: Iterable) -> bool:
    return any(bool(getattr(row, 'is_active', True)) for row in rows)


def sellable_category_groups(rows: Iterable, sellable_ids: Iterable[int]) -> list[dict]:
    """Return enabled, eligible groups, including all legacy duplicate IDs.

    Excluding inactive duplicate IDs from the returned group would lose their
    still-active plans on the following screen. Newly linked categories may
    also be eligible before they have a plan. Only the overall logical group
    state controls visibility; individual plan.is_active remains authoritative.
    """
    sellable = {int(cid) for cid in sellable_ids if cid is not None}
    groups: dict[str, dict] = {}
    for row in rows:
        key = category_name_key(getattr(row, 'name', ''))
        if not key:
            continue
        group = groups.setdefault(key, {
            'name': str(getattr(row, 'name', '') or '').strip(),
            'ids': [], 'enabled': False, 'has_plans': False,
        })
        cid = int(row.id)
        if cid not in group['ids']:
            group['ids'].append(cid)
        if getattr(row, 'is_active', True):
            group['enabled'] = True
            group['name'] = str(getattr(row, 'name', '') or '').strip()
        if cid in sellable:
            group['has_plans'] = True
    return [group for group in groups.values() if group['enabled'] and group['has_plans']]



def eligible_category_ids_for_servers(rows: Iterable, server_ids: Iterable[int], plan_category_ids: Iterable[int] = ()) -> set[int]:
    """Categories available for a public service type, including newly linked drafts.

    Plan-backed categories remain eligible even when a legacy category-to-server
    link is stale. Newly created categories can appear as soon as they are
    explicitly linked to an active public server; selecting them will report
    that no plans are available until the admin adds one.
    """
    allowed = {int(sid) for sid in server_ids if str(sid).isdigit() and int(sid) > 0}
    result = {int(cid) for cid in plan_category_ids if str(cid).isdigit() and int(cid) > 0}
    if not allowed:
        return set()
    for row in rows:
        raw = getattr(row, 'server_ids', None) or []
        if isinstance(raw, str):
            raw = raw.split(',')
        linked = list(raw) if isinstance(raw, (list, tuple, set)) else []
        linked.append(getattr(row, 'server_id', None))
        if any(str(sid).strip().isdigit() and int(str(sid).strip()) in allowed for sid in linked if sid is not None):
            result.add(int(row.id))
    return result


def category_button_label(name: str | None) -> str:
    """Place lightning on the RTL/right side of the Telegram category label.

    Telegram uses bidirectional text layout, and a trailing emoji in a mixed
    Persian/Latin title appears visually on the *left*. A leading RLM + emoji
    keeps it on the right without modifying category names stored in Admin Web.
    """
    title = str(name or '').strip()
    if '⚡' not in title:
        return title
    rest = ' '.join(title.replace('⚡', ' ').split())
    return f'\u200f⚡ {rest}' if rest else '\u200f⚡'


def public_provider_servers(servers: Iterable, provider: str, *, active_only: bool = True) -> list:
    """Use one provider/scope check for bot inventory and admin diagnostics.

    Inactive public servers still define where a category belongs in the menu,
    but are never returned when provisioning or listing purchasable plans.
    Reseller-only servers must never supply public inventory.
    """
    from app.services.service_type_catalog import normalize_service_provider, provider_members_for_service_type

    expected = provider_members_for_service_type(provider)
    if not expected:
        return []
    result = []
    for server in servers:
        if normalize_service_provider(getattr(server, 'server_type', '')) not in expected:
            continue
        scope = str((getattr(server, 'meta', None) or {}).get('scope') or 'public').lower()
        if scope not in ('public', 'all'):
            continue
        if active_only and not bool(getattr(server, 'is_active', False)):
            continue
        result.append(server)
    return result


def category_bot_status(rows: Iterable, servers: Iterable, active_plan_server_pairs: Iterable[tuple[int, int]] = ()) -> dict:
    """Explain visibility using the same server constraints as the bot.

    This is diagnostic only; the bot keeps enforcing active servers/plans at buy time.
    """
    from app.services.service_type_catalog import normalize_service_provider, service_provider_label

    rows = list(rows)
    server_map = {int(server.id): server for server in servers}
    linked = []
    for row in rows:
        raw_ids = getattr(row, 'server_ids', None) or []
        if isinstance(raw_ids, str):
            raw_ids = raw_ids.split(',')
        values = list(raw_ids) if isinstance(raw_ids, (list, tuple, set)) else []
        values.append(getattr(row, 'server_id', None))
        for sid in values:
            try:
                sid = int(str(sid).strip())
            except (ValueError, TypeError):
                continue
            if sid > 0 and sid not in linked:
                linked.append(sid)
    available = [server_map[sid] for sid in linked if sid in server_map]
    public = [s for s in available if str((getattr(s, 'meta', None) or {}).get('scope') or 'public').lower() in ('public', 'all')]
    active = [s for s in public if bool(getattr(s, 'is_active', False))]
    provider_keys = []
    for s in public:
        provider = normalize_service_provider(getattr(s, 'server_type', ''))
        if provider and provider not in provider_keys:
            provider_keys.append(provider)
    active_ids = {int(s.id) for s in active}
    ids = {int(r.id) for r in rows}
    has_plan = any(int(cid) in ids and int(sid) in active_ids for cid, sid in active_plan_server_pairs if cid is not None and sid is not None)
    if not category_is_enabled(rows):
        status = 'inactive_category'
        detail = 'Category is deactivated.'
    elif not linked:
        status = 'unlinked'
        detail = 'Link at least one public server to this category.'
    elif not available:
        status = 'missing_servers'
        detail = 'Linked server IDs no longer exist. Edit the category.'
    elif not public:
        status = 'reseller_only'
        detail = 'Only reseller/private servers are linked; public bot cannot show this category.'
    elif not provider_keys:
        status = 'unsupported_provider'
        detail = 'Server provider type is not recognized. Check Servers.'
    elif not active:
        status = 'paused'
        detail = 'Shown under its provider Service Type, but all linked public servers are inactive; purchasing is paused.'
    elif not has_plan:
        status = 'no_plan'
        detail = 'Shown in bot; create an active plan for users to buy.'
    else:
        status = 'ready'
        detail = 'Shown under the linked provider Service Type; available plans depend on the active server.'
    return {
        'status': status,
        'detail': detail,
        'providers': provider_keys,
        'provider_labels': [service_provider_label(provider) for provider in provider_keys],
        'active_public_server_ids': [int(s.id) for s in active],
        'inactive_public_server_ids': [int(s.id) for s in public if not getattr(s, 'is_active', False)],
    }
