from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import json
import re
from decimal import Decimal, InvalidOperation
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy import select, update, delete, or_, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from app.core.config import settings
from app.database.session import SessionLocal
from app.database.models import User, Server, ClientService, TestAccountUsage, TestAccountCounter
from app.database.defaults import get_setting_value, WELCOME_TEXT_DEFAULT
from app.bot.keyboards.common import BTN_TEST_ACCOUNT, CB_TEST_ACCOUNT, back_main_inline, main_menu_inline, report_home_inline
from app.bot.service_presenter import send_service_info
from app.xui.client import XuiClientPayload
from app.services.xui_service import XuiService
from app.services.mikrotik_service import MikroTikService
from app.services.pasarguard_service import PasarGuardService
from app.bot.utils import ui_page

router = Router()

def parse_inbounds(text: str) -> list[int]:
    return [int(x) for x in re.split(r'[,\s]+', text.strip()) if x.isdigit()]

def parse_volume_gb(value: str | None, default: str = '1') -> float:
    raw = (value or default).strip().replace(',', '.')
    try:
        parsed = Decimal(raw)
    except (InvalidOperation, ValueError):
        parsed = Decimal(default)
    if parsed <= 0:
        parsed = Decimal(default)
    return float(parsed)

def format_gb(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f'{value:g}'

def _is_duplicate_test_usage_error(exc: Exception) -> bool:
    text = str(exc)
    return 'test_account_usages' in text and ('telegram_id' in text or 'ix_test_account_usages_telegram_id' in text)


def _is_remote_client_name_conflict(exc: Exception) -> bool:
    """Return True only for duplicate client username/email errors from a remote panel."""
    text = str(exc or '').strip().lower()
    return any(phrase in text for phrase in (
        'email already in use',
        'email is already in use',
        'email already exists',
        'duplicate email',
        'username already in use',
        'username already exists',
        'duplicate username',
    ))


_SEQUENTIAL_TEST_NAME_RE = re.compile(r'^test_(\d+)$', re.IGNORECASE)


def _extract_test_number(value: str | None) -> int:
    match = _SEQUENTIAL_TEST_NAME_RE.fullmatch(str(value or '').strip())
    return int(match.group(1)) if match else 0


async def _next_test_client_name() -> str:
    """Allocate a persistent sequential name such as ``test_000001``.

    The counter is updated in its own committed transaction so a number is never
    reused after a remote timeout or a local provisioning rollback. PostgreSQL
    and SQLite use an atomic UPSERT, making allocation safe across concurrent bot
    workers and repeated button clicks.
    """
    async with SessionLocal() as counter_session:
        rows = (
            await counter_session.execute(
                select(ClientService.client_username, ClientService.xui_email).where(
                    or_(
                        ClientService.client_username.ilike('test_%'),
                        ClientService.xui_email.ilike('test_%'),
                    )
                )
            )
        ).all()
        max_existing = max(
            (
                max(_extract_test_number(client_username), _extract_test_number(xui_email))
                for client_username, xui_email in rows
            ),
            default=0,
        )
        first_available = max_existing + 1
        dialect_name = counter_session.get_bind().dialect.name

        if dialect_name == 'postgresql':
            stmt = (
                pg_insert(TestAccountCounter)
                .values(id=1, next_number=first_available + 1)
                .on_conflict_do_update(
                    index_elements=[TestAccountCounter.id],
                    set_={
                        'next_number': func.greatest(
                            TestAccountCounter.next_number,
                            first_available,
                        ) + 1,
                    },
                )
                .returning(TestAccountCounter.next_number - 1)
            )
            allocated = int((await counter_session.execute(stmt)).scalar_one())
        elif dialect_name == 'sqlite':
            stmt = (
                sqlite_insert(TestAccountCounter)
                .values(id=1, next_number=first_available + 1)
                .on_conflict_do_update(
                    index_elements=[TestAccountCounter.id],
                    set_={
                        'next_number': func.max(
                            TestAccountCounter.next_number,
                            first_available,
                        ) + 1,
                    },
                )
                .returning(TestAccountCounter.next_number - 1)
            )
            allocated = int((await counter_session.execute(stmt)).scalar_one())
        else:
            counter = await counter_session.get(TestAccountCounter, 1, with_for_update=True)
            if counter is None:
                allocated = first_available
                counter_session.add(TestAccountCounter(id=1, next_number=allocated + 1))
            else:
                allocated = max(int(counter.next_number or 1), first_available)
                counter.next_number = allocated + 1

        await counter_session.commit()
    return f'test_{allocated:06d}'


async def reserve_test_account_usage(session, user_id: int, telegram_id: int) -> int | None:
    """Atomically reserve the one-time test-account slot for a Telegram user.

    PostgreSQL is the default database for D Bot. Using ON CONFLICT DO NOTHING
    makes this handler safe against double-clicks and concurrent callbacks.
    SQLite/other engines fall back to flush+IntegrityError handling.
    """
    dialect_name = session.get_bind().dialect.name
    if dialect_name == 'postgresql':
        stmt = (
            pg_insert(TestAccountUsage)
            .values(
                user_id=user_id,
                telegram_id=telegram_id,
                service_id=None,
                created_at=datetime.utcnow(),
            )
            .on_conflict_do_nothing(index_elements=[TestAccountUsage.telegram_id])
            .returning(TestAccountUsage.id)
        )
        result = await session.execute(stmt)
        usage_id = result.scalar_one_or_none()
        return int(usage_id) if usage_id is not None else None

    usage = TestAccountUsage(user_id=user_id, telegram_id=telegram_id, service_id=None)
    session.add(usage)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        if _is_duplicate_test_usage_error(exc):
            return None
        raise
    return int(usage.id)


def _display_username(value: str | None) -> str:
    text = str(value or '').strip()
    if not text:
        return '-'
    return text if text.startswith('@') else f'@{text}'


def _local_now_text() -> str:
    try:
        return datetime.now(ZoneInfo(settings.TZ)).strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


async def _notify_admins_test_account(
    bot,
    *,
    telegram_id: int,
    username: str | None,
    full_name: str | None,
    client_name: str,
) -> None:
    """Best-effort owner notification for every successfully created test account."""
    try:
        admin_ids = list(dict.fromkeys(settings.owner_ids or settings.admin_ids or []))
    except Exception:
        admin_ids = []
    if not admin_ids:
        return
    text = (
        '🧪 گزارش دریافت اکانت تست\n'
        '━━━━━━━━━━━━━━\n'
        f'👤 کاربر: {full_name or "-"}\n'
        f'🆔 آیدی عددی: {telegram_id}\n'
        f'🔗 یوزرنیم: {_display_username(username)}\n'
        f'🕒 تاریخ و ساعت: {_local_now_text()}\n'
        f'🧪 نام اکانت تست: {client_name}'
    )
    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, text, reply_markup=report_home_inline())
        except Exception:
            pass


