"""Shared Telegram/Mini App reseller checkout, immutable invoices and approval.

User row locks serialize purchases across both surfaces. A pending remote write
is never replayed: ambiguous panel creation is held for owner reconciliation.
"""
from datetime import datetime,timedelta
from sqlalchemy import select,func
from app.database.models import (User,Server,Setting,ResellerPackage,ResellerAccount,
    MiniAppOperation,PasarGuardPanelOrder,PasarGuardPanelMeter,ResellerTopupRequest,WalletTransaction)
from app.database.defaults import get_setting_value
from app.bot.keyboards.common import get_user_button
from app.services.reseller_billing import policy,credit
from app.services.reseller_management import profile,save_profile
from app.services.live_pricing import quote_plan,plan_price_label
from app.services.payment_cards import reseller_payment_card
from app.core.security import encrypt_text

GB=1024**3
KIND='reseller_join'
OPEN={'waiting_receipt','pending','processing','review'}
LABELS={'volume':'خرید سرویس حجمی','payg':'خرید سرویس پرداخت به‌ازای مصرف','panel':'خرید وب پنل نمایندگی'}


async def access():
    if not (await get_user_button('reseller_request'))[1]:
        raise ValueError('درخواست نمایندگی غیرفعال است.')


async def selected_mode(s,user_id,*,exclude=None):
    account=await s.scalar(select(ResellerAccount).where(ResellerAccount.user_id==user_id))
    modes={account.billing_mode or 'volume'} if account else set()
    excluded=await s.get(MiniAppOperation,exclude) if exclude else None
    own_panel=(excluded.result or {}).get('panel_id',-1) if excluded else -1
    panel=await s.scalar(select(PasarGuardPanelOrder.id).where(PasarGuardPanelOrder.id!=own_panel,PasarGuardPanelOrder.user_id==user_id,
        PasarGuardPanelOrder.status.in_(['pending','processing','approved','delivery_pending','review_required'])).limit(1))
    if panel:modes.add((await profile(s,f'panels:{user_id}')).get('billing_mode','payg'))
    ops=(await s.scalars(select(MiniAppOperation).where(MiniAppOperation.user_id==user_id,
        MiniAppOperation.kind==KIND,MiniAppOperation.status.in_(list(OPEN))))).all()
    modes.update(op.payload['mode'] for op in ops if op.id!=exclude)
    if len(modes)>1:raise ValueError('حساب شما دو مدل تعرفه دارد؛ ابتدا مدیر آن را بررسی کند.')
    return next(iter(modes),None)


async def require_mode(s,user_id,mode,*,exclude=None):
    existing=await selected_mode(s,user_id,exclude=exclude)
    if existing and existing!=mode:
        raise ValueError('هر نماینده فقط می‌تواند یک مدل تعرفه داشته باشد؛ مدل فعلی شما '+('حجمی' if existing=='volume' else 'پرداخت به‌ازای مصرف')+' است.')


