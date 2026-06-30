from sqlalchemy import select
from app.database.models import Setting
from app.database.session import SessionLocal

WELCOME_TEXT_DEFAULT = '''Welcome to D BOT 🚀

Use this bot to buy services, manage your configs, check service details, open tickets, and access reseller/referral features.

Tap a button below to continue.'''

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
    'payg_price_per_gb': '0',
    'channel_url': '',
    'anti_sharing_enabled': '1',
    'anti_sharing_default_ip_limit': '2',
    'anti_sharing_scan_minutes': '5',
    'anti_sharing_auto_ban_24h_after': '2',
    'anti_sharing_auto_ban_permanent_after': '3',

    'service_type_v2ray_enabled': '1',
    'service_type_v2ray_label': 'V2Ray',
    'service_type_openvpn_enabled': '1',
    'service_type_openvpn_label': 'OpenVPN - L2TP',
    'rules_text': RULES_TEXT_DEFAULT,
    'plan_order_public': '',
    'plan_order_reseller': '',
}

async def seed_default_settings() -> None:
    async with SessionLocal() as session:
        for key, value in DEFAULT_SETTINGS.items():
            existing = await session.get(Setting, key)
            if existing is None:
                session.add(Setting(key=key, value=value))
        await session.commit()

async def get_setting_value(key: str, default: str = '') -> str:
    async with SessionLocal() as session:
        row = await session.get(Setting, key)
        return row.value if row else default

async def set_setting_value(key: str, value: str) -> None:
    async with SessionLocal() as session:
        row = await session.get(Setting, key)
        if row:
            row.value = value
        else:
            session.add(Setting(key=key, value=value))
        await session.commit()
