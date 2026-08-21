from __future__ import annotations

from app.core.config import settings


def is_owner(user_id: int | None) -> bool:
    """Full-access bot owner check."""
    return bool(user_id is not None and user_id in settings.owner_ids)


def is_seller(user_id: int | None) -> bool:
    """Limited seller/admin check. Sellers must not access management routes."""
    return bool(user_id is not None and user_id in settings.seller_ids)


def is_staff(user_id: int | None) -> bool:
    return is_owner(user_id) or is_seller(user_id)


def require_owner(user_id: int | None) -> bool:
    return is_owner(user_id)
