from __future__ import annotations

import logging
from datetime import datetime, timedelta

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import and_, delete, func, or_, select, update

from app.database.models import (
    ClientService,
    Order,
    Server,
    ServiceDeletionTask,
    TestAccountUsage,
    User,
)
from app.database.session import SessionLocal
from app.services.mikrotik_service import MikroTikService
from app.services.reseller_service import (
    apply_reseller_usage_delta,
    drop_inactive_reservation,
    reconcile_reseller_accounting,
    release_reserved_volume,
)
from app.services.service_deletion_audit import (
    build_service_deletion_snapshot,
    notify_admins_service_deletion,
)
from app.services.service_grace import (
    SERVICE_RENEWAL_GRACE,
    grace_deadline,
    is_auto_purge_service,
    is_tombstone,
    local_terminal_reason,
    mark_service_active,
    mark_service_disabled,
)
from app.services.xui_service import XuiService

logger = logging.getLogger(__name__)

TEST_ACCOUNT_PURGE_AFTER = timedelta(hours=6)
TASK_BATCH_SIZE = 50
SERVICE_SCAN_BATCH_SIZE = 500

_PENDING_TASK_STATUSES = ('pending', 'retry')
_NOT_FOUND_TOKENS = (
    'not found',
    'not exist',
    'not exists',
    'record not found',
    'no such',
    'already deleted',
    '404',
)


def retry_delay(attempt_count: int) -> timedelta:
    """Return a bounded retry delay for temporary panel failures."""
    delays_minutes = (5, 15, 30, 60, 180, 360, 720)
    index = min(max(int(attempt_count or 1) - 1, 0), len(delays_minutes) - 1)
    return timedelta(minutes=delays_minutes[index])


