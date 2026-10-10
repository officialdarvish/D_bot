"""PasarGuard-only wallet metering. Remote users are always filtered and ownership-checked.

Polling is not instantaneous: cutoff latency is up to the job interval plus PasarGuard
API latency. Charges use cumulative total minus paid checkpoint so retries cannot
charge the same traffic twice; every wallet debit and checkpoint share one transaction.
"""
from __future__ import annotations

import logging
import asyncio
from datetime import datetime
from math import ceil
from sqlalchemy import select

from app.database.models import PasarGuardPanelMeter, PasarGuardPanelOrder, Server, User, WalletTransaction
from app.database.session import SessionLocal
from app.services.pasarguard_service import PasarGuardService

log = logging.getLogger(__name__)
GIB = 1024 ** 3


def price_for_usage(traffic_bytes: int, seconds: int, gb_price: int, hourly_price: int) -> tuple[int, int]:
    """Integer arithmetic avoids float billing drift; round cumulative totals only."""
    return ((max(0, traffic_bytes) * gb_price + GIB - 1) // GIB,
            (max(0, seconds) * hourly_price + 3599) // 3600)


class PanelMeterAPI:
    def __init__(self, provider: PasarGuardService | None = None):
        self.provider = provider or PasarGuardService()

    async def list_own_users(self, server, order) -> list[dict]:
        """Only return users whose admin.id is *exactly* the purchased admin ID.

        Fail closed if paging/filter/ownership cannot be verified. Never pass an
        unbounded ALL-admin query to status or billing operations.
        """
        admin_id = int(order.admin_id or 0)
        if admin_id <= 0:
            raise RuntimeError('Reseller PasarGuard Admin ID is missing')
        rows: list[dict] = []
        offset = 0
        while True:
            data = await self.provider._request(server, 'GET', '/api/users',
                params={'admin_ids': admin_id, 'offset': offset, 'limit': 100, 'load_sub': 'false'})
            if not isinstance(data, dict) or not isinstance(data.get('users'), list) or not isinstance(data.get('total'), int):
                raise RuntimeError('PasarGuard returned an unverifiable user page')
            page = data['users']
            for row in page:
                owner = row.get('admin') if isinstance(row, dict) else None
                if not isinstance(owner, dict) or int(owner.get('id') or 0) != admin_id:
                    raise RuntimeError('PasarGuard user listing returned a user outside the reseller ownership scope')
                if int(row.get('id') or 0) <= 0 or row.get('used_traffic') is None:
                    raise RuntimeError('PasarGuard user usage data is incomplete')
                rows.append(row)
            offset += len(page)
            if offset >= data['total']:
                return rows
            if not page or offset > 200000:
                raise RuntimeError('PasarGuard user pagination failed; no billing applied')

    async def set_users(self, server, order, enable: bool, *, only_ids: set[int] | None = None) -> list[int]:
        users = await self.list_own_users(server, order)
        if any(str(row.get('status', '')).lower() not in
               {'active', 'disabled', 'on_hold', 'limited', 'expired'} for row in users):
            raise RuntimeError('PasarGuard user status is missing or unknown')
        ids = [int(row['id']) for row in users
               if (only_ids is None or int(row['id']) in only_ids)
               and str(row['status']).lower() == ('disabled' if enable else 'active')]
        endpoint = '/api/users/bulk/enable' if enable else '/api/users/bulk/disable'
        for pos in range(0, len(ids), 100):
            # Each batch is exclusively from verified OWN-user results.
            await self.provider._request(server, 'POST', endpoint, json={'ids': ids[pos:pos+100]})
        return ids

    async def change_password(self, server, order, password: str) -> None:
        from app.services.pasarguard_panel_sales import validate_panel_password
        if not validate_panel_password(password):
            raise ValueError('Password policy requires 12+ chars, 2 lowercase, 2 uppercase, 2 digits and a symbol')
        # Uses Owner connection and fixed username from a verified purchased order.
        await self.provider._request(server, 'PUT', f'/api/admin/by-id/{int(order.admin_id)}', json={'password': password})

    async def poll(self, order_id: int, *, bot=None, now: datetime | None = None) -> dict:
        now = now or datetime.utcnow()
        # Fetch remote without holding a database transaction/lock across network.
        async with SessionLocal() as session:
            meter = (await session.execute(select(PasarGuardPanelMeter).where(
                PasarGuardPanelMeter.order_id == order_id))).scalar_one_or_none()
            order = await session.get(PasarGuardPanelOrder, order_id)
            if not meter or not order or order.status not in {'approved', 'delivery_pending'}:
                return {}
            server = await session.get(Server, order.server_id)
            if not server or not server.is_active or server.server_type != 'pasarguard':
                raise RuntimeError('PasarGuard panel is unavailable')
            user_id = order.user_id
        users = await self.list_own_users(server, order)
        async with SessionLocal() as session:
            locked = (await session.execute(select(PasarGuardPanelMeter).where(
                PasarGuardPanelMeter.order_id == order_id).with_for_update())).scalar_one_or_none()
            account = await session.get(User, user_id, with_for_update=True)
            if locked is None or account is None:
                return {}
            offsets = dict(locked.usage_offsets or {})
            increment = 0
            for row in users:
                key = str(row['id'])
                current = max(0, int(row['used_traffic']))
                previous = int(offsets.get(key, 0))
                # Usage counters may reset after plan renewal; bill the fresh
                # counter starting at zero, not only after it overtakes old value.
                increment += current - previous if current >= previous else current
                offsets[key] = current
            if not locked.suspended:
                locked.last_error = None
            locked.usage_offsets = offsets
            locked.traffic_bytes = int(locked.traffic_bytes or 0) + increment
            elapsed = max(0, int((now - locked.last_meter_at).total_seconds()))
            if not locked.suspended:
                locked.billable_seconds += elapsed
            # A stale concurrent refresh must never rewind the time checkpoint.
            locked.last_meter_at = max(now, locked.last_meter_at)
            traffic_due, hours_due = price_for_usage(
                locked.traffic_bytes, locked.billable_seconds, locked.gb_price_irt, locked.hourly_price_irt)
            # Keep unpaid debt when a meter exceeds the remaining wallet balance.
            # Recharging the wallet settles previous usage *before* a panel resumes.
            owed = max(0, traffic_due + hours_due - int(locked.total_charged_irt or 0))
            balance = max(0, int(account.wallet_balance or 0))
            paid = min(owed, balance)
            account.wallet_balance = balance - paid
            # Assessed usage is separate from actual wallet debits. The latter
            # is the durable checkpoint, so partial payments are not lost.
            locked.billed_traffic_irt = traffic_due
            locked.billed_hours_irt = hours_due
            locked.total_charged_irt += paid
            if paid:
                session.add(WalletTransaction(user_id=account.id, amount_irt=-paid,
                    tx_type='debit', description=f'PasarGuard PAYG panel #{order_id}: traffic + time'))
            just_suspended = not locked.suspended and account.wallet_balance <= 0 and (locked.gb_price_irt > 0 or locked.hourly_price_irt > 0)
            if just_suspended:
                locked.suspended = True
            await session.commit()
            suspended = bool(locked.suspended)
            remaining = int(account.wallet_balance)
        if suspended:
            # Re-run on every poll: reseller may create new users while wallet is empty.
            # Persist intent BEFORE the remote call, so partial upstream batch
            # failures cannot strand already-disabled users on later resume.
            try:
                active_ids = {int(r['id']) for r in users if r.get('status') == 'active'}
                if active_ids:
                    async with SessionLocal() as session:
                        m = (await session.execute(select(PasarGuardPanelMeter).where(
                            PasarGuardPanelMeter.order_id == order_id).with_for_update())).scalar_one()
                        m.auto_disabled_user_ids = sorted(set(m.auto_disabled_user_ids or []) | active_ids)
                        await session.commit()
                if active_ids:
                    await self.set_users(server, order, False, only_ids=active_ids)
                async with SessionLocal() as session:
                    m = (await session.execute(select(PasarGuardPanelMeter).where(
                        PasarGuardPanelMeter.order_id == order_id).with_for_update())).scalar_one()
                    m.last_error = None
                    await session.commit()
            except Exception as exc:
                log.exception('PAYG suspend failed order=%s', order_id)
                async with SessionLocal() as session:
                    m = (await session.execute(select(PasarGuardPanelMeter).where(
                        PasarGuardPanelMeter.order_id == order_id))).scalar_one_or_none()
                    if m:
                        m.last_error = f'Unable to suspend panel users: {type(exc).__name__}'
                        await session.commit()
        if just_suspended and bot is not None:
            try:
                async with SessionLocal() as session:
                    u = await session.get(User, user_id)
                await bot.send_message(u.telegram_id,
                    f'⚠️ موجودی کیف پول شما برای پنل نمایندگی {order.username} به پایان رسید. '
                    'کاربران این پنل غیرفعال می‌شوند. بعد از شارژ، از منوی پنل گزینه فعال‌سازی را انتخاب کنید.')
            except Exception:
                log.exception('PAYG low-balance alert delivery failed order=%s', order_id)
        return {'charged': paid, 'remaining': remaining, 'suspended': suspended,
                'traffic_bytes': sum(max(0, int(r['used_traffic'])) for r in users),
                'user_count': len(users)}

    async def resume(self, order_id: int) -> int:
        # Meter once to avoid resuming an account with unpaid, newly incurred usage.
        await self.poll(order_id)
        async with SessionLocal() as session:
            order = await session.get(PasarGuardPanelOrder, order_id)
            meter = (await session.execute(select(PasarGuardPanelMeter).where(
                PasarGuardPanelMeter.order_id == order_id))).scalar_one()
            user = await session.get(User, order.user_id)
            server = await session.get(Server, order.server_id)
            if int(user.wallet_balance or 0) <= 0:
                raise ValueError('کیف پول خالی است؛ ابتدا شارژ کنید.')
            restore_ids = set(meter.auto_disabled_user_ids or [])
        restored = await self.set_users(server, order, True, only_ids=restore_ids)
        async with SessionLocal() as session:
            meter = (await session.execute(select(PasarGuardPanelMeter).where(
                PasarGuardPanelMeter.order_id == order_id).with_for_update())).scalar_one()
            meter.suspended = False
            meter.auto_disabled_user_ids = []
            meter.last_meter_at = datetime.utcnow()
            meter.last_error = None
            await session.commit()
        return len(restored)


async def sync_panel_payg(bot=None) -> None:
    async with SessionLocal() as session:
        ids = (await session.execute(select(PasarGuardPanelMeter.order_id).join(
            PasarGuardPanelOrder, PasarGuardPanelOrder.id == PasarGuardPanelMeter.order_id)
            .where(PasarGuardPanelOrder.status.in_(['approved', 'delivery_pending'])))).scalars().all()
    api = PanelMeterAPI()
    # Bounded concurrency keeps larger reseller catalogs from exceeding the
    # minute-long polling interval; DB row locks serialize shared-wallet debits.
    semaphore = asyncio.Semaphore(4)

    async def sync_one(oid: int) -> None:
        async with semaphore:
            try:
                await api.poll(int(oid), bot=bot)
            except Exception as exc:
                log.exception('PasarGuard PAYG metering failed order=%s', oid)
                try:
                    async with SessionLocal() as err_session:
                        record = (await err_session.execute(select(PasarGuardPanelMeter).where(
                            PasarGuardPanelMeter.order_id == int(oid)))).scalar_one_or_none()
                        if record:
                            record.last_error = f'Metering unavailable: {type(exc).__name__}'
                            await err_session.commit()
                except Exception:
                    log.exception('Unable to persist PAYG meter error order=%s', oid)

    await asyncio.gather(*(sync_one(int(oid)) for oid in ids))
