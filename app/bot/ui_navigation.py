"""Shared Telegram UI lifecycle: one live page, revocable buttons, final artifacts.

Business handlers retain their authorization/financial checks. This transport
layer only renders messages and restores earlier *input/menu* snapshots.
"""
from __future__ import annotations
import asyncio
import copy
import json
import logging
import re
import secrets
import time
import weakref
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import wraps
from html import escape

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError, TelegramServerError, TelegramRetryAfter
from aiogram.types import CallbackQuery, Message, Chat, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.methods import SendMessage, EditMessageText, EditMessageCaption, EditMessageReplyMarkup, EditMessageMedia
from aiogram.types import InputMediaPhoto, InputMediaDocument, InputMediaVideo, InputMediaAnimation, InputMediaAudio

RESTART = 'restart:start'
BACK = 'navigation:back'
TTL = 86400
MAX_HISTORY = 20
_context = ContextVar('dbot_ui_context', default=None)
_role = ContextVar('dbot_ui_role', default=None)
_bypass = ContextVar('dbot_ui_internal_transport', default=False)
_receipt_flow = ContextVar('dbot_receipt_flow', default=False)
RECEIPT_ACTIONS=('order:approve:','order:reject:','wallet_topup:approve:','wallet_topup:reject:','resadmin:req_approve:','resadmin:req_reject:','pgadmin:approve:','pgadmin:reject:','paygwallet:review:')
logger = logging.getLogger(__name__)
CALLBACK_ACK_TIMEOUT = 3
_redis = None
_memory = {}
_locks = weakref.WeakValueDictionary()


def configure_ui_storage(redis):
    global _redis
    _redis = redis


def current_ui():
    ctx = _context.get()
    return ctx if ctx and not ctx.closed else None


@contextmanager
def output_role(role):
    token = _role.set(role)
    try: yield
    finally: _role.reset(token)


def navigation_page(fn):
    @wraps(fn)
    async def wrapped(*args, **kwargs):
        with output_role('page'):
            return await fn(*args, **kwargs)
    return wrapped


def receipt_message(fn):
    @wraps(fn)
    async def wrapped(*args,**kwargs):
        token=_receipt_flow.set(True)
        try:return await fn(*args,**kwargs)
        finally:_receipt_flow.reset(token)
    return wrapped

def terminal_delivery(fn):
    @wraps(fn)
    async def wrapped(*args, **kwargs):
        with output_role('delivery'):
            return await fn(*args, **kwargs)
    return wrapped


def restart_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text='🔄 شروع مجدد ربات', callback_data=RESTART)]])


def empty_list_text(text):
    value=str(text or '')
    return bool(re.search(r'هیچ|لیست.{0,10}خالی|ثبت نشده|ثبت‌نشده|درخواستی وجود ندارد|خالی است|هنوز.{0,30}(?:نشده|نساخته)',value))


def completion_text(text):
    """Legacy completion adapter; prompts/errors/details remain editable pages.

    Explicit final/delivery roles take precedence and do not depend on wording.
    """
    value = str(text or '').strip()
    head = re.sub('<[^>]+>', '', value.split('\n')[0])
    if not value or value.startswith(('❌','⚠','⛔','⏳','🔎','📌')): return False
    if any(word in head for word in ('پیش‌نمایش','پیش نمایش','مشخصات زیر پیدا شد','مشخصات زیر','گیرنده:','مرحله ')): return False
    if any(word in value for word in ('حالا ', 'سپس ', 'در مرحله بعد', 'را ارسال کنید', 'را بفرستید', 'را انتخاب کنید', 'تأیید می‌کنید', 'تایید می‌کنید')) and not value.startswith('✅ تمدید سرویس با موفقیت'):
        return False
    if re.search(r'\b(?:saved|deleted|completed|successfully|cancelled)\b',head,re.I):return True
    return bool(re.search(r'(?:ذخیره|ثبت|حذف|اعمال|انجام|فعال|غیرفعال|تأیید|تایید|ارسال|ویرایش|اضافه|لغو|ساخته|تمدید|بروزرسانی|به‌روز|پاک|مسدود|باز|تکمیل|متوقف|منتقل|آزاد)\s+(?:گردید|شد|شدند|شد\.|شد؛)|با موفقیت|پایان یافت|تمام شد', head))


def _key(bot, chat):
    return f'dbot:ui:v2:{bot.id}:{chat}'


