"""Bounded replay of database-only background transactions after PostgreSQL deadlock."""
import asyncio
import logging
import random
from sqlalchemy.exc import DBAPIError

logger = logging.getLogger(__name__)


def is_deadlock(exc):
    if not isinstance(exc, DBAPIError):
        return False
    pending, seen = [exc], set()
    while pending:
        item = pending.pop()
        if id(item) in seen:
            continue
        seen.add(id(item))
        if getattr(item, 'sqlstate', None) == '40P01' or getattr(item, 'pgcode', None) == '40P01':
            return True
        for name in ('orig', '__cause__', '__context__'):
            child = getattr(item, name, None)
            if child is not None:
                pending.append(child)
    return False


async def run_snapshot_transaction(sessions, operation, *, label, attempts=3):
    """Use only for panel GET + DB updates; never wrap sends or panel mutations."""
    for attempt in range(attempts):
        try:
            async with sessions() as session:
                try:
                    result = await operation(session)
                    await session.commit()
                    return result
                except BaseException:
                    await session.rollback()
                    raise
        except DBAPIError as exc:
            if not is_deadlock(exc) or attempt + 1 >= attempts:
                raise
            logger.warning('Retrying deadlocked snapshot transaction %s attempt=%s/%s', label, attempt + 2, attempts)
            await asyncio.sleep(.05 * (2 ** attempt) + random.uniform(0, .03))
