import base64, hashlib
from cryptography.fernet import Fernet, InvalidToken
from app.core.config import settings

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
        # A valid Fernet token normally starts with gAAAAA. If it does, the
        # encryption key changed and the original password cannot be recovered.
        if raw.startswith('gAAAAA'):
            raise RuntimeError('رمز پنل سرور قابل خواندن نیست. لطفاً از بخش مدیریت سرورها، رمز همین سرور را دوباره ذخیره کنید. اگر FERNET_KEY یا BOT_TOKEN را عوض کرده‌اید، همان مقدار قبلی را برگردانید.')
        # Backward compatibility for mistakenly plain-stored passwords.
        return raw