def _panel_missing(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(token in message for token in _NOT_FOUND_TOKENS)


def _task_identifiers(
    svc: ClientService,
    *,
    is_test: bool,
    deletion_snapshot: dict | None = None,
) -> dict:
    return {
        'client_username': svc.client_username,
        'xui_email': svc.xui_email,
        'xui_uuid': svc.xui_uuid,
        'sub_link': svc.sub_link,
        'inbound_ids': list(svc.inbound_ids or []),
        'is_reseller_service': bool(getattr(svc, 'reseller_id', None)),
        'is_test_service': bool(is_test),
        'deletion_snapshot': dict(deletion_snapshot or {}),
    }


async def enqueue_service_deletion(
    session,
    svc: ClientService,
    *,
    now: datetime | None = None,
    reason: str | None = None,
    is_test: bool = False,
    deletion_snapshot: dict | None = None,
) -> ServiceDeletionTask:
    """Remove a due service locally and persist its panel deletion request.

    Local removal is deliberately not blocked by an unavailable panel. The
    task keeps the upstream identifiers and is retried by the cleanup worker.
    """
    now = now or datetime.utcnow()
    source_service_id = int(svc.id)
    server = await session.get(Server, svc.server_id) if svc.server_id else None
    resolved_reason = reason or local_terminal_reason(svc, now) or svc.disabled_reason or 'expired'
    if deletion_snapshot is None:
        deletion_snapshot = await build_service_deletion_snapshot(
            session,
            svc,
            server=server,
            source='automatic_72h',
            reason=resolved_reason,
            deleted_at=now,
        )

    task = (await session.execute(
        select(ServiceDeletionTask)
        .where(ServiceDeletionTask.source_service_id == source_service_id)
        .limit(1)
    )).scalar_one_or_none()

    original_username = svc.client_username or svc.xui_email or f'#{source_service_id}'
    if task is None:
        task = ServiceDeletionTask(
            source_service_id=source_service_id,
            user_id=svc.user_id,
            server_id=svc.server_id,
            server_type=(server.server_type if server else ''),
            username=original_username[:150],
            identifiers=_task_identifiers(svc, is_test=is_test, deletion_snapshot=deletion_snapshot),
            reason=resolved_reason[:32],
            status='pending',
            attempt_count=0,
            next_attempt_at=now,
            created_at=now,
        )
        session.add(task)
        await session.flush()
    else:
        # Defensive recovery for restored/partially rolled-back databases: if a
        # live service row exists again, refresh the snapshot and make sure the
        # cleanup task is actionable rather than trusting stale completion data.
        task.user_id = svc.user_id
        task.server_id = svc.server_id
        task.server_type = server.server_type if server else task.server_type
        task.username = original_username[:150]
        task.identifiers = _task_identifiers(svc, is_test=is_test, deletion_snapshot=deletion_snapshot)
        task.reason = resolved_reason[:32]
        task.admin_notified_at = None
        if task.status == 'completed':
            task.status = 'pending'
            task.completed_at = None
            task.notified_at = None
            task.next_attempt_at = now

    # Accounting/history rows remain, but no longer point at a service that is
    # outside its renewal window.
    await session.execute(update(Order).where(Order.service_id == source_service_id).values(service_id=None))
    await session.execute(
        update(TestAccountUsage)
        .where(TestAccountUsage.service_id == source_service_id)
        .values(service_id=None)
    )

    if getattr(svc, 'reseller_id', None):
        # Reseller activity/accounting screens rely on the historical row, so
        # keep a non-visible tombstone while releasing any reserved inventory.
        await release_reserved_volume(session, svc)
        svc.is_active = False
        svc.disabled_reason = 'purge_queued'
        svc.disabled_at = svc.disabled_at or now
        if not is_tombstone(svc):
            svc.client_username = f'deleted_{source_service_id}_{original_username}'[:150]
    else:
        # Public/test services can be fully removed. The queue now owns all
        # identifiers needed for eventual deletion from the upstream panel.
        await session.delete(svc)

    return task


async def record_completed_service_deletion(
    session,
    svc: ClientService,
    *,
    now: datetime | None = None,
    reason: str,
    deletion_snapshot: dict,
    panel_status: str = 'deleted',
) -> ServiceDeletionTask:
    """Persist a completed deletion as a durable admin-audit event.

    Successful direct panel deletions do not need retry processing, but keeping
    a completed queue row guarantees that a temporary Telegram outage cannot
    make the manager report disappear.
    """
    now = now or datetime.utcnow()
    source_service_id = int(svc.id)
    server = await session.get(Server, svc.server_id) if svc.server_id else None
    snapshot = dict(deletion_snapshot or {})
    snapshot['panel_status'] = panel_status

    task = (await session.execute(
        select(ServiceDeletionTask)
        .where(ServiceDeletionTask.source_service_id == source_service_id)
        .limit(1)
    )).scalar_one_or_none()
    original_username = svc.client_username or svc.xui_email or f'#{source_service_id}'
    identifiers = _task_identifiers(svc, is_test=False, deletion_snapshot=snapshot)

    if task is None:
        task = ServiceDeletionTask(
            source_service_id=source_service_id,
            user_id=svc.user_id,
            server_id=svc.server_id,
            server_type=(server.server_type if server else ''),
            username=original_username[:150],
            identifiers=identifiers,
            reason=(reason or 'user_delete')[:32],
            status='completed',
            attempt_count=1,
            next_attempt_at=now,
            last_attempt_at=now,
            completed_at=now,
            admin_notified_at=None,
            created_at=now,
        )
        session.add(task)
        await session.flush()
    else:
        task.user_id = svc.user_id
        task.server_id = svc.server_id
        task.server_type = server.server_type if server else task.server_type
        task.username = original_username[:150]
        task.identifiers = identifiers
        task.reason = (reason or 'user_delete')[:32]
        task.status = 'completed'
        task.attempt_count = max(int(task.attempt_count or 0), 1)
        task.next_attempt_at = now
        task.last_attempt_at = now
        task.last_error = None
        task.completed_at = now
        task.admin_notified_at = None
    return task


async def _task_admin_snapshot(session, task: ServiceDeletionTask) -> dict:
    identifiers = dict(task.identifiers or {})
    snapshot = dict(identifiers.get('deletion_snapshot') or {})
    if snapshot:
        return snapshot

    # Backward-compatible fallback for deletion tasks created before detailed
    # admin audit snapshots were introduced.
    user = await session.get(User, task.user_id) if task.user_id else None
    server = await session.get(Server, task.server_id) if task.server_id else None
    return {
        'service_id': task.source_service_id,
        'owner_telegram_id': user.telegram_id if user else None,
        'owner_username': user.username if user else None,
        'owner_full_name': user.full_name if user else None,
        'actor_telegram_id': None,
        'actor_username': None,
        'actor_full_name': None,
        'deletion_source': 'automatic_72h' if task.reason not in ('user_delete', 'reseller_delete') else (
            'reseller_manual' if task.reason == 'reseller_delete' else 'user_manual'
        ),
        'deletion_reason': task.reason,
        'client_username': task.username,
        'panel_username': identifiers.get('xui_email') or identifiers.get('client_username') or task.username,
        'server_name': server.name if server else '-',
        'server_type': task.server_type or (server.server_type if server else '-'),
        'plan_title': '-',
        'total_bytes': 0,
        'used_bytes': 0,
        'remaining_bytes': 0,
        'created_at': None,
        'expires_at': None,
        'deleted_at': task.created_at.isoformat() if task.created_at else None,
        'is_test_service': bool(identifiers.get('is_test_service')),
    }


async def notify_service_deletion_task_admin(
    bot,
    *,
    task_id: int | None = None,
    limit: int = TASK_BATCH_SIZE,
) -> int:
    """Send durable admin reports for queued/automatic deletions.

    A successful report is timestamped on the queue row, so scheduler retries
    Telegram delivery without creating duplicate reports on normal runs.
    """
    if bot is None:
        return 0

    async with SessionLocal() as session:
        query = select(ServiceDeletionTask.id).where(ServiceDeletionTask.admin_notified_at.is_(None))
        if task_id is not None:
            query = query.where(ServiceDeletionTask.id == int(task_id))
        task_ids = list((await session.execute(
            query.order_by(ServiceDeletionTask.id.asc()).limit(max(int(limit or 0), 0))
        )).scalars().all())

    sent = 0
    for current_task_id in task_ids:
        async with SessionLocal() as session:
            task = (await session.execute(
                select(ServiceDeletionTask)
                .where(
                    ServiceDeletionTask.id == int(current_task_id),
                    ServiceDeletionTask.admin_notified_at.is_(None),
                )
                .with_for_update(skip_locked=True)
                .limit(1)
            )).scalar_one_or_none()
            if task is None:
                continue

            snapshot = await _task_admin_snapshot(session, task)
            panel_status = snapshot.get('panel_status') or ('deleted' if task.status == 'completed' else 'queued')
            delivered = await notify_admins_service_deletion(
                bot,
                snapshot,
                panel_status=panel_status,
                task_id=task.id,
            )
            if delivered:
                task.admin_notified_at = datetime.utcnow()
                sent += 1
            await session.commit()
    return sent


async def _delete_task_from_panel(session, task: ServiceDeletionTask) -> tuple[bool, str | None]:
    server = await session.get(Server, task.server_id) if task.server_id else None
    if not server:
        return False, 'Server record is unavailable; panel deletion will be retried.'

    identifiers = dict(task.identifiers or {})
    server_type = str(task.server_type or server.server_type or '').lower()
    try:
        if server_type == 'xui':
            await XuiService().delete_client(
                server,
                identifiers.get('xui_email'),
                identifiers.get('client_username'),
                identifiers.get('xui_uuid'),
                identifiers.get('sub_link'),
            )
        elif server_type in ('mikrotik', 'openvpn', 'l2tp'):
            username = identifiers.get('xui_email') or identifiers.get('client_username') or task.username
            if not username:
                return False, 'No MikroTik/OpenVPN username was stored for deletion.'
            await MikroTikService().delete_user(server, username)
        else:
            return False, f'Unsupported server type for deletion: {server_type or "unknown"}'
        return True, None
    except Exception as exc:
        if _panel_missing(exc):
            # The desired end state is already true, so the task is complete.
            return True, None
        return False, str(exc)


async def _notify_completed_task(bot, session, task: ServiceDeletionTask, now: datetime) -> None:
    if bot is None or task.notified_at is not None:
        return
    identifiers = dict(task.identifiers or {})
    if identifiers.get('is_test_service'):
        task.notified_at = now
        return
    user = await session.get(User, task.user_id) if task.user_id else None
    if not user:
        task.notified_at = now
        return
    try:
        if task.reason in ('user_delete', 'reseller_delete'):
            text = (
                '✅ پاک‌سازی کانفیگ از پنل تکمیل شد.\n\n'
                f'👤 کانفیگ: {task.username or "-"}\n'
                'این کانفیگ قبلاً از ربات حذف شده بود و اکنون حذف آن از پنل نیز با موفقیت انجام شد.'
            )
        else:
            text = (
                '🗑 کانفیگ منقضی‌شده شما پس از پایان مهلت ۷۲ ساعته حذف شد.\n\n'
                f'👤 کانفیگ: {task.username or "-"}\n'
                '✅ از بخش کانفیگ‌های ربات حذف شد.\n'
                '✅ از پنل سرویس نیز حذف شد.'
            )
        await bot.send_message(
            user.telegram_id,
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text='🏠 خانه', callback_data='home:main')]
            ]),
        )
        task.notified_at = now
    except Exception as exc:
        # Panel cleanup is complete even if Telegram cannot deliver this notice.
        logger.warning('Service deletion completion notice failed task_id=%s: %s', task.id, exc)


