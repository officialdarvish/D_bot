"""Post-commit recharge notification and credit-owned panel recovery."""
import logging
from sqlalchemy import select
from app.database.models import MiniAppOperation,PasarGuardPanelOrder,PasarGuardPanelMeter,Order,User,Server
def SessionLocal():
    from app.database.session import SessionLocal as factory
    return factory()
log=logging.getLogger(__name__)

async def enqueue_panel_recharge(session,order):
    panel_id=(order.pricing_meta or {}).get('panel_order_id')
    if not panel_id:return
    panel=await session.get(PasarGuardPanelOrder,panel_id)
    if not panel or panel.user_id!=order.user_id:return
    key=f'panel-recharge:{order.id}'
    if await session.scalar(select(MiniAppOperation.id).where(MiniAppOperation.key==key)):return
    session.add(MiniAppOperation(user_id=order.user_id,key=key,kind='panel_recharge_notice',status='queued',payload={'order_id':order.id,'panel_id':panel_id}))

async def process_panel_recharges(bot=None,*,order_id=None):
    async with SessionLocal() as s:
        rows=(await s.execute(select(MiniAppOperation.id,MiniAppOperation.payload).where(MiniAppOperation.kind=='panel_recharge_notice',MiniAppOperation.status=='queued').order_by(MiniAppOperation.id).limit(100))).all()
    for oid,payload in rows:
        if order_id is not None and payload.get('order_id')!=order_id:continue
        try:await complete_recharge(oid,bot)
        except Exception:log.exception('Panel recharge recovery pending operation=%s',oid)

async def complete_recharge(oid,bot):
    from app.services.pasarguard_panel_meter import PanelMeterAPI
    from app.services.reseller_management import profile
    from app.services.panel_wallet_alerts import topup_keyboard
    # Lock remains held while delivering/recovering, serializing API + job retries.
    # The credited wallet transaction itself has already committed separately.
    async with SessionLocal() as s:
        op=await s.get(MiniAppOperation,oid,with_for_update=True)
        if not op or op.status!='queued':return
        receipt=await s.get(Order,op.payload['order_id']);user=await s.get(User,op.user_id)
        if not receipt or receipt.status!='paid' or not user:return
        state=dict(op.result or {});finance=await profile(s,f'panels:{user.id}')
        panels=(await s.execute(select(PasarGuardPanelOrder,PasarGuardPanelMeter).join(PasarGuardPanelMeter,PasarGuardPanelMeter.order_id==PasarGuardPanelOrder.id).where(PasarGuardPanelOrder.user_id==user.id,PasarGuardPanelOrder.status.in_(['approved','delivery_pending'])))).all()
        errors=[];api=PanelMeterAPI()
        from app.services.panel_billing_policy import panel_billing_mode
        async def eligible(panel,meter,mode):
            server=await s.get(Server,panel.server_id)
            if not server or not server.is_active or panel_billing_mode(server.meta,meter.gb_price_irt,meter.hourly_price_irt,finance)!=mode:
                errors.append(f'{panel.id}: billing policy unavailable')
                return False
            return True
        if finance.get('billing_mode','payg')=='payg' and not finance.get('transition'):
            for panel,meter in panels:
                if not meter.suspended:continue
                if not await eligible(panel,meter,'payg'):continue
                try:
                    # resume only restores IDs recorded by the credit cutoff.
                    # Manual tariff-conversion pauses never enter that set.
                    await api.resume(panel.id)
                except Exception as exc:errors.append(f'{panel.id}: {type(exc).__name__}')
        elif finance.get('billing_mode')=='volume' and not finance.get('transition'):
            for panel,meter in panels:
                if not await eligible(panel,meter,'volume'):continue
                try:await api.poll(panel.id)
                except Exception as exc:errors.append(f'{panel.id}: {type(exc).__name__}')
        if not state.get('notified') and bot is not None:
            await s.refresh(user)
            volume=finance.get('billing_mode')=='volume'
            text=(f'✅ اعتبار حجمی پنل نمایندگی شما افزایش یافت.\n💳 مبلغ پرداخت: {receipt.amount_irt:,} تومان\n💾 حجم قابل ساخت: {int(finance.get("available_bytes",0))/1024**3:.3f} گیگابایت' if volume else f'✅ کیف پول پنل نمایندگی شما شارژ شد.\n💳 مبلغ شارژ: {receipt.amount_irt:,} تومان\n💰 موجودی فعلی: {int(user.wallet_balance or 0):,} تومان')
            if errors:text+='\n⏳ فعال‌سازی خودکار پنل در حال پیگیری است.'
            elif finance.get('billing_mode','payg')=='payg' and any(m.suspended for _,m in panels) and not finance.get('transition'):text+='\n🟢 سرویس‌هایی که به‌علت اتمام اعتبار متوقف شده بودند، فعال شدند.'
            await bot.send_message(user.telegram_id,text,reply_markup=topup_keyboard(op.payload['panel_id']),parse_mode=None)
            state['notified']=True
        state['recovery_errors']=errors;op.result=state
        if state.get('notified') and not errors:op.status='done'
        await s.commit()
