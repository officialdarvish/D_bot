"""Outgoing traffic is mocked; tests never register public installations."""
import asyncio
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import httpx

spec = importlib.util.spec_from_file_location('counter_client', Path(__file__).resolve().parents[2] / 'app/services/installation_counter.py')
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)
RealAsyncClient = httpx.AsyncClient

class ClientTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'DBOT_INSTALLATION_DIR': self.tmp.name}, clear=True)
        self.env.start()
        self.requests = []

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def factory(self, **kwargs):
        self.assertFalse(kwargs.get('follow_redirects'))
        self.assertNotEqual(kwargs.get('verify'), False)
        return RealAsyncClient(transport=httpx.MockTransport(self.handler), **kwargs)

    def handler(self, request):
        self.requests.append(request)
        return httpx.Response(200, json={'ok': True})

    def test_upgrade_without_settings_reports_stable_identity(self):
        with patch.object(client.httpx, 'AsyncClient', self.factory):
            asyncio.run(client.heartbeat())
            asyncio.run(client.heartbeat())
        self.assertEqual(len(self.requests), 2)
        request = self.requests[0]
        self.assertEqual(str(request.url), 'https://count.botgiftshop.ir/heartbeat')
        self.assertEqual(request.method, 'POST')
        self.assertRegex(request.content.decode(), '^[a-f0-9]{64}$')
        self.assertEqual(request.content, self.requests[1].content)
        self.assertEqual((Path(self.tmp.name) / 'token').stat().st_mode & 0o777, 0o600)

    def test_legacy_blank_url_uses_default(self):
        os.environ['DBOT_COUNTER_URL'] = '  '
        self.assertEqual(client.endpoint(), client.DEFAULT_ENDPOINT)

    def test_explicit_disable_preserved_without_token_or_network(self):
        for value in ['false', '0', 'no', ' FALSE ', 'invalid']:
            os.environ['DBOT_COUNTER_ENABLED'] = value
            with patch.object(client.httpx, 'AsyncClient', side_effect=AssertionError('Must not send')):
                asyncio.run(client.heartbeat())
        self.assertFalse((Path(self.tmp.name) / 'token').exists())

    def test_custom_https_and_invalid_endpoints(self):
        os.environ['DBOT_COUNTER_URL'] = 'https://custom.example/counter/'
        self.assertEqual(client.endpoint(), 'https://custom.example/counter')
        for value in ['http://custom.example', 'https://name:pass@example.com', 'https://example.com?token=secret']:
            os.environ['DBOT_COUNTER_URL'] = value
            with patch.object(client.httpx, 'AsyncClient', side_effect=AssertionError('Must not send')):
                asyncio.run(client.heartbeat())
            self.assertEqual(client.endpoint(), '')

    def test_network_failure_does_not_escape_into_bot(self):
        def fail(request):
            raise httpx.ConnectError('offline')
        self.handler = fail
        with patch.object(client.httpx, 'AsyncClient', self.factory):
            asyncio.run(client.heartbeat())
