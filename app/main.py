import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram import BaseMiddleware
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.executors.asyncio import AsyncIOExecutor
from app.core.config import settings
from app.core.logging import setup_logging
from app.database.base import Base
from app.database.session import engine
from app.database import models
from app.jobs.service_alerts import scan_service_alerts
from app.jobs.server_sync import sync_all_servers, sync_mikrotik_usage
from app.bot.handlers import start
from app.bot.handlers.admin import admin_panel, servers, categories, plans, wallet, settings as admin_settings, resellers as admin_resellers
from app.bot.handlers.public import account, my_services, tickets, buy, test_account, reseller
from app.bot.utils import get_ui_message_id
from app.bot.error_reporting import report_bot_error, show_generic_error


class UserSafeErrorMiddleware(BaseMiddleware):
    """Never expose technical exceptions to end users.

    Full tracebacks are sent only to configured owner/admin IDs.
    Users receive a fixed support message.
    """

    async def __call__(self, handler, event, data):
        try:
            return await handler(event, data)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            bot = data.get('bot') if isinstance(data, dict) else None
            try:
                await report_bot_error(bot, exc, context='Unhandled bot handler exception', event=event)
            except Exception:
                logging.getLogger(__name__).exception('Failed to report unhandled bot exception')
            try:
                await show_generic_error(event)
            except Exception:
                logging.getLogger(__name__).exception('Failed to show generic bot error')
            return None


