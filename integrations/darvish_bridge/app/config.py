import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    bot_token: str
    admin_ids: frozenset[int]
    app_secret: str
    public_base_url: str
    webhook_allowed_hosts: frozenset[str]
    settlement_cycle_hours: int
    allow_digital_manual_receipts: bool = False

    @classmethod
    def from_env(cls):
        admins = frozenset(int(x.strip()) for x in os.getenv("ADMIN_TELEGRAM_IDS", "").split(",") if x.strip())
        return cls(
            allow_digital_manual_receipts=os.getenv('ALLOW_DIGITAL_MANUAL_RECEIPTS','0')=='1',
            database_url=os.getenv("DATABASE_URL", "sqlite:///./darvish.sqlite3"),
            bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            admin_ids=admins,
            app_secret=os.getenv("APP_SECRET", "local-development-only-change-in-production"),
            public_base_url=os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/"),
            webhook_allowed_hosts=frozenset(x.strip().lower() for x in os.getenv("WEBHOOK_ALLOWED_HOSTS", "").split(",") if x.strip()),
            settlement_cycle_hours=int(os.getenv("SETTLEMENT_CYCLE_HOURS", "24")),
        )


settings = Settings.from_env()

# Explicit minimal-unit scales. No floating point for financial amounts.
CURRENCY_SCALE = {"USDT": 6, "TON": 9, "USD": 2, "EUR": 2, "UNIT": 2}


def validate_runtime_secrets():
    s = settings
    if not s.bot_token or s.bot_token.startswith('PUT_'):
        raise RuntimeError('TELEGRAM_BOT_TOKEN must be configured')
    if not s.admin_ids:
        raise RuntimeError('ADMIN_TELEGRAM_IDS must be configured')
    if (len(s.app_secret) < 32 or s.app_secret.startswith(('GENERATE_', 'local-development'))):
        raise RuntimeError('APP_SECRET must be replaced with a strong random secret')
    if s.settlement_cycle_hours <= 0 or s.settlement_cycle_hours > 24 * 30:
        raise RuntimeError('SETTLEMENT_CYCLE_HOURS must be between 1 and 720')
