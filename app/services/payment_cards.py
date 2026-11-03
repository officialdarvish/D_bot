"""Resolve a server's reseller payment card without using another vendor's card."""
from sqlalchemy import select,or_
from app.database.models import PaymentCard

async def reseller_payment_card(session,server_id=None,*,panel=False):
    if panel:
        card=await session.scalar(select(PaymentCard).where(PaymentCard.server_type=='panel_reseller',or_(PaymentCard.server_id==server_id,PaymentCard.server_id.is_(None)),PaymentCard.is_active.is_(True)).order_by(PaymentCard.server_id.is_not(None).desc(),PaymentCard.id.desc()).limit(1))
        if card:return card
    if server_id:
        card=await session.scalar(select(PaymentCard).where(PaymentCard.server_id==server_id,PaymentCard.server_type!='panel_reseller',PaymentCard.is_active.is_(True)).order_by((PaymentCard.server_type=='reseller').desc(),PaymentCard.id.desc()).limit(1))
        if card:return card
    return await session.scalar(select(PaymentCard).where(PaymentCard.server_type=='reseller',PaymentCard.server_id.is_(None),PaymentCard.is_active.is_(True)).order_by(PaymentCard.id.desc()).limit(1))
