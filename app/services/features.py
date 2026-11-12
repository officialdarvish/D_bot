"""Shared module gates. Upgrades preserve existing behaviour until explicitly changed."""
from sqlalchemy import select
from app.database.models import Setting, Server
FEATURES=('resellers','openvpn','trials','wallet','tutorials','xray')
async def capabilities(session):
    rows=(await session.execute(select(Setting).where(Setting.key.in_(['feature_'+x for x in FEATURES])))).scalars().all()
    values={r.key:r.value for r in rows}
    result={x:values.get('feature_'+x,'1')=='1' for x in FEATURES}
    if await session.scalar(select(Server.id).where(Server.server_type=='mikrotik').limit(1)):result['openvpn']=True
    return result
async def require_feature(name,session=None):
    from fastapi import HTTPException
    if session is None:
        from app.database.session import SessionLocal
        async with SessionLocal() as session:return await require_feature(name,session)
    if not (await capabilities(session)).get(name,False):raise HTTPException(403,'This module is disabled / این بخش غیرفعال است.')