async def _delete_progress_message(message) -> None:
    if message is None:
        return
    try:
        await message.delete()
    except Exception:
        pass


def _server_default_test_inbounds(server: Server) -> list[int]:
    values: list[int] = []
    meta = server.meta or {}
    source = meta.get('inbounds') or meta.get('inbound_ids') or []
    for item in source:
        raw = item.get('id') if isinstance(item, dict) else item
        try:
            inbound_id = int(raw)
        except (TypeError, ValueError):
            continue
        if inbound_id > 0 and inbound_id not in values:
            values.append(inbound_id)
    return values


async def _load_test_account_targets() -> list[dict]:
    """Load multi-server targets and transparently support old single-server installs."""
    raw = await get_setting_value('test_account_targets_json', '[]')
    rows = []
    try:
        decoded = json.loads(raw or '[]')
        if isinstance(decoded, list):
            rows = decoded
    except (TypeError, ValueError, json.JSONDecodeError):
        rows = []

    targets: list[dict] = []
    seen: set[int] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            server_id = int(row.get('server_id') or 0)
        except (TypeError, ValueError):
            continue
        if server_id <= 0 or server_id in seen:
            continue
        raw_inbounds = row.get('inbound_ids') or []
        if isinstance(raw_inbounds, str):
            raw_inbounds = re.split(r'[,\s]+', raw_inbounds.strip())
        inbound_ids: list[int] = []
        if isinstance(raw_inbounds, list):
            for item in raw_inbounds:
                try:
                    inbound_id = int(item.get('id') if isinstance(item, dict) else item)
                except (TypeError, ValueError):
                    continue
                if inbound_id > 0 and inbound_id not in inbound_ids:
                    inbound_ids.append(inbound_id)
        targets.append({'server_id': server_id, 'inbound_ids': inbound_ids})
        seen.add(server_id)

    if targets:
        return targets
    legacy_server_id = await get_setting_value('test_account_server_id', '')
    if str(legacy_server_id).isdigit():
        return [{
            'server_id': int(legacy_server_id),
            'inbound_ids': parse_inbounds(await get_setting_value('test_account_inbound_ids', '')),
        }]
    return []


