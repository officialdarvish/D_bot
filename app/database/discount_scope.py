"""Add discount scope columns to existing SQLite/PostgreSQL installations."""
from sqlalchemy import inspect


async def ensure_discount_scope_columns(conn):
    columns = await conn.run_sync(lambda sync: {c['name'] for c in inspect(sync).get_columns('discount_codes')})
    for name in ('allowed_server_ids', 'allowed_category_ids', 'allowed_plan_ids'):
        if name not in columns:
            suffix = 'IF NOT EXISTS ' if conn.dialect.name == 'postgresql' else ''
            await conn.exec_driver_sql(f"ALTER TABLE discount_codes ADD COLUMN {suffix}{name} JSON DEFAULT '[]'")
