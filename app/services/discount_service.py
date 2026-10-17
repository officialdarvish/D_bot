from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select

from app.database.models import DiscountCode, DiscountUsage


async def apply_discount_amount(
    session,
    code: str | None,
    amount: int,
    user_id: int | None = None,
    source: str = 'buy',
    server_id: int | None = None,
) -> tuple[int, str | None, DiscountCode | None]:
    """Validate a discount code and return the payable amount.

    ``source`` is stored only when the usage is finalized. Validation rules are
    shared by new purchases, renewals, and any other public checkout flow.
    """
    if not code:
        return int(amount or 0), None, None

    clean = str(code).strip().upper().replace(' ', '')
    discount = (
        await session.execute(
            select(DiscountCode).where(
                func.upper(DiscountCode.code) == clean,
                DiscountCode.is_active == True,  # noqa: E712
            )
        )
    ).scalar_one_or_none()

    if not discount:
        return int(amount or 0), 'کد تخفیف معتبر نیست.', None
    if discount.expires_at and discount.expires_at < datetime.utcnow():
        return int(amount or 0), 'کد تخفیف منقضی شده است.', None
    if discount.max_uses and discount.used_count >= discount.max_uses:
        return int(amount or 0), 'ظرفیت استفاده از این کد تکمیل شده است.', None

    allowed_servers: list[int] = []
    try:
        allowed_servers = [
            int(value)
            for value in (getattr(discount, 'allowed_server_ids', None) or [])
            if int(value) > 0
        ]
    except (TypeError, ValueError):
        allowed_servers = []

    if allowed_servers and (not server_id or int(server_id) not in allowed_servers):
        return int(amount or 0), 'این کد تخفیف برای سرور انتخابی شما فعال نیست.', None

    if user_id and getattr(discount, 'per_user_limit', 1):
        used_by_user = (
            await session.execute(
                select(func.count(DiscountUsage.id)).where(
                    DiscountUsage.discount_id == discount.id,
                    DiscountUsage.user_id == user_id,
                )
            )
        ).scalar() or 0
        if used_by_user >= discount.per_user_limit:
            return (
                int(amount or 0),
                f'شما قبلاً از این کد {used_by_user} بار استفاده کرده‌اید و سقف استفاده شما تکمیل شده است.',
                None,
            )

    base_amount = max(int(amount or 0), 0)
    if discount.discount_type == 'percent':
        discount_amount = int(base_amount * min(max(discount.value, 0), 100) / 100)
    else:
        discount_amount = int(discount.value or 0)

    return max(base_amount - discount_amount, 0), None, discount


async def mark_discount_used(
    session,
    discount_obj: DiscountCode | None,
    user_id: int,
    source: str = 'buy',
) -> None:
    if not discount_obj:
        return
    discount_obj.used_count += 1
    session.add(
        DiscountUsage(
            discount_id=discount_obj.id,
            user_id=user_id,
            source=source,
        )
    )


def order_discount_usage_source(order_id: int, source: str = 'renew') -> str:
    return f'{source}_order:{int(order_id)}'


async def release_order_discount_usage(
    session,
    *,
    order_id: int,
    user_id: int,
    code: str | None,
    source: str = 'renew',
) -> bool:
    """Release a discount reservation tied to a cancelled/rejected order."""
    if not code:
        return False
    clean = str(code).strip().upper().replace(' ', '')
    discount = (
        await session.execute(
            select(DiscountCode).where(func.upper(DiscountCode.code) == clean)
        )
    ).scalar_one_or_none()
    if not discount:
        return False
    usage_source = order_discount_usage_source(order_id, source)
    usage = (
        await session.execute(
            select(DiscountUsage)
            .where(
                DiscountUsage.discount_id == discount.id,
                DiscountUsage.user_id == user_id,
                DiscountUsage.source == usage_source,
            )
            .order_by(DiscountUsage.id.desc())
        )
    ).scalars().first()
    if not usage:
        return False
    await session.delete(usage)
    discount.used_count = max(int(discount.used_count or 0) - 1, 0)
    return True
