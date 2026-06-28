from aiogram import Router, F
from aiogram.types import CallbackQuery
from app.core.config import settings
from app.bot.keyboards.common import sales_section_inline, user_interaction_inline, bot_settings_inline
from app.bot.utils import edit_or_answer

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
