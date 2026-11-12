"""Server-priced bounded day/GB plans and immutable purchase snapshots."""
from types import SimpleNamespace
from app.database.models import Plan
KEY='custom_tariff'
def normalize(values):
    if not values or str(values.get('enabled','0')).lower() not in {'1','true','yes','on'}:return None
    def integer(key,lo,hi):
        raw=values.get(key)
        if isinstance(raw,bool):raise ValueError('Invalid tariff')
        n=int(str(raw))
        if not lo<=n<=hi:raise ValueError('Invalid tariff bounds or price')
        return n
    result={k:integer(k,1,1000000 if 'gb' in k else 3650) for k in ('min_gb','max_gb','min_days','max_days')}
    for k in ('price_gb','price_day'):result[k]=integer(k,0,10**9)
    if result['min_gb']>result['max_gb'] or result['min_days']>result['max_days'] or result['price_gb']+result['price_day']<=0:raise ValueError('Invalid tariff bounds')
    return {'enabled':True,**result}
def selected_plan(plan,gb,days):
    policy=normalize((plan.meta or {}).get(KEY))
    if not policy:return plan
    try:volume=int(str(gb));duration=int(str(days))
    except (ValueError,TypeError):raise ValueError('Choose GB and days / حجم و روز را انتخاب کنید')
    if not policy['min_gb']<=volume<=policy['max_gb'] or not policy['min_days']<=duration<=policy['max_days']:raise ValueError('Outside allowed range / مقدار خارج از بازه مجاز است')
    meta={**(plan.meta or {}),'pricing_currency':'IRT','custom_selection':{'parent_id':plan.id,'volume_gb':volume,'duration_days':duration}}
    meta.pop(KEY,None);meta.pop('price_usd',None)
    return SimpleNamespace(id=plan.id,title=f'{plan.title} | {volume}GB | {duration} Days',volume_gb=volume,duration_days=duration,price_irt=volume*policy['price_gb']+duration*policy['price_day'],server_id=plan.server_id,category_id=plan.category_id,inbound_ids=list(plan.inbound_ids or []),hwid_limit=plan.hwid_limit,is_unlimited=False,is_active=True,meta=meta)
async def snapshot(session,plan,owner_id):
    if not (plan.meta or {}).get('custom_selection'):return plan
    row=Plan(title=plan.title,volume_gb=plan.volume_gb,duration_days=plan.duration_days,price_irt=plan.price_irt,server_id=plan.server_id,category_id=plan.category_id,inbound_ids=plan.inbound_ids,hwid_limit=plan.hwid_limit,is_unlimited=False,is_active=False,meta={**plan.meta,'custom_owner_id':owner_id})
    session.add(row);await session.flush();return row
async def from_form(request,meta):
    form=await request.form()
    if 'custom_enabled' not in form:return meta
    policy=normalize({'enabled':form.get('custom_enabled'),**{k:form.get('custom_'+k) for k in ('min_gb','max_gb','min_days','max_days','price_gb','price_day')}})
    result=dict(meta);result.pop(KEY,None)
    if policy:result[KEY]=policy
    return result
