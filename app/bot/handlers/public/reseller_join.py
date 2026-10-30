"""Telegram front end for the shared reseller checkout (no manual quota entry)."""
import uuid
from aiogram import Router,F
from aiogram.types import CallbackQuery,Message,InlineKeyboardMarkup,InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
from app.bot.states.public_states import ResellerJoin
from app.bot.keyboards.common import back_button
from app.bot.utils import edit_or_answer,ui_message
from app.database.models import User,MiniAppOperation,Server
from app.database.session import SessionLocal
from app.services import reseller_onboarding as flow
from app.core.config import settings
from app.services.pasarguard_panel_sales import validate_panel_username,validate_panel_password
from app.core.security import encrypt_text,decrypt_text
router=Router()

def kb(rows):return InlineKeyboardMarkup(inline_keyboard=rows+[[back_button('home:main')]] )
def button(text,data):return [InlineKeyboardButton(text=text,callback_data=data)]
async def buyer(s,actor):
    user=await s.scalar(select(User).where(User.telegram_id==actor.id))
    if not user:raise ValueError('ابتدا ربات را استارت کنید.')
    return user

async def shop(callback,state):
    await state.clear()
    try:
        async with SessionLocal() as s:
            user=await buyer(s,callback.from_user);cat=await flow.catalog(s,user)
            pending=await s.scalar(select(MiniAppOperation).where(MiniAppOperation.user_id==user.id,MiniAppOperation.kind==flow.KIND,MiniAppOperation.status.in_(list(flow.OPEN))).order_by(MiniAppOperation.id.desc()).limit(1))
        if pending:
            rows=[button('ادامه درخواست',f'rjoin:continue:{pending.id}')]
            if pending.status=='waiting_receipt':rows.append(button('لغو فاکتور',f'rjoin:cancel:{pending.id}'))
            await edit_or_answer(callback,f'درخواست نمایندگی #{pending.id}\nوضعیت: {pending.status}',reply_markup=kb(rows))
        else:
            await edit_or_answer(callback,'نوع نمایندگی را انتخاب کنید. هر نماینده فقط یک مدل تعرفه دارد.',reply_markup=kb([button(flow.LABELS[k],f'rjoin:kind:{k}') for k in cat['options']]))
    except ValueError as exc:await callback.answer(str(exc),show_alert=True);return
    await callback.answer()

@router.callback_query(F.data=='rjoin:shop')
async def home(callback:CallbackQuery,state:FSMContext):await shop(callback,state)

@router.callback_query(F.data.startswith('rjoin:kind:'))
async def kind(callback:CallbackQuery,state:FSMContext):
    kind=callback.data.split(':')[-1]
    async with SessionLocal() as s:
        user=await buyer(s,callback.from_user)
        try:cat=await flow.catalog(s,user)
        except ValueError as exc:await callback.answer(str(exc),show_alert=True);return
    if kind not in cat['options']:await callback.answer('این گزینه فعال نیست.',show_alert=True);return
    await state.clear();await state.update_data(join_kind=kind,join_mode=kind if kind!='panel' else '',join_key=str(uuid.uuid4()))
    if kind=='panel':
        await state.update_data(join_server_id=cat['panel_server_id'])
        await state.set_state(ResellerJoin.username)
        await edit_or_answer(callback,'نام کاربری پنل: ۴ تا ۳۲ نویسه، شروع با حرف انگلیسی، سپس حرف، عدد یا زیرخط.',reply_markup=kb([]))
    else:
        await edit_or_answer(callback,'سرور نمایندگی را انتخاب کنید:',reply_markup=kb([button(v['name'],f"rjoin:server:{v['id']}") for v in cat['servers'] if kind in v['modes']]))
    await callback.answer()

