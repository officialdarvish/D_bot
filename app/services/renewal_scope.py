from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import ClientService, Plan


async def service_purchase_category_id(
    session: AsyncSession,
    service: ClientService | None,
    *,
    persist_fallback: bool = False,
) -> int | None:
    """Return the immutable category in which a service was originally sold.

    Older installations did not store this value on ``client_services``. For those
    rows we fall back to the service's current plan and optionally persist the
    recovered category. New purchases always populate ``purchase_category_id``.
    """
    if service is None:
        return None
    try:
        stored = int(service.purchase_category_id or 0)
    except (TypeError, ValueError):
        stored = 0
    if stored > 0:
        return stored

    current_plan = await session.get(Plan, service.plan_id) if service.plan_id else None
    try:
        recovered = int(current_plan.category_id or 0) if current_plan else 0
    except (TypeError, ValueError):
        recovered = 0
    if recovered <= 0:
        return None
    if persist_fallback:
        service.purchase_category_id = recovered
        await session.flush()
    return recovered


async def renewal_plan_allowed(
    session: AsyncSession,
    service: ClientService | None,
    plan: Plan | None,
    *,
    require_active: bool = False,
    persist_fallback: bool = False,
) -> bool:
    """Validate that a renewal plan belongs to the service's original category."""
    if service is None or plan is None:
        return False
    if require_active and not bool(plan.is_active):
        return False
    if not service.server_id or not plan.server_id or int(plan.server_id) != int(service.server_id):
        return False
    category_id = await service_purchase_category_id(
        session,
        service,
        persist_fallback=persist_fallback,
    )
    if not category_id:
        return False
    try:
        return int(plan.category_id or 0) == int(category_id)
    except (TypeError, ValueError):
        return False
