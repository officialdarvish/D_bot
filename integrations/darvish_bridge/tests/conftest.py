import os
import tempfile
from pathlib import Path

# Set before importing app modules (settings and engine are constructed on import).
TEST_DB = Path(tempfile.gettempdir()) / f"darvish_test_{os.getpid()}.sqlite3"
os.environ['DATABASE_URL'] = f"sqlite:///{TEST_DB}"
os.environ['TELEGRAM_BOT_TOKEN'] = '123456:FAKE_TEST_TOKEN'
os.environ['ADMIN_TELEGRAM_IDS'] = '1001'
os.environ['APP_SECRET'] = 'unit-test-secret-not-for-production-0123456789'

import pytest
from sqlalchemy import delete
from app.database import Base, engine, SessionLocal
from app import models  # noqa: F401


@pytest.fixture(autouse=True)
def isolated_schema():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session
        session.rollback()