@router.message(ResellerJoin.username)
async def username(message:Message,state:FSMContext):
    name=(message.text or '').strip()
    if not validate_panel_username(name):await ui_message(message,'نام معتبر وارد کنید؛ ۴ تا ۳۲ نویسه انگلیسی، شروع با حرف.');return
    try:
        data=await state.get_data()
        async with SessionLocal() as s:await flow.check_panel_username(s,name,data.get('join_server_id'))
    except ValueError as exc:await ui_message(message,str(exc));return
    await state.update_data(join_username=name);await state.set_state(ResellerJoin.password)
    await ui_message(message,'رمز پنل: حداقل ۱۲ نویسه، حداقل دو حرف کوچک، دو حرف بزرگ، دو عدد و یک نماد؛ بدون فاصله.')

@router.message(ResellerJoin.password)
async def password(message:Message,state:FSMContext):
    raw=message.text or ''
    try:await message.delete()
    except Exception:pass
    if not validate_panel_password(raw):await ui_message(message,'رمز مطابق استاندارد نیست؛ دوباره وارد کنید.');return
    await state.update_data(join_password_encrypted=encrypt_text(raw));await state.set_state(None)
    async with SessionLocal() as s:cat=await flow.catalog(s,await buyer(s,message.from_user))
    await ui_message(message,'مدل محاسبه هزینه پنل را انتخاب کنید:',reply_markup=kb([button('حجمی' if m=='volume' else 'پرداخت به‌ازای مصرف',f'rjoin:mode:{m}') for m in cat['panel_modes']]))

@router.callback_query(F.data.startswith('rjoin:mode:'))
async def mode(callback:CallbackQuery,state:FSMContext):
    data=await state.get_data()
    if data.get('join_kind')!='panel':await callback.answer('فرآیند را دوباره آغاز کنید.',show_alert=True);return
    await state.update_data(join_mode=callback.data.split(':')[-1]);await choose_package(callback,state)

@router.callback_query(F.data.startswith('rjoin:server:'))
async def server(callback:CallbackQuery,state:FSMContext):
    await state.update_data(join_server_id=int(callback.data.split(':')[-1]));await choose_package(callback,state)

async def choose_package(callback,state):
    data=await state.get_data()
    if data.get('join_mode')=='volume':
        async with SessionLocal() as s:cat=await flow.catalog(s,await buyer(s,callback.from_user))
        rows=[button(f"{p['title']} · {p['volume_gb']} GB · {p['price']}",f"rjoin:package:{p['id']}") for p in cat['packages'] if p['server_id']==data.get('join_server_id')]
        await edit_or_answer(callback,'بسته حجم نمایندگی را انتخاب کنید:',reply_markup=kb(rows));await callback.answer()
    else:await preview(callback,state)

@router.callback_query(F.data.startswith('rjoin:package:'))
async def package(callback:CallbackQuery,state:FSMContext):
    await state.update_data(join_package_id=int(callback.data.split(':')[-1]));await preview(callback,state)

def request(data):
    return dict(kind=data.get('join_kind'),mode=data.get('join_mode'),server_id=data.get('join_server_id',0),package_id=data.get('join_package_id',0),username=data.get('join_username',''),password=decrypt_text(data['join_password_encrypted']) if data.get('join_password_encrypted') else '')

async def preview(callback,state):
    try:
        async with SessionLocal() as s:q=await flow.quote(s,await buyer(s,callback.from_user),request(await state.get_data()))
        await state.update_data(join_amount=q['amount'])
        text=f"🧾 {q['title']}\nسرور: {q['server_name']}\nتعرفه: {q['mode']}\nهزینه پنل: {q['setup_amount']:,} تومان\nشارژ اولیه: {q['initial_credit']:,} تومان\nبسته: {q.get('package_title') or '-'}\nهر گیگ: {q['rate']:,} تومان\nحداقل ترافیک اولیه: {q.get('min_initial_gb') or '-'} GB\nمبلغ نهایی: {q['amount']:,} تومان"
        await edit_or_answer(callback,text,reply_markup=kb([button('ادامه و پرداخت','rjoin:pay')]))
    except ValueError as exc:await callback.answer(str(exc),show_alert=True);return
    await callback.answer()