class FreshCallbackOnlyMiddleware(BaseMiddleware):
    """Ignore inline buttons from old bot messages.

    Approval/receipt callbacks are allowed because they live on admin notification
    messages, not on the user's current UI page.
    """
    ALLOWED_PREFIXES = (
        # Home must work from every old document/photo/service message.
        # These callbacks deliberately open a fresh main-menu message and should
        # never be blocked by the stale-message guard.
        'home:main', 'profile:home', 'back:main',
        'order:approve:', 'order:reject:',
        'wallet_topup:approve:', 'wallet_topup:reject:',
        'resadmin:access_approve:', 'resadmin:access_reject:',
        'resadmin:req_approve:', 'resadmin:req_reject:', 'resadmin:req:',
        # Renewal reminders are proactive bot messages, not the user's current UI page.
        'svc:renew_menu:', 'reseller:renew:', 'reseller:users', 'menu:my_services',
    )

    async def __call__(self, handler, event, data):
        try:
            callback_data = event.data or ''
            if callback_data.startswith(self.ALLOWED_PREFIXES):
                return await handler(event, data)
            message = getattr(event, 'message', None)
            if message:
                active_mid = get_ui_message_id(message.chat.id)
                if active_mid and int(active_mid) != int(message.message_id):
                    try:
                        await event.answer('این پیام قدیمی است. لطفاً /start را بزنید تا ربات برای شما پیام جدید ارسال کند.', show_alert=False, cache_time=8)
                    except Exception:
                        pass
                    try:
                        await message.edit_reply_markup(reply_markup=None)
                    except Exception:
                        pass
                    return None
        except Exception:
            pass
        return await handler(event, data)


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
            "ALTER TABLE server_categories ADD COLUMN IF NOT EXISTS server_ids JSON DEFAULT '[]'",
            'ALTER TABLE server_categories ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE',
            'ALTER TABLE payment_cards ADD COLUMN IF NOT EXISTS server_id INTEGER',
            'ALTER TABLE client_services ADD COLUMN IF NOT EXISTS notify_20m_sent BOOLEAN DEFAULT FALSE',
            'ALTER TABLE client_services ADD COLUMN IF NOT EXISTS disabled_at TIMESTAMP NULL',
            'ALTER TABLE client_services ADD COLUMN IF NOT EXISTS disabled_reason VARCHAR(32)',
            'ALTER TABLE client_services ADD COLUMN IF NOT EXISTS disabled_notify_count INTEGER DEFAULT 0',
            'ALTER TABLE client_services ADD COLUMN IF NOT EXISTS disabled_last_notified_at TIMESTAMP NULL',
            'ALTER TABLE client_services ADD COLUMN IF NOT EXISTS reseller_id INTEGER NULL',
            'ALTER TABLE client_services ADD COLUMN IF NOT EXISTS reseller_reserved_bytes BIGINT DEFAULT 0',
            'ALTER TABLE client_services ADD COLUMN IF NOT EXISTS reseller_lifetime_used_bytes BIGINT DEFAULT 0',
            "WITH marker AS (INSERT INTO settings(key, value) VALUES ('reseller_inventory_model_v114_applied', '1') ON CONFLICT (key) DO NOTHING RETURNING key) UPDATE reseller_accounts SET total_bytes = GREATEST(COALESCE(total_bytes, 0) - COALESCE(reserved_bytes, 0), 0) WHERE EXISTS (SELECT 1 FROM marker)",
            'ALTER TABLE client_services ADD COLUMN IF NOT EXISTS notify_2h_sent BOOLEAN DEFAULT FALSE',
            'ALTER TABLE client_services ADD COLUMN IF NOT EXISTS notify_24h_sent BOOLEAN DEFAULT FALSE',
            'ALTER TABLE client_services ADD COLUMN IF NOT EXISTS notify_100mb_sent BOOLEAN DEFAULT FALSE',
            'ALTER TABLE client_services ADD COLUMN IF NOT EXISTS notify_1gb_sent BOOLEAN DEFAULT FALSE',
            'ALTER TABLE client_services ADD COLUMN IF NOT EXISTS traffic_baseline_bytes BIGINT DEFAULT 0',
            'ALTER TABLE client_services ADD COLUMN IF NOT EXISTS xui_uuid VARCHAR(80)',
            'ALTER TABLE plans ADD COLUMN IF NOT EXISTS is_unlimited BOOLEAN DEFAULT FALSE',
            'UPDATE plans SET is_unlimited = TRUE WHERE COALESCE(volume_gb, 0) <= 0',
            'ALTER TABLE servers ADD COLUMN IF NOT EXISTS subscription_url TEXT',
            "ALTER TABLE servers ADD COLUMN IF NOT EXISTS display_name VARCHAR(150)",
            "ALTER TABLE servers ADD COLUMN IF NOT EXISTS profile VARCHAR(32) DEFAULT '3x-ui'",
            "ALTER TABLE payment_cards ADD COLUMN IF NOT EXISTS scopes JSON DEFAULT '[]'",
            'ALTER TABLE client_services ALTER COLUMN server_id DROP NOT NULL',
            'ALTER TABLE plans ALTER COLUMN server_id DROP NOT NULL',
            'ALTER TABLE plans ALTER COLUMN category_id DROP NOT NULL',
            'ALTER TABLE plans DROP CONSTRAINT IF EXISTS plans_category_id_fkey',
            'ALTER TABLE plans ADD CONSTRAINT plans_category_id_fkey FOREIGN KEY (category_id) REFERENCES server_categories(id) ON DELETE SET NULL',
            'ALTER TABLE plans DROP CONSTRAINT IF EXISTS plans_server_id_fkey',
            'ALTER TABLE plans ADD CONSTRAINT plans_server_id_fkey FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE SET NULL',
            'ALTER TABLE client_services DROP CONSTRAINT IF EXISTS client_services_server_id_fkey',
            'ALTER TABLE client_services ADD CONSTRAINT client_services_server_id_fkey FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE SET NULL',
            'ALTER TABLE server_categories DROP CONSTRAINT IF EXISTS server_categories_server_id_fkey',
            'ALTER TABLE server_categories ADD CONSTRAINT server_categories_server_id_fkey FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE SET NULL',
            'ALTER TABLE payment_cards DROP CONSTRAINT IF EXISTS payment_cards_server_id_fkey',
            'ALTER TABLE payment_cards ADD CONSTRAINT payment_cards_server_id_fkey FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE SET NULL',
            'ALTER TABLE discount_codes ADD COLUMN IF NOT EXISTS per_user_limit INTEGER DEFAULT 1',
            'ALTER TABLE orders ADD COLUMN IF NOT EXISTS external_payment_id VARCHAR(120)',
            'ALTER TABLE orders ADD COLUMN IF NOT EXISTS external_invoice_url TEXT',
            'ALTER TABLE orders ADD COLUMN IF NOT EXISTS rejection_reason TEXT',
            'ALTER TABLE orders ADD COLUMN IF NOT EXISTS rejected_by BIGINT',
            'ALTER TABLE orders ADD COLUMN IF NOT EXISTS rejected_at TIMESTAMP',
            'ALTER TABLE reseller_topup_requests ADD COLUMN IF NOT EXISTS rejection_reason TEXT',
            'ALTER TABLE reseller_topup_requests ADD COLUMN IF NOT EXISTS rejected_by BIGINT',
            'ALTER TABLE reseller_topup_requests ADD COLUMN IF NOT EXISTS rejected_at TIMESTAMP',
            'UPDATE client_services SET reseller_lifetime_used_bytes = COALESCE(NULLIF(reseller_lifetime_used_bytes, 0), used_bytes, 0) WHERE reseller_id IS NOT NULL',
            'ALTER TABLE users ADD COLUMN IF NOT EXISTS wallet_openvpn_balance BIGINT DEFAULT 0',
            'ALTER TABLE users ADD COLUMN IF NOT EXISTS wallet_v2ray_balance BIGINT DEFAULT 0',
            'ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_code VARCHAR(64)',
            'CREATE UNIQUE INDEX IF NOT EXISTS ix_users_referral_code ON users(referral_code)',
            'ALTER TABLE users ADD COLUMN IF NOT EXISTS referred_by_user_id INTEGER',
            'ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_joined_at TIMESTAMP',
            'ALTER TABLE users DROP CONSTRAINT IF EXISTS users_referred_by_user_id_fkey',
            'ALTER TABLE users ADD CONSTRAINT users_referred_by_user_id_fkey FOREIGN KEY (referred_by_user_id) REFERENCES users(id) ON DELETE SET NULL',
            'ALTER TABLE orders ALTER COLUMN service_id DROP NOT NULL',
            'ALTER TABLE test_account_usages ALTER COLUMN service_id DROP NOT NULL',
            'ALTER TABLE orders DROP CONSTRAINT IF EXISTS orders_service_id_fkey',
            "ALTER TABLE orders ADD CONSTRAINT orders_service_id_fkey FOREIGN KEY (service_id) REFERENCES client_services(id) ON DELETE SET NULL",
            'ALTER TABLE test_account_usages DROP CONSTRAINT IF EXISTS test_account_usages_service_id_fkey',
            "ALTER TABLE test_account_usages ADD CONSTRAINT test_account_usages_service_id_fkey FOREIGN KEY (service_id) REFERENCES client_services(id) ON DELETE SET NULL",
        ]
        for sql in upgrades:
            await safe_upgrade(conn, sql)
        # Remove legacy IP-record / anti-sharing data and columns. Safe-upgrade keeps SQLite/older DBs alive if a DROP is unsupported.
        cleanup_sql = [
            "DELETE FROM settings WHERE key LIKE 'ip_record_%'",
            "DELETE FROM settings WHERE key LIKE 'anti_sharing_%'",
            'DROP TABLE IF EXISTS anti_sharing_violations',
            'ALTER TABLE client_services DROP COLUMN IF EXISTS ip_limit',
            'ALTER TABLE client_services DROP COLUMN IF EXISTS anti_share_violation_count',
            'ALTER TABLE client_services DROP COLUMN IF EXISTS anti_share_banned_until',
            'ALTER TABLE client_services DROP COLUMN IF EXISTS anti_share_banned_permanent',
            'ALTER TABLE client_services DROP COLUMN IF EXISTS anti_share_last_alert_at',
            'ALTER TABLE client_services DROP COLUMN IF EXISTS anti_share_last_ips',
            'ALTER TABLE plans DROP COLUMN IF EXISTS anti_sharing_enabled',
            'UPDATE plans SET is_unlimited = TRUE WHERE COALESCE(volume_gb, 0) <= 0',
            """DO $$ BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'client_services' AND column_name = 'last_payg_used_bytes'
                ) THEN
                    UPDATE client_services SET traffic_baseline_bytes = COALESCE(traffic_baseline_bytes, last_payg_used_bytes, 0);
                END IF;
            END $$""",
            'ALTER TABLE client_services DROP COLUMN IF EXISTS last_payg_used_bytes',
            'ALTER TABLE client_services DROP COLUMN IF EXISTS is_payg',
            'ALTER TABLE plans DROP COLUMN IF EXISTS is_payg',
            'DROP TABLE IF EXISTS payg_usage_logs',
        ]
        for sql in cleanup_sql:
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
    # Database must stay raw: nothing is inserted by default.
    redis = Redis.from_url(settings.REDIS_URL)
    bot = Bot(token=settings.BOT_TOKEN)
    dp = Dispatcher(storage=RedisStorage(redis=redis))
    dp.message.middleware(UserSafeErrorMiddleware())
    dp.callback_query.middleware(UserSafeErrorMiddleware())
    dp.callback_query.middleware(FreshCallbackOnlyMiddleware())
    for r in [
        start.router,
        admin_panel.router, servers.router, categories.router, plans.router, wallet.router, admin_settings.router, admin_resellers.router,
        account.router, my_services.router, tickets.router, buy.router, test_account.router, reseller.router,
    ]:
        dp.include_router(r)
    scheduler = AsyncIOScheduler(
        timezone=settings.TZ,
        executors={'default': AsyncIOExecutor()},
        job_defaults={'coalesce': True, 'max_instances': 1, 'misfire_grace_time': 60},
    )
    scheduler.add_job(scan_service_alerts, 'interval', minutes=45, args=[bot], id='service_alerts', replace_existing=True)
    scheduler.add_job(sync_all_servers, 'interval', seconds=max(300, settings.SERVER_SYNC_SECONDS), id='server_auto_sync', replace_existing=True)
    scheduler.add_job(sync_mikrotik_usage, 'interval', minutes=5, id='mikrotik_usage_sync', replace_existing=True)
    scheduler.start()
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()
        await redis.close()
        await engine.dispose()

if __name__ == '__main__':
    asyncio.run(main())
