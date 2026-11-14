"""Named, sparse snapshots of user-facing text/visibility only. No business settings."""
import json,re,uuid
from fastapi import HTTPException
from sqlalchemy import select
from app.database.models import Setting
from app.bot.custom_texts import build_catalog,legacy_setting_key,legacy_enabled_key,invalidate_custom_text_cache
from app.database.defaults import invalidate_settings_cache
from app.bot.keyboards.common import invalidate_button_settings_cache
PREFIX='custom_profile:'
LIMIT=8


def profile_key(profile_id):
    if not re.fullmatch('[a-f0-9]{32}',profile_id):raise HTTPException(404,'Template not found')
    return PREFIX+profile_id


def invalidate():
    invalidate_custom_text_cache();invalidate_settings_cache();invalidate_button_settings_cache()


async def profiles(session):
    rows=(await session.execute(select(Setting).where(Setting.key.like(PREFIX+'%')))).scalars().all()
    return [{'id':r.key[len(PREFIX):],'name':json.loads(r.value)['name']} for r in rows]


async def capture(session,name):
    name=name.strip()
    if not name or len(name)>80:raise HTTPException(422,'Enter a template name (1–80 characters)')
    if len(await profiles(session))>=LIMIT:raise HTTPException(409,'You can save up to 8 templates')
    catalog=build_catalog();keys={k for e in catalog for k in (e.key,legacy_setting_key(e),legacy_enabled_key(e)) if k}
    values={r.key:r.value for r in (await session.execute(select(Setting).where(Setting.key.in_(keys)))).scalars()}
    texts={};flags={}
    for e in catalog:
        value=values.get(e.key) or values.get(legacy_setting_key(e),'')
        if value and value!=e.default:
            if len(value.encode('utf-16-le'))//2>(64 if e.kind=='button' else 4096):raise HTTPException(422,'A saved text exceeds the Telegram length limit')
            texts[e.key]=value
        key=legacy_enabled_key(e)
        if key and key in values:flags[e.key]=str(values[key]).lower() not in {'0','false','off','no','disabled'}
    from app.services.delivery_templates import SETTING_KEY,normalize_config
    delivery=await session.get(Setting,SETTING_KEY)
    delivery_config=normalize_config(json.loads(delivery.value)) if delivery else None
    from app.services.user_content import load_apps
    tutorials={row['id']:{'name':row['name'],'text':row['text']} for row in await load_apps(session)}
    key=uuid.uuid4().hex
    session.add(Setting(key=PREFIX+key,value=json.dumps({'name':name,'texts':texts,'flags':flags,'delivery':delivery_config,'tutorials':tutorials},ensure_ascii=False)))
    await session.commit()
    return key


async def apply(session,profile_id):
    data={'texts':{},'flags':{}}
    if profile_id!='default':
        row=await session.get(Setting,profile_key(profile_id))
        if not row:raise HTTPException(404,'Template not found')
        data=json.loads(row.value)
    from app.services.delivery_templates import SETTING_KEY,normalize_config,load_config
    current_delivery=await load_config(session)
    delivery=normalize_config(data['delivery']) if data.get('delivery') else {'active':'simple','templates':current_delivery['templates']}
    retained={row['id']:row for row in current_delivery['templates']}
    retained.update({row['id']:row for row in delivery['templates']})
    if len(retained)>30:raise HTTPException(409,'Remove unused delivery templates before applying this profile')
    delivery=normalize_config({**delivery,'templates':list(retained.values())})
    previous_delivery=await session.get(Setting,SETTING_KEY)
    if previous_delivery:await session.delete(previous_delivery)
    catalog=build_catalog()
    keys={k for e in catalog for k in (e.key,legacy_setting_key(e),legacy_enabled_key(e)) if k}
    rows=(await session.execute(select(Setting).where(Setting.key.in_(keys)))).scalars().all()
    for row in rows:await session.delete(row)
    await session.flush()
    writes={}
    for e in catalog:
        value=data.get('texts',{}).get(e.key)
        if value:
            if not isinstance(value,str) or len(value.encode('utf-16-le'))//2>(64 if e.kind=='button' else 4096):raise HTTPException(422,'Template contains invalid text')
            writes[e.key]=value
            legacy=legacy_setting_key(e)
            if legacy:writes[legacy]=value
        enabled=legacy_enabled_key(e)
        if enabled and e.key in data.get('flags',{}):writes[enabled]='1' if data['flags'][e.key] else '0'
    if delivery:writes[SETTING_KEY]=json.dumps(delivery,ensure_ascii=False)
    for key,value in writes.items():session.add(Setting(key=key,value=value))
    if data.get('tutorials'):
        from app.services.user_content import load_apps,save_apps
        apps=await load_apps(session)
        for app in apps:
            saved=data['tutorials'].get(app['id'])
            if saved:app.update({k:saved[k] for k in ('name','text') if k in saved})
        await save_apps(apps,session)
    await session.commit();invalidate()
