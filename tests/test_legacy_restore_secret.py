from __future__ import annotations

import base64
import hashlib
import os
import unittest
from pathlib import Path

from cryptography.fernet import Fernet

os.environ.setdefault('BOT_TOKEN', '123456789:AA_TestTokenForUnitTests_1234567890')
os.environ.setdefault('DATABASE_URL', 'sqlite+aiosqlite:///:memory:')
os.environ.setdefault('FERNET_KEY', 'MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=')

from app.core.security import encrypt_text
from app.services.legacy_backup import (
    LegacyBackupSecretInvalid,
    LegacyBackupSecretRequired,
    legacy_source_box,
    open_legacy_secret,
)


class LegacyRestoreSecretTests(unittest.TestCase):
    def test_cross_install_legacy_secret_accepts_old_fernet_key(self) -> None:
        source_key = Fernet.generate_key()
        ciphertext = Fernet(source_key).encrypt(b'old-panel-password').decode('ascii')
        source_box = legacy_source_box(source_key.decode('ascii'), 'fernet')
        self.assertEqual(open_legacy_secret(ciphertext, source_box, 'server credential'), 'old-panel-password')

    def test_legacy_secret_can_use_old_bot_token_derived_key(self) -> None:
        source_token = '987654321:AA_OldSourceBotToken_ForRestore'
        key = base64.urlsafe_b64encode(hashlib.sha256(source_token.encode('utf-8')).digest())
        ciphertext = Fernet(key).encrypt(b'bot-derived-password').decode('ascii')
        source_box = legacy_source_box(source_token, 'bot_token')
        self.assertEqual(open_legacy_secret(ciphertext, source_box, 'server credential'), 'bot-derived-password')

    def test_legacy_secret_requests_source_secret_for_foreign_ciphertext(self) -> None:
        ciphertext = Fernet(Fernet.generate_key()).encrypt(b'old-panel-password').decode('ascii')
        with self.assertRaises(LegacyBackupSecretRequired):
            open_legacy_secret(ciphertext, None, 'server credential')

    def test_wrong_source_secret_is_rejected(self) -> None:
        ciphertext = Fernet(Fernet.generate_key()).encrypt(b'old-panel-password').decode('ascii')
        wrong_box = legacy_source_box(Fernet.generate_key().decode('ascii'), 'fernet')
        with self.assertRaises(LegacyBackupSecretInvalid):
            open_legacy_secret(ciphertext, wrong_box, 'server credential')

    def test_same_install_ciphertext_still_restores_without_extra_secret(self) -> None:
        ciphertext = encrypt_text('same-install-password')
        self.assertEqual(open_legacy_secret(ciphertext, None, 'server credential'), 'same-install-password')

    def test_web_and_telegram_restore_paths_pass_legacy_secret(self) -> None:
        api_source = Path('app/api/admin_web.py').read_text(encoding='utf-8')
        bot_source = Path('app/bot/handlers/admin/settings.py').read_text(encoding='utf-8')
        self.assertIn("legacy_secret=legacy_secret", api_source)
        self.assertIn("legacy_secret_kind=legacy_secret_kind", api_source)
        self.assertIn("RestoreBackup.legacy_secret", bot_source)
        self.assertIn("legacy_secret=secret", bot_source)


if __name__ == '__main__':
    unittest.main()
