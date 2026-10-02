import base64, hashlib, hmac, secrets
from cryptography.fernet import Fernet, InvalidToken
from app.core.config import settings

try:
    import bcrypt
except Exception:  # pragma: no cover - dependency is pinned in requirements.txt
    bcrypt = None


def _key() -> bytes:
    if settings.FERNET_KEY:
        return settings.FERNET_KEY.encode()
    raw = hashlib.sha256(settings.BOT_TOKEN.encode()).digest()
    return base64.urlsafe_b64encode(raw)

fernet = Fernet(_key())


def encrypt_text(value: str) -> str:
    return fernet.encrypt(value.encode()).decode()


def decrypt_text(value: str) -> str:
    """Decrypt stored secrets.

    Older installs or broken reseller patches may have stored a plain password, while
    real Fernet values can become unreadable if FERNET_KEY/BOT_TOKEN changes.
    - Plain values are returned as-is.
    - Unreadable Fernet-looking values raise a clear error instead of leaking
      cryptography's InvalidToken to users.
    """
    raw = (value or '').strip()
    if not raw:
        return ''
    try:
        return fernet.decrypt(raw.encode()).decode()
    except InvalidToken:
        if raw.startswith('gAAAAA'):
            raise RuntimeError('رمز پنل سرور قابل خواندن نیست. لطفاً از بخش مدیریت سرورها، رمز همین سرور را دوباره ذخیره کنید. اگر FERNET_KEY یا BOT_TOKEN را عوض کرده‌اید، همان مقدار قبلی را برگردانید.')
        return raw


PASSWORD_HASH_PREFIX = 'bcrypt$'


def hash_password(password: str) -> str:
    """Return a bcrypt password hash with an explicit app prefix."""
    if bcrypt is None:
        # Fallback only for unusual local dev environments. Production Docker has bcrypt.
        salt = secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 310_000).hex()
        return f'pbkdf2_sha256$310000${salt}${digest}'
    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(rounds=12)).decode('utf-8')
    return PASSWORD_HASH_PREFIX + hashed


def is_password_hash(value: str | None) -> bool:
    raw = (value or '').strip()
    return raw.startswith(PASSWORD_HASH_PREFIX) or raw.startswith('$2a$') or raw.startswith('$2b$') or raw.startswith('pbkdf2_sha256$')


def verify_password(password: str, stored: str | None) -> bool:
    raw = (stored or '').strip()
    if not raw:
        return False
    candidate = (password or '').encode('utf-8')
    if raw.startswith(PASSWORD_HASH_PREFIX):
        raw_hash = raw[len(PASSWORD_HASH_PREFIX):]
        return bcrypt is not None and bcrypt.checkpw(candidate, raw_hash.encode('utf-8'))
    if raw.startswith('$2a$') or raw.startswith('$2b$'):
        return bcrypt is not None and bcrypt.checkpw(candidate, raw.encode('utf-8'))
    if raw.startswith('pbkdf2_sha256$'):
        try:
            _, rounds, salt, digest = raw.split('$', 3)
            calc = hashlib.pbkdf2_hmac('sha256', candidate, salt.encode(), int(rounds)).hex()
            return hmac.compare_digest(calc, digest)
        except Exception:
            return False
    # Legacy plaintext migration support. Callers should re-save as a hash after success.
    return hmac.compare_digest(password or '', raw)
