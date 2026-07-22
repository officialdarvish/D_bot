from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.core.config import settings


def _engine_kwargs() -> dict:
    """Return engine options that are safe for the configured database driver."""
    url = str(settings.DATABASE_URL)
    if url.startswith('sqlite'):
        return {"pool_pre_ping": True}
    return {
        "pool_size": getattr(settings, 'DB_POOL_SIZE', 5),
        "max_overflow": getattr(settings, 'DB_MAX_OVERFLOW', 5),
        "pool_recycle": 1800,
        "pool_pre_ping": True,
    }


engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs())
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