async def catalog(s,user):
    await access()
    chosen=await selected_mode(s,user.id)
    servers=(await s.scalars(select(Server).where(Server.is_active.is_(True)).order_by(Server.id))).all()
    servers=[v for v in servers if (v.meta or {}).get('scope')=='reseller']
    packages=(await s.scalars(select(ResellerPackage).where(ResellerPackage.is_active.is_(True)).order_by(ResellerPackage.id))).all()
    packages=[p for p in packages if p.server_id in {v.id for v in servers} and p.volume_gb>0]
    volume_enabled=await get_setting_value('reseller_join_volume_enabled','1')=='1'
    payg_enabled=await get_setting_value('reseller_join_payg_enabled','1')=='1'
    panel_enabled=(await get_user_button('panel_sales'))[1] and await get_setting_value('pasarguard_panel_sales_enabled','0')=='1'
    panel_id=int(await get_setting_value('pasarguard_panel_sales_server_id','0') or 0)
    panel=next((v for v in servers if v.id==panel_id and v.server_type=='pasarguard'),None)
    panel_modes=[m for m in (policy(panel)[0] if panel else []) if chosen in (None,m) and await get_setting_value(f'pasarguard_panel_sales_{m}_enabled','1')=='1']
    return {'selected_mode':chosen,'options':[
        kind for kind,enabled in [('volume',volume_enabled and chosen in (None,'volume') and any('volume' in policy(v)[0] for v in servers) and bool(packages)),
        ('panel',panel_enabled and bool(panel) and bool(panel_modes)),
        ('payg',payg_enabled and chosen in (None,'payg') and any('payg' in policy(v)[0] and policy(v)[1]>0 for v in servers))] if enabled],
        'servers':[{'id':v.id,'name':v.name,'modes':policy(v)[0],'rate':policy(v)[1]} for v in servers],
        'packages':[{'id':p.id,'title':p.title,'server_id':p.server_id,'volume_gb':p.volume_gb,'days':p.reseller_validity_days,'price':plan_price_label(p)} for p in packages if p.server_id in {v.id for v in servers}],
        'panel_server_id':panel_id,'panel_modes':panel_modes,
        'panel_min_gb':int(await get_setting_value('pasarguard_panel_sales_min_initial_gb','100') or 100),
        'panel_price':int(await get_setting_value('pasarguard_panel_sales_price_irt','0') or 0),
        'panel_rate':int(await get_setting_value('pasarguard_panel_sales_gb_price_irt','0') or 0),
        'payg_min_credit':int(await get_setting_value('reseller_payg_min_topup_irt','10000') or 10000)}


async def quote(s,user,request):
    cat=await catalog(s,user);kind=request.get('kind');mode=request.get('mode') if kind=='panel' else kind
    if kind not in cat['options'] or mode not in {'volume','payg'}:raise ValueError('این نوع نمایندگی فعال یا برای تعرفه شما مجاز نیست.')
    if kind=='panel' and mode not in cat['panel_modes']:raise ValueError('این روش فروش پنل غیرفعال است.')
    await require_mode(s,user.id,mode)
    sid=cat['panel_server_id'] if kind=='panel' else int(request.get('server_id') or 0)
    server=await s.get(Server,sid)
    if not server or not server.is_active or (server.meta or {}).get('scope')!='reseller' or mode not in policy(server)[0]:
        raise ValueError('سرور برای این مدل نمایندگی فعال نیست.')
    package=None;volume=days=initial=0;rate=policy(server)[1];setup=cat['panel_price'] if kind=='panel' else 0
    if mode=='volume':
        package=await s.get(ResellerPackage,int(request.get('package_id') or 0))
        if not package or not package.is_active or package.volume_gb<=0 or package.server_id!=sid:
            raise ValueError('بسته حجمی برای این سرور فعال نیست.')
        price=(await quote_plan(package)).amount_irt
        volume=package.volume_gb*GB;days=package.reseller_validity_days
    else:
        rate=cat['panel_rate'] if kind=='panel' else rate
        if rate<=0:raise ValueError('قیمت هر گیگ پرداخت به‌ازای مصرف تنظیم نشده است.')
        initial=rate*max(1,cat['panel_min_gb']) if kind=='panel' else max(1,cat['payg_min_credit'])
        price=initial
    card=await reseller_payment_card(s,sid,panel=kind=='panel')
    amount=setup+price
    if amount>0 and not card:raise ValueError('شماره کارت پرداخت این نمایندگی تنظیم نشده است.')
    from app.services.reseller_service import package_inbound_policy
    return dict(inbound_policy=package_inbound_policy(package),kind=kind,mode=mode,server_id=sid,server_name=server.name,package_id=package.id if package else None,
        title=LABELS[kind],package_title=package.title if package else None,volume_bytes=volume,days=days,
        setup_amount=setup,initial_credit=initial,rate=rate,min_initial_gb=cat['panel_min_gb'] if kind=='panel' and mode=='payg' else None,
        amount=amount,card={'id':card.id,'number':card.card_number,'owner':card.owner_name} if card else None)


def view(op):
    q=op.payload
    return {'id':op.id,'key':op.key,'status':op.status,'quote':{k:v for k,v in q.items() if k not in {'request','password_encrypted'}},
        'message':(op.result or {}).get('message',''),'panel_id':(op.result or {}).get('panel_id')}


