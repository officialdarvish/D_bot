from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import AsyncMock
from types import SimpleNamespace

os.environ.setdefault('BOT_TOKEN', '123456789:AA_TestTokenForUnitTests_1234567890')
os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://dbot:test@localhost:5432/dbot')
os.environ.setdefault('FERNET_KEY', 'MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=')

from app.xui.client import XUIClient
from app.services.xui_service import XuiService

ROOT = Path(__file__).resolve().parents[1]
GB = 1024 ** 3


class ClientGroupApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_group_list_normalizes_current_panel_response(self) -> None:
        xui = object.__new__(XUIClient)
        xui._client_api_request = AsyncMock(return_value={
            'success': True,
            'obj': [
                {'name': 'VIP', 'clientCount': 4},
                {'name': 'Customers', 'clientCount': 18},
            ],
        })
        xui._obj = XUIClient._obj.__get__(xui, XUIClient)
        rows = await xui.list_client_groups()
        self.assertEqual([row['name'] for row in rows], ['VIP', 'Customers'])
        xui._client_api_request.assert_awaited_once_with('GET', '/panel/api/clients/groups')

    async def test_group_bulk_add_uses_official_group_endpoint(self) -> None:
        xui = object.__new__(XUIClient)
        xui._client_api_request = AsyncMock(return_value={'success': True})
        result = await xui.bulk_add_clients_to_group(['a@example.com'], 'VIP')
        self.assertTrue(result['success'])
        xui._client_api_request.assert_awaited_once_with(
            'POST', '/panel/api/clients/groups/bulkAdd',
            json={'emails': ['a@example.com'], 'group': 'VIP'},
        )


class PlanGroupServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_plan_group_is_added_and_empty_group_can_be_cleared(self) -> None:
        service = XuiService()
        fake = SimpleNamespace(
            bulk_add_clients_to_group=AsyncMock(return_value={'success': True}),
            bulk_remove_clients_from_group=AsyncMock(return_value={'success': True}),
        )
        await service._apply_plan_group(fake, 'a@example.com', 'VIP')
        fake.bulk_add_clients_to_group.assert_awaited_once_with(['a@example.com'], 'VIP')
        await service._apply_plan_group(fake, 'a@example.com', '', clear_if_empty=True)
        fake.bulk_remove_clients_from_group.assert_awaited_once_with(['a@example.com'])


class FeatureWiringTests(unittest.TestCase):
    def test_admin_button_and_plan_group_wiring_exist(self) -> None:
        common = (ROOT / 'app/bot/keyboards/common.py').read_text(encoding='utf-8')
        panel = (ROOT / 'app/bot/handlers/admin/admin_panel.py').read_text(encoding='utf-8')
        web = (ROOT / 'app/api/admin_web.py').read_text(encoding='utf-8')
        frontend = (ROOT / 'frontend/components/admin-dashboard.tsx').read_text(encoding='utf-8')
        service = (ROOT / 'app/services/xui_service.py').read_text(encoding='utf-8')
        cleanup = (ROOT / 'app/jobs/service_cleanup.py').read_text(encoding='utf-8')
        self.assertIn('بررسی لیست منقضی ها', common)
        self.assertIn('reconcile_expired_service_list', panel)
        self.assertIn('/admin/api/v2/server-groups', web)
        self.assertIn('Sanaei client group', frontend)
        self.assertIn('bulk_add_clients_to_group', service)
        self.assertIn('async def reconcile_expired_service_list', cleanup)
        self.assertIn('ServiceDeletionTask.status.in_(_PENDING_TASK_STATUSES)', cleanup)
        self.assertIn('async def _prune_stale_deletion_tasks', cleanup)
        self.assertIn("stats['removed_stale']", cleanup)


if __name__ == '__main__':
    unittest.main()