def page_key(route):
    """Stable page identity: refresh/page/tab changes do not create ancestors."""
    route=str(route or '')
    route=re.sub(r'_refresh(?=:|$)','',route)
    route=re.sub(r':(?:refresh|reload)(?=:|$)','',route)
    if route.startswith('admin:conversions:check:'):route=route.replace(':check:',':detail:',1)
    if route=='admin:conversions' or route.startswith('admin:conversions:list:'):
        return 'admin:conversions:list'
    if route.startswith('private_chat:reply:'):
        return 'private_chat:conversation:'+route.rsplit(':',1)[-1]
    # Numeric pagination suffixes describe one list, not another input step.
    return re.sub(r'(:list)(?::(?:page:)?\d+)+$',r'\1',route)


def _clean_history(record):
    active=record.get('active') or {}
    active_key=(page_key(active.get('route')),active.get('fsm'))
    cleaned=[]
    for page in record.get('history',[]):
        key=(page_key(page.get('route')),page.get('fsm'))
        if key==active_key and any(key):continue
        prior=next((i for i,p in enumerate(cleaned) if (page_key(p.get('route')),p.get('fsm'))==key),None) if any(key) else None
        if prior is not None:cleaned=cleaned[:prior]
        cleaned.append(page)
    record['history']=cleaned[-MAX_HISTORY:]
    return record


def _empty_placeholder(method):
    markup=getattr(method,'reply_markup',None)
    if not isinstance(markup,InlineKeyboardMarkup) or getattr(method,'__api_method__','')=='editMessageReplyMarkup':return method
    notices=[];rows=[]
    for row in markup.inline_keyboard:
        keep=[]
        for b in row:
            if b.callback_data=='noop' or (b.callback_data or '').startswith('noop:'):
                notices.append(b.text.lstrip('✅📭 '));continue
            keep.append(b)
        if keep:rows.append(keep)
    if not notices:return method
    field='text' if getattr(method,'text',None) is not None else 'caption'
    body=getattr(method,field,None) or ''
    for notice in notices:
        if notice not in body:body+='\n\n'+(escape(notice) if getattr(method,'parse_mode',None)=='HTML' else notice)
    return method.model_copy(update={field:body,'reply_markup':InlineKeyboardMarkup(inline_keyboard=rows)})


async def load_ui(bot, chat):
    key = _key(bot, chat)
    if _redis is not None:
        try:
            raw = await _redis.get(key)
            if raw:return _clean_history(json.loads(raw))
        except Exception:
            logger.warning('UI Redis read unavailable; using bounded fallback')
    value=copy.deepcopy(_memory.get(key, {'active':None,'history':[],'terminal':[]}))
    if value.get('_saved_at',time.time()) < time.time()-TTL:
        _memory.pop(key,None)
        return {'active':None,'history':[],'terminal':[]}
    return _clean_history(value)


async def save_ui(bot, chat, record):
    key = _key(bot, chat)
    record['_saved_at']=time.time()
    if _redis is not None:
        try:
            await _redis.set(key, json.dumps(record, ensure_ascii=False, default=str), ex=TTL)
            # Redis already owns this history. Do not retain a second copy for
            # every user for the entire bot process lifetime.
            _memory.pop(key,None)
            return
        except Exception:
            logger.warning('UI Redis write unavailable; using bounded fallback')
    _memory[key] = copy.deepcopy(record)
    if len(_memory) > 2048: _memory.pop(next(iter(_memory)))


def _back(button):
    data = button.callback_data or ''
    return data.startswith('back:') or (button.text or '').startswith(('🔙','↩️')) or bool(re.search(r'(?:بازگشت|برگشت)(?: به|$)|\bback\b', button.text or '', re.I))


def normalize_markup(markup, *, terminal=False):
    if terminal: return restart_keyboard()
    if not isinstance(markup, InlineKeyboardMarkup): return markup
    rows=[]; restart=False
    for row in markup.inline_keyboard:
        clean=[]
        for b in row:
            if b.callback_data in (RESTART,'home:main','profile:home','report:home'):
                restart=True;continue
            clean.append(b)
        if clean: rows.append(clean)
    # Navigation pages keep a normal Back; proactive messages may keep Restart.
    if restart: rows.append(restart_keyboard().inline_keyboard[0])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _wire_markup(markup, record, reuse=None):
    node = record['active']
    rows=[]; callbacks=[]; nonce=secrets.token_hex(8); had_back=False
    original_callbacks = {b.callback_data for row in markup.inline_keyboard for b in row} if isinstance(markup, InlineKeyboardMarkup) else set()
    conversation_restart = (RESTART in original_callbacks and 'private_chat:end' in original_callbacks
                            and any((value or '').startswith('private_chat:reply:') for value in original_callbacks))
    if isinstance(markup, InlineKeyboardMarkup):
        for row in markup.inline_keyboard:
            clean=[]
            for b in row:
                data=b.callback_data
                if data in (RESTART,'home:main','profile:home','report:home'): continue
                if data==node.get('route') and empty_list_text(node.get('text')) and re.search(r'(?:^|:)(?:list|users|requests)(?::|$)',data or '') and not re.search(r'بروزرسانی|به‌روزرسانی|refresh|reload',b.text,re.I):continue
                if _back(b):
                    had_back=True;continue
                if data:
                    callbacks.append(data)
                    b=b.model_copy(update={'callback_data':f'u:{nonce}:{len(callbacks)-1}'})
                clean.append(b)
            if clean: rows.append(clean)
    if conversation_restart:
        rows.append(restart_keyboard().inline_keyboard[0])
    elif record['history']:
        callbacks.append(BACK)
        rows.append([InlineKeyboardButton(text='🔙 بازگشت', callback_data=f'u:{nonce}:{len(callbacks)-1}')])
    elif had_back:
        # A cold-start legacy page has no restorable parent. Restart is safe;
        # invoking a guessed business callback as Back is not.
        rows.append(restart_keyboard().inline_keyboard[0])
    if reuse and reuse.get('callbacks')==callbacks and reuse.get('nonce'):
        old_nonce=reuse['nonce']
        for row in rows:
            for b in row:
                if b.callback_data and b.callback_data.startswith(f'u:{nonce}:'):
                    b.callback_data=b.callback_data.replace(f'u:{nonce}:',f'u:{old_nonce}:',1)
        nonce=old_nonce
    node['nonce']=nonce;node['callbacks']=callbacks
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


