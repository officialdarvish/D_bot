"""Persistent catalogue presentation and explicit category-to-service bindings.

Settings keep this compatible with existing installations/backups without a schema
migration. Unassigned legacy categories retain provider-based routing.
"""
from __future__ import annotations

import re
from sqlalchemy import select
from app.database.models import Setting
from app.services.category_visibility import category_group_rows, category_name_key

CATEGORY_SERVICE_PREFIX = 'category_service_type:'
SERVICE_BADGE_PREFIX = 'service_type_badge_color:'
SERVICE_PREFIX = 'service_type:custom:'


def category_service_setting(cid: int) -> str:
    return f'{CATEGORY_SERVICE_PREFIX}{int(cid)}'


def service_badge_setting(key: str) -> str:
    return SERVICE_BADGE_PREFIX + key.removeprefix(SERVICE_PREFIX)


async def category_service_bindings(session) -> dict[int, str]:
    rows = (await session.execute(select(Setting).where(Setting.key.like(CATEGORY_SERVICE_PREFIX + '%')))).scalars().all()
    return {int(r.key[len(CATEGORY_SERVICE_PREFIX):]): str(r.value or '') for r in rows
            if r.key[len(CATEGORY_SERVICE_PREFIX):].isdigit()}


def category_service_key(rows, bindings: dict[int, str]) -> str:
    # The newest active row represents the logical group in Web Admin. All
    # duplicate IDs receive the same binding when edited.
    ordered = sorted(rows, key=lambda r: (bool(getattr(r, 'is_active', True)), int(r.id)), reverse=True)
    return next((bindings[int(r.id)] for r in ordered if int(r.id) in bindings), '')


def categories_for_service(rows, kind: str, bindings: dict[int, str]) -> list:
    rows = list(rows)
    key = kind if kind.startswith(SERVICE_PREFIX) else SERVICE_PREFIX + kind
    accepted = {}
    for row in rows:
        name = category_name_key(row.name)
        if name not in accepted:
            selected = category_service_key(category_group_rows(rows, row), bindings)
            accepted[name] = not selected or selected == key
    return [row for row in rows if accepted[category_name_key(row.name)]]


def normalize_badge_color(value: str) -> str:
    color = str(value or '').strip().lower()
    if not re.fullmatch(r'#[0-9a-f]{6}', color):
        raise ValueError('Badge color must be a valid six-digit hex color (#RRGGBB).')
    return color


def badge_emoji(color: str) -> str:
    rgb = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
    palette = [('🔴', (239, 68, 68)), ('🟠', (249, 115, 22)), ('🟡', (234, 179, 8)),
               ('🟢', (34, 197, 94)), ('🔵', (37, 99, 235)), ('🟣', (168, 85, 247)),
               ('⚫', (20, 20, 20)), ('⚪', (240, 240, 240)), ('🟤', (139, 69, 19))]
    return min(palette, key=lambda item: sum((a - b) ** 2 for a, b in zip(rgb, item[1])))[0]


async def service_badges(session, types) -> dict[str, dict[str, str]]:
    rows = (await session.execute(select(Setting).where(Setting.key.like(SERVICE_BADGE_PREFIX + '%')))).scalars().all()
    saved = {r.key: r.value for r in rows}
    result = {}
    for kind, _label, provider in types:
        default = '#22c55e' if provider == 'pasarguard' else '#f97316' if provider == 'mikrotik' else '#2563eb'
        try:
            color = normalize_badge_color(saved.get(service_badge_setting(kind), default))
        except ValueError:
            color = default
        result[kind] = {'badge_color': color, 'badge_emoji': badge_emoji(color)}
    return result