@router.callback_query(F.data=='rjoin:pay')
async def pay(callback:CallbackQuery,state:FSMContext):
    data=await state.get_data()
    try:
        async with SessionLocal() as s:
            op=await flow.checkout(s,await buyer(s,callback.from_user),data.get('join_key',''),request(data),data.get('join_amount'))
            if op.payload['amount']==0:await flow.submit(s,op,'FREE')
            await s.commit()
            if op.payload['amount']==0:await flow.notify(callback.bot,s,op)
            oid=op.id
        await state.clear();await state.update_data(join_order_id=oid);await receipt_screen(callback,state,oid)
    except ValueError as exc:await callback.answer(str(exc),show_alert=True)

async def receipt_screen(callback,state,oid):
    async with SessionLocal() as s:
        op=await s.get(MiniAppOperation,oid);user=await buyer(s,callback.from_user)
        if not op or op.user_id!=user.id or op.kind!=flow.KIND:await callback.answer('درخواست پیدا نشد.',show_alert=True);return
        q=op.payload
        if op.status=='waiting_receipt':
            await state.update_data(join_order_id=oid);await state.set_state(ResellerJoin.receipt)
            await edit_or_answer(callback,f"💳 مبلغ: {q['amount']:,} تومان\nشماره کارت: {q['card']['number']}\nصاحب حساب: {q['card']['owner']}\nعکس رسید را ارسال کنید.",reply_markup=kb([button('لغو فاکتور',f'rjoin:cancel:{oid}')]))
        else:await edit_or_answer(callback,f"درخواست #{oid}\n{op.result.get('message') or op.status}",reply_markup=kb([]))
    await callback.answer()

@router.callback_query(F.data.startswith('rjoin:continue:'))
async def resume(callback:CallbackQuery,state:FSMContext):await receipt_screen(callback,state,int(callback.data.split(':')[-1]))

@router.callback_query(F.data.startswith('rjoin:cancel:'))
async def cancel(callback:CallbackQuery,state:FSMContext):
    async with SessionLocal() as s:
        op=await s.get(MiniAppOperation,int(callback.data.split(':')[-1]),with_for_update=True);user=await buyer(s,callback.from_user)
        if op and op.user_id==user.id and op.kind==flow.KIND and op.status=='waiting_receipt':op.status='cancelled';await s.commit()
    await shop(callback,state)

@router.message(ResellerJoin.receipt)
async def receipt(message:Message,state:FSMContext):
    file_id=message.photo[-1].file_id if message.photo else message.document.file_id if message.document else None
    if not file_id:await ui_message(message,'عکس یا فایل رسید را ارسال کنید.');return
    data=await state.get_data()
    async with SessionLocal() as s:
        user=await buyer(s,message.from_user);op=await s.get(MiniAppOperation,data.get('join_order_id'),with_for_update=True)
        if not op or op.user_id!=user.id or op.kind!=flow.KIND:await ui_message(message,'درخواست معتبر نیست.');return
        try:changed=await flow.submit(s,op,file_id)
        except ValueError as exc:await ui_message(message,str(exc));return
        await s.commit()
        if changed:await flow.notify(message.bot,s,op)
    await state.clear();await ui_message(message,'رسید نمایندگی ثبت شد و منتظر تأیید مدیر است.',reply_markup=kb([]))


def admin(actor):return actor in set(settings.owner_ids+settings.admin_ids)
@router.callback_query(F.data.startswith('rjoin:review:'))
async def review(callback:CallbackQuery):
    if not admin(callback.from_user.id):await callback.answer('دسترسی ندارید.',show_alert=True);return
    async with SessionLocal() as s:
        op=await s.get(MiniAppOperation,int(callback.data.split(':')[-1]))
        if not op or op.kind!=flow.KIND or op.status!='pending':await callback.answer('درخواست در انتظار بررسی نیست.',show_alert=True);return
        q=op.payload;server=await s.get(Server,q['server_id'])
    await edit_or_answer(callback,'سرور فاکتور پرداخت‌شده را تأیید کنید:',reply_markup=kb([button(server.name if server else 'سرور حذف‌شده',f"rjoin:tariff:{op.id}:{q['server_id']}")]))
    await callback.answer()