async def process_service_deletion_queue(bot=None, *, limit: int = TASK_BATCH_SIZE) -> int:
    """Retry pending panel deletions without restoring services to user lists."""
    processed = 0
    for _ in range(max(int(limit or 0), 0)):
        async with SessionLocal() as session:
            now = datetime.utcnow()
            task = (await session.execute(
                select(ServiceDeletionTask)
                .where(
                    ServiceDeletionTask.status.in_(_PENDING_TASK_STATUSES),
                    ServiceDeletionTask.next_attempt_at <= now,
                )
                .order_by(ServiceDeletionTask.next_attempt_at.asc(), ServiceDeletionTask.id.asc())
                .with_for_update(skip_locked=True)
                .limit(1)
            )).scalar_one_or_none()
            if task is None:
                break

            task.attempt_count = int(task.attempt_count or 0) + 1
            task.last_attempt_at = now
            success, error = await _delete_task_from_panel(session, task)
            if success:
                task.status = 'completed'
                task.completed_at = now
                task.last_error = None
                await _notify_completed_task(bot, session, task, now)
                logger.info(
                    'Service panel deletion completed task_id=%s source_service_id=%s attempts=%s',
                    task.id,
                    task.source_service_id,
                    task.attempt_count,
                )
            else:
                task.status = 'retry'
                task.last_error = (error or 'Unknown panel deletion error')[:4000]
                task.next_attempt_at = now + retry_delay(task.attempt_count)
                logger.warning(
                    'Service panel deletion retry scheduled task_id=%s source_service_id=%s attempt=%s next=%s error=%s',
                    task.id,
                    task.source_service_id,
                    task.attempt_count,
                    task.next_attempt_at,
                    task.last_error,
                )
            await session.commit()
            processed += 1
    return processed


