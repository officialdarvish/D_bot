"""Run independently: python3 -m unittest discover -s integrations/installation_counter -p 'test_*.py'."""
import hashlib
import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient

spec = importlib.util.spec_from_file_location('counter_service', Path(__file__).with_name('service.py'))
service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service)


class CounterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / 'counter.sqlite'
        self.clock = 100000
        self.patches = [patch.object(service, 'DATABASE', self.db), patch.object(service.time, 'time', lambda: self.clock)]
        for p in self.patches:
            p.start()
        self.client = TestClient(service.app)

    def tearDown(self):
        self.client.close()
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def test_health_initializes_persistent_store_without_counting_itself(self):
        self.assertEqual(self.client.get('/health').json()['ok'], True)
        self.assertEqual(self.client.get('/count').json()['count'], 0)

    def test_repeat_and_expiry(self):
        for token in ['a' * 64, 'a' * 64, 'b' * 64]:
            self.assertEqual(self.client.post('/heartbeat', content=token).status_code, 200)
        self.assertEqual(self.client.get('/count').json()['count'], 2)
        self.clock += 901
        self.assertEqual(self.client.get('/count').json()['count'], 0)
        self.client.post('/heartbeat', content='a' * 64)
        self.assertEqual(self.client.get('/count').json()['count'], 1)

    def test_invalid_requests_do_not_register_installations(self):
        for body, status in [('x' * 129, 413), ('user@example.com', 422), ('A' * 64, 422), ('', 422)]:
            self.assertEqual(self.client.post('/heartbeat', content=body).status_code, status)
        self.assertEqual(self.client.get('/count').json()['count'], 0)

    def test_only_hashes_are_stored_and_expired_records_are_pruned(self):
        token = 'a' * 64
        self.client.post('/heartbeat', content=token)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute('SELECT token_hash FROM installations').fetchone()[0], hashlib.sha256(token.encode()).hexdigest())
        self.clock += 86401
        self.client.post('/heartbeat', content='b' * 64)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM installations').fetchone()[0], 1)
        for url in ['/users', '/installations', '/docs', '/openapi.json']:
            self.assertEqual(self.client.get(url).status_code, 404)


if __name__ == '__main__':
    unittest.main()
