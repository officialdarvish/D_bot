from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault('BOT_TOKEN', '123456789:AA_TestTokenForUnitTests_1234567890')
os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://dbot:test@localhost:5432/dbot')
os.environ.setdefault('FERNET_KEY', 'MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=')

from app.xui.client import GB, XUIClient


class XuiRenewEnableTests(unittest.IsolatedAsyncioTestCase):
    def make_client(self) -> XUIClient:
        client = object.__new__(XUIClient)
        client.reset_client_traffic = AsyncMock(return_value={'success': True})
        client.attach_client = AsyncMock(return_value={'success': True})
        client.detach_client = AsyncMock(return_value={'success': True})
        client.bulk_attach_clients = AsyncMock(return_value={'success': True})
        client.bulk_set_enabled = AsyncMock(return_value={'success': True})
        client.set_client_enabled = AsyncMock(return_value={'success': True})
        client._list_clients_api = AsyncMock(return_value=[])
        return client

    def assert_membership_untouched(self, xui: XUIClient) -> None:
        xui.attach_client.assert_not_awaited()
        xui.detach_client.assert_not_awaited()

    @patch('app.xui.client.asyncio.sleep', new_callable=AsyncMock)
    async def test_renew_preserves_existing_inbounds_when_no_new_ids_are_requested(self, _sleep) -> None:
        xui = self.make_client()
        state: dict[str, object] = {'updated': False, 'target': {}}

        async def update_client(payload, inbound_ids=None):
            state['updated'] = True
            state['target'] = dict(payload)
            self.assertIsNone(inbound_ids)
            return {'success': True}

        async def find_client(_email):
            target = state['target'] if state['updated'] else {}
            return {
                'client': {
                    'email': 'sample@example.com',
                    'id': '4b51495f-b409-44a8-a020-20a4af05a332',
                    'totalGB': target.get('totalGB', 5 * GB),
                    'expiryTime': target.get('expiryTime', 1),
                    'enable': bool(state['updated']),
                },
                'used_traffic': 0,
                'traffic': {'up': 0, 'down': 0},
                'inbound_ids': [11, 12],
            }

        xui._update_client = AsyncMock(side_effect=update_client)
        xui.find_client = AsyncMock(side_effect=find_client)

        result = await xui.reset_client_plan(
            'sample@example.com', total_gb=20, expire_days=30,
            current_inbound_ids_hint=[11, 12],
        )

        self.assertEqual(result['inbound_ids'], [11, 12])
        self.assertEqual(result['client']['totalGB'], 20 * GB)
        self.assertTrue(result['client']['enable'])
        self.assert_membership_untouched(xui)

    @patch('app.xui.client.asyncio.sleep', new_callable=AsyncMock)
    async def test_renew_adds_new_inbounds_without_detaching_existing_ones(self, _sleep) -> None:
        xui = self.make_client()
        state: dict[str, object] = {
            'updated': False,
            'target': {},
            'inbounds': [11, 12],
        }

        async def update_client(payload, inbound_ids=None):
            state['updated'] = True
            state['target'] = dict(payload)
            self.assertIsNone(inbound_ids)
            return {'success': True}

        async def attach_client(email, inbound_ids):
            self.assertEqual(email, 'sample@example.com')
            # Explicit scope is intentionally reasserted in full after enable,
            # including ID 12 which the panel already reports as attached.
            self.assertEqual(inbound_ids, [12, 13, 14])
            state['inbounds'] = [11, 12, 13, 14]
            return {'success': True}

        async def find_client(_email):
            target = state['target'] if state['updated'] else {}
            return {
                'client': {
                    'email': 'sample@example.com',
                    'id': '4b51495f-b409-44a8-a020-20a4af05a332',
                    'totalGB': target.get('totalGB', 5 * GB),
                    'expiryTime': target.get('expiryTime', 1),
                    'enable': bool(state['updated']),
                },
                'used_traffic': 0,
                'traffic': {'up': 0, 'down': 0},
                'inbound_ids': list(state['inbounds']),
            }

        xui._update_client = AsyncMock(side_effect=update_client)
        xui.attach_client = AsyncMock(side_effect=attach_client)
        xui.find_client = AsyncMock(side_effect=find_client)

        result = await xui.reset_client_plan(
            'sample@example.com',
            total_gb=20,
            expire_days=30,
            inbound_ids=[12, 13, 14],
            current_inbound_ids_hint=[11, 12],
        )

        self.assertEqual(result['inbound_ids'], [11, 12, 13, 14])
        xui.attach_client.assert_awaited_once_with('sample@example.com', [12, 13, 14])
        xui.bulk_attach_clients.assert_not_awaited()
        xui.detach_client.assert_not_awaited()

    @patch('app.xui.client.asyncio.sleep', new_callable=AsyncMock)
    async def test_manual_reseller_exact_scope_detaches_extra_memberships(self, _sleep) -> None:
        xui = self.make_client()
        state: dict[str, object] = {
            'updated': False,
            'target': {},
            'inbounds': [1, 2, 3, 4],
        }

        async def update_client(payload, inbound_ids=None):
            self.assertIsNone(inbound_ids)
            state['updated'] = True
            state['target'] = dict(payload)
            return {'success': True}

        async def attach_client(email, inbound_ids):
            self.assertEqual(email, 'sample@example.com')
            self.assertEqual(inbound_ids, [2, 4])
            return {'success': True}

        async def detach_client(email, inbound_ids):
            self.assertEqual(email, 'sample@example.com')
            self.assertEqual(inbound_ids, [1, 3])
            state['inbounds'] = [2, 4]
            return {'success': True}

        async def find_client(_email):
            target = state['target'] if state['updated'] else {}
            return {
                'client': {
                    'email': 'sample@example.com',
                    'id': '4b51495f-b409-44a8-a020-20a4af05a332',
                    'totalGB': target.get('totalGB', 5 * GB),
                    'expiryTime': target.get('expiryTime', 1),
                    'enable': bool(state['updated']),
                },
                'used_traffic': 0,
                'traffic': {'up': 0, 'down': 0},
                'inbound_ids': list(state['inbounds']),
            }

        xui._update_client = AsyncMock(side_effect=update_client)
        xui.attach_client = AsyncMock(side_effect=attach_client)
        xui.detach_client = AsyncMock(side_effect=detach_client)
        xui.find_client = AsyncMock(side_effect=find_client)

        result = await xui.reset_client_plan(
            'sample@example.com', 10, 30,
            inbound_ids=[2, 4],
            current_inbound_ids_hint=[1, 2, 3, 4],
            exact_inbound_scope=True,
        )

        self.assertEqual(result['inbound_ids'], [2, 4])
        xui.attach_client.assert_awaited_once_with('sample@example.com', [2, 4])
        xui.detach_client.assert_awaited_once_with('sample@example.com', [1, 3])

    @patch('app.xui.client.asyncio.sleep', new_callable=AsyncMock)
    async def test_renew_restores_scope_after_sanaei_detaches_every_inbound(self, _sleep) -> None:
        xui = self.make_client()
        state: dict[str, object] = {
            'updated': False,
            'target': {},
            'inbounds': [],
        }

        async def update_client(payload, inbound_ids=None):
            self.assertIsNone(inbound_ids)
            state['updated'] = True
            state['target'] = dict(payload)
            return {'success': True}

        async def attach_client(email, inbound_ids):
            self.assertEqual(email, 'sample@example.com')
            # An explicit current plan scope is authoritative. Old locally-known
            # memberships can belong to a replaced server and must not be forced
            # back onto the new panel.
            self.assertEqual(inbound_ids, [21, 22])
            state['inbounds'] = list(inbound_ids)
            return {'success': True}

        async def find_client(_email):
            target = state['target'] if state['updated'] else {}
            return {
                'client': {
                    'email': 'sample@example.com',
                    'id': '4b51495f-b409-44a8-a020-20a4af05a332',
                    'totalGB': target.get('totalGB', 5 * GB),
                    'expiryTime': target.get('expiryTime', 1),
                    'enable': bool(state['updated']),
                },
                'used_traffic': 0,
                'traffic': {'up': 0, 'down': 0},
                'inbound_ids': list(state['inbounds']),
            }

        xui._update_client = AsyncMock(side_effect=update_client)
        xui.attach_client = AsyncMock(side_effect=attach_client)
        xui.find_client = AsyncMock(side_effect=find_client)

        result = await xui.reset_client_plan(
            'sample@example.com', 20, 30,
            inbound_ids=[21, 22],
            current_inbound_ids_hint=[11, 12],
        )

        self.assertEqual(result['inbound_ids'], [21, 22])
        xui.attach_client.assert_awaited_once_with(
            'sample@example.com', [21, 22],
        )
        xui.detach_client.assert_not_awaited()

    @patch('app.xui.client.asyncio.sleep', new_callable=AsyncMock)
    async def test_renew_ignores_stale_inbound_hints_after_server_migration(self, _sleep) -> None:
        xui = self.make_client()
        state: dict[str, object] = {
            'updated': False,
            'target': {},
            'inbounds': [2, 4, 7, 123, 124, 125, 127, 151, 152],
        }

        async def update_client(payload, inbound_ids=None):
            self.assertIsNone(inbound_ids)
            state['updated'] = True
            state['target'] = dict(payload)
            return {'success': True}

        async def attach_client(email, inbound_ids):
            self.assertEqual(email, 'sample@example.com')
            # 149/150 are stale IDs from the old server and must never be sent.
            self.assertEqual(inbound_ids, [2, 4, 7, 123, 124, 125, 127, 151, 152])
            state['inbounds'] = list(inbound_ids)
            return {'success': True}

        async def find_client(_email):
            target = state['target'] if state['updated'] else {}
            return {
                'client': {
                    'email': 'sample@example.com',
                    'id': '4b51495f-b409-44a8-a020-20a4af05a332',
                    'totalGB': target.get('totalGB', 5 * GB),
                    'expiryTime': target.get('expiryTime', 1),
                    'enable': bool(state['updated']),
                },
                'used_traffic': 0,
                'traffic': {'up': 0, 'down': 0},
                'inbound_ids': list(state['inbounds']),
            }

        xui._update_client = AsyncMock(side_effect=update_client)
        xui.attach_client = AsyncMock(side_effect=attach_client)
        xui.find_client = AsyncMock(side_effect=find_client)

        current_scope = [2, 4, 7, 123, 124, 125, 127, 151, 152]
        result = await xui.reset_client_plan(
            'sample@example.com', 20, 30,
            inbound_ids=current_scope,
            current_inbound_ids_hint=[2, 4, 7, 123, 124, 125, 127, 151, 152, 149, 150],
        )

        self.assertEqual(result['inbound_ids'], current_scope)
        xui.attach_client.assert_awaited_once_with('sample@example.com', current_scope)
        xui.bulk_attach_clients.assert_not_awaited()
        xui.detach_client.assert_not_awaited()

    @patch('app.xui.client.asyncio.sleep', new_callable=AsyncMock)
    async def test_renew_resets_consumed_traffic_before_new_cycle(self, _sleep) -> None:
        xui = self.make_client()
        state = {'reads': 0, 'updated': False, 'target': {}}

        async def update_client(payload, inbound_ids=None):
            self.assertIsNone(inbound_ids)
            state['updated'] = True
            state['target'] = dict(payload)
            return {'success': True}

        async def find_client(_email):
            state['reads'] += 1
            # Initial read has old usage; every read after reset is zero.
            used = 8 * GB if state['reads'] == 1 else 0
            target = state['target'] if state['updated'] else {}
            return {
                'client': {
                    'email': 'sample@example.com',
                    'id': '4b51495f-b409-44a8-a020-20a4af05a332',
                    'totalGB': target.get('totalGB', 10 * GB),
                    'expiryTime': target.get('expiryTime', 1),
                    'enable': bool(state['updated']),
                },
                'used_traffic': used,
                'traffic': {'up': 0, 'down': used},
                'inbound_ids': [11, 12],
            }

        xui._update_client = AsyncMock(side_effect=update_client)
        xui.find_client = AsyncMock(side_effect=find_client)

        await xui.reset_client_plan('sample@example.com', 20, 30)

        xui.reset_client_traffic.assert_awaited_once_with('sample@example.com')
        self.assert_membership_untouched(xui)

    @patch('app.xui.client.asyncio.sleep', new_callable=AsyncMock)
    async def test_renew_retries_and_fails_when_consumed_traffic_never_resets(self, _sleep) -> None:
        xui = self.make_client()

        async def find_client(_email):
            return {
                'client': {
                    'email': 'sample@example.com',
                    'id': '4b51495f-b409-44a8-a020-20a4af05a332',
                    'totalGB': 10 * GB,
                    'expiryTime': 1,
                    'enable': False,
                },
                'used_traffic': 8 * GB,
                'traffic': {'up': 0, 'down': 8 * GB},
                'inbound_ids': [11, 12],
            }

        xui.find_client = AsyncMock(side_effect=find_client)
        xui._update_client = AsyncMock(return_value={'success': True})

        with self.assertRaisesRegex(RuntimeError, 'consumed traffic did not reset'):
            await xui.reset_client_plan('sample@example.com', 20, 30)

        self.assertEqual(xui.reset_client_traffic.await_count, 2)
        xui._update_client.assert_not_awaited()
        self.assert_membership_untouched(xui)

    @patch('app.xui.client.asyncio.sleep', new_callable=AsyncMock)
    async def test_renew_uses_dedicated_enable_endpoint_when_update_keeps_disabled(self, _sleep) -> None:
        xui = self.make_client()
        state: dict[str, object] = {'updated': False, 'enabled': False, 'target': {}}

        async def update_client(payload, inbound_ids=None):
            self.assertIsNone(inbound_ids)
            state['updated'] = True
            state['target'] = dict(payload)
            return {'success': True}

        async def bulk_enable(emails, enabled):
            self.assertEqual(emails, ['sample@example.com'])
            self.assertTrue(enabled)
            state['enabled'] = True
            return {'success': True}

        async def find_client(_email):
            target = state['target'] if state['updated'] else {}
            return {
                'client': {
                    'email': 'sample@example.com',
                    'id': '4b51495f-b409-44a8-a020-20a4af05a332',
                    'totalGB': target.get('totalGB', 5 * GB),
                    'expiryTime': target.get('expiryTime', 1),
                    'enable': bool(state['enabled']),
                },
                'used_traffic': 0,
                'inbound_ids': [11, 12],
            }

        xui._update_client = AsyncMock(side_effect=update_client)
        xui.bulk_set_enabled = AsyncMock(side_effect=bulk_enable)
        xui.find_client = AsyncMock(side_effect=find_client)

        result = await xui.reset_client_plan('sample@example.com', 20, 30)

        self.assertTrue(result['client']['enable'])
        xui.bulk_set_enabled.assert_awaited_once_with(['sample@example.com'], True)
        xui.set_client_enabled.assert_not_awaited()
        self.assert_membership_untouched(xui)

    @patch('app.xui.client.asyncio.sleep', new_callable=AsyncMock)
    async def test_renew_falls_back_when_bulk_enable_is_unavailable(self, _sleep) -> None:
        xui = self.make_client()
        state: dict[str, object] = {'updated': False, 'enabled': False, 'target': {}}

        async def update_client(payload, inbound_ids=None):
            self.assertIsNone(inbound_ids)
            state['updated'] = True
            state['target'] = dict(payload)
            return {'success': True}

        async def normal_enable(_email, enabled):
            self.assertTrue(enabled)
            state['enabled'] = True
            return {'success': True}

        async def find_client(_email):
            target = state['target'] if state['updated'] else {}
            return {
                'client': {
                    'email': 'sample@example.com',
                    'id': '4b51495f-b409-44a8-a020-20a4af05a332',
                    'totalGB': target.get('totalGB', 5 * GB),
                    'expiryTime': target.get('expiryTime', 1),
                    'enable': bool(state['enabled']),
                },
                'used_traffic': 0,
                'inbound_ids': [11, 12],
            }

        xui._update_client = AsyncMock(side_effect=update_client)
        xui.bulk_set_enabled = AsyncMock(side_effect=RuntimeError('404 bulkEnable unavailable'))
        xui.set_client_enabled = AsyncMock(side_effect=normal_enable)
        xui.find_client = AsyncMock(side_effect=find_client)

        result = await xui.reset_client_plan('sample@example.com', 20, 30)

        self.assertTrue(result['client']['enable'])
        xui.bulk_set_enabled.assert_awaited_once()
        xui.set_client_enabled.assert_awaited_once_with('sample@example.com', True)
        self.assert_membership_untouched(xui)


