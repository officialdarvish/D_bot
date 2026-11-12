"""Conservative, transactional consolidation of compatible legacy connections.

Operational references move together; historical ledgers and server IDs are kept.
Ambiguous identities, conflicting tariffs/policies/cards or duplicate usernames
remain untouched and are listed for review. No remote mutation is performed.
"""
import json
from collections import defaultdict
from sqlalchemy import select,text
from sqlalchemy.orm import class_mapper
from sqlalchemy.types import JSON
from app.database.models import (Server,Setting,ClientService,ResellerAccount,PaymentCard,Plan,ServerCategory,DiscountCode,ResellerPackage,PasarGuardPanelOrder,OpenVPNProfile,ResellerBuildConfig,ServiceDeletionTask,ResellerUsageMeter,Order,MiniAppOperation)
from app.services.server_connections import identity
from app.core.security import decrypt_text

REPORT_KEY='server_connection_migration_v2'
MODELS=(ClientService,ResellerAccount,PaymentCard,Plan,ServerCategory,DiscountCode,ResellerPackage,PasarGuardPanelOrder,OpenVPNProfile,ResellerBuildConfig,ServiceDeletionTask,ResellerUsageMeter,Order,MiniAppOperation)


def remap_json(value,mapping,key=''):
    if isinstance(value,dict):
        if key=='inbound_policies':return {str(mapping.get(int(k),int(k))) if str(k).isdigit() else k:remap_json(v,mapping,k) for k,v in value.items()}
        return {k:remap_json(v,mapping,k) for k,v in value.items()}
    if isinstance(value,list):
        if key in {'server_ids','allowed_server_ids'}:return list(dict.fromkeys(mapping.get(int(v),int(v)) if str(v).isdigit() else v for v in value))
        return [remap_json(v,mapping,key) for v in value]
    if (key=='server_id' or key.endswith('_server_id')) and str(value).isdigit():
        result=mapping.get(int(value),int(value));return str(result) if isinstance(value,str) else result
    return value


