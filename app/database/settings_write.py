"""Atomic settings writes shared by the bot and web panel."""
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.database.models import Setting


def settings_upsert_statement(dialect: str, values: dict[str, str]):
    if dialect == 'postgresql':
        insert = postgres_insert
    elif dialect == 'sqlite':
        insert = sqlite_insert
    else:
        raise ValueError(f'Unsupported settings database dialect: {dialect}')
    # Consistent key order also avoids opposite lock ordering across bulk writers.
    statement = insert(Setting.__table__).values([
        {'key': key, 'value': values[key]} for key in sorted(values)
    ])
    return statement.on_conflict_do_update(
        index_elements=[Setting.__table__.c.key],
        set_={'value': statement.excluded.value},
    )


async def upsert_settings(session, values: dict[str, str]) -> None:
    """Write in the caller's transaction; never commit or retry partial work."""
    if values:
        await session.execute(settings_upsert_statement(session.get_bind().dialect.name, values))
