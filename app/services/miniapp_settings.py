"""Database-backed Mini App presentation and feature controls."""
import json
import re
from urllib.parse import urlsplit
from app.core.branding import BRAND_NAME, MINIAPP_ACCENT
from app.database.models import Setting
from app.database.session import SessionLocal

LAUNCHER_LABEL_MAX = 32
LAUNCHER_LABEL_ERROR = 'Enter a single-line Telegram button label of up to 32 characters.'

DEFAULTS = {
    'enabled': True, 'title': BRAND_NAME, 'welcome': 'اشتراک‌های تو، همیشه در دسترس',
    'menu_text': BRAND_NAME, 'launcher_label': '', 'accent': MINIAPP_ACCENT, 'animations': True, 'fullscreen': False,
    'show_buy': True, 'show_wallet': True, 'show_services': True, 'show_support': True,
    'show_trial': True, 'show_tutorials': True, 'show_rules': True,
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


def clean_launcher_label(value):
    if not isinstance(value, str):
        raise ValueError(LAUNCHER_LABEL_ERROR)
    label = value.strip()
    if len(label) > LAUNCHER_LABEL_MAX or re.search(r'[\x00-\x1f\x7f-\x9f\u2028\u2029]', label):
        raise ValueError(LAUNCHER_LABEL_ERROR)
    return label


def clean_config(values):
    if not isinstance(values, dict):
        raise ValueError('Invalid Mini App configuration.')
    result = dict(DEFAULTS)
    for key in BOOL_KEYS:
        value = values.get(key, DEFAULTS[key])
        result[key] = value is True or str(value).lower() in ('1','true','on')
    # Old title and menu_text values are ignored. Only the launcher label is editable.
    try:
        result['launcher_label'] = clean_launcher_label(values.get('launcher_label', ''))
    except ValueError:
        pass  # Keep other stored preferences if an imported label is invalid.
    result['welcome'] = str(values.get('welcome', DEFAULTS['welcome'])).strip()[:180] or DEFAULTS['welcome']
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


async def read_preferences(session):
    """Read saved preferences before applying global feature availability."""
    row = await session.get(Setting, 'miniapp_config')
    try:
        config = clean_config(json.loads(row.value)) if row else dict(DEFAULTS)
    except (ValueError, TypeError):
        config = dict(DEFAULTS)
    support = await session.get(Setting, 'support_username')
    try:
        name = support_username(support.value if support else '')
    except ValueError:
        name = ''
    config['support_username'] = name
    config['support_url'] = 'https://t.me/' + name if name else ''
    return config


async def read_config(session=None):
    if session is None:
        async with SessionLocal() as owned:
            return await read_config(owned)
    config = await read_preferences(session)
    from app.services.features import capabilities
    features = await capabilities(session)
    config['features'] = features
    config['reseller_enabled'] = config['reseller_enabled'] and features['resellers']
    config['reseller_requests'] = config['reseller_requests'] and features['resellers']
    config['show_wallet'] = config['show_wallet'] and features['wallet']
    return config
