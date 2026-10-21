from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, patch

import httpx

os.environ.setdefault('BOT_TOKEN', '123456789:AA_TestTokenForUnitTests_1234567890')
os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://dbot:test@localhost:5432/dbot')
os.environ.setdefault('FERNET_KEY', 'MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=')

from app.xui.client import XUIClient


class XuiTimeoutResilienceTests(unittest.IsolatedAsyncioTestCase):
    @patch('app.xui.client.asyncio.sleep', new_callable=AsyncMock)
    async def test_get_request_retries_transient_read_timeout(self, _sleep) -> None:
        xui = object.__new__(XUIClient)
        xui.read_retry_attempts = 3
        xui.last_error = ''
        response = httpx.Response(
            200,
            json={'success': True, 'obj': []},
            request=httpx.Request('GET', 'https://panel.example/panel/api/inbounds/list'),
        )
        transport = AsyncMock(side_effect=[httpx.ReadTimeout('slow'), response])
        xui.client = type('FakeClient', (), {'request': transport})()
        xui._path = lambda path: path

        data = await xui._request('GET', '/panel/api/inbounds/list')

        self.assertTrue(data['success'])
        self.assertEqual(transport.await_count, 2)

    @patch('app.xui.client.asyncio.sleep', new_callable=AsyncMock)
    async def test_mutating_post_is_not_blindly_retried(self, _sleep) -> None:
        xui = object.__new__(XUIClient)
        xui.read_retry_attempts = 3
        xui.last_error = ''
        transport = AsyncMock(side_effect=httpx.ReadTimeout('slow'))
        xui.client = type('FakeClient', (), {'request': transport})()
        xui._path = lambda path: path

        with self.assertRaises(httpx.ReadTimeout):
            await xui._request('POST', '/panel/api/clients/update/test', json={'enable': True})

        self.assertEqual(transport.await_count, 1)


class ResellerRenewOperationTimeoutTests(unittest.IsolatedAsyncioTestCase):
    @patch('app.services.xui_service.asyncio.sleep', new_callable=AsyncMock)
    async def test_reseller_renew_timeout_returns_reconciled_success_without_blind_retry(self, _sleep) -> None:
        from app.services.xui_service import XuiService

        service = XuiService()
        service.reset_client_plan_any = AsyncMock(side_effect=httpx.ReadTimeout('slow Sanaei response'))
        reconciled = {
            'result': {'success': True, 'transport_timeout_reconciled': True, 'inbound_ids': [1, 2]},
            'found': {'client': {'email': 'client-a'}},
            'panel_email': 'client-a',
        }
        service._reconcile_reseller_renew_after_timeout = AsyncMock(return_value=reconciled)
        server = type('ServerStub', (), {})()

        result = await service.renew_reseller_client_any(server, ['client-a'], 50, 30)

        self.assertTrue(result['result']['transport_timeout_reconciled'])
        self.assertEqual(service.reset_client_plan_any.await_count, 1)
        service._reconcile_reseller_renew_after_timeout.assert_awaited_once()

    @patch('app.services.xui_service.asyncio.sleep', new_callable=AsyncMock)
    async def test_reseller_renew_retries_once_only_when_timeout_not_committed(self, _sleep) -> None:
        from app.services.xui_service import XuiService

        service = XuiService()
        success = {'result': {'success': True}, 'found': {'client': {'email': 'client-a'}}, 'panel_email': 'client-a'}
        service.reset_client_plan_any = AsyncMock(side_effect=[httpx.ReadTimeout('slow'), success])
        service._reconcile_reseller_renew_after_timeout = AsyncMock(return_value=None)
        server = type('ServerStub', (), {})()

        result = await service.renew_reseller_client_any(server, ['client-a'], 50, 30)

        self.assertTrue(result['result']['success'])
        self.assertEqual(service.reset_client_plan_any.await_count, 2)
        self.assertEqual(service._reconcile_reseller_renew_after_timeout.await_count, 1)

    @patch('app.services.xui_service.asyncio.sleep', new_callable=AsyncMock)
    async def test_reseller_renew_never_leaks_raw_read_timeout_after_final_failure(self, _sleep) -> None:
        from app.services.xui_service import XuiService

        service = XuiService()
        service.reset_client_plan_any = AsyncMock(side_effect=httpx.ReadTimeout('slow'))
        service._reconcile_reseller_renew_after_timeout = AsyncMock(return_value=None)
        server = type('ServerStub', (), {})()

        with self.assertRaises(RuntimeError) as caught:
            await service.renew_reseller_client_any(server, ['client-a'], 50, 30)

        self.assertIn('could not be confirmed', str(caught.exception))
        self.assertEqual(service.reset_client_plan_any.await_count, 2)
        # Reconcile after each timeout plus one final read after the second timeout.
        self.assertEqual(service._reconcile_reseller_renew_after_timeout.await_count, 3)