async def consolidate(session):
    if session.get_bind().dialect.name=='postgresql':
        await session.execute(text('SELECT pg_advisory_xact_lock(314158280)'))
    previous=await session.get(Setting,REPORT_KEY)
    if previous:return json.loads(previous.value)
    servers=(await session.execute(select(Server).order_by(Server.id).with_for_update())).scalars().all()
    report={'schema':2,'merged':[],'conflicts':[]}
    if not servers:return report # A fresh database stays raw.
    if session.get_bind().dialect.name=='postgresql':
        names=sorted({m.__table__.name for m in MODELS}|{'servers','settings'})
        await session.execute(text('LOCK TABLE '+','.join('"'+name+'"' for name in names)+' IN SHARE ROW EXCLUSIVE MODE'))
    groups=defaultdict(list)
    for row in servers:
        if row.server_type=='mikrotik' or (row.meta or {}).get('connection_alias_of'):continue
        groups[identity(row)].append(row)
    mapping={};canonical_rows={}
    for rows in groups.values():
        if len(rows)<2:continue
        ids={r.id for r in rows};reason=''
        try:
            if len({decrypt_text(r.password_encrypted) for r in rows})!=1:reason='credentials differ'
        except RuntimeError:reason='credentials unavailable'
        if len({r.is_active for r in rows})!=1:reason='enable switches differ'
        if len({r.subscription_url.rstrip('/') for r in rows if r.subscription_url})>1:reason='subscription endpoints differ'
        if len({r.category_id for r in rows if r.category_id})>1:reason='category assignments differ'
        if len({json.dumps((r.meta or {}).get('inbound_ids',[]),sort_keys=True) for r in rows})>1:reason='inbound/template assignments differ'
        reseller_rows=[r for r in rows if (r.meta or {}).get('scope','public') in {'reseller','all'}]
        tariff=lambda r:{k:v for k,v in (r.meta or {}).items() if k.startswith(('reseller_','payg_'))}
        if len({json.dumps(tariff(r),sort_keys=True) for r in reseller_rows})>1:reason='reseller tariff policies differ'
        clients=(await session.execute(select(ClientService).where(ClientService.server_id.in_(ids)))).scalars().all()
        names=[r.client_username for r in clients]
        if len(names)!=len(set(names)):reason='the same upstream username has multiple local services'
        accounts=(await session.execute(select(ResellerAccount))).scalars().all()
        for account in accounts:
            account_policies=dict(account.inbound_policies or {})
            if account.server_id in ids and str(account.server_id) not in account_policies and account.inbound_mode=='manual':
                account_policies[str(account.server_id)]={'mode':'manual','inbound_ids':list(account.inbound_ids or [])}
            policies=[v for k,v in account_policies.items() if str(k).isdigit() and int(k) in ids]
            if len({json.dumps(v,sort_keys=True) for v in policies})>1:reason='reseller inbound policies conflict'
        # Compare effective recipients within each sales role before/after remapping.
        # Different public/reseller cards are intentional, not a connection conflict.
        from types import SimpleNamespace
        from app.services.payment_cards import choose_payment_card
        cards=(await session.scalars(select(PaymentCard).where(PaymentCard.is_active.is_(True)))).all()
        public_rows=[r for r in rows if (r.meta or {}).get('scope','public') in {'public','all'}]
        canonical=min(public_rows or rows,key=lambda r:r.id)
        moved=[SimpleNamespace(id=c.id,server_id=canonical.id if c.server_id in ids else c.server_id,
               server_type=c.server_type,is_active=c.is_active,card_number=c.card_number,
               owner_name=c.owner_name,reviewer_telegram_id=c.reviewer_telegram_id) for c in cards]
        signature=lambda c:(c.card_number,c.owner_name,c.reviewer_telegram_id) if c else None
        for row in rows:
            roles=(['public'] if row in public_rows else []) + (['reseller','panel'] if row in reseller_rows else [])
            for role in roles:
                before=choose_payment_card(cards,row.id,provider=row.server_type,role=role)
                after=choose_payment_card(moved,canonical.id,provider=row.server_type,role=role)
                if signature(before)!=signature(after):reason=f'{role} payment recipient would change'
        if reason:
            report['conflicts'].append({'server_ids':sorted(ids),'reason':reason});continue
        canonical=min(public_rows or rows,key=lambda r:r.id)
        canonical.meta={**(canonical.meta or {}),**(tariff(reseller_rows[0]) if reseller_rows else {}),'scope':'all' if public_rows and reseller_rows else (canonical.meta or {}).get('scope','public')}
        canonical.subscription_url=canonical.subscription_url or next((r.subscription_url for r in rows if r.subscription_url),None)
        canonical.category_id=canonical.category_id or next((r.category_id for r in rows if r.category_id),None)
        for row in rows:
            if row.id==canonical.id:continue
            mapping[row.id]=canonical.id
            row.meta={**(row.meta or {}),'connection_alias_of':canonical.id}
        canonical_rows[canonical.id]=canonical
        report['merged'].append({'canonical_id':canonical.id,'alias_ids':sorted(ids-{canonical.id})})
    if mapping:
        for model in MODELS:
            columns=class_mapper(model).columns
            json_names=[c.key for c in columns if isinstance(c.type,JSON)]
            if 'server_id' not in columns and not json_names:continue
            for row in (await session.execute(select(model))).scalars().all():
                if isinstance(row,ResellerAccount) and row.server_id in mapping and row.inbound_mode=='manual' and str(row.server_id) not in (row.inbound_policies or {}):
                    row.inbound_policies={**(row.inbound_policies or {}),str(row.server_id):{'mode':'manual','inbound_ids':list(row.inbound_ids or [])}}
                if hasattr(row,'server_id') and row.server_id in mapping:row.server_id=mapping[row.server_id]
                for name in json_names:
                    value=getattr(row,name)
                    mapped=remap_json(value,mapping,name)
                    if mapped!=value:setattr(row,name,mapped)
        for setting in (await session.execute(select(Setting))).scalars().all():
            if setting.key.startswith('server_connection_migration_'):continue
            if setting.key.endswith('_server_id') and str(setting.value).isdigit() and int(setting.value) in mapping:
                setting.value=str(mapping[int(setting.value)])
            elif setting.value and setting.value[:1] in '[{':
                try:
                    value=json.loads(setting.value);mapped=remap_json(value,mapping)
                    if mapped!=value:setting.value=json.dumps(mapped,ensure_ascii=False)
                except (ValueError,TypeError):pass
    await session.merge(Setting(key=REPORT_KEY,value=json.dumps(report)))
    await session.flush()
    return report


async def sync_alias_connections(session,canonical):
    """Aliases remain usable for historical rows or callbacks already in flight."""
    rows=(await session.execute(select(Server).where(Server.server_type==canonical.server_type))).scalars().all()
    for alias in rows:
        if (alias.meta or {}).get('connection_alias_of')!=canonical.id:continue
        for field in ('panel_url','subscription_url','username','password_encrypted','is_active'):setattr(alias,field,getattr(canonical,field))


async def upgrade_connections():
    from app.database.session import SessionLocal
    import logging
    async with SessionLocal() as session:
        try:
            report=await consolidate(session);await session.commit()
            if report['merged'] or report['conflicts']:
                logging.getLogger(__name__).info('Connection migration: %s merged groups; %s conflicts retained',len(report['merged']),len(report['conflicts']))
        except Exception:
            await session.rollback()
            logging.getLogger(__name__).exception('Connection migration rolled back; existing server IDs retained')
