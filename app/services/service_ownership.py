"""Transfer an owner's personal configuration without changing upstream or billing data."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
import json
import uuid
from sqlalchemy import select, update
from app.core.config import settings
from app.database.models import ClientService, User, Order, ServiceConversion, ServiceDeletionTask, Setting, MiniAppOperation
from app.services.service_grace import visible_in_my_services

class OwnershipTransferError(ValueError):
    pass


def recipient_telegram_id(raw: str) -> int:
    raw = (raw or '').strip()
    if not raw.isdecimal() or len(raw) > 16 or not 0 < int(raw) < 2**52:
        raise OwnershipTransferError('آیدی عددی معتبر کاربر را بفرستید؛ نام کاربری، لینک یا آیدی گروه قابل قبول نیست.')
    return int(raw)


async def eligible_service(session, service_id: int, actor_telegram_id: int, *, lock: bool = False):
    if actor_telegram_id not in settings.admin_ids:
        raise OwnershipTransferError('انتقال مالکیت فقط برای مدیر اصلی ربات مجاز است.')
    actor = (await session.execute(select(User).where(User.telegram_id == actor_telegram_id))).scalar_one_or_none()
    query = select(ClientService).where(ClientService.id == service_id)
    if lock:
        query = query.with_for_update()
    svc = (await session.execute(query)).scalar_one_or_none()
    if not actor or not svc or svc.user_id != actor.id or svc.reseller_id is not None or not visible_in_my_services(svc):
        raise OwnershipTransferError('این سرویس متعلق به حساب شخصی شما نیست یا دیگر قابل انتقال نیست.')
    # Pending actions may still carry the old owner or change/delete this config.
    deletion = await session.scalar(select(ServiceDeletionTask.id).where(ServiceDeletionTask.source_service_id == service_id, ServiceDeletionTask.status != 'completed').limit(1))
    conversion = await session.scalar(select(ServiceConversion.id).where(ServiceConversion.source_service_id == service_id, ServiceConversion.status != 'completed').limit(1))
    order = await session.scalar(select(Order.id).where(Order.service_id == service_id, Order.status.in_(['pending','processing','waiting_receipt','waiting_payment','paid_pending_delivery'])).limit(1))
    native_operation=await session.scalar(select(MiniAppOperation.id).where(MiniAppOperation.status.in_(['queued','processing','review']),MiniAppOperation.payload['service_id'].as_integer()==service_id).limit(1))
    if deletion or conversion or order or native_operation:
        raise OwnershipTransferError('برای این سرویس عملیات حذف، تبدیل یا پرداخت در انتظار انجام وجود دارد؛ ابتدا آن را تعیین تکلیف کنید.')
    return svc, actor


@dataclass(frozen=True)
class OwnershipTransfer:
    service_id: int
    service_name: str
    recipient_id: int
    recipient_telegram_id: int


async def transfer_service_ownership(session, service_id: int, actor_telegram_id: int, target_telegram_id: int) -> OwnershipTransfer:
    """Caller commits once; the ownership change and audit entry share its transaction."""
    target_telegram_id = recipient_telegram_id(str(target_telegram_id))
    svc, actor = await eligible_service(session, service_id, actor_telegram_id, lock=True)
    target = (await session.execute(select(User).where(User.telegram_id == target_telegram_id))).scalar_one_or_none()
    if not target:
        raise OwnershipTransferError('کاربر مقصد پیدا نشد؛ ابتدا باید ربات را استارت کند. سپس آیدی عددی او را دوباره بفرستید.')
    if target.id == actor.id:
        raise OwnershipTransferError('این سرویس هم‌اکنون متعلق به شماست؛ آیدی عددی کاربر دیگری را بفرستید.')
    if target.is_blocked:
        raise OwnershipTransferError('کاربر مقصد مسدود است؛ ابتدا مسدودی او را از مدیریت کاربران بررسی کنید.')
    name = svc.client_username or svc.xui_email or str(svc.id)
    result = await session.execute(update(ClientService).where(ClientService.id == service_id, ClientService.user_id == actor.id, ClientService.reseller_id.is_(None)).values(user_id=target.id).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        raise OwnershipTransferError('مالکیت این سرویس تغییر کرده است؛ فهرست کانفیگ‌ها را دوباره باز کنید.')
    session.add(Setting(key=f'service_ownership_transfer:{uuid.uuid4().hex}', value=json.dumps({
        'service_id': service_id, 'from_user_id': actor.id, 'from_telegram_id': actor_telegram_id,
        'to_user_id': target.id, 'to_telegram_id': target.telegram_id, 'at': datetime.utcnow().isoformat(),
    }, separators=(',', ':'))))
    await session.flush()
    return OwnershipTransfer(service_id, name, target.id, target.telegram_id)
