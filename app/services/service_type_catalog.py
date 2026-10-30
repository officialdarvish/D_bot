from __future__ import annotations

from typing import Iterable

VALID_SERVICE_PROVIDERS = {'xui', 'pasarguard', 'mikrotik'}
V2RAY_SERVICE_MODE = 'v2ray'  # Public catalogue: X-UI/Sanaei + PasarGuard


def normalize_service_provider(value: str | None) -> str:
    raw = (value or '').strip().lower()
    if raw in {'xui', 'x-ui', '3x-ui', '3xui', 'sanaei', 'v2ray', 'vless', 'vmess'}:
        return 'xui'
    if raw in {'pasarguard', 'pasar guard', 'pasar_guard', 'پاسارگارد', 'پاسار گارد'}:
        return 'pasarguard'
    if raw in {'mikrotik', 'microtik', 'openvpn', 'l2tp', 'openvpn-l2tp', 'routeros', 'میکروتیک'}:
        return 'mikrotik'
    return ''



def normalize_service_type_mode(value: str | None) -> str:
    """Service Types can group V2Ray-compatible *providers*, unlike Servers.

    Never treat this value as a concrete backend provider while provisioning.
    """
    raw = str(value or '').strip().lower()
    if raw in ('v2ray', 'xui+pasarguard', 'xui_pasarguard', 'v2ray-mixed'):
        return V2RAY_SERVICE_MODE
    return normalize_service_provider(raw)


def provider_members_for_service_type(mode: str | None) -> set[str]:
    mode = normalize_service_type_mode(mode)
    return {'xui', 'pasarguard'} if mode == V2RAY_SERVICE_MODE else ({mode} if mode else set())


def public_service_type_provider(
    *, slug: str, label: str, configured: str | None,
    available_providers: Iterable[str] | None = None,
    has_dedicated_pasarguard_type: bool = False,
) -> str:
    """Make legacy X-UI Service Types able to display PasarGuard categories.

    Existing installations frequently have one generic 'V2Ray' Service Type,
    originally mapped to X-UI. Once a public PasarGuard category is linked,
    leaving its X-UI-only filter in place hides the category. Auto-combine both
    backends when there is no separately configured PasarGuard service type.
    A dedicated provider mapping still keeps independent services separate,
    and admins may explicitly select the combined V2Ray mode at any time.
    """
    manual = normalize_service_type_mode(configured)
    if manual == V2RAY_SERVICE_MODE:
        return V2RAY_SERVICE_MODE
    base = resolve_service_provider(
        slug=slug, label=label,
        configured=manual if manual else None,
        available_providers=available_providers,
    )
    available = {normalize_service_provider(p) for p in (available_providers or [])}
    if base == 'xui' and 'pasarguard' in available and not has_dedicated_pasarguard_type:
        return V2RAY_SERVICE_MODE
    return base

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
    provider = normalize_service_type_mode(provider)
    return {
        'v2ray': 'V2Ray (Sanaei / 3x-ui + PasarGuard)',
        'xui': 'X-UI / 3x-ui',
        'pasarguard': 'PasarGuard',
        'mikrotik': 'MikroTik / OpenVPN / L2TP',
    }.get(provider, 'Auto')
