from __future__ import annotations

import re
import secrets
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.database.models import Setting

WEB_PATH_KEY = 'web_path'
_WEB_PATH_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{3,63}$')


def normalize_web_path(value: str) -> str:
    raw = (value or '').strip().strip('/')
    if not _WEB_PATH_RE.fullmatch(raw):
        raise ValueError('Web path must be 4 to 64 characters and may contain letters, numbers, dash and underscore.')
    return raw


def generate_web_path() -> str:
    # URL-safe, readable and difficult to guess. Keep it short enough to type.
    return 'dbot-' + secrets.token_urlsafe(9).replace('-', '').replace('_', '')[:12]


def _new_session():
    from app.database.session import SessionLocal
    return SessionLocal()


async def read_web_path(session: AsyncSession | None = None) -> str:
    owns_session = session is None
    if session is None:
        session = _new_session()
    try:
        row = await session.get(Setting, WEB_PATH_KEY)
        raw = str(row.value or '') if row is not None else str(getattr(settings, 'WEB_PATH', '') or '')
        if not raw:
            # Installer always writes WEB_PATH on new installs. This fallback keeps
            # upgraded installations reachable until the admin saves a path.
            return 'dbot'
        try:
            return normalize_web_path(raw)
        except ValueError:
            return 'dbot'
    finally:
        if owns_session:
            await session.close()


async def save_web_path(value: str, session: AsyncSession | None = None, commit: bool = True) -> str:
    clean = normalize_web_path(value)
    owns_session = session is None
    if session is None:
        session = _new_session()
    try:
        await session.merge(Setting(key=WEB_PATH_KEY, value=clean))
        if commit:
            await session.commit()
        else:
            await session.flush()
        return clean
    except Exception:
        if owns_session:
            await session.rollback()
        raise
    finally:
        if owns_session:
            await session.close()


@dataclass(slots=True)
class WebAccessSnapshot:
    web_path: str
    prefix: str
    login_path: str
    admin_path: str
    setup_path: str
    login_url: str


async def read_web_access(session: AsyncSession | None = None) -> WebAccessSnapshot:
    owns_session = session is None
    if session is None:
        session = _new_session()
    try:
        path = await read_web_path(session)
        prefix = '/' + path
        domain_row = await session.get(Setting, 'web_domain')
        db_domain = str(domain_row.value or '').strip() if domain_row else ''
        env_domain = str(getattr(settings, 'DOMAIN_NAME', '') or '').strip()
        public_base = str(getattr(settings, 'PUBLIC_BASE_URL', '') or '').strip().rstrip('/')
        domain = db_domain or env_domain
        https_enabled = bool(getattr(settings, 'ENABLE_HTTPS', True))
        http_port = int(getattr(settings, 'NGINX_HTTP_PORT', 80) or 80)
        https_port = int(getattr(settings, 'NGINX_HTTPS_PORT', 443) or 443)
        api_port = int(getattr(settings, 'API_PORT', 8000) or 8000)
        if db_domain or (domain and not public_base):
            scheme = 'https' if https_enabled else 'http'
            port = https_port if https_enabled else http_port
            suffix = '' if (scheme == 'https' and port == 443) or (scheme == 'http' and port == 80) else f':{port}'
            base = f'{scheme}://{domain}{suffix}'
        elif public_base:
            base = public_base
        elif domain:
            scheme = 'https' if https_enabled else 'http'
            base = f'{scheme}://{domain}'
        else:
            base = f'http://SERVER_IP:{api_port}'
        return WebAccessSnapshot(
            web_path=path,
            prefix=prefix,
            login_path=f'{prefix}/login',
            admin_path=f'{prefix}/admin',
            setup_path=f'{prefix}/setup',
            login_url=f'{base}{prefix}/login',
        )
    finally:
        if owns_session:
            await session.close()