@dataclass
class UiContext:
    bot: object
    chat: int
    event: object
    state: object
    record: dict
    route: str=''
    before: dict | None=None
    before_state: str | None=None
    before_data: dict=field(default_factory=dict)
    pushed: bool=False
    final: bool=False
    force_new: bool=False
    closed: bool=False
    final_ids: list=field(default_factory=list)


async def _expire(bot, chat, mid):
    if not mid:return
    token=_bypass.set(True)
    try:
        try:await bot.delete_message(chat_id=chat,message_id=mid)
        except Exception:
            try:await bot.edit_message_reply_markup(chat_id=chat,message_id=mid,reply_markup=None)
            except Exception:pass
    finally:_bypass.reset(token)


def _message(chat, mid, text=''):
    return Message(message_id=mid,date=datetime.now(timezone.utc),chat=Chat(id=chat,type='private'),text=text)


def _clean_kwargs(method, fields):
    return {name:getattr(method,name) for name in fields if getattr(method,name,None) is not None}


def _input_payload(message):
    payload={}
    for key in ('text','caption','entities','caption_entities'):
        value=getattr(message,key,None)
        if value is not None:
            payload[key]=[v.model_dump(mode='json') for v in value] if isinstance(value,list) else value
    for kind in ('contact','location','venue'):
        obj=getattr(message,kind,None)
        if obj:payload[kind]=obj.model_dump(mode='json')
    for key in ('photo','document','video','animation','audio','voice','video_note','sticker'):
        value=getattr(message,key,None)
        if value:payload['media']={'type':key,'file_id':value[-1].file_id if key=='photo' else value.file_id};break
    return payload


async def _copied_input(bot,method):
    if getattr(method,'__api_method__','') not in ('copyMessage','forwardMessage'):return None
    source=getattr(method,'from_chat_id',None)
    if not isinstance(source,int):return None
    ctx=current_ui()
    record=ctx.record if ctx and ctx.chat==source else await load_ui(bot,source)
    payload=record.get('inputs',{}).get(str(method.message_id))
    if not payload:return None
    import aiogram.methods as methods
    common={'chat_id':method.chat_id}
    common.update(_clean_kwargs(method,('message_thread_id','disable_notification','protect_content','reply_parameters')))
    markup=getattr(method,'reply_markup',None)
    if markup is not None:common['reply_markup']=markup
    media=payload.get('media')
    if payload.get('contact'):
        contact=payload['contact'];return methods.SendContact(**common,**{k:v for k,v in contact.items() if k in ('phone_number','first_name','last_name','vcard')})
    if payload.get('venue'):
        venue=dict(payload['venue']);location=venue.pop('location');venue.update(latitude=location['latitude'],longitude=location['longitude']);return methods.SendVenue(**common,**venue)
    if payload.get('location'):
        location=payload['location'];return methods.SendLocation(**common,latitude=location['latitude'],longitude=location['longitude'])
    if not media:
        return SendMessage(**common,text=payload.get('text') or '',entities=payload.get('entities'))
    kind=media['type']
    cls=getattr(methods,{'video_note':'SendVideoNote'}.get(kind,'Send'+kind.title()))
    if kind not in ('video_note','sticker'):
        common.update(caption=getattr(method,'caption',None) or payload.get('caption'),caption_entities=getattr(method,'caption_entities',None) or payload.get('caption_entities'))
        if isinstance(getattr(method,'parse_mode',None),str):common['parse_mode']=method.parse_mode
    return cls(**common,**{kind:media['file_id']})