async def _test_service_ids(session, service_ids: list[int]) -> set[int]:
    if not service_ids:
        return set()
    rows = (await session.execute(
        select(TestAccountUsage.service_id)
        .where(TestAccountUsage.service_id.in_(service_ids))
    )).scalars().all()
    return {int(service_id) for service_id in rows if service_id is not None}


async def _mark_terminal_services(session, now: datetime, *, limit: int | None = SERVICE_SCAN_BATCH_SIZE) -> None:
    """Backfill/refresh the start of the renewal grace period."""
    terminal_query = (
        select(ClientService)
        .where(or_(
            ClientService.client_username.is_(None),
            ~ClientService.client_username.like('deleted_%'),
        ))
        .where(or_(
            and_(ClientService.expires_at.is_not(None), ClientService.expires_at <= now),
            and_(ClientService.total_bytes > 0, ClientService.used_bytes >= ClientService.total_bytes),
        ))
        .order_by(ClientService.id.asc())
    )
    if limit is not None:
        terminal_query = terminal_query.limit(max(int(limit), 1))
    terminal_candidates = (await session.execute(terminal_query)).scalars().all()
    for svc in terminal_candidates:
        reason = local_terminal_reason(svc, now)
        if reason:
            mark_service_disabled(svc, now, reason=reason)

    # Older installs may already have an inactive auto-purge service without a
    # disabled_at timestamp. Start/backfill the clock once so it cannot remain
    # forever merely because an old sync path omitted the tracking fields.
    tracking_query = (
        select(ClientService)
        .where(
            ClientService.is_active == False,
            ClientService.disabled_at.is_(None),
            or_(
                ClientService.client_username.is_(None),
                ~ClientService.client_username.like('deleted_%'),
            ),
        )
        .order_by(ClientService.id.asc())
    )
    if limit is not None:
        tracking_query = tracking_query.limit(max(int(limit), 1))
    missing_tracking = (await session.execute(tracking_query)).scalars().all()
    for svc in missing_tracking:
        reason = local_terminal_reason(svc, now) or svc.disabled_reason
        if reason in ('expired', 'volume', 'missing_on_panel', 'panel'):
            mark_service_disabled(svc, now, reason=reason)

    await session.flush()