async def _create_test_account_on_target(*, user_id: int, target: dict, volume_gb: float, duration_days: int) -> dict:
    """Provision one test account atomically for one selected backend server."""
    async with SessionLocal() as session:
        server = await session.get(Server, int(target['server_id']))
        if not server or not server.is_active:
            raise RuntimeError(f'Test server #{target["server_id"]} is unavailable')
        if (server.meta or {}).get('scope') == 'reseller':
            raise RuntimeError(f'Test server {server.name} is reseller-only')

        inbound_ids = [int(x) for x in (target.get('inbound_ids') or []) if str(x).isdigit()]
        if server.server_type == 'mikrotik':
            inbound_ids = []
        elif not inbound_ids:
            inbound_ids = _server_default_test_inbounds(server)
        if server.server_type == 'xui' and not inbound_ids:
            raise RuntimeError(f'No active inbound is configured for X-UI test server {server.name}')

        client_name = await _next_test_client_name()
        service = ClientService(
            user_id=user_id,
            server_id=server.id,
            plan_id=None,
            client_username=client_name,
            xui_email=client_name,
            inbound_ids=inbound_ids,
            total_bytes=int(volume_gb * 1024**3),
            expires_at=datetime.utcnow() + timedelta(days=duration_days),
            is_active=True,
        )
        session.add(service)
        await session.flush()
        sub_link = None
        mt_password = None

        if server.server_type == 'xui':
            # A stale name can remain on a remote panel after a restore. Keep
            # consuming the persistent sequence until a genuinely new client is created.
            max_create_attempts = 100
            created = None
            for attempt in range(max_create_attempts):
                if attempt:
                    client_name = await _next_test_client_name()
                    service.client_username = client_name
                    service.xui_email = client_name
                    await session.flush()
                payload = XuiClientPayload(email=client_name, total_gb=volume_gb, expire_days=duration_days)
                try:
                    created = await XuiService().create_client_on_inbounds(server, inbound_ids, payload)
                    break
                except Exception as exc:
                    if _is_remote_client_name_conflict(exc) and attempt + 1 < max_create_attempts:
                        continue
                    raise
            if isinstance(created, dict):
                sub_link = created.get('sub_link')
                service.sub_link = sub_link
                service.xui_uuid = str(created.get('uuid')) if created.get('uuid') is not None else None
        elif server.server_type == 'mikrotik':
            _Plan = type('MikroTikTestPlan', (), {'volume_gb': volume_gb, 'duration_days': duration_days, 'inbound_ids': []})
            created = await MikroTikService().create_user_on_plan(server, _Plan, client_name)
            mt_password = created.get('password') if isinstance(created, dict) else None
            service.sub_link = None
            service.xui_uuid = str(mt_password or '')
        elif server.server_type == 'pasarguard':
            _Plan = type('PasarGuardTestPlan', (), {'volume_gb': volume_gb, 'duration_days': duration_days, 'inbound_ids': inbound_ids, 'hwid_limit': 0})
            created = await PasarGuardService().create_user_on_plan(server, _Plan, client_name)
            sub_link = created.get('sub_link') if isinstance(created, dict) else None
            service.sub_link = sub_link
            service.xui_uuid = str(created.get('uuid') or '') if isinstance(created, dict) else None
        else:
            raise RuntimeError(f'Unsupported test-account server type: {server.server_type}')

        await session.commit()
        return {
            'service_id': int(service.id),
            'server_id': int(server.id),
            'server_name': server.name,
            'server_type': server.server_type,
            'client_name': client_name,
            'sub_link': sub_link,
            'password': mt_password,
            'inbound_ids': inbound_ids,
        }