async def _send_callback_answer(method, send):
    """Acknowledgements are best-effort; never replay the business handler."""
    try:
        return await asyncio.wait_for(send(method), timeout=CALLBACK_ACK_TIMEOUT)
    except (TelegramNetworkError, TelegramServerError, TelegramRetryAfter, TimeoutError) as exc:
        logger.warning('Telegram callback acknowledgement unavailable (%s); continuing without replaying the action.', type(exc).__name__)
        return False
    except TelegramBadRequest as exc:
        if 'query is too old' in str(exc).lower() or 'query id is invalid' in str(exc).lower():
            return True
        raise


async def dispatch_ui_method(bot, method, send):
    """One interception point covers helpers and direct Message.answer calls."""
    if _receipt_flow.get():
        name=getattr(method,'__api_method__','')
        if name=='answerCallbackQuery':return await _send_callback_answer(method,send)
        if name=='deleteMessage':return True
        if name in ('editMessageText','editMessageCaption','editMessageMedia'):
            text=getattr(method,'text',None) or getattr(method,'caption',None) or getattr(getattr(method,'media',None),'caption',None)
            if text:return await send(SendMessage(chat_id=method.chat_id,text=text,reply_markup=getattr(method,'reply_markup',None),**_clean_kwargs(method,('parse_mode',))))
            return _message(method.chat_id,method.message_id).as_(bot)
        return await send(method)
    if _bypass.get():
        if getattr(method,'__api_method__','')=='answerCallbackQuery':return await _send_callback_answer(method,send)
        return await send(method)
    name=getattr(method,'__api_method__','')
    method=_empty_placeholder(method)
    copied=await _copied_input(bot,method)
    if copied is not None:
        current=current_ui()
        with output_role('page' if current and current.chat==method.chat_id else 'notification'):
            return await dispatch_ui_method(bot,copied,send)
    live=current_ui()
    if name=='answerCallbackQuery' and live and isinstance(live.event,CallbackQuery):
        notice=str(getattr(method,'text',None) or '')
        if notice and empty_list_text(notice):
            live.empty_notice=notice;live.empty_page=True
            if getattr(live,'answered',False):return True
        if notice and completion_text(notice) and not live.force_new and not re.search(r'(?:^|:)(?:refresh|reload)(?::|$)',live.route):live.pending_result=notice
        if getattr(live,'answered',False) and not getattr(method,'show_alert',False):
            if notice and not notice.startswith(('⏳','در حال','شروع مجدد')):live.answer_notice=notice
            return True
        live.answered=True
        return await _send_callback_answer(method,send)
    if name=='answerCallbackQuery':return await _send_callback_answer(method,send)
    chat=getattr(method,'chat_id',None)
    if not isinstance(chat,int) or chat <= 0: return await send(method)
    ctx=current_ui()
    own=bool(ctx and ctx.bot.id==bot.id and ctx.chat==chat)
    role=_role.get()
    text=getattr(method,'text',None) or getattr(method,'caption',None) or getattr(getattr(method,'media',None),'caption',None) or ''
    outgoing=name in ('sendMessage','sendPhoto','sendDocument','sendVideo','sendAnimation','sendAudio','sendVoice','sendVideoNote','sendSticker','copyMessage','forwardMessage')
    editing=name in ('editMessageText','editMessageCaption','editMessageMedia','editMessageReplyMarkup')
    if not outgoing and not editing: return await send(method)
    markup = getattr(method, 'reply_markup', None)
    independent = role!='page' and outgoing and isinstance(markup, InlineKeyboardMarkup) and any(
        any((b.callback_data or '').startswith(prefix) for prefix in ('order:approve:', 'order:reject:', 'wallet_topup:approve:', 'wallet_topup:reject:', 'pgadmin:approve:', 'pgadmin:reject:', 'resadmin:req_approve:', 'resadmin:req_reject:', 'resadmin:access_approve:', 'paygwallet:review:'))
        for row in markup.inline_keyboard for b in row)
    if independent:
        return await send(method.model_copy(update={'reply_markup':normalize_markup(markup)}))
    # Approval workers sometimes update only the final receipt keyboard.
    # A completed status label is not a new list page and must never gain Back.
    if name=='editMessageReplyMarkup' and isinstance(markup,InlineKeyboardMarkup):
        buttons=[b for row in markup.inline_keyboard for b in row]
        closed=any((b.callback_data=='noop' or (b.callback_data or '').startswith('noop:closed:')) and completion_text(b.text) for b in buttons)
        passive=all((b.callback_data or '') in ('noop',RESTART,'home:main','profile:home','report:home') or (b.callback_data or '').startswith('noop:closed:') for b in buttons)
        if closed and passive:
            record=ctx.record if own else await load_ui(bot,chat)
            marker=next((b.callback_data for b in buttons if (b.callback_data or '').startswith('noop:closed:order:')),None)
            active=record['active']
            if marker and active:
                ident=marker.rsplit(':',1)[-1]
                if active.get('route') in (f'order:approve:{ident}',f'pending_receipts:order:{ident}'):
                    status=next(b.text for b in buttons if b.callback_data==marker)
                    with output_role('final'):
                        return await dispatch_ui_method(bot,SendMessage(chat_id=chat,text=status),send)
                if active['id']==method.message_id:
                    # The shared UI may now show another order. A late worker
                    # must not remove that order's controls or navigation.
                    return _message(chat,method.message_id).as_(bot)
            result=await send(method.model_copy(update={'reply_markup':restart_keyboard()}))
            mid=method.message_id
            if record['active'] and record['active']['id']==mid:
                record['active']=None;record['history']=[]
                from app.bot.utils import forget_ui_message
                forget_ui_message(chat)
                if own:ctx.final=True
            record['terminal']=(record['terminal']+[mid])[-64:]
            await save_ui(bot,chat,record)
            return result
    # A stale auto-refresh task must not resurrect a finished form.
    if not own and editing:
        record=await load_ui(bot,chat)
        mid=getattr(method,'message_id',None)
        if mid in record['terminal'] or mid in record.get('retired',[]):
            return _message(chat,mid,text).as_(bot)
        if record['active'] and mid == record['active']['id']:
            lock=_locks.setdefault(_key(bot,chat),asyncio.Lock())
            if lock.locked():return _message(chat,mid,text).as_(bot)
            async with lock:
                record=await load_ui(bot,chat)
                if not record['active'] or mid!=record['active']['id']:return _message(chat,mid,text).as_(bot)
                ctx=UiContext(bot,chat,None,None,record,route=record['active'].get('route',''),pushed=True)
                ctx.background=True
                token=_context.set(ctx)
                try:
                    with output_role('page'):return await dispatch_ui_method(bot,method,send)
                finally:ctx.closed=True;_context.reset(token)
    terminal = role in ('final','delivery') or (own and role not in ('page','attachment') and completion_text(text))
    if own and terminal and role not in ('final','delivery') and ctx.state is not None and await ctx.state.get_state() is not None:
        ctx.final_candidate=text;terminal=False
    if own and getattr(ctx,'final_candidate',None) and ctx.final_candidate!=text:
        ctx.final_candidate=None
    if not own and not terminal:
        if role not in ('page','attachment','notification') and completion_text(text):
            return await send(method.model_copy(update={'reply_markup':restart_keyboard()}))
        markup=normalize_markup(getattr(method,'reply_markup',None))
        if isinstance(getattr(method,'reply_markup',None),InlineKeyboardMarkup):method=method.model_copy(update={'reply_markup':markup})
        return await send(method)
    record=ctx.record if own else await load_ui(bot,chat)
    if own:
        ctx.rendered=True
        if empty_list_text(text):ctx.empty_page=True
    if own and not getattr(ctx,'attachments_cleaned',False):
        for mid in record.get('attachments',[]):await _expire(bot,chat,mid)
        record['attachments']=[];ctx.attachments_cleaned=True
    if role=='attachment':
        result=await send(method)
        if getattr(result,'message_id',None):record.setdefault('attachments',[]).append(result.message_id)
        await save_ui(bot,chat,record);return result
    active=record['active']; old_id=active['id'] if active else None
    # Explicit status-to-configuration delivery replaces a terse success prelude;
    # actual multi-part configuration artifacts are retained together.
    if own and role=='delivery' and not getattr(ctx,'delivering',False):
        for mid in ctx.final_ids: await _expire(bot,chat,mid)
        ctx.final_ids.clear();ctx.delivering=True
    if terminal:
        markup=restart_keyboard()
        if editing:
            if name=='editMessageReplyMarkup':
                return await send(method.model_copy(update={'reply_markup':markup}))
            if name=='editMessageText':
                method=SendMessage(chat_id=chat,text=method.text,reply_markup=markup,**_clean_kwargs(method,('parse_mode','entities','link_preview_options')))
            elif name=='editMessageCaption':
                method=SendMessage(chat_id=chat,text=method.caption or '',reply_markup=markup,entities=method.caption_entities,**_clean_kwargs(method,('parse_mode',)))
            else:
                return await send(method.model_copy(update={'reply_markup':markup}))
        else: method=method.model_copy(update={'reply_markup':markup})
        result=await send(method)
        await _expire(bot,chat,old_id)
        if old_id:record.setdefault('retired',[]).append(old_id)
        record['history']=[];record['active']=None
        mid=getattr(result,'message_id',None)
        if mid:record['terminal']=(record['terminal']+[mid])[-64:]
        if own:
            ctx.final=True
            if mid and role!='delivery':ctx.final_ids.append(mid)
        from app.bot.utils import forget_ui_message
        forget_ui_message(chat)
        await save_ui(bot,chat,record)
        return result
    if own and ctx.final:
        # Late cleanup/keyboard edits from a completed handler cannot restore
        # its previous menu or attach another action to the result.
        return _message(chat,(record['terminal'] or [0])[-1],text).as_(bot)
    if name=='editMessageReplyMarkup' and active:
        markup=_wire_markup(getattr(method,'reply_markup',None),record)
        active['markup']=getattr(method,'reply_markup',None).model_dump(mode='json') if isinstance(getattr(method,'reply_markup',None),InlineKeyboardMarkup) else None
        result=await send(method.model_copy(update={'message_id':old_id,'reply_markup':markup}))
        await save_ui(bot,chat,record);return result
    # Push the previous page only once per input/callback, never on errors or a
    # refresh. State snapshots make Back restore a form instead of resubmitting it.
    is_error=str(text).lstrip().startswith(('❌','⚠','⛔')) and not getattr(ctx,'empty_page',False)
    refresh=bool(re.search(r'(?:^|[:_])(?:refresh|reload|noop)(?::|_|$)',ctx.route)) if own else False
    if own and ctx.before and not ctx.force_new:
        now_state=await ctx.state.get_state() if ctx.state is not None else ctx.before_state
        target=page_key(ctx.route)
        same=bool(target and target==page_key(ctx.before.get('route')) and now_state==ctx.before_state)
        refresh=refresh or same
        if target and not same and not ctx.pushed and not is_error:
            ancestor=next((i for i,p in enumerate(record['history']) if page_key(p.get('route'))==target and p.get('fsm')==now_state),None)
            if ancestor is not None:
                record['history']=record['history'][:ancestor];ctx.pushed=True
    if own and ctx.before and not ctx.pushed and not ctx.force_new and not is_error and not refresh:
        snapshot=copy.deepcopy(ctx.before)
        snapshot['fsm']=ctx.before_state;snapshot['data']=copy.deepcopy(ctx.before_data)
        record['history']=(record['history']+[snapshot])[-MAX_HISTORY:]
        ctx.pushed=True
    original=getattr(method,'reply_markup',None)
    render={}
    if isinstance(getattr(method,'parse_mode',None),str):render['parse_mode']=method.parse_mode
    entities=getattr(method,'entities',None) or getattr(method,'caption_entities',None)
    if entities:render['entities']=[e.model_dump(mode='json') for e in entities]
    node={'render':render,'id':old_id,'text':text,'markup':original.model_dump(mode='json') if isinstance(original,InlineKeyboardMarkup) else None,'route':ctx.route if own else '', 'fsm':active.get('fsm') if active else None,'data':active.get('data',{}) if active else {}}
    record['active']=node
    markup=_wire_markup(original,record,reuse=active if refresh or getattr(ctx,'background',False) else None)
    force_new=bool(own and ctx.force_new)
    if force_new:record['history']=[];markup=_wire_markup(original,record)
    result=None
    if old_id and not force_new:
        try:
            if name in ('sendMessage','editMessageText'):
                result=await send(EditMessageText(chat_id=chat,message_id=old_id,text=text,reply_markup=markup,**_clean_kwargs(method,('parse_mode','entities','link_preview_options'))))
            elif name in ('sendPhoto','sendDocument','sendVideo','sendAnimation','sendAudio'):
                field_name=name[4:].lower()
                media_type={'photo':InputMediaPhoto,'document':InputMediaDocument,'video':InputMediaVideo,'animation':InputMediaAnimation,'audio':InputMediaAudio}[field_name]
                media=media_type(media=getattr(method,field_name),caption=getattr(method,'caption',None),**_clean_kwargs(method,('parse_mode','caption_entities')))
                result=await send(EditMessageMedia(chat_id=chat,message_id=old_id,media=media,reply_markup=markup))
            elif editing:
                result=await send(method.model_copy(update={'message_id':old_id,'reply_markup':markup}))
        except TelegramBadRequest as exc:
            if 'message is not modified' in str(exc).lower():result=_message(chat,old_id,text)
            elif name in ('sendMessage','editMessageText') and active and active.get('media') and len(text)<=1024 and (refresh or page_key(ctx.route)==page_key(active.get('route'))):
                try:result=await send(EditMessageCaption(chat_id=chat,message_id=old_id,caption=text,reply_markup=markup,**_clean_kwargs(method,('parse_mode',))))
                except TelegramBadRequest:pass
    if result is None:
        if editing and name=='editMessageText':method=SendMessage(chat_id=chat,text=text,**_clean_kwargs(method,('parse_mode','entities','link_preview_options')))
        elif editing and name=='editMessageCaption':method=SendMessage(chat_id=chat,text=text,entities=method.caption_entities,**_clean_kwargs(method,('parse_mode',)))
        elif editing and name=='editMessageMedia':
            import aiogram.methods as methods
            media=method.media;kind=media.type
            cls=getattr(methods,'Send'+kind.title())
            method=cls(chat_id=chat,**{kind:media.media},caption=media.caption,**_clean_kwargs(media,('parse_mode','caption_entities')))
        result=await send(method.model_copy(update={'reply_markup':markup}))
        await _expire(bot,chat,old_id)
        if old_id:record.setdefault('retired',[]).append(old_id)
    node['id']=getattr(result,'message_id',old_id)
    if isinstance(result,Message):
        for field_name in ('photo','document','video','animation','audio','voice','video_note','sticker'):
            obj=getattr(result,field_name,None)
            if obj:
                node['media']={'type':field_name,'file_id':obj[-1].file_id if field_name=='photo' else obj.file_id};break
    record['retired']=record.get('retired',[])[-64:]
    from app.bot.utils import remember_ui_message
    remember_ui_message(chat,node['id'])
    await save_ui(bot,chat,record)
    return result


