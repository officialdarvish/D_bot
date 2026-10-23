from __future__ import annotations

import unittest
import importlib.util
from pathlib import Path

from cryptography.fernet import Fernet

from app.services.portable_backup import (
    PORTABLE_BACKUP_FORMAT,
    attach_checksum,
    create_portable_secret_box,
    open_portable_secret,
    portable_secret_metadata,
    portable_secret_box_from_meta,
    seal_portable_secret,
    verify_checksum,
)


class PortableBackupTests(unittest.TestCase):
    def _payload(self, password: str = 'panel-secret') -> dict:
        key, box = create_portable_secret_box()
        data = {
            'meta': {
                'app': 'D BOT',
                'format': PORTABLE_BACKUP_FORMAT,
                'created_at': '2026-07-30T00:00:00',
                'portability': 'cross-installation',
                'portable_secrets': portable_secret_metadata(key),
            },
            'servers': [{
                'id': 1,
                'name': 'server-one',
                'password_encrypted': seal_portable_secret(password, box),
            }],
        }
        attach_checksum(data)
        return data

    def test_portable_checksum_detects_modification(self) -> None:
        data = self._payload()
        verify_checksum(data)
        data['servers'][0]['name'] = 'changed'
        with self.assertRaisesRegex(ValueError, 'checksum is invalid'):
            verify_checksum(data)

    def test_secret_can_move_between_two_installation_keys(self) -> None:
        source_box = Fernet(Fernet.generate_key())
        destination_box = Fernet(Fernet.generate_key())
        source_ciphertext = source_box.encrypt(b'different-vps-secret')

        data = self._payload(source_box.decrypt(source_ciphertext).decode('utf-8'))
        portable_box = portable_secret_box_from_meta(data['meta'])
        plaintext = open_portable_secret(data['servers'][0]['password_encrypted'], portable_box)
        destination_ciphertext = destination_box.encrypt(plaintext.encode('utf-8'))

        self.assertNotEqual(source_ciphertext, destination_ciphertext)
        self.assertEqual(destination_box.decrypt(destination_ciphertext), b'different-vps-secret')

    def test_unwrapped_secret_is_rejected(self) -> None:
        data = self._payload()
        box = portable_secret_box_from_meta(data['meta'])
        with self.assertRaisesRegex(ValueError, 'unwrapped credential'):
            open_portable_secret('gAAAAA-old-local-token', box)

    def test_portable_metadata_includes_website_password_secret(self) -> None:
        data = self._payload()
        fields = data['meta']['portable_secrets']['fields']
        self.assertIn('settings.web_admin_password_encrypted', fields)

    def test_source_includes_all_previous_missing_tables(self) -> None:
        source = Path('app/api/admin_web.py').read_text(encoding='utf-8')
        self.assertIn("('reseller_service_activities', ResellerServiceActivity)", source)
        self.assertIn("('test_account_counters', TestAccountCounter)", source)
        self.assertIn("('service_username_counters', ServiceUsernameCounter)", source)
        self.assertIn("('service_deletion_tasks', ServiceDeletionTask)", source)

    def test_legacy_converter_wraps_source_credential(self) -> None:
        spec = importlib.util.spec_from_file_location('convert_legacy_backup', 'scripts/convert_legacy_backup.py')
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)

        source_box = Fernet(Fernet.generate_key())
        legacy = {
            'meta': {'app': 'D BOT', 'format': 3, 'signature': 'host-bound'},
            'servers': [{'id': 1, 'name': 'old', 'password_encrypted': source_box.encrypt(b'old-secret').decode('ascii')}],
        }
        converted = module.convert(legacy, source_box)
        verify_checksum(converted)
        box = portable_secret_box_from_meta(converted['meta'])
        self.assertEqual(open_portable_secret(converted['servers'][0]['password_encrypted'], box), 'old-secret')


if __name__ == '__main__':
    unittest.main()
