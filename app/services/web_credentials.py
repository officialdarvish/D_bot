from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import decrypt_text, encrypt_text, hash_password, is_password_hash, verify_password
from app.database.models import Setting

WEB_ADMIN_USERNAME_KEY = 'web_admin_username'
WEB_ADMIN_PASSWORD_HASH_KEY = 'web_admin_password'
WEB_ADMIN_PASSWORD_SECRET_KEY = 'web_admin_password_encrypted'
WEB_CREDENTIALS_UPDATED_AT_KEY = 'web_credentials_updated_at'
WEB_CREDENTIALS_UPDATED_BY_KEY = 'web_credentials_updated_by'

_USERNAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{2,63}$')


@dataclass(slots=True)
class WebCredentialsSnapshot:
    username: str
    password: str
    password_available: bool
    updated_at: str
    updated_by: str
    source: str


def validate_web_admin_username(value: str) -> str:
    username = (value or '').strip()
    if not _USERNAME_RE.fullmatch(username):
        raise ValueError('Username must be 3 to 64 characters and may contain letters, numbers, dot, dash and underscore.')
    return username


def validate_web_admin_password(value: str) -> str:
    password = value or ''
    if len(password) < 8:
        raise ValueError('Password must contain at least 8 characters.')
    if len(password) > 256:
        raise ValueError('Password is too long. Maximum length is 256 characters.')
    if '\n' in password or '\r' in password or '\x00' in password:
        raise ValueError('Password contains unsupported control characters.')
    return password


def _new_session():
    # Imported lazily so validators and unit tests do not initialize the database
    # engine merely by importing this module.
    from app.database.session import SessionLocal
    return SessionLocal()


async def _setting_value(session: AsyncSession, key: str, default: str = '') -> str:
    row = await session.get(Setting, key)
    return str(row.value or '') if row is not None else default


async def _put(session: AsyncSession, key: str, value: str) -> None:
    await session.merge(Setting(key=key, value=str(value or '')))


async def read_web_credentials(session: AsyncSession | None = None) -> WebCredentialsSnapshot:
    owns_session = session is None
    if session is None:
        session = _new_session()
    try:
        username = (await _setting_value(session, WEB_ADMIN_USERNAME_KEY, settings.WEB_ADMIN_USERNAME or 'admin')).strip()
        password_hash = await _setting_value(session, WEB_ADMIN_PASSWORD_HASH_KEY, settings.WEB_ADMIN_PASSWORD or '')
        encrypted = await _setting_value(session, WEB_ADMIN_PASSWORD_SECRET_KEY, '')
        updated_at = await _setting_value(session, WEB_CREDENTIALS_UPDATED_AT_KEY, '')
        updated_by = await _setting_value(session, WEB_CREDENTIALS_UPDATED_BY_KEY, '')

        password = ''
        source = 'database'
        if encrypted:
            try:
                password = decrypt_text(encrypted)
            except RuntimeError:
                password = ''
                source = 'database-secret-unreadable'
        elif password_hash and not is_password_hash(password_hash):
            # Legacy installations may still keep the active password as plaintext.
            password = password_hash
            source = 'legacy-database'
        else:
            env_password = settings.WEB_ADMIN_PASSWORD or ''
            # Only use the environment fallback when it is demonstrably the active password.
            if env_password and (not password_hash or verify_password(env_password, password_hash)):
                password = env_password
                source = 'environment-fallback'
            elif password_hash:
                source = 'hash-only'
            else:
                source = 'not-configured'

        return WebCredentialsSnapshot(
            username=username or 'admin',
            password=password,
            password_available=bool(password),
            updated_at=updated_at,
            updated_by=updated_by,
            source=source,
        )
    finally:
        if owns_session:
            await session.close()


async def save_web_credentials(
    *,
    username: str | None = None,
    password: str | None = None,
    updated_by: str = 'system',
    session: AsyncSession | None = None,
    commit: bool = True,
) -> WebCredentialsSnapshot:
    if username is None and password is None:
        return await read_web_credentials(session)

    clean_username = validate_web_admin_username(username) if username is not None else None
    clean_password = validate_web_admin_password(password) if password is not None else None

    owns_session = session is None
    if session is None:
        session = _new_session()
    try:
        if clean_username is not None:
            await _put(session, WEB_ADMIN_USERNAME_KEY, clean_username)
        if clean_password is not None:
            await _put(session, WEB_ADMIN_PASSWORD_HASH_KEY, hash_password(clean_password))
            await _put(session, WEB_ADMIN_PASSWORD_SECRET_KEY, encrypt_text(clean_password))
        await _put(session, WEB_CREDENTIALS_UPDATED_AT_KEY, datetime.now(timezone.utc).isoformat())
        await _put(session, WEB_CREDENTIALS_UPDATED_BY_KEY, (updated_by or 'system')[:96])
        if commit:
            await session.commit()
        else:
            await session.flush()
        return await read_web_credentials(session)
    except Exception:
        if owns_session:
            await session.rollback()
        raise
    finally:
        if owns_session:
            await session.close()


async def ensure_web_password_secret(
    *,
    username: str,
    password: str,
    updated_by: str = 'successful-login',
    session: AsyncSession | None = None,
) -> None:
    """Make a verified current password revealable without changing login behavior.

    This is called only after the password has already been successfully verified.
    It upgrades legacy/hash-only installs by adding an encrypted recoverable copy.
    """
    owns_session = session is None
    if session is None:
        session = _new_session()
    try:
        current_username = await _setting_value(session, WEB_ADMIN_USERNAME_KEY, '')
        encrypted = await _setting_value(session, WEB_ADMIN_PASSWORD_SECRET_KEY, '')
        needs_update = not encrypted
        if encrypted:
            try:
                needs_update = decrypt_text(encrypted) != password
            except RuntimeError:
                needs_update = True
        if needs_update or current_username != username:
            await save_web_credentials(
                username=username,
                password=password if needs_update else None,
                updated_by=updated_by,
                session=session,
                commit=False,
            )
            await session.commit()
    except Exception:
        if owns_session:
            await session.rollback()
        raise
    finally:
        if owns_session:
            await session.close()
