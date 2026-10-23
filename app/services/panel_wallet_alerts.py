"""Durable, shared-wallet low-balance notifications for purchased PAYG panels."""
import json
from datetime import datetime
from sqlalchemy import select
from aiogram.types import InlineKeyboardButton,InlineKeyboardMarkup
from app.database.models import User,Setting,PasarGuardPanelOrder
from app.database.session import SessionLocal

THRESHOLDS=(200000,150000,100000,50000)

def topup_keyboard(order_id):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='➕ افزایش اعتبار کیف پول پنل نمایندگی',callback_data=f'pgsale:topup:{order_id}')]])

async def notify_panel_wallet(bot,user_id,order_id):
    if bot is None:return
    async with SessionLocal() as s:
        user=await s.get(User,user_id,with_for_update=True)
        panel=await s.get(PasarGuardPanelOrder,order_id)
        if not user or not panel or panel.user_id!=user.id or panel.status not in {'approved','delivery_pending'}:return
        from app.services.reseller_management import profile
        if (await profile(s,f'panels:{user.id}')).get('billing_mode')=='volume':return
        key=f'pgpanel_wallet_alert:{user.id}'
        row=await s.get(Setting,key)
        try:state=json.loads(row.value) if row else {}
        except (ValueError,TypeError):state={}
        sent=set(state.get('sent',[]));balance=int(user.wallet_balance or 0)
        # Re-arm only levels replenished by a recharge. All purchased panels
        # share this wallet, so state is keyed by user instead of by panel.
        sent={level for level in sent if balance<level}
        due=[level for level in THRESHOLDS if 0<balance<level and level not in sent]
        if due:
            level=min(due)
            await bot.send_message(user.telegram_id,
                f'⚠️ اعتبار کیف پول پنل نمایندگی کمتر از {level:,} تومان شده است.\n'
                f'👤 پنل: {panel.username}\n💰 موجودی فعلی: {balance:,} تومان\n'
                'برای جلوگیری از قطع سرویس، کیف پول پنل نمایندگی را شارژ کنید.',
                reply_markup=topup_keyboard(panel.id),parse_mode=None)
            sent.update(level for level in THRESHOLDS if balance<level)
        value=json.dumps({'sent':sorted(sent),'balance':balance,'updated_at':datetime.utcnow().isoformat()})
        if row:row.value=value
        else:s.add(Setting(key=key,value=value))
        await s.commit()


async def rearm_wallet_alerts(session,user):
    row=await session.get(Setting,f'pgpanel_wallet_alert:{user.id}')
    if not row:return
    try:state=json.loads(row.value)
    except (ValueError,TypeError):return
    balance=int(user.wallet_balance or 0)
    state['sent']=[level for level in state.get('sent',[]) if balance<level]
    state['balance']=balance
    row.value=json.dumps(state)
