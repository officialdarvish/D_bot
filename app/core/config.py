from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')
    BOT_TOKEN: str
    # Full-access owners. Kept for backward compatibility with older .env files.
    ADMIN_IDS: str = ''
    OWNER_IDS: str = ''
    # Limited seller/admin Telegram IDs. Sellers do not get management access.
    SELLER_IDS: str = ''
    DATABASE_URL: str
    REDIS_URL: str = 'redis://redis:6379/0'
    API_HOST: str = '0.0.0.0'
    API_PORT: int = 8000
    FERNET_KEY: str | None = None
    DEFAULT_CHANNEL_URL: str = 'https://t.me/example'
    PAYG_MIN_BALANCE_IRT: int = 300_000
    PAYG_SCAN_MINUTES: int = 60
    TZ: str = 'Asia/Tehran'
    NOWPAYMENTS_API_KEY: str = ''
    NOWPAYMENTS_IPN_SECRET: str = ''
    NOWPAYMENTS_ENABLED: bool = False
    NOWPAYMENTS_PAY_CURRENCY: str = 'trx'
    NOWPAYMENTS_PRICE_CURRENCY: str = 'usd'
    NOWPAYMENTS_API_URL: str = 'https://api.nowpayments.io/v1'
    NOWPAYMENTS_IPN_CALLBACK_URL: str = ''
    SERVER_SYNC_SECONDS: int = 5
    WEB_ADMIN_USERNAME: str = 'admin'
    WEB_ADMIN_PASSWORD: str = ''
    ADMIN_MAX_LOGIN_ATTEMPTS: int = 8
    ADMIN_LOGIN_LOCK_SECONDS: int = 900
    XUI_VERIFY_TLS: bool = True
    XUI_CA_BUNDLE: str = ''
    BACKUP_MAX_UPLOAD_BYTES: int = 5_242_880
    BACKUP_REQUIRE_SIGNATURE: bool = True
    BACKUP_SIGNING_SECRET: str = ''
    DBOT_ALLOW_DOCKER_RESTART: bool = False


    @staticmethod
    def _parse_ids(raw: str) -> list[int]:
        return [int(x.strip()) for x in (raw or '').split(',') if x.strip().isdigit()]

    @property
    def owner_ids(self) -> list[int]:
        # OWNER_IDS overrides ADMIN_IDS when present; ADMIN_IDS remains legacy owner list.
        return self._parse_ids(self.OWNER_IDS or self.ADMIN_IDS)

    @property
    def seller_ids(self) -> list[int]:
        return self._parse_ids(self.SELLER_IDS)

    @property
    def admin_ids(self) -> list[int]:
        # Backward-compatible alias used by older handlers: full-access owners only.
        return self.owner_ids

    @property
    def staff_ids(self) -> list[int]:
        return sorted(set(self.owner_ids + self.seller_ids))

@lru_cache
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
