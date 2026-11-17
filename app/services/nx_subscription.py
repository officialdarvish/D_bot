"""NX public subscription format URLs, derived from the API's authoritative subUrl."""
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

FORMATS = {
    'v2ray': 'V2Ray / Base64',
    'clash': 'Clash / mihomo YAML',
    'singbox': 'sing-box JSON',
    'xray': 'Xray JSON',
    'plain': 'Plain share links',
}


def parse_formats(value=None):
    if value is None:
        return ['v2ray']
    rows = value.split(',') if isinstance(value, str) else value
    if not isinstance(rows, (list, tuple)):
        raise ValueError('Invalid NX subscription formats / فرمت اشتراک NX نامعتبر است')
    selected = list(dict.fromkeys(str(x).strip() for x in rows if str(x).strip()))
    if not selected or any(x not in FORMATS for x in selected):
        raise ValueError('Choose at least one valid NX subscription format / حداقل یک فرمت معتبر اشتراک NX انتخاب کنید')
    return selected


def subscription_links(server, link):
    if not link:
        return []
    parts = urlsplit(str(link).strip())
    if parts.scheme not in {'http', 'https'} or not parts.hostname or parts.username or parts.password:
        raise ValueError('NX API returned an invalid subscription URL')
    path = parts.path.rstrip('/')
    segments = path.split('/')
    if len([x for x in segments if x]) >= 3 and segments[-1] in {*FORMATS, 'page', 'info'}:
        path = path.rsplit('/', 1)[0]
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key != 'format']
    return [
        {'format': fmt, 'label': FORMATS[fmt], 'url': urlunsplit((parts.scheme, parts.netloc, path, urlencode(query + [('format', fmt)]), parts.fragment))}
        for fmt in parse_formats((server.meta or {}).get('nx_subscription_formats'))
    ]
