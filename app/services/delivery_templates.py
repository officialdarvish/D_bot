"""Selectable delivery text templates shared by retail and reseller deliveries."""
from __future__ import annotations

from contextvars import ContextVar
from functools import wraps
from html import escape
from html.parser import HTMLParser
import json
import logging
import re
from string import Formatter

from app.database.models import Setting

log = logging.getLogger(__name__)
SETTING_KEY = 'service_delivery_templates_v1'
SIMPLE_TEXT = ('✅ سرویس شما آماده است.\n\n'
               '👤 نام کاربری: <code>{username}</code>\n'
               '📦 سرویس: <b>{title}</b>\n'
               '💾 ترافیک: <b>{traffic}</b>\n'
               '⏳ اعتبار: <b>{duration}</b>\n'
               '{credentials}\n{subscription_line}')
FIELDS = ['username', 'title', 'traffic', 'duration', 'volume_gb', 'duration_days',
          'sub_link', 'subscription_line', 'credentials', 'server_type', 'password', 'l2tp_server', 'l2tp_ipsec_secret']
FIXED_DELIVERY_TEXT = ContextVar('fixed_delivery_text', default=False)


class DeliveryTemplateText(str):
    """Marks already-rendered templates, so legacy text matching cannot override them."""


def preserve_template_text(fn):
    @wraps(fn)
    async def wrapped(*args, **kwargs):
        selected = any(isinstance(v, DeliveryTemplateText) for v in (*args, *kwargs.values()))
        token = FIXED_DELIVERY_TEXT.set(FIXED_DELIVERY_TEXT.get() or selected)
        try:
            return await fn(*args, **kwargs)
        finally:
            FIXED_DELIVERY_TEXT.reset(token)
    return wrapped


class TemplateHTML(HTMLParser):
    allowed = {'b', 'strong', 'i', 'em', 'u', 'ins', 's', 'strike', 'del', 'code', 'pre', 'blockquote'}
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.stack = []
    def handle_starttag(self, tag, attrs):
        if tag not in self.allowed or attrs:
            raise ValueError('فقط تگ‌های ساده b، i، u، s، code، pre و blockquote بدون ویژگی مجاز هستند.')
        self.stack.append(tag)
    def handle_endtag(self, tag):
        if not self.stack or self.stack.pop() != tag:
            raise ValueError('تگ‌های قالب به‌درستی بسته نشده‌اند.')
    def handle_startendtag(self, tag, attrs):
        raise ValueError('تگ خودبسته در قالب پشتیبانی نمی‌شود.')
    def handle_comment(self, data):
        raise ValueError('کامنت HTML در قالب مجاز نیست.')
    def handle_decl(self, decl):
        raise ValueError('اعلان HTML در قالب مجاز نیست.')
    def unknown_decl(self, decl):
        raise ValueError('اعلان HTML در قالب مجاز نیست.')
    def handle_pi(self, data):
        raise ValueError('دستور پردازشی در قالب مجاز نیست.')
    def handle_data(self, data):
        if '<' in data:
            raise ValueError('علامت < را به صورت &lt; وارد کنید یا تگ HTML معتبر بنویسید.')
    def handle_entityref(self, name):
        if name not in {'amp', 'lt', 'gt', 'quot'}:
            raise ValueError('برای نویسه ویژه از amp، lt، gt، quot یا کد عددی HTML استفاده کنید.')
    def handle_charref(self, name):
        try:
            value = int(name[1:], 16) if name.lower().startswith('x') else int(name)
            if not 0 < value <= 0x10ffff or 0xd800 <= value <= 0xdfff:
                raise ValueError()
        except ValueError as exc:
            raise ValueError('کد نویسه HTML معتبر نیست.') from exc


def validate_text(text: str) -> str:
    if not isinstance(text, str) or not text.strip() or len(text) > 3500 or re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', text):
        raise ValueError('متن قالب باید بین ۱ تا ۳۵۰۰ کاراکتر باشد.')
    try:
        for _, field, spec, conversion in Formatter().parse(text):
            if field is not None and (field not in FIELDS or spec or conversion):
                raise ValueError('متغیر قالب معتبر نیست؛ فقط از متغیرهای معرفی‌شده استفاده کنید.')
    except ValueError as exc:
        raise ValueError('متغیرها و آکولادهای قالب را بررسی کنید: ' + str(exc)) from exc
    parser = TemplateHTML(); parser.feed(text); parser.close()
    if parser.stack:
        raise ValueError('تگ‌های قالب به‌درستی بسته نشده‌اند.')
    return text.strip()


