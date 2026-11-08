"""Release failed conversion claims only after reconciling both panels."""
import asyncio
from sqlalchemy import select, update
from app.database.models import ClientService, Plan, Server, ServiceConversion, MiniAppOperation
from app.services.conversion_provider import _status_matches, set_enabled
from app.services.pasarguard_service import PasarGuardService
from app.services.xui_service import XuiService

REVIEW = ('needs_review', 'failed', 'error', 'review_archived')
READY = 'retry_ready'


async def destination_absent(server, username):
    # Repair lookups may swallow list failures. Never use a best-effort None as
    # evidence that an ambiguous create did not commit.
    if server.server_type == 'pasarguard':
        try:
            await PasarGuardService()._request(server, 'GET', f'/api/user/by-username/{username}')
        except RuntimeError as exc:
            if '(404)' in str(exc): return True
            raise
        return False
    if server.server_type == 'xui':
        return not await XuiService().client_username_exists(server, username)
    raise ValueError('نوع پنل مقصد برای آزادسازی درخواست پشتیبانی نمی‌شود.')


async def source_state(server, username):
    if server.server_type == 'pasarguard':
        return await PasarGuardService().get_user(server, username)
    if server.server_type == 'xui':
        return await XuiService().find_client_any(server, username, exhaustive=True)
    raise ValueError('نوع پنل مبدأ برای آزادسازی درخواست پشتیبانی نمی‌شود.')


async def release_failed(ident, sessions):
    """Transactional claim lock survives concurrent admins and rolls back on crash.

    No quota/expiry changes and no target deletion. A disabled source is restored
    only after a strict absence check. The unique row is reused by the next try.
    """
    try:
        async with asyncio.timeout(45):
            async with sessions() as session:
                async with session.begin():
                    locked = await session.execute(update(ServiceConversion).where(
                        ServiceConversion.id == ident, ServiceConversion.status.in_(REVIEW)
                    ).values(status='retry_check'))
                    if locked.rowcount != 1:
                        item = await session.get(ServiceConversion, ident)
                        if item and item.status == READY: return
                        raise ValueError('وضعیت درخواست تغییر کرده است؛ فهرست را بروزرسانی کنید.')
                    item = await session.get(ServiceConversion, ident)
                    source = await session.get(ClientService, item.source_service_id)
                    plan = await session.get(Plan, item.target_plan_id)
                    if item.target_service_id or not source or not source.is_active or source.disabled_reason == 'converted':
                        raise ValueError('ثبت یا تکمیل مقصد محتمل است؛ درخواست آزاد نشد. ابتدا کانفیگ‌های مبدأ و مقصد را بررسی کنید.')
                    src = await session.get(Server, source.server_id)
                    dst = await session.get(Server, plan.server_id) if plan and plan.server_id else None
                    name = source.xui_email or source.client_username
                    if not src or not dst or not name:
                        raise ValueError('اطلاعات سرور مبدأ یا مقصد ناقص است؛ درخواست آزاد نشد.')
                    target_name = f'cv{source.id}_{item.target_plan_id}'
                    if not await destination_absent(dst, target_name):
                        raise ValueError('کانفیگ مقصد در پنل وجود دارد؛ برای جلوگیری از اعتبار تکراری درخواست آزاد نشد. ابتدا مقصد را بررسی کنید.')
                    found = await source_state(src, name)
                    if not _status_matches(src.server_type, found, True):
                        if not _status_matches(src.server_type, found, False):
                            raise ValueError('وضعیت مبدأ فعال یا غیرفعال تأیید نشده است؛ درخواست آزاد نشد.')
                        await set_enabled(src, name, True)
                    # Check again after restoring the source. Do not unlock if
                    # a previously delayed target write has become visible.
                    if not await destination_absent(dst, target_name):
                        raise ValueError('مقصد در بررسی دوباره موجود است؛ درخواست برای رسیدگی مدیر نگه داشته شد.')
                    item.status = READY
                    # Old drafts/queued confirmations must not consume a newly
                    # released claim. A new preview/key is always required.
                    ops = (await session.scalars(select(MiniAppOperation).where(
                        MiniAppOperation.user_id == item.user_id,
                        MiniAppOperation.kind == 'public_convert',
                        MiniAppOperation.status.in_(('draft', 'queued'))))).all()
                    for op in ops:
                        if (op.payload or {}).get('service_id') == source.id:
                            op.status = 'failed'
                            op.result = {'retryable': True, 'message': 'درخواست قبلی آزاد شد؛ یک پیش‌نمایش جدید دریافت کنید.'}
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('بررسی قطعی پنل‌ها کامل نشد؛ درخواست آزاد نشد. اتصال پنل‌ها را بررسی و دوباره تلاش کنید.') from exc


def claim_message(item):
    if item.status == 'completed':
        return f'تبدیل درخواست #{item.id} قبلاً تکمیل شده است؛ کانفیگ جدید را در کانفیگ‌های من ببینید.'
    if item.status in ('reserved', 'retry_check'):
        return f'درخواست #{item.id} در حال انجام یا بررسی است؛ کمی بعد دوباره بررسی کنید.'
    return f'درخواست خطادار #{item.id} هنوز آزاد نشده است؛ مدیر باید از «بررسی مجدد درخواست‌های تغییر تعرفه» دکمه حذف و آزادسازی را بزند.'


async def ensure_available(sid, sessions):
    async with sessions() as session:
        item = await session.scalar(select(ServiceConversion).where(ServiceConversion.source_service_id == sid))
    # Archive meant delete in the previous UI. Reconcile those legacy entries
    # on the user's next explicit attempt, rather than preserving a hidden lock.
    if item and item.status == 'review_archived':
        await release_failed(item.id, sessions)
        return
    if item and item.status != READY:
        raise ValueError(claim_message(item))
