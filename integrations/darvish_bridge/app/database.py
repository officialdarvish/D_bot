from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.database_url, pool_pre_ping=True, connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {})

if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def sqlite_settings(dbapi_connection, _):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

SessionLocal = sessionmaker(engine, expire_on_commit=False)


def init_db():
    from . import models  # noqa: F401
    Base.metadata.create_all(engine)


def get_db():
    with SessionLocal() as db:
        yield db