async def _prune_stale_deletion_tasks(session, now: datetime) -> int:
    """Remove queue entries that no longer represent a deletable live service.

    Public/test services are physically removed when they enter the deletion
    queue, so tasks whose source row no longer exists must be preserved: the
    task owns the identifiers required to finish the upstream panel deletion.
    Reseller tombstones are preserved for the same reason.  For every other
    still-existing service, however, the queue must match the service's current
    state after a manual reconciliation.
    """
    rows = (await session.execute(
        select(ServiceDeletionTask, ClientService)
        .outerjoin(ClientService, ClientService.id == ServiceDeletionTask.source_service_id)
        .where(ServiceDeletionTask.status.in_(_PENDING_TASK_STATUSES))
    )).all()
    stale_ids: list[int] = []
    for task, svc in rows:
        if svc is None or is_tombstone(svc):
            continue

        stale = bool(svc.is_active) or not is_auto_purge_service(svc, now)
        if not stale:
            identifiers = dict(task.identifiers or {})
            is_test = bool(identifiers.get('is_test_service'))
            if is_test:
                expired_at = svc.expires_at if svc.expires_at and svc.expires_at <= now else None
                due = bool(expired_at and (now - expired_at) >= TEST_ACCOUNT_PURGE_AFTER)
            else:
                deadline = grace_deadline(svc, now)
                due = bool(deadline and deadline <= now)
            stale = not due

        if stale:
            stale_ids.append(int(task.id))

    if stale_ids:
        await session.execute(delete(ServiceDeletionTask).where(ServiceDeletionTask.id.in_(stale_ids)))
    return len(stale_ids)


async def _enqueue_due_services(session, now: datetime, *, limit: int | None = SERVICE_SCAN_BATCH_SIZE) -> int:
    # Six hours is the shortest supported cleanup window (test accounts), so it
    # is a safe lower bound for fetching candidates before applying per-type
    # deadlines in Python.
    candidate_cutoff = now - TEST_ACCOUNT_PURGE_AFTER
    candidate_query = (
        select(ClientService)
        .where(
            ClientService.is_active == False,
            ClientService.disabled_at.is_not(None),
            ClientService.disabled_at <= candidate_cutoff,
            or_(
                ClientService.client_username.is_(None),
                ~ClientService.client_username.like('deleted_%'),
            ),
        )
        .order_by(ClientService.disabled_at.asc(), ClientService.id.asc())
        .with_for_update(skip_locked=True)
    )
    if limit is not None:
        candidate_query = candidate_query.limit(max(int(limit), 1))
    candidates = (await session.execute(candidate_query)).scalars().all()

    test_ids = await _test_service_ids(session, [int(svc.id) for svc in candidates])
    queued = 0
    for svc in candidates:
        if not is_auto_purge_service(svc, now):
            continue

        is_test = int(svc.id) in test_ids
        if is_test:
            expired_at = svc.expires_at if svc.expires_at and svc.expires_at <= now else None
            due = bool(expired_at and (now - expired_at) >= TEST_ACCOUNT_PURGE_AFTER)
        else:
            deadline = grace_deadline(svc, now)
            due = bool(deadline and deadline <= now)
        if not due:
            continue

        await enqueue_service_deletion(
            session,
            svc,
            now=now,
            reason=local_terminal_reason(svc, now) or svc.disabled_reason,
            is_test=is_test,
        )
        queued += 1
    return queued


