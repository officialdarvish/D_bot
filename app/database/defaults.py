from sqlalchemy import select
from app.database.models import Setting
from app.database.session import SessionLocal

WELCOME_TEXT_DEFAULT = '''چطوری ستون؟😎 به ربات ما خوش اومدی 🤘🏻

اینجا می‌تونی سرویس بخری، کانفیگ‌هات رو مدیریت کنی، مشخصات کانفیگ رو استعلام بگیری و با پشتیبانی در ارتباط باشی.

🚪 /start'''

RULES_TEXT_DEFAULT = '''⚠️ قوانین سرویس

• در صورت جنگ، مشکلات سیاسی، قطعی یا اختلال اینترنت، هیچ تضمینی برای متصل ماندن سرویس‌ها وجود ندارد و زمان از دست رفته به سرویس اضافه نخواهد شد.

• ضمانت اتصال تنها برای حداقل ۱ اینترنت خانگی و ۱ اپراتور همراه می‌باشد.

• در صورت عدم اتصال اپراتور یا اینترنت شما، تهیه اینترنت یا سیم‌کارت جایگزین بر عهده کاربر است.

• در اختلالات منطقه‌ای، شهری یا استانی هیچ تضمینی برای دسترسی به سرویس وجود ندارد.

• هیچ تضمینی برای پایداری دائمی سرویس‌ها وجود ندارد؛ مگر اینکه در توضیحات سرویس هنگام خرید ذکر شده باشد.

• تنها برنامه مورد تأیید برای استفاده از سرویس‌ها Happ می‌باشد. در صورت استفاده از سایر برنامه‌ها، هرگونه اختلال یا مشکل احتمالی بر عهده کاربر خواهد بود.

• ساعات پاسخگویی و پشتیبانی از ۹ صبح تا ۱۲ شب می‌باشد. خارج از این بازه زمانی، تأیید خریدها و پاسخ به تیکت‌ها و پیام‌ها در اولین ساعت کاری بعدی انجام خواهد شد.

✅ با انتخاب گزینه «تأیید و موافقم»، تأیید می‌کنید که تمامی موارد فوق را مطالعه کرده و با آن‌ها موافق هستید.'''

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
