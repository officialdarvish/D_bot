"""Admin inbox for failed conversions; inspection never replays panel mutations."""
from __future__ import annotations

import asyncio
from html import escape

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import func, select, update

from app.core.config import settings
from app.database.models import ClientService, Plan, Server, ServiceConversion, User
from app.database.session import SessionLocal
from app.bot.keyboards.common import CB_BACK_ADMIN, back_button
from app.bot.utils import edit_or_answer
from app.services.conversion_provider import _status_matches
from app.services.conversion_recovery import release_failed, READY
from app.services.error_backup import redact
from app.services.pasarguard_service import PasarGuardService
from app.services.xui_service import XuiService

router = Router()
OPEN = ('needs_review', 'failed', 'error')
ARCHIVED = 'review_archived'
PAGE_SIZE = 8
PREFIX = 'admin:conversions'


def markup(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)


def button(text, data):
    return InlineKeyboardButton(text=text, callback_data=data)


async def authorized(callback):
    if callback.from_user.id in settings.admin_ids:
        return True
    await callback.answer('این بخش فقط برای مدیر ربات است.', show_alert=True)
    return False


async def show_list(callback, archived=False, page=0):
    statuses = (ARCHIVED, READY) if archived else OPEN
    async with SessionLocal() as session:
        condition = ServiceConversion.status.in_(statuses)
        total = await session.scalar(select(func.count()).select_from(ServiceConversion).where(condition))
        page = min(max(0, page), max(0, (total - 1) // PAGE_SIZE))
        items = (await session.scalars(select(ServiceConversion).where(condition)
            .order_by(ServiceConversion.id.desc()).offset(page * PAGE_SIZE).limit(PAGE_SIZE))).all()
        users = {u.id: u.telegram_id for u in (await session.scalars(select(User).where(
            User.id.in_([item.user_id for item in items])))).all()} if items else {}
    view = int(archived)
    rows = [[button(f'#{item.id} | کاربر {users.get(item.user_id, item.user_id)} | سرویس {item.source_service_id}',
                    f'{PREFIX}:detail:{item.id}:{view}:{page}')] for item in items]
    nav = []
    if page: nav.append(button('⬅️ قبلی', f'{PREFIX}:list:{view}:{page-1}'))
    if (page + 1) * PAGE_SIZE < total: nav.append(button('بعدی ➡️', f'{PREFIX}:list:{view}:{page+1}'))
    if nav: rows.append(nav)
    rows.extend([
        [button('🔄 بروزرسانی فهرست', f'{PREFIX}:list:{view}:{page}')],
        [button('📂 درخواست‌های حذف‌شده' if not archived else '📋 درخواست‌های خطادار', f'{PREFIX}:list:{1-view}:0')],
        [back_button(CB_BACK_ADMIN)],
    ])
    title = '📂 درخواست‌های حذف‌شده از فهرست' if archived else '🔎 بررسی مجدد درخواست‌های تغییر تعرفه'
    text = f'{title}\n\nتعداد: {total} | صفحه {page+1}\n'
    text += 'درخواستی وجود ندارد.' if not items else 'برای مشاهده جزئیات و بررسی وضعیت پنل، درخواست را انتخاب کنید.'
    await edit_or_answer(callback, text, reply_markup=markup(rows))


async def panel_state(server, username):
    """Bound read-only diagnostics; missing/failed reads never release a claim."""
    if not server or not username: return 'اطلاعات سرور یا نام کانفیگ در دسترس نیست'
    try:
        async with asyncio.timeout(12):
            if server.server_type == 'pasarguard':
                found = await PasarGuardService().get_user(server, username)
            elif server.server_type == 'xui':
                found = await XuiService().find_client_any(server, username, exhaustive=True)
            else: return 'این نوع پنل برای بررسی پشتیبانی نمی‌شود'
        if not found: return 'در پاسخ پنل یافت نشد؛ این نتیجه مجوز تکرار تبدیل نیست'
        if _status_matches(server.server_type, found, True): return 'فعال'
        if _status_matches(server.server_type, found, False): return 'غیرفعال'
        return 'موجود است؛ فعال‌بودن تأیید نشد'
    except Exception:
        return 'وضعیت نامشخص؛ دریافت پاسخ پنل ناموفق بود'


async def show_detail(callback, ident, archived, page, inspect=False):
    async with SessionLocal() as session:
        item = await session.get(ServiceConversion, ident)
        if not item or item.status not in (*OPEN, ARCHIVED, READY):
            await edit_or_answer(callback, 'این درخواست دیگر در فهرست بررسی نیست.', reply_markup=markup([
                [button('بازگشت به فهرست', f'{PREFIX}:list:{int(archived)}:{page}')]]))
            return
        user = await session.get(User, item.user_id)
        source = await session.get(ClientService, item.source_service_id)
        plan = await session.get(Plan, item.target_plan_id)
        src_server = await session.get(Server, source.server_id) if source else None
        dst_server = await session.get(Server, plan.server_id) if plan and plan.server_id else None
    archived = item.status in (ARCHIVED, READY)
    view = int(archived)
    dest_name = f'cv{item.source_service_id}_{item.target_plan_id}'
    source_name = (source.xui_email or source.client_username) if source else ''
    status = 'آزادشده برای تلاش مجدد' if item.status == READY else 'حذف‌شده از فهرست (نیازمند آزادسازی)' if archived else 'نیازمند بررسی'
    safe = lambda value: escape(str(value or '—'))
    text = (f'🔎 <b>درخواست تغییر تعرفه #{item.id}</b>\n'
        f'وضعیت: {status}\nکاربر: <code>{safe(user.telegram_id if user else item.user_id)}</code>\n'
        f'ثبت: {safe(item.created_at)} UTC\n'
        f'سرویس مبدأ: #{item.source_service_id} · <code>{safe(source_name)}</code>\n'
        f'سرور مبدأ: {safe(src_server.name if src_server else None)}\n'
        f'پلن مقصد: {safe(plan.title if plan else item.target_plan_id)}\n'
        f'سرور مقصد: {safe(dst_server.name if dst_server else None)}\n'
        f'نام احتمالی مقصد: <code>{safe(dest_name)}</code>\n\n'
        f'<b>خطای ثبت‌شده:</b>\n<pre>{safe(redact(item.error or "جزئیات خطا ثبت نشده است")[:1000])}</pre>')
    if inspect:
        src_state, dst_state = await asyncio.gather(panel_state(src_server, source_name), panel_state(dst_server, dest_name))
        text += f'\n\n<b>بررسی تازه پنل:</b>\nمبدأ: {safe(src_state)}\nمقصد: {safe(dst_state)}'
    text += '\n\nبررسی فقط وضعیت را می‌خواند. حذف و آزادسازی، نبود مقصد را بررسی می‌کند و در صورت نیاز فقط مبدأ غیرفعال‌شده را فعال می‌کند؛ سپس تلاش مجدد با محاسبه تازه امکان‌پذیر می‌شود.'
    action = 'restore' if item.status == READY else 'ask'
    rows = [[button('🔄 بررسی مجدد وضعیت پنل‌ها', f'{PREFIX}:check:{ident}:{view}:{page}')],
            [button('↩️ بازگرداندن به فهرست بررسی' if item.status == READY else '🗑 حذف و آزادسازی درخواست', f'{PREFIX}:{action}:{ident}:{view}:{page}')],
            [button('بازگشت به فهرست', f'{PREFIX}:list:{view}:{page}')]]
    await edit_or_answer(callback, text, reply_markup=markup(rows), parse_mode='HTML')


@router.callback_query((F.data == PREFIX) | F.data.startswith(PREFIX + ':'))
async def conversion_requests(callback: CallbackQuery):
    if not await authorized(callback): return
    parts = callback.data.split(':')[2:]
    try:
        if not parts:
            action, archived, page = 'list', False, 0
        elif parts[0] == 'list':
            action, archived, page = 'list', bool(int(parts[1])), max(0, int(parts[2]))
        else:
            action, ident, archived, page = parts[0], int(parts[1]), bool(int(parts[2])), max(0, int(parts[3]))
    except (ValueError, IndexError):
        await callback.answer('دکمه نامعتبر است؛ فهرست را دوباره باز کنید.', show_alert=True)
        return
    await callback.answer('در حال بررسی وضعیت پنل‌ها…' if action in ('check', 'archive') else None)
    if action == 'list':
        await show_list(callback, archived, page)
    elif action in ('detail', 'check'):
        await show_detail(callback, ident, archived, page, inspect=action == 'check')
    elif action == 'ask':
        # No destructive action on the first click or on running/completed claims.
        async with SessionLocal() as session:
            item = await session.get(ServiceConversion, ident)
            valid = item and item.status in (*OPEN, ARCHIVED)
        if not valid:
            await show_list(callback, archived, page)
            return
        await edit_or_answer(callback,
            f'🗑 درخواست #{ident} حذف و برای تلاش مجدد آزاد شود؟\n\nابتدا نبود کانفیگ مقصد بررسی می‌شود. اگر مبدأ به‌علت خطای تبدیل غیرفعال شده باشد، فقط وضعیت آن فعال می‌شود. حجم و انقضا تغییر نمی‌کند. در صورت خطای پنل یا موجودبودن مقصد، درخواست آزاد نمی‌شود.',
            reply_markup=markup([[button('تأیید حذف و آزادسازی', f'{PREFIX}:archive:{ident}:0:{page}')],
                                 [button('انصراف', f'{PREFIX}:detail:{ident}:0:{page}')]]))
    elif action == 'archive':
        try:
            await release_failed(ident, SessionLocal)
        except ValueError as exc:
            await edit_or_answer(callback, '❌ ' + str(exc), reply_markup=markup([
                [button('بازگشت به درخواست', f'{PREFIX}:detail:{ident}:{int(archived)}:{page}')]]))
            return
        await edit_or_answer(callback, '✅ درخواست حذف و آزاد شد؛ کاربر می‌تواند از کانفیگ‌های من یک پیش‌نمایش جدید دریافت کند.',
            reply_markup=markup([[button('بازگشت به فهرست', f'{PREFIX}:list:0:{page}')]]))
    elif action == 'restore':
        # Conditional updates make old/double clicks harmless, including another admin's.
        async with SessionLocal() as session:
            await session.execute(update(ServiceConversion).where(ServiceConversion.id == ident,
                ServiceConversion.status.in_((ARCHIVED, READY)))
                .values(status='needs_review'))
            await session.commit()
        await show_list(callback, archived, page)
