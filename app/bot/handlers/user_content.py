"""Public rules/tutorials and their owner-managed bot editors."""
import io
from aiogram import Router,F
from aiogram.types import CallbackQuery,Message,InlineKeyboardMarkup,InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State,StatesGroup
from app.core.roles import is_owner
from app.bot.utils import ui_callback_message,ui_message,remember_ui_message
from app.bot.keyboards.common import back_button,get_user_button,button_enabled_key,invalidate_button_settings_cache
from app.bot.service_presenter import config_restart_keyboard
from app.database.defaults import get_setting_value,set_setting_value,RULES_TEXT_DEFAULT
from app.services.user_content import load_apps,save_apps,normalize_apps,normalize_background,PLATFORMS,BACKGROUND_KEY,MAX_TUTORIAL_VIDEO_BYTES

router=Router()
class ContentForm(StatesGroup):
    value=State()
    artwork=State()
    video=State()


def markup(rows):return InlineKeyboardMarkup(inline_keyboard=rows)
def button(text,data):return InlineKeyboardButton(text=text,callback_data=data)


@router.callback_query(F.data=='menu:rules')
async def public_rules(cb:CallbackQuery):
    if not (await get_user_button('rules'))[1]:
        await cb.answer('نمایش قوانین غیرفعال است.',show_alert=True);return
    await cb.answer()
    await ui_callback_message(cb,await get_setting_value('rules_text',RULES_TEXT_DEFAULT),reply_markup=config_restart_keyboard())


@router.callback_query(F.data.startswith('tutorial:') | (F.data=='menu:tutorials'))
async def tutorials(cb:CallbackQuery):
    if not (await get_user_button('tutorials'))[1]:
        await cb.answer('آموزش غیرفعال است.',show_alert=True);return
    await cb.answer()
    apps=[r for r in await load_apps() if r.get('enabled',True)]
    if cb.data.startswith('tutorial:app:'):
        item=next((r for r in apps if r['id']==cb.data.split(':')[-1]),None)
        if not item:
            await ui_callback_message(cb,'این آموزش دیگر موجود نیست.',reply_markup=config_restart_keyboard());return
        rows=[]
        if item['download_url']:rows.append([InlineKeyboardButton(text='⬇️ دانلود '+item['name'],url=item['download_url'])])
        rows.append([back_button('menu:tutorials')])
        text=item['text'] or 'متن آموزش این برنامه هنوز ثبت نشده است.'
        chunks=[];chunk='';units=0
        for char in text:
            size=len(char.encode('utf-16-le'))//2
            if units+size>3500:chunks.append(chunk);chunk='';units=0
            chunk+=char;units+=size
        if chunk:chunks.append(chunk)
        for index,chunk in enumerate(chunks):
            sent=await cb.message.answer(chunk,parse_mode=None,reply_markup=config_restart_keyboard(markup(rows)) if index==len(chunks)-1 else None)
            if index==len(chunks)-1 and isinstance(getattr(sent,'message_id',None),int):
                remember_ui_message(sent.chat.id,sent.message_id)
        if item.get('video_file_id'):
            try:
                await cb.message.answer_video(item['video_file_id'],caption='🎬 آموزش '+item['name'],parse_mode=None)
            except Exception:
                await cb.message.answer('⚠️ ارسال ویدیو انجام نشد. دوباره آموزش را انتخاب کنید یا به پشتیبانی اطلاع دهید.',parse_mode=None)
        return
    platform=cb.data.split(':')[-1] if cb.data.startswith('tutorial:os:') else None
    rows=([[button(r['name'],'tutorial:app:'+r['id'])] for r in apps if r['platform']==platform] if platform else
          [[button(label,'tutorial:os:'+key)] for key,label in PLATFORMS.items()])
    rows.append([back_button('menu:tutorials' if platform else 'back:main')])
    await ui_callback_message(cb,'برنامه را انتخاب کنید:' if platform else 'آموزش نصب و اتصال؛ سیستم‌عامل را انتخاب کنید:',reply_markup=markup(rows))


@router.callback_query(F.data=='admin:reseller_visibility')
async def reseller_visibility(cb:CallbackQuery):
    if not is_owner(cb.from_user.id):return
    text,enabled=await get_user_button('reseller_menu')
    await cb.answer()
    await ui_callback_message(cb,'نمایش بخش نمایندگی برای همه کاربران: '+('فعال' if enabled else 'غیرفعال')+'\nبا غیرفعال‌کردن، دکمه درخواست نمایندگی و منوی نمایندگی مخفی می‌شوند.',reply_markup=markup([
        [button('غیرفعال کردن' if enabled else 'فعال کردن','content:reseller:toggle')],[back_button('admin:resellers')]]))


