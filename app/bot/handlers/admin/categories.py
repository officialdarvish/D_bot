from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy import select, delete
from app.core.config import settings
from app.core.roles import is_owner
from app.database.session import SessionLocal
from app.database.models import ServerCategory, Server, Plan, Order
from app.bot.states.admin_states import AddCategory, EditCategory
from app.bot.keyboards.common import CB_CATEGORIES, back_button
from app.bot.utils import edit_or_answer, ui_message, ui_callback_message

router = Router()
def admin(uid): return is_owner(uid)

async def categories_kb():
    async with SessionLocal() as session:
        rows = (await session.execute(select(ServerCategory, Server).join(Server, Server.id == ServerCategory.server_id, isouter=True).order_by(ServerCategory.id.desc()))).all()
    keyboard = [[InlineKeyboardButton(text='اسم دسته', callback_data='noop'), InlineKeyboardButton(text='حذف', callback_data='noop')]]
    for c, s in rows:
        keyboard.append([InlineKeyboardButton(text=f'✅ {c.name}' + (f' / {s.name}' if s else ''), callback_data=f'cat:edit:{c.id}'), InlineKeyboardButton(text='❌', callback_data=f'cat:delete:{c.id}')])
    keyboard.append([InlineKeyboardButton(text='افزودن دسته جدید ➕', callback_data='cat:add')])
    keyboard.append([back_button('back:admin')])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

@router.callback_query(F.data == CB_CATEGORIES)
async def categories_menu(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    await edit_or_answer(callback, '✅ مدیریت دسته‌ها:', reply_markup=await categories_kb()); await callback.answer()

@router.callback_query(F.data == 'cat:add')
async def add_category(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    async with SessionLocal() as session:
        all_servers=(await session.execute(select(Server).where(Server.is_active == True))).scalars().all()
        servers=[s for s in all_servers if (s.meta or {}).get('scope') != 'reseller']
    if not servers:
        await ui_callback_message(callback, 'اول باید یک سرور ثبت کنید.', reply_markup=await categories_kb()); await callback.answer(); return
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=s.name, callback_data=f'cat:add_server:{s.id}')] for s in servers] + [[back_button('admin:categories')]])
    await state.clear(); await state.set_state(AddCategory.server_id)
    await ui_callback_message(callback, 'این دسته زیرمجموعه کدام سرور باشد؟', reply_markup=kb); await callback.answer()

@router.callback_query(F.data.startswith('cat:add_server:'))
async def cat_server(callback: CallbackQuery, state: FSMContext):
    await state.update_data(server_id=int(callback.data.split(':')[-1]))
    await state.set_state(AddCategory.name)
    await ui_callback_message(callback, 'نام دسته جدید را وارد کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:categories')]])); await callback.answer()

@router.message(AddCategory.name)
async def save_category(message: Message, state: FSMContext):
    data=await state.get_data()
    async with SessionLocal() as session:
        
        exists=(await session.execute(select(ServerCategory).where(ServerCategory.name == message.text.strip(), ServerCategory.server_id == int(data['server_id'])))).scalar_one_or_none()
        if exists:
            await ui_message(message, '⚠️ این دسته قبلاً برای همین سرور ثبت شده است.', reply_markup=await categories_kb()); await state.clear(); return
        session.add(ServerCategory(name=message.text.strip(), server_id=int(data['server_id']))); await session.commit()
    await state.clear(); await ui_message(message, '✅ دسته ذخیره شد.', reply_markup=await categories_kb())

@router.callback_query(F.data.startswith('cat:delete:'))
async def delete_category(callback: CallbackQuery):
    if not admin(callback.from_user.id): return
    cid=int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        c=await session.get(ServerCategory,cid)
        if c:
            plan_ids=[p.id for p in (await session.execute(select(Plan).where(Plan.category_id == cid))).scalars().all()]
            if plan_ids:
                await session.execute(delete(Order).where(Order.plan_id.in_(plan_ids)))
            await session.execute(delete(Plan).where(Plan.category_id == cid))
            await session.delete(c); await session.commit()
    await edit_or_answer(callback, '✅ دسته و پلن‌های مربوط به آن حذف شد.', reply_markup=await categories_kb()); await callback.answer()

@router.callback_query(F.data.startswith('cat:edit:'))
async def edit_category(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id): return
    await state.clear(); await state.update_data(category_id=int(callback.data.split(':')[-1]))
    await state.set_state(EditCategory.name)
    await ui_callback_message(callback, 'نام جدید دسته را وارد کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button('admin:categories')]])); await callback.answer()

@router.message(EditCategory.name)
async def save_edit_category(message: Message, state: FSMContext):
    data=await state.get_data()
    async with SessionLocal() as session:
        c=await session.get(ServerCategory,int(data['category_id']))
        if c: c.name=message.text.strip(); await session.commit()
    await state.clear(); await ui_message(message, '✅ دسته ویرایش شد.', reply_markup=await categories_kb())
