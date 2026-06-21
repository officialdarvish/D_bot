import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.core.config import settings
from app.core.logging import setup_logging
from app.database.base import Base
from app.database.session import engine
from app.database import models
from app.database.defaults import seed_default_settings
from app.jobs.pay_as_you_go_scanner import scan_payg_usage, scan_service_alerts
from app.jobs.anti_sharing_scanner import scan_anti_sharing
from app.bot.handlers import start
from app.bot.handlers.admin import admin_panel, servers, categories, plans, wallet, anti_sharing, settings as admin_settings, resellers as admin_resellers
from app.bot.handlers.public import account, my_services, tickets, buy, test_account, reseller

async def create_tables():
    logger = logging.getLogger(__name__)

    async def safe_upgrade(conn, sql: str) -> None:
        try:
            await conn.exec_driver_sql(sql)
        except Exception as exc:
            # SQLite/PostgreSQL differ on a few ALTER syntaxes; keep startup alive but log the reason.
            logger.warning("Database upgrade skipped: %s | %s", sql, exc)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Safe lightweight upgrades for older installed versions.
        upgrades = [
            'ALTER TABLE server_categories ADD COLUMN IF NOT EXISTS server_id INTEGER',
            'ALTER TABLE payment_cards ADD COLUMN IF NOT EXISTS server_id INTEGER',
            'ALTER TABLE client_services ADD COLUMN IF NOT EXISTS notify_20m_sent BOOLEAN DEFAULT FALSE',
            'ALTER TABLE client_services ADD COLUMN IF NOT EXISTS reseller_id INTEGER NULL',
            'ALTER TABLE client_services ADD COLUMN IF NOT EXISTS reseller_reserved_bytes BIGINT DEFAULT 0',
            'ALTER TABLE client_services ADD COLUMN IF NOT EXISTS notify_2h_sent BOOLEAN DEFAULT FALSE',
            'ALTER TABLE client_services ADD COLUMN IF NOT EXISTS notify_24h_sent BOOLEAN DEFAULT FALSE',
            'ALTER TABLE client_services ADD COLUMN IF NOT EXISTS notify_100mb_sent BOOLEAN DEFAULT FALSE',
            'ALTER TABLE client_services ADD COLUMN IF NOT EXISTS notify_1gb_sent BOOLEAN DEFAULT FALSE',
            'ALTER TABLE client_services ADD COLUMN IF NOT EXISTS xui_uuid VARCHAR(80)',
            'ALTER TABLE client_services ADD COLUMN IF NOT EXISTS ip_limit INTEGER DEFAULT 0',
            'ALTER TABLE client_services ADD COLUMN IF NOT EXISTS anti_share_violation_count INTEGER DEFAULT 0',
            'ALTER TABLE client_services ADD COLUMN IF NOT EXISTS anti_share_banned_until TIMESTAMP NULL',
            'ALTER TABLE client_services ADD COLUMN IF NOT EXISTS anti_share_banned_permanent BOOLEAN DEFAULT FALSE',
            'ALTER TABLE client_services ADD COLUMN IF NOT EXISTS anti_share_last_alert_at TIMESTAMP NULL',
            "ALTER TABLE client_services ADD COLUMN IF NOT EXISTS anti_share_last_ips JSON DEFAULT '[]'",
            'ALTER TABLE plans ADD COLUMN IF NOT EXISTS is_unlimited BOOLEAN DEFAULT FALSE',
            'ALTER TABLE plans ADD COLUMN IF NOT EXISTS anti_sharing_enabled BOOLEAN DEFAULT TRUE',
            'UPDATE plans SET is_unlimited = TRUE WHERE COALESCE(is_payg, FALSE) = FALSE AND COALESCE(volume_gb, 0) <= 0',
            'UPDATE plans SET anti_sharing_enabled = TRUE WHERE anti_sharing_enabled IS NULL',
            'ALTER TABLE servers ADD COLUMN IF NOT EXISTS subscription_url TEXT',
            'ALTER TABLE discount_codes ADD COLUMN IF NOT EXISTS per_user_limit INTEGER DEFAULT 1',
            'ALTER TABLE orders ADD COLUMN IF NOT EXISTS external_payment_id VARCHAR(120)',
            'ALTER TABLE orders ADD COLUMN IF NOT EXISTS external_invoice_url TEXT',
            'ALTER TABLE users ADD COLUMN IF NOT EXISTS wallet_openvpn_balance BIGINT DEFAULT 0',
            'ALTER TABLE users ADD COLUMN IF NOT EXISTS wallet_v2ray_balance BIGINT DEFAULT 0',
            'ALTER TABLE orders ALTER COLUMN service_id DROP NOT NULL',
            'ALTER TABLE test_account_usages ALTER COLUMN service_id DROP NOT NULL',
            'ALTER TABLE anti_sharing_violations DROP CONSTRAINT IF EXISTS anti_sharing_violations_service_id_fkey',
            "ALTER TABLE anti_sharing_violations ADD CONSTRAINT anti_sharing_violations_service_id_fkey FOREIGN KEY (service_id) REFERENCES client_services(id) ON DELETE CASCADE",
            'ALTER TABLE payg_usage_logs DROP CONSTRAINT IF EXISTS payg_usage_logs_service_id_fkey',
            "ALTER TABLE payg_usage_logs ADD CONSTRAINT payg_usage_logs_service_id_fkey FOREIGN KEY (service_id) REFERENCES client_services(id) ON DELETE CASCADE",
            'ALTER TABLE orders DROP CONSTRAINT IF EXISTS orders_service_id_fkey',
            "ALTER TABLE orders ADD CONSTRAINT orders_service_id_fkey FOREIGN KEY (service_id) REFERENCES client_services(id) ON DELETE SET NULL",
            'ALTER TABLE test_account_usages DROP CONSTRAINT IF EXISTS test_account_usages_service_id_fkey',
            "ALTER TABLE test_account_usages ADD CONSTRAINT test_account_usages_service_id_fkey FOREIGN KEY (service_id) REFERENCES client_services(id) ON DELETE SET NULL",
        ]
        for sql in upgrades:
            await safe_upgrade(conn, sql)

        # PostgreSQL restores/backups that insert explicit IDs can leave SERIAL/IDENTITY
        # sequences behind MAX(id). When that happens, new /start users fail with
        # duplicate users_pkey even though telegram_id is new. Repair critical sequences
        # on every startup; it is safe and idempotent.
        sequence_repairs = [
            ("users", "id"),
            ("client_services", "id"),
            ("orders", "id"),
            ("reseller_accounts", "id"),
            ("reseller_packages", "id"),
            ("reseller_topup_requests", "id"),
            ("servers", "id"),
            ("plans", "id"),
            ("payment_cards", "id"),
            ("discount_usages", "id"),
        ]
        for table_name, column_name in sequence_repairs:
            await safe_upgrade(
                conn,
                f"SELECT setval(pg_get_serial_sequence('{table_name}', '{column_name}'), "
                f"GREATEST(COALESCE((SELECT MAX({column_name}) FROM {table_name}), 0) + 1, 1), false)",
            )

async def main():
    setup_logging()
    await create_tables()
    await seed_default_settings()
    redis = Redis.from_url(settings.REDIS_URL)
    bot = Bot(token=settings.BOT_TOKEN)
    dp = Dispatcher(storage=RedisStorage(redis=redis))
    for r in [
        start.router,
        admin_panel.router, servers.router, categories.router, plans.router, wallet.router, anti_sharing.router, admin_settings.router, admin_resellers.router,
        account.router, my_services.router, tickets.router, buy.router, test_account.router, reseller.router,
    ]:
        dp.include_router(r)
    scheduler = AsyncIOScheduler(timezone=settings.TZ)
    scheduler.add_job(scan_payg_usage, 'interval', minutes=settings.PAYG_SCAN_MINUTES, id='payg_scanner', replace_existing=True)
    scheduler.add_job(scan_service_alerts, 'interval', minutes=20, args=[bot], id='service_alerts', replace_existing=True)
    scheduler.add_job(scan_anti_sharing, 'interval', minutes=1, args=[bot], id='anti_sharing_scanner', replace_existing=True)
    scheduler.start()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