@router.callback_query(F.data=='content:reseller:toggle')
async def reseller_toggle(cb:CallbackQuery):
    if not is_owner(cb.from_user.id):return
    _,enabled=await get_user_button('reseller_menu')
    await set_setting_value(button_enabled_key('reseller_menu'),'0' if enabled else '1');invalidate_button_settings_cache()
    await reseller_visibility(cb)


@router.callback_query(F.data=='content:visibility:rules')
async def rules_visibility(cb:CallbackQuery):
    if not is_owner(cb.from_user.id):return
    _,enabled=await get_user_button('rules')
    await cb.answer()
    await ui_callback_message(cb,'نمایش دکمه قوانین در صفحه اصلی: '+('فعال' if enabled else 'غیرفعال'),reply_markup=markup([
        [button('غیرفعال کردن' if enabled else 'فعال کردن','content:toggle:rules')],[back_button('admin:user_interaction')]]))


@router.callback_query(F.data.in_({'content:toggle:rules','content:toggle:tutorials'}))
async def content_visibility_toggle(cb:CallbackQuery,state:FSMContext):
    if not is_owner(cb.from_user.id):return
    name=cb.data.split(':')[-1]
    if name not in {'rules','tutorials'}:return
    _,enabled=await get_user_button(name)
    await set_setting_value(button_enabled_key(name),'0' if enabled else '1')
    invalidate_button_settings_cache()
    if name=='rules':await rules_visibility(cb)
    else:await admin_tutorials(cb,state)


@router.callback_query(F.data.startswith('content:app_toggle:'))
async def app_visibility_toggle(cb:CallbackQuery,state:FSMContext):
    if not is_owner(cb.from_user.id):return
    ident=cb.data.split(':')[-1];apps=await load_apps()
    item=next((r for r in apps if r['id']==ident),None)
    if not item:await cb.answer('برنامه پیدا نشد.',show_alert=True);return
    item['enabled']=not item.get('enabled',True)
    await save_apps(apps)
    await app_editor(cb,state)


@router.callback_query(F.data=='admin:tutorials')
async def admin_tutorials(cb:CallbackQuery,state:FSMContext):
    if not is_owner(cb.from_user.id):return
    await state.clear();await cb.answer()
    _,enabled=await get_user_button('tutorials')
    rows=[[button('دکمه آموزش: '+('فعال ✅' if enabled else 'غیرفعال ⛔'),'content:toggle:tutorials')],
          [button('➕ افزودن برنامه','content:app:new')]]
    rows += [[button(('✅ ' if r.get('enabled',True) else '⛔ ')+PLATFORMS.get(r['platform'],'')+' | '+r['name'],'content:app:'+r['id'])] for r in await load_apps()]
    rows.append([back_button('admin:user_interaction')])
    await ui_callback_message(cb,'آموزش برنامه‌ها؛ نام، لینک دانلود و متن هر برنامه را دستی وارد کنید.',reply_markup=markup(rows))


@router.callback_query(F.data.startswith('content:app:'))
async def app_editor(cb:CallbackQuery,state:FSMContext):
    if not is_owner(cb.from_user.id):return
    ident=cb.data.split(':')[-1]
    if ident=='new':
        await cb.answer();await ui_callback_message(cb,'سیستم‌عامل برنامه:',reply_markup=markup([[button(v,'content:new:'+k)] for k,v in PLATFORMS.items()]+[[back_button('admin:tutorials')]]));return
    item=next((r for r in await load_apps() if r['id']==ident),None)
    if not item:await cb.answer('برنامه پیدا نشد.',show_alert=True);return
    await state.clear();await cb.answer()
    rows=[[button(label,f'content:field:{ident}:{field}')] for field,label in [('name','نام برنامه'),('download_url','لینک دانلود'),('text','متن آموزش')]]
    rows.insert(0,[button('غیرفعال کردن دکمه برنامه' if item.get('enabled',True) else 'فعال کردن دکمه برنامه','content:app_toggle:'+ident)])
    rows += [[button('🎬 '+('تعویض ویدیو آموزشی' if item.get('video_file_id') else 'افزودن ویدیو آموزشی'),'content:video:'+ident)]]
    rows += [[button('🗑 حذف برنامه','content:delete:'+ident)],[back_button('admin:tutorials')]]
    await ui_callback_message(cb,f"{item['name']} — {PLATFORMS[item['platform']]}\nلینک: {item['download_url'] or 'خالی'}\nمتن: {(item['text'] or 'خالی')[:600]}",parse_mode=None,reply_markup=markup(rows))


@router.callback_query(F.data.startswith('content:new:') | F.data.startswith('content:field:'))
async def edit_field(cb:CallbackQuery,state:FSMContext):
    if not is_owner(cb.from_user.id):return
    parts=cb.data.split(':')
    await state.set_state(ContentForm.value)
    await state.update_data(ident=parts[2] if parts[1]=='field' else None,field=parts[3] if parts[1]=='field' else 'name',platform=parts[2] if parts[1]=='new' else None)
    await cb.answer();await ui_callback_message(cb,'مقدار جدید را ارسال کنید. برای خالی کردن لینک یا متن، فقط - بفرستید.',reply_markup=markup([[back_button('admin:tutorials')]]))