async def handle_test_account(target, telegram_id: int, username: str | None):
    if await get_setting_value('test_account_enabled', '1') != '1':
        await ui_page(target, '⛔️ دریافت اکانت تست فعلاً غیرفعال است.', reply_markup=back_main_inline())
        return

    targets = await _load_test_account_targets()
    volume_gb = parse_volume_gb(await get_setting_value('test_account_volume_gb', '1'), '1')
    try:
        duration_days = max(1, int(await get_setting_value('test_account_duration_days', '1') or '1'))
    except (TypeError, ValueError):
        duration_days = 1
    if not targets:
        await ui_page(target, '⚠️ تنظیمات اکانت تست هنوز توسط مدیر کامل نشده است.', reply_markup=back_main_inline())
        return

    is_admin = telegram_id in settings.admin_ids
    usage_id: int | None = None
    async with SessionLocal() as session:
        user = (await session.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one()
        user_id = int(user.id)
        user_full_name = user.full_name
        user_username = user.username or username

        # One user request may now create several trial services, but it still
        # consumes only one one-time trial entitlement.
        if not is_admin:
            used = (await session.execute(
                select(TestAccountUsage).where(TestAccountUsage.telegram_id == telegram_id)
            )).scalar_one_or_none()
            if used:
                await ui_page(target, '⛔️ شما قبلاً یک بار اکانت تست دریافت کرده‌اید.', reply_markup=back_main_inline())
                return
            usage_id = await reserve_test_account_usage(session, user.id, telegram_id)
            if not usage_id:
                await session.rollback()
                await ui_page(target, '⛔️ شما قبلاً یک بار اکانت تست دریافت کرده‌اید.', reply_markup=back_main_inline())
                return
            # Commit the reservation before remote provisioning so repeated taps
            # cannot start a second multi-server batch while this one is running.
            await session.commit()

    progress_message = None
    try:
        progress_message = await target.bot.send_message(
            telegram_id,
            '⏳ در حال ساخت اکانت تست هستیم، لطفاً صبر کنید...' + f'\n📦 تعداد سرورهای انتخاب‌شده: {len(targets)}'
        )
    except Exception:
        progress_message = None

    successes: list[dict] = []
    failures: list[dict] = []
    from app.bot.error_reporting import report_bot_error
    for item in targets:
        try:
            created = await _create_test_account_on_target(
                user_id=user_id,
                target=item,
                volume_gb=volume_gb,
                duration_days=duration_days,
            )
            successes.append(created)
        except Exception as exc:
            failures.append({'server_id': item.get('server_id'), 'error': str(exc)})
            await report_bot_error(
                target.bot,
                exc,
                context=f'Test account provisioning failed telegram_id={telegram_id} server_id={item.get("server_id")}',
                event=target,
            )

    if not successes:
        # Nothing was delivered; release the entitlement so a normal user can retry.
        if usage_id is not None:
            async with SessionLocal() as session:
                await session.execute(delete(TestAccountUsage).where(TestAccountUsage.id == usage_id))
                await session.commit()
        await _delete_progress_message(progress_message)
        await ui_page(
            target,
            '⚠️ ساخت اکانت تست روی سرورهای انتخاب‌شده کامل نشد. لطفاً چند لحظه دیگر دوباره تلاش کنید یا با پشتیبانی در ارتباط باشید.',
            reply_markup=back_main_inline(),
        )
        return

    # The legacy usage table stores one service_id. Link it to the first success
    # for old history screens; all generated test_* services are independently
    # recognized as trial services by cleanup/alert workers.
    if usage_id is not None:
        async with SessionLocal() as session:
            await session.execute(
                update(TestAccountUsage)
                .where(TestAccountUsage.id == usage_id)
                .values(service_id=successes[0]['service_id'])
            )
            await session.commit()

    for created in successes:
        await _notify_admins_test_account(
            target.bot,
            telegram_id=telegram_id,
            username=user_username,
            full_name=user_full_name,
            client_name=f"{created['client_name']} | {created['server_name']}",
        )
        await send_service_info(
            target.bot,
            telegram_id,
            created['client_name'],
            f"اکانت تست | {created['server_name']}",
            volume_gb,
            duration_days,
            created['sub_link'],
            is_test=True,
            reply_markup=back_main_inline(),
            service_id=created['service_id'],
            server_type=created['server_type'],
            password=created['password'],
        )

    await _delete_progress_message(progress_message)

    async with SessionLocal() as session:
        user = (await session.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one_or_none()
        is_reseller = False
        if user:
            from app.database.models import ResellerAccount
            reseller = (await session.execute(select(ResellerAccount).where(ResellerAccount.user_id == user.id))).scalar_one_or_none()
            is_reseller = bool(reseller and reseller.is_active)

    if failures:
        result_text = (
            f'✅ {len(successes)} اکانت تست برای شما ارسال شد.\n'
            f'⚠️ ساخت اکانت روی {len(failures)} سرور کامل نشد.\n\n'
            'برای سرورهای ناموفق می‌توانید با پشتیبانی در ارتباط باشید.\n\nبه صفحه اصلی برگشتید.'
        )
    else:
        result_text = f'✅ تمام {len(successes)} اکانت تست برای شما ارسال شد.\n\nبه صفحه اصلی برگشتید.'
    await target.bot.send_message(
        telegram_id,
        result_text,
        reply_markup=await main_menu_inline(is_admin, is_reseller=is_reseller),
    )

@router.message(F.text == BTN_TEST_ACCOUNT)
async def test_account_text(message: Message):
    await handle_test_account(message, message.from_user.id, message.from_user.username)

async def safe_callback_answer(callback: CallbackQuery) -> None:
    """Acknowledge inline-button clicks without crashing on expired callbacks."""
    try:
        await callback.answer()
    except TelegramBadRequest as exc:
        # Telegram allows answering callback queries only for a short time.
        # If the query is already expired/invalid, ignore it and continue.
        if 'query is too old' not in str(exc) and 'query ID is invalid' not in str(exc):
            raise


@router.callback_query(F.data == CB_TEST_ACCOUNT)
async def test_account_cb(callback: CallbackQuery):
    await safe_callback_answer(callback)
    await handle_test_account(callback.message, callback.from_user.id, callback.from_user.username)
