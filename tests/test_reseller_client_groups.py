"""Regression tests for per-reseller Sanaei client group assignments."""
from __future__ import annotations

import ast
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault('BOT_TOKEN', '123456789:AA_TestTokenForUnitTests_1234567890')
os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://dbot:test@localhost:5432/dbot')
os.environ.setdefault('FERNET_KEY', 'MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=')

from app.database.models import ResellerAccount
from app.services.xui_service import XuiService
from app.xui.client import XuiClientPayload

ROOT = Path(__file__).resolve().parents[1]


def fake_panel(groups):
    return SimpleNamespace(
        login=AsyncMock(return_value=True),
        list_client_groups=AsyncMock(return_value=groups),
        add_client_to_inbounds=AsyncMock(return_value={'results': [{'success': True}]}),
        find_client=AsyncMock(return_value={'client': {'email': 'reseller-user', 'subId': 'abc123'}}),
        bulk_add_clients_to_group=AsyncMock(return_value={'success': True}),
        bulk_remove_clients_from_group=AsyncMock(return_value={'success': True}),
        delete_client_by_email=AsyncMock(return_value={'success': True}),
        close=AsyncMock(),
    )


class ResellerGroupProvisioningTests(unittest.IsolatedAsyncioTestCase):
    async def make_client(self, group_name: str, groups):
        panel = fake_panel(groups)
        server = SimpleNamespace(panel_url='https://panel.invalid/', username='admin', password_encrypted='encrypted', server_type='xui', subscription_url=None, meta={})
        with patch('app.services.xui_service.XUIClient', return_value=panel), patch('app.services.xui_service.decrypt_text', return_value='secret'):
            result = await XuiService().create_client_on_inbounds(
                server, [2], XuiClientPayload(email='reseller-user', total_gb=10, expire_days=30),
                automatic=False, group_name=group_name,
            )
        return panel, result

    async def test_selected_group_is_checked_before_create_and_attached_after(self):
        panel, result = await self.make_client('Reseller VIP', [{'name': 'Reseller VIP'}])
        panel.list_client_groups.assert_awaited_once()
        panel.add_client_to_inbounds.assert_awaited_once()
        panel.bulk_add_clients_to_group.assert_awaited_once_with(['reseller-user'], 'Reseller VIP')
        self.assertEqual(result['inbound_ids'], [2])

    async def test_no_group_does_not_make_group_requests(self):
        panel, _ = await self.make_client('', [])
        panel.list_client_groups.assert_not_called()
        panel.bulk_add_clients_to_group.assert_not_called()
        panel.add_client_to_inbounds.assert_awaited_once()

    async def test_deleted_group_is_rejected_before_remote_client_creation(self):
        panel = fake_panel([{'name': 'Other'}])
        server = SimpleNamespace(panel_url='https://panel.invalid/', username='admin', password_encrypted='encrypted', server_type='xui', subscription_url=None, meta={})
        with patch('app.services.xui_service.XUIClient', return_value=panel), patch('app.services.xui_service.decrypt_text', return_value='secret'):
            with self.assertRaisesRegex(RuntimeError, 'no longer exists'):
                await XuiService().create_client_on_inbounds(
                    server, [2], XuiClientPayload(email='reseller-user'),
                    automatic=False, group_name='Deleted',
                )
        panel.add_client_to_inbounds.assert_not_called()
        panel.close.assert_awaited_once()

    async def test_failed_group_assignment_rolls_back_new_remote_client(self):
        panel = fake_panel([{'name': 'VIP'}])
        panel.bulk_add_clients_to_group.side_effect = RuntimeError('Group attach was rejected')
        server = SimpleNamespace(panel_url='https://panel.invalid/', username='admin', password_encrypted='encrypted', server_type='xui', subscription_url=None, meta={})
        with patch('app.services.xui_service.XUIClient', return_value=panel), patch('app.services.xui_service.decrypt_text', return_value='secret'):
            with self.assertRaisesRegex(RuntimeError, 'Group attach was rejected'):
                await XuiService().create_client_on_inbounds(
                    server, [2], XuiClientPayload(email='reseller-user'),
                    automatic=False, group_name='VIP',
                )
        panel.add_client_to_inbounds.assert_awaited_once()
        panel.delete_client_by_email.assert_awaited_once_with('reseller-user')


class ResellerGroupWiringTests(unittest.TestCase):
    def test_reseller_model_and_migrations(self):
        self.assertIn('group_name', ResellerAccount.__table__.columns)
        for path in ('app/main.py', 'app/api/main.py'):
            self.assertIn('reseller_accounts ADD COLUMN IF NOT EXISTS group_name', (ROOT / path).read_text('utf-8'))

    def test_reseller_creation_passes_saved_group(self):
        source = (ROOT / 'app/bot/handlers/public/reseller.py').read_text('utf-8')
        tree = ast.parse(source)
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'create_client_on_inbounds']
        self.assertTrue(calls)
        self.assertTrue(any(any(k.arg == 'group_name' for k in call.keywords) for call in calls))
        self.assertIn('selected_group = str(getattr(reseller', source)

    def test_web_edit_exposes_and_validates_group(self):
        frontend = (ROOT / 'frontend/components/admin-dashboard.tsx').read_text('utf-8')
        backend = (ROOT / 'app/api/admin_web.py').read_text('utf-8')
        self.assertIn('Sanaei client group for new reseller configurations', frontend)
        self.assertIn('groupOptionsByServer', frontend)
        self.assertIn('group_name:str|None=Form(None)', backend)
        self.assertIn('XuiService().live_client_groups(server)', backend)
        self.assertIn("'group_name':str(getattr(r, 'group_name', '') or '')", backend)

    def test_group_not_carried_to_different_server(self):
        reseller = (ROOT / 'app/services/reseller_service.py').read_text('utf-8')
        bot = (ROOT / 'app/bot/handlers/public/reseller.py').read_text('utf-8')
        self.assertIn("reseller.group_name = ''", reseller)
        self.assertIn("reseller.group_name = ''", bot)


if __name__ == '__main__':
    unittest.main()
