from __future__ import annotations
from typing import Iterable, TypeVar
from app.database.models import Setting

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
