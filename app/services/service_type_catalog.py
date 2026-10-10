from __future__ import annotations

from typing import Iterable

VALID_SERVICE_PROVIDERS = {'xui', 'pasarguard', 'mikrotik'}


def normalize_service_provider(value: str | None) -> str:
    raw = (value or '').strip().lower()
    if raw in {'xui', 'x-ui', '3x-ui', '3xui', 'sanaei', 'v2ray', 'vless', 'vmess'}:
        return 'xui'
    if raw in {'pasarguard', 'pasar guard', 'pasar_guard', 'پاسارگارد', 'پاسار گارد'}:
        return 'pasarguard'
    if raw in {'mikrotik', 'microtik', 'openvpn', 'l2tp', 'openvpn-l2tp', 'routeros', 'میکروتیک'}:
        return 'mikrotik'
    return ''


def infer_service_provider(text: str | None) -> str:
    raw = (text or '').strip().lower()
    if any(token in raw for token in ('pasarguard', 'pasar guard', 'pasar_guard', 'پاسارگارد', 'پاسار گارد')):
        return 'pasarguard'
    if any(token in raw for token in ('mikrotik', 'microtik', 'openvpn', 'l2tp', 'routeros', 'میکروتیک', 'اوپن')):
        return 'mikrotik'
    return 'xui'


def service_type_provider_key(service_key: str) -> str:
    prefix = 'service_type:custom:'
    key = str(service_key or '').strip()
    slug = key[len(prefix):] if key.startswith(prefix) else key
    return f'service_type_provider:{slug}'


def resolve_service_provider(
    *,
    slug: str,
    label: str,
    configured: str | None = None,
    available_providers: Iterable[str] | None = None,
) -> str:
    """Resolve the backend provider for a user-facing service type.

    Explicit admin mapping always wins. Older service types without a mapping keep
    their historical name-based inference, but when that inference has no sellable
    inventory and exactly one provider does, use that provider automatically. This
    keeps existing installations working after adding PasarGuard or MikroTik plans.
    """
    explicit = normalize_service_provider(configured)
    if explicit:
        return explicit

    inferred = infer_service_provider(f'{slug} {label}')
    available = {
        normalized
        for item in (available_providers or [])
        if (normalized := normalize_service_provider(str(item)))
    }
    if not available or inferred in available:
        return inferred
    if len(available) == 1:
        return next(iter(available))
    return inferred


def service_provider_label(provider: str | None) -> str:
    provider = normalize_service_provider(provider)
    return {
        'xui': 'X-UI / 3x-ui',
        'pasarguard': 'PasarGuard',
        'mikrotik': 'MikroTik / OpenVPN / L2TP',
    }.get(provider, 'Auto')
