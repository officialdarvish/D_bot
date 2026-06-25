from __future__ import annotations
from datetime import datetime, timedelta
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.models import ResellerAccount, ResellerPackage, ResellerTopupRequest, ResellerAccessRequest, ClientService, User

GB = 1024 ** 3

def gb_to_bytes(value: float | int) -> int:
    return int(float(value) * GB)

def bytes_to_gb(value: int | None) -> float:
    return round((value or 0) / GB, 2)

def days_left(expires_at) -> int:
    if not expires_at:
        return 0
    return max((expires_at.date() - datetime.utcnow().date()).days, 0)

def is_reseller_access_active(reseller: ResellerAccount | None) -> bool:
    if not reseller or not reseller.is_active:
        return False
    if reseller.expires_at and reseller.expires_at < datetime.utcnow():
        return False
    return True

def remaining_bytes(reseller: ResellerAccount) -> int:
    return max((reseller.total_bytes or 0) - (reseller.reserved_bytes or 0), 0)

async def get_user_reseller(session: AsyncSession, telegram_id: int) -> tuple[User | None, ResellerAccount | None]:
    user = (await session.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one_or_none()
    if not user:
        return None, None
    reseller = (await session.execute(select(ResellerAccount).where(ResellerAccount.user_id == user.id))).scalar_one_or_none()
    return user, reseller

async def get_reseller_access_request(session: AsyncSession, user_id: int) -> ResellerAccessRequest | None:
    return (await session.execute(select(ResellerAccessRequest).where(ResellerAccessRequest.user_id == user_id))).scalar_one_or_none()

async def create_reseller_access_request(session: AsyncSession, user_id: int) -> ResellerAccessRequest:
    req = await get_reseller_access_request(session, user_id)
    if req:
        if req.status == 'rejected':
            req.status = 'pending'
            req.reviewed_by = None
            req.reviewed_at = None
            req.created_at = datetime.utcnow()
        await session.flush()
        return req
    req = ResellerAccessRequest(user_id=user_id, status='pending')
    session.add(req)
    await session.flush()
    return req

async def approve_reseller_access(session: AsyncSession, request: ResellerAccessRequest, reviewer_telegram_id: int | None = None) -> ResellerAccount:
    request.status = 'approved'
    request.reviewed_by = reviewer_telegram_id
    request.reviewed_at = datetime.utcnow()
    reseller = await ensure_reseller_for_user(session, request.user_id, None, 0)
    reseller.is_active = True
    if reseller.expires_at and reseller.expires_at < datetime.utcnow():
        reseller.expires_at = None
    await session.flush()
    return reseller

async def reject_reseller_access(session: AsyncSession, request: ResellerAccessRequest, reviewer_telegram_id: int | None = None) -> None:
    request.status = 'rejected'
    request.reviewed_by = reviewer_telegram_id
    request.reviewed_at = datetime.utcnow()
    await session.flush()

async def ensure_reseller_for_user(session: AsyncSession, user_id: int, server_id: int | None, validity_days: int = 365) -> ResellerAccount:
    reseller = (await session.execute(select(ResellerAccount).where(ResellerAccount.user_id == user_id))).scalar_one_or_none()
    if reseller:
        if server_id and not reseller.server_id:
            reseller.server_id = server_id
        return reseller
    reseller = ResellerAccount(user_id=user_id, server_id=server_id, total_bytes=0, used_bytes=0, reserved_bytes=0, expires_at=(datetime.utcnow() + timedelta(days=validity_days) if validity_days else None), is_active=True)
    session.add(reseller)
    await session.flush()
    return reseller

async def apply_package(session: AsyncSession, request: ResellerTopupRequest) -> ResellerAccount:
    pkg = await session.get(ResellerPackage, request.package_id)
    reseller = await ensure_reseller_for_user(session, request.user_id, pkg.server_id if pkg else None, pkg.reseller_validity_days if pkg else 365)
    reseller.total_bytes = (reseller.total_bytes or 0) + (request.volume_bytes or 0)
    if pkg and pkg.server_id:
        reseller.server_id = pkg.server_id
    now = datetime.utcnow()
    add_days = pkg.reseller_validity_days if pkg else 365
    base = reseller.expires_at if reseller.expires_at and reseller.expires_at > now else now
    reseller.expires_at = base + timedelta(days=add_days)
    reseller.is_active = True
    request.reseller_id = reseller.id
    request.status = 'approved'
    await session.flush()
    return reseller

async def reserve_volume_for_service(session: AsyncSession, reseller: ResellerAccount, bytes_amount: int) -> None:
    if bytes_amount <= 0:
        raise ValueError('حجم باید بیشتر از صفر باشد.')
    if remaining_bytes(reseller) < bytes_amount:
        raise ValueError('حجم باقی‌مانده نمایندگی کافی نیست.')
    reseller.reserved_bytes = (reseller.reserved_bytes or 0) + bytes_amount
    await session.flush()

async def refund_unused_volume(session: AsyncSession, service: ClientService, reseller: ResellerAccount | None = None) -> int:
    if not service.reseller_id or not service.reseller_reserved_bytes:
        return 0
    if reseller is None:
        reseller = await session.get(ResellerAccount, service.reseller_id)
    if not reseller:
        return 0
    reserved = service.reseller_reserved_bytes or service.total_bytes or 0
    used = service.used_bytes or 0
    refund = max(reserved - used, 0)
    reseller.reserved_bytes = max((reseller.reserved_bytes or 0) - refund, 0)
    service.reseller_reserved_bytes = 0
    return refund

async def reseller_stats(session: AsyncSession, reseller: ResellerAccount) -> dict:
    total_users = (await session.execute(select(func.count(ClientService.id)).where(ClientService.reseller_id == reseller.id, ClientService.is_active == True))).scalar() or 0
    services = (await session.execute(select(ClientService).where(ClientService.reseller_id == reseller.id, ClientService.is_active == True))).scalars().all()
    used = sum(s.used_bytes or 0 for s in services)
    reseller.used_bytes = used
    return {
        'total_users': total_users,
        'used_bytes': used,
        'total_bytes': reseller.total_bytes or 0,
        'reserved_bytes': reseller.reserved_bytes or 0,
        'remaining_bytes': remaining_bytes(reseller),
        'days_left': days_left(reseller.expires_at),
    }
