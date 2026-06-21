from datetime import datetime, timedelta
from sqlalchemy import select
from app.database.session import SessionLocal
from app.database.models import ClientService, User, Plan
from app.database.defaults import get_setting_value
from app.services.wallet_service import WalletService
from app.bot.keyboards.common import back_button
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

async def scan_payg_usage():
    # Placeholder for PAYG scanning. This stays safe and does not block bot startup.
    return

def gb(b): return b/1024**3 if b else 0

async def scan_service_alerts(bot):
    now=datetime.utcnow()
    async with SessionLocal() as session:
        services=(await session.execute(select(ClientService).where(ClientService.is_active == True))).scalars().all()
        for svc in services:
            user=await session.get(User, svc.user_id)
            if not user: continue
            remain=max((svc.total_bytes or 0)-(svc.used_bytes or 0),0)
            rows=[[InlineKeyboardButton(text='تمدید سرویس', callback_data=f'svc:renew_menu:{svc.id}')]]
            kb=InlineKeyboardMarkup(inline_keyboard=rows)
            if svc.total_bytes and remain <= 1024**3 and not getattr(svc,'notify_1gb_sent',False):
                await bot.send_message(user.telegram_id, f'⚠️ اشتراک شما با یوزرنیم {svc.client_username} کمتر از 1 گیگ حجم دارد.', reply_markup=kb)
                setattr(svc,'notify_1gb_sent',True)
            if svc.total_bytes and remain <= 100*1024**2 and not getattr(svc,'notify_100mb_sent',False):
                await bot.send_message(user.telegram_id, f'⚠️ حجم اشتراک شما با یوزرنیم {svc.client_username} کمتر از 100 مگابایت مانده است.', reply_markup=kb)
                setattr(svc,'notify_100mb_sent',True)
            if svc.expires_at:
                delta=svc.expires_at-now
                checks=[('notify_24h_sent',timedelta(hours=24),'کمتر از 24 ساعت'),('notify_2h_sent',timedelta(hours=2),'کمتر از 2 ساعت'),('notify_20m_sent',timedelta(minutes=20),'کمتر از 20 دقیقه')]
                for attr,limit,label in checks:
                    if delta <= limit and delta.total_seconds()>0 and not getattr(svc,attr,False):
                        await bot.send_message(user.telegram_id, f'⏰ از زمان سرویس {svc.client_username} {label} باقی مانده است.', reply_markup=kb)
                        setattr(svc,attr,True)
        await session.commit()