async def checkout(s,user,key,request,expected):
    await s.get(User,user.id,with_for_update=True)
    old=await s.scalar(select(MiniAppOperation).where(MiniAppOperation.key==key))
    # Never retain plaintext passwords in durable request comparisons.
    clean={k:v for k,v in request.items() if k!='password'}
    if old:
        if old.user_id!=user.id or old.kind!=KIND or old.payload.get('request')!=clean:raise ValueError('شناسه درخواست برای خرید دیگری استفاده شده است.')
        return old
    if await s.scalar(select(MiniAppOperation.id).where(MiniAppOperation.user_id==user.id,MiniAppOperation.kind==KIND,MiniAppOperation.status.in_(list(OPEN))).limit(1)):
        raise ValueError('یک درخواست نمایندگی در جریان است؛ ابتدا آن را بررسی یا لغو کنید.')
    q=await quote(s,user,request)
    if q['amount']!=expected:raise ValueError('قیمت تغییر کرده است؛ فاکتور را دوباره بررسی کنید.')
    if q['kind']=='panel':
        from app.services.pasarguard_panel_sales import validate_panel_username,validate_panel_password,PanelResellerProvisioner
        name=str(request.get('username','')).strip()
        if not validate_panel_username(name) or not validate_panel_password(request.get('password','')):raise ValueError('نام کاربری یا رمز پنل مطابق استاندارد پاسارگارد نیست.')
        server=await s.get(Server,q['server_id'],with_for_update=True)
        held=await s.scalar(select(MiniAppOperation.id).where(MiniAppOperation.kind==KIND,MiniAppOperation.status.in_(list(OPEN)),MiniAppOperation.payload['server_id'].as_integer()==server.id,func.lower(MiniAppOperation.payload['username'].as_string())==name.lower()).limit(1))
        if held:raise ValueError('نام کاربری پنل در یک سفارش دیگر رزرو شده است.')
        reserved=await s.scalar(select(PasarGuardPanelOrder.id).where(PasarGuardPanelOrder.server_id==server.id,
            PasarGuardPanelOrder.username==name,PasarGuardPanelOrder.status.in_(['pending','processing','approved','delivery_pending','review_required'])).limit(1))
        if reserved or not await PanelResellerProvisioner().username_available(server,name):raise ValueError('نام کاربری پنل قبلاً ثبت شده است؛ نام دیگری وارد کنید.')
        q.update(username=name,password_encrypted=encrypt_text(request['password']))
    op=MiniAppOperation(user_id=user.id,key=key,kind=KIND,status='waiting_receipt',payload={**q,'request':clean})
    s.add(op);await s.flush()
    return op


async def submit(s,op,file_id):
    if op.status!='waiting_receipt':return False
    if op.created_at<datetime.utcnow()-timedelta(hours=24):raise ValueError('فاکتور منقضی شده است؛ سفارش جدیدی ثبت کنید.')
    await require_mode(s,op.user_id,op.payload['mode'],exclude=op.id)
    op.status='pending';op.result={'receipt_file_id':file_id,'message':'رسید برای تأیید مدیر ثبت شد.'};op.updated_at=datetime.utcnow()
    await s.flush();return True