def normalize_config(raw) -> dict:
    if not isinstance(raw, dict) or not isinstance(raw.get('templates', []), list):
        raise ValueError('فهرست قالب‌ها معتبر نیست.')
    if len(raw.get('templates', [])) > 30:
        raise ValueError('حداکثر ۳۰ قالب متنی قابل ثبت است.')
    templates = []; ids = {'simple', 'legacy'}
    for row in raw.get('templates', []):
        if not isinstance(row, dict):
            raise ValueError('اطلاعات قالب معتبر نیست.')
        ident = row.get('id', ''); name = row.get('name', '')
        if not isinstance(ident, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', ident) or ident in ids:
            raise ValueError('شناسه قالب نامعتبر یا تکراری است.')
        if not isinstance(name, str) or not name.strip() or len(name) > 80:
            raise ValueError('نام قالب باید بین ۱ تا ۸۰ کاراکتر باشد.')
        ids.add(ident)
        templates.append({'id': ident, 'name': name.strip(), 'text': validate_text(row.get('text', ''))})
    active = raw.get('active', 'simple')
    if not isinstance(active, str) or active not in ids:
        raise ValueError('قالب انتخاب‌شده موجود نیست؛ ابتدا یک قالب دیگر انتخاب کنید.')
    return {'active': active, 'templates': templates}


async def load_config(session=None) -> dict:
    if session is None:
        from app.database.session import SessionLocal
        async with SessionLocal() as db:
            return await load_config(db)
    row = await session.get(Setting, SETTING_KEY)
    if not row or not row.value:
        return {'active': 'simple', 'templates': []}
    return normalize_config(json.loads(row.value))


def number(value) -> str:
    try:
        n = max(0, float(value or 0))
        return f'{n:g}'
    except (TypeError, ValueError):
        return '0'


def render_template(text: str, *, username, title, volume_gb, duration_days, sub_link, server_type='xui',
                    password=None, l2tp_server=None, l2tp_ipsec_secret=None, **_) -> DeliveryTemplateText:
    text = validate_text(text)
    values = {key: escape(str(value or '')) for key, value in dict(username=username, title=title, sub_link=sub_link,
        server_type=server_type, password=password, l2tp_server=l2tp_server, l2tp_ipsec_secret=l2tp_ipsec_secret).items()}
    values.update(volume_gb=number(volume_gb), duration_days=number(duration_days))
    values['traffic'] = f'{number(volume_gb)} گیگابایت' if number(volume_gb) != '0' else 'نامحدود'
    values['duration'] = f'{number(duration_days)} روز' if number(duration_days) != '0' else 'بدون انقضا'
    credentials = ''
    if server_type == 'mikrotik':
        for key, label in [('password', 'رمز عبور'), ('l2tp_server', 'سرور اتصال'), ('l2tp_ipsec_secret', 'IPsec Secret')]:
            if values[key]:
                credentials += f'\n{label}: <code>{values[key]}</code>'
    values['credentials'] = credentials
    values['subscription_line'] = f'\n🔗 لینک ساب‌اسکریپشن:\n<code>{values["sub_link"]}</code>' if sub_link else ''
    result = text.format_map(values).strip()
    # Even a manually written template must not accidentally drop access data.
    from app.bot.config_delivery import plain_html
    plain = plain_html(result)
    if sub_link and str(sub_link) not in plain:
        result += '\n' + values['subscription_line']
    if server_type == 'mikrotik' and password and str(password) not in plain:
        result += '\n' + credentials
    return DeliveryTemplateText(result)


async def selected_caption(**values) -> str | None:
    if values.get('is_test'):
        return None  # Trial messaging remains separate from purchased services.
    try:
        config = await load_config()
    except Exception:
        log.warning('Could not load delivery template; using simple preset', exc_info=True)
        config = {'active': 'simple', 'templates': []}
    if config['active'] == 'legacy':
        return None
    text = SIMPLE_TEXT if config['active'] == 'simple' else next(row['text'] for row in config['templates'] if row['id'] == config['active'])
    return render_template(text, **values)
