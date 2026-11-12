"""Reuse authenticated panel connections without rewriting historical finance IDs."""
import hashlib
import hmac
from urllib.parse import urlsplit,urlunsplit
from sqlalchemy import select,text
from app.database.models import Server
from app.core.security import decrypt_text


def normalized_url(value):
    p=urlsplit(str(value).strip())
    return urlunsplit((p.scheme.lower(),p.netloc.lower(),p.path.rstrip('/'),'',''))


def identity(server):
    return (server.server_type,normalized_url(server.panel_url),str(server.username or '').strip())


async def add_shared_connection(session,candidate):
    key=identity(candidate)
    if session.get_bind().dialect.name=='postgresql':
        lock=int.from_bytes(hashlib.sha256(repr(key).encode()).digest()[:8],'big',signed=True)
        await session.execute(text('SELECT pg_advisory_xact_lock(:key)'),{'key':lock})
    rows=(await session.execute(select(Server).where(Server.server_type==candidate.server_type).order_by(Server.id))).scalars().all()
    for row in rows:
        if (row.meta or {}).get('connection_alias_of') or identity(row)!=key:continue
        if not hmac.compare_digest(decrypt_text(row.password_encrypted).encode(),decrypt_text(candidate.password_encrypted).encode()):
            raise ValueError('This panel connection already exists with different credentials; edit the existing server / این اتصال ثبت شده است؛ اطلاعات همان سرور را ویرایش کنید.')
        before=dict(row.meta or {});after=dict(candidate.meta or {})
        old_scope=before.get('scope','public');new_scope=after.get('scope','public')
        if old_scope!=new_scope:before['scope']='all'
        if old_scope=='public' and new_scope in {'reseller','all'}:
            for field in ('reseller_billing_modes','reseller_payg_rate_irt'):
                if field in after:before[field]=after[field]
        if before.pop('deleted_from_panel',False):row.is_active=True
        row.meta=before
        return row
    session.add(candidate)
    await session.flush()
    return candidate
