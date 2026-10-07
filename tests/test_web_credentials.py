from __future__ import annotations

import os
import unittest

os.environ.setdefault('BOT_TOKEN', '123456789:AA_TestTokenForUnitTests_1234567890')
os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://dbot:test@localhost:5432/dbot')
os.environ.setdefault('FERNET_KEY', 'MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=')

from app.core.security import is_password_hash, verify_password
from app.database.models import Setting
from app.services.web_credentials import (
    WEB_ADMIN_PASSWORD_HASH_KEY,
    WEB_ADMIN_PASSWORD_SECRET_KEY,
    WEB_ADMIN_USERNAME_KEY,
    read_web_credentials,
    save_web_credentials,
    validate_web_admin_password,
    validate_web_admin_username,
)


class FakeSession:
    def __init__(self) -> None:
        self.rows: dict[str, Setting] = {}
        self.commits = 0

    async def get(self, _model, key: str):
        return self.rows.get(key)

    async def merge(self, row: Setting):
        self.rows[row.key] = Setting(key=row.key, value=row.value)
        return self.rows[row.key]

    async def commit(self) -> None:
        self.commits += 1

    async def flush(self) -> None:
        return None

    async def rollback(self) -> None:
        return None

    async def close(self) -> None:
        return None


class WebCredentialsTests(unittest.IsolatedAsyncioTestCase):
    async def test_password_is_hashed_and_also_recoverable_encrypted(self) -> None:
        session = FakeSession()
        snap = await save_web_credentials(
            username='owner_admin',
            password='StrongPass-2026',
            updated_by='unit-test',
            session=session,
        )

        self.assertEqual(snap.username, 'owner_admin')
        self.assertEqual(snap.password, 'StrongPass-2026')
        self.assertTrue(snap.password_available)
        self.assertEqual(snap.source, 'database')

        stored_hash = session.rows[WEB_ADMIN_PASSWORD_HASH_KEY].value
        stored_secret = session.rows[WEB_ADMIN_PASSWORD_SECRET_KEY].value
        self.assertTrue(is_password_hash(stored_hash))
        self.assertTrue(verify_password('StrongPass-2026', stored_hash))
        self.assertNotEqual(stored_secret, 'StrongPass-2026')

    async def test_username_change_keeps_current_password(self) -> None:
        session = FakeSession()
        await save_web_credentials(
            username='first_owner',
            password='AnotherPass-2026',
            session=session,
        )
        await save_web_credentials(username='second_owner', session=session)
        snap = await read_web_credentials(session)

        self.assertEqual(session.rows[WEB_ADMIN_USERNAME_KEY].value, 'second_owner')
        self.assertEqual(snap.password, 'AnotherPass-2026')

    def test_username_validation(self) -> None:
        self.assertEqual(validate_web_admin_username('admin_2026'), 'admin_2026')
        with self.assertRaises(ValueError):
            validate_web_admin_username('a b')
        with self.assertRaises(ValueError):
            validate_web_admin_username('ab')

    def test_password_validation(self) -> None:
        self.assertEqual(validate_web_admin_password('12345678'), '12345678')
        with self.assertRaises(ValueError):
            validate_web_admin_password('1234567')
        with self.assertRaises(ValueError):
            validate_web_admin_password('abc\n12345')


if __name__ == '__main__':
    unittest.main()
