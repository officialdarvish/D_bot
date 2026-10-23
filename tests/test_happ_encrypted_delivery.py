from __future__ import annotations

import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault('BOT_TOKEN', '123456789:AA_TestTokenForUnitTests_1234567890')
os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://dbot:test@localhost:5432/dbot')
os.environ.setdefault('FERNET_KEY', 'MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=')

from app.xui.client import XUIClient
from app.services.xui_service import XuiService

ROOT = Path(__file__).resolve().parents[1]


def server(happ: bool):
    return SimpleNamespace(id=9, server_type='xui', panel_url='https://panel.example/abc/',
                           username='admin', password_encrypted='encrypted',
                           meta={'happ_encrypted_sub': happ})


def plan(happ: bool):
    return SimpleNamespace(id=21, server_id=9, meta={'happ_encrypted_sub': happ})


class HappDeliveryTest(unittest.IsolatedAsyncioTestCase):
    async def test_official_happ_endpoint_uses_numeric_client_record_id(self):
        xui = object.__new__(XUIClient)
        xui._client_api_request = AsyncMock(side_effect=[
            {'success': True, 'obj': {'client': {'id': 407, 'uuid': 'some-uuid', 'email': 'test'}}},
            {'success': True, 'obj': {'encryptedLink': 'happ://crypt5/safe-value'}},
        ])
        self.assertEqual(await xui.get_happ_encrypted_link('test'), 'happ://crypt5/safe-value')
        self.assertEqual(xui._client_api_request.await_args_list[0].args, ('GET', '/panel/api/clients/get/test'))
        self.assertEqual(xui._client_api_request.await_args_list[1].args, ('POST', '/panel/api/clients/happLink/407'))

    async def test_does_not_confuse_uuid_or_inbound_with_record_id(self):
        xui = object.__new__(XUIClient)
        xui._client_api_request = AsyncMock(return_value={'success': True, 'obj': {'client': {'id': 'uuid-string', 'email': 'test'}, 'inboundIds': [176]}})
        with self.assertRaisesRegex(RuntimeError, 'numeric client record ID'):
            await xui.get_happ_encrypted_link('test')
        self.assertEqual(xui._client_api_request.await_count, 1)

    async def test_rejects_invalid_happ_response(self):
        xui = object.__new__(XUIClient)
        xui._client_api_request = AsyncMock(side_effect=[
            {'success': True, 'obj': {'client': {'id': 12}}},
            {'success': True, 'obj': {'encryptedLink': 'https://normal-sub.example/abc'}},
        ])
        with self.assertRaisesRegex(RuntimeError, 'not enabled or response is invalid'):
            await xui.get_happ_encrypted_link('test')

    async def test_no_mode_keeps_original_link_without_api(self):
        with patch('app.services.xui_service.XUIClient') as client:
            url = await XuiService().delivery_subscription_link(server(False), 'test', 'https://sub.example/raw')
        self.assertEqual(url, 'https://sub.example/raw')
        client.assert_not_called()

    async def test_yes_mode_uses_happ_and_never_falls_back(self):
        client = SimpleNamespace(login=AsyncMock(return_value=True), close=AsyncMock(),
                                 get_happ_encrypted_link=AsyncMock(return_value='happ://crypt5/test'))
        with patch('app.services.xui_service.XUIClient', return_value=client), \
             patch('app.services.xui_service.decrypt_text', return_value='secret'):
            url = await XuiService().delivery_subscription_link(server(True), 'test', 'https://sub.example/raw', plan=plan(True))
        self.assertEqual(url, 'happ://crypt5/test')
        client.close.assert_awaited_once()

    async def test_api_unavailable_does_not_leak_plain_link(self):
        client = SimpleNamespace(login=AsyncMock(return_value=True), close=AsyncMock(),
                                 get_happ_encrypted_link=AsyncMock(side_effect=RuntimeError('not enabled')))
        with patch('app.services.xui_service.XUIClient', return_value=client), \
             patch('app.services.xui_service.decrypt_text', return_value='secret'):
            url = await XuiService().delivery_subscription_link(server(True), 'test', 'https://sub.example/raw', plan=plan(True))
        self.assertIsNone(url)
        client.close.assert_awaited_once()


    async def test_server_flag_does_not_enable_happ_without_public_plan(self):
        self.assertFalse(XuiService.happ_link_enabled(server(True)))
        self.assertFalse(XuiService.happ_link_enabled(server(True), plan(False)))
        self.assertTrue(XuiService.happ_link_enabled(server(False), plan(True)))
        with patch('app.services.xui_service.XUIClient') as client:
            original = await XuiService().delivery_subscription_link(server(True), 'test', 'https://sub.example/raw')
        self.assertEqual(original, 'https://sub.example/raw')
        client.assert_not_called()

    async def test_happ_public_sales_not_trial_reseller_or_converted(self):
        source_server, source_plan = server(False), plan(True)
        trial = SimpleNamespace(client_username='test_00001', reseller_id=None, plan_id=None, id=50)
        reseller = SimpleNamespace(client_username='client', reseller_id=3, plan_id=21, id=51)
        mockdb = SimpleNamespace(execute=AsyncMock())
        self.assertFalse(await XuiService.service_happ_enabled(mockdb, source_server, trial, source_plan))
        self.assertFalse(await XuiService.service_happ_enabled(mockdb, source_server, reseller, source_plan))
        mockdb.execute.assert_not_called()

        retail = SimpleNamespace(client_username='client', reseller_id=None, plan_id=21, id=52)
        converted = SimpleNamespace(scalar_one_or_none=lambda: 93)
        mockdb.execute = AsyncMock(return_value=converted)
        self.assertFalse(await XuiService.service_happ_enabled(mockdb, source_server, retail, source_plan))
        self.assertEqual(mockdb.execute.await_count, 1)

        free_of_conversion = SimpleNamespace(scalar_one_or_none=lambda: None)
        mockdb.execute = AsyncMock(return_value=free_of_conversion)
        self.assertTrue(await XuiService.service_happ_enabled(mockdb, source_server, retail, source_plan))
        self.assertEqual(mockdb.execute.await_count, 1)

    def test_all_regular_payment_deliveries_enable_happ_policy(self):
        presenter = (ROOT / 'app/bot/service_presenter.py').read_text()
        buy = (ROOT / 'app/bot/handlers/public/buy.py').read_text()
        crypto = (ROOT / 'app/api/main.py').read_text()
        self.assertIn('allow_happ: bool = False', presenter)
        self.assertIn('allow_happ=True', buy)
        self.assertIn('allow_happ=True', crypto)

    def test_convert_keyboard_is_compact_and_only_shows_plan_title(self):
        source = (ROOT / 'app/bot/handlers/public/convert.py').read_text()
        self.assertIn("InlineKeyboardButton(text=p.title, callback_data=f'svcconvert:quote:{sid}:{p.id}')", source)
        self.assertNotIn("{servers[p.server_id].name} — {p.title}", source)

    def test_plan_form_only_has_happ_for_public_xui(self):
        ui = (ROOT / 'frontend/components/admin-dashboard.tsx').read_text()
        plan_form = ui.split('function planForm(', 1)[1].split('function resellerPlanForm(', 1)[0]
        server_form = ui.split('function serverForm(', 1)[1].split('function categoryForm(', 1)[0]
        self.assertIn("name: 'happ_encrypted_sub'", plan_form)
        self.assertIn("name: '__selected_server_type', value: 'xui'", plan_form)
        self.assertNotIn("name: 'happ_encrypted_sub'", server_form)

    def test_web_and_telegram_controls_and_safe_delivery_paths(self):
        web = (ROOT / 'frontend/components/admin-dashboard.tsx').read_text()
        api = (ROOT / 'app/api/admin_web.py').read_text()
        telegram = (ROOT / 'app/bot/handlers/admin/servers.py').read_text()
        presenter = (ROOT / 'app/bot/service_presenter.py').read_text()
        my_services = (ROOT / 'app/bot/handlers/public/my_services.py').read_text()
        self.assertIn('happ_encrypted_sub', web)
        self.assertIn('happ_encrypted_sub', api)
        self.assertNotIn('happ_encrypted_sub', telegram)
        self.assertNotIn('server:happ:yes', telegram)
        self.assertIn('allow_happ', presenter)
        self.assertIn('service_happ_enabled', my_services)
        self.assertIn('happ_delivery_failed', presenter)


if __name__ == '__main__':
    unittest.main()
