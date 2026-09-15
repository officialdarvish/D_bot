from __future__ import annotations

import os
from pathlib import Path
import unittest
from unittest.mock import AsyncMock

import httpx

os.environ.setdefault('BOT_TOKEN', '123456789:AA_TestTokenForUnitTests_1234567890')
os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://dbot:test@localhost:5432/dbot')
os.environ.setdefault('FERNET_KEY', 'MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=')

from app.xui.client import SANAEI_TARGET_VERSION, XUIClient

ROOT = Path(__file__).resolve().parents[1]


class Sanaei380CompatibilityTests(unittest.IsolatedAsyncioTestCase):
    def test_target_version_and_modern_api_contract_are_pinned(self) -> None:
        source = (ROOT / 'app/xui/client.py').read_text(encoding='utf-8')
        self.assertEqual(SANAEI_TARGET_VERSION, '3.8.0')
        for endpoint in (
            '/panel/api/clients/add',
            '/panel/api/clients/update/',
            '/panel/api/clients/bulkAdjust',
            '/panel/api/clients/bulkEnable',
            '/panel/api/clients/bulkDisable',
            '/panel/api/clients/bulkAttach',
            '/panel/api/clients/bulkDetach',
            '/panel/api/clients/bulkResetTraffic',
            '/panel/api/server/status',
            '/csrf-token',
        ):
            self.assertIn(endpoint, source)
        self.assertIn('"limitHwid"', source)
        self.assertIn('"adTag"', source)
        self.assertIn('Authorization', source)
        self.assertIn('Bearer', source)

    async def test_enable_disable_uses_v380_bulk_path_without_read_modify_write(self) -> None:
        xui = object.__new__(XUIClient)
        xui.bulk_set_enabled = AsyncMock(return_value={'success': True, 'obj': {'affected': 1}})
        result = await xui.set_client_enabled('user@example.com', True)
        xui.bulk_set_enabled.assert_awaited_once_with(['user@example.com'], True)
        self.assertTrue(result['success'])

    async def test_cookie_api_request_reauthenticates_once_on_401(self) -> None:
        xui = object.__new__(XUIClient)
        xui.api_token = ''
        xui._pool_key = 'test-cookie-pool'
        XUIClient._shared_auth_until[xui._pool_key] = 123.0
        unauthorized = httpx.HTTPStatusError(
            'unauthorized',
            request=httpx.Request('GET', 'https://panel.example/panel/api/clients/list'),
            response=httpx.Response(401, request=httpx.Request('GET', 'https://panel.example/panel/api/clients/list')),
        )
        xui._request = AsyncMock(side_effect=[unauthorized, {'success': True, 'obj': []}])
        xui.login = AsyncMock(return_value=True)
        result = await xui._client_api_request('GET', '/panel/api/clients/list')
        self.assertTrue(result['success'])
        xui.login.assert_awaited_once()
        self.assertEqual(xui._request.await_count, 2)

    async def test_invalid_bearer_401_is_not_retried(self) -> None:
        xui = object.__new__(XUIClient)
        xui.api_token = 'invalid-token'
        xui._pool_key = 'test-token-pool'
        unauthorized = httpx.HTTPStatusError(
            'unauthorized',
            request=httpx.Request('GET', 'https://panel.example/panel/api/server/status'),
            response=httpx.Response(401, request=httpx.Request('GET', 'https://panel.example/panel/api/server/status')),
        )
        xui._request = AsyncMock(side_effect=unauthorized)
        xui.login = AsyncMock(return_value=True)
        with self.assertRaises(httpx.HTTPStatusError):
            await xui._client_api_request('GET', '/panel/api/server/status')
        xui.login.assert_not_awaited()

    def test_runtime_performance_features_are_enabled(self) -> None:
        main = (ROOT / 'app/main.py').read_text(encoding='utf-8')
        config = (ROOT / 'app/core/config.py').read_text(encoding='utf-8')
        sync = (ROOT / 'app/jobs/server_sync.py').read_text(encoding='utf-8')
        defaults = (ROOT / 'app/database/defaults.py').read_text(encoding='utf-8')
        common = (ROOT / 'app/bot/keyboards/common.py').read_text(encoding='utf-8')
        api = (ROOT / 'app/api/main.py').read_text(encoding='utf-8')
        self.assertIn('AiohttpSession(', main)
        self.assertIn('TELEGRAM_HTTP_CONNECTION_LIMIT', main)
        self.assertIn('REDIS_MAX_CONNECTIONS', main)
        self.assertIn('XUI_MAX_KEEPALIVE_CONNECTIONS', config)
        self.assertIn('DB_MAX_OVERFLOW', config)
        self.assertIn('asyncio.Semaphore', sync)
        self.assertIn('asyncio.gather', sync)
        self.assertIn('_SETTINGS_CACHE_TTL_SECONDS', defaults)
        self.assertIn('_BUTTON_SETTINGS_CACHE_TTL_SECONDS', common)
        self.assertIn('default_response_class=ORJSONResponse', api)


if __name__ == '__main__':
    unittest.main()