async def notify(bot,s,op,*,uploaded=None):
    from aiogram.types import InlineKeyboardButton,InlineKeyboardMarkup
    from app.core.config import settings
    user=await s.get(User,op.user_id);q=op.payload
    text=f"🧾 درخواست نمایندگی #{op.id}\nنام: {user.full_name}\nID: {user.telegram_id}\nUsername: @{user.username or '-'}\n{q['title']} | {q['mode']}\nمبلغ: {q['amount']:,} تومان\nخرید پنل: {q['setup_amount']:,}\nشارژ اولیه: {q['initial_credit']:,}\nبسته: {q.get('package_title') or '-'} | {q['volume_bytes']/GB:g} GB | {q['days']} روز\nیوزرنیم پنل: {q.get('username') or '-'}\nتاریخ: {op.created_at}"
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='✅ بررسی سرور و تعرفه',callback_data=f'rjoin:review:{op.id}'),InlineKeyboardButton(text='❌ رد رسید',callback_data=f'rjoin:reject:{op.id}')]])
    for tid in set(settings.owner_ids+settings.admin_ids):
        try:
            receipt=(op.result or {}).get('receipt_file_id')
            if uploaded and tid==uploaded[0]:
                try:
                    if len(text)>900:raise ValueError('summary too long for caption')
                    await bot.edit_message_caption(chat_id=tid,message_id=uploaded[1],caption=text,reply_markup=kb,parse_mode=None)
                except Exception:
                    await bot.send_message(tid,text,reply_markup=kb,parse_mode=None)
            elif receipt and receipt!='FREE':
                caption=text if len(text)<=900 else None
                try:await bot.send_photo(tid,receipt,caption=caption,reply_markup=kb if caption else None,parse_mode=None)
                except Exception:await bot.send_document(tid,receipt,caption=caption,reply_markup=kb if caption else None,parse_mode=None)
                if not caption:await bot.send_message(tid,text,reply_markup=kb,parse_mode=None)
            else:
                await bot.send_message(tid,text,reply_markup=kb,parse_mode=None)
        except Exception:
            import logging
            logging.getLogger(__name__).warning('Reseller receipt notification failed request=%s recipient=%s',op.id,tid)



async def approve(s,op,actor,server_id,mode):
    if op.status!='pending':raise ValueError('این درخواست قبلاً بررسی شده است.')
    user=await s.get(User,op.user_id,with_for_update=True);q=op.payload
    await require_mode(s,user.id,mode,exclude=op.id)
    # Changing a paid invoice's tariff/server requires a fresh invoice. Approval
    # cannot silently allocate another vendor or another economic model.
    if mode!=q['mode'] or server_id!=q['server_id']:raise ValueError('سرور و مدل باید با فاکتور پرداخت‌شده مطابقت داشته باشند.')
    server=await s.get(Server,server_id)
    if not server or not server.is_active or (server.meta or {}).get('scope')!='reseller' or mode not in policy(server)[0]:raise ValueError('سرور یا تعرفه دیگر فعال نیست.')
    if q['kind']=='panel':
        from app.database.models import PaymentCard
        current_card=await s.get(PaymentCard,q['card']['id']) if q['card'] else None
        order=PasarGuardPanelOrder(user_id=user.id,server_id=server_id,username=q['username'],password_encrypted=q['password_encrypted'],
            amount_irt=q['amount'],payg_gb_price_irt=q['rate'] if mode=='payg' else 0,payg_hourly_price_irt=0,
            payg_max_users=int(await get_setting_value('pasarguard_panel_sales_max_users','0') or 0),
            card_id=current_card.id if current_card else None,receipt_file_id=op.result.get('receipt_file_id','FREE'),status='pending')
        s.add(order);await s.flush();op.result={**op.result,'panel_id':order.id};op.status='processing'
        return order
    from app.services.reseller_service import ensure_reseller_for_user
    account=await ensure_reseller_for_user(s,user.id,server_id,0)
    previous=account.allowed_server_ids or ([account.server_id] if account.server_id else [])
    account.server_id=account.server_id or server_id;account.allowed_server_ids=list(dict.fromkeys(previous+[server_id]));account.billing_mode=mode;account.is_active=True
    from app.database.models import ResellerAccessRequest
    access_request=await s.scalar(select(ResellerAccessRequest).where(ResellerAccessRequest.user_id==user.id))
    if access_request:
        access_request.status='approved';access_request.reviewed_by=actor;access_request.reviewed_at=datetime.utcnow()
    if mode=='volume':
        from app.services.reseller_service import apply_package_inbound_policy
        apply_package_inbound_policy(account,server_id,q.get('inbound_policy',{}))
        account.total_bytes=int(account.total_bytes or 0)+q['volume_bytes']
        if q['days']:
            account.expires_at=max(account.expires_at or datetime.utcnow(),datetime.utcnow())+timedelta(days=q['days'])
        from app.database.models import ResellerServiceActivity
        s.add(ResellerServiceActivity(reseller_id=account.id,server_id=server_id,action='topup',event_key=f'join:{op.id}',username=str(user.telegram_id),volume_bytes=q['volume_bytes'],duration_days=q['days'],meta={'source':'reseller_onboarding','amount_irt':q['amount']}))
    else:
        account.expires_at=None
        finance=await profile(s,f'account:{account.id}',True)
        finance['payg_rate']=q['rate']
        await save_profile(s,f'account:{account.id}',finance)
        await credit(s,account,q['initial_credit'],key=f'join:{op.id}',kind='initial_topup')
    op.status='done';op.result={**op.result,'message':'نمایندگی شما فعال شد؛ از بخش نمایندگی در ربات و مینی‌اپ استفاده کنید.','reviewer':actor,'reseller_id':account.id}
    return None


