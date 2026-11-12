"""One role-aware payment route shared by checkout and connection migration."""
from sqlalchemy import select
from app.database.models import PaymentCard, Server


def choose_payment_card(cards, server_id=None, *, provider=None, role='public'):
    """Resolve active cards without mixing public, reseller and panel routes."""
    cards = [c for c in cards if c.is_active]
    def newest(items):
        return max(items, key=lambda c: c.id, default=None)
    def typed(kind):
        local = newest(c for c in cards if server_id is not None and c.server_id == server_id and c.server_type == kind)
        return local or newest(c for c in cards if c.server_id is None and c.server_type == kind)
    if role == 'panel':
        panel = typed('panel_reseller')
        if panel:
            return panel
    if role in {'reseller', 'panel'}:
        # Retain legacy provider-card fallback for reseller-only connections.
        local = [c for c in cards if server_id is not None and c.server_id == server_id and c.server_type in {'reseller', provider}]
        selected = max(local, key=lambda c: (c.server_type == 'reseller', c.id), default=None)
        return selected or newest(c for c in cards if c.server_id is None and c.server_type == 'reseller')
    return typed(provider)


async def public_payment_card(session, server):
    alias_id=(server.meta or {}).get('connection_alias_of')
    if alias_id:
        server=await session.get(Server,alias_id) or server
    cards = (await session.scalars(select(PaymentCard).where(PaymentCard.is_active.is_(True)))).all()
    return choose_payment_card(cards, server.id, provider=server.server_type)


async def reseller_payment_card(session, server_id=None, *, panel=False):
    server = await session.get(Server, server_id) if server_id else None
    if server and (server.meta or {}).get('connection_alias_of'):
        server=await session.get(Server,server.meta['connection_alias_of']) or server
        server_id=server.id
    cards = (await session.scalars(select(PaymentCard).where(PaymentCard.is_active.is_(True)))).all()
    return choose_payment_card(cards, server_id, provider=server.server_type if server else None, role='panel' if panel else 'reseller')