@router.message(ContentForm.value, lambda message: not (message.text or '').startswith('/'))
async def save_field(message:Message,state:FSMContext):
    if not is_owner(message.from_user.id):return
    data=await state.get_data();apps=await load_apps();ident=data['ident']
    item=next((r for r in apps if r['id']==ident),None) if ident else dict(id='',platform=data['platform'],name='',download_url='',text='')
    if item is None:await state.clear();await ui_message(message,'برنامه حذف شده است.');return
    value=message.text
    if value is None:await ui_message(message,'مقدار را به صورت متن بفرستید.');return
    item[data['field']]='' if value.strip()=='-' else value
    if not ident:apps.append(item)
    try:await save_apps(apps)
    except ValueError as exc:await ui_message(message,str(exc));return
    await state.clear();await ui_message(message,'✅ ذخیره شد.',reply_markup=markup([[back_button('admin:tutorials')]]))


@router.callback_query(F.data.startswith('content:video:'))
async def edit_video(cb:CallbackQuery,state:FSMContext):
    if not is_owner(cb.from_user.id):return
    ident=cb.data.split(':')[-1]
    if not any(r['id']==ident for r in await load_apps()):
        await cb.answer('برنامه پیدا نشد.',show_alert=True);return
    await state.set_state(ContentForm.video);await state.update_data(ident=ident)
    await cb.answer()
    await ui_callback_message(cb,'ویدیو آموزشی را به صورت ویدیو MP4 بفرستید (حداکثر ۵۰ مگابایت). برای حذف ویدیو، فقط - بفرستید.',reply_markup=markup([[back_button('content:app:'+ident)]]))


@router.message(ContentForm.video, lambda message: not (message.text or '').startswith('/'))
async def save_video(message:Message,state:FSMContext):
    if not is_owner(message.from_user.id):return
    data=await state.get_data();apps=await load_apps()
    item=next((r for r in apps if r['id']==data.get('ident')),None)
    if item is None:
        await state.clear();await ui_message(message,'برنامه حذف شده است.');return
    if (message.text or '').strip()=='-':item['video_file_id']=''
    else:
        video=message.video
        if not video or int(video.file_size or 0)>MAX_TUTORIAL_VIDEO_BYTES:
            await ui_message(message,'ویدیو MP4 با حجم حداکثر ۵۰ مگابایت ارسال کنید (به صورت ویدیو، نه فایل).');return
        item['video_file_id']=video.file_id
    await save_apps(apps);await state.clear()
    await ui_message(message,'✅ ویدیو آموزشی ذخیره شد.',reply_markup=markup([[back_button('content:app:'+item['id'])]]))


@router.callback_query(F.data.startswith('content:delete:'))
async def delete_app(cb:CallbackQuery,state:FSMContext):
    if not is_owner(cb.from_user.id):return
    await save_apps([r for r in await load_apps() if r['id']!=cb.data.split(':')[-1]])
    await admin_tutorials(cb,state)


@router.callback_query(F.data=='admin:qr_background')
async def artwork_menu(cb:CallbackQuery,state:FSMContext):
    if not is_owner(cb.from_user.id):return
    await state.set_state(ContentForm.artwork);await cb.answer()
    await ui_callback_message(cb,'پس‌زمینه بارکد را به صورت عکس یا فایل PNG/JPG بفرستید (حداکثر ۵ مگابایت). QR در مرکز تصویر قرار می‌گیرد. برای بازگشت به پس‌زمینه پیش‌فرض، - بفرستید.',reply_markup=markup([[back_button('admin:bot_settings')]]))


@router.message(ContentForm.artwork, lambda message: not (message.text or '').startswith('/'))
async def artwork_save(message:Message,state:FSMContext):
    if not is_owner(message.from_user.id):return
    if (message.text or '').strip()=='-':value=''
    else:
        media=message.document or (message.photo[-1] if message.photo else None)
        if not media or int(media.file_size or 0)>5*1024**2:await ui_message(message,'تصویر معتبر با حجم حداکثر ۵ مگابایت ارسال کنید.');return
        stream=io.BytesIO();await message.bot.download(media,destination=stream)
        try:value=normalize_background(stream.getvalue())
        except Exception:await ui_message(message,'تصویر معتبر PNG/JPG و با ابعاد مناسب ارسال کنید.');return
    await set_setting_value(BACKGROUND_KEY,value);await state.clear()
    await ui_message(message,'✅ پس‌زمینه بارکد ذخیره شد.',reply_markup=markup([[back_button('admin:bot_settings')]]))
