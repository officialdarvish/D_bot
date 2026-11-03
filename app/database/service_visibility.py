"""Idempotent additive migration shared by API and bot startup."""
from sqlalchemy import inspect


async def ensure_service_visibility_column(conn):
    columns = await conn.run_sync(lambda sync: {c['name'] for c in inspect(sync).get_columns('client_services')})
    if 'hidden_from_owner' not in columns:
        suffix = 'IF NOT EXISTS ' if conn.dialect.name == 'postgresql' else ''
        await conn.exec_driver_sql(
            f'ALTER TABLE client_services ADD COLUMN {suffix}hidden_from_owner BOOLEAN NOT NULL DEFAULT FALSE')

    if 'notify_500mb_sent' not in columns:
        suffix = 'IF NOT EXISTS ' if conn.dialect.name == 'postgresql' else ''
        await conn.exec_driver_sql(
            f'ALTER TABLE client_services ADD COLUMN {suffix}notify_500mb_sent BOOLEAN NOT NULL DEFAULT FALSE')
