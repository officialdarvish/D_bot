"""Validation shared by the web API and the standalone VPS domain tool."""
import ipaddress
import re
from urllib.parse import urlsplit

_HOST = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+')


def normalize_domain(value):
    raw = value.strip().lower()
    parsed = urlsplit(raw if '://' in raw else '//' + raw)
    domain = (parsed.hostname or '').rstrip('.')
    if (any(char.isspace() for char in raw) or parsed.scheme not in {'', 'http', 'https'} or parsed.netloc.rstrip('.') != domain
            or parsed.path not in {'', '/'} or parsed.query or parsed.fragment
            or len(domain) > 253 or not _HOST.fullmatch(domain)):
        raise ValueError('Enter a valid domain without a port or path / دامنهٔ معتبر را بدون پورت و مسیر وارد کنید')
    try:
        ipaddress.ip_address(domain)
    except ValueError:
        return domain
    raise ValueError('Enter a DNS domain, not an IP address / نام دامنه را به‌جای آدرس IP وارد کنید')
