from html import escape
import asyncio
import time
from sqlalchemy import select
from app.database.models import Setting
from app.database.session import SessionLocal

WELCOME_TEXT_DEFAULT = '''👋 به {bot_name} خوش آمدید

{description}

🆘 پشتیبانی: {support_username}

برای ادامه، یکی از دکمه‌های زیر را انتخاب کنید.'''

RULES_TEXT_DEFAULT = '''Service Rules ⚠️

• Service stability can be affected by internet outages, political restrictions, routing issues, or provider disruptions.
• Support hours and payment approvals may depend on admin availability.
• Use only recommended clients/apps for best compatibility.
• Abuse, spam, or unauthorized sharing may cause service limitation.

By tapping the button below, you confirm that you have read and accepted these rules.'''

DEFAULT_SETTINGS = {
    'welcome_text': WELCOME_TEXT_DEFAULT,
    'bot_enabled': '1',
    'test_account_enabled': '1',
    'test_account_button_visible': '1',
    'test_account_volume_gb': '1',
    'test_account_duration_days': '1',
    'test_account_server_id': '',
    'test_account_inbound_ids': '',
    'channel_url': '',
    'force_join_enabled': '0',
    'rules_enabled': '0',
    'backup_interval_minutes': '1440',
    'backup_sender_mode': 'current',
    'backup_schedule_enabled': '1',

    'service_type_v2ray_enabled': '1',
    'service_type_v2ray_label': 'V2Ray',
    'service_type_openvpn_enabled': '1',
    'service_type_openvpn_label': 'OpenVPN - L2TP',
    'rules_text': RULES_TEXT_DEFAULT,
    'plan_order_public': '',
    'plan_order_reseller': '',
}

# Bot handlers often need 4-8 independent settings for one screen. Loading a
# one-second snapshot turns those serial database round-trips into a single
# query while keeping admin changes effectively immediate.
_SETTINGS_CACHE: dict[str, str] = {}
_SETTINGS_CACHE_UNTIL: float = 0.0
_SETTINGS_CACHE_LOCK = asyncio.Lock()
_SETTINGS_CACHE_TTL_SECONDS = 1.0


def invalidate_settings_cache() -> None:
    global _SETTINGS_CACHE_UNTIL
    _SETTINGS_CACHE.clear()
    _SETTINGS_CACHE_UNTIL = 0.0


async def _settings_snapshot() -> dict[str, str]:
    global _SETTINGS_CACHE, _SETTINGS_CACHE_UNTIL
    now = time.monotonic()
    if _SETTINGS_CACHE_UNTIL > now:
        return _SETTINGS_CACHE
    async with _SETTINGS_CACHE_LOCK:
        now = time.monotonic()
        if _SETTINGS_CACHE_UNTIL <= now:
            async with SessionLocal() as session:
                rows = (await session.execute(select(Setting))).scalars().all()
            _SETTINGS_CACHE = {str(row.key): str(row.value or '') for row in rows}
            _SETTINGS_CACHE_UNTIL = time.monotonic() + _SETTINGS_CACHE_TTL_SECONDS
    return _SETTINGS_CACHE


async def seed_default_settings() -> None:
    async with SessionLocal() as session:
        for key, value in DEFAULT_SETTINGS.items():
            existing = await session.get(Setting, key)
            if existing is None:
                session.add(Setting(key=key, value=value))
        await session.commit()
    invalidate_settings_cache()


async def get_setting_value(key: str, default: str = '') -> str:
    values = await _settings_snapshot()
    value = values.get(key, default)
    if key in {'welcome_text', 'rules_text'}:
        replacements = {
            '{bot_name}': escape(values.get('bot_name') or 'D BOT', quote=False),
            '{support_username}': escape(values.get('support_username') or '@support', quote=False),
            '{description}': escape(values.get('admin_description') or 'VPN management bot', quote=False),
        }
        for token, replacement in replacements.items():
            value = str(value or '').replace(token, replacement)
    return value


async def set_setting_value(key: str, value: str) -> None:
    async with SessionLocal() as session:
        row = await session.get(Setting, key)
        if row:
            row.value = value
        else:
            session.add(Setting(key=key, value=value))
        await session.commit()
    invalidate_settings_cache()
