"""Customer self-service transfer of remaining prepaid traffic between categories."""
from __future__ import annotations

import logging
from datetime import datetime

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database.session import SessionLocal
from app.database.models import ClientService, Server, ServerCategory, Plan, User, ServiceConversion
from app.services.plan_conversion import load_rules, quote_conversion, format_volume, format_conversion_preview, GIB
from app.services.conversion_provider import live_source, set_enabled, create_converted
from app.services.service_deletion_audit import build_service_deletion_snapshot
from app.jobs.service_cleanup import enqueue_service_deletion, record_completed_service_deletion
from app.bot.keyboards.common import back_button, back_main_inline
from app.bot.utils import edit_or_answer
from app.bot.service_presenter import send_service_info

logger = logging.getLogger(__name__)
router = Router()
SUPPORTED = {'xui', 'pasarguard'}


def kb(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _source(session, sid: int, telegram_id: int):
    user = (await session.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one_or_none()
    svc = await session.get(ClientService, sid)
    if not user or not svc or svc.user_id != user.id or svc.reseller_id is not None or not svc.is_active or str(svc.client_username or '').startswith(('deleted_', 'test_')):
        raise ValueError('این کانفیگ فعال و متعلق به شما نیست.')
    server = await session.get(Server, svc.server_id)
    if not server or server.server_type not in SUPPORTED or not server.is_active or (server.meta or {}).get('scope') == 'reseller':
        raise ValueError('این سرور برای تبدیل تعرفه پشتیبانی نمی‌شود.')
    cat_id = int(svc.purchase_category_id or 0)
    if not cat_id and svc.plan_id:
        old_plan = await session.get(Plan, svc.plan_id)
        cat_id = int(old_plan.category_id or 0) if old_plan else 0
    return user, svc, server, cat_id


async def _destination(session, svc, original_category, target_plan_id, rules):
    source_rule = rules.get(str(original_category)) or {}
    plan = await session.get(Plan, target_plan_id)
    if not plan or not plan.is_active or plan.is_unlimited or not plan.category_id or plan.category_id == original_category:
        raise ValueError('تعرفه مقصد معتبر نیست یا با تعرفه فعلی یکسان است.')
    dest_rule = rules.get(str(plan.category_id)) or {}
    server = await session.get(Server, plan.server_id)
    if not server or not server.is_active or server.server_type not in SUPPORTED or (server.meta or {}).get('scope') == 'reseller' or int(server.id) not in dest_rule.get('server_ids', []):
        raise ValueError('این سرور برای تبدیل فعال نشده است.')
    if svc.server_id not in source_rule.get('server_ids', []):
        raise ValueError('سرور مبدا برای تبدیل فعال نیست.')
    if not source_rule.get('price_per_gb_irt') or not dest_rule.get('price_per_gb_irt'):
        raise ValueError('قیمت هر گیگ دسته مبدا یا مقصد در Plans → Convert تنظیم نشده است.')
    return plan, server, source_rule, dest_rule


async def _live_quote(source_server, svc, source_rule, dest_rule):
    total, used, expiry = await live_source(source_server, svc)
    if expiry is None:
        raise ValueError('برای سرویس بدون انقضای مشخص، تبدیل امکان‌پذیر نیست.')
    return quote_conversion(max(total - used, 0), int(source_rule['price_per_gb_irt']), int(dest_rule['price_per_gb_irt']), expiry)


@router.callback_query(F.data == 'menu:convert')
async def convert_home(callback: CallbackQuery):
    async with SessionLocal() as session:
        user = (await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one_or_none()
        rules = await load_rules(session)
        services = (await session.execute(select(ClientService).where(ClientService.user_id == user.id, ClientService.is_active.is_(True), ClientService.reseller_id.is_(None)).order_by(ClientService.id.desc()))).scalars().all() if user else []
        server_ids = {s.server_id for s in services}
        servers = {s.id: s for s in (await session.execute(select(Server).where(Server.id.in_(server_ids)))).scalars().all()} if server_ids else {}
        plans = {p.id: p for p in (await session.execute(select(Plan).where(Plan.id.in_([s.plan_id for s in services if s.plan_id])))).scalars().all()}
        eligible = []
        for svc in services:
            server = servers.get(svc.server_id)
            plan = plans.get(svc.plan_id)
            cid = svc.purchase_category_id or (plan.category_id if plan else None)
            if (server and server.server_type in SUPPORTED and server.is_active
                and not str(svc.client_username or '').startswith(('test_', 'deleted_'))
                and cid and svc.total_bytes and svc.expires_at and svc.expires_at > datetime.utcnow()
                and (server.meta or {}).get('scope') != 'reseller'
                and server.id in (rules.get(str(cid)) or {}).get('server_ids', [])):
                eligible.append(svc)
    rows = [[InlineKeyboardButton(text=f'📱 {s.client_username or s.xui_email}', callback_data=f'svcconvert:source:{s.id}')] for s in eligible]
    rows.append([back_button('back:main')])
    await edit_or_answer(callback, '🔄 تبدیل تعرفه\n\nکانفیگی را انتخاب کنید که می‌خواهید اعتبار باقی‌مانده آن تبدیل شود.\n\n⚠️ پس از تبدیل موفق، کانفیگ قبلی حذف خواهد شد و زمان انقضا تغییر نمی‌کند.' if eligible else 'فعلاً کانفیگ واجد شرایط برای تبدیل ندارید. تنظیمات Convert را در پنل مدیریت بررسی کنید.', reply_markup=kb(rows))
    await callback.answer()


@router.callback_query(F.data.startswith('svcconvert:source:'))
async def convert_choose_category(callback: CallbackQuery):
    try:
        sid = int(callback.data.split(':')[-1])
        async with SessionLocal() as session:
            _user, svc, _source_server, current = await _source(session, sid, callback.from_user.id)
            rules = await load_rules(session)
            dest_categories = (await session.execute(select(ServerCategory).where(ServerCategory.is_active.is_(True)))).scalars().all()
            plans = (await session.execute(select(Plan).where(Plan.is_active.is_(True), Plan.server_id.is_not(None)))).scalars().all()
            servers = {s.id: s for s in (await session.execute(select(Server).where(Server.is_active.is_(True)))).scalars().all()}
            available = []
            for cat in dest_categories:
                rule = rules.get(str(cat.id)) or {}
                if cat.id == current or not rule.get('price_per_gb_irt'):
                    continue
                allowed = [p for p in plans if p.category_id == cat.id and p.server_id in rule.get('server_ids', []) and p.server_id in servers and servers[p.server_id].server_type in SUPPORTED and (servers[p.server_id].meta or {}).get('scope') != 'reseller']
                if allowed:
                    available.append((cat, len(allowed)))
        rows = [[InlineKeyboardButton(text=f'📦 {cat.name}', callback_data=f'svcconvert:cat:{sid}:{cat.id}')] for cat, _ in available]
        rows.append([back_button('menu:convert')])
        await edit_or_answer(callback, '🗂 دسته مقصد را انتخاب کنید:' if available else 'هیچ دسته مقصدی برای تبدیل فعال نشده است.', reply_markup=kb(rows))
    except (ValueError, TypeError) as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()


@router.callback_query(F.data.startswith('svcconvert:cat:'))
async def convert_choose_server(callback: CallbackQuery):
    try:
        _, _, sid, cid = callback.data.split(':')
        sid, cid = int(sid), int(cid)
        async with SessionLocal() as session:
            _user, svc, _server, current = await _source(session, sid, callback.from_user.id)
            if cid == current:
                raise ValueError('دسته مقصد باید با دسته فعلی متفاوت باشد.')
            rules = await load_rules(session)
            target = rules.get(str(cid)) or {}
            plans = (await session.execute(select(Plan).where(Plan.category_id == cid, Plan.is_active.is_(True)))).scalars().all()
            servers = {s.id: s for s in (await session.execute(select(Server).where(Server.is_active.is_(True)))).scalars().all()}
            valid = [p for p in plans if p.server_id in target.get('server_ids', []) and p.server_id in servers and servers[p.server_id].server_type in SUPPORTED and (servers[p.server_id].meta or {}).get('scope') != 'reseller']
            rows = [[InlineKeyboardButton(text=f'🖥 {servers[p.server_id].name} — {p.title}', callback_data=f'svcconvert:quote:{sid}:{p.id}')] for p in valid]
        rows.append([back_button(f'svcconvert:source:{sid}')])
        await edit_or_answer(callback, '🖥 سرور و پلن مقصد را انتخاب کنید:' if valid else 'سرور/پلنی برای این دسته فعال نیست.', reply_markup=kb(rows))
    except (ValueError, TypeError) as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()


@router.callback_query(F.data.startswith('svcconvert:quote:'))
async def convert_preview(callback: CallbackQuery, state: FSMContext):
    await callback.answer('⏳ در حال دریافت مصرف واقعی از پنل...')
    try:
        sid, pid = (int(item) for item in callback.data.split(':')[-2:])
        async with SessionLocal() as session:
            _user, svc, source_server, cid = await _source(session, sid, callback.from_user.id)
            rules = await load_rules(session)
            plan, dest_server, source_rule, dest_rule = await _destination(session, svc, cid, pid, rules)
            quote = await _live_quote(source_server, svc, source_rule, dest_rule)
            source_cat = await session.get(ServerCategory, cid)
            dest_cat = await session.get(ServerCategory, plan.category_id)
        await state.update_data(convert_quote={
            'source_id': sid, 'target_plan_id': pid,
            'source_remaining_bytes': quote['source_remaining_bytes'],
            'expires_at': quote['expires_at'].isoformat(),
            'source_rate': quote['source_rate_irt'], 'dest_rate': quote['destination_rate_irt'],
        })
        text = format_conversion_preview(
            username=svc.client_username or svc.xui_email or '',
            source_category=source_cat.name if source_cat else str(cid),
            target_category=dest_cat.name if dest_cat else str(plan.category_id),
            target_server=dest_server.name,
            quote=quote,
        )
        await edit_or_answer(callback, text, reply_markup=kb([
            [InlineKeyboardButton(text='✅ تأیید نهایی تبدیل', callback_data=f'svcconvert:confirm:{sid}:{pid}')],
            [back_button(f'svcconvert:cat:{sid}:{plan.category_id}')]
        ]), parse_mode='HTML')
    except Exception as exc:
        logger.warning('Conversion preview failed: %s', exc)
        await callback.message.answer(f'❌ امکان محاسبه تبدیل نیست: {exc}', reply_markup=kb([[back_button('menu:convert')]]))


@router.callback_query(F.data.startswith('svcconvert:confirm:'))
async def convert_confirm(callback: CallbackQuery, state: FSMContext):
    await callback.answer('⏳ درخواست تبدیل دریافت شد؛ لطفاً دوباره کلیک نکنید.')
    try:
        sid, pid = (int(item) for item in callback.data.split(':')[-2:])
    except (ValueError, TypeError):
        return
    saved = (await state.get_data()).get('convert_quote') or {}
    if int(saved.get('source_id') or 0) != sid or int(saved.get('target_plan_id') or 0) != pid:
        await callback.message.answer('پیش‌نمایش تبدیل منقضی شده است. دوباره از ابتدا شروع کنید.', reply_markup=kb([[back_button('menu:convert')]]))
        return
    conversion_id = None
    source_disabled = False
    new_provision_started = False
    dest_created = False
    username = f'cv{sid}_{pid}'
    async with SessionLocal() as session:
        try:
            user, source, source_server, cid = await _source(session, sid, callback.from_user.id)
            existing = (await session.execute(select(ServiceConversion).where(ServiceConversion.source_service_id == sid))).scalar_one_or_none()
            if existing:
                raise ValueError('این کانفیگ قبلاً تبدیل شده یا در حال بررسی است؛ درخواست تکراری امکان‌پذیر نیست.')
            rules = await load_rules(session)
            dest_plan, dest_server, src_rule, dst_rule = await _destination(session, source, cid, pid, rules)
            quote = await _live_quote(source_server, source, src_rule, dst_rule)
            old_remaining = int(saved.get('source_remaining_bytes') or 0)
            if (quote['source_rate_irt'] != int(saved.get('source_rate') or 0) or
                quote['destination_rate_irt'] != int(saved.get('dest_rate') or 0) or
                abs(old_remaining - quote['source_remaining_bytes']) > 1024 ** 2 or
                quote['expires_at'].isoformat() != saved.get('expires_at')):
                raise ValueError('مصرف، نرخ یا انقضای سرویس تغییر کرده؛ لطفاً پیش‌نمایش تبدیل را دوباره مشاهده کنید.')
            item = ServiceConversion(source_service_id=sid, target_plan_id=pid, user_id=user.id,
                status='reserved', source_remaining_bytes=quote['source_remaining_bytes'],
                target_total_bytes=quote['destination_bytes'], source_rate_irt=quote['source_rate_irt'],
                target_rate_irt=quote['destination_rate_irt'], expires_at=quote['expires_at'])
            session.add(item)
            await session.commit()  # Durable unique claim BEFORE any panel-side mutation.
            conversion_id = item.id
        except IntegrityError:
            await session.rollback()
            await callback.message.answer('این کانفیگ هم‌اکنون در حال تبدیل است یا قبلاً تبدیل شده است.')
            return
        except Exception as exc:
            await callback.message.answer(f'❌ {exc}', reply_markup=kb([[back_button('menu:convert')]]))
            return

    try:
        await set_enabled(source_server, source.xui_email or source.client_username, False)
        source_disabled = True
        new_provision_started = True
        created = await create_converted(dest_server, dest_plan, username, quote['destination_bytes'], quote['expires_at'])
        dest_created = True
        async with SessionLocal() as session:
            record = await session.get(ServiceConversion, conversion_id)
            source_db = await session.get(ClientService, sid)
            if not record or not source_db or record.status != 'reserved':
                raise RuntimeError('Conversion reservation changed unexpectedly.')
            new_service = ClientService(user_id=record.user_id, server_id=dest_server.id, plan_id=pid,
                purchase_category_id=dest_plan.category_id, client_username=username, xui_email=username,
                total_bytes=quote['destination_bytes'], used_bytes=0, expires_at=quote['expires_at'], is_active=True,
                xui_uuid=str((created or {}).get('uuid') or ''),
                sub_link=(created or {}).get('sub_link') or None,
                inbound_ids=list((created or {}).get('inbound_ids') or []))
            session.add(new_service)
            await session.flush()
            record.target_service_id = new_service.id
            record.status = 'completed'
            record.completed_at = datetime.utcnow()
            # Hide source immediately. It is disabled upstream; deletion is queued or completed next.
            source_db.is_active = False
            source_db.disabled_reason = 'converted'
            source_db.disabled_at = datetime.utcnow()
            deletion_snapshot = await build_service_deletion_snapshot(session, source_db, server=source_server, source='conversion', reason='converted')
            await enqueue_service_deletion(session, source_db, now=datetime.utcnow(), reason='converted', deletion_snapshot=deletion_snapshot)
            await session.commit()
            new_id = new_service.id
        # Durable deletion task removes the disabled old remote client asynchronously.
        # If upstream is unavailable it retries without affecting the new service.
        await state.update_data(convert_quote=None)
        await callback.message.answer('✅ تبدیل تعرفه انجام شد. کانفیگ جدید با حجم معادل و تاریخ انقضای قبلی ساخته شد. در حال ارسال اطلاعات اتصال...')
        try:
            await send_service_info(callback.message.bot, callback.from_user.id, username,
                dest_plan.title, quote['destination_bytes'] / GIB, round(quote['remaining_seconds'] / 86400, 2),
                (created or {}).get('sub_link') or '', is_test=False, service_id=new_id,
                server_type=dest_server.server_type)
        except Exception:
            logger.exception('Conversion completed but delivery failed for service %s', new_id)
            await callback.message.answer('کانفیگ جدید در «کانفیگ‌های من» ثبت شده است؛ ارسال کارت ناموفق بود. از آن بخش لینک را دریافت کنید.', reply_markup=kb([[back_button('menu:my_services')]]))
    except Exception as exc:
        logger.exception('Plan conversion failed after reservation id=%s', conversion_id)
        # Never automatically retry ambiguous writes; an API timeout can mean creation succeeded.
        async with SessionLocal() as session:
            record = await session.get(ServiceConversion, conversion_id) if conversion_id else None
            if record and record.status != 'completed':
                # Any panel mutation may have succeeded before a timeout/readback failure.
                # Always hold the claimed source for manual reconciliation.
                record.status = 'needs_review'
                record.error = str(exc)[:1500]
                await session.commit()
        # A network timeout may occur AFTER a provider created the client. Never
        # retry blindly. Inform administrators so they can reconcile both panels.
        try:
            from app.core.config import settings
            for admin_id in settings.admin_ids:
                try:
                    await callback.message.bot.send_message(int(admin_id),
                        f'⚠️ نیازمند بررسی تبدیل تعرفه #{conversion_id}\n'
                        f'کاربر: {callback.from_user.id}\nسرویس قدیمی: {sid}\n'
                        f'کانفیگ احتمالی جدید: {username}\nخطا: {str(exc)[:500]}')
                except Exception:
                    logger.warning('Could not notify conversion recovery admin %s', admin_id)
        except Exception:
            logger.exception('Conversion admin notification failed')
        await callback.message.answer('❌ تبدیل به مشکل خورد. برای جلوگیری از ثبت اعتبار تکراری، این درخواست برای بررسی مدیر نگه داشته شد. لطفاً تیکت ثبت کنید و شناسه درخواست را اطلاع دهید: ' + str(conversion_id))
