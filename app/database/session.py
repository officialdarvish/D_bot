from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.core.config import settings


def _engine_kwargs() -> dict:
    """Return engine options that are safe for the configured database driver."""
    url = str(settings.DATABASE_URL)
    if url.startswith('sqlite'):
        return {"pool_pre_ping": True}
    return {
        "pool_size": max(int(settings.DB_POOL_SIZE or 10), 1),
        "max_overflow": max(int(settings.DB_MAX_OVERFLOW or 20), 0),
        "pool_recycle": max(int(settings.DB_POOL_RECYCLE_SECONDS or 1800), 60),
        "pool_pre_ping": True,
    }


engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs())
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