async def _restore(ctx):
    if not ctx.record['history']:return
    previous=ctx.record['history'].pop()
    ctx.pushed=True;ctx.before=None
    await ctx.state.clear()
    if previous.get('fsm'):await ctx.state.set_state(previous['fsm'])
    data=previous.get('data') or {};data.pop('last_bot_message_id',None)
    if data:await ctx.state.update_data(**data)
    markup=InlineKeyboardMarkup.model_validate(previous['markup']) if previous.get('markup') else None
    with output_role('page'):
        media=previous.get('media')
        if media:
            send_media=getattr(ctx.bot,'send_'+media['type'])
            render=dict(previous.get('render') or {})
            if 'entities' in render:render['caption_entities']=render.pop('entities')
            if media['type'] in ('video_note','sticker'):
                await send_media(ctx.chat,media['file_id'],reply_markup=markup)
            else:await send_media(ctx.chat,media['file_id'],caption=previous.get('text') or '',reply_markup=markup,**render)
        else:
            await ctx.bot.send_message(ctx.chat,previous.get('text') or 'بازگشت',reply_markup=markup,**(previous.get('render') or {}))
    if ctx.record['active']:ctx.record['active']['route']=previous.get('route','')


async def _expired_callback(bot,event,record,text):
    await event.answer(text,show_alert=True)
    active=record.get('active')
    if not active or active['id']!=event.message.message_id:
        token=_bypass.set(True)
        try:
            try:await bot.edit_message_reply_markup(chat_id=event.message.chat.id,message_id=event.message.message_id,reply_markup=restart_keyboard())
            except Exception:pass
        finally:_bypass.reset(token)


