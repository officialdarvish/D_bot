from __future__ import annotations
from typing import Iterable, TypeVar
from sqlalchemy import select
from app.database.models import Setting, ServerCategory

T = TypeVar('T')

def parse_id_order(value: str | None) -> list[int]:
    ids: list[int] = []
    for part in str(value or '').replace('[', '').replace(']', '').replace(' ', '').split(','):
        if not part:
            continue
        try:
            iid = int(part)
        except Exception:
            continue
        if iid > 0 and iid not in ids:
            ids.append(iid)
    return ids

async def saved_plan_order(session, kind: str = 'public') -> list[int]:
    key = 'plan_order_reseller' if kind == 'reseller' else 'plan_order_public'
    row = await session.get(Setting, key)
    return parse_id_order(row.value if row else '')

def sort_by_saved_order(items: Iterable[T], order_ids: list[int] | str | None):
    if isinstance(order_ids, str) or order_ids is None:
        order_ids = parse_id_order(order_ids)
    rank = {item_id: idx for idx, item_id in enumerate(order_ids)}
    return sorted(list(items), key=lambda x: (rank.get(int(getattr(x, 'id', 0) or 0), 10_000_000), int(getattr(x, 'price_irt', 0) or 0), int(getattr(x, 'id', 0) or 0)))


async def saved_category_order(session) -> list[str]:
    """Return category-group order as stable normalized names.

    The website stores one representative category ID for each grouped card.
    After the bot filters categories by server/service type, that representative
    row may no longer be present. Resolving IDs against the full category table
    keeps the saved order valid for every filtered bot view.
    """
    row = await session.get(Setting, 'category_order_public')
    ids = parse_id_order(row.value if row else '')
    if not ids:
        return []
    categories = (await session.execute(
        select(ServerCategory).where(ServerCategory.id.in_(ids))
    )).scalars().all()
    by_id = {int(item.id): _category_name_key(item) for item in categories}
    ordered: list[str] = []
    for cid in ids:
        key = by_id.get(cid, '')
        if key and key not in ordered:
            ordered.append(key)
    return ordered


def _category_name_key(item) -> str:
    return ' '.join(str(getattr(item, 'name', '') or '').strip().lower().split())


def sort_categories_by_saved_order(items: Iterable[T], order_ids: list[int] | list[str] | str | None):
    """Sort category rows by the saved order of their grouped category card."""
    rows = list(items)
    if order_ids is None or isinstance(order_ids, str):
        order_ids = parse_id_order(order_ids)

    # New path: saved_category_order resolves representative IDs to normalized
    # category names, so filtering by service type cannot lose the rank.
    if order_ids and isinstance(order_ids[0], str):
        name_rank = {str(key): idx for idx, key in enumerate(order_ids)}
        fallback = len(name_rank) + 1
        return sorted(rows, key=lambda row: (name_rank.get(_category_name_key(row), fallback), -int(getattr(row, 'id', 0) or 0)))

    rank = {int(item_id): idx for idx, item_id in enumerate(order_ids or [])}
    group_ranks: dict[str, int] = {}
    for row in rows:
        key = _category_name_key(row)
        item_rank = rank.get(int(getattr(row, 'id', 0) or 0))
        if item_rank is not None:
            group_ranks[key] = min(group_ranks.get(key, item_rank), item_rank)
    fallback = len(rank) + 1
    return sorted(rows, key=lambda row: (group_ranks.get(_category_name_key(row), fallback), -int(getattr(row, 'id', 0) or 0)))