def _panel_enabled(value, fallback: bool = False) -> bool:
    if value is None:
        return bool(fallback)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on', 'enabled', 'active'}


def _xui_expiry_datetime(client: dict) -> datetime | None:
    try:
        raw = int(client.get('expiryTime') or client.get('expiry_time') or 0)
    except Exception:
        raw = 0
    if raw <= 0:
        return None
    # Sanaei stores expiryTime in milliseconds. Accept seconds as a defensive
    # compatibility fallback for older/custom panel forks.
    if raw > 10_000_000_000:
        raw = raw / 1000
    try:
        return datetime.utcfromtimestamp(raw)
    except Exception:
        return None


def _xui_snapshot_email(found: dict | None) -> str:
    client = (found or {}).get('client') or {}
    return str(client.get('email') or '').strip()


async def _apply_xui_snapshot(session, svc: ClientService, found: dict, now: datetime) -> tuple[bool, bool]:
    """Apply a live X-UI snapshot and return (reactivated, disabled_changed)."""
    client = found.get('client') or {}
    traffic = found.get('traffic') or {}
    panel_email = str(client.get('email') or svc.xui_email or svc.client_username or '').strip()
    if panel_email:
        svc.xui_email = panel_email
        if not svc.client_username:
            svc.client_username = panel_email

    inbound_ids: list[int] = []
    for raw in found.get('inbound_ids') or []:
        try:
            iid = int(raw)
        except Exception:
            continue
        if iid > 0 and iid not in inbound_ids:
            inbound_ids.append(iid)
    if inbound_ids:
        svc.inbound_ids = inbound_ids

    try:
        used = int((traffic.get('up', 0) or 0) + (traffic.get('down', 0) or 0))
    except Exception:
        used = int(svc.used_bytes or 0)
    if found.get('usage_known', True):
        if getattr(svc, 'reseller_id', None):
            await apply_reseller_usage_delta(session, svc, used)
        else:
            svc.used_bytes = max(used, 0)

    total_raw = traffic.get('total')
    if total_raw is None:
        total_raw = client.get('totalGB', client.get('total'))
    if total_raw is not None and found.get('total_known', True):
        try:
            svc.total_bytes = max(int(total_raw or 0), 0)
        except Exception:
            pass

    if 'expiryTime' in client or 'expiry_time' in client:
        svc.expires_at = _xui_expiry_datetime(client)

    before_active = bool(svc.is_active)
    terminal_reason = local_terminal_reason(svc, now)
    panel_active = _panel_enabled(client.get('enable', client.get('enabled')), before_active)
    if panel_active and terminal_reason is None:
        mark_service_active(svc)
        return (not before_active), False

    reason = terminal_reason or 'disabled_on_panel'
    previous_reason = svc.disabled_reason
    mark_service_disabled(svc, now, reason=reason)
    if getattr(svc, 'reseller_id', None):
        await drop_inactive_reservation(session, svc)
    return False, previous_reason != svc.disabled_reason or before_active


