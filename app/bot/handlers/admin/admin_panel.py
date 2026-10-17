from aiogram import Router, F
from aiogram.types import CallbackQuery
from app.core.config import settings
from app.bot.keyboards.common import (
    CB_RECONCILE_EXPIRED, admin_panel_inline, bot_settings_inline, sales_section_inline, user_interaction_inline,
)
from app.bot.utils import edit_or_answer
from app.jobs.service_cleanup import reconcile_expired_service_list

router = Router()

def admin(user_id: int) -> bool:
    return user_id in settings.admin_ids

@router.callback_query(F.data == 'admin:sales_section')
async def sales_section(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    await edit_or_answer(callback, '🛒 بخش فروش', reply_markup=sales_section_inline())
    await callback.answer()

@router.callback_query(F.data == 'admin:user_interaction')
async def user_interaction(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    await edit_or_answer(callback, '👥 تعامل با کاربر', reply_markup=user_interaction_inline())
    await callback.answer()

@router.callback_query(F.data == 'admin:bot_settings')
async def bot_settings(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    await edit_or_answer(callback, '⚙️ تنظیمات ربات', reply_markup=bot_settings_inline())
    await callback.answer()


@router.callback_query(F.data == CB_RECONCILE_EXPIRED)
async def reconcile_expired(callback: CallbackQuery):
    if not admin(callback.from_user.id):
        return
    # Acknowledge immediately so Telegram never reports an old callback while
    # the panel/database reconciliation is running.
    await callback.answer('بررسی لیست منقضی‌ها شروع شد.')
    await edit_or_answer(
        callback,
        '⏳ در حال بررسی دیتابیس و پنل و بازسازی لیست آماده حذف هستیم...\nلطفاً چند لحظه صبر کنید.',
        reply_markup=None,
    )
    try:
        stats = await reconcile_expired_service_list()
    except Exception:
        await edit_or_answer(
            callback,
            '❌ بررسی لیست منقضی‌ها کامل نشد. جزئیات فنی در لاگ سرور ثبت شد.',
            reply_markup=admin_panel_inline(),
        )
        return

    text = (
        '✅ بررسی لیست منقضی‌ها انجام شد.\n'
        '━━━━━━━━━━━━━━━━\n'
        f"🔍 سرویس‌های غیرفعال بررسی‌شده: {stats.get('scanned', 0)}\n"
        f"🟢 سرویس‌های فعال‌شده مجدد: {stats.get('reactivated', 0)}\n"
        f"🔴 سرویس‌های همچنان منقضی/غیرفعال: {stats.get('still_inactive', 0)}\n"
        f"⚠️ سرویس‌های پیدا نشده روی پنل: {stats.get('missing_on_panel', 0)}\n"
        f"🗑 اضافه‌شده به لیست آماده حذف: {stats.get('queued_now', 0)}\n"
        f"🧹 موارد قدیمی/اشتباه حذف‌شده از لیست: {stats.get('removed_stale', 0)}\n"
        f"📋 کل موارد آماده/در انتظار حذف: {stats.get('ready_total', 0)}\n"
        f"⚙️ خطاهای ارتباطی قابل تکرار: {stats.get('errors', 0)}\n"
        '━━━━━━━━━━━━━━━━\n'
        'لیست آماده حذف بر اساس وضعیت فعلی دیتابیس و پنل اصلاح شد.'
    )
    await edit_or_answer(callback, text, reply_markup=admin_panel_inline())