@router.callback_query(F.data.startswith('rjoin:tariff:'))
async def tariff(callback:CallbackQuery):
    if not admin(callback.from_user.id):return
    _,_,oid,sid=callback.data.split(':')
    async with SessionLocal() as s:op=await s.get(MiniAppOperation,int(oid))
    if not op or op.kind!=flow.KIND or op.status!='pending':await callback.answer('درخواست معتبر نیست.',show_alert=True);return
    mode=op.payload['mode']
    await edit_or_answer(callback,'مدل تعرفه فاکتور را تأیید کنید؛ حجم و اعتبار از خرید محاسبه می‌شود.',reply_markup=kb([button('تأیید حجمی' if mode=='volume' else 'تأیید پرداخت به‌ازای مصرف',f'rjoin:approve:{oid}:{sid}:{mode}')]))
    await callback.answer()

@router.callback_query(F.data.startswith('rjoin:approve:'))
async def approve(callback:CallbackQuery):
    if not admin(callback.from_user.id):return
    _,_,oid,sid,mode=callback.data.split(':')
    async with SessionLocal() as s:
        op=await s.get(MiniAppOperation,int(oid),with_for_update=True)
        if not op or op.kind!=flow.KIND:await callback.answer('درخواست پیدا نشد.',show_alert=True);return
        if op.payload['kind']=='panel' and callback.from_user.id not in settings.owner_ids:await callback.answer('تأیید پنل توسط مالک ربات انجام شود.',show_alert=True);return
        try:panel=await flow.approve(s,op,callback.from_user.id,int(sid),mode)
        except ValueError as exc:await callback.answer(str(exc),show_alert=True);return
        user=await s.get(User,op.user_id);await s.commit()
    if panel:
        from app.bot.handlers.admin.panel_reseller_sale import panel_sale_approve
        await panel_sale_approve(callback.model_copy(update={'data':f'pgadmin:approve:{panel.id}'}))
    else:
        from app.services.reseller_billing import reconcile_suspensions
        await reconcile_suspensions(op.result.get('reseller_id'))
        try:await callback.bot.send_message(user.telegram_id,'✅ رسید تأیید شد و نمایندگی شما فعال است. از بخش نمایندگی در خانه ربات یا مینی‌اپ استفاده کنید.',reply_markup=kb([button('نمایندگی','menu:reseller')]))
        except Exception:pass
        await edit_or_answer(callback,'نمایندگی فعال شد.',reply_markup=kb([]));await callback.answer()

@router.callback_query(F.data.startswith('rjoin:reject:'))
async def reject(callback:CallbackQuery):
    if not admin(callback.from_user.id):return
    async with SessionLocal() as s:
        op=await s.get(MiniAppOperation,int(callback.data.split(':')[-1]),with_for_update=True)
        if not op or op.kind!=flow.KIND or op.status!='pending':await callback.answer('درخواست بررسی شده است.',show_alert=True);return
        op.status='rejected';op.result={**op.result,'message':'رسید نمایندگی توسط مدیر رد شد. برای پیگیری با پشتیبانی تماس بگیرید.'}
        user=await s.get(User,op.user_id);await s.commit()
    try:await callback.bot.send_message(user.telegram_id,op.result['message'])
    except Exception:pass
    await edit_or_answer(callback,'رسید رد شد.',reply_markup=kb([]));await callback.answer()

@router.callback_query(F.data=='rjoin:requests')
async def pending_requests(callback:CallbackQuery):
    if not admin(callback.from_user.id):return
    async with SessionLocal() as s:
        rows=(await s.execute(select(MiniAppOperation,User).join(User,User.id==MiniAppOperation.user_id).where(MiniAppOperation.kind==flow.KIND,MiniAppOperation.status.in_(['pending','processing','review'])).order_by(MiniAppOperation.id.desc()).limit(50))).all()
    buttons=[button(f"#{op.id} · {user.telegram_id} · {op.payload['title']} · {op.status}",f'rjoin:review:{op.id}') for op,user in rows]
    await edit_or_answer(callback,'درخواست‌های خرید نمایندگی' if rows else 'درخواست بررسی‌نشده‌ای وجود ندارد.',reply_markup=kb(buttons));await callback.answer()