async def reconcile_expired_service_list(*, scan_limit: int | None = None) -> dict:
    """Reconcile DB-inactive services with panels and rebuild the deletion queue.

    This is the manual repair action behind "بررسی لیست منقضی ها". It does not
    execute panel deletions. It refreshes inactive service state from the live
    panel, restores rows that are actually active again, marks genuinely ended
    or missing services correctly, and rebuilds the pending/retry deletion list
    according to the existing 6h test / 72h normal grace rules.
    """
    now = datetime.utcnow()
    stats = {
        'scanned': 0,
        'reactivated': 0,
        'still_inactive': 0,
        'missing_on_panel': 0,
        'updated': 0,
        'queued_now': 0,
        'removed_stale': 0,
        'ready_total': 0,
        'errors': 0,
    }
    reseller_ids: set[int] = set()

    async with SessionLocal() as session:
        try:
            inactive_query = (
                select(ClientService)
                .where(
                    ClientService.is_active == False,
                    or_(
                        ClientService.client_username.is_(None),
                        ~ClientService.client_username.like('deleted_%'),
                    ),
                )
                .order_by(ClientService.id.asc())
            )
            if scan_limit is not None:
                inactive_query = inactive_query.limit(max(int(scan_limit), 1))
            services = (await session.execute(inactive_query)).scalars().all()
            stats['scanned'] = len(services)

            server_ids = {int(svc.server_id) for svc in services if svc.server_id}
            servers: dict[int, Server] = {}
            if server_ids:
                rows = (await session.execute(select(Server).where(Server.id.in_(server_ids)))).scalars().all()
                servers = {int(row.id): row for row in rows}

            # Fetch each X-UI client list once. This keeps the admin repair fast
            # even with hundreds of inactive DB rows.
            xui_maps: dict[int, dict[str, dict]] = {}
            xui_failures: set[int] = set()
            for sid, server in servers.items():
                if str(server.server_type or '').lower() != 'xui':
                    continue
                try:
                    snapshots = await XuiService().list_client_snapshots(server)
                    xui_maps[sid] = {
                        _xui_snapshot_email(row).lower(): row
                        for row in snapshots
                        if _xui_snapshot_email(row)
                    }
                except Exception as exc:
                    xui_failures.add(sid)
                    stats['errors'] += 1
                    logger.warning('Manual expired-list X-UI snapshot failed server_id=%s: %s', sid, exc)

            for svc in services:
                server = servers.get(int(svc.server_id or 0))
                if not server:
                    # Do not classify a service as missing when its server record
                    # itself is unavailable; preserve it for a later repair.
                    stats['errors'] += 1
                    continue
                try:
                    server_type = str(server.server_type or '').lower()
                    found = None
                    if server_type == 'xui':
                        if int(server.id) in xui_failures:
                            continue
                        client_map = xui_maps.get(int(server.id), {})
                        for ident in (svc.xui_email, svc.client_username):
                            key = str(ident or '').strip().lower()
                            if key and key in client_map:
                                found = client_map[key]
                                break
                        if found is None:
                            # Legacy records can have a stale email but still be
                            # recoverable by UUID/subscription identifiers.
                            try:
                                found = await XuiService().find_client_by_identifiers(
                                    server, svc.xui_email, svc.client_username, svc.xui_uuid, svc.sub_link
                                )
                            except Exception as exc:
                                stats['errors'] += 1
                                logger.warning('Expired-list targeted X-UI lookup failed service_id=%s: %s', svc.id, exc)
                                continue
                        if found:
                            reactivated, changed = await _apply_xui_snapshot(session, svc, found, now)
                            stats['reactivated'] += int(reactivated)
                            stats['updated'] += int(changed or reactivated)
                            if svc.is_active:
                                # A stale deletion task must never delete a service
                                # that the panel now confirms as active.
                                await session.execute(delete(ServiceDeletionTask).where(
                                    ServiceDeletionTask.source_service_id == int(svc.id),
                                    ServiceDeletionTask.status.in_(_PENDING_TASK_STATUSES),
                                ))
                            else:
                                stats['still_inactive'] += 1
                        else:
                            previous = svc.disabled_reason
                            mark_service_disabled(svc, now, reason='missing_on_panel')
                            if getattr(svc, 'reseller_id', None):
                                reseller_ids.add(int(svc.reseller_id))
                                await drop_inactive_reservation(session, svc)
                            stats['missing_on_panel'] += 1
                            stats['still_inactive'] += 1
                            stats['updated'] += int(previous != 'missing_on_panel')
                    elif server_type in ('mikrotik', 'openvpn', 'l2tp'):
                        try:
                            found = await MikroTikService().get_user(server, svc.xui_email or svc.client_username)
                        except Exception as exc:
                            stats['errors'] += 1
                            logger.warning('Expired-list MikroTik lookup failed service_id=%s: %s', svc.id, exc)
                            continue
                        if not found:
                            previous = svc.disabled_reason
                            mark_service_disabled(svc, now, reason='missing_on_panel')
                            if getattr(svc, 'reseller_id', None):
                                reseller_ids.add(int(svc.reseller_id))
                                await drop_inactive_reservation(session, svc)
                            stats['missing_on_panel'] += 1
                            stats['still_inactive'] += 1
                            stats['updated'] += int(previous != 'missing_on_panel')
                            continue
                        baseline = int(getattr(svc, 'traffic_baseline_bytes', 0) or 0)
                        used = MikroTikService.logical_used_bytes(found, baseline, svc.used_bytes or 0)
                        if getattr(svc, 'reseller_id', None):
                            reseller_ids.add(int(svc.reseller_id))
                            await apply_reseller_usage_delta(session, svc, used)
                        else:
                            svc.used_bytes = used
                        svc.total_bytes = MikroTikService.logical_total_bytes(found, baseline, svc.total_bytes or 0)
                        exp = found.get('expire_at')
                        if exp:
                            try:
                                svc.expires_at = datetime.fromisoformat(str(exp).replace('Z', '+00:00')).replace(tzinfo=None)
                            except Exception:
                                try:
                                    svc.expires_at = datetime.fromisoformat(str(exp)[:10])
                                except Exception:
                                    pass
                        terminal_reason = local_terminal_reason(svc, now)
                        panel_active = MikroTikService().user_is_active(found, svc.is_active)
                        if panel_active and terminal_reason is None:
                            mark_service_active(svc)
                            await session.execute(delete(ServiceDeletionTask).where(
                                ServiceDeletionTask.source_service_id == int(svc.id),
                                ServiceDeletionTask.status.in_(_PENDING_TASK_STATUSES),
                            ))
                            stats['reactivated'] += 1
                            stats['updated'] += 1
                        else:
                            mark_service_disabled(svc, now, reason=terminal_reason or 'disabled_on_mikrotik_panel')
                            if getattr(svc, 'reseller_id', None):
                                await drop_inactive_reservation(session, svc)
                            stats['still_inactive'] += 1
                    else:
                        reason = local_terminal_reason(svc, now)
                        if reason:
                            mark_service_disabled(svc, now, reason=reason)
                            stats['still_inactive'] += 1
                except Exception as exc:
                    stats['errors'] += 1
                    logger.exception('Manual expired-list reconcile failed service_id=%s: %s', svc.id, exc)
                if getattr(svc, 'reseller_id', None):
                    reseller_ids.add(int(svc.reseller_id))

            # Catch active DB rows that have locally crossed quota/expiry while
            # rebuilding the queue, then enqueue every service whose grace period
            # is actually due. This updates the "ready for deletion" list only;
            # panel deletion remains the scheduler's responsibility.
            await _mark_terminal_services(session, now, limit=None)
            # Remove old queue rows that became active, were renewed, or are no
            # longer eligible/due for automatic cleanup, then add every service
            # that is due now.  This makes the manual button a true queue
            # reconciliation instead of an append-only scan.
            stats['removed_stale'] = await _prune_stale_deletion_tasks(session, now)
            stats['queued_now'] = await _enqueue_due_services(session, now, limit=None)

            for reseller_id in reseller_ids:
                try:
                    from app.database.models import ResellerAccount
                    reseller = await session.get(ResellerAccount, reseller_id)
                    if reseller:
                        await reconcile_reseller_accounting(session, reseller)
                except Exception:
                    stats['errors'] += 1

            stats['ready_total'] = int(await session.scalar(
                select(func.count()).select_from(ServiceDeletionTask).where(
                    ServiceDeletionTask.status.in_(_PENDING_TASK_STATUSES)
                )
            ) or 0)
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception('Manual expired-list reconciliation failed')
            raise
    return stats


async def cleanup_expired_services(bot=None) -> None:
    """Remove services locally after grace and queue reliable panel cleanup."""
    now = datetime.utcnow()
    queued = 0
    async with SessionLocal() as session:
        try:
            await _mark_terminal_services(session, now)
            queued = await _enqueue_due_services(session, now)
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception('Expired service cleanup scan failed')
            return

    # Run the first panel deletion attempt immediately. Further temporary
    # failures are retried by this same scheduled job with bounded backoff.
    processed = await process_service_deletion_queue(bot)

    # Report every local removal to owners after the first panel attempt, so
    # the status says either completed or queued. Failed Telegram deliveries
    # remain unmarked and are retried by the next scheduler run.
    await notify_service_deletion_task_admin(bot)
    if queued or processed:
        logger.info('Service cleanup queued=%s processed_tasks=%s grace=%s', queued, processed, SERVICE_RENEWAL_GRACE)
