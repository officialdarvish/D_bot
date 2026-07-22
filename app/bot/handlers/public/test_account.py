from datetime import datetime, timedelta
import re
from decimal import Decimal, InvalidOperation
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy import select, update, or_, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from app.core.config import settings
from app.database.session import SessionLocal
from app.database.models import User, Server, ClientService, TestAccountUsage, TestAccountCounter
from app.database.defaults import get_setting_value, WELCOME_TEXT_DEFAULT
from app.bot.keyboards.common import BTN_TEST_ACCOUNT, CB_TEST_ACCOUNT, back_main_inline, main_menu_inline
from app.bot.service_presenter import send_service_info
from app.xui.client import XuiClientPayload
from app.services.xui_service import XuiService
from app.services.mikrotik_service import MikroTikService
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


async def handle_test_account(target, telegram_id: int, username: str | None):
    if await get_setting_value('test_account_enabled', '1') != '1':
        await ui_page(target, '⛔️ دریافت اکانت تست فعلاً غیرفعال است.', reply_markup=back_main_inline())
        return
    server_id = await get_setting_value('test_account_server_id', '')
    saved_inbound_ids = parse_inbounds(await get_setting_value('test_account_inbound_ids', ''))
    volume_gb = parse_volume_gb(await get_setting_value('test_account_volume_gb', '1'), '1')
    duration_days = int(await get_setting_value('test_account_duration_days', '1') or '1')
    if not server_id:
        await ui_page(target, '⚠️ تنظیمات اکانت تست هنوز توسط مدیر کامل نشده است.', reply_markup=back_main_inline())
        return
    is_admin = telegram_id in settings.admin_ids
    async with SessionLocal() as session:
        user = (await session.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one()
        usage_id: int | None = None

        # Regular users can receive only one test account. Full-access admins
        # intentionally bypass TestAccountUsage, so they can create unlimited
        # test clients for panel checks and support troubleshooting.
        if not is_admin:
            used = (
                await session.execute(
                    select(TestAccountUsage).where(TestAccountUsage.telegram_id == telegram_id)
                )
            ).scalar_one_or_none()
            if used:
                await ui_page(target, '⛔️ شما قبلاً یک بار اکانت تست دریافت کرده‌اید.', reply_markup=back_main_inline())
                return

            # Atomically reserve the user's one-time test-account slot before
            # creating the remote client. This prevents duplicate-key crashes when
            # the user taps the button multiple times or Telegram delivers two
            # callbacks at nearly the same time.
            usage_id = await reserve_test_account_usage(session, user.id, telegram_id)
            if not usage_id:
                await session.rollback()
                await ui_page(target, '⛔️ شما قبلاً یک بار اکانت تست دریافت کرده‌اید.', reply_markup=back_main_inline())
                return

        server = await session.get(Server, int(server_id))
        if not server or not server.is_active:
            await ui_page(target, '⚠️ سرور اکانت تست در دسترس نیست.', reply_markup=back_main_inline())
            return
        inbound_ids = saved_inbound_ids or [int(x.get('id') if isinstance(x, dict) else x) for x in ((server.meta or {}).get('inbound_ids') or []) if str(x.get('id') if isinstance(x, dict) else x).isdigit()]
        # MikroTik servers have no inbounds; only X-UI requires them.
        if server.server_type == 'xui' and not inbound_ids:
            await ui_page(target, '⚠️ برای سرور اکانت تست هیچ Inbound فعالی ثبت نشده است.', reply_markup=back_main_inline())
            return
        # Allocate a readable persistent sequence: test_000001, test_000002, ...
        # The number is committed independently so failed remote calls never cause
        # a previously attempted name to be reused.
        client_name = await _next_test_client_name()
        service = ClientService(
            user_id=user.id,
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
        if usage_id is not None:
            await session.execute(
                update(TestAccountUsage)
                .where(TestAccountUsage.id == usage_id)
                .values(service_id=service.id)
            )
        sub_link = None
        mt_password = None
        try:
            if server.server_type == 'xui':
                # A stale/orphan sequential name can remain on 3x-ui after a
                # database restore. On duplicate, consume the next sequence number;
                # never overwrite or update the existing remote client.
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
                    service.xui_uuid = (str(created.get('uuid')) if created.get('uuid') is not None else None)
            elif server.server_type == 'mikrotik':
                _Plan = type('MikroTikTestPlan', (), {'volume_gb': volume_gb, 'duration_days': duration_days, 'inbound_ids': []})
                created = await MikroTikService().create_user_on_plan(server, _Plan, client_name)
                mt_password = created.get('password') if isinstance(created, dict) else None
                service.sub_link = None
                service.xui_uuid = str(mt_password or '')
        except Exception as exc:
            # Roll back the local service and, for regular users, release the
            # one-time reservation when remote provisioning did not finish.
            await session.rollback()
            from app.bot.error_reporting import report_bot_error
            await report_bot_error(
                target.bot,
                exc,
                context=f'Test account provisioning failed telegram_id={telegram_id}',
                event=target,
            )
            await ui_page(
                target,
                '⚠️ ساخت اکانت تست کامل نشد. لطفاً چند لحظه دیگر دوباره تلاش کنید یا با پشتیبانی در ارتباط باشید.',
                reply_markup=back_main_inline(),
            )
            return
        # Capture before commit expires the ORM attributes outside the session.
        new_service_id = service.id
        new_server_type = server.server_type
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            if not is_admin and _is_duplicate_test_usage_error(exc):
                await ui_page(target, '⛔️ شما قبلاً یک بار اکانت تست دریافت کرده‌اید.', reply_markup=back_main_inline())
                return
            raise
    await send_service_info(
        target.bot,
        telegram_id,
        client_name,
        'اکانت تست',
        volume_gb,
        duration_days,
        sub_link,
        is_test=True,
        reply_markup=back_main_inline(),
        service_id=new_service_id,
        server_type=new_server_type,
        password=mt_password,
    )
    async with SessionLocal() as session:
        user = (await session.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one_or_none()
        is_reseller = False
        if user:
            from app.database.models import ResellerAccount
            reseller = (await session.execute(select(ResellerAccount).where(ResellerAccount.user_id == user.id))).scalar_one_or_none()
            is_reseller = bool(reseller and reseller.is_active)
    await target.bot.send_message(
        telegram_id,
        '✅ اکانت تست برای شما ارسال شد.\n\nبه صفحه اصلی برگشتید.',
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
