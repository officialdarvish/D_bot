from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ.setdefault('BOT_TOKEN', '123456789:AA_TestTokenForUnitTests_1234567890')
os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://dbot:test@localhost:5432/dbot')
os.environ.setdefault('FERNET_KEY', 'MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=')

from app.database.models import Plan, Server
from app.services.xui_service import XuiService
from app.xui.client import XUIClient, XuiClientPayload

ROOT = Path(__file__).resolve().parents[1]


class SanaeiHwidIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def test_client_payload_contains_plan_hwid_limit(self) -> None:
        xui = object.__new__(XUIClient)
        payload = XuiClientPayload(email='u@example.com', total_gb=10, expire_days=30, limit_hwid=3)
        client = xui._client_template(payload)
        self.assertEqual(client['limitHwid'], 3)

    async def test_hwid_device_endpoints_match_sanaei_380_contract(self) -> None:
        xui = object.__new__(XUIClient)
        xui._client_api_request = AsyncMock(side_effect=[
            {'success': True, 'obj': [{'id': 9, 'deviceOs': 'Android', 'deviceModel': 'Pixel'}]},
            {'success': True},
            {'success': True},
        ])
        devices = await xui.get_client_hwids('u+1@example.com')
        self.assertEqual(devices[0]['id'], 9)
        await xui.delete_client_hwid('u+1@example.com', 9)
        await xui.clear_client_hwids('u+1@example.com')
        calls = xui._client_api_request.await_args_list
        self.assertEqual(calls[0].args, ('POST', '/panel/api/clients/hwids/u%2B1%40example.com'))
        self.assertEqual(calls[1].args, ('DELETE', '/panel/api/clients/hwids/u%2B1%40example.com/9'))
        self.assertEqual(calls[2].args, ('DELETE', '/panel/api/clients/hwids/u%2B1%40example.com'))

    async def test_bulk_adjust_sends_limit_hwid_without_touching_quota(self) -> None:
        xui = object.__new__(XUIClient)
        xui._client_api_request = AsyncMock(return_value={'success': True})
        await xui.set_client_hwid_limit('u@example.com', 2)
        xui._client_api_request.assert_awaited_once_with(
            'POST', '/panel/api/clients/bulkAdjust',
            json={'emails': ['u@example.com'], 'addDays': 0, 'addBytes': 0, 'flow': '', 'limitHwid': 2},
        )

    @patch('app.services.xui_service.decrypt_text', return_value='secret')
    @patch('app.services.xui_service.XUIClient')
    async def test_plan_renewal_reapplies_hwid_limit(self, client_cls, _decrypt) -> None:
        from types import SimpleNamespace
        fake = client_cls.return_value
        fake.login = AsyncMock(return_value=True)
        fake.close = AsyncMock()
        fake.get_inbounds = AsyncMock(return_value=[{'id': 7, 'enable': True}])
        fake.reset_client_plan = AsyncMock(return_value={'success': True})
        server = SimpleNamespace(panel_url='https://x.example', username='u', password_encrypted='p', meta={})
        plan = SimpleNamespace(volume_gb=10, duration_days=30, inbound_ids=[7], hwid_limit=2, meta={'inbound_mode': 'manual'})
        await XuiService().renew_client_on_plan(server, plan, 'buyer@example.com', current_inbound_ids=[7])
        fake.reset_client_plan.assert_awaited_once_with(
            'buyer@example.com', 10, 30, inbound_ids=[7], current_inbound_ids_hint=[7], limit_hwid=2
        )

    async def test_plan_creation_passes_hwid_limit_to_xui_payload(self) -> None:
        service = XuiService()
        service.create_client_on_inbounds = AsyncMock(return_value={'success': True})
        service._configured_inbound_ids = lambda _server, _plan: [1, 2]
        server = Server(id=1, name='x', server_type='xui', panel_url='https://x.example', username='u', password_encrypted='p')
        plan = Plan(id=1, title='P', volume_gb=20, duration_days=30, price_irt=1, hwid_limit=4, meta={'inbound_mode': 'manual'})
        await service.create_client_on_plan(server, plan, 'buyer@example.com')
        args = service.create_client_on_inbounds.await_args.args
        payload = args[2]
        self.assertEqual(payload.limit_hwid, 4)

    def test_plan_web_and_bot_surfaces_expose_hwid_policy(self) -> None:
        web = (ROOT / 'frontend/components/admin-dashboard.tsx').read_text(encoding='utf-8')
        api = (ROOT / 'app/api/admin_web.py').read_text(encoding='utf-8')
        bot = (ROOT / 'app/bot/handlers/admin/plans.py').read_text(encoding='utf-8')
        user_bot = (ROOT / 'app/bot/handlers/public/my_services.py').read_text(encoding='utf-8')
        admin_settings = (ROOT / 'app/bot/handlers/admin/settings.py').read_text(encoding='utf-8')
        migrations = (ROOT / 'app/main.py').read_text(encoding='utf-8')
        self.assertIn('HWID device limit (0 = unlimited)', web)
        self.assertIn('hwid_limit', api)
        self.assertIn('schedule_plan_hwid_limit_sync', api)
        self.assertIn('schedule_plan_hwid_limit_sync', bot)
        self.assertIn('محدودیت HWID', bot)
        self.assertIn('مشخصات HWID', user_bot)
        self.assertIn('ریست آیدی سخت افزار', user_bot)
        self.assertIn('svc:hwid_clear_confirm:', user_bot)
        self.assertIn('HWID fingerprint:', user_bot)
        self.assertIn('admin:hwid_clear_confirm:', admin_settings)
        self.assertIn('ADD COLUMN IF NOT EXISTS hwid_limit', migrations)


    def test_public_plan_buttons_do_not_append_hwid_device_count(self) -> None:
        buy = (ROOT / 'app/bot/handlers/public/buy.py').read_text(encoding='utf-8')
        services = (ROOT / 'app/bot/handlers/public/my_services.py').read_text(encoding='utf-8')
        self.assertNotIn('device_suffix', buy)
        self.assertIn("return f'{plan.title} - رایگان برای مدیر'", buy)
        self.assertIn("return f'{plan.title} - {plan.price_irt:,} تومان'", buy)
        self.assertNotIn("device_label = f' | 🖥", services)

    def test_service_detail_exposes_owner_hwid_metadata_and_reset(self) -> None:
        user_bot = (ROOT / 'app/bot/handlers/public/my_services.py').read_text(encoding='utf-8')
        self.assertIn('hwid_status: dict | None = None', user_bot)
        self.assertIn('📱 مشخصات دستگاه‌های ثبت‌شده', user_bot)
        self.assertIn('HWID fingerprint:', user_bot)
        self.assertIn('firstSeen', user_bot)
        self.assertIn('lastSeen', user_bot)
        self.assertIn('userAgent', user_bot)
        self.assertIn('♻️ ریست آیدی سخت افزار', user_bot)
        self.assertIn("await XuiService().clear_client_hwids(server, email)", user_bot)
        self.assertIn("svc:hwid_clear_confirm:", user_bot)



if __name__ == '__main__':
    unittest.main()