async def finalize_panel(s,order):
    op=await s.scalar(select(MiniAppOperation).where(MiniAppOperation.kind==KIND,MiniAppOperation.status=='processing',MiniAppOperation.result['panel_id'].as_integer()==order.id).with_for_update())
    if not op:return
    user=await s.get(User,op.user_id,with_for_update=True);q=op.payload
    await require_mode(s,user.id,q['mode'],exclude=op.id)
    finance=await profile(s,f'panels:{user.id}',True)
    finance['billing_mode']=q['mode']
    if q['mode']=='volume':finance['available_bytes']=int(finance.get('available_bytes',0))+q['volume_bytes']
    else:
        user.wallet_balance=int(user.wallet_balance or 0)+q['initial_credit']
        s.add(WalletTransaction(user_id=user.id,amount_irt=q['initial_credit'],tx_type='panel_initial_credit',description=f'Reseller initial invoice #{op.id}'))
    await save_profile(s,f'panels:{user.id}',finance)
    op.status='done';op.result={**op.result,'message':'پنل نمایندگی ساخته شد و اطلاعات ورود ارسال می‌شود.'}


async def check_panel_username(s,username,server_id):
    from app.services.pasarguard_panel_sales import PanelResellerProvisioner,validate_panel_username
    if not validate_panel_username(username):raise ValueError('نام کاربری باید ۴ تا ۳۲ نویسه انگلیسی باشد و با حرف شروع شود.')
    server=await s.get(Server,server_id)
    if not server or not server.is_active or server.server_type!='pasarguard' or (server.meta or {}).get('scope')!='reseller':raise ValueError('سرور پنل فعال نیست.')
    held=await s.scalar(select(MiniAppOperation.id).where(MiniAppOperation.kind==KIND,MiniAppOperation.status.in_(list(OPEN)),MiniAppOperation.payload['server_id'].as_integer()==server.id,func.lower(MiniAppOperation.payload['username'].as_string())==username.lower()).limit(1))
    if held:raise ValueError('این نام کاربری برای سفارش دیگری رزرو شده است؛ نام طولانی‌تری انتخاب کنید.')
    if not await PanelResellerProvisioner().username_available(server,username):raise ValueError('نام کاربری در پاسارگارد تکراری است؛ نام طولانی‌تری انتخاب کنید.')


async def recover(s):
    """Hold interrupted provisioning for review, never allocate or retry it."""
    ids=(await s.execute(select(MiniAppOperation.id,MiniAppOperation.result).where(MiniAppOperation.kind==KIND,MiniAppOperation.status=='processing',MiniAppOperation.updated_at<datetime.utcnow()-timedelta(minutes=15)))).all()
    for oid,result in ids:
        panel=await s.get(PasarGuardPanelOrder,result.get('panel_id'),with_for_update=True) if result.get('panel_id') else None
        op=await s.get(MiniAppOperation,oid,with_for_update=True,populate_existing=True)
        if not op or op.status!='processing' or op.updated_at>=datetime.utcnow()-timedelta(minutes=15):continue
        op.status='review';op.result={**op.result,'message':'ساخت پنل قطع شده و نیازمند بررسی مدیر است؛ دوباره پرداخت نکنید.'}
        if panel and panel.status in {'pending','processing'}:panel.status='review_required'
