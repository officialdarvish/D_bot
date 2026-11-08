from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import unittest


class WebCredentialsCliImportPathTests(unittest.TestCase):
    def test_direct_script_execution_can_import_app_package(self) -> None:
        root = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        env.setdefault('BOT_TOKEN', '123456789:AA_TestTokenForUnitTests_1234567890')
        env.setdefault('DATABASE_URL', 'postgresql+asyncpg://dbot:test@localhost:5432/dbot')
        env.setdefault('FERNET_KEY', 'MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=')

        result = subprocess.run(
            [sys.executable, str(root / 'scripts' / 'web_credentials_cli.py'), '--help'],
            cwd=root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=20,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("No module named 'app'", result.stderr)
        self.assertIn('Read or update the live D BOT website credentials.', result.stdout)


if __name__ == '__main__':
    unittest.main()
