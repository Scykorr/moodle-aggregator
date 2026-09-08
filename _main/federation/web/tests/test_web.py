from pathlib import Path
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'web')]
from app import create_app
from moodle_check import CheckResult
from registry import Registry

HEADERS = {'X-Aggregator-Request': '1'}


class WebTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.registry = Registry(self.directory.name, workers=0)
        self.app = create_app(token='', registry=self.registry)
        self.client = self.app.test_client()

    def tearDown(self):
        self.registry.closed.set()
        self.directory.cleanup()

    def save(self, rows, revision=0):
        return self.client.put('/api/servers', json={'servers': rows, 'revision': revision}, headers=HEADERS)

    def test_page_assets_and_health(self):
        with self.client.get('/') as response:
            self.assertEqual(200, response.status_code)
        with self.client.get('/static/app.js') as response:
            self.assertEqual(200, response.status_code)
        self.assertEqual('ok', self.client.get('/healthz').json['status'])

    def test_many_rows_survive_restart_and_deletion(self):
        rows = [{'id': f'row-{i}', 'address': f'10.30.0.{i}'} for i in range(1, 31)]
        saved = self.save(rows)
        self.assertEqual(200, saved.status_code)
        restarted = Registry(self.directory.name, workers=0)
        self.assertEqual(30, len(restarted.snapshot()['servers']))
        self.assertEqual('http://10.30.0.1/', restarted.rows[0]['address'])
        self.assertEqual(200, self.save(rows[:-1], revision=1).status_code)
        self.assertEqual(29, len(self.client.get('/api/servers').json['servers']))

    def test_conflict_and_invalid_input_do_not_overwrite(self):
        rows = [{'id': 'one', 'address': '10.0.0.1'}]
        self.save(rows)
        self.assertEqual(409, self.save([], revision=0).status_code)
        self.assertEqual(400, self.save([{'id':'one','address':'file:///bad'}], revision=1).status_code)
        self.assertEqual(1, len(self.registry.rows))

    def test_api_requires_token_and_rejects_cross_origin(self):
        client = create_app(token='test-only-password', registry=self.registry).test_client()
        self.assertEqual(401, client.get('/api/servers').status_code)
        self.assertEqual(200, client.get('/api/servers', headers={'Authorization':'Bearer test-only-password'}).status_code)
        self.assertEqual(403, self.client.put('/api/servers', json={}).status_code)
        self.assertEqual(403, self.client.post('/api/check', json={'ids':[]}, headers=dict(HEADERS, Origin='https://other.example')).status_code)

    def test_check_all_deduplicates_pending_work(self):
        self.save([{'id':'one','address':'10.0.0.1'}, {'id':'two','address':'10.0.0.2'}])
        for _ in range(2):
            response = self.client.post('/api/check', json={'ids':['one','two']}, headers=HEADERS)
            self.assertEqual(202, response.status_code)
        self.assertEqual(2, self.registry.jobs.qsize())
        self.assertEqual('queued', response.json['servers'][0]['kind'])

    def test_finished_results_do_not_survive_restart(self):
        self.save([{'id':'one','address':'10.0.0.1'}])
        self.registry.states['one'] = {'kind':'moodle', 'message':'Moodle'}
        restarted = Registry(self.directory.name, workers=0)
        self.assertEqual('idle', restarted.snapshot()['servers'][0]['kind'])

    def test_background_check_ignores_result_after_address_edit(self):
        entered, release = threading.Event(), threading.Event()
        def checker(address):
            entered.set()
            release.wait(3)
            return CheckResult('moodle', 'Old result', address)
        registry = Registry(self.directory.name, checker=checker, workers=1)
        try:
            registry.replace([{'id':'one','address':'10.0.0.1'}], 0)
            registry.check(['one'])
            self.assertTrue(entered.wait(2))
            registry.replace([{'id':'one','address':'10.0.0.2'}], 1)
            release.set()
            registry.jobs.join()
            self.assertEqual('idle', registry.snapshot()['servers'][0]['kind'])
        finally:
            release.set()
            registry.closed.set()


if __name__ == '__main__':
    unittest.main()