class XuiRenewPathTests(unittest.IsolatedAsyncioTestCase):
    @patch('app.services.xui_service.decrypt_text', return_value='secret')
    @patch('app.services.xui_service.XUIClient')
    async def test_manual_public_plan_renewal_reapplies_selected_inbounds(self, client_cls, _decrypt) -> None:
        from types import SimpleNamespace
        from app.services.xui_service import XuiService

        fake = client_cls.return_value
        fake.login = AsyncMock(return_value=True)
        fake.close = AsyncMock()
        fake.get_inbounds = AsyncMock()
        fake.reset_client_plan = AsyncMock(return_value={'inbound_ids': [11, 12, 99]})
        server = SimpleNamespace(
            panel_url='https://panel.example.com', username='admin',
            password_encrypted='encrypted', meta={'inbound_ids': [11, 12, 99]},
        )
        plan = SimpleNamespace(
            volume_gb=25, duration_days=45, inbound_ids=[12, 99],
            meta={'inbound_mode': 'manual'},
        )

        result = await XuiService().renew_client_on_plan(
            server, plan, 'sample@example.com', current_inbound_ids=[11, 12],
        )

        self.assertEqual(result['inbound_ids'], [11, 12, 99])
        fake.get_inbounds.assert_not_awaited()
        fake.reset_client_plan.assert_awaited_once_with(
            'sample@example.com', 25, 45,
            inbound_ids=[12, 99],
            current_inbound_ids_hint=[11, 12],
        )
        fake.close.assert_awaited_once()

    @patch('app.services.xui_service.decrypt_text', return_value='secret')
    @patch('app.services.xui_service.XUIClient')
    async def test_automatic_public_plan_renewal_fetches_every_live_inbound(self, client_cls, _decrypt) -> None:
        from types import SimpleNamespace
        from app.services.xui_service import XuiService

        fake = client_cls.return_value
        fake.login = AsyncMock(return_value=True)
        fake.close = AsyncMock()
        fake.get_inbounds = AsyncMock(return_value=[
            {'id': 21, 'enable': True},
            {'id': 22, 'enable': False},
            {'id': 23, 'enable': True},
        ])
        fake.reset_client_plan = AsyncMock(return_value={'inbound_ids': [21, 23]})
        server = SimpleNamespace(
            panel_url='https://panel.example.com', username='admin',
            password_encrypted='encrypted', meta={'inbound_ids': [1]},
        )
        plan = SimpleNamespace(
            volume_gb=50, duration_days=30, inbound_ids=[1],
            meta={'inbound_mode': 'automatic'},
        )

        await XuiService().renew_client_on_plan(
            server, plan, 'sample@example.com', current_inbound_ids=[],
        )

        fake.get_inbounds.assert_awaited_once()
        fake.reset_client_plan.assert_awaited_once_with(
            'sample@example.com', 50, 30,
            inbound_ids=[21, 23],
            current_inbound_ids_hint=[],
        )

    @patch('app.services.xui_service.decrypt_text', return_value='secret')
    @patch('app.services.xui_service.XUIClient')
    async def test_reseller_automatic_renewal_reapplies_all_live_inbounds(self, client_cls, _decrypt) -> None:
        from types import SimpleNamespace
        from app.services.xui_service import XuiService

        fake = client_cls.return_value
        fake.login = AsyncMock(return_value=True)
        fake.close = AsyncMock()
        fake.find_client_by_identifiers = AsyncMock(return_value={
            'client': {'email': 'panel@example.com'},
            # Sanaei detached all memberships when the client expired.
            'inbound_ids': [],
        })
        fake.get_inbounds = AsyncMock(return_value=[
            {'id': 31, 'enable': True}, {'id': 32, 'enable': True},
        ])
        fake.reset_client_plan = AsyncMock(return_value={
            'client': {'email': 'panel@example.com'}, 'inbound_ids': [31, 32],
        })
        fake.find_client = AsyncMock(return_value={
            'client': {'email': 'panel@example.com'}, 'inbound_ids': [31, 32],
        })
        server = SimpleNamespace(
            panel_url='https://panel.example.com', username='admin',
            password_encrypted='encrypted', meta={'scope': 'reseller'},
        )

        result = await XuiService().reset_client_plan_any(
            server,
            ['stale-name', 'panel@example.com'],
            30,
            60,
            inbound_ids=[99],
            inbound_mode='automatic',
            current_inbound_ids=[11, 12],
        )

        self.assertEqual(result['panel_email'], 'panel@example.com')
        fake.get_inbounds.assert_awaited_once()
        fake.reset_client_plan.assert_awaited_once_with(
            'panel@example.com', 30, 60,
            inbound_ids=[31, 32],
            current_inbound_ids_hint=[11, 12],
            exact_inbound_scope=False,
        )
        fake.close.assert_awaited_once()

    @patch('app.services.xui_service.decrypt_text', return_value='secret')
    @patch('app.services.xui_service.XUIClient')
    async def test_reseller_manual_renewal_reapplies_selected_inbounds(self, client_cls, _decrypt) -> None:
        from types import SimpleNamespace
        from app.services.xui_service import XuiService

        fake = client_cls.return_value
        fake.login = AsyncMock(return_value=True)
        fake.close = AsyncMock()
        fake.get_inbounds = AsyncMock()
        fake.find_client_by_identifiers = AsyncMock(return_value={
            'client': {'email': 'panel@example.com'}, 'inbound_ids': [],
        })
        fake.reset_client_plan = AsyncMock(return_value={
            'client': {'email': 'panel@example.com'}, 'inbound_ids': [41, 42],
        })
        fake.find_client = AsyncMock(return_value={
            'client': {'email': 'panel@example.com'}, 'inbound_ids': [41, 42],
        })
        server = SimpleNamespace(
            panel_url='https://panel.example.com', username='admin',
            password_encrypted='encrypted', meta={'scope': 'reseller', 'inbound_mode': 'manual'},
        )

        await XuiService().reset_client_plan_any(
            server, ['panel@example.com'], 20, 30,
            inbound_ids=[41, 42], inbound_mode='manual', current_inbound_ids=[],
        )

        fake.get_inbounds.assert_not_awaited()
        fake.reset_client_plan.assert_awaited_once_with(
            'panel@example.com', 20, 30,
            inbound_ids=[41, 42], current_inbound_ids_hint=[],
            exact_inbound_scope=True,
        )


    @patch('app.services.xui_service.decrypt_text', return_value='secret')
    @patch('app.services.xui_service.XUIClient')
    async def test_reseller_renewal_forces_all_live_inbounds_even_if_server_is_manual(self, client_cls, _decrypt) -> None:
        from types import SimpleNamespace
        from app.services.xui_service import XuiService

        fake = client_cls.return_value
        fake.login = AsyncMock(return_value=True)
        fake.close = AsyncMock()
        fake.find_client_by_identifiers = AsyncMock(return_value={
            'client': {'email': 'panel@example.com'},
            # Simulate Sanaei auto-detaching everything after expiry/disable.
            'inbound_ids': [],
        })
        fake.get_inbounds = AsyncMock(return_value=[
            {'id': 51, 'enable': True},
            {'id': 52, 'enable': True},
            {'id': 53, 'enable': False},
        ])
        fake.reset_client_plan = AsyncMock(return_value={
            'client': {'email': 'panel@example.com'},
            'inbound_ids': [51, 52],
        })
        fake.find_client = AsyncMock(return_value={
            'client': {'email': 'panel@example.com'},
            'inbound_ids': [51, 52],
        })
        server = SimpleNamespace(
            panel_url='https://panel.example.com', username='admin',
            password_encrypted='encrypted',
            # Even an old/manual reseller server must renew on all live inbounds.
            meta={'scope': 'reseller', 'inbound_mode': 'manual', 'inbound_ids': [999]},
        )

        result = await XuiService().renew_reseller_client_any(
            server, ['old-local-name', 'panel@example.com'], 40, 30,
        )

        self.assertEqual(result['panel_email'], 'panel@example.com')
        fake.get_inbounds.assert_awaited_once()
        fake.reset_client_plan.assert_awaited_once_with(
            'panel@example.com', 40, 30,
            inbound_ids=[51, 52],
            current_inbound_ids_hint=[],
            exact_inbound_scope=False,
        )
        fake.close.assert_awaited_once()

    @patch('app.services.xui_service.decrypt_text', return_value='secret')
    @patch('app.services.xui_service.XUIClient')
    async def test_reseller_manual_policy_is_forwarded_by_renew_entrypoint(self, client_cls, _decrypt) -> None:
        from types import SimpleNamespace
        from app.services.xui_service import XuiService

        fake = client_cls.return_value
        fake.login = AsyncMock(return_value=True)
        fake.close = AsyncMock()
        fake.get_inbounds = AsyncMock()
        fake.find_client_by_identifiers = AsyncMock(return_value={
            'client': {'email': 'panel@example.com'}, 'inbound_ids': [1, 2, 3, 4],
        })
        fake.reset_client_plan = AsyncMock(return_value={
            'client': {'email': 'panel@example.com'}, 'inbound_ids': [2, 4],
        })
        fake.find_client = AsyncMock(return_value={
            'client': {'email': 'panel@example.com'}, 'inbound_ids': [2, 4],
        })
        server = SimpleNamespace(
            panel_url='https://panel.example.com', username='admin',
            password_encrypted='encrypted', meta={'scope': 'reseller'},
        )

        result = await XuiService().renew_reseller_client_any(
            server, ['panel@example.com'], 10, 30,
            inbound_mode='manual', inbound_ids=[2, 4],
        )

        self.assertEqual(result['panel_email'], 'panel@example.com')
        fake.get_inbounds.assert_not_awaited()
        fake.reset_client_plan.assert_awaited_once_with(
            'panel@example.com', 10, 30,
            inbound_ids=[2, 4], current_inbound_ids_hint=[1, 2, 3, 4],
            exact_inbound_scope=True,
        )


