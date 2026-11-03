"""Database-backed Mini App presentation and feature controls."""
import json
import re
from urllib.parse import urlsplit
from sqlalchemy import select
from app.database.models import Setting
from app.database.session import SessionLocal

DEFAULTS = {
    'enabled': True, 'title': 'D Bot', 'welcome': 'اشتراک‌های تو، همیشه در دسترس',
    'menu_text': 'D Bot', 'accent': '#12b9f5', 'animations': True, 'fullscreen': False,
    'show_buy': True, 'show_wallet': True, 'show_services': True, 'show_support': True,
    'reseller_enabled': True, 'reseller_requests': True, 'links': [],
}
BOOL_KEYS = {k for k,v in DEFAULTS.items() if isinstance(v,bool)}


def support_username(value: str, *, required=False):
    value = str(value or '').strip()
    if value.startswith('https://t.me/'):
        value = value.removeprefix('https://t.me/').strip('/')
    value = value.lstrip('@')
    if not value and not required:
        return ''
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{4,31}', value):
        raise ValueError('Enter a valid Telegram support username (5–32 characters).')
    return value


def clean_config(values):
    if not isinstance(values, dict):
        raise ValueError('Invalid Mini App configuration.')
    result = dict(DEFAULTS)
    for key in BOOL_KEYS:
        value = values.get(key, DEFAULTS[key])
        result[key] = value is True or str(value).lower() in ('1','true','on')
    for key,limit in [('title',60),('welcome',180),('menu_text',32)]:
        result[key] = str(values.get(key,DEFAULTS[key])).strip()[:limit] or DEFAULTS[key]
    color = str(values.get('accent',DEFAULTS['accent']))
    if not re.fullmatch(r'#[a-fA-F0-9]{6}',color):
        raise ValueError('Choose a valid accent color.')
    result['accent'] = color
    links = values.get('links',[])
    if not isinstance(links,list) or len(links)>6:
        raise ValueError('Add up to six shortcuts.')
    result['links'] = []
    for item in links:
        if not isinstance(item,dict): raise ValueError('Invalid shortcut.')
        label,url=str(item.get('label','')).strip(),str(item.get('url','')).strip()
        parsed=urlsplit(url)
        if not label or len(label)>50 or len(url)>1000 or parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Shortcuts need a title and a valid HTTPS URL.')
        result['links'].append({'label':label,'url':url})
    return result


async def read_config(session=None):
    owns = session is None
    if owns: session=SessionLocal()
    try:
        row=await session.get(Setting,'miniapp_config')
        try: config=clean_config(json.loads(row.value)) if row else dict(DEFAULTS)
        except (ValueError,TypeError): config=dict(DEFAULTS)
        support=await session.get(Setting,'support_username')
        try: name=support_username(support.value if support else '')
        except ValueError: name=''
        config['support_username']=name
        config['support_url']='https://t.me/'+name if name else ''
        return config
    finally:
        if owns: await session.close()