class UnifiedUiMiddleware(BaseMiddleware):
    async def __call__(self,handler,event,data):
        message=event.message if isinstance(event,CallbackQuery) else event if isinstance(event,Message) else None
        bot=data.get('bot')
        if not bot or not message or message.chat.type!='private':return await handler(event,data)
        chat=message.chat.id;state=data.get('state')
        if state is None:return await handler(event,data)
        key=_key(bot,chat);lock=_locks.setdefault(key,asyncio.Lock())
        if lock.locked():
            if isinstance(event,CallbackQuery):await event.answer('عملیات قبلی در حال انجام است؛ کمی صبر کنید.')
            return
        async with lock:
            distributed=None
            if _redis is not None:
                distributed=_redis.lock(key+':lock',timeout=600,blocking_timeout=1)
                if not await distributed.acquire():
                    if isinstance(event,CallbackQuery):await event.answer('در حال پردازش درخواست قبلی هستیم.')
                    return
            try:
                return await self._run(handler,event,data,bot,chat,state)
            finally:
                if distributed is not None:
                    try:await distributed.release()
                    except Exception:pass

    async def _run(self,handler,event,data,bot,chat,state):
        message=event.message if isinstance(event,CallbackQuery) else event
        record=await load_ui(bot,chat);route=event.data or '' if isinstance(event,CallbackQuery) else ''
        initial_state=await state.get_state()
        if isinstance(event,CallbackQuery) and (route=='noop' or route.startswith('noop:closed:')):
            await event.answer();return
        if isinstance(event,CallbackQuery):
            active=record['active']
            if route.startswith('u:'):
                try:
                    _,nonce,index=route.split(':');index=int(index)
                    if index<0 or not active or event.message.message_id!=active['id'] or nonce!=active.get('nonce'):raise ValueError()
                    route=active['callbacks'][index]
                except (ValueError,IndexError,KeyError):
                    await _expired_callback(bot,event,record,'این پیام منقضی شده است؛ از «شروع مجدد ربات» استفاده کنید.');return
                event=event.model_copy(update={'data':route})
            elif route!=RESTART and event.message.message_id in record['terminal']:
                await _expired_callback(bot,event,record,'این فرآیند تکمیل شده و دکمه‌های آن منقضی است.');return
            elif route!=RESTART and (event.message.message_id in record.get('retired',[]) or (active and event.message.message_id==active['id'] and active.get('nonce'))):
                await _expired_callback(bot,event,record,'این دکمه قدیمی است؛ از دکمه‌های پیام فعلی استفاده کنید.');return
        if (isinstance(event,CallbackQuery) and route.startswith(RECEIPT_ACTIONS)) or (isinstance(event,Message) and initial_state and 'receipt' in initial_state.lower()):
            # Receipts are immutable artifacts, not navigation pages. Follow-up
            # prompts/results get new messages; only their keyboard may change.
            if isinstance(event,CallbackQuery) and record.get('active') and record['active']['id']==message.message_id:
                record['active']=None;record['history']=[];await save_ui(bot,chat,record)
            token=_receipt_flow.set(True)
            try:return await handler(event,data)
            finally:_receipt_flow.reset(token)
        if isinstance(event,CallbackQuery) and route!=RESTART and not (event.data or '').startswith('u:') and (not record['active'] or event.message.message_id!=record['active']['id']):
            old=record['active']
            if old:
                await _expire(bot,chat,old['id']);record.setdefault('retired',[]).append(old['id'])
            content=_input_payload(message)
            record['active']={'id':message.message_id,'text':message.text or message.caption or '',
                'markup':message.reply_markup.model_dump(mode='json') if message.reply_markup else None,
                'route':'notification','fsm':None,'data':{},'render':{}}
            if content.get('media'):record['active']['media']=content['media']
            record['history']=[]
            # An explicitly opened notification starts its own navigation line.
            # Do not restore an unrelated form's state when going Back.
            await state.clear();data['raw_state']=None
        before_state=await state.get_state();before_data=await state.get_data()
        if isinstance(event,Message) and before_state and record['active']:
            route=record['active'].get('route') or 'state:'+before_state
        if isinstance(event,Message) and (event.text or '').split('@')[0].strip()=='/pending_receipts':
            route='pending_receipts:list'
        if not record['active'] and record['terminal'] and before_state:
            await state.clear();before_state=None;before_data={};data['raw_state']=None
        ctx=UiContext(bot,chat,event,state,record,route=route,before=copy.deepcopy(record['active']),before_state=before_state,before_data=before_data,force_new=route in (RESTART,'home:main','profile:home','report:home') or isinstance(event,Message) and str(event.text or '').startswith('/start'))
        if ctx.force_new:record['history']=[];ctx.before=None
        from app.bot.utils import remember_ui_message,forget_ui_message
        if record['active']:remember_ui_message(chat,record['active']['id'])
        else:forget_ui_message(chat)
        if isinstance(event,Message) and not (before_state and any(word in before_state.lower() for word in ('password','token','removeservicefromlist'))):
            inputs=record.setdefault('inputs',{})
            inputs[str(event.message_id)]=_input_payload(event)
            while len(inputs)>32:inputs.pop(next(iter(inputs)))
        token=_context.set(ctx)
        try:
            if isinstance(event,CallbackQuery):await event.answer()
            if route==BACK:
                await _restore(ctx);return
            return await handler(event,data)
        finally:
            try:
                candidate=getattr(ctx,'pending_result',None) or (getattr(ctx,'final_candidate',None) if await state.get_state() is None else None)
                if not ctx.final and candidate:
                    with output_role('final'):await bot.send_message(chat,candidate)
                elif not ctx.final and getattr(ctx,'empty_notice',None) and not getattr(ctx,'rendered',False):
                    with output_role('page'):await bot.send_message(chat,ctx.empty_notice)
                elif not ctx.final and getattr(ctx,'answer_notice',None) and not getattr(ctx,'rendered',False) and not ctx.force_new:
                    with output_role('page'):await bot.send_message(chat,ctx.answer_notice)
                if ctx.final:await state.clear()
                elif record['active']:
                    record['active']['fsm']=await state.get_state();record['active']['data']=await state.get_data()
                await save_ui(bot,chat,record)
                if isinstance(event,Message) and not event.from_user.is_bot and (before_state or ctx.before or ctx.force_new):
                    try:await event.delete()
                    except Exception:pass
            finally:ctx.closed=True;_context.reset(token)