if __name__ == '__main__':
    unittest.main()

class XuiRenewTimeoutReconciliationTests(unittest.IsolatedAsyncioTestCase):
    def make_client(self) -> XUIClient:
        client = object.__new__(XUIClient)
        client.attach_client = AsyncMock(return_value={'success': True})
        client.detach_client = AsyncMock(return_value={'success': True})
        client.bulk_attach_clients = AsyncMock(return_value={'success': True})
        client.bulk_set_enabled = AsyncMock(return_value={'success': True})
        client.set_client_enabled = AsyncMock(return_value={'success': True})
        client._list_clients_api = AsyncMock(return_value=[])
        return client

    @patch('app.xui.client.asyncio.sleep', new_callable=AsyncMock)
    async def test_reset_traffic_read_timeout_is_reconciled_when_panel_committed_it(self, _sleep) -> None:
        import httpx

        xui = self.make_client()
        state = {'used': 8 * GB, 'updated': False, 'target': {}}

        async def reset_traffic(_email):
            state['used'] = 0
            raise httpx.ReadTimeout('slow Sanaei response')

        async def update_client(payload, inbound_ids=None):
            self.assertIsNone(inbound_ids)
            state['updated'] = True
            state['target'] = dict(payload)
            return {'success': True}

        async def find_client(_email):
            target = state['target'] if state['updated'] else {}
            return {
                'client': {
                    'email': 'sample@example.com',
                    'id': '4b51495f-b409-44a8-a020-20a4af05a332',
                    'totalGB': target.get('totalGB', 10 * GB),
                    'expiryTime': target.get('expiryTime', 1),
                    'enable': bool(state['updated']),
                },
                'used_traffic': state['used'],
                'traffic': {'up': 0, 'down': state['used']},
                'inbound_ids': [11, 12],
            }

        xui.reset_client_traffic = AsyncMock(side_effect=reset_traffic)
        xui._update_client = AsyncMock(side_effect=update_client)
        xui.find_client = AsyncMock(side_effect=find_client)

        result = await xui.reset_client_plan('sample@example.com', 20, 30)

        self.assertEqual(result['client']['totalGB'], 20 * GB)
        self.assertTrue(result['client']['enable'])
        xui.reset_client_traffic.assert_awaited_once_with('sample@example.com')

    @patch('app.xui.client.asyncio.sleep', new_callable=AsyncMock)
    async def test_update_read_timeout_is_reconciled_without_duplicate_write(self, _sleep) -> None:
        import httpx

        xui = self.make_client()
        state = {'updated': False, 'target': {}}
        xui.reset_client_traffic = AsyncMock(return_value={'success': True})

        async def update_client(payload, inbound_ids=None):
            self.assertIsNone(inbound_ids)
            state['updated'] = True
            state['target'] = dict(payload)
            raise httpx.ReadTimeout('slow Sanaei response')

        async def find_client(_email):
            target = state['target'] if state['updated'] else {}
            return {
                'client': {
                    'email': 'sample@example.com',
                    'id': '4b51495f-b409-44a8-a020-20a4af05a332',
                    'totalGB': target.get('totalGB', 10 * GB),
                    'expiryTime': target.get('expiryTime', 1),
                    'enable': bool(state['updated']),
                },
                'used_traffic': 0,
                'traffic': {'up': 0, 'down': 0},
                'inbound_ids': [11, 12],
            }

        xui._update_client = AsyncMock(side_effect=update_client)
        xui.find_client = AsyncMock(side_effect=find_client)

        result = await xui.reset_client_plan('sample@example.com', 20, 30)

        self.assertEqual(result['client']['totalGB'], 20 * GB)
        self.assertTrue(result['client']['enable'])
        self.assertEqual(xui._update_client.await_count, 1)
